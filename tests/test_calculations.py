"""How long a shot runs, as the integration's shot-duration sensors work it out.

The rule is the engine's (crop-steering-engine/src/crop_steering_engine/shot_length.py), copied into
the integration as generated/shot_length.py, so these are the seconds the controller runs.
"""

import math

import pytest
from custom_components.crop_steering.generated.shot_length import (
    MIN_SHOT_S,
    raw_seconds,
    shot_seconds,
    valid_cap,
)


def _lph(litres_per_hour):
    return litres_per_hour / 3600.0


@pytest.mark.parametrize(
    "size, substrate, flow_lph, seconds",
    [
        (5.0, 10.0, 2.0, 900.0),  # P2 maintenance: 500 mL at 2 L/hr
        (2.0, 10.0, 2.0, 360.0),  # P1 first ramp shot
        (3.0, 10.0, 2.0, 540.0),  # P3 rescue shot
        (5.0, 15.0, 3.0, 900.0),
        (5.0, 50.0, 5.0, 1800.0),
        (0.5, 10.0, 2.0, 90.0),
        (15.0, 10.0, 2.0, 2700.0),
        (1.0, 1.0, 0.1, 360.0),
        (20.0, 200.0, 50.0, 2880.0),
        (2.0, 11.4, 2 * 3.8, 108.0),  # two 3.8 L/hr drippers share each plant's shot
    ],
)
def test_a_shot_is_its_share_of_the_substrate_over_the_flow(
    size, substrate, flow_lph, seconds
):
    assert math.isclose(raw_seconds(size, substrate, _lph(flow_lph)), seconds)


def test_whole_seconds_within_the_minimum_and_the_room_limit():
    assert shot_seconds(108.9, 900.0) == 108
    assert shot_seconds(540.0, 60.0) == 60
    assert shot_seconds(2.0, 900.0) == MIN_SHOT_S


@pytest.mark.parametrize("cap", [None, 3, float("nan"), "unknown"])
def test_a_limit_that_is_not_one_is_none_and_the_controller_starts_no_shot(cap):
    assert valid_cap(cap) is None
