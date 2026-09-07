"""Run registration is metadata-only, room scoped, durable and explicit about references."""

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.crop_steering.run_api import resolve_runs
from custom_components.crop_steering.run_store import RunStore, normalize_record


class MemoryStore:
    def __init__(self, value=None):
        self.value = value
        self.fail = False

    async def async_load(self):
        return deepcopy(self.value)

    async def async_save(self, value):
        await asyncio.sleep(0)
        if self.fail:
            raise OSError("disk unavailable")
        self.value = deepcopy(value)


def fixture(prefix="", persisted=None):
    states = {}
    entry = SimpleNamespace(entry_id=prefix or "default", data={"room_prefix": prefix})
    hass = SimpleNamespace(
        data={"crop_steering": {}},
        config=SimpleNamespace(time_zone="Pacific/Auckland"),
        states=SimpleNamespace(get=states.get),
    )

    def put(suffix, value, domain="number", attributes=None):
        eid = f"{domain}.crop_steering_{prefix}{suffix}"
        states[eid] = SimpleNamespace(state=str(value), attributes=attributes or {})
        return eid

    values = {
        "p1_target_vwc": 65,
        "p2_vwc_threshold": 50,
        "p3_emergency_vwc_threshold": 30,
        "ec_target_p2": 3,
        "dryback_target": 10,
        "p1_initial_shot_size": 4,
        "p1_shot_size_increment": 1,
    }
    response = {
        "status": "draft",
        "revision": 1,
        "active": {"zones": []},
        "error": None,
        "catalog": {1: {key: {"value": value} for key, value in values.items()}},
    }
    put("vwc_zone_1", 55, "sensor")
    put("ec_zone_1", 3, "sensor")
    put("zone_1_plant_count", 36)
    put("zone_1_ec_target_gen_p2", 6)
    put("zone_1_ec_target_veg_p2", 3)
    put("zone_1_generative_dryback_target", 20)
    put("growth_stage", "Generative", "select")
    put("lights_on_hour", 10)
    put("lights_off_hour", 22)
    manager = SimpleNamespace(
        response=lambda: response,
        entity_id=f"sensor.crop_steering_{prefix}strategy_plan",
        zone_ids=lambda: [1],
        _config=lambda: {"zones": {"1": {"name": "Bed one"}}},
        _state=lambda suffix, domain="sensor": states.get(
            f"{domain}.crop_steering_{prefix}{suffix}"
        ),
        _native_number=lambda zid, key: states.get(
            f"number.crop_steering_{prefix}zone_{zid}_{key}"
        ),
    )
    hass.data["crop_steering"]["_strategy"] = {entry.entry_id: manager}
    store = RunStore(hass, entry, MemoryStore(persisted))
    return store, response, put


def raw(**changes):
    return {
        "name": "Trial A",
        "start_date": "2026-05-01",
        "end_date": "2026-07-31",
        **changes,
    }


def test_register_backdated_run_captures_now_and_edit_preserves_snapshot():
    async def scenario():
        store, response, _ = fixture()
        await store.async_init()
        assert store.response()["runs"] == []
        result = await store.mutate(
            "runs_save", {"expected_revision": 0, "record": raw()}
        )
        record = result["runs"][0]
        assert record["zones"][0]["plant_count"] == 36
        assert record["zones"][0]["parameters"]["p1_initial_shot_size"] == 4
        assert record["lights"] == {"on": 10.0, "off": 22.0}
        assert datetime.fromisoformat(record["captured_at"]) > datetime(
            2026, 7, 31, tzinfo=timezone.utc
        )
        response["catalog"][1]["p2_vwc_threshold"]["value"] = 60
        renamed = await store.mutate(
            "runs_save",
            {
                "expected_revision": 1,
                "record": raw(id=record["id"], name="Renamed", start_date="2026-04-01"),
            },
        )
        assert renamed["runs"][0]["zones"] == record["zones"]
        assert renamed["runs"][0]["captured_at"] == record["captured_at"]
        restored, _, _ = fixture(persisted=store._store.value)
        await restored.async_init()
        assert restored.response()["runs"] == renamed["runs"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "zone_mode,expected",
    [("unavailable", 6), ("unknown", 6), ("", 6), ("Vegetative", 3)],
)
def test_manual_reference_uses_controller_growth_stage_fallback(zone_mode, expected):
    store, _, put = fixture()
    put("zone_1_steering_mode", zone_mode, "select")
    assert store.capture(raw())["zones"][0]["parameters"]["ec_target_p2"] == expected


@pytest.mark.parametrize("status", ["active", "disarming"])
def test_capture_uses_published_snapshot_not_newer_unpublished_document(status):
    store, response, put = fixture()
    now = datetime.now(timezone.utc)
    response.update(
        status=status,
        active={
            "zones": [
                {"zone_id": 1, "status": "active", "parameters": {"ec_target_p2": 8}}
            ]
        },
    )
    put(
        "strategy_plan",
        status,
        "sensor",
        {
            "snapshot_version": 1,
            "room_id": "room:",
            "revision": 1,
            "enabled": True,
            "updated_at": now.isoformat(),
            "valid_until": (now + timedelta(seconds=120)).isoformat(),
            "zones": [
                {"zone_id": 1, "status": "active", "parameters": {"ec_target_p2": 6}}
            ],
        },
    )
    record = store.capture(raw())
    assert record["zones"][0]["parameters"]["ec_target_p2"] == 6
    assert record["zones"][0]["reference_source"].startswith("Verified active-plan")


