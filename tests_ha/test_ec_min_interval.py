"""The EC-correction minimum interval, in a real Home Assistant with the real controller.

An EC correction (a flush or a dilute) and the minimum-daily floor wait this long after the last shot,
so each shot drains and is read again before the next. It was a fixed 10 minutes inside the engine;
it is now a number, room-wide and per zone like the other steering settings. It is 10 on a new room
and on every room updated in place, whatever version it comes from, so nothing waters differently
until the operator changes it. The controller hands the zone's value to decide(), and one whose
integration is older than the setting uses the same 10 without raising the missing-setting alert.
"""

import re
from datetime import datetime, timedelta

import pytest
from conftest import fixture
from crop_steering_engine import decide
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, UPSTREAM_2_25_1, _upgrade

ROOM = "number.crop_steering_ec_min_interval"
ZONE = "number.crop_steering_zone_1_ec_min_interval"


def _intervals(hass):
    """Every EC-correction minimum interval number in the room: the room's own, then one per zone."""
    zone = re.compile(r"number\.crop_steering_zone_\d+_ec_min_interval$")
    zones = sorted(s.entity_id for s in hass.states.async_all("number") if zone.match(s.entity_id))
    return [ROOM, *zones]


async def _set(hass, entity_id, value):
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True
    )


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


async def test_the_zones_own_value_reaches_decide(hass, controller_for):
    await _install(hass)
    await _set(hass, ROOM, 20)
    await _set(hass, ZONE, 25)  # the zone's own value wins over the room's
    c, _fake, _clock = controller_for({})
    room = c.rooms[0]
    c.loop_once(datetime.now())  # the first pass starts the grow-day
    now = datetime.now()
    room.state[1].update(phase="P2", last_shot=now - timedelta(minutes=1))
    snap, p = c._snapshot(room, 1, now, True, False)
    assert p.p2_min_interval_min == 25
    # A dilute is wanted (pore EC a quarter over the P2 target, under max_ec, feed below it): it waits
    # the 25 minutes.
    ec = p.ec_target_p2 * 1.25
    assert ec < p.max_ec - 1
    dilute = {**snap.__dict__, "phase": "P2", "ec": ec, "ec_smooth": ec, "ec_settled": None}
    dilute.update(feed_ec=1.0, vwc=p.p2_threshold + 5, backed_up=False, steering_held=False)
    dilute.update(lights_on=True, hours_to_lights_off=6, daily_vol=0)
    for minutes, fires in ((24, False), (25, True)):
        s = snap.__class__(**{**dilute, "minutes_since_shot": minutes})
        assert (decide(s, p)[4].kind == "p2_dilute") is fires, minutes


async def test_a_controller_updated_ahead_of_a_3_11_1_integration_keeps_ten(hass, controller_for):
    """Only the controller app updated: the room's integration is 3.11.1's, which has no such number."""
    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    for entity_id in _intervals(hass):
        hass.states.async_remove(entity_id)
    assert _intervals(hass) == [ROOM] and hass.states.get(ROOM) is None
    c, _fake, _clock = controller_for({})
    room = c.rooms[0]
    for zone in sorted(room.state):
        assert c._params(room, zone).p2_min_interval_min == 10
    c.loop_once(datetime.now())
    assert ROOM not in c._defaulted_this_loop and ROOM not in c._defaulted
