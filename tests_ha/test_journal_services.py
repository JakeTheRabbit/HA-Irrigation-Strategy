"""The event journal through a real Home Assistant: journal_append and journal_query in its service registry and
auth store, and the crop_steering/subscribe websocket feed for a user who may not use subscribe_events."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import Context, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from test_setup_entry import _install

from custom_components.crop_steering.generated.ids import new_id

DOMAIN = "crop_steering"
F2, F1 = "room:f2_", "room:f1_"
REFUSED = "requires an authenticated Home Assistant administrator"


@pytest.fixture(autouse=True)
def _custom_integrations(hass, enable_custom_integrations):
    hass.config.components.add("frontend")
    yield


def _event(kind="shot.completed", **over):
    ev = {
        "v": 1,
        "id": new_id(),
        "ts": "2026-10-22T07:00:00+00:00",
        "kind": kind,
        "zone": 3,
        "outcome": "ok",
        "source": {"actor": "engine"},
        "correlation": {"intent_id": None},
        "data": {},
    }
    ev.update(over)
    return ev


async def _call(hass, user, name, **data):
    return await hass.services.async_call(
        DOMAIN,
        name,
        data,
        blocking=True,
        return_response=True,
        context=Context(user_id=user.id) if user else Context(),
    )


async def _up(hass, real_api, monkeypatch):
    monkeypatch.setattr(
        hass.http, "async_register_static_paths", AsyncMock(), raising=False
    )
    await _install(hass)


async def test_query_round_trips_what_append_stored(
    hass, real_api, hass_admin_user, monkeypatch
):
    await _up(hass, real_api, monkeypatch)
    assert (
        hass.services.supports_response(DOMAIN, "journal_query")
        is SupportsResponse.ONLY
    )
    assert (
        hass.services.supports_response(DOMAIN, "journal_append")
        is SupportsResponse.OPTIONAL
    )
    fired = []
    hass.bus.async_listen("crop_steering_event", lambda e: fired.append(e.data))
    first = _event()
    out = await _call(
        hass,
        hass_admin_user,
        "journal_append",
        room_id=F2,
        events=[first, _event(), first],
    )
    assert (len(out["accepted"]), len(out["duplicate"]), out["seq_max"]) == (2, 1, 2)
    await hass.async_block_till_done()
    assert [e["seq"] for e in fired] == [1, 2]
    got = await _call(
        hass,
        hass_admin_user,
        "journal_query",
        room_id=F2,
        since="2026-10-22T00:00:00+00:00",
    )
    assert got["events"][0]["seq"] == 1 and len(got["events"]) == 2
    assert got["cursor"] is None


async def test_query_needs_a_signed_in_user_and_append_an_admin(
    hass, real_api, hass_read_only_user, monkeypatch
):
    await _up(hass, real_api, monkeypatch)
    with pytest.raises(HomeAssistantError, match=REFUSED):
        await _call(
            hass, hass_read_only_user, "journal_append", room_id=F2, events=[_event()]
        )
    got = await _call(
        hass,
        hass_read_only_user,
        "journal_query",
        room_id=F2,
        since="2026-10-22T00:00:00+00:00",
    )
    assert got["events"] == []
    with pytest.raises(HomeAssistantError, match="signed-in"):
        await hass.services.async_call(
            DOMAIN,
            "journal_query",
            {"room_id": F2, "since": "2026-10-22T00:00:00+00:00"},
            blocking=True,
            return_response=True,
            context=Context(user_id="not-a-user"),
        )


async def test_a_non_admin_websocket_subscriber_gets_only_its_rooms_events(
    hass, real_api, hass_admin_user, hass_ws_client, hass_read_only_access_token, monkeypatch
):
    await _up(hass, real_api, monkeypatch)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json(
        {"id": 1, "type": "crop_steering/subscribe", "rooms": [F2]}
    )
    assert (await client.receive_json())["success"] is True
    mine, other = _event(), _event()
    await _call(hass, hass_admin_user, "journal_append", room_id=F2, events=[mine])
    await _call(hass, hass_admin_user, "journal_append", room_id=F1, events=[other])
    msg = await asyncio.wait_for(client.receive_json(), 5)
    assert msg["type"] == "event" and msg["id"] == 1
    assert msg["event"]["id"] == mine["id"] and msg["event"]["room_id"] == F2
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(client.receive_json(), 0.3)


async def test_subscribe_without_a_user_is_refused(hass):
    from custom_components.crop_steering.journal_api import _ws_subscribe_handler

    connection = MagicMock(user=None)
    _ws_subscribe_handler(hass, connection, {"id": 7, "type": "crop_steering/subscribe"})
    connection.send_error.assert_called_once()
    assert connection.send_error.call_args.args[:2] == (7, "unauthorized")
    connection.send_result.assert_not_called()


async def test_the_kinds_filter_of_the_websocket_feed(
    hass, real_api, hass_admin_user, hass_ws_client, hass_read_only_access_token, monkeypatch
):
    await _up(hass, real_api, monkeypatch)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json(
        {"id": 1, "type": "crop_steering/subscribe", "kinds": ["phase.changed"]}
    )
    assert (await client.receive_json())["success"] is True
    shot, phase = _event("shot.completed"), _event("phase.changed")
    await _call(
        hass, hass_admin_user, "journal_append", room_id=F2, events=[shot, phase]
    )
    msg = await asyncio.wait_for(client.receive_json(), 5)
    assert msg["event"]["id"] == phase["id"]
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(client.receive_json(), 0.3)
