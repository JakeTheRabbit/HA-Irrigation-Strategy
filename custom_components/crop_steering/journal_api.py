"""The event journal as services, a bus event and a websocket feed (spec section 4).

One store for the site (journal.py, SQLite at <config>/crop_steering/journal.db), set up with the first room and
kept while any room is loaded. `journal_append` stores events (the controller's outbox flush) and `journal_query`
reads them back. Every stored event is re-fired on the bus as `crop_steering_event`; other integration code
writes through `emit()`. A signed-in user who may not call `subscribe_events` for a custom event type can follow
the feed with the `crop_steering/subscribe` websocket command. `history_changes` reads who changed what
(changes.py folds the journal) and `history_revert` puts one change back (an administrator only).
`timeline_get` and `timeline_summary` read what each zone did and is planned to do (timeline.py folds the
journal and the controller's projection_app). Each room's open alerts are sensor.crop_steering_<prefix>alerts_open
(alerts_inbox.py), and `alert_ack` acknowledges one (any signed-in user: staff ack alarms).

Nothing here is needed for watering: a journal that cannot open only logs, `emit()` then does nothing, and the
services that read it answer "unavailable".
"""

from __future__ import annotations

import asyncio
import contextvars
from datetime import datetime, timedelta
import logging
import os
import time

from .admin import async_require_admin, forbidden
from .const import DOMAIN, EVENT_JOURNAL
from .generated.ids import new_id
from .journal import validate_event

_LOGGER = logging.getLogger(__name__)

SERVICES = (
    "journal_append",
    "journal_query",
    "history_changes",
    "history_revert",
    "timeline_get",
    "timeline_summary",
    "alert_ack",
)
MAX_APPEND = 50
# history_changes answers at most this many rows, the newest (`truncated: true` when it cut).
MAX_CHANGES = 2000
READY_TIMEOUT_S = 30
PRUNE_EVERY = timedelta(days=1)
HUB = "_journal"
UNSUBS = "_journal_unsubs"
# [(event_id, kind)] of what emit() records while an API v2 call runs (api_v2.wrap sets it).
EMITTED: contextvars.ContextVar = contextvars.ContextVar(
    "crop_steering_emitted", default=None
)


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
            from .api_v2 import Unavailable

            message = "The event journal is unavailable"
            raise _hub_error(message) from Unavailable(message)

    async def append(self, room_id: str, events: list) -> dict:
        """Store the well-formed events -> {accepted, duplicate, seq_max, rejected: [{id, error}]}. An event that
        is not well formed is rejected on its own, so one bad event never blocks the others (the controller's
        outbox sets it aside); a request that cannot be served at all still raises."""
        if len(events) > MAX_APPEND:
            raise _hub_error(f"journal_append takes at most {MAX_APPEND} events")
        valid, rejected = [], []
        for event in events:
            try:
                valid.append(validate_event(event))
            except ValueError as err:
                event_id = event.get("id") if isinstance(event, dict) else None
                rejected.append({"id": event_id, "error": str(err)})
        await self._wait_ready()
        async with self._lock:
            try:
                out = await self.hass.async_add_executor_job(
                    self._journal.append, room_id, valid
                )
            except ValueError as err:
                raise _hub_error(str(err)) from err
        for event in out.pop("stored"):
            self.hass.bus.async_fire(EVENT_JOURNAL, event)
        out["rejected"] = rejected
        return out

    async def query(self, **kw) -> dict:
        await self._wait_ready()
        try:
            return await self.hass.async_add_executor_job(
                lambda: self._journal.query(**kw)
            )
        except ValueError as err:
            raise _hub_error(str(err)) from err

    async def get(self, event_id: str) -> dict | None:
        await self._wait_ready()
        return await self.hass.async_add_executor_job(self._journal.get, event_id)

    async def backfill(self, room_id: str, rows: dict, build) -> int:
        """Store the room's old history, one source at a time. `rows` maps a source name to its rows, or to
        None when the source is absent or did not load; only a source that is present is imported, and only it
        gets its `backfill:<room>:<source>:v1` flag (so a source that turns up later is still imported).
        `build(rows, names)` -> {name: events} runs in the executor, and is not called for sources already
        done. Quiet: backfilled events are history, so they are not re-fired on the bus. -> how many were new.
        """
        await self._wait_ready()
        flags = {
            n: f"backfill:{room_id}:{n}:v1" for n, r in rows.items() if r is not None
        }
        todo = []
        for name, flag in flags.items():
            done = await self.hass.async_add_executor_job(self._journal.meta_get, flag)
            if done != "done":
                todo.append(name)
        if not todo:
            return 0
        built = await self.hass.async_add_executor_job(build, rows, todo)
        added = 0
        async with self._lock:
            for name in todo:
                if name not in built:  # it failed to build: try again next start
                    continue
                events = built[name]
                for i in range(0, len(events), MAX_APPEND):
                    out = await self.hass.async_add_executor_job(
                        self._journal.append, room_id, events[i : i + MAX_APPEND]
                    )
                    added += len(out["accepted"])
                await self.hass.async_add_executor_job(
                    self._journal.meta_set, flags[name], "done"
                )
        return added

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
        emitted = EMITTED.get()
        if emitted is not None:
            emitted.append((event_id, kind))
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


