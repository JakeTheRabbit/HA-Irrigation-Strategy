"""P1 Extra Shot Rise and P1 Maximum Extra Shots, in a real Home Assistant with the real controller.

Once P1 reads its target it gives one more shot, and another while each raises the settled moisture reading by the
rise, up to the maximum extra shots. Both are numbers, room-wide and per zone like the other steering settings,
0.5 and 3 unless changed: the rule as it was, now with a cap. A new room has them at 0.5 and 3, and so has every
room updated in place, whatever version it comes from, with nothing it restored moved. A controller whose
integration is older than the settings uses the same 0.5 and 3 without raising the missing-setting alert.
"""

import re
from datetime import datetime

import pytest
from conftest import fixture
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, UPSTREAM_2_25_1, _upgrade

SETTINGS = {"p1_rise_pts": (0.5, 0.1, 5), "p1_maximum_extra_shots": (3, 1, 10)}


def _numbers(hass, key):
    """The room's own number for this setting, then one per zone."""
    zone = re.compile(rf"number\.crop_steering_zone_\d+_{key}$")
    zones = sorted(s.entity_id for s in hass.states.async_all("number") if zone.match(s.entity_id))
    return [f"number.crop_steering_{key}", *zones]


async def test_a_new_room_has_the_rule_as_it_was_with_a_cap_of_three(hass):
    await _install(hass)
    for key, (default, low, high) in SETTINGS.items():
        assert _numbers(hass, key) == [f"number.crop_steering_{key}", f"number.crop_steering_zone_1_{key}"]
        for entity_id in _numbers(hass, key):
            state = hass.states.get(entity_id)
            assert float(state.state) == default, entity_id
            assert (state.attributes["min"], state.attributes["max"]) == (low, high)


@pytest.mark.parametrize("name", ["entry_2_17_wizard.json", UPSTREAM_2_25_1, JEV_3_11_1])
async def test_a_room_updated_in_place_gets_them_and_nothing_it_restored_moves(hass, name):
    seed = fixture(name)
    await _upgrade(hass, name, registry_ids=seed.get("registry"))
    for key, (default, _low, _high) in SETTINGS.items():
        numbers = _numbers(hass, key)
        assert len(numbers) == 1 + seed["data"]["num_zones"]
        assert [float(hass.states.get(e).state) for e in numbers] == [default] * len(numbers)
    for entity_id, saved in seed["operator_tuned_numbers"].items():
        tuned = saved[0] if isinstance(saved, list) else saved
        state = hass.states.get(entity_id).state
        if entity_id.startswith("number."):
            assert float(state) == float(tuned), entity_id
        else:
            assert state == tuned, entity_id


async def test_the_controller_reads_the_zones_own_values(hass, controller_for):
    await _install(hass)
    for entity_id, value in (("number.crop_steering_zone_1_p1_rise_pts", 0.8),
                             ("number.crop_steering_zone_1_p1_maximum_extra_shots", 2)):
        await hass.services.async_call(
            "number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True
        )
    c, _fake, _clock = controller_for({})
    p = c._params(c.rooms[0], 1)
    assert (p.p1_rise_pts, p.p1_max_extra_shots) == (0.8, 2)


async def test_a_controller_updated_ahead_of_a_3_11_1_integration_uses_the_rule_as_it_was(
    hass, controller_for
):
    """Only the controller app updated: the room's integration is 3.11.1's, which has neither number."""
    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    for key in SETTINGS:
        for entity_id in _numbers(hass, key):
            hass.states.async_remove(entity_id)
    c, _fake, _clock = controller_for({})
    room = c.rooms[0]
    for zone in sorted(room.state):
        p = c._params(room, zone)
        assert (p.p1_rise_pts, p.p1_max_extra_shots) == (0.5, 3)
    c.loop_once(datetime.now())
    assert not {e for e in c._defaulted_this_loop | set(c._defaulted) if "p1_rise" in e or "extra_shots" in e}
