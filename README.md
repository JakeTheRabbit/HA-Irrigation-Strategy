# Crop Steering System for Home Assistant (v2.3.0)

![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.3.0+-41BDF5?logo=home-assistant&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![Zones](https://img.shields.io/badge/Zones-1%E2%80%936-blue)
![Dependencies](https://img.shields.io/badge/Dependencies-None-brightgreen)
![Status](https://img.shields.io/badge/Status-Production%20Ready-brightgreen)
![License](https://img.shields.io/badge/License-MIT-green)

Turn Home Assistant into a professional crop‑steering controller. This project combines a lightweight HA integration (entities, services) with optional AppDaemon modules (advanced analytics, phase state machine) to automate precision irrigation using VWC/EC sensors.

Highlights in v2.3.0:
- Zero external Python dependencies for the integration
- Dynamic multi‑zone (1–6) entity generation via GUI setup
- Built‑in calculations (P1/P2/P3 shot durations, EC ratio, adjusted thresholds)
- Services for phase transitions, manual shots, and manual override
- Optional AppDaemon suite: dryback detection, sensor fusion, state machine, ML predictor

—

## Architecture

- Home Assistant custom integration (custom_components/crop_steering)
  - Creates entities (sensors, numbers, selects, switches)
  - Performs core calculations in sensors
  - Exposes services and fires events for orchestration/hardware
- AppDaemon (optional, appdaemon/apps/crop_steering)
  - Advanced logic: dryback analysis, state machine, predictions, analytics
  - Listens to integration events and HA entity changes

This separation keeps the HA integration simple and robust while enabling powerful automation when AppDaemon is installed.

## Entities provided by the integration

Entity IDs follow the pattern crop_steering_<key> with per‑zone suffixes where applicable. The number of zones is chosen during config (1–6).

- Switches
  - Global: system_enabled (default on), auto_irrigation_enabled (default on), ec_stacking_enabled, analytics_enabled
  - Per‑zone: zone_X_enabled (default on), zone_X_manual_override

- Selects
  - crop_type (Cannabis_Athena, Cannabis_Hybrid, Cannabis_Indica, Cannabis_Sativa, Tomato, Lettuce, Basil, Custom)
  - growth_stage (Vegetative, Generative, Transition)
  - steering_mode (Vegetative, Generative)
  - irrigation_phase (P0, P1, P2, P3, Manual)
  - Per‑zone: zone_X_group (Ungrouped, Group A–D), zone_X_priority (Critical/High/Normal/Low), zone_X_crop_profile (Follow Main, …)

- Numbers (globals)
  - Substrate/hydraulics: substrate_volume (L), dripper_flow_rate (L/hr), drippers_per_plant
  - Moisture targets: field_capacity (%), veg_dryback_target (%), gen_dryback_target (%), p1_target_vwc (%), p2_vwc_threshold (%)
  - P0: p0_min_wait_time (min), p0_max_wait_time (min), p0_dryback_drop_percent (%)
  - P1: p1_initial_shot_size (%), p1_shot_increment (%), p1_max_shot_size (%), p1_time_between_shots (min), p1_max_shots, p1_min_shots
  - P2: p2_shot_size (%), p2_ec_high_threshold, p2_ec_low_threshold
  - P3: p3_veg_last_irrigation (min), p3_gen_last_irrigation (min), p3_emergency_vwc_threshold (%), p3_emergency_shot_size (%)
  - EC targets (mS/cm): ec_target_flush, ec_target_veg_p0..p3, ec_target_gen_p0..p3
  - Light schedule (system‑wide): lights_on_hour, lights_off_hour (0–23)

- Numbers (per‑zone)
  - zone_X_plant_count, zone_X_max_daily_volume (L), zone_X_shot_size_multiplier (%)

- Sensors (globals)
  - current_phase (reads AppDaemon phase if available, else integration select)
  - irrigation_efficiency (%), water_usage_daily (L), dryback_percentage (%)
  - next_irrigation_time (timestamp, from AppDaemon if present)
  - p1_shot_duration_seconds, p2_shot_duration_seconds, p3_shot_duration_seconds
  - ec_ratio (avg EC ÷ current phase target EC)
  - p2_vwc_threshold_adjusted (%; auto‑adjusts by EC ratio and high/low thresholds)
  - configured_avg_vwc (%), configured_avg_ec (mS/cm) across all configured zone sensors

- Sensors (per‑zone)
  - vwc_zone_X (%), ec_zone_X (mS/cm)
  - zone_X_status (Optimal/Dry/Saturated/Disabled/Sensor Error)
  - zone_X_last_irrigation (timestamp, from AppDaemon if present)
  - zone_X_daily_water_usage (L), zone_X_weekly_water_usage (L), zone_X_irrigation_count_today

Note: Some globals are placeholders until AppDaemon or automations provide backing data.

## Built‑in calculations (in sensors)

- Shot duration (seconds)
  - P1: duration = (substrate_volume × p1_initial_shot_size%) ÷ dripper_flow_rate × 3600
  - P2: duration = (substrate_volume × p2_shot_size%) ÷ dripper_flow_rate × 3600
  - P3: duration = (substrate_volume × p3_emergency_shot_size%) ÷ dripper_flow_rate × 3600
- EC ratio = configured_avg_ec ÷ current phase target EC (selected via steering_mode + irrigation_phase)
- Adjusted P2 threshold
  - base p2_vwc_threshold shifted ±5% when ec_ratio is above p2_ec_high_threshold or below p2_ec_low_threshold
- Zone averages and statuses
  - VWC/EC per zone averaged from front/back sensors (if both configured)
  - Status derived from VWC ranges with basic sanity checks

## Services (domain: crop_steering)

- transition_phase
  - target_phase: P0|P1|P2|P3 (required)
  - reason: string (optional)
  - forced: boolean (optional)
  - Action: sets select.crop_steering_irrigation_phase, fires crop_steering_phase_transition event

- execute_irrigation_shot
  - zone: validated against configured zones (required)
  - duration_seconds: 1–3600 (required)
  - shot_type: P1|P2|P3_emergency (optional; default manual)
  - Action: fires crop_steering_irrigation_shot event for hardware orchestration

- check_transition_conditions
  - No inputs
  - Action: evaluates current phase, avg VWC/EC, EC ratio, and emits crop_steering_transition_check with reasons

- set_manual_override
  - zone: 1–6 (required)
  - timeout_minutes: 1–1440 (optional)
  - enable: boolean (optional; default true)
  - Action: toggles switch.crop_steering_zone_X_manual_override and fires crop_steering_manual_override

### Services summary (quick reference)

| Service | Inputs (required in bold) | Effect |
|---|---|---|
| crop_steering.transition_phase | **target_phase** (P0/P1/P2/P3), reason, forced | Sets phase select, fires phase_transition event |
| crop_steering.execute_irrigation_shot | **zone**, **duration_seconds**, shot_type | Fires irrigation_shot event (for hardware) |
| crop_steering.check_transition_conditions | – | Fires transition_check event with reasons |
| crop_steering.set_manual_override | **zone**, timeout_minutes, enable | Toggles per‑zone manual override, fires event |

## Events fired by the integration

- crop_steering_phase_transition { target_phase, reason, forced, timestamp }
- crop_steering_irrigation_shot { zone, duration_seconds, shot_type, timestamp }
- crop_steering_transition_check { current_phase, avg_vwc, avg_ec, ec_ratio, transition_reasons[], conditions_met, timestamp }
- crop_steering_manual_override { zone, action, timeout_minutes?, timestamp }

### Events summary (quick reference)

| Event | Payload highlights |
|---|---|
| crop_steering_phase_transition | target_phase, reason, forced, timestamp |
| crop_steering_irrigation_shot | zone, duration_seconds, shot_type, timestamp |
| crop_steering_transition_check | current_phase, avg_vwc, avg_ec, ec_ratio, transition_reasons[], conditions_met |
| crop_steering_manual_override | zone, action, timeout_minutes?, timestamp |

## Optional AppDaemon suite (advanced automation)

Located in appdaemon/apps/crop_steering:
- advanced_dryback_detection.py — Multi‑scale peak/valley detection, dryback % and prediction
- intelligent_sensor_fusion.py — IQR/outlier filtering, smoothing, confidence scoring
- ml_irrigation_predictor.py — Simplified predictor with rolling training window
- intelligent_crop_profiles.py — Profiles by crop/stage with adaptive parameters
- phase_state_machine.py — Zone state machine (P0/P1/P2/P3) with transition rules
- master_crop_steering_app.py — Orchestrates modules, listens to HA entities/events

Install AppDaemon if you want autonomous phase control, analytics, and hardware sequencing. The integration works without AppDaemon but will not perform advanced automation on its own.

## Installation

- Integration (HACS recommended)
  1) HACS → Integrations → Custom Repositories → https://github.com/JakeTheRabbit/HA-Irrigation-Strategy (Integration)
  2) Install "Crop Steering System", restart HA
  3) Settings → Devices & Services → Add Integration → Crop Steering System

- AppDaemon (optional, for advanced features)
  1) Install AppDaemon 4 add‑on
  2) Use v15+ paths (supervised HA): /addon_configs/a0d7b954_appdaemon/
  3) Copy appdaemon/apps/crop_steering to your AppDaemon apps dir, include apps.yaml
  4) Restart AppDaemon

