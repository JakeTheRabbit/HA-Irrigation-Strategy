"""Behavioral tests for the f2-control add-on controller.

Drives the real Controller against an in-memory fake HA (no live HA, no /data files),
confirming the shipped add-on fixes:

  * #14  default room takes hardware from the integration's engine_config descriptor;
         NO facility (F2) fallback — an unmapped room holds safe.
  * #20  a shot is interruptible: the kill switch / manual override stops water mid-shot.
  * #21  facility-specific holds are configurable (empty by default); notify unset = no push.
  * #26  rooms added after startup (and a late default-room descriptor) join without a restart.
  * #27  a genuinely-missing setpoint entity is surfaced instead of silently defaulting.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime

import fake_ha

import controller


def _build(options, states=None):
    fake = fake_ha.FakeHA()
    for eid, (state, attrs) in (states or {}).items():
        fake.set_state(eid, state, attrs)
    fake_ha.install(controller, fake, options)
    c = controller.Controller()
    # The controller persists to /data/state.json; on a dev box that resolves to a real
    # writable path and would leak state across tests. Point each build at an isolated
    # temp file and re-seed fresh so every test starts clean.
    c._state_path = os.path.join(tempfile.mkdtemp(prefix="f2test_"), "state.json")
    c._load_state()
    return c, fake


def _desc(prefix="", pump="switch.p", mainline="switch.m", valves=None, num=1, **extra):
    a = {
        "prefix": prefix,
        "pump": pump,
        "mainline": mainline,
        "valves": valves or {"1": "switch.v1"},
        "num_zones": num,
    }
    a.update(extra)
    return a


# --------------------------------------------------------------------- #14
def test_default_room_hardware_comes_from_descriptor_not_f2():
    eid = "sensor.crop_steering_engine_config"
    c, _ = _build(
        {"num_zones": 1},
        states={
            eid: ("ok", _desc(pump="switch.my_pump", mainline="switch.my_main",
                              valves={"1": "switch.my_valve"})),
            "sensor.crop_steering_vwc_zone_1": ("50", {}),
        },
    )
    hw = c.rooms[0].hw
    assert hw["pump"] == "switch.my_pump"
    assert hw["mainline"] == "switch.my_main"
    assert hw["valves"] == {1: "switch.my_valve"}
    # the retired F2 defaults must NOT appear anywhere
    assert "switch.veg_main_pump" not in (hw["pump"], hw["mainline"])
    assert "switch.f2_row1" not in hw["valves"].values()


def test_unmapped_default_room_holds_safe_and_does_not_crash():
    c, fake = _build({"num_zones": 1})  # no descriptor, no hardware option
    room = c.rooms[0]
    assert room.hw["pump"] is None
    block = c._blocked(room, 1)
    assert block and "no hardware mapped" in block
    # safe-off must tolerate the un-mapped room
    c._safe_off()


def test_explicit_hardware_option_overrides_descriptor():
    c, _ = _build(
        {"num_zones": 1, "hardware": {"pump": "switch.opt_pump",
                                      "mainline": "switch.opt_main",
                                      "valves": {"1": "switch.opt_v"}}},
        states={"sensor.crop_steering_engine_config":
                ("ok", _desc(pump="switch.desc_pump"))},
    )
    assert c.rooms[0].hw["pump"] == "switch.opt_pump"


# --------------------------------------------------------------------- #20
def test_wait_shot_interrupts_on_kill_switch(monkeypatch):
    c, fake = _build(
        {"num_zones": 1, "hardware": {"pump": "switch.p", "mainline": "switch.m",
                                      "valves": {"1": "switch.v1"}},
         "enable_flag": "input_boolean.kill"},
        states={"input_boolean.kill": ("on", {})},
    )
    room = c.rooms[0]
    calls = {"n": 0}

    def fake_sleep(_dt):
        calls["n"] += 1
        if calls["n"] == 1:  # flip the kill switch OFF after the first slice
            fake.set_state("input_boolean.kill", "off")

    monkeypatch.setattr(controller.time, "sleep", fake_sleep)
    elapsed, aborted = c._wait_shot(room, 1, 10)
    assert aborted is True
    assert 0 < elapsed < 10  # stopped partway, not the full duration


def test_wait_shot_runs_full_when_enabled(monkeypatch):
    c, fake = _build(
        {"num_zones": 1, "hardware": {"pump": "switch.p", "mainline": "switch.m",
                                      "valves": {"1": "switch.v1"}},
         "enable_flag": "input_boolean.kill"},
        states={"input_boolean.kill": ("on", {})},
    )
    monkeypatch.setattr(controller.time, "sleep", lambda _dt: None)
    elapsed, aborted = c._wait_shot(c.rooms[0], 1, 6)
    assert aborted is False
    assert elapsed == 6


def test_execute_shot_abort_closes_valve_and_alerts(monkeypatch):
    c, fake = _build(
        {"num_zones": 1, "hardware": {"pump": "switch.p", "mainline": "switch.m",
                                      "valves": {"1": "switch.v1"}},
         "enable_flag": "input_boolean.kill"},
        states={"input_boolean.kill": ("on", {})},
    )
    monkeypatch.setattr(controller.time, "sleep",
                        lambda _dt: fake.set_state("input_boolean.kill", "off"))
    c._execute_shot(c.rooms[0], 1, 10, 6)
    # valve driven closed
    assert fake.states["switch.v1"][0] == "off"
    # a kill/override abort alert was raised
    ids = [d.get("notification_id") for (dom, svc, d) in fake.calls
           if dom == "persistent_notification"]
    assert any("killshot" in str(i) for i in ids)
    # partial volume still counted (shot fired)
    assert c.rooms[0].state[1]["shots"] == 1


# --------------------------------------------------------------------- #21
def test_hold_entities_are_configurable_and_f2_ids_no_longer_hardcoded():
    base_states = {
        "sensor.crop_steering_engine_config":
            ("ok", _desc(pump="switch.p", mainline="switch.m", valves={"1": "switch.v1"})),
        "sensor.crop_steering_vwc_zone_1": ("50", {}),
        "input_boolean.f2_control_enabled": ("on", {}),
        "switch.crop_steering_system_enabled": ("on", {}),
        "switch.crop_steering_auto_irrigation_enabled": ("on", {}),
        "switch.crop_steering_zone_1_enabled": ("on", {}),
        # the OLD hardcoded F2 hold — must be IGNORED now
        "input_boolean.f2_fill_mode": ("on", {}),
        # a configured hold
        "input_boolean.my_dose": ("off", {}),
    }
    c, fake = _build({"num_zones": 1, "hold_entities": ["input_boolean.my_dose"]},
                     states=base_states)
    room = c.rooms[0]
    # f2_fill_mode is ON but not configured -> must NOT block
    assert c._blocked(room, 1) is None
    # turn the configured hold on -> blocks with a generic label
    fake.set_state("input_boolean.my_dose", "on")
    block = c._blocked(room, 1)
    assert block and "external hold" in block and "my_dose" in block


def test_notify_service_empty_sends_no_mobile_push():
    c, fake = _build(
        {"num_zones": 1, "hardware": {"pump": "switch.p", "mainline": "switch.m",
                                      "valves": {"1": "switch.v1"}}},
    )
    all_pub = {"default": {1: {"phase": "P2", "vwc": 50.0, "ec": 3.0}}}
    c._maybe_notify(all_pub, datetime(2026, 1, 1, 12, 0))
    notify_calls = [d for (dom, svc, d) in fake.calls if dom == "notify"]
    assert notify_calls == []  # no mobile push when notify_service is unset
    # but a persistent notification still fires
    assert any(dom == "persistent_notification" for (dom, svc, d) in fake.calls)


# --------------------------------------------------------------------- #26
def test_rediscover_adds_late_room_and_maps_default():
    # start unmapped, no extra rooms
    c, fake = _build({"num_zones": 1})
    assert c.rooms[0].hw["pump"] is None
    assert len(c.rooms) == 1
    # integration comes up: default descriptor + a new veg room descriptor appear
    fake.set_state("sensor.crop_steering_engine_config",
                   "ok", _desc(pump="switch.def_pump", valves={"1": "switch.def_v"}))
    fake.set_state("sensor.crop_steering_veg_engine_config", "ok",
                   _desc(prefix="veg_", pump="switch.veg_pump",
                         mainline="switch.veg_main", valves={"1": "switch.veg_v"}, num=1,
                         slug="veg"))
    c._rediscover(datetime(2026, 1, 1, 12, 0))
    # default room now mapped
    assert c.rooms[0].hw["pump"] == "switch.def_pump"
    # veg room joined
    slugs = {r.slug for r in c.rooms}
    assert "veg" in slugs
    veg = next(r for r in c.rooms if r.slug == "veg")
    assert veg.prefix == "veg_"
    assert veg.hw["pump"] == "switch.veg_pump"


# --------------------------------------------------------------------- #27
def test_missing_setpoint_is_surfaced_after_persisting():
    c, fake = _build({"num_zones": 1, "hardware": {"pump": "switch.p",
                      "mainline": "switch.m", "valves": {"1": "switch.v1"}}})
    room = c.rooms[0]
    # neither number.crop_steering_zone_1_p2_shot_size nor the global exists
    for _ in range(3):
        c._defaulted_this_loop = set()
        assert c._zone_num(room, 1, "p2_shot_size", 5) == 5.0
        c._check_defaulted_setpoints()
    assert c._n_defaulted >= 1
    ids = [d.get("notification_id") for (dom, svc, d) in fake.calls
           if dom == "persistent_notification"]
    assert any("defaulted_setpoints" in str(i) for i in ids)


def test_present_setpoint_is_not_flagged():
    c, fake = _build(
        {"num_zones": 1, "hardware": {"pump": "switch.p", "mainline": "switch.m",
                                      "valves": {"1": "switch.v1"}}},
        states={"number.crop_steering_p2_shot_size": ("6", {})},
    )
    room = c.rooms[0]
    for _ in range(4):
        c._defaulted_this_loop = set()
        assert c._zone_num(room, 1, "p2_shot_size", 5) == 6.0
        c._check_defaulted_setpoints()
    assert c._n_defaulted == 0


def test_engine_only_knobs_never_flag_missing_setpoints():
    # `min_floor_drown_ceiling` (and any optional=True knob) is deliberately NOT an
    # integration entity. Building params on a healthy install must not raise the
    # "setpoint entities missing" alert — that would be a permanent false alarm.
    c, fake = _build(
        {"num_zones": 1, "hardware": {"pump": "switch.p", "mainline": "switch.m",
                                      "valves": {"1": "switch.v1"}}},
        # every REAL setpoint present as a global (values arbitrary)
        states={
            f"number.crop_steering_{k}": ("5", {})
            for k in (
                "p2_vwc_threshold", "p1_target_vwc", "field_capacity",
                "p3_emergency_vwc_threshold", "p2_shot_size", "p1_initial_shot_size",
                "p1_shot_size_increment", "p1_maximum_shots", "p1_time_between_shots",
                "generative_dryback_target", "vegetative_dryback_target",
                "p0_maximum_wait_time", "ec_target_gen_p0", "ec_target_gen_p1",
                "ec_target_gen_p2", "p3_emergency_shot_size", "max_daily_volume",
                "maximum_ec", "watchdog_hours", "plant_count",
            )
        },
    )
    room = c.rooms[0]
    for _ in range(4):
        c._defaulted_this_loop = set()
        c._params(room, 1)  # the real production read path
        c._check_defaulted_setpoints()
    assert c._n_defaulted == 0, f"false alarms for: {sorted(c._defaulted)}"


def test_heartbeat_publishes_enable_flag():
    # health.py resolves the kill switch from the heartbeat's enable_flag attribute —
    # the engine must publish it.
    c, fake = _build(
        {"num_zones": 1, "enable_flag": "input_boolean.custom_kill",
         "hardware": {"pump": "switch.p", "mainline": "switch.m",
                      "valves": {"1": "switch.v1"}}},
        states={"sensor.crop_steering_vwc_zone_1": ("50", {})},
    )
    room = c.rooms[0]
    pub = {1: {"phase": "P2", "vwc": 50.0, "ec": 3.0, "fire": False, "block": None,
               "reason": "hold", "blind": False, "p": c._params(room, 1),
               "vmax": None, "next_h": None}}
    c._publish_status(room, pub, datetime(2026, 1, 1, 12, 0))
    state, attrs = fake.sets["sensor.crop_steering_ai_heartbeat"]
    assert attrs["enable_flag"] == "input_boolean.custom_kill"
