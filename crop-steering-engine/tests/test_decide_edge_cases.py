"""Edge-case coverage ported from the retired lean-engine decision harness
before that engine was removed from the repo.

Only the PURE decision-logic / helper cases are kept; they import the ACTIVE engine
(`crop_steering_engine`), never the retired lean engine. The active engine is
authoritative — where a ported assertion would have asserted retired behaviour that the
active core.py no longer implements, the case is either re-expressed against the real
current behaviour or skipped with a comment naming why (shell-only logic the pure core
does not expose).

SKIPPED (shell-only, intentionally not ported here):
  * DEFECT #1/#2 multi-tick `_step_ec_offset` stepping — that staticmethod lives on the
    retired `LeanCropSteering` class, NOT in crop_steering_engine. The active engine
    replaced the stepped EC-offset with the pure `ec_pid` (covered in test_core.py and
    extended below) plus shell-owned offset accumulation in the f2-control add-on. No
    pure entry point exists to port, so those cases have no home in the engine suite.
  * The old `decide()` "EC steer: low/high EC -> threshold DOWN/UP" cases — the active
    core.py `decide()` does NOT mutate p2_threshold from ec_smooth (the EC STEERING
    block is a documented no-op; the IO shell bakes the offset into p.p2_threshold
    BEFORE calling decide()). DESIGN #1's *effect* (offset shifts the firing boundary)
    is still proved here via test_d1_effective_threshold by passing the effective
    threshold in directly.
  * LeanCropSteering state-persistence / activity-log / source-water-gate / timezone
    cases (F1 shell wiring, F3 gate, D3 shadow, STATUS publish, _read_sensor TZ) — tied
    to the retired controller shell. State persistence is already covered against the
    LIVE add-on controller by tests/test_state_migration.py, so re-porting is redundant.
"""

from crop_steering_engine import (
    decide,
    ZoneParams,
    ZoneSnapshot,
    ec_adjust,
    ec_pid,
    cross_zone_outliers,
    validate_params,
    pick_sibling,
    feed_grace_ok,
    zone_safety_status,
    system_safety_status,
    zone_status_label,
)


def P(**kw):
    d = dict(
        p1_target=60,
        p2_threshold=45,
        p2_shot_size=5,
        p1_initial=2,
        p1_incr=0.5,
        p1_max_shots=12,
        p1_time_between_min=15,
        dryback_target=20,
        p0_max_wait_min=45,
        ec_target_p0=4,
        ec_target_p1=5,
        ec_target_p2=6,
        p3_emergency_floor=40,
        p3_emergency_shot=2,
        max_daily_volume=300,
        field_capacity=70,
        max_ec=9,
        stacking_on=False,
    )
    d.update(kw)
    return ZoneParams(**d)


def S(**kw):
    d = dict(
        vwc=50,
        ec=6,
        phase="P2",
        peak_vwc=60,
        dryback_pct=0,
        dryback_rate=2,
        shot_count=0,
        phase_minutes=5,
        minutes_since_shot=99,
        daily_vol=0,
        ec_smooth=6,
        lights_on=True,
        lights_just_on=False,
        hours_to_lights_on=8,
        hours_to_lights_off=8,
        uptime_min=60,
    )
    d.update(kw)
    return ZoneSnapshot(**d)


def ph(s, p):
    return decide(s, p)[0]


def fire(s, p):
    return decide(s, p)[2]


