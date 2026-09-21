"""Declared plumbing, end to end in a real Home Assistant, with the real controller at the far end.

The stub tier cannot see what matters here: whether the real voluptuous treats the question as
required, whether Home Assistant accepts the select, what the descriptor entity really publishes,
and what the add-on's controller does with it. The upgrade tests start from snapshots of old
installs (tests_ha/fixtures/): a room that never declared a layout must come through untouched.
"""

import pytest
from conftest import fixture, switch_calls
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from test_configure import _open, _save_map, _shown
from test_real_flow import VALVE, ZONES, _kept, _seed, _to_zones_step
from test_setup_entry import _install
from test_upgrade_in_place import DESCRIPTOR, _upgrade

KILL = "switch.crop_steering_engine_enabled"
ARMED = (
    KILL,
    "switch.crop_steering_system_enabled",
    "switch.crop_steering_auto_irrigation_enabled",
    "switch.crop_steering_zone_1_enabled",
)
PUMP = "switch.tent_pump"


async def _at_hardware_step(hass):
    _seed(hass)
    hass.states.async_set(PUMP, "off")
    flow_id = await _to_zones_step(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, dict(ZONES))
    assert result["step_id"] == "hardware", result.get("errors")
    return flow_id, result


def _arm(fake):
    for switch in ARMED:
        fake.set_state(switch, "on")


# ------------------------------------------------------------------ the wizard asks
async def test_the_wizard_will_not_go_on_until_the_plumbing_question_is_answered(hass):
    flow_id, form = await _at_hardware_step(hass)
    (question,) = [m for m in form["data_schema"].schema if str(m) == "plumbing"]
    assert list(form["data_schema"].schema)[0] is question  # asked before the switches it governs
    with pytest.raises(InvalidData):  # required, and nothing is filled in for a newcomer
        await hass.config_entries.flow.async_configure(flow_id, {})
    with pytest.raises(InvalidData):  # and only the four layouts are an answer
        await hass.config_entries.flow.async_configure(flow_id, {"plumbing": "siphon"})


async def test_saying_the_room_has_a_pump_without_choosing_one_is_caught_on_that_step(hass):
    flow_id, _form = await _at_hardware_step(hass)
    answer = {"plumbing": "pump_valves", "substrate_volume": 3.2}
    result = await hass.config_entries.flow.async_configure(flow_id, dict(answer))
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "hardware"  # not an abort
    assert "no pump switch is chosen" in result["description_placeholders"]["error"]
    assert _kept(result)["plumbing"] == "pump_valves"  # the answer is still in the form
    result = await hass.config_entries.flow.async_configure(flow_id, {**answer, "pump_switch": PUMP})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["plumbing"] == "pump_valves"


# ------------------------------------------------------------------ wizard -> descriptor -> controller
async def test_a_declared_pump_room_is_watered_pump_first_by_the_real_controller(hass, controller_for):
    hass.states.async_set(PUMP, "off")
    await _install(hass, {"plumbing": "pump_valves", "pump_switch": PUMP})
    descriptor = hass.states.get(DESCRIPTOR).attributes
    assert (descriptor["plumbing"], descriptor["pump"]) == ("pump_valves", PUMP)

    c, fake, _clock = controller_for({"enable_flag": KILL})
    room = c.rooms[0]
    assert room.hw["plumbing"] == "pump_valves"
    _arm(fake)
    assert "setup says" not in (c._blocked(room, 1) or "")
    fake.calls.clear()
    c._execute_shot(room, 1, 30, 5, flow_lps=c._zone_flow_lps(room, 1))
    assert switch_calls(fake) == [
        ("turn_on", PUMP), ("turn_on", VALVE), ("turn_off", VALVE), ("turn_off", PUMP)]  # fmt: skip


