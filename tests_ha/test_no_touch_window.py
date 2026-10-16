"""A room's no-touch window (Pause AI Changes) is one select per room, and it is additive: a new room and every
upgraded one get it at Off, a choice records when it was made and survives a reload, and the real controller reads
the window from Home Assistant, keeps the brain from asking inside it, and sets it back to Off once it is over."""

from datetime import datetime, timedelta

import pytest
from conftest import fixture, room_of
from homeassistant.const import ATTR_OPTION
from homeassistant.util import dt as dt_util
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, _upgrade

NO_TOUCH = "select.crop_steering_ai_no_touch"
NEW_NO_TOUCH = "select.crop_steering_tent_ai_no_touch"  # a new room has a slug: the wizard's "Tent" is tent_


async def _choose(hass, option, entity=NEW_NO_TOUCH):
    await hass.services.async_call(
        "select", "select_option", {"entity_id": entity, ATTR_OPTION: option}, blocking=True
    )


async def test_a_new_room_has_no_window_until_someone_chooses_one(hass):
    entry = await _install(hass)
    state = hass.states.get(NEW_NO_TOUCH)
    assert state.state == "Off"
    assert state.attributes["options"] == ["Off", "1 h", "Until lights-on", "24 h"]
    before = dt_util.utcnow()
    await _choose(hass, "1 h")
    since = hass.states.get(NEW_NO_TOUCH).attributes["since"]
    assert datetime.fromisoformat(since) >= before
    # The choice and when it was made survive the room being reloaded (a restart restores them the same way).
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get(NEW_NO_TOUCH)
    assert (state.state, state.attributes["since"]) == ("1 h", since)


@pytest.mark.parametrize("name", ["entry_2_17_wizard.json", JEV_3_11_1])
async def test_an_upgraded_room_gets_the_select_at_off(hass, name):
    await _upgrade(hass, name, registry_ids=fixture(name).get("registry"))
    assert hass.states.get(NO_TOUCH).state == "Off"


async def test_the_controller_reads_the_window_asks_nothing_inside_it_and_ends_it(
    hass, controller_for, monkeypatch
):
    import functools

    import brain_kit as B
    import brain_bridge
    from brain import client as jc

    client = B.FakeClient(B.judging())
    monkeypatch.setattr(jc, "anthropic", B.FakeSDK(client))
    monkeypatch.setattr(brain_bridge, "Asker", functools.partial(jc.Asker, threaded=False))
    await _install(hass)
    await _choose(hass, "1 h")
    c, fake, _clock = controller_for(
        {
            "enable_flag": "switch.crop_steering_tent_engine_enabled",
            "brain_provider": "claude_haiku",
            "anthropic_api_key": B.SENTINEL,
        }
    )
    room, now = room_of(c), datetime.now()
    until = c._no_touch_until(room, now)
    assert until is not None and timedelta(minutes=58) < until - now <= timedelta(hours=1)
    c.loop_once(now)
    assert not [r for r in client.requests if '<snapshot id="tent:' in str(r["messages"])]  # the room's own asks
    assert fake.sets["sensor.crop_steering_tent_jev"][1]["no_touch_until"] == until.isoformat(timespec="minutes")
    assert c._no_touch_until(room, now + timedelta(hours=1, minutes=1)) is None
    assert ("select", "select_option", {"entity_id": NEW_NO_TOUCH, "option": "Off"}) in fake.calls
