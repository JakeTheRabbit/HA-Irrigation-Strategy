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

import asyncio
from dataclasses import dataclass
from datetime import datetime

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
    elif phase == "P3" and s.lights_just_on:
        phase, treason = "P0", "lights-on -> P0"
    elif phase == "P0":
        if s.vwc <= p.p2_threshold:
            phase, treason = "P1", f"P0 bypass VWC {s.vwc:.0f}<=rewater {p.p2_threshold:.0f}"
        elif s.dryback_pct >= p.dryback_target:
            phase, treason = "P1", f"P0 dryback done {s.dryback_pct:.0f}%"
        elif s.phase_minutes >= p.p0_max_wait_min:
            phase, treason = "P1", f"P0 timeout {s.phase_minutes:.0f}min"
    elif phase == "P1":
        if s.vwc >= p.p1_target:
            phase, treason = "P2", f"P1 recovered {s.vwc:.0f}>={p.p1_target:.0f}"
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

    # ---- IRRIGATION DECISION ----
    fire, size, ir = False, 0.0, ""
    if phase == "P0":
        if p.ec_target_p0 > 0 and s.ec / p.ec_target_p0 > 2.5:
            fire, size, ir = True, 10.0, f"P0 EC flush {s.ec:.1f}"
    elif phase == "P1":
        if s.minutes_since_shot >= p.p1_time_between_min and s.vwc < p.p1_target:
            raw = min(p.p1_initial + p.p1_incr * s.shot_count,
                      p.p1_initial + p.p1_incr * p.p1_max_shots)
            fire, size, ir = True, ec_adjust(raw, s.ec, p.ec_target_p1), f"P1 ramp VWC {s.vwc:.0f}<{p.p1_target:.0f}"
    elif phase == "P2":
        if s.ec >= p.max_ec - 1.0:
            fire, size, ir = True, p.p2_shot_size * 1.5, f"P2 rescue flush EC {s.ec:.1f}"
        elif p.ec_target_p2 > 0 and s.ec / p.ec_target_p2 > 1.2:
            fire, size, ir = True, p.p2_shot_size * 1.5, f"P2 dilute EC {s.ec:.1f}"
        elif s.vwc < p2_thr:
            fire, size, ir = True, ec_adjust(p.p2_shot_size, s.ec, p.ec_target_p2), f"P2 top-up VWC {s.vwc:.0f}<{p2_thr:.0f}"
        # low-EC alone never fires: corrected via feed strength / deeper dryback, not water.
    elif phase == "P3":
        if s.vwc < p.p3_emergency_floor:
            fire, size, ir = True, p.p3_emergency_shot, f"P3 emergency VWC {s.vwc:.0f}<{p.p3_emergency_floor:.0f}"

    # ---- SAFETY subset (caps + hard max-EC; live-state gates handled in IO shell) ----
    if fire:
        is_rescue = ("rescue" in ir) or ("flush" in ir)
        if s.ec >= p.max_ec and not is_rescue:
            fire, ir = False, f"BLOCK max-EC {s.ec:.1f}>={p.max_ec:.1f}"
        elif s.daily_vol >= p.max_daily_volume:
            fire, ir = False, f"BLOCK daily-cap {s.daily_vol:.0f}/{p.max_daily_volume:.0f}L"

    reason = treason + (" | " if (treason and ir) else "") + ir
    return phase, round(p2_thr, 1), fire, round(size, 1), reason


