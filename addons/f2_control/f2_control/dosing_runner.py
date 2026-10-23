"""Batch-tank dosing for every room, as a step machine on the controller's main loop (docs/DOSING.md).

The integration keeps each room's dosing setup and its one request, and publishes them as
sensor.crop_steering_<prefix>dosing_config. The main loop wakes whenever dosing is due (step): it
reads that every 2 s and takes each request once, and runs the dose or batch it took on to its next
wait (a read of the pump, the fill, the mix, a pause), so nothing here sleeps through a wait. A dose sets a pump's volume number and presses its start: the pump's own firmware runs the
motor for that volume and switches it off. A batch holds the watering it could disturb, fills the
tank, mixes it, doses the recipe in order and stamps the fill. Only a timed run (a prime or a pump's
calibration, _run_timed) switches a dosing motor's power on, for its seconds, read back on and off; otherwise
switching one off (a stop, a dose past its time) is the only thing done to its power.
What each room is doing is published as sensor.crop_steering_<prefix>dosing.

Whatever could be left running is written to dosing_state.json before anything moves. Whatever
does not read off when a dose or a batch ends, and whatever a start finds recorded, holds its rooms'
watering and is switched off again on every pass until all of it reads off (_release_stuck). The
irrigation loop asks holds() before every shot. A batch sets its hold under the lock a shot starts
under (Controller._shot_lock): a shot either started before it, and the batch waits for that shot to
end, or never starts. Every switch-on goes through _on; a stop signal that lands in the middle of one
waits for it to land (defer_exit), so the way out (exit) never overtakes it.

A finished batch's tank is read MIX_SETTLE_S after its mix stops (_check_mixes): the room's feed EC and pH
probes against its irrigation EC and pH bands. A reading off its band, or a probe that can't be read, raises
CS-808, leaves the batch not marked good and refuses a batch an automation asks for, never watering.

pH auto-correct (opt-in per room, _ph_tick): while the room's switch is on, the tank's pH probe is read once
a minute; a tank that reads off its pH band, plausibly and steadily, for 5 minutes gets a correction (_run_correct):
held and mixed as a batch is, then a few small doses through the pump with that pH role, each mixed and read again.
It stops at the band, and on a dose that does not move the pH, an overshoot or a probe that can't be read, which
also locks it (CS-809) until a person switches it off or the tank is filled again. The rules are ph_correct.py.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import guards
import ph_correct
from crop_steering_engine.ids import derived_id, new_id

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
# A room's dosing hardware profile (docs/DOSING.md, Hardware profile) sets these per room; each default
# is the constant above, the value every room used before it could be set.
PROFILE = {"hold_wait_s": HOLD_WAIT_S, "fill_open_s": FILL_OPEN_S, "full_blind_s": FULL_BLIND_S,
           "mix_power_s": MIX_POWER_S, "min_flow_ml_s": MIN_FLOW_ML_S, "max_dose_s": MAX_DOSE_S}
REFRESH_S = 30.0  # the pumps' flow and state are read this often
CHORES_S = 30.0  # while a dose or batch runs, stock draws, alerts and volume put-backs wait this long
QUICK_S = 2.0  # the Home Assistant timeout for those chores, for re-sent offs and for the way out
ON_TIMEOUT_S = 4.0  # a switch-on's Home Assistant timeout: always inside the way out's wait for it
REALERT_S = 1800.0  # hardware that does not read off is alerted again this often
DRAW_GIVE_UP_S = 86400.0  # a stock draw not taken within this is given up, with an alert
POLL_FAILS = 15  # one room failing this many passes in a row (30 s) is alerted
REPUBLISH_S = 60.0  # an unchanged status is published again this often (with a new updated_at)
MIX_SETTLE_S = 300.0  # a finished batch's tank is read this long after its mix stopped (the mix check)
HISTORY = 20
ANSWERS = 10  # handled_results keeps the answers to the last this many requests, by request id
OUTBOX = 50  # alerts waiting for Home Assistant, at most
DEAD = ("", "unknown", "unavailable", "none")
# The refill reminder (CS-906): a room's batch tank level is read this often, and said once it has read
# at or under the room's reminder level REMIND_READS times in a row (one bad echo is not a low tank),
# again each day it stays there, and taken down once it reads REMIND_CLEAR_PCT points above it.
REMIND_CHECK_S = 60.0
REMIND_READS = 3
REMIND_EVERY_S = 86400.0
REMIND_CLEAR_PCT = 5.0
MIX_CONFIG_WAIT_S = 1800.0  # a due mix check waits this long at most for a dosing_config it can't read
# A timed run's longest (the integration's dosing.TIMED; the prime's 30 s is ruling R7): its request's seconds, at most.
TIMED_S = {"prime": 30.0, "calibrate": 120.0}
# How a timed run's end reads in the journal (dose.completed): (outcome, code); a refusal is "refused".
_TIMED_ENDS = {"done": ("ok", None), "stopped": ("aborted", None), "stuck": ("failed", "CS-801")}
_RUNNING = {"dose": "dosing", "batch": "making a batch", "prime": "priming",
            "calibrate": "calibrating"}  # handled_result until it ends
_KIND = {"dose": "dose", "batch": "batch", "correct": "pH correction", "prime": "prime",
         "calibrate": "pump calibration"}  # how a job is named to people
_RECORDED = ("dose", "batch", "correct", *TIMED_S)  # what a start that finds its record recovers
_PUT_BACK = ("name", "volume_entity", "dosing_entity", "dosing_prefix", "power_entity")
INTENT_REEMIT_S = 1800.0  # a refusal or hold that stands is journaled again this often (controller.HELD_REEMIT_S)
_NUMBERS = re.compile(r"\d{1,2}:\d{2}|[-+]?\d+(?:\.\d+)?")  # its numbers and times (controller._HELD_NUMBERS)


class _Ended(Exception):
    """A batch ends here, short of finishing; the message says why."""


class _Exit(BaseException):
    """The app is stopping: leave whatever is recorded for the next start. Not an Exception, so no
    handler meant for a failure catches it."""


class _Refused(_Exit):
    """Home Assistant refuses the controller's token (controller._AuthGate): the job ends as when the app
    stops, its record stays, and the thread waits, then recovers it once Home Assistant accepts again."""


def _domain(entity):
    return entity.split(".", 1)[0]


def _fmt(value):
    return f"{value:g}" if isinstance(value, (int, float)) else str(value)


def _whole_ml(ml):
    """A recipe dose in whole mL, half up (12.5 -> 13), as the integration stores one."""
    return math.floor(ml + 0.5)


def _dead(state):
    return state is None or str(state).strip().lower() in DEAD


def _profile(config):
    """The room's hardware profile: each value its dosing_config publishes as a positive number, else
    the default (an integration from before the profile publishes none)."""
    given = config.get("profile") if isinstance(config, dict) else None
    given = given if isinstance(given, dict) else {}
    out = {}
    for key, default in PROFILE.items():
        value = given.get(key)
        usable = (isinstance(value, (int, float)) and not isinstance(value, bool)
                  and math.isfinite(value) and value > 0)
        out[key] = float(value) if usable else default
    return out


def _does(items):
    """"X does" / "X, Y do"."""
    return f"{', '.join(items)} {'does' if len(items) == 1 else 'do'}"


def _still(items):
    """"X still does not read off" / "X, Y still do not read off"."""
    return f"{', '.join(items)} still {'does' if len(items) == 1 else 'do'} not read off"


def _event(*parts):
    """One alert per event: the part of its notification id that tells two events apart."""
    return re.sub(r"[^a-z0-9]+", "_", "_".join(str(p) for p in parts if p).lower()).strip("_")[:80]


# How a dose's result reads in the journal (dose.completed): (outcome, code). Any other end is a failure (CS-806).
_DOSE_ENDS = {"finished": ("ok", None), "ended early": ("partial", "CS-802"), "not confirmed": ("failed", "CS-802"),
              "ran past its time": ("failed", "CS-801"), "stopped": ("aborted", None),
              "interrupted by a restart": ("failed", "CS-803")}


def _actor(by):
    """A request a person made (its `by`) is manual; one with no person, an automation's."""
    return "manual" if by else "automation"


def _dose_event(slug, item, flow, by, batch_id):
    """dose.completed for one dose given (`item` as _Job.dosed keeps it) -> (kind, Outbox.emit keywords). Its id is
    derived from the room and the dose's start, so the dose is the same event live or backfilled (history_events)."""
    at = item["at"]
    when = datetime.fromisoformat(at)
    outcome, code = _DOSE_ENDS.get(str(item.get("result") or "").split(";")[0], ("failed", "CS-806"))
    return "dose.completed", {
        "now": when, "event_id": derived_id(when, f"dosing:{slug}:{at}:dose.completed"), "outcome": outcome,
        "code": code, "actor": _actor(by), "detail": by, "correlation": {"batch_id": batch_id},
        "data": {"pump": item.get("pump"), "ml": item.get("ml"), "given_ml": item.get("given"), "flow_ml_s": flow}}


def _failed(result, name, by, batch_id, codes=(), stopped=None):
    """batch.failed's keywords for a batch (or pH correction) that did not finish: the step it stopped in and why, from
    its result ("stopped: <step>: <reason>"), and the code of its first alert other than CS-806 (CS-806 when it raised
    no other). A stop asked for is aborted."""
    parts = str(result).split(": ", 2)
    step, reason = (parts[1], parts[2]) if len(parts) == 3 and parts[0] == "stopped" else (None, str(result))
    own = [c for c in codes if c != "CS-806"]
    if stopped is None:
        stopped = reason.startswith("stop requested")
    return {"outcome": "aborted" if stopped else "failed", "code": own[0] if own else ("CS-806" if codes else None),
            "actor": _actor(by), "detail": by, "correlation": {"batch_id": batch_id},
            "data": {"step": step, "reason": reason, "recipe": name}}


def history_events(slug, history):
    """The journal events of a room's dosing history from before the journal (Controller._journal_backfill): each dose
    given as dose.completed, each batch's end as batch.step finish (done) or batch.failed, with ids derived from the
    row, "dosing:<slug>:<at>:<kind>" -> [(kind, Outbox.emit keywords)]. A row it cannot read is left out."""
    out = []
    for row in reversed(history):  # the history keeps the newest first
        try:
            at = row["at"]
            when = datetime.fromisoformat(at)
            try:
                ended = datetime.fromisoformat(row["ended_at"])
            except (KeyError, TypeError, ValueError):
                ended = when
            kind, by = row.get("kind"), row.get("by")
            batch_id = derived_id(when, f"dosing:{slug}:{at}:batch") if kind in ("batch", "correct") else None
            events = [_dose_event(slug, item, None, by, batch_id) for item in row.get("dosed") or []
                      if isinstance(item, dict) and item.get("at")]
            if kind == "batch":
                name, result = row.get("name") or "", str(row.get("result") or "")
                end = "batch.step" if result.startswith("finished") else "batch.failed"
                kw = ({"actor": _actor(by), "detail": by, "correlation": {"batch_id": batch_id},
                       "data": {"step": "finish", "state": "done", "recipe": name}} if end == "batch.step"
                      else _failed(result, name, by, batch_id))
                events.append((end, {**kw, "now": ended, "event_id": derived_id(when, f"dosing:{slug}:{at}:{end}")}))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        out += events
    return out


def _ml_s(ml_min):
    """A pump's calibrated mL/min (the integration's pump calibration) in mL/s, or None when it is not a positive
    number."""
    usable = (isinstance(ml_min, (int, float)) and not isinstance(ml_min, bool) and math.isfinite(ml_min)
              and ml_min > 0)
    return ml_min / 60 if usable else None


def _probe_calibrating(config):
    """A feed probe's calibration may be open, so the tank probe may read a buffer: dosing_config's `calibrating` names
    a probe (with or without a pump, calibration.merge_holds), is anything but a pump's alone, or dosing_config can't
    be read at all."""
    if not isinstance(config, dict):
        return True
    entry = config.get("calibrating")
    if not entry:
        return False
    return not (isinstance(entry, dict) and entry.get("pump") and not entry.get("probe"))


def _aware(stamp):
    try:
        parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else None


class _Job:
    """The one dose or batch dosing is running."""

    def __init__(self, room, config, request, kind):
        self.room, self.config, self.request, self.kind = room, config, request, kind
        self.profile = _profile(config)  # the room's hardware profile: its times and limits
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
        self.dosed = []  # each dose in the order it went in: pump, name, mL asked, mL given, result
        self.started_at = None
        self.id = new_id()  # the journal's batch_id: every step of a batch, and its doses, carry it
        self.codes = []  # the codes of the alerts it raised, in order (its batch.failed names the first)


