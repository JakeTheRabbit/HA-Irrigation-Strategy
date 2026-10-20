"""Auto setpoints write a zone's ladder so it stays in order after every write.

Home Assistant refuses a moisture level that breaks the ladder (rescue + 3 <= re-water < peak). The
supervisor judges the whole move as one set; written in the order it was wanted, a lower peak landed
before the lower re-water level and was refused, and the move took another loop to finish.
"""
import pytest

import setpoint_supervisor as ss

START = {"p3_emergency_vwc_threshold": 40.0, "p2_vwc_threshold": 60.0, "p1_target_vwc": 65.0,
         "field_capacity": 67.0}


def _kept(ladder):
    return (ladder["p3_emergency_vwc_threshold"] + 3 <= ladder["p2_vwc_threshold"]
            < ladder["p1_target_vwc"])


@pytest.mark.parametrize("want", [
    {"p1_target_vwc": 59.0, "field_capacity": 61.0, "p2_vwc_threshold": 52.0},  # the whole ladder down
    {"p1_target_vwc": 71.0, "field_capacity": 73.0, "p2_vwc_threshold": 68.0},  # and up
])
def test_every_write_leaves_the_ladder_in_order(want):
    ladder = dict(START)
    out = ss.writes(START, want)
    assert {suffix: value for suffix, value, _why in out} == want
    for suffix, value, _why in out:
        ladder[suffix] = value
        assert _kept(ladder), (suffix, ladder)
