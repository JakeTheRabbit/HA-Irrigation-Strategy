"""Hardware calibration loader and helpers.

Single source of truth for the per-actuator quirks ClimateSense control
loops account for. Reads the `hardware_<room>.yaml` file and exposes
typed accessors:

- `HVACCalibration` — cool/heat offsets, deadband, settle time, range.
- `DehumidifierCalibration` — relay list, stagger, min-off.
- `HumidifierCalibration` — entity, min-off.
- `CO2Calibration` — solenoid, pulse cadence, hard cap, lights-off behaviour.
- `SensorMap` — which sensor entity provides which metric.

The calibration file is intentionally YAML, not Python — operators
edit it directly when their hardware behaviour drifts. The control
loops re-read it on each tick (cheap), so changes take effect
immediately without restarting AppDaemon.

Why this matters: a heat pump set to 27 °C may settle the room at
29 °C because the unit measures return-air, lights add radiant heat,
and the unit's deadband is wider than the canopy can tolerate. The
calibration captures that as `cool_offset_c: -2.0` — ClimateSense
commands the unit to 25 °C and the room actually reaches 27 °C.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

_LOGGER = logging.getLogger(__name__)


@dataclass
class HVACCalibration:
    entity: str
    cool_offset_c: float = 0.0
    heat_offset_c: float = 0.0
    min_setpoint_c: float = 16.0
    max_setpoint_c: float = 30.0
    settle_minutes: float = 8.0
    deadband_c: float = 0.5

    def commanded_setpoint(self, target_c: float, current_c: float) -> float:
        """Return the setpoint to actually send to the unit, accounting for
        the per-direction calibration offset and the configured range.

        Direction is decided by which side of the target we're on:
          - current > target → cooling needed → use cool_offset
          - current < target → heating needed → use heat_offset
          - within deadband  → no change requested

        Offsets are signed: cool_offset_c=-2.0 means "to land at target,
        command target − 2 °C lower than what you'd naively send".
        """
        if abs(current_c - target_c) < self.deadband_c:
            return target_c  # in deadband, no calibration needed
        if current_c > target_c:
            commanded = target_c + self.cool_offset_c
        else:
            commanded = target_c + self.heat_offset_c
        return max(self.min_setpoint_c, min(self.max_setpoint_c, commanded))


@dataclass
class DehumidifierCalibration:
    relays: list[str] = field(default_factory=list)
    stagger_seconds: int = 10
    min_off_seconds: int = 120


@dataclass
class HumidifierCalibration:
    entity: str = ""
    min_off_seconds: int = 120


@dataclass
class CO2Calibration:
    solenoid: str = ""
    pulse_on_seconds: int = 60
    pulse_off_seconds: int = 240
    hard_max_ppm: float = 1800.0
    off_at_lights_off: bool = True


@dataclass
class SensorMap:
    temp_primary: str = ""
    rh_primary: str = ""
    co2: str = ""
    vpd: str = ""
    lights_on: str = ""
    leak: str = ""
    tank_low: str = ""
    ppfd: str | None = None
    canopy_temp: str | None = None


@dataclass
class HardwareCalibration:
    room: str
    hvac_primary: HVACCalibration | None = None
    dehumidifier: DehumidifierCalibration = field(default_factory=DehumidifierCalibration)
    humidifier: HumidifierCalibration = field(default_factory=HumidifierCalibration)
    co2: CO2Calibration = field(default_factory=CO2Calibration)
    sensors: SensorMap = field(default_factory=SensorMap)


def load_hardware_calibration(path: Path | str) -> HardwareCalibration:
    """Load and validate a hardware_<room>.yaml file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Hardware calibration file not found: {p}")
    if yaml is None:
        raise RuntimeError("PyYAML is not available — install it in the AppDaemon container")

    raw = yaml.safe_load(p.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"Hardware calibration root must be a mapping in {p}")

    room = str(raw.get("room", "unknown"))
    hvac = None
    if (h := raw.get("hvac", {}).get("primary")) is not None:
        hvac = HVACCalibration(**_filter_keys(h, HVACCalibration))

    dehu_raw = raw.get("dehumidifier", {}) or {}
    dehu = DehumidifierCalibration(**_filter_keys(dehu_raw, DehumidifierCalibration))

    humid_raw = raw.get("humidifier", {}) or {}
    humid = HumidifierCalibration(**_filter_keys(humid_raw, HumidifierCalibration))

    co2_raw = raw.get("co2", {}) or {}
    co2 = CO2Calibration(**_filter_keys(co2_raw, CO2Calibration))

    sensors_raw = raw.get("sensors", {}) or {}
    sensors = SensorMap(**_filter_keys(sensors_raw, SensorMap))

    return HardwareCalibration(
        room=room,
        hvac_primary=hvac,
        dehumidifier=dehu,
        humidifier=humid,
        co2=co2,
        sensors=sensors,
    )


def _filter_keys(d: dict[str, Any], cls) -> dict[str, Any]:
    """Drop keys not in the dataclass — forward-compatible with new YAML keys."""
    fields = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    return {k: v for k, v in d.items() if k in fields}
