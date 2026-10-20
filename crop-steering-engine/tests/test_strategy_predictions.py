"""Predictive dryback uses remaining VWC points, not relative percent per hour."""

from crop_steering_engine import decide
from test_core import P, S


def test_predictive_dryback_converts_relative_drop_to_actual_vwc_points():
    result = decide(
        S(
            vwc=60,
            peak_vwc=60,
            dryback_rate=1,
            hours_to_lights_off=2,
            hours_to_lights_on=6,
            ec=3,
        ),
        P(dryback_target=10),
    )
    assert result[0] == "P3"
    assert "need 6.0h" in result[4]


def test_predictive_dryback_uses_only_remaining_drop():
    result = decide(
        S(
            vwc=57,
            peak_vwc=60,
            dryback_rate=1,
            hours_to_lights_off=2,
            hours_to_lights_on=3,
            ec=3,
        ),
        P(dryback_target=10),
    )
    assert "need 3.0h" in result[4]
