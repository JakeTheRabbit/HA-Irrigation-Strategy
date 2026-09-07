"""Offline regressions for shot deadlines, blind budgets and durable hardware holds."""
import json
from datetime import datetime, timedelta

import pytest

import controller
import fake_ha


class Clock:
    def __init__(self):
        self.seconds = 0.0

    def sleep(self, seconds):
        self.seconds += seconds

    def monotonic(self):
        return self.seconds


@pytest.fixture
def rig(monkeypatch, tmp_path):
    fake = fake_ha.FakeHA()
    options = {
        "num_zones": 2,
        "hardware": {"pump": "switch.p", "mainline": "switch.m",
                     "valves": {"1": "switch.v1", "2": "switch.v2"}},
        "enable_flag": "input_boolean.kill",
    }
    monkeypatch.setattr(controller, "load_options", lambda: options)
    for name in ("ha_get", "ha_call", "ha_get_all", "ha_set"):
        monkeypatch.setattr(controller, name, getattr(fake, name))
    # Never read a developer machine's /data/state.json during construction.
    with monkeypatch.context() as setup:
        setup.setattr(controller.Controller, "_read_state_file", lambda self: {})
        c = controller.Controller()
    c._state_path = str(tmp_path / "state.json")
    for eid in ("input_boolean.kill", "switch.crop_steering_system_enabled",
                "switch.crop_steering_auto_irrigation_enabled",
                "switch.crop_steering_zone_1_enabled", "switch.crop_steering_zone_2_enabled"):
        fake.set_state(eid, "on")
    for eid in ("switch.p", "switch.m", "switch.v1", "switch.v2"):
        fake.set_state(eid, "off")
    fake.set_state("number.crop_steering_max_daily_volume", "10")
    clock = Clock()
    monkeypatch.setattr(controller.time, "sleep", clock.sleep)
    monkeypatch.setattr(controller.time, "monotonic", clock.monotonic)
    return c, fake, clock


def test_shot_deadline_includes_ha_read_latency(rig, monkeypatch):
    c, fake, clock = rig

    def delayed_get(entity, timeout=8):
        clock.sleep(min(1.0, timeout))
        return fake.ha_get(entity)

    monkeypatch.setattr(controller, "ha_get", delayed_get)
    elapsed, aborted = c._wait_shot(c.rooms[0], 1, 6)
    assert not aborted
    assert clock.seconds == pytest.approx(6)
    assert elapsed == pytest.approx(clock.seconds)


def test_shot_read_timeout_cannot_add_whole_timeout_after_deadline(rig, monkeypatch):
    c, fake, clock = rig

    def timed_out_get(entity, timeout=8):
        clock.sleep(timeout)
        return None, {}, None

    monkeypatch.setattr(controller, "ha_get", timed_out_get)
    elapsed, _aborted = c._wait_shot(c.rooms[0], 1, 3)
    assert clock.seconds <= 3
    assert elapsed == pytest.approx(clock.seconds)


