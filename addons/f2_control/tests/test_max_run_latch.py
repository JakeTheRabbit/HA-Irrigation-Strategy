"""CS-312: a zone whose shots keep being cut to the room's maximum shot length.

With the room's max-run latch switch ON, MAX_RUN_IN_A_ROW cut shots in a row latch the zone until
its Repairs card is fixed (the switch's `resets` attribute moves). OFF, or absent (an integration
from before the latch), the run is only reported on the heartbeat and the zone keeps watering.
"""

from datetime import datetime

import controller

pytest_plugins = ("test_safety_regressions",)

LATCH = "switch.crop_steering_max_run_latch"
N = controller.MAX_RUN_IN_A_ROW


def _sized(fake):
    """Zone 1: 42 plants of 6.75 L on one 4 L/h dripper each, and a 60 s longest shot. A 20 % shot
    wants about 1215 s (cut); a 0.5 % shot about 30 s (not cut)."""
    for key, value in {
        "plant_count": 42,
        "substrate_volume": 6.75,
        "drippers_per_plant": 1,
        "dripper_flow_rate": 4,
    }.items():
        fake.set_state(f"number.crop_steering_zone_1_{key}", str(value))
    fake.set_state("number.crop_steering_max_shot_duration", "60")


def _shots(rig, monkeypatch, *sizes):
    c, fake, _clock = rig
    _sized(fake)
    ran = []
    monkeypatch.setattr(c, "_execute_shot", lambda *args, **kwargs: ran.append(args[2]))
    for size in sizes:
        c._act_zone(c.rooms[0], 1, None, None, (True, size, "test"), None, True, datetime.now())
    return ran


def test_with_the_switch_on_n_cut_shots_in_a_row_latch_the_zone(rig, monkeypatch):
    c, fake, _clock = rig
    fake.set_state(LATCH, "on", {"resets": 4})
    assert _shots(rig, monkeypatch, *[20] * (N - 1)) == [60] * (N - 1)
    room = c.rooms[0]
    assert c._max_run_hold(room, 1) is None  # one short of the run
    _shots(rig, monkeypatch, 20)
    st = room.state[1]
    assert st["capped_in_a_row"] == N and st["max_run_latch"]["resets"] == 4
    assert "CS-312" in c._max_run_hold(room, 1)
    assert "CS-312" in c._blocked(room, 1)
    assert c._max_run_report(room) == {"1": {"capped": N, "latched": True, "resets": 4}}
    assert c._max_run_hold(room, 2) is None  # the other zone waters on

    fake.set_state(LATCH, "unavailable")  # can't be read: still held
    assert "CS-312" in c._max_run_hold(room, 1)
    fake.set_state(LATCH, "on", {"resets": 4})
    assert "CS-312" in c._max_run_hold(room, 1)

    fake.set_state(LATCH, "on", {"resets": 5})  # the Repairs card was fixed
    assert c._max_run_hold(room, 1) is None
    assert (st["capped_in_a_row"], st["max_run_latch"]) == (0, None)
    assert c._max_run_report(room) == {}


def test_switching_the_latch_off_releases_the_zone(rig, monkeypatch):
    c, fake, _clock = rig
    fake.set_state(LATCH, "on", {"resets": 0})
    _shots(rig, monkeypatch, *[20] * N)
    room = c.rooms[0]
    assert "CS-312" in c._max_run_hold(room, 1)
    fake.set_state(LATCH, "off", {"resets": 0})
    assert c._max_run_hold(room, 1) is None and room.state[1]["max_run_latch"] is None


def test_with_the_switch_off_or_absent_the_run_is_only_reported(rig, monkeypatch):
    for state in ("off", None):
        c, fake, _clock = rig
        fake.states.pop(LATCH, None)
        if state:
            fake.set_state(LATCH, state, {"resets": 0})
        room = c.rooms[0]
        room.state[1]["capped_in_a_row"] = 0
        assert _shots(rig, monkeypatch, *[20] * (N + 2)) == [60] * (N + 2)  # every shot runs
        assert room.state[1]["max_run_latch"] is None
        assert c._max_run_hold(room, 1) is None
        assert c._max_run_report(room) == {"1": {"capped": N + 2, "latched": False}}


def test_a_shot_that_is_not_cut_ends_the_run(rig, monkeypatch):
    c, fake, _clock = rig
    fake.set_state(LATCH, "on", {"resets": 0})
    assert _shots(rig, monkeypatch, *[20] * (N - 1), 0.5, *[20] * (N - 1)) == [60] * (N - 1) + [30] + [60] * (N - 1)
    room = c.rooms[0]
    assert room.state[1]["capped_in_a_row"] == N - 1
    assert room.state[1]["max_run_latch"] is None and c._max_run_report(room) == {}


def test_the_heartbeat_carries_the_report(rig, monkeypatch):
    c, fake, _clock = rig
    fake.set_state(LATCH, "on", {"resets": 1})
    _shots(rig, monkeypatch, *[20] * N)
    c._heartbeat(c.rooms[0], datetime.now(), None)
    _state, attributes = fake.sets["sensor.crop_steering_ai_heartbeat"]
    assert attributes["max_run"] == {"1": {"capped": N, "latched": True, "resets": 1}}
