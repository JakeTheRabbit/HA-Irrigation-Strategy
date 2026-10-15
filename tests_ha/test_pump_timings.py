"""The pump's prime and the main line's lead are room settings, in a real Home Assistant with the
real controller. They were fixed at 2 s and 1 s: a pump that takes 4 s to reach pressure opened
every zone valve onto a line still filling. A new room and a room updated in place have them at
2 s and 1 s, so nothing changes until they are set; set, the controller waits them; under an
integration older than them, it keeps waiting 2 s and 1 s, without the missing-setting alert.
"""

import pytest
import controller
from conftest import fixture
from test_declared_plumbing import KILL, _arm
from test_real_flow import VALVE
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, UPSTREAM_2_25_1, _upgrade

PRIME = "number.crop_steering_pump_prime_time"
LEAD = "number.crop_steering_main_line_lead_time"
PUMP, MAIN = "switch.room_pump", "switch.room_main_line"


async def _set(hass, entity_id, value):
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True
    )


async def _pumped_room(hass):
    for switch in (PUMP, MAIN):
        hass.states.async_set(switch, "off")
    await _install(
        hass,
        {
            "plumbing": "pump_mainline_valves",
            "pump_switch": PUMP,
            "main_line_switch": MAIN,
        },
    )


def _opened(c, fake, clock, monkeypatch):
    """Fire one shot: when the controller switched each of pump, main line and valve on."""
    room = c.rooms[0]
    _arm(fake)
    opened = {}
    real = controller.ha_call  # the fake Home Assistant controller_for installed

    def stamped(domain, service, **data):
        if domain == "switch" and service == "turn_on":
            opened[data["entity_id"]] = clock.seconds
        return real(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", stamped)
    c._execute_shot(room, 1, 30, 5, flow_lps=c._zone_flow_lps(room, 1))
    assert room.state[1]["shots"] == 1
    return opened


async def test_a_new_room_has_them_at_two_and_one_second(hass):
    await _install(hass)
    for entity_id, value, top in ((PRIME, 2, 20), (LEAD, 1, 10)):
        state = hass.states.get(entity_id)
        assert float(state.state) == value
        attributes = state.attributes
        limits = (attributes["min"], attributes["max"], attributes["step"])
        assert limits == (0, top, 0.5)
        assert attributes["unit_of_measurement"] == "s"


@pytest.mark.parametrize(
    "name", ["entry_2_17_wizard.json", UPSTREAM_2_25_1, JEV_3_11_1]
)
async def test_a_room_updated_in_place_has_them_at_two_and_one_second(hass, name):
    seed = fixture(name)
    await _upgrade(hass, name, registry_ids=seed.get("registry"))
    assert float(hass.states.get(PRIME).state) == 2
    assert float(hass.states.get(LEAD).state) == 1


async def test_the_controller_waits_the_rooms_own_times(
    hass, controller_for, monkeypatch
):
    await _pumped_room(hass)
    await _set(hass, PRIME, 4)
    await _set(hass, LEAD, 0.5)
    c, fake, clock = controller_for({"enable_flag": KILL})
    assert _opened(c, fake, clock, monkeypatch) == {PUMP: 0.0, MAIN: 4.0, VALVE: 4.5}


async def test_an_integration_without_them_leaves_the_controller_at_two_and_one_second(
    hass, controller_for, monkeypatch
):
    await _pumped_room(hass)
    # As an integration from before these settings has none.
    for entity_id in (PRIME, LEAD):
        hass.states.async_remove(entity_id)
    c, fake, clock = controller_for({"enable_flag": KILL})
    assert _opened(c, fake, clock, monkeypatch) == {PUMP: 0.0, MAIN: 2.0, VALVE: 3.0}
    assert PRIME not in c._defaulted_this_loop and LEAD not in c._defaulted_this_loop