# ---------------------------------------------------------------------------
# Phase transitions
# ---------------------------------------------------------------------------
def test_phase_transitions_extended():
    assert ph(S(lights_on=False, phase="P2"), P()) == "P3"
    assert ph(S(lights_on=False, phase="P1"), P()) == "P3"
    assert ph(S(phase="P3", lights_just_on=True, vwc=42), P()) == "P0"
    assert ph(S(phase="P0", vwc=55, peak_vwc=70, dryback_pct=21), P()) == "P1"
    assert (
        ph(S(phase="P0", vwc=44, peak_vwc=70, dryback_pct=5), P()) == "P1"
    )  # already-dry bypass
    assert (
        ph(S(phase="P0", vwc=58, dryback_pct=5, phase_minutes=50), P()) == "P1"
    )  # timeout
    assert (
        ph(S(phase="P0", vwc=58, dryback_pct=5, phase_minutes=10), P()) == "P0"
    )  # still drying
    # Design #2: P1->P2 "recovered" also requires pore EC back in band (ec <= ec_target_p1*1.15).
    assert ph(S(phase="P1", vwc=61, ec=5, ec_smooth=5), P()) == "P2"
    assert ph(S(phase="P1", vwc=50, shot_count=12), P()) == "P2"  # max-shots escape
    assert ph(S(phase="P1", vwc=50, phase_minutes=121), P()) == "P2"  # 120min ceiling


def test_p2_predictive_p3():
    assert (
        ph(
            S(
                phase="P2",
                vwc=55,
                hours_to_lights_off=2,
                hours_to_lights_on=2,
                dryback_rate=10,
            ),
            P(dryback_target=20),
        )
        == "P3"
    )
    # >3h to lights-off -> no early P3
    assert ph(S(phase="P2", vwc=55, hours_to_lights_off=6), P()) == "P2"


# ---------------------------------------------------------------------------
# Per-phase irrigation firing
# ---------------------------------------------------------------------------
def test_irrigation_per_phase():
    assert fire(S(phase="P1", vwc=50, minutes_since_shot=20), P()) is True
    assert fire(S(phase="P1", vwc=50, minutes_since_shot=5), P()) is False  # cooldown
    assert fire(S(phase="P2", vwc=40, ec=6, ec_smooth=6), P()) is True  # top-up
    assert (
        fire(S(phase="P2", vwc=55, ec=6, ec_smooth=6), P()) is False
    )  # in band -> hold
    assert (
        fire(S(phase="P2", vwc=55, ec=8), P()) is True
    )  # dilute high EC (feed dilutive by default)
    assert (
        fire(S(phase="P2", vwc=55, ec=2, ec_smooth=2), P()) is False
    )  # low EC alone -> no fire
    assert fire(S(phase="P3", vwc=38), P()) is True  # emergency floor
    assert fire(S(phase="P3", vwc=50), P()) is False  # above floor
    assert (
        fire(S(phase="P0", vwc=55, dryback_pct=5, phase_minutes=5), P()) is False
    )  # P0 no fire
    # P0 EC emergency flush (ec / ec_target_p0 > 2.5)
    assert (
        fire(
            S(phase="P0", vwc=55, ec=12, dryback_pct=5, phase_minutes=5),
            P(ec_target_p0=4),
        )
        is True
    )


# ---------------------------------------------------------------------------
# Anti-lockout high-EC flush (any phase) + dilutive-feed/slab-room gate
# ---------------------------------------------------------------------------
def test_anti_lockout_flush_any_phase():
    assert (
        fire(
            S(phase="P0", vwc=50, ec=10, feed_ec=3, dryback_pct=5, phase_minutes=5),
            P(max_ec=9, field_capacity=70),
        )
        is True
    )
    assert (
        fire(
            S(phase="P1", vwc=50, ec=10, feed_ec=3, minutes_since_shot=20),
            P(max_ec=9, field_capacity=70),
        )
        is True
    )
    assert (
        fire(
            S(phase="P3", lights_on=False, vwc=50, ec=10, feed_ec=3),
            P(max_ec=9, field_capacity=70),
        )
        is True
    )
    # BLOCK when the flush can't help: feed not dilutive, or slab saturated.
    assert (
        fire(S(phase="P2", vwc=50, ec=10, feed_ec=10), P(max_ec=9, field_capacity=70))
        is False
    )
    assert (
        fire(S(phase="P2", vwc=69, ec=10, feed_ec=3), P(max_ec=9, field_capacity=70))
        is False
    )


def test_p2_rescue_flush_not_blocked():
    # ec >= max_ec with dilutive feed + room -> rescue flush fires (cap-exempt)
    assert fire(S(phase="P2", vwc=40, ec=9.5), P(max_ec=9)) is True


