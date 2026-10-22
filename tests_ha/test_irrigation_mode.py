"""Each zone's "Watering by" select and the room's timer programs in a real Home Assistant.

select.crop_steering_<prefix>zone_N_irrigation_mode reads steering on a fresh install and on an old
install upgraded in place (the engine waters as before); a saved mode this code cannot read is not
turned into steering. The timer services go through the service registry, schema and auth store, and
sensor.crop_steering_<prefix>timers_config carries the saved programs across a reload."""

import pytest
from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.core import Context, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockUser
from test_setup_entry import _install
from test_upgrade_in_place import _upgrade

from custom_components.crop_steering.const import IRRIGATION_MODES

DOMAIN = "crop_steering"
ROOM = "room:tent_"
SELECT = "select.crop_steering_tent_zone_1_irrigation_mode"
SENSOR = "sensor.crop_steering_tent_timers_config"
JEV_3_11_1 = "entry_3_11_1_pumped_room.json"
REFUSED = "requires an authenticated Home Assistant administrator"
PROGRAM = {
    "name": "Mothers AM",
    "type": "recycle",
    "zones": [1],
    "duration_s": 120,
    "interval_min": 30,
    "window": {"kind": "custom", "from": "08:00", "to": "12:00"},
}


@pytest.fixture(autouse=True)
def _custom_integrations(hass, enable_custom_integrations):
    hass.config.components.add("frontend")
    yield


async def _call(hass, service, user=None, **data):
    return await hass.services.async_call(
        DOMAIN,
        service,
        data,
        blocking=True,
        return_response=True,
        context=Context(user_id=user.id if user else None),
    )


async def test_fresh_install_has_select_zone_1_irrigation_mode_reading_steering(hass):
    await _install(hass)
    state = hass.states.get(SELECT)
    assert state is not None and state.state == "steering"
    assert state.attributes["options"] == IRRIGATION_MODES == ["steering", "timer", "off"]
    assert state.attributes["friendly_name"].endswith("Zone 1 Watering by")
    timers = hass.states.get(SENSOR)
    assert timers.state == "0"
    assert (timers.attributes["programs"], timers.attributes["skips"]) == ([], [])


async def test_upgraded_install_gains_the_select_at_steering(hass):
    await _upgrade(hass, JEV_3_11_1)
    for zone in (1, 2):
        assert hass.states.get(f"select.crop_steering_zone_{zone}_irrigation_mode").state == (
            "steering"
        )
    assert hass.states.get("sensor.crop_steering_timers_config").state == "0"


async def test_a_saved_mode_is_restored_and_one_that_cannot_be_read_is_not_steering(hass):
    await _upgrade(
        hass,
        JEV_3_11_1,
        restored={
            "select.crop_steering_zone_1_irrigation_mode": "timer",
            "select.crop_steering_zone_2_irrigation_mode": "flood",
        },
    )
    assert hass.states.get("select.crop_steering_zone_1_irrigation_mode").state == "timer"
    unreadable = hass.states.get("select.crop_steering_zone_2_irrigation_mode")
    assert unreadable.state == "unknown"
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": unreadable.entity_id, "option": "off"},
        blocking=True,
    )
    assert hass.states.get(unreadable.entity_id).state == "off"


async def test_an_administrator_saves_a_program_and_it_is_kept_across_a_reload(
    hass, hass_admin_user
):
    entry = await _install(hass)
    for service, kind in (
        ("timer_program_list", SupportsResponse.ONLY),
        ("timer_program_preview", SupportsResponse.ONLY),
        ("timer_program_set", SupportsResponse.OPTIONAL),
        ("timer_program_delete", SupportsResponse.OPTIONAL),
        ("timer_skip", SupportsResponse.OPTIONAL),
    ):
        assert hass.services.supports_response(DOMAIN, service) is kind, service
    draft = await _call(hass, "timer_program_preview", room_id=ROOM, program=PROGRAM, hours=48)
    assert draft["shots"] == 16 and draft["total_s"] == 1920.0
    saved = await _call(
        hass, "timer_program_set", hass_admin_user, room_id=ROOM, expected_revision=0,
        program=PROGRAM,
    )
    assert saved["revision"] == 1 and len(saved["preview"]) == 8
    with pytest.raises(HomeAssistantError, match="^Zone 1 is already in timer 'Mothers AM'$"):
        await _call(
            hass, "timer_program_set", hass_admin_user, room_id=ROOM, expected_revision=1,
            program={**PROGRAM, "name": "Second"},
        )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    shown = hass.states.get(SENSOR)
    assert shown.state == "1"
    assert [p["id"] for p in shown.attributes["programs"]] == [saved["program"]["id"]]
    listed = await _call(hass, "timer_program_list")
    assert [(p["room_id"], p["name"]) for p in listed["programs"]] == [(ROOM, "Mothers AM")]
    assert listed["revisions"] == {ROOM: 1}


async def test_a_non_administrator_lists_and_previews_but_may_not_save(hass):
    await _install(hass)
    users = await hass.auth.async_get_group(GROUP_ID_USER)
    staff = MockUser(name="Staff phone", groups=[users]).add_to_hass(hass)
    assert (await _call(hass, "timer_program_list", staff, room_id=ROOM))["revision"] == 0
    assert (await _call(hass, "timer_program_preview", staff, room_id=ROOM, program=PROGRAM))[
        "shots"
    ] >= 0
    for service, data in (
        ("timer_program_set", {"program": PROGRAM}),
        ("timer_program_delete", {"id": "x"}),
        ("timer_skip", {"zone": 1, "at": "2026-10-22T08:00:00+13:00"}),
    ):
        with pytest.raises(HomeAssistantError, match=REFUSED):
            await _call(hass, service, staff, room_id=ROOM, expected_revision=0, **data)
    assert hass.states.get(SENSOR).state == "0"
