"""Auto setpoints: learn a zone from its own shots, fail P1 over to P2 when the substrate stops taking
water, carry the achieved peak forward as the P1 target, and keep probing upward for a higher one.

Numbers mirror F2 Zone 1 as measured 2026-09-19: the probe saturates near 36 %, a 3 % shot lifts about
1.8 points, and the live P1 target of 40 % is something that probe has never read.
"""
import json

import auto_setpoints as au

T0 = 1_800_000_000.0
MIN = 60.0


def _quiet_days(learn, day_rate=0.72, night_rate=0.37, days=au.MIN_RATE_DAYS):
    """Whole photoperiods and nights of quiet dryback readings; a day's MEAN is folded in at the next lights-on."""
    for d in range(days):
        for k in range(au.MIN_RATE_SAMPLES):
            au.tick(learn, 35.0, "P2", T0 + (d + 1) * 86400 + k * MIN, True, day_rate, 45)
            au.tick(learn, 33.0, "P3", T0 + (d + 1) * 86400 + 50000 + k * MIN, False, night_rate, 300)
        au.new_day(learn, f"quiet-{learn['day_n']}", 31.0)  # day_n moves on each fold, so every label is a new day


def _ramp(learn, rises, start=30.0, pct=3.0, phase="P1", t=T0, spike=0.0):
    """Fire shots and let each settle. `rises` are the SETTLED gains; `spike` is a transient on top."""
    vwc = start
    au.new_day(learn, "2026-09-20", start)
    for k, rise in enumerate(rises):
        ts = t + k * 20 * MIN
        au.shot(learn, phase if k else "P0", pct, vwc, ts)
        au.tick(learn, vwc + rise + spike, "P1", ts + 3 * MIN, True, 0.0, 3)  # the spike, before settling
        vwc += rise
        au.tick(learn, vwc, "P1", ts + au.SETTLE_MIN * MIN, True, 0.0, au.SETTLE_MIN)
    return vwc


# ------------------------------------------------------------------ the behaviour the owner asked for
def test_two_flat_shots_fail_p1_over_to_p2_and_the_peak_becomes_the_target():
    learn = au.fresh()
    _ramp(learn, [1.8, 1.8, 1.7, 0.2, 0.1])  # 30 -> 35.3, then the substrate stops taking water
    assert au.ramp_outcome(learn, "P1") == "plateau"
    assert learn["peak"] == 35.6  # the highest SETTLED reading of the ramp
    # right now: a target the zone has already met, so the engine's own rule graduates P1 -> P2
    assert au.p1_target(learn, vwc=35.5, phase="P1") == 35.4
    # and from P2 on, the achieved peak IS the P1 target going forward
    assert au.p1_target(learn, vwc=35.0, phase="P2") == 35.6


def test_a_clean_ramp_means_tomorrow_aims_higher():
    learn = au.fresh()
    _ramp(learn, [1.8, 1.8, 1.8])  # still responding normally when the target was met
    assert au.ramp_outcome(learn, "P2") == "reached"  # the engine graduated it
    assert learn["peak"] == 35.4 and learn["hold_days"] == 0
    assert au.p1_target(learn, vwc=35.0, phase="P2") == 36.4  # always try to get the max up


def test_after_a_plateau_it_holds_the_peak_for_a_few_days_then_probes_again():
    learn = au.fresh()
    _ramp(learn, [1.8, 1.8, 0.1, 0.1])
    au.ramp_outcome(learn, "P1")
    held = learn["peak"]
    for day in range(1, au.HOLD_DAYS + 1):
        assert au.p1_target(learn, vwc=30.0, phase="P0") == held  # no point burning shots into runoff daily
        au.new_day(learn, f"2026-09-{20 + day}", 30.0)
    assert au.p1_target(learn, vwc=30.0, phase="P0") == held + au.PROBE_STEP_PTS


def test_while_the_ramp_is_still_climbing_the_target_is_left_alone():
    learn = au.fresh()
    _ramp(learn, [1.8, 1.7])
    assert au.ramp_outcome(learn, "P1") == "pending"
    assert au.p1_target(learn, vwc=33.5, phase="P1") is None


