"""Ask why in a real Home Assistant: crop_steering.brain_ask through its registry, schema and auth
store; sensor.crop_steering_brain_questions, which the controller app reads, under that exact id;
the last five questions kept across a reload."""

import pytest
import voluptuous as vol
from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.core import Context, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockUser
from test_setup_entry import _install

DOMAIN = "crop_steering"
ROOM = "room:"
QUESTIONS = "sensor.crop_steering_brain_questions"
REFUSED = "requires an authenticated Home Assistant administrator"


async def _ask(hass, user, **data):
    return await hass.services.async_call(
        DOMAIN,
        "brain_ask",
        {"room_id": ROOM, **data},
        blocking=True,
        return_response=True,
        context=Context(user_id=user.id if user else None),
    )


async def test_an_administrator_asks_and_the_controller_is_shown_the_question(
    hass, hass_admin_user
):
    entry = await _install(hass)
    responds = hass.services.supports_response(DOMAIN, "brain_ask")
    assert responds is SupportsResponse.OPTIONAL
    registered = er.async_get(hass).async_get(QUESTIONS)
    assert registered.unique_id == f"{DOMAIN}_{entry.entry_id}_brain_questions"
    assert hass.states.get(QUESTIONS).state == "0"

    said = "  Why did zone 1\nnot water?"
    asked = (await _ask(hass, hass_admin_user, question=said, zone=1))["question"]
    assert (asked["question"], asked["zone"], asked["by"]) == (
        "Why did zone 1 not water?",
        1,
        hass_admin_user.name,
    )
    await hass.async_block_till_done()
    shown = hass.states.get(QUESTIONS)
    assert shown.state == "1" and shown.attributes["questions"] == [asked]


async def test_the_schema_caps_a_question_at_300_characters(hass, hass_admin_user):
    await _install(hass)
    assert (await _ask(hass, hass_admin_user, question="w" * 300))["error"] is None
    too_long, no_zone = {"question": "w" * 301}, {"question": "a", "zone": 0}
    for bad in (too_long, {"question": ""}, {}, no_zone):
        with pytest.raises(vol.Invalid):
            await _ask(hass, hass_admin_user, **bad)
    with pytest.raises(HomeAssistantError, match="Type a question"):
        await _ask(hass, hass_admin_user, question="   ")
    with pytest.raises(HomeAssistantError, match="unknown or ambiguous"):
        await hass.services.async_call(
            DOMAIN,
            "brain_ask",
            {"room_id": "room:nowhere_", "question": "why?"},
            blocking=True,
            return_response=True,
        )
    await hass.async_block_till_done()
    assert hass.states.get(QUESTIONS).state == "1"


async def test_a_signed_in_non_administrator_may_not_ask_and_an_automation_may(hass):
    await _install(hass)
    users = await hass.auth.async_get_group(GROUP_ID_USER)
    staff = MockUser(name="Staff phone", groups=[users]).add_to_hass(hass)
    with pytest.raises(HomeAssistantError, match=REFUSED):
        await _ask(hass, staff, question="why?")
    await hass.async_block_till_done()
    assert hass.states.get(QUESTIONS).state == "0"
    assert (await _ask(hass, None, question="why?"))["question"]["by"] is None


async def test_the_last_five_questions_are_kept_across_a_reload(hass, hass_admin_user):
    entry = await _install(hass)
    for n in range(7):
        await _ask(hass, hass_admin_user, question=f"why {n}?")
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    shown = hass.states.get(QUESTIONS)
    assert [q["question"] for q in shown.attributes["questions"]] == [
        f"why {n}?" for n in range(2, 7)
    ]
