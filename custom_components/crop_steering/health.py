"""Setup health checks, surfaced as Home Assistant Repairs.

Runs shortly after setup and every few minutes, per room (config entry). Each problem becomes
an actionable card in Settings -> Repairs with a plain-language description; it clears itself
when fixed. Read-only (never changes config or hardware)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .room import room_prefix

_LOGGER = logging.getLogger(__name__)

_DEFAULT_KILL_SWITCH = "input_boolean.f2_control_enabled"
DOCS = "https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/wiki/Troubleshooting"
_STALE_MIN = 10
_DEAD = ("unavailable", "unknown", "none", "")
ISSUE_IDS = (
    "kill_switch_missing",
    "engine_offline",
    "zone_no_sensor",
    "fused_sensor_unavailable",
)


def _iid(base: str, slug: str) -> str:
    """Per-room issue id so rooms don't clobber each other's Repairs cards."""
    return base if slug in ("", "default") else f"{base}_{slug}"


def clear_all(hass: HomeAssistant, slug: str = "default") -> None:
    """Remove a room's crop-steering Repairs issues (on unload)."""
    for base in ISSUE_IDS:
        ir.async_delete_issue(hass, DOMAIN, _iid(base, slug))


def _issue(hass, present, issue_id, severity, placeholders=None):
    """Create the issue when `present` is True, otherwise clear it."""
    if present:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=severity,
            translation_key=_base_key(issue_id),
            translation_placeholders=placeholders or {},
            learn_more_url=DOCS,
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, issue_id)


def _base_key(issue_id: str) -> str:
    """Map a per-room issue id back to its base translation key."""
    for base in ISSUE_IDS:
        if issue_id == base or issue_id.startswith(base + "_"):
            return base
    return issue_id


def _kill_switch(hass: HomeAssistant, prefix: str) -> str:
    """Resolve the kill-switch entity id this room's engine actually uses.

    A named room uses its own ``switch.crop_steering_<slug>_engine_enabled``. The default
    room uses whatever the add-on is configured with — published on the engine_config
    descriptor's ``enable_flag`` attribute — falling back to the documented default so a
    stock install still reports correctly.
    """
    if prefix:
        return f"switch.{DOMAIN}_{prefix}engine_enabled"
    desc = hass.states.get(f"sensor.{DOMAIN}_engine_config")
    if desc is not None:
        ef = (getattr(desc, "attributes", {}) or {}).get("enable_flag")
        if ef:
            return ef
    return _DEFAULT_KILL_SWITCH


def run_health_check(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Evaluate one room's setup health and create/clear its Repairs issues."""
    try:
        prefix = room_prefix(entry)
        slug = entry.data.get("room_slug", "default")
        zones = entry.data.get("zones", {}) or {}

        # Kill switch + engine heartbeat are per-room: the engine drives EVERY configured
        # room, each with its own kill switch and prefixed heartbeat. Resolve them per room
        # so a custom default kill switch and additional rooms are all monitored.
        kill = _kill_switch(hass, prefix)
        _issue(
            hass,
            hass.states.get(kill) is None,
            _iid("kill_switch_missing", slug),
            ir.IssueSeverity.ERROR,
        )
        hb = hass.states.get(f"sensor.{DOMAIN}_{prefix}ai_heartbeat")
        offline = hb is None
        if hb is not None:
            try:
                age_min = (
                    datetime.now(timezone.utc) - hb.last_updated
                ).total_seconds() / 60.0
                offline = age_min > _STALE_MIN or str(hb.state).lower() in _DEAD
            except Exception:  # pragma: no cover - defensive
                offline = False
        _issue(hass, offline, _iid("engine_offline", slug), ir.IssueSeverity.WARNING)

        # A zone with no VWC sensor mapped -> it can't be steered.
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
            _iid("zone_no_sensor", slug),
            ir.IssueSeverity.WARNING,
            {"zones": ", ".join(no_sensor)},
        )

        # A fused per-zone sensor (this room's namespace) reads unavailable.
        dead = []
        for zid in zones:
            st = hass.states.get(f"sensor.crop_steering_{prefix}vwc_zone_{zid}")
            if st is not None and str(st.state).lower() in _DEAD:
                dead.append(str(zid))
        _issue(
            hass,
            bool(dead),
            _iid("fused_sensor_unavailable", slug),
            ir.IssueSeverity.WARNING,
            {"zones": ", ".join(dead)},
        )
    except Exception as e:  # pragma: no cover - never let a health check break setup
        _LOGGER.debug("health check skipped: %s", e)
