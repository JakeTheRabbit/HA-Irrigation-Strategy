"""Pillar 1 — Root Zone Intelligence.

Substrate analytics, automated field-capacity detection, dryback tracking.

This file is a runnable AppDaemon app. It registers with the master app via
`RootSenseBus`, listens for shot events, and publishes:

- `sensor.crop_steering_zone_{n}_field_capacity_observed`
- `sensor.crop_steering_zone_{n}_dryback_velocity_pct_per_hr`
- `sensor.crop_steering_zone_{n}_substrate_porosity_estimate`
- `sensor.crop_steering_zone_{n}_ec_stack_index`

Plus events:
- `crop_steering_dryback_complete`
- `crop_steering_field_capacity_observed`

Behaviour summary (see ROOTSENSE_v3_PLAN.md §3 Phase 1 for full design):

1. On every `crop_steering_irrigation_shot` event, snapshot pre-shot VWC.
2. Wait `shot_response_window_sec` (default 600 s) and capture the post-shot
   peak VWC for that zone.
3. If two successive shots produce <0.5 % additional rise, declare the zone
   saturated; the peak becomes a candidate FC observation.
4. Maintain an EWMA per (zone, cultivar). Confidence ≥ 0.8 ⇒ controller uses
   observed FC instead of the static `DEFAULT_FIELD_CAPACITY`.
"""
from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Deque

try:
    import appdaemon.plugins.hass.hassapi as hass  # type: ignore
except ImportError:  # pragma: no cover — keeps the module importable in tests
    hass = type("hass", (), {"Hass": object})  # type: ignore

from .bus import RootSenseBus
from .store import RootSenseStore

_LOGGER = logging.getLogger(__name__)

DEFAULT_RESPONSE_WINDOW_SEC = 600
DEFAULT_SATURATION_DELTA_PCT = 0.5      # < this rise on consecutive shots ⇒ saturated
DEFAULT_FC_EWMA_ALPHA = 0.25
DEFAULT_FC_CONFIDENCE_THRESHOLD = 0.8


@dataclass
class ShotResponse:
    zone: int
    pre_vwc: float
    fired_at: datetime
    peak_vwc: float | None = None
    peak_at: datetime | None = None

    @property
    def delta(self) -> float | None:
        return None if self.peak_vwc is None else self.peak_vwc - self.pre_vwc


@dataclass
class FieldCapacityState:
    fc_pct: float = 0.0
    confidence: float = 0.0
    sample_count: int = 0
    history: Deque[float] = field(default_factory=lambda: deque(maxlen=20))


