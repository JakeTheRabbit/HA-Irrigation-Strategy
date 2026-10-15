"""Every verdict Jev acted on, what code did, and how it turned out.

Entries go to a JSON-lines file in /data (it survives restarts and Rebuilds, like state.json). An entry
that names an `outcome` check is revisited once its time comes; the check's result is written back. A
judge's evidence then carries its own track record ("last 3 hand-overs: VWC held 3 of 3"), and a judge
can refuse to repeat a move that didn't work.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime

MAX_ENTRIES = 2000  # kept in memory and on disk; the oldest go first


class Ledger:
    def __init__(self, path=None):
        self.path = path
        self.entries: list[dict] = []
        self._lock = threading.Lock()
        self._seq = 0
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            self.entries.append(json.loads(line))
            except (OSError, ValueError):
                self.entries = []  # a damaged ledger is started again, never a reason to stop
            self.entries = self.entries[-MAX_ENTRIES:]
            self._seq = max((e.get("id", 0) for e in self.entries), default=0)

    def record(self, judge, room, zone, label, action, evidence=None, check_at=None, check=None, at=None):
        """Add one entry; returns its id. `check_at` (datetime) and `check` (a dict the judge understands)
        schedule an outcome check; `at` is the pass's time (the wall clock when not given)."""
        with self._lock:
            self._seq += 1
            entry = {
                "id": self._seq, "at": (at or datetime.now()).isoformat(timespec="seconds"), "judge": judge,
                "room": room, "zone": zone, "label": str(label), "action": action,
                "evidence": evidence or {}, "check_at": check_at.isoformat() if check_at else None,
                "check": check, "outcome": None,
            }
            self.entries.append(entry)
            self._trim_and_save()
            return entry["id"]

    def due(self, now):
        """Entries whose outcome check is due and not yet done."""
        with self._lock:
            return [e for e in self.entries if e.get("check_at") and e.get("outcome") is None
                    and datetime.fromisoformat(e["check_at"]) <= now]

    def resolve(self, entry_id, outcome, good):
        with self._lock:
            for e in self.entries:
                if e["id"] == entry_id:
                    e["outcome"] = {"what": outcome, "good": bool(good)}
            self._trim_and_save()

    def track(self, judge, room, zone, label=None, last=3):
        """Their last `last` resolved calls for this judge and zone, in one sentence (or "")."""
        with self._lock:
            done = [e for e in self.entries if e["judge"] == judge and e["room"] == room
                    and e["zone"] == zone and e.get("outcome")
                    and (label is None or e["label"] == str(label))][-last:]
        if not done:
            return ""
        good = sum(1 for e in done if e["outcome"]["good"])
        whats = "; ".join(e["outcome"]["what"] for e in done)
        return f"your last {len(done)} call(s) of this kind worked {good} time(s): {whats}"

    def strict(self, judge, room, zone, after=3, clear=2):
        """True while this judge, for this zone, is on the stricter gate: `after` calls in a row that did not work out
        put it there, and `clear` in a row that did take it off. Read from the resolved calls, so a restart keeps it."""
        with self._lock:
            done = [bool(e["outcome"]["good"]) for e in self.entries if e["judge"] == judge
                    and e["room"] == room and e["zone"] == zone and e.get("outcome")]
        on, bad, good = False, 0, 0
        for ok in done:
            bad, good = (0, good + 1) if ok else (bad + 1, 0)
            if bad >= after:
                on = True
            elif on and good >= clear:
                on = False
        return on

    def _trim_and_save(self):
        self.entries = self.entries[-MAX_ENTRIES:]
        if not self.path:
            return
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                for e in self.entries:
                    fh.write(json.dumps(e, default=str) + "\n")
            os.replace(tmp, self.path)
        except OSError:
            pass  # a ledger that can't be written is lost history, never a stopped controller
