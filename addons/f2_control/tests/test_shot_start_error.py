"""An error between "a shot is starting" and the first valve command must not wedge the controller.

`_busy` is set before the shot reads its lead times and writes its in-flight record; if either raised,
`_busy` stayed True for good: every later loop returned at once, the in-flight record was never
reconciled, and no room was watered again (CTL-032). And one room's state that cannot be saved must
not make the save raise for every room."""
import copy
import json
from datetime import datetime

import pytest

import controller
import fake_ha

NOW = datetime(2026, 10, 22, 12, 0)


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
    for name in ("ha_get", "ha_get_status", "ha_call", "ha_get_all", "ha_set", "ha_history"):
        monkeypatch.setattr(controller, name, getattr(fake, name))
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
    monkeypatch.setattr(controller.time, "sleep", lambda s: None)
    return c, fake


def switched(fake):
    return [(svc, d["entity_id"]) for dom, svc, d in fake.calls if dom == "switch"]


def saved(c):
    with open(c._state_path) as fh:
        return json.load(fh)


def loop_runs(c, monkeypatch):
    """True when loop_once gets past its busy guard (stopped right there: nothing else runs)."""
    reached = []

    def stop(*a, **k):
        reached.append(True)
        raise RuntimeError("stop")

    monkeypatch.setattr(c, "_notify_config", stop)
    try:
        c.loop_once(NOW)
    except RuntimeError:
        pass
    return bool(reached)


def test_a_bad_lead_time_before_any_valve_opens_does_not_wedge_the_controller(rig, monkeypatch):
    c, fake = rig
    monkeypatch.setattr(controller, "parameter_override",
                        lambda snap, zone, suffix: "junk" if suffix == "pump_prime_time" else None)
    c._execute_shot(c.rooms[0], 1, 6, 5)
    assert c._busy is False and c._shot_room is None
    assert switched(fake) == []  # nothing opened, and nothing a person may be using was switched off
    assert c.rooms[0].shot_inflight is None
    assert loop_runs(c, monkeypatch)


def test_a_failed_write_ahead_save_does_not_wedge_the_controller(rig, monkeypatch):
    c, fake = rig
    real = c._save_state

    def broken():
        if c.rooms[0].shot_inflight:
            raise TypeError("a room's state cannot be saved")
        return real()

    monkeypatch.setattr(c, "_save_state", broken)
    c._execute_shot(c.rooms[0], 1, 6, 5)
    assert c._busy is False and c._shot_room is None
    assert switched(fake) == []
    assert c.rooms[0].shot_inflight is None  # nothing opened: no record left to block the room's shots
    assert loop_runs(c, monkeypatch)


def test_a_normal_shot_still_opens_closes_and_clears_its_record(rig):
    c, fake = rig
    c._execute_shot(c.rooms[0], 1, 6, 5)
    assert switched(fake) == [("turn_on", "switch.p"), ("turn_on", "switch.m"), ("turn_on", "switch.v1"),
                              ("turn_off", "switch.v1"), ("turn_off", "switch.m"), ("turn_off", "switch.p")]
    assert c._busy is False and c.rooms[0].shot_inflight is None
    assert "_shot_inflight" not in saved(c)["default"]


def test_one_rooms_bad_state_does_not_stop_the_others_saving(rig):
    c, _ = rig
    good = c.rooms[0]
    assert c._save_state()
    bad = copy.copy(good)
    bad.slug = "other"
    bad.state = {1: None}  # cannot be serialised
    c.rooms = [bad, good]
    good.shot_inflight = {"zone": 1, "valve": "switch.v1", "mainline": "switch.m", "pump": "switch.p",
                          "started": "2026-10-22T00:00:00+00:00"}
    assert c._save_state()
    assert saved(c)["default"]["_shot_inflight"]["valve"] == "switch.v1"
    assert "other" not in saved(c)  # the bad room keeps what it had saved before (here: nothing)
