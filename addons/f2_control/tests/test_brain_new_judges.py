"""The Claude brain's new judges (haiku-brain-design section 5, test_brain_new_judges). Balance: asked once a grow-day
late in maintenance, only while a zone's water per plant is out of line with the room and the zones judge has named
no hardware cause; it never directs anything, and its answer reaches tonight's setpoints judge as evidence."""
from datetime import timedelta

import brain_kit as B
import brain_bridge
import jev_kit as K
import pytest
from brain import client as jc
from brain import council
from brain.brain import Brain, JudgeState
from brain.client import Asker
from brain.enrich import enrich
from brain.judges.balance import CHOICES, BalanceJudge
from brain.judges.dusk import DuskJudge
from brain.judges.setpoints import SetpointsJudge
from brain.ledger import Ledger
from test_controller import _build
from test_jev_controller import KILL, NOW, _states

SIBLINGS = {2: {"litres_per_plant": 1.0, "litres_per_plant_words": "1000 mL a plant today"},
            3: {"litres_per_plant": 1.0, "litres_per_plant_words": "1000 mL a plant today"}}


def _ctx(phase="P2", daily_vol=6.0, hours_to_off=1.5, brain=None, **over):
    """4 plants against siblings at 1 L a plant: 6 L is 150 % of the room's median zone, 4 L is 100 %."""
    s = K.snap(phase=phase, daily_vol=daily_vol, hours_to_lights_off=hours_to_off)
    return K.ctx(phase, s=s, plants=4, siblings=SIBLINGS, brain={} if brain is None else brain, **over)


def _answer(label, p=0.8):
    rest = (1.0 - p) / (len(CHOICES) - 1)
    return K.both("toward_room", K.choice_answer(label, {k: (p if k == label else rest) for k in CHOICES}, p))


# ------------------------------------------------------------------ when it is asked
def test_balance_is_due_late_in_maintenance_only_while_the_zone_is_out_of_line():
    j = BalanceJudge()
    assert j.due(_ctx(), None)
    assert j.due(_ctx(daily_vol=2.0), None)  # 50 %: too little water is out of line too
    assert not j.due(_ctx(daily_vol=4.0), None)  # 100 %: in balance
    assert not j.due(_ctx(daily_vol=4.5), None)  # 112 %: inside 85-115 %
    assert not j.due(_ctx(hours_to_off=3.0), None)  # not yet the last 2 h before lights-off
    assert not j.due(_ctx(phase="P1"), None) and not j.due(_ctx(phase="P3"), None)
    assert not j.due(_ctx(lights_on=False), None)


def test_balance_is_asked_once_a_grow_day():
    j = BalanceJudge()
    assert not j.due(_ctx(), NOW - timedelta(hours=1))
    assert j.due(_ctx(), NOW - timedelta(hours=22))


def test_balance_waits_when_the_zones_judge_named_hardware_and_never_runs_without_the_claude_context():
    j = BalanceJudge()
    assert not j.due(_ctx(brain={"zones_hardware": "delivery_fault"}), None)
    assert not j.due(K.ctx("P2", s=K.snap(daily_vol=6.0, hours_to_lights_off=1.5), plants=4, siblings=SIBLINGS),
                     None)  # brain None: the legacy route and rules


def test_balance_evidence_says_the_share_of_the_room():
    ev = BalanceJudge().evidence(_ctx())
    assert ev["water_per_plant_today"] == "1500 mL" and ev["share_of_that"].startswith("150%")
    assert ev["compared_with"] == "the room's median zone: 1000 mL a plant"


# ------------------------------------------------------------------ no directive
def test_balance_never_directs_and_keeps_its_answer_for_the_night():
    ctx = _ctx()
    for label in CHOICES:
        j = BalanceJudge()
        v = {"toward_room": council.combine(_answer(label), "toward_room")}
        assert j.decide(v, ctx) is None
        words = j.words("default", 1, NOW + timedelta(hours=3))
        assert words.startswith(f"the balance judge said {label}, p 0.80, at 13:00: ")
        assert j.words("default", 1, NOW + timedelta(hours=9)) is None  # stale by the next day
        assert j.words("default", 2, NOW) is None


def test_balance_through_the_brain_asks_once_and_returns_nothing_to_act_on():
    j = BalanceJudge()
    t = K.FakeTransport(_answer("less_water_toward_room"))
    asker = Asker("acct", "tok", transport=t, threaded=False, clock=lambda: K.NOW.timestamp())
    brain = Brain(asker, Ledger(None), [j], log=lambda *a: None)
    assert brain.tick(_ctx()) == [] and len(t.calls) == 1
    assert "less_water_toward_room" in j.words("default", 1, NOW)
    assert brain.tick(_ctx()) == [] and len(t.calls) == 1  # not asked again the same grow-day


# ------------------------------------------------------------------ it reaches the setpoints judge
def test_the_answer_reaches_tonights_setpoints_evidence_and_no_other_judges():
    said = "the balance judge said less_water_toward_room, p 0.74, at 22:30: ..."
    night = K.ctx("P3", s=K.snap(phase="P3"), brain={"room_balance": said})
    assert enrich(night, SetpointsJudge(), SetpointsJudge().evidence(night))["room_balance"] == said
    assert "room_balance" not in enrich(night, DuskJudge(), DuskJudge().evidence(night))
    plain = K.ctx("P3", s=K.snap(phase="P3"), brain={"room_balance": None})
    assert "room_balance" not in enrich(plain, SetpointsJudge(), SetpointsJudge().evidence(plain))


@pytest.fixture
def haiku(monkeypatch):
    monkeypatch.setattr(jc, "anthropic", B.FakeSDK(B.FakeClient(B.judging())))
    c, _fake = _build({"num_zones": 1, "enable_flag": KILL, "brain_provider": "claude_haiku",
                       "anthropic_api_key": B.SENTINEL}, states=_states())
    return c


def test_the_controller_hands_the_balance_answer_and_the_zones_hardware_cause_to_the_context(haiku):
    c, room = haiku, haiku.rooms[0]
    j = brain_bridge._judge(c.jev, "balance")
    j.latest[("default", 1)] = (NOW, "the balance judge said more_water_toward_room, p 0.81, at 13:00: ...")
    st = c.jev.state[("default", 1, "zones")] = JudgeState(last_asked=NOW - timedelta(hours=1))
    st.verdicts = {"why_different": council.combine(K.both("why_different", K.choice_answer(
        "delivery_fault", {"delivery_fault": 0.8, "insufficient_evidence": 0.2})), "why_different")}
    got = brain_bridge.brain_context(c, room, 1, None, NOW)
    assert got["room_balance"].startswith("the balance judge said more_water_toward_room")
    assert got["zones_hardware"] == "delivery_fault"
    st.last_asked = NOW - timedelta(hours=20)  # before this grow-day's lights-on: not today's cause
    assert brain_bridge.brain_context(c, room, 1, None, NOW)["zones_hardware"] is None


def test_balance_is_built_on_the_claude_route(tmp_path, monkeypatch):
    monkeypatch.setattr(jc, "anthropic", B.FakeSDK(B.FakeClient(B.judging())))
    haiku = brain_bridge.build({"brain_provider": "claude_haiku", "anthropic_api_key": "k"},
                             str(tmp_path / "s.json"), lambda *a: None)
    assert "balance" in [j.name for j in haiku.judges]
