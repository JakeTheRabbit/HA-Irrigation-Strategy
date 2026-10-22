"""Wall, tablet and dosing-station dashboards from templates (G11): dashboard_create and dashboard_list.

render() is pure: a Lovelace config of built-in cards only (entities, gauge, tile, history-graph)
that names only entities the room has. A room here is what room_of() reads from Home Assistant: the
room's own entities from the entity registry, and the hardware it maps that Home Assistant has.

dashboard_create makes a storage dashboard through Home Assistant's own dashboards collection (the
one Settings > Dashboards uses), saves the config into it, reads it back, and tracks it in the store
crop_steering.dashboards. dashboard_list says, for each, whether it still exists in Home Assistant.
Nothing here switches, presses or sets any hardware. A site that never calls these is unchanged.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from copy import deepcopy
from datetime import datetime, timezone

from .admin import async_require_admin
from .const import DOMAIN
from .generated.ids import new_id
from .journal_api import attribution, note
from .room import room_prefix, zone_device_name

_LOGGER = logging.getLogger(__name__)

TEMPLATES = ("facility_wall", "room_tablet", "dosing_station")
TEMPLATE_INFO = {
    "facility_wall": (
        "Facility wall",
        "Every chosen room at a glance: phase, average moisture and EC, the kill switch.",
    ),
    "room_tablet": (
        "Room tablet",
        "One room's zones: each zone's status, moisture, EC and water today.",
    ),
    "dosing_station": (
        "Dosing station",
        "Each chosen room's feed EC and pH, tanks and dosing state.",
    ),
}
SERVICES = ("dashboard_create", "dashboard_list")
READS = ("dashboard_list",)
STORAGE_KEY = f"{DOMAIN}.dashboards"
# The hardware a dosing station shows, when the room maps it.
DOSING_HARDWARE = (
    "feed_ec_sensor",
    "feed_ph_sensor",
    "tank_ec_sensor",
    "tank_ph_sensor",
    "tank_temperature_sensor",
    "water_level_sensor",
    "tank_last_fill_sensor",
)


# ---------------------------------------------------------------------- pure
def _ours(room, domain, key):
    return f"{domain}.{DOMAIN}_{room['room_id'][len('room:'):]}{key}"


def _pick(room, ids):
    have = set(room["entities"])
    return [e for e in ids if e in have]


def _entities(title, ids):
    return [{"type": "entities", "title": title, "entities": ids}] if ids else []


def _history(title, ids):
    return (
        [
            {
                "type": "history-graph",
                "title": title,
                "hours_to_show": 24,
                "entities": ids,
            }
        ]
        if ids
        else []
    )


def _gauge(entity, name, low, high):
    return {"type": "gauge", "entity": entity, "name": name, "min": low, "max": high}


def _facility_wall(rooms):
    cards, history = [], []
    for room in rooms:
        avg_vwc = _pick(room, [_ours(room, "sensor", "configured_avg_vwc")])
        cards += [_gauge(e, f"{room['name']} VWC", 0, 100) for e in avg_vwc]
        cards += _entities(
            room["name"],
            _pick(
                room,
                [
                    _ours(room, "sensor", "current_phase"),
                    _ours(room, "sensor", "configured_avg_vwc"),
                    _ours(room, "sensor", "configured_avg_ec"),
                    _ours(room, "switch", "room_active"),
                    _ours(room, "switch", "engine_enabled"),
                ],
            ),
        )
        history += avg_vwc
    return [
        {
            "title": "Facility",
            "path": "facility",
            "cards": cards + _history("VWC", history),
        }
    ]


def _room_tablet(rooms):
    if len(rooms) != 1:
        raise ValueError("room_tablet shows one room: choose exactly one")
    room = rooms[0]
    cards = _entities(
        room["name"],
        _pick(
            room,
            [
                _ours(room, "sensor", "current_phase"),
                _ours(room, "switch", "room_active"),
            ],
        ),
    )
    history = []
    for zone in room["zones"]:
        z = zone["zone"]
        cards += [
            {"type": "tile", "entity": e, "name": zone["name"]}
            for e in _pick(room, [_ours(room, "sensor", f"zone_{z}_status")])
        ]
        cards += _entities(
            zone["name"],
            _pick(
                room,
                [
                    _ours(room, "sensor", f"vwc_zone_{z}"),
                    _ours(room, "sensor", f"ec_zone_{z}"),
                    _ours(room, "sensor", f"zone_{z}_last_irrigation"),
                    _ours(room, "sensor", f"zone_{z}_irrigation_count_today"),
                    _ours(room, "sensor", f"zone_{z}_daily_water_usage"),
                ],
            ),
        )
        history += _pick(room, [_ours(room, "sensor", f"vwc_zone_{z}")])
    return [
        {
            "title": room["name"],
            "path": "zones",
            "cards": cards + _history("Zone VWC", history),
        }
    ]


def _dosing_station(rooms):
    cards, history = [], []
    for room in rooms:
        hardware = room.get("hardware", {})
        feed = {}
        for kind in ("feed_ec", "feed_ph"):
            corrected = _pick(room, [_ours(room, "sensor", f"{kind}_corrected")])
            raw = _pick(room, [hardware.get(f"{kind}_sensor", "")])
            feed[kind] = (corrected or raw)[:1]
        cards += [_gauge(e, f"{room['name']} feed EC", 0, 4) for e in feed["feed_ec"]]
        cards += [_gauge(e, f"{room['name']} feed pH", 4, 8) for e in feed["feed_ph"]]
        ids = _pick(
            room,
            [
                _ours(room, "sensor", "dosing_config"),
                _ours(room, "sensor", "stock_low"),
                _ours(room, "sensor", "feed_ec_corrected"),
                _ours(room, "sensor", "feed_ph_corrected"),
                *[hardware.get(key, "") for key in DOSING_HARDWARE],
            ],
        )
        cards += _entities(room["name"], list(dict.fromkeys(ids)))
        history += feed["feed_ec"] + feed["feed_ph"]
    return [
        {
            "title": "Dosing",
            "path": "dosing",
            "cards": cards + _history("Feed", history),
        }
    ]


_RENDER = {
    "facility_wall": _facility_wall,
    "room_tablet": _room_tablet,
    "dosing_station": _dosing_station,
}


def render(template: str, rooms: list[dict]) -> dict:
    """PURE. The Lovelace config of `template` for `rooms` ([{room_id, name, zones: [{zone, name}],
    entities: [...], hardware: {key: entity_id}}]), naming only entities in each room's `entities`.
    """
    if template not in _RENDER:
        raise ValueError(f"Unknown dashboard template {template!r}")
    if not rooms:
        raise ValueError("Choose at least one room")
    return {"views": _RENDER[template](rooms)}


def url_path_for(template: str, used) -> str:
    """PURE. crop-steering-<template>-<n>, n the lowest positive whole number not in `used`."""
    n = 1
    while f"crop-steering-{template}-{n}" in used:
        n += 1
    return f"crop-steering-{template}-{n}"


# ---------------------------------------------------------------------- Home Assistant
def room_of(hass, room_id: str) -> dict:
    """The room render() takes: its enabled entities in the registry, and the mapped hardware Home
    Assistant has a state for."""
    from homeassistant.helpers import entity_registry as er

    from .setup_api import effective

    entries = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if "room:" + room_prefix(e) == room_id
    ]
    if len(entries) != 1:
        raise ValueError(f"Room {room_id} is unknown or ambiguous")
    entry = entries[0]
    data = effective(entry)
    registry = er.async_get(hass)
    ids = {
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if not e.disabled_by
    }
    hardware = {
        key: value
        for key, value in (data.get("hardware") or {}).items()
        if isinstance(value, str) and value and hass.states.get(value) is not None
    }
    zones = data.get("zones") or {}
    return {
        "room_id": room_id,
        "name": entry.title,
        "zones": [
            {"zone": z, "name": zone_device_name(entry, z)}
            for z in range(1, int(data.get("num_zones", 1)) + 1)
            if (zones.get(str(z)) or zones.get(z) or {}).get("active", True)
        ],
        "entities": sorted(ids | set(hardware.values())),
        "hardware": hardware,
    }


def _lovelace(hass):
    """(dashboards collection, {url_path: LovelaceConfig}), or a HomeAssistantError while Home
    Assistant's dashboards are not loaded.

    Read from Home Assistant 2024.10 and 2026.9: hass.data["lovelace"] is a dict there and a
    LovelaceData dataclass here, and 2026.9 keeps the collection nowhere but in the websocket
    commands it serves (DashboardsCollectionWebSocket.storage_collection), so it is found there.
    """
    from homeassistant.exceptions import HomeAssistantError

    data = hass.data.get("lovelace")
    dashboards = getattr(data, "dashboards", None)
    if dashboards is None and isinstance(data, dict):
        dashboards = data.get("dashboards")
    handler = (hass.data.get("websocket_api") or {}).get("lovelace/dashboards/create")
    owner = getattr(inspect.unwrap(handler[0]), "__self__", None) if handler else None
    collection = getattr(owner, "storage_collection", None)
    if dashboards is None or collection is None:
        raise HomeAssistantError(
            "Home Assistant's dashboards are not loaded yet. Try again once Home Assistant has "
            "finished starting."
        )
    return collection, dashboards


class DashboardStore:
    def __init__(self, hass, store=None):
        self.hass = hass
        self._store = store
        self._lock = asyncio.Lock()
        self.document = {"revision": 0, "dashboards": []}
        self.error = None

    async def async_init(self):
        try:
            if self._store is None:
                from homeassistant.helpers.storage import Store

                self._store = Store(self.hass, 1, STORAGE_KEY)
            value = await self._store.async_load()
            if value is not None:
                if not isinstance(value.get("dashboards"), list):
                    raise ValueError("dashboards is not a list")
                self.document = value
        except Exception as error:
            # Creating is then refused, so the file is never overwritten.
            self.error = f"The stored dashboards could not be loaded; they have not been overwritten: {error}"
            _LOGGER.error("Crop Steering dashboards: %s", self.error)

    def listing(self) -> dict:
        try:
            _, existing = _lovelace(self.hass)
        except Exception:
            existing = {}
        return {
            "dashboards": [
                {
                    **{
                        k: deepcopy(d.get(k))
                        for k in (
                            "url_path",
                            "title",
                            "template",
                            "rooms",
                            "created_at",
                        )
                    },
                    "exists": d.get("url_path") in existing,
                }
                for d in self.document["dashboards"]
            ],
            "templates": [
                {
                    "id": t,
                    "name": TEMPLATE_INFO[t][0],
                    "description": TEMPLATE_INFO[t][1],
                }
                for t in TEMPLATES
            ],
            "error": self.error,
        }

    async def create(self, template, room_ids, title=None, who=None) -> dict:
        from homeassistant.exceptions import HomeAssistantError

        from .setup_api import setup_diff

        if template not in TEMPLATES:
            raise ValueError(f"Unknown dashboard template {template!r}")
        if self.error:
            raise ValueError(self.error)
        room_ids = list(dict.fromkeys(room_ids))
        rooms = [room_of(self.hass, room_id) for room_id in room_ids]
        config = render(template, rooms)
        title = (title or "").strip() or (
            f"{TEMPLATE_INFO[template][0]}: " + ", ".join(r["name"] for r in rooms)
        )
        collection, dashboards = _lovelace(self.hass)
        async with self._lock:
            used = (
                {d.get("url_path") for d in self.document["dashboards"]}
                | {item.get("url_path") for item in collection.async_items()}
                | set(dashboards)
            )
            url_path = url_path_for(template, used)
            await collection.async_create_item(
                {
                    "url_path": url_path,
                    "title": title,
                    "icon": "mdi:sprout",
                    "show_in_sidebar": True,
                    "require_admin": False,
                    "mode": "storage",
                }
            )
            await dashboards[url_path].async_save(deepcopy(config))
            if await dashboards[url_path].async_load(False) != config:
                raise HomeAssistantError(
                    f"Dashboard {url_path} was created but its config did not read back"
                )
            who = who or {}
            old = deepcopy(self.document["dashboards"])
            new = old + [
                {
                    "url_path": url_path,
                    "title": title,
                    "template": template,
                    "rooms": room_ids,
                    "created_at": datetime.now(timezone.utc).isoformat(
                        timespec="seconds"
                    ),
                    "by": {"actor": who.get("actor"), "user_id": who.get("user_id")},
                }
            ]
            document = {"revision": self.document["revision"] + 1, "dashboards": new}
            await self._store.async_save(deepcopy(document))
            self.document = document
        shared = new_id()
        for room_id in room_ids:
            note(
                self.hass,
                room_id,
                "config.changed",
                actor=who.get("actor", "system"),
                user_id=who.get("user_id"),
                client=who.get("client"),
                correlation={"causation_id": shared},
                data={
                    "store": "dashboards",
                    "section": "dashboards",
                    "old": old,
                    "new": deepcopy(new),
                    "diff": setup_diff(old, new),
                },
            )
        return {"url_path": url_path, "title": title}


async def async_setup_dashboards(hass, entry) -> None:
    """Once for the site, with the first room that sets up; each room after it only joins."""
    import voluptuous as vol
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError

    data = hass.data.setdefault(DOMAIN, {})
    data.setdefault("_dashboard_entries", set()).add(entry.entry_id)
    if "_dashboards" in data:
        return
    store = data["_dashboards"] = DashboardStore(hass)
    await store.async_init()

    async def handle(call):
        args = call.data
        try:
            if call.service == "dashboard_list":
                return store.listing()
            await async_require_admin(hass, call, f"{DOMAIN}.{call.service}")
            return await store.create(
                args["template"],
                args["rooms"],
                args.get("title"),
                attribution(hass, call),
            )
        except (ValueError, OSError) as error:
            raise HomeAssistantError(str(error)) from error

    schemas = {
        "dashboard_create": {
            vol.Required("template"): str,
            vol.Required("rooms"): [str],
            vol.Optional("title"): str,
            vol.Optional("client"): vol.In(["mcp", "aigrow"]),
            vol.Optional("proposal_token"): str,
        },
        "dashboard_list": {},
    }
    for service in SERVICES:
        hass.services.async_register(
            DOMAIN,
            service,
            handle,
            schema=vol.Schema(schemas[service]),
            supports_response=(
                SupportsResponse.ONLY if service in READS else SupportsResponse.OPTIONAL
            ),
        )


async def async_unload_dashboards(hass, entry) -> None:
    """The services go with the last room; the dashboards stay in Home Assistant."""
    data = hass.data.get(DOMAIN, {})
    entries = data.get("_dashboard_entries", set())
    entries.discard(entry.entry_id)
    if entries or data.pop("_dashboards", None) is None:
        return
    for service in SERVICES:
        hass.services.async_remove(DOMAIN, service)
