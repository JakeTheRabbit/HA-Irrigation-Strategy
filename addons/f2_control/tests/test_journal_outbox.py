"""The controller's journal outbox (journal_out.Outbox): a local JSON-lines file of events, flushed to the
integration's crop_steering.journal_append after a pass. Never on the watering path (ruling R5)."""
import json
import re

import journal_out

ULID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def _lines(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_emit_appends_one_json_line_and_flush_removes_accepted_and_duplicate(tmp_path):
    path = tmp_path / "journal_outbox.jsonl"
    box = journal_out.Outbox(str(path))
    first = box.emit("f2_", "shot.started", zone=3, data={"phase": "P1"})
    assert ULID.match(first)
    rows = _lines(path)
    assert len(rows) == 1
    event = rows[0]
    assert event["v"] == 1 and event["id"] == first and event["room_id"] == "room:f2_"
    assert event["zone"] == 3 and event["kind"] == "shot.started" and event["outcome"] == "ok"
    assert event["source"]["actor"] == "engine" and event["data"] == {"phase": "P1"}
    assert set(event["correlation"]) >= {"intent_id", "causation_id", "batch_id", "run_id"}
    assert "seq" not in event  # only the integration assigns it
    second = box.emit("f2_", "phase.changed", zone=3, data={"from": "P0", "to": "P1", "how": "lights-on"})
    third = box.emit("", "alert.raised", code="CS-207", data={"key": "wd", "title": "dry"})
    calls = []

    def send(room_id, events):
        calls.append((room_id, [e["id"] for e in events]))
        return ([first], [second]) if room_id == "room:f2_" else ([], [])

    assert box.flush(send) == 2
    assert calls == [("room:f2_", [first, second]), ("room:", [third])]
    assert [e["id"] for e in box.pending()] == [third]
    assert [e["id"] for e in _lines(path)] == [third]


def test_outbox_caps_at_5000_dropping_oldest_only_when_it_flushes(tmp_path, monkeypatch):
    path = str(tmp_path / "journal_outbox.jsonl")
    box = journal_out.Outbox(path)
    rewrites = []
    real = journal_out.Outbox._rewrite
    monkeypatch.setattr(journal_out.Outbox, "_rewrite", lambda self, events: (rewrites.append(len(events)),
                                                                              real(self, events)))
    ids = [box.emit("", "intent.held", zone=1, outcome="held", data={"reason": str(n)}) for n in range(6000)]
    assert rewrites == []  # an emit never rewrites the file: it is only ever an append
    assert len(box.pending()) == 6000
    assert box.flush(lambda room_id, events: None) == 0  # the integration is down: trimmed all the same
    assert rewrites == [4500]  # over the cap: to 0.9 x cap, so the next emits do not trim again at once
    assert [e["id"] for e in box.pending()] == ids[1500:]
    # a restart counts what is already in the file: under the cap, nothing is trimmed
    again = journal_out.Outbox(path)
    newest = again.emit("", "intent.held", zone=1, outcome="held", data={"reason": "after"})
    again.flush(lambda room_id, events: None)
    assert rewrites == [4500]
    assert [e["id"] for e in again.pending()] == ids[1500:] + [newest]


def test_a_rejected_event_goes_to_the_dead_letter_file_and_the_rest_still_flush(tmp_path):
    box = journal_out.Outbox(str(tmp_path / "journal_outbox.jsonl"))
    bad = box.emit("", "phase.changed", zone=1, data={})
    good = box.emit("", "phase.changed", zone=1, data={})
    other = box.emit("f2_", "phase.changed", zone=1, data={})
    calls = []

    def send(room_id, events):
        calls.append(room_id)
        ids = [e["id"] for e in events]
        rejected = [{"id": bad, "error": "unknown kind"}] if bad in ids else []
        return [i for i in ids if i != bad], [], rejected

    assert box.flush(send) == 3
    assert calls == ["room:", "room:f2_"]  # the rejection did not stop the flush
    assert box.pending() == []
    dead = _lines(tmp_path / "journal_dead.jsonl")
    assert [(d["event"]["id"], d["error"]) for d in dead] == [(bad, "unknown kind")]
    assert good and other


def test_the_dead_letter_file_keeps_the_newest_500(tmp_path):
    box = journal_out.Outbox(str(tmp_path / "journal_outbox.jsonl"))
    ids = [box.emit("", "phase.changed", zone=1, data={}) for _ in range(510)]

    def send(room_id, events):
        return [], [], [{"id": e["id"], "error": "bad"} for e in events]

    box.flush(send, batch=50, max_batches=20)
    dead = _lines(tmp_path / "journal_dead.jsonl")
    assert [d["event"]["id"] for d in dead] == ids[10:]


def test_an_answer_without_rejected_keeps_what_it_did_not_take(tmp_path):
    box = journal_out.Outbox(str(tmp_path / "journal_outbox.jsonl"))
    took = box.emit("", "phase.changed", zone=1, data={})
    kept = box.emit("", "phase.changed", zone=1, data={})
    assert box.flush(lambda room_id, events: ([took], [])) == 1
    assert [e["id"] for e in box.pending()] == [kept]
    assert not (tmp_path / "journal_dead.jsonl").exists()


def test_a_flush_stops_once_its_time_is_up(tmp_path, monkeypatch):
    clock = {"s": 0.0}
    monkeypatch.setattr(journal_out.time, "monotonic", lambda: clock["s"])
    box = journal_out.Outbox(str(tmp_path / "journal_outbox.jsonl"))
    for _ in range(4):
        box.emit("", "phase.changed", zone=1, data={})
    calls = []

    def send(room_id, events):
        calls.append(len(events))
        clock["s"] += 1.0  # each answer takes a second
        return [e["id"] for e in events], []

    assert box.flush(send, batch=1, budget_s=1.5) == 2  # a third batch would start 2 s in
    assert calls == [1, 1]


def test_flush_stops_at_the_first_failed_batch(tmp_path):
    box = journal_out.Outbox(str(tmp_path / "journal_outbox.jsonl"))
    for prefix in ("", "f2_", "f3_"):
        for _ in range(3):
            box.emit(prefix, "phase.changed", zone=1, data={"from": "P0", "to": "P1", "how": "x"})
    calls = []

    def send(room_id, events):
        calls.append(room_id)
        return None

    assert box.flush(send) == 0
    assert calls == ["room:"]
    assert len(box.pending()) == 9


def test_flush_sends_at_most_max_batches_of_batch_events(tmp_path):
    box = journal_out.Outbox(str(tmp_path / "journal_outbox.jsonl"))
    for _ in range(12):
        box.emit("", "phase.changed", zone=1, data={})
    sizes = []

    def send(room_id, events):
        sizes.append(len(events))
        return [e["id"] for e in events], []

    assert box.flush(send, batch=5, max_batches=2) == 10
    assert sizes == [5, 5]
    assert len(box.pending()) == 2


def test_a_torn_line_is_skipped_and_dropped_at_the_next_flush(tmp_path):
    path = tmp_path / "journal_outbox.jsonl"
    box = journal_out.Outbox(str(path))
    kept = box.emit("", "phase.changed", zone=1, data={})
    with open(path, "a", encoding="utf-8") as fh:
        fh.write('{"v": 1, "id": "torn')  # a crash mid-append
    assert [e["id"] for e in box.pending()] == [kept]
    assert box.flush(lambda room_id, events: ([kept], [])) == 1
    assert _lines(path) == []


def test_a_durable_emit_is_flushed_to_the_file_and_never_fsynced(tmp_path, monkeypatch):
    synced = []
    monkeypatch.setattr(journal_out.os, "fsync", lambda fd: synced.append(fd))
    path = tmp_path / "journal_outbox.jsonl"
    box = journal_out.Outbox(str(path))
    box.emit("", "phase.changed", zone=1, data={})
    started = box.emit("", "shot.started", zone=1, data={}, durable=True)
    assert synced == []  # no fsync on the watering path (ruling R5)
    assert _lines(path)[-1]["id"] == started


def test_an_emit_that_cannot_write_never_raises(tmp_path):
    box = journal_out.Outbox(str(tmp_path / "missing" / "dir" / "journal_outbox.jsonl"))
    assert ULID.match(box.emit("", "shot.started", zone=1, data={}, durable=True))
    assert box.pending() == []
