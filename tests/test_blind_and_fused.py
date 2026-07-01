"""Regression tests for the 2026-06-30 "frozen in P2" incident.

Root cause was a fused-sensor entity-id mismatch: the engine read
`sensor.crop_steering_vwc_zone_N` but the live box's registry-sticky id was the legacy
`sensor.crop_steering_zone_N_vwc`. The engine found no probe -> every zone went blind ->
`decide()` was skipped -> the phase machine froze in P2 (it never even forced P3 at
lights-off). These lock the two fixes:

  1. `_fused_id` resolves a fused sensor under BOTH naming conventions.
  2. `_blind_time_transition` keeps the time-based phase forces alive while a zone is blind,
     so a dead probe can never strand the daily cycle overnight.
"""

import sys
import types
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addons" / "f2_control" / "f2_control"

# controller.py imports `requests` (only inside the add-on container) — stub it for offline import.
if "requests" not in sys.modules:
    _req = types.ModuleType("requests")
    _req.Session = lambda: types.SimpleNamespace(get=None, post=None, headers={})
    sys.modules["requests"] = _req

if str(ADDON) not in sys.path:
    sys.path.insert(0, str(ADDON))

import controller as C  # noqa: E402


def _ctrl():
    c = C.Controller.__new__(C.Controller)
    c._fused_id_cache = {}
    return c


def _fake_ha_get(present):
    """Return a ha_get stub where only entity_ids in `present` resolve to a value."""

    def _g(eid):
        return ("42.0", {}, None) if eid in present else (None, None, None)

    return _g


def test_fused_id_picks_legacy_when_current_absent(monkeypatch):
    # The live-incident case: only the legacy `zone_N_vwc` id exists.
    monkeypatch.setattr(C, "ha_get", _fake_ha_get({"sensor.crop_steering_zone_1_vwc"}))
    c = _ctrl()
    assert c._fused_id("", "vwc", 1) == "sensor.crop_steering_zone_1_vwc"


def test_fused_id_prefers_current_convention(monkeypatch):
    # Both exist -> the current convention wins.
    monkeypatch.setattr(
        C,
        "ha_get",
        _fake_ha_get(
            {"sensor.crop_steering_vwc_zone_1", "sensor.crop_steering_zone_1_vwc"}
        ),
    )
    c = _ctrl()
    assert c._fused_id("", "vwc", 1) == "sensor.crop_steering_vwc_zone_1"


def test_fused_id_prefix_and_ec(monkeypatch):
    monkeypatch.setattr(
        C, "ha_get", _fake_ha_get({"sensor.crop_steering_f1_zone_2_ec"})
    )
    c = _ctrl()
    assert c._fused_id("f1_", "ec", 2) == "sensor.crop_steering_f1_zone_2_ec"


def test_fused_id_override_wins_when_present(monkeypatch):
    monkeypatch.setattr(C, "ha_get", _fake_ha_get({"sensor.my_custom_probe"}))
    c = _ctrl()
    assert (
        c._fused_id("", "vwc", 1, override="sensor.my_custom_probe")
        == "sensor.my_custom_probe"
    )


def test_fused_id_falls_back_to_current_and_does_not_cache(monkeypatch):
    # Neither id present yet (HA not up) -> returns current convention, but does NOT cache,
    # so it re-resolves once the real entity appears.
    monkeypatch.setattr(C, "ha_get", _fake_ha_get(set()))
    c = _ctrl()
    assert c._fused_id("", "vwc", 1) == "sensor.crop_steering_vwc_zone_1"
    assert ("", "vwc", 1) not in c._fused_id_cache
    # now the legacy entity appears -> it resolves to it (no stale cache from before)
    monkeypatch.setattr(C, "ha_get", _fake_ha_get({"sensor.crop_steering_zone_1_vwc"}))
    assert c._fused_id("", "vwc", 1) == "sensor.crop_steering_zone_1_vwc"


def test_fused_id_caches_a_hit(monkeypatch):
    monkeypatch.setattr(C, "ha_get", _fake_ha_get({"sensor.crop_steering_zone_1_vwc"}))
    c = _ctrl()
    assert c._fused_id("", "vwc", 1) == "sensor.crop_steering_zone_1_vwc"
    # entity vanishes — cached value still returned (no re-probe churn)
    monkeypatch.setattr(C, "ha_get", _fake_ha_get(set()))
    assert c._fused_id("", "vwc", 1) == "sensor.crop_steering_zone_1_vwc"


# ---- blind-zone time transitions ----


def _blind_ctrl_and_room(phase):
    c = C.Controller.__new__(C.Controller)
    c._saved = 0

    def _save():
        c._saved += 1

    c._save_state = _save
    z = {1: {"vwc": "sensor.x_vwc_1", "ec": "sensor.x_ec_1"}}
    hw = {"pump": "switch.p", "mainline": "switch.m", "valves": {1: "switch.v1"}}
    room = C.Room(
        "default", "", z, hw, "input_boolean.f2_control_enabled", "", "", 10.0, 22.0
    )
    room.state = {
        1: {
            "phase": phase,
            "last_phase_change": datetime(2026, 6, 30, 8, 0, 0),
            "daily_vol": 5.0,
            "shots": 3,
            "peak": 55.0,
            "last_daily_reset": None,
            "ec_offset": 1.0,
            "last_ec_steer": None,
            "ec_integral": 0.0,
            "ec_prev_err": 0.0,
        }
    }
    return c, room


def test_blind_zone_forced_to_p3_at_lights_off():
    # A blind zone in P2 at night must still be forced to P3 (no overnight strand).
    c, room = _blind_ctrl_and_room("P2")
    now = datetime(2026, 6, 30, 23, 0, 0)  # lights are off (22:00-10:00)
    c._blind_time_transition(room, 1, now, lights_on=False, lights_just_on=False)
    assert room.state[1]["phase"] == "P3"


def test_blind_zone_p3_to_p0_at_lights_on_resets_counters():
    c, room = _blind_ctrl_and_room("P3")
    now = datetime(2026, 6, 30, 10, 1, 0)  # lights just on
    c._blind_time_transition(room, 1, now, lights_on=True, lights_just_on=True)
    assert room.state[1]["phase"] == "P0"
    assert room.state[1]["daily_vol"] == 0.0
    assert room.state[1]["shots"] == 0
    assert room.state[1]["ec_offset"] == 0.0


def test_blind_zone_holds_phase_midday_without_probe():
    # Mid-day, lights on, in P2: a blind zone cannot drive VWC-based transitions, so it holds.
    c, room = _blind_ctrl_and_room("P2")
    now = datetime(2026, 6, 30, 14, 0, 0)
    c._blind_time_transition(room, 1, now, lights_on=True, lights_just_on=False)
    assert room.state[1]["phase"] == "P2"
    assert c._saved == 0  # no state write when nothing changed
