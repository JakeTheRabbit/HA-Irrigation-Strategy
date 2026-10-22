"""Grow-day summaries per room: one record per zone and grow-day, kept for years so grows stay comparable after the
recorder has purged its readings. Read-only data: nothing here changes watering.

The controller app builds each zone's summary at lights-on for the grow-day that just ended (day_summary.py there)
while the room's Record grow days switch is on, and sends them with `grow_day_record`. `grow_days_get` reads them
(any signed-in user, like the run records). `grow_days_backfill` fills grow-days that have no summary from Home
Assistant's long-term statistics (hourly min/max/mean of the zone's moisture and EC sensors, and its water counter),
marked backfilled: dryback, shots and the probes behind the zone cannot be recovered that way.

Stored in its own Store (crop_steering.grow_days.<entry_id>), apart from the run records: a run is a date range over
these days. A record that does not pass on load is dropped with a warning; the rest load.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import date, datetime, timedelta
import logging
import math
import re

from .admin import async_require_admin
from .const import CONF_NUM_ZONES, DOMAIN, MAX_ZONES
from .room import room_prefix

_LOGGER = logging.getLogger(__name__)

SERVICES = ("grow_day_record", "grow_days_get", "grow_days_backfill")
MAX_DATES = 1100  # about three years of grow-days per room; the oldest dates go first
MAX_BATCH = MAX_ZONES * 14
MAX_PROBES = 32
SHOT_KINDS = ("ramp", "extra", "topup", "dilute", "rescue", "p3", "test", "other")
STATS = ("min", "max", "mean")


def _num(v, low=-1e6, high=1e6):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) and low <= v <= high else None


def _text(v, maximum):
    return v.strip()[:maximum] if isinstance(v, str) and v.strip() else None


def _stats(v, keys=STATS):
    if not isinstance(v, dict):
        return None
    out = {k: _num(v.get(k)) for k in keys}
    return out if any(x is not None for x in out.values()) else None


def _day(v):
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        raise ValueError("Use grow-day dates in YYYY-MM-DD format")
    date.fromisoformat(v)
    return v


def normalize_day(raw):
    """One zone's grow-day summary, rebuilt from the keys this version knows, every value bounded."""
    if not isinstance(raw, dict):
        raise ValueError("A grow-day summary must be an object")
    zone = raw.get("zone")
    if (
        isinstance(zone, bool)
        or not isinstance(zone, int)
        or not 1 <= zone <= MAX_ZONES
    ):
        raise ValueError("A grow-day summary needs a zone from 1 to 24")
    lights = raw.get("lights") if isinstance(raw.get("lights"), dict) else {}
    plateau = raw.get("plateau") if isinstance(raw.get("plateau"), dict) else None
    p0 = raw.get("p0") if isinstance(raw.get("p0"), dict) else None
    night = raw.get("night") if isinstance(raw.get("night"), dict) else None
    shots = raw.get("shots") if isinstance(raw.get("shots"), dict) else {}
    litres_by = (
        raw.get("shot_litres") if isinstance(raw.get("shot_litres"), dict) else {}
    )
    targets = raw.get("targets") if isinstance(raw.get("targets"), dict) else {}
    plants = _num(raw.get("plant_count"), 1, 1000)
    plan_day = raw.get("plan_day")
    probes = []
    for p in raw.get("probes") if isinstance(raw.get("probes"), list) else []:
        if not isinstance(p, dict) or p.get("kind") not in ("vwc", "ec"):
            continue
        pid = p.get("entity_id")
        if (
            not isinstance(pid, str)
            or not re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", pid)
            or len(pid) > 200
        ):
            continue
        probes.append(
            {
                "kind": p["kind"],
                "entity_id": pid,
                "name": _text(p.get("name"), 80),
                "unit": _text(p.get("unit"), 16),
                **{k: _num(p.get(k)) for k in ("peak", "trough", "mean")},
                "used_share": _num(p.get("used_share"), 0, 1),
            }
        )
        if len(probes) >= MAX_PROBES:
            break
    return {
        "date": _day(raw.get("date")),
        "zone": zone,
        "partial": raw.get("partial") is True,
        "backfilled": "partial" if raw.get("backfilled") else None,
        "samples": int(_num(raw.get("samples"), 0, 1e7) or 0),
        "began": _text(raw.get("began"), 32),
        "since": _text(raw.get("since"), 40),
        "plan_day": (
            plan_day
            if isinstance(plan_day, int)
            and not isinstance(plan_day, bool)
            and 0 <= plan_day <= 1000
            else None
        ),
        "lights": {k: _num(lights.get(k), 0, 24) for k in ("on", "off")},
        "mode": _text(raw.get("mode"), 24),
        "vwc": _stats(raw.get("vwc"), ("peak", "trough", "mean")),
        "ec": _stats(raw.get("ec")),
        "feed_ec": _stats(raw.get("feed_ec")),
        "feed_ph": _stats(raw.get("feed_ph")),
        "plateau": plateau
        and {
            "value": _num(plateau.get("value")),
            "how": _text(plateau.get("how"), 80),
            "shots": int(_num(plateau.get("shots"), 0, 1000) or 0),
        },
        "p0": p0 and _stats(p0, ("dryback_pct", "drop_pts", "landing")),
        "night": night
        and {
            "rate": _num(night.get("rate")),
            "shots": int(_num(night.get("shots"), 0, 1000) or 0),
        },
        "p1_stall": raw.get("p1_stall") is True,
        "shots": {
            k: int(_num(shots.get(k), 0, 10000) or 0)
            for k in SHOT_KINDS
            if shots.get(k)
        },
        "shot_litres": {
            k: _num(litres_by.get(k), 0, 1e5)
            for k in SHOT_KINDS
            if litres_by.get(k) is not None
        },
        "rescues": int(_num(raw.get("rescues"), 0, 10000) or 0),
        "litres": _num(raw.get("litres"), 0, 1e5),
        "plant_count": int(plants) if plants else None,
        "litres_per_plant": _num(raw.get("litres_per_plant"), 0, 1e4),
        "alerts": (
            [a[:16] for a in raw.get("alerts") or [] if isinstance(a, str)][:20]
            if isinstance(raw.get("alerts"), list)
            else []
        ),
        "targets": {
            k[:40]: _num(v)
            for k, v in list(targets.items())[:16]
            if isinstance(k, str) and _num(v) is not None
        },
        "probes": probes,
    }


