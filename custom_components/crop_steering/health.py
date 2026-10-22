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

from .const import DOMAIN, REPAIRS_DOCS_URL
from .room import resolve_gate, room_prefix

_LOGGER = logging.getLogger(__name__)

_STALE_MIN = 10
_DEAD = ("unavailable", "unknown", "none", "")
ISSUE_IDS = (
    "kill_switch_missing",
    "engine_switch_not_gate",
    "engine_offline",
    "zone_no_sensor",
    "fused_sensor_unavailable",
    "strategy_hold",
    "strategy_degraded",
    "entities_moved",
    "max_run_latch",
    # Raised and cleared by stock_api.py, not by the checks here; listed so every card this
    # integration can show is in one place.
    "stock_low",
    # Raised and cleared by bounds.py, when the room sets up and when a setting changes.
    "outside_zone_bounds",
    # Raised and cleared by calibration.py, hourly and when a feed probe is calibrated.
    "calibration_due",
    # Raised and cleared by calibration.py, when it loads and hourly.
    "probe_offsets_unreadable",
    # Raised and cleared by deprecation.py, once Home Assistant has started.
    "deprecated_entities",
)
# The platforms whose entities the controller reads by exact id and has no other way to find.
# Fused sensors are left out: the controller tolerates their legacy naming and an add-on option
# can map them. The descriptor is found by scanning; the heartbeat is the controller's own.
_READ_BY_ID = ("number", "switch", "select")
_MOVED_SHOWN = 6


def _iid(base: str, slug: str) -> str:
    """Per-room issue id so rooms don't clobber each other's Repairs cards."""
    return base if slug in ("", "default") else f"{base}_{slug}"


def clear_all(hass: HomeAssistant, slug: str = "default") -> None:
    """Remove a room's crop-steering Repairs issues (on unload)."""
    for base in ISSUE_IDS:
        ir.async_delete_issue(hass, DOMAIN, _iid(base, slug))


def _issue(hass, present, issue_id, severity, placeholders=None, fix=None):
    """Create the issue when `present` is True, otherwise clear it. `fix`: the data its
    fix flow gets (repairs.py); without it the card has no Fix button."""
    if present:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            data=fix,
            is_fixable=fix is not None,
            severity=severity,
            translation_key=_base_key(issue_id),
            translation_placeholders=placeholders or {},
            learn_more_url=REPAIRS_DOCS_URL,
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, issue_id)


def _base_key(issue_id: str) -> str:
    """Map a per-room issue id back to its base translation key."""
    for base in ISSUE_IDS:
        if issue_id == base or issue_id.startswith(base + "_"):
            return base
    return issue_id


def _strategy_hold(plan, heartbeat):
    """Why the room's grow-strategy plan is holding the steering of its zones -> (reason,
    severity), or (None, None). The controller then waters those zones only with emergency,
    watchdog and minimum-daily shots. `heartbeat` is None when the controller is offline (that
    has its own issue)."""
    attrs = (getattr(plan, "attributes", {}) or {}) if plan is not None else {}
    if plan is not None and plan.state == "error":
        return attrs.get("error") or "the plan is in error", ir.IssueSeverity.ERROR
    beat = (getattr(heartbeat, "attributes", {}) or {}) if heartbeat is not None else {}
    if beat.get("strategy_error"):
        return beat["strategy_error"], ir.IssueSeverity.ERROR
    if plan is not None and plan.state in ("active", "disarming"):
        waiting = [
            f"zone {row.get('zone_id')} ({row.get('status')})"
            for row in attrs.get("zones") or []
            if isinstance(row, dict) and row.get("status") != "active"
        ]
        if waiting:
            return (
                "not scheduled today: " + ", ".join(waiting),
                ir.IssueSeverity.WARNING,
            )
    return None, None


def moved_entities(hass: HomeAssistant, entry: ConfigEntry) -> list[tuple[str, str]]:
    """This room's entities that are not where the controller reads them -> [(now, expected)].

    The controller, the dashboard and the MCP tools find a setting by its exact entity id
    (`number.crop_steering_<room>zone_1_plant_count`). Home Assistant keeps whatever id an entity
    was first registered under, so a room created by stale code, an id edited in Settings, or a
    collision that left `..._2` behind, leaves the setting somewhere nothing looks: the controller
    runs on its built-in default and says only "setpoint entities missing".

    Reported only when the expected id holds NOTHING (no state, no registry entry). An install
    that works has its entities at these ids already, so this stays quiet there; and nothing is
    renamed for the operator, because an id they chose on purpose is theirs to keep.
    """
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    prefix = room_prefix(entry)
    head = f"{DOMAIN}_{entry.entry_id}_"
    moved = []
    for item in er.async_entries_for_config_entry(registry, entry.entry_id):
        if item.domain not in _READ_BY_ID or not str(item.unique_id).startswith(head):
            continue
        expected = f"{item.domain}.{DOMAIN}_{prefix}{item.unique_id[len(head):]}"
        if (
            item.entity_id != expected
            and registry.async_get(expected) is None
            and hass.states.get(expected) is None
        ):
            moved.append((item.entity_id, expected))
    return sorted(moved)


