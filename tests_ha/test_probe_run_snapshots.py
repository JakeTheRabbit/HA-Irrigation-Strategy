"""Additive probe snapshots in real HA; old run records keep their references on edit."""

from copy import deepcopy
from homeassistant.core import Context
from test_setup_entry import _install
from test_zone_cultivar import _save


async def call(hass, user, action, **data):
    return await hass.services.async_call(
        "crop_steering",
        action,
        {"room_id": "room:tent_", **data},
        blocking=True,
        return_response=True,
        context=Context(user_id=user.id),
    )


async def test_probe_rows_are_captured_and_old_records_load_and_round_trip(
    hass, hass_admin_user
):
    await _install(hass)
    hass.states.async_set(
        "sensor.row_a", "50", {"friendly_name": "Row A", "unit_of_measurement": "%"}
    )
    await _save(hass, hass_admin_user, vwc_sensors=["sensor.row_a"])
    doc = await call(
        hass,
        hass_admin_user,
        "runs_save",
        expected_revision=0,
        record={"name": "Grow", "start_date": "2026-01-01"},
    )
    run = doc["runs"][0]
    assert run["zones"][0]["probes"][0] == {
        "entity_id": "sensor.row_a",
        "row_label": "Row A",
        "position": 0,
        "kind": "vwc",
    }
    old = deepcopy(run)
    old["zones"][0].pop("probes")
    manager = next(iter(hass.data["crop_steering"]["_runs"].values()))
    await manager._store.async_save({"revision": 2, "runs": [old]})
    await manager.async_init()
    assert manager.error is None and manager.response()["runs"] == [old]
    edited = await call(
        hass,
        hass_admin_user,
        "runs_save",
        expected_revision=2,
        record={
            "id": old["id"],
            "name": "Old renamed",
            "start_date": old["start_date"],
        },
    )
    assert edited["runs"][0]["zones"] == old["zones"]


async def test_daily_summaries_refresh_only_open_run_probe_metadata(
    hass, hass_admin_user
):
    await _install(hass)
    doc = await call(
        hass,
        hass_admin_user,
        "runs_save",
        expected_revision=0,
        record={"name": "Open grow", "start_date": "2026-01-01"},
    )
    old = deepcopy(doc["runs"][0])
    await call(
        hass,
        hass_admin_user,
        "grow_day_record",
        days=[
            {
                "date": "2026-09-01",
                "zone": 1,
                "probes": [
                    {
                        "entity_id": "sensor.row_a",
                        "kind": "vwc",
                        "name": "Row A",
                        "peak": 60,
                        "trough": 40,
                        "mean": 50,
                    }
                ],
            }
        ],
    )
    refreshed = (await call(hass, hass_admin_user, "runs_get"))["runs"][0]
    assert refreshed["zones"][0]["probes"][-1]["entity_id"] == "sensor.row_a"
    for key in ("captured_at", "reference_source", "lights"):
        assert refreshed[key] == old[key]
    assert refreshed["zones"][0]["parameters"] == old["zones"][0]["parameters"]
    before = await call(hass, hass_admin_user, "runs_get")
    await call(
        hass,
        hass_admin_user,
        "grow_day_record",
        days=[
            {
                "date": "2026-09-01",
                "zone": 1,
                "probes": [
                    {"entity_id": "sensor.row_a", "kind": "vwc", "name": "Row A"}
                ],
            }
        ],
    )
    assert (await call(hass, hass_admin_user, "runs_get"))["revision"] == before[
        "revision"
    ]
