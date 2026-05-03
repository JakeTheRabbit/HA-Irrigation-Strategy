"""Unit tests for the layered control package — per-actuator + coordinator + watchdog."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from . import _appdaemon_stub  # noqa: F401

from crop_steering.intelligence.climate.control import (  # noqa: E402
    co2 as co2_mod,
    coordinator,
    dehumidifier as dehu_mod,
    exhaust as exhaust_mod,
    humidifier as humid_mod,
    hvac as hvac_mod,
    watchdog as watchdog_mod,
)
from crop_steering.intelligence.climate.control.actions import Action, ActionKind  # noqa: E402
from crop_steering.intelligence.climate.hardware import (  # noqa: E402
    CO2Calibration,
    DehumidifierCalibration,
    ExhaustCalibration,
    HumidifierCalibration,
    HVACCalibration,
    HardwareCalibration,
    SafetyConfig,
    SensorMap,
)


# ════════════════════════════════════════════════════════════════════
# HVAC
# ════════════════════════════════════════════════════════════════════

def _hvac_cal(**overrides):
    base = dict(
        entity="climate.test", cool_offset_c=-2.0, heat_offset_c=0.0,
        deadband_c=0.5, settle_minutes=8, mode_change_cooldown_min=30,
        refresh_interval_min=30,
    )
    base.update(overrides)
    return HVACCalibration(**base)


def test_hvac_proposes_setpoint_with_calibration_offset():
    cal = _hvac_cal()
    state = hvac_mod.HVACState()
    actions = hvac_mod.propose_hvac(target_c=27.0, current_c=29.0, cal=cal, state=state)
    assert any(a.kind == ActionKind.HVAC_SETPOINT and a.value == 25.0 for a in actions)


def test_hvac_skips_in_deadband():
    cal = _hvac_cal()
    state = hvac_mod.HVACState()
    actions = hvac_mod.propose_hvac(target_c=27.0, current_c=27.2, cal=cal, state=state)
    # Within ±0.5 deadband, no action
    assert all(a.kind != ActionKind.HVAC_SETPOINT for a in actions)


def test_hvac_settle_window_blocks_repeat_command():
    cal = _hvac_cal()
    state = hvac_mod.HVACState(
        last_command_at=datetime.utcnow() - timedelta(minutes=2),
        last_setpoint_c=25.0,
    )
    actions = hvac_mod.propose_hvac(target_c=27.0, current_c=29.0, cal=cal, state=state)
    assert all(a.kind != ActionKind.HVAC_SETPOINT for a in actions)


def test_hvac_proposes_mode_change_with_cooldown_respected():
    cal = _hvac_cal(mode_change_cooldown_min=30)
    # Was cooling 10 min ago — too soon to flip to heat
    state = hvac_mod.HVACState(
        last_mode="cool",
        last_mode_change_at=datetime.utcnow() - timedelta(minutes=10),
    )
    # Now we want heat (current 18, target 22)
    actions = hvac_mod.propose_hvac(target_c=22.0, current_c=18.0, cal=cal, state=state)
    assert all(a.kind != ActionKind.HVAC_MODE for a in actions)
    # Now well past cooldown — should propose mode flip
    state.last_mode_change_at = datetime.utcnow() - timedelta(minutes=45)
    actions = hvac_mod.propose_hvac(target_c=22.0, current_c=18.0, cal=cal, state=state)
    assert any(a.kind == ActionKind.HVAC_MODE and a.value == "heat" for a in actions)


def test_hvac_ir_refresh_re_issues_setpoint():
    cal = _hvac_cal(refresh_interval_min=30, settle_minutes=8)
    state = hvac_mod.HVACState(
        last_command_at=datetime.utcnow() - timedelta(minutes=35),  # past refresh
        last_setpoint_c=25.0,
        last_mode="cool",
    )
    # Same conditions as last command — without refresh would be NO action
    actions = hvac_mod.propose_hvac(target_c=27.0, current_c=29.0, cal=cal, state=state)
    setpoint_actions = [a for a in actions if a.kind == ActionKind.HVAC_SETPOINT]
    assert setpoint_actions, "expected IR-insurance refresh"
    assert "IR refresh" in setpoint_actions[0].reason


# ════════════════════════════════════════════════════════════════════
# DEHUMIDIFIER (staging + lead-lag)
# ════════════════════════════════════════════════════════════════════

def _dehu_cal():
    return DehumidifierCalibration(
        units=[
            {"name": "dehu_a", "relays": ["switch.dehu_a_run", "switch.dehu_a_fan"]},
            {"name": "dehu_b", "relays": ["switch.dehu_b_run", "switch.dehu_b_fan"]},
        ],
        stage_persistence_min=5,
        rotation_period_days=7,
    )


def test_dehu_no_action_in_band():
    cal = _dehu_cal()
    state = dehu_mod.DehuState()
    actions = dehu_mod.propose_dehu(
        current_rh=60.0, target_rh=60.0, cal=cal, state=state,
    )
    assert actions == []


def test_dehu_lead_fires_after_demand_persistence():
    cal = _dehu_cal()
    state = dehu_mod.DehuState()
    now = datetime(2026, 5, 1, 12, 0, 0)
    # First tick: demand starts
    actions = dehu_mod.propose_dehu(
        current_rh=70.0, target_rh=60.0, cal=cal, state=state, now=now,
        on_threshold_pct=5.0, demand_persistence_min=3.0,
    )
    assert actions == []  # demand timer just started
    # 4 minutes later: demand persists, lead should fire
    later = now + timedelta(minutes=4)
    actions = dehu_mod.propose_dehu(
        current_rh=70.0, target_rh=60.0, cal=cal, state=state, now=later,
    )
    assert actions, "expected lead dehu staging"
    assert all(a.actuator_class == "dehu" for a in actions)
    assert all(a.kind == ActionKind.SWITCH_ON for a in actions)
    # All actions should target the LEAD unit (dehu_a by default)
    assert all(a.extras["unit"] == "dehu_a" for a in actions)


def test_dehu_lag_fires_only_after_stage_persistence():
    cal = _dehu_cal()
    state = dehu_mod.DehuState()
    now = datetime(2026, 5, 1, 12, 0, 0)
    # Demand starts
    dehu_mod.propose_dehu(current_rh=70, target_rh=60, cal=cal, state=state, now=now)
    # 4 min: lead fires
    actions = dehu_mod.propose_dehu(
        current_rh=70, target_rh=60, cal=cal, state=state, now=now + timedelta(minutes=4),
    )
    for a in actions:
        dehu_mod.apply_action_to_state(state, a, now + timedelta(minutes=4))
    # 6 min after demand started — still under (3 + 5) min — lag should NOT fire yet
    actions = dehu_mod.propose_dehu(
        current_rh=70, target_rh=60, cal=cal, state=state, now=now + timedelta(minutes=6),
    )
    lag_actions = [a for a in actions if a.extras.get("unit") == "dehu_b"]
    assert lag_actions == []
    # 9 min — past (3 + 5) — lag fires
    actions = dehu_mod.propose_dehu(
        current_rh=70, target_rh=60, cal=cal, state=state, now=now + timedelta(minutes=9),
    )
    lag_actions = [a for a in actions if a.extras.get("unit") == "dehu_b"]
    assert lag_actions, "expected lag dehu to stage in"
    assert all(a.kind == ActionKind.SWITCH_ON for a in lag_actions)


def test_dehu_lead_lag_rotation_after_period():
    cal = _dehu_cal()
    state = dehu_mod.DehuState()
    now = datetime(2026, 5, 1, 12, 0, 0)
    dehu_mod.propose_dehu(current_rh=60, target_rh=60, cal=cal, state=state, now=now)
    assert state.lead_unit_name == "dehu_a"
    # 8 days later
    later = now + timedelta(days=8)
    dehu_mod.propose_dehu(current_rh=60, target_rh=60, cal=cal, state=state, now=later)
    assert state.lead_unit_name == "dehu_b"


def test_dehu_releases_lag_first_then_lead():
    cal = _dehu_cal()
    state = dehu_mod.DehuState()
    # Both running
    state.units["dehu_a"] = dehu_mod.DehuUnitState(name="dehu_a", is_on=True,
                                                    last_on_at=datetime.utcnow())
    state.units["dehu_b"] = dehu_mod.DehuUnitState(name="dehu_b", is_on=True,
                                                    last_on_at=datetime.utcnow())
    state.lead_unit_name = "dehu_a"

    actions = dehu_mod.propose_dehu(
        current_rh=55.0, target_rh=60.0, cal=cal, state=state,
        on_threshold_pct=5.0, off_threshold_pct=2.0,
    )
    # First wave: turn off LAG (dehu_b)
    assert actions, "expected stage-off"
    assert all(a.extras["unit"] == "dehu_b" for a in actions)
    assert all(a.kind == ActionKind.SWITCH_OFF for a in actions)


# ════════════════════════════════════════════════════════════════════
# CO2
# ════════════════════════════════════════════════════════════════════

def test_co2_hard_cap_overrides_everything():
    cal = CO2Calibration(solenoid="switch.co2", hard_max_ppm=1800)
    state = co2_mod.CO2State(phase="on",
                              phase_until=datetime.utcnow() + timedelta(seconds=30))
    actions = co2_mod.propose_co2(
        current_ppm=1850, target_ppm=1300, lights_on=True, cal=cal, state=state,
    )
    assert actions
    assert actions[0].kind == ActionKind.SWITCH_OFF
    assert actions[0].severity == "emergency"


def test_co2_does_not_inject_before_lights_on_lead_time():
    cal = CO2Calibration(solenoid="switch.co2", lights_on_lead_min=30)
    state = co2_mod.CO2State()
    now = datetime.utcnow()
    state.last_lights_on_at = now - timedelta(minutes=10)  # only 10 min in
    actions = co2_mod.propose_co2(
        current_ppm=800, target_ppm=1300, lights_on=True,
        cal=cal, state=state, now=now,
    )
    assert actions == []


def test_co2_closes_solenoid_at_lights_off():
    cal = CO2Calibration(solenoid="switch.co2", off_at_lights_off=True)
    state = co2_mod.CO2State(phase="on",
                              phase_until=datetime.utcnow() + timedelta(seconds=30))
    actions = co2_mod.propose_co2(
        current_ppm=1100, target_ppm=1300, lights_on=False, cal=cal, state=state,
    )
    assert any(a.kind == ActionKind.SWITCH_OFF and a.severity == "safety"
               for a in actions)


# ════════════════════════════════════════════════════════════════════
# EXHAUST (emergency)
# ════════════════════════════════════════════════════════════════════

def test_exhaust_fires_on_emergency_temp():
    cal = ExhaustCalibration(entity="switch.exhaust", emergency_temp_c=32.0)
    state = exhaust_mod.ExhaustState()
    actions = exhaust_mod.propose_exhaust(
        current_temp_c=33.0, current_co2_ppm=1000, lights_on=True,
        cal=cal, state=state,
    )
    assert any(a.kind == ActionKind.SWITCH_ON and a.severity == "emergency"
               for a in actions)


def test_exhaust_watchdog_force_off_after_max_runtime():
    cal = ExhaustCalibration(entity="switch.exhaust", max_runtime_min=30)
    state = exhaust_mod.ExhaustState(
        is_on=True,
        last_on_at=datetime.utcnow() - timedelta(minutes=45),
    )
    actions = exhaust_mod.propose_exhaust(
        current_temp_c=24.0, current_co2_ppm=1000, lights_on=True,
        cal=cal, state=state,
    )
    assert any(a.kind == ActionKind.SWITCH_OFF and a.severity == "safety"
               for a in actions)


# ════════════════════════════════════════════════════════════════════
# COORDINATOR
# ════════════════════════════════════════════════════════════════════

def test_coordinator_safety_actions_always_emit():
    safety = [Action(kind=ActionKind.SWITCH_OFF, entity="switch.co2",
                     reason="emergency", severity="emergency",
                     actuator_class="co2")]
    out = coordinator.resolve_proposals(
        proposals={}, safety_actions=safety,
        maintenance_mode=True,  # even in maintenance mode
        active_anomalies=set(),
    )
    assert any(a.severity == "emergency" for a in out)


def test_coordinator_drops_humidifier_when_dehu_proposes_on():
    dehu = [Action(kind=ActionKind.SWITCH_ON, entity="switch.dehu_a_run",
                   reason="r", actuator_class="dehu",
                   extras={"unit": "dehu_a", "role": "lead"})]
    humid = [Action(kind=ActionKind.SWITCH_ON, entity="switch.humid",
                    reason="r", actuator_class="humid")]
    out = coordinator.resolve_proposals(
        proposals={"dehu": dehu, "humid": humid},
        safety_actions=[], maintenance_mode=False,
    )
    # Only the dehu ON should be in the output
    on_actions = [a for a in out if a.kind == ActionKind.SWITCH_ON]
    assert any(a.actuator_class == "dehu" for a in on_actions)
    assert not any(a.actuator_class == "humid" for a in on_actions)


def test_coordinator_defers_lag_dehu_when_ac_already_cooling():
    """When AC is already cooling and temp is above target, the AC is
    pulling water out of the air via condensation. The coordinator
    should hold off on staging the LAG dehu so we don't over-dry."""
    dehu = [
        Action(kind=ActionKind.SWITCH_ON, entity="switch.dehu_b_run",
               reason="r", actuator_class="dehu",
               extras={"unit": "dehu_b", "role": "lag"}),
    ]
    out = coordinator.resolve_proposals(
        proposals={"dehu": dehu}, safety_actions=[],
        maintenance_mode=False,
        ac_is_cooling=True, temp_above_target=True,
    )
    # Lag dehu should be deferred — no SWITCH_ON for dehu_b
    on_actions = [a for a in out if a.kind == ActionKind.SWITCH_ON]
    assert not any(a.extras.get("unit") == "dehu_b" for a in on_actions)


