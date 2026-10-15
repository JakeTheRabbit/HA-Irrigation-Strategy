"""What the Claude brain changes in the shared judge code, and what it leaves exactly as it was (haiku-brain-design
section 15, test_jev_behaviour_edits): the judges' phrasings, the doctrine topics each one carries, the acting
judges, the alert note that no longer quiets a phone, and the day's stage on the default arc."""
import sys
from datetime import datetime

import jev_bridge
import jev_kit as K
from jev import council
from jev.client import Asker
from jev.triage import QUESTIONS, Triage

TOPICS = {  # each judge's with_doctrine(...) call, as written at its call site
    "dawn": ("dryback", "stage", "probe", "closed_loop"), "dusk": ("dryback", "stage", "maintenance"),
    "night": ("dryback", "closed_loop", "probe"), "probe": ("probe", "closed_loop"),
    "ramp": ("ramp", "probe", "ec"), "salt": ("ec", "closed_loop", "stage", "maintenance"),
    "setpoints": ("maintenance", "ec"), "shot": ("probe", "maintenance", "ramp"),
    "stage": ("stage", "ripening", "dryback", "ec", "closed_loop"), "zones": ("probe", "maintenance", "slab"),
}


def test_each_judge_keeps_its_phrasing_and_names_its_doctrine_topics():
    for judge in jev_bridge.judges():
        for variants in judge.questions.values():
            for v in variants:
                assert v["instructions"].startswith(v["base_instructions"] + " Doctrine: ")
                assert v["doctrine_topics"] == TOPICS[judge.name], judge.name


def test_the_acting_judges_are_those_whose_answers_can_act():
    acting = set()
    for judge in jev_bridge.judges():
        src = open(sys.modules[type(judge).__module__].__file__, encoding="utf-8").read()
        if any(f'directive(ctx, "{kind}"' in src for kind in ("advance", "distrust", "ec_mode", "setpoint")):
            acting.add(judge.name)
    assert acting == set(jev_bridge.ACTING_JUDGES)


def _triage(answer, **kw):
    t = K.FakeTransport(K.both("urgency", answer))
    asker = Asker("a", "t", transport=t, threaded=False, clock=lambda: K.NOW.timestamp())
    return Triage(asker, **kw), t


def test_under_claude_the_alert_note_never_keeps_a_push_off_the_phone():
    quiet = K.choice_answer("quiet", {"quiet": 0.95})
    quiet["rationale"] = "nothing is at risk"
    old, _ = _triage(quiet)
    new, sent = _triage(quiet, may_quiet=False, meta=lambda key, now: {"room": "r", "zone": "alert",
                                                                         "judge": "alerts", "asked": "t"})
    for t in (old, new):
        t.push("k", "CS-702", "title", "message", datetime(2026, 9, 27, 13, 0))
    assert old.push("k", "CS-702", "t", "m", K.NOW)[0] is False  # the legacy route keeps its firm quiet
    push, why = new.push("k", "CS-702", "t", "m", K.NOW)
    assert push is True and "noted" in why and new.last["k"]["note"] == "nothing is at risk"
    assert sent.calls[0]["state"]["_brain"]["judge"] == "alerts"


def test_council_keeps_each_phrasings_reason():
    answers = K.both("q", {**K.choice_answer("keep"), "rationale": "one"}, {**K.choice_answer("keep"), "rationale": "two"})
    assert council.combine(answers, "q").notes == ["one", "two"]
    assert council.combine(K.both("q", K.choice_answer("keep")), "q").notes == []


def test_triage_questions_are_unchanged():
    assert all(set(v) == {"type", "instructions", "criteria"} for vs in QUESTIONS.values() for v in vs)
