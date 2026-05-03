"""ClimateSense Pillar 3 — Climate Control.

Closed-loop control of HVAC, dehumidifier, humidifier, and CO2 with
hardware-calibration offsets baked in.

Loops:
- Temp: bang-bang with deadband around `target ± deadband_c`. Sends
  `commanded_setpoint(target, current)` to the HVAC entity, which
  applies the cool/heat offset before sending so e.g. setpoint 25
  produces a measured 27.
- RH: bang-bang with hysteresis matching the existing
  40_environment.yaml defaults (turn dehumidifier on at target+5,
  off at target-2; humidifier mirror image).
- CO2: pulse-injection (on for `pulse_on_seconds`, off for
  `pulse_off_seconds`) while CO2 < target − tolerance and lights are
  on. Hard cap closes the solenoid above `hard_max_ppm`.

Targets come from the timeline pillar via the per-metric
`sensor.climate_target_*` entities. Day-vs-night is decided by
`binary_sensor.gw_lights_on`.

Hard guardrails (all enforced before any service call):
- Dehumidifier never runs while humidifier is on, and vice versa.
- CO2 always closes at lights-off, regardless of measured ppm.
- HVAC commanded setpoint clipped to [min_setpoint_c, max_setpoint_c].
- min_off_seconds prevents short-cycling.
- During `input_boolean.gw_maintenance_mode` ON → no actuator commands.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..base import IntelligenceApp
from ..bus import RootSenseBus
from .hardware import HardwareCalibration, load_hardware_calibration

_LOGGER = logging.getLogger(__name__)


class ClimateSenseControl(IntelligenceApp):
    def initialize(self) -> None:  # noqa: D401
        self.bus = RootSenseBus.instance()
        cfg = self.args or {}
        hardware_path = Path(cfg.get(
            "hardware_file",
            str(Path(self.app_dir) / "crop_steering" / "intelligence" / "climate" / "hardware_f1.yaml"),
        ))
        try:
            self.hw: HardwareCalibration | None = load_hardware_calibration(hardware_path)
            self.log("Loaded hardware calibration for room %s", self.hw.room)
        except Exception as e:  # noqa: BLE001
            self.log("ClimateSenseControl: %s — DISABLED", e, level="ERROR")
            self.hw = None

        self.tick_seconds = int(cfg.get("tick_seconds", 30))
        self.maintenance_entity = cfg.get(
            "maintenance_entity", "input_boolean.gw_maintenance_mode"
        )
        self.environment_enabled_entity = cfg.get(
            "environment_enabled_entity", "input_boolean.gw_environment_enabled"
        )

        # Per-actuator min-off bookkeeping
        self._last_off_at: dict[str, datetime] = {}
        self._last_hvac_command_at: datetime | None = None
        self._co2_phase = "off"           # "on", "off", or "blocked"
        self._co2_phase_until: datetime = datetime.utcnow()

        self.run_every(self._tick, "now+15", self.tick_seconds)

        self.log("ClimateSenseControl ready (tick=%ds)", self.tick_seconds)

    def _tick(self, _kwargs: Any) -> None:
        if not self._is_module_enabled():
            return
        if self.hw is None:
            return
        if not self._is_environment_active():
            return  # operator has globally disabled environment control

        is_day = self._is_lights_on()
        targets = self._resolve_targets(is_day)
        if targets is None:
            return  # timeline pillar hasn't published yet

        current = self._read_room_state()

        self._control_temp(current["temp_c"], targets)
        self._control_rh(current["rh_pct"], targets)
        self._control_co2(current["co2_ppm"], current["lights_on"], targets)

    # ────────────────────────────────────────────────────────── HVAC

    def _control_temp(self, current_c: float | None, targets: dict[str, float]) -> None:
        hvac = self.hw.hvac_primary if self.hw else None
        if hvac is None or current_c is None:
            return
        is_day = self._is_lights_on()
        target = targets.get("day_temp_c" if is_day else "night_temp_c")
        if target is None:
            return

        # Apply calibration: figure out what to actually command the unit.
        commanded = hvac.commanded_setpoint(target_c=target, current_c=current_c)

        # Settle window: don't send a fresh command if we did so recently.
        if self._last_hvac_command_at is not None:
            elapsed_min = (datetime.utcnow() - self._last_hvac_command_at).total_seconds() / 60.0
            if elapsed_min < hvac.settle_minutes:
                return

        # Deadband: skip if we're already close enough to the target.
        if abs(current_c - target) < hvac.deadband_c:
            return

        self.call_service(
            "climate/set_temperature",
            entity_id=hvac.entity,
            temperature=round(commanded, 1),
        )
        self._last_hvac_command_at = datetime.utcnow()
        self.log(
            "HVAC: target=%.1f°C current=%.1f°C → commanded=%.1f°C "
            "(offset=%.1f, settle=%.0fmin)",
            target, current_c, commanded,
            hvac.cool_offset_c if current_c > target else hvac.heat_offset_c,
            hvac.settle_minutes,
        )

    # ────────────────────────────────────────────────────────── RH

    def _control_rh(self, current_pct: float | None, targets: dict[str, float]) -> None:
        if current_pct is None:
            return
        is_day = self._is_lights_on()
        target = targets.get("day_rh_pct" if is_day else "night_rh_pct")
        if target is None:
            return

        # Hysteresis matches the existing 40_environment.yaml defaults
        # so this loop is a drop-in replacement.
        dehu_on_threshold = target + 5
        dehu_off_threshold = target - 2
        humid_on_threshold = target - 5
        humid_off_threshold = target + 2

        if current_pct > dehu_on_threshold:
            self._dehumidify_on()
        elif current_pct < dehu_off_threshold:
            self._dehumidify_off()

        if current_pct < humid_on_threshold:
            self._humidify_on()
        elif current_pct > humid_off_threshold:
            self._humidify_off()

    def _dehumidify_on(self) -> None:
        # Mutually exclusive with humidifier
        self._humidify_off()
        for i, entity in enumerate(self.hw.dehumidifier.relays):  # type: ignore[union-attr]
            if not self._respect_min_off(entity, self.hw.dehumidifier.min_off_seconds):  # type: ignore[union-attr]
                continue
            # Stagger: each subsequent relay turns on `stagger_seconds` later.
            delay = i * self.hw.dehumidifier.stagger_seconds  # type: ignore[union-attr]
            if delay == 0:
                self.call_service("switch/turn_on", entity_id=entity)
            else:
                self.run_in(self._delayed_turn_on, delay, entity_id=entity)

    def _dehumidify_off(self) -> None:
        for entity in self.hw.dehumidifier.relays:  # type: ignore[union-attr]
            if str(self.get_state(entity)).lower() == "on":
                self.call_service("switch/turn_off", entity_id=entity)
                self._last_off_at[entity] = datetime.utcnow()

    def _humidify_on(self) -> None:
        # Mutually exclusive with dehumidifier
        self._dehumidify_off()
        entity = self.hw.humidifier.entity  # type: ignore[union-attr]
        if not entity:
            return
        if not self._respect_min_off(entity, self.hw.humidifier.min_off_seconds):  # type: ignore[union-attr]
            return
        self.call_service("switch/turn_on", entity_id=entity)

    def _humidify_off(self) -> None:
        entity = self.hw.humidifier.entity  # type: ignore[union-attr]
        if entity and str(self.get_state(entity)).lower() == "on":
            self.call_service("switch/turn_off", entity_id=entity)
            self._last_off_at[entity] = datetime.utcnow()

    def _delayed_turn_on(self, kwargs: dict[str, Any]) -> None:
        self.call_service("switch/turn_on", entity_id=kwargs["entity_id"])

    def _respect_min_off(self, entity: str, min_off_s: int) -> bool:
        last = self._last_off_at.get(entity)
        if last and (datetime.utcnow() - last).total_seconds() < min_off_s:
            return False
        return True

    # ────────────────────────────────────────────────────────── CO2

    def _control_co2(self, current_ppm: float | None, lights_on: bool,
                     targets: dict[str, float]) -> None:
        co2 = self.hw.co2 if self.hw else None
        if co2 is None or current_ppm is None:
            return

        # Hard safety cap regardless of phase
        if current_ppm > co2.hard_max_ppm:
            self._co2_solenoid_off()
            return
        if not lights_on and co2.off_at_lights_off:
            self._co2_solenoid_off()
            return

        target = targets.get("co2_ppm")
        if target is None:
            return
        deadband = 50  # ppm — small cushion to avoid pulsing right at target
        if current_ppm >= target - deadband:
            self._co2_solenoid_off()
            return

        # Pulse cycle
        now = datetime.utcnow()
        if now < self._co2_phase_until:
            return
        if self._co2_phase in ("off", "blocked"):
            self._co2_solenoid_on()
            self._co2_phase = "on"
            self._co2_phase_until = now + timedelta(seconds=co2.pulse_on_seconds)
        else:
            self._co2_solenoid_off()
            self._co2_phase = "off"
            self._co2_phase_until = now + timedelta(seconds=co2.pulse_off_seconds)

    def _co2_solenoid_on(self) -> None:
        if self.hw and self.hw.co2.solenoid:
            self.call_service("switch/turn_on", entity_id=self.hw.co2.solenoid)

    def _co2_solenoid_off(self) -> None:
        if self.hw and self.hw.co2.solenoid:
            if str(self.get_state(self.hw.co2.solenoid)).lower() == "on":
                self.call_service("switch/turn_off", entity_id=self.hw.co2.solenoid)
        self._co2_phase = "off"
        self._co2_phase_until = datetime.utcnow()

    # ────────────────────────────────────────────────────────── Helpers

    def _resolve_targets(self, is_day: bool) -> dict[str, float] | None:
        """Read the per-metric target sensors published by the timeline."""
        keys = [
            "day_temp_c", "night_temp_c",
            "day_rh_pct", "night_rh_pct",
            "vpd_kpa", "co2_ppm",
        ]
        out: dict[str, float] = {}
        for k in keys:
            v = self._read_float(f"sensor.climate_target_{k}")
            if v is not None:
                out[k] = v
        if not out:
            return None
        return out

    def _read_room_state(self) -> dict[str, Any]:
        return {
            "temp_c": self._read_float(self.hw.sensors.temp_primary) if self.hw else None,
            "rh_pct": self._read_float(self.hw.sensors.rh_primary) if self.hw else None,
            "co2_ppm": self._read_float(self.hw.sensors.co2) if self.hw else None,
            "vpd_kpa": self._read_float(self.hw.sensors.vpd) if self.hw else None,
            "lights_on": self._is_lights_on(),
        }

    def _is_lights_on(self) -> bool:
        if not self.hw:
            return False
        return str(self.get_state(self.hw.sensors.lights_on)).lower() == "on"

    def _is_environment_active(self) -> bool:
        # Both: master enable AND not in maintenance mode.
        env = str(self.get_state(self.environment_enabled_entity)).lower() == "on"
        maint = str(self.get_state(self.maintenance_entity)).lower() == "on"
        return env and not maint
