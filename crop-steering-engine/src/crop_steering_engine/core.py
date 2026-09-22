# -*- coding: utf-8 -*-
"""crop_steering_engine.core — the PURE crop-steering decision core.

No Home Assistant, no I/O. A plain function over two dataclasses, unit-testable
offline, so it can run identically inside the f2-control add-on, a standalone
service, a worker, or a test — the host no longer matters.
"""
import dataclasses
import math
from dataclasses import dataclass

PHASES = ("P0", "P1", "P2", "P3")

# Minutes after a shot ends before a pore-EC reading counts as SETTLED. For the first half hour or so
# after a shot the probe reads the fresh feed front and the free water still draining, not the slab
# (live F2 2026-09-22: 6-8 mS/cm during the morning ramp on zones whose quiet readings were ~4.5).
# The controller takes a settled reading only this long after the last shot, and an EC correction that
# acts on one waits the same time, so each correction is judged by a reading taken after the last drained.
EC_SETTLE_MIN = 45.0


class Reason(str):
    """decide()'s reason: still exactly the text it always was (logged, published, compared as a
    string), plus WHICH rule produced it (`kind`) and whether that shot may exceed the zone's daily
    budget (`cap_exempt`). Anything that only ever used the text is unaffected."""

    def __new__(cls, text="", kind="idle", cap_exempt=False):
        obj = super().__new__(cls, text)
        obj.kind = kind
        obj.cap_exempt = bool(cap_exempt)
        return obj


# Which shots may take a zone over its daily budget. The budget is a BUDGET, not a wall: routine and
# EC-correction shots stop at it, rescues do not. P1 ramp shots are exempt because the ramp runs in full
# and in order, whatever it is set to: it is bounded by p1_maximum_shots and its shot size, not the budget.
# Kinds that never fire: idle (nothing due), block_high_ec, hold_high_ec, block_daily_cap.
CAP_EXEMPT = {
    "flush_high_ec": True,  # anti-lockout: pore EC at max_ec
    "p0_ec_flush": False,
    "p1_ramp": True,
    "p1_flush": False,  # the ramp is at its ceiling; only EC is keeping P1 open
    "p2_rescue": True,  # pore EC within 1 of max_ec
    "p2_dilute": False,
    "p2_topup": False,
    "p3_emergency": True,
    "watchdog": True,
    "min_daily": False,  # never over the budget by construction: min_daily_volume <= max_daily_volume
}


# ============================================================
# PURE DECISION CORE  (no HA, no IO -> unit-testable)
# ============================================================
@dataclass
class ZoneParams:
    p1_target: float            # P1 ramp ceiling (= WC% max)
    p2_threshold: float         # P2 re-water floor (= WC% min, EC-steered)
    p2_shot_size: float
    p1_initial: float
    p1_incr: float
    p1_max_shots: int
    p1_time_between_min: float
    dryback_target: float       # P0 morning dryback %, also the overnight target
    p0_max_wait_min: float
    ec_target_p0: float
    ec_target_p1: float
    ec_target_p2: float
    p3_emergency_floor: float
    p3_emergency_shot: float
    max_daily_volume: float
    field_capacity: float
    max_ec: float
    stacking_on: bool
    watchdog_hours: float = 3.0   # lights-on "no zone starves" backstop (0 = off)
    p2_min_interval_min: float = 10.0   # min minutes between EC-correction shots (flush/dilute/rescue) —
    #                                     anti short-cycle: a no-runoff nibble every tick STACKS EC instead
    #                                     of diluting it (the pump-cycling failure mode). Let each shot drain
    #                                     + re-read before the next. VWC top-ups stay ungated (self-limiting).
    min_daily_volume: float = 0.0   # MIN litres/zone/day floor during lights-on (per-plant water safety; 0 = off).
    #                                 GUARANTEED + FRONT-STACKED + SENSOR-INDEPENDENT: every plant gets this much,
    #                                 delivered from lights-on as fast as spacing allows, regardless of the VWC
    #                                 threshold — a lying/dead probe cannot suppress it. Clamped < max_daily_volume.
    p1_min_shots: int = 0           # P1 cannot graduate on "target reached" until this many ramp shots have
    #                                 landed (0 = off). The ramp runs as configured; max shots still bounds it.
    drown_ceiling: float = 90.0     # the ONLY VWC gate on the min-daily floor: a hard anti-drown limit well above
    #                                 field capacity. Below it, the floor fires regardless of the probe; at/above it
    #                                 the floor holds (never flood). 90 ~= unreachable in coco -> truly probe-blind.


