"""A refused setup edit is actionable validation and cannot change settings or controls."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from aiohttp import connector
from aiohttp.resolver import ThreadedResolver
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from test_setup_entry import _install

ENGINE = "switch.crop_steering_tent_engine_enabled"


@pytest.fixture(autouse=True)
def _custom_integrations(hass, enable_custom_integrations):
    hass.config.components.add("frontend")
    yield


async def test_watering_blocks_setup_with_actionable_validation_and_preserves_settings(
    hass, real_api, hass_access_token, hass_admin_user, hass_ws_client, monkeypatch
):
    monkeypatch.setattr(
        hass.http, "async_register_static_paths", AsyncMock(), raising=False
    )
    await _install(hass)
    context = Context(user_id=hass_admin_user.id)
    document = await hass.services.async_call(
        "crop_steering",
        "setup_read",
        {},
        blocking=True,
        return_response=True,
        context=context,
    )
    room = document["rooms"][0]
    entry = hass.config_entries.async_get_entry(room["entry_id"])
    before = deepcopy((dict(entry.data), dict(entry.options)))
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": ENGINE}, blocking=True
    )
    payload = {key: room[key] for key in ["entry_id", "active", "zones", "hardware"]}
    payload.update(expected_revision=room["revision"], room_name="Changed room")
    with pytest.raises(HomeAssistantError, match=f"{ENGINE} must read OFF"):
        await hass.services.async_call(
            "crop_steering",
            "setup_save",
            payload,
            blocking=True,
            return_response=True,
            context=context,
        )
    assert (entry.data, entry.options) == before
    assert hass.states.get(ENGINE).state == "on"
    # This client only connects to the fixture's numeric loopback address. Avoid
    # creating pycares' process-long shutdown thread for an unused DNS resolver:
    # the oldest HA pytest plugin correctly rejects it as a leaked test thread.
    with monkeypatch.context() as transport:
        transport.setattr(connector, "DefaultResolver", ThreadedResolver)
        client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "call_service",
            "domain": "crop_steering",
            "service": "setup_save",
            "service_data": payload,
            "return_response": True,
        }
    )
    refused = await client.receive_json()
    assert refused["success"] is False
    assert f"{ENGINE} must read OFF" in refused["error"]["message"]
    assert (entry.data, entry.options) == before
    await client.send_json_auto_id(
        {
            "type": "call_service",
            "domain": "crop_steering",
            "service": "setup_read",
            "service_data": {},
            "return_response": True,
        }
    )
    saved = await client.receive_json()
    assert saved["success"] is True
    assert saved["result"]["response"]["rooms"][0]["entry_id"] == room["entry_id"]
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": ENGINE}, blocking=True
    )
    await client.send_json_auto_id(
        {
            "type": "call_service",
            "domain": "crop_steering",
            "service": "setup_save",
            "service_data": payload,
            "return_response": True,
        }
    )
    accepted = await client.receive_json()
    assert accepted["success"] is True
    assert accepted["result"]["response"]["room_name"] == "Changed room"
    assert accepted["result"]["response"]["revision"] == room["revision"] + 1
    assert hass.states.get(ENGINE).state == "off"
