"""The notch budget: however the band moves, a setting moves at most one notch in any 24 h and two in any 7 days,
and no notch is made for a while after a move was refused or did not work out. Its history is the ledger, read with
defaults, so a ledger an older controller wrote loads as it is."""
import json
from datetime import timedelta

import jev_bridge
import jev_kit as K
import test_jev_setpoints as T
from jev.envelope import COOL_DOWN_H, admit, notch_budget
from jev.judges.setpoints import SHOT, THRESHOLD, SetpointsJudge
from jev.ledger import Ledger

NIGHT = T.NIGHT


def _admit(notches=(), setbacks=(), **over):
    sp = T._sp(notches=list(notches), setbacks=list(setbacks), **over)
    return admit(T._d(5.0, 4.5), T._ctx(sp=sp))


def test_a_view_without_history_admits_as_before():
    assert admit(T._d(5.0, 4.5), T._ctx()) == (True, "one notch inside its range around your value")


def test_one_notch_a_lever_in_any_24_hours():
    ok, why = _admit([(NIGHT - timedelta(hours=23), SHOT, 0.5)])
    assert not ok and why == "notch budget: 0.5 already moved in 24 h (at most 0.5)"
    assert _admit([(NIGHT - timedelta(hours=24), SHOT, 0.5)])[0]  # a full day on
    assert _admit([(NIGHT - timedelta(hours=1), THRESHOLD, 0.5)])[0]  # the other lever is its own budget


def test_two_notches_a_lever_in_any_7_days():
    two = [(NIGHT - timedelta(days=d), SHOT, 0.5) for d in (2, 5)]
    ok, why = _admit(two)
    assert not ok and why == "notch budget: 1 already moved in 7 days (at most 1)"
    assert _admit([(NIGHT - timedelta(days=d), SHOT, 0.5) for d in (2, 7)])[0]  # the older one has left the week


def test_a_refused_or_failed_move_rests_the_zone():
    ok, why = _admit(setbacks=[NIGHT - timedelta(hours=20)])
    assert not ok and why.startswith("notch budget: resting until 2026-09-28 15:00")
    assert _admit(setbacks=[NIGHT - timedelta(hours=COOL_DOWN_H)])[0]


def test_the_judge_is_not_asked_when_nothing_it_picks_could_be_admitted():
    j = SetpointsJudge()
    spent = [(NIGHT - timedelta(hours=2), SHOT, 0.5), (NIGHT - timedelta(hours=2), THRESHOLD, 0.5)]
    assert j.due(T._ctx(sp=T._sp(notches=[])), None)
    assert j.due(T._ctx(sp=T._sp(notches=spent[:1])), None)  # the threshold may still move
    assert not j.due(T._ctx(sp=T._sp(notches=spent)), None)
    assert not j.due(T._ctx(sp=T._sp(setbacks=[NIGHT - timedelta(hours=1)])), None)
    assert notch_budget({}, SHOT, NIGHT) is None


# ------------------------------------------------------------------ the history, from the ledger
def _entry(i, at, label, action="setpoint", zone=1, judge="setpoints", **more):
    return {"id": i, "at": at, "judge": judge, "room": "default", "zone": zone, "label": label, "action": action,
            "evidence": {}, "check_at": None, "check": None, "outcome": None, **more}


def test_the_history_reads_an_older_ledger_with_defaults(tmp_path):
    """Entries as 3.11.1 wrote them: an outcome without its own time counts from check_at; anything unreadable
    and other judges, zones and the legacy ledger lines are passed over."""
    lines = [
        _entry(1, "2026-09-27T13:00:00", "P2", action="advance", judge="ramp"),  # the 3.11.1 fixture's line
        _entry(2, "2026-09-26T23:00:00", "smaller_shots", check_at="2026-09-27T23:00:00",
               outcome={"what": "a day after 'smaller shots': water 116 -> 117 L", "good": False}),
        _entry(3, "2026-09-25T23:00:00", "later_rewater", outcome={"what": "fine", "good": True}),
        _entry(4, "2026-09-25T23:00:00", "smaller_shots", zone=2),
        _entry(5, "not a time", "smaller_shots"),
        _entry(6, None, "bigger_shots"),
        _entry(7, "2026-09-24T23:00:00", "keep"),
    ]
    path = tmp_path / "jev_ledger.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in lines))
    c, room = T._Controller(tmp_path), T._room()
    c.jev.ledger = Ledger(str(path))
    h = jev_bridge.notch_history(c, room, 1, NIGHT)
    assert h["notches"] == [(NIGHT - timedelta(days=1), SHOT, 0.5), (NIGHT - timedelta(days=2), THRESHOLD, 0.5)]
    assert h["setbacks"] == [NIGHT]  # the bad check, known at its check_at
    sp = jev_bridge.setpoint_view(c, room, 1, T.Z1, NIGHT)
    assert sp["notches"] == h["notches"] and sp["setbacks"] == h["setbacks"]


def test_a_controller_without_a_ledger_has_no_history(tmp_path):
    c, room = T._Controller(tmp_path), T._room()
    del c.jev.ledger
    assert jev_bridge.notch_history(c, room, 1, NIGHT) == {"notches": [], "setbacks": []}


# ------------------------------------------------------------------ through the brain
def _night(c, label, now):
    answer = K.choice_answer(label, {label: 0.8, "keep": 0.2})
    c.jev.asker.transport = K.FakeTransport(K.both("tomorrow", answer))
    c.jev.asker.clock = lambda: now.timestamp()
    return c.jev.tick(T._ctx(sp=jev_bridge.setpoint_view(c, T._room(), 1, T.Z1, now), now=now))


def test_a_move_past_its_range_is_filed_and_rests_the_zone(tmp_path):
    c = T._Controller(tmp_path, numbers={SHOT: 3.0, THRESHOLD: 30.5})  # at the bottom of its range 3-4
    assert _night(c, "smaller_shots", NIGHT) == []
    refused = c.jev.ledger.entries[-1]
    assert refused["action"] == "refused" and "outside its range" in refused["evidence"]["why"]
    sp = jev_bridge.setpoint_view(c, T._room(), 1, T.Z1, NIGHT + timedelta(days=1))
    assert sp["setbacks"] == [NIGHT] and not SetpointsJudge().due(T._ctx(sp=sp, now=NIGHT + timedelta(days=1)), None)
    later = NIGHT + timedelta(days=2)  # the rest is over
    assert SetpointsJudge().due(T._ctx(sp=jev_bridge.setpoint_view(c, T._room(), 1, T.Z1, later), now=later), None)


def test_the_budget_refusing_starts_no_rest_of_its_own(tmp_path):
    c = T._Controller(tmp_path)
    c.jev.ledger.record("setpoints", "default", 1, "smaller_shots", "setpoint", at=NIGHT - timedelta(hours=20))
    assert _night(c, "smaller_shots", NIGHT) == []
    assert [e["action"] for e in c.jev.ledger.entries] == ["setpoint"]
    assert "notch budget" in c.jev.journal.recent("default")[0]["reason"]


def test_a_check_that_came_back_bad_is_dated_when_it_was_known():
    led = Ledger(None)
    i = led.record("setpoints", "default", 1, "smaller_shots", "setpoint", at=NIGHT - timedelta(days=1),
                   check_at=NIGHT - timedelta(hours=1))
    led.resolve(i, "no less water", False, at=NIGHT)
    assert led.entries[-1]["outcome"] == {"what": "no less water", "good": False, "at": NIGHT.isoformat()}
