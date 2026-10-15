"""The journal behind the dashboard's live Jev log: every decision, what code did with it, and outcomes."""
import json
from datetime import timedelta
from types import SimpleNamespace

import jev_bridge
import jev_kit as K
from jev.brain import Brain
from jev.client import Asker
from jev.journal import MAX_KEPT, SHOWN, Journal
from jev.judges.ramp import RampJudge
from jev.ledger import Ledger


def _ramp_ctx(**snap_over):
    h = K.history(points=[(m, 38.0 + (0.1 if m < 20 else 0), 5.4) for m in range(0, 90, 1)],
                  shots=[(60, 120, 36.0, 5.0, "p1_ramp"), (35, 120, 37.8, 5.2, "p1_ramp")])
    s = K.snap(**{"phase": "P1", "vwc": 39.2, "shot_count": 3, "minutes_since_shot": 25.0, "ec": 5.6,
                  "ec_settled": 5.6, **snap_over})
    return K.ctx("P1", s=s, h=h)


def _brain(tmp_path, answer):
    t = K.FakeTransport(K.both("ramp_state", answer))
    asker = Asker("acct", "tok", transport=t, threaded=False, clock=lambda: K.NOW.timestamp())
    brain = Brain(asker, Ledger(str(tmp_path / "l.jsonl")), [RampJudge()], log=lambda *a: None)
    brain.journal = Journal(str(tmp_path / "j.jsonl"))
    return brain


def test_an_admitted_answer_is_one_acted_line(tmp_path):
    brain = _brain(tmp_path, K.choice_answer("ec_is_feed_front", {"ec_is_feed_front": 0.8, "real_salt": 0.2}))
    brain.tick(_ramp_ctx())
    brain.tick(_ramp_ctx())  # the same answer again: no second line
    [e] = brain.journal.recent("default")
    assert e["title"] == "Ramp hand-over" and e["zone"] == 1 and e["result"] == "acted"
    assert e["action"] == "hand over to maintenance" and e["verdict"] == "ec is feed front"
    assert e["p"] == 0.8 and e["agreed"] is True and "room" not in e


def test_an_answer_that_asks_for_nothing_is_logged_once_as_no_action(tmp_path):
    brain = _brain(tmp_path, K.choice_answer("keep_ramping", {"keep_ramping": 0.9}))
    brain.tick(_ramp_ctx())
    brain.tick(_ramp_ctx())
    [e] = brain.journal.recent("default")
    assert e["result"] == "no action" and e["action"] == "" and e["verdict"] == "keep ramping"


def test_a_refusal_is_logged_and_a_later_admission_too(tmp_path):
    brain = _brain(tmp_path, K.choice_answer("ec_is_feed_front", {"ec_is_feed_front": 0.8}))
    brain.tick(_ramp_ctx(vwc=34.0))  # more than 3 points under the ceiling: code refuses
    brain.tick(_ramp_ctx())  # the same standing answer, now admitted
    acted, refused = brain.journal.recent("default")
    assert refused["result"] == "refused" and "under the ramp ceiling" in refused["reason"]
    assert acted["result"] == "acted"


def test_outcomes_are_logged_with_how_they_turned_out(tmp_path):
    brain = _brain(tmp_path, K.choice_answer("ec_is_feed_front", {"ec_is_feed_front": 0.8}))
    brain.tick(_ramp_ctx())
    later = K.ctx("P2", s=K.snap(phase="P2", vwc=38.5), now=K.NOW + timedelta(minutes=61))
    brain.tick(later)
    top = brain.journal.recent("default")[0]
    assert top["kind"] == "outcome" and top["title"] == "Ramp hand-over"
    assert top["result"] in ("worked", "did not work") and top["reason"]


def test_the_journal_survives_a_restart_and_keeps_only_the_newest(tmp_path):
    path = str(tmp_path / "j.jsonl")
    j = Journal(path)
    for i in range(MAX_KEPT + 25):
        j.add({"t": f"2026-09-28T10:{i % 60:02d}:00", "room": "default" if i % 2 else "f1", "zone": 1,
               "judge": "salt", "title": "Pore EC", "verdict": str(i), "result": "no action"})
    again = Journal(path)
    assert len(again.entries) == MAX_KEPT and again.entries[-1]["verdict"] == str(MAX_KEPT + 24)
    recent = again.recent("default")  # odd numbers are this room's; the newest odd one is MAX_KEPT + 23
    assert len(recent) == SHOWN and recent[0]["verdict"] == str(MAX_KEPT + 23)


def test_a_damaged_journal_starts_again(tmp_path):
    path = tmp_path / "j.jsonl"
    path.write_text("{not json\n", encoding="utf-8")
    assert Journal(str(path)).entries == []


# ------------------------------------------------------------------ what the dashboard reads
def _published(tmp_path, entries=0, reason="x"):
    brain = _brain(tmp_path, K.choice_answer("keep_ramping", {"keep_ramping": 0.9}))
    brain.flower_start, brain.flower_days = {"*": "2026-08-22"}, 56
    for i in range(entries):
        brain.journal.add({"t": "2026-09-28T10:00:00", "room": "default", "zone": 1 + i % 3, "judge": "salt",
                           "title": "Pore EC", "kind": "decision", "verdict": "below band vegetative",
                           "p": 0.72, "agreed": True, "action": "hold the EC steer", "result": "acted",
                           "reason": reason})
    c = SimpleNamespace(jev=brain, _jev_read=lambda e: "2026-08-22")
    room = SimpleNamespace(slug="default", prefix="", zones={1: {}, 2: {}, 3: {}})
    out = {}
    jev_bridge.publish(c, room, K.NOW, lambda eid, state, attrs: out.__setitem__(eid, (state, attrs)))
    return out


def test_the_log_sensor_carries_the_newest_entries_well_under_the_recorder_limit(tmp_path):
    out = _published(tmp_path, entries=80, reason="r" * 400)
    state, attrs = out["sensor.crop_steering_jev_log"]
    assert state == "10:00 Z2 Pore EC: below band vegetative -> hold the EC steer"  # the 80th: zone 1 + 79 % 3
    assert len(attrs["entries"]) == SHOWN and len(attrs["entries"][0]["reason"]) <= 120
    assert len(json.dumps(attrs)) < 16000


def test_an_empty_log_says_so(tmp_path):
    state, attrs = _published(tmp_path)["sensor.crop_steering_jev_log"]
    assert state == "no decisions yet" and attrs["entries"] == []


def test_the_room_sensor_carries_todays_stage_for_the_chart(tmp_path):
    stage = _published(tmp_path)["sensor.crop_steering_jev"][1]["stage"]
    assert stage["day"] == 37 and stage["name"] == "flower bulk" and stage["steering"] == "vegetative"
    assert stage["pore_ec"] == [3.5, 6.0] and stage["runoff_pct"] == [8, 16]


def test_alert_triage_is_logged_only_when_its_call_changes(tmp_path):
    brain = _brain(tmp_path, K.choice_answer("keep_ramping", {"keep_ramping": 0.9}))
    c = SimpleNamespace(jev=brain)
    room = SimpleNamespace(slug="default")
    for push, why in ((True, "first time: pushed as always"), (True, "first time: pushed as always"),
                      (False, "Jev: remind (p=0.81), card only")):
        jev_bridge.triaged(c, room, 1, "jev_stage_default_z1", "CS-705", "off the stage's arc", push, why)
    held, first = brain.journal.recent("default")
    assert first["action"] == "CS-705: push to the phone" and held["action"] == "CS-705: card only"
    assert held["title"] == "Alert triage" and held["verdict"] == "Jev: remind (p=0.81), card only"
