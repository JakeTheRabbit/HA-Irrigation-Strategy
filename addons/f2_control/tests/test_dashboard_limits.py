"""The limits the dashboard shows come from the controller, never from a copy in the dashboard.

The heartbeat carries how old a reading may be (`max_sensor_age_s`), the longest shot of the last
one the controller sized (`max_shot_s`) and the pore-EC to target ratios a shot is left alone
within (`pore_ec_neutral`); the tank level carries every mark the controller holds by.
"""
import inspect
from datetime import datetime

import pytest

import controller
import tank_level
from crop_steering_engine.defaults import SUBSTRATE_PROFILES
from test_controller import _build
from test_plan_hold_never_stops_rescues import rig  # noqa: F401 (rig: a pytest fixture)
from test_reservoir_minimum import LEVEL, _mapped

pytestmark = pytest.mark.usefixtures("settings_built_in")
BEAT = "sensor.crop_steering_ai_heartbeat"


def _beat(c, fake, room):
    c._heartbeat(room, datetime(2026, 1, 1, 12, 0), False)
    return fake.sets[BEAT][1]


def _room(states=None):
    c, fake = _build(
        {"num_zones": 1, "hardware": {"pump": "switch.p", "mainline": "switch.m",
                                      "valves": {"1": "switch.v1"}}},
        states=states,
    )
    return c, fake, c.rooms[0]


def test_the_heartbeat_carries_the_reading_age_the_controller_reads_with():
    c, fake, room = _room()
    assert _beat(c, fake, room)["max_sensor_age_s"] == controller.SENSOR_MAX_AGE_MIN * 60
    for method in (c._read_sensor, c._unreadable):
        assert inspect.signature(method).parameters["max_age_min"].default == controller.SENSOR_MAX_AGE_MIN


def test_the_heartbeat_carries_the_longest_shot_the_controller_last_sized_with():
    c, fake, room = _room({"number.crop_steering_max_shot_duration": ("600", {})})
    assert _beat(c, fake, room)["max_shot_s"] is None  # no shot sized since the start
    assert c._room_duration_cap(room) == 600.0
    assert _beat(c, fake, room)["max_shot_s"] == 600.0
    fake.set_state("number.crop_steering_max_shot_duration", "2", {})  # not valid: no shot starts
    assert c._room_duration_cap(room) is None
    assert _beat(c, fake, room)["max_shot_s"] is None


def test_the_heartbeat_carries_the_pore_ec_ratios_a_shot_is_left_alone_within():
    c, fake, room = _room()
    profile = SUBSTRATE_PROFILES["generic"]
    low, high = _beat(c, fake, room)["pore_ec_neutral"]
    assert (low, high) == (0.8, 1.0)
    from crop_steering_engine.core import ec_adjust
    for ratio in (low, (low + high) / 2, high):
        assert ec_adjust(3.0, ratio * 2.0, 2.0, profile["ec_adjust_up"], profile["ec_adjust_down"]) == 3.0
    for ratio in (low - 0.01, high + 0.01):
        assert ec_adjust(3.0, ratio * 2.0, 2.0, profile["ec_adjust_up"], profile["ec_adjust_down"]) != 3.0


def test_the_tank_level_carries_every_mark_the_controller_holds_by(rig):  # noqa: F811
    c, fake, room = rig
    _mapped(fake, room, 70)
    c._watch_tank(room)
    attrs = fake.sets[LEVEL][1]
    assert attrs["minimum_pct"] == tank_level.LOW_HOLD_PCT
    assert attrs["release_pct"] == tank_level.LOW_RELEASE_PCT
    assert attrs["over_pct"] == tank_level.OVER_HOLD_PCT
    assert attrs["over_release_pct"] == tank_level.OVER_RELEASE_PCT