# ------------------------------------------------------------------ never learn a false ceiling
def test_shots_that_never_lifted_vwc_are_a_delivery_problem_not_saturation():
    learn = au.fresh()
    _ramp(learn, [0.1, 0.0, 0.1], start=24.0)  # flat from the first shot: water is not reaching the probe
    assert au.ramp_outcome(learn, "P1") == "suspect"
    assert learn["peak"] is None and au.p1_target(learn, vwc=24.2, phase="P1") is None
    assert "not reaching" in au.frozen_reason(learn)


def test_a_plateau_far_below_the_known_peak_is_not_believed():
    learn = au.fresh()
    learn["peak"] = 36.0
    _ramp(learn, [1.8, 1.6, 0.1, 0.1], start=27.0)  # stalls at 30.6, five points under what it held last week
    assert au.ramp_outcome(learn, "P1") == "suspect"
    assert learn["peak"] == 36.0


def test_the_spike_right_after_a_shot_is_not_the_peak():
    learn = au.fresh()
    _ramp(learn, [1.8, 1.8, 0.2, 0.1], spike=2.5)  # free water reads high for minutes, then drains
    au.ramp_outcome(learn, "P1")
    assert learn["peak"] == 33.9  # settled, not 36.4


def test_a_shot_is_judged_by_what_it_retained_right_before_the_next_one():
    # Seen on the twin of F2 Zone 1: eight minutes after a big shot the probe still rides the spike and
    # reads +1.3..+1.8 even at saturation. Shot-to-shot the same ramp reads 1.6, 1.3, 1.5, then 0.5, 0.2.
    learn = au.fresh()
    au.new_day(learn, "d", 31.5)
    pre = [31.5, 33.1, 34.4, 35.9, 36.45, 36.66]  # the reading right before each shot
    for k, (vwc, pct) in enumerate(zip(pre, [3.0, 2.4, 3.0, 3.6, 4.2, 4.8])):
        au.shot(learn, "P1", pct, vwc, T0 + k * 20 * MIN)
        au.tick(learn, vwc + 1.7, "P1", T0 + k * 20 * MIN + 8 * MIN, True, 0.0, 8)  # the spike: must be ignored
    assert [r["rise"] for r in learn["ramp"]] == [1.6, 1.3, 1.5, 0.55, 0.21]
    assert [r["flat"] for r in learn["ramp"]] == [False, False, False, True, True]  # weak vs the ~0.5/% it learned
    assert au.ramp_outcome(learn, "P1") == "plateau" and learn["peak"] == 36.66


# ------------------------------------------------------------------ learning the zone's numbers
def test_gain_and_dryback_rates_are_learned_and_the_model_completes_with_enough_samples():
    learn = au.fresh()
    _ramp(learn, [1.8, 1.8, 1.8])
    assert 0.55 < learn["gain"] < 0.65  # points per 1% shot
    assert au.model(learn) is None  # rates unknown yet
    au.ramp_outcome(learn, "P2")
    _quiet_days(learn, days=1)
    assert au.model(learn) is None  # one day is not a pattern
    _quiet_days(learn, days=1)
    m = au.model(learn)
    assert m is not None and m.knee == learn["peak"]
    assert abs(m.day_rate - 0.72) < 0.05 and abs(m.night_rate - 0.37) < 0.05


def test_plateau_shots_and_fresh_shots_do_not_poison_the_rates_or_the_gain():
    learn = au.fresh()
    _ramp(learn, [1.8, 1.8, 0.1, 0.1])
    assert 0.55 < learn["gain"] < 0.65  # the two flat shots were not averaged in
    au.tick(learn, 35.0, "P2", T0 + 9000, True, 4.0, 5)  # five minutes after a shot: still draining
    assert learn["day_acc"] == [0.0, 0]


