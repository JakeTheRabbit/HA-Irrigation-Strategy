"""The integration writes its own changes to the Journal: a saved setup (with the diff) and an armed plan, read back
through journal_query in a real Home Assistant."""

import pytest
from homeassistant.core import Context
from test_setup_entry import _install

DOMAIN = "crop_steering"
ROOM = "room:tent_"
SINCE = "2000-01-01T00:00:00+00:00"


async def _call(hass, user, service, data):
    return await hass.services.async_call(
        DOMAIN,
        service,
        data,
        blocking=True,
        return_response=True,
        context=Context(user_id=user.id),
    )


async def _journal(hass, user, *kinds):
    """The room's journal rows of these kinds, once the background appends have landed."""
    hub = hass.data[DOMAIN]["_journal"]
    await hub._ready.wait()
    await hass.async_block_till_done()
    got = await _call(
        hass,
        user,
        "journal_query",
        {"room_id": ROOM, "since": SINCE, "kinds": list(kinds)},
    )
    return got["events"]


@pytest.fixture
async def room(hass, hass_admin_user):
    await _install(hass)
    return await _call(hass, hass_admin_user, "setup_read", {})


async def test_setup_save_emits_config_changed_with_the_diff(
    hass, hass_admin_user, room
):
    first = room["rooms"][0]
    await _call(
        hass,
        hass_admin_user,
        "setup_save",
        {
            "entry_id": first["entry_id"],
            "expected_revision": first["revision"],
            "room_name": "Back room",
            "active": first["active"],
            "zones": first["zones"],
            "hardware": first["hardware"],
        },
    )
    (event,) = await _journal(hass, hass_admin_user, "config.changed")
    assert event["source"]["actor"] == "manual"
    assert event["source"]["user_id"] == hass_admin_user.id
    data = event["data"]
    assert (data["store"], data["section"]) == ("setup", "room")
    assert (
        data["old"]["room_name"] == "Tent" and data["new"]["room_name"] == "Back room"
    )
    assert {"path": "room_name", "old": "Tent", "new": "Back room"} in data["diff"]
    assert event["correlation"]["setup_revision"] == data["new"]["revision"]


async def test_strategy_activate_emits_plan_armed(hass, hass_admin_user, room):
    manager = hass.data[DOMAIN]["_strategy"][room["rooms"][0]["entry_id"]]
    manager._readiness = (
        lambda now, zone_ids: {}
    )  # the controller's heartbeat is not what this is about
    saved = await _call(
        hass,
        hass_admin_user,
        "strategy_save",
        {
            "room_id": ROOM,
            "plan": manager.document["plan"],
            "expected_revision": manager.document["revision"],
        },
    )
    armed = await _call(
        hass,
        hass_admin_user,
        "strategy_activate",
        {"room_id": ROOM, "expected_revision": saved["revision"]},
    )
    assert armed["status"] == "armed"
    events = await _journal(hass, hass_admin_user, "plan.saved", "plan.armed")
    assert [e["kind"] for e in events] == ["plan.saved", "plan.armed"]
    assert events[1]["source"]["actor"] == "manual"
    assert events[1]["data"]["revision"] == saved["revision"]
    assert events[1]["data"]["status"] == "armed"
