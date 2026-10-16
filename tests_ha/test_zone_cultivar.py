"""A zone's cultivar label in a real Home Assistant: saved through setup_save while the room waters (a label keeps the
setup revision, so nothing has to be switched off), published on the room descriptor for the dashboard and the
controller, copied into a run at registration and corrected on the run later. A room and a run store from before
the label load unchanged, with no cultivar."""

import pytest
from conftest import fixture
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, _upgrade

DOMAIN = "crop_steering"
DESCRIPTOR = "sensor.crop_steering_tent_engine_config"
ENGINE = "switch.crop_steering_tent_engine_enabled"


async def _call(hass, user, service, data):
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True, context=Context(user_id=user.id))


async def _save(hass, user, **zone1):
    """What Rooms & hardware sends: the whole room, zone 1 changed."""
    (room,) = (await _call(hass, user, "setup_read", {}))["rooms"]
    zones = [dict(z) for z in room["zones"]]
    zones[0].update(zone1)
    await _call(hass, user, "setup_save", {
        "entry_id": room["entry_id"], "expected_revision": room["revision"], "room_name": room["room_name"],
        "active": room["active"], "zones": zones, "hardware": room["hardware"]})
    await hass.async_block_till_done()
    return (await _call(hass, user, "setup_read", {}))["rooms"][0]


async def test_a_cultivar_is_saved_while_the_room_waters_and_keeps_the_revision(hass, hass_admin_user):
    await _install(hass)
    await hass.services.async_call("switch", "turn_on", {"entity_id": ENGINE}, blocking=True)
    before = (await _call(hass, hass_admin_user, "setup_read", {}))["rooms"][0]
    assert before["zones"][0]["cultivar"] == ""
    assert "zone_cultivars" not in hass.states.get(DESCRIPTOR).attributes
    room = await _save(hass, hass_admin_user, cultivar="  Gelato 41 ", name="Row A")
    assert room["revision"] == before["revision"]
    assert room["zones"][0]["cultivar"] == "Gelato 41" and room["zones"][0]["name"] == "Row A"
    assert hass.states.get(ENGINE).state == "on"
    assert hass.states.get(DESCRIPTOR).attributes["zone_cultivars"] == {"1": "Gelato 41"}
    assert hass.states.get(DESCRIPTOR).attributes["zone_names"]["1"] == "Row A"
    room = await _save(hass, hass_admin_user, cultivar="")
    assert room["zones"][0]["cultivar"] == "" and "zone_cultivars" not in hass.states.get(DESCRIPTOR).attributes


async def test_a_change_beside_the_label_still_needs_the_engine_off(hass, hass_admin_user):
    await _install(hass)
    await hass.services.async_call("switch", "turn_on", {"entity_id": ENGINE}, blocking=True)
    with pytest.raises(HomeAssistantError, match="must read OFF"):
        await _save(hass, hass_admin_user, cultivar="Gelato", substrate_volume=7.0)
    with pytest.raises(HomeAssistantError, match="40 characters"):
        await _save(hass, hass_admin_user, cultivar="x" * 41)


async def test_a_run_takes_the_cultivar_and_it_can_be_corrected_later(hass, hass_admin_user):
    await _install(hass)
    await _save(hass, hass_admin_user, cultivar="Gelato")
    room = {"room_id": "room:tent_"}
    doc = await _call(hass, hass_admin_user, "runs_get", room)
    doc = await _call(hass, hass_admin_user, "runs_save", {**room, "expected_revision": doc["revision"],
                                                           "record": {"name": "Run 1", "start_date": "2026-09-01"}})
    (run,) = doc["runs"]
    assert run["zones"][0]["cultivar"] == "Gelato"
    doc = await _call(hass, hass_admin_user, "runs_save", {
        **room, "expected_revision": doc["revision"],
        "record": {"id": run["id"], "name": "Run 1", "start_date": "2026-09-01",
                   "zones": [{"zone_id": 1, "cultivar": "Gelato #33"}]}})
    assert doc["runs"][0]["zones"][0]["cultivar"] == "Gelato #33"
    assert doc["runs"][0]["zones"][0]["parameters"] == run["zones"][0]["parameters"]  # the reference stays


async def test_an_upgraded_room_and_its_old_run_records_load_with_no_cultivar(hass, hass_storage, hass_admin_user):
    seed = fixture(JEV_3_11_1)
    key = f"{DOMAIN}.runs.{seed['entry_id']}"
    old_run = {  # a run record as 3.14.0 stored it: no cultivar anywhere
        "id": "a1b2c3", "room_id": "room:", "name": "Spring", "start_date": "2026-03-01", "end_date": "2026-06-20",
        "time_zone": "UTC", "archived": False, "captured_at": "2026-03-01T08:00:00+00:00",
        "reference_source": "Current manual settings at registration", "lights": {"on": 6.0, "off": 18.0},
        "zones": [{"zone_id": 1, "name": "Zone 1", "vwc_sensor": "sensor.crop_steering_vwc_zone_1",
                   "ec_sensor": None, "plant_count": 12, "reference_source": "Current manual settings at registration",
                   "parameters": {"p1_target_vwc": 55}}],
    }
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": {"revision": 3, "runs": [old_run]}}
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    assert "zone_cultivars" not in hass.states.get("sensor.crop_steering_engine_config").attributes
    (room,) = (await _call(hass, hass_admin_user, "setup_read", {}))["rooms"]
    assert {z["cultivar"] for z in room["zones"]} == {""}
    doc = await _call(hass, hass_admin_user, "runs_get", {"room_id": "room:"})
    assert doc["error"] is None and doc["revision"] == 3
    (run,) = doc["runs"]
    assert run["zones"][0]["cultivar"] is None
    assert {k: v for k, v in run["zones"][0].items() if k != "cultivar"} == old_run["zones"][0]
