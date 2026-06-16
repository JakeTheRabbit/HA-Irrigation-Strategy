"""Pure-function unit harness for lean_crop_steering.decide(). No HA / AppDaemon needed.
Run from this directory: python test_lean_decide.py"""
import sys
from lean_crop_steering import decide, ZoneParams, ZoneSnapshot, ec_adjust


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
case("P1 -> P2 recovered", S(phase="P1", vwc=61), P(), want_phase="P2")
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
case("max-EC blocks P1 normal shot", S(phase="P1", vwc=50, ec=9.5, minutes_since_shot=20), P(max_ec=9), want_fire=False)
case("daily cap blocks", S(phase="P2", vwc=40, daily_vol=300, ec=6, ec_smooth=6), P(max_daily_volume=300), want_fire=False)

# ---- EC steering (threshold direction) ----
_, thr_lo, *_ = decide(S(phase="P2", ec_smooth=4, vwc=55), P(stacking_on=True, ec_target_p2=6, p2_threshold=45))
cases.append((thr_lo < 45, "EC steer: low EC -> threshold DOWN", f"thr={thr_lo}"))
_, thr_hi, *_ = decide(S(phase="P2", ec_smooth=8, vwc=55), P(stacking_on=True, ec_target_p2=6, p2_threshold=45))
cases.append((thr_hi > 45, "EC steer: high EC -> threshold UP", f"thr={thr_hi}"))

# ---- ec_adjust ----
cases.append((ec_adjust(5, 9, 6) == 7.5, "ec_adjust dilute 1.5x", str(ec_adjust(5, 9, 6))))
cases.append((ec_adjust(5, 2, 6) == 2.5, "ec_adjust conserve 0.5x", str(ec_adjust(5, 2, 6))))

passed = sum(1 for ok, *_ in cases if ok)
for ok, name, detail in cases:
    print(("PASS  " if ok else "FAIL  ") + name.ljust(34) + "| " + detail)
print(f"\n{passed}/{len(cases)} passed")
sys.exit(0 if passed == len(cases) else 1)
