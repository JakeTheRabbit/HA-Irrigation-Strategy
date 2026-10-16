"""The zone page's gate list (gate_report.py) is a second, side-effect-free reading of _blocked's gates. Its first
"hold" must always be what _blocked() answers, or the card could say "all clear" while the zone is held."""
from datetime import datetime

import pytest

import gate_report
from test_controller import _build, _desc

pytestmark = pytest.mark.usefixtures("settings_built_in")

KILL = "input_boolean.kill"
HOLD = "input_boolean.tank_dosing"


def _room():
    states = {
        "sensor.crop_steering_engine_config": ("ok", _desc(enable_flag=KILL)),
        KILL: ("on", {}),
        "switch.crop_steering_room_active": ("on", {}),
        "switch.crop_steering_zone_1_enabled": ("on", {}),
        "switch.crop_steering_zone_1_manual_override": ("off", {}),
        HOLD: ("off", {}),
    }
    c, fake = _build({"num_zones": 1, "enable_flag": KILL, "hold_entities": [HOLD]}, states=states)
    return c, fake, c.rooms[0]


CASES = {
    "clear": lambda c, f, r: None,
    "room off": lambda c, f, r: f.set_state("switch.crop_steering_room_active", "off"),
    "kill switch off": lambda c, f, r: f.set_state(KILL, "off"),
    "zone off": lambda c, f, r: f.set_state("switch.crop_steering_zone_1_enabled", "off"),
    "zone switch unreadable": lambda c, f, r: f.set_state("switch.crop_steering_zone_1_enabled", "unavailable"),
    "manual override": lambda c, f, r: f.set_state("switch.crop_steering_zone_1_manual_override", "on"),
    "external hold on": lambda c, f, r: f.set_state(HOLD, "on"),
    "external hold unreadable": lambda c, f, r: f.set_state(HOLD, "unknown"),
    "valve offline": lambda c, f, r: f.set_state("switch.v1", "unavailable"),
    "no valve": lambda c, f, r: r.hw["valves"].pop(1),
    "undrivable": lambda c, f, r: r.hw["valves"].update({1: "light.v1"}),
    "setup pending": lambda c, f, r: setattr(r, "_setup_pending", "Setup changed"),
    "archived": lambda c, f, r: setattr(r, "setup_active", False),
    "retired": lambda c, f, r: setattr(r, "_retired_off", ["System enabled"]),
    "max-run latch": lambda c, f, r: (r.state[1].update(max_run_latch={"since": "x", "resets": 0}),
                                      f.set_state("switch.crop_steering_max_run_latch", "on", {"resets": 0})),
    "kill and zone off": lambda c, f, r: (f.set_state(KILL, "off"),
                                          f.set_state("switch.crop_steering_zone_1_enabled", "off")),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_first_hold_is_what_blocked_answers(case):
    c, fake, room = _room()
    CASES[case](c, fake, room)
    gates = gate_report.report(c, room, 1)
    assert gate_report.first_hold(gates) == c._blocked(room, 1)
    assert all(g["state"] in ("pass", "hold") and g["label"] for g in gates)


def test_a_clear_zone_lists_every_gate_as_passing_and_names_what_is_not_configured():
    c, fake, room = _room()
    gates = gate_report.report(c, room, 1)
    assert gate_report.first_hold(gates) is None
    keys = [g["key"] for g in gates]
    assert keys[:3] == ["setup", "archived", "room_on"] and keys[-1] == "online"
    tank = next(g for g in gates if g["key"] == "tank")
    assert tank["detail"] == "no tank level mapped"


def test_the_report_raises_no_alert_where_blocked_does():
    c, fake, room = _room()
    room.hw["valves"][1] = "light.v1"  # a valve the controller cannot switch: _blocked raises CS-313
    raised = []
    c._alert = lambda key, code, *a, **k: raised.append(code)
    gate_report.report(c, room, 1)
    assert raised == []
    c._blocked(room, 1)
    assert raised == ["CS-313"]


def test_the_gate_list_rides_on_the_waiting_for_sensor():
    c, fake, room = _room()
    fake.set_state("sensor.crop_steering_vwc_zone_1", "55")
    c.loop_once(datetime(2026, 9, 23, 12, 0))
    attrs = fake.sets["sensor.crop_steering_zone_1_waiting_for_app"][1]
    assert attrs["gates"] and attrs["gates"][0]["key"] == "setup"


@pytest.mark.parametrize("policy,valve,remembered", [
    ("Off", "on", None), ("Check closed", "on", None), ("Check closed", "off", None),
    ("Close for each shot", "on", None), ("unavailable", "off", None),
    ("invalid", "off", None), (None, "off", "Close for each shot"),
    (None, "off", "Off"), (None, "off", None),
    ("Check closed", "unavailable", None), ("Close for each shot", "unknown", None),
])
def test_waste_gate_matches_admission_without_remembering_or_alerting(policy, valve, remembered):
    c, fake, room = _room()
    room.waste = "switch.waste"
    room._waste_rule_known = remembered
    fake.set_state(room.waste, valve)
    if policy is not None:
        fake.set_state("select.crop_steering_waste_valve_rule", policy)
    saved = []
    c._save_state = lambda: saved.append(True)
    calls = list(fake.calls)
    gates = gate_report.report(c, room, 1)
    assert room._waste_rule_known == remembered and saved == [] and fake.calls == calls
    assert gate_report.first_hold(gates) == c._blocked(room, 1)
    keys = [g["key"] for g in gates]
    assert keys.index("external_holds") < keys.index("waste") < keys.index("settings")


def test_an_unsupported_waste_actuator_is_reported_as_the_same_hold():
    c, fake, room = _room()
    room.waste = "light.waste"
    fake.set_state(room.waste, "on")
    fake.set_state("select.crop_steering_waste_valve_rule", "Close for each shot")
    held = gate_report.first_hold(gate_report.report(c, room, 1))
    assert held == c._blocked(room, 1) == "waste valve light.waste can't be switched by the controller"


@pytest.mark.parametrize("kind,bypass,reading", [
    ("p3_emergency", "on", "unavailable"), ("watchdog", "on", "unavailable"),
    ("p2_topup", "on", "unavailable"), ("p3_emergency", "off", "unavailable"),
    ("p3_emergency", "on", "7.4"),
])
@pytest.mark.parametrize("half", ["ec", "ph"])
def test_dead_feed_gate_matches_the_shots_rescue_only_exception(kind, bypass, reading, half):
    import controller
    c, fake, room = _room()
    probe = f"sensor.feed_{half}"
    setattr(room, f"feed_{half}_sensor", probe)
    fake.set_state(probe, reading, {"unit_of_measurement": "pH" if half == "ph" else "mS/cm"})
    lo, hi = (5.5, 6.5) if half == "ph" else (2.0, 4.0)
    fake.set_state(f"number.crop_steering_irrigation_{half}_min", str(lo))
    fake.set_state(f"number.crop_steering_irrigation_{half}_max", str(hi))
    fake.set_state("switch.crop_steering_rescue_past_dead_feed_probe", bypass)
    reason = controller.Reason("shot", kind)
    gates = gate_report.report(c, room, 1, reason)
    assert gate_report.first_hold(gates) == c._blocked(room, 1, reason)
    fake.set_state(KILL, "off")
    assert gate_report.first_hold(gate_report.report(c, room, 1, reason)) == c._blocked(room, 1, reason)
