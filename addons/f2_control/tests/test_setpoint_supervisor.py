"""Setpoint supervisor: attainable targets, scheduled through the day, nudged by judgement. It never fires a shot.

LIVE_Z1 is Zone 1's real setpoint set as read from Work HA on 2026-09-19.
"""
import math

import curve_tracker as ct
import engine_twin as et
import setpoint_supervisor as ss

Z1 = ct.ZoneModel(knee=36.0, gain=0.6, day_rate=0.72, night_rate=0.37)
GEN = ct.Recipe(peak_offset=0.0, dryback_pct=15.0, p1_delay_min=75, p1_shot_pct=3.0, p1_gap_min=20,
                p2_shot_pct=2.0, ec_range=(4.0, 7.0))
LIVE_Z1 = dict(p1_target_vwc=40.0, p2_vwc_threshold=34.0, p2_shot_size=3.0, p1_initial_shot_size=2.0,
               p1_shot_size_increment=0.5, p1_maximum_shots=10, p1_minimum_shots=2, p1_time_between_shots=20,
               dryback_target=10.0, p0_maximum_wait_time=60, ec_target_p0=3.0, ec_target_p1=4.5, ec_target_p2=6.0,
               p3_emergency_vwc_threshold=22.0, p3_emergency_shot_size=2.0, max_daily_volume=200.0,
               field_capacity=55.0, maximum_ec=8.5, watchdog_hours=3.0)
PLAN = ct.plan_day(Z1, GEN, 10, 22, 31.5)  # peak 36, floor 30.6, P2 stops 20.67


def _ctx(**kw):
    c = dict(clock_h=14.0, minutes_since_lights_on=240, lights_on=True, phase="P2", vwc=35.0, ec=5.2, feed_ec=3.0,
             peak_today=36.1, shots_today=6, responses=[1.7, 1.8, 1.1], runoff_today=0.4, setpoints=dict(LIVE_Z1), reason="")
    c.update(kw)
    return c


def _want(**kw):
    return ss.desired(Z1, GEN, PLAN, ss.Steer(p2_shot=2.0), _ctx(**kw), ec_seen_max=5.6)


# ------------------------------------------------------------------ attainable
def test_targets_follow_the_zones_own_knee_not_a_textbook_number():
    w = _want()
    assert w["p1_target_vwc"] == 36.0  # live value is 40: above anything this probe has read
    assert w["field_capacity"] == 40.0  # knee + 2, held at the engine's lower bound
    assert w["p2_vwc_threshold"] == 34.8  # one maintenance shot (2% x 0.6) under the peak
    probe2 = ct.ZoneModel(knee=27.0, gain=0.25, day_rate=0.30, night_rate=0.15)  # reads low, steered the same way
    w2 = ss.desired(probe2, GEN, ct.plan_day(probe2, GEN, 10, 22, 23.0), ss.Steer(2.0), _ctx(vwc=26.0), 3.9)
    assert w2["p1_target_vwc"] == 27.0 and w2["p2_vwc_threshold"] == 26.5


def test_ec_target_is_pulled_to_what_the_feed_and_the_zone_can_actually_reach():
    assert ss.attainable_ec_target((4.0, 10.0), feed_ec=3.0, ec_seen_max=5.6) == 6.1  # not the 7.0 midpoint
    assert ss.attainable_ec_target((4.0, 10.0), feed_ec=3.0, ec_seen_max=3.9) == 4.4  # zone 2/3 today
    assert ss.attainable_ec_target((3.0, 4.0), feed_ec=3.0, ec_seen_max=5.6) == 3.5
    w = _want()
    assert w["ec_target_p1"] == w["ec_target_p2"] == 5.5  # P1 can only graduate near this, so it must be reachable


def test_an_unreachable_dryback_is_replaced_by_the_deepest_one_possible():
    stretch = ct.ATHENA["stretch"]  # asks for 45%
    plan = ct.plan_day(Z1, stretch, 10, 22, 31.5)
    w = ss.desired(Z1, stretch, plan, ss.Steer(1.5), _ctx(), ec_seen_max=5.6)
    assert w["dryback_target"] == round(plan.achievable_dryback_pct, 1) < 45.0


