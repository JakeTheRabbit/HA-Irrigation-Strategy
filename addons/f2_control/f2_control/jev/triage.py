"""Which alerts are worth a phone push (the Alerts judge, docs/JEV.md).

The base controller pushes every alert to the phone like a critical fault, every 30 minutes while it
lasts, whatever the hour. Every alert still becomes a Home Assistant notification card; this decides
only the push. The first time an alert is raised it pushes as it always did, because nothing waits on
Jev; Jev's answer then decides whether its repeats keep buzzing a phone. Some alerts always push: a
pump or valve fault, a probe the controller has lost, water not reaching a zone, anything Jev itself
raises about a probe, and dosing hardware that ran past its time, was interrupted by a restart or
stopped a batch (CS-801, CS-803, CS-806: they repeat while something does not read off).
"""
from __future__ import annotations

from datetime import datetime

from . import council
from .judges.base import choice

ALWAYS = {"CS-101", "CS-102", "CS-103", "CS-207", "CS-701", "CS-703", "CS-704", "CS-801", "CS-803",
          "CS-806"}
REASK_H = 6.0

URGENCY = {
    "escalate": "A person should look now: water, plants or equipment are at risk if nobody acts.",
    "remind": "Worth a card for the next time someone checks, not a phone buzz: it needs attention today, not now.",
    "quiet": "Information only: nothing is at risk and nobody needs to act.",
}

QUESTIONS = {
    "urgency": [
        choice("You triage alerts from an automated irrigation controller for a commercial grow room. Judge "
               "only from the alert's text and the facts given. A phone push at night should wake someone only "
               "when water, plants or equipment are at risk.", URGENCY),
        choice("Decide how urgently a person needs to see this irrigation alert. Advice about settings, "
               "comparisons between zones and reminders about something already known are not emergencies; "
               "a zone drying out with nothing watering it, or hardware stuck on, is.", URGENCY),
    ],
}


def always(code):
    return code.startswith("CS-3") or code in ALWAYS


class Triage:
    """`may_quiet=False` (the Claude brain): the answer is kept as a note on the alert and never keeps a push off the
    phone, which is code's call. `meta(key, now)` adds the "_brain" key the Claude route needs to what is asked."""

    def __init__(self, asker, may_quiet=True, meta=None):
        self.asker, self.may_quiet, self.meta = asker, may_quiet, meta
        self.raised: dict[str, int] = {}
        self.last: dict[str, dict] = {}

    def push(self, key, code, title, message, now: datetime):
        """(push?, why). Never raises; any doubt pushes."""
        self.raised[key] = self.raised.get(key, 0) + 1
        if always(code):
            return True, "always pushed"
        k = f"alert:{key}"
        ans = self.asker.result(k)
        age_h = None if ans is None else (self.asker.clock() - ans.at) / 3600.0
        if ans is None or age_h > REASK_H:
            state = {"alert_code": code, "title": title, "message": " ".join(message.split())[:500],
                     "local_time": f"{now:%H:%M}", "raised_today": self.raised[key]}
            if self.meta is not None:
                state["_brain"] = self.meta(key, now)
            self.asker.submit(k, state, council.expand(QUESTIONS))
            return True, "first time: pushed as always"
        v = council.combine(ans.answers, "urgency")
        self.last[key] = {"answer": None if v is None else v.label, "p": None if v is None else v.prob,
                          "note": (v.notes or [None])[0] if v is not None else None}
        if not self.may_quiet:
            return True, f"AI assistant: {'no answer' if v is None else v.label}, noted; pushed by its severity"
        if v is not None and v.firm(0.6) and v.label in ("remind", "quiet"):
            return False, f"Jev: {v.label} (p={v.prob:.2f}), card only"
        return True, "Jev: escalate or unsure, pushed"
