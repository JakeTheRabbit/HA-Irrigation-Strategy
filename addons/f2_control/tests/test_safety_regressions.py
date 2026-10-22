"""Offline regressions for shot deadlines, blind budgets and durable hardware holds."""
import json
from unittest.mock import ANY
from datetime import datetime, timedelta

import pytest

import controller
import fake_ha


pytestmark = pytest.mark.usefixtures("settings_built_in")


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
    for name in ("ha_get", "ha_get_status", "ha_call", "ha_get_all", "ha_set"):
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
    assert c.rooms[0].state[1]["daily_vol"] == pytest.approx(.55)  # 11 s: the valve's 1 s ON read-back too


@pytest.mark.usefixtures("no_blind_grace")
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
        fake.set_state("sensor.crop_steering_dosing_config", "3", {"feed": {"ec": 3.0}})  # flushable: a known feed
    pub = c._loop_room(room, now)
    assert pub[1]["fire"] is False
    assert "daily-cap" in pub[1]["reason"]
    assert not any(dom == "switch" and svc == "turn_on" and data.get("entity_id") == "switch.v1"
                   for dom, svc, data in fake.calls)
    if healthy_sibling:
        assert pub[2]["fire"] is True  # preserve the LIVE probe emergency exception
    # CS-205 must not promise this zone the rescue shots a zone with a working probe keeps.
    card = next(d for dom, svc, d in fake.calls if (dom, svc) == ("persistent_notification", "create")
                and d["notification_id"] == "f2_block_default_z1")
    assert "gets no more water until the next lights-on" in card["message"]
    assert "still run" not in card["message"]


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


def _slow_switch_report(monkeypatch, fake, clock, entity, service, lag_s):
    """Zigbee/MQTT plug: the command is accepted at once, HA sees the new state later."""
    due = {}
    real_call, real_get = controller.ha_call, controller.ha_get

    def call(domain, svc, **data):
        if data.get("entity_id") == entity and svc == service:
            fake.calls.append((domain, svc, data))
            due.setdefault("at", clock.seconds + lag_s)  # the first command's report; a repeat changes nothing
            return True
        return real_call(domain, svc, **data)

    def get(eid, timeout=8):
        if eid == entity and "at" in due and clock.seconds >= due["at"]:
            fake.set_state(entity, "on" if service == "turn_on" else "off")
        return real_get(eid, timeout=timeout)

    monkeypatch.setattr(controller, "ha_call", call)
    monkeypatch.setattr(controller, "ha_get", get)


def test_slow_pump_off_report_does_not_latch_false_fault(rig, monkeypatch):
    # Live 2026-09-14 18:52: a production room's pump reported OFF 1.6 s after turn_off, past the
    # fixed 1 s read-back — a false hold that stopped that room's irrigation for 16 h.
    c, fake, clock = rig
    _slow_switch_report(monkeypatch, fake, clock, "switch.p", "turn_off", 1.6)
    c._execute_shot(c.rooms[0], 1, 6, 6)
    assert c.rooms[0].hardware_fault is None
    assert c._blocked(c.rooms[0], 2) is None


def test_a_pump_off_report_ten_seconds_late_does_not_latch(rig, monkeypatch):
    # Live 2026-09-28 11:18: the same pump reported OFF about 10 s after its turn_off, past the 6 s
    # read-back, and the room stayed held until someone cleared it. What still reads on is sent OFF again
    # and read back once more before any hold.
    c, fake, clock = rig
    _slow_switch_report(monkeypatch, fake, clock, "switch.p", "turn_off", 10)
    c._execute_shot(c.rooms[0], 1, 6, 6)
    assert c.rooms[0].hardware_fault is None
    assert c._blocked(c.rooms[0], 2) is None
    offs = [a for d, s, a in fake.calls if s == "turn_off" and a.get("entity_id") == "switch.p"]
    assert len(offs) == 2  # the close, and once more to the plug that still read on


def test_a_plug_that_missed_the_first_off_obeys_the_second(rig, monkeypatch):
    c, fake, _clock = rig
    real_call = controller.ha_call
    missed = []

    def call(domain, svc, **data):
        if data.get("entity_id") == "switch.p" and svc == "turn_off" and not missed:
            missed.append(True)
            fake.calls.append((domain, svc, data))
            return True  # accepted and never acted on
        return real_call(domain, svc, **data)

    monkeypatch.setattr(controller, "ha_call", call)
    c._execute_shot(c.rooms[0], 1, 6, 6)
    assert fake.states["switch.p"][0] == "off"
    assert c.rooms[0].hardware_fault is None


