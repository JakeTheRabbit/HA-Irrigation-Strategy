"""P1 ends when the ramp stalls under its target.

Seen live: zones read 25-28 % against peak targets of 40-51 %, ramp shots kept firing, growing each time, and the
settled reading did not move. P1 used to end only at the target (plus the extra-shot rise rule) or at the maximum
shots. Now p1_stall_shots ramp shots in a row (2 unless changed) that each raise the settled reading by less than
the rise P1 needs end it, and the rest of that grow-day re-waters under what the zone reached. Never while the probe
is in doubt: then the ramp runs on as before.
"""
import pytest

from crop_steering_engine import decide
from crop_steering_engine.core import P1_STALL_SHOTS, p1_stall, p1_stall_rewater, validate_params
from test_core import P, S


def ramp(**kw):
    """A zone in its ramp at 25 % against a 45 % target, 15 min after its last shot, settled readings given."""
    base = dict(phase="P1", vwc=25.1, peak_vwc=40.0, shot_count=4, minutes_since_shot=20, vwc_settled=25.1,
                p1_settled_before_shot=25.2, p1_flat_shots=1)
    base.update(kw)
    return S(**base)


def params(**kw):
    base = dict(p1_target=45, field_capacity=50, p2_threshold=38, p3_emergency_floor=20, p1_max_shots=12)
    base.update(kw)
    return P(**base)


def test_the_default_is_two_shots():
    assert P1_STALL_SHOTS == 2 and P().p1_stall_shots == 2


def test_the_live_sequence_25_252_251_hands_over_and_rewaters_under_it():
    # shot 1: 25.0 -> 25.2 (counted by the caller as one flat shot); shot 2: 25.2 -> 25.1
    first = ramp(vwc=25.2, vwc_settled=25.2, p1_settled_before_shot=25.0, p1_flat_shots=0, shot_count=1)
    assert p1_stall(first, params()) == 1
    assert decide(first, params())[0] == "P1"  # one flat shot: the ramp gives another
    phase, thr, fire, _size, reason = decide(ramp(), params())
    assert phase == "P2"
    assert reason.startswith("P1 stalled at 25.2%: 2 shots did not raise moisture")
    assert thr == pytest.approx(23.7) and thr < 25.1  # 1.5 under the stalled peak, not the unreachable 38
    assert not fire  # 25.1 is over the day's re-water point: no top-up machine-gun


def test_a_shot_that_rises_resets_the_count():
    rose = ramp(vwc=26.0, vwc_settled=26.0, p1_settled_before_shot=25.1, p1_flat_shots=1)
    assert p1_stall(rose, params()) == 0
    phase, _thr, fire, _size, reason = decide(rose, params())
    assert phase == "P1" and fire and reason.kind == "p1_ramp"


@pytest.mark.parametrize("doubt", [dict(backed_up=True), dict(p1_probe_suspect=True)])
def test_a_probe_in_doubt_keeps_the_ramp_going(doubt):
    phase, _thr, fire, _size, reason = decide(ramp(**doubt), params())
    assert phase == "P1"
    assert fire and reason.kind == "p1_ramp"


def test_no_settled_readings_no_stall():
    assert p1_stall(ramp(vwc_settled=None), params()) == 0
    assert decide(ramp(vwc_settled=None), params())[0] == "P1"


def test_it_waits_out_the_time_between_shots_and_the_minimum_shots():
    assert decide(ramp(minutes_since_shot=5), params())[0] == "P1"
    assert decide(ramp(shot_count=4), params(p1_min_shots=6))[0] == "P1"


def test_off_at_zero_and_the_learned_gain_raises_the_bar():
    assert decide(ramp(), params(p1_stall_shots=0))[0] == "P1"
    # a 0.8 rise passes the 0.5 default, but not 0.3 x a 4-point expected rise
    snap = ramp(vwc=26.0, vwc_settled=26.0, p1_settled_before_shot=25.2, p1_expected_rise=4.0)
    assert decide(snap, params())[0] == "P2"


def test_target_reached_keeps_the_old_rule():
    # At the target the extra-shot rule decides, as before: one extra shot first.
    at = ramp(vwc=45.5, vwc_settled=45.5, p1_settled_before_shot=45.4, p1_reached=True, p1_extra_shots=0)
    phase, _thr, fire, _size, reason = decide(at, params())
    assert phase == "P1" and fire and reason.kind == "p1_extra"
    at = ramp(vwc=45.5, vwc_settled=45.5, p1_settled_before_shot=45.4, p1_reached=True, p1_extra_shots=1)
    phase, _thr, _fire, _size, reason = decide(at, params())
    assert phase == "P2" and "P1 full" in reason


def test_the_rewater_point_stays_under_what_the_zone_reached_and_the_set_one():
    assert p1_stall_rewater(25.2, 38.0, 1.5) == 23.7
    assert p1_stall_rewater(45.0, 38.0, 1.5) == 38.0  # never over the set point
    # under a rescue level the zone stalled below: a point it cannot reach would top it up every pass
    assert p1_stall_rewater(21.0, 38.0, 1.5) == 19.5
    assert p1_stall_rewater(25.2, 38.0, None) == 23.7  # no band: the default


def test_a_zone_that_stalls_under_its_rescue_level_is_not_topped_up_at_once():
    phase, thr, fire, _size, _reason = decide(ramp(), params(p3_emergency_floor=30))
    assert phase == "P2" and thr == pytest.approx(23.7) and not fire


def test_validate_clamps_it():
    p, warns = validate_params(params(p1_stall_shots=50))
    assert p.p1_stall_shots == 10 and isinstance(p.p1_stall_shots, int) and warns