# ---------------------------------------------------------------------------
# FINDING #2 — high-EC non-dilutive returns fire=False AND 'BLOCK' in reason
# ---------------------------------------------------------------------------
def test_f2_high_ec_nondilutive_blocks_with_reason():
    _, _, f, _, r = decide(
        S(
            phase="P1",
            vwc=50,
            ec=9.5,
            ec_smooth=9.5,
            feed_ec=9.5,
            minutes_since_shot=20,
        ),
        P(max_ec=9, field_capacity=70),
    )
    assert f is False and "BLOCK" in r


# ---------------------------------------------------------------------------
# FINDING #5 — P2 near-max EC (ec >= max_ec-1) gated by dilutive-feed/slab-room
# ---------------------------------------------------------------------------
def test_f5_p2_near_max_ec_gate():
    # non-dilutive feed + dry-enough-not-to-top-up -> NO EC-driven rescue flush
    n = decide(
        S(phase="P2", vwc=50, ec=8.5, ec_smooth=8.5, feed_ec=9.0),
        P(max_ec=9, ec_target_p2=6, field_capacity=70, p2_threshold=45),
    )
    assert n[2] is False and "rescue" not in n[4]
    # dilutive feed + slab room -> rescue flush fires
    y = decide(
        S(phase="P2", vwc=50, ec=8.5, ec_smooth=8.5, feed_ec=3.0),
        P(max_ec=9, ec_target_p2=6, field_capacity=70, p2_threshold=45),
    )
    assert y[2] is True and "rescue" in y[4]


# ---------------------------------------------------------------------------
# FINDING #5b — the P2 'dilute' tier carries the same dilutive-feed/slab-room gate
# ---------------------------------------------------------------------------
def test_f5b_p2_dilute_tier_gate():
    # (a) non-dilutive (saltier) feed -> dilute tier must NOT fire
    dn = decide(
        S(phase="P2", vwc=55, ec=7.5, ec_smooth=7.5, feed_ec=10),
        P(max_ec=9, ec_target_p2=6, field_capacity=70, p2_threshold=45),
    )
    assert dn[2] is False and "dilute" not in dn[4]
    # (b) same EC but a DILUTIVE feed -> the dilute shot fires
    dy = decide(
        S(phase="P2", vwc=55, ec=7.5, ec_smooth=7.5, feed_ec=2),
        P(max_ec=9, ec_target_p2=6, field_capacity=70, p2_threshold=45),
    )
    assert dy[2] is True and "dilute" in dy[4]
    # (c) non-dilutive feed but genuinely DRY -> VWC top-up still fires
    dd = decide(
        S(phase="P2", vwc=40, ec=7.5, ec_smooth=7.5, feed_ec=10),
        P(max_ec=9, ec_target_p2=6, field_capacity=70, p2_threshold=45),
    )
    assert dd[2] is True and "top-up" in dd[4]


# ---------------------------------------------------------------------------
# FINDING #6 — P1 EC-driven flush/runoff gated like the anti-lockout/P2-rescue tiers
# ---------------------------------------------------------------------------
def test_f6_p1_ceiling_ec_flush_gate():
    base = dict(p1_target=60, field_capacity=70, ec_target_p1=5, max_ec=12)
    # (a) non-dilutive feed, slab has room -> must NOT flush
    n = decide(
        S(phase="P1", vwc=66, ec=8, ec_smooth=8, feed_ec=9, minutes_since_shot=20),
        P(**base),
    )
    assert n[2] is False and "flush" not in n[4] and "runoff" not in n[4]
    # (b) saltier feed than the slab -> must NOT flush
    s = decide(
        S(phase="P1", vwc=66, ec=8, ec_smooth=8, feed_ec=10, minutes_since_shot=20),
        P(**base),
    )
    assert s[2] is False
    # (c) slab full (vwc >= fc-2) even with dilutive feed -> must NOT flush
    full = decide(
        S(phase="P1", vwc=69, ec=8, ec_smooth=8, feed_ec=3, minutes_since_shot=20),
        P(**base),
    )
    assert full[2] is False
    # (d) dilutive feed + slab room -> flush fires and stays P1
    y = decide(
        S(phase="P1", vwc=66, ec=8, ec_smooth=8, feed_ec=3, minutes_since_shot=20),
        P(**base),
    )
    assert y[0] == "P1" and y[2] is True and ("flush" in y[4] or "runoff" in y[4])
    # (e) the VWC-ramp shot (vwc < ceiling) still fires unconditionally even with non-dilutive feed
    r = decide(
        S(phase="P1", vwc=50, ec=8, ec_smooth=8, feed_ec=10, minutes_since_shot=20),
        P(**base),
    )
    assert r[2] is True and "ramp" in r[4]


