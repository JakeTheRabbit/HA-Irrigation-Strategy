"""In-place upgrade contract for the f2-control add-on (now multi-room aware).

The add-on persists per-zone runtime state to /data/state.json (non-ephemeral). It is
live-installed on many boxes, old and new, so a version bump MUST load an OLDER state
file transparently in place: a missing file, missing keys, unknown extra keys, a bad
timestamp, and zones not present in the file must all be tolerated — new fields fall
back to fresh defaults, never an error, never a wipe.

Stage 2 nests state by room slug ({"default": {"1": {...}}, "veg": {"1": {...}}}). An
OLD single-room file is FLAT ({"1": {...}, "2": {...}}) and MUST still load transparently
as the 'default' room. These tests lock both contracts so an upgrade can't wipe a live box.
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


def _room(zones, slug="default", prefix=""):
    """A minimal Room for the given zone numbers."""
    z = {
        int(k): {"vwc": f"sensor.x_{prefix}vwc_{k}", "ec": f"sensor.x_{prefix}ec_{k}"}
        for k in zones
    }
    hw = {
        "pump": "switch.p",
        "mainline": "switch.m",
        "valves": {int(k): f"switch.v{k}" for k in zones},
    }
    return C.Room(
        slug, prefix, z, hw, "input_boolean.f2_control_enabled", "", "", 10.0, 22.0
    )


def _make(zones, state_path, rooms=None):
    """A Controller with just the attributes _load_state/_save_state need — no __init__,
    so no HA connection, signals, or option parsing."""
    c = C.Controller.__new__(C.Controller)
    c._state_path = str(state_path)
    c.rooms = rooms if rooms is not None else [_room(zones)]
    return c


def test_dripper_settings_drive_flow_without_plant_count(tmp_path):
    """The dripper flow rate + drippers/plant must drive shot length even if plant_count is
    unset (0) — not silently fall back to the flow_lps option. Regression for "it ignored my
    dripper flowrate and drippers per plant"."""
    c = _make([1], tmp_path / "s.json")
    c.flow_lps = 0.02  # the fallback that must NOT win
    room = c.rooms[0]
    c._zone_num = lambda room, zone, key, default: {
        "plant_count": 0,
        "drippers_per_plant": 2,
    }.get(key, default)
    c._num = lambda ent, default: 1.2 if "dripper_flow_rate" in ent else default
    flow = c._zone_flow_lps(room, 1)
    assert (
        abs(flow - (1 * 2 * 1.2 / 3600.0)) < 1e-9
    )  # plant_count defaults to 1 (it cancels)
    assert flow != 0.02  # did NOT fall back to the option


def test_missing_file_yields_fresh_state(tmp_path):
    c = _make([1, 2, 3], tmp_path / "does_not_exist.json")
    c._load_state()
    st = c.rooms[0].state
    assert set(st) == {1, 2, 3}
    assert all(st[z]["phase"] == "P2" for z in st)  # fresh-zone default


def test_corrupt_json_yields_fresh_state(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{ this is not valid json", encoding="utf-8")
    c = _make([1], p)
    c._load_state()  # must not raise
    assert c.rooms[0].state[1]["phase"] == "P2"


def test_old_flat_partial_state_loads_as_default(tmp_path):
    """An OLD flat file (top-level zone keys) loads as the default room, keeping known keys,
    dropping unknown ones, and seeding absent zones fresh."""
    p = tmp_path / "state.json"
    p.write_text(
        json.dumps({"1": {"phase": "P1", "peak": 55.0, "legacy_removed_field": 7}}),
        encoding="utf-8",
    )
    c = _make([1, 2], p)
    c._load_state()
    st = c.rooms[0].state
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
    c._load_state()  # must not raise
    st = c.rooms[0].state
    assert st[1]["phase"] == "P3"
    assert st[1]["last_shot"] is None  # unparseable value rejected, default kept


def test_save_then_load_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    c = _make([1], p)
    c._load_state()  # seed fresh (no file yet)
    c.rooms[0].state[1].update(
        {
            "phase": "P1",
            "peak": 61.0,
            "shots": 3,
            "last_shot": datetime(2026, 6, 27, 10, 5),
            "last_daily_reset": date(2026, 6, 27),
        }
    )
    c._save_state()
    c2 = _make([1], p)
    c2._load_state()
    st = c2.rooms[0].state
    assert st[1]["phase"] == "P1"
    assert st[1]["peak"] == 61.0
    assert st[1]["shots"] == 3
    assert st[1]["last_shot"] == datetime(2026, 6, 27, 10, 5)
    assert st[1]["last_daily_reset"] == date(2026, 6, 27)


# ----------------------------------------------------------------------- multi-room (Stage 2)


def test_two_rooms_keep_independent_state(tmp_path):
    """Default and a named room have overlapping zone numbers; their state must not clobber."""
    p = tmp_path / "state.json"
    rooms = [_room([1, 2], "default", ""), _room([1], "veg", "veg_")]
    c = _make(None, p, rooms=rooms)
    c._load_state()  # seed fresh
    c.rooms[0].state[1]["phase"] = "P1"
    c.rooms[1].state[1]["phase"] = "P3"
    c._save_state()
    # the file is nested by slug, with both rooms present
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert set(saved) == {"default", "veg"}
    assert saved["default"]["1"]["phase"] == "P1"
    assert saved["veg"]["1"]["phase"] == "P3"
    # reload into fresh rooms -> each keeps its own
    c2 = _make(None, p, rooms=[_room([1, 2], "default", ""), _room([1], "veg", "veg_")])
    c2._load_state()
    assert c2.rooms[0].state[1]["phase"] == "P1"
    assert c2.rooms[1].state[1]["phase"] == "P3"
    assert c2.rooms[0].state[2]["phase"] == "P2"  # untouched default zone stays fresh


def test_old_flat_file_loads_default_only_named_rooms_seed_fresh(tmp_path):
    """Upgrading a live single-room box that now has a second room: the old flat file becomes
    the default room's state; the new room seeds fresh (never errors)."""
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"1": {"phase": "P1", "peak": 60.0}}), encoding="utf-8")
    c = _make(None, p, rooms=[_room([1], "default", ""), _room([1], "veg", "veg_")])
    c._load_state()
    assert c.rooms[0].state[1]["phase"] == "P1"  # old flat -> default room
    assert c.rooms[0].state[1]["peak"] == 60.0
    assert c.rooms[1].state[1]["phase"] == "P2"  # named room seeded fresh