# ------------------------------------------------------------------ scheduled through the day
def test_threshold_is_held_under_the_zone_overnight_and_through_p0_so_p0_really_happens():
    night = _want(minutes_since_lights_on=None, lights_on=False, phase="P3")
    p0 = _want(minutes_since_lights_on=20, phase="P0", shots_today=0)
    assert night["p2_vwc_threshold"] == p0["p2_vwc_threshold"] == round(PLAN.floor - 2.0, 1)
    assert p0["dryback_target"] == ss.ADDITIONAL_DRYBACK_PCT  # Athena's 1-5% after lights-on ends P0
    assert p0["p0_maximum_wait_time"] == 75.0  # ...or the planned delay does
    assert night["dryback_target"] == 15.0


def test_threshold_rises_to_the_band_for_the_watering_day_then_drops_to_start_the_dryback():
    assert _want(minutes_since_lights_on=90, phase="P1", shots_today=2)["p2_vwc_threshold"] == 34.8
    assert _want(minutes_since_lights_on=400, phase="P2")["p2_vwc_threshold"] == 34.8
    after_stop = _want(minutes_since_lights_on=(PLAN.p2_stop_h - 10) * 60 + 5, phase="P2")
    assert after_stop["p2_vwc_threshold"] == round(PLAN.floor - 2.0, 1)  # no more top-ups: the dryback has begun


def test_the_ramp_is_even_shots_with_room_to_finish():
    w = _want()
    assert (w["p1_initial_shot_size"], w["p1_shot_size_increment"]) == (3.0, 0.0)
    assert w["p1_maximum_shots"] == PLAN.p1_shots + 3 and w["p1_time_between_shots"] == 20.0


# ------------------------------------------------------------------ writes
def test_writes_are_clamped_stepped_and_never_invert_the_vwc_ladder():
    moves = dict((s, v) for s, v, _w in ss.writes(LIVE_Z1, _want()))
    assert moves["p1_target_vwc"] == 36.0 and moves["field_capacity"] == 40.0
    far = dict(LIVE_Z1, p1_target_vwc=50.0)
    stepped = dict((s, v) for s, v, _w in ss.writes(far, _want()))
    assert stepped["p1_target_vwc"] == 44.0  # 6 points per pass
    assert stepped["field_capacity"] == 44.0  # and field capacity waits above it rather than inverting the ladder
    assert "p3_emergency_shot_size" not in moves and "maximum_ec" not in moves  # safety setpoints are not touched
    upside_down = dict(_want(), p2_vwc_threshold=37.0)
    assert ss.writes(LIVE_Z1, upside_down) == []
    assert ss.writes(dict(LIVE_Z1, **moves), _want()) == []  # already there: nothing to write


# ------------------------------------------------------------------ judgement
def test_evidence_arrives_already_compared_and_in_words():
    e = ss.evidence(Z1, GEN, PLAN, ss.Steer(2.0), _ctx(ec=7.6), ec_trend_24h=0.4, light_note="PPFD 787, 13% below the 7-day norm")
    assert "ABOVE the stage range 4.0 to 7.0" in e["pore_ec"] and "runoff lowers pore EC" in e["feed_ec"]
    assert "rising" in e["pore_ec_trend_24h"] and "reached the peak target" in e["highest_vwc_today"]
    assert e["last_shot_responses"] == ["+1.7 normal", "+1.8 normal", "+1.1 normal"] and "787" in e["light_today"]
    short = ss.evidence(Z1, GEN, PLAN, ss.Steer(2.0), _ctx(peak_today=33.0, responses=[0.2, 0.1]))
    assert "3.0 points short" in short["highest_vwc_today"] and short["last_shot_responses"] == ["+0.2 weak", "+0.1 weak"]


def test_a_flush_verdict_grows_the_p2_shot_and_the_band_with_it_once_a_day_inside_limits():
    sup = ss.Supervisor(Z1, GEN, 10, 22, ec_seen_max=5.6, judge=lambda ev: {"freeze": None, "p2_shot_delta": 0.5, "peak_delta": 0.0})
    moves = dict((s, v) for s, v, _w in sup(_ctx(minutes_since_lights_on=240)))
    assert moves["p2_shot_size"] == 2.5 and moves["p2_vwc_threshold"] == 34.5  # 36 - 0.6 x 2.5
    for _ in range(10):  # the same verdict all afternoon: pore EC answers over a day, so no further nudge today
        sup(_ctx(minutes_since_lights_on=240))
    assert sup.steer.p2_shot == 2.5
    for day in range(10):  # day after day it keeps walking, but never past the allowed range
        sup(_ctx(minutes_since_lights_on=0, shots_today=0))
        sup(_ctx(minutes_since_lights_on=240))
    assert sup.steer.p2_shot == ss.P2_SHOT_RANGE[1]


