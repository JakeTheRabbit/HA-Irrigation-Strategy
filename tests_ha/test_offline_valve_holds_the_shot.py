"""A zone whose valve is offline in Home Assistant is held, before anything opens.

25 Sep 2026, F2: the pump, main line and valves went unavailable for 45 minutes. The controller opened a
shot onto them anyway: Home Assistant took the commands, nothing switched, the close could not be read
back, and a hardware hold latched until someone re-armed the room 7 hours later. Here the integration
maps the valve, a real Home Assistant says it is unavailable, and the real controller must hold the
zone until it reads again, with nothing latched.
"""

from conftest import switch_calls
from test_real_flow import VALVE
from test_recreated_room_controller import ARMED, KILL, _see
from test_setup_entry import _install


async def test_a_zone_is_held_while_its_valve_is_offline_and_freed_when_it_reads(
    hass, controller_for
):
    await _install(hass)
    c, fake, _clock = controller_for({"enable_flag": KILL})
    room = c.rooms[0]
    assert room.hw["valves"] == {1: VALVE}

    hass.states.async_set(VALVE, "unavailable")
    _see(hass, fake)
    for switch in ARMED:
        fake.set_state(switch, "on")
    held = c._blocked(room, 1)
    assert held == f"{VALVE} offline (reads neither on nor off)"
    assert switch_calls(fake) == [] and room.hardware_fault is None

    hass.states.async_set(VALVE, "off")
    _see(hass, fake)
    for switch in ARMED:
        fake.set_state(switch, "on")
    assert c._blocked(room, 1) is None