def test_nested_file_loads_per_room(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(
        json.dumps({"default": {"1": {"phase": "P3"}}, "veg": {"1": {"phase": "P1"}}}),
        encoding="utf-8",
    )
    c = _make(None, p, rooms=[_room([1], "default", ""), _room([1], "veg", "veg_")])
    c._load_state()
    assert c.rooms[0].state[1]["phase"] == "P3"
    assert c.rooms[1].state[1]["phase"] == "P1"


# --------------------------------------------------------------------------- options compat
# An old /data/options.json predates the feed_ec_sensor / feed_ph_sensor keys and may carry
# the old facility-specific substrate_l / flow_lps numbers. Loading it must still work, must
# NOT resurrect any F2-specific default entity id, and an unset feed sensor must DISABLE that
# half of the source-water gate (generic, zero-config-safe) rather than poll a dead entity.


def _init(opts, monkeypatch):
    """Full Controller() with load_options() stubbed to `opts` and no HA reachable (the
    module-level requests stub makes every ha_get/ha_call a caught no-op). Returns the
    default room and the controller."""
    monkeypatch.setattr(C, "load_options", lambda: dict(opts))
    c = C.Controller()
    return c, c.rooms[0]


def test_old_options_without_feed_keys_disables_gate(monkeypatch):
    # an "old" file: no feed_* keys at all
    c, room = _init({"num_zones": 2, "substrate_l": 6, "flow_lps": 0.067}, monkeypatch)
    assert room.feed_ec_sensor == ""  # no F2 atlas/aquaponics fallback
    assert room.feed_ph_sensor == ""
    assert (
        c._read_feed_ec(room) is None
    )  # gate reader short-circuits, never polls an entity
    assert c._read_feed_ph(room) is None


def test_blank_or_whitespace_feed_sensor_is_disabled(monkeypatch):
    c, room = _init({"feed_ec_sensor": "   ", "feed_ph_sensor": ""}, monkeypatch)
    assert room.feed_ec_sensor == ""
    assert room.feed_ph_sensor == ""
    assert c._read_feed_ec(room) is None


def test_feed_sensors_honored_when_explicitly_set(monkeypatch):
    # F2 (and any operator) keeps its behavior by setting these explicitly
    opts = {
        "feed_ec_sensor": "sensor.atlas_legacy_1_ec",
        "feed_ph_sensor": "sensor.my_ph",
    }
    c, room = _init(opts, monkeypatch)
    assert room.feed_ec_sensor == "sensor.atlas_legacy_1_ec"
    assert room.feed_ph_sensor == "sensor.my_ph"


def test_substrate_flow_defaults_are_generic_not_f2(monkeypatch):
    # empty options -> code fallbacks; must be generic placeholders, not F2's real numbers
    c, room = _init({}, monkeypatch)
    assert room.feed_ec_sensor == "" and room.feed_ph_sensor == ""
    assert c.substrate_l == 5.0
    assert c.flow_lps == 0.02  # NOT F2's real 0.04


def test_default_room_is_unprefixed(monkeypatch):
    """The default room must stay un-prefixed so a single-room install's entity ids are unchanged."""
    c, room = _init({"num_zones": 1}, monkeypatch)
    assert room.slug == "default" and room.prefix == ""
    assert c._cs(room, "sensor", "vwc_zone_1") == "sensor.crop_steering_vwc_zone_1"
    assert len(c.rooms) == 1  # no extra rooms discovered offline
