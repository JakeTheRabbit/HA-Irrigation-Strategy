"""sensor.crop_steering_current_phase mirrors the phase the controller publishes and is unknown, with
a reason, when it publishes none. It used to show the irrigation_phase select (the controller never
reads it) and then a hard-coded "P2", so a room whose controller was stopped looked like it was in
maintenance. The entity id does not change, and an old install that had stored "P2" loads cleanly."""

from datetime import timedelta

from pytest_homeassistant_custom_component.common import async_fire_time_changed

from test_setup_entry import _install
from test_upgrade_in_place import _upgrade

PHASE = "sensor.crop_steering_tent_current_phase"
APP = "sensor.crop_steering_tent_app_current_phase"
SELECT = "select.crop_steering_tent_irrigation_phase"


async def _later(hass, freezer, minutes):
    freezer.tick(timedelta(minutes=minutes))
    async_fire_time_changed(hass, fire_all=True)
    await hass.async_block_till_done()


async def test_before_the_controller_reports_no_phase_is_invented(hass):
    await _install(hass)
    state = hass.states.get(PHASE)
    assert state.state == "unknown"
    assert "has not published" in state.attributes["reason"]


async def test_the_operator_marker_select_is_not_shown_as_the_phase(hass):
    await _install(hass)
    hass.states.async_set(SELECT, "P3")
    await hass.async_block_till_done()
    await hass.services.async_call(
        "select", "select_option", {"entity_id": SELECT, "option": "P1"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(PHASE).state == "unknown"


async def test_the_controllers_phase_is_mirrored_then_goes_unknown_when_it_stops(hass, freezer):
    await _install(hass)
    hass.states.async_set(APP, "Z1:P3, Z2:P3")
    await hass.async_block_till_done()
    assert hass.states.get(PHASE).state == "Z1:P3, Z2:P3"
    await _later(hass, freezer, 5)
    assert hass.states.get(PHASE).state == "Z1:P3, Z2:P3"
    await _later(hass, freezer, 6)  # 11 minutes since the last report
    state = hass.states.get(PHASE)
    assert state.state == "unknown" and "10 minutes" in state.attributes["reason"]
    hass.states.async_set(APP, "unavailable")
    await hass.async_block_till_done()
    assert hass.states.get(PHASE).state == "unknown"


async def test_an_old_install_loads_keeps_the_entity_id_and_shows_unknown_not_p2(hass):
    old = "sensor.crop_steering_current_phase"  # registered by the old code under this id
    await _upgrade(hass, "entry_3_11_1_pumped_room.json", registry_ids={old: "current_phase"})
    state = hass.states.get(old)  # same entity id, no controller report yet
    assert state is not None and state.state == "unknown"
    assert hass.states.get(old + "_2") is None
