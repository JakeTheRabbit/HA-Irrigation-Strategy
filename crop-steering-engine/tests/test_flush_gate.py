"""The EC flush gate: a table that drains, not a moisture reading under the field capacity setpoint.

5 Oct 2026, F2 zone 2: pore EC 7.1 against a P2 target of 4.5, feed 3.05, plants yellowing. Its probe reads 15 to
20 points high since the 29 Sep sump flood (70.7 % against a field capacity of 54), and every flush needed the
reading under field capacity - 2, so the zone got no flush at all that day: two P1 shots, then only the daily
minimum. The capped corrections now need dilutive feed and a table that drains; the cap-exempt flushes keep the
field capacity test, so a probe reading high cannot run them outside the daily budget.
"""
from crop_steering_engine.core import CAP_EXEMPT, ZoneParams, ZoneSnapshot, decide


def Z2(**kw):
    """F2 zone 2's settings on 5 Oct 2026 (Vegetative, so the veg EC targets)."""
    d = dict(p1_target=52, p2_threshold=27.5, p2_shot_size=6.0, p1_initial=3.0, p1_incr=0.4, p1_max_shots=6,
             p1_time_between_min=20, dryback_target=15, p0_max_wait_min=60, ec_target_p0=3.0, ec_target_p1=4.5,
             ec_target_p2=4.5, p3_emergency_floor=20, p3_emergency_shot=3.0, max_daily_volume=150,
             field_capacity=54, max_ec=8.5, stacking_on=False, p1_min_shots=2, min_daily_volume=84.0)
    d.update(kw)
    return ZoneParams(**d)


def snap(**kw):
    """18:33 that evening: P2, 70.7 %, pore EC 7.1 settled, 99 L in, 50 minutes since the last shot."""
    d = dict(vwc=70.7, ec=7.1, phase="P2", peak_vwc=71.7, dryback_pct=1.4, dryback_rate=1.5, shot_count=5,
             phase_minutes=300, minutes_since_shot=50, daily_vol=99.3, ec_smooth=7.0, lights_on=True,
             lights_just_on=False, hours_to_lights_on=15.5, hours_to_lights_off=3.5, uptime_min=600, feed_ec=3.05,
             ec_settled=7.1, hours_since_lights_on=8.5)
    d.update(kw)
    return ZoneSnapshot(**d)


def test_zone_2_reading_above_field_capacity_is_diluted():
    phase, _, fire, size, reason = decide(snap(), Z2())
    assert phase == "P2" and fire is True
    assert reason.kind == "p2_dilute" and reason.cap_exempt is False
    assert size == 9.0  # 1.5 x the P2 shot


def test_a_table_that_is_not_draining_gets_no_flush():
    _, _, fire, _, reason = decide(snap(backed_up=True), Z2())
    assert not (fire and reason.kind in ("p2_dilute", "p2_rescue", "flush_high_ec"))


def test_the_rescue_keeps_its_field_capacity_test_and_the_dilute_takes_over():
    # 7.6 is within 1 of max_ec 8.5: the cap-exempt rescue would fire if the reading were under 52
    _, _, fire, _, reason = decide(snap(ec=7.6, ec_settled=7.6), Z2())
    assert fire is True and reason.kind == "p2_dilute" and reason.cap_exempt is False
    _, _, fire, _, reason = decide(snap(ec=7.6, ec_settled=7.6, vwc=50.0), Z2())
    assert fire is True and reason.kind == "p2_rescue"


def test_at_max_ec_a_full_reading_gets_the_capped_dilute_not_the_exempt_flush():
    _, _, fire, _, reason = decide(snap(ec=8.9, ec_settled=8.9), Z2())
    assert fire is True and reason.kind == "p2_dilute" and not CAP_EXEMPT[reason.kind]
    # and the daily budget stops it: a probe reading high cannot flush for ever
    _, _, fire, _, reason = decide(snap(ec=8.9, ec_settled=8.9, daily_vol=150.0), Z2())
    assert fire is False and reason.kind == "block_daily_cap"
    # a reading under field capacity - 2 still gets the anti-lockout flush, exempt as before
    _, _, fire, _, reason = decide(snap(ec=8.9, ec_settled=8.9, vwc=50.0, daily_vol=150.0), Z2())
    assert fire is True and reason.kind == "flush_high_ec" and reason.cap_exempt is True


def test_at_max_ec_a_table_that_is_not_draining_is_blocked_with_its_reason():
    _, _, fire, _, reason = decide(snap(ec=8.9, ec_settled=8.9, vwc=50.0, backed_up=True), Z2())
    assert fire is False and reason.kind == "block_high_ec" and "table not draining" in reason


def test_p1_at_its_ceiling_with_high_pore_ec_gets_its_extra_shot_and_p2_dilutes():
    # P1 no longer flushes on pore EC: at its ceiling the zone gets its one extra shot (scaled up by the EC, as
    # every P1 shot is), and once that shot no longer raises the peak, P2's dilute is what corrects the EC.
    p1 = dict(phase="P1", vwc=68.0, shot_count=2, phase_minutes=70, minutes_since_shot=50, daily_vol=40.0,
              hours_since_lights_on=2.0, hours_to_lights_off=10.0)
    phase, _, fire, size, reason = decide(snap(**p1), Z2())
    assert phase == "P1" and fire is True and reason.kind == "p1_extra" and "flush" not in reason
    assert size == 7.6  # 2x the 3.8 ramp shot: pore EC 7.1 against a P1 target of 4.5
    phase, _, fire, _, reason = decide(snap(**p1, p1_extra_shots=1, p1_peak_before_shot=71.7), Z2())
    assert phase == "P2" and fire is True and reason.kind == "p2_dilute"


def test_settled_ec_still_paces_the_dilute():
    _, _, fire, _, reason = decide(snap(minutes_since_shot=30), Z2())  # a settled reading waits 45 minutes
    assert not (fire and reason.kind == "p2_dilute")


def test_feed_saltier_than_the_slab_never_flushes():
    _, _, fire, _, reason = decide(snap(feed_ec=7.5), Z2())
    assert not (fire and reason.kind in ("p2_dilute", "p2_rescue", "flush_high_ec"))
