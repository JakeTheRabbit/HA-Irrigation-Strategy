"""Switching a zone off stops the shot running in it, with the integration's own zone switch.

The real controller watches the zone's switch through each round of a shot's checks. The switch here
is the one the real integration creates, switched off through Home Assistant the way the dashboard's
"Pause zone scheduling" does it, and the controller sees it over REST at its next round.
"""

from test_recreated_room_controller import _see
from test_setup_entry import _install

KILL = "switch.crop_steering_engine_enabled"
ZONE = "switch.crop_steering_zone_1_enabled"


async def test_the_zone_switch_stops_the_shot_running_in_it(hass, controller_for, monkeypatch):
    await _install(hass)
    await hass.services.async_call("switch", "turn_on", {"entity_id": KILL}, blocking=True)
    assert hass.states.get(ZONE).state == "on"
    c, fake, clock = controller_for({"enable_flag": KILL})
    room = c.rooms[0]
    fake.set_state(room.hw["valves"][1], "on")  # the shot's valve, as _execute_shot leaves it

    await hass.services.async_call("switch", "turn_off", {"entity_id": ZONE}, blocking=True)
    import controller

    def sleep(seconds):  # between two rounds of checks, the controller reads Home Assistant again
        clock.sleep(seconds)
        _see(hass, fake)

    monkeypatch.setattr(controller.time, "sleep", sleep)
    elapsed, ended = c._wait_shot(room, 1, 60)
    assert ended == ("abort", ZONE)
    assert elapsed < 60