# ---------------------------------------------------------------------------
# FINDING #1 — P3->P0 + daily-budget reset not hostage to the in-process light edge
# (pure decide() consequence of the wall-clock new_grow_day flag; shell wiring skipped)
# ---------------------------------------------------------------------------
def test_f1_new_grow_day_pure():
    # (a) P3, lights ON, edge MISSED, new grow-day -> P0
    assert (
        ph(
            S(
                phase="P3",
                lights_on=True,
                lights_just_on=False,
                new_grow_day=True,
                vwc=50,
            ),
            P(),
        )
        == "P0"
    )
    # (b) observed in-process edge still works on its own -> P0
    assert (
        ph(
            S(
                phase="P3",
                lights_on=True,
                lights_just_on=True,
                new_grow_day=False,
                vwc=50,
            ),
            P(),
        )
        == "P0"
    )
    # (c) mid-photoperiod after the reset -> stays P2 (no spurious re-reset)
    assert (
        ph(
            S(
                phase="P2",
                lights_on=True,
                lights_just_on=False,
                new_grow_day=False,
                vwc=55,
                ec=6,
                ec_smooth=6,
            ),
            P(),
        )
        == "P2"
    )
    # (d) lights OFF dominates: new_grow_day must NOT pull a lights-off zone out of P3
    assert (
        ph(
            S(
                phase="P3",
                lights_on=False,
                lights_just_on=False,
                new_grow_day=True,
                vwc=50,
            ),
            P(),
        )
        == "P3"
    )
    # (e) a non-P3 zone is unaffected by new_grow_day
    assert (
        ph(
            S(
                phase="P0",
                lights_on=True,
                lights_just_on=False,
                new_grow_day=True,
                vwc=55,
                dryback_pct=5,
                phase_minutes=5,
            ),
            P(),
        )
        == "P0"
    )


# ---------------------------------------------------------------------------
# DESIGN #2 — P1 ramps to FIELD CAPACITY (not an unachievable p1_target)
# ---------------------------------------------------------------------------
def test_d2_p1_ramps_to_field_capacity():
    # (a) p1_target above FC, vwc just below FC -> P1 ramps, not yet transitioning
    a = decide(
        S(phase="P1", vwc=68, ec=5, ec_smooth=5, minutes_since_shot=20),
        P(p1_target=80, field_capacity=70, ec_target_p1=5),
    )
    assert a[0] == "P1" and a[2] is True
    # (a cont.) at vwc>=FC with EC ok -> transitions to P2 (does not chase unachievable target=80)
    assert (
        ph(
            S(phase="P1", vwc=70, ec=5, ec_smooth=5, minutes_since_shot=20),
            P(p1_target=80, field_capacity=70, ec_target_p1=5),
        )
        == "P2"
    )
    # (b) P1 AT ceiling with HIGH ec, dilutive feed + slab room -> flush, stays P1
    b = decide(
        S(phase="P1", vwc=66, ec=8, ec_smooth=8, minutes_since_shot=20, feed_ec=3),
        P(p1_target=60, field_capacity=70, ec_target_p1=5, max_ec=12),
    )
    assert b[0] == "P1" and b[2] is True and ("flush" in b[4] or "runoff" in b[4])
    # (c) P1 at ceiling with acceptable ec -> transitions to P2
    assert (
        ph(
            S(phase="P1", vwc=71, ec=5, ec_smooth=5, minutes_since_shot=20),
            P(p1_target=80, field_capacity=70, ec_target_p1=5),
        )
        == "P2"
    )