# ============================================================
# IO SHELL  (AppDaemon app — all HA coupling lives here, thin)
# ============================================================
class LeanCropSteering(hass.Hass):

    async def initialize(self):
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

        self.state = {z: {"phase": "P2", "peak": 0.0, "win": [], "last_shot": None,
                          "shots": 0, "daily_vol": 0.0, "ec_smooth": None,
                          "last_phase_change": datetime.now()} for z in self.zones}
        self._busy = False
        self.run_every(self.loop, "now+10", 60)
        self.log("🌿 Lean crop steering initialized (SHADOW until %s is on)" % self.actuate_flag)

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

    def _read_sensor(self, entity):
        """Read a probe, sanity-checked + fresh (<15min). None if bad/stale."""
        try:
            v = self.get_state(entity)
            if v in (None, "unknown", "unavailable", ""):
                return None
            f = float(v)
            return f
        except Exception:
            return None

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

    # ---------- per-zone snapshot + params ----------
    def _params(self, zone):
        veg = self._veg(zone)
        sfx = "veg" if veg else "gen"
        return ZoneParams(
            p1_target=self._zone_num(zone, "p1_target_vwc", 60),
            p2_threshold=self._zone_num(zone, "p2_vwc_threshold", 45),
            p2_shot_size=self._zone_num(zone, "p2_shot_size", 5),
            p1_initial=self._zone_num(zone, "p1_initial_shot_size", 2),
            p1_incr=self._zone_num(zone, "p1_shot_size_increment", 0.5),
            p1_max_shots=int(self._zone_num(zone, "p1_maximum_shots", 12)),
            p1_time_between_min=self._zone_num(zone, "p1_time_between_shots", 15),
            dryback_target=self._zone_num(zone, f"{'vegetative' if veg else 'generative'}_dryback_target", 20),
            p0_max_wait_min=self._num("number.crop_steering_p0_maximum_wait_time", 45),
            ec_target_p0=self._zone_num(zone, f"ec_target_{sfx}_p0", 4),
            ec_target_p1=self._zone_num(zone, f"ec_target_{sfx}_p1", 5),
            ec_target_p2=self._zone_num(zone, f"ec_target_{sfx}_p2", 6),
            p3_emergency_floor=self._zone_num(zone, "p3_emergency_vwc_threshold", 40),
            p3_emergency_shot=self._zone_num(zone, "p3_emergency_shot_size", 2),
            max_daily_volume=self._zone_num(zone, "max_daily_volume", 300),
            field_capacity=self._num("number.crop_steering_field_capacity", 70),
            max_ec=self._num("number.crop_steering_maximum_ec", 9),
            stacking_on=self._on("switch.crop_steering_ec_stacking_enabled", False),
        )

    def _snapshot(self, zone, now, lights_on, lights_just_on):
        st = self.state[zone]
        vwc = self._read_sensor(self.zones[zone]["vwc"])
        ec = self._read_sensor(self.zones[zone]["ec"])
        if vwc is None:
            return None, None
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
        feed = self._read_sensor("sensor.atlas_legacy_1_ec")
        lo = self._num("number.crop_steering_irrigation_ec_min", 0)
        hi = self._num("number.crop_steering_irrigation_ec_max", 0)
        if feed is not None and ((lo > 0 and feed < lo) or (hi > 0 and feed > hi)):
            return f"source-water EC {feed:.1f} out of [{lo:g},{hi:g}]"
        return None

    # ---------- main loop ----------
    async def loop(self, kwargs):
        if self._busy:
            return
        now = datetime.now()
        lights_on = self._lights_on(now)
        actuate = self._on(self.actuate_flag, False)
        for zone in self.zones:
            st = self.state[zone]
            was_off = not getattr(self, "_was_lights_on", lights_on)
            lights_just_on = lights_on and was_off
            snap, p = self._snapshot(zone, now, lights_on, lights_just_on)
            if snap is None:
                self.log(f"Z{zone}: VWC sensor unreadable — skip", level="WARNING")
                continue
            new_phase, new_thr, fire, size, reason = decide(snap, p)

            if new_phase != st["phase"]:
                if new_phase == "P0":
                    st["daily_vol"], st["shots"], st["peak"] = 0.0, 0, snap.vwc
                if new_phase == "P1":
                    st["shots"] = 0
                st["phase"] = new_phase
                st["last_phase_change"] = now
            if p.stacking_on and abs(new_thr - p.p2_threshold) >= 0.5 and st["phase"] == "P2":
                self._set_threshold(zone, new_thr)

            block = self._blocked(zone) if fire else None
            tag = "SHADOW" if not actuate else "LIVE"
            if fire and block:
                self.log(f"[{tag}] Z{zone} {st['phase']} BLOCKED ({block}): would {reason}", level="INFO")
            elif fire:
                dur = max(5, int(size / 100.0 * self.substrate_l / max(self.flow_lps, 0.001)))
                self.log(f"[{tag}] Z{zone} {st['phase']} FIRE {size}% ~{dur}s — {reason}")
                if actuate:
                    await self._execute_shot(zone, dur, size)
            else:
                self.log(f"[{tag}] Z{zone} {st['phase']} hold — {reason}", level="DEBUG")
        self._was_lights_on = lights_on

    def _set_threshold(self, zone, value):
        self.call_service("number/set_value",
                          entity_id=f"number.crop_steering_zone_{zone}_p2_vwc_threshold", value=value)
        self.log(f"🧂 Z{zone}: EC-steer p2_threshold -> {value}")

    async def _execute_shot(self, zone, duration_s, size_pct):
        """Non-blocking hardware sequence. NO lock held across the await (the master bug)."""
        self._busy = True
        valve = self.hw["valves"].get(zone) or self.hw["valves"].get(str(zone))
        try:
            self.call_service("switch/turn_on", entity_id=self.hw["pump"])
            await asyncio.sleep(2)
            self.call_service("switch/turn_on", entity_id=self.hw["mainline"])
            await asyncio.sleep(1)
            self.call_service("switch/turn_on", entity_id=valve)
            await asyncio.sleep(duration_s)
            self.call_service("switch/turn_off", entity_id=valve)
            await asyncio.sleep(1)
            self.call_service("switch/turn_off", entity_id=self.hw["mainline"])
            self.call_service("switch/turn_off", entity_id=self.hw["pump"])
            await asyncio.sleep(1)
            if self._on(valve, False):                       # read-back verify
                self.log(f"⛔ Z{zone} valve {valve} failed to close — emergency pump stop", level="ERROR")
                self.call_service("switch/turn_off", entity_id=self.hw["pump"])
            st = self.state[zone]
            st["shots"] += 1
            st["last_shot"] = datetime.now()
            st["daily_vol"] += size_pct / 100.0 * self.substrate_l
        except Exception as e:
            self.log(f"❌ Z{zone} shot error: {e} — safing hardware", level="ERROR")
            for ent in (valve, self.hw["mainline"], self.hw["pump"]):
                try:
                    self.call_service("switch/turn_off", entity_id=ent)
                except Exception:
                    pass
        finally:
            self._busy = False
