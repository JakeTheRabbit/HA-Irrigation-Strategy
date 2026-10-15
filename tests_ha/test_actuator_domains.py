"""Any on/off actuator drives the irrigation path: a switch, an input_boolean or a valve.

Every zone valve, main line and pump used to be driven with `switch.turn_on` / `switch.turn_off`
and read back as on/off, and the wizard offered switches only. A valve that Home Assistant exposes
as a valve (open_valve / close_valve, states open / closed) or a relay exposed as an input_boolean
could not be used. Here the real wizard maps one, and the real controller runs a full shot on it,
opening, closing and reading it back in its own words; a stuck one latches the hardware hold a stuck
switch does. A domain the controller cannot drive is refused at setup and, mapped by hand, holds
its zone with CS-313 and is never sent a command.

Rooms on switches must not notice: the hardware calls a shot sends on a 2.25.1 and a 3.11.1 room
are compared with the ones the 3.11.1 controller sent, recorded in
tests_ha/fixtures/actuator_calls_3_11_1.json.
"""

import pytest
from conftest import fixture, room_of
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from test_install_to_controller import ARMED, KILL
from test_real_flow import ZONES, _to_zones_step
from test_upgrade_in_place import JEV_3_11_1, UPSTREAM_2_25_1, _jev_3_11_1_app, _upgrade

from custom_components.crop_steering.setup_api import prepare_setup

VALVE = "valve.tent_drip_line"
PUMP = "input_boolean.tent_pump_relay"
COVER = "cover.tent_vent"
OLD_HARDWARE = ("switch.irrigation_pump", "switch.irrigation_main_line", "switch.zone_1_valve")


def _hardware_calls(fake, hardware):
    return [[domain, service, data] for domain, service, data in fake.calls if data.get("entity_id") in hardware]