# ------------------------------------------------------------------ History › Changes (G8)
CANT = "This change can't be put back"
HELD_BY_AI = "Keep or undo the AI change first"
# What a room setup put back sends to setup_save. An empty plumbing or tank level is left out,
# and refused when the room has one now: a save cannot take one away.
SETUP_KEYS = ("room_name", "active", "zones", "hardware", "plumbing", "tank_level")
OPTIONAL_SETUP_KEYS = ("plumbing", "tank_level")


def _room_ids(hass) -> list[str]:
    from .room import room_prefix

    return sorted(
        {"room:" + room_prefix(e) for e in hass.config_entries.async_entries(DOMAIN)}
    )


def _step_scope(hass, room_id: str):
    """The room's "Max setpoint move applies to" choice, or None."""
    state = hass.states.get(
        f"select.{DOMAIN}_{room_id[len('room:'):]}setpoint_step_limit_applies_to"
    )
    return getattr(state, "state", None)


async def history_changes(hass, hub, args: dict) -> dict:
    """{changes, truncated?}: changes.fold_changes over the room's journal (every room when no
    room_id), filtered by zone, key and change kinds, at most MAX_CHANGES rows (the newest), each
    with the name of the Home Assistant user who made it. The fold runs in the executor.
    """
    from .changes import KINDS

    rooms = [args["room_id"]] if args.get("room_id") else _room_ids(hass)
    events = []
    for room_id in rooms:
        cursor = None
        while True:
            page = await hub.query(
                room_id=room_id,
                since=args["since"],
                until=args.get("until"),
                kinds=list(KINDS),
                cursor=cursor,
            )
            events += page["events"]
            cursor = page["cursor"]
            if cursor is None:
                break
    limits = {r: {"step_scope": _step_scope(hass, r)} for r in rooms}
    rows = await hass.async_add_executor_job(_folded, events, limits, dict(args))
    out = {"changes": rows[:MAX_CHANGES]}
    if len(rows) > MAX_CHANGES:
        out["truncated"] = True
    names: dict = {}
    for row in out["changes"]:
        user_id = row["user_id"]
        if user_id and user_id not in names:
            user = await hass.auth.async_get_user(user_id)
            names[user_id] = getattr(user, "name", None)
        row["user_name"] = names.get(user_id) if user_id else None
    return out


def _folded(events, limits, args) -> list:
    """The folded, filtered rows (in the executor)."""
    from . import changes

    rows = changes.fold_changes(events, limits)
    if args.get("zone") is not None:
        rows = [r for r in rows if r["scope"] == f"zone:{args['zone']}"]
    if args.get("key"):
        rows = [r for r in rows if r["key"] == args["key"]]
    if args.get("kinds"):
        rows = [r for r in rows if r["kind"] in args["kinds"]]
    return rows


