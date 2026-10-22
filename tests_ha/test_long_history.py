"""Optional Influx history: actual HA services, old installations and secret isolation."""

from unittest.mock import AsyncMock

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, _upgrade

from custom_components.crop_steering.long_history import connection, parse_values, queries, window


async def call(hass, user, service, room="room:tent_", **data):
    return await hass.services.async_call("crop_steering", service, {"room_id": room, **data},
        blocking=True, return_response=True, context=Context(user_id=user.id) if user else Context())


async def test_disabled_defaults_and_credentials_never_returned(hass, hass_admin_user, monkeypatch):
    entry = await _install(hass)
    initial = await call(hass, hass_admin_user, "history_connection_get")
    assert initial["connection"]["source"] == "recorder"
    manager = hass.data["crop_steering"]["_long_history"][entry.entry_id]
    query = AsyncMock(return_value={"series": []})
    monkeypatch.setattr(manager, "query", query)
    cfg = {"source": "influxdb", "url": "http://influx.example:8086", "username": "reader", "password": "never-return-me"}
    saved = await call(hass, hass_admin_user, "history_connection_save", expected_revision=0, connection=cfg)
    assert "password" not in saved["connection"] and "token" not in saved["connection"]
    assert saved["has_password"] and query.await_count == 1
    with pytest.raises(HomeAssistantError):
        await call(hass, hass_admin_user, "history_connection_save", expected_revision=0, connection=cfg)
    with pytest.raises(HomeAssistantError):
        await call(hass, hass_admin_user, "history_long", entity_ids=["sensor.other_room"], start="2026-01-01T00:00:00Z", end="2026-01-02T00:00:00Z")
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    restored = await call(hass, hass_admin_user, "history_connection_get")
    assert restored == saved
    with pytest.raises(HomeAssistantError, match="administrator"):
        await call(hass, None, "history_connection_get")


async def test_old_install_loads_disabled(hass, hass_admin_user):
    await _upgrade(hass, JEV_3_11_1)
    doc = await call(hass, hass_admin_user, "history_connection_get", room="room:")
    assert doc["connection"]["source"] == "recorder" and doc["revision"] == 0


async def test_corrupt_optional_archive_does_not_block_room_setup(hass, hass_admin_user, hass_storage):
    from conftest import fixture

    key = "crop_steering.history_connection." + fixture(JEV_3_11_1)["entry_id"]
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key,
                         "data": {"revision": 3, "connection": ["corrupted"]}}
    await _upgrade(hass, JEV_3_11_1)
    doc = await call(hass, hass_admin_user, "history_connection_get", room="room:")
    assert doc["connection"]["source"] == "recorder" and doc["revision"] == 0