@dataclass
class ZoneSnapshot:
    vwc: float
    ec: float | None            # None = unavailable/stale; never substitute a low reading
    phase: str                  # 'P0'..'P3'
    peak_vwc: float
    dryback_pct: float
    dryback_rate: float         # %/h
    shot_count: int
    phase_minutes: float
    minutes_since_shot: float
    daily_vol: float
    ec_smooth: float | None
    lights_on: bool
    lights_just_on: bool
    hours_to_lights_on: float
    hours_to_lights_off: float
    uptime_min: float
    feed_ec: float = 3.0          # source-water (tank) EC — for the anti-lockout dilutive-flush test
    new_grow_day: bool = False    # wall-clock fallback: True when in the lights-on window AND the daily
    #                               budget has NOT yet been reset for THIS grow-day (photoperiod).
    ec_settled: float | None = None  # pore EC read >= EC_SETTLE_MIN after the last shot (or the last such
    #                                  reading, held while shots come closer together). When given, EVERY
    #                                  EC rule uses it instead of `ec`; None = fall back to `ec` as before.


def ec_adjust(size: float, ec: float | None, target: float) -> float:
    """Scale a shot by pore-EC vs target: high EC -> bigger (dilute), low EC -> smaller (conserve)."""
    if ec is None or not math.isfinite(ec) or target <= 0:
        return size
    r = ec / target
    if r > 1.5:
        return size * 2.0
    if r > 1.2:
        return size * 1.5
    if r > 1.0:
        return size * 1.2
    if r < 0.5:
        return size * 0.5
    if r < 0.8:
        return size * 0.7
    return size


def ec_pid(ec_smooth, ec_target, base_threshold, integral, prev_error, gains, clamp_frac=0.20):
    """PURE PID on pore-EC error -> a P2-threshold offset (VWC %). Optional, flag-gated upgrade
    to the stepped EC-steer (ec_offset). error = ec_smooth - ec_target:
      EC too HIGH  -> positive offset -> threshold up -> water sooner -> dilute (EC down)
      EC too LOW   -> negative offset -> threshold down -> deeper dryback -> stack (EC up)
    gains = (kp, ki, kd), evaluated per tick (dt folded into the gains). The output and the integral
    are both clamped to +/- clamp_frac*base_threshold (anti-windup). Returns (offset, new_integral, error)."""
    kp, ki, kd = gains
    error = ec_smooth - ec_target
    integral = integral + error
    lim = clamp_frac * base_threshold
    if ki > 0:                                   # anti-windup: hold the I-term inside the output band
        integral = max(-lim / ki, min(lim / ki, integral))
    out = kp * error + ki * integral + kd * (error - prev_error)
    out = max(-lim, min(lim, out))
    return round(out, 2), integral, error


