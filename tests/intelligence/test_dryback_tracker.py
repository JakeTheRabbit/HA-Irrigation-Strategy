"""Unit tests for the local dryback episode tracker in root_zone.py.

These tests do not need an AppDaemon runtime — they exercise the pure
state-machine logic of `_step_dryback_tracker` on a `RootZoneIntelligence`
instance whose AppDaemon hooks are stubbed out.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from . import _appdaemon_stub  # noqa: F401 — installs the AppDaemon stub

from crop_steering.intelligence.root_zone import (  # noqa: E402
    DEFAULT_DRYBACK_MIN_DROP_PCT,
    DEFAULT_DRYBACK_MIN_DURATION_MIN,
    RootZoneIntelligence,
)


@pytest.fixture
def app(tmp_path):
    """Build a RootZoneIntelligence with all AppDaemon side effects neutered."""
    a = RootZoneIntelligence.__new__(RootZoneIntelligence)
    a.app_dir = str(tmp_path)
    a.args = {}
    # Manually reproduce what initialize() sets up, skipping AppDaemon I/O.
    from collections import defaultdict, deque
    from crop_steering.intelligence.bus import RootSenseBus
    from crop_steering.intelligence.store import RootSenseStore
    from crop_steering.intelligence.root_zone import DrybackTracker, FieldCapacityState

    a.bus = RootSenseBus.instance()
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    a.store = RootSenseStore(state_dir / "rootsense.db")
    a.dryback_min_drop_pct = DEFAULT_DRYBACK_MIN_DROP_PCT
    a.dryback_min_duration_min = DEFAULT_DRYBACK_MIN_DURATION_MIN
    a._dryback = defaultdict(DrybackTracker)
    a._fc = defaultdict(FieldCapacityState)
    a._vwc_buf = defaultdict(lambda: deque(maxlen=1440))
    a._ec_buf = defaultdict(lambda: deque(maxlen=1440))
    a._pending = {}

    # No-op the HA-side emit
    a.fire_event = lambda *a_, **k_: None
    a.set_state = lambda *a_, **k_: None
    a.log = lambda *a_, **k_: None
    a.get_state = lambda *a_, **k_: "P0"
    return a


def _drive(app, zone: int, samples: list[tuple[int, float]]):
    """Feed (minutes_offset, vwc) samples into the tracker."""
    base = datetime(2026, 4, 26, 6, 0, 0)
    for minute, vwc in samples:
        ts = base + timedelta(minutes=minute)
        app._step_dryback_tracker(zone, ts, vwc, ec=2.5)


def test_dryback_emits_after_full_cycle(app):
    """Peak → 20%-drop valley → rebound > min_drop emits one episode."""
    captured = []

    def grab(name, **payload):  # fire_event signature
        if name == "crop_steering_dryback_complete":
            captured.append(payload)

    app.fire_event = grab

    # Sample series: rise to 70%, drop to 50% over 60 min, then rebound to 53%.
    series = (
        [(0, 60.0), (5, 65.0), (10, 70.0)]                      # peak
        + [(15, 68.0), (30, 60.0), (60, 50.0), (75, 50.0)]      # valley
        + [(90, 53.0)]                                          # rebound > min_drop_pct
    )
    _drive(app, zone=1, samples=series)

    assert len(captured) == 1
    ep = captured[0]
    assert ep["zone"] == 1
    assert ep["peak_vwc"] == 70.0
    assert ep["valley_vwc"] == 50.0
    assert ep["pct"] == 20.0
    assert ep["duration_min"] >= DEFAULT_DRYBACK_MIN_DURATION_MIN


def test_short_dryback_is_ignored(app):
    """Drop that's too short in duration must not emit."""
    captured = []
    app.fire_event = lambda name, **payload: captured.append(payload)

    _drive(app, zone=2, samples=[
        (0, 70.0), (5, 68.0), (10, 65.0), (12, 67.0),  # rebound at 12 min
    ])
    assert captured == []


def test_micro_fluctuation_is_ignored(app):
    """Tiny VWC wobbles below dryback_min_drop_pct must not emit episodes."""
    captured = []
    app.fire_event = lambda name, **payload: captured.append(payload)

    _drive(app, zone=3, samples=[
        (0, 70.0), (10, 69.7), (20, 70.0), (30, 69.9), (60, 70.1),
    ])
    assert captured == []


def test_new_higher_peak_resets_tracker(app):
    """If VWC rises strictly above the current peak, we should be tracking
    the new peak rather than emitting a fake episode for the wobble."""
    captured = []
    app.fire_event = lambda name, **payload: captured.append(payload)

    _drive(app, zone=4, samples=[
        (0, 60.0), (10, 65.0), (20, 70.0),       # peak at 70
        (30, 69.5),                               # tiny dip
        (40, 72.0),                               # new higher peak
    ])
    assert captured == []
    tracker = app._dryback[4]
    assert tracker.peak_vwc == 72.0
