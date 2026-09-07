"""Bounded, room-local run metadata. No controller/entity/actuator writes."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import date, datetime, timezone
import math
import re
from uuid import uuid4
from zoneinfo import ZoneInfo

from .const import DOMAIN, MAX_ZONES
from .room import room_prefix
from .strategy_model import MODE_KEYS, PARAMETERS as STRATEGY_PARAMETERS

MAX_RUNS = 100
PARAMETERS = set(STRATEGY_PARAMETERS)


def bounded_text(value, label, maximum=80):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{label} must contain 1–{maximum} characters")
    return value.strip()


def calendar_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Use calendar dates in YYYY-MM-DD format")
    return date.fromisoformat(value)


def dates(start, end):
    first = calendar_date(start)
    last = calendar_date(end) if end else None
    if last and not 0 <= (last - first).days <= 365:
        raise ValueError("A run must span 1–366 inclusive calendar days")
    return first, last


def number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Reference values must be numeric")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError("Reference value is outside its supported range")
    return value


def plant_number(value):
    result = number(value, 1, 1000)
    if int(result) != result:
        raise ValueError("Plant count must be a whole number")
    return int(result)


def normalize_record(raw, room_id):
    if not isinstance(raw, dict) or raw.get("room_id") != room_id:
        raise ValueError("Run belongs to another room")
    identifier = bounded_text(raw.get("id"), "Run ID", 64)
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", identifier):
        raise ValueError("Invalid run ID")
    dates(raw.get("start_date"), raw.get("end_date"))
    tz = bounded_text(raw.get("time_zone"), "Time zone", 80)
    ZoneInfo(tz)
    captured = datetime.fromisoformat(
        str(raw.get("captured_at", "")).replace("Z", "+00:00")
    )
    if captured.tzinfo is None:
        raise ValueError("Reference timestamp needs a time zone")
    archived = raw.get("archived", False)
    if not isinstance(archived, bool):
        raise ValueError("Archived must be true or false")
    zones = raw.get("zones")
    if not isinstance(zones, list) or not 1 <= len(zones) <= MAX_ZONES:
        raise ValueError("A run requires 1–24 registered zones")
    clean, seen = [], set()
    for zone in zones:
        if not isinstance(zone, dict):
            raise ValueError("Invalid run zone")
        zid = zone.get("zone_id")
        if (
            isinstance(zid, bool)
            or not isinstance(zid, int)
            or not 1 <= zid <= MAX_ZONES
            or zid in seen
        ):
            raise ValueError("Run zone IDs must be unique and between 1 and 24")
        seen.add(zid)
        sensors = {}
        for metric in ("vwc", "ec"):
            sensor = zone.get(metric + "_sensor")
            if sensor is not None and (
                not isinstance(sensor, str)
                or len(sensor) > 200
                or not re.fullmatch(r"sensor\.[a-z0-9_]+", sensor)
            ):
                raise ValueError("Invalid historical sensor ID")
            sensors[metric + "_sensor"] = sensor
        params = zone.get("parameters", {})
        if not isinstance(params, dict) or not params.keys() <= PARAMETERS:
            raise ValueError("Unsupported reference target")
        clean.append(
            {
                "zone_id": zid,
                "name": bounded_text(zone.get("name"), "Zone name"),
                **sensors,
                "plant_count": (
                    None
                    if zone.get("plant_count") is None
                    else plant_number(zone["plant_count"])
                ),
                "reference_source": bounded_text(
                    zone.get("reference_source", raw.get("reference_source")),
                    "Zone reference source",
                    120,
                ),
                "parameters": {
                    key: number(value, 0, 10000 if key == "max_daily_volume" else 1440)
                    for key, value in params.items()
                },
            }
        )
    lights = raw.get("lights", {})
    if not isinstance(lights, dict):
        raise ValueError("Invalid reference lights schedule")
    return {
        "id": identifier,
        "room_id": room_id,
        "name": bounded_text(raw.get("name"), "Run name"),
        "start_date": raw["start_date"],
        "end_date": raw.get("end_date") or None,
        "time_zone": tz,
        "archived": archived,
        "captured_at": captured.astimezone(timezone.utc).isoformat(),
        "reference_source": bounded_text(
            raw.get("reference_source"), "Reference source", 120
        ),
        "lights": {
            key: None if lights.get(key) is None else number(lights[key], 0, 23.999)
            for key in ("on", "off")
        },
        "zones": clean,
    }


class RunStore:
    def __init__(self, hass, entry, store=None):
        self.hass, self.entry = hass, entry
        self.prefix = room_prefix(entry)
        self.room_id = "room:" + self.prefix
        self.time_zone = getattr(getattr(hass, "config", None), "time_zone", "UTC")
        self._store = store
        self._lock = asyncio.Lock()
        self.document = {"revision": 0, "runs": []}
        self.error = None

    async def async_init(self):
        try:
            if self._store is None:
                from homeassistant.helpers.storage import Store

                self._store = Store(
                    self.hass, 1, f"{DOMAIN}.runs.{self.entry.entry_id}"
                )
            value = await self._store.async_load()
            if value is not None:
                if (
                    not isinstance(value, dict)
                    or type(value.get("revision")) is not int
                    or value["revision"] < 0
                ):
                    raise ValueError("Invalid stored revision")
                records = self._records(value.get("runs"))
                self.document = {"revision": value["revision"], "runs": records}
        except Exception as error:
            self.error = f"Stored run metadata could not be loaded; it has not been overwritten: {error}"

    def _records(self, values):
        if not isinstance(values, list) or len(values) > MAX_RUNS:
            raise ValueError("At most 100 runs can be stored per room")
        records = [normalize_record(value, self.room_id) for value in values]
        if len({record["id"] for record in records}) != len(records):
            raise ValueError("Duplicate run IDs")
        return records

    def response(self):
        return {
            "schema_version": 1,
            "room_id": self.room_id,
            "time_zone": self.time_zone,
            **deepcopy(self.document),
            "error": self.error,
            "max_runs": MAX_RUNS,
        }

    def capture(self, record):
        manager = (
            self.hass.data.get(DOMAIN, {}).get("_strategy", {}).get(self.entry.entry_id)
        )
        if manager is None:
            raise ValueError(
                "Room strategy metadata is unavailable; reload the integration"
            )
        response = manager.response()
        catalog = response["catalog"]
        active = []
        status = response.get("status")
        reference_source = "Current manual settings at registration"
        if status in ("active", "disarming", "error") or response.get("active", {}).get(
            "zones"
        ):
            reference_source = (
                "Stored manual fallback; active plan not verified at registration"
            )
            snapshot = self.hass.states.get(manager.entity_id)
            attrs = snapshot.attributes if snapshot else {}
            now = datetime.now(timezone.utc).timestamp()
            try:
                updated = datetime.fromisoformat(attrs["updated_at"]).timestamp()
                expires = datetime.fromisoformat(attrs["valid_until"]).timestamp()
                if (
                    status in ("active", "disarming")
                    and not response.get("error")
                    and attrs.get("room_id") == self.room_id
                    and attrs.get("snapshot_version") == 1
                    and attrs.get("revision") == response.get("revision")
                    and attrs.get("enabled") is True
                    and not attrs.get("error")
                    and now - 180 <= updated <= now + 60
                    and now < expires <= now + 600
                ):
                    active = attrs.get("zones", [])
                    if not isinstance(active, list):
                        active = []
                    reference_source = "Active-plan targets where valid; stored manual fallback otherwise"
            except (KeyError, ValueError, TypeError):
                pass
        zone_ids = manager.zone_ids()
        config = manager._config()
        zones = []
        for zid in zone_ids:
            params = {
                key: row["value"]
                for key, row in catalog.get(str(zid), catalog.get(zid, {})).items()
                if key in PARAMETERS and row.get("value") is not None
            }
            # Match the controller's zone-mode -> growth-stage -> Generative fallback.
            mode_state = manager._state(f"zone_{zid}_steering_mode", "select")
            if mode_state is None or mode_state.state in ("unknown", "unavailable", ""):
                mode_state = manager._state("growth_stage", "select")
            mode = (
                mode_state.state
                if mode_state and mode_state.state not in ("unknown", "unavailable", "")
                else "Generative"
            )
            family = 0 if str(mode).lower().startswith("veg") else 1
            for key, native in MODE_KEYS.items():
                if key not in PARAMETERS:
                    continue
                params.pop(key, None)
                state = manager._native_number(zid, native[family])
                try:
                    if state is not None:
                        params[key] = number(float(state.state), 0, 1440)
                except (ValueError, TypeError):
                    pass
            planned = next(
                (
                    z
                    for z in active
                    if isinstance(z, dict)
                    and z.get("zone_id") == zid
                    and z.get("status") == "active"
                ),
                None,
            )
            if planned:
                params.update(
                    {
                        key: value
                        for key, value in planned.get("parameters", {}).items()
                        if key in PARAMETERS
                    }
                )
            sensors = {}
            for metric in ("vwc", "ec"):
                candidates = [
                    f"sensor.{DOMAIN}_{self.prefix}{metric}_zone_{zid}",
                    f"sensor.{DOMAIN}_{self.prefix}zone_{zid}_{metric}",
                ]
                sensors[metric + "_sensor"] = next(
                    (
                        eid
                        for eid in candidates
                        if self.hass.states.get(eid) is not None
                    ),
                    None,
                )
            entry_zone = (config.get("zones") or {}).get(str(zid), {})
            state = manager._native_number(zid, "plant_count")
            try:
                plant_count = float(state.state) if state else None
                if plant_count is not None:
                    plant_count = plant_number(plant_count)
            except (ValueError, TypeError):
                plant_count = None
            zones.append(
                {
                    "zone_id": zid,
                    "name": entry_zone.get("name") or f"Zone {zid}",
                    **sensors,
                    "plant_count": plant_count,
                    "parameters": params,
                    "reference_source": (
                        "Verified active-plan reference at registration"
                        if planned
                        else (
                            "Stored manual fallback at registration"
                            if status != "draft"
                            else "Current manual settings at registration"
                        )
                    ),
                }
            )
        lights = {}
        for key in ("on", "off"):
            state = manager._state(f"lights_{key}_hour", "number")
            try:
                lights[key] = number(float(state.state), 0, 23.999) if state else None
            except (ValueError, TypeError):
                lights[key] = None
        return normalize_record(
            {
                **record,
                "id": uuid4().hex,
                "room_id": self.room_id,
                "time_zone": self.time_zone,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "reference_source": reference_source,
                "zones": zones,
                "lights": lights,
                "archived": False,
            },
            self.room_id,
        )

    async def mutate(self, action, data):
        async with self._lock:
            if self.error:
                raise ValueError(self.error)
            if (
                type(data.get("expected_revision")) is not int
                or data["expected_revision"] != self.document["revision"]
            ):
                raise ValueError("Runs changed elsewhere. Reload before saving.")
            values = deepcopy(self.document["runs"])
            if action == "runs_save":
                raw = data.get("record")
                if not isinstance(raw, dict):
                    raise ValueError("A run record is required")
                first, last = dates(raw.get("start_date"), raw.get("end_date"))
                today = datetime.now(ZoneInfo(self.time_zone)).date()
                if not last and (today - first).days > 365:
                    raise ValueError("Close runs older than 366 days with an end date")
                existing = next((r for r in values if r["id"] == raw.get("id")), None)
                if raw.get("id") and existing is None:
                    raise ValueError("Run does not belong to this room")
                if existing:
                    # Renaming/backdating never silently refreshes historical reference metadata.
                    existing.update(
                        name=bounded_text(raw.get("name"), "Run name"),
                        start_date=raw["start_date"],
                        end_date=raw.get("end_date") or None,
                    )
                else:
                    values.append(self.capture(raw))
            elif action == "runs_archive":
                record = next((r for r in values if r["id"] == data.get("id")), None)
                if record is None or type(data.get("archived")) is not bool:
                    raise ValueError(
                        "Known run ID and archived true/false are required"
                    )
                record["archived"] = data["archived"]
            elif action == "runs_import":
                incoming = self._records(data.get("runs"))
                allowed = {
                    z[key]
                    for r in values
                    for z in r["zones"]
                    for key in ("vwc_sensor", "ec_sensor")
                    if z[key]
                }
                for record in incoming:
                    first, last = dates(record["start_date"], record["end_date"])
                    if (
                        not last
                        and (datetime.now(ZoneInfo(self.time_zone)).date() - first).days
                        > 365
                    ):
                        raise ValueError(
                            "Close imported runs older than 366 days with an end date"
                        )
                    for zone in record["zones"]:
                        for metric in ("vwc", "ec"):
                            eid = zone[metric + "_sensor"]
                            patterns = {
                                f"sensor.{DOMAIN}_{self.prefix}{metric}_zone_{zone['zone_id']}",
                                f"sensor.{DOMAIN}_{self.prefix}zone_{zone['zone_id']}_{metric}",
                            }
                            if eid and eid not in allowed | patterns:
                                raise ValueError(
                                    "Imported sensor is not registered to this room"
                                )
                    values = [r for r in values if r["id"] != record["id"]] + [record]
            else:
                raise ValueError("Unsupported run operation")
            normalized = self._records(values)
            next_document = {
                "revision": self.document["revision"] + 1,
                "runs": normalized,
            }
            await self._store.async_save(next_document)
            self.document = next_document
            return self.response()
