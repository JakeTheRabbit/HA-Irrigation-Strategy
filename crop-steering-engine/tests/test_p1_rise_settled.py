"""The P1 rise rule on a settled reading, with the extra shots capped, budgeted and held while a table is backed up.

P1 reads its target, gives one more shot, and ends once a shot no longer raises the reading by the zone's
p1_rise_pts (0.5 unless changed). The rise used to be the change in the zone's raw running highest reading, so a
probe that jumps by half a point could earn another shot, and another, outside the daily budget. The rise is now
measured between settled readings (the median of the last minutes of readings), with the learned gain raising the
bar when a shot should have lifted the reading much further. A clean, settled rise ends P1 exactly as before.
"""
import random

import pytest

from crop_steering_engine import decide, settled_reading, waiting_for
from crop_steering_engine.core import P1_MAX_EXTRA_SHOTS, P1_RISE_PTS, SETTLED_VWC_MIN
from test_core import P, S


def test_the_settings_fall_back_to_the_rule_as_it_was():
    assert (P1_RISE_PTS, P1_MAX_EXTRA_SHOTS) == (0.5, 3)
    p = P()
    assert (p.p1_rise_pts, p.p1_max_extra_shots) == (0.5, 3)


def test_a_settled_reading_is_the_median_of_the_readings():
    assert settled_reading([62.0, 62.4, 61.6, 70.0, 62.1]) == 62.1
    assert settled_reading([61.0, 63.0]) == 62.0
    assert settled_reading([None, float("nan"), 60.0]) == 60.0
    assert settled_reading([]) is None


def rule_12c6d1a(reached, shot_count, min_shots, extra, waited, rise):
    """The P1 to P2 rise rule at 12c6d1a (core.py there): P2 once the extra shot raised the peak by < 0.5."""
    return reached and shot_count >= min_shots and extra >= 1 and waited and rise is not None and rise < 0.5


@pytest.mark.parametrize("before", [58.0, 61.0, 64.5])
@pytest.mark.parametrize("rise", [-0.4, 0.0, 0.2, 0.49, 0.5, 0.51, 1.0, 2.5])
@pytest.mark.parametrize("extra", [0, 1, 2])
@pytest.mark.parametrize("since", [5, 15, 40])
@pytest.mark.parametrize("min_shots", [0, 3, 8])
def test_a_clean_settled_rise_ends_p1_as_12c6d1a_did(before, rise, extra, since, min_shots):
    now = before + rise
    params = P(p1_target=58, p1_min_shots=min_shots)
    snap = S(phase="P1", vwc=now, peak_vwc=now, shot_count=5, minutes_since_shot=since, p1_reached=True, p1_extra_shots=extra,
             p1_peak_before_shot=before if extra else None, vwc_settled=now,
             p1_settled_before_shot=before if extra else None)
    expected = "P2" if rule_12c6d1a(True, 5, min_shots, extra, since >= 15, rise if extra else None) else "P1"
    assert decide(snap, params)[0] == expected


def _ramp_end(seed, minutes=240, true_vwc=62.0, jitter=0.5):
    """A zone at its target whose slab is full (no shot raises it), read every minute with +/- jitter noise, run
    through decide() the way the controller drives it. Its last ramp shot went 20 minutes before the run starts.
    Returns the number of extra shots it was given."""
    rng = random.Random(seed)
    params = P(p1_target=60)
    readings = [(t, true_vwc + rng.uniform(-jitter, jitter)) for t in range(-19, 0)]
    extra, last_shot, before, phase = 0, -20, None, "P1"
    for minute in range(minutes):
        readings.append((minute, true_vwc + rng.uniform(-jitter, jitter)))
        since = minute - last_shot
        window = [v for t, v in readings if t > minute - SETTLED_VWC_MIN and t > last_shot]
        snap = S(phase=phase, vwc=readings[-1][1], peak_vwc=max(v for _, v in readings), shot_count=4 + extra,
                 minutes_since_shot=since, p1_reached=True, p1_extra_shots=extra, vwc_settled=settled_reading(window),
                 p1_settled_before_shot=before)
        phase, _, fire, _, reason = decide(snap, params)
        if phase != "P1":
            return extra
        if fire:
            assert reason.kind == "p1_extra"
            before = settled_reading([v for t, v in readings if t > minute - SETTLED_VWC_MIN])
            extra, last_shot = extra + 1, minute
    return extra