def test_query_inputs_escaped_and_capped():
    cfg = connection({"source": "influxdb", "url": "https://influx.example", "measurement": "x\"; DROP DATABASE secret"})
    first, last, seconds = window("2025-01-01T00:00:00Z", "2025-12-31T00:00:00Z")
    query = queries(cfg, "sensor.probe", cfg["measurement"], first, last, seconds)
    assert 'FROM "x\\"; DROP DATABASE secret"' in query
    assert "LIMIT 1000" in query and seconds >= 30000
    assert '"domain"=\'sensor\'' in query
    with pytest.raises(ValueError):
        window("2020-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
    with pytest.raises(ValueError):
        window("2025-01-01T00:00:00Z", "2026-01-03T00:00:00Z")
    with pytest.raises(ValueError):
        connection({"source": "influxdb", "url": "https://user:password@influx.example"})


def test_influxql_and_flux_response_shapes():
    v1 = '{"results":[{"series":[{"columns":["time","mean","min","max"],"values":[["2026-01-01T00:00:00Z",42,40,44]]}]}]}'
    rows = parse_values(v1, "1")
    assert rows[0]["value"] == 42 and rows[0]["min"] == 40 and rows[0]["max"] == 44
    v2 = ',result,table,_time,_value\n,mean,0,2026-01-01T00:00:00Z,42\n,min,1,2026-01-01T00:00:00Z,40\n,max,2,2026-01-01T00:00:00Z,44\n'
    assert parse_values(v2, "2") == rows


@pytest.mark.parametrize("version", ["1", "2"])
async def test_provider_generated_http_reads(hass, hass_admin_user, monkeypatch, version):
    """Only the external archive transport is substituted; HA and the provider run."""
    from unittest.mock import MagicMock
    from datetime import datetime, timezone

    entry = await _install(hass)
    manager = hass.data["crop_steering"]["_long_history"][entry.entry_id]
    entity = sorted(manager.allowed())[0]
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000

    class Response:
        status = 200

        def __init__(self):
            self.content = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def iter_chunked(self, size):
            if version == "1":
                yield b'{"results":[{"series":[{"columns":["time","mean","min","max"],"values":[["2026-01-01T00:00:00Z",42,40,44]]}]}]}'
            else:
                yield b',result,table,_time,_value\n,mean,0,2026-01-01T00:00:00Z,42\n'

    session = MagicMock()
    session.get.return_value = session.post.return_value = Response()
    monkeypatch.setattr("homeassistant.helpers.aiohttp_client.async_get_clientsession", lambda _: session)
    cfg = connection({"source": "influxdb", "url": "https://influx.example", "version": version,
                      "bucket": "ha", "org": "org", "token": "secret"})
    result = await manager.query(cfg, [entity], "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
    assert result["series"][0]["points"][0]["time"] == stamp
    assert result["series"][0]["points"][0]["value"] == 42
    method = session.get if version == "1" else session.post
    args, kwargs = method.call_args
    assert args[0].endswith("/query") and kwargs["allow_redirects"] is False
    assert "/write" not in args[0]
    if version == "2":
        assert kwargs["headers"]["Authorization"] == "Token secret"
        assert "aggregateWindow" in kwargs["data"]


async def test_old_run_snapshot_sensors_can_be_read_but_arbitrary_entities_cannot(hass, hass_admin_user, monkeypatch):
    """Comparison asks for the sensors an archived run was registered with, which the room may no
    longer map. They are the room's own history, so they read; any other entity still does not."""
    from test_zone_cultivar import _save

    entry = await _install(hass)
    for entity in ("sensor.row_a", "sensor.row_b", "sensor.someone_elses"):
        hass.states.async_set(entity, "50", {"unit_of_measurement": "%"})
    await _save(hass, hass_admin_user, vwc_sensors=["sensor.row_a"])
    await call(hass, hass_admin_user, "runs_save", expected_revision=0, record={"name": "Old", "start_date": "2026-01-01"})
    await _save(hass, hass_admin_user, vwc_sensors=["sensor.row_b"])
    # Saving a mapping reloads the room, so the manager is the one after the saves.
    manager = hass.data["crop_steering"]["_long_history"][entry.entry_id]
    manager.config = connection({"source": "influxdb", "url": "http://influx.example:8086"})
    query = AsyncMock(return_value={"series": []})
    monkeypatch.setattr(manager, "query", query)
    window = {"start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z"}
    await call(hass, hass_admin_user, "history_long", entity_ids=["sensor.row_a"], **window)
    assert query.await_args.args[1] == ["sensor.row_a"]
    with pytest.raises(HomeAssistantError):
        await call(hass, hass_admin_user, "history_long", entity_ids=["sensor.someone_elses"], **window)


async def test_more_than_four_room_sensors_can_be_read_at_once(hass, hass_admin_user, monkeypatch):
    entry = await _install(hass)
    manager = hass.data["crop_steering"]["_long_history"][entry.entry_id]
    manager.config = connection({"source": "influxdb", "url": "http://influx.example:8086"})
    query = AsyncMock(return_value={"series": []})
    monkeypatch.setattr(manager, "query", query)
    ids = [f"sensor.probe_{n}" for n in range(8)]
    monkeypatch.setattr(manager, "allowed", lambda: set(ids))
    window = {"start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z"}
    await call(hass, hass_admin_user, "history_long", entity_ids=ids, **window)
    assert query.await_args.args[1] == ids
    with pytest.raises(HomeAssistantError):
        await call(hass, hass_admin_user, "history_long", entity_ids=[f"sensor.probe_{n}" for n in range(17)], **window)


async def test_an_imported_run_cannot_plant_another_rooms_sensor(hass, hass_admin_user, monkeypatch):
    """runs_import drops probe rows the room does not already have, so history_long cannot be
    pointed at an entity the room never mapped."""
    from copy import deepcopy

    from test_zone_cultivar import _save

    entry = await _install(hass)
    hass.states.async_set("sensor.row_a", "50", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.other_room_probe", "50", {"unit_of_measurement": "%"})
    await _save(hass, hass_admin_user, vwc_sensors=["sensor.row_a"])
    doc = await call(hass, hass_admin_user, "runs_save", expected_revision=0, record={"name": "Mine", "start_date": "2026-01-01"})
    planted = deepcopy(doc["runs"][0])
    planted["id"] = "imported"
    planted["zones"][0]["probes"] += [{"entity_id": "sensor.other_room_probe", "kind": "vwc"}]
    doc = await call(hass, hass_admin_user, "runs_import", expected_revision=doc["revision"], runs=[planted])
    kept = [p["entity_id"] for r in doc["runs"] if r["id"] == "imported" for p in r["zones"][0]["probes"]]
    assert "sensor.row_a" in kept and "sensor.other_room_probe" not in kept
    manager = hass.data["crop_steering"]["_long_history"][entry.entry_id]
    manager.config = connection({"source": "influxdb", "url": "http://influx.example:8086"})
    monkeypatch.setattr(manager, "query", AsyncMock(return_value={"series": []}))
    window = {"start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z"}
    with pytest.raises(HomeAssistantError):
        await call(hass, hass_admin_user, "history_long", entity_ids=["sensor.other_room_probe"], **window)


async def test_one_slow_or_missing_sensor_does_not_fail_the_others(hass, hass_admin_user, monkeypatch):
    import asyncio

    entry = await _install(hass)
    manager = hass.data["crop_steering"]["_long_history"][entry.entry_id]
    cfg = connection({"source": "influxdb", "url": "http://influx.example:8086"})
    monkeypatch.setattr("custom_components.crop_steering.long_history.PER_SERIES_SECONDS", 0.05)
    hass.states.async_set("sensor.slow", "1")
    hass.states.async_set("sensor.good", "1")

    async def read(session, config, entity, first, last, seconds):
        if entity == "sensor.slow":
            await asyncio.sleep(1)
        return [{"time": first.timestamp() * 1000, "value": 1}] if entity == "sensor.good" else []

    monkeypatch.setattr(manager, "read", read)
    result = await manager.query(cfg, ["sensor.slow", "sensor.good", "sensor.gone"], "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
    by = {row["entityId"]: row for row in result["series"]}
    assert by["sensor.good"]["points"] and "error" not in by["sensor.good"]
    assert "timed out" in by["sensor.slow"]["error"]
    assert "Not found in history" in by["sensor.gone"]["error"]
