"""The event journal as services, a bus event and a websocket feed (spec section 4).

One store for the site (journal.py, SQLite at <config>/crop_steering/journal.db), set up with the first room and
kept while any room is loaded. `journal_append` stores events (the controller's outbox flush) and `journal_query`
reads them back. Every stored event is re-fired on the bus as `crop_steering_event`; other integration code
writes through `emit()`. A signed-in user who may not call `subscribe_events` for a custom event type can follow
the feed with the `crop_steering/subscribe` websocket command.

Nothing here is needed for watering: a journal that cannot open only logs, `emit()` then does nothing, and the
two services answer "unavailable".
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
import os
import time

from .admin import async_require_admin
from .const import DOMAIN, EVENT_JOURNAL
from .generated.ids import new_id
from .journal import validate_event

_LOGGER = logging.getLogger(__name__)

SERVICES = ("journal_append", "journal_query")
MAX_APPEND = 50
READY_TIMEOUT_S = 30
PRUNE_EVERY = timedelta(days=1)
HUB = "_journal"
UNSUBS = "_journal_unsubs"


def _hub_error(message):
    from homeassistant.exceptions import HomeAssistantError

    return HomeAssistantError(message)


class JournalHub:
    """The site's journal, with its asynchronous face.

    It is `opening` until the file is open, then `ok`; `failed` when it could not be opened. Events and calls
    that arrive while it opens wait (at most READY_TIMEOUT_S) and go in, in order, once it is open. All writes
    take one lock, shared with the hub of a reloaded room, so two connections never race for a sequence number.
    """

    def __init__(self, hass, path: str, lock: asyncio.Lock | None = None) -> None:
        from .journal import Journal

        self.hass = hass
        self.path = path
        self.ok = False
        self.failed = False
        self.closed = False
        self._ready = asyncio.Event()
        self._lock = lock or asyncio.Lock()
        self._tasks: set = set()
        self._journal = Journal(path)

    @property
    def opening(self) -> bool:
        return not self._ready.is_set()

    async def async_init(self) -> None:
        try:
            await self.hass.async_add_executor_job(self._open)
            self.ok = True
        except Exception as err:  # never block setup or watering on the journal
            self.failed = True
            _LOGGER.warning("Event journal unavailable (%s): %s", self.path, err)
        finally:
            self._ready.set()

    def _open(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._journal.open()

    def close_soon(self) -> None:
        """Stop taking new events and close the file in the background, once the events already accepted are
        stored (a room reload does not wait on it)."""
        self.closed = True
        self.hass.async_create_task(self._close())

    async def _close(self) -> None:
        await self._ready.wait()  # a reload while the file is still opening must not leak the connection
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self.ok = False
        await self.hass.async_add_executor_job(self._journal.close)

    async def _wait_ready(self) -> None:
        if not self._ready.is_set():
            try:
                await asyncio.wait_for(self._ready.wait(), READY_TIMEOUT_S)
            except asyncio.TimeoutError:
                pass
        if not self.ok:
            raise _hub_error("The event journal is unavailable")

    async def append(self, room_id: str, events: list) -> dict:
        if len(events) > MAX_APPEND:
            raise _hub_error(f"journal_append takes at most {MAX_APPEND} events")
        await self._wait_ready()
        async with self._lock:
            try:
                out = await self.hass.async_add_executor_job(
                    self._journal.append, room_id, events
                )
            except ValueError as err:
                raise _hub_error(str(err)) from err
        for event in out.pop("stored"):
            self.hass.bus.async_fire(EVENT_JOURNAL, event)
        return out

    async def query(self, **kw) -> dict:
        await self._wait_ready()
        try:
            return await self.hass.async_add_executor_job(
                lambda: self._journal.query(**kw)
            )
        except ValueError as err:
            raise _hub_error(str(err)) from err

    async def prune(self) -> None:
        if self.ok:
            await self.hass.async_add_executor_job(
                self._journal.prune, int(time.time() * 1000)
            )

    def schedule(self, room_id: str, event: dict) -> None:
        """Store one event in the background, behind the ones already waiting."""
        task = self.hass.async_create_task(self._emit(room_id, event))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _emit(self, room_id: str, event: dict) -> None:
        try:
            await self.append(room_id, [event])
        except Exception as err:
            _LOGGER.warning("Journal event %s dropped: %s", event.get("kind"), err)


def emit(
    hass,
    room_id: str,
    kind: str,
    *,
    zone=None,
    outcome="ok",
    code=None,
    actor="system",
    detail=None,
    user_id=None,
    client=None,
    data=None,
    correlation=None,
    readback=None,
) -> str | None:
    """Record one event and return its id, or None when there is no journal, it could not be opened, or the
    event is not well formed. Fire-and-forget: the append is scheduled, never awaited (a journal still opening
    takes it once open), and nothing here raises. Call it from the event loop.
    """
    try:
        hub = hass.data.get(DOMAIN, {}).get(HUB)
        if hub is None or hub.failed or hub.closed:
            return None
        event_id = new_id()
        event = {
            "v": 1,
            "id": event_id,
            "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "zone": zone,
            "kind": kind,
            "outcome": outcome,
            "code": code,
            "source": {
                "actor": actor,
                "detail": detail,
                "program_id": None,
                "user_id": user_id,
                "judge": None,
                "client": client,
            },
            "correlation": {
                "intent_id": None,
                "causation_id": None,
                "batch_id": None,
                "run_id": None,
                "plan_revision": None,
                "setup_revision": None,
                "proposal_token": None,
                "ledger_id": None,
                **(correlation or {}),
            },
            "data": data or {},
            "readback": readback,
        }
        validate_event(event)
        hub.schedule(room_id, event)
        return event_id
    except Exception as err:
        _LOGGER.warning("Journal event %s not recorded: %s", kind, err)
        return None


def note(hass, room_id: str, kind: str, **kw) -> str | None:
    """emit() for the producers: a journal problem is only logged at debug and never reaches the write it
    describes."""
    try:
        return emit(hass, room_id, kind, **kw)
    except Exception as err:
        _LOGGER.debug("Journal event %s not recorded: %s", kind, err)
        return None


def attribution(hass, call) -> dict:
    """Who a service call is from, by the setpoint_log rule: a `client` of mcp or aigrow names the actor, a
    signed-in user without one is manual, and no user is an automation."""
    data = call.data
    client = data.get("client")
    user_id = getattr(call.context, "user_id", None)
    if client in ("mcp", "aigrow"):
        actor = client
    elif user_id:
        actor = "manual"
    else:
        actor = "automation"
    return {
        "actor": actor,
        "user_id": user_id,
        "client": client,
        "proposal_token": data.get("proposal_token"),
    }


def _wire(hass, hub) -> list:
    """The parts that need the real Home Assistant: the websocket command and the daily prune. -> unsubs."""
    from homeassistant.helpers.event import async_track_time_interval

    data = hass.data[DOMAIN]
    if not data.get("_journal_ws"):
        from homeassistant.components import websocket_api

        websocket_api.async_register_command(hass, _ws_subscribe_decorated())
        data["_journal_ws"] = True

    async def daily(_now):
        try:
            await hub.prune()
        except Exception as err:
            _LOGGER.warning("Journal prune failed: %s", err)

    return [async_track_time_interval(hass, daily, PRUNE_EVERY)]


def _subscribe_schema():
    import voluptuous as vol

    return {
        vol.Required("type"): f"{DOMAIN}/subscribe",
        vol.Optional("rooms"): [str],
        vol.Optional("kinds"): [str],
    }


def _ws_subscribe_handler(hass, connection, msg) -> None:
    from homeassistant.core import callback

    if connection.user is None:
        connection.send_error(msg["id"], "unauthorized", "A signed-in user is required")
        return
    if hass.data.get(DOMAIN, {}).get(HUB) is None:
        connection.send_error(
            msg["id"], "unavailable", "The event journal is unavailable"
        )
        return
    rooms = set(msg.get("rooms") or ())
    kinds = set(msg.get("kinds") or ())

    @callback
    def forward(event) -> None:
        body = event.data
        if rooms and body.get("room_id") not in rooms:
            return
        if kinds and body.get("kind") not in kinds:
            return
        connection.send_message({"id": msg["id"], "type": "event", "event": body})

    connection.subscriptions[msg["id"]] = hass.bus.async_listen(EVENT_JOURNAL, forward)
    connection.send_result(msg["id"])


def _ws_subscribe_decorated():
    from homeassistant.components import websocket_api
    from homeassistant.core import callback

    @websocket_api.websocket_command(_subscribe_schema())
    @callback
    def ws_subscribe(hass, connection, msg):
        _ws_subscribe_handler(hass, connection, msg)

    return ws_subscribe


async def _open_and_prune(hub) -> None:
    await hub.async_init()
    try:
        await hub.prune()
    except Exception as err:
        _LOGGER.warning("Journal prune failed: %s", err)


async def async_setup_journal(hass) -> None:
    """Once for the site, with the first room; each room after it only joins (async_unload_journal)."""
    import voluptuous as vol
    from homeassistant.core import SupportsResponse

    data = hass.data.setdefault(DOMAIN, {})
    if HUB in data:
        return
    hub = JournalHub(
        hass,
        hass.config.path(DOMAIN, "journal.db"),
        data.setdefault("_journal_lock", asyncio.Lock()),
    )

    async def handle(call):
        user_id = getattr(call.context, "user_id", None)
        if call.service == "journal_append":
            await async_require_admin(hass, call, f"{DOMAIN}.journal_append")
            who = attribution(hass, call)
            events = []
            for raw in call.data["events"]:
                if not isinstance(raw, dict):
                    raise _hub_error("each event must be an object")
                source = dict(raw.get("source") or {})
                if who["client"] and not source.get("client"):
                    source["client"] = who["client"]
                events.append({**raw, "source": source})
            return await hub.append(call.data["room_id"], events)
        if user_id and await hass.auth.async_get_user(user_id) is None:
            raise _hub_error(
                f"{DOMAIN}.journal_query requires a signed-in Home Assistant user"
            )
        args = {k: v for k, v in call.data.items() if k != "client"}
        return await hub.query(**args)

    schemas = {
        "journal_append": {
            vol.Required("room_id"): str,
            vol.Required("events"): list,
            vol.Optional("client"): str,
        },
        "journal_query": {
            vol.Required("room_id"): str,
            vol.Required("since"): str,
            vol.Optional("until"): str,
            vol.Optional("kinds"): [str],
            vol.Optional("zones"): [vol.Coerce(int)],
            vol.Optional("actor"): str,
            vol.Optional("limit"): vol.All(vol.Coerce(int), vol.Range(min=1, max=500)),
            vol.Optional("cursor"): str,
            vol.Optional("client"): str,
        },
    }
    for service in SERVICES:
        hass.services.async_register(
            DOMAIN,
            service,
            handle,
            schema=vol.Schema(schemas[service]),
            supports_response=(
                SupportsResponse.OPTIONAL
                if service == "journal_append"
                else SupportsResponse.ONLY
            ),
        )
    try:
        data[UNSUBS] = _wire(hass, hub)
    except Exception:
        for service in SERVICES:
            hass.services.async_remove(DOMAIN, service)
        raise
    data[HUB] = hub
    # Opened and pruned in the background: setup, and a room reload, never wait on the journal's file.
    hass.async_create_task(_open_and_prune(hub))


async def async_unload_journal(hass) -> None:
    """The site's journal goes with the last room (the caller checks that no other room is loaded)."""
    data = hass.data.get(DOMAIN, {})
    hub = data.pop(HUB, None)
    if hub is None:
        return
    for unsub in data.pop(UNSUBS, []):
        unsub()
    for service in SERVICES:
        hass.services.async_remove(DOMAIN, service)
    hub.close_soon()