class GrowDayStore:
    def __init__(self, hass, entry, store=None):
        self.hass, self.entry = hass, entry
        self.prefix = room_prefix(entry)
        self.room_id = "room:" + self.prefix
        self._store = store
        self._lock = asyncio.Lock()
        self.days = {}  # (date, zone) -> summary
        self.dropped = 0

    async def async_init(self):
        if self._store is None:
            from homeassistant.helpers.storage import Store

            self._store = Store(
                self.hass, 1, f"{DOMAIN}.grow_days.{self.entry.entry_id}"
            )
        value = await self._store.async_load()
        rows = value.get("days") if isinstance(value, dict) else None
        for raw in rows if isinstance(rows, list) else []:
            try:
                day = normalize_day(raw)
            except (ValueError, TypeError) as error:
                self.dropped += 1
                _LOGGER.warning(
                    "A stored grow-day summary of %s was left out: %s",
                    self.room_id,
                    error,
                )
                continue
            self.days[(day["date"], day["zone"])] = day

    def response(self, start=None, end=None, zone=None):
        rows = [
            deepcopy(d)
            for (day, z), d in sorted(self.days.items())
            if (start is None or day >= start)
            and (end is None or day <= end)
            and (zone is None or z == zone)
        ]
        dates = sorted({day for day, _z in self.days})
        return {
            "schema_version": 1,
            "room_id": self.room_id,
            "days": rows,
            "first": dates[0] if dates else None,
            "last": dates[-1] if dates else None,
            "count": len(self.days),
            "max_dates": MAX_DATES,
        }

    async def _commit(self, incoming, replace):
        """Store these summaries; a backfilled day never replaces a recorded one."""
        async with self._lock:
            taken = 0
            for day in incoming:
                key = (day["date"], day["zone"])
                if not replace and key in self.days:
                    continue
                self.days[key] = day
                taken += 1
            dates = sorted({d for d, _z in self.days})
            if len(dates) > MAX_DATES:
                keep = set(dates[-MAX_DATES:])
                self.days = {k: v for k, v in self.days.items() if k[0] in keep}
            if taken:
                await self._store.async_save(
                    {"days": [self.days[k] for k in sorted(self.days)]}
                )
            return taken

    async def record(self, rows):
        incoming, refused = [], []
        for raw in rows:
            try:
                incoming.append(normalize_day(raw))
            except (ValueError, TypeError) as error:
                refused.append(str(error))
        return {"taken": await self._commit(incoming, True), "refused": refused}

    async def backfill(self, start, end):
        """Fill grow-days without a summary from long-term statistics -> how many were added."""
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.statistics import (
            statistics_during_period,
        )
        from homeassistant.util import dt as dt_util

        first, last = date.fromisoformat(_day(start)), date.fromisoformat(_day(end))
        if not 0 <= (last - first).days <= 400:
            raise ValueError("Backfill 1 to 401 grow-days at a time")
        config = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        zones = int(config.get(CONF_NUM_ZONES) or 1)
        on = self.hass.states.get(f"number.{DOMAIN}_{self.prefix}lights_on_hour")
        try:
            on_hour = float(on.state) if on else 0.0
        except ValueError:
            on_hour = 0.0
        ids = {}
        for z in range(1, zones + 1):
            for metric in ("vwc", "ec"):
                for eid in (
                    f"sensor.{DOMAIN}_{self.prefix}{metric}_zone_{z}",
                    f"sensor.{DOMAIN}_{self.prefix}zone_{z}_{metric}",
                ):
                    if self.hass.states.get(eid) is not None:
                        ids[eid] = (z, metric)
                        break
            ids[f"sensor.{DOMAIN}_{self.prefix}zone_{z}_daily_water_usage"] = (
                z,
                "water",
            )
        tz = dt_util.get_default_time_zone()
        begin = datetime.combine(first, datetime.min.time(), tz) + timedelta(
            hours=on_hour
        )
        finish = datetime.combine(
            last + timedelta(days=1), datetime.min.time(), tz
        ) + timedelta(hours=on_hour)
        stats = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            begin,
            finish,
            set(ids),
            "hour",
            None,
            {"min", "max", "mean"},
        )
        acc = {}
        for eid, rows in (stats or {}).items():
            z, metric = ids[eid]
            for row in rows:
                at = row.get("start")
                at = (
                    dt_util.utc_from_timestamp(at)
                    if isinstance(at, (int, float))
                    else at
                )
                local = dt_util.as_local(at) - timedelta(hours=on_hour)
                key = (local.date().isoformat(), z)
                bucket = acc.setdefault(key, {}).setdefault(
                    metric, {"min": [], "max": [], "mean": []}
                )
                for k in STATS:
                    if _num(row.get(k)) is not None:
                        bucket[k].append(row[k])
        incoming = []
        for (day, z), metrics in sorted(acc.items()):
            if not first.isoformat() <= day <= last.isoformat():
                continue

            def band(m, keys=STATS):
                b = metrics.get(m)
                if not b or not b["mean"]:
                    return None
                vals = (
                    min(b["min"] or b["mean"]),
                    max(b["max"] or b["mean"]),
                    sum(b["mean"]) / len(b["mean"]),
                )
                return dict(zip(keys, (round(v, 3) for v in vals)))

            water = metrics.get("water")
            incoming.append(
                normalize_day(
                    {
                        "date": day,
                        "zone": z,
                        "partial": True,
                        "backfilled": True,
                        "vwc": band("vwc", ("trough", "peak", "mean")),
                        "ec": band("ec"),
                        "litres": (
                            round(max(water["max"]), 3)
                            if water and water["max"]
                            else None
                        ),
                    }
                )
            )
        return await self._commit(incoming, False)