def decide(s: ZoneSnapshot, p: ZoneParams):
    """PURE control step. Returns (new_phase, new_p2_threshold, fire, size, reason).

    Mirrors the distilled algorithm: phase transition -> EC steering (P2) ->
    irrigation decision -> the cap/EC safety subset. Gate checks that need live HA
    (dosing interlock, source-water, zone-enable) are applied in the IO shell.

    `reason` is a Reason: the same text as always, plus `.kind` (the rule that produced it) and
    `.cap_exempt` (whether this shot may exceed the daily budget; see CAP_EXEMPT).
    """
    phase = s.phase
    p2_thr = p.p2_threshold
    treason = ""
    # Every EC rule reads the SETTLED pore EC when the caller supplies one (see EC_SETTLE_MIN): a raw
    # reading taken minutes after a shot is the feed front passing the probe, not the slab.
    settled = s.ec_settled is not None and math.isfinite(s.ec_settled)
    ec = s.ec_settled if settled else s.ec
    ec_known = ec is not None and math.isfinite(ec)

    # ---- PHASE TRANSITIONS (checked before irrigation) ----
    if not s.lights_on and phase != "P3":
        phase, treason = "P3", "lights-off -> P3"
    elif phase == "P3" and (s.lights_just_on or (s.lights_on and s.new_grow_day)):
        why = "lights-on -> P0" if s.lights_just_on else "new grow-day -> P0 (missed light edge)"
        phase, treason = "P0", why
    elif phase in ("P1", "P2") and s.lights_on and s.new_grow_day:
        # Still in yesterday's daytime phases when a new photoperiod has begun (the controller was not
        # running across lights-off, or the schedule moved): today starts at P0 with its own budget and
        # counters, instead of carrying yesterday's spent budget through the whole day.
        phase, treason = "P0", "new grow-day -> P0 (reset)"
    elif phase == "P0":
        if s.vwc <= p.p2_threshold:
            phase, treason = "P1", f"P0 bypass VWC {s.vwc:.0f}<=rewater {p.p2_threshold:.0f}"
        elif s.dryback_pct >= p.dryback_target:
            phase, treason = "P1", f"P0 dryback done {s.dryback_pct:.0f}%"
        elif s.phase_minutes >= p.p0_max_wait_min:
            phase, treason = "P1", f"P0 timeout {s.phase_minutes:.0f}min"
    elif phase == "P1":
        # Ramp to the ACHIEVABLE ceiling, graduate once pore EC is flushed back to band.
        p1_ceiling = min(p.p1_target, p.field_capacity)
        # P1 is the ramp AS CONFIGURED and ends only when the ramp is complete: target reached (with the
        # minimum shots in) or the maximum shots delivered. There is deliberately NO time-based exit - a
        # zone gate-blocked before or during the ramp (feed pH/EC, dosing hold) waits in P1 and resumes;
        # phases always run in order. Lights-off -> P3 (above) is the only other way out.
        min_in = s.shot_count >= p.p1_min_shots
        if s.vwc >= p1_ceiling and ec_known and ec <= p.ec_target_p1 * 1.15 and min_in:
            phase, treason = "P2", f"P1 recovered {s.vwc:.0f}>={p1_ceiling:.0f} EC ok {ec:.1f}"
        elif not ec_known and s.vwc >= p1_ceiling and s.shot_count > 0 and min_in:
            # Do not claim EC recovery or keep watering an already-full slab blindly.
            phase, treason = "P2", "P1 VWC recovered after watering; EC unknown (flush unverified)"
        elif s.shot_count >= p.p1_max_shots:
            phase, treason = "P2", f"P1 max shots {s.shot_count}/{p.p1_max_shots}"
        elif s.vwc >= p1_ceiling and min_in and s.daily_vol >= p.max_daily_volume:
            # The ramp is complete and only pore EC holds P1 open, but the flush it wants is not exempt
            # from the daily budget, which is spent: staying would hold the zone here with nothing to fire.
            phase, treason = "P2", "P1 complete at ceiling; EC flush over daily budget"
    elif phase == "P2":
        # predictive P3: only if starting dryback NOW would finish by lights-on.
        if s.uptime_min >= 10 and s.vwc >= p.p3_emergency_floor and s.hours_to_lights_off <= 3.0:
            rate = s.dryback_rate if (s.dryback_rate and s.dryback_rate > 0) else 0.1
            # Target is relative % of detected peak; measured rate is VWC
            # percentage points/hour. Predict only the still-needed point drop.
            target_vwc = s.peak_vwc * (1.0 - p.dryback_target / 100.0)
            remaining_points = max(0.0, s.vwc - target_vwc)
            hours_needed = remaining_points / rate if s.peak_vwc > 0 else float("inf")
            if hours_needed <= 12 and s.hours_to_lights_on <= hours_needed:
                phase, treason = "P3", f"predictive P3 (need {hours_needed:.1f}h, {s.hours_to_lights_on:.1f}h to on)"

    # ---- EC STEERING (P2) ----
    # The IO shell (f2-control add-on) owns the P2 EC-steer: it accumulates a PID/step
    # ec_offset (anti-windup, persisted, flag-gated) and bakes it into p.p2_threshold
    # BEFORE calling decide(). Applying a second ec_smooth-based nudge here would
    # double-correct the operator's tuned offset, so p2_thr just tracks that offset
    # threshold. (clamped lo/hi inside the shell.)

    # ---- IRRIGATION DECISION (priority order) ----
    fire, size, ir, kind = False, 0.0, "", "idle"

    # anti short-cycle: an EC-correction shot must drain + re-read before the next, else small no-runoff
    # shots STACK EC instead of diluting it (the pump-cycling-every-minute failure mode seen live).
    # Judged on a SETTLED reading it also waits for the next settled one: a held value cannot see what the
    # last correction did, and re-firing on it would flush every few minutes for ever.
    ec_gap = max(p.p2_min_interval_min, EC_SETTLE_MIN) if settled else p.p2_min_interval_min
    ec_gap_ok = s.minutes_since_shot >= ec_gap
    settle_ok = not settled or s.minutes_since_shot >= EC_SETTLE_MIN
    # an EC correction also needs water that can dilute: feed below pore EC, and room left in the slab
    flush_ok = ec_known and s.feed_ec < ec and s.vwc < p.field_capacity - 2.0

    # PRIORITY 1 — ANTI-LOCKOUT: high pore EC FLUSHES in ANY phase, never locks out.
    if ec_known and ec >= p.max_ec:
        if not flush_ok:
            why = "feed not dilutive" if s.feed_ec >= ec else "slab saturated"
            reason = treason + (" | " if treason else "") + f"BLOCK high EC {ec:.1f} — {why} (self-clears)"
            return phase, round(p2_thr, 1), False, 0.0, Reason(reason, "block_high_ec")
        if ec_gap_ok:
            excess = max(ec - p.max_ec, 0.0)
            size = p.p2_shot_size * (1.5 + min(excess, 3.0) * 0.3)
            fire, ir, kind = True, f"FLUSH high EC {ec:.1f}>={p.max_ec:.1f} (anti-lockout)", "flush_high_ec"
        else:
            # over the ceiling but a flush just fired — hold this tick so it can drain (no machine-gun, no normal shot)
            reason = treason + (" | " if treason else "") + f"HOLD high EC {ec:.1f} — flush draining ({s.minutes_since_shot:.0f}/{ec_gap:.0f}min)"
            return phase, round(p2_thr, 1), False, 0.0, Reason(reason, "hold_high_ec")

    # PRIORITY 2 — normal per-phase rules
    if not fire:
        if phase == "P0":
            # P0 is the morning dryback: it fires only a genuine EC flush, gated like every other flush.
            if (ec_known and p.ec_target_p0 > 0 and ec / p.ec_target_p0 > 2.5
                    and flush_ok and ec_gap_ok):
                fire, size, ir, kind = True, 10.0, f"P0 EC flush {ec:.1f}", "p0_ec_flush"
        elif phase == "P1":
            p1_ceiling = min(p.p1_target, p.field_capacity)
            ec_high = ec_known and ec > p.ec_target_p1 * 1.15 and flush_ok
            ramp = s.vwc < p1_ceiling
            if s.minutes_since_shot >= p.p1_time_between_min and (ramp or (ec_high and settle_ok)):
                raw = min(p.p1_initial + p.p1_incr * s.shot_count,
                          p.p1_initial + p.p1_incr * p.p1_max_shots)
                if ramp:
                    ir, kind = f"P1 ramp VWC {s.vwc:.0f}<{p1_ceiling:.0f}", "p1_ramp"
                else:
                    ir, kind = f"P1 flush/runoff EC {ec:.1f} (at ceiling {p1_ceiling:.0f})", "p1_flush"
                fire, size = True, ec_adjust(raw, ec, p.ec_target_p1)
        elif phase == "P2":
            if ec_known and ec >= p.max_ec - 1.0:
                if flush_ok and ec_gap_ok:
                    fire, size, ir, kind = True, p.p2_shot_size * 1.5, f"P2 rescue flush EC {ec:.1f}", "p2_rescue"
                elif s.vwc < p2_thr:
                    fire, size, ir, kind = True, ec_adjust(p.p2_shot_size, ec, p.ec_target_p2), f"P2 top-up VWC {s.vwc:.0f}<{p2_thr:.0f}", "p2_topup"
            elif ec_known and p.ec_target_p2 > 0 and ec / p.ec_target_p2 > 1.2 and flush_ok and ec_gap_ok:
                fire, size, ir, kind = True, p.p2_shot_size * 1.5, f"P2 dilute EC {ec:.1f}", "p2_dilute"
            elif s.vwc < p2_thr:
                fire, size, ir, kind = True, ec_adjust(p.p2_shot_size, ec, p.ec_target_p2), f"P2 top-up VWC {s.vwc:.0f}<{p2_thr:.0f}", "p2_topup"
        elif phase == "P3":
            if s.vwc < p.p3_emergency_floor:
                fire, size, ir, kind = True, p.p3_emergency_shot, f"P3 emergency VWC {s.vwc:.0f}<{p.p3_emergency_floor:.0f}", "p3_emergency"

    # PRIORITY 3 — LIGHTS-ON WATERING WATCHDOG: backstop so no enabled zone ever starves. Never in P0: at
    # lights-on the whole night counts as "no water", and P0 is the dryback the day is meant to start with.
    watchdog_due = (p.watchdog_hours > 0 and s.lights_on and phase != "P0"
                    and s.minutes_since_shot > p.watchdog_hours * 60.0 and s.vwc < p2_thr)
    watchdog_ir = f"WATCHDOG {s.minutes_since_shot / 60.0:.1f}h no water (VWC {s.vwc:.0f}<{p2_thr:.0f})"
    if not fire and watchdog_due:
        fire, size, ir, kind = True, p.p2_shot_size, watchdog_ir, "watchdog"

    # PRIORITY 4 — MINIMUM DAILY VOLUME floor (per-plant water safety, GUARANTEED + FRONT-STACKED +
    # SENSOR-INDEPENDENT): every enabled zone MUST put through at least min_daily_volume L per photoperiod.
    # It fires from lights-on as fast as the anti-short-cycle spacing allows (so the minimum lands early /
    # front-stacked) and REGARDLESS of the VWC threshold — a lying or dead probe cannot starve a plant.
    # The ONLY VWC gate is the hard anti-drown ceiling (never flood). Feed-water + dosing safety still apply
    # in the IO shell (we never water with bad feed, even for the floor). 0 = off.
    if (not fire and p.min_daily_volume > 0 and s.lights_on
            and s.daily_vol < p.min_daily_volume
            and s.vwc < p.drown_ceiling
            and s.minutes_since_shot >= p.p2_min_interval_min):
        fire, size, ir, kind = True, p.p2_shot_size, f"MIN-DAILY floor {s.daily_vol:.1f}<{p.min_daily_volume:.1f}L (guaranteed)", "min_daily"

    # ---- SAFETY: daily cap is a BUDGET, not a wall — exemptions are by kind (CAP_EXEMPT) ----
    # NOTE: the MIN-DAILY floor above can never be blocked by this cap — the floor only fires while
    # daily_vol < min_daily_volume, and validate_params() clamps min_daily_volume <= max_daily_volume,
    # so floor-fires => daily_vol < min <= max => the cap's (daily_vol >= max) test is always false.
    # The two are mutually exclusive by construction; the floor's "guaranteed" contract holds.
    if fire and not CAP_EXEMPT[kind] and s.daily_vol >= p.max_daily_volume:
        if watchdog_due:
            # The routine shot is over budget, but the zone has had no water for watchdog_hours in
            # daylight and sits under its re-water threshold: it gets the watchdog's cap-exempt shot,
            # not nothing (live F2 2026-09-22: Z1 dry 14:06-22:00 behind a spent budget).
            fire, size, ir, kind = True, p.p2_shot_size, watchdog_ir + " — over the daily budget", "watchdog"
        else:
            fire, ir, kind = False, f"BLOCK daily-cap {s.daily_vol:.0f}/{p.max_daily_volume:.0f}L (budget; emergencies exempt)", "block_daily_cap"

    reason = treason + (" | " if (treason and ir) else "") + ir
    if not ec_known:
        reason += (" | " if reason else "") + "EC unknown: base VWC watering; salt protection unverified"
    return phase, round(p2_thr, 1), fire, round(size, 1), Reason(reason, kind, fire and CAP_EXEMPT.get(kind, False))


