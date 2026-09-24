"""A controller watering one long shot is still reporting, as the real Home Assistant sees it.

25 Sep 2026, lights-on: three shots in a row held the controller's loop for 8.2 minutes, and the
dashboard said the controller was not running while it watered. One shot can be 15 minutes, past
both of the integration's own limits, 10 minutes each: the engine-offline repair (the heartbeat's
last write) and a zone's "Controller not reporting" (its status label's last write). Only what the
controller writes during the shot reaches Home Assistant here, as it would over REST.
"""

from datetime import datetime, timedelta

from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.crop_steering import health
from test_setup_entry import _install

DOMAIN = "crop_steering"
KILL = "switch.crop_steering_engine_enabled"
STATUS = "sensor.crop_steering_zone_1_status"
NOT_REPORTING = "Controller not reporting"


def _written(hass, fake):
    """What the controller's REST writes since the last call put in Home Assistant."""
    for entity_id, (state, attributes) in fake.sets.items():
        hass.states.async_set(entity_id, state, attributes)
    fake.sets.clear()


async def test_a_fifteen_minute_shot_leaves_the_room_reporting(hass, freezer, controller_for):
    entry = await _install(hass)
    c, fake, _clock = controller_for({"enable_flag": KILL})
    c.loop_once(datetime.now())
    _written(hass, fake)
    await hass.async_block_till_done()
    label = hass.states.get(STATUS).state
    assert label != NOT_REPORTING  # the premise: the room has reported

    for entity_id in (KILL, "switch.crop_steering_room_active"):
        fake.set_state(entity_id, "on")  # nobody stops the shot
    freezer.tick(timedelta(minutes=15))  # Home Assistant's clock, while the shot holds the loop
    elapsed, ended = c._wait_shot(c.rooms[0], 1, 900)
    assert ended is None and elapsed >= 900
    _written(hass, fake)
    async_fire_time_changed(hass, fire_all=True)
    await hass.async_block_till_done()

    health.run_health_check(hass, entry)
    assert ir.async_get(hass).async_get_issue(DOMAIN, "engine_offline") is None
    assert hass.states.get(STATUS).state == label