async def test_a_pumped_room_that_loses_its_pump_mapping_is_held_by_the_real_controller(
    hass, controller_for
):
    """The whole point, across both layers. Setup refuses this edit, so the mapping is removed the
    way a restored backup or a hand-edited .storage file would do it. On 2.18.0 the controller then
    opened the valve with no pump and counted 1.5 L as delivered."""
    hass.states.async_set(PUMP, "off")
    entry = await _install(hass, {"plumbing": "pump_valves", "pump_switch": PUMP})
    data = {**entry.data, "hardware": {**entry.data["hardware"], "pump_switch": ""}}
    hass.config_entries.async_update_entry(entry, data=data)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    descriptor = hass.states.get(DESCRIPTOR).attributes
    assert descriptor["plumbing"] == "pump_valves" and not descriptor["pump"]

    c, fake, _clock = controller_for({"enable_flag": KILL})
    room = c.rooms[0]
    _arm(fake)
    assert "no pump switch is mapped" in c._blocked(room, 1)
    fake.calls.clear()
    c._execute_shot(room, 1, 30, 5, flow_lps=c._zone_flow_lps(room, 1))
    assert switch_calls(fake) == []  # the valve never opens
    assert room.state[1]["shots"] == 0 and room.state[1]["daily_vol"] == 0  # and no water is claimed


# ------------------------------------------------------------------ upgrade in place: never declared
async def test_a_2_18_tent_that_never_declared_publishes_exactly_what_it_did(hass):
    _entry, seed = await _upgrade(hass, "entry_2_18_one_switch_tent.json")
    descriptor = hass.states.get(DESCRIPTOR).attributes
    assert "plumbing" not in descriptor
    assert "plumbing" not in seed["data"]  # the snapshot really is from before the question existed
    assert float(hass.states.get("number.crop_steering_p1_target_vwc").state) == 63  # nothing the operator set moved


async def test_the_controller_carries_a_2_18_tent_straight_on_after_the_update(hass, controller_for):
    """Armed and mid grow-day, both halves updated. The fingerprint controller 0.15.1 saved (it is in
    the snapshot, computed by that version's own code) must still match, or the tent sits dry
    behind 'Setup changed; disarm...' until somebody notices."""
    _entry, seed = await _upgrade(hass, "entry_2_18_one_switch_tent.json")
    hass.states.async_set(KILL, "on")
    c, fake, _clock = controller_for({"enable_flag": KILL}, saved_state=seed["controller_saved"])
    room = c.rooms[0]
    assert room._setup_pending is None, room._setup_pending
    assert room.setup_revision == 1 and room.state[1]["shots"] == 5
    assert "plumbing" not in room.hw
    _arm(fake)
    fake.calls.clear()
    c._execute_shot(room, 1, 30, 5, flow_lps=c._zone_flow_lps(room, 1))
    assert switch_calls(fake) == [("turn_on", VALVE), ("turn_off", VALVE)]  # as 2.18.0 watered it


async def test_a_2_17_pumped_room_is_still_driven_pump_mainline_valve(hass, controller_for):
    await _upgrade(hass, "entry_2_17_wizard.json")
    assert "plumbing" not in hass.states.get(DESCRIPTOR).attributes
    c, _fake, _clock = controller_for({"enable_flag": KILL})
    assert "plumbing" not in c.rooms[0].hw and c.rooms[0].hw["pump"] == "switch.main_pump"


# ------------------------------------------------------------------ upgrade in place: declaring later
async def test_configure_offers_an_old_room_the_layout_its_switches_imply_and_saving_declares_it(hass):
    entry, _seed_data = await _upgrade(hass, "entry_2_18_one_switch_tent.json")
    flow = await _open(hass, entry, "edit_zones")
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"num_zones": 1})
    assert _shown(flow)["plumbing"] == "valves_only"  # a prefill, shown to the operator, not a stored guess
    assert "plumbing" not in entry.data

    revision = entry.data["setup_revision"]
    await _save_map(hass, entry)  # pressing Submit on what is shown
    assert entry.data["plumbing"] == "valves_only"
    assert entry.data["setup_revision"] == revision + 1  # an ordinary setup change, adopted the ordinary way
    assert hass.states.get(DESCRIPTOR).attributes["plumbing"] == "valves_only"


async def test_a_pumped_2_17_room_is_offered_pump_and_main_line(hass):
    entry, _seed_data = await _upgrade(hass, "entry_2_17_wizard.json")
    flow = await _open(hass, entry, "edit_zones")
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"num_zones": int(entry.data["num_zones"])}
    )
    assert _shown(flow)["plumbing"] == "pump_mainline_valves"
    assert fixture("entry_2_17_wizard.json")["data"].get("plumbing") is None