def test_coordinator_emergency_suppresses_normal_control():
    normal = [Action(kind=ActionKind.SWITCH_ON, entity="switch.dehu",
                     reason="r", actuator_class="dehu",
                     extras={"unit": "dehu_a", "role": "lead"})]
    out = coordinator.resolve_proposals(
        proposals={"dehu": normal}, safety_actions=[],
        maintenance_mode=False,
        active_anomalies={"climate_emergency_temp"},
    )
    # Normal proposals filtered out under emergency
    assert not any(a.actuator_class == "dehu" and a.severity == "normal" for a in out)


# ════════════════════════════════════════════════════════════════════
# WATCHDOG
# ════════════════════════════════════════════════════════════════════

def test_watchdog_flags_stale_sensor():
    hw = HardwareCalibration(
        room="T",
        sensors=SensorMap(temp_primary="sensor.temp", rh_primary="sensor.rh", co2="sensor.co2"),
        safety=SafetyConfig(sensor_stale_seconds=90),
    )
    now = datetime.utcnow()
    sensor_state = {
        "sensor.temp": {"value": 24.0, "last_update": now - timedelta(seconds=120)},
        "sensor.rh": {"value": 60.0, "last_update": now},
        "sensor.co2": {"value": 1000.0, "last_update": now},
    }
    _, codes = watchdog_mod.watchdog_check(
        hw=hw, sensor_state=sensor_state, actuator_runtime={}, now=now,
    )
    assert any("climate_sensor_stale" in c for c in codes)


