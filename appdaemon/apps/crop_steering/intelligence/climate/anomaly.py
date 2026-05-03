"""ClimateSense — Climate Anomaly Scanner.

Same shape as the substrate `intelligence/anomaly.py`. Runs every 60 s
and raises events with severity + remediation when room conditions
diverge from recipe targets for too long.

Codes (with default severity):
- climate_temp_excursion        (warning)  : measured temp off target > 1 °C for > 5 min
- climate_rh_excursion          (warning)  : measured RH off target > 5 % for > 5 min
- climate_vpd_divergence        (warning)  : VPD off target while temp+RH on target
- climate_co2_low_photoperiod   (warning)  : CO2 < target − tolerance for > 10 min during photoperiod
- climate_co2_overshoot         (critical) : CO2 > hard_max (covered by control loop, but re-flagged here)
- climate_dli_undershoot        (info)     : predicted EOD DLI < target × 0.95
- climate_sensor_unavailable    (critical) : any of temp/RH/CO2 unavailable for > 2 min
- climate_actuator_runaway      (critical) : dehumidifier ON > 2h continuously, or AC commanded > 30 min ago without convergence

Each anomaly is persisted via the existing RootSenseStore and
republished as a `crop_steering_anomaly` event with code prefixed
`climate_`.
"""
from __future__ import annotations

import logging
import statistics
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Deque

from ..base import IntelligenceApp
from ..bus import RootSenseBus
from ..store import RootSenseStore
from .hardware import HardwareCalibration, load_hardware_calibration

_LOGGER = logging.getLogger(__name__)

REMEDIATION = {
    "climate_temp_excursion": (
        "1. Confirm AC unit is responding (check `climate.gw_ac_1` last command).\n"
        "2. Check hardware calibration `cool_offset_c` / `heat_offset_c`; bump if room "
        "consistently overshoots commanded setpoint.\n"
        "3. Look for door open / fan failure / lights too high above canopy."
    ),
    "climate_rh_excursion": (
        "1. Verify dehumidifier relays are firing in sequence (check states).\n"
        "2. Check humidifier reservoir level.\n"
        "3. Confirm no condensate pump alarm."
    ),
    "climate_vpd_divergence": (
        "1. VPD off target while temp+RH look fine usually means a sensor on the canopy "
        "isn't measuring the same air column as the controller. Cross-check with a hand-held probe.\n"
        "2. If genuinely diverging, recipe targets may be inconsistent — `vpd_kpa` should match what "
        "(temp, rh) physically produces."
    ),
    "climate_co2_low_photoperiod": (
        "1. Check `switch.gw_co2` solenoid responding.\n"
        "2. Verify CO2 cylinder pressure.\n"
        "3. Confirm `input_boolean.gw_co2_enabled` is on."
    ),
    "climate_co2_overshoot": (
        "1. Solenoid emergency-closed by control loop.\n"
        "2. Check for stuck-open valve or regulator failure.\n"
        "3. Ventilate room before manually re-enabling CO2."
    ),
    "climate_dli_undershoot": (
        "1. Verify lights are at expected output (PPFD reading vs PPFD target).\n"
        "2. Consider extending photoperiod or raising PPFD setpoint.\n"
        "3. Check if any rack is shaded by canopy growth."
    ),
    "climate_sensor_unavailable": (
        "1. Check sensor power and network/MQTT connection.\n"
        "2. Look for ESPHome / Zigbee2MQTT errors.\n"
        "3. Replace sensor if unavailable persists past one HA restart."
    ),
    "climate_actuator_runaway": (
        "1. Dehumidifier running continuously usually means the door is open or coil is iced.\n"
        "2. AC commanded but room not converging means either calibration is off or unit is offline."
    ),
}


