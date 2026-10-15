"""The plan task (jev/plan_task.py, jev_bridge.plan_task): under the Claude brain only, what a drift from the grower's
plan means. Its answer picks one of the drift's code-written suggestions and nothing else; it is asked only when due,
with the kill switch on, no no-touch window and fresh readings, at most four times a photoperiod, and an unsure
answer is looked at once more."""
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

import jev_bridge
import jev_kit as K
import plan_adherence as A
from jev import plan_task as P
from jev.client import Asker
from jev.journal import Journal
from jev.ledger import Ledger
from test_plan_adherence import NOW, view

EDITED = {"number.crop_steering_zone_1_p2_shot_size": 6.0, "number.crop_steering_zone_2_p2_shot_size": 5.0}


def _choice(label, p=0.8):
    rest = (1 - p) / (len(P.CAUSE) - 1)
    return K.choice_answer(label, {k: (p if k == label else rest) for k in P.CAUSE})


class Rig:
    def __init__(self, answers, haiku=True, kill=True):
        self.transport = K.ScriptedTransport(*answers)
        self.clock = NOW.timestamp()
        asker = Asker("anthropic", "key", transport=self.transport, threaded=False, clock=lambda: self.clock)
        status = SimpleNamespace(provider="claude_haiku" if haiku else "jev_legacy")
        self.jev = SimpleNamespace(asker=asker, status=status, journal=Journal(None), ledger=Ledger(None),
                                   plan=P.PlanTask(asker, jev_bridge.plan_meta))
        self.kill, self.no_touch = kill, None
        self.room = SimpleNamespace(slug="default", prefix="", enable_flag="input_boolean.kill",
                                    _adherence=A.fresh(), hardware_fault=None, strategy_snapshot={})

    def _on(self, entity, default=False):
        return self.kill

    def _no_touch_until(self, room, now):
        return self.no_touch

    def run(self, v, adh=None):
        drifts = A.detect(v, adh if adh is not None else self.adh)
        return jev_bridge.plan_task(self, self.room, v.now, v, drifts)


@pytest.fixture(autouse=True)
def healthy(monkeypatch):
    monkeypatch.setattr(jev_bridge, "room_health", lambda c, room, now: ("ok", None))


def _edited_rig(*answers, **kw):
    rig = Rig(answers or [K.both("cause", _choice("deliberate_change"))], **kw)
    rig.adh = A.fresh()
    A.detect(view(), rig.adh)  # the baseline
    return rig


def test_a_firm_answer_picks_the_drifts_suggestion_and_the_evidence_has_no_entity_id():
    rig = _edited_rig(K.both("cause", _choice("plan_out_of_date")))
    v = view(natives=EDITED, now=NOW)
    assert rig.run(v) == {}  # the drift has just appeared: asked once it has lasted 10 minutes
    later = view(natives=EDITED, now=NOW + timedelta(minutes=11))
    notes = rig.run(later)
    [call] = rig.transport.calls
    state = call["state"]
    assert state["_brain"]["judge"] == "plan" and state["_brain"]["zone"] == "room"
    assert "number." not in json.dumps(state) and "sensor." not in json.dumps(state)
    assert "has no effect" in state["plan_drift"]
    assert set(call["questions"]) == {"cause__v0", "cause__v1"}
    later2 = view(natives=EDITED, now=NOW + timedelta(minutes=12))
    notes = rig.run(later2)
    suggestion, why, action = notes["shadowed_edit"]
    assert suggestion.startswith("The plan moves this setting") or suggestion.startswith("The plan keeps")
    assert action == "advise"
    panel = A.panel(later2, A.detect(later2, rig.adh), notes)
    assert panel["drifts"][0]["suggestion"] == suggestion


def test_a_key_the_drift_does_not_accept_is_no_answer():
    verdict = SimpleNamespace(label="reading_holds_plan", prob=0.9, agreed=True, n=2, notes=["x"],
                              firm=lambda p: True)
    drift = A.Drift("shadowed_edit", 1, 3, "l", "f", ("a", "b", "c"))
    assert P.pick(verdict, drift) == (0, "")
    assert set(P.ALLOWED_KEYS["shadowed_edit"]) == {"deliberate_change", "plan_out_of_date", "no_effect_today"}
    assert "transition_missed" in P.ALLOWED_KEYS and "plan_ending" not in P.ALLOWED_KEYS


def test_an_unsure_answer_is_looked_at_once_more_then_the_first_suggestion_stands():
    split = K.both("cause", _choice("deliberate_change"), _choice("plan_out_of_date"))
    rig = _edited_rig(split, split, split)
    for minutes in (0, 11, 12, 13, 14, 15):
        notes = rig.run(view(natives=EDITED, now=NOW + timedelta(minutes=minutes)))
    assert len(rig.transport.calls) == 2  # the ask and one second look
    assert "second_look" in rig.transport.calls[1]["state"]
    assert notes["shadowed_edit"][0].startswith("Your change to")


def test_at_most_four_asks_a_photoperiod_six_hours_apart():
    rig = _edited_rig(K.both("cause", _choice("deliberate_change")))
    for hours in range(0, 30):
        rig.run(view(natives=EDITED, now=NOW + timedelta(minutes=11, hours=hours / 2)))
    assert len(rig.transport.calls) <= P.ASKS_PER_DAY
    assert len(rig.transport.calls) >= 2


@pytest.mark.parametrize("why", ["kill", "no_touch", "health", "legacy"])
def test_nothing_is_asked_when_the_brain_may_not(why, monkeypatch):
    rig = _edited_rig(kill=why != "kill", haiku=why != "legacy")
    if why == "no_touch":
        rig.no_touch = NOW + timedelta(hours=1)
    if why == "health":
        monkeypatch.setattr(jev_bridge, "room_health", lambda c, room, now: ("impaired", "stale"))
    for minutes in (0, 11, 30):
        rig.run(view(natives=EDITED, now=NOW + timedelta(minutes=minutes)))
    assert rig.transport.calls == []


def test_no_drift_asks_nothing_and_costs_nothing():
    rig = _edited_rig()
    for minutes in (0, 40, 400):
        assert rig.run(view(now=NOW + timedelta(minutes=minutes))) == {}
    assert rig.transport.calls == []


@pytest.mark.parametrize("error", ["HTTP 401 authentication", "budget spent", "the model declined"])
def test_a_brain_that_fails_leaves_exactly_the_rules_line(error):
    """Whatever goes wrong with the brain, the panel shows code's own first suggestion, as it does under rules; the
    CS-713 card never depended on the brain."""
    rig = _edited_rig()
    rig.transport.error = error
    rig.transport.script = []
    for minutes in (0, 11, 12):
        notes = rig.run(view(natives=EDITED, now=NOW + timedelta(minutes=minutes)))
    assert notes == {}
    v = view(natives=EDITED, now=NOW + timedelta(minutes=12))
    drifts = A.detect(v, rig.adh)
    assert A.panel(v, drifts, notes)["drifts"][0]["suggestion"] == drifts[0].suggestions[0]
