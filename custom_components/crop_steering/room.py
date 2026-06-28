"""Multi-room helpers.

Each config entry is a *room*. The first/default room uses **no** entity prefix, so existing
single-room installs (e.g. F2) are completely unchanged. Additional rooms namespace their
entities as ``crop_steering_<slug>_*`` so rooms are fully isolated — own zones, sensors,
hardware and setpoints, nothing shared.
"""
from __future__ import annotations

import re


def slugify_room(name: str) -> str:
    """A safe entity-id-friendly slug for a room name."""
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return s or "room"


def room_prefix(entry) -> str:
    """The entity-id prefix for this room's config entry.

    Returns ``""`` for the default room (legacy, un-prefixed) or ``"<slug>_"`` for an
    additional room. Used as ``f"{DOMAIN}_{room_prefix(entry)}{key}"``.
    """
    try:
        return entry.data.get("room_prefix", "") or ""
    except Exception:  # pragma: no cover - defensive
        return ""


def build_engine_config(prefix, slug, num_zones, zones, hardware):
    """PURE. The room descriptor the f2-control add-on reads from
    ``sensor.crop_steering_<prefix>engine_config`` to DISCOVER and drive an additional room
    (the add-on can't read the config entry directly). Maps each zone's valve switch, the
    shared pump/mainline, the per-room kill switch, and the optional source-water probes.

    The default room (prefix "") publishes ``input_boolean.f2_control_enabled`` as its
    kill switch and is ignored by the add-on (it's built from the add-on options instead);
    a named room publishes its own ``switch.crop_steering_<slug>_engine_enabled``.
    """
    zones = zones or {}
    valves = {}
    for z in range(1, int(num_zones) + 1):
        cfg = zones.get(str(z)) or zones.get(z) or {}
        sw = cfg.get("zone_switch", "")
        if sw:
            valves[z] = sw
    enable_flag = (
        "input_boolean.f2_control_enabled"
        if prefix == ""
        else f"switch.crop_steering_{prefix}engine_enabled"
    )
    hw = hardware or {}
    return {
        "slug": slug,
        "prefix": prefix,
        "num_zones": int(num_zones),
        "pump": hw.get("pump_switch", ""),
        "mainline": hw.get("main_line_switch", ""),
        "valves": valves,
        "enable_flag": enable_flag,
        "feed_ec_sensor": hw.get("feed_ec_sensor", ""),
        "feed_ph_sensor": hw.get("feed_ph_sensor", ""),
    }
