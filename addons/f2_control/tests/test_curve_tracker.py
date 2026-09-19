"""Day planner + reference curve.

Model numbers are the F2 Zone 1 fit from 9 days of history (2026-09-19): knee 36, 0.6 pts per 1% shot,
0.72 pts/h lights-on, 0.37 pts/h lights-off. Recipe numbers follow Athena's Precision Irrigation Strategy.
"""
import curve_tracker as ct

Z1 = ct.ZoneModel(knee=36.0, gain=0.6, day_rate=0.72, night_rate=0.37)
GEN = ct.Recipe(peak_offset=0.0, dryback_pct=12.0, p1_delay_min=60, p1_shot_pct=3.0,
                p1_gap_min=20, p2_shot_pct=2.0)


def _plan(**kw):
    args = dict(model=Z1, recipe=GEN, lights_on_h=10, lights_off_h=22, start_vwc=31.5)
    args.update(kw)
    return ct.plan_day(**args)


def test_p1_waits_for_transpiration_then_ramps_to_the_peak_in_whole_shots():
    p = _plan()
    assert p.p1_start_h == 11.0  # 60 min after lights-on: transpiration before irrigation
    assert p.peak == 36.0  # generative: at field capacity, not above it
    assert p.p1_shots == 4  # 30.78 at 11:00; each 3% shot nets 1.8 minus 0.24 lost in the gap
    assert p.p1_end_h == 11.0 + 3 * 20 / 60


def test_p2_cadence_comes_from_gain_and_dryback_rate_not_a_guess():
    p = _plan()
    assert round(p.p2_lift, 2) == 1.2  # 2% x 0.6
    assert round(p.p2_interval_min) == 100  # 1.2 pts / 0.72 pts per hour
    assert p.band == (36.0 - 1.2, 36.0)


def test_p2_stops_early_enough_to_land_the_dryback_target_at_lights_on():
    p = _plan()
    assert p.p2_stop_h == 22.0 and p.achievable_dryback_pct >= 12.0  # the 12 h night alone gives 4.44 pts
    deep = _plan(recipe=ct.Recipe(**{**GEN.__dict__, "dryback_pct": 20.0}))
    assert round(deep.p2_stop_h, 2) == round(22.0 - 2.76 / 0.72, 2)  # 7.2 needed - 4.44 overnight, at 0.72/h


def test_an_unreachable_dryback_is_capped_and_reported_not_silently_chased():
    p = _plan(recipe=ct.Recipe(**{**GEN.__dict__, "dryback_pct": 45.0}))  # Athena generative
    assert p.p2_stop_h == p.p1_end_h  # never eats into the P1 ramp
    assert p.achievable_dryback_pct < 45.0 and "unreachable" in p.note
    assert round(p.floor, 1) == round(36.0 * (1 - p.achievable_dryback_pct / 100), 1)  # floor follows what is possible


def test_a_faster_drinking_day_makes_a_deeper_dryback_attainable():
    # uptake is not a constant: measure the day's rate and the attainable target moves with it
    slow = ct.plan_day(ct.ZoneModel(36.0, 0.6, 0.50, 0.30), ct.ATHENA["bulk"], 10, 22, 31.5)
    fast = ct.plan_day(ct.ZoneModel(36.0, 0.6, 1.40, 0.60), ct.ATHENA["bulk"], 10, 22, 31.5)
    assert slow.achievable_dryback_pct < 35.0 <= fast.achievable_dryback_pct
    assert fast.note == "" and "unreachable" in slow.note


def test_reference_follows_the_chart_shape_through_the_day():
    p = _plan()
    assert ct.reference(p, 10.5)[0] == "P0"
    ph, lo, hi = ct.reference(p, 11.5)
    assert ph == "P1" and 30.0 < lo < hi <= 36.0
    assert ct.reference(p, 15.0) == ("P2", 34.8, 36.0)
    ph, lo, hi = ct.reference(p, 3.0)  # overnight
    assert ph == "P3" and hi < 36.0


def test_every_athena_stage_carries_its_pore_ec_range():
    assert ct.ATHENA["stretch"].ec_range == (4.0, 10.0) and ct.ATHENA["finish"].ec_range == (3.0, 4.0)
