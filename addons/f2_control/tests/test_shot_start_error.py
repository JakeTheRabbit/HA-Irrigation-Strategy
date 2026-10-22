"""An error between "a shot is starting" and the first valve command must not wedge the controller.

`_busy` is set before the shot reads its lead times and writes its in-flight record; if either raised,
`_busy` stayed True for good: every later loop returned at once, the in-flight record was never
reconciled, and no room was watered again (CTL-032). And one room's state that cannot be saved must
not make the save raise for every room, nor let a shot open with no record on disk."""
import copy
import json
from datetime import date, datetime, timedelta

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
    with pytest.raises(ValueError):  # the room's pass stops and says so (CS-212, loop_once)
        c._execute_shot(c.rooms[0], 1, 6, 5)
    assert c._busy is False and c._shot_room is None
    assert switched(fake) == []  # nothing opened, and nothing a person may be using was switched off
    assert c.rooms[0].shot_inflight is None
    assert loop_runs(c, monkeypatch)


def unsavable(room, zone=2):
    room.state[zone]["day_hist"] = [object()]  # what json cannot write


def test_a_shot_whose_record_cannot_be_saved_opens_nothing(rig, monkeypatch):
    c, fake = rig
    room = c.rooms[0]
    unsavable(room)
    before = dict(room.state[1])
    with pytest.raises(RuntimeError, match="in-flight record was not saved"):
        c._execute_shot(room, 1, 6, 5)
    assert switched(fake) == []
    assert room.state[1]["daily_vol"] == before["daily_vol"] and room.state[1]["last_shot"] == before["last_shot"]
    assert c._busy is False and c._shot_room is None and room.shot_inflight is None
    assert loop_runs(c, monkeypatch)


def test_a_shot_is_refused_when_the_state_file_cannot_be_written(rig, tmp_path):
    c, fake = rig
    c._state_path = str(tmp_path / "missing" / "state.json")
    with pytest.raises(RuntimeError, match="state file could not be written"):
        c._execute_shot(c.rooms[0], 1, 6, 5)
    assert switched(fake) == [] and c._busy is False and c.rooms[0].shot_inflight is None


def test_a_room_whose_state_cannot_be_saved_fails_one_pass_then_runs_on_its_last_saved_state(rig):
    c, fake = rig
    room = c.rooms[0]
    room.state[1]["daily_vol"] = 4.0
    assert c._save_state()
    unsavable(room)
    c._save_state()
    assert list(c._unsaved_rooms) == ["default"]
    with pytest.raises(RuntimeError, match="last saved state was loaded back"):  # loud: CS-212 (loop_once)
        c._loop_room(room, NOW)
    assert c._unsaved_rooms == {} and room.state[1]["daily_vol"] == 4.0  # never less water counted
    assert room.state[2]["day_hist"] == []
    c._restore_unsaved_room(room)  # the next pass is not stopped
    c._execute_shot(room, 1, 6, 5)  # and can shoot
    assert ("turn_on", "switch.v1") in switched(fake)


def test_a_shot_fired_after_the_last_good_save_still_holds_the_interval(rig):
    c, _ = rig
    room = c.rooms[0]
    today = date.today()
    st = room.state[1]
    st.update(last_daily_reset=today, daily_vol=2.0, shots=1, last_shot=datetime.now() - timedelta(hours=3))
    st["water_history"] = [{"grow_day": today.isoformat(), "litres": 2.0, "complete": False}]
    assert c._save_state()
    unsavable(room)  # then the room cannot save, and a shot is counted in memory only
    st.update(daily_vol=3.0, shots=2, last_shot=datetime.now())
    st["water_history"] = [{"grow_day": today.isoformat(), "litres": 3.0, "complete": False}]
    c._save_state()
    with pytest.raises(RuntimeError, match="loaded back"):
        c._loop_room(room, NOW)
    st = room.state[1]
    assert c._minutes_since_shot(st, datetime.now()) < 1  # the shot interval still counts from that shot
    assert (st["daily_vol"], st["shots"], st["water_history"][-1]["litres"]) == (3.0, 2, 3.0)


def test_a_new_day_in_memory_keeps_its_own_counters(rig):
    c, _ = rig
    room = c.rooms[0]
    today = date.today()
    st = room.state[1]
    st.update(last_daily_reset=today - timedelta(days=1), daily_vol=9.0, shots=6)
    assert c._save_state()
    unsavable(room)
    st.update(last_daily_reset=today, daily_vol=1.5, shots=1)  # today's water, less than yesterday's
    c._save_state()
    with pytest.raises(RuntimeError, match="loaded back"):
        c._loop_room(room, NOW)
    st = room.state[1]
    assert (st["last_daily_reset"], st["daily_vol"], st["shots"]) == (today, 1.5, 1)


def test_a_kept_hold_that_cannot_be_saved_stays_stopped(rig):
    c, _ = rig
    room = c.rooms[0]
    assert c._save_state()
    room.hardware_fault = {"reason": object(), "entities": [], "switches": []}  # kept from memory, unsaveable
    c._save_state()
    for _ in range(2):
        with pytest.raises(RuntimeError, match="stays stopped"):
            c._loop_room(room, NOW)
    assert room.hardware_fault is not None  # the hold is never dropped


def test_a_room_with_no_saved_state_to_go_back_to_stays_stopped(rig):
    c, fake = rig
    room = c.rooms[0]
    room.state[1]["daily_vol"] = 4.0
    unsavable(room)
    c._save_state()
    for _ in range(2):
        with pytest.raises(RuntimeError, match="stays stopped"):
            c._loop_room(room, NOW)
    assert room.state[1]["daily_vol"] == 4.0  # nothing reset: the daily cap is not lifted
    room.state[2]["day_hist"] = []  # once it saves, the room runs again
    c._restore_unsaved_room(room)
    assert c._unsaved_rooms == {}


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
    bad.state = {1: dict(good.state[1])}
    unsavable(bad, 1)
    c.rooms = [bad, good]
    good.shot_inflight = {"zone": 1, "valve": "switch.v1", "mainline": "switch.m", "pump": "switch.p",
                          "started": "2026-10-22T00:00:00+00:00"}
    assert c._save_state()
    assert saved(c)["default"]["_shot_inflight"]["valve"] == "switch.v1"
    assert "other" not in saved(c)  # the bad room keeps what it had saved before (here: nothing)
    assert list(c._unsaved_rooms) == ["other"]