def _two_shots(c, fake, monkeypatch):
    """A normal shot, then one whose zone valve never reads OFF again: the hardware calls of each."""
    import controller

    room = c.rooms[0]
    for switch in ARMED[1:]:
        fake.set_state(switch, "on")
    fake.calls.clear()
    c._execute_shot(room, 1, 10, 5, flow_lps=0.05)
    sent = {"shot": _hardware_calls(fake, OLD_HARDWARE)}
    assert room.hardware_fault is None
    real = controller.ha_call

    def stuck(domain, service, **data):
        if data.get("entity_id") == "switch.zone_1_valve" and service == "turn_off":
            fake.calls.append((domain, service, data))
            return True  # taken, and the valve stays ON
        return real(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", stuck)
    fake.calls.clear()
    c._execute_shot(room, 1, 10, 5, flow_lps=0.05)
    sent["valve_stuck_open"] = _hardware_calls(fake, OLD_HARDWARE)
    assert room.hardware_fault is not None
    return sent


@pytest.mark.parametrize("name", [UPSTREAM_2_25_1, JEV_3_11_1])
async def test_a_room_on_switches_sends_exactly_the_calls_it_always_did(
    hass, controller_for, monkeypatch, name
):
    seed = fixture(name)
    await _upgrade(hass, name, registry_ids=seed["registry"])
    hass.states.async_set(KILL, "on")
    if name == UPSTREAM_2_25_1:
        c, fake, _clock = controller_for(seed["addon_options"], saved_state=seed["controller_saved"])
    else:
        c, fake, *_ = _jev_3_11_1_app(controller_for, monkeypatch, "options_3_11_1_jev_typesafe.json")
    assert _two_shots(c, fake, monkeypatch) == fixture("actuator_calls_3_11_1.json")[name]


# ------------------------------------------------------------------ a valve and a relay helper
def _seed(hass):
    hass.states.async_set(VALVE, "closed")
    hass.states.async_set(PUMP, "off")
    hass.states.async_set(COVER, "closed")
    hass.states.async_set("sensor.gt1_vwc", "41", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.gt1_ec", "3100", {"unit_of_measurement": "µS/cm"})


async def _install_valve_room(hass):
    _seed(hass)
    flow = hass.config_entries.flow
    flow_id = await _to_zones_step(hass)
    result = await flow.async_configure(flow_id, {**ZONES, "zone_1_switch": VALVE})
    assert result["step_id"] == "hardware", result.get("description_placeholders")
    result = await flow.async_configure(flow_id, {"plumbing": "pump_valves", "pump_switch": PUMP})
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    await hass.async_block_till_done()
    return result["result"]


async def _armed_valve_room(hass, controller_for):
    await _install_valve_room(hass)
    c, fake, _clock = controller_for({"enable_flag": KILL})
    room = room_of(c)
    assert room.hw["valves"] == {1: VALVE} and room.hw["pump"] == PUMP
    assert room._setup_pending is None  # the valve reads closed and the relay off: adopted
    for switch in ARMED:
        fake.set_state(switch, "on")
    assert c._blocked(room, 1) is None
    return c, fake, room


async def test_the_wizard_takes_a_valve_and_a_relay_helper_and_the_controller_runs_a_shot_on_them(
    hass, controller_for
):
    c, fake, room = await _armed_valve_room(hass, controller_for)
    fake.calls.clear()
    c._execute_shot(room, 1, 30, 5, flow_lps=c._zone_flow_lps(room, 1))
    assert _hardware_calls(fake, (VALVE, PUMP)) == [
        ["input_boolean", "turn_on", {"entity_id": PUMP}],
        ["valve", "open_valve", {"entity_id": VALVE}],
        ["valve", "close_valve", {"entity_id": VALVE}],
        ["input_boolean", "turn_off", {"entity_id": PUMP}],
    ]
    assert fake.states[VALVE][0] == "closed" and fake.states[PUMP][0] == "off"  # read back closed
    assert room.hardware_fault is None and room.shot_inflight is None
    assert room.state[1]["shots"] == 1


@pytest.mark.parametrize("left", ["open", "closing", "unavailable"])
async def test_a_valve_that_does_not_read_closed_latches_the_hold_a_stuck_switch_does(
    hass, controller_for, monkeypatch, left
):
    import controller

    c, fake, room = await _armed_valve_room(hass, controller_for)
    real = controller.ha_call

    def stuck(domain, service, **data):
        if data.get("entity_id") == VALVE and service == "close_valve":
            fake.calls.append((domain, service, data))
            fake.set_state(VALVE, left)
            return True
        return real(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", stuck)
    c._execute_shot(room, 1, 30, 5, flow_lps=c._zone_flow_lps(room, 1))
    assert room.hardware_fault is not None
    assert fake.states[PUMP][0] == "off"  # the line behind it is closed all the same
    assert "hardware" in c._blocked(room, 1).lower()
    fake.calls.clear()
    c._execute_shot(room, 1, 30, 5, flow_lps=c._zone_flow_lps(room, 1))
    assert _hardware_calls(fake, (VALVE, PUMP)) == []  # nothing opens behind the hold

    # Cleared only once the engine is off and the valve really reads closed.
    fake.set_state(KILL, "off")
    c._recover_hardware_faults()
    assert room.hardware_fault is not None
    fake.set_state(VALVE, "closed")
    c._recover_hardware_faults()
    assert room.hardware_fault is None


async def test_setup_waits_while_a_valve_is_open(hass):
    _seed(hass)
    hass.states.async_set(VALVE, "open")
    flow_id = await _to_zones_step(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, {**ZONES, "zone_1_switch": VALVE})
    assert result["step_id"] == "zones" and result["errors"] == {"base": "setup_invalid"}
    assert f"{VALVE} must read CLOSED before changing setup (it is OPEN: close it" in (
        result["description_placeholders"]["error"]
    )


# ------------------------------------------------------------------ a domain it cannot drive
async def test_a_cover_is_refused_as_a_valve_by_the_wizard_and_by_the_setup_page(hass):
    _seed(hass)
    flow_id = await _to_zones_step(hass)
    with pytest.raises(InvalidData) as refused:
        await hass.config_entries.flow.async_configure(flow_id, {**ZONES, "zone_1_switch": COVER})
    assert "belongs to domain cover" in str(refused.value.schema_errors)

    payload = {"room_name": "Tent", "zones": [{"id": 1, "valve": COVER}]}
    with pytest.raises(ValueError, match="can't open or close a cover"):
        prepare_setup(hass, payload)
    with pytest.raises(ValueError, match="can't open or close a cover"):
        prepare_setup(hass, {**payload, "zones": [{"id": 1, "valve": VALVE}], "hardware": {"pump_switch": COVER}})


async def test_a_cover_mapped_by_hand_holds_its_zone_with_cs_313_and_is_never_driven(
    hass, controller_for
):
    _seed(hass)
    c, fake, _clock = controller_for(
        {"enable_flag": KILL, "num_zones": 2, "hardware": {"valves": {"1": COVER, "2": VALVE}}}
    )
    room = c.rooms[0]
    for switch in (*ARMED, "switch.crop_steering_zone_2_enabled"):
        fake.set_state(switch, "on")
    held = c._blocked(room, 1)
    assert held and COVER in held
    card = next(
        d for dom, svc, d in fake.calls
        if (dom, svc) == ("persistent_notification", "create") and d["notification_id"] == "f2_actuator_default_z1"
    )
    assert "(CS-313)" in card["title"] and COVER in card["message"]
    assert c._blocked(room, 2) is None  # the zone on a valve is watered as usual

    fake.calls.clear()
    c._execute_shot(room, 1, 30, 5, flow_lps=0.05)  # even asked directly, it is never sent a command
    assert [call for call in fake.calls if call[2].get("entity_id") == COVER] == []
