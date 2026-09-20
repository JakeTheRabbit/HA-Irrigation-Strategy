"""A room with ONE switch (a tent: one smart plug or solenoid, no separate pump or mainline relay).

The integration has always saved such a room: pump and mainline are optional there, and it even
refuses one switch in two roles. The controller, though, demanded pump AND mainline AND valve, so the
room saved, showed up, and never watered. Seen on a first tent install (switch.gt1_irrigation_switch).

Rule now: a zone needs its valve. Pump and mainline are used when mapped and skipped when not. Every
fail-closed guarantee still holds over whatever hardware the room has.
"""
import pytest

import controller
from test_controller import _build, _desc

KILL = "input_boolean.kill"
VALVE = "switch.gt1_irrigation_switch"
FLAGS = {
    KILL: ("on", {}),
    "switch.crop_steering_system_enabled": ("on", {}),
    "switch.crop_steering_auto_irrigation_enabled": ("on", {}),
    "switch.crop_steering_zone_1_enabled": ("on", {}),
}


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    """Shots run against time.monotonic/sleep: fake both so a fired shot costs no real time."""
    now = {"seconds": 0.0}
    monkeypatch.setattr(controller.time, "monotonic", lambda: now["seconds"])
    monkeypatch.setattr(controller.time, "sleep", lambda dt: now.__setitem__("seconds", now["seconds"] + dt))
    return now


def _room(pump=None, mainline=None, extra=None):
    states = {
        "sensor.crop_steering_engine_config": ("ok", _desc(pump=pump, mainline=mainline, valves={"1": VALVE},
                                                           enable_flag=KILL)),
        VALVE: ("off", {}),
        **FLAGS,
    }
    for entity in (pump, mainline):
        if entity:
            states[entity] = ("off", {})
    states.update(extra or {})
    return _build({"num_zones": 1, "enable_flag": KILL}, states=states)


def _switch_calls(fake):
    return [(svc, d["entity_id"]) for dom, svc, d in fake.calls if dom == "switch"]


def test_a_valve_only_room_is_mapped_and_waters_with_its_one_switch():
    c, fake = _room()
    room = c.rooms[0]
    assert room.hw["valves"] == {1: VALVE} and not room.hw.get("pump") and not room.hw.get("mainline")
    assert "no hardware" not in (c._blocked(room, 1) or "")
    c._execute_shot(room, 1, 6, 2.0)
    assert _switch_calls(fake) == [("turn_on", VALVE), ("turn_off", VALVE)]
    assert room.state[1]["shots"] == 1 and room.hardware_fault is None  # counted, and closed cleanly


def test_a_pump_without_a_mainline_is_sequenced_pump_first_and_closed_valve_first():
    c, fake = _room(pump="switch.pump")
    c._execute_shot(c.rooms[0], 1, 6, 2.0)
    assert _switch_calls(fake) == [
        ("turn_on", "switch.pump"), ("turn_on", VALVE), ("turn_off", VALVE), ("turn_off", "switch.pump")]


def test_the_full_three_switch_sequence_and_its_timing_are_unchanged(clock):
    c, fake = _room(pump="switch.pump", mainline="switch.main")
    c._execute_shot(c.rooms[0], 1, 6, 2.0)
    assert _switch_calls(fake) == [
        ("turn_on", "switch.pump"), ("turn_on", "switch.main"), ("turn_on", VALVE),
        ("turn_off", VALVE), ("turn_off", "switch.main"), ("turn_off", "switch.pump")]
    assert clock["seconds"] == pytest.approx(2 + 1 + 6 + 1 + 1)  # pump lead, mainline lead, shot, close gap, read-back


def test_a_valve_only_room_that_will_not_close_still_latches_the_hardware_hold(monkeypatch):
    c, fake = _room()
    real = controller.ha_call

    def stuck(domain, service, **data):
        if service == "turn_off" and data.get("entity_id") == VALVE:
            fake.calls.append((domain, service, data))
            return True  # command accepted, state never changes
        return real(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", stuck)
    c._execute_shot(c.rooms[0], 1, 6, 2.0)
    assert c.rooms[0].hardware_fault is not None
    assert "hardware" in c._blocked(c.rooms[0], 1).lower()


def test_a_failed_valve_command_cuts_the_pump_it_had_already_started(monkeypatch):
    c, fake = _room(pump="switch.pump")
    real = controller.ha_call

    def refuse_valve(domain, service, **data):
        if service == "turn_on" and data.get("entity_id") == VALVE:
            return False
        return real(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", refuse_valve)
    c._execute_shot(c.rooms[0], 1, 6, 2.0)
    assert fake.states["switch.pump"][0] == "off"
    assert c.rooms[0].state[1]["shots"] == 0  # no water, not counted


def test_a_zone_without_a_valve_is_still_unmapped_and_held():
    states = {"sensor.crop_steering_engine_config": ("ok", _desc(pump="switch.pump", mainline="switch.main",
                                                                 valves={"1": ""}, enable_flag=KILL)), **FLAGS}
    c, _fake = _build({"num_zones": 1, "enable_flag": KILL}, states=states)
    assert "no hardware mapped" in c._blocked(c.rooms[0], 1)


def test_a_valve_only_setup_revision_is_adopted_not_rejected_as_incomplete():
    c, fake = _room(extra={KILL: ("off", {})})
    attrs = dict(fake.states["sensor.crop_steering_engine_config"][1], setup_revision=1, active=True, active_zone_ids=[1])
    fake.set_state("sensor.crop_steering_engine_config", "ok", attrs)
    c._apply_setup_descriptors()
    room = c.rooms[0]
    assert getattr(room, "setup_revision", 0) == 1 and room._setup_pending is None


def test_an_additional_valve_only_room_is_discovered():
    c, fake = _room()
    fake.set_state("sensor.crop_steering_gt1_engine_config", "ok",
                   _desc(prefix="gt1_", pump=None, mainline=None, valves={"1": "switch.gt1_valve"},
                         slug="gt1", enable_flag="switch.crop_steering_gt1_engine_enabled"))
    fake.set_state("sensor.crop_steering_gt1_vwc_zone_1", "40", {})
    assert [r.slug for r in c._discover_rooms()] == ["gt1"]
