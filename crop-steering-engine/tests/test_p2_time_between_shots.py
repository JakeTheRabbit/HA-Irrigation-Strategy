"""P2 Time Between Shots: a P2 top-up waits this long after the last shot.

A top-up goes in under the probe and takes minutes to reach it. Judged again a pass (60 s) later the
zone still reads under the re-water threshold, so it got another top-up every pass until the first
one arrived. The gap counts from the last shot of any kind. 0 is off, and is the default.
"""

from crop_steering_engine import decide, validate_params, waiting_for
from test_core import P, S

DAY = dict(phase="P2", vwc=40, ec=6, ec_smooth=6)  # under the 45 re-water threshold, EC on target


def kind(s, p):
    return decide(s, p)[4].kind


def test_a_top_up_waits_the_gap_from_the_last_shot():
    p = P(p2_threshold=45, p2_time_between_min=8)
    for minutes in (0, 1, 5, 7.9):
        result = decide(S(**DAY, minutes_since_shot=minutes), p)
        assert result[2] is False and result[4].kind == "idle", minutes
    assert kind(S(**DAY, minutes_since_shot=8), p) == "p2_topup"


def test_a_probe_that_reads_low_gets_one_top_up_every_gap_not_every_pass():
    p = P(p2_threshold=45, p2_time_between_min=5)
    since, fired = 99.0, []
    for minute in range(30):  # one pass a minute; the probe never moves
        if decide(S(**DAY, minutes_since_shot=since), p)[2]:
            fired.append(minute)
            since = 0.0
        since += 1.0
    assert fired == [0, 5, 10, 15, 20, 25]


def test_zero_and_the_default_keep_todays_behaviour():
    for p in (P(p2_threshold=45, p2_time_between_min=0), P(p2_threshold=45)):
        assert p.p2_time_between_min == 0
        assert kind(S(**DAY, minutes_since_shot=0), p) == "p2_topup"


def test_the_gap_holds_only_the_top_up():
    p = P(p2_threshold=45, p2_time_between_min=60, ec_target_p2=4, p2_min_interval_min=10)
    dilute = {**DAY, "ec": 6, "ec_smooth": 6, "feed_ec": 3.0}  # 6 / 4 > 1.2 and the feed dilutes
    assert kind(S(**dilute, minutes_since_shot=10), p) == "p2_dilute"
    night = dict(phase="P3", vwc=30, lights_on=False, hours_to_lights_on=6)
    assert kind(S(**night, minutes_since_shot=1), p) == "p3_emergency"


def test_waiting_for_says_when_the_next_top_up_may_go():
    p = P(p2_threshold=45, p2_time_between_min=8)
    topup = next(i for i in waiting_for(S(**DAY, minutes_since_shot=3), p) if i["rule"] == "p2_topup")
    assert (topup["op"], topup["value"], topup["in_min"]) == ("<", 45, 5.0)
    off = next(i for i in waiting_for(S(**DAY, minutes_since_shot=3), P()) if i["rule"] == "p2_topup")
    assert "in_min" not in off


def test_the_engine_keeps_it_between_zero_and_two_hours():
    for given, kept in ((-1, 0), (0, 0), (30, 30), (500, 120)):
        p, _warnings = validate_params(P(p2_time_between_min=given))
        assert p.p2_time_between_min == kept
