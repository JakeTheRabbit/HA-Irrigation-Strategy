"""Batch-tank dosing per room, stored and served; see dosing.py for the rules and docs/DOSING.md for
the contract.

Response-only services addressed by canonical room id, like the stock services. Reading is open to
any signed-in user, and so is a stop; saving the setup and asking for a dose or a batch need an
administrator. Nothing here switches, presses or sets any hardware: the room's setup and its one
request are published as sensor.crop_steering_<prefix>dosing_config, and the controller app, which
reads that every 2 s, does the work and reports it as sensor.crop_steering_<prefix>dosing.

The sensor's batch carries the recipe in use today (dosing.in_use: the feed schedule's week, a
recipe picked by hand, else the batch's own), and is written again at Home Assistant's midnight, so
the week moves on by itself.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import date, datetime, timezone
import uuid

from . import dosing
from .admin import async_require_admin
from .const import DOMAIN
from .room import room_prefix

SERVICES = ("dosing_get", "dosing_save", "dosing_request")
SIGNAL = f"{DOMAIN}_dosing_changed"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> date:
    """Today in Home Assistant's time zone: the feed schedule's day."""
    from homeassistant.util import dt as dt_util

    return dt_util.now().date()


def _valid(value) -> dict:
    """A stored document, checked as strictly as a save except that its entities need not exist
    yet (a device that has not come back since Home Assistant started); anything else is refused.
    """
    if not isinstance(value, dict) or type(value.get("revision")) is not int:
        raise ValueError("Invalid stored revision")
    data = dosing.empty()
    data["revision"] = value["revision"]
    data["pumps"], data["batch"] = dosing.clean(
        value.get("pumps", []), value.get("batch")
    )
    data["feed"] = dosing.clean_feed(value.get("feed"), data["pumps"])
    request = value.get("request")
    data["request"] = (
        request if isinstance(request, dict) and request.get("id") else None
    )
    updated = value.get("updated_at")
    data["updated_at"] = updated if isinstance(updated, str) else None
    return data


class DosingStore:
    def __init__(self, hass, entry, store=None):
        self.hass, self.entry = hass, entry
        self.prefix = room_prefix(entry)
        self.room_id = "room:" + self.prefix
        self._store = store
        self._lock = asyncio.Lock()
        self.data = dosing.empty()
        self.error = None

    @property
    def status_entity(self) -> str:
        """What the controller app publishes about this room's dosing (docs/DOSING.md, Status)."""
        return f"sensor.{DOMAIN}_{self.prefix}dosing"

    async def async_init(self):
        try:
            if self._store is None:
                from homeassistant.helpers.storage import Store

                self._store = Store(
                    self.hass, 1, f"{DOMAIN}.dosing.{self.entry.entry_id}"
                )
            value = await self._store.async_load()
            if value is not None:
                self.data = _valid(value)
        except Exception as error:
            self.error = (
                "The stored dosing setup could not be loaded; it has not been overwritten: "
                f"{error}"
            )

    def start(self):
        """Write the sensor again at each of Home Assistant's midnights, when the feed schedule's
        week may move on. Returns the unsubscribe."""
        from homeassistant.core import callback
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        from homeassistant.helpers.event import async_track_time_change

        @callback
        def midnight(_now):
            async_dispatcher_send(self.hass, f"{SIGNAL}_{self.entry.entry_id}")

        return async_track_time_change(self.hass, midnight, hour=0, minute=0, second=0)

    def pending(self) -> bool:
        """Whether the stored request still waits for the controller (dosing.pending): it reads the
        request id the controller last published as handled."""
        state = self.hass.states.get(self.status_entity)
        handled = (state.attributes or {}).get("handled") if state else None
        return dosing.pending(self.data["request"], handled, _now())

    def running(self) -> bool:
        """Whether the controller reports a dose or a batch running in this room: its setup is not
        changed under it."""
        state = self.hass.states.get(self.status_entity)
        return state is not None and state.state in ("dosing", "batch")

    def candidates(self) -> list[dict]:
        """Every entity of a domain the setup can use, for the dashboard's pickers."""
        out = []
        for state in self.hass.states.async_all(dosing.CANDIDATE_DOMAINS):
            attributes = state.attributes or {}
            out.append(
                {
                    "entity_id": state.entity_id,
                    "name": attributes.get("friendly_name") or state.entity_id,
                    "domain": state.entity_id.split(".", 1)[0],
                    "state": state.state,
                    "unit": attributes.get("unit_of_measurement"),
                    "device_class": attributes.get("device_class"),
                }
            )
        return sorted(out, key=lambda item: item["entity_id"])

    def response(self, error=None, can_edit=False) -> dict:
        """What dosing_get answers. `can_edit`: the caller is an administrator, who may save."""
        return {
            "schema_version": 1,
            "room_id": self.room_id,
            "config": deepcopy(self.data),
            "feed_now": dosing.feed_now(self.data["feed"], _today()),
            "candidates": self.candidates(),
            "can_edit": can_edit,
            "error": error or self.error,
        }

    def sensor(self) -> tuple:
        """sensor.crop_steering_<prefix>dosing_config as (state, attributes): the setup's revision,
        and its pumps, batch (its recipe the one in use today) and request, and `feed`: which recipe
        that is and why (dosing.feed_now). Unknown while the stored setup cannot be read, so the
        controller acts on nothing it cannot read."""
        if self.error:
            return None, {"error": self.error}
        batch = deepcopy(self.data["batch"])
        batch["recipe"] = self.recipe()
        return self.data["revision"], {
            "pumps": deepcopy(self.data["pumps"]),
            "batch": batch,
            "request": deepcopy(self.data["request"]),
            "feed": dosing.feed_now(self.data["feed"], _today()),
        }

    def recipe(self) -> list[dict]:
        """The doses of the recipe in use today (dosing.in_use), else the batch's own recipe."""
        recipe = dosing.in_use(self.data["feed"], _today())
        return deepcopy(recipe["doses"] if recipe else self.data["batch"]["recipe"])

    async def save(self, data, can_edit=False) -> dict:
        async with self._lock:
            if self.error:
                return self.response(can_edit=can_edit)
            if data.get("expected_revision") != self.data["revision"]:
                return self.response("revision", can_edit)
            if self.pending() or self.running():
                return self.response("busy", can_edit)
            stored = self.data["feed"]
            # A save without the feed (a dashboard from before it) keeps the stored one.
            sent = data.get("feed")
            batch = data.get("batch")
            if isinstance(batch, dict):
                # A page from before recipe names, or one that does not send the refill reminder, keeps
                # the stored ones.
                kept = {key: self.data["batch"].get(key) for key in ("name", *dosing.REMINDER)}
                batch = {**kept, **batch}
            try:
                pumps, batch = dosing.clean(
                    data.get("pumps"),
                    batch,
                    self._exists,
                    self._stock_tanks(),
                )
                feed = dosing.clean_feed(
                    stored if sent is None else sent, pumps, self._exists
                )
            except dosing.DosingError as error:
                return self.response(str(error), can_edit)
            if sent is not None and feed["stage"] != stored["stage"]:
                dosing.pick(feed, feed["stage"], _today())
            else:  # how long a pick holds is the store's to say, never the caller's
                feed["held_until"] = stored["held_until"]
            draft = deepcopy(self.data)
            draft.update(
                revision=self.data["revision"] + 1,
                pumps=pumps,
                batch=batch,
                feed=feed,
                updated_at=_now().isoformat(),
            )
            await self._commit(draft)
            return self.response(can_edit=can_edit)

    async def request(self, data, by) -> dict:
        """Store one request for the controller. A stop always replaces what is pending; a dose or a
        batch waits for the one before it to be handled. The setup's revision does not move.
        """
        async with self._lock:
            if self.error:
                return {"request": None, "error": self.error}
            action = data.get("action")
            if action != "stop" and self.pending():
                return {"request": None, "error": "busy"}
            try:
                pump, ml = dosing.check_request(
                    self.data, action, data.get("pump"), data.get("ml")
                )
            except dosing.DosingError as error:
                return {"request": None, "error": str(error)}
            request = {
                "id": uuid.uuid4().hex,
                "action": action,
                "pump": pump,
                "ml": ml,
                "at": _now().isoformat(),
                "by": by,
            }
            draft = deepcopy(self.data)
            draft["request"] = request
            await self._commit(draft)
            return {"request": deepcopy(request), "error": None}

    def _exists(self, entity_id) -> bool:
        return self.hass.states.get(entity_id) is not None

    def _stock_tanks(self) -> set:
        """The ids of this room's stock tanks (stock_api.py), which a pump may be linked to."""
        stock = (
            self.hass.data.get(DOMAIN, {}).get("_stock", {}).get(self.entry.entry_id)
        )
        return (
            {tank["id"] for tank in stock.data["tanks"]} if stock is not None else set()
        )

    async def _commit(self, draft):
        """Store it; only a saved change becomes the room's setup and request."""
        await self._store.async_save(draft)
        self.data = draft
        from homeassistant.helpers.dispatcher import async_dispatcher_send

        async_dispatcher_send(self.hass, f"{SIGNAL}_{self.entry.entry_id}")


