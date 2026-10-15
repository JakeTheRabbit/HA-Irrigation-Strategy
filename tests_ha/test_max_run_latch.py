"""The max-run latch (CS-312), in a real Home Assistant: the per-room switch, the Repairs card and its fix.

A room set up from this release gets the switch ON; a room set up before it keeps watering exactly
as it did, with the switch OFF, and is only told when a zone keeps hitting its longest allowed shot.
"""

import json
from datetime import datetime

import pytest
from homeassistant.components.repairs import repairs_flow_manager
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component

from conftest import fixture, room_of, switch_calls
from custom_components.crop_steering import health
from test_kill_switch_repair import _shipped_options
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, KILL, UPSTREAM_2_25_1, _upgrade

DOMAIN = "crop_steering"
LATCH = "switch.crop_steering_max_run_latch"
HEARTBEAT = "sensor.crop_steering_ai_heartbeat"
# A new room has a slug: the wizard's "Tent" is tent_, its card max_run_latch_tent (an upgraded room keeps the above).
NEW_LATCH = "switch.crop_steering_tent_max_run_latch"
NEW_HEARTBEAT = "sensor.crop_steering_tent_ai_heartbeat"
NEW_CARD = "max_run_latch_tent"
N = 3  # the controller's MAX_RUN_IN_A_ROW


def _card(hass, issue="max_run_latch"):
    return ir.async_get(hass).async_get_issue(DOMAIN, issue)


def _beat(hass, max_run, heartbeat=HEARTBEAT):
    hass.states.async_set(heartbeat, "healthy", {"max_run": max_run})


async def test_a_room_set_up_now_gets_the_latch_on(hass):
    entry = await _install(hass)
    assert entry.data["max_run_latch"] is True
    latch = hass.states.get(NEW_LATCH)
    assert latch.state == "on" and latch.attributes["resets"] == 0


@pytest.mark.parametrize("name", [UPSTREAM_2_25_1, JEV_3_11_1])
async def test_a_room_set_up_before_it_gets_the_latch_off(hass, name):
    entry, seed = await _upgrade(hass, name, registry_ids=fixture(name)["registry"])
    assert entry.data == seed["data"]  # loading marks nothing
    assert hass.states.get(LATCH).state == "off"


async def test_the_card_only_reports_while_nothing_is_latched(hass):
    entry = await _install(hass)
    _beat(hass, {"1": {"capped": 3, "latched": False}}, NEW_HEARTBEAT)
    health.run_health_check(hass, entry)
    card = _card(hass, NEW_CARD)
    assert card.severity is ir.IssueSeverity.WARNING and not card.is_fixable
    assert card.translation_placeholders["zones"] == "1"
    assert "Nothing has been stopped" in card.translation_placeholders["what"]
    _beat(hass, {}, NEW_HEARTBEAT)  # the zone's next shot was not cut
    health.run_health_check(hass, entry)
    assert _card(hass, NEW_CARD) is None


async def test_the_repairs_fix_releases_a_latched_zone(hass):
    assert await async_setup_component(hass, "repairs", {})
    entry = await _install(hass)
    _beat(hass, {"1": {"capped": 3, "latched": True, "resets": 0}}, NEW_HEARTBEAT)
    health.run_health_check(hass, entry)
    card = _card(hass, NEW_CARD)
    assert card.severity is ir.IssueSeverity.ERROR and card.is_fixable
    assert "stopped watering zone(s) 1" in card.translation_placeholders["what"]

    flows = repairs_flow_manager(hass)
    result = await flows.async_init(DOMAIN, data={"issue_id": NEW_CARD})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "confirm"
    assert result["description_placeholders"]["zones"] == "1"
    result = await flows.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert hass.states.get(NEW_LATCH).attributes["resets"] == 1  # what the controller watches
    assert _card(hass, NEW_CARD) is None
    # The controller has not seen the reset yet: its beat still says latched, with the old count.
    health.run_health_check(hass, entry)
    assert _card(hass, NEW_CARD) is None


