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


def test_outbox_caps_at_5000_dropping_oldest(tmp_path):
    box = journal_out.Outbox(str(tmp_path / "journal_outbox.jsonl"))
    ids = [box.emit("", "intent.held", zone=1, outcome="held", data={"reason": str(n)}) for n in range(5001)]
    pending = box.pending()
    assert len(pending) == 5000
    assert [e["id"] for e in pending] == ids[1:]
    # a restart counts what is already in the file
    again = journal_out.Outbox(str(tmp_path / "journal_outbox.jsonl"))
    newest = again.emit("", "intent.held", zone=1, outcome="held", data={"reason": "after"})
    assert [e["id"] for e in again.pending()] == ids[2:] + [newest]


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


def test_a_durable_emit_fsyncs_and_a_plain_one_does_not(tmp_path, monkeypatch):
    synced = []
    monkeypatch.setattr(journal_out.os, "fsync", lambda fd: synced.append(fd))
    box = journal_out.Outbox(str(tmp_path / "journal_outbox.jsonl"))
    box.emit("", "phase.changed", zone=1, data={})
    assert synced == []
    box.emit("", "shot.started", zone=1, data={}, durable=True)
    assert len(synced) == 1


def test_an_emit_that_cannot_write_never_raises(tmp_path):
    box = journal_out.Outbox(str(tmp_path / "missing" / "dir" / "journal_outbox.jsonl"))
    assert ULID.match(box.emit("", "shot.started", zone=1, data={}, durable=True))
    assert box.pending() == []
