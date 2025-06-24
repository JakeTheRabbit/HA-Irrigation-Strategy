# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## System Overview

This is an **Advanced Automated Crop Steering System** for Home Assistant that uses rule-based logic, statistical analysis, and sensor-driven automation to optimize precision irrigation. The system implements a sophisticated 4-phase irrigation cycle (P0-P3) with real-time decision making based on VWC and EC sensor data.

## Current Architecture (v2.0)

### Core Components
- **Home Assistant Integration**: `custom_components/crop_steering/` - Main HA integration with UI configuration
- **AppDaemon Automation Modules**: `appdaemon/apps/crop_steering/` - Rule-based irrigation logic and sensor processing
- **Configuration File**: `crop_steering.env` - Hardware and sensor configuration
- **Dashboard System**: `dashboards/` - AppDaemon YAML dashboards for monitoring and control

### System Architecture
1. **Integration Layer**: Home Assistant custom integration with config flow
2. **Automation Layer**: AppDaemon modules with statistical analysis, sensor validation, and dryback detection
3. **Configuration Layer**: File-based hardware configuration (crop_steering.env)
4. **Dashboard Layer**: Real-time monitoring with AppDaemon YAML dashboards

## Key Files Structure

```
custom_components/crop_steering/     # Home Assistant Integration
├── __init__.py                     # Integration setup
├── config_flow.py                  # Setup wizard
├── sensor.py                       # Integration sensors
├── number.py                       # Configuration parameters
├── switch.py                       # Control switches
├── select.py                       # Selection entities
└── services.py                     # Integration services

appdaemon/apps/crop_steering/       # Automation Modules
├── master_crop_steering_app.py     # Main irrigation coordinator
├── ml_irrigation_predictor.py      # Statistical trend analysis
├── intelligent_sensor_fusion.py    # IQR-based sensor validation
├── advanced_dryback_detection.py   # Peak detection algorithms
├── intelligent_crop_profiles.py    # Parameter management
└── advanced_crop_steering_dashboard.py # (Deprecated - replaced by YAML dashboards)
```

## Development Workflow

### Configuration Management
- **UI-first approach** - all configuration through Home Assistant integration setup
- **File-based hardware config** - sensor and hardware entities defined in crop_steering.env
- **No manual YAML editing** - users configure through integration config flow

### Making Changes
1. **Integration entities**: Modify files in `custom_components/crop_steering/`
2. **AI logic**: Edit AppDaemon modules in `appdaemon/apps/crop_steering/`
3. **Hardware config**: Update `crop_steering.env` for sensor/hardware entities
4. **Documentation**: Update guides in `docs/` directory

### Safety & Validation
- Statistical sensor validation with IQR-based outlier detection
- Multi-layer safety systems with emergency irrigation response
- Thread-safe AppDaemon operation with proper synchronization
- Comprehensive error handling and graceful degradation

## Irrigation System Logic

### Four-Phase Irrigation Cycle
- **P0 (Morning Dryback)**: Controlled drying phase after lights-on, no irrigation until dryback target reached
- **P1 (Ramp-Up)**: Progressive irrigation with increasing shot sizes until VWC target achieved
- **P2 (Maintenance)**: EC-ratio and VWC threshold-based irrigation decisions throughout photoperiod
- **P3 (Pre-Lights-Off)**: Final dryback phase with emergency-only irrigation

### Technical Features
- **Statistical Analysis**: Trend analysis using scipy.stats for irrigation prediction
- **Sensor Validation**: IQR-based outlier detection (currently bypassed in implementation)
- **Dryback Detection**: Multi-scale peak detection using scipy.signal.find_peaks
- **Rule-Based Logic**: Threshold-based decisions with configurable parameters
- **Real-time Monitoring**: AppDaemon YAML dashboards with professional styling

## Configuration Requirements

Users configure through Home Assistant integration:
1. **Add Integration**: Search "Crop Steering" in Devices & Services
2. **Configure Hardware**: Enter sensor and irrigation hardware entity names
3. **Select Crop Profile**: Choose plant type and growth stage
4. **Setup AppDaemon**: Install AI modules for advanced features

## System Architecture

### Integration Flow
- Home Assistant integration provides entities and configuration
- AppDaemon reads integration entities and controls hardware
- Automation modules process sensor data using rule-based logic
- Dashboard displays real-time monitoring and system status

### Module Coordination
- `master_crop_steering_app.py` coordinates all automation modules
- Individual modules handle specific functions (trend analysis, sensor validation, profiles)
- Thread-safe operation ensures reliable concurrent processing
- AppDaemon YAML dashboards provide professional monitoring interface

## Testing & Validation

This system requires physical hardware (sensors, pumps, valves) for full testing. When making changes:
- Test integration setup through Home Assistant UI
- Verify AppDaemon modules in AppDaemon logs
- Monitor irrigation decision logic and phase transitions
- Validate sensor processing and emergency irrigation responses

## Documentation

Complete documentation in `docs/`:
- `installation_guide.md` - Step-by-step setup for beginners
- `operation_guide.md` - System operation and monitoring
- `dashboard_guide.md` - Dashboard usage and navigation
- `troubleshooting.md` - Problem resolution and maintenance

# important-instruction-reminders
Do what has been asked; nothing more, nothing less.
NEVER create files unless they're absolutely necessary for achieving your goal.
ALWAYS prefer editing an existing file to creating a new one.
NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.

# IMPORTANT: Current System Status
This system has been completely overhauled from the original package-based approach to a modern automated integration:
- NO packages/ directory exists anymore
- NO blueprints/ directory exists anymore  
- NO old dashboard YAML cards exist
- The system now uses: Integration + AppDaemon automation modules + crop_steering.env configuration
- Dashboard uses AppDaemon YAML files for professional monitoring interface
- All configuration is done through Home Assistant integration UI, not manual YAML editing

## Actual System Logic Flow

### Sensor Processing Pipeline
1. **VWC Sensor Updates** → Direct sensor values (sensor fusion currently bypassed)
2. **Dryback Detection** → Peak detection using scipy.signal.find_peaks
3. **Emergency Check** → Critical VWC threshold triggers immediate irrigation
4. **Phase Evaluation** → Rule-based logic determines irrigation needs per zone

### Four-Phase Decision Logic
- **P0**: No irrigation, wait for dryback target (X% drop from peak VWC)
- **P1**: Progressive shots (3-10 maximum) with increasing volume until VWC target
- **P2**: Threshold-based irrigation (VWC < 60% OR EC ratio conditions)
- **P3**: Emergency-only irrigation, controlled final dryback

### Hardware Control Sequence
1. Safety checks (overrides, system enabled, tank not filling)
2. Pump priming (2 seconds)
3. Main line pressure (1 second)
4. Zone valve activation
5. Irrigation duration
6. Controlled shutdown sequence

### Statistical Methods Used
- **IQR Outlier Detection**: Q3 + 1.5 * IQR for sensor validation
- **Trend Analysis**: scipy.stats linear regression for prediction
- **Peak Detection**: Multi-scale algorithms with adaptive thresholds
- **Confidence Scoring**: Statistical confidence in dryback detection

The system is a **sophisticated rule-based irrigation controller** with statistical analysis, not a true AI/ML system.