def test_shot_accounting_includes_command_latency_and_deadline_overrun(rig, monkeypatch):
    c, fake, clock = rig
    timings = {}

    def delayed_call(domain, service, **data):
        if data.get("entity_id") == "switch.v1":
            # Model a device switching immediately but HA acknowledging two seconds later.
            timings[service] = clock.seconds
            result = fake.ha_call(domain, service, **data)
            clock.sleep(2)
            return result
        return fake.ha_call(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", delayed_call)
    c._execute_shot(c.rooms[0], 1, 6, 6)
    # Valve open acknowledgement consumes the deadline; it must not add two more seconds.
    assert timings["turn_off"] - timings["turn_on"] == pytest.approx(6)
    # Conservatively include the close acknowledgement interval: .05 L/s for 8 seconds.
    assert c.rooms[0].state[1]["daily_vol"] == pytest.approx(.4)


def test_accounting_does_not_hide_request_overrun(rig, monkeypatch):
    c, fake, clock = rig

    def late_read(entity, timeout=8):
        if entity == "input_boolean.kill":
            # An OS/socket stall may exceed its requested timeout. We must record it.
            clock.sleep(10)
        return fake.ha_get(entity)

    monkeypatch.setattr(controller, "ha_get", late_read)
    c._execute_shot(c.rooms[0], 1, 6, 6)
    assert c.rooms[0].state[1]["daily_vol"] == pytest.approx(.5)


@pytest.mark.parametrize("healthy_sibling", [False, True])
def test_blind_fallback_and_sibling_copy_stop_at_own_daily_cap(rig, healthy_sibling):
    c, fake, _clock = rig
    room = c.rooms[0]
    now = datetime(2026, 9, 7, 12)
    for st in room.state.values():
        st.update(phase="P2", last_shot=now - timedelta(hours=2), daily_vol=1000)
    if healthy_sibling:
        # Live sibling may legitimately need a high-EC emergency above its own cap.
        fake.set_state("sensor.crop_steering_vwc_zone_2", "30")
        fake.set_state("sensor.crop_steering_ec_zone_2", "12")
    pub = c._loop_room(room, now)
    assert pub[1]["fire"] is False
    assert "daily-cap" in pub[1]["reason"]
    assert not any(dom == "switch" and svc == "turn_on" and data.get("entity_id") == "switch.v1"
                   for dom, svc, data in fake.calls)
    if healthy_sibling:
        assert pub[2]["fire"] is True  # preserve the LIVE probe emergency exception


def _fail_valve_close(monkeypatch, fake, mode="on"):
    def call(domain, service, **data):
        if domain == "switch" and service == "turn_off" and data.get("entity_id") == "switch.v1":
            fake.calls.append((domain, service, data))
            fake.set_state("switch.v1", mode)
            return True
        return fake.ha_call(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", call)


@pytest.mark.parametrize("close_state", ["on", "unavailable", "unknown"])
def test_unconfirmed_close_prevents_next_zone_pumping(rig, monkeypatch, close_state):
    c, fake, _clock = rig
    _fail_valve_close(monkeypatch, fake, close_state)
    c._execute_shot(c.rooms[0], 1, 6, 6)
    before = len([1 for d, s, a in fake.calls if d == "switch" and s == "turn_on"
                  and a.get("entity_id") == "switch.p"])
    c._execute_shot(c.rooms[0], 2, 6, 6)
    after = len([1 for d, s, a in fake.calls if d == "switch" and s == "turn_on"
                 and a.get("entity_id") == "switch.p"])
    assert after == before
    assert "hardware" in c._blocked(c.rooms[0], 2).lower()


def test_fault_survives_restart_and_requires_off_then_verified_recovery(rig, monkeypatch):
    c, fake, _clock = rig
    _fail_valve_close(monkeypatch, fake)
    c._execute_shot(c.rooms[0], 1, 6, 6)
    # The hardware recovers on its own while the engine is still armed.
    monkeypatch.setattr(controller, "ha_call", fake.ha_call)
    fake.set_state("switch.v1", "off")
    c._load_state()  # simulate reloading durable state after restart/rebuild
    assert c._blocked(c.rooms[0], 2) is not None
    # An OFF acknowledgement with an unreadable valve must not clear the fault.
    fake.set_state("input_boolean.kill", "off")
    fake.set_state("switch.v1", "unavailable")
    c.loop_once(datetime(2026, 9, 7, 12))
    fake.set_state("input_boolean.kill", "on")
    assert "hardware" in c._blocked(c.rooms[0], 2).lower()
    # Verified all-off while explicitly disarmed clears the durable latch.
    fake.set_state("input_boolean.kill", "off")
    fake.set_state("switch.v1", "off")
    c.loop_once(datetime(2026, 9, 7, 12, 1))
    fake.set_state("input_boolean.kill", "on")
    c._load_state()
    assert c._blocked(c.rooms[0], 2) is None


def test_fault_blocks_other_room_sharing_pump_but_not_independent_room(rig, monkeypatch):
    c, fake, _clock = rig
    _fail_valve_close(monkeypatch, fake)
    c._execute_shot(c.rooms[0], 1, 6, 6)
    for slug, pump in (("shared", "switch.p"), ("separate", "switch.other_pump")):
        room = controller.Room(slug, slug + "_", {1: {}},
                               {"pump": pump, "mainline": "switch." + slug + "_main",
                                "valves": {1: "switch." + slug + "_valve"}},
                               "input_boolean." + slug, "", "", 10, 22)
        c.rooms.append(room)
        c._load_room_state(room, {})
        for eid in (room.enable_flag, "switch.crop_steering_" + slug + "_system_enabled",
                    "switch.crop_steering_" + slug + "_auto_irrigation_enabled"):
            fake.set_state(eid, "on")
    blocked = c._blocked(c.rooms[1], 1)
    assert blocked and "hardware" in blocked.lower()
    assert c._blocked(c.rooms[2], 1) is None
    # Disarming only the fault owner must not silently resume another armed room
    # sharing its pump, even after the faulty valve has physically recovered.
    monkeypatch.setattr(controller, "ha_call", fake.ha_call)
    fake.set_state("switch.v1", "off")
    fake.set_state("input_boolean.kill", "off")
    c.loop_once(datetime(2026, 9, 7, 12))
    blocked = c._blocked(c.rooms[1], 1)
    assert blocked and "hardware" in blocked.lower()


def test_old_state_without_fault_metadata_keeps_counters_and_runs(rig):
    c, _fake, _clock = rig
    c._load_room_state(c.rooms[0], {"default": {"1": {"daily_vol": 4, "shots": 2}}})
    assert c.rooms[0].state[1]["daily_vol"] == 4
    assert c.rooms[0].state[1]["shots"] == 2
    assert c._blocked(c.rooms[0], 1) is None


def test_hardware_fault_is_visible_even_when_no_irrigation_is_due(rig, monkeypatch):
    c, fake, _clock = rig
    _fail_valve_close(monkeypatch, fake)
    c._execute_shot(c.rooms[0], 1, 6, 6)
    for zone in (1, 2):
        fake.set_state(f"sensor.crop_steering_vwc_zone_{zone}", "65")
        fake.set_state(f"sensor.crop_steering_ec_zone_{zone}", "3")
    c.loop_once(datetime(2026, 9, 7, 12))
    assert fake.sets["sensor.crop_steering_app_status"][0] == "error"
    assert fake.sets["sensor.crop_steering_ai_heartbeat"][1]["hardware_fault"]


@pytest.mark.parametrize("bad_fault", [{}, None, "damaged"])
def test_corrupt_fault_metadata_does_not_silently_rearm(rig, bad_fault):
    c, _fake, _clock = rig
    c._load_room_state(c.rooms[0], {"default": {"_hardware_fault": bad_fault,
                                              "1": {"daily_vol": 4}}})
    assert c.rooms[0].state[1]["daily_vol"] == 4
    assert c._blocked(c.rooms[0], 1) is not None


@pytest.mark.parametrize("failure", ["mainline_open", "wait_exception"])
def test_error_cleanup_also_latches_when_hardware_does_not_close(rig, monkeypatch, failure):
    c, fake, _clock = rig

    def failed_call(domain, service, **data):
        eid = data.get("entity_id")
        if failure == "mainline_open" and eid == "switch.m" and service == "turn_on":
            return False
        if eid == "switch.p" and service == "turn_off":
            return False  # pump remains ON during the error cleanup
        return fake.ha_call(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", failed_call)
    if failure == "wait_exception":
        def fail_wait(*args, **kwargs):
            raise RuntimeError("unexpected I/O error")
        monkeypatch.setattr(c, "_wait_shot", fail_wait)
    c._execute_shot(c.rooms[0], 1, 6, 6)
    assert c._blocked(c.rooms[0], 2) is not None


def test_absent_room_fault_survives_save_and_blocks_shared_hardware_until_rediscovery(rig):
    c, fake, _clock = rig
    orphan = {
        "1": {"phase": "P2", "shots": 7, "daily_vol": 12.5},
        "_hardware_fault": {"reason": "valve close unknown",
                            "entities": ["switch.p", "switch.veg_m", "switch.veg_v"]},
        "future_metadata": {"keep": True},
    }
    saved = {"default": {"1": {"daily_vol": 3}}, "veg": orphan,
             "other_unavailable_room": {"1": {"shots": 11}}}
    with open(c._state_path, "w") as state_file:
        json.dump(saved, state_file)
    c._load_state()  # only the default descriptor was available at restart
    assert c._blocked(c.rooms[0], 1) is not None
    # Independent hardware must remain usable; only the recorded shared pump is held.
    independent = controller.Room("independent", "independent_", {1: {}},
                                  {"pump": "switch.other", "mainline": "switch.other_m",
                                   "valves": {1: "switch.other_v"}},
                                  "input_boolean.independent", "", "", 10, 22)
    c.rooms.append(independent)
    c._load_room_state(independent, {})
    assert c._hardware_fault_block(independent) is None
    c.rooms[0].state[1]["daily_vol"] = 4
    assert c._save_state()
    with open(c._state_path) as state_file:
        retained = json.load(state_file)
    assert retained["veg"] == orphan
    assert retained["other_unavailable_room"] == saved["other_unavailable_room"]
    assert retained["default"]["1"]["daily_vol"] == 4
    # OFF hardware and default engine are not enough: the absent owner cannot be verified.
    fake.set_state("input_boolean.kill", "off")
    for eid in ("switch.veg_m", "switch.veg_v"):
        fake.set_state(eid, "off")
    c.loop_once(datetime(2026, 9, 7, 12))
    assert c._hardware_fault_block(c.rooms[0]) is not None
    # The descriptor returns. Restore its counters and fault before allowing recovery.
    fake.set_state("sensor.crop_steering_veg_engine_config", "veg", {
        "slug": "veg", "prefix": "veg_", "num_zones": 1,
        "pump": "switch.p", "mainline": "switch.veg_m", "valves": {"1": "switch.veg_v"},
        "enable_flag": "switch.crop_steering_veg_engine_enabled",
    })
    fake.set_state("switch.crop_steering_veg_engine_enabled", "on")
    c._rediscover(datetime(2026, 9, 7, 12, 1))
    veg = next(room for room in c.rooms if room.slug == "veg")
    assert veg.state[1]["shots"] == 7
    assert veg.state[1]["daily_vol"] == 12.5
    assert c._hardware_fault_block(c.rooms[0]) is not None
    fake.set_state("switch.crop_steering_veg_engine_enabled", "off")
    c.loop_once(datetime(2026, 9, 7, 12, 2))
    assert c._hardware_fault_block(c.rooms[0]) is None
    c._load_state()
    assert c._hardware_fault_block(c.rooms[0]) is None
    with open(c._state_path) as state_file:
        recovered = json.load(state_file)
    assert "_hardware_fault" not in recovered["veg"]
    assert recovered["veg"]["future_metadata"] == {"keep": True}


@pytest.mark.parametrize("bad_fault", [{}, None, {"entities": [None]}])
def test_orphan_fault_with_unusable_hardware_map_holds_until_owner_returns(rig, bad_fault):
    c, _fake, _clock = rig
    with open(c._state_path, "w") as state_file:
        json.dump({"veg": {"_hardware_fault": bad_fault}}, state_file)
    c._load_state()
    assert c._hardware_fault_block(c.rooms[0]) is not None


@pytest.mark.parametrize("shot_percent,max_seconds,expected_seconds", [
    (2, 60, 60),       # requested 121.5s, capped at 60s
    (2, 900, 121),     # controller truncates a fractional second
    (0.01, 900, 5),    # controller minimum run duration
])
def test_act_zone_accounts_effective_runtime_at_configured_flow(
    rig, shot_percent, max_seconds, expected_seconds
):
    c, fake, clock = rig
    room = c.rooms[0]
    for key, value in {
        "plant_count": 42, "substrate_volume": 6.75,
        "drippers_per_plant": 1, "dripper_flow_rate": 4,
    }.items():
        fake.set_state(f"number.crop_steering_zone_1_{key}", str(value))
    fake.set_state("number.crop_steering_max_shot_duration", str(max_seconds))
    c._act_zone(room, 1, None, None, (True, shot_percent, "accounting regression"),
                None, True, datetime.now())
    expected_litres = 42 * 1 * 4 / 3600 * expected_seconds
    assert room.state[1]["daily_vol"] == pytest.approx(expected_litres)
    assert c._water_usage(room, 1, datetime.now())[0] == round(expected_litres, 2)
    assert room.state[1]["shots"] == 1
    assert clock.seconds == pytest.approx(expected_seconds + 5)


def test_capped_shot_partial_abort_uses_configured_flow(rig, monkeypatch):
    c, fake, clock = rig
    room = c.rooms[0]
    for key, value in {
        "plant_count": 42, "substrate_volume": 6.75,
        "drippers_per_plant": 1, "dripper_flow_rate": 4,
    }.items():
        fake.set_state(f"number.crop_steering_zone_1_{key}", str(value))
    fake.set_state("number.crop_steering_max_shot_duration", "60")
    original_wait = c._wait_shot
    def abort_after_ten(room, zone, duration_s, started=None):
        clock.sleep(10)
        fake.set_state(room.enable_flag, "off")
        return original_wait(room, zone, duration_s, started=started)
    monkeypatch.setattr(c, "_wait_shot", abort_after_ten)
    c._act_zone(room, 1, None, None, (True, 2, "partial accounting"),
                None, True, datetime.now())
    assert room.state[1]["daily_vol"] == pytest.approx(42 * 4 / 3600 * 10)
    assert room.state[1]["shots"] == 1


def test_inflight_sizing_edits_do_not_rewrite_delivered_litres(rig, monkeypatch):
    c, fake, _clock = rig
    room = c.rooms[0]
    for key, value in {
        "plant_count": 42, "substrate_volume": 6.75,
        "drippers_per_plant": 1, "dripper_flow_rate": 4,
    }.items():
        fake.set_state(f"number.crop_steering_zone_1_{key}", str(value))
    fake.set_state("number.crop_steering_max_shot_duration", "60")
    original_wait = c._wait_shot

    def change_sizing(room, zone, duration_s, started=None):
        for key, value in {"plant_count": 84, "substrate_volume": 12,
                           "dripper_flow_rate": 8}.items():
            fake.set_state(f"number.crop_steering_zone_1_{key}", str(value))
        return original_wait(room, zone, duration_s, started=started)

    monkeypatch.setattr(c, "_wait_shot", change_sizing)
    c._act_zone(room, 1, None, None, (True, 2, "sizing race"),
                None, True, datetime.now())
    assert room.state[1]["daily_vol"] == pytest.approx(42 * 4 / 3600 * 60)
    assert c._water_usage(room, 1, datetime.now())[0] == 2.8
