"""Dashboards from templates (G11) through a real Home Assistant: dashboard_create makes a storage
dashboard in Home Assistant's own dashboards collection whose config names only the room's entities,
dashboard_list shows it, and one the user deleted in Home Assistant lists with exists false."""

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from test_setup_entry import _install

DOMAIN = "crop_steering"
ROOM = "room:tent_"


async def _call(hass, user, service, **data):
    return await hass.services.async_call(
        DOMAIN,
        service,
        data,
        blocking=True,
        return_response=True,
        context=Context(user_id=user.id),
    )


def _collection(hass):
    import inspect

    handler = hass.data["websocket_api"]["lovelace/dashboards/create"][0]
    return inspect.unwrap(handler).__self__.storage_collection


def _named(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "entity":
                yield value
            elif key == "entities":
                yield from value
            else:
                yield from _named(value)
    elif isinstance(node, list):
        for item in node:
            yield from _named(item)


async def test_create_then_list_shows_it_and_ha_serves_it(hass, hass_admin_user):
    await _install(hass)
    assert await async_setup_component(hass, "lovelace", {})
    made = await _call(hass, hass_admin_user, "dashboard_create", template="room_tablet", rooms=[ROOM])
    assert made["url_path"] == "crop-steering-room_tablet-1"

    served = hass.data["lovelace"]
    dashboards = served.dashboards if hasattr(served, "dashboards") else served["dashboards"]
    config = await dashboards[made["url_path"]].async_load(False)
    assert config["views"] and config["views"][0]["cards"]
    named = set(_named(config))
    assert named and all(hass.states.get(e) is not None for e in named)
    assert "sensor.crop_steering_tent_zone_1_status" in named
    item = next(i for i in _collection(hass).async_items() if i["url_path"] == made["url_path"])
    assert (item["mode"], item["title"]) == ("storage", made["title"])

    again = await _call(hass, hass_admin_user, "dashboard_create", template="room_tablet", rooms=[ROOM], title="Tent")
    assert (again["url_path"], again["title"]) == ("crop-steering-room_tablet-2", "Tent")

    listed = await _call(hass, hass_admin_user, "dashboard_list")
    assert [(d["url_path"], d["template"], d["rooms"], d["exists"]) for d in listed["dashboards"]] == [
        ("crop-steering-room_tablet-1", "room_tablet", [ROOM], True),
        ("crop-steering-room_tablet-2", "room_tablet", [ROOM], True),
    ]
    assert [t["id"] for t in listed["templates"]] == ["facility_wall", "room_tablet", "dosing_station"]

    with pytest.raises(HomeAssistantError, match="Unknown dashboard template"):
        await _call(hass, hass_admin_user, "dashboard_create", template="kiosk", rooms=[ROOM])


async def test_a_dashboard_deleted_in_ha_lists_exists_false(hass, hass_admin_user):
    await _install(hass)
    assert await async_setup_component(hass, "lovelace", {})
    made = await _call(hass, hass_admin_user, "dashboard_create", template="facility_wall", rooms=[ROOM])
    collection = _collection(hass)
    item = next(i for i in collection.async_items() if i["url_path"] == made["url_path"])
    await collection.async_delete_item(item["id"])
    await hass.async_block_till_done()

    listed = await _call(hass, hass_admin_user, "dashboard_list")
    assert [(d["url_path"], d["exists"]) for d in listed["dashboards"]] == [(made["url_path"], False)]
    # Its number is free again only once nothing tracks it: the next one is 2.
    again = await _call(hass, hass_admin_user, "dashboard_create", template="facility_wall", rooms=[ROOM])
    assert again["url_path"] == "crop-steering-facility_wall-2"


async def test_without_dashboards_loaded_a_create_says_so(hass, hass_admin_user):
    await _install(hass)
    with pytest.raises(HomeAssistantError, match="dashboards are not loaded yet"):
        await _call(hass, hass_admin_user, "dashboard_create", template="facility_wall", rooms=[ROOM])
    assert (await _call(hass, hass_admin_user, "dashboard_list"))["dashboards"] == []


async def test_list_reads_ha_dashboards_even_when_the_collection_cannot_be_reached(
    hass, hass_admin_user
):
    await _install(hass)
    assert await async_setup_component(hass, "lovelace", {})
    made = await _call(hass, hass_admin_user, "dashboard_create", template="room_tablet", rooms=[ROOM])
    hass.data["websocket_api"].pop("lovelace/dashboards/create")

    listed = await _call(hass, hass_admin_user, "dashboard_list")
    assert [(d["url_path"], d["exists"]) for d in listed["dashboards"]] == [(made["url_path"], True)]
    with pytest.raises(HomeAssistantError, match="cannot reach HA's dashboards collection"):
        await _call(hass, hass_admin_user, "dashboard_create", template="room_tablet", rooms=[ROOM])


async def test_a_failed_create_leaves_no_dashboard_and_frees_its_number(hass, hass_admin_user):
    await _install(hass)
    assert await async_setup_component(hass, "lovelace", {})
    store = hass.data[DOMAIN]["_dashboards"]._store
    saved = store.async_save

    async def refuse(_data):
        raise OSError("disk full")

    store.async_save = refuse
    with pytest.raises(HomeAssistantError, match="disk full"):
        await _call(hass, hass_admin_user, "dashboard_create", template="room_tablet", rooms=[ROOM])
    await hass.async_block_till_done()
    assert not [i for i in _collection(hass).async_items() if i["url_path"].startswith("crop-steering-")]
    served = hass.data["lovelace"]
    dashboards = served.dashboards if hasattr(served, "dashboards") else served["dashboards"]
    assert "crop-steering-room_tablet-1" not in dashboards
    assert (await _call(hass, hass_admin_user, "dashboard_list"))["dashboards"] == []

    store.async_save = saved
    made = await _call(hass, hass_admin_user, "dashboard_create", template="room_tablet", rooms=[ROOM])
    assert made["url_path"] == "crop-steering-room_tablet-1"


async def test_a_dashboard_with_nothing_to_show_is_refused(hass, hass_admin_user):
    await _install(hass)
    assert await async_setup_component(hass, "lovelace", {})
    # A room with no dosing entities: the ones a dosing station would show are disabled.
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    for key in ("dosing_config", "stock_low", "feed_ec_corrected", "feed_ph_corrected"):
        if registry.async_get(f"sensor.crop_steering_tent_{key}"):
            registry.async_update_entity(
                f"sensor.crop_steering_tent_{key}",
                disabled_by=er.RegistryEntryDisabler.USER,
            )
    with pytest.raises(HomeAssistantError, match="would show nothing"):
        await _call(hass, hass_admin_user, "dashboard_create", template="dosing_station", rooms=[ROOM])
    assert not [i for i in _collection(hass).async_items() if i["url_path"].startswith("crop-steering-")]
