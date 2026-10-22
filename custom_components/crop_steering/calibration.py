"""Two-point calibration checks of a room's feed-water pH and EC probes, and their history.

The grower puts the probe in two reference solutions and records what it read in each. From those
two points this works out the probe's slope (100 % reads every step true) and its offset at the
anchor (pH 7, or EC 0), and whether the probe passes, is drifting or fails. Nothing here changes a
reading or touches hardware: a record says whether to trust the probe that guards the feed, and
when it was last checked. Stored per room in a store of its own; a room without one simply has no
history yet. Reading is open to any signed-in user; recording a check needs an administrator.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import logging
import math
from uuid import uuid4

from .admin import async_require_admin
from .const import DOMAIN
from .journal_api import attribution, note
from .room import room_prefix

_LOGGER = logging.getLogger(__name__)

SERVICES = ("calibration_get", "calibration_record")
HISTORY = 100
# probe -> (kind, the room setting that names its sensor)
PROBES = {"feed_ph": ("ph", "feed_ph_sensor"), "feed_ec": ("ec", "feed_ec_sensor")}
# kind -> readable range, smallest gap between the two references, anchor, offset pass / drifting
KINDS = {
    "ph": {"range": (0.0, 14.0), "spread": 1.0, "anchor": 7.0, "offset": (0.1, 0.3)},
    "ec": {"range": (0.0, 20.0), "spread": 0.5, "anchor": 0.0, "offset": (0.1, 0.3)},
}
SLOPE_PASS, SLOPE_DRIFTING = (95.0, 105.0), (90.0, 110.0)


def _number(value, low, high, label):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not low <= value <= high
    ):
        raise ValueError(f"{label} must be a number from {low:g} to {high:g}")
    return float(value)


def evaluate(kind, points):
    """PURE. The slope (%), the offset at the anchor and the verdict from two points, each the
    reference solution's value and what the probe read in it."""
    spec = KINDS[kind]
    if not isinstance(points, list) or len(points) != 2:
        raise ValueError("A two-point calibration needs exactly two points")
    clean = []
    for point in points:
        if not isinstance(point, dict):
            raise ValueError("Invalid calibration point")
        clean.append(
            {
                "reference": _number(
                    point.get("reference"), *spec["range"], "Reference"
                ),
                "reading": _number(point.get("reading"), *spec["range"], "Reading"),
            }
        )
    (ref1, read1), (ref2, read2) = ((p["reference"], p["reading"]) for p in clean)
    if abs(ref2 - ref1) < spec["spread"]:
        raise ValueError(
            f"The two reference solutions must be at least {spec['spread']:g} apart"
        )
    slope = (read2 - read1) / (ref2 - ref1)
    slope_pct = round(slope * 100, 1)
    offset = round(read1 + slope * (spec["anchor"] - ref1) - spec["anchor"], 3)
    good, drifting = spec["offset"]
    if SLOPE_PASS[0] <= slope_pct <= SLOPE_PASS[1] and abs(offset) <= good:
        verdict = "pass"
    elif (
        SLOPE_DRIFTING[0] <= slope_pct <= SLOPE_DRIFTING[1] and abs(offset) <= drifting
    ):
        verdict = "drifting"
    else:
        verdict = "fail"
    return {
        "points": clean,
        "slope_pct": slope_pct,
        "offset": offset,
        "verdict": verdict,
    }


