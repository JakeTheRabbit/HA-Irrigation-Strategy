"""A saved change to a room's setup is recorded where Home Assistant keeps who changed what: its
logbook (the Activity panel, and the room's device page), with the person who saved it, and its
log at INFO. A refused change records nothing: nothing changed, and its reason is the refusal.

The integration fires the logbook's own event, and these read the entries back through the real
recorder and the real logbook, as the Activity panel does."""

import logging
from datetime import timedelta

import pytest
from homeassistant.components.logbook.helpers import async_determine_event_types
from homeassistant.components.logbook.processor import EventProcessor
from homeassistant.components.recorder import get_instance
from homeassistant.const import EVENT_LOGBOOK_ENTRY
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.crop_steering.setup_api import LOGBOOK_ENTRY
from test_setup_entry import _install

DOMAIN = "crop_steering"
# The wizard's room is new, so it has a slug: "Tent" is tent_.
DESCRIPTOR = "sensor.crop_steering_tent_engine_config"
ENGINE = "switch.crop_steering_tent_engine_enabled"


@pytest.fixture
def mock_recorder_before_hass(async_test_recorder):
    """The recorder's database is made before Home Assistant is: the test plugin's rule, which
    this repository's own autouse fixtures (they need `hass`) would otherwise break."""


@pytest.fixture
async def room(recorder_mock, hass, hass_admin_user, caplog):
    assert await async_setup_component(hass, "logbook", {})
    await _install(hass)
    caplog.set_level(logging.INFO, logger=f"custom_components.{DOMAIN}.setup_api")
    return await _call(hass, hass_admin_user, "setup_read", {})


async def _call(hass, user, service, data):
    return await hass.services.async_call(
        DOMAIN,
        service,
        data,
        blocking=True,
        return_response=True,
        context=Context(user_id=user.id),
    )


def _saved_as(document, name):
    """What Rooms & hardware sends to save the room under a new name."""
    room = document["rooms"][0]
    return {
        "entry_id": room["entry_id"],
        "expected_revision": room["revision"],
        "room_name": name,
        "active": room["active"],
        "zones": room["zones"],
        "hardware": room["hardware"],
    }


async def _activity(hass):
    """This integration's lines in the room's Activity, as the logbook serves them: the room's
    device page asks for its entities' entries, the room descriptor among them."""
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)
    processor = EventProcessor(
        hass, async_determine_event_types(hass, [DESCRIPTOR], None), [DESCRIPTOR]
    )
    now = dt_util.utcnow()
    rows = await get_instance(hass).async_add_executor_job(
        processor.get_events, now - timedelta(hours=1), now + timedelta(minutes=1)
    )
    return [row for row in rows if row.get("domain") == DOMAIN]


def test_it_fires_the_event_the_logbook_records():
    assert LOGBOOK_ENTRY == EVENT_LOGBOOK_ENTRY


async def test_a_rename_is_in_the_rooms_activity_with_who_saved_it(
    hass, hass_admin_user, room, caplog
):
    await _call(hass, hass_admin_user, "setup_save", _saved_as(room, "Back room"))
    (line,) = await _activity(hass)
    assert (line["name"], line["message"], line["entity_id"]) == (
        "Back room",
        "setup saved (revision 2): renamed from “Tent”",
        DESCRIPTOR,
    )
    assert line["context_user_id"] == hass_admin_user.id
    assert "Back room: setup saved (revision 2): renamed from “Tent”" in caplog.messages


async def test_a_refused_change_records_nothing(hass, hass_admin_user, room, caplog):
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": ENGINE}, blocking=True
    )
    with pytest.raises(HomeAssistantError, match="must read OFF"):
        await _call(hass, hass_admin_user, "setup_save", _saved_as(room, "Back room"))
    assert await _activity(hass) == []
    assert not [m for m in caplog.messages if "setup saved" in m]


async def test_archiving_and_restoring_the_room_are_recorded(
    hass, hass_admin_user, room
):
    await _call(
        hass,
        hass_admin_user,
        "setup_remove",
        {
            "entry_id": room["rooms"][0]["entry_id"],
            "expected_revision": room["rooms"][0]["revision"],
            "confirm_name": "Tent",
        },
    )
    archived = await _call(hass, hass_admin_user, "setup_read", {})
    restore = {**_saved_as(archived, "Tent"), "active": True}
    await _call(hass, hass_admin_user, "setup_save", restore)
    assert [line["message"] for line in await _activity(hass)] == [
        "archived (revision 2)",
        "setup saved (revision 3): restored",
    ]