async def history_revert(hass, hub, call) -> dict:
    """Put one change back -> {reverted_event_id, new_event_id, readback, error?}. A setting is
    written back and read back (presets.write_numbers); a store section is saved again from its
    `old` copy at the current revision. Either is journaled as manual, "put back", caused by the
    change. A setting or section that moved since is StaleRevision; a change that is not
    revertible is refused."""
    from .changes import PUT_BACK, fold_changes

    event_id = call.data["event_id"]
    event = await hub.get(event_id)
    if event is None:
        raise _hub_error(f"No change {event_id} in the journal")
    rows = fold_changes([event], {})
    if not rows or not rows[0]["revertible"]:
        raise _hub_error(CANT)
    who = {
        **attribution(hass, call),
        "actor": "manual",
        "detail": PUT_BACK,
        "causation_id": event_id,
    }
    emitted, outer = [], EMITTED.get()
    token = EMITTED.set(emitted)
    try:
        answer = await _put_back(hass, event, who, call)
    except (ValueError, KeyError, TypeError) as err:
        raise _hub_error(str(err)) from err
    finally:
        EMITTED.reset(token)
        if outer is not None:
            outer.extend(emitted)
    return {
        "reverted_event_id": event_id,
        "new_event_id": emitted[0][0] if emitted else None,
        **answer,
    }


def _stale(what, revision=None):
    from .api_v2 import StaleRevision

    return StaleRevision(
        f"{what} has changed since this change; reload the history", revision
    )


async def _put_back(hass, event, who, call) -> dict:
    from . import overlays, presets
    from .api_v2 import GuardRefused

    data, room_id = event["data"], event["room_id"]
    entry = presets._entry(hass, room_id=room_id)
    if event["kind"] == "target.changed":
        entity_id = data["entity_id"]
        held = overlays.overlays_for(hass, entry.entry_id)
        if held is not None and entity_id in held.rows:
            raise GuardRefused(HELD_BY_AI)
        now = presets._state(hass, entity_id)
        if now is None or not presets.same(now, data["new"]):
            raise _stale(f"The setting {data.get('key') or entity_id}")
        (row,) = await presets.write_numbers(
            hass,
            entry.entry_id,
            [
                {
                    "entity_id": entity_id,
                    "key": data.get("key"),
                    "value": data["old"],
                    "zone": event.get("zone"),
                }
            ],
            who,
        )
        return {"readback": row["readback"], "error": row.get("error")}
    expected = call.data.get("expected_revision")

    def check(name, current, new, revision):
        if (expected is not None and expected != revision) or current != new:
            raise _stale(name, revision)

    if event["kind"] == "calibration.committed":
        from .calibration import resolve_calibration

        store = resolve_calibration(hass, room_id)

        def applied():
            return next(
                (
                    r.get("id")
                    for r in store.document["records"]
                    if r.get("probe") == data.get("probe") and r.get("applied")
                ),
                None,
            )

        check(
            "The probe's calibration",
            applied(),
            data.get("record_id"),
            store.document["revision"],
        )
        await store.revert(data["probe"], who)
        # What it replaced is applied again (or nothing, when it replaced none).
        return _read_back(applied() == data.get("superseded_record_id"))
    return await _put_back_section(hass, entry, room_id, data, who, call, check)


def _read_back(match: bool) -> dict:
    return {"readback": "verified" if match else "refused"}


def _programs(programs) -> list:
    """Timer programs as compared on read-back: without ids and time stamps, in any order."""
    import json

    return sorted(
        json.dumps(
            {
                k: v
                for k, v in p.items()
                if k not in ("id", "created_at", "updated_at", "deleted_at")
            },
            sort_keys=True,
            default=str,
        )
        for p in programs
        if not p.get("deleted_at")
    )


def _fix(entry) -> tuple:
    """A probe offset as compared on read-back: (offset, curve); none is (0.0, None)."""
    entry = entry or {}
    return (float(entry.get("offset", 0.0)), entry.get("curve"))