def resolve_dosing(hass, room_id):
    if not isinstance(room_id, str) or not room_id.startswith("room:"):
        raise ValueError("A canonical room_id is required")
    matches = [
        manager
        for manager in hass.data.get(DOMAIN, {}).get("_dosing", {}).values()
        if manager.room_id == room_id
    ]
    if len(matches) != 1:
        raise ValueError("Dosing room is unknown or ambiguous")
    return matches[0]


async def _caller(hass, call):
    """The signed-in user making the call, or None: an automation, or a user Home Assistant does not
    know. Their name goes into a request's `by`; whether they are an administrator is `can_edit`.
    """
    user_id = getattr(call.context, "user_id", None)
    return await hass.auth.async_get_user(user_id) if user_id else None


async def _require_signed_in(hass, call, action):
    """A stop only switches things off, so anyone who may look at the room may stop its dosing: any
    signed-in user, administrator or not, and an automation (no user) as before. A user id Home
    Assistant does not know is refused, as the administrator check refuses it."""
    from homeassistant.exceptions import HomeAssistantError

    if getattr(call.context, "user_id", None) and await _caller(hass, call) is None:
        raise HomeAssistantError(f"{action} requires a signed-in Home Assistant user")


async def async_setup_dosing(hass, entry):
    import voluptuous as vol
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError

    manager = DosingStore(hass, entry)
    await manager.async_init()
    hass.data.setdefault(DOMAIN, {}).setdefault("_dosing", {})[entry.entry_id] = manager
    unsubscribe = manager.start()
    if unsubscribe:
        entry.async_on_unload(unsubscribe)
    # The room's stock tanks, set up before it, follow the pumps linked to them (stock_api.py).
    from homeassistant.helpers.dispatcher import async_dispatcher_send

    async_dispatcher_send(hass, f"{SIGNAL}_{entry.entry_id}")

    async def handle(call):
        if call.service == "dosing_request" and call.data.get("action") == "stop":
            await _require_signed_in(hass, call, f"{DOMAIN}.{call.service}")
        elif call.service != "dosing_get":
            await async_require_admin(hass, call, f"{DOMAIN}.{call.service}")
        try:
            target = resolve_dosing(hass, call.data["room_id"])
            user = await _caller(hass, call)
            if call.service == "dosing_request":
                return await target.request(call.data, getattr(user, "name", None))
            can_edit = bool(getattr(user, "is_admin", False))
            if call.service == "dosing_get":
                return target.response(can_edit=can_edit)
            return await target.save(call.data, can_edit)
        except (ValueError, KeyError, OSError) as error:
            raise HomeAssistantError(str(error)) from error

    schemas = {
        "dosing_get": {vol.Required("room_id"): str},
        "dosing_save": {
            vol.Required("room_id"): str,
            vol.Required("expected_revision"): vol.All(int, vol.Range(min=0)),
            vol.Required("pumps"): list,
            vol.Required("batch"): dict,
            vol.Optional("feed"): dict,
        },
        "dosing_request": {
            vol.Required("room_id"): str,
            vol.Required("action"): vol.In(dosing.ACTIONS),
            vol.Optional("pump"): str,
            vol.Optional("ml"): vol.Coerce(float),
        },
    }
    for service in SERVICES:
        hass.services.async_register(
            DOMAIN,
            service,
            handle,
            schema=vol.Schema(schemas[service]),
            supports_response=SupportsResponse.ONLY,
        )


async def async_unload_dosing(hass, entry):
    managers = hass.data.get(DOMAIN, {}).get("_dosing", {})
    managers.pop(entry.entry_id, None)
    if not managers:
        for service in SERVICES:
            hass.services.async_remove(DOMAIN, service)
