"""Unit tests for AnomalyScanner per-zone and peer rules.

Each rule is exercised in isolation. The scanner's tick loop is not
called — we drive its private rule methods with synthetic state so the
tests stay fast and deterministic.
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta

import pytest

from . import _appdaemon_stub  # noqa: F401

from crop_steering.intelligence.anomaly import AnomalyScanner  # noqa: E402
from crop_steering.intelligence.bus import RootSenseBus  # noqa: E402
from crop_steering.intelligence.store import RootSenseStore  # noqa: E402


@pytest.fixture
def scanner(tmp_path):
    """A bare AnomalyScanner whose state-write side effects are captured."""
    a = AnomalyScanner.__new__(AnomalyScanner)
    a.app_dir = str(tmp_path)
    a.args = {}
    a.bus = RootSenseBus.instance()
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    a.store = RootSenseStore(state_dir / "rootsense.db")
    a.scan_interval_s = 60
    a.peer_groups = {}
    a._vwc_buf = defaultdict(lambda: deque(maxlen=60))
    a._ec_buf = defaultdict(lambda: deque(maxlen=360))
    a._last_dryback_ts = {}
    a._consecutive_low_response_shots = defaultdict(int)
    a._active_anomalies = set()

    a.fired = []
    a.set_state = lambda *a_, **k_: None
    a.log = lambda *a_, **k_: None

    def fake_fire(name, **payload):
        a.fired.append((name, payload))

    a.fire_event = fake_fire

    a._states: dict[str, str | float | None] = {}
    a.get_state = lambda eid, *_, **__: a._states.get(eid)
    a._is_module_enabled = lambda: True
    return a


def test_emitter_blockage_after_three_low_response_shots(scanner):
    """Three consecutive shots with ΔVWC < 0.3 % raise emitter_blockage."""
    payload = {"zone": 1, "delta": 0.1, "pre_vwc": 60.0, "peak_vwc": 60.05}
    scanner._on_shot_response("shot.response", payload)
    scanner._on_shot_response("shot.response", payload)
    assert not any(c == "crop_steering_anomaly" for c, _ in scanner.fired)
    scanner._on_shot_response("shot.response", payload)
    codes = [p["code"] for c, p in scanner.fired if c == "crop_steering_anomaly"]
    assert "emitter_blockage" in codes


def test_responsive_shot_resets_low_response_counter(scanner):
    """A healthy shot in the middle resets the consecutive count."""
    low = {"zone": 2, "delta": 0.1, "pre_vwc": 60.0, "peak_vwc": 60.05}
    healthy = {"zone": 2, "delta": 1.5, "pre_vwc": 60.0, "peak_vwc": 61.5}
    scanner._on_shot_response("shot.response", low)
    scanner._on_shot_response("shot.response", low)
    scanner._on_shot_response("shot.response", healthy)
    scanner._on_shot_response("shot.response", low)
    codes = [p["code"] for c, p in scanner.fired if c == "crop_steering_anomaly"]
    assert "emitter_blockage" not in codes


def test_ec_drift_high_when_mean_exceeds_target(scanner):
    """6h mean EC > 1.3× target raises ec_drift_high."""
    now = datetime.utcnow()
    for i in range(60):
        scanner._ec_buf[3].append((now - timedelta(minutes=i), 4.0))  # mean 4.0
    scanner._states["number.crop_steering_zone_3_ec_target"] = "2.5"  # 4 / 2.5 = 1.6×
    scanner._check_ec_drift_high(zone=3)
    codes = [p["code"] for c, p in scanner.fired if c == "crop_steering_anomaly"]
    assert "ec_drift_high" in codes


def test_ec_drift_clears_when_mean_returns_to_normal(scanner):
    """Once EC settles back, the anomaly is cleared from the active set."""
    now = datetime.utcnow()
    for i in range(60):
        scanner._ec_buf[4].append((now - timedelta(minutes=i), 4.0))
    scanner._states["number.crop_steering_zone_4_ec_target"] = "2.5"
    scanner._check_ec_drift_high(zone=4)
    assert "ec_drift_high:4" in scanner._active_anomalies

    # Replace buffer with healthy values
    scanner._ec_buf[4].clear()
    for i in range(60):
        scanner._ec_buf[4].append((now - timedelta(minutes=i), 2.6))
    scanner._check_ec_drift_high(zone=4)
    assert "ec_drift_high:4" not in scanner._active_anomalies


def test_vwc_flat_line_during_photoperiod(scanner):
    """Stddev < 0.05 over 30 min during photoperiod raises vwc_flat_line."""
    scanner._states["binary_sensor.crop_steering_lights"] = "on"
    now = datetime.utcnow()
    for i in range(20):
        # Tiny wobble within ±0.02 — stdev will be far below 0.05.
        scanner._vwc_buf[5].append(
            (now - timedelta(minutes=29 - i), 60.00 + (0.01 if i % 2 else -0.01))
        )
    scanner._check_vwc_flat_line(zone=5)
    codes = [p["code"] for c, p in scanner.fired if c == "crop_steering_anomaly"]
    assert "vwc_flat_line" in codes


def test_vwc_flat_line_skipped_outside_photoperiod(scanner):
    """No flat-line anomaly when lights are off — that's normal at night."""
    scanner._states["binary_sensor.crop_steering_lights"] = "off"
    now = datetime.utcnow()
    for i in range(20):
        scanner._vwc_buf[6].append((now - timedelta(minutes=29 - i), 60.0))
    scanner._check_vwc_flat_line(zone=6)
    codes = [p["code"] for c, p in scanner.fired if c == "crop_steering_anomaly"]
    assert "vwc_flat_line" not in codes


def test_peer_vwc_deviation_outlier(scanner):
    """A zone deviating > 2σ from peer mean raises peer_vwc_deviation.

    With only a few peers the outlier inflates stdev and can mask itself,
    so we use a 6-zone group with one clear outlier — the population stdev
    over [60, 60, 60, 60, 60, 90] is ≈ 11.2 and the outlier sits 25 above
    the mean, comfortably > 2σ.
    """
    for z, v in zip([1, 2, 3, 4, 5, 6], [60.0, 60.0, 60.0, 60.0, 60.0, 90.0]):
        scanner._states[f"sensor.crop_steering_zone_{z}_avg_vwc"] = str(v)
    scanner._check_peer_deviation("flower_a", [1, 2, 3, 4, 5, 6])
    payloads = [p for c, p in scanner.fired if c == "crop_steering_anomaly"]
    deviation_for_6 = [p for p in payloads
                      if p["code"] == "peer_vwc_deviation" and p["zone"] == 6]
    assert deviation_for_6, "expected peer_vwc_deviation anomaly for zone 6"


def test_anomaly_is_not_re_raised_while_active(scanner):
    """Once an anomaly is in _active_anomalies, _raise() must not double-fire."""
    payload = {"zone": 7, "delta": 0.1, "pre_vwc": 60, "peak_vwc": 60.05}
    for _ in range(6):
        scanner._on_shot_response("shot.response", payload)
    emitter_events = [p for c, p in scanner.fired
                      if c == "crop_steering_anomaly" and p["code"] == "emitter_blockage"]
    assert len(emitter_events) == 1
