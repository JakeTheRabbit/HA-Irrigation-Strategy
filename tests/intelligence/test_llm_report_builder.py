"""Unit tests for the L0 report builder.

L0 means: build the JSON, publish it as a sensor + event, but make NO
LLM call. We test the pure helpers (classify_status, compute_deltas,
compute_triage, estimate_tokens) plus an integration-style test that
exercises build_report() against a synthetic state-getter.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from . import _appdaemon_stub  # noqa: F401

from crop_steering.intelligence.llm.report_builder import (  # noqa: E402
    RootSenseReportBuilder,
    classify_status,
    compute_deltas,
    compute_triage,
    estimate_tokens,
)
from crop_steering.intelligence.climate.hardware import (  # noqa: E402
    HardwareCalibration, SensorMap,
)


# ───────────────────────────────────────────── classify_status

@pytest.mark.parametrize("value, target, tol, want", [
    (25.0, 25.0, 1.0, "on_target"),
    (25.4, 25.0, 1.0, "on_target"),     # err 0.4 ≤ 0.5*tol → on_target
    (25.6, 25.0, 1.0, "near_target"),   # err 0.6 > 0.5*tol but ≤ tol
    (24.0, 25.0, 1.0, "near_target"),   # err 1.0 == tol exactly → near_target (inclusive band)
    (26.5, 25.0, 1.0, "off_target"),    # err 1.5 > tol → off_target
    (23.5, 25.0, 1.0, "off_target"),    # err 1.5 > tol → off_target (other side)
])
def test_classify_status_buckets(value, target, tol, want):
    assert classify_status(value, target, tol) == want


# ───────────────────────────────────────────── compute_deltas

def test_compute_deltas_skips_below_threshold():
    a = {"climate": {"temp_c": 26.0, "rh_pct": 60.0}}
    b = {"climate": {"temp_c": 26.4, "rh_pct": 62.5}}
    deltas = compute_deltas(a, b, threshold=1.0)
    # temp delta = 0.4 (below threshold) → skipped
    assert "climate.temp_c" not in deltas
    # rh delta = 2.5 → kept
    assert "climate.rh_pct" in deltas
    assert deltas["climate.rh_pct"].startswith("+")


def test_compute_deltas_walks_nested_substrate():
    a = {"substrate": {"1": {"vwc": 60.0, "ec": 4.0}, "2": {"vwc": 58.0, "ec": 5.0}}}
    b = {"substrate": {"1": {"vwc": 60.0, "ec": 4.1}, "2": {"vwc": 58.5, "ec": 5.5}}}
    deltas = compute_deltas(a, b, threshold=0.3)
    # zone 1 ec: 0.1 below threshold
    assert "substrate.1.ec" not in deltas
    # zone 2 ec: 0.5 above threshold
    assert "substrate.2.ec" in deltas


def test_compute_deltas_handles_missing_keys():
    a = {"climate": {"temp_c": 26.0}}
    b = {"climate": {"temp_c": 27.5, "co2_ppm": 1200}}  # co2_ppm new
    deltas = compute_deltas(a, b, threshold=1.0)
    assert "climate.temp_c" in deltas
    # New keys: no prior value → not in deltas
    assert "climate.co2_ppm" not in deltas


# ───────────────────────────────────────────── compute_triage

def test_triage_anomaly_takes_precedence():
    snap = {"climate": {"temp_status": "off_target"}}
    triage = compute_triage(snap, {"ec_drift_high:zone=2"},
                             last_triage_at=None, now=datetime(2026, 1, 1))
    assert triage.startswith("anomaly:")


def test_triage_drift_when_metric_off_target():
    snap = {"climate": {"temp_status": "off_target", "rh_status": "on_target"}}
    triage = compute_triage(snap, set(), last_triage_at=datetime(2026, 1, 1, 12, 0, 0),
                             now=datetime(2026, 1, 1, 12, 30, 0))
    assert triage == "drift:temp"


def test_triage_heartbeat_after_24h():
    snap = {"climate": {"temp_status": "on_target"}}
    triage = compute_triage(snap, set(),
                             last_triage_at=datetime(2026, 1, 1, 12, 0, 0),
                             now=datetime(2026, 1, 2, 13, 0, 0))
    assert triage == "heartbeat"


def test_triage_ok_when_quiet_and_recent():
    snap = {"climate": {"temp_status": "on_target", "rh_status": "on_target"}}
    triage = compute_triage(snap, set(),
                             last_triage_at=datetime(2026, 1, 1, 12, 0, 0),
                             now=datetime(2026, 1, 1, 13, 0, 0))
    assert triage == "ok"


# ───────────────────────────────────────────── estimate_tokens

def test_estimate_tokens_proportional_to_payload_size():
    small = {"a": 1}
    big = {"a": list(range(100))}
    assert estimate_tokens(big) > estimate_tokens(small)


def test_l0_target_payload_under_500_tokens():
    """The whole point of L0 is a compact report. A realistic full
    snapshot with 6 substrate zones + climate + anomalies must come in
    well under 500 tokens to keep future LLM-call costs low."""
    realistic = {
        "ts": "2026-04-26T15:30:00Z",
        "phase": "P2", "intent": 0,
        "recipe_phase": "Mid flower (week 3-5)", "recipe_day": 28,
        "climate": {
            "temp_c": 26.5, "temp_target": 26.0, "temp_status": "near_target",
            "rh_pct": 56, "rh_target": 55, "rh_status": "on_target",
            "leaf_vpd_kpa": 1.14, "leaf_vpd_target": 1.20, "leaf_vpd_status": "near_target",
            "co2_ppm": 1280, "co2_target": 1300, "co2_status": "near_target",
            "lights_on": True,
            "dli_today_mol": 16.2, "dli_predicted_mol": 37.4,
        },
        "substrate": {
            str(i): {"vwc": 58.0, "ec": 4.1, "dryback_h": 0.8, "fc": 68.5}
            for i in range(1, 7)
        },
        "deltas_15m_ago": {"climate.rh_pct": "+2", "substrate.2.ec": "+0.3"},
        "active_anomalies": ["ec_drift_high:zone=2"],
        "triage": "anomaly:ec_drift_high",
    }
    tokens = estimate_tokens(realistic)
    assert tokens < 500, f"L0 report at {tokens} tokens — too big for cheap LLM calls"


# ───────────────────────────────────────────── build_report integration

@pytest.fixture
def builder(tmp_path):
    """Build a RootSenseReportBuilder bypassing AppDaemon initialize()."""
    b = RootSenseReportBuilder.__new__(RootSenseReportBuilder)
    b.app_dir = str(tmp_path)
    b.args = {}
    from crop_steering.intelligence.bus import RootSenseBus
    from crop_steering.intelligence.store import RootSenseStore
    from collections import deque
    b.bus = RootSenseBus.instance()
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    b.store = RootSenseStore(state_dir / "rootsense.db")
    b._history = deque(maxlen=8)
    b._active_anomalies = set()
    b._last_triage_at = None
    b.delta_threshold = 1.0
    b.hw = HardwareCalibration(
        room="F1",
        sensors=SensorMap(
            temp_primary="sensor.gw_room_1_temp",
            rh_primary="sensor.gw_room_1_rh",
            co2="sensor.gw_room_1_co2",
            vpd="sensor.gw_room_1_vpd",
            lights_on="binary_sensor.gw_lights_on",
            leaf_temp="sensor.gw_room_1_leaf_temp",
        ),
    )
    return b


def _state_table(**overrides) -> dict[str, str]:
    """A realistic synthetic HA state snapshot for the report builder."""
    base = {
        "select.crop_steering_irrigation_phase": "P2",
        "number.crop_steering_steering_intent": "0",
        "sensor.climate_recipe_active_phase": "Mid flower (week 3-5)",
        "number.crop_steering_climate_grow_day_offset": "28",
        # Sensors
        "sensor.gw_room_1_temp": "26.5",
        "sensor.gw_room_1_rh": "56",
        "sensor.gw_room_1_co2": "1280",
        "sensor.gw_room_1_vpd": "1.18",
        "sensor.climate_leaf_vpd_kpa": "1.14",
        "binary_sensor.gw_lights_on": "on",
        # Targets (day, since lights on)
        "sensor.climate_target_day_temp_c": "26.0",
        "sensor.climate_target_day_rh_pct": "55",
        "sensor.climate_target_co2_ppm": "1300",
        "sensor.climate_target_leaf_vpd_kpa": "1.20",
        # DLI
        "sensor.climate_dli_today_mol": "16.2",
        "sensor.climate_dli_predicted_mol": "37.4",
        # Substrate (zones 1-6)
        **{f"sensor.crop_steering_zone_{i}_avg_vwc": str(60 - i)
           for i in range(1, 7)},
        **{f"sensor.crop_steering_zone_{i}_avg_ec": str(4.0 + i * 0.1)
           for i in range(1, 7)},
    }
    base.update(overrides)
    return base


def test_build_report_basic_shape(builder):
    state = _state_table()
    report = builder.build_report(now=datetime(2026, 5, 1, 14, 0, 0),
                                    state_overrides=state)
    assert report["phase"] == "P2"
    assert report["recipe_phase"] == "Mid flower (week 3-5)"
    assert report["recipe_day"] == 28
    assert report["climate"]["temp_c"] == 26.5
    assert report["climate"]["temp_status"] in ("on_target", "near_target")
    # Leaf VPD as primary
    assert "leaf_vpd_kpa" in report["climate"]
    assert "leaf_vpd_target" in report["climate"]
    # 6 substrate zones
    assert len(report["substrate"]) == 6
    # Token estimate
    assert report["estimated_tokens"] > 0


def test_build_report_uses_night_target_when_lights_off(builder):
    state = _state_table(**{
        "binary_sensor.gw_lights_on": "off",
        "sensor.climate_target_night_temp_c": "20.0",
        "sensor.climate_target_night_rh_pct": "48",
    })
    report = builder.build_report(now=datetime(2026, 5, 1, 22, 0, 0),
                                    state_overrides=state)
    # Night target is selected, day target is ignored
    assert report["climate"]["temp_target"] == 20.0
    assert report["climate"]["rh_target"] == 48.0


def test_build_report_includes_active_anomalies(builder):
    builder._active_anomalies = {"ec_drift_high:zone=2", "climate_temp_excursion"}
    state = _state_table()
    report = builder.build_report(now=datetime(2026, 5, 1, 14, 0, 0),
                                    state_overrides=state)
    assert "ec_drift_high:zone=2" in report["active_anomalies"]
    assert report["triage"].startswith("anomaly:")


def test_build_report_triage_drift_when_temp_off(builder):
    state = _state_table(**{
        "sensor.gw_room_1_temp": "30.0",  # well above 26 target
    })
    report = builder.build_report(now=datetime(2026, 5, 1, 14, 0, 0),
                                    state_overrides=state)
    assert report["climate"]["temp_status"] == "off_target"
    assert report["triage"] == "drift:temp"


def test_build_report_deltas_against_prior_history(builder):
    state1 = _state_table()
    r1 = builder.build_report(now=datetime(2026, 5, 1, 14, 0, 0),
                                state_overrides=state1)
    builder._history.append(r1)
    state2 = _state_table(**{"sensor.gw_room_1_rh": "62"})  # +6 from baseline 56
    r2 = builder.build_report(now=datetime(2026, 5, 1, 14, 15, 0),
                                state_overrides=state2)
    assert "climate.rh_pct" in r2["deltas_15m_ago"]
    assert r2["deltas_15m_ago"]["climate.rh_pct"].startswith("+")


def test_build_report_l0_does_not_call_llm(builder):
    """The whole point of L0: zero LLM calls. We assert by construction —
    the module simply doesn't import any LLM client. If someone adds
    one, this test will start failing for a real reason."""
    import crop_steering.intelligence.llm.report_builder as mod
    assert "anthropic" not in mod.__dict__
    assert "openai" not in mod.__dict__
    # And the only http-ish thing in the module is json
    src = open(mod.__file__, encoding="utf-8").read()
    assert "import requests" not in src
    assert "import aiohttp" not in src
