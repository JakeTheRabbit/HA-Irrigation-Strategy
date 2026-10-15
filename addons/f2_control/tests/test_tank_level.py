"""The tank level: a distance sensor in any distance unit, or a low float, and the drawdown check.

A level sensor is trusted unless it is unavailable (ESPHome sends only changes, so a timeout would cry wolf on
every quiet tank). The case that needs catching is a sensor stuck reading high while the shots drain the tank:
the litres the shots draw are counted against the level's fall, at the litres per 1 % the tank has shown.
"""
import json

import pytest

import controller
import tank_level
from test_plan_hold_never_stops_rescues import rig  # noqa: F401 (rig: a pytest fixture)

DIST, FLOAT = "sensor.tank_distance", "binary_sensor.tank_low"
LEVEL = "sensor.crop_steering_tank_level"
DESCRIPTOR = {
    "tank_distance_sensor": DIST,
    "tank_low_float": FLOAT,
    "tank_level": {"full_mm": 100, "empty_mm": 1100, "float_low_state": "on"},
}


def _mapped(c, fake, room, reading="25.4", unit="cm"):
    room.tank = tank_level.mapping(DESCRIPTOR)
    fake.set_state(DIST, reading, {"unit_of_measurement": unit})
    fake.set_state(FLOAT, "off")
    return room


# ---------------------------------------------------------------- the level, in any distance unit
@pytest.mark.parametrize("reading,unit", [("254", "mm"), ("25.4", "cm"), ("0.254", "m"), ("10", "in"),
                                          ("0.8333333333333334", "ft")])
def test_the_same_tank_read_in_any_distance_unit_gives_the_same_level(rig, reading, unit):  # noqa: F811
    c, fake, room = rig
    _mapped(c, fake, room, reading, unit)
    pct, low = c._tank_level(room)
    assert pct == pytest.approx(84.6)  # 254 mm down, with full at 100 mm and empty at 1100 mm
    assert low is False


def test_a_reading_in_cm_and_in_inches_publish_the_same_level(rig):  # noqa: F811
    c, fake, room = rig
    published = []
    for reading, unit in (("25.4", "cm"), ("10", "in")):
        _mapped(c, fake, room, reading, unit)
        room.tank_drawdown = tank_level.fresh()
        c._watch_tank(room)
        published.append(fake.sets[LEVEL][0])
    assert published[0] == pytest.approx(published[1]) == pytest.approx(84.6)
    assert fake.sets[LEVEL][1]["unit_of_measurement"] == "%"


@pytest.mark.parametrize("state,low_state,low", [("on", "on", True), ("off", "on", False),
                                                 ("off", "off", True), ("unavailable", "on", None)])
def test_the_float_says_low_in_the_state_it_was_mapped_with(rig, state, low_state, low):  # noqa: F811
    c, fake, room = rig
    room.tank = tank_level.mapping({"tank_low_float": FLOAT, "tank_level": {"float_low_state": low_state}})
    fake.set_state(FLOAT, state)
    assert c._tank_level(room) == (None, low)


def test_a_room_with_no_tank_level_mapped_reads_publishes_and_saves_nothing(rig):  # noqa: F811
    c, fake, room = rig
    assert room.tank == {}
    c._watch_tank(room)
    assert LEVEL not in fake.sets
    c._save_state()
    with open(c._state_path) as fh:
        assert "_tank" not in json.load(fh)["default"]


@pytest.mark.parametrize("attrs", [
    {},
    {"tank_distance_sensor": DIST},  # no levels
    {"tank_distance_sensor": DIST, "tank_level": {"full_mm": 900, "empty_mm": 100}},
    {"tank_distance_sensor": DIST, "tank_level": {"full_mm": "100", "empty_mm": 1100}},
])
def test_a_distance_sensor_without_usable_levels_is_not_read(attrs):
    assert tank_level.mapping(attrs) == {}


# ---------------------------------------------------------------- the drawdown check
def _learned(state, litres_per_pct=40.0):
    """A tank that has fallen 10 % while the shots drew 10 x litres_per_pct."""
    tank_level.observe(state, 80.0)
    tank_level.drawn(state, 10 * litres_per_pct)
    assert tank_level.observe(state, 70.0)
    assert state["litres_per_pct"] == pytest.approx(litres_per_pct)
    return state


