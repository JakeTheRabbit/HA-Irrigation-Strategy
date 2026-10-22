"""The room's AI overlays: a setting the AI brain moved, which goes back to the operator's value by itself.

An overlay opens when the controller's brain writes one of this room's numbers and names, with its
`crop_steering_setpoint_write` event (setpoint_log.py), when the change runs out: the lights-on that
ends the grow-day it is for. Until then the number holds the AI's value (`new`); underneath it the
value is the operator's (`old`), and a further AI move on the same setting keeps that `old`. When it
runs out the operator's value is put back. Any other write to the number meanwhile (the operator, an
automation, the learner, the safety put-back) ends the overlay and that value stands. Keep ends it
with the AI's value kept as the operator's; Undo puts the operator's value back now. Both are also on the
phone: the push about the AI's move carries Keep and Undo (notify_api.py), and a tap comes back as the
mobile_app app's `mobile_app_notification_action` event, as the phone's own user, who must be an
administrator here as on the page.

One Home Assistant store per room. A room that has never had one (a fresh install, or one updated
from a version without overlays) reads as none, and nothing is written until the brain moves a
setting: a number the brain wrote before the update is a plain value and never goes back.
"""

from __future__ import annotations

from datetime import timedelta
from functools import partial
import logging

from . import setpoint_log
from .const import DOMAIN
from .journal_api import attribution, note
from .notify_api import KEEP, UNDO
from .room import room_prefix

_LOGGER = logging.getLogger(__name__)

SERVICES = ("overlay_get", "overlay_keep", "overlay_undo")
TAPPED = "mobile_app_notification_action"
ACTIONS = {KEEP: "overlay_keep", UNDO: "overlay_undo"}


def _when(value):
    """An overlay's `expires` -> an aware datetime, or None when it names no time."""
    from homeassistant.util import dt as dt_util

    when = dt_util.parse_datetime(value) if isinstance(value, str) else None
    return when if when is not None and when.tzinfo is not None else None


class Overlays:
    def __init__(self, hass, entry, store=None):
        self.hass, self.entry = hass, entry
        self.room_id = "room:" + room_prefix(entry)
        self._store = store
        self._timers = {}  # entity_id -> cancel
        # entity_id -> {entity_id, zone, field, old, new, by, at, expires}
        self.rows = {}
        self.error = None

    async def async_init(self):
        try:
            if self._store is None:
                from homeassistant.helpers.storage import Store

                self._store = Store(
                    self.hass, 1, f"{DOMAIN}.overlays.{self.entry.entry_id}"
                )
            value = await self._store.async_load()
            if value is not None:
                if not isinstance(value, dict) or not isinstance(
                    value.get("overlays"), list
                ):
                    raise ValueError("Invalid stored AI overlays")
                self.rows = {
                    row["entity_id"]: row
                    for row in value["overlays"]
                    if isinstance(row, dict)
                    and isinstance(row.get("entity_id"), str)
                    and _when(row.get("expires")) is not None
                }
        except Exception as error:
            self.error = f"Stored AI overlays could not be loaded; they have not been overwritten: {error}"
        for entity_id, row in self.rows.items():
            self._arm(entity_id, _when(row["expires"]))

    def _arm(self, entity_id, when):
        from homeassistant.helpers.event import async_track_point_in_utc_time

        self._cancel(entity_id)
        self._timers[entity_id] = async_track_point_in_utc_time(
            self.hass, partial(self._ran_out, entity_id), when
        )

    def _cancel(self, entity_id):
        cancel = self._timers.pop(entity_id, None)
        if cancel is not None:
            cancel()

    def unload(self):
        for entity_id in list(self._timers):
            self._cancel(entity_id)

    async def _save(self):
        await self._store.async_save({"overlays": list(self.rows.values())})

    async def written(self, entity_id, field, zone, old, new, who, expires):
        """Every write to one of the room's numbers (number.py): a brain write naming when it runs out
        opens or moves an overlay; any other write ends the one on that number."""
        from homeassistant.util import dt as dt_util

        if self.error is not None or old == new:
            return
        row = self.rows.get(entity_id)
        when = _when(expires) if who == "brain" else None
        base = row["old"] if row is not None else old
        if when is None or base is None or base == new:
            if row is not None:
                await self.end(entity_id)
            return
        self.rows[entity_id] = {
            "entity_id": entity_id,
            "zone": zone,
            "field": field,
            "old": base,
            "new": new,
            "by": who,
            "at": dt_util.utcnow().isoformat(timespec="seconds"),
            "expires": when.isoformat(timespec="seconds"),
        }
        await self._save()
        self._arm(entity_id, when)

    async def end(self, entity_id, *, put_back=False, context=None):
        """End the overlay on `entity_id` -> its row, or None when there is none. `put_back`: the
        operator's value goes back on the number, if it still holds the AI's value."""
        row = self.rows.pop(entity_id, None)
        self._cancel(entity_id)
        if row is None:
            return None
        await self._save()
        state = self.hass.states.get(entity_id)
        try:
            holds = abs(float(state.state) - float(row["new"])) < 1e-6
        except (AttributeError, TypeError, ValueError):
            holds = False
        if put_back and holds:
            log = setpoint_log.log_for(self.hass, self.entry.entry_id)
            # Running out (no caller): the change log records the AI's change going back.
            if context is None and log is not None:
                log.claim(
                    {
                        "entity_id": entity_id,
                        "value": row["old"],
                        "who": "brain",
                        "reason": "overlay ran out",
                    }
                )
            await self.hass.services.async_call(
                "number",
                "set_value",
                {"entity_id": entity_id, "value": row["old"]},
                blocking=True,
                context=context,
            )
        return row

    def journal(self, row, call, *, undone):
        """Keep or Undo on an overlay -> a `target.changed` on the overlay layer that says the overlay is gone
        (`new` is None). It is not a value change: Undo's put-back is the base layer's own row (setpoint_log),
        and Keep moves no value."""
        try:
            who = attribution(self.hass, call)
            zone = row.get("zone")
            note(
                self.hass,
                self.room_id,
                "target.changed",
                zone=zone,
                actor=who["actor"],
                user_id=who["user_id"],
                client=who["client"],
                correlation={"proposal_token": who["proposal_token"]},
                data={
                    "key": row.get("field"),
                    "scope": "room" if zone is None else f"zone:{zone}",
                    "layer": "overlay",
                    "old": row["new"],
                    "new": None,
                    "expires": row.get("expires"),
                    "reason": "undone" if undone else "kept",
                    "expected": None,
                    "entity_id": row["entity_id"],
                },
            )
        except Exception as err:  # the journal never undoes a keep or an undo
            _LOGGER.debug("Overlay journal event not recorded: %s", err)

    async def _ran_out(self, entity_id, _now):
        from homeassistant.util import dt as dt_util

        self._timers.pop(entity_id, None)
        state = self.hass.states.get(entity_id)
        if entity_id in self.rows and (
            state is None or state.state in ("unknown", "unavailable")
        ):
            # The number is not loaded yet (Home Assistant starting): try again in a minute.
            self._arm(entity_id, dt_util.utcnow() + timedelta(minutes=1))
            return
        await self.end(entity_id, put_back=True)

    def response(self):
        return {
            "schema_version": 1,
            "room_id": self.room_id,
            "overlays": sorted(
                (dict(row) for row in self.rows.values()), key=lambda r: r["at"]
            ),
            "error": self.error,
        }


