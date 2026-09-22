"""While a grow-strategy plan is held, decide() stops steering but keeps the water-safety rules.

The controller holds routine shots while the room's plan is held, stale or missing. It used to hold every
shot, and a routine decision also masks the rescues behind it: a zone drying in P2 is a top-up first, so
the watchdog never came up and the zone got nothing all day. ZoneSnapshot.steering_held asks decide() for
the rescues only: the P3 emergency, the lights-on watchdog and the minimum-daily floor.
"""

import pytest

from crop_steering_engine import decide
from test_core import P, S


def held(**snap):
    return S(steering_held=True, **snap)


def kind_of(result):
    return result[4].kind


@pytest.mark.parametrize(
    "snap,params",
    [
        (dict(phase="P0", vwc=50, ec=12, feed_ec=3, dryback_pct=5), dict(ec_target_p0=2, max_ec=15)),
        (dict(phase="P1", vwc=50, minutes_since_shot=20), {}),
        (dict(phase="P1", vwc=66, ec=8, feed_ec=3, minutes_since_shot=20), dict(max_ec=12)),
        (dict(phase="P2", vwc=40, ec=8.5, feed_ec=3), {}),
        (dict(phase="P2", vwc=55, ec=7.5, feed_ec=3, minutes_since_shot=30), {}),
        (dict(phase="P2", vwc=40, minutes_since_shot=30), {}),
        (dict(phase="P2", vwc=55, ec=10, feed_ec=3), {}),
    ],
    ids=["p0_ec_flush", "p1_ramp", "p1_flush", "p2_rescue", "p2_dilute", "p2_topup", "flush_high_ec"],
)
def test_a_held_zone_is_not_steered(snap, params):
    assert decide(S(**snap), P(**params))[2] is True  # steered when the plan is fine
    result = decide(held(**snap), P(**params))
    assert result[2] is False and kind_of(result) == "idle"


def test_a_zone_drying_in_p2_gets_the_watchdog_not_the_top_up_it_would_have_had():
    snap = dict(phase="P2", vwc=40, minutes_since_shot=200)
    assert kind_of(decide(S(**snap), P())) == "p2_topup"
    result = decide(held(**snap), P(watchdog_hours=3))
    assert result[2] is True and kind_of(result) == "watchdog" and result[4].cap_exempt
    assert "WATCHDOG" in result[4]


def test_the_minimum_daily_floor_fires_where_a_top_up_would_have():
    snap = dict(phase="P2", vwc=40, daily_vol=3, minutes_since_shot=30)
    assert kind_of(decide(S(**snap), P(min_daily_volume=10))) == "p2_topup"
    result = decide(held(**snap), P(min_daily_volume=10))
    assert result[2] is True and kind_of(result) == "min_daily"


def test_the_minimum_daily_floor_still_fires_in_the_morning_dryback_and_the_ramp():
    for phase in ("P0", "P1"):
        result = decide(held(phase=phase, vwc=58, daily_vol=0, minutes_since_shot=30), P(min_daily_volume=10))
        assert kind_of(result) == "min_daily", phase


def test_the_overnight_emergency_fires():
    result = decide(held(phase="P3", vwc=35, lights_on=False), P())
    assert result[2] is True and kind_of(result) == "p3_emergency" and result[3] == 2


def test_phases_still_move_while_held():
    assert decide(held(phase="P2", vwc=55, lights_on=False), P())[0] == "P3"
    assert decide(held(phase="P3", vwc=55, lights_just_on=True), P())[0] == "P0"
    assert decide(held(phase="P0", vwc=44), P())[0] == "P1"


def test_high_ec_with_water_that_cannot_dilute_still_blocks_every_shot():
    result = decide(held(phase="P2", vwc=40, ec=10, feed_ec=11, minutes_since_shot=200), P())
    assert result[2] is False and kind_of(result) == "block_high_ec"


def test_high_ec_that_steering_would_flush_leaves_room_for_the_watchdog():
    result = decide(held(phase="P2", vwc=40, ec=10, feed_ec=3, minutes_since_shot=200), P())
    assert kind_of(result) == "watchdog"


def test_not_held_is_exactly_as_before():
    for snap in (dict(phase="P2", vwc=40), dict(phase="P3", vwc=35, lights_on=False), dict(phase="P1", vwc=50)):
        assert decide(S(**snap), P()) == decide(S(steering_held=False, **snap), P())