class CalibrationStore:
    def __init__(self, hass, entry, store=None):
        self.hass, self.entry = hass, entry
        self.prefix = room_prefix(entry)
        self.room_id = "room:" + self.prefix
        self._store = store
        self._lock = asyncio.Lock()
        self.document = {"revision": 0, "records": []}
        self.error = None

    async def async_init(self):
        try:
            if self._store is None:
                from homeassistant.helpers.storage import Store

                self._store = Store(
                    self.hass, 1, f"{DOMAIN}.calibration.{self.entry.entry_id}"
                )
            value = await self._store.async_load()
            if value is not None:
                if (
                    not isinstance(value, dict)
                    or type(value.get("revision")) is not int
                    or value["revision"] < 0
                    or not isinstance(value.get("records"), list)
                ):
                    raise ValueError("Invalid stored calibration history")
                self.document = {
                    "revision": value["revision"],
                    "records": value["records"][:HISTORY],
                }
        except Exception as error:
            self.error = f"Stored calibration history could not be loaded; it has not been overwritten: {error}"

    def sensors(self):
        """Each feed probe's sensor as the room's setup names it now, or None."""
        state = self.hass.states.get(f"sensor.{DOMAIN}_{self.prefix}engine_config")
        attributes = state.attributes if state else {}
        return {
            probe: attributes.get(key) or None for probe, (_kind, key) in PROBES.items()
        }

    def response(self):
        return {
            "schema_version": 1,
            "room_id": self.room_id,
            **deepcopy(self.document),
            "sensors": self.sensors(),
            "error": self.error,
            "max_records": HISTORY,
        }

    async def record(self, data):
        async with self._lock:
            if self.error:
                raise ValueError(self.error)
            if data.get("expected_revision") != self.document["revision"]:
                raise ValueError(
                    "Calibration history changed elsewhere. Reload before saving."
                )
            probe = data.get("probe")
            if probe not in PROBES:
                raise ValueError("Calibrate the feed-water pH or EC probe")
            note = (data.get("note") or "").strip()
            if len(note) > 200:
                raise ValueError("A note holds at most 200 characters")
            kind = PROBES[probe][0]
            record = {
                "id": uuid4().hex,
                "probe": probe,
                "kind": kind,
                "entity_id": self.sensors()[probe],
                "at": datetime.now(timezone.utc).isoformat(),
                **evaluate(kind, data.get("points")),
                "note": note,
            }
            document = {
                "revision": self.document["revision"] + 1,
                "records": [record, *self.document["records"]][:HISTORY],
            }
            await self._store.async_save(document)
            self.document = document
            return self.response()


def journal_record(hass, room_id, response, call):
    """A check was recorded -> `calibration.captured`. It only judges the probe: nothing is applied to it."""
    try:
        record = response["records"][0]
        who = attribution(hass, call)
        note(
            hass,
            room_id,
            "calibration.captured",
            actor=who["actor"],
            user_id=who["user_id"],
            client=who["client"],
            data={
                "applied": False,
                "record_id": record["id"],
                "probe": record["probe"],
                "kind": record["kind"],
                "entity_id": record["entity_id"],
                "slope_pct": record["slope_pct"],
                "offset": record["offset"],
                "verdict": record["verdict"],
                "points": record["points"],
                "note": record["note"],
            },
        )
    except Exception as err:  # the record stands whatever the journal does
        _LOGGER.debug("Calibration journal event not recorded: %s", err)


def resolve_calibration(hass, room_id):
    if not isinstance(room_id, str) or not room_id.startswith("room:"):
        raise ValueError("A canonical room_id is required")
    matches = [
        manager
        for manager in hass.data.get(DOMAIN, {}).get("_calibration", {}).values()
        if manager.room_id == room_id
    ]
    if len(matches) != 1:
        raise ValueError("Calibration room is unknown or ambiguous")
    return matches[0]


async def async_setup_calibration(hass, entry):
    import voluptuous as vol
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError

    manager = CalibrationStore(hass, entry)
    await manager.async_init()
    hass.data.setdefault(DOMAIN, {}).setdefault("_calibration", {})[
        entry.entry_id
    ] = manager

    async def handle(call):
        if call.service != "calibration_get":
            await async_require_admin(hass, call, f"{DOMAIN}.{call.service}")
        try:
            target = resolve_calibration(hass, call.data["room_id"])
            if call.service == "calibration_get":
                return target.response()
            response = await target.record(call.data)
            journal_record(hass, call.data["room_id"], response, call)
            return response
        except (ValueError, KeyError, OSError) as error:
            raise HomeAssistantError(str(error)) from error

    for service in SERVICES:
        schema = {vol.Required("room_id"): str}
        if service == "calibration_record":
            schema[vol.Required("expected_revision")] = vol.All(int, vol.Range(min=0))
            schema[vol.Required("probe")] = str
            schema[vol.Required("points")] = list
            schema[vol.Optional("note")] = str
        hass.services.async_register(
            DOMAIN,
            service,
            handle,
            schema=vol.Schema(schema),
            supports_response=SupportsResponse.ONLY,
        )


async def async_unload_calibration(hass, entry):
    managers = hass.data.get(DOMAIN, {}).get("_calibration", {})
    managers.pop(entry.entry_id, None)
    if not managers:
        for service in SERVICES:
            hass.services.async_remove(DOMAIN, service)