def overlays_for(hass, entry_id):
    return hass.data.get(DOMAIN, {}).get("_overlays", {}).get(entry_id)


async def async_setup_overlays(hass, entry):
    import voluptuous as vol
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError

    from .admin import async_require_admin
    from .api_v2 import fields, wrap

    held = Overlays(hass, entry)
    await held.async_init()
    rooms = hass.data.setdefault(DOMAIN, {}).setdefault("_overlays", {})
    rooms[entry.entry_id] = held

    def room(call):
        matches = [
            item for item in rooms.values() if item.room_id == call.data["room_id"]
        ]
        if len(matches) != 1:
            raise HomeAssistantError("AI overlay room is unknown or ambiguous")
        return matches[0]

    async def get(call):
        # Reading only: anyone who may look at the room may see what the AI has changed.
        return room(call).response()

    async def keep(call):
        await async_require_admin(hass, call, f"{DOMAIN}.{call.service}")
        held = room(call)
        ended = await held.end(call.data["entity_id"])
        if ended is None:
            raise HomeAssistantError(f"No AI overlay on {call.data['entity_id']}")
        held.journal(ended, call, undone=False)

    async def undo(call):
        await async_require_admin(hass, call, f"{DOMAIN}.{call.service}")
        held = room(call)
        ended = await held.end(
            call.data["entity_id"], put_back=True, context=call.context
        )
        if ended is None:
            raise HomeAssistantError(f"No AI overlay on {call.data['entity_id']}")
        held.journal(ended, call, undone=True)

    one = vol.Schema(fields({vol.Required("room_id"): str}))
    each = vol.Schema({vol.Required("room_id"): str, vol.Required("entity_id"): str})
    hass.services.async_register(
        DOMAIN,
        "overlay_get",
        wrap(get),
        schema=one,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(DOMAIN, "overlay_keep", keep, schema=each)
    hass.services.async_register(DOMAIN, "overlay_undo", undo, schema=each)

    async def tapped(event):
        """Keep or Undo tapped on a phone: each setting it names, through the same service as the page,
        as the phone's user. One that has run out or ended meanwhile has nothing left to do.
        """
        head, _, ids = str(event.data.get("action", "")).partition(":")
        if head not in ACTIONS:
            return
        for entity_id in filter(None, ids.split(",")):
            held = next(
                (item for item in rooms.values() if entity_id in item.rows), None
            )
            if held is None:
                _LOGGER.info(
                    "Crop Steering: %s from a phone: no AI overlay on %s now",
                    head,
                    entity_id,
                )
                continue
            try:
                await hass.services.async_call(
                    DOMAIN,
                    ACTIONS[head],
                    {"room_id": held.room_id, "entity_id": entity_id},
                    blocking=True,
                    context=event.context,
                )
            except Exception as error:  # a refused tap changes nothing
                _LOGGER.warning(
                    "Crop Steering: %s from a phone not done on %s: %s",
                    head,
                    entity_id,
                    error,
                )

    if "_overlay_taps" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["_overlay_taps"] = hass.bus.async_listen(TAPPED, tapped)


async def async_unload_overlays(hass, entry):
    rooms = hass.data.get(DOMAIN, {}).get("_overlays", {})
    held = rooms.pop(entry.entry_id, None)
    if held is not None:
        held.unload()
    if not rooms:
        for service in SERVICES:
            hass.services.async_remove(DOMAIN, service)
        stop = hass.data.get(DOMAIN, {}).pop("_overlay_taps", None)
        if stop is not None:
            stop()
