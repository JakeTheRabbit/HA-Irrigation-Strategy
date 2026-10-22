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

Pump prime and calibration (G3): pump_precheck names what stops a timed run of a pump now (read
only, open like dosing_get); pump_prime and pump_calibrate (administrators) leave a timed request for
the controller, refused while any blocker stands; pump_stop (any signed-in user) leaves a stop_pump
that pre-empts a waiting prime or calibration of that pump and never a batch. A calibration opens a
pump session in calibration.py; the controller's handled_result gives the seconds it ran, and
pump_calibration_commit turns the mL measured into the pump's calibrated flow (and writes its flow
number). MCP gets none of these (spec 5.5).
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import logging
import math
import uuid

from . import calibration as calibration_module, dosing
from .admin import async_require_admin, forbidden
from .api_v2 import GuardRefused, Unavailable
from .const import DOMAIN
from .journal_api import attribution, note
from .room import room_prefix

_LOGGER = logging.getLogger(__name__)

PUMP_SERVICES = (
    "pump_precheck",
    "pump_prime",
    "pump_stop",
    "pump_calibrate",
    "pump_calibration_commit",
)
SERVICES = ("dosing_get", "dosing_save", "dosing_request", *PUMP_SERVICES)
# A precheck only reads, as dosing_get does; a pump stop only switches off, as a room stop does: any
# signed-in user. The rest of the pump services need an administrator.
OPEN = ("pump_stop",)
SIGNAL = f"{DOMAIN}_dosing_changed"
PRIME_SECONDS = dosing.TIMED["prime"]
CALIBRATE_SECONDS = dosing.TIMED["calibrate"]
OFFLINE_S = 600  # a controller heartbeat older than this: the controller is offline
BUSY = "Another dosing request is still waiting for the controller"
HELD = "A dosing pump is being calibrated or primed: doses and batches wait until it is done"
WAITING = "A dose or batch is waiting — an admin, or the room Stop, can cancel it."
PRIME_HOLD_S = 60  # a prime holds room dosing for its run and this long after it
# Fields of a pump only the store sets (a calibration commit, a prime): a save keeps the stored ones.
OWNED = ("calibrated_ml_min", "calibrations", "primed_at")
# Fields a page from before the catalogue does not send: a save without them keeps the stored ones.
KEPT = ("model", "solution_type")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> date:
    """Today in Home Assistant's time zone: the feed schedule's day."""
    from homeassistant.util import dt as dt_util

    return dt_util.now().date()


def _kept(pump, stored: dict):
    """A pump as a save sends it, with what the save keeps from the stored one of its id: a page from
    before pH roles (or the catalogue) sends none, and each keeps its stored role (model, solution
    type); its calibration and prime are the store's alone, whatever the page sends."""
    if not isinstance(pump, dict):
        return pump
    old = stored.get(pump.get("id"), {})
    out = {key: value for key, value in pump.items() if key not in OWNED}
    out.update({key: old[key] for key in OWNED if key in old})
    out.update({key: old[key] for key in KEPT if key not in pump and key in old})
    if "ph_role" not in pump and "solution_type" not in pump:
        out["ph_role"] = old.get("ph_role")
    return out


