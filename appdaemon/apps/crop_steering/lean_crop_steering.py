"""
Lean F2 crop-steering controller — the distilled algorithm in one file.

A minimal AppDaemon app that reproduces the master engine's agronomic behaviour
(4-phase P0->P3 state machine + per-phase irrigation + EC-steering feedback) in
~1/20th the code. It REUSES the existing crop_steering HA number/switch entities
and the apps.yaml hardware map — no integration rewrite.

SAFETY: starts in SHADOW mode. With input_boolean.lean_actuate_enabled OFF (default)
it computes + LOGS every decision but touches no hardware. Flip the flag to actuate
(only after shadow parity vs master is proven AND master is disabled in apps.yaml).

The decision core `decide()` is PURE (no HA/IO) -> unit-testable offline. That is the
bug class that bit the master engine (lock-across-await, EC divergence); here it is a
plain function you can assert over without a live HA.
"""

import dataclasses
import json
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

try:
    import appdaemon.plugins.hass.hassapi as hass
except ImportError:  # allow importing the pure decision core offline (unit tests, no AppDaemon)
    class _StubHass:
        pass

    class hass:  # type: ignore
        Hass = _StubHass

PHASES = ("P0", "P1", "P2", "P3")


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


@dataclass
class ZoneSnapshot:
    vwc: float
    ec: float
    phase: str                  # 'P0'..'P3'
    peak_vwc: float
    dryback_pct: float
    dryback_rate: float         # %/h
    shot_count: int
    phase_minutes: float
    minutes_since_shot: float
    daily_vol: float
    ec_smooth: float
    lights_on: bool
    lights_just_on: bool
    hours_to_lights_on: float
    hours_to_lights_off: float
    uptime_min: float
    feed_ec: float = 3.0          # source-water (tank) EC — for the anti-lockout dilutive-flush test
    new_grow_day: bool = False    # wall-clock fallback: True when in the lights-on window AND the daily
    #                               budget has NOT yet been reset for THIS grow-day (photoperiod). Lets
    #                               P3->P0 + the budget reset fire even if the off->on light edge was
    #                               missed (AppDaemon restart/reload across the lights-on moment).


def ec_adjust(size: float, ec: float, target: float) -> float:
    """Scale a shot by pore-EC vs target: high EC -> bigger (dilute), low EC -> smaller (conserve)."""
    if target <= 0:
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


def decide(s: ZoneSnapshot, p: ZoneParams):
    """PURE control step. Returns (new_phase, new_p2_threshold, fire, size, reason).

    Mirrors the distilled algorithm: phase transition -> EC steering (P2) ->
    irrigation decision -> the cap/EC safety subset. Gate checks that need live HA
    (dosing interlock, source-water, zone-enable) are applied in the IO shell.
    """
    phase = s.phase
    p2_thr = p.p2_threshold
    treason = ""

    # ---- PHASE TRANSITIONS (checked before irrigation) ----
    if not s.lights_on and phase != "P3":
        phase, treason = "P3", "lights-off -> P3"
    elif phase == "P3" and (s.lights_just_on or (s.lights_on and s.new_grow_day)):
        # P0 entry fires on the in-process off->on edge OR, as a wall-clock fallback, whenever we are
        # in the lights-on window and this grow-day's budget reset hasn't happened yet. The fallback
        # catches a restart/reload ACROSS the lights-on moment, which never observes the edge and
        # would otherwise strand the zone in P3 (emergency-only) on a stale daily budget all day.
        why = "lights-on -> P0" if s.lights_just_on else "new grow-day -> P0 (missed light edge)"
        phase, treason = "P0", why
    elif phase == "P0":
        if s.vwc <= p.p2_threshold:
            phase, treason = "P1", f"P0 bypass VWC {s.vwc:.0f}<=rewater {p.p2_threshold:.0f}"
        elif s.dryback_pct >= p.dryback_target:
            phase, treason = "P1", f"P0 dryback done {s.dryback_pct:.0f}%"
        elif s.phase_minutes >= p.p0_max_wait_min:
            phase, treason = "P1", f"P0 timeout {s.phase_minutes:.0f}min"
    elif phase == "P1":
        # Ramp to the ACHIEVABLE ceiling (never chase VWC above field capacity), and only
        # graduate once pore EC has also been flushed back to band — P1 pushes runoff/flush
        # before handing off to P2. max-shots / 120min remain safety escape hatches.
        p1_ceiling = min(p.p1_target, p.field_capacity)
        if s.vwc >= p1_ceiling and s.ec <= p.ec_target_p1 * 1.15:
            phase, treason = "P2", f"P1 recovered {s.vwc:.0f}>={p1_ceiling:.0f} EC ok {s.ec:.1f}"
        elif s.shot_count >= p.p1_max_shots:
            phase, treason = "P2", f"P1 max shots {s.shot_count}/{p.p1_max_shots}"
        elif s.phase_minutes >= 120:
            phase, treason = "P2", "P1 120min ceiling"
    elif phase == "P2":
        # predictive P3: only if starting dryback NOW would finish by lights-on.
        if s.uptime_min >= 10 and s.vwc >= p.p3_emergency_floor and s.hours_to_lights_off <= 3.0:
            rate = s.dryback_rate if (s.dryback_rate and s.dryback_rate > 0) else 0.1
            hours_needed = p.dryback_target / rate
            if hours_needed <= 12 and s.hours_to_lights_on <= hours_needed:
                phase, treason = "P3", f"predictive P3 (need {hours_needed:.1f}h, {s.hours_to_lights_on:.1f}h to on)"

    # ---- EC STEERING (P2 only) ----
    if phase == "P2" and p.stacking_on and p.ec_target_p2 > 0:
        if s.ec_smooth < p.ec_target_p2 * 0.90:
            p2_thr = p.p2_threshold - 1.0          # deeper dryback -> EC stacks UP
        elif s.ec_smooth > p.ec_target_p2 * 1.10:
            p2_thr = p.p2_threshold + 1.0          # water sooner -> dilute
        lo = p.p3_emergency_floor + 3.0
        hi = min(p.p1_target, p.field_capacity) - 1.0
        p2_thr = max(lo, min(hi, p2_thr))

    # ---- IRRIGATION DECISION (priority order) ----
    fire, size, ir = False, 0.0, ""

    # PRIORITY 1 — ANTI-LOCKOUT: high pore EC FLUSHES in ANY phase, it never locks out.
    # The only hard block is when a flush physically can't help (feed not dilutive, or slab full),
    # and even that self-clears the moment the feed improves or the slab dries back.
    if s.ec >= p.max_ec:
        if s.feed_ec < s.ec and s.vwc < p.field_capacity - 2.0:
            excess = max(s.ec - p.max_ec, 0.0)
            size = p.p2_shot_size * (1.5 + min(excess, 3.0) * 0.3)   # bigger flush the further over the ceiling
            fire, ir = True, f"FLUSH high EC {s.ec:.1f}>={p.max_ec:.1f} (anti-lockout)"
        else:
            why = "feed not dilutive" if s.feed_ec >= s.ec else "slab saturated"
            reason = treason + (" | " if treason else "") + f"BLOCK high EC {s.ec:.1f} — {why} (self-clears)"
            return phase, round(p2_thr, 1), False, 0.0, reason

    # PRIORITY 2 — normal per-phase rules (skipped if the anti-lockout flush already fired)
    if not fire:
        if phase == "P0":
            if p.ec_target_p0 > 0 and s.ec / p.ec_target_p0 > 2.5:
                fire, size, ir = True, 10.0, f"P0 EC flush {s.ec:.1f}"
        elif phase == "P1":
            p1_ceiling = min(p.p1_target, p.field_capacity)
            # The EC-driven runoff/flush shot uses the SAME dilutive-feed/slab-room gate as the other
            # EC-flush tiers (anti-lockout, P2 rescue): firing it with a non-dilutive/saltier feed or a
            # full slab only adds salt + water without dropping EC, so it can't help — let the 120-min
            # ceiling graduate to P2 instead. The VWC-ramp shot (vwc<ceiling) stays unconditional.
            ec_high = s.ec > p.ec_target_p1 * 1.15 and s.feed_ec < s.ec and s.vwc < p.field_capacity - 2.0
            if s.minutes_since_shot >= p.p1_time_between_min and (s.vwc < p1_ceiling or ec_high):
                raw = min(p.p1_initial + p.p1_incr * s.shot_count,
                          p.p1_initial + p.p1_incr * p.p1_max_shots)
                if s.vwc < p1_ceiling:
                    ir = f"P1 ramp VWC {s.vwc:.0f}<{p1_ceiling:.0f}"
                else:
                    ir = f"P1 flush/runoff EC {s.ec:.1f} (at ceiling {p1_ceiling:.0f})"   # cap-exempt
                fire, size = True, ec_adjust(raw, s.ec, p.ec_target_p1)
        elif phase == "P2":
            # Same dilutive-feed/slab-room gate as the anti-lockout tier: only add water for EC
            # when a flush can actually help. If EC is near-max but the feed can't dilute or the
            # slab is full, do NOT add water for the EC (no rescue, no dilute) — a plain VWC
            # top-up may still apply via the s.vwc < p2_thr path below.
            flush_ok = s.feed_ec < s.ec and s.vwc < p.field_capacity - 2.0
            if s.ec >= p.max_ec - 1.0:
                if flush_ok:
                    fire, size, ir = True, p.p2_shot_size * 1.5, f"P2 rescue flush EC {s.ec:.1f}"
                elif s.vwc < p2_thr:
                    fire, size, ir = True, ec_adjust(p.p2_shot_size, s.ec, p.ec_target_p2), f"P2 top-up VWC {s.vwc:.0f}<{p2_thr:.0f}"
            elif p.ec_target_p2 > 0 and s.ec / p.ec_target_p2 > 1.2 and flush_ok:
                fire, size, ir = True, p.p2_shot_size * 1.5, f"P2 dilute EC {s.ec:.1f}"
            elif s.vwc < p2_thr:
                fire, size, ir = True, ec_adjust(p.p2_shot_size, s.ec, p.ec_target_p2), f"P2 top-up VWC {s.vwc:.0f}<{p2_thr:.0f}"
            # low-EC alone never fires: corrected via feed strength / deeper dryback, not water.
        elif phase == "P3":
            if s.vwc < p.p3_emergency_floor:
                fire, size, ir = True, p.p3_emergency_shot, f"P3 emergency VWC {s.vwc:.0f}<{p.p3_emergency_floor:.0f}"

    # PRIORITY 3 — LIGHTS-ON WATERING WATCHDOG: backstop so no enabled zone ever starves.
    # Fires only if nothing above watered it AND it has gone watchdog_hours with no water while dry.
    if (not fire and p.watchdog_hours > 0 and s.lights_on
            and s.minutes_since_shot > p.watchdog_hours * 60.0 and s.vwc < p2_thr):
        fire, size, ir = True, p.p2_shot_size, f"WATCHDOG {s.minutes_since_shot / 60.0:.1f}h no water (VWC {s.vwc:.0f}<{p2_thr:.0f})"

    # ---- SAFETY: daily cap is a BUDGET, not a wall — emergencies (flush/watchdog/rescue) exempt ----
    if fire:
        emergency = (ir.startswith("FLUSH") or ir.startswith("WATCHDOG")
                     or "rescue" in ir or "flush" in ir or "emergency" in ir)
        if s.daily_vol >= p.max_daily_volume and not emergency:
            fire, ir = False, f"BLOCK daily-cap {s.daily_vol:.0f}/{p.max_daily_volume:.0f}L (budget; emergencies exempt)"

    reason = treason + (" | " if (treason and ir) else "") + ir
    return phase, round(p2_thr, 1), fire, round(size, 1), reason