See docs/installation_guide.md for step‑by‑step details.

## Testing & Hardware Simulation

The integration automatically creates test helper entities for system simulation without requiring real hardware:

**Hardware Simulation (Input Boolean entities)**
- Pumps & Valves: water_pump_1/2, nutrient_pump_a/b/c, ph_up/down_pump, main_water_valve, zone_1-6_valve, recirculation_valve, drain_valve
- Status Indicators: system_ready, emergency_stop, various alarms and calibration status
- Operational States: auto_mode, manual_override, night_mode, maintenance_mode, flush_mode, dose_mode
- Zone Controls: zone_1-6_enabled 
- Safety Systems: flow/pressure sensor status, leak detection, pump overload protection
- Communication: modbus_connected, wifi_connected, sensor_hub_online, controller_responsive

**Sensor Simulation (Input Number entities)**
- Tank Sensors: water_level (%), pH (0-14), EC (mS/cm), temperature (°C), flow_rate (L/min), pressure (bar)
- Zone Sensors: Per-zone VWC (%), EC (mS/cm), temperature (°C) for zones 1-6
- Environmental: ambient_temperature/humidity, light_intensity (lux)
- System Performance: pump_frequency (Hz), valve_position (%), system_pressure (bar)

All test helpers are automatically created during integration setup and appear under the "Crop Steering Test Helpers" device. These entities maintain their state across Home Assistant restarts and provide realistic ranges with appropriate units and icons.

