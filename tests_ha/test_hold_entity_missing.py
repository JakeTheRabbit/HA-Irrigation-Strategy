"""A hold entity a REAL Home Assistant does not have, over its real REST API (CS-210).

The controller tells a hold that does not exist from one that is only offline by the answer Home
Assistant gives for it: 404 from `GET /api/states/<entity>`. A fake cannot prove that answer, so here
the hold reads go to Home Assistant's real REST API with an administrator's token, and the card is
created and taken down through its real `persistent_notification` services. The room's other
entities are the controller_for mirror (conftest). Only the HTTP listener's start is stood in for
(conftest.real_api), and the panel's static files, which need that listener.
"""

from unittest.mock import AsyncMock

import controller
import pytest
from conftest import room_of, switch_calls
from homeassistant.components import persistent_notification
from homeassistant.setup import async_setup_component
from test_real_flow import VALVE
from test_setup_entry import _install

KILL = "switch.crop_steering_tent_engine_enabled"
ARMED = (KILL, "switch.crop_steering_tent_system_enabled", "switch.crop_steering_tent_auto_irrigation_enabled",
         "switch.crop_steering_tent_zone_1_enabled")
DOSING = "input_boolean.tank_dosing"
FILL = "input_boolean.tank_fill"
CARD = "f2_holds_missing"
REAL = {name: getattr(controller, name) for name in ("ha_get_status", "ha_call")}


@pytest.fixture(autouse=True)
def _custom_integrations(hass, enable_custom_integrations):
    """Home Assistant's real `http` and `api` (conftest.real_api); the frontend is marked loaded."""
    hass.config.components.add("frontend")
    yield


@pytest.fixture
async def api(hass, real_api, hass_access_token, monkeypatch):
    """The installed room, with the controller's hold reads and its cards going over the real REST API."""
    monkeypatch.setattr(hass.http, "async_register_static_paths", AsyncMock(), raising=False)
    assert await async_setup_component(hass, "persistent_notification", {})
    await _install(hass)
    monkeypatch.setattr(controller, "BASE", real_api)
    monkeypatch.setattr(controller, "HDR", {"Authorization": f"Bearer {hass_access_token}",
                                            "Content-Type": "application/json"})
    return real_api


def wire(fake, monkeypatch):
    """Hold reads and notifications to the real Home Assistant; everything else stays on the mirror."""
    monkeypatch.setattr(controller, "ha_get_status", REAL["ha_get_status"])

    def ha_call(domain, service, **data):
        if domain == "persistent_notification":
            fake.calls.append((domain, service, data))
            return REAL["ha_call"](domain, service, **data)
        return fake.ha_call(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", ha_call)


def cards(hass):
    return persistent_notification._async_get_or_create_notifications(hass)


async def test_a_missing_hold_is_named_at_start_and_its_card_goes_once_it_exists(
    hass, api, controller_for, monkeypatch
):
    hass.states.async_set(DOSING, "off")
    c, fake, _clock = controller_for({"hold_entities": [DOSING, FILL]})
    wire(fake, monkeypatch)
    assert hass.states.get(KILL).state == "off"  # a fresh room: nothing is watered yet

    # At start, before any watering: Home Assistant's real 404 for the missing hold, its 200 for the other.
    await hass.async_add_executor_job(c._check_holds)
    card = cards(hass)[CARD]
    assert card["title"] == "Hold entity not in Home Assistant, no shots (CS-210)"
    assert f"Not in Home Assistant: {FILL}" in card["message"] and DOSING not in card["message"]
    assert switch_calls(fake) == []

    # Watering switched on: the missing hold still holds every shot, and says why.
    for switch in ARMED:
        fake.set_state(switch, "on")
    fake.set_state(VALVE, "off")
    room = room_of(c)
    assert await hass.async_add_executor_job(c._blocked, room, 1) == (
        f"Hold entity {FILL} does not exist in Home Assistant. Remove it from the app's hold entities, "
        "or create it.")

    # Created in Home Assistant: the next check takes the card down, and the hold reads off.
    hass.states.async_set(FILL, "off")
    fake.set_state(FILL, "off")
    await hass.async_add_executor_job(c._check_holds)
    assert CARD not in cards(hass) and c._holds_card is False
    assert await hass.async_add_executor_job(c._blocked, room, 1) != (
        f"Hold entity {FILL} does not exist in Home Assistant. Remove it from the app's hold entities, "
        "or create it.")


async def test_a_hold_that_exists_but_is_unavailable_is_not_called_missing(
    hass, api, controller_for, monkeypatch
):
    hass.states.async_set(FILL, "unavailable")
    c, fake, _clock = controller_for({"hold_entities": [FILL]})
    wire(fake, monkeypatch)
    await hass.async_add_executor_job(c._check_holds)
    assert CARD not in cards(hass)
    for switch in ARMED:
        fake.set_state(switch, "on")
    fake.set_state(VALVE, "off")
    assert await hass.async_add_executor_job(c._blocked, room_of(c), 1) == (
        f"external hold {FILL} unreadable (reads neither on nor off)")