def catalog() -> dict:
    """dosing_get's `catalog`: each model's name and dial -> nominal mL/min (dial keys as text, for
    JSON), or None for a pump with no table."""
    return {
        catalog_id: (
            None
            if entry is None
            else {
                "name": entry["name"],
                "nominal_ml_min": {
                    str(dial): ml for dial, ml in entry["nominal_ml_min"].items()
                },
            }
        )
        for catalog_id, entry in dosing.PUMP_CATALOG.items()
    }


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
    # A setup stored before the hardware profile has none: it takes the defaults, today's timings.
    data["profile"] = dosing.clean_profile(value.get("profile"))
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
        # A prime's request id -> (pump, who, asked at), until the controller reports it.
        self._primes = {}
        # Each prime holds room dosing: request id -> {pump, until}, until its run is reported plus
        # 60 s. The latest `until` of them all holds the room.
        self._prime_holds = {}
        self._hold_timer = None

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
        from homeassistant.helpers.event import (
            async_track_state_change_event,
            async_track_time_change,
        )

        @callback
        def midnight(_now):
            async_dispatcher_send(self.hass, f"{SIGNAL}_{self.entry.entry_id}")

        @callback
        def status(event):
            self._status_changed(event.data.get("new_state"))

        unsubscribes = (
            async_track_time_change(self.hass, midnight, hour=0, minute=0, second=0),
            # The controller's report of a timed run: a calibration's seconds, a prime's done.
            async_track_state_change_event(self.hass, [self.status_entity], status),
        )

        def unsubscribe():
            for each in unsubscribes:
                each()
            self._end_hold_timer()

        return unsubscribe

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
        """What dosing_get answers. `can_edit`: the caller is an administrator, who may save. Each pump
        with an open calibration session carries it as `calibration_session` (never stored).
        """
        config = deepcopy(self.data)
        calibration = self._calibration()
        for pump in config["pumps"]:
            session = calibration.pump_view(pump["id"]) if calibration else None
            if session is not None:
                pump["calibration_session"] = session
        return {
            "schema_version": 1,
            "room_id": self.room_id,
            "config": config,
            "catalog": catalog(),
            "feed_now": dosing.feed_now(self.data["feed"], _today()),
            "candidates": self.candidates(),
            "can_edit": can_edit,
            "error": error or self.error,
        }

    def sensor(self) -> tuple:
        """sensor.crop_steering_<prefix>dosing_config as (state, attributes): the setup's revision,
        and its pumps, batch (its recipe the one in use today), hardware profile and request, and `feed`:
        which recipe that is and why (dosing.feed_now). Unknown while the stored setup cannot be read, so the
        controller acts on nothing it cannot read."""
        if self.error:
            return None, {"error": self.error}
        batch = deepcopy(self.data["batch"])
        batch["recipe"] = self.recipe()
        # Only while a feed-probe or pump calibration session is open (calibration.py), or a prime holds
        # the room: the controller holds batches and pH correction on it. Absent otherwise, so the
        # descriptor is as it always was.
        calibration = self._calibration()
        calibrating = calibration_module.merge_holds(
            [
                *(calibration.open_holds() if calibration is not None else []),
                self._priming(),
            ]
        )
        return self.data["revision"], {
            "pumps": deepcopy(self.data["pumps"]),
            "batch": batch,
            "profile": deepcopy(self.data["profile"]),
            "request": deepcopy(self.data["request"]),
            "feed": dosing.feed_now(self.data["feed"], _today()),
            **({"calibrating": calibrating} if calibrating else {}),
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
                kept = {
                    key: self.data["batch"].get(key)
                    for key in ("name", *dosing.REMINDER)
                }
                batch = {**kept, **batch}
            sent_pumps = data.get("pumps")
            if isinstance(sent_pumps, list):
                by_id = {p["id"]: p for p in self.data["pumps"]}
                sent_pumps = [_kept(pump, by_id) for pump in sent_pumps]
            try:
                pumps, batch = dosing.clean(
                    sent_pumps,
                    batch,
                    self._exists,
                    self._stock_tanks(),
                )
                feed = dosing.clean_feed(
                    stored if sent is None else sent, pumps, self._exists
                )
                # A save that sends no profile keeps the stored one.
                profile = dosing.clean_profile(
                    data.get("profile", self.data["profile"])
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
                profile=profile,
                updated_at=_now().isoformat(),
            )
            await self._commit(draft)
            return self.response(can_edit=can_edit)

    async def request(self, data, by) -> dict:
        """Store one request for the controller. A stop always replaces what is pending; a dose or a
        batch waits for the one before it to be handled. The setup's revision does not move. A batch
        run anyway (an administrator's test refill) says so with `run_anyway`.
        """
        async with self._lock:
            if self.error:
                return {"request": None, "error": self.error}
            action = data.get("action")
            if action != "stop" and self.pending():
                return {"request": None, "error": "busy"}
            if action in ("dose", "batch") and self.pump_hold():
                return {"request": None, "error": HELD}
            try:
                pump, ml = dosing.check_request(
                    self.data,
                    action,
                    data.get("pump"),
                    data.get("ml"),
                    data.get("run_anyway", False),
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
            if data.get("run_anyway"):
                request["run_anyway"] = True
            replaced = self.data["request"] if self.pending() else None
            draft = deepcopy(self.data)
            draft["request"] = request
            await self._commit(draft)
            self._replaced(replaced)
            return {"request": deepcopy(request), "error": None}

    # ------------------------------------------------------------------ pump prime / calibrate (G3)
    def _calibration(self):
        """The room's calibration store (calibration.py), which holds the pump sessions, or None."""
        return (
            self.hass.data.get(DOMAIN, {})
            .get("_calibration", {})
            .get(self.entry.entry_id)
        )

    def _on(self, entity_id) -> bool:
        state = self.hass.states.get(entity_id) if entity_id else None
        return state is not None and state.state == "on"

    def precheck(self, pump_id) -> dict:
        """What stops a timed run of the pump now (dosing.BLOCKERS), read from its power switch, the
        dosing status, the batch hardware, an open probe session and the controller's heartbeat.
        Changes nothing."""
        pump = dosing.find_pump(self.data, pump_id)
        power = pump.get("power_entity")
        state = self.hass.states.get(power) if power else None
        heartbeat = self.hass.states.get(f"sensor.{DOMAIN}_{self.prefix}ai_heartbeat")
        try:
            age = (_now() - heartbeat.last_updated).total_seconds()
        except (AttributeError, TypeError):
            age = math.inf
        calibration = self._calibration()
        other = calibration.pump_holding() if calibration is not None else None
        found = {
            code
            for code, applies in (
                ("no_power_entity", state is None or state.state == "unavailable"),
                ("batch_running", self.running()),
                ("mix_pump_on", self._on(self.data["batch"].get("mix_pump"))),
                ("tank_filling", self._on(self.data["batch"].get("fill_valve"))),
                ("calibrating", calibration is not None and calibration.probe_open()),
                (
                    "pump_calibrating",
                    other is not None and other["pump"] != pump["id"],
                ),
                ("controller_offline", age > OFFLINE_S),
            )
            if applies
        }
        blockers = dosing.pump_blockers(found)
        return {"ok": not blockers, "blockers": blockers}

    async def _timed(self, action, pump_id, seconds, by) -> tuple[dict | None, list]:
        """Store a prime's or a calibration's request, unless a blocker stands -> (request, blockers)."""
        if self.error:
            raise Unavailable(self.error)
        pump, seconds = dosing.check_timed(self.data, action, pump_id, seconds)
        blockers = self.precheck(pump)["blockers"]
        if blockers:
            return None, blockers
        if self.pending():
            raise GuardRefused(BUSY)
        request = {
            "id": uuid.uuid4().hex,
            "action": action,
            "pump": pump,
            "ml": None,
            "seconds": seconds,
            "at": _now().isoformat(),
            "by": by,
        }
        draft = deepcopy(self.data)
        draft["request"] = request
        await self._commit(draft)
        return request, []

    async def pump_prime(self, pump_id, seconds, by, who=None) -> dict:
        async with self._lock:
            request, blockers = await self._timed("prime", pump_id, seconds, by)
        if request is None:
            return {"request_id": None, "outcome": "refused", "blockers": blockers}
        self._primes[request["id"]] = (request["pump"], who or {}, _now())
        # The controller may take it up to REQUEST_MAX_AGE_S after it was asked for; the hold is cut
        # to the run's report plus 60 s once that comes.
        self._hold_prime(
            request["pump"],
            request["id"],
            dosing.REQUEST_MAX_AGE_S + request["seconds"] + PRIME_HOLD_S,
        )
        return {"request_id": request["id"], "outcome": "requested", "blockers": []}

    async def pump_calibrate(self, pump_id, seconds, by, who=None) -> dict:
        calibration = self._calibration()
        if calibration is None:
            raise ValueError("The room's calibration store is not set up")
        async with self._lock:
            request, blockers = await self._timed("calibrate", pump_id, seconds, by)
        if request is None:
            return {
                "session_id": None,
                "request_id": None,
                "outcome": "refused",
                "blockers": blockers,
            }
        session = calibration.pump_open(
            request["pump"], request["id"], request["seconds"]
        )
        return {
            "session_id": session["id"],
            "request_id": request["id"],
            "outcome": "requested",
            "blockers": [],
        }

    async def pump_stop(self, pump_id, by, admin=True) -> dict:
        """End a prime or a calibration of the pump. What still waits for the controller decides what
        is stored (the waiting request never ran; the answer names it in `replaced`):
        - nothing, or this pump's own prime, calibration or stop_pump: a stop_pump of this pump;
        - another pump's prime, calibration or stop_pump: a room stop instead, which stops every pump
          (the safe direction; one request slot cannot hold both), `replaced` {upgraded_to, was};
        - a room stop: kept, it stops this pump too, and its id is the answer;
        - a dose or a batch, which only an administrator could ask for: replaced only when `admin`
          (an administrator or an automation), else refused with WAITING.
        A running batch or another pump's running job is never touched by a stop_pump (the controller
        stops only this pump).
        """
        async with self._lock:
            if self.error:
                raise Unavailable(self.error)
            pump = dosing.find_pump(self.data, pump_id)["id"]
            waiting = self.data["request"] if self.pending() else None
            action = waiting.get("action") if waiting else None
            if action == "stop":
                return {"request_id": waiting["id"], "replaced": None}
            if action in ("dose", "batch") and not admin:
                raise GuardRefused(WAITING)
            upgrade = action in ("prime", "calibrate", "stop_pump") and (
                waiting.get("pump") != pump
            )
            request = {
                "id": uuid.uuid4().hex,
                "action": "stop" if upgrade else "stop_pump",
                "pump": None if upgrade else pump,
                "ml": None,
                "at": _now().isoformat(),
                "by": by,
            }
            draft = deepcopy(self.data)
            draft["request"] = request
            await self._commit(draft)
            self._replaced(waiting)  # only the replaced request's own hold or session
        if upgrade:
            replaced = {"upgraded_to": "stop", "was": deepcopy(waiting)}
        elif waiting and action != "stop_pump":
            replaced = {key: waiting.get(key) for key in ("id", "action", "pump")}
        else:
            replaced = None
        return {"request_id": request["id"], "replaced": replaced}

    def _replaced(self, request):
        """A waiting request was replaced before the controller took it. A prime then never runs: its
        report and its hold go. A calibration never runs: its session ends, so the pump's later runs
        are drawn from stock again."""
        if not isinstance(request, dict):
            return
        if request.get("action") == "prime":
            self._primes.pop(request.get("id"), None)
            if self._prime_holds.pop(request.get("id"), None) is not None:
                self._rearm()
        elif request.get("action") == "calibrate":
            calibration = self._calibration()
            if calibration is not None:
                calibration.pump_close(request_id=request.get("id"))

    def _dispatch(self):
        from homeassistant.helpers.dispatcher import async_dispatcher_send

        async_dispatcher_send(self.hass, f"{SIGNAL}_{self.entry.entry_id}")

    def _hold_prime(self, pump, request_id, seconds):
        """Hold room dosing for this prime for `seconds` from now. A report shortens only its own
        request's hold; the room stays held until the latest of them all."""
        self._prime_holds[request_id] = {
            "pump": pump,
            "until": _now() + timedelta(seconds=seconds),
        }
        self._rearm()

    def _rearm(self):
        """The holds changed: drop the ended ones and the primes no report can come for any more, write
        the descriptor again now, and again when the latest hold ends."""
        now = _now()
        self._prime_holds = {
            rid: hold for rid, hold in self._prime_holds.items() if now < hold["until"]
        }
        stale = now - timedelta(
            seconds=dosing.REQUEST_MAX_AGE_S + PRIME_SECONDS[1] + PRIME_HOLD_S
        )
        self._primes = {
            rid: prime for rid, prime in self._primes.items() if prime[2] > stale
        }
        self._end_hold_timer()
        holding = self._priming()
        if holding is not None:
            left = (datetime.fromisoformat(holding["until"]) - now).total_seconds()
            self._hold_timer = calibration_module._later(
                self.hass, left + 1, lambda _now: self._rearm()
            )
        self._dispatch()

    def _end_hold_timer(self):
        if self._hold_timer:
            self._hold_timer()
            self._hold_timer = None

    def _priming(self) -> dict | None:
        """The primes' hold on room dosing as {pump, request_id, until} of the one that ends last, or
        None."""
        now = _now()
        live = [
            (hold["until"], rid, hold["pump"])
            for rid, hold in self._prime_holds.items()
            if now < hold["until"]
        ]
        if not live:
            return None
        until, rid, pump = max(live)
        return {"pump": pump, "request_id": rid, "until": until.isoformat()}

    def pump_hold(self) -> dict | None:
        """What holds room dosing for a pump now: its open calibration session ({pump, session_id,
        until}) or a prime ({pump, request_id, until}); None when nothing does."""
        calibration = self._calibration()
        held = calibration.pump_holding() if calibration is not None else None
        return held or self._priming()

    def _status_changed(self, new_state):
        """The controller published its status: the report of a calibration's request gives the session
        its seconds; one of a prime stamps the pump's primed_at and journals pump.primed. A controller
        that keeps each request's answer by its id (handled_results) is read for each request awaited
        here, by its own id; an older one only in handled_result.
        """
        attributes = getattr(new_state, "attributes", None) or {}
        answers = attributes.get("handled_results")
        if not isinstance(answers, dict):
            self._report(attributes.get("handled_result"))
            return
        calibration = self._calibration()
        awaited = [*self._primes]
        if calibration is not None:
            awaited += [
                session["request_id"]
                for session in calibration.sessions.values()
                if "pump" in session and session["ran_s"] is None
            ]
        for request_id in dict.fromkeys(awaited):
            result = answers.get(request_id)
            if isinstance(result, dict) and result.get("id") == request_id:
                self._report(result)

    def _report(self, result):
        """One timed request's report {id, ran_s, result, ...} from the controller."""
        if not isinstance(result, dict) or not result.get("id"):
            return
        ran_s = result.get("ran_s")
        if (
            isinstance(ran_s, bool)
            or not isinstance(ran_s, (int, float))
            or not (math.isfinite(ran_s) and ran_s >= 0)
        ):
            # A run that never started (refused, stuck) may come with no seconds: it ran none. A
            # prime reported done without them is over too: no report of it is awaited any more.
            if result.get("result") in (None, "done"):
                primed = self._primes.pop(result["id"], None)
                if primed is not None:
                    self._hold_prime(primed[0], result["id"], PRIME_HOLD_S)
                return
            ran_s = 0
        calibration = self._calibration()
        if calibration is not None and calibration.pump_reported(
            result["id"], ran_s, result.get("result")
        ):
            return
        primed = self._primes.pop(result["id"], None)
        if primed is not None:
            self._hold_prime(primed[0], result["id"], PRIME_HOLD_S)
            self.hass.async_create_task(
                self._primed(primed[0], primed[1], ran_s, result.get("result"))
            )

    async def _primed(self, pump_id, who, ran_s, result):
        at = _now().isoformat()
        if ran_s > 0:
            async with self._lock:
                draft = deepcopy(self.data)
                pump = next((p for p in draft["pumps"] if p["id"] == pump_id), None)
                if pump is None or self.error:
                    return
                pump["primed_at"] = at
                await self._commit(draft)
        outcome = (
            "ok"
            if result == "done"
            else "aborted" if result == "stopped" else "refused"
        )
        self._journal(
            "pump.primed",
            who,
            {"pump": pump_id, "ran_s": ran_s, "result": result},
            outcome,
        )

    async def pump_calibration_commit(self, session_id, measured_ml, who=None) -> dict:
        """The mL the pump gave in its calibration run -> its calibrated flow, mL/min, stored with the
        calibration (the newest 30 kept); a flow number of the pump is set to it in mL/s and read back.
        """
        calibration = self._calibration()
        if calibration is None:
            raise ValueError("The room's calibration store is not set up")
        session = calibration.session(session_id, pump=True)
        ran_s = session["ran_s"]
        if ran_s is None:
            raise ValueError(
                "The calibration run has not been reported yet. Wait for the pump to stop."
            )
        if ran_s <= 0:
            raise ValueError(
                f"The calibration run did not run: {session['result'] or 'no time reported'}"
            )
        if (
            isinstance(measured_ml, bool)
            or not isinstance(measured_ml, (int, float))
            or not math.isfinite(measured_ml)
            or not 0 < measured_ml <= dosing.MAX_ML * 10
        ):
            raise ValueError("The measured mL must be a number above 0")
        ml_min = round(measured_ml / ran_s * 60, 2)
        ml_min = int(ml_min) if float(ml_min).is_integer() else ml_min
        who = who or {}
        async with self._lock:
            if self.error:
                raise Unavailable(self.error)
            # Committed (or ended) while this call waited for the lock: refused as an expired one.
            if calibration.session(session_id, pump=True) is not session:
                raise ValueError(calibration_module.EXPIRED)
            draft = deepcopy(self.data)
            pump = next((p for p in draft["pumps"] if p["id"] == session["pump"]), None)
            if pump is None:
                raise ValueError(f"unknown pump: {session['pump']}")
            previous = pump.get("calibrated_ml_min")
            record = {
                "id": uuid.uuid4().hex,
                "pump": pump["id"],
                "run_s": ran_s,
                "measured_ml": measured_ml,
                "ml_min": ml_min,
                "previous_ml_min": previous,
                "at": _now().isoformat(),
                "by": who.get("user_id"),
            }
            pump["calibrated_ml_min"] = ml_min
            pump["calibrations"] = [record, *pump.get("calibrations", [])][
                : dosing.MAX_CALIBRATIONS
            ]
            draft.update(revision=self.data["revision"] + 1, updated_at=record["at"])
            await self._commit(draft)
            calibration.pump_close(session_id)
        written = await self._write_flow(pump.get("flow_entity"), ml_min / 60)
        self._journal(
            "pump.calibrated",
            who,
            {
                "pump": pump["id"],
                "ml_min": ml_min,
                "previous_ml_min": previous,
                "run_s": ran_s,
                "measured_ml": measured_ml,
                "session_id": session_id,
                "flow_entity_written": written,
            },
        )
        return {
            "ml_min": ml_min,
            "previous_ml_min": previous,
            "flow_entity_written": written,
        }

    async def _write_flow(self, entity_id, ml_s) -> bool:
        """Set a number/input_number flow entity to `ml_s` and read it back; a sensor is never written."""
        domain = (entity_id or "").partition(".")[0]
        if domain not in ("number", "input_number"):
            return False
        value = round(ml_s, 4)
        value = int(value) if float(value).is_integer() else value
        try:
            await self.hass.services.async_call(
                domain,
                "set_value",
                {"entity_id": entity_id, "value": value},
                blocking=True,
            )
            state = self.hass.states.get(entity_id)
            read = float(state.state)
        except (
            Exception
        ) as error:  # the calibration stands; the answer says the number was not set
            _LOGGER.warning(
                "Pump flow %s not set to %s mL/s: %s", entity_id, value, error
            )
            return False
        return math.isfinite(read) and abs(read - value) <= max(0.005, 0.01 * value)

    def _journal(self, kind, who, data, outcome="ok"):
        who = who or {}
        note(
            self.hass,
            self.room_id,
            kind,
            outcome=outcome,
            actor=who.get("actor", "system"),
            user_id=who.get("user_id"),
            client=who.get("client"),
            data=data,
        )

    def pump_sensors(self) -> dict:
        """Each pump's sensor.crop_steering_<prefix>dosing_pump_<id>_ml_min (its calibrated flow) and
        _last_calibrated, as {entity_id: (state, attributes)}; sensor.py publishes them.
        """
        out = {}
        for pump in self.data["pumps"]:
            base = f"sensor.{DOMAIN}_{self.prefix}dosing_pump_{pump['id']}"
            calibrations = pump.get("calibrations") or []
            common = {"room_id": self.room_id, "pump": pump["id"]}
            out[f"{base}_ml_min"] = (
                pump.get("calibrated_ml_min", "unknown"),
                {
                    **common,
                    "friendly_name": f"{pump['name']} flow",
                    "unit_of_measurement": "mL/min",
                    "nominal_ml_min": dosing.nominal_ml_min(pump.get("model")),
                    "model": pump.get("model"),
                },
            )
            out[f"{base}_last_calibrated"] = (
                calibrations[0]["at"] if calibrations else "unknown",
                {
                    **common,
                    "friendly_name": f"{pump['name']} last calibrated",
                    "device_class": "timestamp",
                    "previous_ml_min": (
                        calibrations[0].get("previous_ml_min") if calibrations else None
                    ),
                },
            )
        return out

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

    if getattr(call.context, "user_id", None) and await _caller(hass, call) is None:
        raise forbidden(f"{action} requires a signed-in Home Assistant user")


async def _handle_pump(hass, call):
    """The pump services (G3). A precheck reads and a pump stop only switches off: any signed-in user;
    a prime, a calibration and its commit need an administrator."""
    from homeassistant.exceptions import HomeAssistantError

    service, data = call.service, call.data
    if service in OPEN:
        await _require_signed_in(hass, call, f"{DOMAIN}.{service}")
    elif service != "pump_precheck":
        await async_require_admin(hass, call, f"{DOMAIN}.{service}")
    try:
        target = resolve_dosing(hass, data["room_id"])
        if service == "pump_precheck":
            return target.precheck(data["pump"])
        user = await _caller(hass, call)
        by = getattr(user, "name", None)
        if service == "pump_stop":
            # An automation (no user) is trusted as the administrator checks trust it.
            admin = user is None or bool(getattr(user, "is_admin", False))
            return await target.pump_stop(data["pump"], by, admin)
        who = attribution(hass, call)
        if service == "pump_prime":
            return await target.pump_prime(data["pump"], data["seconds"], by, who)
        if service == "pump_calibrate":
            return await target.pump_calibrate(data["pump"], data["seconds"], by, who)
        return await target.pump_calibration_commit(
            data["session_id"], data["measured_ml"], who
        )
    except (ValueError, KeyError, OSError) as error:
        raise HomeAssistantError(str(error)) from error


async def async_setup_dosing(hass, entry):
    import voluptuous as vol
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError

    from .api_v2 import failure, fields, nested_revision, wrap

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
        if call.service in PUMP_SERVICES:
            return await _handle_pump(hass, call)
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

    def refusal(call, result):
        """API v2: a request or save this service answered as refused instead of raising."""
        error = result.get("error") if isinstance(result, dict) else None
        if not error or (call.service == "dosing_request" and result.get("request")):
            return None
        if error == "revision":
            return failure(
                "stale_revision",
                "The dosing setup changed elsewhere. Reload before saving.",
                nested_revision(result),
            )
        if error == "busy":
            return failure(
                "guard_refused",
                "A dose or batch is waiting or running: try again after it",
            )
        if error == HELD:
            return failure("guard_refused", error)
        if error == resolve_dosing(hass, call.data["room_id"]).error:
            return failure("unavailable", error)
        return failure("invalid", error)

    def pump_refused(call, result):
        """API v2: a prime or calibration a blocker refused ({outcome: refused, blockers})."""
        if not isinstance(result, dict) or result.get("outcome") != "refused":
            return None
        return failure(
            "guard_refused",
            "The pump cannot run now: "
            + "; ".join(b["message"] for b in result.get("blockers") or ()),
        )

    schemas = {
        "dosing_get": {vol.Required("room_id"): str},
        "dosing_save": {
            vol.Required("room_id"): str,
            vol.Required("expected_revision"): vol.All(int, vol.Range(min=0)),
            vol.Required("pumps"): list,
            vol.Required("batch"): dict,
            vol.Optional("feed"): dict,
            vol.Optional("profile"): dict,
        },
        "dosing_request": {
            vol.Required("room_id"): str,
            vol.Required("action"): vol.In(dosing.REQUEST_ACTIONS),
            vol.Optional("pump"): str,
            vol.Optional("ml"): vol.Coerce(float),
            vol.Optional("run_anyway"): bool,
        },
        "pump_precheck": {vol.Required("room_id"): str, vol.Required("pump"): str},
        "pump_prime": {
            vol.Required("room_id"): str,
            vol.Required("pump"): str,
            vol.Required("seconds"): vol.All(
                vol.Coerce(float), vol.Range(min=PRIME_SECONDS[0], max=PRIME_SECONDS[1])
            ),
        },
        "pump_stop": {vol.Required("room_id"): str, vol.Required("pump"): str},
        "pump_calibrate": {
            vol.Required("room_id"): str,
            vol.Required("pump"): str,
            vol.Required("seconds"): vol.All(
                vol.Coerce(float),
                vol.Range(min=CALIBRATE_SECONDS[0], max=CALIBRATE_SECONDS[1]),
            ),
        },
        "pump_calibration_commit": {
            vol.Required("room_id"): str,
            vol.Required("session_id"): str,
            vol.Required("measured_ml"): vol.Coerce(float),
        },
    }
    for service in SERVICES:
        hass.services.async_register(
            DOMAIN,
            service,
            wrap(
                handle,
                revision_of=nested_revision,
                error_of={
                    "dosing_request": refusal,
                    "dosing_save": refusal,
                    "pump_prime": pump_refused,
                    "pump_calibrate": pump_refused,
                },
            ),
            schema=vol.Schema(fields(schemas[service])),
            # Reads answer only; a pump service that leaves a request or stores a flow may answer.
            supports_response=(
                SupportsResponse.OPTIONAL
                if service in PUMP_SERVICES and service != "pump_precheck"
                else SupportsResponse.ONLY
            ),
        )


async def async_unload_dosing(hass, entry):
    managers = hass.data.get(DOMAIN, {}).get("_dosing", {})
    managers.pop(entry.entry_id, None)
    if not managers:
        for service in SERVICES:
            hass.services.async_remove(DOMAIN, service)
