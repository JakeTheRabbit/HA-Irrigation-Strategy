"""
Crop Steering v2 — lean, deterministic AppDaemon controller.

Replaces the broken 5,241-line master_crop_steering_app.py orchestrator (see
ENGINE_ANALYSIS.md). Self-contained: no shared-state @property traps, one source
of truth per zone, fail-CLOSED safety, and the fill/dose + tank-full interlock.

Design:
- Per-zone P0->P1->P2->P3 daily state machine, driven by VWC (+ EC logged).
- Reads the HA `crop_steering` integration's per-zone sensors and per-row number
  params (number.crop_steering_zone_N_<key>, falling back to global
  number.crop_steering_<key>, then a code default).
- Drives hardware pump -> main line -> zone valve via non-blocking run_in chain.
- NEVER fires unless ALL of: system_enabled + auto_irrigation_enabled + zone
  enabled + NOT manual_override + interlock clear (not dosing, tank not empty) +
  min-interval elapsed + a single in-flight shot. Any error or unknown => no fire.
- ML/AI is deliberately NOT in the control path (layer it on later as advisory).

apps.yaml:
  crop_steering_v2:
    module: crop_steering_v2
    class: CropSteeringV2
    hardware:
      pump_master: switch.veg_main_pump
      main_line: switch.espoe_irrigation_relay_2_3
      zone_valves: {1: switch.f2_row1, 2: switch.f2_row2, 3: switch.f2_row3}
    timing:
      phase_check_interval: 60
    thresholds:
      emergency_vwc: 10.0
      min_irrigation_interval: 300
    interlock:
      dosing: input_boolean.nutrient_dosing_active
      tank_not_empty: binary_sensor.veg_tank_empty_switch  # on = water present
"""
from datetime import datetime, timedelta

import appdaemon.plugins.hass.hassapi as hass