def test_p2_top_ups_near_the_ceiling_never_teach_the_gain():
    # On the twin this was a runaway: near-ceiling shots retain little, the gain halved, the P2 band shrank,
    # the threshold crept up hourly and P2 water tripled.
    learn = au.fresh()
    _ramp(learn, [1.8, 1.8, 1.8, 0.1, 0.1])
    au.ramp_outcome(learn, "P1")
    gain = learn["gain"]
    for k in range(12):
        ts = T0 + 40000 + k * 60 * MIN
        au.shot(learn, "P2", 3.0, learn["peak"] - 1.5, ts)  # a maintenance shot fired just under the peak
        au.tick(learn, learn["peak"] - 1.0, "P2", ts + au.SETTLE_MIN * MIN, True, 0.0, au.SETTLE_MIN)
    assert learn["gain"] == gain


def test_learned_state_survives_a_restart():
    learn = au.fresh()
    _ramp(learn, [1.8, 1.8, 0.1, 0.1])
    au.ramp_outcome(learn, "P1")
    assert au.restore(json.loads(json.dumps(learn))) == learn
    assert au.restore({"peak": "garbage", "ramp": 7}) == au.fresh()  # a corrupt file never crashes the engine


# ------------------------------------------------------------------ what gets written
CURRENT = dict(p1_target_vwc=40.0, field_capacity=55.0, p2_vwc_threshold=34.0, p3_emergency_vwc_threshold=22.0, p2_shot_size=3.0)


def test_wanted_keeps_the_vwc_ladder_attainable_and_in_order():
    learn = au.fresh()
    _ramp(learn, [1.8, 1.8, 0.2, 0.1])
    au.ramp_outcome(learn, "P1")
    want = au.wanted(learn, CURRENT, vwc=33.8, phase="P2", plan_ctx=None)
    assert want["p1_target_vwc"] == 33.9
    assert want["field_capacity"] == 40.0  # target + 2, held at the engine's lower bound
    assert want["p2_vwc_threshold"] == round(33.9 - learn["gain"] * 3.0, 1)  # one maintenance shot under the peak
    assert "p3_emergency_vwc_threshold" not in want  # 22 already sits 3 below the threshold: not ours to touch
    crowded = au.wanted(learn, dict(CURRENT, p3_emergency_vwc_threshold=31.5), vwc=33.8, phase="P2", plan_ctx=None)
    assert crowded["p3_emergency_vwc_threshold"] == round(crowded["p2_vwc_threshold"] - 3.0, 1)


def test_with_a_complete_model_the_p2_threshold_is_scheduled_through_the_day():
    learn = au.fresh()
    _ramp(learn, [1.8, 1.8, 1.8, 0.1, 0.1])
    au.ramp_outcome(learn, "P1")
    _quiet_days(learn)
    ctx = dict(lights_on_h=10, lights_off_h=22, shots_today=6, dryback_pct=12.0, p0_wait_min=60,
               p1_shot_pct=3.0, p1_gap_min=20, start_vwc=31.0)
    day = au.wanted(learn, CURRENT, vwc=35.0, phase="P2", plan_ctx=dict(ctx, minutes_since_lights_on=300))
    night = au.wanted(learn, CURRENT, vwc=33.0, phase="P3", plan_ctx=dict(ctx, minutes_since_lights_on=None))
    dawn = au.wanted(learn, CURRENT, vwc=31.0, phase="P0", plan_ctx=dict(ctx, minutes_since_lights_on=20, shots_today=0))
    assert day["p2_vwc_threshold"] == round(learn["peak"] - learn["gain"] * 3.0, 1)  # hold the band by day
    assert night["p2_vwc_threshold"] < 31.0 and dawn["p2_vwc_threshold"] == night["p2_vwc_threshold"]
    # held UNDER the zone overnight and through P0: no lights-on watchdog shot, a real P0, a real dryback


def test_nothing_is_wanted_until_something_has_been_learned():
    assert au.wanted(au.fresh(), CURRENT, vwc=31.0, phase="P0", plan_ctx=None) == {}


def test_status_tells_the_operator_what_it_is_doing():
    learn = au.fresh()
    assert au.status(learn, enabled=False)[0] == "off"
    assert au.status(learn, enabled=True)[0] == "learning"
    _ramp(learn, [0.1, 0.0, 0.1], start=24.0)
    au.ramp_outcome(learn, "P1")
    state, attrs = au.status(learn, enabled=True)
    assert state == "frozen" and attrs["p1_outcome"] == "suspect" and attrs["learned_peak"] is None
