"""Batch-tank dosing for every room, on one thread of its own (docs/DOSING.md).

The integration keeps each room's dosing setup and its one request, and publishes them as
sensor.crop_steering_<prefix>dosing_config. This thread reads that every 2 s and takes each request
once. A dose sets a pump's volume number and presses its start: the pump's own firmware runs the
motor for that volume and switches it off. A batch holds the watering it could disturb, fills the
tank, mixes it, doses the recipe in order and stamps the fill. Nothing here ever switches a dosing
motor on; switching one off (a stop, a dose past its time) is the only thing done to its power.
What each room is doing is published as sensor.crop_steering_<prefix>dosing.

Whatever could be left running is written to dosing_state.json before anything moves. Whatever
does not read off when a dose or a batch ends, and whatever a start finds recorded, holds its rooms'
watering and is switched off again on every pass until all of it reads off (_release_stuck). The
irrigation loop asks holds() before every shot. A batch sets its hold under the lock a shot starts
under (Controller._shot_lock): a shot either started before it, and the batch waits for that shot to
end, or never starts. Every switch-on goes through _on, which the way out (exit) never overtakes.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone

POLL_S = 2.0  # each room's dosing_config is read this often
READ_S = 1.0  # a dosing pump is read this often during a dose
MAX_AGE_S = 120.0  # a dose or batch asked for longer ago than this is never acted on
HOLD_WAIT_S = 600.0  # a batch waits this long at most for a shot in flight in a room it holds
MIX_POWER_S = 20.0  # the mix pump must draw its power within this
FILL_OPEN_S = 10.0  # the fill valve must read on within this
FULL_BLIND_S = 15.0  # a full sensor that reads nothing for this long mid-fill ends the fill
# Read-back after a command, as the controller reads back a valve (Controller._confirm_switches).
CONFIRM_FIRST_S, CONFIRM_POLL_S, CONFIRM_TIMEOUT_S = 1.0, 0.5, 6.0
VOLUME_TOLERANCE_ML = 0.5
MIN_FLOW_ML_S = 0.05  # a flow below this is no calibration: a dose would be expected to take hours
MAX_DOSE_S = 1200.0  # no dose may be expected to take longer than 20 min
DOSE_CAP_S = MAX_DOSE_S + 60.0  # and none is left running past this, whatever its expected time
REFRESH_S = 30.0  # the pumps' flow and state are read this often
CHORES_S = 30.0  # while a dose or batch runs, stock draws, alerts and volume put-backs wait this long
QUICK_S = 2.0  # the Home Assistant timeout for those chores, for re-sent offs and for the way out
ON_TIMEOUT_S = 4.0  # a switch-on's Home Assistant timeout: always inside the way out's wait for it
EXIT_GATE_S = 5.0  # the way out waits this long for a switch-on in flight to land
EXIT_JOIN_S = 3.0  # and this long for the thread to switch its own job's hardware off
REALERT_S = 1800.0  # hardware that does not read off is alerted again this often
DRAW_GIVE_UP_S = 86400.0  # a stock draw not taken within this is given up, with an alert
STALL_S = 600.0  # the thread not seen going round for this long is stalled (health)
POLL_FAILS = 15  # one room failing this many passes in a row (30 s) is alerted
REPUBLISH_S = 60.0  # an unchanged status is published again this often (with a new updated_at)
HISTORY = 20
OUTBOX = 50  # alerts waiting for Home Assistant, at most
DEAD = ("", "unknown", "unavailable", "none")
_RUNNING = {"dose": "dosing", "batch": "making a batch"}  # handled_result until it ends
_PUT_BACK = ("name", "volume_entity", "dosing_entity", "dosing_prefix", "power_entity")


class _Ended(Exception):
    """A batch ends here, short of finishing; the message says why."""


class _Exit(BaseException):
    """The app is stopping: leave whatever is recorded for the next start. Not an Exception, so no
    handler meant for a failure catches it."""


def _domain(entity):
    return entity.split(".", 1)[0]


def _fmt(value):
    return f"{value:g}" if isinstance(value, (int, float)) else str(value)


def _dead(state):
    return state is None or str(state).strip().lower() in DEAD


def _does(items):
    """"X does" / "X, Y do"."""
    return f"{', '.join(items)} {'does' if len(items) == 1 else 'do'}"


def _still(items):
    """"X still does not read off" / "X, Y still do not read off"."""
    return f"{', '.join(items)} still {'does' if len(items) == 1 else 'do'} not read off"


def _event(*parts):
    """One alert per event: the part of its notification id that tells two events apart."""
    return re.sub(r"[^a-z0-9]+", "_", "_".join(str(p) for p in parts if p).lower()).strip("_")[:80]


def _aware(stamp):
    try:
        parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else None


class _Job:
    """The one dose or batch this thread is running."""

    def __init__(self, room, config, request, kind):
        self.room, self.config, self.request, self.kind = room, config, request, kind
        self.stopped = False  # a stop request for this room arrived
        self.stopped_by = None
        self.deadline = None  # a batch's watchdog, on the runner's clock
        self.step = None  # the batch step running
        self.pump = None  # a single dose's pump
        self.dose = None  # the dose running: pump, ml, started_at, expected_s
        self.pressed = None  # when the running dose's start was pressed, on the runner's clock
        self.cut_at = None  # when a stop or a cut was sent to the running dose, on the runner's clock
        self.left = []  # what the running dose's end left not reading off
        self.doses = {}  # pump -> mL of every dose started, for the history
        self.started_at = None


class DosingRunner:
    def __init__(self, controller, *, get, call, publish, alert, state_path, log=print,
                 sleep=time.sleep, monotonic=time.monotonic, now=None, history=None, respond=None):
        self.c = controller
        # get(entity, timeout=...) -> (state, attributes, last_updated) with .last_changed;
        # call(domain, service, timeout=..., **data) -> bool; publish(entity, state, attributes);
        # alert(room, code, title, message, event) -> True once Home Assistant has it;
        # history(entity, since) -> [(state, last_changed), ...] or None;
        # respond(domain, service, data, timeout) -> (HTTP status or None, the service's answer).
        self._get, self._call, self._publish = get, call, publish
        self._deliver, self._log = alert, log
        self._history = history or (lambda _entity, _since: None)
        self._respond = respond
        self._sleep, self._mono = sleep, monotonic
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.path = state_path
        self._lock = threading.RLock()  # guards everything below; never held across a Home Assistant call
        self._gate = threading.Lock()  # held across a switch-on (_on), so exit() never overtakes one
        self._held = {}  # room slug -> the slugs of the rooms its batch, or what it left on, holds
        self._stuck = {}  # room slug -> what did not read off, held until it does (_release_stuck)
        self._job = None
        self._exiting = False
        self._recovered = False
        self._thread = None
        self.beat = None  # when the thread last went round, on the runner's clock (health)
        self._polled = None
        self._chores = None  # when the chores (draws, alerts, put-backs) last ran
        self._fails = {}  # room slug -> passes in a row that failed
        self._live = {}  # slug -> what its status shows that is not persisted
        self._corrupt = False  # dosing_state.json could not be read at start (see recover)
        self._sweep = set()  # rooms whose dosing hardware a corrupt file leaves to switch off
        self._doc = self._read()

    # ------------------------------------------------------------------ what the controller calls
    def holds(self, room):
        """Why a dose or batch holds this room's watering (docs/DOSING.md), else None: "making a
        batch" while a batch holds it, "dosing hardware still on: <entity>" while something a dose or
        a batch left, or a start found recorded, does not read off."""
        found = None
        with self._lock:
            for slug, rooms in self._held.items():
                if room.slug not in rooms:
                    continue
                stuck = self._stuck.get(slug)
                if stuck is not None:
                    return "dosing hardware still on: " + ", ".join(stuck["left"])
                found = "making a batch"
        return found

    def start(self):
        thread = threading.Thread(target=self._run, name="dosing", daemon=True)
        with self._lock:
            self._thread = thread
        thread.start()
        return thread

    def health(self):
        """For the controller's main loop: None before start() and on the way out; "dead" once the
        thread has stopped, "stalled" when it has not gone round for STALL_S, else "ok"."""
        with self._lock:
            thread, exiting = self._thread, self._exiting
        if thread is None or exiting:
            return None
        if not thread.is_alive():
            return "dead"
        beat = self.beat
        return "stalled" if beat is not None and self._mono() - beat > STALL_S else "ok"

    def restart(self):
        """The thread died: recover as after a restart (whatever is recorded is held and switched
        off; nothing is resumed), say so, and start it again."""
        with self._lock:
            self._job = None
            self._held.clear()
            self._stuck.clear()
            self._recovered = False
        self.recover()
        self._alert(None, "CS-806", "dosing stopped with an error and was started again",
                    "The controller's dosing thread stopped with an error, and the controller started "
                    "it again. Whatever a dose or batch had running was switched off and holds its "
                    "rooms' watering until it reads off; nothing was resumed. Check the controller "
                    "app's log, and the tank if a dose or batch was running.",
                    _event("thread", self._now().isoformat()))
        return self.start()

    def recover(self):
        """At start-up, and when the thread is started again: whatever a dose or batch left recorded
        holds its rooms (the batch's, or the dose's own), is switched off, and is switched off again
        on every pass until every part of it reads off (_release_stuck); a batch's hold goes off only
        then. CS-803 says so, and again every 30 min while anything does not read off. Its volume
        number is put back. Nothing is ever resumed. After a corrupt dosing_state.json, every room
        with dosing set up has its current dosing hardware switched off the same way. Always True:
        holding needs nothing from Home Assistant."""
        swept = False
        with self._lock:
            if self._recovered:
                return True
            self._recovered = True
            for slug, block in list(self._doc["rooms"].items()):
                if isinstance(block, dict) and isinstance(block.get("inflight"), dict):
                    self._recover_record(slug)
            if self._corrupt:
                self._corrupt, swept = False, True
                self._sweep = {room.slug for room in list(self.c.rooms)}
                self._write()  # a fresh file; the one that could not be read is kept as .bad
        if swept:
            self._alert(None, "CS-803", "dosing lost its record of what was running",
                        "dosing_state.json could not be read at start, so whether a dose or a batch "
                        "was running is not known. It was kept as dosing_state.json.bad, and every "
                        "room with dosing set up has its dosing pumps' power, fill valve, mix pump and "
                        "mix valves switched off; a room whose hardware does not read off is held until "
                        "it does. Check the batch tanks before dosing again.",
                        _event("state_file", self._now().isoformat()))
        self._release_stuck()
        return True

    def exit(self):
        """The app is stopping (SIGTERM, after the irrigation's own safe-off): no switch-on starts
        from here on (one in flight lands first, EXIT_GATE_S at most), the thread gets EXIT_JOIN_S to
        switch its own job's hardware off, and then everything recorded is switched off again, each
        off with a QUICK_S timeout and no read-back. The records stay, and a batch's hold stays on,
        so the next start reads it all back off (recover) and raises CS-803."""
        got = self._gate.acquire(timeout=EXIT_GATE_S)
        try:
            with self._lock:
                self._exiting = True
                thread = self._thread
        finally:
            if got:
                self._gate.release()
        if thread is not None and thread is not threading.current_thread() and thread.is_alive():
            thread.join(EXIT_JOIN_S)
        with self._lock:
            records = [
                dict(block["inflight"]) for block in self._doc["rooms"].values()
                if isinstance(block, dict) and isinstance(block.get("inflight"), dict)
            ]
        for record in records:
            for entity in record.get("off") or []:
                if isinstance(entity, str) and "." in entity:
                    self._send_off(entity)

    # ------------------------------------------------------------------ the thread
    def _run(self):
        while not self._exiting:
            self.beat = self._mono()
            try:
                if self.recover():
                    self.poll()
            except _Exit:
                return
            except Exception as e:  # the dosing thread must never die
                self._log("dosing: error", repr(e))
            if not self._exiting:
                self._sleep(POLL_S)

    def poll(self, busy=None):
        """Read every room's dosing_config once: take each new request, publish each room's status.
        `busy` is the dose or batch running (this is its pass between reads): then only a stop is
        acted on, a dose or batch is refused, and the chores wait CHORES_S between runs."""
        now = self._polled = self.beat = self._mono()
        self._safely(self._release_stuck)
        self._safely(self._sweep_rooms)
        if busy is None or self._chores is None or now - self._chores >= CHORES_S:
            self._chores = now
            for chore in (self._restore_pending, self._send_draws, self._send_alerts):
                self._safely(chore)
        for room in list(self.c.rooms):
            try:
                self._poll_room(room, busy)
            except Exception as e:  # one room's error never stops the others
                self._room_failed(room, e)
            else:
                self._fails.pop(room.slug, None)

    def _poll_room(self, room, busy):
        config = self._config(room)
        job = busy if busy is not None and busy.room.slug == room.slug else None
        request = config.get("request") if config else None
        if isinstance(request, dict) and isinstance(request.get("id"), str):
            with self._lock:
                handled = self._block(room)["handled"]
            if request["id"] != handled:
                self._take(room, config, request, busy)
        # A running job keeps the setup it read when one read of it fails: still dosing, not unavailable.
        self._show(room, job.config if config is False and job is not None else config)

    def _safely(self, work):
        try:
            work()
        except _Exit:
            raise
        except Exception as e:
            self._log("dosing: error", repr(e))

    def _room_failed(self, room, error):
        count = self._fails[room.slug] = self._fails.get(room.slug, 0) + 1
        self._log(f"[{room.slug}] dosing: error", repr(error))
        if count == POLL_FAILS:
            self._alert(room.slug, "CS-806", "dosing in this room keeps failing",
                        f"The controller's dosing has failed {count} times in a row for this room "
                        f"(the last: {error!r}), so a request for it may not be taken and its status "
                        "is not up to date. Anything a dose or batch left not reading off is still "
                        "switched off and held. Check the controller app's log and the room's dosing "
                        "setup.", _event("poll", self._now().isoformat()))

    def _take(self, room, config, request, busy):
        age = self._age(request)
        action = request.get("action")
        with self._lock:
            stuck = self._stuck.get(room.slug)
            left = list(stuck["left"]) if stuck else []
        here = busy is not None and busy.room.slug == room.slug
        if action == "stop" and (here or stuck):  # never too old while there is something to stop
            return self._settle(room, config, request, self._stop(room, config, busy, request))
        if age is None or age > MAX_AGE_S:
            return self._settle(room, config, request, "too old to act on")
        if action == "stop":
            return self._settle(room, config, request, self._stop(room, config, busy, request))
        if busy is not None:
            where = "" if here else f" in room {busy.room.slug}"
            return self._settle(room, config, request, f"refused: a {busy.kind} is running{where}")
        if stuck:
            return self._settle(room, config, request, f"refused: {_does(left)} not read off yet")
        if action not in ("dose", "batch"):
            return self._settle(room, config, request, f"refused: unknown action {action!r}")
        with self._lock:  # taken: from here on it is handled, whatever comes of it
            block = self._block(room)
            block["handled"], block["handled_result"] = request["id"], _RUNNING[action]
            self._write()
        if action == "dose":
            return self._run_dose(room, config, request)
        return self._run_batch(room, config, request)

    def _stop(self, room, config, busy, request):
        """Every pump's power in the room off, the running job's and the current setup's (a setup
        saved since the job started may name other pumps), and whatever the room left not reading
        off; a dose or batch running in the room ends at its next check, and a room held by what did
        not read off is released once all of it does."""
        job = busy if busy is not None and busy.room.slug == room.slug else None
        entities = [p["power_entity"] for p in job.config["pumps"]] if job is not None else []
        entities += [p["power_entity"] for p in config["pumps"]]
        with self._lock:
            stuck = deepcopy(self._stuck.get(room.slug))
        if stuck:
            entities += stuck["entities"]
        if job is not None:
            job.stopped, job.stopped_by = True, request.get("by")
            if job.pressed is not None and job.cut_at is None:
                job.cut_at = self._mono()  # a stopped dose drew until now (_stock_draw)
        left = self._switch_off(entities)
        if stuck and not left and stuck["hold"]:
            left = self._switch_off([stuck["hold"]])
        if stuck and not left:
            self._release(room.slug, stuck)
        return "stopped" + (f"; {_does(left)} not read off" if left else "")

    # ------------------------------------------------------------------ one dose
    def _run_dose(self, room, config, request):
        """One dose, always settled: an error in the controller cuts the pump and ends it "stopped: an
        error in the controller" (CS-806); a pump whose power does not read off keeps its record and
        holds the room's watering until it does (_release_stuck)."""
        pump = next((p for p in config["pumps"] if p["id"] == request.get("pump")), None)
        if pump is None:
            return self._settle(room, config, request,
                                f"refused: there is no pump {request.get('pump')} in this room's setup")
        job = _Job(room, config, request, "dose")
        job.pump = pump
        with self._lock:
            self._job = job
        try:
            result = self._dose(job, pump, request.get("ml"))
        except _Exit:
            self._exit_off(job)
            raise
        except Exception as e:  # outside the watch itself: the dose is still cut and settled
            result = self._dose_error(job, pump, e)
        finally:
            with self._lock:
                self._job = None
        left, started = list(job.left), job.started_at
        if left:
            code = "CS-801" if result == "ran past its time" else "CS-806"
            if result == "stopped":  # the other ends named it in their own alert already
                self._alert(room.slug, "CS-806", "a dose was stopped, but its pump does not read off",
                            f"The dose of {pump['name']} was stopped, but {_still(left)}, so watering "
                            "in this room is held, and the off is sent again every 2 seconds, until it "
                            "does. Switch it off by hand if it is still running, and check the tank "
                            "before dosing again.", _event(pump["id"], started))
            self._hold_stuck(room, left, None, {room.slug}, code, "a dosing pump does not read off",
                             f"A dose of {pump['name']} ended ({result}).",
                             "Check the pump, and the tank, before dosing again.",
                             _event(pump["id"], started), alerted=True)
        entry = None
        if not result.startswith("refused"):
            entry = {"kind": "dose", "at": started, "ended_at": self._now().isoformat(),
                     "result": result, "doses": {pump["id"]: request.get("ml")}, "by": request.get("by")}
        self._settle(room, config, request, result, entry=entry, clear=not left, final=True)
        self._safely(self._send_draws)  # what it drew, now that nothing runs

    def _dose_error(self, job, pump, error):
        """An error in the controller in the middle of a dose: its power off and read back, and, for a
        single dose, CS-806 (a batch says it in its own)."""
        self._log(f"[{job.room.slug}] dosing: dose error", repr(error))
        if job.pressed is not None and job.cut_at is None:
            job.cut_at = self._mono()
        try:
            job.left = self._switch_off([pump["power_entity"]])
        except Exception as again:
            self._log(f"[{job.room.slug}] dosing: could not switch the pump off", repr(again))
            job.left = [pump["power_entity"]]
        if job.kind == "dose":
            self._alert(job.room.slug, "CS-806", "a dose was stopped by an error in the controller",
                        f"The dose of {pump['name']} stopped: an error in the controller ({error!r}). "
                        f"Its power ({pump['power_entity']}) was switched off"
                        + (", but it does not read off, so watering in this room is held, and the off "
                           "is sent again every 2 seconds, until it does." if job.left else ".")
                        + " How much went in is not known: check the tank before dosing again.",
                        _event(pump["id"], job.started_at))
        return "stopped: an error in the controller"

    def _dose(self, job, pump, ml):
        """One dose of `ml` mL through `pump` (docs/DOSING.md, One dose) -> "finished", "ended early",
        "ran past its time", "not confirmed" or "stopped" ("stopped: an error in the controller"), or
        "refused: why" when nothing was pressed. job.left: what its end left not reading off."""
        job.left, job.pressed, job.cut_at = [], None, None
        why, flow = self._dose_check(pump, ml)
        if why:
            return f"refused: {why}"
        volume = pump["volume_entity"]
        old = None
        if pump.get("restore_volume", True):
            old = self._number(volume)
            if old is None:
                return f"refused: {volume} can't be read, so it could not be put back"
        expected = ml / flow
        started = self._now().isoformat()
        job.started_at = job.started_at or started
        job.dose = {"pump": pump["id"], "ml": ml, "started_at": started,
                    "expected_s": round(expected, 1)}
        record = {"pump": pump["id"], "ml": ml, "at": started}
        if old is not None:  # what to put back, even after a restart (recover)
            record.update(old_volume=old, **{key: pump.get(key) for key in _PUT_BACK})
        fields = {"dose": record, "doses": {**job.doses, pump["id"]: ml}}
        if job.kind == "dose":  # a single dose never records, or touches, a batch's hold
            fields.update(kind="dose", at=started, request=job.request["id"],
                          by=job.request.get("by"), off=self._dosing_hardware(job.config))
        if not self._record(job, fields, merge=job.kind == "batch"):
            job.dose = None
            return "refused: the dose could not be written to dosing_state.json"
        self._show(job.room, job.config)
        try:
            result = self._run_one(job, pump, ml, flow, expected)
        except (_Exit, _Ended):
            raise
        except Exception as e:
            result = self._dose_error(job, pump, e)
        finally:
            job.dose = None
        if old is not None and not self._put_back(job.room.slug, record):
            self._queue_put_back(job.room.slug, record)  # the pump may still run: later
        end = job.cut_at if job.cut_at is not None else self._mono()
        elapsed = end - job.pressed if job.pressed is not None else 0.0
        result = self._stock_draw(job, pump, ml, flow, result, elapsed, started)
        if not result.startswith("refused"):
            job.doses[pump["id"]] = ml
            with self._lock:
                self._block(job.room)["last"][pump["id"]] = {"ml": ml, "at": started, "result": result}
        return result

    def _stock_draw(self, job, pump, ml, flow, result, elapsed, started):
        """What the dose took from the pump's stock tank (docs/DOSING.md, Stock tanks): finished, the
        mL asked for; any other end that pressed start, that or the seconds from the press to the
        moment it ended, or its stop or cut was sent, x the flow, whichever is less; not confirmed,
        nothing, and the result says so. Queued for stock_draw."""
        tank = pump.get("stock_tank")
        if not tank or result.startswith("refused"):
            return result
        if result == "not confirmed":
            return "not confirmed; nothing drawn from its stock tank"
        amount = ml if result == "finished" else min(ml, max(0.0, elapsed) * flow)
        if amount > 0:
            self._queue_draw(job.room, {
                "key": f"{job.room.prefix}:{pump['id']}:{started}",
                "room_id": f"room:{job.room.prefix}",
                "draws": {tank: round(amount, 1)},
                "source": job.kind,
                "note": f"{pump['name']}: {result}",
            })
        return result

    def _queue_draw(self, room, draw):
        """Saved before it is sent, so it survives Home Assistant being down or a restart; sent with
        the chores (_send_draws)."""
        with self._lock:
            block = self._block(room)
            if all(pending.get("key") != draw["key"] for pending in block["draws"]):
                block["draws"].append({**draw, "queued_at": self._now().isoformat()})
            self._write()

    def _send_draws(self):
        """Send every stock draw not yet taken, asking for the service's answer. Taken: dropped. A
        tank the room does not have, a refusal (HTTP 4xx), or no answer for DRAW_GIVE_UP_S: dropped,
        kept in the room's history and alerted (CS-807). Otherwise sent again with the next chores:
        its key means the integration never counts one twice."""
        with self._lock:
            pending = [
                (slug, draw) for slug, block in self._doc["rooms"].items() if isinstance(block, dict)
                for draw in block.get("draws") or [] if isinstance(draw, dict) and draw.get("key")
            ]
            for _slug, draw in pending:
                draw.setdefault("queued_at", self._now().isoformat())  # queued by an older version
            pending = [(slug, dict(draw)) for slug, draw in pending]
        for slug, draw in pending:
            data = {k: draw[k] for k in ("room_id", "key", "draws", "source", "note") if draw.get(k) is not None}
            status, answer = self._ask("crop_steering", "stock_draw", data)
            why = None
            if status is None or not 200 <= status < 300 and not 400 <= status < 500:
                queued = _aware(draw.get("queued_at"))
                if queued is None or (self._now() - queued).total_seconds() < DRAW_GIVE_UP_S:
                    continue
                why = "Home Assistant did not take it within 24 hours"
            elif status >= 400:
                why = f"Home Assistant refused it (HTTP {status})"
            else:
                skipped = (answer or {}).get("skipped") if isinstance(answer, dict) else None
                unknown = [t for t in (skipped or []) if t in (draw.get("draws") or {})]
                if unknown:
                    why = f"{_does(unknown)} not name one of this room's stock tanks"
            self._drop_draw(slug, draw, why)

    def _drop_draw(self, slug, draw, why):
        with self._lock:
            block = self._block(slug)
            block["draws"] = [d for d in block["draws"] if d.get("key") != draw["key"]]
            if why:
                self._add_history(block, {
                    "kind": "draw", "at": draw.get("queued_at"), "ended_at": self._now().isoformat(),
                    "result": f"not taken off its stock tank: {why}", "doses": {}, "by": None,
                    "draws": draw.get("draws"), "note": draw.get("note"),
                })
            self._write()
        if why:
            amounts = ", ".join(f"{_fmt(ml)} mL from {tank}" for tank, ml in (draw.get("draws") or {}).items())
            self._alert(slug, "CS-807", "a dose was not taken off its stock tank",
                        f"{draw.get('note') or 'A dose'}: {amounts} was not taken off its stock tank: "
                        f"{why}. That stock tank's level is now higher than what is in it: set it in "
                        "Stock tanks (Set level), and check the pump's stock tank in the dosing setup.",
                        _event("draw", draw.get("key")))

    def _ask(self, domain, service, data):
        """A service call that asks for the service's answer -> (HTTP status or None, the answer)."""
        if self._respond is None:  # no way to ask: a plain call, taken when it answers
            return (200 if self._call(domain, service, timeout=QUICK_S, **data) else None), None
        return self._respond(domain, service, data, QUICK_S)

    def _put_back(self, slug, dose):
        """A pump's volume number, put back to what it was before a dose (restore_volume) once the
        pump reads idle or its power reads off, and read back: when it does not read back, the
        volume number of <pump> could not be put back, and CS-806 says so. -> False while it must
        wait (queued, and tried again with the chores)."""
        pump = {"dosing_entity": dose.get("dosing_entity") or "", "dosing_prefix": dose.get("dosing_prefix")}
        idle = bool(pump["dosing_entity"]) and self._dosing(pump)[0] is False
        if not idle and self._state(dose.get("power_entity")) != "off":
            return False
        volume, value = dose["volume_entity"], dose["old_volume"]
        self._call(_domain(volume), "set_value", entity_id=volume, value=value)
        if not self._confirm_value(volume, value):
            name = dose.get("name") or dose.get("pump")
            self._alert(slug, "CS-806", "a dosing pump's volume could not be put back",
                        f"After a dose, the volume number of {name} could not be put back to "
                        f"{_fmt(value)} mL: {volume} reads {self._state(volume)}. Its firmware may keep "
                        "its batch recipe in it: set it back by hand before the next batch.",
                        _event("volume", dose.get("pump"), dose.get("at")))
        return True

    def _queue_put_back(self, slug, dose):
        with self._lock:
            block = self._block(slug)
            same = [r for r in block["restores"] if (r.get("pump"), r.get("at")) == (dose.get("pump"), dose.get("at"))]
            if not same:
                block["restores"].append(dict(dose))
            self._write()

    def _restore_pending(self):
        with self._lock:
            pending = [
                (slug, dict(dose)) for slug, block in self._doc["rooms"].items() if isinstance(block, dict)
                for dose in block.get("restores") or []
                if isinstance(dose, dict) and dose.get("volume_entity") and dose.get("old_volume") is not None
            ]
        for slug, dose in pending:
            if not self._put_back(slug, dose):
                continue
            with self._lock:
                block = self._block(slug)
                block["restores"] = [r for r in block["restores"]
                                     if (r.get("pump"), r.get("at")) != (dose.get("pump"), dose.get("at"))]
                self._write()

    def _uncalibrated(self, pump):
        """Why the pump's flow can't be used, or None: it must read a number of at least
        MIN_FLOW_ML_S (a firmware that divides by a zero flow runs its motor for ever, and a tiny one
        would put every time limit hours away)."""
        flow = self._number(pump["flow_entity"])
        if flow is not None and flow >= MIN_FLOW_ML_S:
            return None
        reading = self._state(pump["flow_entity"])
        return f"{pump['name']} is not calibrated (flow {'missing' if reading is None else reading})"

    @staticmethod
    def _too_long(pump, ml, flow):
        return (f"{_fmt(ml)} mL of {pump['name']} would take {ml / flow / 60:.1f} min at "
                f"{_fmt(flow)} mL/s, more than {MAX_DOSE_S / 60:g} min")

    def _dose_check(self, pump, ml):
        """Why this dose must not start (docs/DOSING.md, One dose, step 1) and the pump's flow."""
        why = self._uncalibrated(pump)
        if why:
            return why, None
        flow = self._number(pump["flow_entity"])
        if (isinstance(ml, bool) or not isinstance(ml, (int, float)) or not math.isfinite(ml)
                or not 0 < ml <= float(pump.get("max_ml") or 0)):
            return f"{_fmt(ml)} mL is not more than 0 and at most {_fmt(pump.get('max_ml'))} mL", None
        if ml / flow > MAX_DOSE_S:
            return self._too_long(pump, ml, flow), None
        dosing = self._dosing(pump)[0]
        if dosing is True:
            return f"{pump['name']} already reads dosing", None
        if dosing is None:  # it could not be watched
            return f"{pump['name']}'s dosing state ({pump['dosing_entity']}) can't be read", None
        if str(self._state(pump["power_entity"])).strip().lower() == "on":
            return f"{pump['name']} is running by hand", None  # its power is its motor's own switch
        return None, flow

    def _run_one(self, job, pump, ml, flow, expected):
        """Set the volume, read it back, press start, and watch the pump dose and stop."""
        volume, start = pump["volume_entity"], pump["start_entity"]
        self._call(_domain(volume), "set_value", entity_id=volume, value=ml)
        if not self._confirm_value(volume, ml):
            return f"refused: {volume} did not read back {_fmt(ml)} mL, so start was not pressed"
        pressed_at, pressed = self._now(), self._mono()  # before the press: the recorder is read from here
        domain = _domain(start)
        try:
            if not self._on(job, start, "turn_on" if domain == "script" else "press"):
                self._log(f"[{job.room.slug}] dosing: pressing {start} failed; watching the pump anyway")
        except _Ended:  # a stop, or the batch's watchdog, came first: nothing was pressed
            return "stopped"
        job.pressed = pressed
        deadline = pressed + min(expected * 1.25 + 20, DOSE_CAP_S)
        confirm_by = pressed + expected + 15
        batch = " The batch stops here." if job.kind == "batch" else ""
        seen = blind = False
        while True:
            if self._exiting:
                raise _Exit()
            if job.stopped or self._late(job):
                if job.cut_at is None:
                    job.cut_at = self._mono()
                job.left = self._switch_off([pump["power_entity"]])  # a stop sent it: this reads it back
                return "stopped"
            dosing, changed = self._dosing(pump)
            now = self._mono()
            if dosing is None:
                blind = True
            elif dosing:
                seen = True
            elif seen:
                return self._verdict(job, pump, ml, flow, expected, pressed_at, seen, blind, batch)
            elif changed is not None and changed >= pressed_at:
                # It changed since the press and no read saw it dose: a dose too short to catch between
                # two reads, or a sensor back from unavailable. Only the recorder can tell, and it may
                # take a few seconds to have it.
                verdict = self._verdict(job, pump, ml, flow, expected, pressed_at, seen, blind, batch,
                                        final=now >= confirm_by)
                if verdict:
                    return verdict
            if not seen and now >= confirm_by:
                return self._verdict(job, pump, ml, flow, expected, pressed_at, seen, blind, batch)
            if now >= deadline:
                job.cut_at = now
                job.left = self._switch_off([pump["power_entity"]])
                held = (", but it still does not read off, so watering in this room is held, and the off "
                        "is sent again every 2 seconds, until it does. Switch it off by hand now."
                        if job.kind == "dose" else ", but it still does not read off: switch it off by hand now.")
                self._alert(
                    job.room.slug, "CS-801", "a dosing pump ran past its time and was switched off",
                    f"{pump['name']} was asked for {_fmt(ml)} mL, about {expected:.0f} seconds at its "
                    f"calibrated {_fmt(flow)} mL/s, and was still dosing after {deadline - pressed:.0f} "
                    f"seconds. Its power ({pump['power_entity']}) was switched off"
                    + (held if job.left else ".")
                    + " The tank may have more than was asked for. Check the pump, its calibration and "
                    f"its firmware before dosing again.{batch}",
                    _event(pump["id"], job.dose and job.dose["started_at"]),
                )
                return "ran past its time"
            self._wait(job, READ_S)

    def _verdict(self, job, pump, ml, flow, expected, pressed_at, seen, blind, batch, final=True):
        """How a dose the pump no longer reads dosing ended: "finished" only when a read saw it dose,
        or the recorder shows it dosing after the press; "not confirmed" (CS-802) when it read
        unavailable or unknown at any point after the press, or never dosing; "ended early" (CS-802)
        when it stopped in less than half its expected time. None: not in the recorder yet, and not
        `final`: asked again on the next read."""
        went, dead = self._recorded(pump, self._history(pump["dosing_entity"], pressed_at), pressed_at)
        if not (seen or went or blind or dead) and not final:
            return None
        elapsed = self._mono() - job.pressed
        event = _event(pump["id"], job.dose and job.dose["started_at"])
        if blind or dead:
            self._alert(job.room.slug, "CS-802", "a dose could not be confirmed",
                        f"{pump['name']} was asked for {_fmt(ml)} mL and its start was pressed, but "
                        f"{pump['dosing_entity']} read unavailable or unknown during the dose, so whether "
                        "it dosed, and how much, is not known (a pump that restarts mid-dose drops it). "
                        f"Check the pump and the tank before dosing again.{batch}", event)
            return "not confirmed"
        if not (seen or went):
            self._alert(job.room.slug, "CS-802", "a dose could not be confirmed",
                        f"{pump['name']} was asked for {_fmt(ml)} mL and its start was pressed, but "
                        f"{pump['dosing_entity']} never read dosing within {expected + 15:.0f} seconds, "
                        "so whether it dosed is not known. Check the pump is online and what its dosing "
                        f"sensor reports, and the tank, before dosing again.{batch}", event)
            return "not confirmed"
        if elapsed < expected / 2:
            self._alert(job.room.slug, "CS-802", "a dose ended early",
                        f"{pump['name']} was asked for {_fmt(ml)} mL, about {expected:.0f} seconds at its "
                        f"calibrated {_fmt(flow)} mL/s, but read not dosing again after {elapsed:.0f} "
                        f"seconds: it ended early, with about {_fmt(round(min(ml, elapsed * flow), 1))} mL "
                        "in. Check the pump, its calibration and its firmware, and the tank, before "
                        f"dosing again.{batch}", event)
            return "ended early"
        return "finished"

    def _recorded(self, pump, rows, since):
        """What the recorder holds for the pump after `since` -> (it went dosing, it read unavailable
        or unknown). The first row is the state it was already in at `since`, which counts only when
        it changed after it."""
        went = dead = False
        for index, row in enumerate(rows or []):
            try:
                state, stamp = row[0], row[1]
            except (TypeError, IndexError, KeyError):
                continue
            changed = _aware(stamp)
            if index == 0 and (changed is None or changed < since):
                continue
            if _dead(state):
                dead = True
            elif self._is_dosing(pump, state):
                went = True
        return went, dead

    # ------------------------------------------------------------------ a batch
    def _run_batch(self, room, config, request):
        """A batch, always settled: checked and recorded before anything moves; any end but finishing
        switches everything off and raises CS-806; whatever does not read off keeps the record and
        holds the rooms (and its hold stays on) until it does."""
        job = _Job(room, config, request, "batch")
        batch = config["batch"]
        try:
            why, plan = self._batch_check(job)
            held = None if why else self._held_rooms(room, batch)
        except Exception as e:  # nothing has moved: a refusal
            self._log(f"[{room.slug}] dosing: batch check error", repr(e))
            why = f"an error in the controller ({e!r})"
        if why:
            return self._settle(room, config, request, f"refused: {why}")
        job.started_at = self._now().isoformat()
        record = {"kind": "batch", "at": job.started_at, "request": request["id"],
                  "by": request.get("by"), "off": self._dosing_hardware(config),
                  "hold": batch.get("hold_entity"), "held": sorted(held), "doses": {}}
        if not self._record(job, record):
            return self._settle(room, config, request,
                                "refused: the batch could not be written to dosing_state.json", clear=True)
        with self._lock:
            self._job = job
        stuck, hold_left, told = [], [], True
        try:
            job.deadline = self._mono() + self._watchdog(batch, plan)
            with self._lock:
                self._live_of(room)["batch"] = {
                    "step": "idle", "pump": None, "started_at": job.started_at, "step_started_at": None,
                    "steps": [], "result": None, "ended_at": None}
            self._hold(job, held)
            self._close(job, held)
            self._fill(job)
            self._mix(job)
            self._pause(job, "premix", batch.get("premix_min"))
            self._doses(job, plan)
            self._pause(job, "postmix", batch.get("postmix_min"))
            warning, hold_left = self._finish(job)
            result = "finished" + (f"; {warning}" if warning else "")
        except _Exit:
            self._exit_off(job)
            raise
        except Exception as end:  # _Ended, or anything unforeseen: every way out cleans up the same
            if not isinstance(end, _Ended):
                self._log(f"[{room.slug}] dosing: batch error", repr(end))
            reason = str(end) if isinstance(end, _Ended) else f"an error in the controller ({end!r})"
            result = f"stopped: {job.step}: {reason}"
            try:
                stuck, hold_left = self._ended(job, reason)
            except Exception as e:  # never hold the rooms for good: whatever may be on is tried again
                self._log(f"[{room.slug}] dosing: batch cleanup error", repr(e))
                stuck, told = self._dosing_hardware(config), False
        finally:
            with self._lock:
                self._job = None
        with self._lock:
            view = self._live_of(room)["batch"]
            view.update(step="idle", pump=None, result=result, ended_at=self._now().isoformat())
        left = bool(stuck or hold_left)
        if left:
            title = ("a finished batch's hold did not release" if result.startswith("finished")
                     else "a batch was stopped")
            self._hold_stuck(room, stuck, batch.get("hold_entity"), held, "CS-806", title,
                             f"A batch that started {job.started_at} ended ({result}).",
                             "Check the tank before making another batch.", _event(job.started_at),
                             alerted=told)
        else:
            with self._lock:
                self._held.pop(room.slug, None)
        entry = {"kind": "batch", "at": job.started_at, "ended_at": view["ended_at"], "result": result,
                 "doses": dict(job.doses), "by": request.get("by")}
        self._settle(room, config, request, result, entry=entry, clear=not left, final=True)
        self._safely(self._send_draws)  # what its doses drew, now that nothing runs

    def _batch_check(self, job):
        """Why this batch must not start, else its doses: [(pump, ml, flow)] in recipe order, each
        recipe mL entity read now (it wins over the recipe's mL; 0 skips the pump)."""
        room, config = job.room, job.config
        batch = config["batch"]
        if self.c._hardware_fault_block(room):
            return "the room has a hardware fault latched", None
        hold = batch.get("hold_entity")
        if hold:
            state = self._state(hold)
            if _dead(state):
                return f"{hold} can't be read", None
            if state.strip().lower() == "on":
                return f"{hold} is on already: something else is dosing", None
        if batch.get("fill_valve") and self._full(batch) is None:
            return "the tank's full sensor can't be read", None
        if (batch.get("mix_pump") and float(batch.get("mix_min_w") or 0) > 0
                and not batch.get("mix_power_sensor")):
            return "the mix pump has a minimum power but no power sensor to read it", None
        pumps = {p["id"]: p for p in config["pumps"]}
        plan = []
        for item in batch.get("recipe") or []:
            pump = pumps.get(item.get("pump"))
            if pump is None:
                return f"the recipe doses {item.get('pump')}, which is not set up", None
            ml = item.get("ml") or 0
            if item.get("ml_entity"):  # it wins over the fixed mL, and is never replaced by it
                ml = self._number(item["ml_entity"])
                if ml is None:
                    return f"the recipe amount for {pump['name']} can't be read", None
            if ml <= 0:
                continue
            if ml > float(pump.get("max_ml") or 0):
                return f"{_fmt(ml)} mL of {pump['name']} is more than its {_fmt(pump['max_ml'])} mL", None
            why = self._uncalibrated(pump)
            if why:
                return why, None
            flow = self._number(pump["flow_entity"])
            if ml / flow > MAX_DOSE_S:
                return self._too_long(pump, ml, flow), None
            plan.append((pump, ml, flow))
        return None, plan

    def _held_rooms(self, room, batch):
        """The rooms a batch holds: its own, every room whose pump, main line or valves are among the
        batch's fill valve, mix pump, mix valves or switches to close, and every room that shares its
        pump or main line (closing them would cut that room's shot)."""
        hardware = {batch.get("fill_valve"), batch.get("mix_pump"), *(batch.get("mix_valves") or []),
                    *(batch.get("close_entities") or [])} - {None, ""}
        line = {room.hw.get("pump"), room.hw.get("mainline")} - {None, ""}
        held = {room.slug}
        for other in list(self.c.rooms):
            own = {other.hw.get("pump"), other.hw.get("mainline")} - {None, ""}
            valves = set((other.hw.get("valves") or {}).values()) - {None, ""}
            if (own | valves) & hardware or own & line:
                held.add(other.slug)
        return held

    @staticmethod
    def _watchdog(batch, plan):
        """The hold's wait for a shot + fill timeout + premix + postmix + every dose's capped deadline
        + 10 min, in seconds."""
        minutes = (HOLD_WAIT_S / 60 + float(batch.get("fill_timeout_min") or 20)
                   + float(batch.get("premix_min") or 0) + float(batch.get("postmix_min") or 0) + 10)
        return minutes * 60 + sum(min(ml / flow * 1.25 + 20, DOSE_CAP_S) for _pump, ml, flow in plan)

    def _hold(self, job, held):
        self._begin(job, "hold")
        with self.c._shot_lock:  # the lock a shot starts under: see the module note
            with self._lock:
                self._held[job.room.slug] = set(held)
        hold = job.config["batch"].get("hold_entity")
        if hold:
            self._on(job, hold)
            if self._confirm([hold], "on"):
                raise _Ended(f"{hold} did not read on")
        waited = self._mono()
        while self.c._shot_running(held):
            self._check(job)
            if self._mono() - waited >= HOLD_WAIT_S:
                raise _Ended("a shot was still running after 10 minutes")
            self._wait(job, POLL_S)
        self._done(job)

    def _close(self, job, held):
        self._begin(job, "close")
        targets = []
        for other in list(self.c.rooms):
            if other.slug in held:
                hw = other.hw
                targets += [v for _zone, v in sorted((hw.get("valves") or {}).items())]
                targets += [hw.get("mainline"), hw.get("pump")]  # valves first, then back up the line
        stuck = self._switch_off(targets + list(job.config["batch"].get("close_entities") or []))
        if stuck:
            raise _Ended(f"{', '.join(stuck)} did not read off")
        self._done(job)

    def _fill(self, job):
        batch = job.config["batch"]
        valve = batch.get("fill_valve")
        if not valve:
            return self._skip(job, "fill", "no fill valve: the tank is filled already")
        full = self._full(batch)
        if full:
            return self._skip(job, "fill", "the tank reads full already")
        self._begin(job, "fill")
        sensor = batch.get("full_entity")
        if full is None:
            self._fill_alert(job, "the batch tank could not be filled",
                             f"{sensor} can't be read, so the fill valve was not opened.")
            raise _Ended("the tank's full sensor can't be read")
        minutes = float(batch.get("fill_timeout_min") or 20)
        self._on(job, valve)
        began = self._mono()
        if self._confirm([valve], "on", FILL_OPEN_S):
            stuck = self._switch_off([valve])
            self._fill_alert(job, "the batch tank could not be filled",
                             f"the fill valve ({valve}) did not open: it did not read on within "
                             f"{FILL_OPEN_S:.0f} seconds. It was switched off"
                             + (", but it still does not read off: close it by hand now." if stuck else "."))
            raise _Ended("the fill valve did not open")
        filled, blind, why = False, None, None
        while True:
            state = self._full(batch)
            now = self._mono()
            if state:
                filled = True
                break
            if state is None:
                blind = now if blind is None else blind
                if now - blind >= FULL_BLIND_S:
                    why = "the full sensor stopped reporting"
                    break
            else:
                blind = None
            if now - began >= minutes * 60:
                why = f"the tank did not read full within {minutes:g} min"
                break
            self._check(job)
            self._wait(job, POLL_S)
        stuck = self._switch_off([valve])  # always closed, and read back
        closed = ("It was switched off, but it still does not read off: close it by hand now."
                  if stuck else "The fill valve was switched off.")
        if why == "the full sensor stopped reporting":
            self._fill_alert(job, "the batch tank could not be filled",
                             f"the full sensor stopped reporting: {sensor} read nothing usable for "
                             f"{FULL_BLIND_S:.0f} seconds while the fill valve ({valve}) was open. {closed}")
            raise _Ended(why)
        if not filled:
            self._fill_alert(job, "the batch tank did not fill in time",
                             f"the fill valve ({valve}) was open for {minutes:g} minutes and {sensor} "
                             f"never read {batch.get('full_state') or 'on'}. {closed}")
            raise _Ended(why)
        if stuck:
            raise _Ended(f"{valve} did not read off after filling")
        self._done(job)

    def _fill_alert(self, job, title, what):
        self._alert(job.room.slug, "CS-804", title,
                    f"The batch could not fill the tank: {what} The batch stops here. Check the water "
                    "supply, the fill valve and the full sensor.", _event(job.started_at))

    def _mix(self, job):
        batch = job.config["batch"]
        pump = batch.get("mix_pump")
        if not pump:
            return self._skip(job, "mix", "no mix pump")
        self._begin(job, "mix")
        valves = list(batch.get("mix_valves") or [])
        for valve in valves:
            self._on(job, valve)
        closed = self._confirm(valves, "on")
        if closed:  # never run the pump against a closed valve
            raise _Ended(f"{', '.join(closed)} did not open")
        self._on(job, pump)
        if self._confirm([pump], "on"):
            self._mix_alert(job, pump, f"The mix pump ({pump}) was switched on, but does not read on")
            raise _Ended(f"the mix pump ({pump}) did not read on")
        watts, sensor = float(batch.get("mix_min_w") or 0), batch.get("mix_power_sensor")
        if watts > 0 and sensor:
            began = self._mono()
            while True:
                drawn = self._number(sensor)
                if drawn is not None and drawn >= watts:
                    break
                if self._mono() - began >= MIX_POWER_S:
                    self._mix_alert(job, pump, f"The mix pump ({pump}) was switched on, but {sensor} did not "
                                    f"read {watts:g} W within {MIX_POWER_S:.0f} seconds (it reads "
                                    f"{self._state(sensor)})")
                    raise _Ended(f"the mix pump did not draw {watts:g} W within {MIX_POWER_S:.0f} s")
                self._check(job)
                self._wait(job, READ_S)
        self._done(job)

    def _mix_alert(self, job, pump, what):
        self._send_off(pump)  # before the alert, whose push can take a while; the batch's end reads it back
        self._alert(job.room.slug, "CS-805", "the mixing pump did not start",
                    f"{what}. The batch stops here and the mix pump and valves are switched off. Check "
                    "the pump, its power sensor, and that the mix valves open.", _event(job.started_at))

    def _pause(self, job, step, minutes):
        minutes = float(minutes or 0)
        if minutes <= 0:
            return self._skip(job, step, "0 min")
        self._begin(job, step)
        end = self._mono() + minutes * 60
        while self._mono() < end:
            self._check(job)
            self._wait(job, max(0.0, min(POLL_S, end - self._mono())))
        self._done(job)

    def _doses(self, job, plan):
        if not plan:
            return self._skip(job, "dose", "nothing to dose")
        self._begin(job, "dose")
        for pump, ml, _flow in plan:
            with self._lock:
                self._live_of(job.room)["batch"]["pump"] = pump["id"]
            result = self._dose(job, pump, ml)
            with self._lock:
                self._live_of(job.room)["batch"]["pump"] = None
            if result != "finished":
                self._check(job)  # a stop or the watchdog says so itself
                raise _Ended(f"{pump['name']}: {result}")
        self._done(job)

    def _finish(self, job):
        """The mix pump off and its valves closed (read back), the fill stamped, the hold released
        (read back) -> (a warning for the result or None, the hold when it does not read off)."""
        batch = job.config["batch"]
        self._begin(job, "finish")
        stuck = self._switch_off([batch.get("mix_pump"), *(batch.get("mix_valves") or [])])
        if stuck:
            raise _Ended(f"{', '.join(stuck)} did not read off")
        warning = None
        stamp = batch.get("filled_at_entity")
        if stamp and not self._call("input_datetime", "set_datetime", entity_id=stamp,
                                    timestamp=self._now().timestamp()):
            warning = f"{stamp} could not be stamped"
            self._alert(job.room.slug, "CS-806", "a finished batch could not be stamped",
                        f"The batch finished, but its end time could not be stamped on {stamp}. The "
                        "stock tanks count batches by it, so this one is not taken off the stock tanks "
                        "that are not linked to a dosing pump: record it by hand (Stock tanks, Record a "
                        f"batch), and check {stamp}.", _event("stamp", job.started_at))
        hold = batch.get("hold_entity")
        hold_left = self._switch_off([hold]) if hold else []
        if hold_left:
            self._alert(job.room.slug, "CS-806", "a finished batch's hold did not release",
                        f"The batch finished, but its hold ({hold}) does not read off, so the rooms it "
                        "held stay held, and the off is sent again every 2 seconds, until it does. "
                        f"Check {hold}.", _event(job.started_at))
        self._done(job)
        return warning, hold_left

    def _ended(self, job, reason):
        """Any end but finishing: every dosing pump's power, the fill valve, the mix pump and the mix
        valves off and read back, and only once they all read off, the hold; then CS-806
        -> (what does not read off, the hold when it does not)."""
        batch = job.config["batch"]
        with self._lock:
            view = self._live_of(job.room)["batch"]
            if view["steps"] and view["steps"][-1]["state"] == "running":
                view["steps"][-1].update(state="failed", note=reason)
        stuck = self._switch_off(self._dosing_hardware(job.config))
        hold = batch.get("hold_entity")
        hold_left = self._switch_off([hold]) if hold and not stuck else []
        names = {pump["id"]: pump["name"] for pump in job.config["pumps"]}
        dosed = ", ".join(f"{_fmt(ml)} mL of {names.get(p, p)}" for p, ml in job.doses.items()) or "nothing"
        if stuck:
            after = (f", but {_still(stuck)}, so the rooms the batch held stay held"
                     + (", and its hold stays on," if hold else "")
                     + " until they do: the off is sent again every 2 seconds.")
        elif hold_left:
            after = (f", but its hold ({hold}) does not read off, so the rooms the batch held stay held "
                     "until it does.")
        else:
            after = (" and the hold released" if hold else "") + ", and the rooms it held water again."
        self._alert(
            job.room.slug, "CS-806", "a batch was stopped",
            f"The batch stopped in its {job.step} step: {reason}. Every dosing pump's power, the fill "
            f"valve, the mix pump and the mix valves were switched off{after}"
            f" Dosed before it stopped: {dosed}. Check the tank before making another batch.",
            _event(job.started_at),
        )
        self._log(f"[{job.room.slug}] dosing: batch stopped in {job.step}: {reason}")
        return stuck, hold_left

    def _check(self, job, catch=False):
        """End the batch now if it must: the app stopping, a stop request (read now when `catch`,
        rather than at the next pass), or its watchdog."""
        if self._exiting:
            raise _Exit()
        if catch:
            self._catch_stop(job)
        if job.stopped:
            raise _Ended(self._stop_reason(job))
        if self._late(job):
            raise _Ended("it ran past its watchdog")

    def _catch_stop(self, job):
        """A stop for the job's room, read now: before every switch-on and at every step change."""
        config = self._config(job.room)
        request = config.get("request") if config else None
        if not (isinstance(request, dict) and request.get("action") == "stop"
                and isinstance(request.get("id"), str)):
            return
        with self._lock:
            handled = self._block(job.room)["handled"]
        if request["id"] != handled:
            self._take(job.room, config, request, job)

    def _on(self, job, entity, service="turn_on"):
        """Every switch-on, and every start press, goes through here. A stop is read first (and the
        watchdog checked); then, with the gate held across the call so the way out (exit) never
        overtakes it, the exit and stop flags are checked under the runner lock immediately before
        the call."""
        self._check(job, catch=True)
        with self._gate:
            with self._lock:
                if self._exiting:
                    raise _Exit()
                if job.stopped:
                    raise _Ended(self._stop_reason(job))
            return self._call(_domain(entity), service, entity_id=entity, timeout=ON_TIMEOUT_S)

    def _late(self, job):
        return job.deadline is not None and self._mono() > job.deadline

    @staticmethod
    def _stop_reason(job):
        return "stop requested" + (f" by {job.stopped_by}" if job.stopped_by else "")

    def _exit_off(self, job):
        """The thread's own way out of a dose or batch (the app is stopping): its hardware off at
        once, each with a QUICK_S timeout and no read-back. The record stays for the next start."""
        if job.kind == "dose":
            entities = [job.pump["power_entity"]] if job.pump else []
        else:
            entities = self._dosing_hardware(job.config)
        for entity in entities:
            try:
                self._send_off(entity)
            except Exception as e:
                self._log(f"[{job.room.slug}] dosing: could not switch {entity} off on the way out", repr(e))

    # ------------------------------------------------------------------ what does not read off
    def _hold_stuck(self, room, entities, hold, held, code, title, intro, advice, event, alerted):
        """What a dose or batch left not reading off: its rooms held, and _release_stuck switches it
        off again every pass (its hold, if any, only after the rest reads off) and repeats `code`
        every REALERT_S until it all reads off. `alerted`: the first alert went out already (if not,
        the first pass that hears Home Assistant raises it, and the release says so either way)."""
        with self._lock:
            self._held[room.slug] = set(held or {room.slug})
            self._stuck[room.slug] = self._entry(entities, hold, held or {room.slug}, code, title, event,
                                                 intro, advice, alerted=self._mono() if alerted else None,
                                                 announce=not alerted)

    @staticmethod
    def _entry(entities, hold, held, code, title, event, intro, advice, *, alerted, announce=False,
               sent=True):
        entities = [e for e in dict.fromkeys(entities) if e]
        return {"entities": entities, "hold": hold, "held": set(held),
                "left": entities or ([hold] if hold else []), "code": code, "title": title,
                "event": event, "intro": intro, "advice": advice, "alerted": alerted,
                "announce": announce, "sent": sent, "hold_sent": not entities and hold is not None and sent}

    def _recover_record(self, slug):
        """A record a start found (the lock held): its rooms held, its hardware left to _release_stuck,
        its history written once, its volume number queued to be put back."""
        block = self._block(slug)
        record = dict(block["inflight"])
        kind = record.get("kind")
        off = [e for e in record.get("off") or [] if isinstance(e, str) and "." in e]
        hold = record.get("hold") if kind == "batch" and isinstance(record.get("hold"), str) else None
        held = {s for s in record.get("held") or [] if isinstance(s, str)} | {slug}
        at = record.get("at")
        if kind in ("dose", "batch"):
            intro = (f"A {kind} that started {at} was still running when the controller app stopped, so "
                     "it did not finish, and the controller never resumes one. Its dosing pumps' power, "
                     "the fill valve, the mix pump and the mix valves were switched off"
                     + (", and its hold is released once they read off." if hold else "."))
            advice = ("Check the tank: what was dosed before the stop is in it; dose the rest by hand or "
                      "make a fresh batch.")
        else:  # swept after a corrupt dosing_state.json
            intro = ("dosing_state.json could not be read, so this room's dosing pumps' power, fill "
                     "valve, mix pump and mix valves were switched off.")
            advice = "Check the batch tank before dosing again."
        self._held[slug] = held
        self._stuck[slug] = self._entry(off, hold, held, "CS-803", "a dose or batch was interrupted by a restart",
                                        _event("restart", at), intro, advice, alerted=None,
                                        announce=kind in ("dose", "batch"), sent=False)
        if kind in ("dose", "batch") and not record.get("recovered"):
            self._add_history(block, {
                "kind": kind, "at": at, "ended_at": self._now().isoformat(),
                "result": "interrupted by a restart", "doses": record.get("doses") or {},
                "by": record.get("by"),
            })
            block["inflight"] = {**record, "recovered": True}  # its history is written once
        dose = record.get("dose")
        if isinstance(dose, dict) and dose.get("old_volume") is not None and dose.get("volume_entity"):
            if not any((r.get("pump"), r.get("at")) == (dose.get("pump"), dose.get("at"))
                       for r in block["restores"]):
                block["restores"].append(dict(dose))
        self._write()
        self._log(f"[{slug}] dosing: a {kind or 'dose or batch'} was recorded as running: switching it off")

    def _sweep_rooms(self):
        """After a corrupt dosing_state.json: each room with dosing set up gets a record of its CURRENT
        dosing hardware, recovered as a restart's (held and switched off until it reads off), once its
        setup can be read; a room with no dosing has nothing to do."""
        with self._lock:
            pending = set(self._sweep)
        if not pending:
            return
        for room in list(self.c.rooms):
            if room.slug not in pending:
                continue
            config = self._config(room)
            if config is False:
                continue  # can't be read yet: on the next pass
            with self._lock:
                self._sweep.discard(room.slug)
                hardware = self._dosing_hardware(config) if config else []
                if not hardware:
                    continue
                block = self._block(room)
                block["inflight"] = {"kind": "sweep", "at": self._now().isoformat(), "off": hardware,
                                     "held": [room.slug]}
                self._recover_record(room.slug)
        with self._lock:
            self._sweep &= {room.slug for room in list(self.c.rooms)}

    def _release_stuck(self):
        """Whatever a dose or batch left not reading off, or a start found recorded, is read on every
        pass and sent off again until it all reads off; unavailable, unknown or missing is never off.
        A batch's hold goes off only then; once that reads off too, the rooms water again, the record
        is cleared, and whoever was told is told so. Its alert is repeated every REALERT_S."""
        with self._lock:
            entries = {slug: deepcopy(entry) for slug, entry in self._stuck.items()}
        for slug, entry in entries.items():
            if not entry["sent"]:  # just found: every part is told off first, whatever it reads
                for entity in entry["entities"]:
                    self._send_off(entity)
                self._mark(slug, sent=True)
                continue
            left, answered = self._still_on(entry["entities"])
            if not left and entry["hold"]:
                if not entry["hold_sent"]:  # the rest reads off: now the hold, read on the next pass
                    self._send_off(entry["hold"])
                    self._mark(slug, hold_sent=True, left=[entry["hold"]])
                    continue
                left, heard = self._still_on([entry["hold"]])
                answered = answered or heard
            if not left:
                self._release(slug, entry)
                continue
            now = self._mono()
            due = (entry["alerted"] is None and answered) or (
                entry["alerted"] is not None and now - entry["alerted"] >= REALERT_S)
            with self._lock:
                live = self._stuck.get(slug)
                if live is None:
                    continue  # released meanwhile (a stop)
                live["left"] = left
                if due:
                    live["alerted"] = now
            if due:
                self._alert(slug, entry["code"], entry["title"], self._stuck_message(entry, left),
                            entry["event"])

    def _mark(self, slug, **fields):
        with self._lock:
            if slug in self._stuck:
                self._stuck[slug].update(fields)

    def _still_on(self, entities):
        """-> (the ones that do not read off, each sent off again; whether Home Assistant answered)."""
        left, answered = [], False
        for entity in entities:
            state = self._state(entity, quick=True)
            answered = answered or state is not None
            if state != "off":
                left.append(entity)
                answered = self._send_off(entity) or answered
        return left, answered

    def _release(self, slug, entry):
        with self._lock:
            if self._stuck.pop(slug, None) is None:
                return
            self._held.pop(slug, None)
            self._block(slug)["inflight"] = None
            self._write()
        self._log(f"[{slug}] dosing: {', '.join(entry['entities'] + [h for h in [entry['hold']] if h]) or 'all of it'}"
                  " reads off now; the hold is released")
        if entry["announce"] or entry["alerted"] is not None:
            self._alert(slug, entry["code"], entry["title"], self._stuck_message(entry, []), entry["event"])

    @staticmethod
    def _stuck_message(entry, left):
        if left:
            tail = (f"{_still(left)}, so watering stays held in the rooms it holds, and the off is sent "
                    "again every 2 seconds until it reads off. Check it, and switch it off by hand if "
                    "it is still running.")
        else:
            tail = ("Everything now reads off" + ("; the hold was released" if entry["hold"] else "")
                    + ", so watering carries on.")
        return f"{entry['intro']} {tail} {entry['advice']}"

    # ------------------------------------------------------------------ alerts
    def _alert(self, slug, code, title, message, event):
        """An alert for one event (docs/DOSING.md, Alerts), kept in dosing_state.json until Home
        Assistant has it: tried now, and again with the chores until it is created. A newer one for
        the same event replaces one still waiting."""
        item = {"slug": slug, "code": code, "title": title, "message": message, "event": event}
        with self._lock:
            outbox = [a for a in self._doc["outbox"]
                      if (a.get("slug"), a.get("code"), a.get("event")) != (slug, code, event)]
            self._doc["outbox"] = [*outbox, item][-OUTBOX:]
            self._write()
        self._send_alerts()

    def _send_alerts(self):
        with self._lock:
            pending = [dict(a) for a in self._doc["outbox"] if isinstance(a, dict)]
        for item in pending:
            room = next((r for r in list(self.c.rooms) if r.slug == item.get("slug")), None)
            try:
                created = self._deliver(room, item.get("code"), item.get("title"), item.get("message"),
                                        item.get("event"))
            except Exception as e:
                self._log("dosing: alert error", repr(e))
                created = False
            if not created:
                continue
            with self._lock:
                self._doc["outbox"] = [a for a in self._doc["outbox"] if a != item]
                self._write()

    # ------------------------------------------------------------------ the batch's steps, shown
    def _begin(self, job, step):
        job.step = step
        now = self._now().isoformat()
        with self._lock:
            view = self._live_of(job.room)["batch"]
            view.update(step=step, step_started_at=now)
            view["steps"].append({"step": step, "state": "running", "at": now, "note": None})
        self._show(job.room, job.config)
        self._check(job, catch=True)  # a stop is looked for at every step

    def _done(self, job):
        with self._lock:
            self._live_of(job.room)["batch"]["steps"][-1]["state"] = "done"
        self._show(job.room, job.config)

    def _skip(self, job, step, note):
        job.step = step
        with self._lock:
            self._live_of(job.room)["batch"]["steps"].append(
                {"step": step, "state": "skipped", "at": self._now().isoformat(), "note": note})
        self._show(job.room, job.config)
        self._check(job, catch=True)

    # ------------------------------------------------------------------ status
    def _live_of(self, room):
        with self._lock:
            return self._live.setdefault(room.slug, {
                "readings": {}, "refreshed": None, "revision": None, "published": None,
                "published_at": None,
                "batch": {"step": "idle", "pump": None, "started_at": None, "step_started_at": None,
                          "steps": [], "result": None, "ended_at": None},
            })

    def _show(self, room, config):
        """Publish sensor.crop_steering_<prefix>dosing when it changed, and at least once a minute,
        with `updated_at` the time of this publish (the page tells a stale controller by it). Nothing
        is published for a room whose integration has no dosing_config (from before dosing)."""
        live = self._live_of(room)
        if config is None and live["published"] is None:
            return
        if config:
            self._refresh(config, live)
        state, attributes = self._status(room, config, live)
        now = self._mono()
        if live["published"] == (state, attributes) and now - live["published_at"] < REPUBLISH_S:
            return
        self._publish(f"sensor.crop_steering_{room.prefix}dosing", state,
                      {**attributes, "updated_at": self._now().isoformat()})
        with self._lock:
            live["published"], live["published_at"] = (state, deepcopy(attributes)), now

    def _refresh(self, config, live):
        """Each pump's flow and state, read every REFRESH_S, and when the setup changes while nothing
        runs (a dose or batch keeps the chores out of its way), with a QUICK_S timeout."""
        now = self._mono()
        fresh = live["refreshed"] is not None and now - live["refreshed"] < REFRESH_S
        if fresh and (self._job is not None or live["revision"] == config["revision"]):
            return
        readings = {}
        for pump in config["pumps"]:
            dosing = self._dosing(pump, quick=True)[0]
            readings[pump["id"]] = {
                "flow": self._number(pump["flow_entity"], quick=True),
                "state": "unavailable" if dosing is None else "dosing" if dosing else "idle",
            }
        with self._lock:
            live.update(readings=readings, refreshed=now, revision=config["revision"])

    def _status(self, room, config, live):
        with self._lock:
            block = deepcopy(self._block(room))
            job = self._job if self._job is not None and self._job.room.slug == room.slug else None
            batch = deepcopy(live["batch"])
            readings = dict(live["readings"])
        pumps = {}
        for pump in config["pumps"] if config else []:
            reading = readings.get(pump["id"], {})
            dose = job.dose if job is not None and job.dose and job.dose["pump"] == pump["id"] else None
            pumps[pump["id"]] = {
                "state": "dosing" if dose else reading.get("state", "idle"),
                "flow_ml_s": reading.get("flow"),
                "target_ml": dose["ml"] if dose else None,
                "started_at": dose["started_at"] if dose else None,
                "expected_s": dose["expected_s"] if dose else None,
                "last": block["last"].get(pump["id"]),
            }
        state = ("unavailable" if not config else "idle" if job is None
                 else "batch" if job.kind == "batch" else "dosing")
        return state, {
            "pumps": pumps,
            "batch": batch,
            "handled": block["handled"],
            "handled_result": block["handled_result"],
            "history": block["history"],
            "friendly_name": "Dosing (controller)",
        }

    # ------------------------------------------------------------------ reading Home Assistant
    def _config(self, room):
        """The room's dosing setup as the integration publishes it: None with no dosing_config at all
        (an integration from before dosing), False when it can't be read (never acted on), else
        {"revision", "pumps", "batch", "request"}."""
        state, attributes, _updated = self._get(f"sensor.crop_steering_{room.prefix}dosing_config")
        if state is None:
            return None
        if str(state).strip().lower() in DEAD or not isinstance(attributes, dict):
            return False
        pumps, batch = attributes.get("pumps"), attributes.get("batch")
        if not (isinstance(pumps, list) and all(self._pump_readable(p) for p in pumps)
                and isinstance(batch, dict) and self._batch_readable(batch)):
            return False
        return {"revision": state, "pumps": pumps, "batch": batch, "request": attributes.get("request")}

    @staticmethod
    def _pump_readable(pump):
        return isinstance(pump, dict) and all(
            isinstance(pump.get(key), str) and pump[key]
            for key in ("id", "name", "volume_entity", "start_entity", "dosing_entity", "power_entity",
                        "flow_entity")
        ) and isinstance(pump.get("max_ml"), (int, float))

    @staticmethod
    def _batch_readable(batch):
        lists = all(isinstance(batch.get(key) or [], list)
                    for key in ("mix_valves", "close_entities", "recipe"))
        return lists and all(isinstance(item, dict) for item in batch.get("recipe") or [])

    def _fetch(self, entity, quick=False):
        return self._get(entity, timeout=QUICK_S) if quick else self._get(entity)

    def _state(self, entity, quick=False):
        if not entity:
            return None
        state = self._fetch(entity, quick)[0]
        return None if state is None else str(state)

    def _number(self, entity, quick=False):
        try:
            value = float(self._state(entity, quick))
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) else None

    def _dosing(self, pump, quick=False):
        """(True / False / None when it reads nothing usable, when its state last changed)."""
        read = self._fetch(pump["dosing_entity"], quick)
        state, changed = read[0], _aware(getattr(read, "last_changed", None))
        if _dead(state):
            return None, changed
        return self._is_dosing(pump, state), changed

    @staticmethod
    def _is_dosing(pump, state):
        if pump["dosing_entity"].startswith("binary_sensor."):
            return str(state).strip().lower() == "on"
        return str(state).startswith(pump.get("dosing_prefix") or "Dosing")

    def _full(self, batch):
        """Whether the tank reads full: True / False, or None when its full entity reads nothing."""
        state = self._state(batch.get("full_entity"))
        if _dead(state):
            return None
        return state.strip().lower() == str(batch.get("full_state") or "on").strip().lower()

    def _age(self, request):
        at = _aware(request.get("at"))
        return (self._now() - at).total_seconds() if at else None

    @staticmethod
    def _dosing_hardware(config):
        """What a stop, an interrupted batch or a restart switches off: every pump's power, then the
        fill valve, the mix pump and the mix valves."""
        batch = config["batch"]
        return [e for e in (*(p["power_entity"] for p in config["pumps"]), batch.get("fill_valve"),
                            batch.get("mix_pump"), *(batch.get("mix_valves") or [])) if e]

    # ------------------------------------------------------------------ switching, with read-back
    def _switch_off(self, entities):
        """Switch these off, read them back, re-send once to what does not read off -> whatever still
        does not (empty when every one reads off). The off is sent whatever a switch reads: a stale
        OFF must never be the reason a pump or valve was not told."""
        entities = [e for e in dict.fromkeys(entities) if e]
        for e in entities:
            self._call(_domain(e), "turn_off", entity_id=e)
        stuck = self._confirm(entities, "off")
        for e in stuck:
            self._call(_domain(e), "turn_off", entity_id=e)
        return self._confirm(stuck, "off")

    def _send_off(self, entity):
        """An off with a QUICK_S timeout and no read-back -> whether Home Assistant took it."""
        return self._call(_domain(entity), "turn_off", entity_id=entity, timeout=QUICK_S)

    def _confirm(self, entities, want, timeout=None):
        """Read these back until each reads `want`: first at 1 s, then every 0.5 s up to `timeout`
        (CONFIRM_TIMEOUT_S) -> the ones that don't."""
        if not entities:
            return []
        deadline = self._mono() + (CONFIRM_TIMEOUT_S if timeout is None else timeout)
        self._sleep(CONFIRM_FIRST_S)
        while True:
            left = [e for e in entities if self._state(e) != want]
            if not left or self._mono() >= deadline:
                return left
            self._sleep(CONFIRM_POLL_S)

    def _confirm_value(self, entity, value):
        deadline = self._mono() + CONFIRM_TIMEOUT_S
        self._sleep(CONFIRM_FIRST_S)
        while True:
            read = self._number(entity)
            if read is not None and abs(read - value) <= VOLUME_TOLERANCE_ML:
                return True
            if self._mono() >= deadline:
                return False
            self._sleep(CONFIRM_POLL_S)

    def _wait(self, job, seconds):
        """Sleep a moment, answering every room's requests on the way (a stop among them)."""
        self.beat = self._mono()
        if self._polled is None or self._mono() - self._polled >= POLL_S:
            self.poll(busy=job)
        self._sleep(max(0.0, seconds))

    # ------------------------------------------------------------------ dosing_state.json
    def _read(self):
        """The saved document. One that can't be read is kept as dosing_state.json.bad and the start
        sweeps every room's dosing hardware off (recover): what was running is not known."""
        try:
            with open(self.path, encoding="utf-8") as fh:
                doc = json.load(fh)
            if not isinstance(doc, dict) or not isinstance(doc.get("rooms", {}), dict):
                raise ValueError("not a dosing_state document")
        except FileNotFoundError:
            doc = {}
        except (OSError, ValueError) as e:
            self._log("dosing: dosing_state.json can't be read; kept as dosing_state.json.bad:", e)
            try:
                os.replace(self.path, self.path + ".bad")
            except OSError as moved:
                self._log("dosing: it could not be kept:", moved)
            self._corrupt = True
            doc = {}
        rooms, outbox = doc.get("rooms") or {}, doc.get("outbox")
        return {"rooms": {str(k): v for k, v in rooms.items() if isinstance(v, dict)},
                "outbox": [a for a in outbox if isinstance(a, dict)] if isinstance(outbox, list) else []}

    def _write(self):
        """Atomically (tmp + os.replace), the file and its directory synced so it survives a power
        cut; False when it could not be saved."""
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._doc, fh)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
            self._sync_dir()
            return True
        except (OSError, TypeError, ValueError) as e:
            self._log("dosing: dosing_state.json could not be saved:", e)
            return False

    def _sync_dir(self):
        """The rename itself is only durable once the directory is synced (POSIX). A system that can't
        open a directory (Windows) has nothing to sync."""
        try:
            fd = os.open(os.path.dirname(os.path.abspath(self.path)), os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)

    def _block(self, room):
        """One room's saved part (the caller holds the lock): the last request handled and its result,
        the dose or batch in flight, each pump's last dose, the history, the stock draws not yet
        delivered and the volume numbers still to put back."""
        slug = getattr(room, "slug", room)
        block = self._doc["rooms"].get(slug)
        if not isinstance(block, dict):
            block = self._doc["rooms"][slug] = {}
        for key, default in (("handled", None), ("handled_result", None), ("inflight", None)):
            block.setdefault(key, default)
        for key in ("history", "draws", "restores"):
            if not isinstance(block.get(key), list):
                block[key] = []
        if not isinstance(block.get("last"), dict):
            block["last"] = {}
        return block

    @staticmethod
    def _add_history(block, entry):
        block["history"] = [entry, *block["history"]][:HISTORY]

    def _record(self, job, fields, merge=False):
        """What is about to move, saved before it moves. A new record also takes the job's request, in
        the same write; one added to (a batch's next dose) leaves alone any request answered since."""
        with self._lock:
            block = self._block(job.room)
            record = dict(block["inflight"] or {}) if merge else {}
            record.update(fields)
            block["inflight"] = record
            if not merge:
                block["handled"], block["handled_result"] = job.request["id"], _RUNNING[job.kind]
            return self._write()

    def _settle(self, room, config, request, result, entry=None, clear=False, final=False):
        """A request handled: its id and result saved (and the record of what ran cleared) and shown.
        `final`: the end of the dose or batch it started, which leaves a request handled since (a stop,
        a refusal) as the one shown, so none is ever taken twice."""
        with self._lock:
            block = self._block(room)
            if not final or block["handled"] == request["id"]:
                block["handled"], block["handled_result"] = request["id"], result
            if clear:
                block["inflight"] = None
            if entry is not None:
                self._add_history(block, entry)
            self._write()
        self._log(f"[{room.slug}] dosing: {request.get('action')} request: {result}")
        self._show(room, config)
        return result
