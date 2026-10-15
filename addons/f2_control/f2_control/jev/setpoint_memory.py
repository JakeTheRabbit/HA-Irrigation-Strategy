"""What the Setpoints judge remembers per zone, in /data/jev_setpoints.json (docs/JEV.md).

- `home`: the operator's own value of each setting Jev may move, the centre of its band. It is the value first
  seen, and it follows the operator: any value Jev did not write becomes the new home.
- `written`: the last value Jev wrote for each setting, so an operator's edit can be told from Jev's own.
- `pending`: a write Home Assistant has not reflected yet, so for a few minutes the old value is not an edit.
- `last`: the last move {suffix, from, to, at, day, words, choice, reverted}.
- `frozen_until`: when a zone paused after a safety revert may be moved again.
"""
from __future__ import annotations

import json
import os
import threading


def _blank():
    return {"home": {}, "written": {}, "pending": None, "last": None, "frozen_until": None}


class SetpointMemory:
    def __init__(self, path=None):
        self.path = path
        self.zones: dict[str, dict] = {}
        self._lock = threading.Lock()
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
                self.zones = {k: {**_blank(), **v} for k, v in data.items() if isinstance(v, dict)}
            except (OSError, ValueError, AttributeError):
                self.zones = {}  # a damaged memory starts again: every zone re-centres on the operator's values

    def zone(self, room, zone):
        with self._lock:
            return self.zones.setdefault(f"{room}:{zone}", _blank())

    def save(self):
        if not self.path:
            return
        with self._lock:
            data = json.dumps(self.zones, default=str, indent=1)
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(data)
            os.replace(tmp, self.path)
        except OSError:
            pass  # lost memory re-centres the bands on the operator's values; it never stops the controller
