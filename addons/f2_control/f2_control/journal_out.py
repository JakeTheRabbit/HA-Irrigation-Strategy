"""The controller's journal outbox: events (spec section 4, v 1) for the integration's event journal.

Each event is one JSON line in `journal_outbox.jsonl`, beside the state file. Emitting is a local append and
nothing else, and it never raises: the journal is never on the watering path (ruling R5). Nothing is fsynced.
`durable=True` (shot.started, written before the pump opens) only flushes Python's buffer to the OS, so the line
is in the file before the pump is asked to start. The trade-off: a power cut (not a crash of the controller,
whose writes the OS still has) can lose that line, and the shot then has no shot.started; an fsync could stall
the shot on a slow or failing disk, and watering never waits on the journal.

The controller flushes the outbox after its pass (Controller._flush_journal) to crop_steering.journal_append,
which is idempotent on `id`. An event leaves the file once the integration has it (accepted or duplicate), or
rejected it: a rejected event goes to `journal_dead.jsonl` (the newest DEAD_CAP kept), so one bad event never
blocks the others. Only a flush rewrites the file: over `cap` events it keeps the newest 0.9 x cap. The
integration, not this file, assigns `seq`.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime

from crop_steering_engine.ids import new_id

CAP = 5000
DEAD_CAP = 500
_CORRELATION = ("intent_id", "causation_id", "batch_id", "run_id", "plan_revision", "setup_revision",
                "proposal_token", "ledger_id")


def _log(*a):
    print("[Crop Steering Controller]", *a, flush=True)


class Outbox:
    def __init__(self, path: str, cap: int = CAP):
        self.path = path
        self.cap = cap
        self.client = "f2_control"  # source.client (the controller sets its version)
        self._lock = threading.Lock()
        self._warned = False

    def _warn(self, what, err):
        if not self._warned:  # one line per run: a full disk must not flood the log
            self._warned = True
            _log(f"journal outbox: {what} failed ({err}); events may be lost, watering is not affected")

    def emit(self, room_prefix: str, kind: str, *, zone=None, outcome="ok", code=None, actor="engine",
             detail=None, program_id=None, data=None, correlation=None, readback=None, durable=False,
             now: datetime | None = None, event_id: str | None = None) -> str:
        """Append one event for the room with this prefix ("" or "f2_", never its slug) -> its id. `event_id`: one
        derived from the row an event mirrors (ids.derived_id), so the same row is always the same event."""
        event_id = event_id or new_id()
        try:
            event = {
                "v": 1,
                "id": event_id,
                "ts": (now or datetime.now()).astimezone().isoformat(timespec="milliseconds"),
                "room_id": "room:" + room_prefix,
                "zone": zone if isinstance(zone, int) and not isinstance(zone, bool) else None,
                "kind": kind,
                "outcome": outcome,
                "code": code,
                "source": {"actor": actor, "detail": detail, "program_id": program_id, "user_id": None,
                           "judge": None, "client": self.client},
                "correlation": {**dict.fromkeys(_CORRELATION), **(correlation or {})},
                "data": data or {},
                "readback": readback,
            }
            line = json.dumps(event, default=str) + "\n"
            with self._lock:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(line)
                    if durable:
                        fh.flush()
        except Exception as err:
            self._warn("emit", err)
        return event_id

    def _read(self, path=None) -> list[dict]:
        """The events in the file, oldest first; a torn line (a crash mid-append) is skipped."""
        out = []
        try:
            with open(path or self.path, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(event, dict):
                        out.append(event)
        except FileNotFoundError:
            pass
        return out

    def _rewrite(self, events):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.writelines(json.dumps(e, default=str) + "\n" for e in events)
        os.replace(tmp, self.path)

    def _bury(self, dead):
        """Rejected events -> journal_dead.jsonl, one log line each, the newest DEAD_CAP kept."""
        path = os.path.join(os.path.dirname(self.path), "journal_dead.jsonl")
        for item in dead:
            _log(f"journal: event {item['event'].get('id')} ({item['event'].get('kind')}) rejected by the "
                 f"integration: {item['error']}; kept in {os.path.basename(path)}")
        rows = (self._read(path) + dead)[-DEAD_CAP:]
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.writelines(json.dumps(r, default=str) + "\n" for r in rows)
        os.replace(tmp, path)

    def count(self) -> int:
        """How many lines the outbox holds (torn ones too), counted without reading them as events."""
        with self._lock:
            try:
                with open(self.path, "rb") as fh:
                    return sum(1 for _ in fh)
            except FileNotFoundError:
                return 0

    def pending(self) -> list[dict]:
        with self._lock:
            return [e for e in self._read() if e.get("id")]

    def flush(self, send, batch: int = 50, max_batches: int = 4, budget_s: float | None = None) -> int:
        """Send the pending events, each room's in order and at most `batch` to a call, through
        send(room_id, events) -> (accepted ids, duplicate ids[, rejected [{id, error}]]), or None for a failure,
        which stops the flush. At most `max_batches` calls, and none started once `budget_s` has passed. Then,
        whatever was sent, an outbox over its cap keeps its newest 0.9 x cap. -> how many events left it."""
        began = time.monotonic()
        events = self.pending()
        rooms: dict[str, list] = {}
        for event in events:
            rooms.setdefault(event.get("room_id"), []).append(event)
        done: set = set()
        dead: list = []
        calls = 0
        stop = False
        for room_id, items in rooms.items():
            for i in range(0, len(items), batch):
                if calls >= max_batches or (budget_s is not None and time.monotonic() - began >= budget_s):
                    stop = True
                    break
                calls += 1
                chunk = items[i:i + batch]
                answer = send(room_id, chunk)
                if answer is None:
                    stop = True
                    break
                accepted, duplicate, *rest = answer
                done.update(accepted or ())
                done.update(duplicate or ())
                errors = {r.get("id"): r.get("error") for r in (rest[0] if rest else None) or ()
                          if isinstance(r, dict)}
                for event in chunk:
                    if event["id"] in errors and event["id"] not in done:
                        done.add(event["id"])
                        dead.append({"error": errors[event["id"]], "event": event})
            if stop:
                break
        if dead:
            try:
                self._bury(dead)
            except Exception as err:
                self._warn("dead-letter write", err)
        with self._lock:  # what was appended meanwhile is kept
            current = self._read()
            keep = [e for e in current if e.get("id") and e["id"] not in done]
            if len(keep) > self.cap:
                keep = keep[-int(self.cap * 0.9):]
            if len(keep) != len(current):
                self._rewrite(keep)
        return len(done)
