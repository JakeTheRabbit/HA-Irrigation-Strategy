"""Unit tests for ClimateSense hardware calibration."""
from __future__ import annotations

from pathlib import Path

import pytest

from . import _appdaemon_stub  # noqa: F401

from crop_steering.intelligence.climate.hardware import (  # noqa: E402
    HVACCalibration,
    load_hardware_calibration,
)


def test_hvac_calibration_applies_cool_offset():
    """Setting target=27, current=29 (room hot) commands 25 with cool_offset=-2."""
    cal = HVACCalibration(
        entity="climate.gw_ac_1",
        cool_offset_c=-2.0,
        heat_offset_c=0.0,
        deadband_c=0.5,
    )
    assert cal.commanded_setpoint(target_c=27.0, current_c=29.0) == pytest.approx(25.0)


def test_hvac_calibration_applies_heat_offset():
    """Room cold — heat offset takes precedence."""
    cal = HVACCalibration(
        entity="climate.gw_ac_1",
        cool_offset_c=-2.0,
        heat_offset_c=+1.0,
        deadband_c=0.5,
    )
    # current 18, target 22 → heating needed → command 22 + 1 = 23
    assert cal.commanded_setpoint(target_c=22.0, current_c=18.0) == pytest.approx(23.0)


def test_hvac_calibration_returns_target_in_deadband():
    """Within deadband — no command change."""
    cal = HVACCalibration(entity="x", cool_offset_c=-2.0, deadband_c=0.5)
    # diff = 0.4 < deadband 0.5 → no offset applied
    assert cal.commanded_setpoint(target_c=24.0, current_c=24.4) == pytest.approx(24.0)


def test_hvac_calibration_clips_to_min_max():
    cal = HVACCalibration(
        entity="x",
        cool_offset_c=-10.0,
        heat_offset_c=+10.0,
        min_setpoint_c=18.0,
        max_setpoint_c=28.0,
    )
    # Big cool offset would go below 18 → clip
    assert cal.commanded_setpoint(target_c=22.0, current_c=30.0) == pytest.approx(18.0)
    # Big heat offset would exceed 28 → clip
    assert cal.commanded_setpoint(target_c=22.0, current_c=10.0) == pytest.approx(28.0)


def test_load_real_f1_hardware_file():
    """Smoke test the actual hardware_f1.yaml shipped with the repo."""
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "appdaemon" / "apps" / "crop_steering" / "intelligence" / "climate" / "hardware_f1.yaml"
    cal = load_hardware_calibration(path)
    assert cal.room == "F1"
    # The HVAC primary is wired
    assert cal.hvac_primary is not None
    assert cal.hvac_primary.entity == "climate.gw_ac_1"
    assert cal.hvac_primary.cool_offset_c == pytest.approx(-2.0)
    # 4 dehumidifier relays
    assert len(cal.dehumidifier.relays) == 4
    assert "gw_dehumidifier_relay_1" in cal.dehumidifier.relays[0]
    # CO2 hard cap matches the existing 40_environment.yaml safety
    assert cal.co2.hard_max_ppm == pytest.approx(1800.0)
    assert cal.co2.off_at_lights_off is True
    # Sensor map points at gw_room_1 entities
    assert cal.sensors.temp_primary == "sensor.gw_room_1_temp"
    assert cal.sensors.lights_on == "binary_sensor.gw_lights_on"


def test_calibration_loader_filters_unknown_keys(tmp_path):
    """Forward-compat: a YAML with extra keys we don't know about must
    still load — we ignore the unknowns rather than blow up."""
    f = tmp_path / "hw.yaml"
    f.write_text("""
room: TestRoom
hvac:
  primary:
    entity: climate.test
    cool_offset_c: -1.5
    future_param_we_dont_have: 42
""")
    cal = load_hardware_calibration(f)
    assert cal.room == "TestRoom"
    assert cal.hvac_primary.cool_offset_c == pytest.approx(-1.5)
