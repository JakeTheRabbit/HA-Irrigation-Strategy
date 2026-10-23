"""How long a shot runs (shot_length.py): the one rule the controller times shots with and the
integration's shot-duration sensors show."""

import math

import pytest

from crop_steering_engine.shot_length import (
    DEFAULT_MAX_SHOT_S,
    MIN_SHOT_S,
    raw_seconds,
    shot_seconds,
    valid_cap,
)


def test_a_shot_is_its_share_of_the_substrate_over_the_flow():
    # 2% of 11.4 L through two 3.8 L/hr drippers: 108 s, not the 216 one dripper would take.
    assert math.isclose(raw_seconds(2.0, 11.4, 2 * 3.8 / 3600.0), 108.0)
    # 5% of 10 L at 2 L/hr: 900 s
    assert math.isclose(raw_seconds(5.0, 10.0, 2.0 / 3600.0), 900.0)


def test_whole_seconds_within_the_minimum_and_the_room_limit():
    assert shot_seconds(108.9, 900.0) == 108
    assert shot_seconds(540.0, 60.0) == 60
    assert shot_seconds(2.0, 900.0) == MIN_SHOT_S


@pytest.mark.parametrize("value", [60, "60", 60.0, MIN_SHOT_S])
def test_a_room_limit_of_five_seconds_or_more_is_one(value):
    assert valid_cap(value) == float(value)


@pytest.mark.parametrize(
    "value",
    [None, "", "unknown", "abc", 4.9, 0, -60, float("nan"), "inf", float("-inf")],
)
def test_a_room_limit_that_is_not_one_is_none_never_a_default(value):
    assert valid_cap(value) is None


def test_a_room_without_a_limit_runs_within_fifteen_minutes():
    assert DEFAULT_MAX_SHOT_S == 900.0
