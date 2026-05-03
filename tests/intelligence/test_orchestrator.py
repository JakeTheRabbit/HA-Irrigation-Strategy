"""Unit tests for IrrigationOrchestrator gates and emergency triggers."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from . import _appdaemon_stub  # noqa: F401

from crop_steering.intelligence.bus import RootSenseBus  # noqa: E402
from crop_steering.intelligence.orchestration import (  # noqa: E402
    DEFAULT_FLUSH_COOLDOWN_MIN,
    IrrigationOrchestrator,
)
from crop_steering.intelligence.store import RootSenseStore  # noqa: E402


@pytest.fixture
def orchestrator(tmp_path):
    o = IrrigationOrchestrator.__new__(IrrigationOrchestrator)
    o.app_dir = str(tmp_path)
    o.args = {}
    o.bus = RootSenseBus.instance()
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    o.store = RootSenseStore(state_dir / "rootsense.db")
    o.flush_cooldown = timedelta(minutes=DEFAULT_FLUSH_COOLDOWN_MIN)
    o.emergency_vwc = 40.0
    o._last_flush_at = {}
    o._suppressed_zones = set()
    o._is_module_enabled = lambda: True

    o.service_calls: list[tuple[str, dict]] = []

    def fake_call_service(name, **kw):
        o.service_calls.append((name, kw))

    o.call_service = fake_call_service
    o.fire_event = lambda *a, **k: None
    o.log = lambda *a, **k: None

    o._states: dict[str, str | None] = {
        "select.crop_steering_irrigation_phase": "P2",
        "number.crop_steering_steering_intent": "0",
    }
    o.get_state = lambda eid, *_, **__: o._states.get(eid)
    o.entity_exists = lambda eid: True
    return o


def _set_zone(o, zone, *, vwc=None, ec_feed=None, ec_runoff=None,
              flow_lpm=2.0, substrate_l=10.0):
    if vwc is not None:
        o._states[f"sensor.crop_steering_zone_{zone}_avg_vwc"] = str(vwc)
    if ec_feed is not None:
        o._states[f"sensor.crop_steering_zone_{zone}_ec_feed"] = str(ec_feed)
    if ec_runoff is not None:
        o._states[f"sensor.crop_steering_zone_{zone}_ec_runoff"] = str(ec_runoff)
    o._states[f"number.crop_steering_zone_{zone}_dripper_flow_rate"] = str(flow_lpm)
    o._states[f"number.crop_steering_zone_{zone}_substrate_size"] = str(substrate_l)


def test_emergency_rescue_fires_when_vwc_below_threshold(orchestrator):
    _set_zone(orchestrator, 1, vwc=30.0)  # below default 40
    orchestrator._fire_emergency_rescue(zone=1, vwc=30.0)
    custom = [c for c in orchestrator.service_calls if c[0] == "crop_steering/custom_shot"]
    assert custom, "expected custom_shot service call for emergency rescue"
    assert custom[-1][1]["intent"] == "rescue"
    assert custom[-1][1]["target_zone"] == 1


def test_flush_fires_when_runoff_far_above_feed(orchestrator):
    _set_zone(orchestrator, 2, ec_feed=2.0, ec_runoff=4.0)  # 2.0× ratio
    orchestrator._maybe_fire_flush(zone=2)
    flush = [c for c in orchestrator.service_calls
             if c[0] == "crop_steering/custom_shot"
             and c[1].get("intent") == "rebalance_ec"]
    assert flush, "expected flush shot when ec_runoff/ec_feed > 1.5"


def test_flush_cooldown_prevents_back_to_back(orchestrator):
    _set_zone(orchestrator, 3, ec_feed=2.0, ec_runoff=4.0)
    orchestrator._maybe_fire_flush(zone=3)
    first_count = len([c for c in orchestrator.service_calls
                       if c[1].get("intent") == "rebalance_ec"])
    orchestrator._maybe_fire_flush(zone=3)
    orchestrator._maybe_fire_flush(zone=3)
    second_count = len([c for c in orchestrator.service_calls
                        if c[1].get("intent") == "rebalance_ec"])
    assert first_count == 1
    assert second_count == 1, "cooldown must suppress a second flush"


def test_flush_skipped_when_runoff_close_to_feed(orchestrator):
    _set_zone(orchestrator, 4, ec_feed=2.0, ec_runoff=2.5)  # 1.25× — below 1.5
    orchestrator._maybe_fire_flush(zone=4)
    assert not any(c[1].get("intent") == "rebalance_ec"
                   for c in orchestrator.service_calls)


def test_anomaly_critical_suppresses_zone(orchestrator):
    """A critical anomaly on a zone should add it to _suppressed_zones."""
    orchestrator._on_anomaly("anomaly.detected", {
        "zone": 5, "severity": "critical", "code": "valve_runtime",
    })
    assert 5 in orchestrator._suppressed_zones


def test_custom_shot_event_blocked_for_suppressed_zone(orchestrator):
    orchestrator._suppressed_zones.add(6)
    _set_zone(orchestrator, 6, vwc=55)
    orchestrator._on_custom_shot_event(
        "crop_steering_custom_shot",
        {"target_zone": 6, "intent": "manual", "volume_ml": 200, "tag": "test"},
        None,
    )
    fired = [c for c in orchestrator.service_calls
             if c[0] == "crop_steering/execute_irrigation_shot"]
    assert not fired, "suppressed zone should not get a hardware shot"


def test_custom_shot_event_routes_through_hardware_service(orchestrator):
    _set_zone(orchestrator, 7, vwc=55, flow_lpm=2.0)
    orchestrator._on_custom_shot_event(
        "crop_steering_custom_shot",
        {"target_zone": 7, "intent": "manual", "volume_ml": 200, "tag": "test"},
        None,
    )
    fired = [c for c in orchestrator.service_calls
             if c[0] == "crop_steering/execute_irrigation_shot"]
    assert fired, "expected hardware service call after custom_shot event"
    args = fired[-1][1]
    assert args["zone"] == 7
    # 200 mL / 2 L/min = 0.1 min = 6 s
    assert args["duration_seconds"] == 6