# ---------------------------------------------------------------------------
# DESIGN #1 — the effective P2 threshold (base + persisted ec_offset) shifts the
# top-up firing boundary. The IO shell bakes the offset into p.p2_threshold BEFORE
# calling decide(); core.py's decide() does NOT re-derive a threshold from ec_smooth
# (its EC STEERING block is a no-op), so we prove the effect by passing the effective
# threshold straight in. (The old "stacking_on -> threshold DOWN/UP" decide() cases
# are skipped — that mutation no longer exists in the active engine.)
# ---------------------------------------------------------------------------
def test_d1_effective_threshold():
    a = decide(
        S(phase="P2", vwc=44, ec=6, ec_smooth=6), P(p2_threshold=43)
    )  # eff = base45 + (-2)
    b = decide(
        S(phase="P2", vwc=44, ec=6, ec_smooth=6), P(p2_threshold=45)
    )  # base, no offset
    assert a[2] is False and b[2] is True


def test_d1_offset_clamp_helper():
    # The IO-shell clamp bounds offset drift to +/-20% of base; reproduce the formula here
    # (the engine exposes ec_pid's clamp; the stepped-offset clamp itself lives in the shell).
    def clamp_offset(proposed, base):
        return max(-0.20 * base, min(0.20 * base, proposed))

    assert clamp_offset(-99, 45) == -9.0
    assert clamp_offset(99, 45) == 9.0
    assert clamp_offset(-3, 45) == -3.0


# ---------------------------------------------------------------------------
# Watchdog + daily-cap budget (emergencies exempt)
# ---------------------------------------------------------------------------
def test_watchdog():
    assert (
        fire(
            S(
                phase="P3",
                lights_on=True,
                lights_just_on=False,
                vwc=42,
                ec=6,
                feed_ec=3,
                minutes_since_shot=200,
            ),
            P(p2_threshold=45, p3_emergency_floor=40, watchdog_hours=3),
        )
        is True
    )
    # lights-off -> never
    assert (
        fire(
            S(phase="P3", lights_on=False, vwc=42, ec=6, minutes_since_shot=200),
            P(p2_threshold=45, p3_emergency_floor=40, watchdog_hours=3),
        )
        is False
    )
    # recent water -> no fire
    assert (
        fire(
            S(
                phase="P3",
                lights_on=True,
                lights_just_on=False,
                vwc=42,
                ec=6,
                minutes_since_shot=60,
            ),
            P(p2_threshold=45, p3_emergency_floor=40, watchdog_hours=3),
        )
        is False
    )


def test_daily_cap_budget_and_exemptions():
    # normal top-up blocked once over the cap
    assert (
        fire(
            S(phase="P2", vwc=40, daily_vol=300, ec=6, ec_smooth=6),
            P(max_daily_volume=300),
        )
        is False
    )
    # FLUSH exempt from the cap
    assert (
        fire(
            S(phase="P2", vwc=50, ec=10, feed_ec=3, daily_vol=999),
            P(max_ec=9, max_daily_volume=300, field_capacity=70),
        )
        is True
    )
    # WATCHDOG exempt from the cap
    assert (
        fire(
            S(
                phase="P3",
                lights_on=True,
                lights_just_on=False,
                vwc=42,
                ec=6,
                feed_ec=3,
                minutes_since_shot=200,
                daily_vol=999,
            ),
            P(
                p2_threshold=45,
                p3_emergency_floor=40,
                watchdog_hours=3,
                max_daily_volume=300,
            ),
        )
        is True
    )


