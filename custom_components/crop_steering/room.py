"""Multi-room helpers.

Each config entry is a *room*. Every room namespaces its entities as
``crop_steering_<slug>_*`` so rooms are fully isolated — own zones, sensors, hardware and
setpoints, nothing shared. Only a room created before every new room got a slug, or imported
from a .env file (the default room), keeps **no** entity prefix, so those installs are
completely unchanged.
"""

from __future__ import annotations

import re

from .const import DOMAIN, LEGACY_KILL_SWITCH


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


def default_gate(prefix: str) -> str:
    """The kill switch a room of this kind has when nothing names another: a named room its own
    Engine Enabled switch, the default room the legacy helper."""
    return f"switch.{DOMAIN}_{prefix}engine_enabled" if prefix else LEGACY_KILL_SWITCH


def resolve_gate(hass, prefix: str, setup=None) -> tuple[str, bool]:
    """The kill switch this room's controller stops on -> (entity id, reported by the controller).

    The one rule the integration uses (health checks, setup, the setup API). Best source: the
    running controller, which names its gate on the room's heartbeat; that covers a custom add-on
    ``enable_flag`` option. Then the room's published setup (its engine_config descriptor), then
    the room kind's default.

    Except while the controller is BEHIND: its heartbeat reports an older ``setup_revision`` than
    the room publishes. It then holds every zone until it adopts the new setup, and adopting moves
    it to the descriptor's flag, so the flag it names is the one being left behind. That is every
    first install where the controller app was started before the integration was set up: the
    app's shipped option names the legacy helper, which a fresh install never creates.

    ``setup`` is a setup the caller holds rather than the one Home Assistant publishes (the setup
    API judging a save): its flag stands in for the descriptor's, and it has no published revision
    for the heartbeat to be behind.
    """
    hb = hass.states.get(f"sensor.{DOMAIN}_{prefix}ai_heartbeat")
    beat = (getattr(hb, "attributes", {}) or {}) if hb is not None else {}
    if setup is None:
        desc = hass.states.get(f"sensor.{DOMAIN}_{prefix}engine_config")
        published = (getattr(desc, "attributes", {}) or {}) if desc is not None else {}
    else:
        published = {"enable_flag": setup.get("enable_flag")}
    have, want = beat.get("setup_revision"), published.get("setup_revision")
    behind = type(have) is int and type(want) is int and want > have
    if beat.get("enable_flag") and not (behind and published.get("enable_flag")):
        return beat["enable_flag"], True
    return published.get("enable_flag") or default_gate(prefix), False


def room_gate(hass, prefix: str, setup=None) -> str:
    """The kill switch this room's controller stops on (see resolve_gate)."""
    return resolve_gate(hass, prefix, setup)[0]


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


def restored_state_is_ours(entry, last_state) -> bool:
    """PURE. Whether a state Home Assistant offers to restore belongs to THIS room.

    Home Assistant keeps the last state of a removed entity for seven days, keyed by entity id,
    and this integration pins its entity ids. So a room that is deleted and set up again was
    handed the deleted room's states: its setpoints over the answers just typed into the
    wizard, its room on/off switch, and its kill switch. A room deleted while armed came back
    armed.

    A state written before this config entry existed cannot be this room's. Anything else is
    restored exactly as before: an entry from before Home Assistant recorded `created_at`
    carries the epoch, so everything is newer than it, and where either time is missing or
    cannot be compared the answer is yes.
    """
    created = getattr(entry, "created_at", None)
    written = getattr(last_state, "last_updated", None)
    if created is None or written is None:
        return True
    try:
        return written >= created
    except TypeError:  # one of them is naive: no basis for throwing a room's state away
        return True


# The room climate sensors a setup can map (config_flow, hardware step).
CLIMATE_SENSORS = ("temperature_sensor", "humidity_sensor", "vpd_sensor")


def build_engine_config(
    prefix,
    slug,
    num_zones,
    zones,
    hardware,
    setup=None,
    integration_version=None,
    entry_id=None,
    substrate=None,
):
    """PURE. The room descriptor the f2-control add-on reads from
    ``sensor.crop_steering_<prefix>engine_config`` to DISCOVER and drive an additional room
    (the add-on can't read the config entry directly). Maps each zone's valve switch, the
    shared pump/mainline, the per-room kill switch, and the optional source-water probes.

    The default room (prefix "") publishes the legacy helper (``LEGACY_KILL_SWITCH``) as its
    kill switch unless its setup names one (the add-on's ``enable_flag`` option overrides it
    until a revisioned setup is adopted; the engine's heartbeat reports the flag actually in
    use, see ``room_gate``). Since add-on 0.11.0 the default room's hardware map
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
    enable_flag = default_gate(prefix)
    hw = hardware or {}
    setup = setup or {}
    # Only when DECLARED. A room that never declared its plumbing publishes byte-for-byte the
    # descriptor it always did, so the controller's saved setup fingerprint still matches and an
    # update does not strand the room behind a disarm cycle.
    declared = {"plumbing": setup["plumbing"]} if setup.get("plumbing") else {}
    # The tank level, likewise only when mapped: a distance sensor and/or a low float, and how the
    # controller turns them into a level (full and empty distances, the float's low state).
    declared.update(
        {k: hw[k] for k in ("tank_distance_sensor", "tank_low_float") if hw.get(k)}
    )
    # The room's light, likewise only when mapped: the controller checks it against the lights hours.
    declared.update(
        {"light_entity": hw["light_entity"]} if hw.get("light_entity") else {}
    )
    # The room's climate sensors, likewise only when mapped: read-only, for the dashboard's history
    # chart. The controller reads none of them.
    declared.update({k: hw[k] for k in CLIMATE_SENSORS if hw.get(k)})
    if setup.get("tank_level") and (
        hw.get("tank_distance_sensor") or hw.get("tank_low_float")
    ):
        declared["tank_level"] = setup["tank_level"]
    # Which integration Home Assistant actually loaded, for the dashboard's sidebar and for pairing
    # diagnostics. Passed in (this module reads nothing from Home Assistant itself). The
    # controller's setup fingerprint reads named keys only, so this does not disturb a
    # restart-resume (addons/f2_control/tests/test_versions.py pins that).
    versions = (
        {"integration_version": integration_version} if integration_version else {}
    )
    # WHICH room this is. A room that is deleted and set up again publishes the same entity ids
    # and starts its setup revision again at 1; without this the running controller cannot tell
    # it from the room it already adopted, and goes on driving the old map. Like the version, it
    # is not one of the keys the setup fingerprint reads.
    which = {"entry_id": entry_id} if entry_id else {}
    # What the room grows in (its substrate select), passed in like the version. The controller
    # reads it with "generic" as the default and adopts it with no disarm cycle: it is not one of
    # the keys the setup fingerprint reads.
    grown_in = {"substrate": substrate} if substrate else {}
    return {
        **declared,
        **versions,
        **which,
        **grown_in,
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
