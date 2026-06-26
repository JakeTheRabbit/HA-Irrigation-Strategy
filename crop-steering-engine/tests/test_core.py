"""Offline unit tests for the pure crop-steering core. No HA, no I/O."""
from crop_steering_engine import (
    decide, ZoneParams, ZoneSnapshot, ec_adjust, ec_pid, pick_sibling, feed_grace_ok,
    cross_zone_outliers, validate_params, zone_safety_status, system_safety_status, zone_status_label,
)


def P(**kw):
    d = dict(p1_target=60, p2_threshold=45, p2_shot_size=5, p1_initial=2, p1_incr=0.5,
             p1_max_shots=12, p1_time_between_min=15, dryback_target=20, p0_max_wait_min=45,
             ec_target_p0=4, ec_target_p1=5, ec_target_p2=6, p3_emergency_floor=40,
             p3_emergency_shot=2, max_daily_volume=300, field_capacity=70, max_ec=9, stacking_on=False)
    d.update(kw); return ZoneParams(**d)


def S(**kw):
    d = dict(vwc=50, ec=6, phase="P2", peak_vwc=60, dryback_pct=0, dryback_rate=2, shot_count=0,
             phase_minutes=5, minutes_since_shot=99, daily_vol=0, ec_smooth=6, lights_on=True,
             lights_just_on=False, hours_to_lights_on=8, hours_to_lights_off=8, uptime_min=60)
    d.update(kw); return ZoneSnapshot(**d)


def ph(s, p): return decide(s, p)[0]
def fire(s, p): return decide(s, p)[2]


def test_phase_transitions():
    assert ph(S(lights_on=False, phase="P2"), P()) == "P3"
    assert ph(S(phase="P3", lights_just_on=True, vwc=42), P()) == "P0"
    assert ph(S(phase="P0", vwc=55, peak_vwc=70, dryback_pct=21), P()) == "P1"
    assert ph(S(phase="P0", vwc=44, peak_vwc=70, dryback_pct=5), P()) == "P1"   # already-dry bypass
    assert ph(S(phase="P1", vwc=61, ec=5, ec_smooth=5), P()) == "P2"
    assert ph(S(phase="P1", vwc=50, shot_count=12), P()) == "P2"                # max-shots escape


def test_irrigation():
    assert fire(S(phase="P1", vwc=50, minutes_since_shot=20), P()) is True
    assert fire(S(phase="P1", vwc=50, minutes_since_shot=5), P()) is False      # cooldown
    assert fire(S(phase="P2", vwc=40, ec=6, ec_smooth=6), P()) is True          # top-up
    assert fire(S(phase="P2", vwc=55, ec=6, ec_smooth=6), P()) is False         # in band -> hold
    assert fire(S(phase="P3", vwc=35), P()) is True                            # emergency floor


def test_anti_lockout_flush():
    _, _, f, _, r = decide(S(phase="P2", vwc=55, ec=10, feed_ec=3), P())        # dilutive feed + room
    assert f is True and "FLUSH" in r
    _, _, f2, _, r2 = decide(S(phase="P2", vwc=55, ec=10, feed_ec=11), P())     # non-dilutive
    assert f2 is False and "BLOCK" in r2


def test_watchdog_and_cap():
    assert fire(S(phase="P2", vwc=40, minutes_since_shot=300, ec=6, ec_smooth=6), P(watchdog_hours=3)) is True
    assert fire(S(phase="P2", vwc=40, daily_vol=400, ec=6, ec_smooth=6), P(max_daily_volume=300)) is False
    # emergency flush exempt from the cap
    assert fire(S(phase="P2", vwc=55, ec=10, feed_ec=3, daily_vol=400), P(max_daily_volume=300)) is True


