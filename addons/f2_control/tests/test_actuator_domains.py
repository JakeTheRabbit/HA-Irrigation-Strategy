"""A zone valve, main line or pump can be a switch, an input_boolean or a valve (controller.ACTUATORS).

Each is opened, closed and read back in its own domain's words: a valve with open_valve / close_valve,
reading open / closed. Every path that switches that hardware or reads it back goes through the one
table: the shot, its close and read-back, the interrupted-shot record, a shot something else cut short,
stopping the app, and clearing a hardware hold. A domain the table does not have is never sent a
command and holds its zone with CS-313.
"""
from datetime import datetime, timedelta, timezone

import pytest

import controller
import fake_ha

VALVE, PUMP, MAIN = "valve.v1", "input_boolean.p", "switch.m"
STARTED = datetime(2026, 9, 23, 1, 0, tzinfo=timezone.utc)


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
        "hardware": {"pump": PUMP, "mainline": MAIN, "valves": {"1": VALVE, "2": "cover.v2"}},
        "enable_flag": "input_boolean.kill",
    }
    monkeypatch.setattr(controller, "load_options", lambda: options)
    for name in ("ha_get", "ha_call", "ha_get_all", "ha_set", "ha_history"):
        monkeypatch.setattr(controller, name, getattr(fake, name))
    with monkeypatch.context() as setup:
        setup.setattr(controller.Controller, "_read_state_file", lambda self: {})
        c = controller.Controller()
    c._state_path = str(tmp_path / "state.json")
    for eid in ("input_boolean.kill", "switch.crop_steering_system_enabled",
                "switch.crop_steering_auto_irrigation_enabled",
                "switch.crop_steering_zone_1_enabled", "switch.crop_steering_zone_2_enabled"):
        fake.set_state(eid, "on")
    fake.set_state(VALVE, "closed")
    fake.set_state("cover.v2", "closed")
    fake.set_state(PUMP, "off")
    fake.set_state(MAIN, "off")
    clock = Clock()
    monkeypatch.setattr(controller.time, "sleep", clock.sleep)
    monkeypatch.setattr(controller.time, "monotonic", clock.monotonic)
    return c, fake, clock


def hardware(fake):
    return [(dom, svc, d["entity_id"]) for dom, svc, d in fake.calls
            if d.get("entity_id") in (VALVE, PUMP, MAIN, "cover.v2")]


def test_each_domain_is_switched_and_read_in_its_own_words(rig):
    _c, fake, _clock = rig
    for entity in (VALVE, PUMP, MAIN):
        assert controller.hw_call(entity, True) and controller.hw_get(entity)[0] == "on"
        assert controller.hw_call(entity, False) and controller.hw_get(entity)[0] == "off"
    assert hardware(fake) == [
        ("valve", "open_valve", VALVE), ("valve", "close_valve", VALVE),
        ("input_boolean", "turn_on", PUMP), ("input_boolean", "turn_off", PUMP),
        ("switch", "turn_on", MAIN), ("switch", "turn_off", MAIN),
    ]
    fake.set_state(VALVE, "closing")
    assert controller.hw_get(VALVE)[0] == "closing"  # neither on nor off: not closed yet
    assert controller.hw_get("cover.v2")[0] == "closed"  # a domain it can't drive is read as it is
    assert controller.hw_call("cover.v2", False) is False
    assert "cover.v2" not in [entity for *_, entity in hardware(fake)]


def test_a_shot_opens_up_the_line_and_closes_back_down_it(rig):
    c, fake, _clock = rig
    room = c.rooms[0]
    assert c._blocked(room, 1) is None
    c._execute_shot(room, 1, 6, 6)
    assert hardware(fake) == [
        ("input_boolean", "turn_on", PUMP), ("switch", "turn_on", MAIN), ("valve", "open_valve", VALVE),
        ("valve", "close_valve", VALVE), ("switch", "turn_off", MAIN), ("input_boolean", "turn_off", PUMP),
    ]
    assert room.hardware_fault is None and room.state[1]["shots"] == 1


def test_a_zone_on_a_cover_is_held_with_cs_313_and_never_switched(rig):
    c, fake, _clock = rig
    room = c.rooms[0]
    fake.calls.clear()
    held = c._blocked(room, 2)
    assert held.startswith("cover.v2 can't be switched")
    cards = [d for dom, svc, d in fake.calls if (dom, svc) == ("persistent_notification", "create")]
    assert [d["notification_id"] for d in cards] == ["f2_actuator_default_z2"]
    assert "(CS-313)" in cards[0]["title"] and "cover.v2" in cards[0]["message"]
    fake.calls.clear()
    c._execute_shot(room, 2, 6, 6)
    assert hardware(fake) == [] and room.hardware_fault is None and room.shot_inflight is None


def test_a_valve_closed_by_someone_else_cuts_the_shot_short_and_is_not_closed_again(rig, monkeypatch):
    c, fake, clock = rig
    room = c.rooms[0]
    real = controller.ha_get

    def get(entity, timeout=8):
        if entity == VALVE and clock.seconds >= 6:
            fake.set_state(VALVE, "closed")  # a guard automation closes it
        return real(entity, timeout=timeout)

    monkeypatch.setattr(controller, "ha_get", get)
    c._execute_shot(room, 1, 30, 6)
    assert ("valve", "close_valve", VALVE) not in hardware(fake)
    assert ("input_boolean", "turn_off", PUMP) in hardware(fake) and room.hardware_fault is None


def test_an_interrupted_shot_on_a_valve_is_closed_from_its_record_and_its_history(rig):
    c, fake, _clock = rig
    room = c.rooms[0]
    room.shot_inflight = {"zone": 1, "valve": VALVE, "mainline": None, "pump": None,
                          "started": STARTED.isoformat()}
    # Home Assistant restarted since the shot opened it, so its last change is not when the shot did.
    fake.set_state(VALVE, "open", last_updated=(STARTED + timedelta(minutes=10)).isoformat())
    fake.history[VALVE] = [("open", (STARTED + timedelta(seconds=3)).isoformat()),
                           ("unavailable", (STARTED + timedelta(minutes=9)).isoformat()),
                           ("open", (STARTED + timedelta(minutes=10)).isoformat())]
    c._reconcile_inflight()
    assert hardware(fake) == [("valve", "close_valve", VALVE)]
    assert fake.states[VALVE][0] == "closed" and room.shot_inflight is None


def test_stopping_mid_shot_closes_the_valve(rig):
    c, fake, _clock = rig
    room = c.rooms[0]
    room.shot_inflight = {"zone": 1, "valve": VALVE, "mainline": None, "pump": None,
                          "started": STARTED.isoformat()}
    fake.set_state(VALVE, "open", last_updated=(STARTED + timedelta(seconds=2)).isoformat())
    c._shot_room = room
    c._safe_off()
    assert hardware(fake) == [("valve", "close_valve", VALVE)] and room.shot_inflight is None


def test_a_hold_clears_only_once_the_valve_reads_closed(rig):
    c, fake, _clock = rig
    room = c.rooms[0]
    del room.hw["valves"][2]  # a room on hardware it can switch
    c._latch_hardware_fault(room, "zone 1 valve/pump/mainline close not confirmed")
    fake.set_state("input_boolean.kill", "off")
    fake.set_state(VALVE, "open")
    c._recover_hardware_faults()
    assert room.hardware_fault is not None
    fake.set_state(VALVE, "closed")
    c._recover_hardware_faults()
    assert room.hardware_fault is None
