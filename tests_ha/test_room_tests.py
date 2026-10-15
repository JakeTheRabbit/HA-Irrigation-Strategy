"""A zone's test shot, in a real Home Assistant with the real controller.

Each zone has a Test Shot button on its own device, named for its room; the dashboard's test shot
presses it through the integration's test_shot service, and the controller waters that zone for 10
seconds at its next pass, through every gate a shot passes: a test shot and not one of the day's shots.
"""

from datetime import datetime

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from test_real_flow import VALVE
from test_setup_entry import _install

DOMAIN = "crop_steering"
BUTTON = "button.crop_steering_zone_1_test_shot"
KILL = "switch.crop_steering_engine_enabled"
ARMED = (
    KILL,
    "switch.crop_steering_room_active",
    "switch.crop_steering_system_enabled",
    "switch.crop_steering_auto_irrigation_enabled",
    "switch.crop_steering_zone_1_enabled",
)


async def _service(hass, admin, name, data):
    return await hass.services.async_call(
        DOMAIN,
        name,
        data,
        blocking=True,
        return_response=True,
        context=Context(user_id=admin.id),
    )


def _seen(hass, fake, *entity_ids):
    """What Home Assistant now says about these, as the controller reads it over REST."""
    for entity_id in entity_ids:
        state = hass.states.get(entity_id)
        fake.set_state(entity_id, state.state, dict(state.attributes))


def _valve_calls(fake):
    return [
        (service, data["entity_id"])
        for domain, service, data in fake.calls
        if domain == "switch" and data["entity_id"] == VALVE
    ]


async def test_each_zone_has_a_test_shot_button_on_its_own_device_named_for_its_room(
    hass, hass_admin_user
):
    await _install(hass)
    assert hass.states.get(BUTTON).state == "unknown"  # never pressed
    registry = er.async_get(hass)
    zone_device = registry.async_get("number.crop_steering_zone_1_plant_count").device_id
    assert registry.async_get(BUTTON).device_id == zone_device

    hass.states.async_set("switch.second_room_valve", "off")
    await _service(
        hass,
        hass_admin_user,
        "setup_create",
        {
            "room_name": "Second Room",
            "active": True,
            "plumbing": "valves_only",
            "hardware": {},
            "zones": [
                {
                    "id": 1,
                    "name": "Bench",
                    "active": True,
                    "valve": "switch.second_room_valve",
                    "vwc_sensors": [],
                    "ec_sensors": [],
                    "plant_count": 4,
                }
            ],
        },
    )
    await hass.async_block_till_done()
    named = "button.crop_steering_second_room_zone_1_test_shot"
    assert hass.states.get(named).state == "unknown"
    pressed = await _service(
        hass, hass_admin_user, "test_shot", {"room_id": "room:second_room_", "zone": 1}
    )
    assert pressed["requested"] == hass.states.get(named).state != "unknown"
    assert hass.states.get(BUTTON).state == "unknown"  # the other room's is not touched
    with pytest.raises(HomeAssistantError, match="no zone 2 to test"):
        await _service(
            hass, hass_admin_user, "test_shot", {"room_id": "room:second_room_", "zone": 2}
        )


async def test_the_dashboards_test_shot_waters_the_zone_through_the_real_controller(
    hass, hass_admin_user, controller_for
):
    await _install(hass)
    c, fake, _clock = controller_for({"enable_flag": KILL})
    room = c.rooms[0]
    for switch in ARMED:
        fake.set_state(switch, "on")
    c.loop_once(datetime.now())  # the button's state now is where the controller starts from
    shots, water = room.state[1]["shots"], room.state[1]["daily_vol"]
    fake.calls.clear()

    await _service(hass, hass_admin_user, "test_shot", {"room_id": "room:", "zone": 1})
    _seen(hass, fake, BUTTON)
    c.loop_once(datetime.now())
    assert _valve_calls(fake) == [("turn_on", VALVE), ("turn_off", VALVE)]
    assert room.state[1]["shots"] == shots  # a test, not one of the day's shots
    assert room.state[1]["daily_vol"] > water  # but its water counts toward the day's
    assert fake.sets["sensor.crop_steering_zone_1_status_app"][0] == "Test shot"

    fake.calls.clear()
    c.loop_once(datetime.now())  # the same press is acted on once
    assert _valve_calls(fake) == []


async def test_a_test_shot_still_passes_every_gate(hass, hass_admin_user, controller_for):
    """The kill switch off: the press is seen, and nothing opens."""
    await _install(hass)
    c, fake, _clock = controller_for({"enable_flag": KILL})
    for switch in ARMED[1:]:
        fake.set_state(switch, "on")
    fake.set_state(KILL, "off")
    c.loop_once(datetime.now())
    fake.calls.clear()

    await _service(hass, hass_admin_user, "test_shot", {"room_id": "room:", "zone": 1})
    _seen(hass, fake, BUTTON)
    c.loop_once(datetime.now())
    assert _valve_calls(fake) == []
