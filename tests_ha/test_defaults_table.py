"""The one defaults table, in a real Home Assistant with the real controller.

The integration's entity defaults, what setup offers a new room, and the controller's fallbacks now
come from one table. Setup used to offer a new room 6 L, 2.0 L/h and 1 dripper while the same
room's numbers, left alone, started at 10 L, 1.2 L/h and 2 drippers: it now offers what the numbers
start at, says the values are generic, and the room's setup reports them as generic until changed.
Nothing an installed room runs on moves: not an entity default, not a value the operator set, and
not a controller fallback (an upgraded room whose settings all read unavailable hands decide()
exactly what the release before the table did).
"""

import dataclasses
import re

import pytest
from conftest import fixture
from custom_components.crop_steering import setup_api
from custom_components.crop_steering.config_flow import _zone_schema
from custom_components.crop_steering.generated.defaults import (
    ENTITY_DEFAULTS,
    SIZING_DEFAULTS,
)
from test_fallbacks_pinned import PARAMS_12C6D1A
from test_real_flow import ZONES, _seed, _to_zones_step
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, UPSTREAM_2_25_1, _upgrade

GENERIC = sorted(SIZING_DEFAULTS)
NEW = "tent_"  # every new room has a slug: the wizard's "Tent"


def _defaults(schema):
    return {
        str(marker): marker.default()
        for marker in schema
        if callable(getattr(marker, "default", None))
    }


def _generic(hass, entry):
    return setup_api.setup_room(hass, entry)["zones"][0]["sizing_generic"]


async def test_setup_offers_a_new_room_the_sizing_its_numbers_start_at(hass):
    # The generic values, written out: what a new room's numbers have always started at.
    assert SIZING_DEFAULTS == {
        "substrate_volume": 10.0,
        "plant_count": 4,
        "drippers_per_plant": 2,
        "dripper_flow_rate": 1.2,
    }
    assert _defaults(_zone_schema(1))["zone_1_plant_count"] == 4
    _seed(hass)
    flow_id = await _to_zones_step(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, dict(ZONES))
    assert result["step_id"] == "hardware"
    offered = _defaults(result["data_schema"].schema)
    assert {key: offered[key] for key in SIZING_DEFAULTS if key in offered} == {
        "substrate_volume": 10.0,  # was 6
        "dripper_flow_rate": 1.2,  # was 2.0
        "drippers_per_plant": 2,  # was 1
    }
    assert (offered["field_capacity"], offered["max_ec"]) == (70.0, 9.0)


async def test_a_new_room_left_on_the_generic_sizing_is_marked_until_it_is_changed(hass):
    entry = await _install(hass)
    for key in ("substrate_volume", "dripper_flow_rate", "drippers_per_plant"):
        state = hass.states.get(f"number.crop_steering_{NEW}{key}")
        assert float(state.state) == SIZING_DEFAULTS[key], key
    assert float(hass.states.get(f"number.crop_steering_{NEW}zone_1_plant_count").state) == 4
    assert _generic(hass, entry) == GENERIC

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": f"number.crop_steering_{NEW}substrate_volume", "value": 6.5},
        blocking=True,
    )
    assert _generic(hass, entry) == [k for k in GENERIC if k != "substrate_volume"]


async def test_a_room_set_up_with_its_own_sizing_is_not_marked(hass):
    entry = await _install(
        hass,
        {"substrate_volume": 3.5, "dripper_flow_rate": 4.0, "drippers_per_plant": 1},
    )
    assert _generic(hass, entry) == ["plant_count"]  # the test's tent has the 4 plants


async def test_every_number_on_a_new_room_starts_at_its_entity_default(hass):
    await _install(hass)
    seen = 0
    for state in hass.states.async_all("number"):
        key = re.sub(rf"^number\.crop_steering_{NEW}(zone_\d+_)?", "", state.entity_id)
        if key in ENTITY_DEFAULTS:
            assert float(state.state) == float(ENTITY_DEFAULTS[key]), state.entity_id
            seen += 1
    assert seen > 60, "the scan found too few numbers: fix the test"


@pytest.mark.parametrize("name", [UPSTREAM_2_25_1, JEV_3_11_1])
async def test_an_upgraded_room_with_no_setting_readable_waters_on_the_same_fallbacks(
    hass, controller_for, monkeypatch, name
):
    seed = fixture(name)
    await _upgrade(hass, name, registry_ids=seed.get("registry"))
    c, fake, _clock = controller_for({})
    room = c.rooms[0]
    room.strategy_snapshot = None  # no grow plan: the settings themselves are what is read
    for entity_id in list(fake.states):
        if entity_id.startswith(("number.crop_steering_", "input_number.crop_steering_")):
            fake.set_state(entity_id, "unavailable")
    handed = []
    original = c._params.__globals__["validate_params"]

    def validate(raw):
        handed.append(raw)
        return original(raw)

    monkeypatch.setitem(c._params.__globals__, "validate_params", validate)
    for zone in sorted(room.state):
        c._params(room, zone, ec_known=False)
    assert len(handed) == len(room.state) >= 1
    for raw in handed:
        assert dataclasses.asdict(raw) == dataclasses.asdict(PARAMS_12C6D1A)