**Using Test Helpers**
1. Install the integration normally
2. Test helpers appear automatically in your entity list
3. Adjust input_number values to simulate sensor readings
4. Toggle input_boolean entities to simulate hardware states
5. Services and automations respond to these simulated inputs just like real hardware
6. No manual entity cleanup required - helpers are part of the integration

## Configuration

- GUI setup (recommended)
  - Choose number of zones (1–6)
  - Map hardware (pump/main line/zone switches) and sensors for each zone
  - Optionally map environmental sensors (temp/humidity/VPD)

- Import from YAML (optional)
  - The config flow supports importing from Home Assistant config.yaml (top‑level) with a zones: section
  - Integration validates referenced entity IDs during import

## Operation overview

- Phases (managed by AppDaemon state machine when installed)
  - P0 Morning dryback → P1 Ramp‑up → P2 Maintenance → P3 Pre‑lights‑off → back to P0 on lights‑on
  - Light timing uses lights_on_hour and lights_off_hour numbers (system‑wide)
- Per‑zone logic
  - Integration exposes per‑zone sensors, numbers, switches; AppDaemon decides when to irrigate per zone
- Safety & limits
  - Emergency thresholds and manual overrides available per zone

## Tips

- Provide two VWC/EC sensors per zone for better averaging
- Start with defaults, then tune p2_vwc_threshold and EC targets to match your media/genetics
- Use zone_X_shot_size_multiplier to bias individual zones without changing global targets

## Troubleshooting

- Use the check_transition_conditions service to see current reasoning
- Ensure AppDaemon is installed and apps copied if advanced features are expected
- Validate all entity IDs during setup; missing sensors will result in None/0 readings
- CI validates manifest and structure; no extra python deps are required

## License

MIT License

## Acknowledgments

- Home Assistant Community, AppDaemon developers, and contributors advancing precision irrigation

## Architecture diagram

```mermaid
flowchart LR
  subgraph HA[Home Assistant]
    I[Crop Steering Integration]
    E[Entities<br/>sensors/numbers/selects/switches]
    SVC[Services]
    BUS[(State & Event Bus)]
  end

  I --> E
  I --> SVC
  I <--> BUS

  subgraph AD[AppDaemon (optional)]
    M[MasterCropSteeringApp]
    D[AdvancedDrybackDetector]
    F[IntelligentSensorFusion]
    P[ML Irrigation Predictor]
    SM[Zone State Machine]
  end

  BUS <--> M
  M --> D
  M --> F
  M --> P
  M --> SM
  M --> HW[(Pump/Main/Zone Valves)]
```

## Modules & key classes

- custom_components/crop_steering
  - services.py — registers services and fires events
  - sensor.py — Sensor entities and calculations (avg EC/VWC, EC ratio, shot durations, adjusted thresholds)
  - number.py — All tunable parameters (substrate, P0/P1/P2/P3, EC targets, lights hours, per‑zone limits)
  - select.py — crop_type, growth_stage, steering_mode, irrigation_phase; per‑zone group/priority/profile
  - switch.py — global toggles and per‑zone enable/manual override
  - __init__.py — setup/unload, platform load, service setup

- appdaemon/apps/crop_steering (optional)
  - master_crop_steering_app.py — MasterCropSteeringApp (orchestrates modules, listens to HA)
  - advanced_dryback_detection.py — AdvancedDrybackDetector
  - intelligent_sensor_fusion.py — IntelligentSensorFusion
  - ml_irrigation_predictor.py — SimplifiedIrrigationPredictor
  - phase_state_machine.py — ZoneStateMachine, IrrigationPhase, PhaseTransition
  - intelligent_crop_profiles.py — IntelligentCropProfiles

## Screenshots

![Dashboard Screenshot](screenshot.jpeg)