class DosingRunner:
    def __init__(self, controller, *, get, call, publish, alert, state_path, log=print,
                 sleep=time.sleep, monotonic=time.monotonic, now=None, history=None, respond=None,
                 actuators=None, refused=None):
        self.c = controller
        # get(entity, timeout=...) -> (state, attributes, last_updated) with .last_changed;
        # call(domain, service, timeout=..., **data) -> bool; publish(entity, state, attributes);
        # alert(room, code, title, message, event) -> True once Home Assistant has it;
        # history(entity, since) -> [(state, last_changed), ...] or None;
        # respond(domain, service, data, timeout) -> (HTTP status or None, the service's answer);
        # actuators: the controller's actuator table (controller.ACTUATORS), domain -> (on service, off
        # service, on state, off state).
        self._get, self._call, self._publish = get, call, publish
        self._deliver, self._log = alert, log
        self._history = history or (lambda _entity, _since: None)
        self._respond = respond
        self._actuators = actuators or {}
        self._refused = refused or (lambda: False)  # Home Assistant refuses the token (_Refused)
        self._sleep, self._mono = sleep, monotonic
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._recovered_rows = []  # (slug, history entry) _recover_record wrote, for the journal (journal_recovered)
        self._intents = {}  # what _journal_intent journaled lately -> when, on the runner's clock
        self.path = state_path
        # Guards everything below; never held across a Home Assistant call. Re-entrant: the stop signal
        # runs exit() on the main loop, which may be in the middle of a step.
        self._lock = threading.RLock()
        self._held = {}  # room slug -> the slugs of the rooms its batch, or what it left on, holds
        self._stuck = {}  # room slug -> what did not read off, held until it does (_release_stuck)
        self._job = None
        self._steps = None  # the running dose or batch: a generator that yields the seconds to its next step
        self._due = None  # when its next step is due, on the runner's clock
        self._switching = False  # a switch-on is on its way (_on)
        self._exit_pending = None  # the stop that landed in the middle of it (defer_exit)
        self._exiting = False
        self._recovered = False
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
                job = self._job
                correcting = job is not None and job.kind == "correct" and job.room.slug == slug
                found = "correcting the batch tank's pH" if correcting else "making a batch"
        return found

    def step(self):
        """One go of dosing on the controller's main loop: every room's dosing_config is read every
        POLL_S (which takes a new request, and starts its dose or batch at once), and the dose or batch
        running is run on to its next wait when that is due. Never raises: an error is logged, and
        one inside a dose or batch is recovered as after a restart (_crashed). -> the seconds until
        dosing is next due."""
        try:
            if not self._exiting:
                # Nothing new is asked of Home Assistant while it refuses the token; a dose or batch
                # running sees the refusal at its next step and ends (_Refused).
                refused = self._refused()
                if self._steps is None and not refused:  # one runs only once recovered (taken in poll)
                    self.recover()
                if not refused and (self._polled is None or self._mono() - self._polled >= POLL_S):
                    self.poll()
                if self._steps is not None and self._mono() >= self._due:
                    self._advance()
        except _Refused:
            with self._lock:
                self._job = None
                self._recovered = False  # what the job left is recovered once Home Assistant accepts
        except _Exit:
            pass
        except Exception as e:  # dosing never stops the irrigation loop
            self._log("dosing: error", repr(e))
        now = self._mono()
        due = (now if self._polled is None else self._polled) + POLL_S
        if self._steps is not None:
            due = min(due, self._due)
        return max(0.0, due - now)

    def running(self):
        """Whether a dose or batch is running: a shot's wait steps it on too (Controller._wait_shot)."""
        return self._steps is not None

    def _start(self, steps):
        """A dose or batch just taken: its first step now (all of it, when it ends before any wait)."""
        self._steps, self._due = steps, self._mono()
        self._advance()

    def _advance(self):
        """The running dose or batch, on to its next wait (or its end)."""
        try:
            wait = next(self._steps)
        except StopIteration:
            self._steps = self._due = None
            return
        except _Exit:
            self._steps = self._due = None
            raise
        except Exception as e:  # it settles its own failures: this one escaped
            self._steps = self._due = None
            self._crashed(e)
            return
        self._due = self._mono() + max(0.0, wait)

    def _crashed(self, error):
        """A dose or batch stopped with an error it did not settle: recover as after a restart (whatever
        is recorded is held and switched off; nothing is resumed), and say so."""
        self._log("dosing: error", repr(error))
        with self._lock:
            self._job = None
            self._held.clear()
            self._stuck.clear()
            self._recovered = False
        self.recover()
        self._alert(None, "CS-806", "dosing stopped with an error and started again",
                    f"The dosing of the controller stopped with an error ({error!r}), and the controller "
                    "started it again. The controller set to off what a dose or batch had on. That hardware "
                    "holds the shots of its rooms until it reads off. The controller did not continue the "
                    "dose or batch. Read the controller log. If a dose or batch was running, check the tank.",
                    _event("crash", self._now().isoformat()))

    def recover(self):
        """At start-up, and after a dose or batch crashed (_crashed): whatever a dose or batch left recorded
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
                        "The controller could not read dosing_state.json at start, so it does not know if a "
                        "dose or a batch was running. It kept the file as dosing_state.json.bad. In each room "
                        "with dosing, it set the power of the dosing pumps, the fill valve, the mix pump and "
                        "the mix valves to off. A room whose hardware does not read off stays held until it "
                        "does. Check the batch tanks before the next dose.",
                        _event("state_file", self._now().isoformat()))
        self._release_stuck()
        return True

    def recorded(self):
        """Whether a dose or batch has anything recorded: what exit() switches off again."""
        with self._lock:
            return any(isinstance(block, dict) and isinstance(block.get("inflight"), dict)
                       for block in self._doc["rooms"].values())

    def recorded_entity(self):
        """The first switch a recorded dose or batch lists to switch off, or None."""
        with self._lock:
            for block in self._doc["rooms"].values():
                record = block.get("inflight") if isinstance(block, dict) else None
                for entity in (record.get("off") or []) if isinstance(record, dict) else []:
                    if isinstance(entity, str) and "." in entity:
                        return entity
        return None

    def running_off(self):
        """What the running dose or batch has on: what _exit_off switches off."""
        with self._lock:
            job = self._job
        return [] if job is None else self._job_off(job)

    def _job_off(self, job):
        if job.kind == "dose" or job.kind in TIMED_S:
            return [job.pump["power_entity"]] if job.pump else []
        return self._dosing_hardware(job.config)

    def stop_starting(self):
        """The app is stopping (SIGTERM, before the irrigation's own safe-off): no dose, batch or
        switch-on starts from here on."""
        with self._lock:
            self._exiting = True

    def defer_exit(self, stop):
        """The app is stopping while a switch-on is on its way (SIGTERM lands on the main loop, so in
        the middle of _on): nothing more starts, and `stop` (the way out) runs as soon as that call
        has landed, at most ON_TIMEOUT_S, so its offs come after it. -> False when none is on its way
        (stop at once)."""
        with self._lock:
            if not self._switching:
                return False
            self._exiting, self._exit_pending = True, stop
            return True

    def exit(self, within=None):
        """The app is stopping (SIGTERM, after the irrigation's own safe-off): nothing starts from here
        on, and everything recorded is switched off again, each off with a QUICK_S timeout and no
        read-back. The records stay, and a batch's hold stays on, so the next start reads it all back
        off (recover) and raises CS-803. With `within` (seconds) every off is cut to fit inside it,
        and an off that no longer fits is not sent."""
        end = None if within is None else self._mono() + within
        with self._lock:
            self._exiting = True
            records = [
                dict(block["inflight"]) for block in self._doc["rooms"].values()
                if isinstance(block, dict) and isinstance(block.get("inflight"), dict)
            ]
        unsent = []
        for record in records:
            for entity in record.get("off") or []:
                if isinstance(entity, str) and "." in entity:
                    timeout = QUICK_S if end is None else min(QUICK_S, end - self._mono())
                    if timeout > 0:
                        self._send_off(entity, timeout)
                    else:
                        unsent.append(entity)
        if unsent:
            self._log("dosing: no time left to switch off " + ", ".join(unsent) + "; recorded for the next start")

    # ------------------------------------------------------------------ every room, every POLL_S
    def poll(self, busy=None):
        """Read every room's dosing_config once: take each new request, publish each room's status.
        While a dose or batch runs only a stop is acted on, a dose or batch is refused, and the chores
        wait CHORES_S between runs. `busy`: that dose or batch, when it is not the one running now."""
        now = self._polled = self._mono()
        busy = busy or self._job
        self._safely(self._release_stuck)
        self._safely(self._sweep_rooms)
        if busy is None or self._chores is None or now - self._chores >= CHORES_S:
            self._chores = now
            for chore in (self._restore_pending, self._send_draws, self._send_alerts):
                self._safely(chore)
        self._safely(self._check_mixes)
        for room in list(self.c.rooms):
            try:
                self._poll_room(room, busy or self._job)  # one taken here is running from now on
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
        if config and job is None:
            self._remind(room, config["batch"])
            self._ph_tick(room, config)

    def _remind(self, room, batch):
        """The refill reminder (CS-906, docs/DOSING.md): nothing refills a batch tank by itself, so once its
        level has read at or under the room's remind_pct for REMIND_READS reads in a row, a person is told
        to refill it, again each day it stays there (kept across a restart), and the notification goes
        once the level reads REMIND_CLEAR_PCT above it. Never while a dose or batch runs in the room; a
        level that reads nothing changes nothing."""
        live, now = self._live_of(room), self._mono()
        if live["remind_read"] is not None and now - live["remind_read"] < REMIND_CHECK_S:
            return
        live["remind_read"] = now
        remind, entity = batch.get("remind_pct"), batch.get("level_entity")
        if not entity or isinstance(remind, bool) or not isinstance(remind, (int, float)) or remind <= 0:
            live["remind_low"] = 0
            self._end_reminder(room)
            return
        try:
            pct = float(self._state(entity, quick=True))
        except (TypeError, ValueError):
            return
        if not math.isfinite(pct):
            return
        if pct > remind:
            live["remind_low"] = 0
            if pct >= remind + REMIND_CLEAR_PCT:
                self._end_reminder(room)
            return
        live["remind_low"] += 1
        when = self._now()
        with self._lock:
            block = self._block(room)
            last = _aware(block.get("reminded_at"))
            if live["remind_low"] < REMIND_READS or (
                last is not None and 0 <= (when - last).total_seconds() < REMIND_EVERY_S
            ):
                return
            block["reminded_at"] = when.isoformat()
        self._alert(room.slug, "CS-906", f"batch tank at {pct:g}%, refill it",
                    f"The batch tank reads {pct:g}%, at or below its refill reminder ({remind:g}%). Refill "
                    "the tank by hand, or make a batch. Nothing refills the tank automatically. This alert "
                    f"comes again each day while the tank stays at or below {remind:g}%. It clears when "
                    f"the tank reads {remind + REMIND_CLEAR_PCT:g}%.", "remind")

    def _end_reminder(self, room):
        """Take the refill reminder down (one waiting for Home Assistant too), so it is said again the
        next time the tank runs low. Kept up until Home Assistant has dismissed it."""
        with self._lock:
            block = self._doc["rooms"].get(room.slug)
            if not isinstance(block, dict) or block.get("reminded_at") is None:
                return
            self._doc["outbox"] = [a for a in self._doc["outbox"]
                                   if (a.get("slug"), a.get("code")) != (room.slug, "CS-906")]
        if self.c._dosing_dismiss(room, "CS-906", "remind"):
            with self._lock:
                block["reminded_at"] = None
                self._write()

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
            self._alert(room.slug, "CS-806", "dosing in this room fails again and again",
                        f"The dosing of the controller failed {count} times in sequence for this room "
                        f"(the last: {error!r}). The controller can miss a dosing request, and the dosing "
                        "status is not current. Hardware that a dose or batch left on is still set to off "
                        "and held. Read the controller log. Check the dosing setup of the room.",
                        _event("poll", self._now().isoformat()))

    def _take(self, room, config, request, busy):
        age = self._age(request)
        action = request.get("action")
        with self._lock:
            stuck = self._stuck.get(room.slug)
            left = list(stuck["left"]) if stuck else []
        here = busy is not None and busy.room.slug == room.slug
        stops = {"stop": self._stop, "stop_pump": self._stop_pump}
        if action in stops and (here or stuck):  # never too old while there is something to stop
            return self._settle(room, config, request, stops[action](room, config, busy, request))
        if age is None or age > MAX_AGE_S:
            return self._settle(room, config, request, "too old to act on")
        if action in stops:
            return self._settle(room, config, request, stops[action](room, config, busy, request))
        # Each controller keeps its own record of what it has handled, so two on one room would both take
        # this request. Refused, not deferred: it would be too old by the time the hold ends.
        if action in ("dose", "batch", *TIMED_S) and self.c.duplicate_hold(room):
            return self._settle(room, config, request, "refused: another controller is driving this room")
        if busy is not None:
            where = "" if here else f" in room {busy.room.slug}"
            return self._settle(room, config, request, f"refused: a {_KIND[busy.kind]} is running{where}")
        if stuck:
            return self._settle(room, config, request, f"refused: {_does(left)} not read off yet")
        if action not in ("dose", "batch", *TIMED_S):
            return self._settle(room, config, request, f"refused: unknown action {action!r}")
        why = self._mix_refuses(room) if action == "batch" and request.get("by") is None else None
        if why:  # an automation's batch (no user): a person makes the next one after a failed mix check
            return self._settle(room, config, request, f"refused: {why}")
        with self._lock:  # taken: from here on it is handled, whatever comes of it
            block = self._block(room)
            self._answer(block, request["id"], _RUNNING[action])
            self._write()
        runs = {"dose": self._run_dose, "batch": self._run_batch}
        self._start(runs.get(action, self._run_timed)(room, config, request))
        return None

    def _stop(self, room, config, busy, request):
        """Every pump's power in the room off, the running job's and the current setup's (a setup
        saved since the job started may name other pumps), and whatever the room left not reading
        off; a dose or batch running in the room ends at its next check, and a room held by what did
        not read off is released once all of it does."""
        job = busy if busy is not None and busy.room.slug == room.slug else None
        entities = [p["power_entity"] for p in job.config["pumps"]] if job is not None else []
        entities += [p["power_entity"] for p in config["pumps"]] + self._unreadable_powers(config)
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

    def _stop_pump(self, room, config, busy, request):
        """A stop of one pump (the integration's pump_stop): that pump's prime or calibration running in the room
        ends at its next tick (_timed_run), which switches it off and reads it back off; a dose, batch or pH
        correction running in the room is left alone (the room's stop ends it); else the pump's power is switched
        off and read back, and a power that does not read off latches the room and raises CS-801, as a run's does."""
        job = busy if busy is not None and busy.room.slug == room.slug else None
        if job is not None and job.kind in TIMED_S and job.pump["id"] == request.get("pump"):
            job.stopped, job.stopped_by = True, request.get("by")
            if job.pressed is not None and job.cut_at is None:
                job.cut_at = self._mono()  # it ran until now (ran_s)
            return "stopped"
        if job is not None and job.kind not in TIMED_S:
            return f"refused: a {_KIND[job.kind]} is running, and a pump's stop leaves it alone"
        pump = next((p for p in config["pumps"] if p["id"] == request.get("pump")), None)
        if pump is None:  # a pump whose setup can't be read is still switched off by its name's power
            power = next(iter(self._unreadable_powers(config, request.get("pump"))), None)
            if power is None:
                return self._no_pump(config, request.get("pump"))
            pump = {"id": request.get("pump"), "name": request.get("pump"), "power_entity": power}
        left = self._switch_off([pump["power_entity"]])
        if left:
            event = _event(pump["id"], self._now().isoformat())
            self._alert(room.slug, "CS-801", "a dosing pump does not read off after a stop",
                        f"A stop of {pump['name']} set its power ({pump['power_entity']}) to off, but it does not "
                        "read off. The shots of this room are held, and the controller sends the off again each "
                        "2 s until it reads off. If the pump still runs, stop it by hand. Check the tank before "
                        "the next dose.", event)
            self._hold_stuck(room, left, None, {room.slug}, "CS-801", "a dosing pump does not read off",
                             f"A stop of {pump['name']} did not read its power off.",
                             "Check the pump and the tank before the next dose.", event, alerted=True)
        return "stopped" + (f"; {_does(left)} not read off" if left else "")

    # ------------------------------------------------------------------ a timed run (prime, calibrate)
    def _run_timed(self, room, config, request):
        """A prime or a pump's calibration run (the integration's pump_prime / pump_calibrate), always settled: the
        pump's power on and read back on, its request's seconds (at most TIMED_S) with a stop and the abort checks
        read every READ_S, then off and read back off on every way it ends. What does not read off latches the room
        as a dose's does (CS-801); the app stopping sends the off and leaves the record for the next start. Its end
        is reported as {id, action, pump, ran_s, result: done | stopped | refused: why | stuck} in handled_results
        under its request id (and handled_result while no other request was handled since), which the integration
        reads (dosing_api._status_changed): ran_s is the seconds from the switch-on to the off, 0 for a refused or
        stuck run."""
        action = request["action"]
        pump = next((p for p in config["pumps"] if p["id"] == request.get("pump")), None)
        if pump is None:
            return self._settle(room, config, request, self._no_pump(config, request.get("pump")))
        seconds = request.get("seconds")
        if (isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds)
                or seconds <= 0):
            return self._settle(room, config, request, f"refused: {_fmt(seconds)} s is not a run length")
        seconds = min(float(seconds), TIMED_S[action])
        job = _Job(room, config, request, action)
        job.pump, power = pump, pump["power_entity"]
        why = self._timed_check(job)
        if why:
            self._journal_intent(room, "intent.refused", why, job)
            return self._settle(room, config, request, f"refused: {why}")
        job.started_at = self._now().isoformat()
        if not self._record(job, {"kind": action, "at": job.started_at, "request": request["id"],
                                  "by": request.get("by"), "pump": pump["id"], "seconds": seconds, "off": [power]}):
            return self._settle(room, config, request,
                                f"refused: the {_KIND[action]} could not be written to dosing_state.json", clear=True)
        with self._lock:
            self._job = job
        job.dose = {"pump": pump["id"], "ml": None, "started_at": job.started_at, "expected_s": seconds}
        self._show(room, config)
        try:
            try:
                result = yield from self._timed_run(job, power, seconds)
            except _Exit:
                self._exit_off(job)  # its record stays: the next start reads it back off (recover)
                raise
            except Exception as e:  # anything unforeseen: still switched off and read back
                self._log(f"[{room.slug}] dosing: {_KIND[action]} error", repr(e))
                result = "stopped"
            if job.cut_at is None:
                job.cut_at = self._mono()
            try:
                left = self._switch_off([power])
            except Exception as e:
                self._log(f"[{room.slug}] dosing: could not switch {power} off", repr(e))
                left = [power]
        finally:
            job.dose = None
            with self._lock:
                self._job = None
        ran = (0 if left or result.startswith("refused") or job.pressed is None
               else round(max(0.0, job.cut_at - job.pressed), 1))
        if left:
            result, event = "stuck", _event(pump["id"], job.started_at)
            self._alert(room.slug, "CS-801", f"a dosing pump does not read off after a {_KIND[action]}",
                        f"The {_KIND[action]} of {pump['name']} ended, and the controller set its power ({power}) "
                        "to off, but it does not read off. The shots of this room are held, and the controller sends "
                        "the off again each 2 s until it reads off. If the pump still runs, stop it by hand. Check "
                        "the tank before the next dose.", event)
            self._hold_stuck(room, left, None, {room.slug}, "CS-801", "a dosing pump does not read off",
                             f"A {_KIND[action]} of {pump['name']} ended, and its power did not read off.",
                             "Check the pump and the tank before the next dose.", event, alerted=True)
        outcome, code = _TIMED_ENDS.get(result, ("refused", None))
        self._journal(room, lambda: ("dose.completed", {
            "outcome": outcome, "code": code, "actor": _actor(request.get("by")), "detail": request.get("by"),
            "data": {"pump": pump["id"], "kind": action, "seconds": seconds, "ran_s": ran, "result": result,
                     "ml": None, "given_ml": None, "flow_ml_s": None}}))
        entry = {"kind": action, "at": job.started_at, "ended_at": self._now().isoformat(), "result": result,
                 "pump": pump["id"], "seconds": seconds, "ran_s": ran, "doses": {}, "dosed": [],
                 "by": request.get("by")}
        self._settle(room, config, request, self._timed_report(request, ran, result), entry=entry, clear=not left,
                     final=True)

    def _timed_check(self, job):
        """Why a timed run must not start (guards.DOSE_RUN; then guards.CALIBRATING, which every hold but its own
        pump's holds; then the kill switch), else None."""
        ctx = {"pump": job.pump, "profile": job.profile, "action": job.kind, "batch": job.config["batch"]}
        hit = guards.first(self, guards.DOSE_RUN, job.room, None, ctx) or guards.first(
            self, guards.CALIBRATING, job.room, None, {"config": job.config, "own": job.pump["id"]})
        if hit:
            return guards.Why(hit)
        return self._run_abort(job.room)

    def _run_abort(self, room):
        """Why a timed run must end now, read at every tick: the room's kill switch off, a hardware fault latched,
        a shot in flight in the room. Else None."""
        gate = guards._m(self.c).room_gate(room)
        if not self.c._on(gate, False):
            return f"the room's kill switch ({gate}) is off"
        fault = self.c._hardware_fault_block(room)
        if fault:
            return fault
        return "a shot is in flight in this room" if getattr(room, "shot_inflight", None) else None

    def _timed_run(self, job, power, seconds):
        """The power on (_on, which reads a stop first) and read back on, then each READ_S: the app stopping, a
        refused token, a stop (read now) and the abort checks, until `seconds` from the switch-on -> "done",
        "stopped" or "refused: <power> did not read on". job.pressed: the switch-on; job.cut_at: when it ended."""
        try:
            self._on(job, power)
        except _Ended:  # a stop came first: nothing was switched on
            return "stopped"
        job.pressed = self._mono()
        if self._confirm([power], "on", min(CONFIRM_TIMEOUT_S, seconds)):  # never longer than the run itself
            return f"refused: {power} did not read on"
        end = job.pressed + seconds
        while True:
            if self._exiting:
                raise _Exit()
            if self._refused():
                raise _Refused()
            self._catch_stop(job)
            why = self._stop_reason(job) if job.stopped else self._run_abort(job.room)
            now = self._mono()
            if why:
                if job.cut_at is None:
                    job.cut_at = now
                self._log(f"[{job.room.slug}] dosing: the {_KIND[job.kind]} of {job.pump['name']} stopped: {why}")
                return "stopped"
            if now >= end:
                job.cut_at = now
                return "done"
            yield min(READ_S, end - now)

    @staticmethod
    def _timed_report(request, ran_s, result):
        """handled_result of a timed run: {id, action, pump, ran_s, result}, its result done, stopped, stuck or
        "refused: <why>" (any other words, such as "too old to act on", are a refusal)."""
        if result not in ("done", "stopped", "stuck") and not result.startswith("refused"):
            result = f"refused: {result}"
        return {"id": request.get("id"), "action": request.get("action"), "pump": request.get("pump"),
                "ran_s": ran_s, "result": result}

    # ------------------------------------------------------------------ one dose
    def _run_dose(self, room, config, request):
        """One dose, always settled: an error in the controller cuts the pump and ends it "stopped: an
        error in the controller" (CS-806); a pump whose power does not read off keeps its record and
        holds the room's watering until it does (_release_stuck)."""
        pump = next((p for p in config["pumps"] if p["id"] == request.get("pump")), None)
        if pump is None:
            return self._settle(room, config, request, self._no_pump(config, request.get("pump")))
        job = _Job(room, config, request, "dose")
        job.pump = pump
        with self._lock:
            self._job = job
        try:
            result = yield from self._dose(job, pump, request.get("ml"))
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
                self._alert(room.slug, "CS-806", "a dose stopped, but its pump does not read off",
                            f"The dose of {pump['name']} stopped, but {_still(left)}. The shots of this room "
                            "are held, and the controller sends the off again each 2 s until it reads off. "
                            "If the pump still runs, stop it by hand. Check the tank before the next dose.",
                            _event(pump["id"], started))
            self._hold_stuck(room, left, None, {room.slug}, code, "a dosing pump does not read off",
                             f"A dose of {pump['name']} ended ({result}).",
                             "Check the pump and the tank before the next dose.",
                             _event(pump["id"], started), alerted=True)
        entry = None
        if not result.startswith("refused"):
            entry = {"kind": "dose", "at": started, "ended_at": self._now().isoformat(),
                     "result": result, "doses": {pump["id"]: request.get("ml")},
                     "dosed": list(job.dosed), "by": request.get("by")}
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
            self._alert(job.room.slug, "CS-806", "an error in the controller stopped a dose",
                        f"The dose of {pump['name']} stopped because of an error in the controller ({error!r}). "
                        f"The controller set its power ({pump['power_entity']}) to off"
                        + (", but it does not read off. The shots of this room are held, and the controller "
                           "sends the off again each 2 s until it reads off." if job.left else ".")
                        + " The dosed volume is not known. Check the tank before the next dose.",
                        _event(pump["id"], job.started_at))
        return "stopped: an error in the controller"

    def _dose(self, job, pump, ml):
        """One dose of `ml` mL through `pump` (docs/DOSING.md, One dose) -> "finished", "ended early",
        "ran past its time", "not confirmed" or "stopped" ("stopped: an error in the controller"), or
        "refused: why" when nothing was pressed. job.left: what its end left not reading off."""
        job.left, job.pressed, job.cut_at = [], None, None
        if job.kind == "dose":  # a single dose waits for a pump's calibration or prime (guards.CALIBRATING)
            hit = guards.first(self, guards.CALIBRATING, job.room, None, {"config": job.config, "dose": True})
            if hit:
                self._journal_intent(job.room, "intent.refused", guards.Why(hit), job)
                return f"refused: {hit[1]}"
        why, flow = self._dose_check(pump, ml, job.profile)
        if why:
            self._journal_intent(job.room, "intent.refused", why, job)
            return f"refused: {why}"
        volume = pump["volume_entity"]
        old = None
        if pump.get("restore_volume", True):
            old = self._device(volume, "volume")[0]
            if old is None:
                return f"refused: {volume} can't be read, so it could not be put back"
        expected = ml / flow
        started = self._now().isoformat()
        job.started_at = job.started_at or started
        job.dose = {"pump": pump["id"], "ml": ml, "started_at": started,
                    "expected_s": round(expected, 1)}
        record = {"pump": pump["id"], "name": pump["name"], "ml": ml, "at": started}
        if old is not None:  # what to put back, even after a restart (recover)
            record.update(old_volume=old, **{key: pump.get(key) for key in _PUT_BACK})
        fields = {"dose": record, "doses": {**job.doses, pump["id"]: ml}}
        if job.kind == "dose":  # a single dose never records, or touches, a batch's hold
            fields.update(kind="dose", at=started, request=job.request["id"],
                          by=job.request.get("by"), off=self._dosing_hardware(job.config))
        if not self._record(job, fields, merge=job.kind != "dose"):
            job.dose = None
            return "refused: the dose could not be written to dosing_state.json"
        self._show(job.room, job.config)
        try:
            result = yield from self._run_one(job, pump, ml, flow, expected)
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
        given = self._given(result, ml, flow, elapsed)
        if not result.startswith("refused"):
            self._journal(job.room, lambda: _dose_event(
                job.room.slug, {"pump": pump["id"], "ml": ml, "given": given, "result": result, "at": started}, flow,
                job.request.get("by"), job.id if job.kind != "dose" else None))
        result = self._stock_draw(job, pump, given, result, started)
        if not result.startswith("refused"):
            job.doses[pump["id"]] = ml
            job.dosed.append({"pump": pump["id"], "name": pump["name"], "ml": ml, "given": given,
                              "result": result, "at": started})
            with self._lock:
                self._block(job.room)["last"][pump["id"]] = {"ml": ml, "given": given, "at": started,
                                                            "result": result}
            self._record(job, {"dosed": list(job.dosed)}, merge=True)  # kept if the app stops next
        return result

    @staticmethod
    def _given(result, ml, flow, elapsed):
        """What a dose gave, in mL (docs/DOSING.md, Exact dose record): finished, the mL asked for;
        not confirmed or refused, not known (None); any other end, that or the seconds from the press
        to the moment it ended, or its stop or cut was sent, x the flow, whichever is less."""
        if result == "finished":
            return ml
        if result == "not confirmed" or result.startswith("refused"):
            return None
        return round(min(ml, max(0.0, elapsed) * flow), 1)

    def _stock_draw(self, job, pump, given, result, started):
        """What the dose took from the pump's stock tank (docs/DOSING.md, Stock tanks): what it gave;
        not confirmed, nothing, and the result says so. Queued for stock_draw."""
        tank = pump.get("stock_tank")
        if not tank or result.startswith("refused"):
            return result
        if given is None:
            return "not confirmed; nothing drawn from its stock tank"
        if given > 0:
            self._queue_draw(job.room, {
                "key": f"{job.room.prefix}:{pump['id']}:{started}",
                "room_id": f"room:{job.room.prefix}",
                "draws": {tank: round(given, 1)},
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
                        f"{draw.get('note') or 'A dose'}: {amounts} was not taken off its stock tank, because "
                        f"{why}. The level of that stock tank now shows more than the tank contains. Set the "
                        "level in Stock tanks (Set level). Check the stock tank of the pump in the dosing setup.",
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
        if not idle and self._hw_state(dose.get("power_entity")) != "off":
            return False
        volume, value = dose["volume_entity"], dose["old_volume"]
        if not self._set_volume(volume, value):
            name = dose.get("name") or dose.get("pump")
            self._alert(slug, "CS-806", "the volume of a dosing pump was not restored",
                        f"After a dose, the controller could not set the volume number of {name} back to "
                        f"{_fmt(value)} mL: {volume} reads {self._device(volume, 'volume')[1]}. The firmware of "
                        "the pump can keep its batch recipe in this number. Set it back by hand before the next batch.",
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

    def _uncalibrated(self, pump, profile=PROFILE):
        """Why the pump's flow can't be used, or None: it must read a number of at least the profile's
        min_flow_ml_s (a firmware that divides by a zero flow runs its motor for ever, and a tiny one
        would put every time limit hours away)."""
        flow, reading = self._flow(pump)
        if flow is not None and flow >= profile["min_flow_ml_s"]:
            return None
        return f"{pump['name']} is not calibrated (flow {'missing' if reading is None else _fmt(reading)})"

    def _flow(self, pump, quick=False):
        """A pump's flow in mL/s -> (the number or None, its reading): its flow entity's, which wins; with none, its
        calibrated_ml_min / 60 (the integration's pump calibration, G3)."""
        if pump.get("flow_entity"):
            flow, reading, _unit = self._device(pump["flow_entity"], "flow", quick)
            return flow, reading
        flow = _ml_s(pump.get("calibrated_ml_min"))
        return flow, flow

    @staticmethod
    def _too_long(pump, ml, flow, profile=PROFILE):
        return (f"{_fmt(ml)} mL of {pump['name']} would take {ml / flow / 60:.1f} min at "
                f"{_fmt(flow)} mL/s, more than {profile['max_dose_s'] / 60:g} min")

    def _dose_check(self, pump, ml, profile=PROFILE):
        """Why this dose must not start (docs/DOSING.md, One dose, step 1; guards.DOSE, its words a guards.Why) and
        the pump's flow."""
        ctx = {"pump": pump, "ml": ml, "profile": profile}
        hit = guards.first(self, guards.DOSE, None, None, ctx)
        if hit:
            return guards.Why(hit), None
        return None, ctx["flow"]

    def _run_one(self, job, pump, ml, flow, expected):
        """Set the volume, read it back, press start, and watch the pump dose and stop."""
        volume, start = pump["volume_entity"], pump["start_entity"]
        if not self._set_volume(volume, ml):
            return f"refused: {volume} did not read back {_fmt(ml)} mL, so start was not pressed"
        pressed_at, pressed = self._now(), self._mono()  # before the press: the recorder is read from here
        domain = _domain(start)
        try:
            if not self._on(job, start, "turn_on" if domain == "script" else "press"):
                self._log(f"[{job.room.slug}] dosing: pressing {start} failed; watching the pump anyway")
        except _Ended:  # a stop, or the batch's watchdog, came first: nothing was pressed
            return "stopped"
        job.pressed = pressed
        deadline = pressed + min(expected * 1.25 + 20, job.profile["max_dose_s"] + 60)
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
                held = (", but it still does not read off. The shots of this room are held, and the controller "
                        "sends the off again each 2 s until it reads off. Stop the pump by hand now."
                        if job.kind == "dose" else ", but it still does not read off. Stop the pump by hand now.")

                self._alert(
                    job.room.slug, "CS-801", "a dosing pump ran past its time, power set to off",
                    f"The controller asked {pump['name']} for {_fmt(ml)} mL, about {expected:.0f} s at its "
                    f"calibrated {_fmt(flow)} mL/s. The pump still dosed after {deadline - pressed:.0f} s. "
                    f"The controller set its power ({pump['power_entity']}) to off"
                    + (held if job.left else ".")
                    + " The tank can contain more than the requested volume. Check the pump, its calibration "
                    f"and its firmware before the next dose.{batch}",
                    _event(pump["id"], job.dose and job.dose["started_at"]),
                )
                return "ran past its time"
            yield READ_S

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
            self._alert(job.room.slug, "CS-802", "a dose was not confirmed",
                        f"The controller asked {pump['name']} for {_fmt(ml)} mL and pressed its start, but "
                        f"{pump['dosing_entity']} read unavailable or unknown during the dose. So the controller "
                        "does not know if the pump dosed, or how much. A pump that restarts during a dose stops "
                        f"the dose. Check the pump and the tank before the next dose.{batch}", event)
            return "not confirmed"
        if not (seen or went):
            self._alert(job.room.slug, "CS-802", "a dose was not confirmed",
                        f"The controller asked {pump['name']} for {_fmt(ml)} mL and pressed its start, but "
                        f"{pump['dosing_entity']} did not read dosing within {expected + 15:.0f} s. So the "
                        "controller does not know if the pump dosed. Make sure that the pump is online. "
                        f"Check its dosing sensor and the tank before the next dose.{batch}", event)
            return "not confirmed"
        if elapsed < expected / 2:
            self._alert(job.room.slug, "CS-802", "a dose ended early",
                        f"The controller asked {pump['name']} for {_fmt(ml)} mL, about {expected:.0f} s at its "
                        f"calibrated {_fmt(flow)} mL/s, but it read not dosing again after {elapsed:.0f} s. "
                        f"The dose ended early, with about {_fmt(round(min(ml, elapsed * flow), 1))} mL in the "
                        "tank. Check the pump, its calibration, its firmware and the tank before the next "
                        f"dose.{batch}", event)
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
            self._journal_intent(room, "intent.refused", why, job)
            return self._settle(room, config, request, f"refused: {why}")
        job.started_at = self._now().isoformat()
        record = {"kind": "batch", "at": job.started_at, "request": request["id"],
                  "name": batch.get("name") or "", "by": request.get("by"),
                  "off": self._dosing_hardware(config),
                  "hold": batch.get("hold_entity"), "held": sorted(held), "doses": {}}
        if not self._record(job, record):
            return self._settle(room, config, request,
                                "refused: the batch could not be written to dosing_state.json", clear=True)
        with self._lock:
            self._job = job
        stuck, hold_left, told = [], [], True
        try:
            job.deadline = self._mono() + self._watchdog(batch, plan, job.profile)
            with self._lock:
                self._live_of(room)["batch"] = {
                    "step": "idle", "pump": None, "name": batch.get("name") or "",
                    "started_at": job.started_at, "step_started_at": None,
                    "steps": [], "result": None, "ended_at": None}
            yield from self._hold(job, held)
            self._close(job, held)
            yield from self._fill(job)
            yield from self._mix(job)
            yield from self._pause(job, "premix", batch.get("premix_min"))
            yield from self._doses(job, plan)
            yield from self._pause(job, "postmix", batch.get("postmix_min"))
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
        if not result.startswith("finished"):
            self._journal(room, lambda: ("batch.failed", _failed(result, batch.get("name") or "", request.get("by"),
                                                                 job.id, job.codes, job.stopped)))
        left = bool(stuck or hold_left)
        if left:
            title = ("the hold of a finished batch did not release" if result.startswith("finished")
                     else "a batch stopped")
            self._hold_stuck(room, stuck, batch.get("hold_entity"), held, "CS-806", title,
                             f"A batch that started {job.started_at} ended ({result}).",
                             "Check the tank before the next batch.", _event(job.started_at),
                             alerted=told)
        else:
            with self._lock:
                self._held.pop(room.slug, None)
            if result.startswith("finished"):
                self._plan_mix(room, job.started_at)
        entry = {"kind": "batch", "at": job.started_at, "ended_at": view["ended_at"], "result": result,
                 "name": batch.get("name") or "", "doses": dict(job.doses), "dosed": list(job.dosed),
                 "by": request.get("by")}
        self._settle(room, config, request, result, entry=entry, clear=not left, final=True)
        self._safely(self._send_draws)  # what its doses drew, now that nothing runs

    def _batch_check(self, job):
        """Why this batch must not start, else its doses: [(pump, ml, flow)] in recipe order, each
        recipe mL entity read now (it wins over the recipe's mL; 0 skips the pump), in whole mL."""
        room, config = job.room, job.config
        batch = config["batch"]
        hit = guards.first(self, guards.BATCH, room, None, {"batch": batch}) or guards.first(
            self, guards.CALIBRATING, room, None, {"config": config})
        if hit:
            return guards.Why(hit), None
        pumps = {p["id"]: p for p in config["pumps"]}
        plan = []
        for item in batch.get("recipe") or []:
            line = {"item": item, "pumps": pumps}
            hit = guards.first(self, guards.RECIPE, room, None, line)
            if hit:
                return guards.Why(hit), None
            ml = _whole_ml(line["ml"])
            if ml <= 0:
                continue
            dose = {"pump": line["pump"], "ml": ml, "profile": job.profile}
            hit = guards.first(self, guards.RECIPE_DOSE, room, None, dose)
            if hit:
                return guards.Why(hit), None
            plan.append((dose["pump"], ml, dose["flow"]))
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
    def _watchdog(batch, plan, profile=PROFILE):
        """The hold's wait for a shot + fill timeout + premix + postmix + every dose's capped deadline
        + 10 min, in seconds, with the room's hardware profile."""
        cap = profile["max_dose_s"] + 60
        minutes = (profile["hold_wait_s"] / 60 + float(batch.get("fill_timeout_min") or 20)
                   + float(batch.get("premix_min") or 0) + float(batch.get("postmix_min") or 0) + 10)
        return minutes * 60 + sum(min(ml / flow * 1.25 + 20, cap) for _pump, ml, flow in plan)

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
            if self._mono() - waited >= job.profile["hold_wait_s"]:
                raise _Ended(f"a shot was still running after {job.profile['hold_wait_s'] / 60:g} minutes")
            yield POLL_S
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
        if self._over(job):
            return self._skip(job, "fill", "the tank level reads over its full mark")
        self._begin(job, "fill")
        sensor = batch.get("full_entity")
        if full is None:
            self._fill_alert(job, "the batch tank did not fill",
                             f"The controller cannot read {sensor}, so it did not open the fill valve.")
            raise _Ended("the tank's full sensor can't be read")
        minutes = float(batch.get("fill_timeout_min") or 20)
        open_s, blind_s = job.profile["fill_open_s"], job.profile["full_blind_s"]
        self._on(job, valve)
        began = self._mono()
        if self._confirm([valve], "on", open_s):
            stuck = self._switch_off([valve])
            self._fill_alert(job, "the batch tank did not fill",
                             f"The fill valve ({valve}) did not open. It did not read on within "
                             f"{open_s:.0f} s. The controller set it to off"
                             + (", but it still does not read off. Close it by hand now." if stuck else "."))
            raise _Ended("the fill valve did not open")
        filled, blind, why = False, None, None
        while True:
            state = self._full(batch)
            now = self._mono()
            if state or self._over(job):
                filled = True
                break
            if state is None:
                blind = now if blind is None else blind
                if now - blind >= blind_s:
                    why = "the full sensor stopped reporting"
                    break
            else:
                blind = None
            if now - began >= minutes * 60:
                why = f"the tank did not read full within {minutes:g} min"
                break
            self._check(job)
            yield POLL_S
        stuck = self._switch_off([valve])  # always closed, and read back
        closed = ("The controller set it to off, but it still does not read off. Close it by hand now."
                  if stuck else "The controller set the fill valve to off.")
        if why == "the full sensor stopped reporting":
            self._fill_alert(job, "the batch tank did not fill",
                             f"The full sensor stopped its reports. {sensor} gave no usable reading for "
                             f"{blind_s:.0f} s while the fill valve ({valve}) was open. {closed}")
            raise _Ended(why)
        if not filled:
            self._fill_alert(job, "the batch tank did not fill in time",
                             f"The fill valve ({valve}) was open for {minutes:g} min, and {sensor} "
                             f"did not read {batch.get('full_state') or 'on'}. {closed}")
            raise _Ended(why)
        if stuck:
            raise _Ended(f"{valve} did not read off after filling")
        self._done(job)
        filled_hook = getattr(self.c, "_tank_estimate_filled", None)  # the estimated tank level counts again
        if filled_hook is not None:
            try:
                filled_hook(job.room)
            except Exception as e:
                self._log("dosing: the estimated tank level could not be reset", job.room.slug, e)

    def _over(self, job):
        """The overfill guard (Controller._tank_over): the room's mapped tank level reads over its full mark, so the
        fill valve is not opened, or is closed. False with no level mapped, or when it can't be asked."""
        over = getattr(self.c, "_tank_over", None)
        try:
            return over is not None and over(job.room) is True
        except Exception as e:
            self._log("dosing: the overfill guard could not be read", job.room.slug, e)
            return False

    def _fill_alert(self, job, title, what):
        self._alert(job.room.slug, "CS-804", title,
                    f"The batch could not fill the tank. {what} The batch stops here. Check the water "
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
            self._mix_alert(job, pump, f"The controller started the mix pump ({pump}), but it does not read on")
            raise _Ended(f"the mix pump ({pump}) did not read on")
        watts, sensor = float(batch.get("mix_min_w") or 0), batch.get("mix_power_sensor")
        if watts > 0 and sensor:
            began, within = self._mono(), job.profile["mix_power_s"]
            while True:
                drawn, reading, unit = self._device(sensor, "power")
                if drawn is not None and drawn >= watts:
                    break
                if self._mono() - began >= within:
                    self._mix_alert(job, pump, f"The controller started the mix pump ({pump}), but {sensor} did "
                                    f"not read {watts:g} W within {within:.0f} s (it reads "
                                    f"{reading}{f' {unit}' if unit else ''})")
                    raise _Ended(f"the mix pump did not draw {watts:g} W within {within:.0f} s")
                self._check(job)
                yield READ_S
        self._done(job)

    def _mix_alert(self, job, pump, what):
        self._send_off(pump)  # before the alert, whose push can take a while; the batch's end reads it back
        self._alert(job.room.slug, "CS-805", "the mix pump did not start",
                    f"{what}. The batch stops here, and the controller sets the mix pump and the mix valves "
                    "to off. Check the pump and its power sensor. Make sure that the mix valves open.",
                    _event(job.started_at))

    def _pause(self, job, step, minutes):
        minutes = float(minutes or 0)
        if minutes <= 0:
            return self._skip(job, step, "0 min")
        self._begin(job, step)
        end = self._mono() + minutes * 60
        while self._mono() < end:
            self._check(job)
            yield max(0.0, min(POLL_S, end - self._mono()))
        self._done(job)

    def _doses(self, job, plan):
        if not plan:
            return self._skip(job, "dose", "nothing to dose")
        self._begin(job, "dose")
        for pump, ml, _flow in plan:
            with self._lock:
                self._live_of(job.room)["batch"]["pump"] = pump["id"]
            result = yield from self._dose(job, pump, ml)
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
            self._alert(job.room.slug, "CS-806", "the end time of a finished batch was not recorded",
                        f"The batch finished, but the controller could not write its end time to {stamp}. "
                        "The stock tanks count batches from this time. So this batch is not taken off the "
                        "stock tanks that have no link to a dosing pump. Record it by hand (Stock tanks, "
                        f"Record a batch). Check {stamp}.", _event("stamp", job.started_at))
        hold = batch.get("hold_entity")
        hold_left = self._switch_off([hold]) if hold else []
        if hold_left:
            self._alert(job.room.slug, "CS-806", "the hold of a finished batch did not release",
                        f"The batch finished, but its hold ({hold}) does not read off. The rooms that it "
                        "held stay held, and the controller sends the off again each 2 s until it reads off. "
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
        dosed = ", ".join(f"{_fmt(d['given'])} mL of {d['name']}" if d["given"] is not None
                          else f"an unknown amount of {d['name']}" for d in job.dosed) or "nothing"
        if stuck:
            after = (f", but {_still(stuck)}. The rooms that the batch held stay held"
                     + (", and its hold stays on," if hold else "")
                     + " until they read off. The controller sends the off again each 2 s.")
        elif hold_left:
            after = (f", but its hold ({hold}) does not read off. The rooms that the batch held stay held "
                     "until it reads off.")
        else:
            after = (" and released the hold" if hold else "") + ". The rooms that it held get water again."
        what = _KIND[job.kind]
        self._alert(
            job.room.slug, "CS-806", f"a {what} stopped",
            f"The {what} stopped in its {job.step} step: {reason}. The controller set the power of each "
            f"dosing pump, the fill valve, the mix pump and the mix valves to off{after}"
            f" Dosed before the stop: {dosed}. Check the tank before the next batch.",
            _event(job.started_at),
        )
        self._log(f"[{job.room.slug}] dosing: {what} stopped in {job.step}: {reason}")
        return stuck, hold_left

    def _check(self, job, catch=False):
        """End the batch now if it must: the app stopping, Home Assistant refusing the token, a stop
        request (read now when `catch`, rather than at the next pass), or its watchdog."""
        if self._exiting:
            raise _Exit()
        if self._refused():
            raise _Refused()
        if catch:
            self._catch_stop(job)
        if job.stopped:
            raise _Ended(self._stop_reason(job))
        if self._late(job):
            raise _Ended("it ran past its watchdog")

    def _catch_stop(self, job):
        """A stop (or a pump's stop) for the job's room, read now: before every switch-on, at every step change and
        every tick of a timed run."""
        config = self._config(job.room)
        request = config.get("request") if config else None
        if not (isinstance(request, dict) and request.get("action") in ("stop", "stop_pump")
                and isinstance(request.get("id"), str)):
            return
        with self._lock:
            handled = self._block(job.room)["handled"]
        if request["id"] != handled:
            self._take(job.room, config, request, job)

    def _on(self, job, entity, service=None):
        """Every switch-on (its domain's on service, _actuator), and every start press (`service`), goes
        through here. A stop is read first (and the watchdog checked); then the exit and stop flags
        are checked under the runner lock immediately before the call. A stop signal that lands while
        the call is on its way waits for it (defer_exit), and runs here once it has landed."""
        self._check(job, catch=True)
        with self._lock:
            if self._exiting:
                raise _Exit()
            if self._refused():
                raise _Refused()
            if job.stopped:
                raise _Ended(self._stop_reason(job))
            self._switching = True
        try:
            return self._call(_domain(entity), service or self._actuator(entity)[0], entity_id=entity,
                              timeout=ON_TIMEOUT_S)
        finally:
            with self._lock:
                self._switching = False
                stop, self._exit_pending = self._exit_pending, None
            if stop is not None:
                stop()

    def _late(self, job):
        return job.deadline is not None and self._mono() > job.deadline

    @staticmethod
    def _stop_reason(job):
        return "stop requested" + (f" by {job.stopped_by}" if job.stopped_by else "")

    def _exit_off(self, job):
        """A dose or batch's own way out (the app is stopping, or Home Assistant refuses the token): its
        hardware off at once, each with a QUICK_S timeout and no read-back. The record stays for the next
        start."""
        for entity in self._job_off(job):
            try:
                self._send_off(entity)
            except Exception as e:
                self._log(f"[{job.room.slug}] dosing: could not switch {entity} off on the way out", repr(e))

    # ------------------------------------------------------------------ the mix check
    def _mix_bands(self, room):
        """What a finished batch's tank is checked against: [(quantity, its tank probe, low, high)] for each of
        the room's feed EC and pH probes that is mapped and has a band (a bound of 0 or less is no bound). None when
        a mapped probe's band can't be read (Controller._feed_band): whether there is anything to check can't be known."""
        bands = []
        for quantity, probe in (("ec", getattr(room, "feed_ec_sensor", "")),
                                ("ph", getattr(room, "feed_ph_sensor", ""))):
            if not probe:
                continue
            lo, hi, unread = self.c._feed_band(room, quantity)
            if unread:
                return None
            if lo > 0 or hi > 0:
                bands.append((quantity, probe, lo, hi))
        return bands

    def _plan_mix(self, room, started_at):
        """A finished batch's mix check, due MIX_SETTLE_S from now; none when nothing can check it (no tank
        probe with a band), which also lets go of an older batch's verdict. A band that can't be read plans the
        check: _judge_mix waits for it."""
        due = (self._now() + timedelta(seconds=MIX_SETTLE_S)).isoformat()
        with self._lock:
            self._block(room)["mix"] = ({"batch": started_at, "due": due, "verdict": None}
                                        if self._mix_bands(room) != [] else None)
            self._write()

    def _check_mixes(self):
        """Each room's mix check that is due, read now (never in a room making a batch: it remakes the tank)."""
        for room in list(self.c.rooms):
            with self._lock:
                block = self._doc["rooms"].get(room.slug)
                mix = deepcopy(block.get("mix")) if isinstance(block, dict) else None
                busy = self._job is not None and self._job.room.slug == room.slug
            if not isinstance(mix, dict) or mix.get("verdict") is not None or mix.get("gave_up_at") or busy:
                continue
            due = _aware(mix.get("due"))
            if due is None or self._now() >= due:
                self._judge_mix(room, mix)

    def _judge_mix(self, room, mix):
        """The tank read through the device-unit table and judged: "good" with every reading inside its band,
        else "off target" or "not read" with CS-808. Neither holds watering."""
        bands = self._mix_bands(room)
        if bands is None:  # a band can't be read: judged on a later pass, and until then the batch is not marked good
            live = self._live_of(room)
            if live.get("mix_deferred") != mix.get("batch"):  # said once per batch, not every pass
                live["mix_deferred"] = mix.get("batch")
                self._log(f"[{room.slug}] dosing: mix check of the batch that started {mix.get('batch')} waits: "
                          "the room's feed EC or pH band can't be read")
            return
        config = self._config(room) if bands else None
        if bands and _probe_calibrating(config):  # a probe in its buffer is no tank reading
            due = _aware(mix.get("due"))
            if not isinstance(config, dict) and (due is None or
                                                 (self._now() - due).total_seconds() >= MIX_CONFIG_WAIT_S):
                return self._give_up_mix(room, mix)
            live = self._live_of(room)
            if live.get("mix_calibrating") != mix.get("batch"):
                live["mix_calibrating"] = mix.get("batch")
                why = guards.CALIBRATING_PROBE if config else "the dosing setup can't be read (a calibration may be open)"
                self._log(f"[{room.slug}] dosing: mix check of the batch that started {mix.get('batch')} waits: {why}")
            return
        found, off, unread = {}, [], []
        for quantity, probe, lo, hi in bands:
            value, state, unit = self._device(  # calibrated (Controller._feed_read, R4)
                probe, quantity, keep_unknown=False,
                pick=lambda read, q=quantity, p=probe: self.c._feed_read(room, q, p, read, self._fetch)[1])
            name = {"ec": "EC", "ph": "pH"}[quantity]
            band = f"{_fmt(lo) if lo > 0 else 'no minimum'} to {_fmt(hi) if hi > 0 else 'no maximum'}"
            found[quantity] = value
            if value is None:
                unread.append(f"its {name} probe ({probe}) is not readable (it reads {state}"
                              + (f" {unit}" if unit else "") + ")")
            elif (lo > 0 and value < lo) or (hi > 0 and value > hi):
                off.append(f"its {name} reads {value:g}, outside the feed {name} band of the room ({band})")
        verdict = None if not bands else "not read" if unread else "off target" if off else "good"
        why = "; ".join(unread + off) or None
        with self._lock:
            block = self._block(room)
            if not isinstance(block.get("mix"), dict) or block["mix"].get("batch") != mix.get("batch"):
                return  # a newer batch has replaced it
            block["mix"] = None if verdict is None else {
                **mix, "verdict": verdict, "checked_at": self._now().isoformat(), "why": why, **found}
            for entry in block["history"]:
                if isinstance(entry, dict) and entry.get("kind") == "batch" and entry.get("at") == mix.get("batch"):
                    entry["mix"] = verdict
            self._write()
        self._log(f"[{room.slug}] dosing: mix check of the batch that started {mix.get('batch')}: "
                  f"{verdict or 'nothing to check'}" + (f" ({why})" if why else ""))
        if verdict in ("not read", "off target"):
            self._alert(room.slug, "CS-808",
                        "the mix of a batch was not checked" if unread else "the mix of a batch is outside its band",
                        f"The batch that started {mix.get('batch')} finished. The controller read its tank "
                        f"{MIX_SETTLE_S / 60:g} min after the mix stopped: {why}. The batch is not marked good. "
                        "The controller refuses a batch that an automation asks for until a batch made by hand "
                        "passes this check. The shots continue. Check the tank and its probes. Then correct the "
                        "tank, or make the next batch by hand.",
                        _event("mix", mix.get("batch")))

    def _give_up_mix(self, room, mix):
        """A due mix check whose dosing_config has not been readable (or published) for MIX_CONFIG_WAIT_S: it ends with
        no verdict (gave_up_at), so the batch is never marked good and an automation's next batch stays refused
        (_mix_refuses), and CS-808 says so once."""
        with self._lock:
            block = self._block(room)
            if not isinstance(block.get("mix"), dict) or block["mix"].get("batch") != mix.get("batch"):
                return  # a newer batch has replaced it
            block["mix"] = {**mix, "gave_up_at": self._now().isoformat(),
                            "why": "the dosing setup could not be read"}
            self._write()
        self._log(f"[{room.slug}] dosing: mix check of the batch that started {mix.get('batch')}: not checked, the "
                  f"dosing setup could not be read for {MIX_CONFIG_WAIT_S / 60:g} min")
        self._alert(room.slug, "CS-808", "the mix of a batch was not checked",
                    f"The batch that started {mix.get('batch')} finished, but the controller could not read the dosing "
                    f"setup of the room (sensor.crop_steering_{room.prefix}dosing_config) for "
                    f"{MIX_CONFIG_WAIT_S / 60:g} min after its mix check was due, so it did not read the tank: a feed "
                    "probe calibration may be open. The batch is not marked good. The controller refuses a batch that "
                    "an automation asks for until a batch made by hand passes this check. The shots continue. Check "
                    "the integration and the tank, then make the next batch by hand.",
                    _event("mix", mix.get("batch")))

    def _mix_refuses(self, room):
        """Why a batch an automation asks for is refused: the last batch's mix check failed, or is still due."""
        with self._lock:
            block = self._doc["rooms"].get(room.slug)
            mix = block.get("mix") if isinstance(block, dict) else None
        if not isinstance(mix, dict) or mix.get("verdict") == "good":
            return None
        if mix.get("verdict") is None:
            return "the last batch's mix is not checked yet"
        return f"the last batch's mix check failed ({mix.get('why') or mix.get('verdict')}); make the next batch by hand"

    # ------------------------------------------------------------------ pH auto-correct
    def _ph_block(self, room):
        """The room's pH auto-correct record in dosing_state.json (the caller holds the lock): the day and
        the doses given on it, the latch, and the refusals told today. A file from before it has none."""
        block = self._block(room)
        ph = block.get("ph")
        if not isinstance(ph, dict):
            ph = block["ph"] = {}
        ph.setdefault("day", None)
        ph.setdefault("doses", 0)
        ph.setdefault("latch", None)
        if not isinstance(ph.get("told"), dict):
            ph["told"] = {}
        return ph

    @staticmethod
    def _ph_view(block):
        """What the status shows of pH auto-correct: the doses today and the latch, or None before any."""
        ph = block.get("ph")
        if not isinstance(ph, dict):
            return None
        return {"day": ph.get("day"), "doses": ph.get("doses", 0), "latch": ph.get("latch")}

    def _today(self):
        return self._now().astimezone().date().isoformat()

    def _ph_reading(self, room, probe):
        """The tank's pH now, calibrated (Controller._feed_read, R4), or None: no number, a unit the table refuses, or
        a reading older than ph_correct.PROBE_MAX_AGE_S (or stamped in the future)."""
        read = self.c._feed_read(room, "ph", probe, self._fetch(probe), self._fetch)[1]
        state, attributes = read[0], read[1] or {}
        try:
            number = float(state)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number):
            return None
        stamp = _aware(read[2] if len(read) > 2 else None)
        if stamp is None:
            return None
        age = (self._now() - stamp).total_seconds()
        if age < -60 or age > ph_correct.PROBE_MAX_AGE_S:
            return None
        return self.c._canonical(probe, "ph", number, attributes.get("unit_of_measurement"),
                                 keep_unknown=False)[0]

    def _ph_settings(self, room):
        px = room.prefix
        return {key: ph_correct.setting(self.c._num_or_none(f"number.crop_steering_{px}ph_correct_{key}"), key)
                for key in ph_correct.SETTINGS}

    def _ph_fill(self, config):
        """The tank's last fill stamp (filled_at_entity), which a latch is kept for: a new fill clears it."""
        stamp = config["batch"].get("filled_at_entity")
        return self._state(stamp, quick=True) if stamp else None

    def _ph_tick(self, room, config):
        """pH auto-correct (docs/DOSING.md), once a minute while nothing runs: with the room's switch on and
        its kill switch on, a tank whose probe reads off the room's feed pH band, plausibly and steadily,
        for ph_correct.STEADY_S gets a correction (_run_correct). It never acts while a dose, batch or
        correction runs anywhere, while the room's dosing hardware does not read off, while the room has a
        hardware fault latched or another controller drives it, or while it is locked after a failure."""
        live, now = self._live_of(room), self._mono()
        if live.get("ph_read") is not None and now - live["ph_read"] < ph_correct.READ_EVERY_S:
            return
        live["ph_read"] = now
        watch = live.setdefault("ph_watch", ph_correct.Watch())
        px = room.prefix
        enabled = self._state(f"switch.crop_steering_{px}ph_auto_correct", quick=True)
        if enabled != "on":
            watch.reset()
            if enabled == "off":  # only a definite operator reset clears a fault; an unreadable switch cannot
                self._ph_unlatch(room, "pH auto-correct was switched off")
            return
        with self._lock:
            idle = self._job is None and room.slug not in self._stuck
        if not idle or not self.c._dosing_may_act(room):
            watch.reset()
            return
        probe = getattr(room, "feed_ph_sensor", "")
        lo, hi, unread = self.c._feed_band(room, "ph")
        if not probe or unread or (lo <= 0 and hi <= 0):
            watch.reset()
            return
        hit = guards.first(self, guards.CALIBRATING, room, None, {"config": config})
        if hit:  # held while a calibration is open; the tank is read afresh after it
            watch.reset()
            self._journal_intent(room, "intent.held", guards.Why(hit))
            return
        ph = self._ph_reading(room, probe)
        way = watch.read(ph, lo, hi, now)
        if way is None:
            return
        # Locked until a person switches it off or the tank is filled again (PH_LOCK); what can't correct it is said
        # (PH_SETUP, PH_DOSE: _ph_refuse, CS-809); what is in the way is waited out without a word (PH_WAIT).
        ctx = {"config": config, "way": way}
        for stage, refuses in ((guards.PH_LOCK, False), (guards.PH_SETUP, True), (guards.PH_WAIT, False),
                               (guards.PH_DOSE, True)):
            hit = guards.first(self, stage, room, None, ctx)
            if hit:
                if refuses:
                    self._ph_refuse(room, ph, lo, hi, hit[1])
                self._journal_intent(room, "intent.refused" if refuses else "intent.held", guards.Why(hit))
                return
        pump, fill, s, flow, ml = ctx["pump"], ctx["fill"], ctx["s"], ctx["flow"], ctx["ml"]
        tries = min(int(s["max_tries"]), ctx["left"])
        watch.reset()
        self._log(f"[{room.slug}] dosing: tank pH {ph:g} is off its band ({lo:g} to {hi:g}): correcting with "
                  f"{pump['name']}, {ml} mL at most {tries} times")
        self._start(self._run_correct(room, config, pump, way, ph, ml, flow, tries, s, lo, hi, probe, fill))

    def _ph_refuse(self, room, ph, lo, hi, why):
        """The tank needs correcting and pH auto-correct can't: CS-809, once a day for each reason."""
        today = self._today()
        with self._lock:
            told = self._ph_block(room)["told"]
            if told.get(why) == today:
                return
            told.clear()
            told[why] = today
            self._write()
        self._log(f"[{room.slug}] dosing: pH auto-correct can't correct the tank: {why}")
        self._alert(room.slug, "CS-809", "pH auto-correct can't correct the batch tank",
                    f"The batch tank reads pH {ph:g}, outside the feed pH band of the room ({_fmt(lo)} to "
                    f"{_fmt(hi)}). pH auto-correct is on, but it did not dose: {why}. While the feed pH is "
                    "outside its band, the source-water gate holds the shots of the room. Correct the tank by "
                    "hand, or fix the reason. This alert comes again tomorrow while it lasts.",
                    _event("ph_refused", today))

    def _ph_unlatch(self, room, why):
        with self._lock:
            block = self._doc["rooms"].get(room.slug)
            ph = block.get("ph") if isinstance(block, dict) else None
            if not isinstance(ph, dict) or not ph.get("latch"):
                return
            ph["latch"] = None
            self._write()
        self._log(f"[{room.slug}] dosing: pH auto-correct unlocked: {why}")

    def _ph_count(self, room):
        """One dose pressed: it counts toward the day's doses whatever came of it."""
        today = self._today()
        with self._lock:
            block = self._ph_block(room)
            if block["day"] != today:
                block["day"], block["doses"] = today, 0
            block["doses"] += 1
            self._write()

    def _run_correct(self, room, config, pump, way, ph, ml, flow, tries, s, lo, hi, probe, fill):
        """One correction, always settled: recorded before anything moves; the room held and its tank mixed
        as a batch is (the hold, the close, the mix with its read-back and power check); then up to `tries`
        doses of `ml` through `pump`, each mixed for mix_min and the tank read again (ph_correct.verdict).
        Any end but reaching the band locks pH auto-correct (CS-809); every end switches the mix off and
        releases the hold as a batch does, and what does not read off holds the rooms until it does."""
        job = _Job(room, config, {"id": None, "by": None}, "correct")
        job.pump = pump
        batch = config["batch"]
        held = self._held_rooms(room, batch)
        job.started_at = self._now().isoformat()
        record = {"kind": "correct", "at": job.started_at, "by": None, "off": self._dosing_hardware(config),
                  "hold": batch.get("hold_entity"), "held": sorted(held), "doses": {}}
        if not self._record(job, record, merge=True):
            self._log(f"[{room.slug}] dosing: the pH correction could not be written to dosing_state.json")
            return
        with self._lock:
            self._job = job
            self._live_of(room)["batch"] = {
                "step": "idle", "pump": None, "name": "pH correction", "started_at": job.started_at,
                "step_started_at": None, "steps": [], "result": None, "ended_at": None}
        stuck, hold_left, told, readings, outcome = [], [], True, [ph], None
        try:
            each = min(ml / flow * 1.25 + 20, job.profile["max_dose_s"] + 60) + s["mix_min"] * 60
            job.deadline = (self._mono() + job.profile["hold_wait_s"] + job.profile["mix_power_s"]
                            + tries * each + 600)
            yield from self._hold(job, held)
            self._close(job, held)
            yield from self._mix(job)
            before = ph
            for _ in range(tries):
                self._ph_allowed(job)
                self._begin(job, "dose")
                with self._lock:
                    self._live_of(room)["batch"]["pump"] = pump["id"]
                result = yield from self._dose(job, pump, ml)
                with self._lock:
                    self._live_of(room)["batch"]["pump"] = None
                if not result.startswith("refused"):
                    self._ph_count(room)
                if result != "finished":
                    self._check(job)
                    raise _Ended(f"{pump['name']}: {result}")
                self._done(job)
                yield from self._pause(job, "postmix", s["mix_min"])
                after = self._ph_reading(room, probe)
                readings.append(after)
                outcome = ph_correct.verdict(way, before, after, lo, hi, s["margin"])
                if outcome != "again":
                    break
                before = after
            if outcome == "again":
                outcome = "not enough"
            hold_left = self._ph_finish(job)
            result = "finished: " + {"done": "the tank is inside its band",
                                     "not enough": "the doses did not bring the tank into its band",
                                     "no response": "a dose did not move the pH",
                                     "overshot": "the pH went past the other side of its band",
                                     "not read": "the probe could not be read after the mix"}[outcome]
        except _Exit:
            self._exit_off(job)
            raise
        except Exception as end:  # _Ended, or anything unforeseen: cleaned up as a batch is
            if not isinstance(end, _Ended):
                self._log(f"[{room.slug}] dosing: pH correction error", repr(end))
            reason = str(end) if isinstance(end, _Ended) else f"an error in the controller ({end!r})"
            result = f"stopped: {job.step}: {reason}"
            try:
                stuck, hold_left = self._ended(job, reason)
            except Exception as e:
                self._log(f"[{room.slug}] dosing: pH correction cleanup error", repr(e))
                stuck, told = self._dosing_hardware(config), False
        finally:
            with self._lock:
                self._job = None
        with self._lock:
            view = self._live_of(room)["batch"]
            view.update(step="idle", pump=None, result=result, ended_at=self._now().isoformat())
        if not result.startswith("finished"):
            self._journal(room, lambda: ("batch.failed", _failed(result, "pH correction", None, job.id, job.codes,
                                                                 job.stopped)))
        left = bool(stuck or hold_left)
        if left:
            self._hold_stuck(room, stuck, batch.get("hold_entity"), held, "CS-806", "a pH correction stopped",
                             f"A pH correction that started {job.started_at} ended ({result}).",
                             "Check the tank before the next dose.", _event(job.started_at), alerted=told)
        else:
            with self._lock:
                self._held.pop(room.slug, None)
        shown = [None if v is None else round(v, 2) for v in readings]
        entry = {"kind": "correct", "at": job.started_at, "ended_at": view["ended_at"], "result": result,
                 "doses": dict(job.doses), "dosed": list(job.dosed), "by": None, "ph": shown}
        with self._lock:
            block = self._block(room)
            if not left:
                block["inflight"] = None
            self._add_history(block, entry)
            if outcome != "done":
                self._ph_block(room)["latch"] = {"at": job.started_at, "why": result, "fill": fill}
            self._write()
        self._log(f"[{room.slug}] dosing: pH correction {result} (pH {shown})")
        self._show(room, config)
        if outcome != "done":
            read = ", then ".join("not readable" if v is None else f"{v:g}" for v in shown)
            self._alert(room.slug, "CS-809", "the batch tank's pH was not corrected",
                        f"pH auto-correct started at pH {ph:g}, outside the feed pH band of the room "
                        f"({_fmt(lo)} to {_fmt(hi)}), and dosed {pump['name']}. It stopped: {result}. The pH "
                        f"read {read}. pH auto-correct is now locked for this tank: it doses no more until a "
                        "person switches it off and on again, or the tank is filled again. While the feed pH is "
                        "outside its band, the source-water gate holds the shots of the room. Check the probe, "
                        "the pump and the tank, and correct the tank by hand.",
                        _event("ph", job.started_at))
        self._safely(self._send_draws)

    def _ph_allowed(self, job):
        """Before each dose of a correction: it ends when its switch, the room or the room's kill switch
        went off since it started (no dose is made on its own while a person has stopped the room)."""
        room = job.room
        if self._state(f"switch.crop_steering_{room.prefix}ph_auto_correct") != "on":
            raise _Ended("pH auto-correct was switched off")
        if not self.c._dosing_may_act(room):
            raise _Ended("the room or its kill switch was switched off")

    def _ph_finish(self, job):
        """The end of a correction: the mix pump off and its valves closed (read back), then the hold
        released (read back) -> the hold when it does not read off."""
        batch = job.config["batch"]
        self._begin(job, "finish")
        stuck = self._switch_off([batch.get("mix_pump"), *(batch.get("mix_valves") or [])])
        if stuck:
            raise _Ended(f"{', '.join(stuck)} did not read off")
        hold = batch.get("hold_entity")
        hold_left = self._switch_off([hold]) if hold else []
        self._done(job)
        return hold_left

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
        hold = record.get("hold") if kind in ("batch", "correct") and isinstance(record.get("hold"), str) else None
        held = {s for s in record.get("held") or [] if isinstance(s, str)} | {slug}
        at = record.get("at")
        if kind in _RECORDED:
            intro = (f"A {_KIND[kind]} that started {at} was still running when the controller stopped. It did "
                     "not finish, and the controller does not continue it. The controller set the power of "
                     "its dosing pumps, the fill valve, the mix pump and the mix valves to off"
                     + (". It releases the hold when they read off." if hold else "."))
            advice = ("Check the tank, because it contains what the controller dosed before the stop. Dose "
                      "the remaining volume by hand, or make a new batch.")
        else:  # swept after a corrupt dosing_state.json
            intro = ("The controller could not read dosing_state.json. It set the power of the dosing pumps, "
                     "the fill valve, the mix pump and the mix valves of this room to off.")
            advice = "Check the batch tank before the next dose."
        self._held[slug] = held
        self._stuck[slug] = self._entry(off, hold, held, "CS-803", "a restart stopped a dose or batch",
                                        _event("restart", at), intro, advice, alerted=None,
                                        announce=kind in _RECORDED, sent=False)
        if kind in _RECORDED and not record.get("recovered"):
            dosed = [d for d in record.get("dosed") or [] if isinstance(d, dict)]
            dose = record.get("dose")
            if isinstance(dose, dict) and not any(d.get("at") == dose.get("at") for d in dosed):
                # the dose the stop cut: how much it gave is not known
                dosed.append({"pump": dose.get("pump"), "name": dose.get("name") or dose.get("pump"),
                              "ml": dose.get("ml"), "given": None, "result": "interrupted by a restart",
                              "at": dose.get("at")})
            entry = {"kind": kind, "at": at, "ended_at": self._now().isoformat(),
                     "result": "interrupted by a restart", "doses": record.get("doses") or {},
                     "dosed": dosed, "by": record.get("by")}
            if kind == "batch":
                entry["name"] = record.get("name") or ""
            if kind in TIMED_S and isinstance(record.get("request"), str):  # its report: ran_s not known
                self._answer(block, record["request"], self._timed_report(
                    {"id": record["request"], "action": kind, "pump": record.get("pump")}, 0, "stopped"),
                    latest=block.get("handled") == record["request"])
            self._add_history(block, entry)
            self._recovered_rows.append((slug, entry))
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
            state = self._hw_state(entity, quick=True)
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
            tail = (f"{_still(left)}. The shots stay held in the rooms that it holds, and the controller "
                    "sends the off again each 2 s until it reads off. Check it. If it still runs, stop it "
                    "by hand.")
        else:
            tail = ("All the hardware now reads off" + (", and the controller released the hold" if entry["hold"]
                                                        else "")
                    + ". The shots continue.")
        return f"{entry['intro']} {tail} {entry['advice']}"

    # ------------------------------------------------------------------ alerts
    def _alert(self, slug, code, title, message, event):
        """An alert for one event (docs/DOSING.md, Alerts), kept in dosing_state.json until Home
        Assistant has it: tried now, and again with the chores until it is created. A newer one for
        the same event replaces one still waiting."""
        item = {"slug": slug, "code": code, "title": title, "message": message, "event": event}
        with self._lock:
            job = self._job
            if job is not None and job.room.slug == slug:
                job.codes.append(code)  # for its batch.failed
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
        # A local append: it can wait briefly on Outbox._lock while a flush rewrites the outbox, never longer.
        self._journal_step(job, step, "running")
        self._show(job.room, job.config)
        self._check(job, catch=True)  # a stop is looked for at every step

    def _done(self, job):
        with self._lock:
            last = self._live_of(job.room)["batch"]["steps"][-1]
            last["state"] = "done"
        self._journal_step(job, last["step"], "done")  # may wait briefly on Outbox._lock during a flush
        self._show(job.room, job.config)

    def _skip(self, job, step, note):
        job.step = step
        with self._lock:
            self._live_of(job.room)["batch"]["steps"].append(
                {"step": step, "state": "skipped", "at": self._now().isoformat(), "note": note})
        self._journal_step(job, step, "skipped")  # may wait briefly on Outbox._lock during a flush
        self._show(job.room, job.config)
        self._check(job, catch=True)

    # ------------------------------------------------------------------ the journal
    def _journal(self, room, make):
        """One event to the controller's journal outbox (journal_out.Outbox.emit), `make()` -> (kind, its keywords):
        built and appended locally, never a wait, and an error anywhere in it is only logged. Nothing a dose or batch
        does waits on it or changes with it. -> whether it was appended."""
        journal = getattr(self.c, "journal", None)
        if journal is None:
            return False
        try:
            kind, kw = make()
            journal.emit(getattr(room, "prefix", ""), kind, **kw)
        except Exception as e:
            self._log("dosing: journal error", repr(e))
            return False
        return True

    def _journal_intent(self, room, kind, why, job=None):
        """intent.refused / intent.held {guard, reason} for a dose, batch or pH correction a guard stopped (`why` a
        guards.Why; words with no guard are not journaled), with the guard's code. Once per (room, guard, words without
        their numbers, job) and again each INTENT_REEMIT_S while it stands, as the controller's _journal_held: each
        request refused is journaled, a refusal the pH tick meets each minute every 30 min. An error is only logged."""
        guard = getattr(why, "guard", None)
        if guard is None:
            return
        try:
            now, seen = self._mono(), self._intents
            for key in [k for k, at in seen.items() if not 0 <= now - at < INTENT_REEMIT_S]:
                del seen[key]  # a stale one, and so the keys never grow
            key = (room.slug, kind, guard, _NUMBERS.sub("#", str(why)), job.id if job is not None else None)
            if key in seen:
                return
        except Exception as e:
            self._log("dosing: journal error", repr(e))
            return

        def make():
            by = job.request.get("by") if job is not None else None
            batch_id = job.id if job is not None and job.kind != "dose" else None
            return kind, {"outcome": "refused" if kind == "intent.refused" else "held", "code": why.code,
                          "actor": _actor(by), "detail": by,
                          "correlation": {"batch_id": batch_id} if batch_id else None,
                          "data": {"guard": guard, "reason": str(why)}}

        if self._journal(room, make):  # kept only once it is in the outbox, so a failed one is tried again
            seen[key] = now

    def journal_recovered(self):
        """The rows a restart interrupted (_recover_record), to the journal, on every start that finds one, once its
        room is known (the controller calls this after each pass). Ids derived as the backfill's: one event each."""
        with self._lock:
            rows, self._recovered_rows = self._recovered_rows, []
        keep = []
        for slug, entry in rows:
            room = next((r for r in list(self.c.rooms) if r.slug == slug), None)
            if room is None:
                keep.append((slug, entry))
                continue
            for kind, kw in history_events(slug, [entry]):
                self._journal(room, lambda kind=kind, kw=kw: (kind, kw))
        if keep:
            with self._lock:
                self._recovered_rows = (keep + self._recovered_rows)[-HISTORY:]

    def _journal_step(self, job, step, state):
        """batch.step for a batch's (or pH correction's) step, with the job's id as its batch_id."""

        def make():
            with self._lock:
                name = self._live_of(job.room)["batch"].get("name") or ""
            by = job.request.get("by")
            return "batch.step", {"actor": _actor(by), "detail": by, "correlation": {"batch_id": job.id},
                                  "data": {"step": step, "state": state, "recipe": name}}

        self._journal(job.room, make)

    # ------------------------------------------------------------------ status
    def _live_of(self, room):
        with self._lock:
            return self._live.setdefault(room.slug, {
                "readings": {}, "refreshed": None, "revision": None, "published": None,
                "published_at": None, "remind_read": None, "remind_low": 0,
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
                "flow": self._flow(pump, quick=True)[0],
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
                 else "batch" if job.kind in ("batch", "correct") else "dosing")
        return state, {
            "pumps": pumps,
            # the pumps whose setup can't be read: each refused, the others working (_config)
            "unreadable_pumps": [p.get("id") if isinstance(p, dict) else None
                                 for p in (config.get("unreadable") or () if config else ())],
            "batch": batch,
            "handled": block["handled"],
            "handled_result": block["handled_result"],
            "handled_results": block["handled_results"],
            "history": block["history"],
            "mix": block.get("mix") if isinstance(block.get("mix"), dict) else None,
            "last_batch": block["last_batch"],
            "ph_correct": self._ph_view(block),
            "friendly_name": "Dosing (controller)",
        }

    # ------------------------------------------------------------------ reading Home Assistant
    def _config(self, room):
        """The room's dosing setup as the integration publishes it: None with no dosing_config at all
        (an integration from before dosing), False when it can't be read (never acted on), else
        {"revision", "pumps", "unreadable", "batch", "request", "profile"}. A pump that can't be read is left out
        of `pumps` and kept in `unreadable`: a request for it is refused (_no_pump) and a stop still switches its
        power off (_unreadable_powers), while the room's other pumps work as before."""
        state, attributes, _updated = self._get(f"sensor.crop_steering_{room.prefix}dosing_config")
        if state is None:
            return None
        if str(state).strip().lower() in DEAD or not isinstance(attributes, dict):
            return False
        pumps, batch = attributes.get("pumps"), attributes.get("batch")
        if not (isinstance(pumps, list) and isinstance(batch, dict) and self._batch_readable(batch)):
            return False
        return {"revision": state, "pumps": [p for p in pumps if self._pump_readable(p)],
                "unreadable": [p for p in pumps if not self._pump_readable(p)],
                "batch": batch, "request": attributes.get("request"),
                "profile": attributes.get("profile"), "calibrating": attributes.get("calibrating")}

    @staticmethod
    def _pump_readable(pump):
        """Every entity named, and max_ml; the flow entity may be left out only for a pump with a calibrated flow."""
        return isinstance(pump, dict) and all(
            isinstance(pump.get(key), str) and pump[key]
            for key in ("id", "name", "volume_entity", "start_entity", "dosing_entity", "power_entity")
        ) and (isinstance(pump.get("flow_entity"), str) and bool(pump["flow_entity"])
               or not pump.get("flow_entity") and _ml_s(pump.get("calibrated_ml_min")) is not None
               ) and isinstance(pump.get("max_ml"), (int, float))

    @staticmethod
    def _no_pump(config, pump_id):
        """The refusal of a request for a pump `config` has none of: its setup can't be read, or there is none."""
        if any(isinstance(p, dict) and p.get("id") == pump_id for p in config.get("unreadable") or ()):
            return f"refused: the setup of pump {pump_id} can't be read"
        return f"refused: there is no pump {pump_id} in this room's setup"

    @staticmethod
    def _unreadable_powers(config, pump_id=None):
        """The power switches the room's unreadable pumps (or the one `pump_id`) name: a stop still switches them off."""
        return [p["power_entity"] for p in config.get("unreadable") or ()
                if isinstance(p, dict) and isinstance(p.get("power_entity"), str) and "." in p["power_entity"]
                and (pump_id is None or p.get("id") == pump_id)]

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

    def _device(self, entity, quantity, quick=False, keep_unknown=True, pick=None):
        """One read of a dosing device's number (a pump's volume or flow, a recipe amount, the mix pump's
        power, a tank probe) through the device-unit table (Controller._canonical) -> (the number in the
        quantity's canonical unit, mL, mL/s, W, mS/cm or pH, or None; the state as read; its unit). A unit
        the table does not know, or none, is read in that unit as it always was, never set aside: a dose
        is refused all the same for an uncalibrated flow, more than max_ml, more than MAX_DOSE_S and a
        volume that does not read back. `keep_unknown=False` (a tank probe): such a unit is read only
        while plausible, and a refused one (ppm) not at all. `pick(read)`: the read to use instead of `entity`'s
        own (a calibrated feed probe, Controller._feed_read)."""
        read = self._fetch(entity, quick)
        read = read if pick is None else pick(read)
        state, unit = read[0], (read[1] or {}).get("unit_of_measurement")
        state = None if state is None else str(state)
        try:
            number = float(state)
        except (TypeError, ValueError):
            return None, state, unit
        if not math.isfinite(number):
            return None, state, unit
        return self.c._canonical(entity, quantity, number, unit, keep_unknown=keep_unknown)[0], state, unit

    def _actuator(self, entity):
        """(on service, off service, on state, off state) for dosing hardware: its domain's row in the
        actuator table, so a valve opens and closes; any other domain is switched turn_on / turn_off and
        read back on / off, as dosing always drove it (a light or fan relay works)."""
        return self._actuators.get(_domain(entity), ("turn_on", "turn_off", "on", "off"))

    def _hw_state(self, entity, quick=False):
        """Dosing hardware's state in on/off words: its domain's on state reads "on", its off state "off"."""
        state = self._state(entity, quick)
        if state is None:
            return None
        row = self._actuator(entity)
        return {row[2]: "on", row[3]: "off"}.get(state, state)

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

    @classmethod
    def _dosing_hardware(cls, config):
        """What a stop, an interrupted batch or a restart switches off: every pump's power (an unreadable pump's
        too), then the fill valve, the mix pump and the mix valves."""
        batch = config["batch"]
        return [e for e in (*(p["power_entity"] for p in config["pumps"]), *cls._unreadable_powers(config),
                            batch.get("fill_valve"),
                            batch.get("mix_pump"), *(batch.get("mix_valves") or [])) if e]

    # ------------------------------------------------------------------ switching, with read-back
    def _switch_off(self, entities):
        """Switch these off, read them back, re-send once to what does not read off -> whatever still
        does not (empty when every one reads off). The off is sent whatever a switch reads: a stale
        OFF must never be the reason a pump or valve was not told."""
        entities = [e for e in dict.fromkeys(entities) if e]
        for e in entities:
            self._call(_domain(e), self._actuator(e)[1], entity_id=e)
        stuck = self._confirm(entities, "off")
        for e in stuck:
            self._call(_domain(e), self._actuator(e)[1], entity_id=e)
        return self._confirm(stuck, "off")

    def _send_off(self, entity, timeout=QUICK_S):
        """An off with a QUICK_S timeout and no read-back -> whether Home Assistant took it."""
        return self._call(_domain(entity), self._actuator(entity)[1], entity_id=entity, timeout=timeout)

    def _confirm(self, entities, want, timeout=None):
        """Read these back until each reads `want` ("on" or "off", _hw_state): first at 1 s, then every
        0.5 s up to `timeout` (CONFIRM_TIMEOUT_S) -> the ones that don't."""
        if not entities:
            return []
        timeout = CONFIRM_TIMEOUT_S if timeout is None else timeout
        deadline = self._mono() + timeout
        self._sleep(min(CONFIRM_FIRST_S, timeout))
        while True:
            left = [e for e in entities if self._hw_state(e) != want]
            if not left or self._mono() >= deadline:
                return left
            self._sleep(CONFIRM_POLL_S)

    def _set_volume(self, entity, ml):
        """Set a pump's volume number to `ml` mL in the number's own unit (0.1 for 100 mL in L) and read
        it back -> whether it reads `ml` mL again."""
        unit = self._device(entity, "volume")[2]
        per_unit = self.c._canonical(entity, "volume", 1.0, unit, keep_unknown=True)[0]  # mL in one of it
        self._call(_domain(entity), "set_value", entity_id=entity, value=ml if per_unit == 1 else ml / per_unit)
        return self._confirm_value(entity, ml)

    def _confirm_value(self, entity, ml):
        deadline = self._mono() + CONFIRM_TIMEOUT_S
        self._sleep(CONFIRM_FIRST_S)
        while True:
            read = self._device(entity, "volume")[0]
            if read is not None and abs(read - ml) <= VOLUME_TOLERANCE_ML:
                return True
            if self._mono() >= deadline:
                return False
            self._sleep(CONFIRM_POLL_S)

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
        the dose or batch in flight, each pump's last dose, the last batch, the history, the stock
        draws not yet delivered and the volume numbers still to put back."""
        slug = getattr(room, "slug", room)
        block = self._doc["rooms"].get(slug)
        if not isinstance(block, dict):
            block = self._doc["rooms"][slug] = {}
        for key, default in (("handled", None), ("handled_result", None), ("inflight", None),
                             ("last_batch", None)):
            block.setdefault(key, default)
        for key in ("history", "draws", "restores"):
            if not isinstance(block.get(key), list):
                block[key] = []
        if not isinstance(block.get("last"), dict):
            block["last"] = {}
        if not isinstance(block.get("handled_results"), dict):
            block["handled_results"] = {}
        return block

    @staticmethod
    def _answer(block, request_id, result, latest=True):
        """A request's answer, kept by its id in handled_results (the last ANSWERS), so a later request never takes
        it away (the integration reads a timed run's report by its id); `latest`: it is also handled and
        handled_result, the request handled last, as every reader had them."""
        answers = block["handled_results"]
        answers.pop(request_id, None)
        answers[request_id] = result
        for old in list(answers)[:-ANSWERS]:
            del answers[old]
        if latest:
            block["handled"], block["handled_result"] = request_id, result

    @staticmethod
    def _add_history(block, entry):
        block["history"] = [entry, *block["history"]][:HISTORY]
        if entry.get("kind") == "batch":
            block["last_batch"] = entry  # named, and kept past the history's last 20

    def _record(self, job, fields, merge=False):
        """What is about to move, saved before it moves. A new record also takes the job's request, in
        the same write; one added to (a batch's next dose) leaves alone any request answered since."""
        with self._lock:
            block = self._block(job.room)
            record = dict(block["inflight"] or {}) if merge else {}
            record.update(fields)
            block["inflight"] = record
            if not merge:
                self._answer(block, job.request["id"], _RUNNING[job.kind])
            return self._write()

    def _settle(self, room, config, request, result, entry=None, clear=False, final=False):
        """A request handled: its id and result saved (and the record of what ran cleared) and shown.
        `final`: the end of the dose or batch it started, which leaves a request handled since (a stop,
        a refusal) as the one shown, so none is ever taken twice."""
        if request.get("action") in TIMED_S and not isinstance(result, dict):
            result = self._timed_report(request, 0, result)  # the integration waits for this shape
        with self._lock:
            block = self._block(room)
            # A final answer to a request handled before others (a stop, a refusal) is kept by its id only.
            self._answer(block, request["id"], result, latest=not final or block["handled"] == request["id"])
            if clear:
                block["inflight"] = None
            if entry is not None:
                self._add_history(block, entry)
            self._write()
        self._log(f"[{room.slug}] dosing: {request.get('action')} request: {result}")
        self._show(room, config)
        return result
