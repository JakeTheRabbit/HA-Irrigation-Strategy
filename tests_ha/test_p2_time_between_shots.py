"""P2 Time Between Shots, in a real Home Assistant with the real controller.

A top-up goes in under the probe and takes minutes to reach it, so a zone still reading under its
re-water threshold a pass later got another top-up every minute until the first one arrived. The
setting is a number, room-wide and per zone like the other steering settings, and 0 turns it off.
It is 0 on a new room and on every room updated in place, whatever version it comes from, so
nothing waters differently until the operator sets it. A controller whose integration is older than
the setting uses the same 0 without raising the missing-setting alert.
"""

import re
from datetime import datetime, timedelta

import pytest
from conftest import fixture
from crop_steering_engine import decide
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, UPSTREAM_2_25_1, _upgrade

ROOM = "number.crop_steering_p2_time_between_shots"
ZONE = "number.crop_steering_zone_1_p2_time_between_shots"
WAITING = "sensor.crop_steering_zone_1_waiting_for_app"


def _gaps(hass):
    """Every P2 Time Between Shots number in the room: the room's own, then one per zone."""
    zone = re.compile(r"number\.crop_steering_zone_\d+_p2_time_between_shots$")
    zones = sorted(s.entity_id for s in hass.states.async_all("number") if zone.match(s.entity_id))
    return [ROOM, *zones]


async def _set(hass, entity_id, value):
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True
    )


async def _daytime(hass):
    """Lights around now, so the zone is mid-photoperiod whenever this runs."""
    now = datetime.now()
    await _set(hass, "number.crop_steering_lights_on_hour", (now.hour - 4) % 24)
    await _set(hass, "number.crop_steering_lights_off_hour", (now.hour + 8) % 24)


async def test_a_new_room_has_it_off(hass):
    await _install(hass)
    assert _gaps(hass) == [ROOM, ZONE]
    for entity_id in _gaps(hass):
        state = hass.states.get(entity_id)
        assert float(state.state) == 0
        assert (state.attributes["min"], state.attributes["max"]) == (0, 60)
        assert state.attributes["unit_of_measurement"] == "min"


@pytest.mark.parametrize("name", ["entry_2_17_wizard.json", UPSTREAM_2_25_1, JEV_3_11_1])
async def test_a_room_updated_in_place_has_it_off_and_nothing_else_moves(hass, name):
    seed = fixture(name)
    await _upgrade(hass, name, registry_ids=seed.get("registry"))
    gaps = _gaps(hass)
    assert len(gaps) == 1 + seed["data"]["num_zones"]
    assert [float(hass.states.get(e).state) for e in gaps] == [0] * len(gaps)
    for entity_id, saved in seed["operator_tuned_numbers"].items():
        tuned = saved[0] if isinstance(saved, list) else saved
        state = hass.states.get(entity_id).state
        if entity_id.startswith("number."):
            assert float(state) == float(tuned), entity_id
        else:
            assert state == tuned, entity_id


async def test_the_controller_waits_the_zones_own_time_and_says_when(hass, controller_for):
    await _install(hass)
    await _daytime(hass)
    await _set(hass, ROOM, 5)
    await _set(hass, ZONE, 8)  # the zone's own value wins over the room's
    c, fake, _clock = controller_for({})
    room = c.rooms[0]
    c.loop_once(datetime.now())  # the first pass starts the grow-day
    now = datetime.now()
    room.state[1].update(phase="P2", last_shot=now - timedelta(minutes=1))
    snap, p = c._snapshot(room, 1, now, True, False)
    assert p.p2_time_between_min == 8
    assert snap.vwc < p.p2_threshold  # a top-up is wanted...
    assert decide(snap, p)[2] is False  # ...and waits
    later = snap.__class__(**{**snap.__dict__, "minutes_since_shot": 8})
    assert decide(later, p)[4].kind == "p2_topup"

    c.loop_once(now)
    for entity_id, (state, attributes) in fake.sets.items():  # its REST writes, into HA
        hass.states.async_set(entity_id, state, attributes)
    await hass.async_block_till_done()
    conditions = {c["rule"]: c for c in hass.states.get(WAITING).attributes["conditions"]}
    assert 6.5 <= conditions["p2_topup"]["in_min"] <= 7.0


async def test_a_controller_updated_ahead_of_a_3_11_1_integration_has_it_off(hass, controller_for):
    """Only the controller app updated: the room's integration is 3.11.1's, which has no such number."""
    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    for entity_id in _gaps(hass):
        hass.states.async_remove(entity_id)
    assert _gaps(hass) == [ROOM] and hass.states.get(ROOM) is None
    c, _fake, _clock = controller_for({})
    room = c.rooms[0]
    for zone in sorted(room.state):
        assert c._params(room, zone).p2_time_between_min == 0
    c.loop_once(datetime.now())
    assert ROOM not in c._defaulted_this_loop and ROOM not in c._defaulted