@pytest.mark.parametrize("seed", range(100))
def test_a_jumpy_reading_earns_no_extra_shot(seed):
    # The one extra shot the rule always gives at the target, and none for the jitter after it.
    assert _ramp_end(seed) == 1


def test_a_settled_rise_keeps_p1_going_and_a_small_one_ends_it():
    extra = dict(phase="P1", vwc=62, peak_vwc=63, shot_count=5, minutes_since_shot=20, p1_extra_shots=1,
                 p1_peak_before_shot=61, p1_settled_before_shot=61.5)
    rose = decide(S(**extra, vwc_settled=62.1), P())
    assert rose[0] == "P1" and rose[2] and rose[4].kind == "p1_extra"
    flat = decide(S(**extra, vwc_settled=61.8), P())  # the raw peak rose 2, the settled reading 0.3
    assert flat[0] == "P2" and "raised the settled reading 0.3 (< 0.5)" in flat[4]


def test_the_rise_needed_is_the_zones_setting():
    extra = dict(phase="P1", vwc=62, peak_vwc=62, shot_count=5, minutes_since_shot=20, p1_extra_shots=1,
                 p1_settled_before_shot=61.3, vwc_settled=62)
    assert decide(S(**extra), P())[0] == "P1"
    assert decide(S(**extra), P(p1_rise_pts=1.0))[0] == "P2"


def test_a_learned_gain_raises_the_rise_needed():
    # The last shot should have lifted the reading 3 points: 0.7 is under 0.3 of that, so the slab is full.
    extra = dict(phase="P1", vwc=62, peak_vwc=62, shot_count=5, minutes_since_shot=20, p1_extra_shots=1,
                 p1_settled_before_shot=61.3, vwc_settled=62)
    assert decide(S(**extra), P())[0] == "P1"
    gained = decide(S(**extra, p1_expected_rise=3.0), P())
    assert gained[0] == "P2" and "(< 0.9)" in gained[4]
    assert decide(S(**extra, p1_expected_rise=1.0), P())[0] == "P1"  # 0.3 of 1 is under the setting's 0.5


def test_the_extra_shots_stop_at_the_cap():
    extra = dict(phase="P1", vwc=62, peak_vwc=66, shot_count=6, minutes_since_shot=20, p1_peak_before_shot=63)
    assert decide(S(**extra, p1_extra_shots=2), P())[0] == "P1"  # still rising, under the cap
    capped = decide(S(**extra, p1_extra_shots=3), P())
    assert capped[0] == "P2" and capped[2] is False and "P1 extra shots 3/3" in capped[4]
    assert decide(S(**extra, p1_extra_shots=1), P(p1_max_extra_shots=1))[0] == "P2"


def test_the_extra_shots_count_toward_the_daily_budget():
    at_target = dict(phase="P1", vwc=62, shot_count=4, minutes_since_shot=20)
    under = decide(S(**at_target, daily_vol=200), P(max_daily_volume=300))
    assert under[2] and under[4].kind == "p1_extra" and not under[4].cap_exempt
    spent = decide(S(**at_target, daily_vol=300), P(max_daily_volume=300))
    assert spent[0] == "P2" and spent[2] is False


def test_no_extra_shot_while_the_table_is_backed_up():
    at_target = dict(phase="P1", vwc=62, shot_count=4, minutes_since_shot=20)
    held = decide(S(**at_target, backed_up=True), P())
    assert held[0] == "P1" and held[2] is False and held[4].kind == "hold_backed_up"
    assert decide(S(**at_target), P())[4].kind == "p1_extra"  # cleared: the extra shot goes
    ramp = decide(S(phase="P1", vwc=50, minutes_since_shot=20, backed_up=True), P())
    assert ramp[2] and ramp[4].kind == "p1_ramp"  # the ramp under the target is not an extra shot


def test_waiting_for_says_the_rise_needed():
    snap = S(phase="P1", vwc=62, shot_count=5, p1_extra_shots=1, p1_expected_rise=3.0)
    done = next(c for c in waiting_for(snap, P()) if c["rule"] == "p1_done")
    assert done["rise_min"] == 0.9
    done = next(c for c in waiting_for(snap, P(p1_rise_pts=1.2)) if c["rule"] == "p1_done")
    assert done["rise_min"] == 1.2
