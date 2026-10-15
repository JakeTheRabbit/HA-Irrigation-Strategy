"""A room's no-touch window (Pause AI Changes) is one select per room, and it is additive: a new room and every
upgraded one get it at Off, and a choice records when it was made and survives a reload."""

from datetime import datetime

import pytest
from conftest import fixture
from homeassistant.const import ATTR_OPTION
from homeassistant.util import dt as dt_util
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, _upgrade

NO_TOUCH = "select.crop_steering_ai_no_touch"


async def _choose(hass, option):
    await hass.services.async_call(
        "select", "select_option", {"entity_id": NO_TOUCH, ATTR_OPTION: option}, blocking=True
    )


async def test_a_new_room_has_no_window_until_someone_chooses_one(hass):
    entry = await _install(hass)
    state = hass.states.get(NO_TOUCH)
    assert state.state == "Off"
    assert state.attributes["options"] == ["Off", "1 h", "Until lights-on", "24 h"]
    before = dt_util.utcnow()
    await _choose(hass, "1 h")
    since = hass.states.get(NO_TOUCH).attributes["since"]
    assert datetime.fromisoformat(since) >= before
    # The choice and when it was made survive the room being reloaded (a restart restores them the same way).
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get(NO_TOUCH)
    assert (state.state, state.attributes["since"]) == ("1 h", since)


@pytest.mark.parametrize("name", ["entry_2_17_wizard.json", JEV_3_11_1])
async def test_an_upgraded_room_gets_the_select_at_off(hass, name):
    await _upgrade(hass, name, registry_ids=fixture(name).get("registry"))
    assert hass.states.get(NO_TOUCH).state == "Off"