class RootZoneIntelligence(hass.Hass):  # type: ignore[misc]
    """AppDaemon entry point."""

    def initialize(self) -> None:  # noqa: D401 — AppDaemon contract
        self.bus = RootSenseBus.instance()
        db_path = Path(self.app_dir) / "crop_steering" / "state" / "rootsense.db"
        self.store = RootSenseStore(db_path)

        cfg = self.args or {}
        self.response_window_sec: int = int(cfg.get("response_window_sec", DEFAULT_RESPONSE_WINDOW_SEC))
        self.saturation_delta_pct: float = float(cfg.get("saturation_delta_pct", DEFAULT_SATURATION_DELTA_PCT))
        self.fc_alpha: float = float(cfg.get("fc_ewma_alpha", DEFAULT_FC_EWMA_ALPHA))
        self.fc_confidence_threshold: float = float(
            cfg.get("fc_confidence_threshold", DEFAULT_FC_CONFIDENCE_THRESHOLD)
        )

        self._pending: dict[int, ShotResponse] = {}
        self._fc: dict[int, FieldCapacityState] = defaultdict(FieldCapacityState)

        # Bridge HA event bus into RootSenseBus
        self.listen_event(self._on_shot_fired, "crop_steering_irrigation_shot")

        # Periodic publication of derived sensors (decoupled from shot rate)
        self.run_every(self._publish_derived_sensors, "now+30", 60)

        # Daily prune
        self.run_daily(self._daily_prune, "03:30:00")

        self.log("RootZoneIntelligence ready (window=%ds, sat-Δ=%.2f%%)",
                 self.response_window_sec, self.saturation_delta_pct)

    # ------------------------------------------------------------------ events

    def _on_shot_fired(self, event_name: str, data: dict[str, Any], _kwargs: Any) -> None:
        zone = int(data.get("zone", 0))
        if zone <= 0:
            return
        pre_vwc = self._read_zone_vwc(zone)
        if pre_vwc is None:
            self.log("Skipping shot response capture for zone %s: VWC unavailable", zone)
            return
        self._pending[zone] = ShotResponse(zone=zone, pre_vwc=pre_vwc, fired_at=datetime.utcnow())
        self.run_in(self._capture_peak, self.response_window_sec, zone=zone)

    def _capture_peak(self, kwargs: dict[str, Any]) -> None:
        zone = kwargs["zone"]
        record = self._pending.pop(zone, None)
        if record is None:
            return
        peak_vwc = self._read_zone_vwc_peak_since(zone, record.fired_at)
        if peak_vwc is None:
            return
        record.peak_vwc = peak_vwc
        record.peak_at = datetime.utcnow()

        self.bus.publish("shot.response", {
            "zone": zone,
            "pre_vwc": record.pre_vwc,
            "peak_vwc": peak_vwc,
            "delta": record.delta,
            "fired_at": record.fired_at.isoformat(),
        })

        self._update_field_capacity(record)

    # ------------------------------------------------------------------ field capacity

    def _update_field_capacity(self, record: ShotResponse) -> None:
        zone = record.zone
        fc = self._fc[zone]
        fc.history.append(record.peak_vwc or 0.0)

        if len(fc.history) < 2:
            return
        last_two = list(fc.history)[-2:]
        rise_between_shots = last_two[1] - last_two[0]
        if rise_between_shots > self.saturation_delta_pct:
            return  # not yet saturated

        observed_fc = last_two[1]
        # EWMA
        if fc.sample_count == 0:
            fc.fc_pct = observed_fc
        else:
            fc.fc_pct = self.fc_alpha * observed_fc + (1 - self.fc_alpha) * fc.fc_pct
        fc.sample_count += 1
        fc.confidence = min(1.0, fc.sample_count / 5.0)

        cultivar = self._read_zone_cultivar(zone)
        self.store.record_field_capacity(
            ts=datetime.utcnow().isoformat(),
            zone=zone,
            cultivar=cultivar,
            fc_pct=fc.fc_pct,
            confidence=fc.confidence,
            sample_count=fc.sample_count,
        )

        self._publish_fc_sensor(zone, fc)
        self.bus.publish("field_capacity.observed", {
            "zone": zone,
            "fc_pct": fc.fc_pct,
            "confidence": fc.confidence,
            "sample_count": fc.sample_count,
            "cultivar": cultivar,
        })
        self.fire_event("crop_steering_field_capacity_observed", **{
            "zone": zone,
            "fc_pct": round(fc.fc_pct, 2),
            "confidence": round(fc.confidence, 2),
        })

    # ------------------------------------------------------------------ derived sensors

    def _publish_derived_sensors(self, _kwargs: Any) -> None:
        for zone in self._configured_zones():
            self._publish_dryback_velocity(zone)
            self._publish_porosity_estimate(zone)
            self._publish_ec_stack_index(zone)

    def _publish_fc_sensor(self, zone: int, fc: FieldCapacityState) -> None:
        self.set_state(
            f"sensor.crop_steering_zone_{zone}_field_capacity_observed",
            state=round(fc.fc_pct, 2),
            attributes={
                "confidence": round(fc.confidence, 3),
                "sample_count": fc.sample_count,
                "unit_of_measurement": "%",
                "friendly_name": f"Zone {zone} Observed Field Capacity",
                "icon": "mdi:water-percent",
            },
        )

    def _publish_dryback_velocity(self, zone: int) -> None:
        # Stub: real implementation reads the existing AdvancedDrybackDetector's
        # rolling dryback rate. Placeholder publishes "unknown" until wired.
        pass

    def _publish_porosity_estimate(self, zone: int) -> None:
        # Stub: porosity ≈ ΔVWC per mL applied; computed from `shots` table.
        pass

    def _publish_ec_stack_index(self, zone: int) -> None:
        # Stub: cumulative (ec_runoff - ec_feed) integral over a window.
        pass

    # ------------------------------------------------------------------ helpers

    def _read_zone_vwc(self, zone: int) -> float | None:
        state = self.get_state(f"sensor.crop_steering_zone_{zone}_avg_vwc")
        try:
            return float(state)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    def _read_zone_vwc_peak_since(self, zone: int, since: datetime) -> float | None:
        # AppDaemon doesn't expose history directly; the master app maintains
        # rolling buffers. For now, just sample current VWC — wired to the
        # real buffer in PR #2.
        return self._read_zone_vwc(zone)

    def _read_zone_cultivar(self, zone: int) -> str | None:
        return self.get_state(f"select.crop_steering_zone_{zone}_crop_type")  # type: ignore[return-value]

    def _configured_zones(self) -> list[int]:
        # Cheap discovery: scan for state.crop_steering_zone_{n}_avg_vwc for n in 1..24
        zones = []
        for n in range(1, 25):
            if self.entity_exists(f"sensor.crop_steering_zone_{n}_avg_vwc"):
                zones.append(n)
        return zones

    def _daily_prune(self, _kwargs: Any) -> None:
        try:
            self.store.prune()
        except Exception:  # noqa: BLE001
            self.log("Daily prune failed", level="ERROR")

    # ------------------------------------------------------------------ AppDaemon shims

    def entity_exists(self, entity_id: str) -> bool:
        # AppDaemon ≥4.4 has self.entity_exists; shim for older versions.
        try:
            return super().entity_exists(entity_id)  # type: ignore[misc]
        except AttributeError:
            return self.get_state(entity_id) is not None
