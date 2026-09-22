"""zone_N_status has one writer, the integration, and shows what the controller says about the zone.

Both used to write it: the integration's polled sensor with fixed 40 % / 70 % thresholds, the
controller over REST with its phase-aware label. The state flipped between "Dry - Needs Water" and,
say, "Overnight dryback" about twice a minute. Now the controller publishes zone_N_status_app and the
integration's sensor mirrors it, is not polled, and writes only when what it shows changes.
"""

from datetime import datetime, timedelta

from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from test_setup_entry import _install

STATUS = "sensor.crop_steering_zone_1_status"
APP = "sensor.crop_steering_zone_1_status_app"
KILL = "switch.crop_steering_engine_enabled"


async def _later(hass, minutes):
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=minutes))
    await hass.async_block_till_done()


async def test_before_the_controller_reports_the_zone_says_so_rather_than_guess_from_a_threshold(hass):
    await _install(hass)  # the tent's probe reads 41 %: the old sensor called that "Optimal"
    state = hass.states.get(STATUS)
    assert state.state == "Controller not reporting"


async def test_the_zone_status_is_the_controllers_label_with_its_reason(hass):
    await _install(hass)
    hass.states.async_set(APP, "Overnight dryback", {"reason": "lights-off -> P3"})
    await hass.async_block_till_done()
    state = hass.states.get(STATUS)
    assert state.state == "Overnight dryback"
    assert state.attributes["reason"] == "lights-off -> P3"


async def test_a_controller_that_stops_reporting_is_shown_as_not_reporting(hass):
    await _install(hass)
    hass.states.async_set(APP, "Optimal", {"reason": "in band"})
    await hass.async_block_till_done()
    await _later(hass, 5)
    assert hass.states.get(STATUS).state == "Optimal"
    await _later(hass, 11)
    assert hass.states.get(STATUS).state == "Controller not reporting"


async def test_a_controller_from_before_this_still_writing_the_zone_status_is_not_fought(hass):
    await _install(hass)
    for minute in range(1, 7):  # what 0.16.x does every loop, across several of the old poll intervals
        hass.states.async_set(STATUS, "Topping up", {"reason": "P2 top-up VWC 40<45"})
        await _later(hass, minute)
        assert hass.states.get(STATUS).state == "Topping up"


async def test_with_this_controller_the_zone_status_has_exactly_one_writer(hass, controller_for):
    await _install(hass)
    c, fake, _clock = controller_for({"enable_flag": KILL})
    c.loop_once(datetime.now())
    assert APP in fake.sets and STATUS not in fake.sets  # the controller never writes it
    for entity_id, (state, attributes) in fake.sets.items():  # what its REST writes put in HA
        hass.states.async_set(entity_id, state, attributes)
    await hass.async_block_till_done()
    label, attributes = fake.sets[APP]
    shown = hass.states.get(STATUS)
    assert shown.state == label and shown.attributes["reason"] == attributes["reason"]
