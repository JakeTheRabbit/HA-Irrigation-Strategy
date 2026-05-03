"""Shared base for RootSense intelligence apps.

Provides:
- module-enable switch gating (`_is_module_enabled`)
- common `_read_float` / `_configured_zones` helpers used by every pillar
- a uniform `app_state_dir` resolution so the SQLite store always lives at
  appdaemon/apps/crop_steering/state/rootsense.db regardless of how the
  hosting AppDaemon container mounts paths.

Every pillar app inherits from `IntelligenceApp` instead of `hass.Hass`
directly. Pillars stay independently enableable: if the switch is OFF the
periodic loops short-circuit before doing any work.
"""
from __future__ import annotations

import logging
from pathlib import Path

try:
    import appdaemon.plugins.hass.hassapi as hass  # type: ignore
except ImportError:  # pragma: no cover
    hass = type("hass", (), {"Hass": object})  # type: ignore

_LOGGER = logging.getLogger(__name__)

#: Map app class name → switch entity that gates it.
MODULE_SWITCH = {
    "RootZoneIntelligence":   "switch.crop_steering_intelligence_root_zone_enabled",
    "AdaptiveIrrigation":     "switch.crop_steering_intelligence_adaptive_enabled",
    "AgronomicIntelligence":  "switch.crop_steering_intelligence_agronomic_enabled",
    "IrrigationOrchestrator": "switch.crop_steering_intelligence_orchestrator_enabled",
    "AnomalyScanner":         "switch.crop_steering_intelligence_anomaly_enabled",
}


class IntelligenceApp(hass.Hass):  # type: ignore[misc]
    """Mixin-style base for the five intelligence pillars.

    Subclasses should still define their own ``initialize()`` — they call
    ``super().initialize()`` (or just ignore this base if they need full
    control). The helper methods below are available on every subclass.
    """

    # ------------------------------------------------------------------ gating

    def _is_module_enabled(self) -> bool:
        """Return True if this pillar's enable switch is on (or missing)."""
        switch = MODULE_SWITCH.get(type(self).__name__)
        if switch is None:
            return True  # unknown class — fail-open during development
        try:
            state = self.get_state(switch)
        except Exception:  # noqa: BLE001
            return True
        if state is None:
            # entity hasn't been created yet (fresh install before integration
            # reload) — default to ENABLED so the operator's first reload
            # doesn't silently skip everything. Subsequent runs find the
            # switch and respect its actual state.
            return True
        return str(state).lower() == "on"

    # ------------------------------------------------------------------ paths

    def _state_dir(self) -> Path:
        """Resolve the rootsense.db directory under appdaemon/apps/.../state/."""
        base = Path(self.app_dir) / "crop_steering" / "state"
        base.mkdir(parents=True, exist_ok=True)
        return base

    # ------------------------------------------------------------------ reads

    def _read_float(self, entity_id: str, default: float | None = None) -> float | None:
        try:
            return float(self.get_state(entity_id))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default

    def _read_int(self, entity_id: str, default: int | None = None) -> int | None:
        try:
            return int(float(self.get_state(entity_id)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default

    def _configured_zones(self) -> list[int]:
        """Return zone IDs that have a `..._avg_vwc` sensor in HA."""
        zones: list[int] = []
        for n in range(1, 25):
            if self.entity_exists(f"sensor.crop_steering_zone_{n}_avg_vwc"):
                zones.append(n)
        return zones

    # ------------------------------------------------------------------ shims

    def entity_exists(self, entity_id: str) -> bool:
        try:
            return super().entity_exists(entity_id)  # type: ignore[misc]
        except AttributeError:
            return self.get_state(entity_id) is not None
