"""The runoff estimator's settings and its AC and dehumidifier mapping, in a real Home Assistant: off and neutral on a
new room and an upgraded one with nothing else moving, and units mapped through setup reach the descriptor, which
the controller reads (read only)."""

import pytest
from conftest import fixture
from homeassistant.core import Context
from homeassistant.helpers import entity_registry as er
from test_declared_plumbing import NEW_DESCRIPTOR
from test_setup_entry import _install
from test_upgrade_in_place import DESCRIPTOR, JEV_3_11_1, UPSTREAM_2_25_1, _upgrade

DOMAIN = "crop_steering"
AC = "switch.tent_ac"
DEHUM = "sensor.tent_dehumidifier_power"


def _settings(prefix):
    return {
        f"select.crop_steering_{prefix}runoff_estimator": "off",
        f"number.crop_steering_{prefix}sump_litres_per_run": 0.0,
        f"number.crop_steering_{prefix}sump_pump_flow_lpm": 0.0,
        f"number.crop_steering_{prefix}runoff_attribution_min": 90.0,
        f"number.crop_steering_{prefix}hvac_run_power_w": 50.0,
    }


def _check(hass, prefix):
    for entity_id, want in _settings(prefix).items():
        state = hass.states.get(entity_id).state
        assert (float(state) if entity_id.startswith("number.") else state) == want, entity_id


async def test_a_new_room_has_the_estimator_off(hass):
    await _install(hass)
    _check(hass, "tent_")
    options = hass.states.get("select.crop_steering_tent_runoff_estimator").attributes["options"]
    assert options == ["off", "shadow", "shown_alerts", "ai"]
    descriptor = hass.states.get(NEW_DESCRIPTOR).attributes
    assert "ac_entities" not in descriptor and "dehumidifier_entities" not in descriptor


@pytest.mark.parametrize("name", [UPSTREAM_2_25_1, JEV_3_11_1])
async def test_an_upgraded_room_has_it_off_and_nothing_else_moves(hass, name):
    seed = fixture(name)
    await _upgrade(hass, name, registry_ids=seed.get("registry"))
    _check(hass, "")
    registry = er.async_get(hass)
    assert [e for e in (seed.get("registry") or {}) if registry.async_get(e) is None] == []
    descriptor = hass.states.get(DESCRIPTOR).attributes
    assert "ac_entities" not in descriptor and "dehumidifier_entities" not in descriptor
    for entity_id, saved in seed["operator_tuned_numbers"].items():
        tuned = str(saved[0] if isinstance(saved, list) else saved)
        state = hass.states.get(entity_id).state
        if entity_id.startswith("number."):
            state, tuned = float(state), float(tuned)
        assert state == tuned, entity_id


async def test_acs_and_dehumidifiers_map_through_setup_and_reach_the_controller(
    hass, hass_admin_user, controller_for
):
    hass.states.async_set(AC, "off")
    hass.states.async_set(DEHUM, "0", {"unit_of_measurement": "W"})
    await _install(hass)

    async def call(name, data=None):
        return await hass.services.async_call(
            DOMAIN, name, data or {}, blocking=True, return_response=True, context=Context(user_id=hass_admin_user.id)
        )

    (room,) = (await call("setup_read"))["rooms"]
    assert (room["hardware"]["ac_entities"], room["hardware"]["dehumidifier_entities"]) == ([], [])
    hardware = {**room["hardware"], "ac_entities": [AC], "dehumidifier_entities": [DEHUM]}
    payload = {"entry_id": room["entry_id"], "expected_revision": room["revision"], "room_name": room["room_name"],
               "active": room["active"], "hardware": hardware, "zones": room["zones"],
               **({"plumbing": room["plumbing"]} if room.get("plumbing") else {})}
    await call("setup_save", payload)
    await hass.async_block_till_done()
    descriptor = hass.states.get(NEW_DESCRIPTOR).attributes
    assert (descriptor["ac_entities"], descriptor["dehumidifier_entities"]) == ([AC], [DEHUM])
    (after,) = (await call("setup_read"))["rooms"]
    assert after["hardware"]["ac_entities"] == [AC]
    # a unit Home Assistant does not have is refused, and nothing is saved
    bad = {**payload, "expected_revision": after["revision"], "hardware": {**hardware, "ac_entities": ["switch.nope"]}}
    with pytest.raises(Exception):
        await call("setup_save", bad)
    c, _fake, _clock = controller_for({})
    c._apply_setup_descriptors()
    assert [r.hvac_units for r in c.rooms if r.prefix == "tent_"] == [[AC, DEHUM]]
