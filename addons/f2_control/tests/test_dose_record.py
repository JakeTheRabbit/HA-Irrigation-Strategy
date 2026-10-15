"""The exact dose record (docs/DOSING.md, Exact dose record): each dose in the order it went in, with
what it gave and not only what was asked, and the last batch kept by its recipe's name.

Driven as test_dosing_runner.py drives it: the real Controller, the in-memory Home Assistant and a
fake clock.
"""
from __future__ import annotations

import json

import pytest

import dosing_runner
from test_dosing_runner import BALANCE, BASE, BATCH, BLOOM, _full_batch, _interrupted, make_rig


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return make_rig(tmp_path, monkeypatch)


def test_a_named_batch_records_each_dose_in_order_and_is_kept_as_the_last_batch(rig):
    r = rig()
    _full_batch(r)
    r.config(pumps=(BALANCE, BLOOM), batch=dict(BATCH, name="Week 3"))
    seen = []
    r.clock.at(30, lambda: seen.append(r.status()[1]["batch"]["name"]))
    r.ask("batch")
    r.poll()
    status = r.status()[1]
    assert seen == ["Week 3"]  # named while it runs
    entry = status["history"][0]
    assert (entry["kind"], entry["name"], entry["result"]) == ("batch", "Week 3", "finished")
    assert [(d["pump"], d["name"], d["ml"], d["given"], d["result"]) for d in entry["dosed"]] == [
        ("balance", "Balance", 300, 300, "finished"),
        ("bloom", "Bloom", 150.0, 150.0, "finished"),
    ]
    assert status["last_batch"] == entry and r.saved()["last_batch"] == entry
    assert status["pumps"]["bloom"]["last"]["given"] == 150.0


def test_a_batch_with_no_name_is_still_the_last_batch(rig):
    r = rig()
    _full_batch(r)  # a setup from before recipe names: no name at all
    r.ask("batch")
    r.poll()
    assert r.status()[1]["last_batch"]["name"] == ""


def test_a_dose_that_ends_early_records_what_it_gave_not_what_was_asked(rig):
    r = rig()
    r.config()
    r.behaviour["button.balance_start"] = "early"  # the firmware stops at a fifth: 2 s of 10
    r.ask(ml=100)
    r.poll()
    status = r.status()[1]
    [dosed] = status["history"][0]["dosed"]
    assert dosed["result"] == "ended early" and dosed["ml"] == 100
    assert 15 <= dosed["given"] <= 50  # seconds from the press to its end x 10 mL/s
    assert status["pumps"]["balance"]["last"]["given"] == dosed["given"]
    assert status["history"][0]["doses"] == {"balance": 100}  # what was asked, as before


def test_a_dose_that_could_not_be_confirmed_gave_an_unknown_amount(rig):
    r = rig()
    r.config()
    r.behaviour["button.balance_start"] = "silent"
    r.ask(ml=50)
    r.poll()
    [dosed] = r.status()[1]["history"][0]["dosed"]
    assert (dosed["result"], dosed["given"]) == ("not confirmed", None)


def test_the_last_batch_outlives_the_history(rig, monkeypatch):
    monkeypatch.setattr(dosing_runner, "HISTORY", 2)
    r = rig()
    _full_batch(r)
    r.config(pumps=(BALANCE, BLOOM), batch=dict(BATCH, name="Week 3"))
    r.ask("batch")
    r.poll()
    for _ in range(3):
        r.ask(ml=10)
        r.poll()
    status = r.status()[1]
    assert [h["kind"] for h in status["history"]] == ["dose", "dose"]
    assert status["last_batch"]["name"] == "Week 3"


def test_a_batch_cut_by_a_restart_keeps_what_each_dose_gave_and_its_name(rig, tmp_path):
    finished = {"pump": "balance", "name": "Balance", "ml": 300, "given": 300, "result": "finished",
                "at": BASE.isoformat()}
    _interrupted(tmp_path, name="Week 3", dosed=[finished],
                 dose={"pump": "bloom", "name": "Bloom", "ml": 150, "at": "2026-09-28T01:05:00+00:00"})
    r = rig()
    assert r.runner.recover() is True
    saved = r.saved()
    entry = saved["history"][0]
    assert (entry["name"], entry["result"]) == ("Week 3", "interrupted by a restart")
    assert entry["dosed"] == [
        finished,
        {"pump": "bloom", "name": "Bloom", "ml": 150, "given": None, "result": "interrupted by a restart",
         "at": "2026-09-28T01:05:00+00:00"},
    ]
    assert saved["last_batch"] == entry


def test_a_record_from_before_the_exact_dose_record_recovers(rig, tmp_path):
    _interrupted(tmp_path)  # an older app's batch record: no name, no doses given
    r = rig()
    assert r.runner.recover() is True
    entry = r.saved()["history"][0]
    assert (entry["name"], entry["dosed"], entry["doses"]) == ("", [], {"balance": 300})


def test_a_dosing_state_from_before_the_exact_dose_record_loads(rig, tmp_path):
    old = {"ml": 50, "at": BASE.isoformat(), "result": "finished"}
    (tmp_path / "dosing_state.json").write_text(json.dumps({"rooms": {"default": {
        "handled": "abc", "handled_result": "finished", "inflight": None, "last": {"balance": old},
        "history": [{"kind": "batch", "at": BASE.isoformat(), "ended_at": BASE.isoformat(),
                     "result": "finished", "doses": {"balance": 300}, "by": "Alex"}]}}}), encoding="utf-8")
    r = rig()
    assert r.runner.recover() is True
    r.config()
    r.poll()
    status = r.status()[1]
    assert status["last_batch"] is None  # it was never kept apart; the history still has it
    assert status["pumps"]["balance"]["last"] == old and status["history"][0]["doses"] == {"balance": 300}
    r.ask(ml=20)
    r.poll()
    assert r.status()[1]["pumps"]["balance"]["last"]["given"] == 20