def test_expired_plan_is_labeled_fallback_and_invalid_plant_count_unknown():
    store, response, put = fixture()
    response.update(
        status="active",
        active={
            "zones": [
                {"zone_id": 1, "status": "active", "parameters": {"ec_target_p2": 8}}
            ]
        },
    )
    put(
        "strategy_plan",
        "active",
        "sensor",
        {
            "updated_at": "2026-01-01T00:00:00+00:00",
            "valid_until": "2026-01-01T00:01:00+00:00",
        },
    )
    put("zone_1_plant_count", "1.5")
    record = store.capture(raw())
    assert "not verified" in record["reference_source"]
    assert record["zones"][0]["plant_count"] is None
    assert record["zones"][0]["parameters"]["ec_target_p2"] == 6


def test_revision_races_fail_atomically_and_storage_failure_does_not_advance():
    async def scenario():
        store, _, _ = fixture()
        await store.async_init()
        results = await asyncio.gather(
            *(
                store.mutate("runs_save", {"expected_revision": 0, "record": raw()})
                for _ in range(2)
            ),
            return_exceptions=True,
        )
        assert sum(isinstance(r, ValueError) for r in results) == 1
        assert store.document["revision"] == 1
        before = deepcopy(store.document)
        store._store.fail = True
        with pytest.raises(OSError):
            await store.mutate("runs_save", {"expected_revision": 1, "record": raw()})
        assert store.document == before

    asyncio.run(scenario())


def test_archive_restore_and_room_bound_import():
    async def scenario():
        store, _, _ = fixture()
        await store.async_init()
        record = (
            await store.mutate("runs_save", {"expected_revision": 0, "record": raw()})
        )["runs"][0]
        for revision, value in [(1, True), (2, False)]:
            result = await store.mutate(
                "runs_archive",
                {"expected_revision": revision, "id": record["id"], "archived": value},
            )
            assert result["runs"][0]["archived"] is value
        wrong = deepcopy(record)
        wrong["room_id"] = "room:f2_"
        with pytest.raises(ValueError, match="another room"):
            await store.mutate("runs_import", {"expected_revision": 3, "runs": [wrong]})
        wrong = deepcopy(record)
        wrong["zones"][0]["vwc_sensor"] = "sensor.crop_steering_f2_vwc_zone_1"
        with pytest.raises(ValueError, match="not registered"):
            await store.mutate("runs_import", {"expected_revision": 3, "runs": [wrong]})
        assert store.document["revision"] == 3
        imported = await store.mutate(
            "runs_import", {"expected_revision": 3, "runs": [record]}
        )
        assert len(imported["runs"]) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "changes",
    [
        {"start_date": "2026-02-30"},
        {"end_date": "2026-04-30"},
        {"end_date": "2027-05-02"},
        {"name": "x" * 81},
    ],
)
def test_invalid_metadata_rejected(changes):
    store, _, _ = fixture()
    with pytest.raises(ValueError):
        store.capture(raw(**changes))


def test_import_validation_rejects_nan_fractional_counts_and_unsupported_parameters():
    store, _, _ = fixture()
    record = store.capture(raw())
    for mutate in [
        lambda r: r["zones"][0].update(plant_count=1.5),
        lambda r: r["zones"][0]["parameters"].update(ec_target_p2=float("nan")),
        lambda r: r["zones"][0]["parameters"].update(p3_last_irrigation=2),
    ]:
        value = deepcopy(record)
        mutate(value)
        with pytest.raises(ValueError):
            normalize_record(value, "room:")


def test_corrupt_store_is_readonly_and_unknown_or_ambiguous_room_rejected():
    async def scenario():
        store, _, _ = fixture(persisted={"revision": 4, "runs": "bad"})
        await store.async_init()
        assert store.response()["error"]
        with pytest.raises(ValueError, match="not been overwritten"):
            await store.mutate("runs_save", {"expected_revision": 0, "record": raw()})
        store.hass.data["crop_steering"]["_runs"] = {"one": store}
        assert resolve_runs(store.hass, "room:") is store
        for room in ["", "default", "room:f2_"]:
            with pytest.raises(ValueError):
                resolve_runs(store.hass, room)
        store.hass.data["crop_steering"]["_runs"]["two"] = store
        with pytest.raises(ValueError, match="ambiguous"):
            resolve_runs(store.hass, "room:")

    asyncio.run(scenario())


def test_zone_count_and_duplicate_ids_are_bounded():
    store, _, _ = fixture()
    record = store.capture(raw())
    record["zones"] = [record["zones"][0]] * 25
    with pytest.raises(ValueError, match="1–24"):
        normalize_record(record, "room:")
    record["zones"] = record["zones"][:2]
    with pytest.raises(ValueError, match="unique"):
        normalize_record(record, "room:")


def test_more_than_100_runs_and_old_ongoing_import_are_rejected():
    async def scenario():
        store, _, _ = fixture()
        await store.async_init()
        with pytest.raises(ValueError, match="100"):
            await store.mutate(
                "runs_import", {"expected_revision": 0, "runs": [{}] * 101}
            )
        record = store.capture(raw())
        record.update(start_date="2020-01-01", end_date=None)
        with pytest.raises(ValueError, match="Close imported"):
            await store.mutate(
                "runs_import", {"expected_revision": 0, "runs": [record]}
            )
        assert store.document["revision"] == 0

    asyncio.run(scenario())
