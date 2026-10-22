"""The room's display options (Settings > Display) in a real Home Assistant: display_get and
display_save through the service registry, schema and auth store; sensor.crop_steering_<prefix>display
under that exact id; every option off on a fresh install AND on an old install upgraded in place,
which has no store at all; saves kept across a reload."""

import pytest
import voluptuous as vol
from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.core import Context, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockUser
from test_setup_entry import _install
from test_upgrade_in_place import _upgrade

from custom_components.crop_steering.display import OPTIONS, defaults

DOMAIN = "crop_steering"
ROOM = "room:tent_"
SENSOR = "sensor.crop_steering_tent_display"
REFUSED = "requires an authenticated Home Assistant administrator"


async def _call(hass, service, user=None, room=ROOM, **data):
    return await hass.services.async_call(
        DOMAIN,
        service,
        {"room_id": room, **data},
        blocking=True,
        return_response=True,
        context=Context(user_id=user.id if user else None),
    )


def test_every_option_defaults_to_the_dashboard_as_it_was():
    units = {"ec_unit": "mS/cm", "temp_unit": "C", "volume_unit": "L", "clock": 24}
    assert defaults() == {
        key: units.get(key, "cards" if key == "today_zone_layout" else False)
        for key in OPTIONS
    }


async def test_a_fresh_room_shows_every_option_off(hass):
    entry = await _install(hass)
    assert hass.services.supports_response(DOMAIN, "display_get") is (
        SupportsResponse.ONLY
    )
    registered = er.async_get(hass).async_get(SENSOR)
    assert registered.unique_id == f"{DOMAIN}_{entry.entry_id}_display"
    shown = hass.states.get(SENSOR)
    assert shown.state == "0"
    assert {k: shown.attributes[k] for k in OPTIONS} == defaults()
    read = await _call(hass, "display_get")
    assert (read["revision"], read["options"], read["error"]) == (0, defaults(), None)


async def test_an_old_install_without_a_store_loads_with_every_option_off(hass):
    """Upgraded in place from a seeded 3.11.1 room: no display store exists, and nothing shows."""
    await _upgrade(hass, "entry_3_11_1_pumped_room.json")
    [display] = [
        s for s in hass.states.async_all("sensor") if s.entity_id.endswith("_display")
    ]
    assert display.state == "0"
    assert {k: display.attributes[k] for k in OPTIONS} == defaults()


async def test_an_administrator_saves_and_it_is_kept_across_a_reload(
    hass, hass_admin_user
):
    entry = await _install(hass)
    saved = await _call(
        hass,
        "display_save",
        hass_admin_user,
        expected_revision=0,
        options={"show_climate": True, "today_zone_layout": "table"},
    )
    assert saved["revision"] == 1
    assert saved["options"] == {
        **defaults(),
        "show_climate": True,
        "today_zone_layout": "table",
    }
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).state == "1"
    assert hass.states.get(SENSOR).attributes["show_climate"] is True
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    shown = hass.states.get(SENSOR)
    assert shown.state == "1" and shown.attributes["today_zone_layout"] == "table"


async def test_a_save_is_refused_for_a_stale_revision_or_a_bad_option(
    hass, hass_admin_user
):
    await _install(hass)
    for options, match in (
        ({"no_such_option": True}, "Unknown display option"),
        ({"show_climate": "yes"}, "true or false"),
        ({"today_zone_layout": "grid"}, "one of"),
        ({"clock": "12"}, "one of: 12, 24"),
        ({"ec_unit": "ppm640"}, "one of"),
        ({}, "at least one"),
    ):
        with pytest.raises(HomeAssistantError, match=match):
            await _call(
                hass,
                "display_save",
                hass_admin_user,
                expected_revision=0,
                options=options,
            )
    with pytest.raises(HomeAssistantError, match="changed elsewhere"):
        await _call(
            hass,
            "display_save",
            hass_admin_user,
            expected_revision=3,
            options={"show_climate": True},
        )
    with pytest.raises(vol.Invalid):
        await _call(
            hass, "display_save", hass_admin_user, options={"show_climate": True}
        )
    with pytest.raises(HomeAssistantError, match="unknown or ambiguous"):
        await _call(hass, "display_get", room="room:nowhere_")
    assert hass.states.get(SENSOR).state == "0"


async def test_a_non_administrator_reads_but_may_not_save(hass):
    await _install(hass)
    users = await hass.auth.async_get_group(GROUP_ID_USER)
    staff = MockUser(name="Staff phone", groups=[users]).add_to_hass(hass)
    assert (await _call(hass, "display_get", staff))["revision"] == 0
    with pytest.raises(HomeAssistantError, match=REFUSED):
        await _call(
            hass,
            "display_save",
            staff,
            expected_revision=0,
            options={"show_camera": True},
        )
    assert hass.states.get(SENSOR).state == "0"
