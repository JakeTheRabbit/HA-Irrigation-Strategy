"""Optional room-scoped InfluxDB history. Only bounded, generated read queries.

Connection secrets stay in a HA Store, never returned to the dashboard or descriptor.
Default source is recorder. A saved connection is tested before it replaces the old one.
"""

from __future__ import annotations

import asyncio
import csv
from datetime import datetime, timedelta, timezone
import io
import json
import math
from urllib.parse import urlsplit

import aiohttp

from .admin import async_require_admin
from .api_v2 import StaleRevision
from .const import DOMAIN
from .room import room_prefix

SERVICES = ("history_connection_get", "history_connection_save", "history_long")
MAX_POINTS = 1000
MAX_BYTES = 2_000_000


def connection(raw, previous=None):
    """Validate identifiers; query text and arbitrary query endpoints are never accepted."""
    if not isinstance(raw, dict):
        raise ValueError("History connection must be an object")
    previous = previous or {}
    result = {
        key: raw.get(key, previous.get(key, default))
        for key, default in {
            "source": "recorder",
            "url": "",
            "version": "1",
            "database": "homeassistant",
            "bucket": "",
            "org": "",
            "username": "",
            "password": "",
            "token": "",
            "measurement": "",
            "field": "value",
            "tag": "entity_id",
            "domain_tag": "domain",
            "full_entity_id": False,
        }.items()
    }
    if result["source"] not in ("recorder", "influxdb") or result["version"] not in (
        "1",
        "2",
    ):
        raise ValueError("Choose recorder or InfluxDB and version 1 or 2")
    for key, value in result.items():
        if key == "full_entity_id":
            if type(value) is not bool:
                raise ValueError("Entity tag format must be a boolean")
        elif (
            not isinstance(value, str)
            or len(value) > 2048
            or any(ord(c) < 32 for c in value)
        ):
            raise ValueError("Invalid connection field")
    if result["url"] or result["source"] == "influxdb":
        url = urlsplit(result["url"])
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError(
                "Use an HTTP or HTTPS InfluxDB URL without embedded credentials"
            )
    if result["source"] == "influxdb":
        if not result["field"] or not result["tag"]:
            raise ValueError("A field and entity tag are required")
        if (
            not result["database"]
            if result["version"] == "1"
            else not (result["bucket"] and result["org"] and result["token"])
        ):
            raise ValueError("Enter the database, or bucket, organisation and token")
    result["url"] = result["url"].rstrip("/")
    return result