def test_a_pump_that_never_reports_off_still_latches_and_within_seconds(rig, monkeypatch):
    # Patience for a slow report must not become blindness to a stuck one.
    c, fake, clock = rig
    _slow_switch_report(monkeypatch, fake, clock, "switch.p", "turn_off", 3600)
    before = clock.seconds
    c._execute_shot(c.rooms[0], 1, 6, 6)
    assert c.rooms[0].hardware_fault is not None
    assert "hardware" in c._blocked(c.rooms[0], 2).lower()
    # The shot, both bounded read-backs, and sequencing: still well inside the minute's loop.
    assert clock.seconds - before < 6 + controller.CONFIRM_TIMEOUT_S + controller.CONFIRM_RETRY_S + 10


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
                    "switch.crop_steering_" + slug + "_auto_irrigation_enabled",
                    "switch.crop_steering_" + slug + "_zone_1_enabled"):
            fake.set_state(eid, "on")
        for switch in (pump, "switch." + slug + "_main", "switch." + slug + "_valve"):
            if switch not in fake.states:  # its own feed path exists, switched off
                fake.set_state(switch, "off")
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


def test_a_pump_whose_switch_on_errored_is_switched_off_before_its_alert(rig, monkeypatch):
    """CS-302: Home Assistant answered the pump's turn_on with an error, but the pump may be on all the same. It
    is switched off before the alert, whose phone push can take a while, not only in the cleanup after it."""
    c, fake, _clock = rig
    steps = []

    def call(domain, service, **data):
        steps.append((service, data.get("entity_id") or data.get("notification_id")))
        if (service, data.get("entity_id")) == ("turn_on", "switch.p"):
            return False
        return fake.ha_call(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", call)
    c._execute_shot(c.rooms[0], 1, 6, 6)
    card = steps.index(("create", "f2_hw_default_z1"))
    assert ("turn_off", "switch.p") in steps[steps.index(("turn_on", "switch.p")):card]


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
    assert room.state[1]["daily_vol"] == pytest.approx(42 * 4 / 3600 * 11)  # and the valve's 1 s ON read-back
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


def test_a_second_hardware_hold_is_announced_after_the_first_is_cleared(rig):
    """A cleared hold left its key in _alerted: a second hold within 30 minutes raised no card at
    all (the recovery pass only re-announces a key that is missing), and the room stayed dry."""
    c, fake, _clock = rig
    room = c.rooms[0]

    def cards():
        return [d for dom, svc, d in fake.calls if (dom, svc) == ("persistent_notification", "create")
                and d["notification_id"] == "f2_hardware_fault_default"]

    c._latch_hardware_fault(room, "zone 1 valve/pump/mainline close not confirmed")
    assert len(cards()) == 1
    fake.set_state("input_boolean.kill", "off")  # the operator clears it: engine off, hardware off
    c._recover_hardware_faults()
    assert room.hardware_fault is None
    fake.set_state("input_boolean.kill", "on")
    c._latch_hardware_fault(room, "zone 2 valve/pump/mainline close not confirmed")
    assert len(cards()) == 2 and "zone 2" in cards()[-1]["message"]


@pytest.mark.parametrize("stuck, code", [("switch.p", "CS-302"), ("switch.m", "CS-303"), ("switch.v1", "CS-304")])
def test_a_switch_that_takes_its_turn_on_but_never_reads_on_cancels_the_shot_uncounted(rig, monkeypatch, stuck, code):
    """CTL-002: a dead relay or an offline plug that still acks takes the turn_on and stays OFF. The shot is
    cancelled before any water is counted, its alert raised, and everything set back to off."""
    c, fake, _clock = rig
    room = c.rooms[0]
    steps, codes = [], []

    def call(domain, service, **data):
        steps.append((service, data.get("entity_id")))
        if (service, data.get("entity_id")) == ("turn_on", stuck):
            fake.calls.append((domain, service, data))
            return True  # accepted, never switches
        return fake.ha_call(domain, service, **data)

    alert = c._alert
    monkeypatch.setattr(controller, "ha_call", call)
    monkeypatch.setattr(c, "_alert", lambda key, cs, *a, **k: (codes.append(cs), alert(key, cs, *a, **k))[1])
    c._execute_shot(room, 1, 60, 5, flow_lps=0.05)
    assert room.state[1]["daily_vol"] == 0
    assert room.state[1]["shots"] == 0
    assert code in codes
    assert all(fake.states[e][0] == "off" for e in ("switch.p", "switch.m", "switch.v1"))
    assert room.shot_inflight is None
    assert c._hardware_fault_block(room) is None
    downstream = {"switch.p": ("switch.m", "switch.v1"), "switch.m": ("switch.v1",), "switch.v1": ()}[stuck]
    assert not any(("turn_on", e) in steps for e in downstream)


def test_switches_that_read_on_add_no_time_before_the_valve_opens(rig, monkeypatch):
    """CTL-002: the ON read-back runs inside the pump's prime and the main line's lead, so a normal shot opens
    its valve when it always did and is counted as before."""
    c, fake, clock = rig
    room = c.rooms[0]
    opened = {}

    def call(domain, service, **data):
        if service == "turn_on":
            opened[data.get("entity_id")] = clock.seconds
        return fake.ha_call(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", call)
    c._execute_shot(room, 1, 60, 5, flow_lps=0.05)
    assert opened["switch.v1"] - opened["switch.p"] == pytest.approx(
        controller.FALLBACK["pump_prime_time"] + controller.FALLBACK["main_line_lead_time"])
    assert room.state[1]["daily_vol"] == pytest.approx(3.0)
    assert room.state[1]["shots"] == 1
    assert room.shot_inflight is None


def _turn_on_times(c, fake, clock, monkeypatch, prime, lead):
    room = c.rooms[0]
    fake.set_state("number.crop_steering_pump_prime_time", str(prime))
    fake.set_state("number.crop_steering_main_line_lead_time", str(lead))
    opened = {}

    def call(domain, service, **data):
        if service == "turn_on":
            opened[data.get("entity_id")] = clock.seconds
        return fake.ha_call(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", call)
    return room, opened


@pytest.mark.parametrize("prime, lead", [(4, 0.5), (0.5, 0.5)])
def test_a_lead_under_the_first_read_back_is_not_stretched(rig, monkeypatch, prime, lead):
    """CTL-002 CI: a switch that reads ON at once is read back within a prime or lead shorter than 1 s,
    so a 0.5 s main-line lead still opens the valve 0.5 s after the main line, not 1 s."""
    c, fake, clock = rig
    room, opened = _turn_on_times(c, fake, clock, monkeypatch, prime, lead)
    c._execute_shot(room, 1, 60, 5, flow_lps=0.05)
    assert opened["switch.m"] - opened["switch.p"] == pytest.approx(prime)
    assert opened["switch.v1"] - opened["switch.m"] == pytest.approx(lead)
    assert room.state[1]["shots"] == 1


@pytest.mark.parametrize("on_at", [2.0, None])
def test_a_main_line_still_off_at_its_short_lead_keeps_the_valve_shut(rig, monkeypatch, on_at):
    """CTL-002 CI: with a 0.5 s lead the main line's first read comes at 0.5 s; if it still reads off then,
    the valve waits for a confirmed ON (here at 2 s), and never opens if it never reads ON."""
    c, fake, clock = rig
    room, opened = _turn_on_times(c, fake, clock, monkeypatch, 2, 0.5)
    real_call, real_get = controller.ha_call, controller.ha_get
    closed = []

    def call(domain, service, **data):
        if (service, data.get("entity_id")) == ("turn_on", "switch.m"):
            opened["switch.m"] = clock.seconds
            fake.calls.append((domain, service, data))
            return True  # taken; its state follows `on_at`
        if (service, data.get("entity_id")) == ("turn_off", "switch.m"):
            closed.append(clock.seconds)
        return real_call(domain, service, **data)

    def get(entity, timeout=8):
        if entity == "switch.m" and "switch.m" in opened and not closed:
            late = on_at is not None and clock.seconds - opened["switch.m"] >= on_at
            if "switch.v1" in opened:
                assert late  # the valve opened only after the main line read ON
            return controller.HAState("on" if late else "off", {}, None)
        return real_get(entity, timeout=timeout)

    monkeypatch.setattr(controller, "ha_call", call)
    monkeypatch.setattr(controller, "ha_get", get)
    c._execute_shot(room, 1, 60, 5, flow_lps=0.05)
    if on_at is None:
        assert "switch.v1" not in opened and room.state[1]["shots"] == 0
    else:
        assert opened["switch.v1"] - opened["switch.m"] >= on_at
        assert room.state[1]["shots"] == 1


def _valve_reads(c, fake, clock, monkeypatch, state_at):
    """The valve's state as Home Assistant reports it: `state_at(seconds since its turn_on, window_over)`.
    `window_over` turns True once the controller's ON read-back has given up. Returns the seconds of the
    valve's turn_on and turn_off, and the alerts raised (code, message)."""
    times, alerts, over = {}, [], [False]
    real_call, real_get, real_confirm, alert = controller.ha_call, controller.ha_get, c._confirm_switches, c._alert

    def call(domain, service, **data):
        if data.get("entity_id") == "switch.v1":
            times.setdefault(service, clock.seconds)
            fake.calls.append((domain, service, data))
            if service == "turn_off":
                fake.set_state("switch.v1", "off")
            return True
        return real_call(domain, service, **data)

    def get(entity, timeout=8):
        if entity == "switch.v1" and "turn_on" in times and "turn_off" not in times:
            return controller.HAState(state_at(clock.seconds - times["turn_on"], over[0]), {}, None)
        return real_get(entity, timeout=timeout)

    def confirm(entities, want, deadline=None, **kw):
        ok = real_confirm(entities, want, deadline, **kw)
        over[0] = over[0] or (want == "on" and tuple(entities) == ("switch.v1",) and not ok)
        return ok

    monkeypatch.setattr(controller, "ha_call", call)
    monkeypatch.setattr(controller, "ha_get", get)
    monkeypatch.setattr(c, "_confirm_switches", confirm)
    monkeypatch.setattr(c, "_alert", lambda key, cs, title, msg, *a, **k: (alerts.append((cs, msg)),
                                                                          alert(key, cs, title, msg, *a, **k))[1])
    return times, alerts


def test_a_valve_that_reports_on_late_inside_the_read_back_runs_a_normal_shot(rig, monkeypatch):
    """CTL-002 review: a plug that reports its ON about 10 s late (seen on a live install) is not a dead valve."""
    c, fake, clock = rig
    room = c.rooms[0]
    times, alerts = _valve_reads(c, fake, clock, monkeypatch, lambda t, over: "on" if t >= 10 else "off")
    c._execute_shot(room, 1, 60, 5, flow_lps=0.05)
    assert alerts == []
    assert times["turn_off"] - times["turn_on"] == pytest.approx(60)  # the read-back ran inside the shot
    assert room.state[1]["daily_vol"] == pytest.approx(3.0) and room.state[1]["shots"] == 1
    assert room.state[1]["on_failures"] is None


@pytest.mark.parametrize("valve, counted", [
    ("off", False),  # a dead relay: every read a definite OFF, no water
    ("unavailable", True),  # unreadable throughout: water may have flowed
    ("late", True),  # ON just after the read-back gave up: it did open
], ids=["definite-off", "unavailable", "on-just-after-the-window"])
def test_a_valve_that_does_not_read_on_is_counted_only_when_it_may_have_opened(rig, monkeypatch, valve, counted):
    """CTL-002 review: count conservatively. Only a valve read as a definite OFF throughout counts no water."""
    c, fake, clock = rig
    room = c.rooms[0]
    states = {"off": lambda t, over: "off", "unavailable": lambda t, over: "unavailable",
              "late": lambda t, over: "on" if over else "off"}
    times, alerts = _valve_reads(c, fake, clock, monkeypatch, states[valve])
    room.state[1]["on_failures"] = {"count": 1, "last": datetime.now().isoformat()}
    c._execute_shot(room, 1, 60, 5, flow_lps=0.05)
    # a definite failure (the whole 16 s with no ON) adds to the zone's run; an ON on the final read ends it
    assert room.state[1]["on_failures"] == (None if valve == "late" else {"count": 2, "last": ANY})
    assert [code for code, _msg in alerts] == ["CS-304"]
    assert f"did not read on within {controller.SWITCH_ON_S:g} s" in alerts[0][1]
    assert times["turn_off"] - times["turn_on"] >= controller.SWITCH_ON_S
    if counted:
        assert room.state[1]["daily_vol"] == pytest.approx(0.05 * (times["turn_off"] - times["turn_on"]))
        assert "counts the" in alerts[0][1]
    else:
        assert room.state[1]["daily_vol"] == 0 and room.state[1]["shots"] == 0
        assert "did not count the shot" in alerts[0][1]
    assert all(fake.states[e][0] == "off" for e in ("switch.p", "switch.m", "switch.v1"))
    assert room.shot_inflight is None and c._hardware_fault_block(room) is None


def test_a_zone_whose_valve_will_not_open_backs_off_then_resets_once_it_does(rig, monkeypatch):
    """CTL-002 review: a dead valve is not retried every pass (short-cycling the pump). After three such shots
    in a row the zone, rescue shots included, is tried at most once every 30 min, until its valve reads on."""
    c, fake, clock = rig
    room = c.rooms[0]
    dead = [True]
    times, alerts = _valve_reads(c, fake, clock, monkeypatch, lambda t, over: "off" if dead[0] else "on")

    def shot(**kw):
        times.clear()
        c._execute_shot(room, 1, 60, 5, flow_lps=0.05, **kw)
        return "turn_on" in times

    assert shot() and shot()
    assert "shots of this zone in a row could not start" not in alerts[-1][1]
    assert shot()  # the third in a row: the zone backs off, and says so at once
    assert "The last 3 shots of this zone in a row could not start" in alerts[-1][1]
    assert not shot() and not shot(plan_exempt=True)  # held, a rescue shot too: no command sent
    room.state[1]["on_failures"]["last"] = (datetime.now() - timedelta(minutes=31)).isoformat()
    assert shot()  # retried after 30 min, still dead: backed off again
    assert room.state[1]["on_failures"]["count"] == 4 and not shot()
    room.state[1]["on_failures"]["last"] = (datetime.now() - timedelta(minutes=31)).isoformat()
    dead[0] = False
    assert shot()
    assert room.state[1]["on_failures"] is None and room.state[1]["shots"] == 1
    assert shot()  # and the next shot runs as usual


def test_the_switch_on_backoff_survives_a_restart_and_an_old_state_file_loads(rig):
    c, _fake, _clock = rig
    room = c.rooms[0]
    old = c._serialize_zone(room.state[1])
    del old["on_failures"]  # a state file from before the backoff
    assert c._apply_saved_zone(c._fresh_zone(), old)["on_failures"] is None
    room.state[1]["on_failures"] = {"count": 3, "last": datetime.now().isoformat()}
    assert c._save_state()
    c._load_state()
    assert room.state[1]["on_failures"]["count"] == 3
    assert controller._switch_on_retry_at(room.state[1]) > datetime.now()
    bad = {**old, "on_failures": {"count": "3", "last": "yesterday"}}
    assert c._apply_saved_zone(c._fresh_zone(), bad)["on_failures"] is None


@pytest.mark.parametrize("stage", ["pump-read-back", "main-read-back", "valve-read-back", "lead-time"])
def test_the_kill_switch_stops_a_shot_while_it_opens(rig, monkeypatch, stage):
    """CTL-002 review: the operator's switches are read through the ON read-backs and the lead times too, so
    the kill switch stops a shot that is still opening within about 2 s. Water counts only once the valve
    was sent ON; it is a stop, not a switch that failed, so the zone does not back off."""
    c, fake, clock = rig
    room = c.rooms[0]
    stuck = {"pump-read-back": "switch.p", "main-read-back": "switch.m", "valve-read-back": "switch.v1"}.get(stage)
    flip_after = 0.5 if stage == "lead-time" else 3.0  # after `trigger`'s turn_on
    trigger = stuck or "switch.p"
    if stage == "lead-time":  # a long prime: the stop is seen inside it, not at the main line's read-back
        fake.set_state("number.crop_steering_pump_prime_time", "8")
    at, flip, alerts, real_call, alert = {}, [], [], controller.ha_call, c._alert

    def call(domain, service, **data):
        entity = data.get("entity_id")
        at.setdefault((service, entity), clock.seconds)
        if (service, entity) == ("turn_on", stuck):
            fake.calls.append((domain, service, data))
            return True  # reports ON late: still off when the kill switch goes
        return real_call(domain, service, **data)

    def sleep(seconds):
        clock.sleep(seconds)
        on = at.get(("turn_on", trigger))
        if on is not None and clock.seconds - on >= flip_after and not flip:
            flip.append(clock.seconds)
            fake.set_state("input_boolean.kill", "off")

    monkeypatch.setattr(controller, "ha_call", call)
    monkeypatch.setattr(controller.time, "sleep", sleep)
    monkeypatch.setattr(c, "_alert", lambda key, cs, *a, **k: (alerts.append(cs), alert(key, cs, *a, **k))[1])
    c._execute_shot(room, 1, 60, 5, flow_lps=0.05)
    first_off = min(t for (service, _e), t in at.items() if service == "turn_off")
    assert first_off - flip[0] <= 2.0
    assert alerts == ["CS-305"]
    assert all(fake.states[e][0] == "off" for e in ("switch.p", "switch.m", "switch.v1"))
    assert room.shot_inflight is None and c._hardware_fault_block(room) is None
    assert room.state[1]["on_failures"] is None
    if stage == "valve-read-back":
        assert room.state[1]["daily_vol"] == pytest.approx(0.05 * (first_off - at[("turn_on", "switch.v1")]))
        assert room.state[1]["shots"] == 1
    else:
        assert ("turn_on", "switch.v1") not in at and room.state[1]["daily_vol"] == 0


def test_an_error_in_the_stopped_while_opening_handler_still_counts_the_water_already_given(rig, monkeypatch):
    """#197 x #208: a hold stops a shot whose valve was sent ON and is still reading back. Closing it cut short
    raises (its CS-307 alert fails): the shot's water so far is counted all the same, once, after the cleanup."""
    c, fake, clock = rig
    room = c.rooms[0]
    c.hold_entities = ["input_boolean.hold"]
    fake.set_state("input_boolean.hold", "off")
    at, real_call, real_alert, counted = {}, controller.ha_call, c._alert, []

    def call(domain, service, **data):
        entity = data.get("entity_id")
        at.setdefault((service, entity), clock.seconds)
        if (service, entity) == ("turn_on", "switch.v1"):
            fake.calls.append((domain, service, data))
            return True  # reports ON late: the valve is sent ON and still reads off while the hold goes on
        return real_call(domain, service, **data)

    def sleep(seconds):
        clock.sleep(seconds)
        on = at.get(("turn_on", "switch.v1"))
        if on is not None and clock.seconds - on >= 3.0:
            fake.set_state("input_boolean.hold", "on")

    def alert(key, code, *args, **kwargs):
        if code == "CS-307":
            raise RuntimeError("notify failed")
        return real_alert(key, code, *args, **kwargs)

    real_advance = c._advance_shot_counters
    monkeypatch.setattr(c, "_advance_shot_counters", lambda *a, **k: (counted.append(a[2]), real_advance(*a, **k))[1])
    monkeypatch.setattr(controller, "ha_call", call)
    monkeypatch.setattr(controller.time, "sleep", sleep)
    monkeypatch.setattr(c, "_alert", alert)
    c._execute_shot(room, 1, 60, 5, flow_lps=0.05)
    assert ("turn_off", "switch.v1") in at  # the handler did stop the shot while it opened
    assert len(counted) == 1  # counted once
    assert room.state[1]["daily_vol"] > 0 and room.state[1]["shots"] == 1
    assert all(fake.states[e][0] == "off" for e in ("switch.p", "switch.m", "switch.v1"))
    assert room.shot_inflight is None and c._hardware_fault_block(room) is None


def test_a_hanging_read_cannot_stretch_the_valve_read_back(rig, monkeypatch):
    """CTL-002 review: each ON read is bounded by what is left of the read-back, not the 8 s a read may take."""
    c, fake, clock = rig
    room = c.rooms[0]
    times, real_call, real_get = {}, controller.ha_call, controller.ha_get

    def call(domain, service, **data):
        if data.get("entity_id") == "switch.v1":
            times.setdefault(service, clock.seconds)
        return real_call(domain, service, **data)

    def get(entity, timeout=8):
        if entity == "switch.v1" and "turn_on" in times and "turn_off" not in times:
            clock.sleep(timeout)  # Home Assistant hangs: the read takes all the time it is given
            return controller.HAState(None, {}, None)
        return real_get(entity, timeout=timeout)

    monkeypatch.setattr(controller, "ha_call", call)
    monkeypatch.setattr(controller, "ha_get", get)
    c._execute_shot(room, 1, 60, 5, flow_lps=0.05)
    assert times["turn_off"] - times["turn_on"] <= controller.SWITCH_ON_S + 4
    assert room.state[1]["daily_vol"] == pytest.approx(0.05 * (times["turn_off"] - times["turn_on"]))


def test_a_manual_test_shot_is_not_held_by_the_backoff(rig):
    """CTL-002 review: a backed-off zone still takes its Test Shot (steering off): it is how a repair is checked."""
    c, fake, _clock = rig
    room = c.rooms[0]
    room.state[1]["on_failures"] = {"count": 3, "last": datetime.now().isoformat()}
    c._execute_shot(room, 1, 60, 5, flow_lps=0.05)
    assert not any(svc == "turn_on" for _dom, svc, _d in fake.calls)  # an automatic or rescue shot waits
    c._execute_shot(room, 1, 60, 5, flow_lps=0.05, steering=False)
    assert ("switch", "turn_on", {"entity_id": "switch.v1"}) in fake.calls
    assert room.state[1]["on_failures"] is None and room.state[1]["daily_vol"] == pytest.approx(3.0)


def test_a_switch_on_backoff_saved_with_a_timezone_is_dropped(rig):
    c, _fake, _clock = rig
    saved = {**c._serialize_zone(c.rooms[0].state[1]),
             "on_failures": {"count": 3, "last": "2026-10-22T10:00:00+13:00"}}
    assert c._apply_saved_zone(c._fresh_zone(), saved)["on_failures"] is None


def test_hanging_operator_switch_reads_cannot_stretch_the_valve_read_back(rig, monkeypatch):
    """CTL-002 review: the operator checks inside the valve's read-back are bounded by its end too."""
    c, fake, clock = rig
    room = c.rooms[0]
    times, real_call, real_get = {}, controller.ha_call, controller.ha_get
    operator = {"input_boolean.kill", "switch.crop_steering_room_active", "switch.crop_steering_zone_1_enabled",
                "switch.crop_steering_zone_1_manual_override"}

    def call(domain, service, **data):
        if data.get("entity_id") == "switch.v1":
            times.setdefault(service, clock.seconds)
            if service == "turn_on":
                fake.calls.append((domain, service, data))
                return True  # stays off: the read-back runs its whole length
        return real_call(domain, service, **data)

    def get(entity, timeout=8):
        if entity in operator and "turn_on" in times and "turn_off" not in times:
            clock.sleep(timeout)  # Home Assistant hangs on the operator's switches
            return controller.HAState(None, {}, None)
        return real_get(entity, timeout=timeout)

    monkeypatch.setattr(controller, "ha_call", call)
    monkeypatch.setattr(controller, "ha_get", get)
    c._execute_shot(room, 1, 60, 5, flow_lps=0.05)
    assert times["turn_off"] - times["turn_on"] <= controller.SWITCH_ON_S + 3


@pytest.mark.parametrize("on_at", [10, 12])
def test_a_late_valve_cannot_run_a_short_shot_to_twice_its_length(rig, monkeypatch, on_at):
    """CTL-002 final review: a 5 s shot whose valve reports ON only at 10 or 12 s is closed once its time (or
    the first 6 s read-back stage) is up and counted as maybe open. Its own time cut the read-back short, so
    it is not a definite failure: the zone's run of failed shots is left as it was."""
    c, fake, clock = rig
    room = c.rooms[0]
    room.state[1]["on_failures"] = {"count": 1, "last": datetime.now().isoformat()}
    times, alerts = _valve_reads(c, fake, clock, monkeypatch, lambda t, over: "on" if t >= on_at else "off")
    c._execute_shot(room, 1, 5, 5, flow_lps=0.05)
    open_s = times["turn_off"] - times["turn_on"]
    assert open_s <= 2 * 5
    assert [code for code, _msg in alerts] == ["CS-304"] and "counts the" in alerts[0][1]
    assert room.state[1]["daily_vol"] == pytest.approx(0.05 * open_s)
    assert room.state[1]["on_failures"]["count"] == 1  # unchanged
    assert "shots of this zone in a row could not start" not in alerts[0][1]
    assert all(fake.states[e][0] == "off" for e in ("switch.p", "switch.m", "switch.v1"))


@pytest.mark.parametrize("opens", [True, False], ids=["opening-then-open", "still-opening"])
def test_a_valve_reporting_opening_is_waited_for_then_counted_if_it_never_reads_open(rig, monkeypatch, opens):
    """CTL-002 final review: a valve. entity's "opening" is on its way: waited for, and if the read-back ends
    while it still says so, it may be open: closed and counted, not a definite failure."""
    c, fake, clock = rig
    room = c.rooms[0]
    times, alerts = _valve_reads(c, fake, clock, monkeypatch,
                                 lambda t, over: "on" if opens and t >= 3 else "opening")
    c._execute_shot(room, 1, 60, 5, flow_lps=0.05)
    open_s = times["turn_off"] - times["turn_on"]
    if opens:
        assert alerts == [] and room.state[1]["daily_vol"] == pytest.approx(3.0)
    else:
        assert [code for code, _msg in alerts] == ["CS-304"]
        assert room.state[1]["daily_vol"] == pytest.approx(0.05 * open_s)


@pytest.mark.usefixtures("no_blind_grace")
def test_blind_fallback_does_not_water_at_night(rig):
    """CTL-001: a dead probe with no healthy sibling must not get the timer shot with the lights off."""
    c, fake, _clock = rig
    room = c.rooms[0]
    now = datetime(2026, 9, 7, 23, 30)  # lights 10-22: off
    room._was_lights_on = False
    for st in room.state.values():
        st.update(phase="P3", last_shot=now - timedelta(hours=2), daily_vol=0.0,
                  last_phase_change=now - timedelta(hours=1))
    pub = c._loop_room(room, now)
    assert pub[1]["fire"] is False and pub[2]["fire"] is False
    assert not any(dom == "switch" and svc == "turn_on" for dom, svc, _data in fake.calls)
    assert room.state[1]["daily_vol"] == 0.0 and room.state[2]["daily_vol"] == 0.0


def _blind_day(c, fake, now, phase, daily_vol=0.0, since_shot=30):
    """Both probes dead (no sibling to copy), a 4 L minimum daily water on zone 1 (1000 mL x 4 plants)."""
    room = c.rooms[0]
    fake.set_state("number.crop_steering_zone_1_min_daily_ml_per_plant", "1000")
    fake.set_state("number.crop_steering_zone_1_plant_count", "4")
    for st in room.state.values():
        st.update(phase=phase, last_shot=now - timedelta(minutes=since_shot), daily_vol=0.0,
                  last_phase_change=now - timedelta(minutes=10), last_daily_reset=now.date())
    room.state[1]["daily_vol"] = daily_vol
    return room


@pytest.mark.usefixtures("no_blind_grace")
@pytest.mark.parametrize("phase", ["P2", "P3"])
def test_a_blind_zone_behind_its_minimum_daily_water_gets_the_floor(rig, phase):
    """CTL-031: the minimum daily water does not need the probe; a blind zone behind it is watered with the lights on,
    between the timer shots (30 min since the last, under the 90 min timer)."""
    c, fake, _clock = rig
    now = datetime(2026, 9, 7, 14, 0)  # lights 10-22: on, 4 h in, the floor's line at 4/9 of 4 L
    room = _blind_day(c, fake, now, phase)
    room._was_lights_on = True
    pub = c._loop_room(room, now)
    assert pub[1]["fire"] is True and "MIN-DAILY floor" in str(pub[1]["reason"])
    assert pub[2]["fire"] is False  # no floor set on zone 2
    assert room.state[1]["daily_vol"] > 0.0


@pytest.mark.usefixtures("no_blind_grace")
@pytest.mark.parametrize(
    "hour, phase, daily_vol",
    [
        (23, "P3", 0.0),  # lights off: never at night
        (11, "P0", 0.0),  # the morning dryback comes first, as for a zone with a probe
        (14, "P2", 2.0),  # already ahead of the line (4/9 of 4 L): the water so far counts
    ],
)
def test_a_blind_zone_gets_no_floor_shot_when_none_is_due(rig, hour, phase, daily_vol):
    c, fake, _clock = rig
    now = datetime(2026, 9, 7, hour, 0)
    room = _blind_day(c, fake, now, phase, daily_vol)
    room._was_lights_on = hour < 22
    pub = c._loop_room(room, now)
    assert pub[1]["fire"] is False
    assert room.state[1]["daily_vol"] == daily_vol


@pytest.mark.usefixtures("no_blind_grace")
def test_the_blind_timer_shot_is_not_doubled_by_the_floor(rig):
    """A timer shot due fires once, as the timer shot; the floor counts it and waits its interval."""
    c, fake, _clock = rig
    now = datetime(2026, 9, 7, 14, 0)
    room = _blind_day(c, fake, now, "P2", since_shot=120)
    room._was_lights_on = True
    pub = c._loop_room(room, now)
    assert pub[1]["fire"] is True and "FALLBACK" in str(pub[1]["reason"])
    after = room.state[1]["daily_vol"]
    pub = c._loop_room(room, now + timedelta(minutes=1))
    assert pub[1]["fire"] is False and room.state[1]["daily_vol"] == after


@pytest.mark.usefixtures("no_blind_grace")
@pytest.mark.parametrize("held", [1, 2])
def test_no_floor_shot_into_a_table_that_is_not_draining(rig, held):
    """CS-310 holds the floor (the engine zeroes it for a backed-up zone): the blind zone's own table (1), or the
    sibling it copies (2)."""
    c, fake, _clock = rig
    now = datetime(2026, 9, 7, 14, 0)
    room = _blind_day(c, fake, now, "P2")
    room._was_lights_on = True
    if held == 2:
        fake.set_state("sensor.crop_steering_vwc_zone_2", "60")
    room._backed_up = {held: now}
    pub = c._loop_room(room, now)
    assert pub[1]["fire"] is False and room.state[1]["daily_vol"] == 0.0


@pytest.mark.usefixtures("no_blind_grace")
def test_a_blind_zone_copying_a_sibling_gets_the_floor_and_no_copy_on_top_of_it(rig):
    c, fake, _clock = rig
    now = datetime(2026, 9, 7, 14, 0)
    room = _blind_day(c, fake, now, "P2")
    room._was_lights_on = True
    fake.set_state("sensor.crop_steering_vwc_zone_2", "60")  # the sibling: wet, nothing due
    pub = c._loop_room(room, now)
    assert pub[2]["fire"] is False
    assert pub[1]["fire"] is True and "MIN-DAILY floor" in str(pub[1]["reason"])
    after = room.state[1]["daily_vol"]
    fake.set_state("sensor.crop_steering_vwc_zone_2", "30")  # the sibling now wants a routine top-up
    pub = c._loop_room(room, now + timedelta(minutes=2))
    assert pub[2]["fire"] is True
    assert pub[1]["fire"] is False and "waits" in str(pub[1]["reason"])
    assert room.state[1]["daily_vol"] == after


@pytest.mark.usefixtures("no_blind_grace")
def test_the_blind_alert_names_the_daily_minimum(rig):
    c, fake, _clock = rig
    now = datetime(2026, 9, 7, 14, 0)
    room = _blind_day(c, fake, now, "P2")
    room._was_lights_on = True
    c._loop_room(room, now)
    card = next(d for dom, svc, d in fake.calls if (dom, svc) == ("persistent_notification", "create")
                and d["notification_id"] == "f2_blind_default_z1")
    assert "daily minimum of 4 L" in card["message"]


@pytest.mark.usefixtures("no_blind_grace")
def test_a_blind_zone_copies_every_ramp_shot_even_inside_the_ec_interval(rig):
    """Only a floor shot makes a copy wait: a P1 ramp every 5 min (under the 10 min EC interval) is copied every time."""
    c, fake, _clock = rig
    room = c.rooms[0]
    now = datetime(2026, 9, 7, 11, 0)
    room._was_lights_on = True
    fake.set_state("number.crop_steering_max_daily_volume", "1000")
    fake.set_state("number.crop_steering_p1_time_between_shots", "5")
    fake.set_state("number.crop_steering_ec_min_interval", "10")
    fake.set_state("sensor.crop_steering_vwc_zone_2", "30")  # the sibling: dry, ramping
    for st in room.state.values():
        st.update(phase="P1", shots=0, last_shot=now - timedelta(hours=1), daily_vol=0.0,
                  last_phase_change=now - timedelta(minutes=30), last_daily_reset=now.date())
    for step in range(3):
        at = now + timedelta(minutes=5 * step)
        fake.set_state("sensor.crop_steering_vwc_zone_2", str(30 + 3 * step))  # each ramp shot takes
        pub = c._loop_room(room, at)
        assert pub[2]["fire"] is True, (step, pub[2]["reason"], pub[2].get("phase"))
        assert pub[1]["fire"] is True and "COPY Z2" in str(pub[1]["reason"]), (step, pub[1]["reason"])
        for st in room.state.values():  # the shots land at the pass's time (the rig's wall clock is real)
            st["last_shot"] = at
