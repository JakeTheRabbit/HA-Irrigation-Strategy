"""P3 Dryback Hold, in a real Home Assistant with the real controller.

P3 waters only below the rescue level, so a night that dries faster than the day goes on past the
dryback target to the rescue level. A new per-zone switch lets P3 hold the overnight dryback at its
target instead: a zone that dries to the day's peak less its dryback target gets a shot the size of its
rescue shot. It is off on a new room and on every room updated in place, and off (or missing, under an
older integration) P3 decides exactly as before.
"""

import re
from datetime import datetime

import pytest
from conftest import fixture, room_of, switch_calls
from test_real_flow import VALVE
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, UPSTREAM_2_25_1, _upgrade

# The wizard's room is new, so it has a slug: "Tent" is tent_ (an upgraded room keeps no prefix).
KILL = "switch.crop_steering_tent_engine_enabled"
ARMED = (
    KILL,
    "switch.crop_steering_tent_system_enabled",
    "switch.crop_steering_tent_auto_irrigation_enabled",
    "switch.crop_steering_tent_zone_1_enabled",
)
HOLD = "switch.crop_steering_tent_zone_1_p3_dryback_hold"
STATUS = "sensor.crop_steering_tent_zone_1_status_app"
WAITING = "sensor.crop_steering_tent_zone_1_waiting_for_app"


def _holds(hass, prefix=""):
    pattern = re.compile(rf"switch\.crop_steering_{prefix}zone_\d+_p3_dryback_hold$")
    return sorted(s.entity_id for s in hass.states.async_all("switch") if pattern.match(s.entity_id))


async def _set(hass, entity_id, value):
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True
    )


async def _night(hass):
    """Lights off around now, so the new room's zone is in P3 whenever this runs."""
    now = datetime.now()
    await _set(hass, "number.crop_steering_tent_lights_on_hour", (now.hour + 4) % 24)
    await _set(hass, "number.crop_steering_tent_lights_off_hour", (now.hour - 8) % 24)


async def test_a_new_room_has_the_hold_off_on_every_zone(hass):
    await _install(hass)
    assert _holds(hass, "tent_") == [HOLD]
    assert hass.states.get(HOLD).state == "off"


@pytest.mark.parametrize("name", ["entry_2_17_wizard.json", UPSTREAM_2_25_1, JEV_3_11_1])
async def test_a_room_updated_in_place_has_it_off_and_nothing_else_moves(hass, name):
    seed = fixture(name)
    await _upgrade(hass, name, registry_ids=seed.get("registry"))
    holds = _holds(hass)
    assert len(holds) == seed["data"]["num_zones"]
    assert [hass.states.get(e).state for e in holds] == ["off"] * len(holds)
    for entity_id, saved in seed["operator_tuned_numbers"].items():
        tuned = saved[0] if isinstance(saved, list) else saved
        state = hass.states.get(entity_id).state
        if entity_id.startswith("number."):
            assert float(state) == float(tuned), entity_id
        else:
            assert state == tuned, entity_id


async def _armed_night(hass, controller_for, hold):
    """A zone whose day peaked at 70%: a 30% dryback ends at 49%, and the seeded probe reads 41%, above
    the 40% rescue level. One controller pass; returns the controller, its fake REST side and the room."""
    await _install(hass)
    await _night(hass)
    for mode in ("vegetative", "generative"):  # whichever mode the zone steers in
        await _set(hass, f"number.crop_steering_tent_zone_1_{mode}_dryback_target", 30)
    await hass.services.async_call(
        "switch", "turn_on" if hold else "turn_off", {"entity_id": HOLD}, blocking=True
    )
    c, fake, _clock = controller_for({"enable_flag": KILL})
    room = room_of(c)
    for switch in ARMED:
        fake.set_state(switch, "on")
    c.loop_once(datetime.now())  # the first pass starts the grow-day
    room.state[1].update(phase="P3", peak=70.0, last_shot=None)
    now = datetime.now()
    snap, p = c._snapshot(room, 1, now, False, False)
    assert (p.p3_hold, p.dryback_target, p.p3_emergency_floor, snap.vwc) == (hold, 30, 40, 41)
    fake.calls.clear()
    c.loop_once(now)
    for entity_id, (state, attributes) in fake.sets.items():  # its REST writes, into HA
        hass.states.async_set(entity_id, state, attributes)
    await hass.async_block_till_done()
    return c, fake, room


async def test_switched_on_a_zone_dried_to_its_target_gets_a_rescue_sized_shot(hass, controller_for):
    _c, fake, room = await _armed_night(hass, controller_for, hold=True)
    assert switch_calls(fake) == [("turn_on", VALVE), ("turn_off", VALVE)]
    assert room.state[1]["shots"] == 1
    assert hass.states.get(STATUS).state == "Holding dryback"
    conditions = {item["rule"]: item for item in hass.states.get(WAITING).attributes["conditions"]}
    assert (conditions["p3_hold"]["value"], conditions["p3_hold"]["dryback"]) == (49.0, 30)


async def test_switched_off_the_zone_dries_on_as_before(hass, controller_for):
    _c, fake, room = await _armed_night(hass, controller_for, hold=False)
    assert switch_calls(fake) == []
    assert room.state[1]["shots"] == 0
    conditions = [item["rule"] for item in hass.states.get(WAITING).attributes["conditions"]]
    assert "p3_hold" not in conditions and "p3_emergency" in conditions


async def test_a_controller_updated_ahead_of_a_3_11_1_integration_leaves_the_hold_off(
    hass, controller_for
):
    """Only the controller app updated: the room's integration is 3.11.1's, which has no such switch."""
    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    for entity_id in _holds(hass):
        hass.states.async_remove(entity_id)
    assert _holds(hass) == []
    c, _fake, _clock = controller_for({})
    room = c.rooms[0]
    for zone in sorted(room.state):
        assert c._params(room, zone).p3_hold is False