def test_watchdog_force_closes_co2_above_emergency():
    hw = HardwareCalibration(
        room="T",
        co2=CO2Calibration(solenoid="switch.co2"),
        sensors=SensorMap(co2="sensor.co2"),
        safety=SafetyConfig(emergency_co2_ppm=1800),
    )
    now = datetime.utcnow()
    sensor_state = {"sensor.co2": {"value": 1900, "last_update": now}}
    actions, codes = watchdog_mod.watchdog_check(
        hw=hw, sensor_state=sensor_state, actuator_runtime={}, now=now,
    )
    assert any("climate_emergency_co2" in c for c in codes)
    assert any(a.entity == "switch.co2" and a.kind == ActionKind.SWITCH_OFF
               and a.severity == "emergency" for a in actions)


def test_watchdog_kills_runaway_actuator():
    hw = HardwareCalibration(
        room="T",
        safety=SafetyConfig(actuator_max_runtime_min={"dehumidifier": 60}),
        sensors=SensorMap(),
    )
    now = datetime.utcnow()
    runtime = {
        "switch.dehu_a": {
            "is_on": True,
            "last_on_at": now - timedelta(minutes=90),
            "actuator_class": "dehumidifier",
        },
    }
    actions, codes = watchdog_mod.watchdog_check(
        hw=hw, sensor_state={}, actuator_runtime=runtime, now=now,
    )
    assert any("climate_actuator_runaway" in c for c in codes)
    assert any(a.entity == "switch.dehu_a" and a.kind == ActionKind.SWITCH_OFF
               for a in actions)