# ---------------------------------------------------------------------------
# Per-zone independence (zones decide off their own params)
# ---------------------------------------------------------------------------
def test_per_zone_independence():
    a = decide(
        S(phase="P1", vwc=64, ec=5, minutes_since_shot=20),
        P(p1_target=78, ec_target_p1=5),
    )  # still ramping (target 78)
    b = decide(
        S(phase="P1", vwc=64, ec=5, minutes_since_shot=20),
        P(p1_target=62, ec_target_p1=5),
    )  # already past target 62
    assert a[2] is True and b[0] == "P2"


# ---------------------------------------------------------------------------
# ec_adjust tiers
# ---------------------------------------------------------------------------
def test_ec_adjust_tiers():
    assert ec_adjust(5, 9, 6) == 7.5  # ratio 1.5 -> 1.5x
    assert ec_adjust(5, 2, 6) == 2.5  # ratio 0.33 -> 0.5x
    # additional tier coverage from the active core thresholds
    assert ec_adjust(5, 12, 6) == 10.0  # ratio 2.0 -> 2.0x
    assert ec_adjust(5, 7, 6) == 6.0  # ratio ~1.17 -> 1.2x
    assert ec_adjust(5, 3, 6) == 3.5  # ratio 0.5 -> 0.7x band
    assert ec_adjust(5, 6, 6) == 5.0  # in band -> unchanged
    assert ec_adjust(5, 6, 0) == 5.0  # non-positive target -> unchanged


# ---------------------------------------------------------------------------
# ec_pid (pure PID -> threshold offset, anti-windup)
# ---------------------------------------------------------------------------
def test_ec_pid_direction_and_clamp():
    base = 45.0
    # EC above target -> positive offset (water sooner -> dilute)
    off, integ, err = ec_pid(6.0, 5.0, base, 0.0, 0.0, (0.5, 0.1, 0.0))
    assert off > 0 and err == 1.0 and integ == 1.0
    # EC below target -> negative offset (deeper dryback -> stack)
    off2, _, err2 = ec_pid(4.0, 5.0, base, 0.0, 0.0, (0.5, 0.1, 0.0))
    assert off2 < 0 and err2 == -1.0
    # anti-windup: a huge error + wound-up integral can't exceed +/-20% of base (9.0)
    off3, integ3, _ = ec_pid(20.0, 5.0, base, 100.0, 0.0, (5.0, 1.0, 0.0))
    assert abs(off3) <= 0.20 * base + 1e-6 and abs(integ3) <= 9.0 + 1e-6
    # at target with no I -> zero
    assert ec_pid(5.0, 5.0, base, 0.0, 0.0, (0.5, 0.0, 0.0))[0] == 0.0


# ---------------------------------------------------------------------------
# validate_params — clamping incl. the 12.2-EC fat-finger + extended bounds
# ---------------------------------------------------------------------------
def test_validate_ec_fat_finger():
    vp, w = validate_params(P(ec_target_p2=12.2, max_ec=9))
    assert vp.ec_target_p2 == 9.0 and len(w) >= 1
    vp2, w2 = validate_params(P())
    assert w2 == []


def test_validate_extended_clamps():
    vp, w = validate_params(
        P(
            p2_shot_size=50,
            p1_initial=0.1,
            p1_incr=9,
            p1_time_between_min=999,
            p0_max_wait_min=1,
            p3_emergency_shot=99,
            max_daily_volume=5,
        )
    )
    assert vp.p2_shot_size == 20.0
    assert vp.p1_initial == 0.5
    assert vp.p1_incr == 5.0
    assert vp.p1_time_between_min == 120.0
    assert vp.p0_max_wait_min == 5.0
    assert vp.p3_emergency_shot == 15.0
    assert vp.max_daily_volume == 10.0
    assert len(w) == 7


def test_validate_p1_max_shots_stays_int():
    vp, _ = validate_params(P(p1_max_shots=99))
    assert vp.p1_max_shots == 40 and isinstance(vp.p1_max_shots, int)


def test_validate_min_daily_le_max():
    vp, w = validate_params(P(min_daily_volume=400, max_daily_volume=300))
    assert vp.min_daily_volume == 300 and any("min_daily_volume" in x for x in w)


