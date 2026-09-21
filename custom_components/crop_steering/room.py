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


def zone_device_name(entry, zone_num) -> str:
    """The Home Assistant device name for a zone: what the operator called it in setup.

    Three platforms used to name this device themselves, and differently ("Zone 1" in one,
    "Crop Steering Zone 1" in two others), so the name Home Assistant showed depended on which
    platform registered it last, and was never the name that had been typed. Seen on a first
    install: the zone was set up as "GT1" and Home Assistant offered a device called "Zone 1".
    Entity ids and entity names are not derived from this, so nothing else moves.
    """
    try:
        data = {**(entry.data or {}), **(getattr(entry, "options", None) or {})}
    except Exception:  # pragma: no cover - defensive, as room_prefix above
        data = {}
    zones = data.get("zones") or {}
    zone = zones.get(str(zone_num)) or zones.get(zone_num) or {}
    name = zone.get("name") if isinstance(zone, dict) else None
    return (
        name.strip() if isinstance(name, str) and name.strip() else f"Zone {zone_num}"
    )


def build_engine_config(
    prefix, slug, num_zones, zones, hardware, setup=None, integration_version=None
):
    """PURE. The room descriptor the f2-control add-on reads from
    ``sensor.crop_steering_<prefix>engine_config`` to DISCOVER and drive an additional room
    (the add-on can't read the config entry directly). Maps each zone's valve switch, the
    shared pump/mainline, the per-room kill switch, and the optional source-water probes.

    The default room (prefix "") publishes ``input_boolean.f2_control_enabled`` as its
    kill switch (the add-on's ``enable_flag`` option overrides it; the engine's heartbeat
    reports the flag actually in use). Since add-on 0.11.0 the default room's hardware map
    is read from this descriptor too — explicit add-on options take precedence. A named
    room publishes its own ``switch.crop_steering_<slug>_engine_enabled``.
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
    setup = setup or {}
    # Only when DECLARED. A room that never declared its plumbing publishes byte-for-byte the
    # descriptor it always did, so the controller's saved setup fingerprint still matches and an
    # update does not strand the room behind a disarm cycle.
    declared = {"plumbing": setup["plumbing"]} if setup.get("plumbing") else {}
    # Which integration Home Assistant actually loaded, for the dashboard's sidebar and for pairing
    # diagnostics. Passed in (this module stays import-free so it can be loaded on its own). The
    # controller's setup fingerprint reads named keys only, so this does not disturb a
    # restart-resume (addons/f2_control/tests/test_versions.py pins that).
    versions = (
        {"integration_version": integration_version} if integration_version else {}
    )
    return {
        **declared,
        **versions,
        "setup_api_version": 1,
        "setup_revision": setup.get("setup_revision", 0),
        "active": setup.get("active", True),
        "room_name": setup.get("room_name", setup.get("name", slug)),
        "active_zone_ids": [
            z
            for z in range(1, int(num_zones) + 1)
            if (zones.get(str(z)) or zones.get(z) or {}).get("active", True)
        ],
        "zone_names": {
            str(z): (zones.get(str(z)) or zones.get(z) or {}).get("name", f"Zone {z}")
            for z in range(1, int(num_zones) + 1)
        },
        "slug": slug,
        "prefix": prefix,
        "num_zones": int(num_zones),
        "pump": hw.get("pump_switch", ""),
        "mainline": hw.get("main_line_switch", ""),
        "valves": valves,
        "enable_flag": setup.get("enable_flag") or enable_flag,
        "feed_ec_sensor": hw.get("feed_ec_sensor", ""),
        "feed_ph_sensor": hw.get("feed_ph_sensor", ""),
        # Read-only overview mappings. No ambient-temperature or feed-probe fallback.
        "water_level_sensor": hw.get("water_level_sensor", ""),
        "tank_temperature_sensor": hw.get("tank_temperature_sensor", ""),
        "tank_ec_sensor": hw.get("tank_ec_sensor", ""),
        "tank_ph_sensor": hw.get("tank_ph_sensor", ""),
        "tank_last_fill_sensor": hw.get("tank_last_fill_sensor", ""),
        "tank_fill_entity": hw.get("tank_fill_entity", ""),
    }
