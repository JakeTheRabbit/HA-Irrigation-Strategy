"""The recipe-stage select only shows a stage once its setpoints are written.

Picking a stage the moisture-order check refuses used to leave the select on that stage
although nothing was written. Now the pick is refused with an error and the select keeps
the stage that is really applied.
"""

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_setup_entry import _install

Z1 = "number.crop_steering_tent_zone_1_"
SELECT = "select.crop_steering_tent_recipe_stage"
LEVELS = ("p3_emergency_vwc_threshold", "p2_vwc_threshold", "p1_target_vwc")


def _ladder(hass):
    return {k: float(hass.states.get(Z1 + k).state) for k in LEVELS}


async def _pick(hass, stage):
    await hass.services.async_call(
        "select", "select_option", {"entity_id": SELECT, "option": stage}, blocking=True
    )


async def test_a_refused_stage_leaves_the_select_on_the_old_stage(hass):
    from custom_components.crop_steering.recipe import get_manager

    entry = await _install(hass)
    mgr = get_manager(hass, entry)
    await _pick(hass, "Bulk")
    assert hass.states.get(SELECT).state == "Bulk"
    before = _ladder(hass)
    shot = hass.states.get(Z1 + "p2_shot_size").state

    recipe = dict(mgr.recipe)
    recipe["stages"] = {
        **recipe["stages"],
        "Custom": {
            "p1_target_vwc": 50.0,
            "p2_vwc_threshold": 42.0,
            "p2_shot_size": 3.0,
        },
    }
    await mgr.async_save(recipe)

    with pytest.raises(HomeAssistantError, match="rescue level"):
        await _pick(hass, "Custom")
    assert hass.states.get(SELECT).state == "Bulk"
    assert mgr.active_stage == "Bulk"
    assert _ladder(hass) == before
    assert hass.states.get(Z1 + "p2_shot_size").state == shot


async def test_an_accepted_stage_shows_on_the_select(hass):
    await _install(hass)
    await _pick(hass, "Ripen")
    assert hass.states.get(SELECT).state == "Ripen"
    assert _ladder(hass)["p1_target_vwc"] == 58.0


async def test_a_failed_setpoint_write_leaves_the_select_on_the_old_stage(hass):
    from unittest.mock import patch

    from custom_components.crop_steering.number import async_set_numbers
    from custom_components.crop_steering.recipe import get_manager

    entry = await _install(hass)
    mgr = get_manager(hass, entry)
    await _pick(hass, "Bulk")
    bad = Z1 + "p2_shot_size"

    async def _fail_one(hass_, pairs):
        applied, failed = await async_set_numbers(
            hass_, [(e, v) for e, v in pairs if e != bad]
        )
        return applied, failed + [(bad, "boom")]

    with patch("custom_components.crop_steering.number.async_set_numbers", _fail_one):
        with pytest.raises(
            HomeAssistantError, match="only partly applied.*p2_shot_size"
        ):
            await _pick(hass, "Ripen")
    assert hass.states.get(SELECT).state == "Bulk"
    assert mgr.active_stage == "Bulk"


async def test_apply_recipe_names_every_room_that_failed_and_applies_the_rest(hass):
    from types import SimpleNamespace

    from custom_components.crop_steering.const import DOMAIN
    from custom_components.crop_steering.recipe import get_manager

    entry = await _install(hass)
    mgr = get_manager(hass, entry)

    async def _refuse(stage=None):
        raise HomeAssistantError(
            "Stage 'Ripen' only partly applied: p2_shot_size (boom)"
        )

    # A second room whose apply fails, after the real one in the loop.
    fake = SimpleNamespace(
        entry=SimpleNamespace(title="Flower B", entry_id="b"),
        active_stage="Veg",
        async_apply=_refuse,
    )
    hass.data[DOMAIN]["_recipe"]["b"] = fake
    try:
        with pytest.raises(HomeAssistantError, match=r"Flower B: .*p2_shot_size"):
            await hass.services.async_call(
                "crop_steering", "apply_recipe", {"stage": "Ripen"}, blocking=True
            )
    finally:
        hass.data[DOMAIN]["_recipe"].pop("b")
    assert mgr.active_stage == "Ripen"  # the room that could take it did
    assert _ladder(hass)["p1_target_vwc"] == 58.0
