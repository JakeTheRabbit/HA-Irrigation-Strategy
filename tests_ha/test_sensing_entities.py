"""The read-only sensing toggles, and the optional leaf temperature sensor, in a real Home Assistant: a new room and
an upgraded one get them switched off, nothing else moves, and a leaf sensor mapped for the room or for one zone
reaches the descriptor (display only) without holding the controller.
"""

import pytest
from conftest import fixture
from homeassistant.core import Context
from homeassistant.helpers import entity_registry as er
from test_declared_plumbing import NEW_DESCRIPTOR, UPGRADED_KILL
from test_setup_entry import _install
from test_upgrade_in_place import DESCRIPTOR, JEV_3_11_1, UPSTREAM_2_25_1, _upgrade

DOMAIN = "crop_steering"
LEAF = "sensor.tent_leaf_temperature"
ZONE_LEAF = "sensor.zone_1_leaf_temperature"


def _toggles(prefix):
    return {
        f"switch.crop_steering_{prefix}water_vpd_insight": "off",
        f"switch.crop_steering_{prefix}plant_stress_card": "off",
        f"select.crop_steering_{prefix}shot_check": "off",
        f"number.crop_steering_{prefix}cwsi_lower_baseline": "0.0",
        f"number.crop_steering_{prefix}cwsi_upper_baseline": "0.0",
    }


async def test_a_new_room_gets_every_toggle_off(hass):
    await _install(hass)
    for entity_id, state in _toggles("tent_").items():
        assert hass.states.get(entity_id).state == state, entity_id
    shot_check = hass.states.get("select.crop_steering_tent_shot_check")
    assert shot_check.attributes["options"] == ["off", "table", "table_and_alert"]
    descriptor = hass.states.get(NEW_DESCRIPTOR).attributes
    assert "leaf_temperature_sensor" not in descriptor and "zone_leaf_sensors" not in descriptor


@pytest.mark.parametrize("name", [UPSTREAM_2_25_1, JEV_3_11_1])
async def test_an_upgraded_room_gets_them_off_and_nothing_else_moves(hass, controller_for, name):
    seed = fixture(name)
    await _upgrade(hass, name, registry_ids=seed.get("registry"))
    for entity_id, state in _toggles("").items():
        assert hass.states.get(entity_id).state == state, entity_id
    registry = er.async_get(hass)
    assert [e for e in (seed.get("registry") or {}) if registry.async_get(e) is None] == []
    descriptor = hass.states.get(DESCRIPTOR).attributes
    assert "zone_leaf_sensors" not in descriptor and "leaf_temperature_sensor" not in descriptor
    for entity_id, saved in seed["operator_tuned_numbers"].items():
        tuned = str(saved[0] if isinstance(saved, list) else saved)
        state = hass.states.get(entity_id).state
        if entity_id.startswith("number."):
            state, tuned = float(state), float(tuned)
        assert state == tuned, entity_id
    # The controller reads the new select and switch as off: no table, no record.
    hass.states.async_set(UPGRADED_KILL, "on")
    c, _fake, _clock = controller_for(seed.get("addon_options") or {}, saved_state=seed.get("controller_saved"))
    room = c.rooms[0]
    c._sensing_options(room)
    assert (room._shot_check, room._water_vpd_on) == ("off", False)


async def test_a_room_leaf_sensor_reaches_the_descriptor(hass):
    hass.states.async_set(LEAF, "24.1", {"unit_of_measurement": "°C"})
    await _install(hass, {"leaf_temperature_sensor": LEAF})
    assert hass.states.get(NEW_DESCRIPTOR).attributes["leaf_temperature_sensor"] == LEAF


async def test_a_zone_maps_its_own_leaf_sensor_through_setup(hass, hass_admin_user):
    hass.states.async_set(ZONE_LEAF, "23.4", {"unit_of_measurement": "°C"})
    await _install(hass)

    async def call(name, data=None):
        return await hass.services.async_call(
            DOMAIN, name, data or {}, blocking=True, return_response=True, context=Context(user_id=hass_admin_user.id)
        )

    (room,) = (await call("setup_read"))["rooms"]
    assert room["zones"][0]["leaf_temperature_sensor"] == ""
    zones = [{**room["zones"][0], "leaf_temperature_sensor": ZONE_LEAF}]
    payload = {"entry_id": room["entry_id"], "expected_revision": room["revision"], "room_name": room["room_name"],
               "active": room["active"], "hardware": dict(room["hardware"]), "zones": zones,
               **({"plumbing": room["plumbing"]} if room.get("plumbing") else {})}
    await call("setup_save", payload)
    await hass.async_block_till_done()
    (after,) = (await call("setup_read"))["rooms"]
    assert after["zones"][0]["leaf_temperature_sensor"] == ZONE_LEAF
    assert hass.states.get(NEW_DESCRIPTOR).attributes["zone_leaf_sensors"] == {"1": ZONE_LEAF}
