"""The EC-correction minimum interval: an EC correction waits this long after the last shot.

A small shot that makes no runoff stacks salt instead of washing it out, so each correction drains and
is read again before the next. The gap was a fixed 10 minutes; it is now a setting, and 10 stays the
default, so a room nobody changes waters as before. The engine keeps it between 1 minute and 2 hours:
0 would let a correction fire every pass.
"""

from crop_steering_engine import ZoneParams, decide, validate_params
from test_core import P, S

DILUTE = dict(phase="P2", vwc=50, ec=6, ec_smooth=6, feed_ec=3.0)  # 6 / 4 > 1.2 and the feed dilutes


def kind(s, p):
    return decide(s, p)[4].kind


def test_the_default_is_todays_ten_minutes():
    field = ZoneParams.__dataclass_fields__["p2_min_interval_min"]
    assert field.default == 10


def test_a_changed_interval_moves_when_a_correction_may_go():
    p = P(p2_threshold=45, ec_target_p2=4, p2_min_interval_min=25)
    for minutes in (10, 24.9):
        assert kind(S(**DILUTE, minutes_since_shot=minutes), p) != "p2_dilute", minutes
    assert kind(S(**DILUTE, minutes_since_shot=25), p) == "p2_dilute"
    shorter = P(p2_threshold=45, ec_target_p2=4, p2_min_interval_min=5)
    assert kind(S(**DILUTE, minutes_since_shot=5), shorter) == "p2_dilute"


def test_the_engine_keeps_it_between_one_minute_and_two_hours():
    for given, kept in ((0, 1), (1, 1), (10, 10), (500, 120)):
        p, _warnings = validate_params(P(p2_min_interval_min=given))
        assert p.p2_min_interval_min == kept
