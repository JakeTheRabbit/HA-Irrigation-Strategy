"""The site store and its services: supply_get and supply_save (G1: pump capacity, exclusive groups),
and the presets every client shares with preset_list/save/delete/apply and copy_config (G10).

One store for the whole site (crop_steering.site), set up with the first room; each room after it
only joins, and the store, the sensor and the services stay while any room is loaded. Reading is
open to any signed-in user; a save needs an administrator.

sensor.crop_steering_supply_config is what the controller app reads: its state is the revision and
its attributes the pumps, the groups, the meters and each active zone's demand in L/h. It exists
only once a supply has been saved, so a site that never saved one reads exactly as before.
Nothing here switches, presses or sets any hardware. A preset apply or a copy writes the rooms'
own numbers, each read back (presets.py); presets keep their own revision, apart from the supply's.
"""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from datetime import datetime, timezone

from . import presets, site_store
from .admin import async_require_admin
from .api_v2 import StaleRevision, Unavailable
from .const import DOMAIN
from .generated.guards import zone_demand_lph
from .generated.ids import new_id
from .journal_api import attribution, note
from .room import room_prefix

_LOGGER = logging.getLogger(__name__)

SERVICES = (
    "supply_get",
    "supply_save",
    "preset_list",
    "preset_save",
    "preset_delete",
    "preset_apply",
    "copy_config",
)
READS = ("supply_get", "preset_list")
SENSOR = f"sensor.{DOMAIN}_supply_config"
STORAGE_KEY = f"{DOMAIN}.site"
SIZING_KEYS = ("plant_count", "drippers_per_plant", "dripper_flow_rate")


