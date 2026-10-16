"""The room's climate sensors in its descriptor, for the dashboard's history chart, in a real Home
Assistant. Read-only: the controller reads none of them, so a room that maps them, and an old
install that never did, are adopted with no disarm cycle.
"""

from conftest import fixture
from test_declared_plumbing import NEW_DESCRIPTOR, UPGRADED_KILL
from test_setup_entry import _install
from test_upgrade_in_place import DESCRIPTOR, UPSTREAM_2_25_1, _upgrade

CLIMATE = {
    "temperature_sensor": "sensor.tent_air_temperature",
    "humidity_sensor": "sensor.tent_air_humidity",
    "vpd_sensor": "sensor.tent_vpd",
}


async def test_a_new_room_publishes_the_climate_sensors_it_maps(hass):
    for entity_id in CLIMATE.values():
        hass.states.async_set(entity_id, "1")
    await _install(hass, dict(CLIMATE))
    descriptor = hass.states.get(NEW_DESCRIPTOR).attributes
    assert {key: descriptor.get(key) for key in CLIMATE} == CLIMATE


async def test_a_new_room_without_climate_sensors_publishes_no_climate_keys(hass):
    await _install(hass)
    descriptor = hass.states.get(NEW_DESCRIPTOR).attributes
    assert not set(CLIMATE) & set(descriptor)


async def test_an_old_room_comes_through_the_update_unchanged(hass, controller_for):
    """A 2.25.1 room, armed mid grow-day: its saved setup fingerprint still matches, so the update
    needs no disarm cycle, and its descriptor carries no climate key it never mapped."""
    seed = fixture(UPSTREAM_2_25_1)
    await _upgrade(hass, UPSTREAM_2_25_1, registry_ids=seed["registry"])
    assert not any(seed["data"]["hardware"].get(key) for key in CLIMATE)
    descriptor = hass.states.get(DESCRIPTOR).attributes
    assert not set(CLIMATE) & set(descriptor)
    hass.states.async_set(UPGRADED_KILL, "on")
    c, _fake, _clock = controller_for(
        seed["addon_options"], saved_state=seed["controller_saved"]
    )
    assert c.rooms[0]._setup_pending is None, c.rooms[0]._setup_pending


async def test_an_old_room_that_maps_climate_later_is_not_held_by_the_controller(
    hass, controller_for
):
    seed = fixture(UPSTREAM_2_25_1)
    entry, _seed = await _upgrade(hass, UPSTREAM_2_25_1, registry_ids=seed["registry"])
    data = {**entry.data, "hardware": {**entry.data["hardware"], **CLIMATE}}
    hass.config_entries.async_update_entry(entry, data=data)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    descriptor = hass.states.get(DESCRIPTOR).attributes
    assert {key: descriptor.get(key) for key in CLIMATE} == CLIMATE
    hass.states.async_set(UPGRADED_KILL, "on")
    c, _fake, _clock = controller_for(
        seed["addon_options"], saved_state=seed["controller_saved"]
    )
    assert c.rooms[0]._setup_pending is None, c.rooms[0]._setup_pending
