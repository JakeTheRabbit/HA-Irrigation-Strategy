"""The engine never clips a moisture level its Home Assistant setting accepts.

A setting accepted a peak target of 87 (5-95) and the engine used 85 with CS-401, because the engine
took 20-85. Each of the four moisture levels now has one range, the same in the setting, the engine,
grow plans and Auto setpoints. The tops are 100, because the order between the levels is what bounds
the water; the floors, where the engine always had them, catch a slipped digit.
"""

import dataclasses
from datetime import datetime

import pytest
from conftest import fixture, room_of
from crop_steering_engine import validate_params
from crop_steering_engine.core import _PARAM_BOUNDS
from custom_components.crop_steering.const import MOISTURE_RANGES
from custom_components.crop_steering.strategy_model import ENGINE_BOUNDS as GROW_PLANS
from homeassistant.exceptions import ServiceValidationError
from setpoint_supervisor import BOUNDS as AUTO_SETPOINTS
from test_setup_entry import _install

# Each setting (its entity key), the engine's name for it, and its one range.
LEVELS = {
    "p1_target_vwc": ("p1_target", (20, 100)),
    "p2_vwc_threshold": ("p2_threshold", (10, 100)),
    "field_capacity": ("field_capacity", (40, 100)),
    "p3_emergency_vwc_threshold": ("p3_emergency_floor", (10, 65)),
}


async def _set(hass, entity_id, value):
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True
    )


async def test_each_level_has_one_range_everywhere(hass, controller_for):
    await _install(hass)
    c, _fake, _clock = controller_for({})
    params = c._params(room_of(c), 1)
    for key, (engine, expected) in LEVELS.items():
        for entity_id in (
            f"number.crop_steering_tent_{key}",  # a new room has a slug: the wizard's "Tent"
            f"number.crop_steering_tent_zone_1_{key}",
        ):
            state = hass.states.get(entity_id)
            assert (state.attributes["min"], state.attributes["max"]) == expected
        assert MOISTURE_RANGES[key] == expected
        assert _PARAM_BOUNDS[engine] == expected
        assert GROW_PLANS[key] == expected
        assert AUTO_SETPOINTS[key] == expected
        # Neither end of what the setting accepts is clipped.
        for value in expected:
            _clamped, warnings = validate_params(
                dataclasses.replace(params, **{engine: float(value)})
            )
            assert not [w for w in warnings if w.startswith(f"{engine}=")], (
                engine,
                value,
            )


async def test_a_peak_target_of_87_is_used_as_set(hass, controller_for):
    await _install(hass)
    await _set(hass, "number.crop_steering_tent_zone_1_field_capacity", 90)
    await _set(hass, "number.crop_steering_tent_zone_1_p1_target_vwc", 87)
    c, fake, _clock = controller_for({})
    assert c._params(room_of(c), 1).p1_target == 87
    c.loop_once(datetime.now())
    notices = [
        d.get("title", "")
        for dom, svc, d in fake.calls
        if (dom, svc) == ("persistent_notification", "create")
    ]
    assert not [title for title in notices if "CS-401" in title]


# ------------------------------------------------------------------ the order between the levels
# rescue + 3 <= re-water < peak. A rescue level above the re-water level waters all night, outside
# the daily cap. A move that breaks a rule the ladder kept is refused; one that leaves an already
# inverted ladder no worse is not, so it can be repaired one number at a time; and a move of several
# levels (a recipe stage) is judged as one set, whatever order its numbers are written in.
Z1 = "number.crop_steering_zone_1_"


def _ladder(hass, scope):
    return {
        key: float(hass.states.get(f"{scope}{key}").state)
        for key in ("p3_emergency_vwc_threshold", "p2_vwc_threshold", "p1_target_vwc")
    }


async def test_an_inverted_ladder_is_repaired_one_number_at_a_time(hass, monkeypatch):
    """The 3.11.1 room (tests_ha/fixtures), its zone 1 left with a rescue level over its re-water
    level and a re-water level over its peak target, as an older version could leave it."""
    import test_upgrade_in_place as upgrade

    seed = fixture(upgrade.JEV_3_11_1)
    seed["operator_tuned_numbers"][Z1 + "p3_emergency_vwc_threshold"] = "45.0"
    seed["operator_tuned_numbers"][Z1 + "p2_vwc_threshold"] = "58.0"
    monkeypatch.setattr(upgrade, "fixture", lambda name: seed)
    await upgrade._upgrade(hass, upgrade.JEV_3_11_1, registry_ids=seed["registry"])
    assert _ladder(hass, Z1) == {
        "p3_emergency_vwc_threshold": 45.0,
        "p2_vwc_threshold": 58.0,
        "p1_target_vwc": 55.5,
    }  # it loads as it was: nothing is moved for the operator

    await _set(hass, Z1 + "p3_emergency_vwc_threshold", 35)  # the peak rule is still broken
    await _set(hass, Z1 + "p2_vwc_threshold", 50)
    assert _ladder(hass, Z1) == {
        "p3_emergency_vwc_threshold": 35.0,
        "p2_vwc_threshold": 50.0,
        "p1_target_vwc": 55.5,
    }

    # Repaired, it is kept: a rescue level 3 points under the re-water level is the closest it may go.
    with pytest.raises(ServiceValidationError, match="rescue level"):
        await _set(hass, Z1 + "p3_emergency_vwc_threshold", 48)
    with pytest.raises(ServiceValidationError, match="below the peak target"):
        await _set(hass, Z1 + "p1_target_vwc", 50)
    await _set(hass, Z1 + "p3_emergency_vwc_threshold", 47)
    assert _ladder(hass, Z1)["p3_emergency_vwc_threshold"] == 47.0


async def test_a_recipe_stage_is_judged_as_one_set(hass):
    from custom_components.crop_steering.recipe import get_manager

    entry = await _install(hass)
    mgr = get_manager(hass, entry)
    z1 = Z1.replace("crop_steering_", "crop_steering_tent_")  # a new room has a slug: tent_
    before = {scope: _ladder(hass, scope) for scope in ("number.crop_steering_tent_", z1)}
    assert before[z1] == {
        "p3_emergency_vwc_threshold": 40.0,
        "p2_vwc_threshold": 60.0,
        "p1_target_vwc": 65.0,
    }

    # Ripen moves the peak to 58, under today's re-water level of 60: written first, on its own,
    # it would be refused. As a set (re-water 46) it is in order, and all of it is written.
    await hass.services.async_call(
        "crop_steering", "apply_recipe", {"stage": "Ripen"}, blocking=True
    )
    for scope in before:
        assert _ladder(hass, scope) == {
            "p3_emergency_vwc_threshold": 40.0,
            "p2_vwc_threshold": 46.0,
            "p1_target_vwc": 58.0,
        }, scope

    # A stage whose re-water level comes within 3 points of the rescue level writes nothing.
    recipe = dict(mgr.recipe)
    recipe["stages"] = {
        **recipe["stages"],
        "Custom": {"p1_target_vwc": 50.0, "p2_vwc_threshold": 42.0, "p2_shot_size": 3.0},
    }
    await mgr.async_save(recipe)
    with pytest.raises(ServiceValidationError, match="rescue level"):
        await hass.services.async_call(
            "crop_steering", "apply_recipe", {"stage": "Custom"}, blocking=True
        )
    assert _ladder(hass, z1)["p1_target_vwc"] == 58.0
    assert float(hass.states.get(z1 + "p2_shot_size").state) != 3.0