# ------------------------------------------------------------------ with the real controller
def _see(hass, fake):
    """Let the controller see Home Assistant as it is now (it reads over REST every loop)."""
    for state in hass.states.async_all():
        attributes = json.loads(json.dumps(dict(state.attributes), default=str))
        fake.set_state(state.entity_id, state.state, attributes)


def _cut_shots(c, fake, n, room=None):
    """`n` shots on zone 1, each wanting far longer than the room's 5 s longest shot -> the switch
    calls of each."""
    room = room or c.rooms[0]
    fake.set_state(f"number.crop_steering_{room.prefix}max_shot_duration", "5")
    each = []
    for _ in range(n):
        fake.calls.clear()
        c._act_zone(room, 1, None, None, (True, 80, "test"), None, True, datetime.now())
        each.append(switch_calls(fake))
    return each


def _armed(fake, *switches):
    for switch in switches:
        fake.set_state(switch, "on")


async def test_a_new_room_latches_and_the_repairs_fix_waters_it_again(hass, controller_for):
    assert await async_setup_component(hass, "repairs", {})
    entry = await _install(hass)
    c, fake, _clock = controller_for(_shipped_options())
    room = room_of(c)
    _armed(fake, room.enable_flag, "switch.crop_steering_tent_zone_1_enabled")
    shots = _cut_shots(c, fake, N, room)
    assert all(calls and calls == shots[0] for calls in shots)  # each one ran, cut to 5 s
    assert "CS-312" in c._blocked(room, 1)  # and the zone is held

    c._heartbeat(room, datetime.now(), None)
    hass.states.async_set(NEW_HEARTBEAT, *fake.sets[NEW_HEARTBEAT])
    health.run_health_check(hass, entry)
    assert _card(hass, NEW_CARD).is_fixable

    flows = repairs_flow_manager(hass)
    result = await flows.async_init(DOMAIN, data={"issue_id": NEW_CARD})
    result = await flows.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    _see(hass, fake)
    assert "CS-312" not in (c._blocked(room, 1) or "")
    assert room.state[1]["max_run_latch"] is None
    c._heartbeat(room, datetime.now(), None)
    assert fake.sets[NEW_HEARTBEAT][1]["max_run"] == {}


@pytest.mark.parametrize("name", [UPSTREAM_2_25_1, JEV_3_11_1])
async def test_an_upgraded_room_is_told_and_keeps_watering(hass, controller_for, name):
    seed = fixture(name)
    entry, _seed = await _upgrade(hass, name, registry_ids=seed["registry"])
    hass.states.async_set(KILL, "on")
    saved = seed.get("controller_saved") or fixture("state_3_11_1_learn_jev.json")["state"]
    c, fake, _clock = controller_for(
        seed.get("addon_options") or _shipped_options(), saved_state=saved
    )
    room = c.rooms[0]
    _armed(
        fake,
        "switch.crop_steering_system_enabled",
        "switch.crop_steering_auto_irrigation_enabled",
        "switch.crop_steering_zone_1_enabled",
    )
    shots = _cut_shots(c, fake, N + 1)
    assert shots[0] == [
        ("turn_on", "switch.irrigation_pump"),
        ("turn_on", "switch.irrigation_main_line"),
        ("turn_on", "switch.zone_1_valve"),
        ("turn_off", "switch.zone_1_valve"),
        ("turn_off", "switch.irrigation_main_line"),
        ("turn_off", "switch.irrigation_pump"),
    ]
    assert all(calls == shots[0] for calls in shots)  # every shot, past the run, as before
    assert room.state[1]["max_run_latch"] is None
    assert "CS-312" not in (c._blocked(room, 1) or "")

    c._heartbeat(room, datetime.now(), None)
    hass.states.async_set(HEARTBEAT, *fake.sets[HEARTBEAT])
    health.run_health_check(hass, entry)
    card = _card(hass)
    assert card.severity is ir.IssueSeverity.WARNING and not card.is_fixable
