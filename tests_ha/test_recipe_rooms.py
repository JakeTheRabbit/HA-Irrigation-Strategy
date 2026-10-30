"""The recipe services act on one room. With two rooms a call names its room, and the other room's
setpoints and recipe table stay as they were; without a room the call is refused."""

import copy

import pytest
from conftest import fixture
from custom_components.crop_steering.recipe import get_manager
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_setup_entry import _install

DOMAIN = "crop_steering"
TENT = "number.crop_steering_tent_zone_1_p1_target_vwc"  # the wizard's room has the slug tent
OLD = "number.crop_steering_zone_1_p1_target_vwc"  # an upgraded room keeps un-prefixed ids


async def _two_rooms(hass):
    tent = await _install(hass)
    seed = fixture("entry_2_25_1_pumped_room.json")
    for entity_id, (state, attributes) in seed["states"].items():
        hass.states.async_set(entity_id, state, attributes)
    old = MockConfigEntry(
        domain=DOMAIN,
        version=seed.get("version", 1),
        minor_version=seed.get("minor_version", 1),
        entry_id=seed["entry_id"],
        unique_id=seed["unique_id"],
        title=seed["title"],
        data=seed["data"],
        options=seed["options"],
    )
    old.add_to_hass(hass)
    assert await hass.config_entries.async_setup(old.entry_id)
    await hass.async_block_till_done()
    assert old.state is ConfigEntryState.LOADED
    return tent, old


async def test_a_recipe_call_names_its_room_and_leaves_the_other_alone(hass):
    tent, old = await _two_rooms(hass)
    old_vwc = hass.states.get(OLD).state
    old_recipe = copy.deepcopy(get_manager(hass, old).recipe)

    for service, data in (
        ("apply_recipe", {"stage": "Ripen"}),
        ("save_recipe", {"recipe": {"stages": {}}}),
    ):
        with pytest.raises(HomeAssistantError, match="name the room"):
            await hass.services.async_call(DOMAIN, service, data, blocking=True)
    assert float(hass.states.get(TENT).state) == 65.0
    assert get_manager(hass, tent).active_stage != "Ripen"

    await hass.services.async_call(
        DOMAIN, "apply_recipe", {"stage": "Ripen", "room": "tent"}, blocking=True
    )
    await hass.async_block_till_done()
    assert float(hass.states.get(TENT).state) == 58.0
    assert hass.states.get(OLD).state == old_vwc

    tent_recipe = copy.deepcopy(get_manager(hass, tent).recipe)
    tent_recipe["stages"]["Custom"] = {"p2_shot_size": 3.0}
    await hass.services.async_call(
        DOMAIN, "save_recipe", {"recipe": tent_recipe, "room": "tent"}, blocking=True
    )
    assert get_manager(hass, tent).recipe["stages"]["Custom"] == {"p2_shot_size": 3.0}
    assert get_manager(hass, old).recipe == old_recipe