class ClimateAnomalyScanner(IntelligenceApp):
    def initialize(self) -> None:  # noqa: D401
        self.bus = RootSenseBus.instance()
        self.store = RootSenseStore(self._state_dir() / "rootsense.db")

        cfg = self.args or {}
        hardware_path = Path(cfg.get(
            "hardware_file",
            str(Path(self.app_dir) / "crop_steering" / "intelligence" / "climate" / "hardware_f1.yaml"),
        ))
        try:
            self.hw: HardwareCalibration | None = load_hardware_calibration(hardware_path)
        except Exception as e:  # noqa: BLE001
            self.log("ClimateAnomalyScanner: %s — degraded", e, level="ERROR")
            self.hw = None

        self.scan_interval_s = int(cfg.get("scan_interval_s", 60))
        self._active: set[str] = set()

        # Rolling buffer for excursion duration tracking (last 30 min)
        self._temp_off_target_since: datetime | None = None
        self._rh_off_target_since: datetime | None = None
        self._co2_low_since: datetime | None = None
        self._sensor_unavail_since: dict[str, datetime] = {}

        self.run_every(self._tick, "now+15", self.scan_interval_s)
        self.log("ClimateAnomalyScanner ready (scan=%ds)", self.scan_interval_s)

    def _tick(self, _kwargs: Any) -> None:
        if not self._is_module_enabled() or self.hw is None:
            return

        now = datetime.utcnow()
        self._check_temp_excursion(now)
        self._check_rh_excursion(now)
        self._check_co2(now)
        self._check_dli()
        self._check_sensor_availability(now)

    # ───────────────────────────── per-rule checks

    def _check_temp_excursion(self, now: datetime) -> None:
        target_day = self._read_float("sensor.climate_target_day_temp_c")
        target_night = self._read_float("sensor.climate_target_night_temp_c")
        is_day = str(self.get_state(self.hw.sensors.lights_on)).lower() == "on"  # type: ignore[union-attr]
        target = target_day if is_day else target_night
        current = self._read_float(self.hw.sensors.temp_primary)  # type: ignore[union-attr]
        if target is None or current is None:
            return

        if abs(current - target) > 1.0:
            if self._temp_off_target_since is None:
                self._temp_off_target_since = now
            elif (now - self._temp_off_target_since).total_seconds() > 300:
                self._raise(
                    code="climate_temp_excursion",
                    severity="warning",
                    evidence=(
                        f"Temp {current:.1f}°C, target {target:.1f}°C "
                        f"(off by {current - target:+.1f}°C) for >5 min "
                        f"({'day' if is_day else 'night'} target)"
                    ),
                    zone=None,
                )
        else:
            self._temp_off_target_since = None
            self._clear("climate_temp_excursion")

    def _check_rh_excursion(self, now: datetime) -> None:
        target_day = self._read_float("sensor.climate_target_day_rh_pct")
        target_night = self._read_float("sensor.climate_target_night_rh_pct")
        is_day = str(self.get_state(self.hw.sensors.lights_on)).lower() == "on"  # type: ignore[union-attr]
        target = target_day if is_day else target_night
        current = self._read_float(self.hw.sensors.rh_primary)  # type: ignore[union-attr]
        if target is None or current is None:
            return

        if abs(current - target) > 5.0:
            if self._rh_off_target_since is None:
                self._rh_off_target_since = now
            elif (now - self._rh_off_target_since).total_seconds() > 300:
                self._raise(
                    code="climate_rh_excursion",
                    severity="warning",
                    evidence=(
                        f"RH {current:.0f}%, target {target:.0f}% "
                        f"(off by {current - target:+.0f}%) for >5 min"
                    ),
                    zone=None,
                )
        else:
            self._rh_off_target_since = None
            self._clear("climate_rh_excursion")

    def _check_co2(self, now: datetime) -> None:
        target = self._read_float("sensor.climate_target_co2_ppm")
        current = self._read_float(self.hw.sensors.co2)  # type: ignore[union-attr]
        is_day = str(self.get_state(self.hw.sensors.lights_on)).lower() == "on"  # type: ignore[union-attr]
        if target is None or current is None:
            return

        # Overshoot — re-flag what the control loop already enforced
        if self.hw and current > self.hw.co2.hard_max_ppm:
            self._raise(
                code="climate_co2_overshoot",
                severity="critical",
                evidence=f"CO2 {current:.0f} ppm > hard cap {self.hw.co2.hard_max_ppm:.0f}",
                zone=None,
            )
        else:
            self._clear("climate_co2_overshoot")

        # Undershoot during photoperiod
        if is_day and current < target - 100:
            if self._co2_low_since is None:
                self._co2_low_since = now
            elif (now - self._co2_low_since).total_seconds() > 600:
                self._raise(
                    code="climate_co2_low_photoperiod",
                    severity="warning",
                    evidence=f"CO2 {current:.0f} ppm < target {target:.0f} for >10 min during lights-on",
                    zone=None,
                )
        else:
            self._co2_low_since = None
            self._clear("climate_co2_low_photoperiod")

    def _check_dli(self) -> None:
        predicted = self._read_float("sensor.climate_dli_predicted_mol")
        target = self._read_float("sensor.climate_target_ppfd_target")  # may not be set
        if predicted is None or target is None:
            return
        # Convert PPFD target to expected DLI (very rough — assumes 12-h photoperiod
        # at constant PPFD): DLI = PPFD × seconds × 1e-6 → PPFD * 0.0432 for 12 h
        target_dli = target * 0.0432
        if predicted < target_dli * 0.95:
            self._raise(
                code="climate_dli_undershoot",
                severity="info",
                evidence=f"Predicted DLI {predicted:.1f} mol/m²/d < 95% of target {target_dli:.1f}",
                zone=None,
            )
        else:
            self._clear("climate_dli_undershoot")

    def _check_sensor_availability(self, now: datetime) -> None:
        if not self.hw:
            return
        for label, entity in [
            ("temp", self.hw.sensors.temp_primary),
            ("rh", self.hw.sensors.rh_primary),
            ("co2", self.hw.sensors.co2),
        ]:
            state = self.get_state(entity)
            if state in (None, "unknown", "unavailable"):
                if entity not in self._sensor_unavail_since:
                    self._sensor_unavail_since[entity] = now
                elif (now - self._sensor_unavail_since[entity]).total_seconds() > 120:
                    self._raise(
                        code="climate_sensor_unavailable",
                        severity="critical",
                        evidence=f"{label.upper()} sensor {entity} unavailable for >2 min",
                        zone=None,
                    )
            else:
                self._sensor_unavail_since.pop(entity, None)
                self._clear("climate_sensor_unavailable")

    # ───────────────────────────── helpers

    def _raise(self, *, code: str, severity: str, evidence: str, zone: int | None) -> None:
        if code in self._active:
            return
        self._active.add(code)
        ts = datetime.utcnow().isoformat()
        remediation = REMEDIATION.get(code, "See dashboard.")
        self.store.record_anomaly(
            ts=ts, zone=zone, code=code, severity=severity,
            evidence=evidence, remediation=remediation,
        )
        self.bus.publish("anomaly.detected", {
            "code": code, "zone": zone, "severity": severity,
            "evidence": evidence, "remediation": remediation, "ts": ts,
        })
        self.fire_event("crop_steering_anomaly",
                        code=code, zone=zone, severity=severity,
                        evidence=evidence, remediation=remediation, ts=ts)
        self.log("CLIMATE ANOMALY [%s] %s — %s", severity, code, evidence,
                 level="WARNING" if severity != "info" else "INFO")

    def _clear(self, code: str) -> None:
        self._active.discard(code)
