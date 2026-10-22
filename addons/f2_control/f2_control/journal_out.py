"""The controller's journal outbox: events (spec section 4, v 1) for the integration's event journal.

Each event is one JSON line in `journal_outbox.jsonl`, beside the state file. Emitting is a local append and
nothing else, and it never raises: the journal is never on the watering path (ruling R5). Only `durable=True`
(shot.started, written before the pump opens) is fsynced. The controller flushes the outbox after its pass
(Controller._flush_journal) to crop_steering.journal_append, which is idempotent on `id`, and an event leaves
the file only once the integration has it (accepted or duplicate). The file keeps at most `cap` events,
dropping the oldest. The integration, not this file, assigns `seq`.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime

from crop_steering_engine.ids import new_id

CAP = 5000
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
        try:
            with open(path, encoding="utf-8") as fh:
                self._count = sum(1 for line in fh if line.strip())
        except OSError:  # no outbox yet (or unreadable): it starts empty
            self._count = 0

    def _warn(self, what, err):
        if not self._warned:  # one line per run: a full disk must not flood the log
            self._warned = True
            _log(f"journal outbox: {what} failed ({err}); events may be lost, watering is not affected")

    def emit(self, room_prefix: str, kind: str, *, zone=None, outcome="ok", code=None, actor="engine",
             detail=None, program_id=None, data=None, correlation=None, readback=None, durable=False,
             now: datetime | None = None) -> str:
        """Append one event for the room with this prefix ("" or "f2_", never its slug) -> its id."""
        event_id = new_id()
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
                        os.fsync(fh.fileno())
                self._count += 1
                if self._count > self.cap:
                    self._rewrite(self._read()[-self.cap:], durable)
        except Exception as err:
            self._warn("emit", err)
        return event_id

    def _read(self) -> list[dict]:
        """The events in the file, oldest first; a torn line (a crash mid-append) is skipped."""
        out = []
        try:
            with open(self.path, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(event, dict) and event.get("id"):
                        out.append(event)
        except FileNotFoundError:
            pass
        return out

    def _rewrite(self, events, durable=False):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.writelines(json.dumps(e, default=str) + "\n" for e in events)
            if durable:
                fh.flush()
                os.fsync(fh.fileno())
        os.replace(tmp, self.path)
        self._count = len(events)

    def pending(self) -> list[dict]:
        with self._lock:
            return self._read()

    def flush(self, send, batch: int = 50, max_batches: int = 4) -> int:
        """Send the pending events, each room's in order and at most `batch` to a call, through
        send(room_id, events) -> (accepted ids, duplicate ids), or None for a failure, which stops the flush.
        At most `max_batches` calls. -> how many events left the outbox."""
        events = self.pending()
        rooms: dict[str, list] = {}
        for event in events:
            rooms.setdefault(event.get("room_id"), []).append(event)
        done: set = set()
        calls = 0
        for room_id, items in rooms.items():
            for i in range(0, len(items), batch):
                if calls >= max_batches:
                    break
                calls += 1
                answer = send(room_id, items[i:i + batch])
                if answer is None:
                    break
                accepted, duplicate = answer
                done.update(accepted or ())
                done.update(duplicate or ())
            else:
                continue
            break
        if done:
            with self._lock:  # what was appended meanwhile is kept
                self._rewrite([e for e in self._read() if e.get("id") not in done])
        return len(done)
