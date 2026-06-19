"""Pure-function unit harness for lean_crop_steering.decide(). No HA / AppDaemon needed.
Run from this directory: python test_lean_decide.py"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")   # Windows cp1252 stdout can't encode → / — in detail strings
except Exception:
    pass
import os
import tempfile
from datetime import datetime, timedelta, timezone
from lean_crop_steering import (decide, ZoneParams, ZoneSnapshot, ec_adjust, cross_zone_outliers,
                                validate_params, LeanCropSteering, pick_sibling, feed_grace_ok,
                                zone_safety_status, system_safety_status, zone_status_label)


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


cases = []


def case(name, snap, par, want_phase=None, want_fire=None):
    ph, thr, fire, size, reason = decide(snap, par)
    ok = ((want_phase is None or ph == want_phase) and (want_fire is None or fire == want_fire))
    cases.append((ok, name, f"phase={ph} fire={fire} size={size} thr={thr} :: {reason}"))


# ---- phase transitions ----
case("lights-off -> P3 from P2", S(lights_on=False, phase="P2"), P(), want_phase="P3")
case("lights-off -> P3 from P1", S(lights_on=False, phase="P1"), P(), want_phase="P3")
case("lights-on P3 -> P0", S(phase="P3", lights_just_on=True, vwc=42), P(), want_phase="P0")
case("P0 -> P1 dryback done", S(phase="P0", vwc=55, peak_vwc=70, dryback_pct=21), P(), want_phase="P1")
case("P0 -> P1 already-dry bypass", S(phase="P0", vwc=44, peak_vwc=70, dryback_pct=5), P(), want_phase="P1")
case("P0 -> P1 timeout", S(phase="P0", vwc=58, dryback_pct=5, phase_minutes=50), P(), want_phase="P1")
case("P0 holds (still drying)", S(phase="P0", vwc=58, dryback_pct=5, phase_minutes=10), P(), want_phase="P0")
# Design #2: P1->P2 "recovered" now also requires pore EC back in band (ec <= ec_target_p1*1.15).
# Default S() has ec=6 which exceeds 5*1.15=5.75, so graduation needs an in-band EC here.
case("P1 -> P2 recovered", S(phase="P1", vwc=61, ec=5, ec_smooth=5), P(), want_phase="P2")
case("P1 -> P2 max shots", S(phase="P1", vwc=50, shot_count=12), P(), want_phase="P2")
case("P1 -> P2 120min ceiling", S(phase="P1", vwc=50, phase_minutes=121), P(), want_phase="P2")
case("P2 -> P3 predictive", S(phase="P2", vwc=55, hours_to_lights_off=2, hours_to_lights_on=2, dryback_rate=10),
     P(dryback_target=20), want_phase="P3")
case("P2 no early P3 (>3h to off)", S(phase="P2", vwc=55, hours_to_lights_off=6), P(), want_phase="P2")

# ---- irrigation ----
case("P1 fires VWC<target", S(phase="P1", vwc=50, minutes_since_shot=20), P(), want_fire=True)
case("P1 cooldown blocks", S(phase="P1", vwc=50, minutes_since_shot=5), P(), want_fire=False)
case("P2 top-up VWC<thr", S(phase="P2", vwc=40, ec=6, ec_smooth=6), P(), want_fire=True)
case("P2 hold (VWC>thr, EC in band)", S(phase="P2", vwc=55, ec=6, ec_smooth=6), P(), want_fire=False)
case("P2 dilute high EC", S(phase="P2", vwc=55, ec=8), P(), want_fire=True)
case("P2 low-EC alone NO fire", S(phase="P2", vwc=55, ec=2, ec_smooth=2), P(), want_fire=False)
case("P3 emergency fires", S(phase="P3", vwc=38), P(), want_fire=True)
case("P3 no fire above floor", S(phase="P3", vwc=50), P(), want_fire=False)
case("P0 no fire", S(phase="P0", vwc=55, dryback_pct=5, phase_minutes=5), P(), want_fire=False)
case("P0 EC emergency flush", S(phase="P0", vwc=55, ec=12, dryback_pct=5, phase_minutes=5), P(ec_target_p0=4), want_fire=True)

# ---- safety ----
case("max-EC -> P2 rescue flush (not blocked)", S(phase="P2", vwc=40, ec=9.5), P(max_ec=9), want_fire=True)
case("high-EC + non-dilutive feed BLOCKS", S(phase="P1", vwc=50, ec=9.5, feed_ec=9.5, minutes_since_shot=20), P(max_ec=9), want_fire=False)
case("daily cap blocks", S(phase="P2", vwc=40, daily_vol=300, ec=6, ec_smooth=6), P(max_daily_volume=300), want_fire=False)

# ---- FINDING #5: P2 near-max EC (ec >= max_ec-1) gated by the same dilutive-feed/slab-room test ----
# non-dilutive feed + dry-enough-to-not-top-up -> NO EC-driven fire (must not rescue-flush)
_p5n = decide(S(phase="P2", vwc=50, ec=8.5, ec_smooth=8.5, feed_ec=9.0), P(max_ec=9, ec_target_p2=6, field_capacity=70, p2_threshold=45))
cases.append((_p5n[2] is False and "rescue" not in _p5n[4],
              "F5 P2 near-max EC non-dilutive -> no rescue flush", f"fire={_p5n[2]} :: {_p5n[4]}"))
# dilutive feed + slab room -> rescue flush DOES fire
_p5y = decide(S(phase="P2", vwc=50, ec=8.5, ec_smooth=8.5, feed_ec=3.0), P(max_ec=9, ec_target_p2=6, field_capacity=70, p2_threshold=45))
cases.append((_p5y[2] is True and "rescue" in _p5y[4],
              "F5 P2 near-max EC dilutive+room -> rescue flush fires", f"fire={_p5y[2]} :: {_p5y[4]}"))

# ---- FINDING #5b: the P2 'dilute' tier (1.2 < ec/target, ec < max_ec-1) carries the SAME dilutive-feed/
# slab-room gate as the rescue tier — firing a dilute shot with a non-dilutive/saltier feed adds salt+water
# that can't lower pore EC (pushes it the WRONG way). Geometry: ec_target_p2=6 so ratio>1.2 at ec>7.2, and
# max_ec=9 so ec=7.5 is in the dilute window (< max_ec-1=8). vwc=55 < fc-2=68 so the slab has room.
# (a) non-dilutive (saltier) feed -> dilute tier must NOT fire (no flush/dilute; VWC top-up path is off too)
_p5dn = decide(S(phase="P2", vwc=55, ec=7.5, ec_smooth=7.5, feed_ec=10), P(max_ec=9, ec_target_p2=6, field_capacity=70, p2_threshold=45))
cases.append((_p5dn[2] is False and "dilute" not in _p5dn[4],
              "F5b P2 dilute-tier non-dilutive feed -> no dilute fire", f"fire={_p5dn[2]} :: {_p5dn[4]}"))
# (b) same EC but a DILUTIVE feed -> the dilute shot legitimately fires (gate must not suppress real dilution)
_p5dy = decide(S(phase="P2", vwc=55, ec=7.5, ec_smooth=7.5, feed_ec=2), P(max_ec=9, ec_target_p2=6, field_capacity=70, p2_threshold=45))
cases.append((_p5dy[2] is True and "dilute" in _p5dy[4],
              "F5b P2 dilute-tier dilutive feed -> dilute fires", f"fire={_p5dy[2]} :: {_p5dy[4]}"))
# (c) non-dilutive feed but genuinely DRY (vwc < p2_thr) -> still gets a VWC top-up (dry zone not starved)
_p5dd = decide(S(phase="P2", vwc=40, ec=7.5, ec_smooth=7.5, feed_ec=10), P(max_ec=9, ec_target_p2=6, field_capacity=70, p2_threshold=45))
cases.append((_p5dd[2] is True and "top-up" in _p5dd[4],
              "F5b P2 dilute-tier non-dilutive but dry -> VWC top-up still fires", f"fire={_p5dd[2]} :: {_p5dd[4]}"))

# ---- FINDING #2: high-EC non-dilutive returns fire=False AND 'BLOCK' in reason (so the IO alert matches) ----
_p2b = decide(S(phase="P1", vwc=50, ec=9.5, ec_smooth=9.5, feed_ec=9.5, minutes_since_shot=20), P(max_ec=9, field_capacity=70))
cases.append((_p2b[2] is False and "BLOCK" in _p2b[4],
              "F2 high-EC non-dilutive -> fire False + BLOCK in reason", f"fire={_p2b[2]} :: {_p2b[4]}"))

# ---- FINDING #6: P1 EC-driven flush/runoff shot gated by the SAME dilutive-feed/slab-room test as the
# anti-lockout + P2-rescue tiers. Geometry: ceiling = min(p1_target 60, fc 70) = 60, so vwc 66 is AT/above
# the ceiling (VWC-ramp branch OFF) and the only thing that could fire is the EC flush. ec 8 > 5*1.15=5.75.
# (a) non-dilutive feed (feed_ec >= ec), slab has room -> must NOT flush (can't drop EC, just adds salt+water)
_p6n = decide(S(phase="P1", vwc=66, ec=8, ec_smooth=8, feed_ec=9, minutes_since_shot=20),
              P(p1_target=60, field_capacity=70, ec_target_p1=5, max_ec=12))
cases.append((_p6n[2] is False and "flush" not in _p6n[4] and "runoff" not in _p6n[4],
              "F6 P1 ceiling+high-EC non-dilutive -> no flush", f"fire={_p6n[2]} :: {_p6n[4]}"))
# (b) saltier feed than the slab is also non-dilutive -> must NOT flush
_p6s = decide(S(phase="P1", vwc=66, ec=8, ec_smooth=8, feed_ec=10, minutes_since_shot=20),
              P(p1_target=60, field_capacity=70, ec_target_p1=5, max_ec=12))
cases.append((_p6s[2] is False,
              "F6 P1 ceiling+high-EC saltier feed -> no flush", f"fire={_p6s[2]} :: {_p6s[4]}"))
# (c) slab full (vwc >= fc-2) even with dilutive feed -> must NOT flush (no room; let 120-min escape graduate)
_p6f = decide(S(phase="P1", vwc=69, ec=8, ec_smooth=8, feed_ec=3, minutes_since_shot=20),
              P(p1_target=60, field_capacity=70, ec_target_p1=5, max_ec=12))
cases.append((_p6f[2] is False,
              "F6 P1 ceiling+high-EC slab-full -> no flush", f"fire={_p6f[2]} :: {_p6f[4]}"))
# (d) dilutive feed + slab room -> flush DOES fire and stays P1 (the legitimate runoff/flush)
_p6y = decide(S(phase="P1", vwc=66, ec=8, ec_smooth=8, feed_ec=3, minutes_since_shot=20),
              P(p1_target=60, field_capacity=70, ec_target_p1=5, max_ec=12))
cases.append((_p6y[0] == "P1" and _p6y[2] is True and ("flush" in _p6y[4] or "runoff" in _p6y[4]),
              "F6 P1 ceiling+high-EC dilutive+room -> flush fires", f"phase={_p6y[0]} fire={_p6y[2]} :: {_p6y[4]}"))
# (e) the VWC-ramp shot (vwc < ceiling) still fires UNCONDITIONALLY — even with a non-dilutive feed —
# because that's a hydration shot, not an EC flush; gating it would starve a genuinely dry P1 zone.
_p6r = decide(S(phase="P1", vwc=50, ec=8, ec_smooth=8, feed_ec=10, minutes_since_shot=20),
              P(p1_target=60, field_capacity=70, ec_target_p1=5, max_ec=12))
cases.append((_p6r[2] is True and "ramp" in _p6r[4],
              "F6 P1 VWC-ramp shot still fires unconditionally", f"fire={_p6r[2]} :: {_p6r[4]}"))

# ---- FINDING #1: P3->P0 + daily-budget reset must NOT be hostage to the in-process off->on light edge.
# If AppDaemon restarts/reloads ACROSS lights-on (down 09:59, up 10:01), lights_just_on is never observed
# (it derives from the in-process _was_lights_on). A wall-clock fallback (new_grow_day) forces P3->P0 so the
# zone isn't stranded in P3 (emergency-only) on yesterday's stale budget for the whole photoperiod.
# (a) the failure mode: P3, lights ON, edge MISSED (lights_just_on=False), new grow-day -> P0
_f1a = decide(S(phase="P3", lights_on=True, lights_just_on=False, new_grow_day=True, vwc=50), P())
cases.append((_f1a[0] == "P0",
              "F1 P3 + lights-on + missed edge + new grow-day -> P0", f"phase={_f1a[0]} :: {_f1a[4]}"))
# (b) the original in-process edge still works on its own (new_grow_day False) -> P0
_f1b = decide(S(phase="P3", lights_on=True, lights_just_on=True, new_grow_day=False, vwc=50), P())
cases.append((_f1b[0] == "P0",
              "F1 P3 + observed light edge (no wall-clock) -> P0", f"phase={_f1b[0]} :: {_f1b[4]}"))
# (c) mid-photoperiod after the reset (same grow-day, new_grow_day=False, no edge): must NOT re-enter P0.
# A P2 zone with the budget already reset for today stays P2 — the fallback can't spuriously reset it.
_f1c = decide(S(phase="P2", lights_on=True, lights_just_on=False, new_grow_day=False, vwc=55, ec=6, ec_smooth=6), P())
cases.append((_f1c[0] == "P2",
              "F1 mid-photoperiod (reset done) -> stays P2, no re-reset", f"phase={_f1c[0]} :: {_f1c[4]}"))
# (d) lights OFF dominates: new_grow_day must NOT pull a lights-off zone out of P3 (the lights-off->P3
# rule is checked first and P3 with no light has nothing to advance to).
_f1d = decide(S(phase="P3", lights_on=False, lights_just_on=False, new_grow_day=True, vwc=50), P())
cases.append((_f1d[0] == "P3",
              "F1 lights-off + new_grow_day -> stays P3 (no spurious P0)", f"phase={_f1d[0]} :: {_f1d[4]}"))
# (e) a non-P3 zone is unaffected by new_grow_day (only P3 has the P0-entry branch).
_f1e = decide(S(phase="P0", lights_on=True, lights_just_on=False, new_grow_day=True, vwc=55, dryback_pct=5, phase_minutes=5), P())
cases.append((_f1e[0] == "P0",
              "F1 new_grow_day on a P0 zone is a no-op (still P0)", f"phase={_f1e[0]} :: {_f1e[4]}"))

# ---- DESIGN #2: P1 ramps to FIELD CAPACITY (not an unachievable p1_target), flushes EC before P2 ----
# (a) p1_target above FC, vwc just below FC -> P1 ramps (fire True), NOT yet transitioning
case("D2 P1 ramps below FC (target>FC)", S(phase="P1", vwc=68, ec=5, ec_smooth=5, minutes_since_shot=20),
     P(p1_target=80, field_capacity=70, ec_target_p1=5), want_phase="P1", want_fire=True)
# (a cont.) at vwc>=FC with EC ok -> transitions to P2 (does NOT chase the unachievable p1_target=80)
case("D2 P1->P2 at FC not unachievable target", S(phase="P1", vwc=70, ec=5, ec_smooth=5, minutes_since_shot=20),
     P(p1_target=80, field_capacity=70, ec_target_p1=5), want_phase="P2")
# (b) P1 AT ceiling (ramp off) with HIGH ec, dilutive feed + slab room -> fires a runoff/flush shot
# AND does NOT transition to P2. Geometry: ceiling = min(p1_target 60, fc 70) = 60, vwc 66 is >= ceiling
# (so the VWC-ramp branch is off and the FLUSH branch is what fires) yet < fc-2 (68) so the slab has room.
_d2b = decide(S(phase="P1", vwc=66, ec=8, ec_smooth=8, minutes_since_shot=20, feed_ec=3),
              P(p1_target=60, field_capacity=70, ec_target_p1=5, max_ec=12))
cases.append((_d2b[0] == "P1" and _d2b[2] is True and ("flush" in _d2b[4] or "runoff" in _d2b[4]),
              "D2 P1 at ceiling + high EC -> flush, stays P1", f"phase={_d2b[0]} fire={_d2b[2]} :: {_d2b[4]}"))
# (c) P1 at ceiling with acceptable ec -> transitions to P2
case("D2 P1 at ceiling EC ok -> P2", S(phase="P1", vwc=71, ec=5, ec_smooth=5, minutes_since_shot=20),
     P(p1_target=80, field_capacity=70, ec_target_p1=5), want_phase="P2")

# ---- EC steering (threshold direction) — DESIGN #1 keeps decide()'s direction logic unchanged ----
_, thr_lo, *_ = decide(S(phase="P2", ec_smooth=4, vwc=55), P(stacking_on=True, ec_target_p2=6, p2_threshold=45))
cases.append((thr_lo < 45, "EC steer: low EC -> threshold DOWN", f"thr={thr_lo}"))
_, thr_hi, *_ = decide(S(phase="P2", ec_smooth=8, vwc=55), P(stacking_on=True, ec_target_p2=6, p2_threshold=45))
cases.append((thr_hi > 45, "EC steer: high EC -> threshold UP", f"thr={thr_hi}"))

# ---- DESIGN #1: decide() steers around the EFFECTIVE threshold (base + persisted ec_offset). ----
# _params() builds p2_threshold = base + offset, so a -2 offset (base 45 -> eff 43) moves the top-up
# boundary down: vwc=44 holds at eff-43 but would have fired at base-45. Proves the offset is what
# decide() consumes (no operator-entity write needed).
_d1a = decide(S(phase="P2", vwc=44, ec=6, ec_smooth=6), P(p2_threshold=43))   # effective = base(45) + offset(-2)
_d1b = decide(S(phase="P2", vwc=44, ec=6, ec_smooth=6), P(p2_threshold=45))   # operator base, no offset
cases.append((_d1a[2] is False and _d1b[2] is True,
              "D1 effective threshold = base+offset shifts the top-up boundary",
              f"eff43.fire={_d1a[2]} base45.fire={_d1b[2]}"))
# loop()'s offset clamp bounds drift to +/-20% of base, so EC-steer can never run the floor away.
def _clamp_offset(proposed, base): return max(-0.20 * base, min(0.20 * base, proposed))
cases.append((_clamp_offset(-99, 45) == -9.0 and _clamp_offset(99, 45) == 9.0 and _clamp_offset(-3, 45) == -3.0,
              "D1 ec_offset clamps to +/-20% of base", f"{_clamp_offset(-99,45)},{_clamp_offset(99,45)},{_clamp_offset(-3,45)}"))

# ---- DEFECT #1/#2: the EC-steer offset is PROPORTIONAL off BASE, not an INTEGRATOR off the effective
# threshold. The old code nudged decide()'s already-offset threshold by ±1 and fed (new_thr-base) back as
# the offset, so a SUSTAINED EC deviation ratcheted the offset 1,2,3,...->the ±20% rail (and a transient
# excursion never decayed). Drive the REAL loop step (_step_ec_offset) across N ticks and assert it PARKS
# at ±1 (≈1 VWC-point), not the rail, and that an in-band EC DECAYS the offset back toward 0.
_step = LeanCropSteering._step_ec_offset      # the real per-tick offset update used by loop()
_BASE, _TGT = 45.0, 6.0                        # base threshold; ec_target_p2

# (a) steady HIGH EC (ec_smooth=8 > 6*1.10) over 30 ticks -> offset settles at +1.0 (NOT +9.0 rail)
_off = 0.0
for _ in range(30):
    _off = _step(_off, 8.0, _TGT, _BASE)
cases.append((_off == 1.0,
              "D1 multi-tick: steady high EC parks offset at +1 (not the +9 rail)", f"offset={_off}"))
# (a') AGRONOMIC consequence: with the offset parked at +1, _params builds the EFFECTIVE re-water floor
# = base+offset = 46, so the zone tops up at vwc<46 — NOT at vwc<54 (base+9) as the old integrator did.
# Probe the firing boundary with stacking OFF (decide()'s own ±1 nudge is bounded and does not feed back,
# so the parked offset IS the floor): vwc=45.9 fires, vwc=46.1 holds; and the old rail (54) would wrongly
# fire a vwc=53 zone (~8 VWC-points too wet). Effective threshold here = base(45) + parked offset(+1).
_eff_thr = _BASE + _off
_eff_fire = decide(S(phase="P2", vwc=45.9, ec=6, ec_smooth=6), P(ec_target_p2=6, p2_threshold=_eff_thr))
_eff_hold = decide(S(phase="P2", vwc=46.1, ec=6, ec_smooth=6), P(ec_target_p2=6, p2_threshold=_eff_thr))
_old_rail = decide(S(phase="P2", vwc=53.0, ec=6, ec_smooth=6), P(ec_target_p2=6, p2_threshold=_BASE + 9.0))
cases.append((_eff_thr == 46.0 and _eff_fire[2] is True and _eff_hold[2] is False and _old_rail[2] is True,
              "D1 multi-tick: re-water floor settles at base+1 (waters ~46, not the old base+9 rail ~54)",
              f"eff_thr={_eff_thr} fire@45.9={_eff_fire[2]} hold@46.1={_eff_hold[2]} oldRail@53={_old_rail[2]}"))

# (b) steady LOW EC (ec_smooth=4 < 6*0.90) over 30 ticks -> offset settles at -1.0 (NOT the -9.0 rail)
_offlo = 0.0
for _ in range(30):
    _offlo = _step(_offlo, 4.0, _TGT, _BASE)
cases.append((_offlo == -1.0,
              "D1 multi-tick: steady low EC parks offset at -1 (not the -9 rail)", f"offset={_offlo}"))

# (c) after building offset under high EC, an IN-BAND EC (0.90 <= ratio <= 1.10) DECAYS it back toward 0
# (the old integrator pinned it — it never unwound when EC returned to band).
_offd = 1.0                                    # start parked high
_offd = _step(_offd, 6.0, _TGT, _BASE)         # one in-band tick
cases.append((_offd == 0.0,
              "D1 multi-tick: in-band EC decays the offset back toward 0 (no permanent shift)", f"offset={_offd}"))
# (c') and it does NOT overshoot below 0 on continued in-band ticks (parks at 0)
for _ in range(5):
    _offd = _step(_offd, 6.0, _TGT, _BASE)
cases.append((_offd == 0.0,
              "D1 multi-tick: in-band EC holds offset at 0 (no overshoot)", f"offset={_offd}"))
# (d) a single step is bounded to ±1 even from a large stale offset (no jump to the proposal/rail)
cases.append((_step(5.0, 4.0, _TGT, _BASE) == 4.0 and _step(-5.0, 8.0, _TGT, _BASE) == -4.0,
              "D1 multi-tick: per-tick move is bounded to ±1 (no integration jump)",
              f"{_step(5.0,4.0,_TGT,_BASE)},{_step(-5.0,8.0,_TGT,_BASE)}"))

# ---- ec_adjust ----
cases.append((ec_adjust(5, 9, 6) == 7.5, "ec_adjust dilute 1.5x", str(ec_adjust(5, 9, 6))))
cases.append((ec_adjust(5, 2, 6) == 2.5, "ec_adjust conserve 0.5x", str(ec_adjust(5, 2, 6))))

# ---- INVARIANT 1: anti-lockout — high EC FLUSHES in any phase (dilutive feed); blocks only if it can't help ----
case("anti-lockout FLUSH in P0", S(phase="P0", vwc=50, ec=10, feed_ec=3, dryback_pct=5, phase_minutes=5), P(max_ec=9, field_capacity=70), want_fire=True)
case("anti-lockout FLUSH in P1", S(phase="P1", vwc=50, ec=10, feed_ec=3, minutes_since_shot=20), P(max_ec=9, field_capacity=70), want_fire=True)
case("anti-lockout FLUSH in P3", S(phase="P3", lights_on=False, vwc=50, ec=10, feed_ec=3), P(max_ec=9, field_capacity=70), want_fire=True)
case("high EC BLOCK: feed not dilutive", S(phase="P2", vwc=50, ec=10, feed_ec=10), P(max_ec=9, field_capacity=70), want_fire=False)
case("high EC BLOCK: slab saturated", S(phase="P2", vwc=69, ec=10, feed_ec=3), P(max_ec=9, field_capacity=70), want_fire=False)

# ---- INVARIANT 2: lights-on watering watchdog (backstop when phase logic declines a dry zone) ----
case("WATCHDOG fires (P3 lights-on, dry, >3h)", S(phase="P3", lights_on=True, lights_just_on=False, vwc=42, ec=6, feed_ec=3, minutes_since_shot=200), P(p2_threshold=45, p3_emergency_floor=40, watchdog_hours=3), want_fire=True)
case("WATCHDOG no-fire (lights-off)", S(phase="P3", lights_on=False, vwc=42, ec=6, minutes_since_shot=200), P(p2_threshold=45, p3_emergency_floor=40, watchdog_hours=3), want_fire=False)
case("WATCHDOG no-fire (recent water)", S(phase="P3", lights_on=True, lights_just_on=False, vwc=42, ec=6, minutes_since_shot=60), P(p2_threshold=45, p3_emergency_floor=40, watchdog_hours=3), want_fire=False)

# ---- daily cap is a BUDGET: emergencies (flush/watchdog) exempt ----
case("daily-cap exempts FLUSH", S(phase="P2", vwc=50, ec=10, feed_ec=3, daily_vol=999), P(max_ec=9, max_daily_volume=300, field_capacity=70), want_fire=True)
case("daily-cap exempts WATCHDOG", S(phase="P3", lights_on=True, lights_just_on=False, vwc=42, ec=6, feed_ec=3, minutes_since_shot=200, daily_vol=999), P(p2_threshold=45, p3_emergency_floor=40, watchdog_hours=3, max_daily_volume=300), want_fire=True)

# ---- INVARIANT 3: cross-zone outlier detector ----
def _vs(v): return S(daily_vol=v)
cases.append((len(cross_zone_outliers({1: _vs(50), 2: _vs(48), 3: _vs(8)})) == 1, "cross-zone [50,48,8] flags 1", str(cross_zone_outliers({1: _vs(50), 2: _vs(48), 3: _vs(8)}))))
cases.append((cross_zone_outliers({1: _vs(20), 2: _vs(20), 3: _vs(20)}) == [], "cross-zone even -> none", "ok"))
cases.append((cross_zone_outliers({1: _vs(2), 2: _vs(3)}) == [], "cross-zone tiny-vol -> none (median<5)", "ok"))

# ---- INVARIANT 4: config validation clamps the fat-finger ----
_vp, _w = validate_params(P(ec_target_p2=12.2, max_ec=9))
cases.append((_vp.ec_target_p2 == 9.0 and len(_w) >= 1, "validate ec 12.2 -> clamp 9 + warn", f"ec={_vp.ec_target_p2} warns={_w}"))
_vp2, _w2 = validate_params(P())
cases.append((_w2 == [], "validate sane params -> no warn", str(_w2)))

# FINDING #4: the extended clamp set (shot sizes, P1 ramp params, waits, caps).
_vp4, _w4 = validate_params(P(p2_shot_size=50, p1_initial=0.1, p1_incr=9, p1_time_between_min=999,
                             p0_max_wait_min=1, p3_emergency_shot=99, max_daily_volume=5))
cases.append((_vp4.p2_shot_size == 20.0 and _vp4.p1_initial == 0.5 and _vp4.p1_incr == 5.0
              and _vp4.p1_time_between_min == 120.0 and _vp4.p0_max_wait_min == 5.0
              and _vp4.p3_emergency_shot == 15.0 and _vp4.max_daily_volume == 10.0 and len(_w4) == 7,
              "F4 extended clamps (shot/p1/wait/cap) all bound + warned",
              f"shot={_vp4.p2_shot_size} init={_vp4.p1_initial} incr={_vp4.p1_incr} warns={len(_w4)}"))
# FINDING #4: p1_max_shots clamps AND stays an int (not a float) after clamping.
_vp4b, _ = validate_params(P(p1_max_shots=99))
cases.append((_vp4b.p1_max_shots == 40 and isinstance(_vp4b.p1_max_shots, int),
              "F4 p1_max_shots clamps to 40 and stays int", f"val={_vp4b.p1_max_shots!r} type={type(_vp4b.p1_max_shots).__name__}"))

# ---- INVARIANT 5: zones decide INDEPENDENTLY off their own params ----
_zA = decide(S(phase="P1", vwc=64, ec=5, minutes_since_shot=20), P(p1_target=78, ec_target_p1=5))   # strain A still ramping (target 78)
_zB = decide(S(phase="P1", vwc=64, ec=5, minutes_since_shot=20), P(p1_target=62, ec_target_p1=5))   # strain B already past its target 62
cases.append((_zA[2] is True and _zB[0] == "P2", "per-zone independence: same VWC, different recipe -> different outcome", f"A.fire={_zA[2]} B.phase={_zB[0]}"))

# ---- INVARIANT 6 (F3): per-zone state survives a restart — daily_vol budget must NOT zero on reload ----
# Exercise the REAL IO-shell persistence helpers (no HA): bind the unbound methods onto a minimal
# stand-in that supplies only the attributes they touch. A reload must restore daily_vol/last_shot/
# phase, so the daily cap can't be defeated once per AppDaemon file-watch reload.
class _Persist:
    """Minimal carrier for the real _load_state/_save_state/_fresh_zone/_advance_shot_counters methods."""
    _fresh_zone = LeanCropSteering._fresh_zone
    _load_state = LeanCropSteering._load_state
    _save_state = LeanCropSteering._save_state
    _advance_shot_counters = LeanCropSteering._advance_shot_counters
    substrate_l = 6.0
    def __init__(self, path, zones):
        self._state_path = path
        self.zones = zones
        self.state = {}
    def log(self, *a, **k):
        pass

with tempfile.TemporaryDirectory() as _td:
    _sp = os.path.join(_td, "state.json")
    # 1) a process writes a mid-photoperiod budget...
    _w = _Persist(_sp, {1: None, 2: None})
    _w.state = {1: _w._fresh_zone(), 2: _w._fresh_zone()}
    _shot = datetime(2026, 6, 18, 14, 30, 0)
    _pc = datetime(2026, 6, 18, 10, 0, 0)
    _steer = datetime(2026, 6, 18, 13, 0, 0)
    _reset_date = datetime(2026, 6, 18).date()
    _w.state[1].update(phase="P2", daily_vol=210.0, shots=7, peak=66.0, ec_smooth=6.1,
                       last_shot=_shot, last_phase_change=_pc,
                       ec_offset=-2.5, last_ec_steer=_steer,   # DESIGN #1: EC-steer offset persists too
                       last_daily_reset=_reset_date)           # FINDING #1: grow-day reset stamp persists too
    _w._save_state()
    # 2) ...a reload constructs fresh and restores from disk (the initialize() path).
    _r = _Persist(_sp, {1: None, 2: None})
    _restored = _r._load_state()
    cases.append((_restored[1]["daily_vol"] == 210.0 and _restored[1]["shots"] == 7,
                  "F3 restart: daily_vol/shots survive reload (not zeroed)",
                  f"daily_vol={_restored[1]['daily_vol']} shots={_restored[1]['shots']}"))
    cases.append((_restored[1]["last_shot"] == _shot and _restored[1]["last_phase_change"] == _pc,
                  "F3 restart: last_shot/last_phase_change round-trip as datetime",
                  f"last_shot={_restored[1]['last_shot']!r}"))
    cases.append((_restored[1]["phase"] == "P2" and _restored[2]["daily_vol"] == 0.0,
                  "F3 restart: phase restored; untouched zone stays fresh",
                  f"z1.phase={_restored[1]['phase']} z2.daily_vol={_restored[2]['daily_vol']}"))
    # DESIGN #1: ec_offset (float) and last_ec_steer (datetime) round-trip; fresh zone defaults
    cases.append((_restored[1]["ec_offset"] == -2.5 and _restored[1]["last_ec_steer"] == _steer,
                  "D1 restart: ec_offset/last_ec_steer round-trip",
                  f"ec_offset={_restored[1]['ec_offset']} last_ec_steer={_restored[1]['last_ec_steer']!r}"))
    cases.append((_restored[2]["ec_offset"] == 0.0 and _restored[2]["last_ec_steer"] is None,
                  "D1 restart: fresh zone defaults ec_offset=0/last_ec_steer=None",
                  f"ec_offset={_restored[2]['ec_offset']} last_ec_steer={_restored[2]['last_ec_steer']!r}"))
    # FINDING #1: the grow-day reset stamp round-trips as a date; fresh zone defaults to None ("never reset"
    # -> always permits the first P0 entry). Without this, a reload across lights-on can't tell the budget
    # is stale and the zone strands in P3 on yesterday's budget.
    from datetime import date as _date
    cases.append((_restored[1]["last_daily_reset"] == _reset_date and isinstance(_restored[1]["last_daily_reset"], _date),
                  "F1 restart: last_daily_reset round-trips as date",
                  f"last_daily_reset={_restored[1]['last_daily_reset']!r}"))
    cases.append((_restored[2]["last_daily_reset"] is None,
                  "F1 restart: fresh zone defaults last_daily_reset=None", f"{_restored[2]['last_daily_reset']!r}"))

# corrupt / missing state file -> fresh state, never a crash (fail safe)
_bad = _Persist(os.path.join(tempfile.gettempdir(), "lean_no_such_state_%d.json" % os.getpid()),
                {1: None})
cases.append((_bad._load_state()[1]["daily_vol"] == 0.0,
              "F3 restart: missing state file -> fresh (no crash)", "ok"))

# ---- DEFECT #3: SHADOW mode must advance the shot bookkeeping (a 'virtual shot') so shadow exercises the
# SAME cooldown/ramp/daily-cap state machine as live — otherwise minutes_since_shot is stuck at 1e9, shadow
# re-emits FIRE every tick, and the go-live parity gate never sees cadence/cap dynamics. Both live
# (_execute_shot) and the shadow FIRE branch now route through _advance_shot_counters; exercise it directly.
with tempfile.TemporaryDirectory() as _td3:
    _vs_path = os.path.join(_td3, "vstate.json")
    _vp = _Persist(_vs_path, {1: None})
    _vp.state = {1: _vp._fresh_zone()}
    # baseline: fresh zone has no shots, no last_shot (minutes_since_shot would be 1e9 in _snapshot)
    _before_shots = _vp.state[1]["shots"]
    _before_ls = _vp.state[1]["last_shot"]
    _vp._advance_shot_counters(1, 5.0)          # one virtual P2 shot, 5% of a 6 L substrate
    _s1 = _vp.state[1]
    cases.append((_before_shots == 0 and _before_ls is None
                  and _s1["shots"] == 1 and isinstance(_s1["last_shot"], datetime)
                  and abs(_s1["daily_vol"] - 0.30) < 1e-9,
                  "D3 shadow virtual-shot advances shots/last_shot/daily_vol",
                  f"shots={_s1['shots']} last_shot={_s1['last_shot'] is not None} daily_vol={_s1['daily_vol']}"))
    # a SECOND virtual shot accumulates the budget and bumps the count (cadence/cap now progress in shadow)
    _vp._advance_shot_counters(1, 5.0)
    _s2 = _vp.state[1]
    cases.append((_s2["shots"] == 2 and abs(_s2["daily_vol"] - 0.60) < 1e-9,
                  "D3 shadow virtual-shot accumulates (2 shots -> daily_vol grows)",
                  f"shots={_s2['shots']} daily_vol={_s2['daily_vol']}"))
    # and it PERSISTS (so a mid-shadow reload doesn't zero the shadow budget either)
    _vp_reload = _Persist(_vs_path, {1: None})
    _vr = _vp_reload._load_state()
    cases.append((_vr[1]["shots"] == 2 and abs(_vr[1]["daily_vol"] - 0.60) < 1e-9,
                  "D3 shadow virtual-shot bookkeeping persists across reload",
                  f"shots={_vr[1]['shots']} daily_vol={_vr[1]['daily_vol']}"))

# ---- FINDING #1 (IO-shell wiring): _grow_day_start + the new_grow_day boolean that decide() consumes.
# These are the shell-side pieces that turn "wall clock" into the pure new_grow_day flag. The pure decide()
# consequence is covered by the F1 cases above; here we prove the shell computes the flag correctly.
from datetime import date as _date, datetime as _dt

class _Clock:
    """Minimal carrier for the real _grow_day_start (needs only the two light-hour attrs)."""
    _grow_day_start = LeanCropSteering._grow_day_start
    def __init__(self, on, off):
        self.lights_on_hour, self.lights_off_hour = on, off

# day schedule on=10 off=22: before lights-on we're still in YESTERDAY's grow-day; at/after, today's.
_c = _Clock(10, 22)
cases.append((_c._grow_day_start(_dt(2026, 6, 19, 11, 0)) == _date(2026, 6, 19),
              "F1 grow_day_start: day-sched after lights-on -> today", str(_c._grow_day_start(_dt(2026, 6, 19, 11, 0)))))
cases.append((_c._grow_day_start(_dt(2026, 6, 19, 9, 0)) == _date(2026, 6, 18),
              "F1 grow_day_start: day-sched before lights-on -> yesterday", str(_c._grow_day_start(_dt(2026, 6, 19, 9, 0)))))
# overnight schedule on=18 off=6: the photoperiod running at 02:00 began at YESTERDAY's 18:00 lights-on.
_co = _Clock(18, 6)
cases.append((_co._grow_day_start(_dt(2026, 6, 19, 2, 0)) == _date(2026, 6, 18),
              "F1 grow_day_start: overnight-sched pre-dawn -> yesterday (photoperiod start)", str(_co._grow_day_start(_dt(2026, 6, 19, 2, 0)))))
cases.append((_co._grow_day_start(_dt(2026, 6, 19, 20, 0)) == _date(2026, 6, 19),
              "F1 grow_day_start: overnight-sched after lights-on -> today", str(_co._grow_day_start(_dt(2026, 6, 19, 20, 0)))))

# the new_grow_day formula the shell feeds decide(): lights_on AND (last_daily_reset is None OR < grow_day_start)
def _new_grow_day(lights_on, last_daily_reset, gds):
    return lights_on and (last_daily_reset is None or last_daily_reset < gds)
_gds = _date(2026, 6, 19)
cases.append((_new_grow_day(True, None, _gds) is True,
              "F1 new_grow_day: never-reset (None) while lights-on -> True", "ok"))
cases.append((_new_grow_day(True, _date(2026, 6, 18), _gds) is True,
              "F1 new_grow_day: yesterday's reset while lights-on -> True (stale budget)", "ok"))
cases.append((_new_grow_day(True, _date(2026, 6, 19), _gds) is False,
              "F1 new_grow_day: already reset today -> False (no re-reset)", "ok"))
cases.append((_new_grow_day(False, None, _gds) is False,
              "F1 new_grow_day: lights-off -> False regardless", "ok"))

# ---- FINDING #1 (end-to-end stamp): after _load_state restores a stale (yesterday) reset and decide()
# returns P0, the loop's P0 block stamps last_daily_reset = grow_day_start. Mirror that stamp + re-derive
# new_grow_day to prove it self-clears (no second reset within the same grow-day).
_stamped = _new_grow_day(True, _gds, _gds)   # after stamping last_daily_reset = grow_day_start
cases.append((_stamped is False,
              "F1 after P0 stamp -> new_grow_day clears (idempotent within grow-day)", "ok"))

# ---- FINDING #3 (IO-shell): the source-water EC gate FAILS CLOSED on a stale/unreadable feed probe
# (when bounds are configured), instead of skipping the check. Bind the real _blocked + its helpers onto a
# stand-in whose get_state() simulates HA. Only bites in LIVE mode, but a fail-OPEN safety gate is the bug.
class _Gate:
    """Carrier for the real _blocked/_read_feed_ec/_read_sensor/_num/_on against a scripted HA state map."""
    _blocked = LeanCropSteering._blocked
    _read_feed_ec = LeanCropSteering._read_feed_ec
    _read_sensor = LeanCropSteering._read_sensor
    _num = LeanCropSteering._num
    _on = LeanCropSteering._on
    def __init__(self, states, bounds=(0.0, 0.0), feed_attr=None,
                 last_good_value=None, last_good_time=None, feed_grace_min=30.0):
        # states: entity -> value; bounds: (ec_min, ec_max); feed_attr: last_changed iso for the feed probe
        self._states = dict(states)
        self._states["number.crop_steering_irrigation_ec_min"] = bounds[0]
        self._states["number.crop_steering_irrigation_ec_max"] = bounds[1]
        self._feed_attr = feed_attr
        # CHANGE 2 feed-tracking state the real _blocked/_read_feed_ec now read/update.
        self._feed_last_good_value = last_good_value
        self._feed_last_good_time = last_good_time
        self.feed_grace_min = feed_grace_min
    def get_state(self, entity, attribute=None):
        if attribute == "last_changed":
            return self._feed_attr if entity == "sensor.atlas_legacy_1_ec" else None
        return self._states.get(entity)
    def _alert(self, *a, **k):
        pass

# HA stores last_changed in UTC and AppDaemon hands it back tz-NAIVE; model that exactly (naive UTC, no
# offset) so the freshness math is exercised the way it runs on the +12 box. Using naive LOCAL here (the old
# harness) hid the timezone bug that blinded every probe.
def _ha_ts(mins_ago=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=mins_ago)).replace(tzinfo=None).isoformat()

# all upstream gates open; feed probe present + in band, bounds configured -> NOT blocked
_open = {"switch.crop_steering_system_enabled": "on", "switch.crop_steering_auto_irrigation_enabled": "on",
         "switch.crop_steering_zone_1_enabled": "on", "switch.crop_steering_zone_1_manual_override": "off",
         "input_boolean.nutrient_dosing_active": "off", "input_boolean.f2_fill_mode": "off",
         "input_boolean.f2_flush_mode": "off", "switch.tank_filling": "off",
         "sensor.atlas_legacy_1_ec": "2.5"}
_g_ok = _Gate(_open, bounds=(1.0, 6.0), feed_attr=_ha_ts())
cases.append((_g_ok._blocked(1) is None,
              "F3 gate: fresh in-band feed + bounds -> not blocked", f"{_g_ok._blocked(1)!r}"))

# feed probe UNAVAILABLE (None) while bounds are configured AND no last-known-good -> MUST block (fail closed)
_unavail = dict(_open); _unavail["sensor.atlas_legacy_1_ec"] = "unavailable"
_g_unavail = _Gate(_unavail, bounds=(1.0, 6.0))   # last_good_time defaults None -> nothing to ride on
_rb = _g_unavail._blocked(1)
cases.append((_rb is not None and "holding" in _rb,
              "F3 gate: unavailable feed + bounds + no last-good -> BLOCK (fail closed)", f"{_rb!r}"))

# feed probe STALE (last_changed > 20min) while bounds are configured AND no last-good -> MUST block (fail closed)
_g_stale = _Gate(_open, bounds=(1.0, 6.0), feed_attr=_ha_ts(45))
_rs = _g_stale._blocked(1)
cases.append((_rs is not None and "holding" in _rs,
              "F3 gate: stale feed (>20min) + bounds + no last-good -> BLOCK (fail closed)", f"{_rs!r}"))

# NO bounds configured (min=max=0) + unreadable feed -> gate is DISARMED, must NOT block on feed
# (preserves prior behaviour: source-water check is opt-in via the bound entities).
_g_nobounds = _Gate(_unavail, bounds=(0.0, 0.0))
cases.append((_g_nobounds._blocked(1) is None,
              "F3 gate: no bounds + unreadable feed -> not blocked (gate disarmed)", f"{_g_nobounds._blocked(1)!r}"))

# feed present but OUT of band -> the original out-of-range block still fires
_oob = dict(_open); _oob["sensor.atlas_legacy_1_ec"] = "8.0"
_g_oob = _Gate(_oob, bounds=(1.0, 6.0), feed_attr=_ha_ts())
_ro = _g_oob._blocked(1)
cases.append((_ro is not None and "out of" in _ro,
              "F3 gate: in-range bounds, feed too high -> out-of-range block", f"{_ro!r}"))

# ============================================================
# CHANGE 1 — dead-VWC-probe zone COPIES a healthy sibling (pure pick_sibling helper)
# ============================================================
# pick_sibling: the recipe-closest healthy zone (nearest p1_target) wins.
cases.append((pick_sibling(60, [(1, 55), (2, 62), (3, 75)]) == 2,
              "C1 pick_sibling: closest p1_target wins", str(pick_sibling(60, [(1, 55), (2, 62), (3, 75)]))))
# exact tie on distance -> LOWEST zone number breaks it. Blind target 60; zone 1 (=55, dist 5) and
# zone 3 (=65, dist 5) tie -> zone 1.
cases.append((pick_sibling(60, [(3, 65), (1, 55), (2, 80)]) == 1,
              "C1 pick_sibling: exact tie -> lowest zone number", str(pick_sibling(60, [(3, 65), (1, 55), (2, 80)]))))
# a single healthy zone is always the choice (whatever its target).
cases.append((pick_sibling(60, [(2, 99)]) == 2,
              "C1 pick_sibling: single healthy zone -> that one", str(pick_sibling(60, [(2, 99)]))))
# no healthy zones -> None (loop falls back to the safe schedule instead of copying).
cases.append((pick_sibling(60, []) is None,
              "C1 pick_sibling: no healthy zones -> None", str(pick_sibling(60, []))))
# exact-match target beats a near one (dist 0).
cases.append((pick_sibling(50, [(1, 48), (2, 50), (3, 52)]) == 2,
              "C1 pick_sibling: exact target match wins (dist 0)", str(pick_sibling(50, [(1, 48), (2, 50), (3, 52)]))))

# ---- CHANGE 1 (resolution semantics): a blind zone COPIES the sibling's (fire,size) verbatim; if NO
# zone is healthy it runs the fallback top-up gated on the fallback interval. Mirror the loop's PASS-2
# logic over a tiny decisions map to prove WHEN+HOW-MUCH are borrowed and the reason strings are tagged.
def _resolve_blind(blind_p1, healthy, decisions, mss, p2_shot, fallback_min):
    """Mirror of loop() PASS 2 for a single blind zone (pure, for the test)."""
    if healthy:
        sib = pick_sibling(blind_p1, healthy)
        s_fire, s_size, _ = decisions[sib]
        return (s_fire, s_size, f"COPY Z{sib} (VWC probe dead)")
    return (mss >= fallback_min, p2_shot, "FALLBACK schedule (no live probe)")

# sibling FIRING -> blind zone copies fire=True and the sibling's size; reason tags the sibling.
_cb1 = _resolve_blind(60, [(2, 62), (3, 75)], {2: (True, 7.5, "P2 top-up"), 3: (False, 0.0, "hold")}, 5, 5.0, 90)
cases.append((_cb1[0] is True and _cb1[1] == 7.5 and _cb1[2] == "COPY Z2 (VWC probe dead)",
              "C1 blind copies a FIRING sibling's (fire,size)", f"{_cb1}"))
# sibling HOLDING -> blind zone copies fire=False too (it mirrors WHEN, including 'not now').
_cb2 = _resolve_blind(60, [(2, 62)], {2: (False, 0.0, "P2 hold")}, 5, 5.0, 90)
cases.append((_cb2[0] is False and _cb2[2] == "COPY Z2 (VWC probe dead)",
              "C1 blind copies a HOLDING sibling (mirrors 'not now')", f"{_cb2}"))
# EVERY zone blind, last shot recent (< fallback) -> fallback HOLDS.
_cb3 = _resolve_blind(60, [], {}, 30, 5.0, 90)
cases.append((_cb3[0] is False and _cb3[1] == 5.0 and _cb3[2] == "FALLBACK schedule (no live probe)",
              "C1 all-blind fallback holds before the interval", f"{_cb3}"))
# EVERY zone blind, last shot older than fallback interval -> fallback FIRES a p2_shot_size top-up.
_cb4 = _resolve_blind(60, [], {}, 120, 5.0, 90)
cases.append((_cb4[0] is True and _cb4[1] == 5.0 and _cb4[2] == "FALLBACK schedule (no live probe)",
              "C1 all-blind fallback fires after the interval (p2_shot_size)", f"{_cb4}"))

# ============================================================
# CHANGE 2 — dead/stale shared FEED probe runs on last-known-good within grace, holds past it
# ============================================================
# feed_grace_ok (pure, epoch-seconds floats):
_now_ts = _dt(2026, 6, 19, 12, 0, 0).timestamp()
cases.append((feed_grace_ok(_now_ts, _now_ts - 10 * 60, 30) is True,
              "C2 feed_grace_ok: 10min-old good reading within 30min grace -> True", "ok"))
cases.append((feed_grace_ok(_now_ts, _now_ts - 45 * 60, 30) is False,
              "C2 feed_grace_ok: 45min-old good reading past 30min grace -> False", "ok"))
cases.append((feed_grace_ok(_now_ts, None, 30) is False,
              "C2 feed_grace_ok: never-good (None) -> False", "ok"))
# boundary: exactly at grace is NOT within (strict <) -> False
cases.append((feed_grace_ok(_now_ts, _now_ts - 30 * 60, 30) is False,
              "C2 feed_grace_ok: exactly at grace edge -> False (strict)", "ok"))

# ---- CHANGE 2 (_blocked): live feed dead but a FRESH last-known-good exists -> run on it (NOT blocked).
_g_lkg = _Gate(_unavail, bounds=(1.0, 6.0),
               last_good_value=3.2, last_good_time=_dt.now() - __import__("datetime").timedelta(minutes=10))
cases.append((_g_lkg._blocked(1) is None,
              "C2 gate: dead feed + fresh last-known-good (10min) -> run on last-good (not blocked)",
              f"{_g_lkg._blocked(1)!r}"))
# ---- live feed dead AND last-known-good is STALE (past grace) -> fail closed (block).
_g_lkg_stale = _Gate(_unavail, bounds=(1.0, 6.0),
                     last_good_value=3.2, last_good_time=_dt.now() - __import__("datetime").timedelta(minutes=45))
_rl = _g_lkg_stale._blocked(1)
cases.append((_rl is not None and "holding" in _rl,
              "C2 gate: dead feed + STALE last-known-good (45min) -> BLOCK (fail closed)", f"{_rl!r}"))
# ---- _read_feed_ec STAMPS last-known-good when the live read is a number IN band.
_g_stamp = _Gate(_open, bounds=(1.0, 6.0), feed_attr=_ha_ts())   # live feed 2.5, in [1,6]
_before_t = _g_stamp._feed_last_good_time
_seen = _g_stamp._read_feed_ec()
cases.append((_seen == 2.5 and _before_t is None and _g_stamp._feed_last_good_value == 2.5
              and _g_stamp._feed_last_good_time is not None,
              "C2 _read_feed_ec: in-band live read stamps last-known-good", f"seen={_seen} lkg={_g_stamp._feed_last_good_value}"))
# ---- _read_feed_ec does NOT stamp an OUT-of-band live read (that's bad water, not a 'good' reading).
_g_nostamp = _Gate(_oob, bounds=(1.0, 6.0), feed_attr=_ha_ts())   # live feed 8.0, > hi 6
_seen2 = _g_nostamp._read_feed_ec()
cases.append((_seen2 == 8.0 and _g_nostamp._feed_last_good_value is None,
              "C2 _read_feed_ec: out-of-band live read does NOT stamp last-known-good",
              f"seen={_seen2} lkg={_g_nostamp._feed_last_good_value}"))
# ---- with NO bounds configured the gate is disarmed, so any numeric read is 'good' and gets stamped.
_g_nobounds_stamp = _Gate(_oob, bounds=(0.0, 0.0), feed_attr=_ha_ts())
_seen3 = _g_nobounds_stamp._read_feed_ec()
cases.append((_seen3 == 8.0 and _g_nobounds_stamp._feed_last_good_value == 8.0,
              "C2 _read_feed_ec: no bounds -> any numeric read stamps last-good", f"lkg={_g_nobounds_stamp._feed_last_good_value}"))

# ============================================================
# TIMEZONE REGRESSION — _read_sensor freshness must treat HA's tz-naive UTC last_changed AS UTC, not as
# naive-local. The live bug: on a UTC+12 box a FRESH probe (last_changed = now-in-UTC = 01:08 while local
# clock is 13:08) computed a 12 h age -> every zone read blind -> whole engine fell back. Bind the real
# _read_sensor onto a stub and assert fresh-accepted / stale-rejected across naive-UTC and aware-UTC.
# ============================================================
class _RS:
    _read_sensor = LeanCropSteering._read_sensor
    def __init__(self, value, last_changed):
        self._v, self._lc = value, last_changed
    def get_state(self, entity, attribute=None):
        return self._lc if attribute == "last_changed" else self._v

cases.append((_RS(45.0, _ha_ts(0))._read_sensor("sensor.x", lo=0, hi=100) == 45.0,
              "TZ _read_sensor: fresh naive-UTC last_changed ACCEPTED (the bug false-blinded it)",
              str(_RS(45.0, _ha_ts(0))._read_sensor("sensor.x", lo=0, hi=100))))
cases.append((_RS(45.0, _ha_ts(45))._read_sensor("sensor.x", lo=0, hi=100, max_age_min=20) is None,
              "TZ _read_sensor: genuinely 45-min-old probe still rejected (freshness intact)",
              str(_RS(45.0, _ha_ts(45))._read_sensor("sensor.x", lo=0, hi=100, max_age_min=20))))
cases.append((_RS(45.0, datetime.now(timezone.utc).isoformat())._read_sensor("sensor.x", lo=0, hi=100) == 45.0,
              "TZ _read_sensor: fresh aware-UTC (+00:00) last_changed accepted", "ok"))

# ============================================================
# STATUS REPUBLISH helpers — vocabulary MUST stay byte-identical to master_crop_steering_app.
# The f2 + native dashboards and the engine-error / stranded-P3 watchdog automations key off these
# exact strings; a drift here is a SILENTLY broken alarm the moment lean takes over from master.
# zone_safety_status mirrors master._update_safety_status_entities (lines ~7467-7475).
# ============================================================
# fc=70, max_ec=9 throughout
cases.append((zone_safety_status(72, 3.0, 70, 9) == "over_saturated",
              "STATUS zone_safety: vwc>=field_capacity -> over_saturated", zone_safety_status(72, 3.0, 70, 9)))
cases.append((zone_safety_status(50, 9.5, 70, 9) == "ec_limit_exceeded",
              "STATUS zone_safety: ec>=max_ec -> ec_limit_exceeded", zone_safety_status(50, 9.5, 70, 9)))
# the hard limits outrank the 'approaching' bands: saturated wins even when EC is also over.
cases.append((zone_safety_status(72, 10.0, 70, 9) == "over_saturated",
              "STATUS zone_safety: saturated outranks ec ceiling", zone_safety_status(72, 10.0, 70, 9)))
cases.append((zone_safety_status(66, 3.0, 70, 9) == "approaching_saturation",
              "STATUS zone_safety: within 5% of fc -> approaching_saturation", zone_safety_status(66, 3.0, 70, 9)))
cases.append((zone_safety_status(50, 8.5, 70, 9) == "approaching_ec_limit",
              "STATUS zone_safety: within 1 of max_ec -> approaching_ec_limit", zone_safety_status(50, 8.5, 70, 9)))
cases.append((zone_safety_status(50, 3.0, 70, 9) == "safe",
              "STATUS zone_safety: mid-range -> safe", zone_safety_status(50, 3.0, 70, 9)))
# a blind probe (vwc/ec None) is not assessable -> safe (a dead probe must not raise a false safety alarm).
cases.append((zone_safety_status(None, None, 70, 9) == "safe",
              "STATUS zone_safety: blind (None,None) -> safe", zone_safety_status(None, None, 70, 9)))
cases.append((zone_safety_status(None, 9.5, 70, 9) == "ec_limit_exceeded",
              "STATUS zone_safety: vwc dead but ec over -> ec_limit_exceeded", zone_safety_status(None, 9.5, 70, 9)))

# system roll-up: master = unsafe if any over_sat/ec_exceeded; else warning if any approaching; else safe.
cases.append((system_safety_status(["safe", "safe", "safe"]) == ("safe", 0, 0, 3),
              "STATUS system_safety: all safe -> safe,0,0,3", str(system_safety_status(["safe", "safe", "safe"]))))
cases.append((system_safety_status(["safe", "approaching_ec_limit", "safe"]) == ("warning", 0, 1, 2),
              "STATUS system_safety: one approaching -> warning,0,1,2",
              str(system_safety_status(["safe", "approaching_ec_limit", "safe"]))))
cases.append((system_safety_status(["ec_limit_exceeded", "approaching_saturation", "safe"]) == ("unsafe", 1, 1, 1),
              "STATUS system_safety: one unsafe outranks warning -> unsafe,1,1,1",
              str(system_safety_status(["ec_limit_exceeded", "approaching_saturation", "safe"]))))
cases.append((system_safety_status([]) == ("safe", 0, 0, 0),
              "STATUS system_safety: no zones -> safe,0,0,0", str(system_safety_status([]))))

# zone_status_label — the human tile string (demo shows 'Optimal' for a steady P2 zone).
cases.append((zone_status_label("P2", False, None, False, "P2 hold") == "Optimal",
              "STATUS zone_label: steady P2 -> Optimal (matches f2 demo)", zone_status_label("P2", False, None, False, "P2 hold")))
cases.append((zone_status_label("P2", True, None, False, "P2 top-up") == "Topping up",
              "STATUS zone_label: P2 firing -> Topping up", zone_status_label("P2", True, None, False, "P2 top-up")))
cases.append((zone_status_label("P1", True, None, False, "P1 ramp") == "Refilling",
              "STATUS zone_label: P1 firing -> Refilling", zone_status_label("P1", True, None, False, "P1 ramp")))
cases.append((zone_status_label("P0", False, None, False, "") == "Drying back",
              "STATUS zone_label: P0 holding -> Drying back", zone_status_label("P0", False, None, False, "")))
cases.append((zone_status_label("P2", False, None, True, "COPY Z1") == "Probe dead — copying",
              "STATUS zone_label: blind -> Probe dead", zone_status_label("P2", False, None, True, "COPY Z1")))
cases.append((zone_status_label("P2", False, "manual override", False, "").startswith("Blocked:"),
              "STATUS zone_label: live gate -> Blocked:", zone_status_label("P2", False, "manual override", False, "")))
cases.append((zone_status_label("P2", False, None, False, "BLOCK high EC 10.5 — feed not dilutive") == "Blocked — EC/cap",
              "STATUS zone_label: decide-level BLOCK -> Blocked — EC/cap", zone_status_label("P2", False, None, False, "BLOCK")))

# ============================================================
# STATUS REPUBLISH — the IO method _publish_status. Bind the real method onto a stand-in that captures
# set_state, and assert the master CONTRACT: the actuate gate (no writes in shadow), master-identical
# state strings, AND the attribute KEYS the consumers read (activity_log.feed — the one the review caught).
# ============================================================
class _Pub:
    """Carrier for the real _publish_status, capturing every set_state(entity)->(state,attrs)."""
    _publish_status = LeanCropSteering._publish_status
    def __init__(self):
        self.calls = {}
        self._busy = False
        self._activity = []
        self.state = {1: {"last_shot": None}, 2: {"last_shot": _dt(2026, 6, 19, 11, 0)}, 3: {"last_shot": None}}
    def set_state(self, eid, state=None, attributes=None):
        self.calls[eid] = (state, attributes or {})
    def _on(self, e, d=False):
        return True
    def log(self, *a, **k):
        pass

_pub_now = _dt(2026, 6, 19, 12, 0, 0)
_pub_in = {
    1: {"phase": "P2", "vwc": 57, "ec": 3.0, "fire": False, "block": None, "reason": "P2 hold", "blind": False, "p": P()},
    2: {"phase": "P1", "vwc": 50, "ec": 5.0, "fire": True, "block": None, "reason": "P1 ramp", "blind": False, "p": P()},
    3: {"phase": "P2", "vwc": 72, "ec": 9.6, "fire": True,
        "block": "source-water EC dead >30min — holding (fail-closed)", "reason": "P2 top-up", "blind": False, "p": P()},
}
# SHADOW (actuate False) must publish NOTHING — master still owns these entities.
_ps = _Pub(); _ps._publish_status(_pub_in, False, _pub_now)
cases.append((_ps.calls == {}, "STATUS publish: SHADOW gate emits nothing", f"{len(_ps.calls)} writes"))
# LIVE publishes the master surface with master vocabulary.
_pl = _Pub(); _pl._publish_status(_pub_in, True, _pub_now)
cases.append((_pl.calls.get("sensor.crop_steering_system_safety_status", (None,))[0] == "unsafe",
              "STATUS publish: system_safety unsafe (z3 over_saturated)",
              str(_pl.calls.get("sensor.crop_steering_system_safety_status"))))
cases.append((_pl.calls.get("sensor.crop_steering_app_status", (None,))[0] == "error",
              "STATUS publish: app_status=error on room fail-closed hold",
              str(_pl.calls.get("sensor.crop_steering_app_status"))))
cases.append((_pl.calls.get("sensor.crop_steering_app_current_phase", (None,))[0] == "Z1:P2, Z2:P1, Z3:P2",
              "STATUS publish: app_current_phase summary", str(_pl.calls.get("sensor.crop_steering_app_current_phase"))))
# DEFECT-1 GUARD: the activity feed MUST be the 'feed' attribute (master contract; f2 reads attributes.feed).
_alog = _pl.calls.get("sensor.crop_steering_activity_log", (None, {}))
cases.append(("feed" in _alog[1] and "log" not in _alog[1],
              "STATUS publish: activity_log uses master's 'feed' attribute (not 'log')", str(sorted(_alog[1].keys()))))
# last_irrigation_app republished from last_shot where present (z2), absent where None (z1/z3).
cases.append((_pl.calls.get("sensor.crop_steering_zone_2_last_irrigation_app", (None,))[0] == _dt(2026, 6, 19, 11, 0).isoformat()
              and "sensor.crop_steering_zone_1_last_irrigation_app" not in _pl.calls,
              "STATUS publish: last_irrigation_app from last_shot (present z2, absent z1)",
              str(_pl.calls.get("sensor.crop_steering_zone_2_last_irrigation_app"))))

passed = sum(1 for ok, *_ in cases if ok)
for ok, name, detail in cases:
    print(("PASS  " if ok else "FAIL  ") + name.ljust(34) + "| " + detail)
print(f"\n{passed}/{len(cases)} passed")
sys.exit(0 if passed == len(cases) else 1)
