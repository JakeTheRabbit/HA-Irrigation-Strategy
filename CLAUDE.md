# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## System Overview

Advanced Crop Steering System for Home Assistant (v2.3.1) - A sophisticated rule-based irrigation controller with statistical analysis for precision agriculture. Combines a Home Assistant integration with optional AppDaemon modules for autonomous 4-phase irrigation cycles based on VWC/EC sensor data.

## Development Commands

### Linting & Validation
```bash
# Python linting (check code style)
ruff check .

# Python formatting (check only, don't fix)
black --check .

# YAML linting
yamllint -s .

# Full CI validation (run all checks)
python -m pip install ruff==0.5.5 black==24.4.2 yamllint==1.35.1
ruff check . && black --check . && yamllint -s .
```

### Testing
```bash
# View AppDaemon logs (if using AppDaemon add-on)
docker logs addon_a0d7b954_appdaemon -f

# Test integration loading in Home Assistant
# 1. Copy custom_components/crop_steering to HA config directory
# 2. Restart Home Assistant
# 3. Check logs: Settings → System → Logs
```

### Home Assistant Development
```bash
# Reload integration without restart (after code changes)
# Developer Tools → YAML → Reload Custom Components

# Monitor events (Developer Tools → Events → Listen)
# Event types to monitor:
# - crop_steering_phase_transition
# - crop_steering_irrigation_shot
# - crop_steering_transition_check
# - crop_steering_manual_override
```

## Architecture

### Two-Layer System Design
1. **Home Assistant Integration** (`custom_components/crop_steering/`)
   - Provides 100+ entities (sensors, numbers, switches, selects)
   - Config flow UI for setup (no YAML editing required)
   - Services for phase control and irrigation execution
   - Events for automation/hardware control

2. **AppDaemon Automation** (`appdaemon/apps/crop_steering/`) - Optional
   - Autonomous phase transitions (P0→P1→P2→P3)
   - Statistical sensor processing and validation
   - Hardware sequencing (pump → main line → zone valve)
   - Real-time decision making

### Critical Files
- `custom_components/crop_steering/config_flow.py` - Integration setup wizard
- `custom_components/crop_steering/sensor.py` - Core calculations (shot durations, EC ratio, thresholds)
- `custom_components/crop_steering/services.py` - Service handlers and event dispatching
- `appdaemon/apps/crop_steering/master_crop_steering_app.py` - Main automation coordinator
- `appdaemon/apps/apps.yaml` - AppDaemon app configuration

## Implementation Details

### Phase Logic (P0-P3 Cycle)
```
P0 (Morning Dryback): Wait for X% VWC drop from peak → transition to P1
P1 (Ramp-Up): Progressive shots (2-10% volume) until target VWC → transition to P2
P2 (Maintenance): Threshold-based irrigation (VWC < 60% or EC ratio triggers)
P3 (Pre-Lights-Off): Emergency-only irrigation, prepare for night
```

### Hardware Control Sequence
```python
# Safety checks → Pump prime (2s) → Main line (1s) → Zone valve → Irrigate → Shutdown
```

### Sensor Processing
- **VWC/EC Averaging**: Front/back sensor pairs per zone
- **Outlier Detection**: IQR method (Q3 + 1.5*IQR) - currently bypassed
- **Dryback Detection**: scipy.signal.find_peaks with multi-scale analysis
- **EC Ratio**: Current EC ÷ Target EC drives threshold adjustments

## Key Entity Patterns

Entities follow predictable naming:
- Global: `crop_steering_<parameter>` (e.g., `crop_steering_p2_shot_size`)
- Per-zone: `crop_steering_zone_X_<parameter>` (e.g., `crop_steering_zone_1_enabled`)
- Sensors: `sensor.crop_steering_<metric>` 
- Services: `crop_steering.<action>` (transition_phase, execute_irrigation_shot, etc.)

## Important Notes

### System Status
- Modern integration-based architecture (v2.3.1+)
- NO packages/ or blueprints/ directories (legacy removed)
- Configuration via Home Assistant UI only (no manual YAML editing)
- AppDaemon provides automation, not required for basic operation

### Dependencies
- **Integration**: Zero external Python dependencies
- **AppDaemon modules**: scipy, numpy (installed with AppDaemon)
- **Home Assistant**: 2024.3.0+ required

### Testing Approach
- Integration creates test helper entities automatically
- Input_boolean entities simulate hardware (pumps, valves)
- Input_number entities simulate sensors (VWC, EC, temperature)
- No real hardware required for development/testing