"""An older default room holds while the integration's switches can't be read.

A default room set up before rooms had their own engine switch is armed by Home Assistant's own
helper, `input_boolean.f2_control_enabled`, which stays on when the Crop Steering integration is not
running (not loaded after an update, its entry disabled, Home Assistant in safe mode). Here a real
Home Assistant runs such an install, makes the integration's switches unavailable, and the real
controller must hold the zone, then free it once they read again.
"""

from conftest import switch_calls
from test_recreated_room_controller import _see
from test_upgrade_in_place import _upgrade

KILL = "input_boolean.f2_control_enabled"
ZONE = "switch.crop_steering_zone_1_enabled"


async def test_an_older_room_holds_while_the_integration_switches_cannot_be_read(
    hass, controller_for
):
    await _upgrade(hass, "entry_env_era.json")
    hass.states.async_set(KILL, "on")
    for switch in ("switch.veg_valve", "switch.veg_pump", "switch.veg_main"):
        hass.states.async_set(switch, "off")
    c, fake, _clock = controller_for({"enable_flag": KILL})
    room = c.rooms[0]
    assert room.enable_flag == KILL and room.hw["valves"] == {1: "switch.veg_valve"}
    _see(hass, fake)
    assert hass.states.get(ZONE).state == "on"
    assert c._blocked(room, 1) is None  # watered while its integration runs

    switches = [s for s in hass.states.async_all("switch") if s.entity_id.startswith("switch.crop_")]
    for state in switches:
        hass.states.async_set(state.entity_id, "unavailable", state.attributes)
    _see(hass, fake)
    assert c._blocked(room, 1) == f"{ZONE} unreadable (reads neither on nor off)"
    assert switch_calls(fake) == []

    for state in switches:  # the integration back: each switch as it was
        hass.states.async_set(state.entity_id, state.state, state.attributes)
    _see(hass, fake)
    assert c._blocked(room, 1) is None