def _check_moved(hass: HomeAssistant, entry: ConfigEntry, slug: str) -> None:
    try:
        moved = moved_entities(hass, entry)
    except (
        Exception
    ) as e:  # a registry this cannot read is no reason to skip the other checks
        _LOGGER.debug("moved-entity check skipped: %s", e)
        return
    shown = "\n".join(
        f"- `{now}` should be `{expected}`" for now, expected in moved[:_MOVED_SHOWN]
    )
    more = len(moved) - _MOVED_SHOWN
    _issue(
        hass,
        bool(moved),
        _iid("entities_moved", slug),
        ir.IssueSeverity.WARNING,
        {
            "count": str(len(moved)),
            "entities": shown + (f"\n- and {more} more" if more > 0 else ""),
        },
    )


def _check_max_run(hass, entry, prefix, slug, heartbeat):
    """CS-312: zones whose last shots all ran into the room's longest allowed shot, as the
    controller reports them on its heartbeat. A zone it latched (the room's max-run latch switch
    is ON) is stopped until this card is fixed; otherwise the card only reports. A latched zone
    whose reset the controller has not seen yet is left off the card."""
    beat = (getattr(heartbeat, "attributes", {}) or {}) if heartbeat is not None else {}
    zones = beat.get("max_run") if isinstance(beat.get("max_run"), dict) else {}
    switch = hass.states.get(f"switch.{DOMAIN}_{prefix}max_run_latch")
    resets = (getattr(switch, "attributes", {}) or {}).get("resets", 0)
    latched, capped = [], []
    for zone, row in sorted(zones.items()):
        if not isinstance(row, dict):
            continue
        if row.get("latched"):
            if row.get("resets") == resets:
                latched.append(str(zone))
        else:
            capped.append(str(zone))
    if latched:
        what = (
            "The controller has stopped watering zone(s) "
            + ", ".join(latched)
            + " until this card is fixed: open it and confirm."
        )
    else:
        what = (
            "Nothing has been stopped: the room's max-run latch switch is off, so the zones "
            "keep watering."
        )
    _issue(
        hass,
        bool(latched or capped),
        _iid("max_run_latch", slug),
        ir.IssueSeverity.ERROR if latched else ir.IssueSeverity.WARNING,
        {"zones": ", ".join(latched or capped), "what": what},
        fix={"entry_id": entry.entry_id} if latched else None,
    )


def run_health_check(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Evaluate one room's setup health and create/clear its Repairs issues."""
    try:
        prefix = room_prefix(entry)
        slug = entry.data.get("room_slug", "default")
        zones = entry.data.get("zones", {}) or {}
        # Before the room-off stand-down: this is a fault of the setup, not of a room that is
        # resting, and it is best found before the room is switched on.
        _check_moved(hass, entry, slug)

        # Room switched OFF (nothing growing): unplugged probes and an idle engine are expected,
        # so clear this room's issues and stand down. A missing switch (older install) means ON.
        room = hass.states.get(f"switch.{DOMAIN}_{prefix}room_active")
        if room is not None and str(room.state).lower() == "off":
            for base in ISSUE_IDS:
                # Stock runs low whether or not anything grows, and only its own store
                # raises that card again; the same goes for a setting held above its limit,
                # a feed probe due for calibration and a retired entity still in use.
                if base not in (
                    "entities_moved",
                    "stock_low",
                    "outside_zone_bounds",
                    "calibration_due",
                    "probe_offsets_unreadable",
                    "deprecated_entities",
                ):
                    _issue(hass, False, _iid(base, slug), ir.IssueSeverity.WARNING)
            return

        # Kill switch + engine heartbeat are per-room: the engine drives EVERY configured
        # room, each with its own kill switch and prefixed heartbeat. Resolve them per room
        # so a custom default kill switch and additional rooms are all monitored.
        kill, reported = resolve_gate(hass, prefix)
        _issue(
            hass,
            hass.states.get(kill) is None,
            _iid("kill_switch_missing", slug),
            ir.IssueSeverity.ERROR,
            {
                "kill_switch": kill,
                "source": (
                    "the one its controller reports"
                    if reported
                    else "as the room's setup publishes it: the controller has not reported its own yet"
                ),
            },
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

        # An operator who turns Engine Enabled OFF expects water to stop. Only the running
        # controller knows its gate, so only a current heartbeat can say that switch is not it.
        own = f"switch.{DOMAIN}_{prefix}engine_enabled"
        _issue(
            hass,
            reported
            and not offline
            and kill != own
            and hass.states.get(own) is not None,
            _iid("engine_switch_not_gate", slug),
            ir.IssueSeverity.WARNING,
            {"kill_switch": kill, "engine_switch": own},
        )

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

        _check_max_run(hass, entry, prefix, slug, None if offline else hb)

        # Every hold of the room's grow-strategy plan, and a plan running on its last snapshot.
        plan = hass.states.get(f"sensor.{DOMAIN}_{prefix}strategy_plan")
        reason, severity = _strategy_hold(plan, None if offline else hb)
        _issue(
            hass,
            bool(reason),
            _iid("strategy_hold", slug),
            severity or ir.IssueSeverity.WARNING,
            {"reason": str(reason or "")},
        )
        degraded = (getattr(plan, "attributes", {}) or {}).get("degraded_reason")
        _issue(
            hass,
            bool(degraded),
            _iid("strategy_degraded", slug),
            ir.IssueSeverity.WARNING,
            {"reason": str(degraded or "")},
        )
    except Exception as e:  # pragma: no cover - never let a health check break setup
        _LOGGER.debug("health check skipped: %s", e)
