"""Limits that follow each zone's size, in a real Home Assistant.

The daily water limit and the maximum shot length used to be fixed (200 L, 3600 s) whatever the
zone. They now follow plants x litres per plant and dripper flow. A value an upgraded room already
holds above its new limit is never moved: it reads back unchanged, one Repairs card names it, and
the limit applies to the next edit."""

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import issue_registry as ir

from conftest import fixture
from custom_components.crop_steering.bounds import daily_volume_bound, shot_duration_bound
from custom_components.crop_steering.generated.defaults import ZONE_BOUNDS
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, _upgrade

DOMAIN = "crop_steering"
ISSUE = "outside_zone_bounds"
DAILY_2 = "number.crop_steering_zone_2_max_daily_volume"
DURATION = "number.crop_steering_max_shot_duration"


def test_the_hard_limits():
    assert ZONE_BOUNDS == {
        "max_daily_volume": {"substrate_multiple": 4.0, "floor": 20.0},
        "max_shot_duration": {"substrate_multiple": 1.0, "floor": 900.0},
    }
    assert daily_volume_bound(100, 10) == 4000.0  # a big zone: far over the old fixed 200 L
    assert daily_volume_bound(4, 2) == 32.0
    assert daily_volume_bound(1, 0.65) == 20.0  # never under the floor (the entity default)
    assert shot_duration_bound(10, 2, 2.0) == 9000.0  # 10 L at 4 L/h per plant
    assert shot_duration_bound(0.65, 1, 4.0) == 900.0  # never under the floor (the entity default)
    for unreadable in ((None, 10), (0, 10), ("unknown", 10)):
        assert daily_volume_bound(*unreadable) is None
    assert shot_duration_bound(10, 2, 0) is None


async def _set(hass, entity_id, value):
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True
    )


def _card(hass):
    return ir.async_get(hass).async_get_issue(DOMAIN, ISSUE)


async def test_a_large_zone_can_be_given_more_than_the_old_fixed_limit(hass):
    await _install(hass)
    await _set(hass, "number.crop_steering_zone_1_plant_count", 100)
    await _set(hass, "number.crop_steering_substrate_volume", 10)
    daily = "number.crop_steering_zone_1_max_daily_volume"
    assert hass.states.get(daily).attributes["max"] == 4000.0
    await _set(hass, daily, 1000)  # the old entity refused anything over 200
    assert float(hass.states.get(daily).state) == 1000.0
    with pytest.raises(ServiceValidationError):
        await _set(hass, daily, 4001)
    assert float(hass.states.get(daily).state) == 1000.0
    assert _card(hass) is None


async def test_an_upgraded_room_keeps_values_above_the_new_limit_and_repairs_names_them(hass):
    seed = fixture(JEV_3_11_1)
    # The old room: 2 L per plant (zone 2 has 10 plants, 2 drippers of 2 L/h each) and two values
    # the old fixed limits allowed but the zone's size now does not (80 L and 1800 s).
    await _upgrade(
        hass,
        JEV_3_11_1,
        registry_ids=seed["registry"],
        restored={
            "number.crop_steering_substrate_volume": "2.0",
            DAILY_2: "150.0",
            DURATION: "3000",
        },
    )
    assert float(hass.states.get(DAILY_2).state) == 150.0  # kept, nothing moved
    assert float(hass.states.get(DURATION).state) == 3000.0
    card = _card(hass)
    assert card is not None and card.translation_key == ISSUE
    assert card.translation_placeholders["count"] == "2"
    named = card.translation_placeholders["settings"]
    assert f"`{DAILY_2}`: 150 (limit 80)" in named
    assert f"`{DURATION}`: 3000 (limit 1800)" in named
    assert "zone_1_max_daily_volume" not in named  # 12 plants x 2 L x 4 = 96 L, and it holds 20

    # The next edit is bounded, and a refused edit moves nothing.
    with pytest.raises(ServiceValidationError):
        await _set(hass, DAILY_2, 100)
    assert float(hass.states.get(DAILY_2).state) == 150.0
    await _set(hass, DAILY_2, 60)
    named = _card(hass).translation_placeholders["settings"]
    assert DAILY_2 not in named and DURATION in named
    await _set(hass, DURATION, 1800)
    assert _card(hass) is None  # every setting within its limit: the card clears itself


async def test_an_upgraded_room_within_every_limit_gets_no_card(hass):
    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    assert _card(hass) is None
    assert hass.states.get(DAILY_2).attributes["max"] == 400.0  # 10 plants x 10 L x 4
    assert hass.states.get(DURATION).attributes["max"] == 9000.0