def resolve_days(hass, room_id):
    if not isinstance(room_id, str) or not room_id.startswith("room:"):
        raise ValueError("A canonical room_id is required")
    matches = [
        m
        for m in hass.data.get(DOMAIN, {}).get("_grow_days", {}).values()
        if m.room_id == room_id
    ]
    if len(matches) != 1:
        raise ValueError("Grow-day room is unknown or ambiguous")
    return matches[0]


async def async_setup_grow_days(hass, entry):
    import voluptuous as vol
    from .api_v2 import fields, wrap
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError

    manager = GrowDayStore(hass, entry)
    await manager.async_init()
    hass.data.setdefault(DOMAIN, {}).setdefault("_grow_days", {})[
        entry.entry_id
    ] = manager
    if hass.services.has_service(DOMAIN, SERVICES[0]):
        return

    async def handle(call):
        # Reading is open, as run records are; recording and backfilling need an administrator (or no user:
        # the controller app and automations).
        if call.service != "grow_days_get":
            await async_require_admin(hass, call, f"{DOMAIN}.{call.service}")
        try:
            target = resolve_days(hass, call.data["room_id"])
            if call.service == "grow_day_record":
                response = await target.record(call.data["days"])
                runs = (
                    hass.data.get(DOMAIN, {})
                    .get("_runs", {})
                    .get(target.entry.entry_id)
                )
                if runs is not None:
                    try:
                        await runs.refresh_probes(call.data["days"])
                    except OSError:
                        _LOGGER.warning(
                            "Grow-day readings saved; optional run probe snapshots could not be refreshed"
                        )
                return response
            if call.service == "grow_days_backfill":
                added = await target.backfill(call.data["start"], call.data["end"])
                return {
                    **target.response(call.data["start"], call.data["end"]),
                    "added": added,
                }
            for key in ("start", "end"):
                if call.data.get(key) is not None:
                    _day(call.data[key])
            return target.response(
                call.data.get("start"), call.data.get("end"), call.data.get("zone")
            )
        except (ValueError, KeyError, OSError) as error:
            raise HomeAssistantError(str(error)) from error

    schemas = {
        "grow_day_record": {
            vol.Required("days"): vol.All(list, vol.Length(max=MAX_BATCH))
        },
        "grow_days_get": {
            vol.Optional("start"): str,
            vol.Optional("end"): str,
            vol.Optional("zone"): vol.All(int, vol.Range(min=1, max=MAX_ZONES)),
        },
        "grow_days_backfill": {vol.Required("start"): str, vol.Required("end"): str},
    }
    for service in SERVICES:
        hass.services.async_register(
            DOMAIN,
            service,
            wrap(handle),
            schema=vol.Schema(
                fields({vol.Required("room_id"): str, **schemas[service]})
            ),
            # The controller app sends grow_day_record over REST, asking for the answer.
            supports_response=(
                SupportsResponse.OPTIONAL
                if service == "grow_day_record"
                else SupportsResponse.ONLY
            ),
        )


async def async_unload_grow_days(hass, entry):
    managers = hass.data.get(DOMAIN, {}).get("_grow_days", {})
    managers.pop(entry.entry_id, None)
    if not managers:
        for service in SERVICES:
            hass.services.async_remove(DOMAIN, service)