def test_helpers():
    assert ec_adjust(5, 12, 6) == 10.0           # ratio 2.0 -> 2x
    assert ec_adjust(5, 3, 6) == 3.5             # ratio 0.5 -> 0.7x band
    assert ec_adjust(5, 2, 6) == 2.5             # ratio 0.33 -> 0.5x
    assert pick_sibling(60, [(1, 55), (2, 62), (3, 75)]) == 2
    assert pick_sibling(60, [(3, 65), (1, 55), (2, 80)]) == 1   # tie -> lowest zone
    assert pick_sibling(60, []) is None
    assert feed_grace_ok(1000.0, 940.0, 30) is True
    assert feed_grace_ok(1000.0, None, 30) is False
    out = cross_zone_outliers({1: S(daily_vol=50), 2: S(daily_vol=48), 3: S(daily_vol=8)})
    assert any(z == 3 for z, _ in out)


def test_validate_clamps():
    p, w = validate_params(P(field_capacity=120, max_ec=20))
    assert p.field_capacity == 90.0 and p.max_ec == 15.0
    assert any("field_capacity" in x for x in w)


def test_p2_anti_short_cycle():
    p = P()
    HOT = dict(phase="P2", vwc=55, ec=7.5, ec_smooth=7.5, feed_ec=3, peak_vwc=60)   # EC over 1.2x target, feed dilutive
    assert fire(S(**HOT, minutes_since_shot=30), p) is True               # enough gap -> dilute fires
    _, _, f, _, r = decide(S(**HOT, minutes_since_shot=3), p)
    assert f is False and "dilute" not in r.lower()                       # too soon -> no machine-gun (the live bug)
    # the anti-lockout flush (EC >= max_ec) also waits between flushes, holding (not blocking) meanwhile
    too_soon = decide(S(phase="P2", vwc=55, ec=10, feed_ec=3, minutes_since_shot=2), p)
    assert too_soon[2] is False and "HOLD" in too_soon[4]
    assert decide(S(phase="P2", vwc=55, ec=10, feed_ec=3, minutes_since_shot=30), p)[2] is True   # gap ok -> flush
    # a genuinely DRY zone still tops up even when it's too soon to EC-correct (VWC top-ups stay ungated)
    assert fire(S(phase="P2", vwc=40, ec=7.5, ec_smooth=7.5, feed_ec=3, minutes_since_shot=3), p) is True


def test_ec_pid():
    base = 45.0
    # EC above target -> positive offset (threshold up -> water sooner -> dilute)
    off, integ, err = ec_pid(6.0, 5.0, base, 0.0, 0.0, (0.5, 0.1, 0.0))
    assert off > 0 and err == 1.0 and integ == 1.0
    # EC below target -> negative offset (deeper dryback -> stack)
    off2, _, err2 = ec_pid(4.0, 5.0, base, 0.0, 0.0, (0.5, 0.1, 0.0))
    assert off2 < 0 and err2 == -1.0
    # anti-windup clamp: a huge error + wound-up integral can't exceed +/-20% of base (9.0)
    off3, integ3, _ = ec_pid(20.0, 5.0, base, 100.0, 0.0, (5.0, 1.0, 0.0))
    assert abs(off3) <= 0.20 * base + 1e-6 and abs(integ3) <= 9.0 + 1e-6
    # at target with no I -> zero
    assert ec_pid(5.0, 5.0, base, 0.0, 0.0, (0.5, 0.0, 0.0))[0] == 0.0


def test_status_helpers():
    assert zone_safety_status(72, 3, 70, 9) == "over_saturated"
    assert zone_safety_status(50, 9.5, 70, 9) == "ec_limit_exceeded"
    assert zone_safety_status(50, 3, 70, 9) == "safe"
    assert system_safety_status(["safe", "safe", "safe"]) == ("safe", 0, 0, 3)
    assert system_safety_status(["ec_limit_exceeded", "approaching_saturation", "safe"]) == ("unsafe", 1, 1, 1)
    assert zone_status_label("P2", False, None, False, "P2 hold") == "Optimal"
    assert zone_status_label("P2", False, None, True, "") == "Probe dead — copying"
