"""P3 Time Between Shots: a P3 emergency shot waits this long after the last shot.

A rescue goes in under the probe and takes minutes to reach it. Judged again a pass (60 s) later the
zone still reads under the rescue level, so a stuck-low probe got a full pump and valve cycle every
pass all night. The gap counts from the last shot, so the first rescue of a night still goes at once.
"""

from crop_steering_engine import decide, waiting_for
from test_core import P, S

NIGHT = dict(phase="P3", vwc=30, lights_on=False, hours_to_lights_on=6)


def kind(s, p):
    return decide(s, p)[4].kind


def test_the_first_rescue_goes_at_once_and_the_next_waits_the_gap_from_the_last_shot():
    p = P(p3_emergency_floor=40, p3_time_between_min=10)
    assert kind(S(**NIGHT, minutes_since_shot=240), p) == "p3_emergency"  # the last shot was the day's
    assert kind(S(**NIGHT, minutes_since_shot=1e9), p) == "p3_emergency"  # never watered at all
    for minutes in (0, 1, 5, 9.9):
        result = decide(S(**NIGHT, minutes_since_shot=minutes), p)
        assert result[2] is False and result[4].kind == "idle", minutes
    assert kind(S(**NIGHT, minutes_since_shot=10), p) == "p3_emergency"


def test_a_night_with_a_stuck_low_probe_gets_one_rescue_every_gap_not_every_pass():
    p = P(p3_emergency_floor=40, p3_time_between_min=10)
    since, fired = 600.0, []
    for minute in range(60):  # one pass a minute for an hour; the probe never moves
        if decide(S(**NIGHT, minutes_since_shot=since), p)[2]:
            fired.append(minute)
            since = 0.0
        since += 1.0
    assert fired == [0, 10, 20, 30, 40, 50]


def test_zero_turns_it_off_and_none_keeps_the_old_behaviour():
    for gap in (0, None):
        p = P(p3_emergency_floor=40, p3_time_between_min=gap)
        assert kind(S(**NIGHT, minutes_since_shot=1), p) == "p3_emergency", gap


def test_the_gap_holds_only_the_p3_emergency():
    p = P(p2_threshold=45, p3_time_between_min=10)
    assert kind(S(phase="P2", vwc=40, minutes_since_shot=1), p) == "p2_topup"
    above = {**NIGHT, "vwc": 45}  # above the rescue level: nothing is due, gap or not
    assert kind(S(**above, minutes_since_shot=1), p) == "idle"


def test_waiting_for_says_when_the_next_rescue_may_go():
    p = P(p3_emergency_floor=40, p3_time_between_min=10)
    rescue = next(i for i in waiting_for(S(**NIGHT, minutes_since_shot=3), p) if i["rule"] == "p3_emergency")
    assert (rescue["op"], rescue["value"], rescue["in_min"]) == ("<", 40, 7.0)
    old = next(i for i in waiting_for(S(**NIGHT, minutes_since_shot=3), P()) if i["rule"] == "p3_emergency")
    assert "in_min" not in old