async def _put_back_section(hass, entry, room_id, data, who, call, check) -> dict:
    """A store section saved again from its `old` copy, through the store's own save path, then read
    back from the store and compared with `old`."""
    from copy import deepcopy

    store, section, old, new = data["store"], data["section"], data["old"], data["new"]
    if store == "timers":
        from . import timers_api

        room = timers_api._rooms(hass)[entry.entry_id]
        revision = room.document["revision"]
        check("The timer programs", room.document["programs"], new, revision)
        live = {p.get("id") for p in new if not p.get("deleted_at")}
        olds = [p for p in deepcopy(old) if not p.get("deleted_at")]
        revived = [p for p in olds if p.get("id") not in live]
        programs = [
            p if p.get("id") in live else {k: v for k, v in p.items() if k != "id"}
            for p in olds
        ]
        await timers_api.set_programs(hass, entry.entry_id, programs, revision, who)
        now = room.programs()
        known = {p.get("id") for p in old}
        fresh = [p for p in now if p.get("id") not in known]
        return {
            **_read_back(_programs(now) == _programs(olds)),
            # A program the change had deleted comes back under a new id.
            "renewed": [
                {"name": n.get("name"), "old_id": o.get("id"), "id": n.get("id")}
                for o, n in zip(revived, fresh)
            ],
        }
    if store == "site":
        from . import site_store

        site = hass.data[DOMAIN]["_site"]
        if section == "supply":
            revision = site.document["revision"]
            check("The supply", site_store.supply_of(site.document), new, revision)
            out = await site.save({**deepcopy(old), "expected_revision": revision}, who)
            return _read_back(
                out["readback"]["status"] == "ok"
                and site_store.supply_of(site.document) == old
            )
        if section == "alert_rules":
            revision = site.document["alert_rules_revision"]
            check("The alert rules", site.document["alert_rules"], new, revision)

            def put(stored):
                stored[:] = deepcopy(old)

            await site._save_alert_rules(revision, put, who, room_id)
            return _read_back(site.document["alert_rules"] == old)
        revision = site.document["presets_revision"]
        check("The presets", site.document["presets"], new, revision)

        def change(stored):
            stored[:] = deepcopy(old)

        await site._save_presets(revision, change, who, room_id)
        return _read_back(site.document["presets"] == old)
    if store == "calibration":
        from .calibration import resolve_calibration

        cal = resolve_calibration(hass, room_id)
        check(
            "The probe offsets",
            cal.document["probe_user_offsets"],
            new,
            cal.document["revision"],
        )
        entities = []
        for entity_id in sorted(set(old) | set(new)):
            if old.get(entity_id) == new.get(entity_id):
                continue
            fix = old.get(entity_id) or {}
            await cal.probe_offset_set(
                {
                    "entity_id": entity_id,
                    "offset": fix.get("offset", 0.0),
                    "curve": fix.get("curve") or "none",
                    "expected_revision": cal.document["revision"],
                },
                who,
            )
            now = cal.document["probe_user_offsets"].get(entity_id)
            entities.append(
                {"entity_id": entity_id, **_read_back(_fix(now) == _fix(fix))}
            )
        refused = any(e["readback"] == "refused" for e in entities)
        return {**_read_back(not refused), "entities": entities}
    return await _put_back_setup(hass, entry, old, new, who, call, check)


async def _put_back_setup(hass, entry, old, new, who, call, check) -> dict:
    """The room setup, whole: refused when its old copy lacks a part the setup has now, as a save
    without it would keep today's part (never a partial put back). The save keeps every safety
    check (setup_save's own)."""
    from copy import deepcopy

    from . import setup_api

    async with hass.data[DOMAIN]["_setup"]["lock"]:
        before = setup_api.setup_room(hass, entry)
        owned = setup_api._owned(before)
        if set(owned) - set(old):
            raise _hub_error(CANT)
        payload = {}
        for key in SETUP_KEYS:
            if key in OPTIONAL_SETUP_KEYS and not old.get(key):
                if owned.get(key):  # a save cannot take it away
                    raise _hub_error(CANT)
                continue
            payload[key] = deepcopy(old[key])
        check("The room setup", owned, new, before["revision"])
        result = await setup_api.save_setup(
            hass,
            {
                **payload,
                "entry_id": entry.entry_id,
                "expected_revision": before["revision"],
            },
        )
        setup_api._record(hass, "setup_save", before, result, call.context, who)
        return _read_back(setup_api._owned(setup_api.setup_room(hass, entry)) == old)


