"""The site store and its services: supply_get and supply_save (G1: pump capacity, exclusive groups).

One store for the whole site (crop_steering.site), set up with the first room; each room after it
only joins, and the store, the sensor and the services stay while any room is loaded. Reading is
open to any signed-in user; a save needs an administrator.

sensor.crop_steering_supply_config is what the controller app reads: its state is the revision and
its attributes the pumps, the groups, the meters and each active zone's demand in L/h. It exists
only once a supply has been saved, so a site that never saved one reads exactly as before.
Nothing here switches, presses or sets any hardware.
"""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from datetime import datetime, timezone

from . import site_store
from .admin import async_require_admin
from .const import DOMAIN
from .generated.guards import zone_demand_lph
from .generated.ids import new_id
from .journal_api import attribution, note
from .room import room_prefix

_LOGGER = logging.getLogger(__name__)

SERVICES = ("supply_get", "supply_save")
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
                raise ValueError(self.error)
            if data["expected_revision"] != self.document["revision"]:
                raise ValueError(
                    "Supply settings changed elsewhere. Reload before saving."
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
            shared = new_id()
            who = who or {}
            for room_id in ids:
                note(
                    self.hass,
                    room_id,
                    "config.changed",
                    actor=who.get("actor", "system"),
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


async def async_setup_site(hass, entry) -> None:
    """Once for the site, with the first room that sets up; each room after it only joins (and
    publishes again, as its sizing may have changed)."""
    import voluptuous as vol
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError

    data = hass.data.setdefault(DOMAIN, {})
    data.setdefault("_site_entries", set()).add(entry.entry_id)
    if "_site" in data:
        data["_site"].publish()
        return
    site = data["_site"] = SiteStore(hass)
    await site.async_init()
    site.publish()

    async def handle(call):
        try:
            if call.service == "supply_get":
                return await site.response()
            await async_require_admin(hass, call, f"{DOMAIN}.supply_save")
            return await site.save(call.data, attribution(hass, call))
        except (ValueError, OSError) as error:
            raise HomeAssistantError(str(error)) from error

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
    }
    for service in SERVICES:
        hass.services.async_register(
            DOMAIN,
            service,
            handle,
            schema=vol.Schema(schemas[service]),
            supports_response=(
                SupportsResponse.ONLY
                if service == "supply_get"
                else SupportsResponse.OPTIONAL
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
