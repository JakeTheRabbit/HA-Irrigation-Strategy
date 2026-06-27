"""In-place upgrade contract for the f2-control add-on.

The add-on persists per-zone runtime state to /data/state.json (non-ephemeral). It is
live-installed on many boxes, old and new, so a version bump MUST load an OLDER state
file transparently in place: a missing file, missing keys, unknown extra keys, a bad
timestamp, and zones not present in the file must all be tolerated — new fields fall
back to fresh defaults, never an error, never a wipe. These tests lock that contract so
a future change can't silently break existing installs.
"""

import json
import sys
import types
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addons" / "f2_control" / "f2_control"  # controller.py + vendored engine

# controller.py imports `requests` (only present inside the add-on container). Stub it so
# the module imports offline; we only exercise the pure state load/save logic here.
if "requests" not in sys.modules:
    _req = types.ModuleType("requests")
    _req.Session = lambda: types.SimpleNamespace(get=None, post=None, headers={})
    sys.modules["requests"] = _req

if str(ADDON) not in sys.path:
    sys.path.insert(0, str(ADDON))

import controller as C  # noqa: E402  (after sys.path / stub setup)


def _make(zones, state_path):
    """A Controller with just the attributes _load_state/_save_state need — no __init__,
    so no HA connection, signals, or option parsing."""
    c = C.Controller.__new__(C.Controller)
    c.zones = list(zones)
    c._state_path = str(state_path)
    return c


def test_missing_file_yields_fresh_state(tmp_path):
    c = _make([1, 2, 3], tmp_path / "does_not_exist.json")
    st = c._load_state()
    assert set(st) == {1, 2, 3}
    assert all(st[z]["phase"] == "P2" for z in st)  # fresh-zone default


def test_corrupt_json_yields_fresh_state(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{ this is not valid json", encoding="utf-8")
    c = _make([1], p)
    st = c._load_state()  # must not raise
    assert st[1]["phase"] == "P2"


def test_old_partial_state_keeps_known_drops_unknown_seeds_new(tmp_path):
    p = tmp_path / "state.json"
    # An "old" file: only a couple of keys, an unknown legacy field, and only zone 1.
    p.write_text(
        json.dumps({"1": {"phase": "P1", "peak": 55.0, "legacy_removed_field": 7}}),
        encoding="utf-8",
    )
    c = _make([1, 2], p)
    st = c._load_state()
    assert st[1]["phase"] == "P1"  # known key restored
    assert st[1]["peak"] == 55.0
    assert "legacy_removed_field" not in st[1]  # unknown key ignored
    assert "shots" in st[1]  # a key absent from the file -> fresh default present
    assert st[2]["phase"] == "P2"  # a zone absent from the file -> seeded fresh


def test_bad_timestamp_is_tolerated(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(
        json.dumps({"1": {"phase": "P3", "last_shot": "not-a-date"}}), encoding="utf-8"
    )
    c = _make([1], p)
    st = c._load_state()  # must not raise
    assert st[1]["phase"] == "P3"
    assert st[1]["last_shot"] is None  # unparseable value rejected, default kept


def test_save_then_load_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    c = _make([1], p)
    c.state = {1: c._fresh_zone()}
    c.state[1].update(
        {
            "phase": "P1",
            "peak": 61.0,
            "shots": 3,
            "last_shot": datetime(2026, 6, 27, 10, 5),
            "last_daily_reset": date(2026, 6, 27),
        }
    )
    c._save_state()
    st = _make([1], p)._load_state()
    assert st[1]["phase"] == "P1"
    assert st[1]["peak"] == 61.0
    assert st[1]["shots"] == 3
    assert st[1]["last_shot"] == datetime(2026, 6, 27, 10, 5)
    assert st[1]["last_daily_reset"] == date(2026, 6, 27)