# ------------------------------------------------------------------ Alerts inbox
async def alert_ack(hass, hub, call) -> dict:
    """Acknowledge one open alert -> {room_id, alert_event_id, event_id}: journals alert.acknowledged
    (who acked it by attribution), then a threshold rule's live state becomes acknowledged. An alert
    that is not in the room's journal, or no longer open, is refused (ValueError), and so is an ack
    the journal does not take (nothing changes then)."""
    from . import alerts_inbox

    room_id, alert_id = call.data["room_id"], call.data["alert_event_id"]
    event = await hub.get(alert_id)
    if (
        event is None
        or event.get("room_id") != room_id
        or event.get("kind") != "alert.raised"
    ):
        raise ValueError(f"No alert {alert_id} in {room_id}")
    if alert_id not in {
        a["event_id"] for a in await alerts_inbox.read_open(hass, hub, room_id)
    }:
        raise ValueError(f"The alert {alert_id} is already closed")
    raised = event.get("data") or {}
    data = {"alert_event_id": alert_id}
    for key in ("rule_id", "key"):
        if raised.get(key):
            data[key] = raised[key]
    who = attribution(hass, call)
    ack_id = emit(
        hass,
        room_id,
        "alert.acknowledged",
        zone=event.get("zone"),
        code=event.get("code"),
        actor=who["actor"],
        user_id=who["user_id"],
        client=who["client"],
        data=data,
        correlation={
            "causation_id": alert_id,
            "proposal_token": who["proposal_token"],
        },
    )
    if ack_id is None:
        raise ValueError("The journal is not available; try again")
    if raised.get("rule_id"):
        alerts_inbox.acknowledge_rule(hass, raised["rule_id"])
    return {"room_id": room_id, "alert_event_id": alert_id, "event_id": ack_id}


# ------------------------------------------------------------------ Timeline (G5)
PROJECTION = f"sensor.{DOMAIN}_{{}}projection_app"


async def _all_events(hub, **kw) -> list:
    events, cursor = [], None
    while True:
        page = await hub.query(**kw, cursor=cursor)
        events += page["events"]
        cursor = page["cursor"]
        if cursor is None:
            return events


def _local_tz():
    from homeassistant.util import dt as dt_util

    return dt_util.get_default_time_zone()


def _rooms_of(args) -> list[str]:
    rooms = list(dict.fromkeys(args["rooms"]))
    if not rooms or not all(
        isinstance(r, str) and r.startswith("room:") for r in rooms
    ):
        raise _hub_error("rooms are ids such as room:f2_")
    return rooms


async def _read(hub, room_id, since, until, *, openers, kinds=None) -> list:
    """The room's events for [since, until) by timeline.windows (completions past the end; with `openers`,
    starts before it), only `kinds` when given."""
    from . import timeline

    events = []
    for low, high, wanted in timeline.windows(since, until, openers=openers):
        wanted = [k for k in wanted if kinds is None or k in kinds]
        if wanted:
            events += await _all_events(
                hub,
                room_id=room_id,
                since=low.isoformat(),
                until=high.isoformat(),
                kinds=wanted,
            )
    return events


def _pumps(hass) -> dict:
    """{room_id: the room's pump switch} for every room with one."""
    from .room import room_prefix
    from .setup_api import effective

    out = {}
    for entry in hass.config_entries.async_entries(DOMAIN):
        pump = (effective(entry).get("hardware") or {}).get("pump_switch")
        if pump:
            out["room:" + room_prefix(entry)] = pump
    return out


