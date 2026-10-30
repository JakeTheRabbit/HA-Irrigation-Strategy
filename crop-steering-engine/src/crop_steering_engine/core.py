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
# (seen live: 6-8 mS/cm during the morning ramp on zones whose quiet readings were ~4.5).
# The controller takes a settled reading only this long after the last shot, and an EC correction that
# acts on one waits the same time, so each correction is judged by a reading taken after the last drained.
EC_SETTLE_MIN = 45.0
# P1 ends when a shot at or over the P1 target no longer raises the zone's highest reading by this much (a rule
# adopted on 6 Oct 2026): reach the target, give one more shot, and if the peak did not rise, the slab is full.
# It is the fallback of the zone's p1_rise_pts setting (ZoneParams.p1_rise_pts).
P1_RISE_PTS = 0.5
# With the zone's learned gain known, a rise also has to reach this share of what the last shot should have lifted
# (the auto setpoints' own plateau test), so a probe that moves a lot per shot is not kept in P1 by its noise.
P1_RISE_GAIN_FRACTION = 0.3
# Extra shots P1 may give once it has read its target: the fallback of p1_maximum_extra_shots.
P1_MAX_EXTRA_SHOTS = 3
# Ramp shots in a row, under the P1 target, that may each raise the settled reading by less than the rise P1 needs
# (p1_rise) before P1 ends as stalled: the fallback of ZoneParams.p1_stall_shots. A slab that cannot reach its target
# otherwise ramps on, with growing shots, to the maximum shots and then re-waters at a point it never reaches.
P1_STALL_SHOTS = 2
# Points under the stalled peak the re-water point sits for the rest of that grow-day while the zone's gain is not
# learned (the auto setpoints' DEFAULT_BAND_PTS).
P1_STALL_BAND_PTS = 1.5
# Minutes of readings a settled moisture reading is the median of (settled_reading).
SETTLED_VWC_MIN = 10.0
# P0 flushes when pore EC is over this multiple of the P0 EC target, with a shot this size (% of substrate).
P0_EC_FLUSH_RATIO = 2.5
P0_EC_FLUSH_SHOT = 10.0
# P0 stall exit (ZoneParams.p0_stall_exit): judged only once P0 has run this long, and a dryback slower than this
# (VWC points per hour) counts as stalled. Points/h, as the controller measures dryback_rate.
P0_STALL_AFTER_MIN = 30.0
P0_STALL_RATE_FLOOR = 0.1
# P2 dilutes at pore EC over this multiple of the P2 EC target: the fallback of ZoneParams.p2_dilute_ratio.
P2_DILUTE_RATIO = 1.2
# A flush to an EC target (ZoneParams.ec_flush_target) never aims under the feed EC plus this margin: water at the
# feed's own EC cannot bring the slab below it.
EC_FLUSH_FEED_MARGIN = 0.2
# P2 modes (ZoneParams.p2_mode): moisture-driven top-ups (as always), a timer, or a timer with a moisture ceiling and
# the moisture top-up kept as a floor rescue.
P2_MODES = ("moisture", "timed", "timed_guarded")
# ec_adjust's multipliers by pore EC / target, the first row that matches: over the ratio, then under it.
EC_ADJUST_UP = ((1.5, 2.0), (1.2, 1.5), (1.0, 1.2))
EC_ADJUST_DOWN = ((0.5, 0.5), (0.8, 0.7))
# These are the "generic" substrate profile's values (defaults.SUBSTRATE_PROFILES); the caller passes the room's
# profile through ZoneParams, and a caller that passes nothing gets these.


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
# Kinds that never fire: idle (nothing due), block_high_ec, hold_high_ec, block_daily_cap, hold_backed_up.
CAP_EXEMPT = {
    "flush_high_ec": True,  # anti-lockout: pore EC at max_ec
    "p0_ec_flush": False,
    "p1_ramp": True,
    "p1_extra": False,  # a P1 shot at or over the target, to see whether the slab still takes water: budgeted
    "p1_flush": False,  # no longer fired (3.11.0); kept so an old reason's kind still has an entry
    "p2_rescue": True,  # pore EC within 1 of max_ec
    "p2_dilute": False,
    "p2_topup": False,
    "p2_timed": False,  # a timed P2 shot (p2_mode timed / timed_guarded): steering, inside the budget
    "p3_emergency": True,
    "p3_hold": False,  # holds the overnight dryback at its target: steering, not a rescue
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
    dryback_target: float       # P0's dryback % while p0_additional_dryback is 0, and the overnight one unless
    #                             p3_dryback_target is given
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
    #                                 GUARANTEED + PACED + SENSOR-INDEPENDENT: every plant gets this much, spread
    #                                 evenly over the day (floor_share), regardless of the VWC threshold — a
    #                                 lying/dead probe cannot suppress it. Clamped < max_daily_volume.
    p1_min_shots: int = 0           # P1 cannot graduate on "target reached" until this many ramp shots have
    #                                 landed (0 = off). The ramp runs as configured; max shots still bounds it.
    drown_ceiling: float = 90.0     # the ONLY VWC gate on the min-daily floor: a hard anti-drown limit well above
    #                                 field capacity. Below it, the floor fires regardless of the probe; at/above it
    #                                 the floor holds (never flood). 90 ~= unreachable in coco -> truly probe-blind.
    min_floor_finish_h: float = 3.0  # the min-daily floor is paced to be complete this many hours before lights-off,
    #                                  when the evening dryback (predictive P3) may start.
    p3_time_between_min: float | None = None  # min minutes from the last shot to a P3 emergency shot, so a rescue
    #                                  soaks down to the probe before moisture is judged again. Without it a zone
    #                                  still reading under the rescue level got another rescue every pass (60 s)
    #                                  until the water arrived. The gap counts from the last shot, so the first
    #                                  rescue of a night still goes at once. 0 = off. None: as before (no gap).
    p1_rise_pts: float = P1_RISE_PTS  # an extra P1 shot that raises the reading less than this ends P1
    p1_max_extra_shots: int = P1_MAX_EXTRA_SHOTS  # extra P1 shots after the target is read; at this many P1 ends
    p1_stall_shots: int = P1_STALL_SHOTS  # ramp shots in a row under the target without the rise P1 needs; at this
    #                                       many P1 ends as stalled (p1_stall). 0 = off: the ramp runs to max shots.
    p1_stall_band: float = P1_STALL_BAND_PTS  # the zone's usual P2 drop: after a stall the day re-waters this far
    #                                           under what the zone reached (p1_stall_rewater)
    p0_additional_dryback: float = 0.0  # P0 ends once VWC is this % below the highest reading since lights-on,
    #                                     the small extra dryback before the first shot. 0 = off: P0 waits for
    #                                     dryback_target, as before.
    p2_time_between_min: float = 0.0  # min minutes from the last shot to a P2 top-up, so a shot soaks down to the
    #                                   probe before moisture is judged again. Without it a zone still reading under
    #                                   the re-water threshold got another top-up every pass (60 s) until the water
    #                                   arrived. Only the top-up waits: the EC corrections keep p2_min_interval_min.
    #                                   0 = off (as before).
    p3_hold: bool = False  # P3 holds the overnight dryback at its target with rescue-sized shots. Off: P3 waters
    #                        only below the rescue level, as before.
    p3_dryback_target: float | None = None  # the overnight dryback, a relative % of the day's peak, read by
    #                                         predictive P3 and the P3 hold. None: dryback_target, as before.
    # From the room's substrate profile (defaults.SUBSTRATE_PROFILES); the defaults are the generic profile's.
    ec_settle_min: float = EC_SETTLE_MIN
    p0_ec_flush_ratio: float = P0_EC_FLUSH_RATIO
    p0_ec_flush_shot: float = P0_EC_FLUSH_SHOT
    ec_adjust_up: tuple = EC_ADJUST_UP
    ec_adjust_down: tuple = EC_ADJUST_DOWN
    # Opt-in phase settings. Each default is the rule as it was, so a caller that passes none decides as before.
    p0_min_wait_min: float = 0.0  # nothing but the P0 bypass ends P0 before this many minutes. 0 = off.
    p0_stall_exit: bool = False  # P0 starts P1 early when its dryback is too slow to finish before p0_max_wait_min
    ec_flush_target: float = 0.0  # once an EC flush has fired, budgeted dilute shots go on until the settled pore
    #                               EC is at or under this (never under the feed EC + EC_FLUSH_FEED_MARGIN). 0 = off.
    p2_dilute_ratio: float = P2_DILUTE_RATIO  # P2 dilutes at pore EC over this multiple of the P2 EC target
    p2_mode: str = "moisture"  # one of P2_MODES
    p2_timed_interval_min: float = 60.0  # timed P2: a shot every this many minutes since the last shot
    p2_timed_shot_size: float = 0.0  # timed P2 shot size, % of substrate; 0 = p2_shot_size
    p2_timed_first_h: float = 0.0  # timed P2: no timed shot before this many hours after lights-on
    p2_end_h_before_off: float = 0.0  # P1/P2 hand over to P3 this many hours before lights-off. 0 = off (as before)


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
    feed_ec: float | None = 3.0   # source-water (tank) EC — for the anti-lockout dilutive-flush test; None = unknown
    #                               (never measured): no rule reasons about the feed, so no EC flush and no CS-206 hold
    new_grow_day: bool = False    # wall-clock fallback: True when in the lights-on window AND the daily
    #                               budget has NOT yet been reset for THIS grow-day (photoperiod).
    ec_settled: float | None = None  # pore EC read >= EC_SETTLE_MIN after the last shot (or the last such
    #                                  reading, held while shots come closer together). When given, EVERY
    #                                  EC rule uses it instead of `ec`; None = fall back to `ec` as before.
    steering_held: bool = False   # the caller holds routine steering (a grow-strategy plan that is held,
    #                               stale or missing): only the water-safety rules fire, the P3 emergency,
    #                               the watchdog and the minimum-daily floor. Phases still move.
    hours_since_lights_on: float | None = None  # hours since this photoperiod's lights-on; None = unknown, and the
    #                                             min-daily floor then front-stacks (fires until met, as before).
    backed_up: bool = False  # the caller saw this zone's moisture rise with no water going in (CS-310): its table is
    #                          not draining, so no EC correction pours more water into it.
    p1_reached: bool = False  # this P1 has read at or over its ceiling (the caller latches it)
    p1_peak_before_shot: float | None = None  # the zone's peak_vwc right before its last P1 shot
    p1_extra_shots: int = 0  # P1 shots fired after the ceiling was reached
    vwc_settled: float | None = None  # the zone's settled moisture now (settled_reading), and the same right before
    p1_settled_before_shot: float | None = None  # its last P1 shot: when both are given the rise is measured on them,
    #                                              not on the raw peak, so one noisy reading cannot earn a shot
    p1_expected_rise: float | None = None  # what the last P1 shot should have lifted the reading by, from the zone's
    #                                        learned gain; None = not learned, and the rise is judged on p1_rise_pts
    p1_flat_shots: int = 0  # the ramp shots in a row BEFORE the last one that did not give the rise P1 needs (the
    #                         caller counts them; p1_stall adds the last one)
    p1_probe_suspect: bool = False  # the caller doubts this probe today (water bypassing it, CS-710, or a flat
    #                                 reading): a ramp that does not rise is then not read as a stalled slab
    ec_flushing: bool = False  # an EC flush fired and the zone has not reached its ec_flush_target yet (the caller
    #                            latches it, and clears it at the target, at lights-off and at lights-on)


def settled_reading(readings):
    """PURE. The median of a run of moisture readings (the last SETTLED_VWC_MIN minutes of them), or None if there
    are none: one jumpy reading moves it far less than it moves the latest reading or the running highest."""
    vals = sorted(v for v in readings if v is not None and math.isfinite(v))
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def p1_rise(s: ZoneSnapshot, p: ZoneParams):
    """PURE. (rise, needed): how much the last P1 shot raised the zone's reading, settled when the caller gives both
    settled readings and the zone's peak otherwise (None before the first extra shot), and the rise it needed to keep
    P1 going: p1_rise_pts, or more once the learned gain says the shot should have lifted the reading further."""
    if s.vwc_settled is not None and s.p1_settled_before_shot is not None:
        rise = s.vwc_settled - s.p1_settled_before_shot
    else:
        rise = None if s.p1_peak_before_shot is None else s.peak_vwc - s.p1_peak_before_shot
    need = p.p1_rise_pts
    if s.p1_expected_rise is not None and math.isfinite(s.p1_expected_rise) and s.p1_expected_rise > 0:
        need = max(need, P1_RISE_GAIN_FRACTION * s.p1_expected_rise)
    return rise, need


def p1_stall(s: ZoneSnapshot, p: ZoneParams) -> int:
    """PURE. How many P1 ramp shots in a row, the last one included, raised the settled reading by less than the rise
    P1 needs (p1_rise): the caller's count of the earlier ones plus the last. 0 when the last one gave the rise, or
    either settled reading is missing (the raw peak says nothing under the target)."""
    if s.vwc_settled is None or s.p1_settled_before_shot is None:
        return 0
    rise, need = p1_rise(s, p)
    return max(0, int(s.p1_flat_shots)) + 1 if rise < need else 0


def p1_stall_rewater(stalled_at: float, p2_threshold: float, band: float) -> float:
    """PURE. The re-water point for the rest of a grow-day whose P1 stalled at `stalled_at`: `band` (the zone's
    usual P2 drop) under what the zone reached, never over the set point. Not floored at the rescue level: a zone
    that stalled under it would otherwise be topped up every pass at a point it cannot reach."""
    band = band if band is not None and math.isfinite(band) and band > 0 else P1_STALL_BAND_PTS
    return round(max(0.0, min(p2_threshold, stalled_at - band)), 1)


def p0_dryback(p: ZoneParams) -> float:
    """PURE. How far below the highest reading since lights-on P0 lets a zone dry before the ramp starts."""
    return p.p0_additional_dryback if p.p0_additional_dryback > 0 else p.dryback_target


def p0_stalled(s: ZoneSnapshot, p: ZoneParams) -> bool:
    """PURE. The P0 stall exit (p0_stall_exit): after P0_STALL_AFTER_MIN of P0, the dryback is drying slower than
    P0_STALL_RATE_FLOOR points/h, or at its measured rate it would not reach its target before p0_max_wait_min. Never
    while the probe is in doubt (a flat or bypassed reading fakes a stall) or the table is backing up."""
    if not p.p0_stall_exit or s.phase_minutes < P0_STALL_AFTER_MIN or s.p1_probe_suspect or s.backed_up:
        return False
    if s.peak_vwc <= 0:
        return False
    rate = s.dryback_rate if s.dryback_rate and math.isfinite(s.dryback_rate) else 0.0
    if rate < P0_STALL_RATE_FLOOR:
        return True
    remaining = max(0.0, s.vwc - s.peak_vwc * (1.0 - p0_dryback(p) / 100.0))
    return s.phase_minutes + remaining / rate * 60.0 > p.p0_max_wait_min


def ec_flush_goal(s: ZoneSnapshot, p: ZoneParams) -> float | None:
    """PURE. The pore EC a flush episode stops at (ec_flush_target), never under the feed EC + EC_FLUSH_FEED_MARGIN;
    None when the target is off."""
    if not p.ec_flush_target or p.ec_flush_target <= 0:
        return None
    feed = s.feed_ec if s.feed_ec is not None and math.isfinite(s.feed_ec) else 0.0
    return max(p.ec_flush_target, feed + EC_FLUSH_FEED_MARGIN)


def p2_timed_size(p: ZoneParams) -> float:
    """PURE. The size of a timed P2 shot: its own, or the maintenance shot size when it is 0."""
    return p.p2_timed_shot_size if p.p2_timed_shot_size and p.p2_timed_shot_size > 0 else p.p2_shot_size


def p2_timed_ceiling(p: ZoneParams) -> float:
    """PURE. Guarded timed P2 skips a slot while VWC is at or over this: the P1 target, or field capacity - 2."""
    return min(p.p1_target, p.field_capacity - 2.0)


def floor_share(s: ZoneSnapshot, p: ZoneParams) -> float:
    """PURE. How much of the min-daily floor should be in by now, 0..1: a straight line from nothing at lights-on
    to all of it min_floor_finish_h before lights-off. 1 without a clock, or once that point has passed."""
    if s.hours_since_lights_on is None:
        return 1.0
    window = s.hours_since_lights_on + s.hours_to_lights_off - p.min_floor_finish_h
    if window <= 0:
        return 1.0
    return min(1.0, max(0.0, s.hours_since_lights_on / window))


def p3_dryback(p: ZoneParams) -> float:
    """The overnight dryback, a relative % of the day's peak: its own target when given, else the shared one."""
    return p.dryback_target if p.p3_dryback_target is None else p.p3_dryback_target


def p3_hold_level(s: ZoneSnapshot, p: ZoneParams) -> float | None:
    """The VWC P3 holds a zone at overnight when the hold is on: the day's peak less the overnight dryback,
    a relative % (a 30% dryback from an 86.5% peak ends at 60.55%). None when it is off or no peak is known."""
    if not p.p3_hold or s.peak_vwc <= 0:
        return None
    return s.peak_vwc * (1.0 - p3_dryback(p) / 100.0)


def ec_adjust(size: float, ec: float | None, target: float, up=EC_ADJUST_UP, down=EC_ADJUST_DOWN) -> float:
    """Scale a shot by pore-EC vs target: high EC -> bigger (dilute), low EC -> smaller (conserve)."""
    if ec is None or not math.isfinite(ec) or target <= 0:
        return size
    r = ec / target
    for over, mult in up:
        if r > over:
            return size * mult
    for under, mult in down:
        if r < under:
            return size * mult
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
    elif phase in ("P1", "P2") and p.p2_end_h_before_off > 0 and s.hours_to_lights_off <= p.p2_end_h_before_off:
        # Timed P2 end (opt-in): the day's watering ends this long before lights-off, whatever moisture reads.
        phase, treason = "P3", f"timed P2 end {s.hours_to_lights_off:.1f}h<={p.p2_end_h_before_off:g}h to lights-off"
    elif phase == "P0":
        # The bypass first: a zone already at its rescue floor never waits out the minimum wait. Not the re-water
        # point: the overnight dryback leaves every slab under it at lights-on, and P0 is the plants' time to
        # start drinking before the first shot (#195).
        if s.vwc <= p.p3_emergency_floor:
            phase, treason = "P1", f"P0 emergency bypass VWC {s.vwc:.0f}<=floor {p.p3_emergency_floor:.0f}"
        elif s.phase_minutes < p.p0_min_wait_min:
            pass  # the minimum wait (opt-in): nothing else ends P0 before it
        elif s.dryback_pct >= p0_dryback(p):
            phase, treason = "P1", f"P0 dryback done {s.dryback_pct:.0f}%"
        elif p0_stalled(s, p):
            phase, treason = "P1", f"P0 stalled: dryback {s.dryback_rate:.2f} pts/h too slow to finish"
        elif s.phase_minutes >= p.p0_max_wait_min:
            phase, treason = "P1", f"P0 timeout {s.phase_minutes:.0f}min"
    elif phase == "P1":
        # The P1 rule (adopted 6 Oct 2026): ramp to the P1 target, then give one more shot. If that shot did not raise
        # the zone's highest reading by P1_RISE_PTS, the slab is full: P2. If it did, another shot, until one does
        # not. The maximum shots still end P1. There is deliberately NO time-based exit: a zone gate-blocked before or
        # during the ramp (feed pH/EC, dosing hold) waits in P1 and resumes; lights-off -> P3 (above) is the only
        # other way out. Pore EC no longer holds P1 open: P2's dilute shots correct it.
        # The rise is measured on settled readings when the caller has them (p1_rise), the extra shots stop at
        # p1_max_extra_shots, and they come out of the daily budget: a spent budget at the target ends P1.
        # Under the target, p1_stall_shots ramp shots in a row without the rise P1 needs end it as stalled: the slab
        # takes no more today. Never while the probe is in doubt (backed up, bypassed, flat): the ramp then runs on.
        p1_ceiling = min(p.p1_target, p.field_capacity)
        reached = s.p1_reached or s.vwc >= p1_ceiling
        rise, need = p1_rise(s, p)
        waited = s.minutes_since_shot >= p.p1_time_between_min
        if s.shot_count >= p.p1_max_shots:
            phase, treason = "P2", f"P1 max shots {s.shot_count}/{p.p1_max_shots}"
        elif (not reached and p.p1_stall_shots > 0 and waited and not s.backed_up and not s.p1_probe_suspect
              and s.shot_count >= p.p1_min_shots and p1_stall(s, p) >= p.p1_stall_shots):
            at = max(s.vwc_settled, s.p1_settled_before_shot)
            phase, treason = "P2", f"P1 stalled at {at:.1f}%: {p1_stall(s, p)} shots did not raise moisture"
            # This tick already re-waters under what the zone reached; the caller holds it for the grow-day.
            p2_thr = p1_stall_rewater(at, p2_thr, p.p1_stall_band)
        elif reached and s.p1_extra_shots >= p.p1_max_extra_shots and waited:
            phase, treason = "P2", f"P1 extra shots {s.p1_extra_shots}/{p.p1_max_extra_shots}"
        elif reached and s.daily_vol >= p.max_daily_volume:
            phase, treason = "P2", f"P1 at its target with the daily budget spent ({s.daily_vol:.0f}/{p.max_daily_volume:.0f}L)"
        elif (reached and s.shot_count >= p.p1_min_shots and s.p1_extra_shots >= 1
              and waited and rise is not None and rise < need):
            what = "settled reading" if s.vwc_settled is not None and s.p1_settled_before_shot is not None else "peak"
            phase, treason = "P2", f"P1 full: the last shot raised the {what} {max(rise, 0.0):.1f} (< {round(need, 2):g})"
    elif phase == "P2":
        # predictive P3: only if starting dryback NOW would finish by lights-on. A timed P2 end replaces it.
        if p.p2_end_h_before_off <= 0 and s.uptime_min >= 10 and s.vwc >= p.p3_emergency_floor and s.hours_to_lights_off <= 3.0:
            rate = s.dryback_rate if (s.dryback_rate and s.dryback_rate > 0) else 0.1
            # Target is relative % of detected peak; measured rate is VWC
            # percentage points/hour. Predict only the still-needed point drop.
            target_vwc = s.peak_vwc * (1.0 - p3_dryback(p) / 100.0)
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
    ec_gap = max(p.p2_min_interval_min, p.ec_settle_min) if settled else p.p2_min_interval_min
    ec_gap_ok = s.minutes_since_shot >= ec_gap
    # An EC correction needs water that can dilute (feed below pore EC) and a table that drains (not backed up):
    # the runoff carries the salt out, so a full slab is where a flush works. The capped corrections (P0 flush,
    # P2 dilute) need nothing more: the daily budget and the settle gap bound them. The cap-exempt
    # flushes (anti-lockout, P2 rescue) also need the reading under field capacity - 2, so that a probe reading
    # above that setpoint cannot run them outside the budget for ever (observed on a production room, 5 Oct 2026: a
    # zone read 70 against a field capacity of 54, and that test had stopped every flush while its pore EC sat at 7).
    feed_known = s.feed_ec is not None and math.isfinite(s.feed_ec)
    dilutive = ec_known and feed_known and s.feed_ec < ec and not s.backed_up
    flush_ok = dilutive and s.vwc < p.field_capacity - 2.0

    # PRIORITY 1 — ANTI-LOCKOUT: high pore EC FLUSHES in ANY phase, never locks out. While steering is held
    # the flush waits too (it steers to max_ec, a setpoint the plan manages); the blocks below still apply.
    # A slab that reads full gets no anti-lockout flush; the capped corrections below still flush it.
    # A feed never measured neither flushes nor holds: the zone is watered on its moisture (noted in the reason).
    if ec_known and ec >= p.max_ec and (flush_ok or not dilutive) and (feed_known or s.backed_up):
        if not dilutive:
            why = "table not draining" if s.backed_up else "feed not dilutive"
            reason = treason + (" | " if treason else "") + f"BLOCK high EC {ec:.1f} — {why} (self-clears)"
            return phase, round(p2_thr, 1), False, 0.0, Reason(reason, "block_high_ec")
        if ec_gap_ok:
            if not s.steering_held:
                excess = max(ec - p.max_ec, 0.0)
                size = p.p2_shot_size * (1.5 + min(excess, 3.0) * 0.3)
                fire, ir, kind = True, f"FLUSH high EC {ec:.1f}>={p.max_ec:.1f} (anti-lockout)", "flush_high_ec"
        else:
            # over the ceiling but a flush just fired — hold this tick so it can drain (no machine-gun, no normal shot)
            reason = treason + (" | " if treason else "") + f"HOLD high EC {ec:.1f} — flush draining ({s.minutes_since_shot:.0f}/{ec_gap:.0f}min)"
            return phase, round(p2_thr, 1), False, 0.0, Reason(reason, "hold_high_ec")

    # PRIORITY 2 — normal per-phase rules. While steering is held only the P3 emergency runs: a held plan
    # stops the steering, never the water-safety rules (the watchdog and the floor below run either way).
    if not fire and not s.steering_held:
        if phase == "P0":
            # P0 is the morning dryback: it fires only a genuine EC flush, gated like every other flush.
            if (ec_known and p.ec_target_p0 > 0 and ec / p.ec_target_p0 > p.p0_ec_flush_ratio
                    and dilutive and ec_gap_ok):
                fire, size, ir, kind = True, p.p0_ec_flush_shot, f"P0 EC flush {ec:.1f}", "p0_ec_flush"
        elif phase == "P1":
            p1_ceiling = min(p.p1_target, p.field_capacity)
            reached = s.p1_reached or s.vwc >= p1_ceiling
            if s.minutes_since_shot >= p.p1_time_between_min:
                raw = min(p.p1_initial + p.p1_incr * s.shot_count,
                          p.p1_initial + p.p1_incr * p.p1_max_shots)
                rise, _need = p1_rise(s, p)
                if not reached:
                    ir, kind = f"P1 ramp VWC {s.vwc:.0f}<{p1_ceiling:.0f}", "p1_ramp"
                elif s.backed_up:  # CS-310: the table is not draining, so no extra water goes into it
                    ir, kind = "HOLD P1 extra shot: the table is not draining", "hold_backed_up"
                elif s.p1_extra_shots == 0 or rise is None:
                    ir, kind = f"P1 extra shot at the target {p1_ceiling:.0f}", "p1_extra"
                else:
                    ir, kind = f"P1 extra shot: the last one raised the peak {rise:.1f}", "p1_extra"
                if kind != "hold_backed_up":
                    fire, size = True, ec_adjust(raw, ec, p.ec_target_p1, p.ec_adjust_up, p.ec_adjust_down)
        elif phase == "P2":
            goal = ec_flush_goal(s, p) if s.ec_flushing else None
            timed = p.p2_mode in ("timed", "timed_guarded")
            topup_due = s.vwc < p2_thr and s.minutes_since_shot >= p.p2_time_between_min
            topup = ec_adjust(p.p2_shot_size, ec, p.ec_target_p2, p.ec_adjust_up, p.ec_adjust_down)
            if ec_known and ec >= p.max_ec - 1.0 and flush_ok and ec_gap_ok:
                fire, size, ir, kind = True, p.p2_shot_size * 1.5, f"P2 rescue flush EC {ec:.1f}", "p2_rescue"
            elif ec_known and p.ec_target_p2 > 0 and ec / p.ec_target_p2 > p.p2_dilute_ratio and dilutive and ec_gap_ok:
                fire, size, ir, kind = True, p.p2_shot_size * 1.5, f"P2 dilute EC {ec:.1f}", "p2_dilute"
            elif goal is not None and ec_known and ec > goal and flush_ok and ec_gap_ok:
                # A flush episode carries on to its target: budgeted dilute shots, gated as every other flush.
                fire, size, ir, kind = True, p.p2_shot_size * 1.5, f"P2 flush to EC target {ec:.1f}>{goal:.1f}", "p2_dilute"
            elif timed:
                ceiling = p2_timed_ceiling(p)
                slot_open = s.hours_since_lights_on is None or s.hours_since_lights_on >= p.p2_timed_first_h
                if p.p2_mode == "timed_guarded" and topup_due:  # the floor rescue: the moisture top-up still fires
                    fire, size, ir, kind = True, topup, f"P2 top-up VWC {s.vwc:.0f}<{p2_thr:.0f}", "p2_topup"
                elif slot_open and s.minutes_since_shot >= p.p2_timed_interval_min:
                    if p.p2_mode == "timed_guarded" and s.vwc >= ceiling:
                        ir = f"SKIP timed P2 shot: VWC {s.vwc:.1f}>={ceiling:.1f} (ceiling)"
                    else:
                        fire, size, kind = True, p2_timed_size(p), "p2_timed"
                        ir = (f"P2 timed shot every {p.p2_timed_interval_min:g}min "
                              f"({s.minutes_since_shot:.0f}min since the last)")
            elif topup_due:
                fire, size, ir, kind = True, topup, f"P2 top-up VWC {s.vwc:.0f}<{p2_thr:.0f}", "p2_topup"
    p3_gap = p.p3_time_between_min or 0.0
    if not fire and phase == "P3" and s.vwc < p.p3_emergency_floor and s.minutes_since_shot >= p3_gap:
        fire, size, ir, kind = True, p.p3_emergency_shot, f"P3 emergency VWC {s.vwc:.0f}<{p.p3_emergency_floor:.0f}", "p3_emergency"
    # P3 HOLD (opt-in): instead of letting a fast night dry on to the rescue level, a rescue-sized shot each
    # time the zone dries to the day's peak less the overnight dryback, the P3 time between shots apart. It
    # steers, so a held plan stops it and the daily budget holds it (CAP_EXEMPT); the rescue stays the floor.
    hold = p3_hold_level(s, p)
    if (not fire and phase == "P3" and not s.steering_held and hold is not None and s.vwc < hold
            and s.minutes_since_shot >= p3_gap):
        why = f"P3 hold dryback VWC {s.vwc:.1f}<{hold:.1f} ({p3_dryback(p):g}% of peak {s.peak_vwc:.1f})"
        fire, size, ir, kind = True, p.p3_emergency_shot, why, "p3_hold"

    # PRIORITY 3 — LIGHTS-ON WATERING WATCHDOG: backstop so no enabled zone ever starves. Never in P0: at
    # lights-on the whole night counts as "no water", and P0 is the dryback the day is meant to start with.
    watchdog_due = (p.watchdog_hours > 0 and s.lights_on and phase != "P0"
                    and s.minutes_since_shot > p.watchdog_hours * 60.0 and s.vwc < p2_thr)
    watchdog_ir = f"WATCHDOG {s.minutes_since_shot / 60.0:.1f}h no water (VWC {s.vwc:.0f}<{p2_thr:.0f})"
    if not fire and watchdog_due:
        fire, size, ir, kind = True, p.p2_shot_size, watchdog_ir, "watchdog"

    # PRIORITY 4 — MINIMUM DAILY VOLUME floor (per-plant water safety, GUARANTEED + PACED +
    # SENSOR-INDEPENDENT): every enabled zone MUST put through at least min_daily_volume L per photoperiod,
    # REGARDLESS of the VWC threshold — a lying or dead probe (a probe in a wet spot) cannot starve a plant.
    # Never in P0: the morning dryback comes first, as for the watchdog. Then it is due whenever the zone is
    # behind floor_share's straight line to the whole minimum min_floor_finish_h before lights-off, so a zone
    # behind at the end of P0 catches up in P1 and the rest lands spaced out through P2; past that point, or
    # without a clock, it fires until the minimum is in. Every shot the zone gets counts toward it. The ONLY
    # VWC gate is the hard anti-drown ceiling (never flood). Feed-water + dosing safety still apply in the IO
    # shell (we never water with bad feed, even for the floor). 0 = off.
    floor_due = p.min_daily_volume * floor_share(s, p)
    if (not fire and p.min_daily_volume > 0 and s.lights_on and phase != "P0"
            and s.daily_vol < floor_due
            and s.vwc < p.drown_ceiling
            and s.minutes_since_shot >= p.p2_min_interval_min):
        fire, size, ir, kind = (
            True, p.p2_shot_size,
            f"MIN-DAILY floor {s.daily_vol:.1f}<{floor_due:.1f} of {p.min_daily_volume:.1f}L (guaranteed)", "min_daily",
        )

    # ---- SAFETY: daily cap is a BUDGET, not a wall — exemptions are by kind (CAP_EXEMPT) ----
    # NOTE: the MIN-DAILY floor above can never be blocked by this cap — the floor only fires while
    # daily_vol < min_daily_volume, and validate_params() clamps min_daily_volume <= max_daily_volume,
    # so floor-fires => daily_vol < min <= max => the cap's (daily_vol >= max) test is always false.
    # The two are mutually exclusive by construction; the floor's "guaranteed" contract holds.
    if fire and not CAP_EXEMPT[kind] and s.daily_vol >= p.max_daily_volume:
        if watchdog_due:
            # The routine shot is over budget, but the zone has had no water for watchdog_hours in
            # daylight and sits under its re-water threshold: it gets the watchdog's cap-exempt shot,
            # not nothing (seen live: a zone left dry from 14:06 to lights-off behind a spent budget).
            fire, size, ir, kind = True, p.p2_shot_size, watchdog_ir + " — over the daily budget", "watchdog"
        else:
            fire, ir, kind = False, f"BLOCK daily-cap {s.daily_vol:.0f}/{p.max_daily_volume:.0f}L (budget; emergencies exempt)", "block_daily_cap"

    reason = treason + (" | " if (treason and ir) else "") + ir
    if not ec_known:
        reason += (" | " if reason else "") + "EC unknown: base VWC watering; salt protection unverified"
    elif not feed_known and ec >= p.max_ec:
        reason += (" | " if reason else "") + f"high EC {ec:.1f} not flushed: feed EC unknown"
    return phase, round(p2_thr, 1), fire, round(size, 1), Reason(reason, kind, fire and CAP_EXEMPT.get(kind, False))


def next_shot_size(s: ZoneSnapshot, p: ZoneParams) -> float:
    """PURE. The size of this zone's next routine shot, % of substrate, as decide() would size it now, in the
    phase decide() puts the zone in: in P0 the ramp's first shot; in P1 its next ramp shot (the extra shots at
    the ceiling are ramp-sized too); in P2 a maintenance shot, scaled by EC; in P3 a rescue-sized one. For
    planning water (a reservoir refilled before it runs short), not a forecast of when it fires; EC
    corrections, flushes, the watchdog and the daily minimum are left out."""
    settled = s.ec_settled is not None and math.isfinite(s.ec_settled)
    ec = s.ec_settled if settled else s.ec
    phase = decide(s, p)[0]
    if phase in ("P0", "P1"):
        count = s.shot_count if s.phase == "P1" and phase == "P1" else 0
        raw = min(p.p1_initial + p.p1_incr * count, p.p1_initial + p.p1_incr * p.p1_max_shots)
        return ec_adjust(raw, ec, p.ec_target_p1, p.ec_adjust_up, p.ec_adjust_down)
    if phase == "P2":
        if p.p2_mode in ("timed", "timed_guarded"):
            return p2_timed_size(p)
        return ec_adjust(p.p2_shot_size, ec, p.ec_target_p2, p.ec_adjust_up, p.ec_adjust_down)
    return p.p3_emergency_shot


def waiting_for(s: ZoneSnapshot, p: ZoneParams) -> list:
    """PURE. What would move this zone next, by the rules decide() applies, and what they compare.

    A list of conditions; whichever comes first acts. Each is {"rule", "shot", "to"} (a shot, or the
    phase it leads to) with a reading test {"metric": "vwc"|"ec", "op", "value", "now"}, a wait
    {"in_min"}, or both when a shot needs both. The EC reading is the settled one when there is one,
    as decide() uses. P0's dryback says which dryback, from which peak ({"dryback", "peak"}), and a P2
    top-up waits out the time between P2 shots when one is set. A held plan (steering_held) leaves out
    the routine shots it stops. It says what the engine checks, not what will happen: the controller's
    gates (switches, feed water, the daily water limit), the EC flush and rescue rules, the watchdog,
    the daily minimum and P2's early move to P3 in the last three hours before lights-off are not in
    it, and nothing is forecast.
    """
    settled = s.ec_settled is not None and math.isfinite(s.ec_settled)
    ec = s.ec_settled if settled else s.ec
    ec_known = ec is not None and math.isfinite(ec)
    items = []

    def add(rule, shot=False, to=None, metric=None, op=None, value=None, now=None, in_min=None, **extra):
        item = {"rule": rule, "shot": shot, "to": to}
        if metric is not None:
            item.update(metric=metric, op=op, value=round(value, 2),
                        now=None if now is None else round(now, 2))
        if in_min is not None:
            item["in_min"] = round(max(0.0, in_min), 1)
        item.update(extra)
        items.append(item)

    if s.phase == "P0":
        add("p0_timeout", to="P1", in_min=max(p.p0_max_wait_min, p.p0_min_wait_min) - s.phase_minutes)
        add("p0_bypass", to="P1", metric="vwc", op="<=", value=p.p3_emergency_floor, now=s.vwc)
        if s.peak_vwc > 0:
            wait = p.p0_min_wait_min - s.phase_minutes
            add("p0_dryback", to="P1", metric="vwc", op="<=",
                value=s.peak_vwc * (1.0 - p0_dryback(p) / 100.0), now=s.vwc,
                dryback=round(p0_dryback(p), 2), peak=round(s.peak_vwc, 1),
                **({"in_min": round(wait, 1)} if wait > 0 else {}))
    elif s.phase == "P1":
        ceiling = min(p.p1_target, p.field_capacity)
        reached = s.p1_reached or s.vwc >= ceiling
        if s.shot_count < p.p1_max_shots and not s.steering_held and not reached:
            add("p1_ramp", shot=True, metric="vwc", op="<", value=ceiling, now=s.vwc,
                in_min=p.p1_time_between_min - s.minutes_since_shot)
        # At the target: one more shot, then P2 once a shot no longer raises the reading by the rise it needs.
        add("p1_done", to="P2", metric="vwc", op=">=", value=ceiling, now=s.vwc,
            shots_left=max(0, p.p1_min_shots - s.shot_count, 0 if s.p1_extra_shots else 1), ec_max=None, ec_now=None,
            rise_min=round(p1_rise(s, p)[1], 2))
        add("p1_max_shots", to="P2", shots_left=max(0, p.p1_max_shots - s.shot_count))
    elif s.phase == "P2":
        if not s.steering_held:
            gap = p.p2_time_between_min
            if p.p2_mode != "timed":  # a pure timer has no moisture top-up
                add("p2_topup", shot=True, metric="vwc", op="<", value=p.p2_threshold, now=s.vwc,
                    in_min=gap - s.minutes_since_shot if gap > 0 else None)
            if p.p2_mode in ("timed", "timed_guarded"):
                waits = [p.p2_timed_interval_min - s.minutes_since_shot]
                if s.hours_since_lights_on is not None:
                    waits.append((p.p2_timed_first_h - s.hours_since_lights_on) * 60.0)
                extra = {"ceiling": round(p2_timed_ceiling(p), 2)} if p.p2_mode == "timed_guarded" else {}
                add("p2_timed", shot=True, in_min=max(waits), size=round(p2_timed_size(p), 2), **extra)
            if ec_known and p.ec_target_p2 > 0:
                add("p2_dilute", shot=True, metric="ec", op=">", value=p.ec_target_p2 * p.p2_dilute_ratio, now=ec)
        if p.p2_end_h_before_off > 0:
            add("lights_off", to="P3", in_min=(s.hours_to_lights_off - p.p2_end_h_before_off) * 60.0, timed_end=True)
        else:
            add("lights_off", to="P3", in_min=s.hours_to_lights_off * 60.0)
    elif s.phase == "P3":
        p3_gap = p.p3_time_between_min or 0.0
        add("p3_emergency", shot=True, metric="vwc", op="<", value=p.p3_emergency_floor, now=s.vwc,
            in_min=p3_gap - s.minutes_since_shot if p3_gap > 0 else None)
        hold = p3_hold_level(s, p)
        if hold is not None and not s.steering_held:
            add("p3_hold", shot=True, metric="vwc", op="<", value=hold, now=s.vwc,
                in_min=p3_gap - s.minutes_since_shot if p3_gap > 0 else None, dryback=p3_dryback(p))
        add("lights_on", to="P0", in_min=s.hours_to_lights_on * 60.0)
    return items


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
# The four moisture levels take exactly the range their Home Assistant setting accepts, so the
# engine never clips a value the setting took. Their tops are 100: what bounds the water is the
# order between them (the re-water level stays at least 3 points over the rescue level and under
# the peak), not a fixed number. A probe reads on its own scale, so only the
# floors guard, against a slipped digit such as 6.5 for 65; they stay where they were, so a room
# steering low (a peak of 20, a re-water level of 15) waters as set.
_PARAM_BOUNDS = {
    "p1_target": (20.0, 100.0), "p2_threshold": (10.0, 100.0),
    "ec_target_p0": (0.5, 9.0), "ec_target_p1": (0.5, 9.0), "ec_target_p2": (0.5, 9.0),
    "dryback_target": (2.0, 60.0), "p3_emergency_floor": (10.0, 65.0),
    "field_capacity": (40.0, 100.0), "max_ec": (3.0, 15.0), "watchdog_hours": (0.0, 12.0),
    "p2_shot_size": (0.5, 20.0), "p1_initial": (0.5, 15.0), "p1_incr": (0.0, 5.0),
    "p1_max_shots": (1.0, 40.0), "p1_time_between_min": (1.0, 120.0),
    "p0_max_wait_min": (5.0, 240.0), "p3_emergency_shot": (0.5, 15.0),
    "max_daily_volume": (10.0, 2000.0), "min_daily_volume": (0.0, 500.0),
    "drown_ceiling": (50.0, 100.0), "min_floor_finish_h": (0.0, 12.0),
    "p1_rise_pts": (0.1, 5.0), "p1_max_extra_shots": (1.0, 30.0), "p1_stall_shots": (0.0, 10.0),
    "p0_additional_dryback": (0.0, 40.0),
    "p2_time_between_min": (0.0, 120.0),
    "p2_min_interval_min": (1.0, 120.0),
    "p0_min_wait_min": (0.0, 240.0), "ec_flush_target": (0.0, 9.0), "p2_dilute_ratio": (1.0, 3.0),
    "p2_timed_interval_min": (5.0, 720.0), "p2_timed_shot_size": (0.0, 20.0), "p2_timed_first_h": (0.0, 24.0),
    "p2_end_h_before_off": (0.0, 12.0),
}


def validate_params(p):
    """PURE. Clamp out-of-range params; return (clamped_ZoneParams, [warnings])."""
    warns, fixes = [], {}
    for name, (lo, hi) in _PARAM_BOUNDS.items():
        v = getattr(p, name)
        if v < lo or v > hi:
            nv = max(lo, min(hi, v))
            if name in ("p1_max_shots", "p1_max_extra_shots", "p1_stall_shots"):
                nv = int(nv)
            fixes[name] = nv
            warns.append(f"{name}={v:g} out of [{lo:g},{hi:g}] -> clamped to {nv:g}")
    if p.p2_mode not in P2_MODES:
        fixes["p2_mode"] = "moisture"
        warns.append(f"p2_mode={p.p2_mode!s} unknown -> moisture")
    # the P0 minimum wait never exceeds the maximum wait
    eff_max_wait = fixes.get("p0_max_wait_min", p.p0_max_wait_min)
    eff_min_wait = fixes.get("p0_min_wait_min", p.p0_min_wait_min)
    if eff_min_wait > eff_max_wait:
        fixes["p0_min_wait_min"] = eff_max_wait
        warns.append(f"p0_min_wait_min={eff_min_wait:g} > p0_max_wait_min={eff_max_wait:g} -> clamped to {eff_max_wait:g}")
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
# A label sets at its threshold but clears only once the reading is this far back past it, and it never
# eases to a milder label before it has been shown this long: a reading sitting on a threshold gives one
# change, not one a minute.
SAFETY_BAND_VWC = 1.0  # VWC points
SAFETY_BAND_EC = 0.2  # mS/cm
SAFETY_HOLD_MIN = 5.0


def _safety_rank(label):
    return 2 if label in _SYS_UNSAFE else (1 if label in _SYS_WARN else 0)


def zone_safety_status(vwc, ec, field_capacity, max_ec, prev=None, held_min=None):
    """PURE. Per-zone safety label (safe / over_saturated / ec_limit_exceeded /
    approaching_saturation / approaching_ec_limit). vwc/ec may be None (blind).
    `prev` is the label shown now and `held_min` the minutes it has been shown; with neither, the
    plain label at the thresholds."""

    def band(label, width):
        return width if label == prev else 0

    if vwc is not None and field_capacity and vwc >= field_capacity - band("over_saturated", SAFETY_BAND_VWC):
        label = "over_saturated"
    elif ec is not None and max_ec and ec >= max_ec - band("ec_limit_exceeded", SAFETY_BAND_EC):
        label = "ec_limit_exceeded"
    elif vwc is not None and field_capacity and vwc >= field_capacity - 5 - band(
        "approaching_saturation", SAFETY_BAND_VWC
    ):
        label = "approaching_saturation"
    elif ec is not None and max_ec and ec >= max_ec - 1 - band("approaching_ec_limit", SAFETY_BAND_EC):
        label = "approaching_ec_limit"
    elif ec is None or not math.isfinite(ec):
        label = "ec_unknown"
    else:
        label = "safe"
    if held_min is not None and held_min < SAFETY_HOLD_MIN and _safety_rank(label) < _safety_rank(prev):
        return prev
    return label


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
        if getattr(reason, "kind", None) == "p3_hold":
            return "Holding dryback"
        return {"P0": "Flushing", "P1": "Refilling", "P2": "Topping up", "P3": "Emergency"}.get(phase, "Watering")
    return {"P0": "Drying back", "P1": "Ramping", "P2": "Optimal", "P3": "Overnight dryback"}.get(phase, "Idle")
