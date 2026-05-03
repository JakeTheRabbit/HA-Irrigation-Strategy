"""Pillar 3 — Agronomic Intelligence.

- TranspirationModel    : Penman–Monteith approximation per zone.
- ClimateSubstrateModel : rolling correlation between VPD and dryback velocity.
- RunAnalytics          : nightly aggregation that emits `crop_steering_run_report`.

This file is a runnable AppDaemon app. It is read-mostly: it consumes
sensor data and bus events, writes to the analytics store, and emits HA
events but never schedules irrigation directly.
"""
from __future__ import annotations

import json
import logging
import math
import statistics
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Deque

from .base import IntelligenceApp
from .bus import RootSenseBus
from .store import RootSenseStore

_LOGGER = logging.getLogger(__name__)


@dataclass
class TranspirationSample:
    ts: datetime
    et_ml_per_hr: float
    vpd_kpa: float
    ppfd: float


class AgronomicIntelligence(IntelligenceApp):
    def initialize(self) -> None:
        self.bus = RootSenseBus.instance()
        self.store = RootSenseStore(self._state_dir() / "rootsense.db")

        cfg = self.args or {}
        self.air_movement_m_s: float = float(cfg.get("room_air_movement_m_s", 0.3))
        self.canopy_temp_entity: str | None = cfg.get("canopy_temp_entity")
        self.air_temp_entity: str | None = cfg.get("air_temp_entity")
        self.rh_entity: str | None = cfg.get("rh_entity")
        self.ppfd_entity: str | None = cfg.get("ppfd_entity")
        self.lights_off_entity: str = cfg.get("lights_off_entity", "binary_sensor.crop_steering_lights")

        self._samples: dict[int, Deque[TranspirationSample]] = defaultdict(lambda: deque(maxlen=720))
        self._dryback_window: dict[int, Deque[tuple[float, float]]] = defaultdict(lambda: deque(maxlen=120))

        # Compute & publish transpiration every 5 minutes
        self.run_every(self._publish_transpiration, "now+30", 300)

        # Subscribe to dryback events to feed the climate-substrate correlator
        self.bus.subscribe("dryback.complete", self._on_dryback_complete)

        # Nightly run report
        self.run_daily(self._emit_run_report, "23:55:00")

        self.log("AgronomicIntelligence ready")

    # ------------------------------------------------------------------ Transpiration

    def _publish_transpiration(self, _kwargs: Any) -> None:
        if not self._is_module_enabled():
            return
        vpd = self._read_vpd_kpa()
        ppfd = self._read_float(self.ppfd_entity, default=0.0) if self.ppfd_entity else 0.0
        if vpd is None:
            return
        et_total_ml_h = self._penman_monteith_ml_per_hr(vpd_kpa=vpd, ppfd=ppfd)
        for zone in self._configured_zones():
            # Per-zone gain calibration TBD in PR #4 — start with global value.
            self._samples[zone].append(TranspirationSample(
                ts=datetime.utcnow(), et_ml_per_hr=et_total_ml_h, vpd_kpa=vpd, ppfd=ppfd,
            ))
            self.set_state(
                f"sensor.crop_steering_zone_{zone}_transpiration_ml_per_hr",
                state=round(et_total_ml_h, 1),
                attributes={
                    "vpd_kpa": round(vpd, 3),
                    "ppfd": round(ppfd, 1),
                    "unit_of_measurement": "mL/h",
                    "friendly_name": f"Zone {zone} Transpiration",
                    "icon": "mdi:water-sync",
                },
            )

    def _penman_monteith_ml_per_hr(self, vpd_kpa: float, ppfd: float) -> float:
        """Hourly transpiration estimate, mL of water per hour per plant.

        Simplified Penman-Monteith: assumes 1 m² leaf area, gamma=0.066 kPa/°C.
        Real implementation uses canopy LAI from a future vision module; here
        we approximate ET (mm/h) ≈ k * VPD * f(PPFD), with k tuned in PR #4.
        """
        # ET (mm/h) ≈ 0.06 * VPD * (1 + PPFD/2000); 1 mm = 1 L/m²
        et_mm_h = 0.06 * vpd_kpa * (1.0 + min(ppfd, 2000.0) / 2000.0)
        # 1 m² leaf area placeholder ⇒ 1 mm = 1000 mL
        return max(0.0, et_mm_h * 1000.0 / 4.0)  # /4 for "per plant" rough scaling

    def _read_vpd_kpa(self) -> float | None:
        # Either pull a precomputed VPD sensor, or derive from temp + RH
        vpd = self.get_state("sensor.crop_steering_vpd")
        try:
            return float(vpd)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pass
        t = self._read_float(self.air_temp_entity)
        rh = self._read_float(self.rh_entity)
        if t is None or rh is None:
            return None
        es = 0.6108 * math.exp(17.27 * t / (t + 237.3))
        ea = es * (rh / 100.0)
        return max(0.0, es - ea)

    # ------------------------------------------------------------------ Climate↔Substrate

    def _on_dryback_complete(self, _topic: str, payload: dict[str, Any]) -> None:
        if not self._is_module_enabled():
            return
        zone = int(payload.get("zone", 0))
        velocity = float(payload.get("slope_pct_h", 0.0))  # %/hour
        vpd_avg = float(payload.get("vpd_avg", 0.0))
        if vpd_avg <= 0:
            return
        self._dryback_window[zone].append((vpd_avg, velocity))
        self._publish_vpd_ceiling(zone)

    def _publish_vpd_ceiling(self, zone: int) -> None:
        samples = list(self._dryback_window[zone])
        if len(samples) < 10:
            return
        # Find VPD bin where dryback velocity slope sharply increases.
        sorted_by_vpd = sorted(samples, key=lambda s: s[0])
        vpds = [s[0] for s in sorted_by_vpd]
        vels = [s[1] for s in sorted_by_vpd]
        # Naive: ceiling = VPD at which velocity exceeds 1.5× median
        median_v = statistics.median(vels)
        ceiling = next((v for v, vel in sorted_by_vpd if vel > 1.5 * median_v), max(vpds))
        cultivar = self._read_zone_cultivar(zone) or "unknown"
        self.set_state(
            f"sensor.crop_steering_cultivar_{cultivar}_vpd_ceiling_kpa",
            state=round(ceiling, 2),
            attributes={
                "sample_count": len(samples),
                "median_velocity_pct_per_hr": round(median_v, 3),
                "unit_of_measurement": "kPa",
                "friendly_name": f"VPD ceiling — {cultivar}",
                "icon": "mdi:weather-windy",
            },
        )

    # ------------------------------------------------------------------ Run report

    def _emit_run_report(self, _kwargs: Any) -> None:
        if not self._is_module_enabled():
            return
        run_date = datetime.utcnow().date().isoformat()
        report: dict[str, Any] = {"run_date": run_date, "zones": {}}
        for zone in self._configured_zones():
            shots = self.store.recent_shots(zone, hours=24)
            report["zones"][zone] = {
                "shot_count": len(shots),
                "total_volume_ml": round(sum(s.get("volume_ml") or 0 for s in shots), 1),
                "mean_runoff_pct": round(
                    statistics.mean([s["runoff_pct"] for s in shots if s.get("runoff_pct") is not None] or [0.0]), 2
                ),
            }
        self.store.write_run_report(run_date, report)
        self.bus.publish("run.report", report)
        self.fire_event("crop_steering_run_report", report=report)
        self.log("Emitted run report for %s (%d zones)", run_date, len(report["zones"]))

    # ------------------------------------------------------------------ helpers

    def _read_float(self, entity_id: str | None, default: float | None = None) -> float | None:
        # Override of base helper — accepts None entity_id (returns default).
        if not entity_id:
            return default
        return super()._read_float(entity_id, default=default)

    def _read_zone_cultivar(self, zone: int) -> str | None:
        return self.get_state(f"select.crop_steering_zone_{zone}_crop_type")  # type: ignore[return-value]

    # _configured_zones / entity_exists live on IntelligenceApp.