def _timeline_room(hass, room_id, pump) -> tuple[dict, list]:
    """What timeline.build needs of one room, and its projection_app intents (the only planned source)."""
    from . import timers_api
    from .site_api import SENSOR as SUPPLY

    prefix = room_id[len("room:") :]
    state = hass.states.get(PROJECTION.format(prefix))
    intents = getattr(state, "attributes", {}).get("intents") if state else None
    if (
        state is None
        or state.state in ("unavailable", "unknown")
        or not isinstance(intents, list)
    ):
        intents, source = [], "unavailable"
    else:
        source = "projection_app"
    timers = next(
        (r for r in timers_api._rooms(hass).values() if r.room_id == room_id), None
    )
    supply = hass.states.get(SUPPLY)
    attrs = supply.attributes if supply is not None else {}
    capacity = next(
        (
            p.get("max_flow_lph")
            for p in attrs.get("irrigation_pumps") or ()
            if pump and p.get("entity_id") == pump
        ),
        None,
    )
    room = {
        "room_id": room_id,
        "lights_hours": timers.lights() if timers is not None else None,
        "pump": pump,
        "capacity_lph": capacity,
        "planned_source": source,
        # The integration owns the timers config, so the timeline reads the skips itself.
        "skips": timers.skips_in_force() if timers is not None else [],
    }
    return room, [{**i, "room_id": room_id} for i in intents if isinstance(i, dict)]


async def timeline_get(hass, hub, args: dict) -> dict:
    """{rooms, errors, truncated?}: timeline.build over each room's shot, hold, queue, alert and flow events in
    [start, end) (and the shots running across its edges) and its projection_app intents, in HA local time. A
    room's pump load is its pump's: the shots of every room on that pump are read, asked for or not. The fold
    runs in the executor.
    """
    from homeassistant.util import dt as dt_util

    from . import timeline
    from .site_api import SENSOR as SUPPLY

    tz = _local_tz()
    start, end = timeline.at(args["start"], tz), timeline.at(args["end"], tz)
    if start is None or end is None:
        raise _hub_error("start and end are ISO times")
    try:
        timeline.check_span(start, end)
    except ValueError as err:
        raise _hub_error(str(err)) from err
    asked = _rooms_of(args)
    pump_of = _pumps(hass)
    supply = hass.states.get(SUPPLY)
    demand = (supply.attributes.get("zone_demand_lph") if supply else None) or {}
    pumps = {}
    for room_id in asked:
        pump = pump_of.get(room_id)
        if pump:
            pumps[pump] = {
                r: dict(demand.get(r) or {}) for r, p in pump_of.items() if p == pump
            }
    rooms, events, planned = [], [], []
    for room_id in asked:
        events += await _read(hub, room_id, start, end, openers=True)
        room, intents = _timeline_room(hass, room_id, pump_of.get(room_id))
        rooms.append(room)
        planned += intents
    for room_id in sorted(
        {r for members in pumps.values() for r in members} - set(asked)
    ):
        events += await _read(
            hub, room_id, start, end, openers=True, kinds=timeline.SHOT_KINDS
        )
    return await hass.async_add_executor_job(
        lambda: timeline.build(
            rooms,
            events,
            planned,
            start,
            end,
            now=dt_util.now(),
            tz=tz,
            zones=args.get("zones"),
            pumps=pumps,
        )
    )


async def timeline_summary(hass, hub, args: dict) -> dict:
    """{days: [{date, rooms: [{room_id, shots, failed, warnings, held, queued}]}]}, each local day of each room
    read from local midnight to the next (a shot counted once, on the day it started).
    """
    from homeassistant.util import dt as dt_util

    from . import timeline

    tz = _local_tz()
    try:
        days = timeline.check_days(args["days"])
    except ValueError as err:
        raise _hub_error(str(err)) from err
    rooms = _rooms_of(args)
    events = []
    for room_id in rooms:
        for day in sorted(set(days)):
            since = datetime.combine(day, datetime.min.time(), tz)
            until = datetime.combine(day + timedelta(days=1), datetime.min.time(), tz)
            events += await _read(hub, room_id, since, until, openers=False)
    now = dt_util.now()
    out = await hass.async_add_executor_job(
        lambda: timeline.summarise(events, args["days"], rooms=rooms, tz=tz, now=now)
    )
    return {"days": out}


