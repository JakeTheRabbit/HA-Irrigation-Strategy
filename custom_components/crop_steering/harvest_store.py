"""Each run's harvest: the yield and what was learned at the end of a grow, entered by hand. Read-only data for
History > Grows: nothing here changes watering.

Kept in its own Store per room (crop_steering.harvests.<entry_id>), keyed by run id, apart from the run records:
an older integration that rewrites the run records never drops a harvest. Every field is optional. Worked out
when read (on the dashboard), never stored: grams per plant, g/m2, grams per litre fed and the dry/wet ratio.

`harvests_get` is open to any signed-in user, as the run records are; `runs_set_harvest` needs an administrator
and the revision `harvests_get` returned. A stored harvest that does not pass on load is left out with a warning;
the rest load.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import date, datetime, timezone
import logging
import math
import re

from .admin import async_require_admin
from .api_v2 import StaleRevision
from .const import DOMAIN, MAX_ZONES
from .room import room_prefix

_LOGGER = logging.getLogger(__name__)

SERVICES = ("harvests_get", "runs_set_harvest")
MAX_PLANTS = 500
MAX_TERPENES = 20
WEIGHTS = {
    "wet_weight_g": 1e8,
    "dry_weight_g": 1e8,
    "plants_harvested": 100000,
    "canopy_m2": 100000,
}


def _amount(value, label, high):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    if not math.isfinite(value) or not 0 <= value <= high:
        raise ValueError(f"{label} is outside its supported range")
    return float(value)


def _text(value, label, maximum):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str) or len(value.strip()) > maximum:
        raise ValueError(f"{label} must contain at most {maximum} characters")
    return value.strip()


def _weights(raw, label):
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be an object")
    out = {key: _amount(raw.get(key), key, high) for key, high in WEIGHTS.items()}
    if out["plants_harvested"] is not None and out["plants_harvested"] != int(
        out["plants_harvested"]
    ):
        raise ValueError("Plants harvested must be a whole number")
    if out["plants_harvested"] is not None:
        out["plants_harvested"] = int(out["plants_harvested"])
    return out if any(v is not None for v in out.values()) else None


def normalize_harvest(raw):
    """A harvest block rebuilt from the keys this version knows, every value bounded; missing fields are None."""
    if not isinstance(raw, dict):
        raise ValueError("A harvest must be an object")
    when = raw.get("harvest_date")
    if when is not None:
        if not isinstance(when, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", when):
            raise ValueError("Use a harvest date in YYYY-MM-DD format")
        date.fromisoformat(when)
    zones = raw.get("zones") or {}
    if not isinstance(zones, dict):
        raise ValueError("Zone harvests must be an object")
    clean_zones = {}
    for key, value in zones.items():
        try:
            zone = int(key)
        except (TypeError, ValueError):
            raise ValueError("Zone harvests are keyed by zone number") from None
        if not 1 <= zone <= MAX_ZONES:
            raise ValueError("Zone harvests are keyed by zone number")
        weights = _weights(value, f"Zone {zone}")
        if weights:
            clean_zones[str(zone)] = weights
    plants = raw.get("plants") or []
    if not isinstance(plants, list) or len(plants) > MAX_PLANTS:
        raise ValueError(f"At most {MAX_PLANTS} plant entries")
    clean_plants = []
    for plant in plants:
        if not isinstance(plant, dict):
            raise ValueError("A plant entry must be an object")
        clean_plants.append(
            {
                "label": _text(plant.get("label"), "Plant label", 40),
                "zone": (
                    int(plant["zone"])
                    if isinstance(plant.get("zone"), int)
                    and not isinstance(plant.get("zone"), bool)
                    and 1 <= plant["zone"] <= MAX_ZONES
                    else None
                ),
                "wet_g": _amount(plant.get("wet_g"), "Plant wet weight", 1e6),
                "dry_g": _amount(plant.get("dry_g"), "Plant dry weight", 1e6),
            }
        )
    lab = raw.get("lab") or {}
    if not isinstance(lab, dict):
        raise ValueError("Lab results must be an object")
    terpenes = lab.get("terpenes") or {}
    if not isinstance(terpenes, dict) or len(terpenes) > MAX_TERPENES:
        raise ValueError(f"At most {MAX_TERPENES} terpenes")
    return {
        "harvest_date": when,
        "room": _weights(raw.get("room"), "Room"),
        "zones": clean_zones,
        "plants": clean_plants,
        "quality": _text(raw.get("quality"), "Quality grade", 40),
        "notes": _text(raw.get("notes"), "Notes", 500),
        "lab": {
            "thc_pct": _amount(lab.get("thc_pct"), "THC %", 100),
            "terpenes": {
                _text(name, "Terpene name", 40): _amount(value, "Terpene value", 100)
                for name, value in terpenes.items()
                if _text(name, "Terpene name", 40)
            },
        },
        "updated_at": (
            raw.get("updated_at") if isinstance(raw.get("updated_at"), str) else None
        ),
    }


class HarvestStore:
    def __init__(self, hass, entry, store=None):
        self.hass, self.entry = hass, entry
        self.room_id = "room:" + room_prefix(entry)
        self._store = store
        self._lock = asyncio.Lock()
        self.revision = 0
        self.harvests = {}

    async def async_init(self):
        if self._store is None:
            from homeassistant.helpers.storage import Store

            self._store = Store(
                self.hass, 1, f"{DOMAIN}.harvests.{self.entry.entry_id}"
            )
        value = await self._store.async_load()
        if not isinstance(value, dict):
            return
        if type(value.get("revision")) is int and value["revision"] >= 0:
            self.revision = value["revision"]
        stored = value.get("harvests")
        for run_id, raw in stored.items() if isinstance(stored, dict) else ():
            try:
                self.harvests[str(run_id)] = normalize_harvest(raw)
            except (ValueError, TypeError) as error:
                _LOGGER.warning(
                    "The stored harvest of run %s in %s was left out: %s",
                    run_id,
                    self.room_id,
                    error,
                )

    def response(self):
        return {
            "schema_version": 1,
            "room_id": self.room_id,
            "revision": self.revision,
            "harvests": deepcopy(self.harvests),
        }

    async def set(self, data):
        async with self._lock:
            if data.get("expected_revision") != self.revision:
                raise StaleRevision(
                    "Harvests changed elsewhere. Reload before saving.", self.revision
                )
            run_id = data.get("run_id")
            runs = (
                self.hass.data.get(DOMAIN, {}).get("_runs", {}).get(self.entry.entry_id)
            )
            if runs is None or not any(
                r["id"] == run_id for r in runs.document["runs"]
            ):
                raise ValueError("Run does not belong to this room")
            harvests = deepcopy(self.harvests)
            if data.get("harvest") is None:
                harvests.pop(run_id, None)
            else:
                block = normalize_harvest(data["harvest"])
                block["updated_at"] = datetime.now(timezone.utc).isoformat()
                harvests[run_id] = block
            await self._store.async_save(
                {"revision": self.revision + 1, "harvests": harvests}
            )
            self.revision += 1
            self.harvests = harvests
            return self.response()


def resolve_harvests(hass, room_id):
    if not isinstance(room_id, str) or not room_id.startswith("room:"):
        raise ValueError("A canonical room_id is required")
    matches = [
        m
        for m in hass.data.get(DOMAIN, {}).get("_harvests", {}).values()
        if m.room_id == room_id
    ]
    if len(matches) != 1:
        raise ValueError("Harvest room is unknown or ambiguous")
    return matches[0]


async def async_setup_harvests(hass, entry):
    import voluptuous as vol
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError

    from .api_v2 import fields, wrap

    manager = HarvestStore(hass, entry)
    await manager.async_init()
    hass.data.setdefault(DOMAIN, {}).setdefault("_harvests", {})[
        entry.entry_id
    ] = manager
    if hass.services.has_service(DOMAIN, SERVICES[0]):
        return

    async def handle(call):
        if call.service != "harvests_get":
            await async_require_admin(hass, call, f"{DOMAIN}.{call.service}")
        try:
            target = resolve_harvests(hass, call.data["room_id"])
            if call.service == "harvests_get":
                return target.response()
            return await target.set(call.data)
        except (ValueError, KeyError, OSError) as error:
            raise HomeAssistantError(str(error)) from error

    schemas = {
        "harvests_get": {},
        "runs_set_harvest": {
            vol.Required("expected_revision"): vol.All(int, vol.Range(min=0)),
            vol.Required("run_id"): str,
            vol.Required("harvest"): vol.Any(None, dict),
        },
    }
    for service in SERVICES:
        hass.services.async_register(
            DOMAIN,
            service,
            wrap(handle),
            schema=vol.Schema(
                fields({vol.Required("room_id"): str, **schemas[service]})
            ),
            supports_response=SupportsResponse.ONLY,
        )


async def async_unload_harvests(hass, entry):
    managers = hass.data.get(DOMAIN, {}).get("_harvests", {})
    managers.pop(entry.entry_id, None)
    if not managers:
        for service in SERVICES:
            hass.services.async_remove(DOMAIN, service)
