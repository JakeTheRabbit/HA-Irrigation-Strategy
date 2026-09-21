"""The integration and the REAL controller, across a room being deleted and set up again.

The controller process outlives the room: nobody restarts an add-on because they re-ran a setup
wizard. It had adopted the first room; the second publishes the same entity ids and a setup
revision that starts again at 1, so the controller took it for the room it already had and went
on driving the first room's valve. See addons/f2_control/tests/test_recreated_room.py for the
controller's own tests; this is the two halves together, in a real Home Assistant.
"""

import json
from datetime import datetime

from conftest import fixture, switch_calls
from test_real_flow import VALVE, ZONES
from test_setup_entry import _install
from test_upgrade_in_place import _upgrade

DOMAIN = "crop_steering"
KILL = "switch.crop_steering_engine_enabled"
DESCRIPTOR = "sensor.crop_steering_engine_config"
OTHER_VALVE = "switch.gt4_irrigation_switch"
ARMED = (
    KILL,
    "switch.crop_steering_system_enabled",
    "switch.crop_steering_auto_irrigation_enabled",
    "switch.crop_steering_zone_1_enabled",
)


def _see(hass, fake):
    """The controller reads Home Assistant over REST every loop: show it the present state, and
    forget what no longer exists."""
    current = {state.entity_id for state in hass.states.async_all()}
    for entity_id in [e for e in fake.states if e not in current]:
        del fake.states[entity_id]
    for state in hass.states.async_all():
        attributes = json.loads(json.dumps(dict(state.attributes), default=str))
        fake.set_state(state.entity_id, state.state, attributes)


async def test_the_descriptor_says_which_room_it_is(hass):
    entry = await _install(hass)
    assert hass.states.get(DESCRIPTOR).attributes["entry_id"] == entry.entry_id


async def test_a_room_set_up_again_with_another_valve_is_driven_through_the_new_valve(
    hass, controller_for, monkeypatch
):
    first = await _install(hass)
    c, fake, _clock = controller_for({"enable_flag": KILL})
    room = c.rooms[0]
    assert room.hw["valves"] == {1: VALVE} and room.setup_revision == 1

    # Setup is done again, this time on a different switch. The controller keeps running.
    assert await hass.config_entries.async_remove(first.entry_id)
    await hass.async_block_till_done()
    hass.states.async_set(OTHER_VALVE, "off")
    monkeypatch.setitem(ZONES, "zone_1_switch", OTHER_VALVE)
    second = await _install(hass)
    assert second.entry_id != first.entry_id
    assert hass.states.get(DESCRIPTOR).attributes["setup_revision"] == 1  # not higher than adopted

    _see(hass, fake)
    c._rediscover(datetime.now())
    assert room.hw["valves"] == {1: OTHER_VALVE}  # was still the first room's valve
    assert room.setup_revision == 1 and room._setup_pending is None

    # Armed, the new room is watered through ITS valve and the old one is never touched.
    for switch in ARMED:
        fake.set_state(switch, "on")
    fake.calls.clear()
    c._execute_shot(room, 1, 30, 5, flow_lps=c._zone_flow_lps(room, 1))
    assert switch_calls(fake) == [("turn_on", OTHER_VALVE), ("turn_off", OTHER_VALVE)]


async def test_a_room_set_up_again_is_not_adopted_while_the_old_valve_is_on(
    hass, controller_for, monkeypatch
):
    first = await _install(hass)
    c, fake, _clock = controller_for({"enable_flag": KILL})
    room = c.rooms[0]
    assert await hass.config_entries.async_remove(first.entry_id)
    await hass.async_block_till_done()
    hass.states.async_set(OTHER_VALVE, "off")
    monkeypatch.setitem(ZONES, "zone_1_switch", OTHER_VALVE)
    await _install(hass)

    _see(hass, fake)
    fake.set_state(VALVE, "on")  # the first room's valve, left running by hand
    c._rediscover(datetime.now())
    assert room._setup_pending and room.hw["valves"] == {1: VALVE}
    assert "Setup" in c._blocked(room, 1)


# ------------------------------------------------------------------ upgrade in place
async def test_an_upgraded_room_is_carried_straight_on_and_its_identity_is_written_down(
    hass, controller_for
):
    """The seeded 2.18 tent, armed, with the state file its old controller saved (no `entry_id` in
    it). After the update: resumed with the kill switch left ON, no hold, no alert, and the room's
    identity recorded for next time."""
    import os

    entry, seed = await _upgrade(hass, "entry_2_18_one_switch_tent.json")
    assert "entry_id" not in json.dumps(seed["controller_saved"])
    hass.states.async_set(KILL, "on")
    c, _fake, _clock = controller_for({"enable_flag": KILL}, saved_state=seed["controller_saved"])
    room = c.rooms[0]
    assert room.setup_revision == seed["data"]["setup_revision"] and room._setup_pending is None
    assert "Setup" not in (c._blocked(room, 1) or "")
    saved = json.load(open(os.environ["F2_STATE_PATH"]))["default"]["_setup"]
    assert saved["entry_id"] == entry.entry_id


async def test_the_new_attribute_does_not_move_an_upgraded_rooms_fingerprint(hass, controller_for):
    import controller as controller_module

    _entry, seed = await _upgrade(hass, "entry_2_18_one_switch_tent.json")
    attrs = json.loads(json.dumps(dict(hass.states.get(DESCRIPTOR).attributes), default=str))
    room = type("R", (), {"enable_flag": KILL})()
    now = controller_module.Controller._setup_fingerprint(attrs, room)
    assert now == seed["controller_saved"]["default"]["_setup"]["fingerprint"]
    assert fixture("entry_2_18_one_switch_tent.json")["data"] == seed["data"]