def test_the_drawdown_check_catches_a_sensor_stuck_high():
    state = _learned(tank_level.fresh())
    for _ in range(4):  # 4 x 60 L at 40 L per 1 %: the level should have fallen 6 %
        tank_level.drawn(state, 60.0)
        trusted = tank_level.observe(state, 70.0)
    assert trusted is False and state["stuck"] is True


def test_a_level_that_falls_with_the_shots_is_trusted_and_teaches_the_litres_per_pct():
    state = _learned(tank_level.fresh())
    for step in range(1, 5):
        tank_level.drawn(state, 60.0)
        assert tank_level.observe(state, 70.0 - 1.5 * step)
    assert not state["stuck"]
    assert state["litres_per_pct"] == pytest.approx(40.0)  # 240 L over 6 %: what it already knew


def test_before_the_litres_per_pct_are_known_nothing_is_called_stuck():
    state = tank_level.fresh()
    tank_level.observe(state, 70.0)
    tank_level.drawn(state, 5000.0)
    assert tank_level.observe(state, 70.0) and not state["stuck"]


def test_a_refill_trusts_the_level_again():
    state = _learned(tank_level.fresh())
    tank_level.drawn(state, 400.0)
    assert not tank_level.observe(state, 70.0)
    assert tank_level.observe(state, 95.0)  # the tank was refilled: the sensor moves
    assert state == {"base_pct": 95.0, "litres": 0.0, "litres_per_pct": 40.0, "stuck": False,
                     "low": False, "over": False}


def test_the_shots_feed_the_check_and_a_stuck_sensor_publishes_no_level(rig, capsys):  # noqa: F811
    c, fake, room = rig
    _mapped(c, fake, room, "400", "mm")  # 70 %
    room.tank_drawdown = _learned(tank_level.fresh())
    c._watch_tank(room)
    assert fake.sets[LEVEL][0] == pytest.approx(70.0)
    for _ in range(5):  # five 5 % shots on 42 plants x 6.75 L: 14.175 L each, 70.875 L, about 1.8 %
        c._advance_shot_counters(room, 1, 5.0)
    assert room.tank_drawdown["litres"] == pytest.approx(70.875)
    c._watch_tank(room)
    assert fake.sets[LEVEL][0] == pytest.approx(70.0)  # not yet enough water drawn to judge
    for _ in range(10):
        c._advance_shot_counters(room, 1, 5.0)
    c._watch_tank(room)
    state, attrs = fake.sets[LEVEL]
    assert state == "unknown" and attrs["stuck"] is True
    assert c._tank_level(room)[0] is None
    assert "it looks stuck" in capsys.readouterr().out
    with open(c._state_path) as fh:
        assert json.load(fh)["default"]["_tank"]["stuck"] is True


# ---------------------------------------------------------------- old installs
@pytest.mark.parametrize("block", [
    {"1": {}},  # every state file before the tank level
    {"_tank": "garbage"},
    {"_tank": {"base_pct": "x", "litres": -3, "litres_per_pct": 0, "stuck": "yes"}},
])
def test_a_state_file_without_a_readable_tank_block_loads_fresh(rig, block):  # noqa: F811
    c, _fake, room = rig
    c._load_room_state(room, {"default": block})
    assert room.tank_drawdown == tank_level.fresh()


def test_the_learned_litres_per_pct_survive_a_restart(rig):  # noqa: F811
    c, _fake, room = rig
    room.tank_drawdown = _learned(tank_level.fresh())
    c._save_state()
    with open(c._state_path) as fh:
        saved = json.load(fh)
    c._load_room_state(room, saved)
    assert room.tank_drawdown == {"base_pct": 70.0, "litres": 0.0, "litres_per_pct": 40.0, "stuck": False,
                                  "low": False, "over": False}


def test_the_descriptor_mapping_is_picked_up_without_an_adoption(rig):  # noqa: F811
    c, fake, room = rig
    fake.set_state("sensor.crop_steering_engine_config", "ok", {"prefix": "", "setup_revision": 0, **DESCRIPTOR})
    c._apply_setup_descriptors()
    assert room.tank == {"distance": DIST, "full_mm": 100.0, "empty_mm": 1100.0, "float": FLOAT,
                         "float_low_state": "on"}
    assert controller.UNITS["distance"]["canonical"] == "mm"