# ---------------------------------------------------------------------------
# cross_zone_outliers
# ---------------------------------------------------------------------------
def test_cross_zone_outliers():
    def vs(v):
        return S(daily_vol=v)

    assert len(cross_zone_outliers({1: vs(50), 2: vs(48), 3: vs(8)})) == 1
    assert cross_zone_outliers({1: vs(20), 2: vs(20), 3: vs(20)}) == []
    assert cross_zone_outliers({1: vs(2), 2: vs(3)}) == []  # median < 5 -> none


# ---------------------------------------------------------------------------
# pick_sibling (blind zone copies the recipe-closest healthy sibling)
# ---------------------------------------------------------------------------
def test_pick_sibling():
    assert pick_sibling(60, [(1, 55), (2, 62), (3, 75)]) == 2  # closest target wins
    assert (
        pick_sibling(60, [(3, 65), (1, 55), (2, 80)]) == 1
    )  # exact tie -> lowest zone
    assert pick_sibling(60, [(2, 99)]) == 2  # single healthy zone
    assert pick_sibling(60, []) is None  # none -> None
    assert pick_sibling(50, [(1, 48), (2, 50), (3, 52)]) == 2  # exact match (dist 0)


# ---------------------------------------------------------------------------
# feed_grace_ok (last-known-good feed reading within grace)
# ---------------------------------------------------------------------------
def test_feed_grace_ok():
    now = 1000.0
    assert feed_grace_ok(now, now - 10 * 60, 30) is True  # 10min old, 30min grace
    assert feed_grace_ok(now, now - 45 * 60, 30) is False  # 45min old, past grace
    assert feed_grace_ok(now, None, 30) is False  # never good
    assert feed_grace_ok(now, now - 30 * 60, 30) is False  # exactly at edge -> strict <


# ---------------------------------------------------------------------------
# STATUS republish helpers — vocabulary must stay byte-identical to the master app
# ---------------------------------------------------------------------------
def test_zone_safety_status():
    assert zone_safety_status(72, 3.0, 70, 9) == "over_saturated"
    assert zone_safety_status(50, 9.5, 70, 9) == "ec_limit_exceeded"
    assert (
        zone_safety_status(72, 10.0, 70, 9) == "over_saturated"
    )  # saturated outranks ec
    assert zone_safety_status(66, 3.0, 70, 9) == "approaching_saturation"
    assert zone_safety_status(50, 8.5, 70, 9) == "approaching_ec_limit"
    assert zone_safety_status(50, 3.0, 70, 9) == "safe"
    assert zone_safety_status(None, None, 70, 9) == "safe"  # blind probe -> safe
    assert (
        zone_safety_status(None, 9.5, 70, 9) == "ec_limit_exceeded"
    )  # vwc dead, ec over


def test_system_safety_status():
    assert system_safety_status(["safe", "safe", "safe"]) == ("safe", 0, 0, 3)
    assert system_safety_status(["safe", "approaching_ec_limit", "safe"]) == (
        "warning",
        0,
        1,
        2,
    )
    assert system_safety_status(
        ["ec_limit_exceeded", "approaching_saturation", "safe"]
    ) == (
        "unsafe",
        1,
        1,
        1,
    )
    assert system_safety_status([]) == ("safe", 0, 0, 0)


def test_zone_status_label():
    assert zone_status_label("P2", False, None, False, "P2 hold") == "Optimal"
    assert zone_status_label("P2", True, None, False, "P2 top-up") == "Topping up"
    assert zone_status_label("P1", True, None, False, "P1 ramp") == "Refilling"
    assert zone_status_label("P0", False, None, False, "") == "Drying back"
    assert (
        zone_status_label("P2", False, None, True, "COPY Z1") == "Probe dead — copying"
    )
    assert zone_status_label("P2", False, "manual override", False, "").startswith(
        "Blocked:"
    )
    assert (
        zone_status_label(
            "P2", False, None, False, "BLOCK high EC 10.5 — feed not dilutive"
        )
        == "Blocked — EC/cap"
    )