def pick_sibling(blind_p1_target, healthy):
    """PURE. A zone whose VWC probe is dead can't decide for itself, so it COPIES a healthy sibling's
    decision this tick. Pick the recipe-closest sibling = the healthy zone whose p1_target is nearest
    the blind zone's p1_target (same ramp ceiling ⇒ same drink habit). Tie, or any need for a default,
    breaks to the LOWEST-numbered healthy zone (deterministic). `healthy` is a list of (zone, p1_target);
    returns the chosen zone, or None if there are no healthy zones."""
    best = None
    for zone, tgt in healthy:
        dist = abs(tgt - blind_p1_target)
        # strictly-less keeps the FIRST (lowest, since we sort) zone on a tie -> lowest-zone tiebreak
        if best is None or dist < best[0] or (dist == best[0] and zone < best[1]):
            best = (dist, zone)
    return best[1] if best else None


def feed_grace_ok(now_ts, last_good_ts, grace_min):
    """PURE. Is a last-known-good feed-EC reading still inside the grace window? Epoch-seconds floats.
    True iff we HAVE a good reading (last_good_ts is not None) AND it is younger than grace_min minutes.
    Never-good (last_good_ts None) -> False (nothing to fall back on -> caller fails closed)."""
    if last_good_ts is None:
        return False
    return (now_ts - last_good_ts) < grace_min * 60.0