def test_a_guard_freezes_every_setpoint_and_a_dead_judge_changes_nothing():
    frozen = ss.Supervisor(Z1, GEN, 10, 22, 5.6, judge=lambda ev: {"freeze": "delivery failure 0.91"})
    assert frozen(_ctx(minutes_since_lights_on=240)) == []
    dead = ss.Supervisor(Z1, GEN, 10, 22, 5.6, judge=lambda ev: None)
    alone = ss.Supervisor(Z1, GEN, 10, 22, 5.6)
    assert dead(_ctx(minutes_since_lights_on=240)) == alone(_ctx(minutes_since_lights_on=240))


# ------------------------------------------------------------------ does the ENGINE then follow the curve?
DEMAND = lambda m, day: 0.6 + 0.63 * math.sin(math.pi * m / day)  # noqa: E731  midday transpiration peak


def _day(trace, d=0):
    rows = trace[d * 1440:(d + 1) * 1440]
    shots = [(r["h"] % 24, r["shot"], r["phase"]) for r in rows if r["shot"]]
    return rows, shots


def test_with_todays_live_setpoints_the_real_engine_skips_p0_and_burns_the_ramp_into_runoff():
    rows, shots = _day(et.run(Z1, LIVE_Z1, 31.5, 5.2, 3.0, demand=DEMAND)[0])
    ramp = [s for _h, s, ph in shots if ph in ("P0", "P1")]
    assert shots[0][0] < 10.1  # first shot the minute the lights come on
    assert len(ramp) >= 7 and max(ramp) >= 5.0  # escalating shots chasing a 40% target the probe cannot read
    assert sum(s for _h, s, _p in shots) > 35.0  # % of substrate volume in a day


def test_with_the_supervisor_the_same_engine_traces_the_chart():
    sup = ss.Supervisor(Z1, GEN, 10, 22, ec_seen_max=5.6)
    trace, changes = et.run(Z1, LIVE_Z1, 31.5, 5.2, 3.0, days=2, supervisor=sup, demand=DEMAND)
    rows, shots = _day(trace, d=1)  # day 2: setpoints have settled
    ramp = [s for _h, s, ph in shots if ph in ("P0", "P1")]
    assert shots[0][0] >= 10.5  # a real P0: transpiration before irrigation
    assert 3 <= len(ramp) <= 7 and max(ramp) <= 3.6  # an even ramp, no escalation
    assert max(r["vwc"] for r in rows) <= Z1.knee + 2.0  # a little P1 runoff, as Athena intends, not a 40% chase
    stop = sup.plan.p2_stop_h
    p2 = [r["vwc"] for r in rows if sup.plan.p1_end_h + 1.0 <= r["h"] % 24 <= stop and r["h"] % 24 > 10]
    assert min(p2) >= sup.plan.band[0] - 0.8  # the engine's own top-ups hold the band
    assert shots[-1][0] <= stop + 0.3  # and stop on time, so the dryback starts when planned
    peak, end = max(r["vwc"] for r in rows), rows[-1]["vwc"]
    assert abs((peak - end) / peak * 100 - 15.0) < 3.5
    base = sum(s for _h, s, _p in _day(et.run(Z1, LIVE_Z1, 31.5, 5.2, 3.0, days=2, demand=DEMAND)[0], 1)[1])
    assert sum(s for _h, s, _p in shots) < base * 0.75  # and far less water goes to runoff
    assert any(s == "p1_target_vwc" and old == 40.0 and new == 36.0 for _h, s, old, new, _w in changes)


def test_the_judge_is_told_the_24h_ec_trend_and_todays_light():
    seen = []
    sup = ss.Supervisor(Z1, GEN, 10, 22, 5.6, judge=lambda ev: seen.append(ev))
    sup(_ctx(minutes_since_lights_on=240, ec=5.2))
    sup(_ctx(minutes_since_lights_on=240, ec=5.9, light_note="PPFD 787, 13% below the 7-day norm"))
    assert "pore_ec_trend_24h" not in seen[0]
    assert "+0.7" in seen[1]["pore_ec_trend_24h"] and "rising" in seen[1]["pore_ec_trend_24h"]
    assert "787" in seen[1]["light_today"]
