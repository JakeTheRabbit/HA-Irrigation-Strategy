"""Setup health checks, surfaced as Home Assistant Repairs.

Runs shortly after setup and every few minutes. Each problem becomes an actionable card in
Settings -> Repairs with a plain-language description; it clears itself when fixed. Read-only
(never changes config or hardware)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

KILL_SWITCH = "input_boolean.f2_control_enabled"
HEARTBEAT = "sensor.crop_steering_ai_heartbeat"
DOCS = "https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/wiki/Troubleshooting"
_STALE_MIN = 10
_DEAD = ("unavailable", "unknown", "none", "")
ISSUE_IDS = (
    "kill_switch_missing",
    "engine_offline",
    "zone_no_sensor",
    "fused_sensor_unavailable",
)


def clear_all(hass: HomeAssistant) -> None:
    """Remove all crop-steering Repairs issues (on unload)."""
    for issue_id in ISSUE_IDS:
        ir.async_delete_issue(hass, DOMAIN, issue_id)


def _issue(hass, present, issue_id, severity, placeholders=None):
    """Create the issue when `present` is True, otherwise clear it."""
    if present:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=severity,
            translation_key=issue_id,
            translation_placeholders=placeholders or {},
            learn_more_url=DOCS,
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, issue_id)


def run_health_check(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Evaluate setup health and create/clear Repairs issues."""
    try:
        zones = entry.data.get("zones", {}) or {}

        # 1. Kill switch helper missing -> the engine add-on can't run.
        _issue(
            hass,
            hass.states.get(KILL_SWITCH) is None,
            "kill_switch_missing",
            ir.IssueSeverity.ERROR,
        )

        # 2. Engine heartbeat missing or stale -> the f2-control add-on isn't running.
        hb = hass.states.get(HEARTBEAT)
        offline = hb is None
        if hb is not None:
            try:
                age_min = (
                    datetime.now(timezone.utc) - hb.last_updated
                ).total_seconds() / 60.0
                offline = age_min > _STALE_MIN or str(hb.state).lower() in _DEAD
            except Exception:  # pragma: no cover - defensive
                offline = False
        _issue(hass, offline, "engine_offline", ir.IssueSeverity.WARNING)

        # 3. A zone with no VWC sensor mapped -> it can't be steered.
        no_sensor = []
        for zid, zc in zones.items():
            vwc = zc.get("vwc_sensors") or [
                s for s in (zc.get("vwc_front"), zc.get("vwc_back")) if s
            ]
            if not vwc:
                no_sensor.append(str(zid))
        _issue(
            hass,
            bool(no_sensor),
            "zone_no_sensor",
            ir.IssueSeverity.WARNING,
            {"zones": ", ".join(no_sensor)},
        )

        # 4. A fused per-zone sensor reads unavailable -> probe(s) offline.
        dead = []
        for zid in zones:
            st = hass.states.get(f"sensor.crop_steering_vwc_zone_{zid}")
            if st is not None and str(st.state).lower() in _DEAD:
                dead.append(str(zid))
        _issue(
            hass,
            bool(dead),
            "fused_sensor_unavailable",
            ir.IssueSeverity.WARNING,
            {"zones": ", ".join(dead)},
        )
    except Exception as e:  # pragma: no cover - never let a health check break setup
        _LOGGER.debug("health check skipped: %s", e)
