"""Settings > Repairs says when a setting is not where the controller looks for it.

First real install, 2026-09-21: Home Assistant was still running a pre-2.18 integration, which
let Home Assistant choose the entity ids (`number.gt1_crop_steering_zone_1_plant_count`). The
controller reads `number.crop_steering_zone_1_plant_count`, found nothing, and ran on its built-in
defaults: a 150 L daily cap on a two-plant tent. The only sign was a controller notification,
"Setpoint entities missing". Entity ids are for life, so a restart does not cure it.
"""

import pytest
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from custom_components.crop_steering import health
from test_setup_entry import _install
from test_upgrade_in_place import _known_numbers, _upgrade
from conftest import fixture

DOMAIN = "crop_steering"
PLANTS = "number.crop_steering_zone_1_plant_count"
CAP = "number.crop_steering_zone_1_max_daily_volume"
ROOM = "switch.crop_steering_room_active"


def _card(hass, slug="default"):
    issue_id = "entities_moved" if slug == "default" else f"entities_moved_{slug}"
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


def _move(hass, entity_id, to):
    er.async_get(hass).async_update_entity(entity_id, new_entity_id=to)


async def test_fresh_install_has_no_card(hass):
    entry = await _install(hass)
    assert health.moved_entities(hass, entry) == []
    health.run_health_check(hass, entry)
    assert _card(hass) is None


async def test_a_setting_that_has_moved_is_named_with_where_it_should_be(hass):
    entry = await _install(hass)
    _move(hass, PLANTS, "number.gt1_crop_steering_zone_1_plant_count")
    _move(hass, CAP, "number.gt1_crop_steering_zone_1_max_daily_volume")
    await hass.async_block_till_done()
    health.run_health_check(hass, entry)
    card = _card(hass)
    assert card is not None and card.severity is ir.IssueSeverity.WARNING
    assert card.translation_placeholders["count"] == "2"
    listed = card.translation_placeholders["entities"]
    assert (
        f"`number.gt1_crop_steering_zone_1_plant_count` should be `{PLANTS}`" in listed
    )
    assert CAP in listed

    # Put back, the card clears by itself. Nothing was renamed for the operator.
    _move(hass, "number.gt1_crop_steering_zone_1_plant_count", PLANTS)
    _move(hass, "number.gt1_crop_steering_zone_1_max_daily_volume", CAP)
    await hass.async_block_till_done()
    health.run_health_check(hass, entry)
    assert _card(hass) is None


async def test_it_is_shown_while_the_room_is_off_which_is_when_it_is_safest_to_find(
    hass,
):
    entry = await _install(hass)
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": ROOM}, blocking=True
    )
    _move(hass, PLANTS, "number.somewhere_else")
    await hass.async_block_till_done()
    health.run_health_check(hass, entry)
    assert _card(hass) is not None


async def test_a_long_list_is_cut_short_and_counted(hass):
    entry = await _install(hass)
    numbers = [
        e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.domain == "number"
    ][:9]
    for index, entity_id in enumerate(numbers):
        _move(hass, entity_id, f"number.stale_code_made_this_{index}")
    await hass.async_block_till_done()
    health.run_health_check(hass, entry)
    placeholders = _card(hass).translation_placeholders
    assert placeholders["count"] == "9" and "and 3 more" in placeholders["entities"]


async def test_sensors_and_buttons_are_not_judged(hass):
    """The controller tolerates the fused sensors' legacy naming and never reads a button."""
    entry = await _install(hass)
    _move(hass, "sensor.crop_steering_vwc_zone_1", "sensor.crop_steering_zone_1_vwc")
    _move(hass, "button.crop_steering_zone_1_trigger_shot", "button.gt1_trigger_shot")
    await hass.async_block_till_done()
    assert health.moved_entities(hass, entry) == []


@pytest.mark.parametrize(
    "name",
    ["entry_2_17_wizard.json", "entry_2_18_one_switch_tent.json", "entry_env_era.json"],
)
async def test_upgrade_in_place_a_working_old_install_gets_no_card(hass, name):
    entry, _seed = await _upgrade(
        hass, name, registry_ids=_known_numbers(fixture(name))
    )
    assert health.moved_entities(hass, entry) == []
    health.run_health_check(hass, entry)
    assert _card(hass) is None


async def test_an_id_the_operator_changed_on_purpose_is_reported_and_left_alone(hass):
    """tests_ha/test_upgrade_in_place.py promises an operator's own id is kept. It is: the card
    says the controller cannot see that setting, and changes nothing."""
    seed = fixture("entry_2_17_wizard.json")
    entry, _seed = await _upgrade(
        hass,
        "entry_2_17_wizard.json",
        registry_ids={"number.my_p1_target": "p1_target_vwc"},
    )
    assert health.moved_entities(hass, entry) == [
        ("number.my_p1_target", "number.crop_steering_p1_target_vwc")
    ]
    health.run_health_check(hass, entry)
    assert er.async_get(hass).async_get("number.my_p1_target") is not None
    assert seed["entry_id"] == entry.entry_id


async def test_a_second_room_is_judged_by_its_own_prefixed_ids(hass):
    from test_upgrade_in_place import (
        test_a_second_room_can_still_be_added_beside_an_upgraded_default_room as add_veg_tent,
    )

    await add_veg_tent(hass)
    default, veg = hass.config_entries.async_entries(DOMAIN)
    assert (
        health.moved_entities(hass, default) == []
        and health.moved_entities(hass, veg) == []
    )
    _move(hass, "number.crop_steering_veg_tent_zone_1_plant_count", "number.veg_plants")
    await hass.async_block_till_done()
    assert health.moved_entities(hass, default) == []
    assert health.moved_entities(hass, veg) == [
        ("number.veg_plants", "number.crop_steering_veg_tent_zone_1_plant_count")
    ]
    health.run_health_check(hass, veg)
    assert _card(hass) is None and _card(hass, "veg_tent") is not None
