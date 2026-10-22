"""The room's setpoint change log: which setting moved, from what to what, when, and who moved it.

Every write to one of this room's numbers is appended here (number.py), one Home Assistant store
per room. It is append-only: nothing edits or removes a row, and only the oldest fall off past
MAX_CHANGES. A room that has never written one (a fresh install, or one updated from a version
without the log) reads as an empty log; nothing is written until a setting moves.

Who: Home Assistant sees only the controller app's token, so the controller names the writer of
each of its writes first, with the `crop_steering_setpoint_write` event (the learner, the AI brain,
or the brain's safety put-back). A claim names one write: that write consumes it, and the controller
takes it back (`crop_steering_setpoint_claim_cancel`) when its write did not land. A write it has not
named is the operator's when a signed-in person made it, and Home Assistant's own (an automation or a
script) otherwise.
"""

from __future__ import annotations

import asyncio
import time
from copy import deepcopy

from .const import DOMAIN
from .room import room_prefix

MAX_CHANGES = 2000
CLAIM_EVENT = f"{DOMAIN}_setpoint_write"
CANCEL_EVENT = f"{DOMAIN}_setpoint_claim_cancel"
# A named write lands within seconds; a claim older than this names nothing.
CLAIM_S = 120
CONTROLLER_WRITERS = ("learner", "brain", "safety")
SERVICE = "setpoint_log_get"


class SetpointLog:
    def __init__(self, hass, entry, store=None):
        self.hass, self.entry = hass, entry
        self.room_id = "room:" + room_prefix(entry)
        self._store = store
        self._lock = asyncio.Lock()
        # entity_id -> (value, who, monotonic seconds, expires or None, reason or None, expected or None,
        # claim_id or None: a controller from before CTL-035 sends none)
        self._claims = {}
        self._reasons = (
            {}
        )  # entity_id -> (reason, expected) the last named write gave, for record()
        self.changes = []
        self.error = None

    async def async_init(self):
        try:
            if self._store is None:
                from homeassistant.helpers.storage import Store

                self._store = Store(
                    self.hass, 1, f"{DOMAIN}.setpoint_log.{self.entry.entry_id}"
                )
            value = await self._store.async_load()
            if value is not None:
                if not isinstance(value, dict) or not isinstance(
                    value.get("changes"), list
                ):
                    raise ValueError("Invalid stored setpoint change log")
                self.changes = [
                    row for row in value["changes"] if isinstance(row, dict)
                ]
        except Exception as error:
            self.error = f"Stored setpoint change log could not be loaded; it has not been overwritten: {error}"

    def claim(self, data):
        """The controller is about to write `entity_id` = `value`, as `who`."""
        try:
            entity_id, value, who = data["entity_id"], float(data["value"]), data["who"]
        except (KeyError, TypeError, ValueError):
            return
        if isinstance(entity_id, str) and who in CONTROLLER_WRITERS:
            # `expires`: a brain write that is an overlay going back by itself then (overlays.py).
            expires = data.get("expires")
            # `reason`: why the controller moved it, in words (an AI assistant change says why).
            # `reason` and `expected`: why the controller moved it and the result it expects, in words (an AI
            # assistant power's write names both; the next night's scorecard compares the result).
            reason, expected = (
                text[:200] if isinstance(text, str) and text else None
                for text in (data.get("reason"), data.get("expected"))
            )
            self._claims[entity_id] = (
                value,
                who,
                time.monotonic(),
                expires,
                reason,
                expected,
                data.get("claim_id"),
            )

    def cancel(self, data):
        """The controller's write did not land: drop its claim, when it is still the one named."""
        try:
            claim = self._claims.get(data["entity_id"])
            same = (
                claim is not None
                and claim[6] is not None
                and claim[6] == data.get("claim_id")
                and claim[1] == data.get("who")
                and abs(claim[0] - float(data["value"])) < 1e-6
            )
        except (KeyError, TypeError, ValueError):
            return
        if same:
            del self._claims[data["entity_id"]]

    async def who(self, entity_id, value, context):
        """-> (who, the expiry the controller named with its write, or None)."""
        claim = self._claims.pop(entity_id, None)
        if (
            claim is not None
            and abs(claim[0] - float(value)) < 1e-6
            and time.monotonic() - claim[2] <= CLAIM_S
        ):
            if claim[4] or claim[5]:
                self._reasons[entity_id] = (claim[4], claim[5])
            return claim[1], claim[3]
        user_id = getattr(context, "user_id", None)
        user = await self.hass.auth.async_get_user(user_id) if user_id else None
        return (
            "operator"
            if user is not None and not user.system_generated
            else "home_assistant"
        ), None

    async def record(self, entity_id, field, zone, old, new, context):
        """Append one change -> (who, expires) as who(). A log that could not be loaded is never overwritten."""
        from homeassistant.util import dt as dt_util

        self._reasons.pop(entity_id, None)
        who, expires = await self.who(entity_id, new, context)
        reason, expected = self._reasons.pop(entity_id, None) or (None, None)
        if self.error is not None or old == new:
            return who, expires
        row = {
            "at": dt_util.utcnow().isoformat(timespec="seconds"),
            "entity_id": entity_id,
            "field": field,
            "zone": zone,
            "old": old,
            "new": new,
            "who": who,
        }
        if reason:  # only a write the controller named with a reason carries one
            row["reason"] = reason
        if expected:
            row["expected"] = expected
        async with self._lock:
            self.changes.append(row)
            del self.changes[:-MAX_CHANGES]
            await self._store.async_save({"changes": self.changes})
        return who, expires

    def response(self):
        return {
            "schema_version": 1,
            "room_id": self.room_id,
            "changes": deepcopy(self.changes),
            "error": self.error,
            "max_changes": MAX_CHANGES,
        }


def log_for(hass, entry_id):
    return hass.data.get(DOMAIN, {}).get("_setpoint_log", {}).get(entry_id)


async def async_setup_setpoint_log(hass, entry):
    import voluptuous as vol
    from homeassistant.core import SupportsResponse, callback
    from homeassistant.exceptions import HomeAssistantError

    log = SetpointLog(hass, entry)
    await log.async_init()
    logs = hass.data.setdefault(DOMAIN, {}).setdefault("_setpoint_log", {})
    logs[entry.entry_id] = log

    @callback
    def claimed(event):
        log.claim(event.data)

    @callback
    def cancelled(event):
        log.cancel(event.data)

    entry.async_on_unload(hass.bus.async_listen(CLAIM_EVENT, claimed))
    entry.async_on_unload(hass.bus.async_listen(CANCEL_EVENT, cancelled))

    async def handle(call):
        # Reading only: anyone who may look at the room may read who changed what.
        matches = [
            item for item in logs.values() if item.room_id == call.data["room_id"]
        ]
        if len(matches) != 1:
            raise HomeAssistantError("Setpoint change log room is unknown or ambiguous")
        return matches[0].response()

    hass.services.async_register(
        DOMAIN,
        SERVICE,
        handle,
        schema=vol.Schema({vol.Required("room_id"): str}),
        supports_response=SupportsResponse.ONLY,
    )


async def async_unload_setpoint_log(hass, entry):
    logs = hass.data.get(DOMAIN, {}).get("_setpoint_log", {})
    logs.pop(entry.entry_id, None)
    if not logs:
        hass.services.async_remove(DOMAIN, SERVICE)