def window(start, end):
    try:
        first, last = (
            datetime.fromisoformat(v.replace("Z", "+00:00")) for v in (start, end)
        )
        if first.tzinfo is None or last.tzinfo is None:
            raise ValueError
        first, last = first.astimezone(timezone.utc), last.astimezone(timezone.utc)
        span = (last - first).total_seconds()
        if not 0 < span <= 366 * 86400 or last > datetime.now(timezone.utc):
            raise ValueError
        return first, last, max(1, math.ceil(span / (MAX_POINTS - 1)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError(
            "History requires an elapsed range of at most 366 days"
        ) from None


def quote(value, mark='"'):
    return mark + value.replace("\\", "\\\\").replace(mark, "\\" + mark) + mark


def queries(config, entity, measurement, first, last, seconds):
    tag_value = entity if config["full_entity_id"] else entity.split(".", 1)[1]
    domain_tag = config.get("domain_tag", "domain")
    if config["version"] == "1":
        field = quote(config["field"])
        return (
            f"SELECT mean({field}) AS mean,min({field}) AS min,max({field}) AS max FROM {quote(measurement)} "
            f"WHERE {quote(config['tag'])}={quote(tag_value, chr(39))} "
            + (f"AND {quote(domain_tag)}='sensor' " if domain_tag else "")
            + f"AND time >= {quote(first.isoformat(), chr(39))} AND time < {quote(last.isoformat(), chr(39))} "
            f"GROUP BY time({seconds}s) fill(none) LIMIT {MAX_POINTS}"
        )
    # JSON string escaping is also Flux string escaping. No operator input is query syntax.
    q = json.dumps
    base = (
        f"from(bucket: {q(config['bucket'])}) |> range(start: time(v: {q(first.isoformat())}), stop: time(v: {q(last.isoformat())})) "
        f"|> filter(fn: (r) => r._measurement == {q(measurement)} and r._field == {q(config['field'])} and r[{q(config['tag'])}] == {q(tag_value)}"
        + (f' and r[{q(domain_tag)}] == "sensor"' if domain_tag else "")
        + ") "
    )
    return "\n".join(
        base
        + f'|> aggregateWindow(every: {seconds}s, fn: {fn}, createEmpty: false, timeSrc: "_start") |> limit(n: {MAX_POINTS}) |> yield(name: "{fn}")'
        for fn in ("mean", "min", "max")
    )


def parse_values(body, version):
    out = {}
    if version == "1":
        doc = json.loads(body)
        if doc.get("error") or any(r.get("error") for r in doc.get("results", [])):
            raise ValueError("InfluxDB rejected the read query")
        for result in doc.get("results", []):
            for series in result.get("series", []):
                for values in series.get("values", []):
                    row = dict(zip(series["columns"], values))
                    out[
                        datetime.fromisoformat(
                            row["time"].replace("Z", "+00:00")
                        ).timestamp()
                        * 1000
                    ] = {k: row.get(k) for k in ("mean", "min", "max")}
    else:
        headers = None
        for row in csv.reader(io.StringIO(body)):
            if not row or row[0].startswith("#"):
                continue
            if "_time" in row and "_value" in row:
                headers = row
                continue
            if headers:
                values = dict(zip(headers, row))
                if values.get("_value") and values.get("_time"):
                    stamp = (
                        datetime.fromisoformat(
                            values["_time"].replace("Z", "+00:00")
                        ).timestamp()
                        * 1000
                    )
                    out.setdefault(stamp, {})[values.get("result", "mean")] = float(
                        values["_value"]
                    )
    rows = []
    for stamp, values in sorted(out.items())[:MAX_POINTS]:
        value = values.get("mean")
        if isinstance(value, (int, float)) and math.isfinite(value):
            rows.append(
                {
                    "time": stamp,
                    "value": value,
                    "min": values.get("min"),
                    "max": values.get("max"),
                }
            )
    return rows


class LongHistory:
    def __init__(self, hass, entry):
        from homeassistant.helpers.storage import Store

        self.hass, self.entry = hass, entry
        self.room_id = "room:" + room_prefix(entry)
        self.store = Store(hass, 1, f"{DOMAIN}.history_connection.{entry.entry_id}")
        self.config = connection({})
        self.revision = 0
        self.lock = asyncio.Lock()

    def public(self):
        return {
            "room_id": self.room_id,
            "revision": self.revision,
            "connection": {
                k: v for k, v in self.config.items() if k not in ("password", "token")
            },
            "has_password": bool(self.config["password"]),
            "has_token": bool(self.config["token"]),
        }

    def allowed(self):
        from homeassistant.helpers import entity_registry as er

        registry = er.async_get(self.hass)
        allowed = {
            e.entity_id
            for e in er.async_entries_for_config_entry(registry, self.entry.entry_id)
            if e.domain == "sensor"
        }
        cfg = {**self.entry.data, **self.entry.options}
        for zone in cfg.get("zones", {}).values():
            for key, value in zone.items():
                if (
                    key.endswith(("_sensor", "_front", "_back"))
                    and isinstance(value, str)
                    and value.startswith("sensor.")
                ):
                    allowed.add(value)
                elif key.endswith("_sensors") and isinstance(value, list):
                    allowed.update(
                        v
                        for v in value
                        if isinstance(v, str) and v.startswith("sensor.")
                    )
        allowed.update(
            v
            for v in cfg.get("hardware", {}).values()
            if isinstance(v, str) and v.startswith("sensor.")
        )
        return allowed

    async def query(self, config, ids, start, end):
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        first, last, seconds = window(start, end)
        session = async_get_clientsession(self.hass)
        series = []
        async with asyncio.timeout(8):
            for entity in ids:
                state = self.hass.states.get(entity)
                measurement = config["measurement"] or (
                    state.attributes.get("unit_of_measurement") if state else None
                )
                if not measurement:
                    measurement = entity
                query = queries(config, entity, str(measurement), first, last, seconds)
                if config["version"] == "1":
                    request = session.get(
                        config["url"] + "/query",
                        params={"db": config["database"], "q": query},
                        auth=(
                            aiohttp.BasicAuth(config["username"], config["password"])
                            if config["username"]
                            else None
                        ),
                        allow_redirects=False,
                    )
                else:
                    request = session.post(
                        config["url"] + "/api/v2/query",
                        params={"org": config["org"]},
                        data=query,
                        headers={
                            "Authorization": "Token " + config["token"],
                            "Content-Type": "application/vnd.flux",
                            "Accept": "text/csv",
                        },
                        allow_redirects=False,
                    )
                async with request as response:
                    if response.status != 200:
                        raise ValueError("InfluxDB connection or read query failed")
                    body = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        body.extend(chunk)
                        if len(body) > MAX_BYTES:
                            raise ValueError(
                                "InfluxDB response exceeds the history size limit"
                            )
                    points = parse_values(body.decode("utf-8"), config["version"])
                series.append(
                    {
                        "entityId": entity,
                        "points": [
                            p
                            for p in points
                            if first.timestamp() * 1000
                            <= p["time"]
                            < last.timestamp() * 1000
                        ],
                    }
                )
        return {
            "start": first.isoformat(),
            "end": last.isoformat(),
            "series": series,
            "warnings": [
                "InfluxDB: downsampled mean with min/max, at most 1000 points per sensor."
            ],
        }


async def async_setup_long_history(hass, entry):
    import voluptuous as vol
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError

    from .api_v2 import fields, wrap

    manager = LongHistory(hass, entry)
    stored = await manager.store.async_load()
    if isinstance(stored, dict):
        try:
            manager.config = connection(stored.get("connection", {}))
            manager.revision = max(0, int(stored.get("revision", 0)))
        except (ValueError, TypeError, OverflowError):
            pass  # Corrupt optional configuration cannot stop irrigation or old installations.
    hass.data.setdefault(DOMAIN, {}).setdefault("_long_history", {})[
        entry.entry_id
    ] = manager
    if hass.services.has_service(DOMAIN, SERVICES[0]):
        return

    async def handle(call):
        await async_require_admin(
            hass, call, f"{DOMAIN}.{call.service}", allow_no_user=False
        )
        matches = [
            m
            for m in hass.data[DOMAIN]["_long_history"].values()
            if m.room_id == call.data["room_id"]
        ]
        if len(matches) != 1:
            raise HomeAssistantError("History room is unknown or ambiguous")
        target = matches[0]
        if target.lock.locked():
            raise HomeAssistantError("Another history request is in progress")
        try:
            async with target.lock:
                if call.service == "history_connection_get":
                    return target.public()
                if call.service == "history_connection_save":
                    if call.data["expected_revision"] != target.revision:
                        raise StaleRevision(
                            "History connection changed elsewhere; reload",
                            target.revision,
                        )
                    candidate = connection(call.data["connection"], target.config)
                    if candidate["source"] == "influxdb":
                        probe = sorted(target.allowed())[:1]
                        if not probe:
                            raise ValueError(
                                "Map a room sensor before testing InfluxDB"
                            )
                        now = datetime.now(timezone.utc)
                        await target.query(
                            candidate,
                            probe,
                            (now - timedelta(hours=1)).isoformat(),
                            now.isoformat(),
                        )
                    await target.store.async_save(
                        {"revision": target.revision + 1, "connection": candidate}
                    )
                    target.config, target.revision = candidate, target.revision + 1
                    return target.public()
                ids = list(dict.fromkeys(call.data["entity_ids"]))
                if not 1 <= len(ids) <= 4 or any(
                    e not in target.allowed() for e in ids
                ):
                    raise ValueError("Select 1-4 sensors already mapped to this room")
                if target.config["source"] != "influxdb":
                    raise ValueError("InfluxDB history is not enabled")
                return await target.query(
                    target.config, ids, call.data["start"], call.data["end"]
                )
        except (
            ValueError,
            TypeError,
            KeyError,
            OSError,
            aiohttp.ClientError,
            TimeoutError,
        ):
            # Never relay upstream error bodies/URLs: they may contain credentials.
            raise HomeAssistantError(
                "History connection or bounded read failed; check settings and retry"
            ) from None

    schemas = {
        "history_connection_get": {},
        "history_connection_save": {
            vol.Required("expected_revision"): vol.All(int, vol.Range(min=0)),
            vol.Required("connection"): dict,
        },
        "history_long": {
            vol.Required("entity_ids"): [str],
            vol.Required("start"): str,
            vol.Required("end"): str,
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


async def async_unload_long_history(hass, entry):
    managers = hass.data.get(DOMAIN, {}).get("_long_history", {})
    managers.pop(entry.entry_id, None)
    if not managers:
        for service in SERVICES:
            hass.services.async_remove(DOMAIN, service)