def pick_sibling(blind_p1_target, healthy):
    """PURE. A blind-probe zone copies the recipe-closest healthy sibling (nearest p1_target;
    tie -> lowest zone). `healthy` = list of (zone, p1_target); returns the zone or None."""
    best = None
    for zone, tgt in healthy:
        dist = abs(tgt - blind_p1_target)
        if best is None or dist < best[0] or (dist == best[0] and zone < best[1]):
            best = (dist, zone)
    return best[1] if best else None


def feed_grace_ok(now_ts, last_good_ts, grace_min):
    """PURE. Is a last-known-good feed-EC reading still inside the grace window (epoch-seconds)?
    True iff last_good_ts is not None AND younger than grace_min minutes. None -> False (fail closed)."""
    if last_good_ts is None:
        return False
    return (now_ts - last_good_ts) < grace_min * 60.0


def cross_zone_outliers(snaps):
    """PURE. snaps: {zone -> ZoneSnapshot|None}. Flag a zone drinking < 40% of the cross-zone median
    daily_vol (median >= 5L). Returns [(zone, reason), …]."""
    vols = [(z, s.daily_vol) for z, s in snaps.items() if s is not None]
    out = []
    if len(vols) >= 2:
        vs = sorted(v for _, v in vols)
        med = vs[len(vs) // 2]
        if med >= 5.0:
            for z, v in vols:
                if v < 0.4 * med:
                    out.append((z, f"Zone {z} {v:.0f}L vs ~{med:.0f}L on the other rows — under-drinking (probe/valve/delivery?)"))
    return out


def detect_vmax(wetup_vwc, min_points=4, plateau_delta=0.6, plateau_runs=2):
    """PURE. Detect a zone's P1 wet-up ceiling (Vmax) from an ordered series of
    post-shot VWC readings during the morning ramp.

    A shot that raises VWC by <= `plateau_delta` points is marginal uptake; once
    `plateau_runs` consecutive marginal shots occur, the substrate has reached its
    field-capacity ceiling. Returns (vmax, confidence in 0..1), or (None, 0.0) when
    there isn't enough data or no plateau yet (still wetting up).

    Advisory only: the caller publishes it as a sensor. It does NOT change any
    irrigation decision in this version.
    """
    pts = [float(v) for v in wetup_vwc if v is not None]
    if len(pts) < min_points:
        return None, 0.0
    deltas = [pts[i + 1] - pts[i] for i in range(len(pts) - 1)]
    run, plateau_at = 0, None
    for i, d in enumerate(deltas):
        if d <= plateau_delta:  # marginal / flat / slight drop
            run += 1
            if run >= plateau_runs:
                plateau_at = i + 1  # point index where the plateau locked
                break
        else:
            run = 0
    if plateau_at is None:
        return None, 0.0
    vmax = max(pts[: plateau_at + 1])
    split = plateau_at - plateau_runs + 1
    early = [d for d in deltas[:split] if d > 0]
    tail = deltas[split : plateau_at + 1]
    early_rate = (sum(early) / len(early)) if early else plateau_delta
    tail_rate = (sum(abs(d) for d in tail) / len(tail)) if tail else 0.0
    contrast = (1.0 - tail_rate / early_rate) if early_rate > 0 else 0.0
    coverage = min(len(pts) / 8.0, 1.0)
    conf = 0.65 * max(0.0, min(1.0, contrast)) + 0.35 * coverage
    return round(vmax, 1), round(max(0.0, min(1.0, conf)), 2)


# clamp ranges for config validation (the 12.2-EC fat-finger class). (lo, hi) per field.
_PARAM_BOUNDS = {
    "p1_target": (20.0, 85.0), "p2_threshold": (10.0, 70.0),
    "ec_target_p0": (0.5, 9.0), "ec_target_p1": (0.5, 9.0), "ec_target_p2": (0.5, 9.0),
    "dryback_target": (2.0, 60.0), "p3_emergency_floor": (10.0, 60.0),
    "field_capacity": (40.0, 90.0), "max_ec": (3.0, 15.0), "watchdog_hours": (0.0, 12.0),
    "p2_shot_size": (0.5, 20.0), "p1_initial": (0.5, 15.0), "p1_incr": (0.0, 5.0),
    "p1_max_shots": (1.0, 40.0), "p1_time_between_min": (1.0, 120.0),
    "p0_max_wait_min": (5.0, 240.0), "p3_emergency_shot": (0.5, 15.0),
    "max_daily_volume": (10.0, 2000.0), "min_daily_volume": (0.0, 500.0),
    "drown_ceiling": (50.0, 100.0),
}


def validate_params(p):
    """PURE. Clamp out-of-range params; return (clamped_ZoneParams, [warnings])."""
    warns, fixes = [], {}
    for name, (lo, hi) in _PARAM_BOUNDS.items():
        v = getattr(p, name)
        if v < lo or v > hi:
            nv = max(lo, min(hi, v))
            if name == "p1_max_shots":
                nv = int(nv)
            fixes[name] = nv
            warns.append(f"{name}={v:g} out of [{lo:g},{hi:g}] -> clamped to {nv:g}")
    # the ramp minimum can never exceed the ramp maximum (else P1 could only exit at max shots anyway)
    eff_p1max = int(fixes.get("p1_max_shots", p.p1_max_shots))
    if p.p1_min_shots > eff_p1max:
        fixes["p1_min_shots"] = eff_p1max
        warns.append(f"p1_min_shots={p.p1_min_shots:g} > p1_max_shots={eff_p1max:g} -> clamped to {eff_p1max:g}")
    # the floor can never exceed the cap (else it would fight the budget block)
    eff_min = fixes.get("min_daily_volume", p.min_daily_volume)
    eff_max = fixes.get("max_daily_volume", p.max_daily_volume)
    if eff_min > eff_max:
        fixes["min_daily_volume"] = eff_max
        warns.append(f"min_daily_volume={eff_min:g} > max_daily_volume={eff_max:g} -> clamped to {eff_max:g}")
    return (dataclasses.replace(p, **fixes) if fixes else p), warns


# ---- STATUS REPUBLISH helpers (PURE) — reproduce the master sensor.crop_steering_* vocabulary ----
_SYS_UNSAFE = ("over_saturated", "ec_limit_exceeded")
_SYS_WARN = ("approaching_saturation", "approaching_ec_limit", "ec_unknown")


def zone_safety_status(vwc, ec, field_capacity, max_ec):
    """PURE. Per-zone safety label (safe / over_saturated / ec_limit_exceeded /
    approaching_saturation / approaching_ec_limit). vwc/ec may be None (blind)."""
    if vwc is not None and field_capacity and vwc >= field_capacity:
        return "over_saturated"
    if ec is not None and max_ec and ec >= max_ec:
        return "ec_limit_exceeded"
    if vwc is not None and field_capacity and vwc >= field_capacity - 5:
        return "approaching_saturation"
    if ec is not None and max_ec and ec >= max_ec - 1:
        return "approaching_ec_limit"
    if ec is None or not math.isfinite(ec):
        return "ec_unknown"
    return "safe"


def system_safety_status(zone_labels):
    """PURE. Roll per-zone safety labels into (status, unsafe, warning, safe) counts."""
    labels = list(zone_labels)
    unsafe = sum(1 for s in labels if s in _SYS_UNSAFE)
    warning = sum(1 for s in labels if s in _SYS_WARN)
    status = "unsafe" if unsafe else ("warning" if warning else "safe")
    return status, unsafe, warning, max(0, len(labels) - unsafe - warning)


def zone_status_label(phase, fire, blocked, blind, reason=""):
    """PURE. Human one-liner for the per-zone status tile."""
    if blind:
        return "Probe dead — copying"
    if blocked:
        return ("Blocked: " + str(blocked))[:80]
    if "BLOCK" in (reason or ""):
        return "Blocked — EC/cap"
    if fire:
        return {"P0": "Flushing", "P1": "Refilling", "P2": "Topping up", "P3": "Emergency"}.get(phase, "Watering")
    return {"P0": "Drying back", "P1": "Ramping", "P2": "Optimal", "P3": "Overnight dryback"}.get(phase, "Idle")
