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


# ------------------------------------------------------------------ the behaviour Ben asked for
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


# ------------------------------------------------------------------ the engine's P1 EC gate
def test_a_p1_ec_target_stricter_than_the_p2_target_must_not_hold_a_plateaued_ramp_in_flush():
    # live F2 Zone 1 on 2026-09-19: pore EC 5.2, P1 EC target 4.5 (gate 5.18), P2 EC target 6.0
    assert au.p1_ec_gate(5.2, 4.5, 6.0) == 4.6  # just enough: 4.6 x 1.15 = 5.29
    assert au.p1_ec_gate(5.0, 4.5, 6.0) is None  # already passes
    assert au.p1_ec_gate(7.5, 4.5, 6.0) is None  # genuinely high EC: the engine's flush is what we want
    assert au.p1_ec_gate(None, 4.5, 6.0) is None


# ------------------------------------------------------------------ end to end against the REAL engine
import math  # noqa: E402

import engine_twin as et  # noqa: E402
import setpoint_supervisor as ss  # noqa: E402

LIVE_Z1 = dict(p1_target_vwc=40.0, p2_vwc_threshold=34.0, p2_shot_size=3.0, p1_initial_shot_size=2.0,
               p1_shot_size_increment=0.5, p1_maximum_shots=10, p1_minimum_shots=2, p1_time_between_shots=20,
               dryback_target=10.0, p0_maximum_wait_time=60, ec_target_p0=3.0, ec_target_p1=4.5, ec_target_p2=6.0,
               p3_emergency_vwc_threshold=22.0, p3_emergency_shot_size=2.0, max_daily_volume=200.0,
               field_capacity=55.0, maximum_ec=8.5, watchdog_hours=3.0)


def _auto(learn):
    """The controller's _auto_tick, against the twin: learn every minute, write what is wanted."""
    def hook(ctx):
        ts = ctx["minute"] * 60.0
        au.new_day(learn, f"day{ctx['minute'] // 1440}", ctx["vwc"])
        if ctx["shot"]:
            au.shot(learn, ctx["phase"], ctx["shot"], ctx["vwc"], ts)
        au.tick(learn, ctx["vwc"], ctx["phase"], ts, ctx["lights_on"], ctx["dryback_rate"], ctx["minutes_since_shot"])
        au.ramp_outcome(learn, ctx["phase"])
        sp = ctx["setpoints"]
        current = {k: sp[k] for k in ("p1_target_vwc", "field_capacity", "p2_vwc_threshold",
                                      "p3_emergency_vwc_threshold", "p2_shot_size")}
        out = ss.writes(current, au.wanted(learn, current, ctx["vwc"], ctx["phase"], None))
        if ctx["phase"] == "P1" and learn["outcome"] == "plateau":
            gate = au.p1_ec_gate(ctx["ec"], sp["ec_target_p1"], sp["ec_target_p2"])
            if gate is not None:
                out.append(("ec_target_p1", gate, "p1 ec gate"))
        return out
    return hook


def _days(trace):
    return [trace[d * 1440:(d + 1) * 1440] for d in range(len(trace) // 1440)]


def test_against_the_real_engine_a_plateau_hands_p1_over_to_p2_and_the_peak_carries_forward():
    import curve_tracker as ct
    zone = ct.ZoneModel(knee=36.0, gain=0.6, day_rate=0.72, night_rate=0.37)
    demand = lambda m, day: 0.6 + 0.63 * math.sin(math.pi * m / day)  # noqa: E731
    base, _ = et.run(zone, LIVE_Z1, 31.5, 5.2, 3.0, days=2, demand=demand)
    learn = au.fresh()
    auto, changes = et.run(zone, LIVE_Z1, 31.5, 5.2, 3.0, days=2, supervisor=_auto(learn), every_min=1, demand=demand)

    def ramp(rows):
        return [r["shot"] for r in rows if r["shot"] and r["phase"] in ("P0", "P1")]

    def p2_start(rows):
        return next(r["h"] % 24 for r in rows if r["phase"] == "P2")

    b1, a1, a2 = _days(base)[0], _days(auto)[0], _days(auto)[1]
    assert len(ramp(b1)) >= 7  # today: the engine chases a 40% target this probe cannot read, to max shots
    # handed over when it stopped rising, at least one 20-minute ramp interval sooner (the margin was 0.5 h
    # while the engine also fired a WATCHDOG shot in P0 at lights-on, which delayed the base run's ramp)
    assert len(ramp(a1)) < len(ramp(b1)) and p2_start(a1) <= p2_start(b1) - 20 / 60
    assert 35.0 <= learn["peak"] <= 37.5  # it found the real ceiling by itself
    assert any(s == "p1_target_vwc" and new < 38.0 for _h, s, _old, new, _w in changes)
    assert abs(a2[300]["p1_target"] - learn["peak"]) < 0.06  # and that peak IS the P1 target the next day
    b2 = _days(base)[1]
    assert sum(ramp(a2)) < sum(ramp(b2)) * 0.5  # the ramp stops where the substrate does: half the ramp water
    assert sum(r["shot"] for r in a2) < sum(r["shot"] for r in b2)  # and the day as a whole uses less
    thresholds = {new for _h, s, _old, new, _w in changes if s == "p2_vwc_threshold"}
    assert len(thresholds) <= 3  # the band is set from a stable gain: no hourly creep