class SiteStore:
    def __init__(self, hass, store=None):
        self.hass = hass
        self._store = store
        self._lock = asyncio.Lock()
        self.document = site_store.empty()
        self.error = None
        self.warnings = []

    async def async_init(self):
        try:
            if self._store is None:
                from homeassistant.helpers.storage import Store

                self._store = Store(self.hass, 1, STORAGE_KEY)
            value = await self._store.async_load()
            if value is not None:
                self.document, self.warnings = site_store.load(value)
                for warning in self.warnings:
                    _LOGGER.warning(
                        "Crop Steering site store: stored %s could not be read and reads as empty "
                        "until a save replaces it: %s",
                        warning["section"],
                        warning["error"],
                    )
        except Exception as error:
            # The supply then reads as not set up; a save is refused, so the file is never overwritten.
            self.error = (
                "The stored site settings could not be loaded; they have not been "
                f"overwritten: {error}"
            )
            _LOGGER.error("Crop Steering site store: %s", self.error)

    def rooms(self, skip=None) -> list[dict]:
        """Every active room's pump and each active zone's demand in L/h (not the room of the
        config entry `skip`, which is going away)."""
        from .setup_api import effective, setup_sizing

        rooms = []
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            data = effective(entry)
            if entry.entry_id == skip or not data.get("active", True):
                continue
            zones = {}
            for zone in range(1, int(data.get("num_zones", 1)) + 1):
                cfg = (
                    data.get("zones", {}).get(str(zone))
                    or data.get("zones", {}).get(zone)
                    or {}
                )
                if not cfg.get("active", True):
                    continue
                size = {
                    key: setup_sizing(self.hass, data, cfg, zone, key)
                    for key in SIZING_KEYS
                }
                zones[zone] = zone_demand_lph(**size)
            rooms.append(
                {
                    "room_id": "room:" + room_prefix(entry),
                    "pump": data.get("hardware", {}).get("pump_switch", ""),
                    "zones": zones,
                }
            )
        return rooms

    async def check(self, section: dict) -> dict:
        """The capacity check, worked out off the event loop (the rooms are read on it)."""
        return await self.hass.async_add_executor_job(
            site_store.capacity_check,
            section["irrigation_pumps"],
            self.rooms(),
            section["zone_groups"],
        )

    async def response(self) -> dict:
        section = site_store.supply_of(self.document)
        return {
            "revision": self.document["revision"],
            **deepcopy(section),
            "capacity_check": await self.check(section),
            "warnings": deepcopy(self.warnings),
            "error": self.error,
        }

    def publish(self, skip=None):
        """sensor.crop_steering_supply_config: absent until a supply is saved, unavailable while the
        stored settings cannot be read (the controller then runs as it did before)."""
        if self.error:
            self.hass.states.async_set(SENSOR, "unavailable", {"error": self.error})
            return
        if not self.document["revision"]:
            self.hass.states.async_remove(SENSOR)
            return
        demand = {}
        for room in self.rooms(skip):
            if room["zones"]:
                demand[room["room_id"]] = {
                    str(zone): lph for zone, lph in sorted(room["zones"].items())
                }
        document = self.document
        self.hass.states.async_set(
            SENSOR,
            str(document["revision"]),
            {
                "friendly_name": "Crop Steering supply",
                "irrigation_pumps": deepcopy(document["irrigation_pumps"]),
                "zone_groups": deepcopy(document["zone_groups"]),
                "zone_meters": deepcopy(document["zone_meters"]),
                "zone_demand_lph": demand,
            },
        )

    def _new_section(self, data) -> dict:
        section = deepcopy(site_store.supply_of(self.document))
        section["irrigation_pumps"] = site_store.clean_pumps(data["irrigation_pumps"])
        if "water_sources" in data:
            section["water_sources"] = site_store.clean_sources(data["water_sources"])
        if "zone_groups" in data:
            section["zone_groups"] = site_store.clean_groups(data["zone_groups"])
        if "zone_meters" in data:
            section["zone_meters"] = site_store.clean_meters(data["zone_meters"])
        return section

    async def save(self, data, who=None) -> dict:
        from .setup_api import setup_diff

        async with self._lock:
            if self.error:
                raise Unavailable(self.error)
            if data["expected_revision"] != self.document["revision"]:
                raise StaleRevision(
                    "Supply settings changed elsewhere. Reload before saving.",
                    self.document["revision"],
                )
            unread = [
                w["section"]
                for w in self.warnings
                if w["section"] != "irrigation_pumps" and w["section"] not in data
            ]
            if unread:
                raise ValueError(
                    f"The stored {', '.join(unread)} could not be read and would be lost. "
                    "Send that section in this save to replace it."
                )
            old = deepcopy(site_store.supply_of(self.document))
            new = self._new_section(data)
            check = await self.check(new)
            diff = setup_diff(old, new)
            if data.get("preview"):
                # Shown, not refused: the caller draws the sentence and the suggested count.
                return {"diff": diff, "capacity_check": check}
            site_store.refuse_over_capacity(check)
            document = {
                **self.document,
                **new,
                "revision": self.document["revision"] + 1,
            }
            await self._store.async_save(deepcopy(document))
            self.document = document
            self.warnings = [
                w
                for w in self.warnings
                if w["section"] != "irrigation_pumps" and w["section"] not in data
            ]
            self.publish()
            self._journal(old, new, diff, who)
            result = await self.response()
            published = self.hass.states.get(SENSOR)
            result["readback"] = {
                "status": (
                    "ok"
                    if published is not None
                    and published.state == str(document["revision"])
                    else "mismatch"
                ),
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "entity_id": SENSOR,
            }
            return result

    # ------------------------------------------------------------------ presets (G10)
    def presets_response(self) -> dict:
        return {
            "revision": self.document["presets_revision"],
            "presets": [
                deepcopy(p) for p in self.document["presets"] if not p.get("deleted_at")
            ],
            "error": self.error,
        }

    def preset(self, preset_id) -> dict:
        for preset in self.document["presets"]:
            if preset.get("id") == preset_id and not preset.get("deleted_at"):
                return deepcopy(preset)
        raise ValueError(f"No preset {preset_id}")

    async def save_preset(self, data, values, who=None) -> dict:
        """A new preset of `values` ({section: {key: value}}, captured from data["from"])."""
        name = str(data.get("name") or "").strip()
        if not name or len(name) > 60:
            raise ValueError("A preset needs a name of up to 60 characters")
        scope = data.get("scope")
        if scope not in presets.SCOPES:
            raise ValueError("scope must be targets, timers or all")
        source = presets.ref(data.get("from"))
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        who = who or {}
        preset = {
            "id": new_id(),
            "name": name,
            "scope": scope,
            "sections": list(presets.SCOPES[scope]),
            "from": source,
            "values": deepcopy(values),
            "created_at": stamp,
            "updated_at": stamp,
            "deleted_at": None,
            "by": {"actor": who.get("actor"), "user_id": who.get("user_id")},
        }

        def change(stored):
            stored.append(preset)
            return deepcopy(preset)

        result, revision = await self._save_presets(
            data["expected_revision"], change, who, source["room_id"]
        )
        return {"preset": result, "revision": revision}

    async def delete_preset(self, data, who=None) -> dict:
        """Soft: the preset leaves the list and stays in the store with deleted_at."""
        source = self.preset(data["id"]).get("from")
        if not isinstance(source, dict) or not isinstance(source.get("room_id"), str):
            raise ValueError(f"Preset {data['id']} has no source room")
        room_id = source["room_id"]

        def change(stored):
            for preset in stored:
                if preset.get("id") == data["id"] and not preset.get("deleted_at"):
                    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    preset.update(deleted_at=stamp, updated_at=stamp)
                    return deepcopy(preset)
            raise ValueError(f"No preset {data['id']}")

        result, revision = await self._save_presets(
            data["expected_revision"], change, who, room_id
        )
        return {"preset": result, "revision": revision}

    async def _save_presets(self, expected_revision, change, who, room_id):
        """Change a copy of the presets, save, and journal config.changed (never failing the save)."""
        from .setup_api import setup_diff

        async with self._lock:
            if self.error:
                raise Unavailable(self.error)
            if expected_revision != self.document["presets_revision"]:
                raise StaleRevision(
                    "Presets changed elsewhere. Reload before saving.",
                    self.document["presets_revision"],
                )
            old = deepcopy(self.document["presets"])
            stored = deepcopy(old)
            result = change(stored)
            document = {
                **self.document,
                "presets": stored,
                "presets_revision": self.document["presets_revision"] + 1,
            }
            await self._store.async_save(deepcopy(document))
            self.document = document
        who = who or {}
        note(
            self.hass,
            room_id,
            "config.changed",
            actor=who.get("actor", "system"),
            detail=who.get("detail"),
            user_id=who.get("user_id"),
            client=who.get("client"),
            correlation=(
                {"causation_id": who["causation_id"]}
                if who.get("causation_id")
                else None
            ),
            data={
                "store": "site",
                "section": "presets",
                "old": old,
                "new": deepcopy(stored),
                "diff": setup_diff(old, stored),
            },
        )
        return result, document["presets_revision"]

    def _journal(self, old, new, diff, who):
        """config.changed with the whole section before and after, once in the journal of every room
        whose pump or zone is in the old or the new section (all sharing one causation_id so a fold
        can count the change once); the first room when none is. Never fails or delays the save.
        """
        try:
            if not diff:
                return
            rooms = self.rooms()
            pumps = {p["entity_id"] for s in (old, new) for p in s["irrigation_pumps"]}
            named = {
                room_id
                for s in (old, new)
                for key in ("zone_groups", "zone_meters")
                for room_id in s[key]
            }
            ids = sorted(
                r["room_id"]
                for r in rooms
                if r["pump"] in pumps or r["room_id"] in named
            )
            if not ids and rooms:
                ids = [min(r["room_id"] for r in rooms)]
            who = who or {}
            shared = who.get("causation_id") or new_id()
            for room_id in ids:
                note(
                    self.hass,
                    room_id,
                    "config.changed",
                    actor=who.get("actor", "system"),
                    detail=who.get("detail"),
                    user_id=who.get("user_id"),
                    client=who.get("client"),
                    correlation={"causation_id": shared},
                    data={
                        "store": "site",
                        "section": "supply",
                        "old": old,
                        "new": new,
                        "diff": diff,
                    },
                )
        except Exception as error:
            _LOGGER.debug("Supply change not journaled: %s", error)


