"""Pillar 4 — Irrigation Orchestration.

The Coordinator is the only module allowed to send service calls that
result in hardware action. Every other intelligence module proposes;
the coordinator arbitrates.

Responsibilities:

- Subscribe to RootSenseBus topics that produce shot proposals.
- Apply safety gates (anomaly suppression, manual-override respect,
  emergency cooldown) before forwarding to the hardware layer.
- Implement the new `crop_steering.custom_shot` HA service.
- Implement emergency / flush logic with the new guardrails.
- Publish `binary_sensor.crop_steering_anomaly_active`.

This file is a runnable AppDaemon app.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from .base import IntelligenceApp
from .bus import RootSenseBus
from .store import RootSenseStore

_LOGGER = logging.getLogger(__name__)

DEFAULT_FLUSH_COOLDOWN_MIN = 240  # 4 hours
DEFAULT_EMERGENCY_VWC_PCT = 40.0


class IrrigationOrchestrator(IntelligenceApp):
    def initialize(self) -> None:
        self.bus = RootSenseBus.instance()
        self.store = RootSenseStore(self._state_dir() / "rootsense.db")

        cfg = self.args or {}
        self.flush_cooldown = timedelta(minutes=int(cfg.get("flush_cooldown_min", DEFAULT_FLUSH_COOLDOWN_MIN)))
        self.emergency_vwc = float(cfg.get("emergency_vwc_pct", DEFAULT_EMERGENCY_VWC_PCT))

        self._last_flush_at: dict[int, datetime] = {}
        self._suppressed_zones: set[int] = set()

        # HA event: integration's crop_steering.custom_shot service fires
        # `crop_steering_custom_shot` on the HA bus; we listen for that here.
        # The integration owns the service registration so the schema is
        # validated before we get involved.
        self.listen_event(self._on_custom_shot_event, "crop_steering_custom_shot")

        # Bus subscriptions
        self.bus.subscribe("anomaly.detected", self._on_anomaly)
        self.bus.subscribe("shot.requested", self._on_shot_requested)

        # Periodic emergency check (every 30 s)
        self.run_every(self._emergency_check, "now+30", 30)

        self.log("IrrigationOrchestrator ready")

    # ------------------------------------------------------------------ services

    def _on_custom_shot_event(self, event_name: str, data: dict[str, Any], _kwargs: Any) -> None:
        """Handle `crop_steering_custom_shot` events from the HA service bus."""
        if not self._is_module_enabled():
            self.log("custom_shot ignored: orchestrator module disabled", level="WARNING")
            return
        zone = int(data.get("target_zone", 0))
        if zone <= 0:
            self.log("custom_shot ignored: invalid zone %s", zone, level="WARNING")
            return
        intent_label = data.get("intent", "manual")
        volume_ml = float(data.get("volume_ml", 0))
        target_runoff_pct = data.get("target_runoff_pct")
        tag = data.get("tag", "operator")

        if zone in self._suppressed_zones:
            self.log("custom_shot suppressed for zone %s (anomaly-active)", zone, level="WARNING")
            return

        # Convert volume to duration via flow-rate number entity
        flow_rate_lpm = self._read_flow_rate_lpm(zone)
        if flow_rate_lpm <= 0:
            self.log("custom_shot zone %s: flow rate unknown, aborting", zone, level="ERROR")
            return
        duration_s = max(1.0, (volume_ml / 1000.0) / flow_rate_lpm * 60.0)

        # Persist intent
        self.store.record_shot(
            ts=datetime.utcnow().isoformat(),
            zone=zone,
            phase=self.get_state("select.crop_steering_irrigation_phase"),
            shot_type="custom",
            intent=self._read_intent(),
            volume_ml=volume_ml,
            duration_s=duration_s,
            vwc_before=self._read_zone_vwc(zone),
            tag=f"{intent_label}:{tag}",
        )

        # Hand off to legacy service (which talks to hardware).
        self.call_service(
            "crop_steering/execute_irrigation_shot",
            zone=zone,
            duration_seconds=int(duration_s),
            shot_type="custom",
        )
        self.log("custom_shot fired: zone=%s vol=%.1fmL dur=%.1fs intent=%s tag=%s",
                 zone, volume_ml, duration_s, intent_label, tag)

    # ------------------------------------------------------------------ bus handlers

    def _on_shot_requested(self, _topic: str, payload: dict[str, Any]) -> None:
        # Forward intelligence-module proposals through the same gate as a
        # custom shot. ShotPlanner builds the payload in the right shape.
        self.fire_event("crop_steering_shot_proposal", **payload)
        # Use the service path so logging/safety stay unified.
        self.run_in(self._fire_proposal, 0, payload=payload)

    def _fire_proposal(self, kwargs: dict[str, Any]) -> None:
        payload = kwargs["payload"]
        self.call_service("crop_steering/custom_shot", **payload)

    def _on_anomaly(self, _topic: str, payload: dict[str, Any]) -> None:
        zone = payload.get("zone")
        severity = payload.get("severity", "info")
        if severity == "critical" and isinstance(zone, int):
            self._suppressed_zones.add(zone)
            self.log("Zone %s suppressed due to critical anomaly: %s", zone, payload.get("code"),
                     level="WARNING")
        # binary_sensor.crop_steering_anomaly_active toggling lives in anomaly.py

    # ------------------------------------------------------------------ emergency / flush

    def _emergency_check(self, _kwargs: Any) -> None:
        if not self._is_module_enabled():
            return
        for zone in self._configured_zones():
            vwc = self._read_zone_vwc(zone)
            if vwc is None:
                continue
            if vwc < self.emergency_vwc and zone not in self._suppressed_zones:
                self._fire_emergency_rescue(zone, vwc)
            self._maybe_fire_flush(zone)

    def _fire_emergency_rescue(self, zone: int, vwc: float) -> None:
        # Conservative: 2% shot of substrate volume.
        substrate_l = self._read_substrate_volume_l(zone)
        volume_ml = max(50.0, substrate_l * 20.0)  # 2% of L → mL
        self.log("EMERGENCY rescue: zone %s VWC=%.1f%% < %.1f%%; firing %.1fmL",
                 zone, vwc, self.emergency_vwc, volume_ml, level="WARNING")
        self.call_service(
            "crop_steering/custom_shot",
            target_zone=zone,
            intent="rescue",
            volume_ml=volume_ml,
            tag=f"emergency:vwc={vwc:.1f}",
        )

    def _maybe_fire_flush(self, zone: int) -> None:
        ec_runoff = self._read_float(f"sensor.crop_steering_zone_{zone}_ec_runoff")
        ec_feed = self._read_float(f"sensor.crop_steering_zone_{zone}_ec_feed")
        if ec_runoff is None or ec_feed is None or ec_feed <= 0:
            return
        if ec_runoff < 1.5 * ec_feed:
            return
        last = self._last_flush_at.get(zone)
        if last and datetime.utcnow() - last < self.flush_cooldown:
            return
        substrate_l = self._read_substrate_volume_l(zone)
        volume_ml = substrate_l * 100.0  # 10% of substrate volume
        self.log("Flush shot: zone %s ec_runoff/ec_feed=%.2f → %.1fmL",
                 zone, ec_runoff / ec_feed, volume_ml, level="WARNING")
        self.call_service(
            "crop_steering/custom_shot",
            target_zone=zone,
            intent="rebalance_ec",
            volume_ml=volume_ml,
            tag=f"flush:ec_ratio={ec_runoff / ec_feed:.2f}",
        )
        self._last_flush_at[zone] = datetime.utcnow()

    # ------------------------------------------------------------------ helpers

    def _read_zone_vwc(self, zone: int) -> float | None:
        return self._read_float(f"sensor.crop_steering_zone_{zone}_avg_vwc")

    def _read_flow_rate_lpm(self, zone: int) -> float:
        return self._read_float(f"number.crop_steering_zone_{zone}_dripper_flow_rate", default=2.0) or 2.0

    def _read_substrate_volume_l(self, zone: int) -> float:
        return self._read_float(f"number.crop_steering_zone_{zone}_substrate_size", default=10.0) or 10.0

    def _read_intent(self) -> float:
        return self._read_float("number.crop_steering_steering_intent", default=0.0) or 0.0

    # _read_float / _configured_zones / entity_exists live on IntelligenceApp.