def _not_put_back(call, result):
    """API v2: a put back whose setting did not read back as the old value."""
    from .api_v2 import failure

    if result.get("readback") != "refused":
        return None
    return failure(
        "guard_refused",
        f"Not put back: {result.get('error') or 'it did not read back'}",
    )


def _readback_of(call, result):
    from .api_v2 import _readback

    if call.service == "history_revert":
        return result.get("readback", "none")
    return _readback(call, result)


def _wire(hass, hub) -> list:
    """The parts that need the real Home Assistant: the websocket command, the daily prune and the alerts
    inbox. -> unsubs."""
    from homeassistant.helpers.event import async_track_time_interval

    from .alerts_inbox import INBOX, Inbox

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

    prune = async_track_time_interval(hass, daily, PRUNE_EVERY)
    inbox = data[INBOX] = Inbox(hass, hub)
    try:
        return [prune, *inbox.start()]
    except Exception:
        prune()
        data.pop(INBOX, None)
        raise


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


def _join_inbox(hass, entry) -> None:
    from .alerts_inbox import INBOX
    from .room import room_prefix

    inbox = hass.data.get(DOMAIN, {}).get(INBOX)
    if entry is not None and inbox is not None:
        inbox.join("room:" + room_prefix(entry))


async def async_setup_journal(hass, entry=None) -> None:
    """Once for the site, with the first room; each room after it only joins (async_unload_journal), and
    `entry`'s room gets its alerts inbox sensor."""
    import voluptuous as vol
    from homeassistant.core import SupportsResponse

    from .api_v2 import fields, wrap
    from .changes import CHANGE_KINDS

    data = hass.data.setdefault(DOMAIN, {})
    if HUB in data:
        _join_inbox(hass, entry)
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
        if call.service == "history_revert":
            await async_require_admin(hass, call, f"{DOMAIN}.history_revert")
            return await history_revert(hass, hub, call)
        if user_id and await hass.auth.async_get_user(user_id) is None:
            raise forbidden(
                f"{DOMAIN}.{call.service} requires a signed-in Home Assistant user"
            )
        if call.service == "history_changes":
            return await history_changes(hass, hub, call.data)
        if call.service == "timeline_get":
            return await timeline_get(hass, hub, call.data)
        if call.service == "timeline_summary":
            return await timeline_summary(hass, hub, call.data)
        if call.service == "alert_ack":
            try:
                return await alert_ack(hass, hub, call)
            except ValueError as err:
                raise _hub_error(str(err)) from err
        args = {
            k: v for k, v in call.data.items() if k not in ("client", "proposal_token")
        }
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
        "history_changes": {
            vol.Optional("room_id"): str,
            vol.Required("since"): str,
            vol.Optional("until"): str,
            vol.Optional("zone"): vol.Coerce(int),
            vol.Optional("key"): str,
            vol.Optional("kinds"): [vol.In(CHANGE_KINDS)],
        },
        "history_revert": {
            vol.Required("event_id"): str,
            vol.Optional("expected_revision"): vol.All(int, vol.Range(min=0)),
        },
        "timeline_get": {
            vol.Required("rooms"): [str],
            vol.Required("start"): str,
            vol.Required("end"): str,
            vol.Optional("zones"): [vol.Coerce(int)],
        },
        "timeline_summary": {
            vol.Required("rooms"): [str],
            vol.Required("days"): [str],
        },
        "alert_ack": {
            vol.Required("room_id"): str,
            vol.Required("alert_event_id"): str,
        },
    }
    for service in SERVICES:
        hass.services.async_register(
            DOMAIN,
            service,
            wrap(
                handle,
                readback_of=_readback_of,
                error_of={"history_revert": _not_put_back},
            ),
            schema=vol.Schema(fields(schemas[service])),
            supports_response=(
                SupportsResponse.OPTIONAL
                if service in ("journal_append", "history_revert", "alert_ack")
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
    _join_inbox(hass, entry)
    # Opened and pruned in the background: setup, and a room reload, never wait on the journal's file.
    hass.async_create_task(_open_and_prune(hub))


def _snapshot(hass, entry) -> dict:
    """Copies of the room's old rows, by source (on the event loop). None: the store is not there, or it could
    not be loaded (so it is not imported, and not marked done). The source stores are only read.
    """
    data = hass.data.get(DOMAIN, {})
    readers = {
        "setpoint_log": ("_setpoint_log", lambda s: list(s.changes)),
        "stock": ("_stock", lambda s: list(s.data["history"])),
        "calibration": ("_calibration", lambda s: list(s.document["records"])),
        "overlays": ("_overlays", lambda s: list(s.rows.values())),
    }
    out = {}
    for name, (key, rows) in readers.items():
        store = data.get(key, {}).get(entry.entry_id)
        try:
            out[name] = (
                None if store is None or getattr(store, "error", None) else rows(store)
            )
        except Exception as err:
            _LOGGER.warning("Journal backfill skipped %s: %s", name, err)
            out[name] = None
    return out


def _build(room_id, cutoff, rows, names) -> dict:
    """The events of the sources in `names`, without any from `cutoff` on (a live event already covers
    those). A source that fails to build is left out, and so is not marked done."""
    from . import journal

    importers = {
        "setpoint_log": lambda: journal.import_setpoint_log(
            room_id, rows["setpoint_log"], rows["overlays"] or ()
        ),
        "stock": lambda: journal.import_stock_history(room_id, rows["stock"]),
        "calibration": lambda: journal.import_calibration(room_id, rows["calibration"]),
        "overlays": lambda: journal.import_overlays(
            room_id, rows["overlays"], rows["setpoint_log"] or ()
        ),
    }
    out = {}
    for name in names:
        try:
            out[name] = [
                e for e in importers[name]() if journal._when(e["ts"]) < cutoff
            ]
        except Exception as err:
            _LOGGER.warning("Journal backfill skipped %s: %s", name, err)
    return out


async def async_backfill_room(hass, entry) -> None:
    """Once per source per room, after its stores are set up: import the setpoint log, stock history,
    calibration history and held overlays as journal events. Ids come from the rows, so a run that is cut
    short and repeated adds nothing twice. Never raises: a journal that is down just has no history yet, and
    tries again next start.
    """
    from datetime import UTC

    from .room import room_prefix

    cutoff = datetime.now(UTC)  # a row from now on is covered by its live event
    try:
        hub = hass.data.get(DOMAIN, {}).get(HUB)
        if hub is None or hub.failed or hub.closed:
            return
        room_id = "room:" + room_prefix(entry)
        added = await hub.backfill(
            room_id,
            _snapshot(hass, entry),
            lambda rows, names: _build(room_id, cutoff, rows, names),
        )
        if added:
            _LOGGER.info("Journal backfilled %d events for %s", added, room_id)
    except Exception as err:
        _LOGGER.warning("Journal backfill failed: %s", err)


def async_leave_journal(hass, entry) -> None:
    """The room's alerts inbox sensor goes with the room."""
    from .alerts_inbox import INBOX
    from .room import room_prefix

    inbox = hass.data.get(DOMAIN, {}).get(INBOX)
    if inbox is not None:
        inbox.leave("room:" + room_prefix(entry))


async def async_unload_journal(hass) -> None:
    """The site's journal goes with the last room (the caller checks that no other room is loaded)."""
    from .alerts_inbox import INBOX

    data = hass.data.get(DOMAIN, {})
    hub = data.pop(HUB, None)
    if hub is None:
        return
    for unsub in data.pop(UNSUBS, []):
        unsub()
    inbox = data.pop(INBOX, None)
    if inbox is not None:
        inbox.stop()
    for service in SERVICES:
        hass.services.async_remove(DOMAIN, service)
    hub.close_soon()