def cross_zone_outliers(snaps):
    """PURE. snaps: {zone -> ZoneSnapshot|None}. Same room ⇒ zones should drink alike, so a zone
    getting far less water than the others is a probe/valve/delivery fault, not a happy plant.
    Coarse on purpose (strains differ): flag a zone whose daily_vol < 40% of the cross-zone median.
    Returns [(zone, reason), …]."""
    vols = [(z, s.daily_vol) for z, s in snaps.items() if s is not None]
    out = []
    if len(vols) >= 2:
        vs = sorted(v for _, v in vols)
        med = vs[len(vs) // 2]
        if med >= 5.0:                       # only meaningful once the day has real water in it
            for z, v in vols:
                if v < 0.4 * med:
                    out.append((z, f"Zone {z} {v:.0f}L vs ~{med:.0f}L on the other rows — under-drinking (probe/valve/delivery?)"))
    return out


# clamp ranges for config validation (the 12.2-EC fat-finger class). (lo, hi) per field.
_PARAM_BOUNDS = {
    "p1_target": (20.0, 85.0), "p2_threshold": (10.0, 70.0),
    "ec_target_p0": (0.5, 9.0), "ec_target_p1": (0.5, 9.0), "ec_target_p2": (0.5, 9.0),
    "dryback_target": (2.0, 60.0), "p3_emergency_floor": (10.0, 60.0),
    "field_capacity": (40.0, 90.0), "max_ec": (3.0, 15.0), "watchdog_hours": (0.0, 12.0),
    "p2_shot_size": (0.5, 20.0), "p1_initial": (0.5, 15.0), "p1_incr": (0.0, 5.0),
    "p1_max_shots": (1.0, 40.0), "p1_time_between_min": (1.0, 120.0),
    "p0_max_wait_min": (5.0, 240.0), "p3_emergency_shot": (0.5, 15.0),
    "max_daily_volume": (10.0, 2000.0),
}


def validate_params(p):
    """PURE. Clamp out-of-range params and report what was clamped. Returns (clamped_ZoneParams, [warnings])."""
    warns, fixes = [], {}
    for name, (lo, hi) in _PARAM_BOUNDS.items():
        v = getattr(p, name)
        if v < lo or v > hi:
            nv = max(lo, min(hi, v))
            if name == "p1_max_shots":
                nv = int(nv)                       # keep shot count an int after clamping
            fixes[name] = nv
            warns.append(f"{name}={v:g} out of [{lo:g},{hi:g}] → clamped to {nv:g}")
    return (dataclasses.replace(p, **fixes) if fixes else p), warns


# ---- STATUS REPUBLISH helpers (PURE) ------------------------------------------------
# Lean writes NO status sensors of its own — the whole sensor.crop_steering_* status surface
# (app_status, system_safety_status, zone_N_phase/safety_status, …) is published at RUNTIME by
# master_crop_steering_app. On cutover (master off, lean live) every one of those would freeze and
# the dashboards + the engine-error / stranded-P3 watchdog automations that key off them go blind.
# These pure helpers reproduce master's EXACT published vocabulary so lean can republish the same
# surface byte-for-byte; the thin IO method _publish_status() does the set_state (and only when lean
# is the live actuator, so it never fights master during the shadow run).
_SYS_UNSAFE = ("over_saturated", "ec_limit_exceeded")
_SYS_WARN = ("approaching_saturation", "approaching_ec_limit")


def zone_safety_status(vwc, ec, field_capacity, max_ec):
    """PURE. Per-zone safety label — byte-identical vocabulary + thresholds to master's
    _update_safety_status_entities (safe / over_saturated / ec_limit_exceeded /
    approaching_saturation / approaching_ec_limit). vwc/ec may be None (blind probe) -> not assessable
    on that axis. Order matters: the hard limits (saturated / EC ceiling) outrank the 'approaching' bands."""
    if vwc is not None and field_capacity and vwc >= field_capacity:
        return "over_saturated"
    if ec is not None and max_ec and ec >= max_ec:
        return "ec_limit_exceeded"
    if vwc is not None and field_capacity and vwc >= field_capacity - 5:
        return "approaching_saturation"
    if ec is not None and max_ec and ec >= max_ec - 1:
        return "approaching_ec_limit"
    return "safe"


def system_safety_status(zone_labels):
    """PURE. Roll the per-zone safety labels into master's system vocabulary + counts:
    returns (status, unsafe_zones, warning_zones, safe_zones) where status is 'unsafe' if any zone is
    over_saturated/ec_limit_exceeded, else 'warning' if any is approaching_*, else 'safe'."""
    labels = list(zone_labels)
    unsafe = sum(1 for s in labels if s in _SYS_UNSAFE)
    warning = sum(1 for s in labels if s in _SYS_WARN)
    status = "unsafe" if unsafe else ("warning" if warning else "safe")
    return status, unsafe, warning, max(0, len(labels) - unsafe - warning)


def zone_status_label(phase, fire, blocked, blind, reason=""):
    """PURE. Human one-liner for the f2 per-zone tile (sensor.crop_steering_zone_N_status; 'Optimal' in
    the demo). Lean-owned (master published no zone_N_status); derived from this tick's outcome so the
    operator reads intent, not a phase code. blocked = the live-gate reason (None if not gated)."""
    if blind:
        return "Probe dead — copying"
    if blocked:                                   # live gate: dosing/feed/override/zone-disabled
        return ("Blocked: " + str(blocked))[:80]
    if "BLOCK" in (reason or ""):                 # decide()-level block (high-EC non-dilutive / daily-cap)
        return "Blocked — EC/cap"
    if fire:
        return {"P0": "Flushing", "P1": "Refilling", "P2": "Topping up", "P3": "Emergency"}.get(phase, "Watering")
    return {"P0": "Drying back", "P1": "Ramping", "P2": "Optimal", "P3": "Overnight dryback"}.get(phase, "Idle")


# ============================================================
# IO SHELL  (AppDaemon app — all HA coupling lives here, thin)
# ============================================================
class LeanCropSteering(hass.Hass):

    def initialize(self):
        # SYNC app on purpose: AppDaemon 4.x runs async apps with COROUTINE API calls (get_state/call_service/
        # set_state must be awaited). Lean's IO reads return values directly, so it must be a sync app — in
        # which AppDaemon's API calls are synchronous and value-returning. (An async app silently turned every
        # self.get_state() into an un-awaited Task -> float(Task) -> None -> every probe blind.)
        cfg = self.args or {}
        # zone -> raw probes (F2 defaults; override via apps.yaml args.zones)
        self.zones = cfg.get("zones", {
            1: {"vwc": "sensor.f2_row_1_vwc",    "ec": "sensor.f2_row_1_pwec"},
            2: {"vwc": "sensor.veg_sdi12_vwc_2", "ec": "sensor.veg_sdi12_ec_2"},
            3: {"vwc": "sensor.veg_sdi12_vwc",   "ec": "sensor.veg_sdi12_ec"},
        })
        self.hw = cfg.get("hardware", {
            "pump": "switch.veg_main_pump",
            "mainline": "switch.espoe_irrigation_relay_2_3",
            "valves": {1: "switch.f2_row1", 2: "switch.f2_row2", 3: "switch.f2_row3"},
        })
        self.lights_on_hour = cfg.get("lights_on_hour", 10)
        self.lights_off_hour = cfg.get("lights_off_hour", 22)
        self.actuate_flag = cfg.get("actuate_flag", "input_boolean.lean_actuate_enabled")
        self.flow_lps = float(cfg.get("flow_lps", 0.067))   # ~4 L/min/dripper -> L/s for duration calc
        self.substrate_l = float(cfg.get("substrate_l", 6))
        self._start = datetime.now()
        # CHANGE 1: a zone whose VWC probe is dead ("blind") copies a healthy sibling's WHEN+HOW-MUCH
        # rather than skipping (skip = dries back = the bad outcome). If EVERY zone is blind, each runs a
        # safe modest top-up on this interval (min since its last shot) so the room never fully starves.
        self.blind_fallback_min = float(cfg.get("blind_fallback_min", 90))
        self._blind_zones = set()        # zones currently blind (for first-time-blind throttled alerting)
        # CHANGE 2: the SHARED source-water feed-EC probe (sensor.atlas_legacy_1_ec) can go stale/dead.
        # Track the last reading that was a number IN the configured [ec_min, ec_max] band; inside a grace
        # window we run on that last-known-good instead of hard-blocking the whole room on one dead probe.
        self.feed_grace_min = float(cfg.get("feed_grace_min", 30))
        self._feed_last_good_value = None      # float — last in-band feed EC
        self._feed_last_good_time = None       # datetime — when we last saw it

        # State persists across AppDaemon restarts / file-watch reloads (I6): an in-memory-only
        # daily_vol would zero on every reload mid-photoperiod and let the daily-cap be defeated
        # once per reload (unbounded over-irrigation). daily_vol is reset ONLY on the real P3->P0
        # lights-on transition (loop()), never on process start.
        self._state_path = cfg.get("state_file",
                                   os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                "lean_crop_steering_state.json"))
        self.state = self._load_state()
        self._busy = False
        self._alerted = {}                       # alert-key -> last-fired time (30-min throttle)
        self._activity = []                      # newest-first event log republished to sensor.crop_steering_activity_log
        # SHADOW observability: dump each tick's decisions to a JSON next to this file so a shadow run can be
        # watched/troubleshot over ssh WITHOUT AppDaemon stdout access (shadow leaves no HA-state trace —
        # the republisher is actuate-gated). Always written, shadow OR live; best-effort, never breaks the loop.
        self._shadow_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lean_shadow.json")
        self._write_shadow(self._start, self._lights_on(self._start), False, {}, {}, note="initialized")
        self.run_every(self.loop, "now+10", 60)
        self.log("🌿 Lean crop steering initialized (SHADOW until %s is on)" % self.actuate_flag)

    # ---------- durable per-zone state (survives restart / file-watch reload) ----------
    def _fresh_zone(self):
        return {"phase": "P2", "peak": 0.0, "win": [], "last_shot": None,
                "shots": 0, "daily_vol": 0.0, "ec_smooth": None,
                "last_phase_change": datetime.now(),
                "ec_offset": 0.0, "last_ec_steer": None,
                "last_daily_reset": None}      # grow-day date the budget was last zeroed (wall-clock reset stamp)

    def _load_state(self):
        """Restore daily_vol/shots/peak/last_shot/phase/last_phase_change from disk so a mid-photoperiod
        reload cannot zero the daily budget. Missing/corrupt file -> fresh state (fail safe, never crash)."""
        state = {z: self._fresh_zone() for z in self.zones}
        try:
            with open(self._state_path, "r", encoding="utf-8") as fh:
                saved = json.load(fh)
        except (FileNotFoundError, ValueError, OSError):
            return state
        restored = 0
        for z in self.zones:
            d = saved.get(str(z)) or saved.get(z)     # JSON keys are strings
            if not isinstance(d, dict):
                continue
            st = state[z]
            for k in ("phase", "peak", "shots", "daily_vol", "ec_smooth", "ec_offset"):
                if k in d and d[k] is not None:
                    st[k] = d[k]
            for k in ("last_shot", "last_phase_change", "last_ec_steer"):
                iso = d.get(k)
                if iso:
                    try:
                        st[k] = datetime.fromisoformat(iso)
                    except (ValueError, TypeError):
                        pass
            ldr = d.get("last_daily_reset")           # grow-day reset stamp persists as an ISO date
            if ldr:
                try:
                    st["last_daily_reset"] = date.fromisoformat(ldr)
                except (ValueError, TypeError):
                    pass
            restored += 1
        if restored:
            self.log(f"↻ restored persisted state for {restored} zone(s) from {self._state_path}")
        return state

    def _save_state(self):
        """Atomically persist the durable fields. Volatile sample window (win) is intentionally dropped
        (it rebuilds in minutes and isn't part of the safety budget)."""
        out = {}
        for z, st in self.state.items():
            ls, lpc = st.get("last_shot"), st.get("last_phase_change")
            les, ldr = st.get("last_ec_steer"), st.get("last_daily_reset")
            out[str(z)] = {
                "phase": st.get("phase"), "peak": st.get("peak"),
                "shots": st.get("shots"), "daily_vol": st.get("daily_vol"),
                "ec_smooth": st.get("ec_smooth"),
                "ec_offset": float(st.get("ec_offset") or 0.0),
                "last_shot": ls.isoformat() if isinstance(ls, datetime) else None,
                "last_phase_change": lpc.isoformat() if isinstance(lpc, datetime) else None,
                "last_ec_steer": les.isoformat() if isinstance(les, datetime) else None,
                "last_daily_reset": ldr.isoformat() if isinstance(ldr, date) else None,
            }
        try:
            tmp = self._state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(out, fh)
            os.replace(tmp, self._state_path)
        except OSError as e:
            self.log(f"state save failed ({e})", level="WARNING")

    # ---------- alerts (phone + persistent_notification -> the f2 beefy banner) ----------
    def _alert(self, key, title, message):
        now = datetime.now()
        last = self._alerted.get(key)
        if last and (now - last).total_seconds() < 1800:
            return
        self._alerted[key] = now
        self.log(f"🔔 {title}: {message}")
        try:
            self.call_service("persistent_notification/create", title=title, message=message,
                              notification_id=f"lean_{key}")
        except Exception:
            pass
        try:
            self.call_service("notify/mobile_app_s23ultra", title=title, message=message)
        except Exception:
            pass

    # ---------- helpers ----------
    def _num(self, entity, default):
        try:
            v = self.get_state(entity)
            return float(v) if v not in (None, "unknown", "unavailable", "") else float(default)
        except Exception:
            return float(default)

    def _zone_num(self, zone, suffix, default):
        per = f"number.crop_steering_zone_{zone}_{suffix}"
        glob = f"number.crop_steering_{suffix}"
        if self.entity_exists(per):
            return self._num(per, default)
        return self._num(glob, default)

    def _on(self, entity, default=False):
        try:
            v = self.get_state(entity)
            if v in (None, "unknown", "unavailable", ""):
                return default
            return str(v).lower() in ("on", "true", "open", "1")
        except Exception:
            return default

    def _read_sensor(self, entity, lo=0.0, hi=200.0, max_age_min=20):
        """Read a probe with two guards. Returns the value, or None if it should be rejected.

        (a) RANGE: a parsed value outside [lo, hi] is rejected (None) — fat-finger / garbage.
        (b) FRESHNESS (best-effort): read the entity's last_changed; if it parses and is older
            than max_age_min, reject (None). If ANY part of the freshness check fails to parse or
            raises, do NOT reject — fall through to returning the value (never false-kill a live probe)."""
        try:
            v = self.get_state(entity)
            if v in (None, "unknown", "unavailable", ""):
                return None
            f = float(v)
        except Exception:
            return None
        if f < lo or f > hi:
            return None
        try:
            lc = self.get_state(entity, attribute="last_changed")
            if lc:
                ts = datetime.fromisoformat(str(lc).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    # HA stores last_changed in UTC; AppDaemon returns it tz-NAIVE. Comparing that against a
                    # naive LOCAL datetime.now() is off by the box's UTC offset — on a +12 (NZ) box every live
                    # probe read as 12 h stale and the whole engine went blind. Treat the naive HA stamp as UTC.
                    ts = ts.replace(tzinfo=timezone.utc)
                if (datetime.now(timezone.utc) - ts).total_seconds() > max_age_min * 60.0:
                    return None
        except Exception:
            pass                                   # freshness check failed — never false-kill a live probe
        return f

    def _read_feed_ec(self):
        """CHANGE 2: read the shared source-water feed EC (sensor.atlas_legacy_1_ec) AND, when it reads as
        a number inside the configured [ec_min, ec_max] band, stamp it as last-known-good. Returns the LIVE
        value (or None if stale/unreadable). The last-good cache lets _blocked()/_snapshot() ride out a
        transient probe dropout for `feed_grace_min` minutes instead of hard-blocking the whole room.
        If no band is configured (ec_min==ec_max==0) the gate is disarmed, so any numeric read is 'good'."""
        feed = self._read_sensor("sensor.atlas_legacy_1_ec", lo=0, hi=20)
        if feed is not None:
            lo = self._num("number.crop_steering_irrigation_ec_min", 0)
            hi = self._num("number.crop_steering_irrigation_ec_max", 0)
            in_band = ((lo <= 0 or feed >= lo) and (hi <= 0 or feed <= hi))
            if in_band:
                self._feed_last_good_value = feed
                self._feed_last_good_time = datetime.now()
        return feed

    def _veg(self, zone):
        sel = self.get_state(f"select.crop_steering_zone_{zone}_steering_mode") or \
              self.get_state("select.crop_steering_growth_stage") or "Generative"
        return str(sel).lower().startswith("veg")

    def _lights_on(self, now):
        h = now.hour + now.minute / 60.0
        on, off = self.lights_on_hour, self.lights_off_hour
        return (on <= h < off) if on <= off else (h >= on or h < off)

    def _hours_to(self, now, target_hour):
        h = now.hour + now.minute / 60.0
        d = target_hour - h
        return d if d >= 0 else d + 24.0

    def _grow_day_start(self, now):
        """The calendar DATE on which the current photoperiod (grow-day) began at lights-on. The daily
        budget belongs to this grow-day, not the calendar day. Used for the wall-clock P0-reset fallback
        (mirrors master_crop_steering_app's grow_day_start) so a reload across lights-on still resets.
        For both a normal day-schedule (on<off) and an overnight one (on>off), the photoperiod running
        now began at today's lights-on iff we're at/after lights-on; before that we're still inside
        yesterday's photoperiod (its lights-on was yesterday), so the grow-day is yesterday's date."""
        h = now.hour + now.minute / 60.0
        started_today = h >= self.lights_on_hour
        return now.date() if started_today else (now - timedelta(days=1)).date()

    # ---------- per-zone snapshot + params ----------
    def _params(self, zone):
        # EVERY field is per-zone-addressable (per-zone entity first, global as a template default).
        # Each zone is an independent recipe — different strain/cultivar/substrate is fine.
        veg = self._veg(zone)
        sfx = "veg" if veg else "gen"
        # Operator BASE threshold + the persisted in-memory EC-steer offset = the EFFECTIVE
        # threshold decide() steers around. We never write the operator entity (DESIGN #1); the
        # offset is bounded and resets daily, so EC-steer can't ratchet the operator's floor down.
        base = self._zone_num(zone, "p2_vwc_threshold", 45)
        raw = ZoneParams(
            p1_target=self._zone_num(zone, "p1_target_vwc", 60),
            p2_threshold=base + float(self.state[zone].get("ec_offset", 0.0)),
            p2_shot_size=self._zone_num(zone, "p2_shot_size", 5),
            p1_initial=self._zone_num(zone, "p1_initial_shot_size", 2),
            p1_incr=self._zone_num(zone, "p1_shot_size_increment", 0.5),
            p1_max_shots=int(self._zone_num(zone, "p1_maximum_shots", 12)),
            p1_time_between_min=self._zone_num(zone, "p1_time_between_shots", 15),
            dryback_target=self._zone_num(zone, f"{'vegetative' if veg else 'generative'}_dryback_target", 20),
            p0_max_wait_min=self._zone_num(zone, "p0_maximum_wait_time", 45),
            ec_target_p0=self._zone_num(zone, f"ec_target_{sfx}_p0", 4),
            ec_target_p1=self._zone_num(zone, f"ec_target_{sfx}_p1", 5),
            ec_target_p2=self._zone_num(zone, f"ec_target_{sfx}_p2", 6),
            p3_emergency_floor=self._zone_num(zone, "p3_emergency_vwc_threshold", 40),
            p3_emergency_shot=self._zone_num(zone, "p3_emergency_shot_size", 2),
            max_daily_volume=self._zone_num(zone, "max_daily_volume", 300),
            field_capacity=self._zone_num(zone, "field_capacity", 70),
            max_ec=self._zone_num(zone, "maximum_ec", 9),
            stacking_on=self._on("switch.crop_steering_ec_stacking_enabled", False),
            watchdog_hours=self._zone_num(zone, "watchdog_hours", 3),
        )
        p, warns = validate_params(raw)        # clamp the 12.2-fat-finger class + alert what was clamped
        for w in warns:
            self._alert(f"cfg_z{zone}_{w.split('=')[0]}", "Lean config clamp", f"Zone {zone}: {w}")
        return p

    def _snapshot(self, zone, now, lights_on, lights_just_on):
        st = self.state[zone]
        vwc = self._read_sensor(self.zones[zone]["vwc"], lo=0, hi=100)
        ec = self._read_sensor(self.zones[zone]["ec"], lo=0, hi=20)
        if vwc is None:
            # CHANGE 1: VWC probe dead -> this zone is "blind". Return its PARAMS (not None) so the loop's
            # PASS 2 can still find a recipe-similar sibling (needs p1_target) and run the safe fallback
            # (needs p2_shot_size). Leave durable state untouched — a blind zone can't track peak/phase.
            return None, self._params(zone)
        if vwc > st["peak"]:
            st["peak"] = vwc
        st["win"] = (st["win"] + [(now, vwc)])[-30:]      # ~30 samples
        # dryback rate: slope over the window, %/h (positive = drying)
        rate = 0.0
        if len(st["win"]) >= 3:
            t0, v0 = st["win"][0]
            dt_h = (now - t0).total_seconds() / 3600.0
            if dt_h > 0:
                rate = max(0.0, (v0 - vwc) / dt_h)
        if ec is not None:
            st["ec_smooth"] = ec if st["ec_smooth"] is None else 0.3 * ec + 0.7 * st["ec_smooth"]
        # CHANGE 2: feed EC for decide() = live if readable; else last-known-good if still in grace;
        # else the existing 3.0 default. _read_feed_ec refreshes last-good when the live read is in band.
        feed_live = self._read_feed_ec()
        if feed_live is not None:
            feed_ec = feed_live
        elif feed_grace_ok(now.timestamp(),
                           self._feed_last_good_time.timestamp() if self._feed_last_good_time else None,
                           self.feed_grace_min):
            feed_ec = self._feed_last_good_value
        else:
            feed_ec = None
        # Wall-clock new-grow-day signal for the P3->P0 + budget-reset fallback (decide() stays pure):
        # True while we're in the lights-on window AND this grow-day's reset hasn't been stamped yet, so
        # P3 advances to P0 even if the in-process off->on light edge was missed (restart across lights-on).
        gds = self._grow_day_start(now)
        ldr = st.get("last_daily_reset")
        new_grow_day = lights_on and (ldr is None or ldr < gds)
        snap = ZoneSnapshot(
            vwc=vwc, ec=(ec if ec is not None else 0.0), phase=st["phase"],
            peak_vwc=st["peak"], dryback_pct=((st["peak"] - vwc) / st["peak"] * 100 if st["peak"] > 0 else 0),
            dryback_rate=rate, shot_count=st["shots"],
            phase_minutes=(now - st["last_phase_change"]).total_seconds() / 60.0,
            minutes_since_shot=((now - st["last_shot"]).total_seconds() / 60.0 if st["last_shot"] else 1e9),
            daily_vol=st["daily_vol"], ec_smooth=(st["ec_smooth"] if st["ec_smooth"] is not None else 0.0),
            lights_on=lights_on, lights_just_on=lights_just_on,
            hours_to_lights_on=self._hours_to(now, self.lights_on_hour),
            hours_to_lights_off=self._hours_to(now, self.lights_off_hour),
            uptime_min=(now - self._start).total_seconds() / 60.0,
            feed_ec=(feed_ec if feed_ec is not None else 3.0),
            new_grow_day=new_grow_day,
        )
        return snap, self._params(zone)

    # ---------- live-state gates (the bits decide() can't see) ----------
    def _blocked(self, zone):
        if not self._on("switch.crop_steering_system_enabled", False):
            return "system disabled"
        if not self._on("switch.crop_steering_auto_irrigation_enabled", False):
            return "auto-irrigation disabled"
        if not self._on(f"switch.crop_steering_zone_{zone}_enabled", True):
            return "zone disabled"
        if self._on(f"switch.crop_steering_zone_{zone}_manual_override", False):
            return "manual override"
        for f in ("input_boolean.nutrient_dosing_active", "input_boolean.f2_fill_mode",
                  "input_boolean.f2_flush_mode", "switch.tank_filling"):
            if self._on(f, False):
                return f"dosing/fill ({f.split('.')[-1]})"
        feed = self._read_feed_ec()        # live read; also refreshes last-known-good when in band
        lo = self._num("number.crop_steering_irrigation_ec_min", 0)
        hi = self._num("number.crop_steering_irrigation_ec_max", 0)
        if lo > 0 or hi > 0:
            # Source-water bounds are configured -> the feed-EC gate is armed.
            if feed is None:
                # CHANGE 2: a transient probe dropout shouldn't slam the whole room shut. Ride on the
                # last-known-good reading for a grace window (feed_grace_min); only past grace do we
                # fail closed. _read_sensor returns None on stale (>max_age) / garbage.
                if feed_grace_ok(datetime.now().timestamp(),
                                 self._feed_last_good_time.timestamp() if self._feed_last_good_time else None,
                                 self.feed_grace_min):
                    self._alert("feed_stale", "Feed probe stale — running on last-known-good",
                                f"sensor.atlas_legacy_1_ec unreadable; using last-known-good EC "
                                f"{self._feed_last_good_value:.1f} (grace {self.feed_grace_min:.0f}min).")
                    return None
                self._alert("feed_dead", "Feed probe dead — holding irrigation",
                            f"sensor.atlas_legacy_1_ec dead >{self.feed_grace_min:.0f}min with no good "
                            f"reading in grace — feed gate fail-closed, holding all zones.")
                return f"source-water EC dead >{self.feed_grace_min:.0f}min — holding (fail-closed)"
            if (lo > 0 and feed < lo) or (hi > 0 and feed > hi):
                # A NUMERIC but out-of-band feed is bad water, not a probe failure -> block as before.
                return f"source-water EC {feed:.1f} out of [{lo:g},{hi:g}]"
        return None

    @staticmethod
    def _step_ec_offset(cur, ec_smooth, ec_target_p2, base):
        """PURE. One 30-min step of the EC-steer offset. PROPORTIONAL off BASE, not an integrator:
        a SUSTAINED EC error parks the offset at ±1 (≈1 VWC-point nudge); an IN-BAND EC decays it back
        toward 0. Moves at most ±1 per call toward the target, then clamps to ±20% of base. Direction
        mirrors decide()'s EC-steer (ec_smooth vs ec_target_p2 ±10%). This is the fix for the old ratchet
        where the offset integrated to the ±20% rail under any steady deviation."""
        if ec_target_p2 <= 0:
            return cur
        if ec_smooth < ec_target_p2 * 0.90:
            target = -1.0                        # low EC -> deeper dryback (threshold DOWN)
        elif ec_smooth > ec_target_p2 * 1.10:
            target = 1.0                         # high EC -> water sooner (threshold UP)
        else:
            target = 0.0                         # in band -> decay the offset away
        step = max(-1.0, min(1.0, target - cur))   # at most ±1 VWC-point per tick (no integration)
        return max(-0.20 * base, min(0.20 * base, cur + step))

    def _minutes_since_shot(self, st, now):
        """Minutes since this zone's last shot (1e9 if it has never fired). Used for a BLIND zone's
        fallback cadence, where there's no snapshot to read minutes_since_shot from."""
        ls = st.get("last_shot")
        return (now - ls).total_seconds() / 60.0 if ls else 1e9

    # ---------- main loop ----------
    def loop(self, kwargs):
        if self._busy:
            return
        now = datetime.now()
        lights_on = self._lights_on(now)
        actuate = self._on(self.actuate_flag, False)
        was_off = not getattr(self, "_was_lights_on", lights_on)
        lights_just_on = lights_on and was_off

        # PASS 1 — snapshot every zone. A zone with a readable VWC is HEALTHY: run decide() and the
        # healthy-only state mutations (phase transition, EC-steer offset), and stash its decision.
        # A zone with an unreadable VWC is BLIND: it can't decide for itself this tick (no peak/phase),
        # so we only stash its params + cadence and resolve its decision in PASS 2 by COPYING a sibling.
        snaps = {}                 # zone -> ZoneSnapshot (healthy only, for the cross-zone outlier check)
        decisions = {}             # zone -> (fire, size, reason)  (resolved this tick)
        healthy = []               # [(zone, p1_target)] for sibling selection
        blind = []                 # [(zone, params)]
        params = {}                # zone -> ZoneParams (all zones)
        for zone in self.zones:
            st = self.state[zone]
            snap, p = self._snapshot(zone, now, lights_on, lights_just_on)
            params[zone] = p
            if snap is None:
                # BLIND: VWC probe dead. Don't touch durable state; defer the decision to PASS 2.
                blind.append((zone, p))
                continue
            snaps[zone] = snap
            healthy.append((zone, p.p1_target))
            new_phase, new_thr, fire, size, reason = decide(snap, p)

            if new_phase != st["phase"]:
                if new_phase == "P0":
                    st["daily_vol"], st["shots"], st["peak"] = 0.0, 0, snap.vwc  # daily budget resets ONLY here
                    st["ec_offset"], st["last_ec_steer"] = 0.0, None  # EC-steer offset clears daily -> no day-by-day ratchet
                    st["last_daily_reset"] = self._grow_day_start(now)  # stamp this grow-day so the wall-clock
                    #                                                     fallback self-clears (no re-reset until tomorrow)
                if new_phase == "P1":
                    st["shots"] = 0
                st["phase"] = new_phase
                st["last_phase_change"] = now
                self._save_state()                       # persist phase + (P0) the budget/offset reset
            # EC-steer is an in-memory OFFSET on top of the operator's base threshold — we never write
            # the operator entity (DESIGN #1). The offset is PROPORTIONAL off BASE, not an integrator off
            # the effective threshold: a sustained EC error parks the offset at ±1 (≈1 VWC-point nudge),
            # an in-band EC decays it back toward 0 — it can drift but never ratchet to the clamp rail.
            # Direction mirrors decide()'s EC-steer (ec_smooth vs ec_target_p2 ±10%). Moves at most once
            # per 30 min, by at most one step toward the ±1 target, then clamps to ±20% of base.
            if p.stacking_on and st["phase"] == "P2" and p.ec_target_p2 > 0:
                base = self._zone_num(zone, "p2_vwc_threshold", 45)
                les = st.get("last_ec_steer")
                if les is None or (now - les).total_seconds() >= 1800:
                    st["ec_offset"] = self._step_ec_offset(
                        float(st.get("ec_offset", 0.0)), snap.ec_smooth, p.ec_target_p2, base)
                    st["last_ec_steer"] = now
                    self._save_state()
            decisions[zone] = (fire, size, reason)

        # PASS 2 — resolve BLIND zones (VWC probe dead). A blind zone never SKIPS (skip = dries back =
        # the bad outcome). It mirrors WHEN + HOW-MUCH from the recipe-closest healthy sibling this tick;
        # if EVERY zone is blind it runs a safe modest top-up on a fallback cadence. The copied/fallback
        # FIRE still goes through the blind zone's OWN live gates (_blocked) and OWN valve/counters (the
        # act path below) — it borrows the sibling's timing + size, not its gates or hardware.
        for zone, p in blind:
            st = self.state[zone]
            if healthy:
                sib = pick_sibling(p.p1_target, healthy)
                s_fire, s_size, _ = decisions[sib]
                decisions[zone] = (s_fire, s_size, f"COPY Z{sib} (VWC probe dead)")
                if zone not in self._blind_zones:        # first time blind -> throttled alert
                    self._alert(f"blind_z{zone}", "Zone moisture probe dead — copying sibling",
                                f"Zone {zone} moisture probe dead — copying Zone {sib}.")
            else:
                # every zone blind -> safe fallback schedule: a modest top-up on the fallback interval
                mss = self._minutes_since_shot(st, now)
                f_fire = mss >= self.blind_fallback_min
                decisions[zone] = (f_fire, p.p2_shot_size, "FALLBACK schedule (no live probe)")
                if zone not in self._blind_zones:
                    self._alert(f"blind_z{zone}", "Zone moisture probe dead — no live sibling",
                                f"Zone {zone} moisture probe dead and no healthy sibling — safe fallback "
                                f"schedule ({self.blind_fallback_min:.0f}min top-ups).")
            self._blind_zones.add(zone)
        # a zone that came back to life clears its blind flag (so a future blackout re-alerts)
        self._blind_zones = {z for z in self._blind_zones if z not in snaps}

        # ACT — apply each resolved decision through the zone's OWN live gates + hardware.
        pub = {}                       # zone -> per-zone status record for the republisher
        for zone in self.zones:
            if zone not in decisions:
                self.log(f"Z{zone}: VWC sensor unreadable, no decision — skip", level="WARNING")
                continue
            fire, size, reason = decisions[zone]
            block = self._blocked(zone) if fire else None     # ONE live-gate read; reused for publish
            self._act_zone(zone, params[zone], snaps.get(zone), decisions[zone], block, actuate, lights_on, now)
            snap = snaps.get(zone)
            pub[zone] = {"phase": self.state[zone]["phase"], "vwc": snap.vwc if snap else None,
                         "ec": snap.ec if snap else None, "fire": fire, "block": block,
                         "reason": reason, "blind": snap is None, "p": params[zone]}

        # cross-zone outlier detector — same room ⇒ zones should drink alike; flag the under-driller
        for z, why in cross_zone_outliers(snaps):
            self._alert(f"xzone_{z}", "Zone under-drinking vs siblings", why)
        # republish the master status surface (sensor.crop_steering_*) so the dashboards + the
        # engine-error / stranded-P3 watchdog automations survive cutover. No-op in SHADOW: master still
        # owns these entities then, so writing them would fight it (see _publish_status's actuate gate).
        self._publish_status(pub, actuate, now)
        self._write_shadow(now, lights_on, actuate, pub, decisions)
        self._was_lights_on = lights_on

    def _write_shadow(self, now, lights_on, actuate, pub, decisions, note=None):
        """Dump this tick's per-zone decisions to lean_shadow.json (atomic, best-effort). The ssh-tailable
        window into a shadow run: mode, lights, and each zone's phase/vwc/ec/fire/size/reason/block."""
        try:
            zones = {}
            for z in sorted(decisions):
                d = pub.get(z, {})
                fire, size, reason = decisions[z]
                zones[str(z)] = {"phase": d.get("phase"), "vwc": d.get("vwc"), "ec": d.get("ec"),
                                 "fire": fire, "size": size, "reason": reason,
                                 "blind": d.get("blind"), "block": d.get("block")}
            out = {"ts": now.isoformat(), "mode": "LIVE" if actuate else "SHADOW",
                   "lights_on": lights_on, "zones": zones}
            if note:
                out["note"] = note
            # one-shot IO diagnostic: what does get_state actually return in-app for a probe + a custom-
            # component switch, and how does the freshness math land? (master notes get_state can't see some
            # custom-component entities.) Reveals null-cause during a shadow run; cheap, trim once resolved.
            try:
                z1 = self.zones[sorted(self.zones)[0]]["vwc"]
                out["_diag"] = {
                    "z1_vwc_entity": z1,
                    "z1_vwc_raw": repr(self.get_state(z1)),
                    "z1_vwc_last_changed": repr(self.get_state(z1, attribute="last_changed")),
                    "sys_enabled_raw": repr(self.get_state("switch.crop_steering_system_enabled")),
                    "now_local": datetime.now().isoformat(),
                    "now_utc": datetime.now(timezone.utc).isoformat(),
                }
            except Exception as e:
                out["_diag"] = {"err": repr(e)}
            tmp = self._shadow_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(out, fh, indent=1)
            os.replace(tmp, self._shadow_path)
        except Exception as e:
            self.log(f"shadow status write failed ({e})", level="WARNING")

    # ---------- status republisher (the master sensor.crop_steering_* surface) ----------
    def _publish_status(self, pub, actuate, now):
        """Republish the master status surface from THIS tick's per-zone records so the f2 + native
        dashboards and the engine-error / stranded-P3 watchdog automations keep working once lean owns the
        grow. Vocabulary is byte-identical to master (zone_safety_status / system_safety_status / app_status
        strings + 'P0'..'P3' phases), so the consumers need no change.

        Gated on ACTUATE: in SHADOW the master app still runs and owns these entities — writing them would
        stomp master every tick and corrupt the parity comparison. Lean publishes only when it is the live
        actuator (master disabled in apps.yaml). Best-effort: a publish failure must never break the loop."""
        if not actuate or not pub:
            return
        try:
            zone_labels = []
            for zone in sorted(pub):
                d = pub[zone]
                p = d["p"]
                saf = zone_safety_status(d["vwc"], d["ec"], p.field_capacity, p.max_ec)
                zone_labels.append(saf)
                self.set_state(f"sensor.crop_steering_zone_{zone}_phase", state=d["phase"],
                               attributes={"friendly_name": f"Zone {zone} Phase", "icon": "mdi:water-circle",
                                           "reason": d["reason"], "engine": "lean"})
                self.set_state(f"sensor.crop_steering_zone_{zone}_safety_status", state=saf,
                               attributes={"vwc": d["vwc"], "ec": d["ec"],
                                           "field_capacity": p.field_capacity, "max_ec_limit": p.max_ec})
                self.set_state(f"sensor.crop_steering_zone_{zone}_status",
                               state=zone_status_label(d["phase"], d["fire"], d["block"], d["blind"], d["reason"]),
                               attributes={"reason": d["reason"]})
                # last-irrigation tile: lean's last_shot maps 1:1 to master's last_irrigation_app (exact
                # semantics + ISO/timestamp). (daily_water_app / irrigation_count_app are NOT republished:
                # lean's daily_vol unit and per-phase shot count don't match master's litres/daily-count —
                # publishing them would show a wrong number, so those f2 tiles stay blank by design.)
                ls = self.state[zone].get("last_shot")
                if ls is not None:
                    self.set_state(f"sensor.crop_steering_zone_{zone}_last_irrigation_app", state=ls.isoformat(),
                                   attributes={"friendly_name": f"Zone {zone} Last Irrigation",
                                               "device_class": "timestamp", "icon": "mdi:history"})
            sys_stat, unsafe, warning, safe = system_safety_status(zone_labels)
            self.set_state("sensor.crop_steering_system_safety_status", state=sys_stat,
                           attributes={"unsafe_zones": unsafe, "warning_zones": warning, "safe_zones": safe})

            # app-level summary + liveness (the f2 header + 'alive' indicator read these)
            summary = ", ".join(f"Z{z}:{pub[z]['phase']}" for z in sorted(pub))
            self.set_state("sensor.crop_steering_app_current_phase", state=summary,
                           attributes={"friendly_name": "Zone Phases", "icon": "mdi:water-circle"})
            # app_status='error' surfaces a whole-room feed-hold to the engine-error watchdog automation.
            room_held = any(d["block"] and "fail-closed" in str(d["block"]) for d in pub.values())
            app_state = "error" if room_held else ("irrigating" if self._busy else "safe_idle")
            self.set_state("sensor.crop_steering_app_status", state=app_state,
                           attributes={"friendly_name": "Crop Steering App Status", "icon": "mdi:water-sync",
                                       "engine": "lean", "mode": "LIVE", "updated": now.isoformat()})
            self.set_state("sensor.crop_steering_system_state",
                           state=("active" if self._on("switch.crop_steering_system_enabled", False) else "disabled"),
                           attributes={"engine": "lean"})
            self.set_state("sensor.crop_steering_ai_heartbeat", state="healthy",
                           attributes={"engine": "lean", "last_beat": now.isoformat()})

            # current decision + activity log (newest first — the f2 feed calls this "ground truth")
            fired = [f"Z{z} {d['phase']} {d['reason']}" for z, d in sorted(pub.items()) if d["fire"] and not d["block"]]
            held = [f"Z{z} {d['phase']} {d['block'] or d['reason']}"
                    for z, d in sorted(pub.items()) if d["block"] or "BLOCK" in d["reason"]]
            decision_line = fired[0] if fired else (held[0] if held else "Holding — all zones in band")
            self.set_state("sensor.crop_steering_current_decision", state=decision_line[:255],
                           attributes={"fired": fired, "blocked": held, "timestamp": now.isoformat()})
            for line in fired + held:
                self._activity.insert(0, f"{now.strftime('%H:%M')} {line}"[:120])
            del self._activity[60:]
            # master publishes the feed under the 'feed' attribute = newline-joined newest-first, and f2
            # reads attributes.feed (splitting on "\n"); match that EXACTLY or the activity card collapses
            # to a single line on cutover (the newest event only).
            self.set_state("sensor.crop_steering_activity_log",
                           state=(self._activity[0] if self._activity else "idle")[:255],
                           attributes={"feed": "\n".join(self._activity[:50]),
                                       "event_count": len(self._activity)})

            # coarse next-irrigation estimate: earliest (last_shot + cooldown) over un-gated P1/P2 zones
            nxt = None
            for zone, d in pub.items():
                if d["block"] or d["phase"] not in ("P1", "P2"):
                    continue
                ls = self.state[zone].get("last_shot")
                due = (ls + timedelta(minutes=d["p"].p1_time_between_min)) if ls else now
                if due < now:
                    due = now
                if nxt is None or due < nxt:
                    nxt = due
            self.set_state("sensor.crop_steering_app_next_irrigation",
                           state=(nxt.isoformat() if nxt else "unknown"),
                           attributes={"friendly_name": "Next Irrigation Time", "icon": "mdi:clock-outline",
                                       "device_class": "timestamp"})
        except Exception as e:
            self.log(f"status publish failed ({e})", level="WARNING")

    def _act_zone(self, zone, p, snap, decision, block, actuate, lights_on, now):
        """Apply one resolved (fire, size, reason) through the zone's OWN live gates + hardware. Shared by
        healthy zones and blind (copy/fallback) zones — a blind zone has snap=None, so any snapshot-derived
        escalation (the starving-zone watchdog alert) is guarded on `snap is not None`. `block` is the
        live-gate reason computed once by loop() (None if the zone isn't firing / isn't gated)."""
        st = self.state[zone]
        fire, size, reason = decision
        # WATCHDOG alert — a starving zone (no water > watchdog_hours, lights-on, dry) that's being
        # blocked is URGENT. We do NOT auto-override the block (it's feed-safety or operator intent);
        # we escalate to the human (who can use Rehydrate, which respects feed but ignores phase/cap).
        # Needs live VWC/cadence -> only for a healthy zone (snap present).
        if (snap is not None and fire and block and lights_on and p.watchdog_hours > 0
                and snap.minutes_since_shot > p.watchdog_hours * 60 and snap.vwc < p.p2_threshold):
            self._alert(f"wd_z{zone}", "URGENT — zone starving",
                        f"Zone {zone}: no water {snap.minutes_since_shot / 60.0:.1f}h, "
                        f"VWC {snap.vwc:.0f}<{p.p2_threshold:.0f}, blocked by '{block}'. Needs you.")
        tag = "SHADOW" if not actuate else "LIVE"
        if fire and block:
            self.log(f"[{tag}] Z{zone} {st['phase']} BLOCKED ({block}): would {reason}", level="INFO")
        elif fire:
            dur = max(5, int(size / 100.0 * self.substrate_l / max(self.flow_lps, 0.001)))
            self.log(f"[{tag}] Z{zone} {st['phase']} FIRE {size}% ~{dur}s — {reason}")
            if actuate:
                self._execute_shot(zone, dur, size)
            else:
                # SHADOW: advance a VIRTUAL shot (no hardware) so shadow runs the same cooldown/
                # ramp/daily-cap dynamics as live — otherwise the go-live parity gate is bogus
                # (counters frozen -> FIRE re-emitted every tick, cap/cadence never exercised).
                self._advance_shot_counters(zone, size)
        else:
            # FINDING #2: a decide()-level BLOCK (high-EC non-dilutive, daily-cap) means the zone is
            # stranded — it WANTED water and was refused. Don't let that be DEBUG-silent; page it
            # (throttled) so a salty/blocked zone is never invisible to the operator.
            if "BLOCK" in reason:
                self._alert(f"block_z{zone}", "Zone blocked — needs attention",
                            f"Zone {zone} ({st['phase']}): {reason}")
            self.log(f"[{tag}] Z{zone} {st['phase']} hold — {reason}", level="DEBUG")

    def _advance_shot_counters(self, zone, size_pct):
        """Advance the shot/cadence/budget bookkeeping (shots, last_shot, daily_vol) and persist.
        Used by BOTH the live shot (_execute_shot) and the SHADOW 'virtual shot' so shadow exercises
        the same cooldown/ramp/daily-cap state machine as live (the go-live parity gate is otherwise
        untrustworthy: shadow would re-emit FIRE every tick with minutes_since_shot stuck at 1e9)."""
        st = self.state[zone]
        st["shots"] += 1
        st["last_shot"] = datetime.now()
        st["daily_vol"] += size_pct / 100.0 * self.substrate_l
        self._save_state()                           # persist the budget spend + last_shot

    def _execute_shot(self, zone, duration_s, size_pct):
        """Hardware sequence (sync app -> runs in an AppDaemon worker thread; time.sleep blocks only that
        thread, never the main loop, so there is no lock-across-await / qsize backlog). self._busy guards
        re-entry. Only ever called in LIVE mode (actuate on)."""
        self._busy = True
        valve = self.hw["valves"].get(zone) or self.hw["valves"].get(str(zone))
        try:
            self.call_service("switch/turn_on", entity_id=self.hw["pump"])
            time.sleep(2)
            self.call_service("switch/turn_on", entity_id=self.hw["mainline"])
            time.sleep(1)
            self.call_service("switch/turn_on", entity_id=valve)
            time.sleep(duration_s)
            self.call_service("switch/turn_off", entity_id=valve)
            time.sleep(1)
            self.call_service("switch/turn_off", entity_id=self.hw["mainline"])
            self.call_service("switch/turn_off", entity_id=self.hw["pump"])
            time.sleep(1)
            if self._on(valve, False):                       # read-back verify
                # Stuck-open valve is the highest-priority hardware fault and (F1) has no external
                # backstop. Cut the pressure source AND the mainline, then page the operator — this
                # path must never be silent (ERROR-log alone won't push a notification).
                self.log(f"⛔ Z{zone} valve {valve} failed to close — emergency pump stop", level="ERROR")
                self.call_service("switch/turn_off", entity_id=self.hw["pump"])
                self.call_service("switch/turn_off", entity_id=self.hw["mainline"])
                self._alert(f"valve_z{zone}", "URGENT — valve stuck open",
                            f"Zone {zone}: valve {valve} did not close after shot. Pump + mainline cut. "
                            f"Check the solenoid now — slab may keep filling if there is residual head.")
            self._advance_shot_counters(zone, size_pct)
        except Exception as e:
            self.log(f"❌ Z{zone} shot error: {e} — safing hardware", level="ERROR")
            for ent in (valve, self.hw["mainline"], self.hw["pump"]):
                try:
                    self.call_service("switch/turn_off", entity_id=ent)
                except Exception:
                    pass
        finally:
            self._busy = False
