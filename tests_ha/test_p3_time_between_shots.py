"""P3 Time Between Shots, in a real Home Assistant with the real controller.

A rescue goes in under the probe and takes minutes to reach it, so a zone still reading under the
rescue level a pass later got another one every minute all night. The setting is a number, room-wide
and per zone like the other steering settings, 10 minutes unless changed, and 0 turns it off. A new
room has it at 10, and so has every room updated in place, whatever version it comes from: a new
entity has no saved value. A controller whose integration is older than the setting uses the same 10
without raising the missing-setting alert.
"""

import re
from datetime import datetime, timedelta

import pytest
from conftest import fixture, room_of
from crop_steering_engine import decide
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, UPSTREAM_2_25_1, _upgrade

ROOM = "number.crop_steering_p3_time_between_shots"
ZONE = "number.crop_steering_zone_1_p3_time_between_shots"
RESCUE_LEVEL = "number.crop_steering_zone_1_p3_emergency_vwc_threshold"
WAITING = "sensor.crop_steering_zone_1_waiting_for_app"


def _new(entity_id):
    """The same id on a new room, which has a slug: the wizard's "Tent" is tent_."""
    return entity_id.replace("crop_steering_", "crop_steering_tent_", 1)


def _gaps(hass, prefix=""):
    """Every P3 Time Between Shots number in the room: the room's own, then one per zone."""
    zone = re.compile(rf"number\.crop_steering_{prefix}zone_\d+_p3_time_between_shots$")
    zones = sorted(s.entity_id for s in hass.states.async_all("number") if zone.match(s.entity_id))
    return [ROOM.replace("crop_steering_", f"crop_steering_{prefix}", 1), *zones]


async def _set(hass, entity_id, value):
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True
    )


async def _night(hass, prefix=""):
    """Lights off around now, so the zone is in P3 whenever this runs."""
    now = datetime.now()
    await _set(hass, f"number.crop_steering_{prefix}lights_on_hour", (now.hour + 4) % 24)
    await _set(hass, f"number.crop_steering_{prefix}lights_off_hour", (now.hour - 8) % 24)


async def test_a_new_room_spaces_its_p3_shots_ten_minutes_apart(hass):
    await _install(hass)
    assert _gaps(hass, "tent_") == [_new(ROOM), _new(ZONE)]
    for entity_id in _gaps(hass, "tent_"):
        state = hass.states.get(entity_id)
        assert float(state.state) == 10
        assert (state.attributes["min"], state.attributes["max"]) == (0, 60)
        assert state.attributes["unit_of_measurement"] == "min"


@pytest.mark.parametrize(
    "name", ["entry_2_17_wizard.json", UPSTREAM_2_25_1, JEV_3_11_1]
)
async def test_a_room_updated_in_place_has_it_at_ten_minutes_and_nothing_else_moves(hass, name):
    seed = fixture(name)
    await _upgrade(hass, name, registry_ids=seed.get("registry"))
    gaps = _gaps(hass)
    assert len(gaps) == 1 + seed["data"]["num_zones"]
    assert [float(hass.states.get(e).state) for e in gaps] == [10] * len(gaps)
    for entity_id, saved in seed["operator_tuned_numbers"].items():
        tuned = saved[0] if isinstance(saved, list) else saved
        state = hass.states.get(entity_id).state
        if entity_id.startswith("number."):
            assert float(state) == float(tuned), entity_id
        else:
            assert state == tuned, entity_id


async def test_the_controller_spaces_a_rescue_by_the_zones_own_time_and_says_when(
    hass, controller_for
):
    await _install(hass)
    await _night(hass, "tent_")
    await _set(hass, _new(RESCUE_LEVEL), 50)  # over the probe's reading, under the re-water level: a rescue is wanted
    await _set(hass, _new(ZONE), 12)  # the zone's own value wins over the room's 10
    c, fake, _clock = controller_for({})
    room = room_of(c)
    c.loop_once(datetime.now())  # the first pass starts the grow-day
    now = datetime.now()
    room.state[1].update(phase="P3", last_shot=now - timedelta(minutes=1))
    snap, p = c._snapshot(room, 1, now, False, False)
    assert p.p3_time_between_min == 12
    assert snap.vwc < p.p3_emergency_floor  # a rescue is wanted...
    assert decide(snap, p)[2] is False  # ...and waits
    later = snap.__class__(**{**snap.__dict__, "minutes_since_shot": 12})
    assert decide(later, p)[4].kind == "p3_emergency"

    c.loop_once(now)
    for entity_id, (state, attributes) in fake.sets.items():  # its REST writes, into HA
        hass.states.async_set(entity_id, state, attributes)
    await hass.async_block_till_done()
    conditions = {c["rule"]: c for c in hass.states.get(_new(WAITING)).attributes["conditions"]}
    assert 10.5 <= conditions["p3_emergency"]["in_min"] <= 11.0


async def test_a_controller_updated_ahead_of_a_3_11_1_integration_uses_ten_minutes(
    hass, controller_for
):
    """Only the controller app updated: the room's integration is 3.11.1's, which has no such number."""
    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    for entity_id in _gaps(hass):
        hass.states.async_remove(entity_id)
    assert _gaps(hass) == [ROOM] and hass.states.get(ROOM) is None
    c, _fake, _clock = controller_for({})
    room = c.rooms[0]
    for zone in sorted(room.state):
        assert c._params(room, zone).p3_time_between_min == 10
    c.loop_once(datetime.now())
    assert ROOM not in c._defaulted_this_loop and ROOM not in c._defaulted
