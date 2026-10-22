"""What dosing and the AI assistant journal (journal_out.Outbox), and the one-time backfill of their history.

A batch's steps are batch.step events sharing one batch_id, a dose is dose.completed with what it gave, a batch that
fails is batch.failed with its code. Each ledger row (brain/ledger.py) is mirrored as ai.judgement and, once its check
is known, ai.outcome, both carrying correlation.ledger_id, and the brain's own setpoint write names the same ledger id
in its claim, so the integration's target.changed can be matched to its outcome. A journal that breaks never stops a
dose, a batch or a verdict.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import brain_bridge
import controller
import fake_ha
import journal_out
from brain.envelope import Directive
from brain.ledger import Ledger
from crop_steering_engine.ids import derived_id
from test_dosing_runner import BALANCE, BASE, BATCH, _full_batch, _interrupted, make_rig

STEPS = ("hold", "close", "fill", "mix", "premix", "dose", "postmix", "finish")
AT = datetime(2026, 10, 20, 23, 0)
CHECKED = datetime(2026, 10, 21, 23, 0)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return make_rig(tmp_path, monkeypatch)


def _events(outbox, kind=None):
    return [e for e in outbox.pending() if kind is None or e["kind"] == kind]


# ------------------------------------------------------------------ dosing
def test_every_batch_step_shares_one_batch_id(rig):
    r = rig()
    _full_batch(r)
    r.ask("batch", by="Ben")
    r.poll()
    steps = _events(r.c.journal, "batch.step")
    assert {e["correlation"]["batch_id"] for e in steps} == {steps[0]["correlation"]["batch_id"]}
    assert steps[0]["correlation"]["batch_id"]
    assert [e["data"]["step"] for e in steps if e["data"]["state"] == "running"] == list(STEPS)
    assert [(e["data"]["step"], e["data"]["state"]) for e in steps] == [
        (step, state) for step in STEPS for state in ("running", "done")]
    assert {e["data"]["recipe"] for e in steps} == {""}  # the batch's name (BATCH has none)
    assert {(e["room_id"], e["source"]["actor"], e["source"]["detail"]) for e in steps} == {
        ("room:", "manual", "Ben")}
    # Its doses carry the same batch id.
    doses = _events(r.c.journal, "dose.completed")
    assert [e["data"]["pump"] for e in doses] == ["balance", "bloom"]
    assert {e["correlation"]["batch_id"] for e in doses} == {steps[0]["correlation"]["batch_id"]}
    assert not _events(r.c.journal, "batch.failed")


def test_a_skipped_step_is_journaled_as_skipped(rig):
    r = rig()
    r.config(pumps=(BALANCE,), batch=dict(BATCH, recipe=[], fill_valve=None, full_entity=None))
    r.ask("batch", by=None)
    r.poll()
    states = {e["data"]["step"]: e["data"]["state"] for e in _events(r.c.journal, "batch.step")}
    assert states["fill"] == "skipped" and states["dose"] == "skipped"
    assert {e["source"]["actor"] for e in _events(r.c.journal, "batch.step")} == {"automation"}


def test_a_dose_journals_given_ml(rig):
    r = rig()
    r.config()
    r.ask(ml=50)
    r.poll()
    (done,) = _events(r.c.journal, "dose.completed")
    assert done["data"] == {"pump": "balance", "ml": 50, "given_ml": 50, "flow_ml_s": 10.0}
    assert (done["outcome"], done["code"], done["source"]["actor"]) == ("ok", None, "manual")
    assert done["correlation"]["batch_id"] is None
    started = r.status()[1]["history"][0]["dosed"][0]["at"]
    assert done["id"] == derived_id(datetime.fromisoformat(started),
                                    f"dosing:default:{started}:dose.completed")  # as its backfill would be


@pytest.mark.parametrize("how, outcome, code", [("silent", "failed", "CS-802"), ("early", "partial", "CS-802")])
def test_a_dose_that_did_not_finish_journals_its_outcome_and_code(rig, how, outcome, code):
    r = rig()
    r.config()
    r.behaviour["button.balance_start"] = how
    r.ask(ml=50)
    r.poll()
    (done,) = _events(r.c.journal, "dose.completed")
    assert (done["outcome"], done["code"]) == (outcome, code)


def test_a_refused_dose_journals_nothing(rig):
    r = rig()
    r.config()
    r.ask(ml=999999)
    r.poll()
    assert _events(r.c.journal) == []


def test_a_failed_batch_is_batch_failed_with_its_own_code(rig):
    r = rig()
    _full_batch(r)
    r.full_after = None
    r.ask("batch")
    r.poll()
    (failed,) = _events(r.c.journal, "batch.failed")
    assert (failed["outcome"], failed["code"]) == ("failed", "CS-804")
    assert failed["data"]["step"] == "fill"
    assert failed["data"]["reason"] == "the tank did not read full within 20 min"
    batch_ids = {e["correlation"]["batch_id"] for e in _events(r.c.journal) if e["kind"].startswith("batch.")}
    assert len(batch_ids) == 1


def test_a_stopped_batch_is_an_aborted_batch(rig):
    r = rig()
    _full_batch(r)
    r.ask("batch")
    r.clock.at(150, lambda: r.ask("stop", by="Sam"))
    r.poll()
    (failed,) = _events(r.c.journal, "batch.failed")
    assert (failed["outcome"], failed["code"], failed["data"]["step"]) == ("aborted", "CS-806", "premix")


def test_a_journal_that_breaks_never_stops_a_batch(rig, monkeypatch):
    r = rig()
    _full_batch(r)

    def broken(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(r.c.journal, "emit", broken)
    r.ask("batch")
    r.poll()
    assert r.status()[1]["handled_result"] == "finished" and r.codes() == []


def test_an_event_that_cannot_be_built_never_changes_a_dose_or_a_failed_batch(rig, monkeypatch):
    import dosing_runner

    def broken(*a, **k):
        raise ValueError("bad event")

    monkeypatch.setattr(dosing_runner, "_dose_event", broken)
    monkeypatch.setattr(dosing_runner, "_failed", broken)
    monkeypatch.setattr(dosing_runner, "_actor", broken)
    r = rig()
    r.config()
    r.ask(ml=50)
    r.poll()
    assert r.status()[1]["handled_result"] == "finished"
    _full_batch(r)
    r.full_after = None
    r.ask("batch")
    r.poll()
    assert r.status()[1]["handled_result"] == "stopped: fill: the tank did not read full within 20 min"
    assert r.codes() == ["CS-804", "CS-806"]
    assert {e["kind"] for e in _events(r.c.journal)} == {"alert.raised"}  # the controller's own alerts only


def test_a_dose_and_batch_a_restart_interrupted_are_journaled_on_every_start(rig, tmp_path):
    dosed = [{"pump": "balance", "name": "Balance", "ml": 300, "given": 300, "result": "finished",
              "at": BASE.isoformat()}]
    cut = {"pump": "bloom", "name": "Bloom", "ml": 150, "at": (BASE + timedelta(minutes=1)).isoformat()}
    _interrupted(tmp_path, dosed=dosed, dose=cut, name="Week 3")
    r = rig()
    assert r.runner.recover() is True
    r.runner.journal_recovered()
    events = _events(r.c.journal)
    assert [(e["kind"], e["outcome"], e["code"]) for e in events] == [
        ("dose.completed", "ok", None), ("dose.completed", "failed", "CS-803"), ("batch.failed", "failed", None)]
    assert events[2]["data"] == {"step": None, "reason": "interrupted by a restart", "recipe": "Week 3"}
    assert len({e["correlation"]["batch_id"] for e in events}) == 1
    r.runner.journal_recovered()
    assert len(_events(r.c.journal)) == 3  # each once
    # The next start finds another one: it is journaled too, not only on the first start after the upgrade.
    later = (BASE + timedelta(days=1)).isoformat()
    _interrupted(tmp_path, kind="dose", at=later, dosed=[],
                 dose={"pump": "balance", "name": "Balance", "ml": 20, "at": later})
    runner = r.build(tmp_path / "dosing_state.json")
    r.c.dosing = runner
    assert runner.recover() is True
    runner.journal_recovered()
    (cut,) = _events(r.c.journal)[3:]
    assert (cut["kind"], cut["code"], cut["data"]["pump"]) == ("dose.completed", "CS-803", "balance")
    assert cut["id"] == derived_id(datetime.fromisoformat(later), f"dosing:default:{later}:dose.completed")


# ------------------------------------------------------------------ the AI assistant's ledger
def _brain_rig(tmp_path, rooms=(("default", ""), ("f2", "f2_"))):
    outbox = journal_out.Outbox(str(tmp_path / "journal_outbox.jsonl"))
    ledger = Ledger(str(tmp_path / "jev_ledger.jsonl"))
    c = SimpleNamespace(journal=outbox, jev=SimpleNamespace(ledger=ledger),
                        rooms=[SimpleNamespace(slug=s, prefix=p) for s, p in rooms])
    brain_bridge.journal_ledger(c)
    return c, outbox, ledger


def test_a_ledger_record_and_resolve_mirror_as_judgement_and_outcome(tmp_path):
    c, outbox, ledger = _brain_rig(tmp_path)
    row = ledger.record("setpoints", "default", 1, "smaller_shots", "setpoint", evidence={"tomorrow": "smaller_shots"},
                        check_at=CHECKED, at=AT)
    (judged,) = _events(outbox)
    assert judged["kind"] == "ai.judgement" and judged["correlation"]["ledger_id"] == str(row)
    assert judged["data"] == {"judge": "setpoints", "label": "smaller_shots", "action": "setpoint",
                              "power": "nudge_setpoints", "evidence": {"tomorrow": "smaller_shots"}}
    assert (judged["room_id"], judged["zone"], judged["source"]["actor"]) == ("room:", 1, "ai")
    assert judged["id"] == derived_id(AT.replace(tzinfo=timezone.utc), f"ledger:{row}")
    assert datetime.fromisoformat(judged["ts"]).replace(tzinfo=None) == AT
    ledger.resolve(row, "VWC held its target", True, at=CHECKED)
    outcome = _events(outbox, "ai.outcome")[0]
    assert outcome["data"] == {"what": "VWC held its target", "good": True}
    assert outcome["correlation"]["ledger_id"] == str(row)
    assert outcome["id"] == derived_id(CHECKED.replace(tzinfo=timezone.utc), f"ledger:{row}:outcome")


def test_a_refused_move_is_a_refused_judgement(tmp_path):
    _c, outbox, ledger = _brain_rig(tmp_path)
    ledger.record("setpoints", "default", 1, "smaller_shots", "refused", evidence={"why": "notch budget"}, at=AT)
    (judged,) = _events(outbox)
    assert (judged["outcome"], judged["data"]["action"]) == ("refused", "refused")


def test_a_ledger_row_for_slug_f2_lands_in_room_f2_(tmp_path):
    _c, outbox, ledger = _brain_rig(tmp_path)
    ledger.record("plan", "f2", "room", "catch_up", "catch_up", at=AT)
    ledger.record("setpoints", "gone", 1, "keep", "setpoint", at=AT)  # a room no longer here: nothing
    (judged,) = _events(outbox)
    assert (judged["room_id"], judged["zone"]) == ("room:f2_", None)


def test_a_listener_that_breaks_never_stops_the_ledger(tmp_path):
    ledger = Ledger(str(tmp_path / "jev_ledger.jsonl"))

    def broken(what, entry):
        raise RuntimeError("no journal")

    ledger.listener = broken
    row = ledger.record("setpoints", "default", 1, "keep", "setpoint", at=AT)
    ledger.resolve(row, "fine", True, at=CHECKED)
    assert ledger.entries[0]["outcome"]["good"] is True
    assert Ledger(str(tmp_path / "jev_ledger.jsonl")).entries[0]["id"] == row


class _Writes:
    """The controller as apply_setpoint and apply_values see it: _auto_write records what it was asked."""

    def __init__(self, tmp_path, ledger):
        from brain.journal import Journal
        from brain.setpoint_memory import SetpointMemory

        self.jev = SimpleNamespace(ledger=ledger, setpoints=SetpointMemory(str(tmp_path / "sp.json")),
                                   journal=Journal(None))
        self.writes, self.events = [], []

    def _auto_write(self, room, zone, suffix, old, value, learn, now, by="auto", reason=None, expected=None,
                    **named):
        self.writes.append((suffix, old, value, by, named.get("ledger_id")))
        return True

    def _notify_event(self, *a):
        self.events.append(a)

    def _number_range(self, room, zone, suffix):
        return 0.0, 100.0


def test_the_brains_setpoint_write_names_its_ledger_row(tmp_path):
    ledger = Ledger(None)
    c = _Writes(tmp_path, ledger)
    room = SimpleNamespace(slug="f2", prefix="f2_", state={1: {}})
    row = ledger.record("setpoints", "f2", 1, "smaller_shots", "setpoint", at=AT)
    d = Directive("setpoints", "setpoint", {"suffix": "p2_shot_size", "from": 5.0, "to": 4.5, "words": "P2 shot",
                                            "choice": "smaller_shots"}, "why", AT + timedelta(hours=1))
    brain_bridge.apply_setpoint(c, room, 1, d, SimpleNamespace(setpoints={}), AT)
    assert c.writes == [("p2_shot_size", 5.0, 4.5, brain_bridge.SETPOINTS_BY, str(row))]
    pending = c.jev.setpoints.zone("f2", 1)["pending"]
    assert pending["ledger_id"] == str(row)  # a write sent again names it too
    # A move the ledger holds no row for (a dry run, an older answer) names none.
    c.writes.clear()
    brain_bridge.apply_setpoint(c, room, 1, d, SimpleNamespace(setpoints={}), AT + timedelta(minutes=1))
    assert c.writes[0][4] is None


def test_a_power_write_names_its_ledger_row(tmp_path):
    ledger = Ledger(None)
    c = _Writes(tmp_path, ledger)
    room = SimpleNamespace(slug="f2", prefix="f2_", state={1: {}})
    row = ledger.record("shotsize", "f2", 1, "values", "shot_size", at=AT)
    d = Directive("shotsize", "shot_size", {"values": {"p2_shot_size": 4.0}, "reasons": {}, "expected": "less"},
                  "why", AT + timedelta(hours=1))
    ctx = SimpleNamespace(shots={"current": {"p2_shot_size": 5.0}, "day": "2026-10-20"}, targets=None)
    brain_bridge.apply_values(c, room, 1, d, ctx, AT)
    assert c.writes == [("p2_shot_size", 5.0, 4.0, f"{brain_bridge.AI_BY} (shot sizes)", str(row))]


# ------------------------------------------------------------------ the controller: the claim and the backfill
@pytest.fixture
def start(monkeypatch, tmp_path):
    """Controller() on a fake Home Assistant, its data folder tmp_path; called again, the app started again."""
    monkeypatch.setattr(controller, "SETTINGS_WAIT_PASSES", 0)
    monkeypatch.setenv("F2_STATE_PATH", str(tmp_path / "state.json"))
    fake = fake_ha.FakeHA()
    for eid in ("input_boolean.kill", "switch.crop_steering_zone_1_enabled"):
        fake.set_state(eid, "on")
    for eid in ("switch.p", "switch.m", "switch.v1"):
        fake.set_state(eid, "off")
    options = {"num_zones": 1, "enable_flag": "input_boolean.kill", "hold_entities": [],
               "hardware": {"pump": "switch.p", "mainline": "switch.m", "valves": {"1": "switch.v1"}}}
    fake_ha.install(controller, fake, options)

    def build():
        c = controller.Controller()
        c.fake = fake
        return c

    return build


DOSING = {"rooms": {"default": {"history": [
    {"kind": "batch", "at": "2026-10-20T08:00:00+00:00", "ended_at": "2026-10-20T08:20:00+00:00",
     "result": "finished", "name": "Week 3", "doses": {"balance": 300}, "by": "Ben",
     "dosed": [{"pump": "balance", "name": "Balance", "ml": 300, "given": 300, "result": "finished",
                "at": "2026-10-20T08:05:00+00:00"}]},
    {"kind": "dose", "at": "2026-10-19T08:00:00+00:00", "ended_at": "2026-10-19T08:01:00+00:00",
     "result": "not confirmed", "doses": {"bloom": 40}, "by": None,
     "dosed": [{"pump": "bloom", "name": "Bloom", "ml": 40, "given": None, "result": "not confirmed",
                "at": "2026-10-19T08:00:00+00:00"}]},
    {"kind": "batch", "at": "2026-10-18T08:00:00+00:00", "ended_at": "2026-10-18T08:30:00+00:00",
     "result": "stopped: fill: the tank did not read full within 20 min", "name": "Week 2", "doses": {},
     "dosed": [], "by": "Ben"},
]}}}
LEDGER = [
    {"id": 4, "at": "2026-10-19T23:00:00", "judge": "setpoints", "room": "default", "zone": 1,
     "label": "smaller_shots", "action": "setpoint", "evidence": {"tomorrow": "smaller_shots"},
     "check_at": "2026-10-20T23:00:00", "check": {}, "outcome": {"what": "VWC held", "good": True,
                                                                 "at": "2026-10-20T23:00:00"}},
    {"id": 5, "at": "2026-10-20T23:00:00", "judge": "setpoints", "room": "elsewhere", "zone": 1,
     "label": "keep", "action": "setpoint", "evidence": {}, "check_at": None, "check": None, "outcome": None},
]


def _seed(tmp_path):
    (tmp_path / "dosing_state.json").write_text(json.dumps(DOSING), encoding="utf-8")
    (tmp_path / "jev_ledger.jsonl").write_text("".join(json.dumps(r) + "\n" for r in LEDGER), encoding="utf-8")


def _expected_ids():
    def at(s):
        return datetime.fromisoformat(s)

    return {
        derived_id(at("2026-10-20T08:05:00+00:00"), "dosing:default:2026-10-20T08:05:00+00:00:dose.completed"),
        derived_id(at("2026-10-20T08:00:00+00:00"), "dosing:default:2026-10-20T08:00:00+00:00:batch.step"),
        derived_id(at("2026-10-19T08:00:00+00:00"), "dosing:default:2026-10-19T08:00:00+00:00:dose.completed"),
        derived_id(at("2026-10-18T08:00:00+00:00"), "dosing:default:2026-10-18T08:00:00+00:00:batch.failed"),
        derived_id(at("2026-10-19T23:00:00+00:00"), "ledger:4"),
        derived_id(at("2026-10-20T23:00:00+00:00"), "ledger:4:outcome"),
    }


def _pass(c):
    """What a pass does for the backfill, after its rooms and before its flush (Controller.loop_once)."""
    c._journal_backfill()


def test_backfill_runs_once_and_ids_are_stable(start, tmp_path):
    _seed(tmp_path)
    c = start()
    assert _events(c.journal) == []  # never at start: the first pass acts first
    _pass(c)
    events = _events(c.journal)
    assert {e["id"] for e in events} == _expected_ids()
    by_kind = {e["kind"]: e for e in events}
    assert by_kind["batch.step"]["data"] == {"step": "finish", "state": "done", "recipe": "Week 3"}
    failed = by_kind["batch.failed"]
    assert (failed["outcome"], failed["data"]["step"], failed["data"]["recipe"]) == ("failed", "fill", "Week 2")
    assert by_kind["ai.outcome"]["data"] == {"what": "VWC held", "good": True}
    assert {e["room_id"] for e in events} == {"room:"}
    assert {e["source"]["detail"] for e in events if e["kind"] == "dose.completed"} == {"Ben", None}
    assert [e["kind"] for e in events][:2] == ["batch.failed", "dose.completed"]  # oldest first
    # The flag is in the room's block once the state is saved; a second start sends nothing.
    assert c.rooms[0].journal_backfill is True and c._save_state()
    assert json.loads((tmp_path / "state.json").read_text())["default"]["_journal_backfill"] == 1
    c.journal.flush(lambda room_id, chunk: ([e["id"] for e in chunk], []))
    again = start()
    _pass(again)
    assert _events(again.journal) == []


def test_a_backfill_that_runs_again_sends_the_same_ids(start, tmp_path):
    _seed(tmp_path)
    c = start()
    _pass(c)
    first = {e["id"] for e in _events(c.journal)}  # never saved: as if the app stopped before its save
    (tmp_path / "journal_outbox.jsonl").unlink()
    again = start()
    _pass(again)
    assert {e["id"] for e in _events(again.journal)} == first


def test_backfill_flag_is_not_read_back_as_a_room(start, tmp_path):
    c = start()
    _pass(c)
    assert c._save_state()
    saved = json.loads((tmp_path / "state.json").read_text())
    assert set(saved) == {"default"} and saved["default"]["_journal_backfill"] == 1
    again = start()
    assert [r.slug for r in again.rooms] == ["default"] and set(again._read_state_file()) == {"default"}
    assert again.rooms[0].journal_backfill is True


def test_a_room_with_no_history_is_flagged_and_sends_nothing(start):
    c = start()
    _pass(c)
    assert _events(c.journal) == [] and c.rooms[0].journal_backfill is True


def test_the_first_pass_acts_before_any_backfill(start, tmp_path):
    _seed(tmp_path)
    c = start()
    assert c.rooms[0].journal_backfill is False and _events(c.journal) == []
    seen = []
    real = c._loop_room

    def loop_room(room, now):
        seen.append(len(_events(c.journal)))  # what the outbox holds while the room acts
        return real(room, now)

    c._loop_room = loop_room
    c.loop_once(datetime(2026, 10, 22, 12, 0))
    assert seen == [0]
    assert {e["id"] for e in _events(c.journal)} >= _expected_ids()  # queued after the room's pass


def _big_ledger(tmp_path, n):
    rows = [{"id": i, "at": (AT + timedelta(minutes=i)).isoformat(), "judge": "setpoints", "room": "default",
             "zone": 1, "label": "keep", "action": "setpoint", "evidence": {}, "check_at": None, "check": None,
             "outcome": {"what": "held", "good": True, "at": (CHECKED + timedelta(minutes=i)).isoformat()}}
            for i in range(1, n + 1)]
    (tmp_path / "jev_ledger.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return {e for r in rows for _k, kw in brain_bridge.ledger_events(r) for e in [kw["event_id"]]}


def test_a_backfill_never_drops_a_live_event_and_finishes_over_several_passes(start, tmp_path):
    expected = _big_ledger(tmp_path, 60)  # 120 events
    c = start()
    c.journal = journal_out.Outbox(str(tmp_path / "small_outbox.jsonl"), cap=50)
    live = {c.journal.emit("", "alert.raised", data={"key": f"k{i}"}) for i in range(20)}
    down = {"value": True}

    def append(data, timeout):
        if down["value"]:
            return 500, None
        return 200, {"accepted": [e["id"] for e in data["events"]], "duplicate": [], "rejected": []}

    c.fake.responses[("crop_steering", "journal_append")] = append
    sent = []
    for _ in range(10):  # the integration is down: nothing leaves, the backfill waits for room
        _pass(c)
        c._journal_skip = 0
        c._flush_journal()
        pending = {e["id"] for e in _events(c.journal)}
        assert live <= pending and len(pending) <= 25
    assert c.rooms[0].journal_backfill is False
    down["value"] = False
    passes = 0
    while not c.rooms[0].journal_backfill:
        passes += 1
        assert passes < 50
        _pass(c)
        c._flush_journal()
        sent += [e["id"] for dom, svc, data in c.fake.calls if svc == "journal_append" for e in data["events"]]
        c.fake.calls.clear()
    c._flush_journal()
    sent += [e["id"] for dom, svc, data in c.fake.calls if svc == "journal_append" for e in data["events"]]
    assert passes > 1 and live <= set(sent) and expected <= set(sent)


def test_at_most_200_backfill_events_a_pass(start, tmp_path):
    _big_ledger(tmp_path, 150)  # 300 events
    c = start()
    _pass(c)
    assert len(_events(c.journal)) == 200 and c.rooms[0].journal_backfill is False
    _pass(c)
    assert len(_events(c.journal)) == 300 and c.rooms[0].journal_backfill is True


def test_a_torn_read_is_tried_again_later_and_never_sets_the_flag(start, tmp_path, monkeypatch):
    lines = []
    monkeypatch.setattr(controller, "log", lambda *a: lines.append(" ".join(str(x) for x in a)))
    c = start()
    (tmp_path / "dosing_state.json").write_text('{"rooms": {"default": {"hist', encoding="utf-8")  # torn
    for _ in range(12):
        _pass(c)
    assert c.rooms[0].journal_backfill is False and _events(c.journal) == []
    assert len([x for x in lines if "journal backfill" in x]) == 1  # one line for the run of failures
    _seed(tmp_path)
    for _ in range(controller.JOURNAL_BACKOFF_PASSES + 1):
        _pass(c)
    assert c.rooms[0].journal_backfill is True
    # Its dosing half; its ledger half was read (no file then) on the first pass, and is not held back by dosing.
    ledger = {derived_id(datetime.fromisoformat("2026-10-19T23:00:00+00:00"), "ledger:4"),
              derived_id(datetime.fromisoformat("2026-10-20T23:00:00+00:00"), "ledger:4:outcome")}
    assert {e["id"] for e in _events(c.journal)} == _expected_ids() - ledger


def _two_rooms(c, tmp_path):
    """A second room beside the default one, and dosing history in both."""
    c.rooms.append(SimpleNamespace(slug="f2", prefix="f2_", journal_backfill=False))
    doc = json.loads(json.dumps(DOSING))
    doc["rooms"]["f2"] = {"history": [dict(DOSING["rooms"]["default"]["history"][1], by="Sam")]}
    (tmp_path / "dosing_state.json").write_text(json.dumps(doc), encoding="utf-8")


def _damage_ledger(tmp_path):
    with open(tmp_path / "jev_ledger.jsonl", "a", encoding="utf-8") as fh:
        fh.write('{"id": 6, "at": "2026-\n')


DOSING_IDS = 4  # the default room's dosing events in DOSING


def _kinds(c, room_id):
    return [e["kind"] for e in _events(c.journal) if e["room_id"] == room_id]


def test_a_damaged_ledger_never_holds_back_the_dosing_history_of_any_room(start, tmp_path):
    _seed(tmp_path)
    _damage_ledger(tmp_path)
    c = start()
    _two_rooms(c, tmp_path)
    _pass(c)
    assert len([k for k in _kinds(c, "room:") if not k.startswith("ai.")]) == DOSING_IDS
    assert _kinds(c, "room:f2_") == ["dose.completed"]
    assert not [k for k in _kinds(c, "room:") if k.startswith("ai.")]
    # The ledger half waits in both rooms (which room a damaged line was for is not known).
    assert (c.rooms[0].journal_backfill, c.rooms[1].journal_backfill) == (False, False)


def test_after_three_failed_runs_the_readable_ledger_lines_are_queued(start, tmp_path, monkeypatch):
    lines = []
    monkeypatch.setattr(controller, "log", lambda *a: lines.append(" ".join(str(x) for x in a)))
    _seed(tmp_path)
    _damage_ledger(tmp_path)
    c = start()
    passes = 0
    while not c.rooms[0].journal_backfill:
        passes += 1
        assert passes < 40
        _pass(c)
    assert passes == 3 * controller.JOURNAL_BACKOFF_PASSES + 4  # 3 failed runs, each backing off, then the 4th
    assert {e["id"] for e in _events(c.journal)} == _expected_ids()
    assert [x for x in lines if "unreadable" in x] == ["journal backfill: ledger: 1 unreadable lines skipped"]
    assert len([x for x in lines if "journal backfill" in x]) == 2  # the failure run, then the skip


def test_a_damaged_dosing_state_never_holds_back_the_ledger(start, tmp_path):
    _seed(tmp_path)
    c = start()  # (the dosing runner sets a file it cannot read aside at start: damaged after it)
    (tmp_path / "dosing_state.json").write_text('{"rooms": {"default": {"hist', encoding="utf-8")
    _pass(c)
    assert sorted(_kinds(c, "room:")) == ["ai.judgement", "ai.outcome"]
    assert c.rooms[0].journal_backfill is False  # its dosing half is still to come


def test_live_and_backfilled_ledger_ids_match_in_every_time_zone(tmp_path):
    script = tmp_path / "ids.py"
    script.write_text(f"""