def _rows_refused(call, result):
    """API v2: an apply or copy whose target refused a value (or a timer it may not take out). The
    other values are written; every row is in `data.applied`."""
    from .api_v2 import failure

    refused = [
        row for row in result.get("applied") or () if row.get("readback") == "refused"
    ]
    if not refused:
        return None
    return failure(
        "guard_refused",
        "Not applied: "
        + "; ".join(f"{row['key']}: {row.get('error')}" for row in refused),
    )


async def async_setup_site(hass, entry) -> None:
    """Once for the site, with the first room that sets up; each room after it only joins (and
    publishes again, as its sizing may have changed)."""
    import voluptuous as vol
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError

    from .api_v2 import fields, wrap

    data = hass.data.setdefault(DOMAIN, {})
    data.setdefault("_site_entries", set()).add(entry.entry_id)
    if "_site" in data:
        data["_site"].publish()
        return
    site = data["_site"] = SiteStore(hass)
    await site.async_init()
    site.publish()

    async def handle(call):
        args = call.data
        try:
            if call.service == "supply_get":
                return await site.response()
            if call.service == "preset_list":
                return site.presets_response()
            await async_require_admin(hass, call, f"{DOMAIN}.{call.service}")
            who = attribution(hass, call)
            if call.service == "supply_save":
                return await site.save(args, who)
            if call.service == "preset_save":
                sections = presets.SCOPES.get(args["scope"], ())
                values, skipped = presets.read_source(hass, args["from"], sections)
                saved = await site.save_preset(args, values, who)
                return {**saved, "skipped": skipped}
            if call.service == "preset_delete":
                return await site.delete_preset(args, who)
            preview = args.get("preview", False)
            if call.service == "preset_apply":
                preset = site.preset(args["preset_id"])
                detail = f"preset {preset['name']}"
                return await presets.apply(
                    hass,
                    preset["values"],
                    args["to"],
                    preview,
                    {**who, "detail": detail},
                )
            sections = list(args["sections"])
            if not sections or not set(sections) <= set(presets.SECTIONS):
                raise ValueError(
                    "sections must name one or more of " + ", ".join(presets.SECTIONS)
                )
            source = presets.ref(args["from"])
            wanted, skipped = presets.read_source(hass, source, sections)
            detail = "copy from " + source["room_id"]
            if "zone" in source:
                detail += f" zone {source['zone']}"
            copied = await presets.apply(
                hass, wanted, args["to"], preview, {**who, "detail": detail}
            )
            return {**copied, "skipped": skipped}
        except (ValueError, OSError) as error:
            raise HomeAssistantError(str(error)) from error

    whole = vol.All(int, vol.Range(min=0))
    common = {
        vol.Optional("client"): vol.In(["mcp", "aigrow"]),
        vol.Optional("proposal_token"): str,
    }
    schemas = {
        "supply_get": {},
        "supply_save": {
            vol.Required("expected_revision"): vol.All(int, vol.Range(min=0)),
            vol.Required("irrigation_pumps"): list,
            vol.Optional("water_sources"): list,
            vol.Optional("zone_groups"): dict,
            vol.Optional("zone_meters"): dict,
            vol.Optional("preview"): bool,
            vol.Optional("client"): vol.In(["mcp", "aigrow"]),
            vol.Optional("proposal_token"): str,
        },
        "preset_list": {},
        "preset_save": {
            vol.Required("name"): str,
            vol.Required("scope"): vol.In(list(presets.SCOPES)),
            vol.Required("from"): dict,
            vol.Required("expected_revision"): whole,
            **common,
        },
        "preset_delete": {
            vol.Required("id"): str,
            vol.Required("expected_revision"): whole,
            **common,
        },
        "preset_apply": {
            vol.Required("preset_id"): str,
            vol.Required("to"): [dict],
            vol.Optional("preview"): bool,
            **common,
        },
        "copy_config": {
            vol.Required("from"): dict,
            vol.Required("to"): [dict],
            vol.Required("sections"): [vol.In(list(presets.SECTIONS))],
            vol.Optional("preview"): bool,
            **common,
        },
    }
    for service in SERVICES:
        hass.services.async_register(
            DOMAIN,
            service,
            wrap(
                handle,
                error_of={"preset_apply": _rows_refused, "copy_config": _rows_refused},
            ),
            schema=vol.Schema(fields(schemas[service])),
            supports_response=(
                SupportsResponse.ONLY if service in READS else SupportsResponse.OPTIONAL
            ),
        )


async def async_unload_site(hass, entry) -> None:
    """The site store goes with the last room: its services and its sensor."""
    data = hass.data.get(DOMAIN, {})
    entries = data.get("_site_entries", set())
    entries.discard(entry.entry_id)
    site = data["_site"] if entries else data.pop("_site", None)
    if site is None:
        return
    if entries:
        site.publish(skip=entry.entry_id)
        return
    for service in SERVICES:
        hass.services.async_remove(DOMAIN, service)
    hass.states.async_remove(SENSOR)
