"""What Jev decided, newest first: every answer it gave, what code did with it, and how it turned out.

The ledger keeps only what acted, for track records. The journal keeps every decision, including the answers
that asked for nothing and the directives code refused, so the dashboard's live log can show the whole story.
It is a JSON-lines file in /data (it survives restarts, like the ledger) holding the last MAX_KEPT entries.
"""
from __future__ import annotations

import json
import os
import threading

MAX_KEPT = 400  # on disk and in memory; the oldest go first
SHOWN = 30  # entries published on the room's jev_log sensor (Home Assistant records attributes under 16 KB)

TITLES = {
    "dawn": "Morning start", "ramp": "Ramp hand-over", "salt": "Pore EC", "dusk": "Day end",
    "probe": "Probe trust", "shot": "Shot landing", "night": "Night low", "zones": "Zone comparison",
    "stage": "Stage arc", "setpoints": "Setpoints",
}
ADVANCE = {"P1": "start the ramp now", "P2": "hand over to maintenance", "P3": "end the day's watering"}
EC_MODE = {"hold": "hold the EC steer", "decay": "ease the EC steer back", "steer": "let the EC steer work"}


def action_words(d):
    """A directive in a few plain words, or "" for none."""
    if d is None:
        return ""
    if d.kind == "advance":
        return ADVANCE.get(d.value, f"move to {d.value}")
    if d.kind == "distrust":
        return f"set the probe aside ({str(d.value).replace('_', ' ')})"
    if d.kind == "ec_mode":
        return EC_MODE.get(d.value, f"EC steer: {d.value}")
    if d.kind == "alert":
        v = d.value if isinstance(d.value, dict) else {}
        return f"{v.get('code', 'alert')}: {v.get('title', '')}".strip(": ")
    if d.kind == "setpoint":
        v = d.value if isinstance(d.value, dict) else {}
        return v.get("words") or f"{v.get('suffix')} {v.get('from')} -> {v.get('to')}"
    return f"{d.kind} {d.value}"


def verdict_words(label):
    if label is None:
        return "no answer"
    if isinstance(label, bool):
        return "yes" if label else "no"
    return str(label).replace("_", " ")


class Journal:
    def __init__(self, path=None):
        self.path = path
        self.entries: list[dict] = []
        self.version = 0  # bumped on every change, so a publisher can skip unchanged passes
        self._lock = threading.Lock()
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    self.entries = [json.loads(line) for line in fh if line.strip()]
            except (OSError, ValueError):
                self.entries = []  # a damaged journal starts again, never a reason to stop
            self.entries = self.entries[-MAX_KEPT:]

    def add(self, entry: dict):
        with self._lock:
            self.entries.append(entry)
            trimmed = len(self.entries) > MAX_KEPT
            self.entries = self.entries[-MAX_KEPT:]
            self.version += 1
            self._save(entry, rewrite=trimmed)

    def recent(self, room, limit=SHOWN):
        """This room's newest `limit` entries, newest first, without the room field and with the free-text
        fields capped, so the published list stays well under Home Assistant's 16 KB attribute limit."""
        with self._lock:
            mine = [e for e in reversed(self.entries) if e.get("room") == room][:limit]
        caps = {"reason": 120, "verdict": 80, "action": 80}
        return [{k: (v[:caps[k]] if k in caps and isinstance(v, str) else v) for k, v in e.items() if k != "room"}
                for e in mine]

    def _save(self, entry, rewrite):
        if not self.path:
            return
        try:
            if rewrite:
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    for e in self.entries:
                        fh.write(json.dumps(e, default=str) + "\n")
                os.replace(tmp, self.path)
            else:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, default=str) + "\n")
        except OSError:
            pass  # a journal that can't be written is a shorter log, never a stopped controller


def decision(room, zone, judge, at, verdicts, directive, result, reason):
    """One decision entry: the judge's main verdict, what it asked for, and what code did with it.
    `result` is "acted", "refused", "no action" or "waiting"; `reason` is code's why."""
    main = next((v for v in verdicts.values() if v is not None), None)
    return {
        "t": at.isoformat(timespec="seconds"), "room": room, "zone": zone, "judge": judge,
        "title": TITLES.get(judge, judge), "kind": "decision",
        "verdict": verdict_words(None if main is None else main.label),
        "p": None if main is None or main.prob is None else round(float(main.prob), 2),
        "agreed": None if main is None else bool(main.agreed),
        "action": action_words(directive), "result": result, "reason": str(reason or "")[:120],
    }


def label_words(action, label):
    """A ledger entry's action and label in plain words ("hold the EC steer", "smaller shots")."""
    label = "" if label is None else str(label)
    if action == "advance":
        return ADVANCE.get(label, f"move to {label}")
    if action == "ec_mode":
        return EC_MODE.get(label, f"EC steer: {label}")
    if action == "distrust":
        return f"set the probe aside ({label.replace('_', ' ')})"
    return label.replace("_", " ")


def outcome(room, zone, judge, at, label, what, good, of=None, action=None):
    """An outcome entry: how an earlier action turned out. `of` is the time of the decision it checks (the
    decision entry's `t`), so the dashboard can show the outcome on that decision instead of as its own row."""
    return {
        "t": at.isoformat(timespec="seconds"), "room": room, "zone": zone, "judge": judge,
        "title": TITLES.get(judge, judge), "kind": "outcome", "verdict": label_words(action, label),
        "of": of, "p": None, "agreed": None,
        "action": "", "result": "worked" if good else "did not work", "reason": str(what or "")[:120],
    }