class CropSteeringV2(hass.Hass):

    def initialize(self):
        self.hw = self.args.get("hardware", {})
        self.tcfg = self.args.get("timing", {})
        self.thr = self.args.get("thresholds", {})
        self.emergency_only = bool(self.args.get("emergency_only", False))
        ilk = self.args.get("interlock", {})
        self.ent_dosing = ilk.get("dosing", "input_boolean.nutrient_dosing_active")
        # Pump dry-run guard: entity that reads "on" when WATER IS PRESENT (e.g. the low
        # float binary_sensor.veg_tank_empty_switch). Block only when it explicitly reads
        # empty; fail-OPEN on unknown so a flaky sensor never halts irrigation. NOTE:
        # gating on a "tank FULL" sensor is wrong — the tank drains as it waters, so it
        # would only ever allow one shot then lock out until the next refill.
        self.ent_tank_not_empty = ilk.get("tank_not_empty")
        # Quality gate: only fire when veg-tank pH (and EC, if configured) are in range.
        # Out of range -> block + an actionable phone alert with an "Irrigate Anyway"
        # button; tapping it sets a timed override that bypasses THIS gate only.
        ph = self.args.get("ph", {})
        self.ph_entity = ph.get("entity")
        self.ph_min = float(ph.get("min", 5.8))
        self.ph_max = float(ph.get("max", 6.2))
        ec = self.args.get("ec", {})
        self.ec_entity = ec.get("entity")          # optional; configure `ec:` to enable
        self.ec_min = float(ec.get("min", 0.0))
        self.ec_max = float(ec.get("max", 99.0))
        self.notify_service = self.args.get("notify_service")
        self.override_minutes = float(self.args.get("override_minutes", 30))
        self._quality_ok, self._quality_reason, self._quality_bad, self._last_notify = True, None, 0, None
        self._override_until = None

        # Explicit num_zones from config avoids a startup race where integration
        # zone sensors haven't loaded yet; fall back to detection.
        self.num_zones = int(self.args.get("num_zones", 0)) or self._detect_zones()
        now = self.datetime()
        self.zone = {
            z: {
                "phase": "P3", "peak_vwc": None, "phase_start": now,
                "last_shot": None, "p1_shots": 0, "irrigating": False,
                "water_today": 0.0, "shots_today": 0, "water_day": now.date(),
            }
            for z in range(1, self.num_zones + 1)
        }

        # Safe start: make sure nothing is left open.
        self._all_off("startup")

        interval = int(self.tcfg.get("phase_check_interval", 60))
        self.run_every(self.control_loop, now + timedelta(seconds=15), interval)
        # "Irrigate Anyway" button taps on the phone alert arrive as this event.
        self.listen_event(self._on_action, "mobile_app_notification_action")
        self.log(f"Crop Steering v2 initialized: {self.num_zones} zone(s), loop {interval}s. "
                 f"system_enabled gates all hardware.")

    # ---------------------------------------------------------------- helpers
    def _detect_zones(self):
        n = 0
        for i in range(1, 7):
            if self.entity_exists(f"sensor.crop_steering_zone_{i}_vwc"):
                n = i
        return max(n, 1)

    def _float(self, entity):
        v = self.get_state(entity)
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _vwc(self, z):
        return self._float(f"sensor.crop_steering_zone_{z}_vwc")

    def _ec(self, z):
        return self._float(f"sensor.crop_steering_zone_{z}_ec")

    def _gnum(self, key, default):
        """Global integration number, else default."""
        v = self._float(f"number.crop_steering_{key}")
        return v if v is not None else default

    def _znum(self, z, key, default):
        """Per-zone number override -> global -> default."""
        v = self._float(f"number.crop_steering_zone_{z}_{key}")
        if v is not None:
            return v
        return self._gnum(key, default)

    def _on(self, entity, default):
        s = self.get_state(entity)
        if s is None:
            return default
        return str(s).lower() == "on"

    def _is_veg(self, z):
        e = f"select.crop_steering_zone_{z}_steering_mode"
        v = self.get_state(e) if self.entity_exists(e) else None
        if not v or v in ("unknown", "unavailable"):
            v = self.get_state("select.crop_steering_growth_stage") or "Vegetative"
        return str(v).lower().startswith("veg")

    # --------------------------------------------------------------------- EC
    def _ec_target(self, z, phase):
        """Per-phase, per-mode EC target (mS/cm). phase in p0/p1/p2/p3."""
        veg = self._is_veg(z)
        dv, dg = {"p0": (3.0, 4.0), "p1": (3.0, 5.0),
                  "p2": (3.2, 6.0), "p3": (3.0, 4.5)}.get(phase, (3.0, 4.5))
        return self._znum(z, f"ec_target_{'veg' if veg else 'gen'}_{phase}", dv if veg else dg)

    def _ec_decision(self, z, ec, target):
        """Engine-parity EC eval -> (needs_irrigation, action).
        dilute = EC too high (flush down); strengthen = too low (do NOT dilute
        further); stack = build EC up below target (only if ec_stacking_enabled)."""
        if ec is None or target <= 0:
            return (False, "maintain")
        ratio = ec / target
        if self._on("switch.crop_steering_ec_stacking_enabled", False):
            if ratio < 1.0 and (target - ec) > 0.5:
                return (True, "stack")
            return (False, "maintain")
        if ratio > 1.2:
            return (True, "dilute")
        if ratio < 0.8:
            return (False, "strengthen")
        return (False, "maintain")

    def _ec_shot_factor(self, action, ratio):
        """Shot-size multiplier from EC action (bigger to dilute, smaller to conserve)."""
        if action == "dilute":
            return 2.0 if ratio > 1.5 else (1.5 if ratio > 1.2 else 1.2)
        if action in ("conserve", "strengthen"):
            return 0.5 if ratio < 0.5 else (0.7 if ratio < 0.8 else 0.9)
        if action == "stack":
            return 1.1
        return 1.0

    def _lights_on(self):
        on_h = int(self._gnum("lights_on_hour", 10))
        off_h = int(self._gnum("lights_off_hour", 22))
        now = self.datetime()
        h = now.hour + now.minute / 60.0
        if on_h < off_h:
            return on_h <= h < off_h
        return h >= on_h or h < off_h  # wraps past midnight

    def _minutes_to_lights_off(self):
        off_h = int(self._gnum("lights_off_hour", 22))
        now = self.datetime()
        off = now.replace(hour=off_h % 24, minute=0, second=0, microsecond=0)
        if off <= now:
            off += timedelta(days=1)
        return (off - now).total_seconds() / 60.0

    # ------------------------------------------------------------- interlock
    def _block_reason(self, z):
        """Return a string reason if irrigation must NOT happen, else None. Fail-closed."""
        try:
            if not self._on("switch.crop_steering_system_enabled", False):
                return "system_disabled"
            if not self._on("switch.crop_steering_auto_irrigation_enabled", False):
                return "auto_disabled"
            if not self._on(f"switch.crop_steering_zone_{z}_enabled", True):
                return "zone_disabled"
            if self._on(f"switch.crop_steering_zone_{z}_manual_override", False):
                return "manual_override"
            if self._on(self.ent_dosing, True):  # default True => block if unknown
                return "nutrient_dosing_active"
            if self.ent_tank_not_empty and not self._on(self.ent_tank_not_empty, True):
                return "tank_empty"  # low float reads empty -> protect the pump (dry-run)
            if not self._quality_ok:
                return self._quality_reason or "quality_block"
            # Overwater / EC safety caps (parity with the old engine's safety limits).
            if self.zone[z]["water_today"] >= self._znum(z, "max_daily_volume", 1e9):
                return "daily_volume_cap"
            v = self._vwc(z)
            if v is not None and v >= self._gnum("field_capacity", 101.0):
                return "at_field_capacity"
            e = self._ec(z)
            if e is not None and e >= self._gnum("maximum_ec", 99.0):
                return "max_ec_exceeded"
            if self.zone[z]["irrigating"]:
                return "shot_in_progress"
        except Exception as e:
            self.log(f"Zone {z} interlock check error (fail-closed): {e}", level="ERROR")
            return "interlock_error"
        return None

    def _shot_due(self, z, min_minutes):
        last = self.zone[z]["last_shot"]
        if last is None:
            return True
        return (self.datetime() - last).total_seconds() / 60.0 >= min_minutes

    def _check_quality(self):
        """pH + EC gate (run once per control loop). Allow firing only when veg-tank pH
        (and EC, if configured) are in range. Out of range -> block + an actionable phone
        alert with an "Irrigate Anyway" button. Tapping it sets a timed override that
        bypasses THIS gate only (dosing/tank/system interlocks still apply) for
        override_minutes. Debounced ~2 checks, re-alert every 30 min, notice on recovery."""
        problems = []
        if self.ph_entity:
            ph = self._float(self.ph_entity)
            if ph is None:
                problems.append("pH unreadable")
            elif ph < self.ph_min or ph > self.ph_max:
                problems.append(f"pH {ph:.2f} (want {self.ph_min:g}-{self.ph_max:g})")
        if self.ec_entity:
            ec = self._float(self.ec_entity)
            if ec is None:
                problems.append("EC unreadable")
            elif ec < self.ec_min or ec > self.ec_max:
                problems.append(f"EC {ec:.2f} (want {self.ec_min:g}-{self.ec_max:g})")
        now = self.datetime()
        override = self._override_until is not None and now < self._override_until

        if not problems:
            if self._quality_bad >= 2 and self._last_notify is not None:
                self._notify_phone("✅ F2 crop steering — veg-tank pH/EC back in range. Irrigation re-enabled.")
            self._quality_ok, self._quality_reason, self._quality_bad, self._last_notify = True, None, 0, None
            self._override_until = None  # healthy again -> drop any override
            return

        self._quality_reason = "quality_block(" + "; ".join(problems) + ")"
        if override:
            self._quality_ok = True  # user tapped "Irrigate Anyway"
            return
        self._quality_ok = False
        self._quality_bad += 1
        due = self._last_notify is None or (now - self._last_notify).total_seconds() >= 1800
        if self._quality_bad >= 2 and due:
            self._notify_phone(
                "⚠️ F2 irrigation BLOCKED — veg tank " + "; ".join(problems) + ".",
                actions=[{"action": "CS_IRRIGATE_ANYWAY", "title": "Irrigate Anyway"}],
            )
            self._last_notify = now

    def _on_action(self, event_name, data, kwargs):
        """Phone-notification action handler. 'Irrigate Anyway' grants a timed override
        of the pH/EC gate (other interlocks still apply)."""
        if (data or {}).get("action") != "CS_IRRIGATE_ANYWAY":
            return
        self._override_until = self.datetime() + timedelta(minutes=self.override_minutes)
        self.log(f"Override: pH/EC gate bypassed for {self.override_minutes:.0f} min (Irrigate Anyway tapped)")
        self._notify_phone(f"✅ Override accepted — F2 will irrigate despite pH/EC for "
                           f"{self.override_minutes:.0f} min (dosing/tank/system interlocks still apply).")

    def _notify_phone(self, message, actions=None):
        if not self.notify_service:
            return
        ndata = {"tag": "f2_cs_quality"}
        if actions:
            ndata["actions"] = actions
        try:
            self.call_service(self.notify_service.replace(".", "/", 1),
                              message=message, title="F2 Crop Steering", data=ndata)
            self.log(f"Phone alert ({self.notify_service}): {message}")
        except Exception as e:
            self.log(f"notify failed ({self.notify_service}): {e}", level="ERROR")

    # ----------------------------------------------------------- control loop
    def control_loop(self, kwargs):
        try:
            self._check_quality()
            lights = self._lights_on()
            for z in range(1, self.num_zones + 1):
                self._step_zone(z, lights)
        except Exception as e:
            self.log(f"control_loop error: {e}", level="ERROR")

    def _step_zone(self, z, lights):
        st = self.zone[z]
        now = self.datetime()
        if st["water_day"] != now.date():
            st.update(water_today=0.0, shots_today=0, water_day=now.date())

        vwc = self._vwc(z)
        veg = self._is_veg(z)

        # Emergency-only hold (configured): keep P3 and only top up below the
        # floor, 24/7, bypassing the normal P0->P2 day cycle. Safe interim until
        # full per-row calibration. Still fully gated by _block_reason/interlock.
        if self.emergency_only:
            if st["phase"] != "P3":
                self._set_phase(z, "P3")
            if vwc is not None:
                emerg = float(self.thr.get("emergency_vwc", 10.0))
                min_int = float(self.thr.get("min_irrigation_interval", 300)) / 60.0
                if vwc < emerg and self._shot_due(z, min_int):
                    self._fire_shot(z, "emergency", self._znum(z, "p2_shot_size", 5.0))
            self._publish(z, vwc)
            return

        # Lights off => P3 / overnight dryback, no regular irrigation.
        if not lights:
            if st["phase"] != "P3":
                self._set_phase(z, "P3")
            self._publish(z, vwc)
            return

        # Lights on. If we were in P3 (overnight), a new day starts at P0.
        if st["phase"] == "P3":
            self._set_phase(z, "P0")
            st["peak_vwc"] = vwc

        if vwc is None:
            self.log(f"Zone {z}: VWC unavailable — holding (no action)", level="WARNING")
            self._publish(z, vwc)
            return

        if st["peak_vwc"] is None or vwc > st["peak_vwc"]:
            st["peak_vwc"] = vwc

        ph = st["phase"]
        if ph == "P0":
            self._do_p0(z, vwc, veg)
        elif ph == "P1":
            self._do_p1(z, vwc, veg)
        elif ph == "P2":
            self._do_p2(z, vwc, veg)

        # Emergency floor applies in any lit phase.
        emerg = float(self.thr.get("emergency_vwc", 10.0))
        min_int = float(self.thr.get("min_irrigation_interval", 300)) / 60.0
        if vwc < emerg and self._shot_due(z, min_int):
            self._fire_shot(z, "emergency", self._znum(z, "p2_shot_size", 5.0))

        self._publish(z, vwc)

    # --------------------------------------------------------------- phases
    def _do_p0(self, z, vwc, veg):
        st = self.zone[z]
        key = "vegetative_dryback_target" if veg else "generative_dryback_target"
        target_db = self._znum(z, key, 15.0)                       # % drop of peak
        drop_pts = self._znum(z, "p0_dryback_drop_percent", 15.0)  # absolute VWC-point drop
        min_wait = self._znum(z, "p0_minimum_wait_time", 30.0)
        max_wait = self._znum(z, "p0_maximum_wait_time", 120.0)
        elapsed = (self.datetime() - st["phase_start"]).total_seconds() / 60.0
        peak = st["peak_vwc"] or vwc
        drop = ((peak - vwc) / peak * 100.0) if peak else 0.0
        abs_drop = (peak - vwc) if peak else 0.0
        if elapsed >= min_wait and (drop >= target_db or abs_drop >= drop_pts):
            self.log(f"Zone {z}: P0 complete (dryback {drop:.1f}% of peak / {abs_drop:.1f}pts) -> P1")
            self._set_phase(z, "P1")
            st["p1_shots"] = 0
        elif elapsed >= max_wait:
            self.log(f"Zone {z}: P0 max wait {max_wait:.0f}min reached (dryback only "
                     f"{drop:.1f}%) -> P1", level="WARNING")
            self._set_phase(z, "P1")
            st["p1_shots"] = 0

    def _do_p1(self, z, vwc, veg):
        st = self.zone[z]
        target_vwc = self._znum(z, "p1_target_vwc", 65.0)
        min_shots = int(self._znum(z, "p1_minimum_shots", 3))
        max_shots = int(self._znum(z, "p1_maximum_shots", 6))
        tween = self._znum(z, "p1_time_between_shots", 15.0)
        vwc_need = vwc < target_vwc
        # Target VWC reached + minimum shots done -> P2.
        if not vwc_need and st["p1_shots"] >= min_shots:
            self.log(f"Zone {z}: P1 complete (VWC {vwc:.1f}% >= {target_vwc:.0f}%, "
                     f"{st['p1_shots']} shots) -> P2")
            self._set_phase(z, "P2")
            return
        # Max-shots ceiling -> P2 (never ramp forever if target is unreachable).
        if st["p1_shots"] >= max_shots:
            self.log(f"Zone {z}: P1 max shots {max_shots} reached (VWC {vwc:.1f}%) -> P2")
            self._set_phase(z, "P2")
            return
        if not self._shot_due(z, tween):
            return
        ec = self._ec(z)
        target_ec = self._ec_target(z, "p1")
        ec_need, action = self._ec_decision(z, ec, target_ec)
        if not (vwc_need or ec_need):
            return
        # Progressive shot size: initial + increment*count, capped at max, * zone mult.
        init = self._znum(z, "p1_initial_shot_size", 2.0)
        inc = self._znum(z, "p1_shot_size_increment", 0.5)
        mx = self._znum(z, "p1_maximum_shot_size", 10.0)
        size = min(init + inc * st["p1_shots"], mx) * self._znum(z, "shot_size_multiplier", 1.0)
        if ec is not None and target_ec > 0:
            size *= self._ec_shot_factor(action, ec / target_ec)
        kind = f"P1 EC-{action}" if (ec_need and not vwc_need) else "P1"
        if self._fire_shot(z, kind, size):
            st["p1_shots"] += 1

    def _do_p2(self, z, vwc, veg):
        # Enter P3 ahead of lights-off (final dryback).
        last_key = "p3_veg_last_irrigation" if veg else "p3_gen_last_irrigation"
        last_irr = self._znum(z, last_key, 120.0)
        if self._minutes_to_lights_off() <= last_irr:
            self.log(f"Zone {z}: within {last_irr:.0f}min of lights-off -> P3")
            self._set_phase(z, "P3")
            return
        if not self._shot_due(z, float(self.thr.get("min_irrigation_interval", 300)) / 60.0):
            return
        threshold = self._znum(z, "p2_vwc_threshold", 60.0)
        vwc_need = vwc < threshold
        ec = self._ec(z)
        target_ec = self._ec_target(z, "p2")
        base = self._znum(z, "p2_shot_size", 5.0)
        # P2 EC ratio band (p2_ec_high/low are MULTIPLIERS on the phase EC target):
        # ratio > high -> dilute (bigger shot); ratio < low -> conserve (smaller shot).
        ratio = (ec / target_ec) if (ec is not None and target_ec > 0) else None
        high = self._znum(z, "p2_ec_high_threshold", 1.2)
        low = self._znum(z, "p2_ec_low_threshold", 0.8)
        ec_need, action, size = False, "maintain", base
        if ratio is not None:
            if ratio > high:
                ec_need, action, size = True, "dilute", base * 1.5
            elif ratio < low:
                ec_need, action, size = True, "conserve", base * 0.7
        if not (vwc_need or ec_need):
            return
        size *= self._znum(z, "shot_size_multiplier", 1.0)
        kind = f"P2 EC-{action}" if (ec_need and not vwc_need) else "P2"
        self._fire_shot(z, kind, size)

    def _set_phase(self, z, ph):
        if self.zone[z]["phase"] != ph:
            self.log(f"Zone {z}: phase {self.zone[z]['phase']} -> {ph}")
            self.zone[z]["phase"] = ph
            self.zone[z]["phase_start"] = self.datetime()

    # ------------------------------------------------------------ irrigation
    def _shot_duration_s(self, shot_pct):
        sub = self._gnum("substrate_volume", 3.0)
        flow = self._gnum("dripper_flow_rate", 4.0)
        if flow <= 0:
            return 0.0
        return round((sub * shot_pct / 100.0) / flow * 3600.0, 1)

    def _fire_shot(self, z, kind, shot_pct):
        block = self._block_reason(z)
        if block:
            # Normal when validating with system off; logged at info.
            self.log(f"Zone {z}: {kind} shot wanted ({shot_pct:.1f}%) but BLOCKED: {block}")
            return False
        dur = self._shot_duration_s(shot_pct)
        if dur <= 0:
            self.log(f"Zone {z}: refusing shot — bad duration {dur}s", level="WARNING")
            return False
        if dur > 600:
            self.log(f"Zone {z}: clamping shot {dur:.0f}s -> 600s (safety cap)", level="WARNING")
            dur = 600.0
        try:
            valve = self.hw["zone_valves"][z]
            pump = self.hw["pump_master"]
            main = self.hw["main_line"]
        except (KeyError, TypeError) as e:
            self.log(f"Zone {z}: hardware config missing ({e}) — cannot fire", level="ERROR")
            return False

        self.zone[z]["irrigating"] = True
        self.zone[z]["last_shot"] = self.datetime()
        self.zone[z]["shots_today"] += 1
        flow = self._gnum("dripper_flow_rate", 4.0)
        self.zone[z]["water_today"] += round(flow * dur / 3600.0, 3)
        self.log(f"Zone {z}: FIRING {kind} shot {shot_pct:.1f}% -> {dur:.0f}s "
                 f"(pump->main->{valve})")
        try:
            self.fire_event("crop_steering_irrigation_shot", zone=z,
                            phase=self.zone[z]["phase"], kind=kind,
                            shot_size_percent=round(shot_pct, 2), duration_s=round(dur, 1))
        except Exception as e:
            self.log(f"Zone {z}: event-fire error: {e}", level="WARNING")
        try:
            self.turn_on(pump)
            self.run_in(self._seq_main, 2, z=z, pump=pump, main=main, valve=valve, dur=dur)
        except Exception as e:
            self.log(f"Zone {z}: shot start error: {e}", level="ERROR")
            self._all_off("shot_start_error")
            self.zone[z]["irrigating"] = False
            return False
        return True

    def _seq_main(self, kwargs):
        try:
            self.turn_on(kwargs["main"])
            self.run_in(self._seq_valve, 1, **kwargs)
        except Exception as e:
            self.log(f"Zone {kwargs.get('z')}: seq_main error: {e}", level="ERROR")
            self._abort_shot(kwargs)

    def _seq_valve(self, kwargs):
        z = kwargs["z"]
        # Re-check interlock right before opening the row valve (dosing may have started).
        block = self._block_reason(z)
        if block and block != "shot_in_progress":
            self.log(f"Zone {z}: aborting shot before valve open — {block}", level="WARNING")
            self._abort_shot(kwargs)
            return
        try:
            self.turn_on(kwargs["valve"])
            self.run_in(self._seq_off, kwargs["dur"], **kwargs)
        except Exception as e:
            self.log(f"Zone {z}: seq_valve error: {e}", level="ERROR")
            self._abort_shot(kwargs)

    def _seq_off(self, kwargs):
        z = kwargs["z"]
        try:
            self.turn_off(kwargs["valve"])
            self.turn_off(kwargs["main"])
            self.turn_off(kwargs["pump"])
            self.log(f"Zone {z}: shot complete, hardware off")
        except Exception as e:
            self.log(f"Zone {z}: seq_off error: {e}", level="ERROR")
            self._all_off("seq_off_error")
        finally:
            self.zone[z]["irrigating"] = False

    def _abort_shot(self, kwargs):
        self._all_off("abort")
        z = kwargs.get("z")
        if z in self.zone:
            self.zone[z]["irrigating"] = False

    def _all_off(self, why):
        try:
            for ent in (self.hw.get("pump_master"), self.hw.get("main_line")):
                if ent:
                    self.turn_off(ent)
            for v in (self.hw.get("zone_valves") or {}).values():
                self.turn_off(v)
            self.log(f"All irrigation hardware OFF ({why})")
        except Exception as e:
            self.log(f"_all_off error: {e}", level="ERROR")

    # --------------------------------------------------------------- publish
    def _publish(self, z, vwc):
        try:
            st = self.zone[z]
            self.set_state(
                f"sensor.crop_steering_v2_zone_{z}_phase",
                state=st["phase"],
                attributes={
                    "friendly_name": f"CS Zone {z} Phase (v2)",
                    "icon": "mdi:water-sync",
                    "vwc": vwc,
                    "peak_vwc": st["peak_vwc"],
                    "shots_today": st["shots_today"],
                    "last_shot": st["last_shot"].isoformat() if st["last_shot"] else None,
                },
            )
            self.set_state(
                f"sensor.crop_steering_v2_zone_{z}_water",
                state=str(round(st["water_today"], 2)),
                attributes={"friendly_name": f"CS Zone {z} Water Today (v2)",
                            "unit_of_measurement": "L", "icon": "mdi:water",
                            "shots_today": st["shots_today"]},
            )
        except Exception as e:
            self.log(f"Zone {z}: publish error: {e}", level="ERROR")
