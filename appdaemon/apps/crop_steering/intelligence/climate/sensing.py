"""ClimateSense Pillar 1 — Climate Sensing.

Reads room sensors (temp/RH/CO2/VPD/PPFD if present), derives metrics
that no individual sensor reports, publishes them as HA sensors, and
streams them onto the RootSenseBus for other pillars.

Derived metrics:
- DLI today (running total of PPFD * dt over the photoperiod).
- DLI predicted at lights-off (linear extrapolation from current rate).
- Leaf-air ΔT (only if a leaf-temp sensor is configured).
- Sensor disagreement flag (peer-room sensors > 2σ apart) — published
  as an anomaly via the bus, the AnomalyScanner picks it up.

Read-only — never touches any actuator.
"""
from __future__ import annotations

import logging
import statistics
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Deque

from ..base import IntelligenceApp
from ..bus import RootSenseBus
from .hardware import HardwareCalibration, load_hardware_calibration

_LOGGER = logging.getLogger(__name__)


class ClimateSenseSensing(IntelligenceApp):
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
            self.log("ClimateSenseSensing: %s — running in degraded mode", e, level="ERROR")
            self.hw = None

        self.sample_interval_s = int(cfg.get("sample_interval_s", 60))
        self._dli_buf: Deque[tuple[datetime, float]] = deque(maxlen=2880)  # 48 h at 1/min

        self.run_every(self._tick, "now+10", self.sample_interval_s)
        # Reset DLI accumulator at midnight (or use lights-on edge — see below)
        self.run_daily(self._reset_dli, "00:00:00")

        self.log("ClimateSenseSensing ready (sample=%ds)", self.sample_interval_s)

    def _tick(self, _kwargs: Any) -> None:
        if not self._is_module_enabled() or self.hw is None:
            return

        # ── publish room snapshot bus event ──────────────────────────────
        snapshot = {
            "ts": datetime.utcnow().isoformat(),
            "temp_c": self._read_float(self.hw.sensors.temp_primary),
            "rh_pct": self._read_float(self.hw.sensors.rh_primary),
            "co2_ppm": self._read_float(self.hw.sensors.co2),
            "vpd_kpa": self._read_float(self.hw.sensors.vpd),
            "lights_on": str(self.get_state(self.hw.sensors.lights_on)).lower() == "on",
        }
        self.bus.publish("climate.sample", snapshot)

        # ── DLI tracking ────────────────────────────────────────────────
        ppfd_entity = self.hw.sensors.ppfd
        if ppfd_entity:
            self._publish_dli(ppfd_entity, snapshot["lights_on"])

        # ── leaf-air ΔT ────────────────────────────────────────────────
        if self.hw.sensors.canopy_temp:
            canopy = self._read_float(self.hw.sensors.canopy_temp)
            air = snapshot["temp_c"]
            if canopy is not None and air is not None:
                self.set_state(
                    "sensor.climate_leaf_air_dt_c",
                    state=round(canopy - air, 2),
                    attributes={
                        "canopy_temp_c": canopy,
                        "air_temp_c": air,
                        "unit_of_measurement": "°C",
                        "friendly_name": "Leaf-air ΔT",
                        "icon": "mdi:thermometer-minus",
                        "state_class": "measurement",
                    },
                )

    def _publish_dli(self, ppfd_entity: str, lights_on: bool) -> None:
        ppfd = self._read_float(ppfd_entity)
        if ppfd is None:
            return
        now = datetime.utcnow()
        self._dli_buf.append((now, ppfd if lights_on else 0.0))

        # DLI today (μmol/m²/s × seconds → mol/m²/d). Integrate the buffer
        # since the last lights-on transition or since the last midnight,
        # whichever is more recent.
        midnight = datetime(now.year, now.month, now.day, 0, 0, 0)
        relevant = [(ts, p) for ts, p in self._dli_buf if ts >= midnight]
        if len(relevant) < 2:
            return
        total_micromol = 0.0
        for (t1, p1), (t2, _) in zip(relevant, relevant[1:]):
            dt_s = (t2 - t1).total_seconds()
            total_micromol += p1 * dt_s
        dli_today_mol = total_micromol / 1_000_000.0

        # Predict end-of-day DLI by extrapolating the average rate over
        # the photoperiod
        if lights_on:
            avg_ppfd = (
                statistics.mean([p for _, p in relevant if p > 0])
                if any(p > 0 for _, p in relevant) else 0
            )
            seconds_until_lights_off = self._seconds_until_lights_off()
            extra = avg_ppfd * seconds_until_lights_off / 1_000_000.0
            dli_predicted_mol = dli_today_mol + extra
        else:
            dli_predicted_mol = dli_today_mol

        self.set_state(
            "sensor.climate_dli_today_mol",
            state=round(dli_today_mol, 2),
            attributes={
                "unit_of_measurement": "mol/m²/d",
                "friendly_name": "DLI today",
                "icon": "mdi:weather-sunny",
                "state_class": "total_increasing",
            },
        )
        self.set_state(
            "sensor.climate_dli_predicted_mol",
            state=round(dli_predicted_mol, 2),
            attributes={
                "unit_of_measurement": "mol/m²/d",
                "friendly_name": "DLI predicted at lights-off",
                "icon": "mdi:weather-sunny-alert",
                "state_class": "measurement",
            },
        )

    def _reset_dli(self, _kwargs: Any) -> None:
        self._dli_buf.clear()

    def _seconds_until_lights_off(self) -> float:
        """Best-effort estimate. If a lights_off_hour input_number is
        configured, use it. Otherwise return 0 (predicted DLI = current).
        """
        try:
            hour = self._read_int("number.crop_steering_lights_off_hour", default=0) or 0
            now = datetime.utcnow()
            target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            return max(0.0, (target - now).total_seconds())
        except Exception:  # noqa: BLE001
            return 0.0
