"""The plan task (docs/GROW_PLANS.md, "How the controller checks the plan is running"): under the Claude Haiku brain
only, the brain is asked what the most important drift code found between the grower's plan and the room means.

It advises and nothing else: its answer picks which of the drift's code-written suggestions the panel shows
(plan_adherence.PICK), and a key a drift does not accept is no answer. Code found the drift and worked out every
fact it is shown; a CS-713 card is raised by code whatever the brain says, or whether it is asked at all. Built like
the Feed task: a room task outside Brain, with its own "_brain" key.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import plan_adherence

from . import council
from .doctrine import doctrine
from .judges.base import choice, noul, with_doctrine

FIRM = 0.6
ASKS_PER_DAY = 4  # asks a room may make a photoperiod, second looks apart
AFTER_MIN = 30.0  # first asked this long after lights-on, once the day has had its chance to move on
EVERY_H = 6.0  # asked again this often while the same drift lasts
DEBOUNCE_MIN = 10.0  # a drift of a new class is asked about once it has lasted this long

CAUSE = {
    "deliberate_change": "Someone changed a setting on purpose; the plan, not the setting, should change to match.",
    "plan_out_of_date": "The plan no longer fits the room (its dates, zones or the run have moved on) and needs the "
                        "grower.",
    "reading_holds_plan": "A missing or frozen reading is holding the plan back; the plan itself is fine.",
    "settings_disagree": "A setting outside the plan (the steering select, the lights hours) disagrees with it, and "
                         "the plan is right.",
    "no_effect_today": "The drift is real but changes nothing about today's watering.",
    "insufficient_evidence": "The facts do not support any of the other answers.",
}

QUESTIONS = with_doctrine({
    "cause": [
        choice("You are checking whether one room is running the grow plan its grower chose. Code found the drift "
               "described under plan_drift and has already worked out the facts below it. Say what the drift most "
               "likely means for the grower. Judge only from the facts given.", CAUSE),
        choice("A grow plan sets this room's targets day by day. Something in the room is not running as the plan "
               "says (see plan_drift). Which of these best explains it?", CAUSE),
    ],
}, doctrine("closed_loop", limit=3))

KEEP_YES = ("The reading that stopped the plan moving on is one this zone needs to be watered safely on today's "
            "targets, so the zone should stay on yesterday's targets until it is back.")
KEEP_NO = "The engine waters this zone safely without that reading, so today's targets can apply now."
KEEP = with_doctrine({
    "keep_yesterday": [
        noul("The plan has not moved on to today because of the reading named under why_not_moved_on. Is that "
             "reading a reason to keep yesterday's targets in force today?", KEEP_YES, KEEP_NO),
        noul("Today's plan day changes the targets listed under change_today, but it has not been applied because "
             "of the reading under why_not_moved_on. Should the zone stay on yesterday's targets until that reading "
             "is back?", KEEP_YES, KEEP_NO),
    ],
}, doctrine("closed_loop", limit=3))
KEEP_FIRM = 0.7  # both phrasings below 0.5 and their average p_yes at most 0.3
BRIDGE_CLASSES = ("transition_missed", "armed_not_started")
STRICT_WITHIN_MIN = 45.0  # on the stricter gate, a second firm "no" within this long of the first

ALLOWED_KEYS = {cls: tuple(keys) for cls, keys in plan_adherence.PICK.items()}


def catch_up_says_no(verdict):
    """True on a firm "no": both phrasings answered and below 0.5, averaging a p_yes of 0.3 or less."""
    return verdict is not None and verdict.label is False and verdict.firm(KEEP_FIRM)


def pick(verdict, drift):
    """(index of the suggestion to show, the brain's rationale) for a drift: the answer's when it is firm and the
    drift accepts it, else (0, "") (the drift's own first suggestion)."""
    if verdict is None or not verdict.firm(FIRM) or verdict.label not in ALLOWED_KEYS.get(drift.cls, ()):
        return 0, ""
    return plan_adherence.PICK[drift.cls][verdict.label], (verdict.notes or [""])[0]


def unsure(verdict):
    return verdict is None or verdict.n < 2 or not verdict.agreed or verdict.prob < FIRM


def evidence(view, drift, extra=None):
    """What the brain is shown about one drift: code's sentences, no entity id, no number it would have to compute."""
    rows = view.in_force()
    zones = []
    for z in sorted(rows):
        zp = plan_adherence.zone_plan(view, z)
        if not isinstance(zp["day"], int):
            continue
        words = f"{view.titles.get(z) or f'zone {z}'}: day {zp['day']}"
        if zp["of_days"]:
            words += f" of {zp['of_days']}"
        if zp["week"]:
            words += f" (week {zp['week']})"
        if zp["profile"]:
            words += f", profile '{zp['profile']}'"
        if zp["steering_pct"] is not None:
            words += f" at {zp['steering_pct']:g} % generative"
        nxt = zp["next_change"]
        words += (f". Next change on day {nxt['day']}, in {nxt['in_days']} days, to '{nxt['profile']}'." if nxt
                  else ".")
        zones.append(words)
    status = view.status
    applied = view.attrs.get("grow_day")
    out = {
        "plan_status": f"{status}, revision {view.attrs.get('revision')}"
                       + (f"; applied day: {applied}" if applied else "")
                       + f"; today's grow-day began at the lights-on of {view.expected_day.isoformat()}.",
        "plan_today": zones or "no zone has a plan day in force",
        "plan_drift": drift.facts or drift.line,
        "phase_today": {f"zone {z}": [f"{e.get('at', '')[11:16]} {e.get('from') or '?'} -> {e.get('to')}"
                                     f" ({e.get('how')})" for e in log]
                        for z, log in sorted(((extra or {}).get("phase_log") or {}).items())} or "not recorded",
    }
    if drift.cls in ("transition_missed", "armed_not_started"):
        out["why_not_moved_on"] = view.attrs.get("degraded_reason") or "the plan has not said why"
        out["engine_without_it"] = ("Without a moisture reading a zone is watered on its sibling's shots or a timer; "
                                    "without a root-zone EC reading it is watered by moisture alone, with EC sizing "
                                    "and salt checks paused.")
    if drift.cls in BRIDGE_CLASSES and drift.extra.get("zones"):
        out["change_today"] = drift.line
    if drift.cls == "steering_disagrees":
        out["steering_select"] = drift.line
    for key, value in (extra or {}).items():
        if key != "phase_log" and value:
            out[key] = value
    return out


class PlanTask:
    """One room's asks: what is asked, when, and the answer read once. `meta(room, now)` is the "_brain" key."""

    def __init__(self, asker, meta):
        self.asker, self.meta = asker, meta
        self.rooms: dict[str, dict] = {}

    def record(self, room, day):
        rec = self.rooms.get(room)
        if rec is None or rec["day"] != day:
            rec = self.rooms[room] = {"room": room, "day": day, "asks": 0, "last": None, "asked_at": None, "cls": None,
                                      "seen": {}, "read_seq": None, "notes": {}, "reasked": False,
                                      "reask_due": False, "drift": None}
        return rec

    def due(self, rec, drift, now, lights_on_at):
        """Whether the room may be asked about `drift` now (the caller has checked the brain may ask at all)."""
        if self.asker.pending(self.key(rec)):
            return False
        if rec["reask_due"] and not rec["reasked"]:
            return True
        if rec["asks"] >= ASKS_PER_DAY or lights_on_at is None or now < lights_on_at + timedelta(minutes=AFTER_MIN):
            return False
        first = rec["seen"].setdefault(drift.cls, now)
        if now - first < timedelta(minutes=DEBOUNCE_MIN):
            return False
        if rec["cls"] != drift.cls:
            return True
        return rec["last"] is None or now - rec["last"] >= timedelta(hours=EVERY_H)

    @staticmethod
    def key(rec):
        return f"plan:{rec['room']}"

    def ask(self, rec, state, questions, now):
        at = self.asker.clock()
        if not self.asker.submit(self.key(rec), dict(state, _brain=self.meta(rec["room"], now)),
                                 council.expand(questions)):
            return False
        second = rec["reask_due"] and not rec["reasked"]
        rec.update(asked_at=at, last=now, reask_due=False)
        if second:
            rec["reasked"] = True
        else:
            rec["asks"] += 1
        return True

    def answer(self, rec):
        """The newest answer to this room's ask, once, when it has come in; else None."""
        if rec.get("asked_at") is None:
            return None
        ans = self.asker.result(self.key(rec))
        if ans is None or ans.at < rec["asked_at"] or ans.seq == rec["read_seq"]:
            return None
        rec["read_seq"] = ans.seq
        return ans


@dataclass
class PlanContext:
    """The room as the envelope's catch_up branch reads it (envelope._admit_catch_up): code's facts, never the
    brain's. Days are ISO dates; times local and naive, like the controller's."""

    now: datetime
    status: str | None = None
    required: bool = False
    error: str | None = None
    managed: tuple = ()
    room_zones: tuple = ()
    revision: int | None = None
    expected_day: str | None = None
    in_force_days: dict = field(default_factory=dict)  # {zone: the date whose targets are in force}
    parameters: dict = field(default_factory=dict)  # {zone: the targets in force}
    preview: dict = field(default_factory=dict)  # {zone: today's preview row}
    degraded_kind: str | None = None
    degraded_since: datetime | None = None
    lights_on: bool = False
    lights_on_at: datetime | None = None
    lights_off_at: datetime | None = None
    busy: bool = False
    room_hold: str | None = None
    health: str = "ok"
    no_touch: bool = False
    cooldown_until: datetime | None = None
    bridge_day: str | None = None
    powers: dict | None = None  # the room's AI powers (jev.powers): catch-up needs plan_catch_up
    snap: object = None  # what admit() reads of a zone context: a room has none
    params: object = None