import json, sys
from datetime import datetime
from types import SimpleNamespace
sys.path.insert(0, {str(Path(brain_bridge.__file__).parent)!r})
import brain_bridge, journal_out
from brain.ledger import Ledger
outbox = journal_out.Outbox(sys.argv[1] + "/out.jsonl")
ledger = Ledger(sys.argv[1] + "/ledger.jsonl")
c = SimpleNamespace(journal=outbox, jev=SimpleNamespace(ledger=ledger), rooms=[SimpleNamespace(slug="d", prefix="")])
brain_bridge.journal_ledger(c)
row = ledger.record("setpoints", "d", 1, "keep", "setpoint", at=datetime(2026, 10, 20, 23, 0))
ledger.resolve(row, "held", True, at=datetime(2026, 10, 21, 23, 0))
live = [e["id"] for e in outbox.pending()]
back = [kw["event_id"] for _k, kw in brain_bridge.ledger_events(ledger.entries[0])]
print(json.dumps([live, back]))
""", encoding="utf-8")
    seen = []
    for tz in ("UTC0", "NZST-13", "PST8PDT"):
        folder = tmp_path / tz
        folder.mkdir()
        out = subprocess.run([sys.executable, str(script), str(folder)], capture_output=True, text=True,
                             env={**os.environ, "TZ": tz}, check=True).stdout
        live, back = json.loads(out.strip().splitlines()[-1])
        assert live == back
        seen.append(tuple(live))
    assert len(set(seen)) == 1
    assert seen[0][0] == derived_id(datetime(2026, 10, 20, 23, 0, tzinfo=timezone.utc), "ledger:1")


def test_the_pass_journals_what_a_restart_interrupted(start):
    c = start()
    called = []
    c.dosing.journal_recovered = lambda: called.append(True)
    c.loop_once(datetime(2026, 10, 22, 12, 0))
    assert called == [True]


def test_the_controllers_claim_carries_the_ledger_id(start):
    c = start()
    entity = "number.crop_steering_zone_1_p2_shot_size"
    c.fake.set_state(entity, "5")
    assert c._auto_write(c.rooms[0], 1, "p2_shot_size", 5.0, 4.5, {}, datetime(2026, 10, 22, 23, 0),
                         by=brain_bridge.SETPOINTS_BY, ledger_id="7")
    (claim,) = [d for name, d in c.fake.events if name == "crop_steering_setpoint_write"]
    assert claim["ledger_id"] == "7" and claim["who"] == "brain"
    c.fake.events.clear()
    assert c._auto_write(c.rooms[0], 1, "p2_shot_size", 4.5, 4.0, {}, datetime(2026, 10, 23, 23, 0), by="auto")
    (claim,) = [d for name, d in c.fake.events if name == "crop_steering_setpoint_write"]
    assert "ledger_id" not in claim  # the learner's write: as before
