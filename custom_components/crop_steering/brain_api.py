"""Ask the AI assistant why: crop_steering.brain_ask, stored per room and served.

A question is stored with its room (the last five) and published as
sensor.crop_steering_<prefix>brain_questions. The controller app reads that, asks the brain when it
runs on Claude Haiku, and publishes each answer, matched by the question's id, as
sensor.crop_steering_<prefix>brain_answers. Nothing here asks anything or changes a setting. An ask
spends the room's AI budget, so a signed-in user must be an administrator; an automation may ask.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import uuid

from .admin import async_require_admin
from .const import DOMAIN, MAX_ZONES
from .room import room_prefix

SERVICE = "brain_ask"
SIGNAL = f"{DOMAIN}_brain_questions_changed"
MAX_QUESTION = 300  # characters: a question, not a document
KEEP = 5  # the questions kept, as the controller keeps the answers


def _valid(value) -> list:
    """The stored questions that are well formed, oldest first; anything else is dropped."""
    items = value.get("questions") if isinstance(value, dict) else None
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        if not isinstance(item.get("question"), str):
            continue
        zone = item.get("zone")
        out.append(
            {
                "id": item["id"],
                "question": item["question"][:MAX_QUESTION],
                "zone": zone if type(zone) is int else None,
                "at": item.get("at") if isinstance(item.get("at"), str) else None,
                "by": item.get("by") if isinstance(item.get("by"), str) else None,
            }
        )
    return out[-KEEP:]


class BrainQuestions:
    def __init__(self, hass, entry, store=None):
        self.hass, self.entry = hass, entry
        self.prefix = room_prefix(entry)
        self.room_id = "room:" + self.prefix
        self._store = store
        self._lock = asyncio.Lock()
        self.questions: list = []

    async def async_init(self):
        if self._store is None:
            from homeassistant.helpers.storage import Store

            self._store = Store(
                self.hass, 1, f"{DOMAIN}.brain_questions.{self.entry.entry_id}"
            )
        # An unreadable file starts empty; the next question rewrites it.
        try:
            self.questions = _valid(await self._store.async_load())
        except Exception:
            self.questions = []

    def sensor(self) -> tuple:
        """sensor.crop_steering_<prefix>brain_questions as (state, attributes): how many are kept,
        and the questions, oldest first."""
        return len(self.questions), {"questions": deepcopy(self.questions)}

    async def ask(self, question, zone, by) -> dict:
        async with self._lock:
            item = {
                "id": uuid.uuid4().hex,
                "question": question,
                "zone": zone,
                "at": datetime.now(timezone.utc).isoformat(),
                "by": by,
            }
            draft = (self.questions + [item])[-KEEP:]
            await self._store.async_save({"questions": draft})
            self.questions = draft
            from homeassistant.helpers.dispatcher import async_dispatcher_send

            async_dispatcher_send(self.hass, f"{SIGNAL}_{self.entry.entry_id}")
            return {"question": deepcopy(item), "error": None}


def resolve_questions(hass, room_id):
    if not isinstance(room_id, str) or not room_id.startswith("room:"):
        raise ValueError("A canonical room_id is required")
    matches = [
        manager
        for manager in hass.data.get(DOMAIN, {}).get("_brain_questions", {}).values()
        if manager.room_id == room_id
    ]
    if len(matches) != 1:
        raise ValueError("Room is unknown or ambiguous")
    return matches[0]


async def async_setup_brain(hass, entry):
    import voluptuous as vol
    from .api_v2 import fields, wrap
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError

    manager = BrainQuestions(hass, entry)
    await manager.async_init()
    hass.data.setdefault(DOMAIN, {}).setdefault("_brain_questions", {})[
        entry.entry_id
    ] = manager

    async def handle(call):
        await async_require_admin(hass, call, f"{DOMAIN}.{SERVICE}")
        question = " ".join(call.data["question"].split())
        if not question:
            raise HomeAssistantError("Type a question to ask")
        try:
            target = resolve_questions(hass, call.data["room_id"])
        except ValueError as error:
            raise HomeAssistantError(str(error)) from error
        user_id = getattr(call.context, "user_id", None)
        user = await hass.auth.async_get_user(user_id) if user_id else None
        by = getattr(user, "name", None)
        return await target.ask(question, call.data.get("zone"), by)

    hass.services.async_register(
        DOMAIN,
        SERVICE,
        wrap(handle),
        schema=vol.Schema(
            fields(
                {
                    vol.Required("room_id"): str,
                    vol.Required("question"): vol.All(
                        str, vol.Length(min=1, max=MAX_QUESTION)
                    ),
                    vol.Optional("zone"): vol.All(int, vol.Range(min=1, max=MAX_ZONES)),
                }
            )
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )


async def async_unload_brain(hass, entry):
    managers = hass.data.get(DOMAIN, {}).get("_brain_questions", {})
    managers.pop(entry.entry_id, None)
    if not managers:
        hass.services.async_remove(DOMAIN, SERVICE)
