"""The EC-correction minimum interval, in a real Home Assistant with the real controller.

An EC correction (a flush or a dilute) and the minimum-daily floor wait this long after the last shot,
so each shot drains and is read again before the next. It was a fixed 10 minutes inside the engine;
it is now a number, room-wide and per zone like the other steering settings. It is 10 on a new room
and on every room updated in place, whatever version it comes from, so nothing waters differently
until the operator changes it.
"""

import re

import pytest
from conftest import fixture
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, UPSTREAM_2_25_1, _upgrade

ROOM = "number.crop_steering_ec_min_interval"
ZONE = "number.crop_steering_zone_1_ec_min_interval"


def _intervals(hass):
    """Every EC-correction minimum interval number in the room: the room's own, then one per zone."""
    zone = re.compile(r"number\.crop_steering_zone_\d+_ec_min_interval$")
    zones = sorted(s.entity_id for s in hass.states.async_all("number") if zone.match(s.entity_id))
    return [ROOM, *zones]


async def test_a_new_room_has_todays_ten_minutes(hass):
    await _install(hass)
    assert _intervals(hass) == [ROOM, ZONE]
    for entity_id in _intervals(hass):
        state = hass.states.get(entity_id)
        assert float(state.state) == 10
        assert (state.attributes["min"], state.attributes["max"]) == (1, 120)
        assert state.attributes["unit_of_measurement"] == "min"


@pytest.mark.parametrize("name", ["entry_2_17_wizard.json", UPSTREAM_2_25_1, JEV_3_11_1])
async def test_a_room_updated_in_place_gets_it_at_ten_and_nothing_else_moves(hass, name):
    seed = fixture(name)
    await _upgrade(hass, name, registry_ids=seed.get("registry"))
    intervals = _intervals(hass)
    assert len(intervals) == 1 + seed["data"]["num_zones"]
    assert [float(hass.states.get(e).state) for e in intervals] == [10] * len(intervals)
    for entity_id, saved in seed["operator_tuned_numbers"].items():
        tuned = saved[0] if isinstance(saved, list) else saved
        state = hass.states.get(entity_id).state
        if entity_id.startswith("number."):
            assert float(state) == float(tuned), entity_id
        else:
            assert state == tuned, entity_id
