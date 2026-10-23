"""A zone's enable switch, the room's kill switch and the growth stage, P2 mode and watering-by selects
journal target.changed with who moved them (setpoint_log.toggle), through a real Home Assistant: a
signed-in person is manual with their user id, a change no person made is the system's, one change is
one event, and history_revert puts a switch back (and journals that once, as the put back)."""

import pytest
from homeassistant.core import Context
from test_presets import ROOM, SINCE, _three_zones, p2_mode

DOMAIN = "crop_steering"
ZONE_2 = "switch.crop_steering_room_zone_2_enabled"
KILL = "switch.crop_steering_room_engine_enabled"
STAGE = "select.crop_steering_room_growth_stage"


@pytest.fixture(autouse=True)
def _custom_integrations(hass, enable_custom_integrations):
    hass.config.components.add("frontend")
    yield


async def _call(hass, user, service, **data):
    return await hass.services.async_call(
        DOMAIN,
        service,
        data,
        blocking=True,
        return_response=True,
        context=Context(user_id=user.id),
    )


async def _events(hass, user):
    await hass.data[DOMAIN]["_journal"]._ready.wait()
    await hass.async_block_till_done()
    return (
        await _call(
            hass,
            user,
            "journal_query",
            room_id=ROOM,
            since=SINCE,
            kinds=["target.changed"],
        )
    )["events"]


async def test_a_person_pausing_a_zone_is_journaled_with_their_user_and_put_back(
    hass, hass_admin_user
):
    await _three_zones(hass)
    assert hass.states.get(ZONE_2).state == "on"
    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": ZONE_2},
        blocking=True,
        context=Context(user_id=hass_admin_user.id),
    )
    (paused,) = [
        e
        for e in await _events(hass, hass_admin_user)
        if e["data"]["entity_id"] == ZONE_2
    ]
    assert (paused["zone"], paused["source"]["actor"], paused["source"]["user_id"]) == (
        2,
        "manual",
        hass_admin_user.id,
    )
    assert {k: paused["data"][k] for k in ("key", "scope", "layer", "old", "new")} == {
        "key": "enabled",
        "scope": "zone:2",
        "layer": "base",
        "old": "on",
        "new": "off",
    }
    changes = (
        await _call(hass, hass_admin_user, "history_changes", room_id=ROOM, since=SINCE)
    )["changes"]
    (row,) = [c for c in changes if c["id"] == paused["id"]]
    assert row["revertible"] is True and row["user_name"] == hass_admin_user.name

    out = await _call(
        hass, hass_admin_user, "history_revert", api=2, event_id=paused["id"]
    )
    assert out["ok"] is True and out["readback"]["status"] == "verified", out
    assert hass.states.get(ZONE_2).state == "on"
    rows = [
        e
        for e in await _events(hass, hass_admin_user)
        if e["data"]["entity_id"] == ZONE_2
    ]
    # The pause and its put back, once (the listener leaves the put back to history_revert).
    assert len(rows) == 2
    (back,) = [e for e in rows if e["id"] != paused["id"]]
    assert back["correlation"]["causation_id"] == paused["id"]
    assert (back["source"]["detail"], back["data"]["new"]) == ("put back", "on")


async def test_selects_and_the_kill_switch_name_who_moved_them(hass, hass_admin_user):
    await _three_zones(hass)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": p2_mode(1), "option": "Timed"},
        blocking=True,
        context=Context(user_id=hass_admin_user.id),
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": STAGE, "option": "Generative"},
        blocking=True,
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": KILL}, blocking=True
    )
    events = {e["data"]["entity_id"]: e for e in await _events(hass, hass_admin_user)}
    mode, stage, kill = events[p2_mode(1)], events[STAGE], events[KILL]
    assert (mode["data"]["key"], mode["data"]["new"], mode["source"]["actor"]) == (
        "p2_mode",
        "Timed",
        "manual",
    )
    assert (stage["zone"], stage["data"]["key"], stage["source"]["actor"]) == (
        None,
        "growth_stage",
        "system",
    )
    assert (kill["data"]["key"], kill["data"]["old"], kill["data"]["new"]) == (
        "engine_enabled",
        "off",
        "on",
    )
    assert kill["source"]["user_id"] is None
