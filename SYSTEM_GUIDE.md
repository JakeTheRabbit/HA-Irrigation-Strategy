# Crop Steering System Guide

Version 2.3.1 | 6-Zone Coco Coir | Athena Nutrients | GroundWork Probes

---

## Table of Contents

1. [What This System Does](#what-this-system-does)
2. [Architecture](#architecture)
3. [The Four Phases](#the-four-phases)
4. [Daily Cycle — What Happens Automatically](#daily-cycle)
5. [Entity Reference](#entity-reference)
6. [Configuration](#configuration)
7. [Dashboard Layout](#dashboard-layout)
8. [Zone Management](#zone-management)
9. [Phase Parameters — What Each One Does](#phase-parameters)
10. [EC Targets and Ratio Logic](#ec-targets)
11. [Per-Zone Targets](#per-zone-targets)
12. [Manual Override](#manual-override)
13. [Emergency Irrigation](#emergency-irrigation)
14. [AI Heartbeat](#ai-heartbeat)
15. [Safety Layers](#safety-layers)
16. [Sensor Fusion](#sensor-fusion)
17. [Crop Profiles](#crop-profiles)
18. [Persistent State](#persistent-state)
19. [Failure Modes and Troubleshooting](#failure-modes)
20. [Known Issues](#known-issues)
21. [Hardware Map](#hardware-map)

---

<a name="what-this-system-does"></a>
## 1. What This System Does

This is an automated irrigation controller for cannabis grown in coco coir. It reads VWC (volumetric water content) and pore-water EC from substrate probes, decides when and how much to water each zone, and actuates solenoid valves through Home Assistant.

The system runs a 4-phase daily irrigation cycle (P0-P3) independently per zone. It uses sensor fusion, dryback detection, EC ratio logic, and an ML predictor to make irrigation decisions. Every decision passes through multiple safety checks before a valve opens.

**Hardware controlled:**
- 1 main line solenoid (`switch.irrigation_mainline`)
- 6 zone valve solenoids (`switch.irrigation_table_1_valve` through `switch.irrigation_table_6_valve`)
- No dedicated pump — constant-pressure switch auto-starts when the main line opens

**Sensors read:**
- 6 VWC probes (one per zone): `sensor.substrate_N_substrate_N_vwc_coco_coir`
- 6 EC probes (one per zone): `sensor.substrate_N_substrate_N_pwec`
- Room temperature, humidity, VPD from GroundWork gateway

---

<a name="architecture"></a>
## 2. Architecture

The system has two halves:

### HA Custom Component (`/config/custom_components/crop_steering/`)

Creates all the entities in Home Assistant — switches, numbers, selects, sensors, and buttons. These are the knobs you turn on the dashboard. The component itself does not make irrigation decisions; it just holds state.

**Files:**
| File | Purpose |
|------|---------|
| `__init__.py` | Registers platforms: sensor, switch, select, number, button |
| `switch.py` | System switches + per-zone enabled/override switches |
| `number.py` | All tunable parameters (phase timing, shot sizes, EC targets, per-zone targets) |
| `select.py` | Crop type, growth stage, steering mode, per-zone group/priority/profile/phase override |
| `sensor.py` | Calculated sensors (shot durations, EC ratio, zone VWC/EC, zone status) |
| `button.py` | Per-zone trigger shot buttons |
| `services.py` | HA services: `transition_phase`, `execute_irrigation_shot`, `set_manual_override`, `check_transition_conditions` |
| `config_flow.py` | Setup wizard — loads from `crop_steering.env` or manual UI config |
| `env_parser.py` | Parses `crop_steering.env` for zone/hardware/parameter configuration |
| `zone_config.py` | Zone configuration helper (also parses `.env`) |
| `const.py` | Constants: domain name, defaults, phase lists, crop types |

### AppDaemon App (`/addon_configs/.../apps/crop_steering/`)

This is the brain. It reads entity states, runs the decision loop, and actuates hardware.

**Files:**
| File | Purpose |
|------|---------|
| `master_crop_steering_app.py` | Main app (~5900 lines). All irrigation logic, phase transitions, safety, analytics |
| `base_async_app.py` | Base class with sync/async entity access wrappers and HA REST API fallback |
| `phase_state_machine.py` | Per-zone state machine: phase transitions, validation, data tracking |
| `intelligent_sensor_fusion.py` | Multi-sensor outlier detection, reliability scoring, Kalman filtering |
| `advanced_dryback_detection.py` | Peak/valley detection, dryback rate calculation, prediction |
| `intelligent_crop_profiles.py` | Strain-specific parameter profiles with adaptive learning |
| `ml_irrigation_predictor.py` | Lightweight ML predictor (no external deps — pure math) |

### Entity Naming

The custom component sets `_attr_object_id = f"crop_steering_{key}"` on every entity. This means all entities created by the component have the `crop_steering_` prefix:

| You might expect | Actual HA entity ID |
|---|---|
| `switch.system_enabled` | `switch.crop_steering_system_enabled` |
| `number.p1_target_vwc` | `number.crop_steering_p1_target_vwc` |
| `select.zone_1_phase_override` | `select.crop_steering_zone_1_phase_override` |
| `button.zone_1_trigger_shot` | `button.crop_steering_zone_1_trigger_shot` |

The AppDaemon app tries both naming conventions (with and without prefix) when reading entity states. It uses a startup cache warm via the HA REST API to populate a `switch_state_cache` since `get_state()` returns `None` for custom component entities in AppDaemon.

Sensors **created by AppDaemon** (via `set_state`) do not have this issue — they use the exact entity ID passed (e.g., `sensor.crop_steering_zone_1_phase`).

Hardware entities from other integrations keep their own naming (e.g., `switch.irrigation_mainline`, `sensor.substrate_1_substrate_1_vwc_coco_coir`).

### Communication Flow

```
crop_steering.env
       |
       v
Custom Component (creates HA entities with crop_steering_ prefix)
       |
       v
Home Assistant (holds entity state, fires events)
       |
       v
AppDaemon master_crop_steering_app (reads entities via listen_state + REST API fallback)
       |
       v
Hardware (valves, pump via HA switch services)
```

The AppDaemon app uses `listen_state` callbacks to populate an in-memory cache for sensor and switch values, because `get_state()` cannot see custom component entities. The REST API (`_check_ha_entity_state`) is a final fallback.

---

<a name="the-four-phases"></a>
## 3. The Four Phases

Each zone runs its own independent phase cycle every day. Phases advance automatically based on sensor readings and time.

### P0 — Morning Dryback

**When:** Lights turn on (08:00 by default).
**What:** No irrigation. The substrate dries back from overnight saturation. The system records the peak VWC at lights-on and tracks how far VWC drops.
**Exits when (any of):**
- Dryback reaches the target percentage (default 50% of peak VWC lost)
- VWC drops by at least `p0_dryback_drop_percent` (default 15%)
- Maximum wait time exceeded (default 120 min)
- Dryback rate is too slow (<0.1%/min after 1 hour)
- Minimum wait time must be met first (default 30 min)

**Emergency exception:** If EC ratio exceeds 2.5x target during P0, a large flush shot (10% substrate volume) fires to prevent salt damage.

### P1 — Ramp-Up

**When:** P0 ends.
**What:** Progressive irrigation shots that increase in size to bring VWC back to target. The system starts with small shots and works up.
**Shot sizing:** `initial_shot_size + (shot_increment * shot_count)`, capped at `max_shot_size`, multiplied by the zone's `shot_size_multiplier`.
**Exits when:**
- VWC reaches `p1_target_vwc` (default 65%) AND minimum shots completed (default 3)
- Maximum shots reached (default 6) — exits even if target not met
**Cooldown:** `p1_time_between_shots` (default 15 min) between each shot.
**EC logic:** Shots are adjusted by EC ratio — if EC is high, shots are larger (dilution); if EC is low, shots are smaller (conservation).

### P2 — Maintenance

**When:** P1 target VWC reached.
**What:** Steady-state irrigation. Fires a fixed-size shot whenever VWC drops below the threshold.
**Trigger:** `zone_vwc < p2_vwc_threshold` (default 60%).
**Shot size:** `p2_shot_size` (default 5% of substrate volume), adjusted by EC ratio:
- EC ratio > `p2_ec_high_threshold` (1.2): shot increased 1.5x (flush excess salts)
- EC ratio < `p2_ec_low_threshold` (0.8): shot decreased 0.7x (conserve nutrients)
**Exits when:** ML/time-based prediction determines there isn't enough time before lights-off for the substrate to dry back overnight.

### P3 — Pre-Lights-Off

**When:** Calculated by dryback rate prediction — the system estimates how long the substrate needs to dry to the overnight target, and starts P3 early enough.
**What:** No irrigation unless emergency. The goal is to enter the dark period with the substrate at the right moisture level for generative steering.
**Emergency only:** Fires a small shot if VWC drops below `p3_emergency_vwc_threshold` (default 40%) or EC ratio exceeds 2.0x target.
**Exits when:** Lights turn on the next morning → P0.

### Phase Cycle Summary

```
Lights ON → P0 (dryback) → P1 (ramp-up) → P2 (maintenance) → P3 (dry-down) → Lights OFF
                                                                                    |
                                                                          Next morning: P0
```

---

<a name="daily-cycle"></a>
## 4. Daily Cycle — What Happens Automatically

Assuming lights 08:00–20:00, Cannabis_Athena profile, vegetative stage:

| Time | What Happens |
|------|-------------|
| 08:00 | Lights on. All zones transition P3→P0. Peak VWC recorded. |
| 08:00–09:30 | P0 dryback. No watering. System watches VWC fall. |
| ~09:30 | Dryback target met or timeout. Zones transition P0→P1. |
| 09:30–11:00 | P1 ramp-up. Progressive shots every 15 min. Shot sizes increase. |
| ~11:00 | VWC reaches 65% target. Zones transition P1→P2. |
| 11:00–17:00 | P2 maintenance. Shots fire when VWC drops below 60%. EC-adjusted. |
| ~17:00 | System predicts dryback timing. Zones transition P2→P3. |
| 17:00–20:00 | P3 pre-lights-off. No irrigation unless emergency VWC (<40%). |
| 20:00 | Lights off. Zones stay in P3 until next morning. |

Actual timing varies per zone based on sensor readings. Zones operate independently.

### Decision Loop

The main decision loop runs every 60 seconds (`phase_check_interval`). Each cycle:

1. Check all zone phase transitions
2. Read current system state (all VWC, EC, environmental sensors)
3. Load crop profile parameters (Cannabis_Athena defaults if none active)
4. Get dryback status from peak detector
5. Get ML irrigation predictions
6. Make irrigation decision per zone based on phase requirements
7. Execute irrigation if needed (one zone at a time, max 1 concurrent)
8. Update tracking sensors

### Irrigation Execution Sequence

When a shot fires:

1. Turn on main line (`switch.irrigation_mainline`), wait 1s
2. Turn on zone valve (`switch.irrigation_table_N_valve`)
3. Wait for shot duration
4. Turn off zone valve, wait 1s
5. Turn off main line, wait 1s
6. Wait 30s for sensor stabilization
7. Read post-irrigation VWC, calculate efficiency

The pump is not directly controlled — it auto-starts via pressure switch when the main line opens.

A `finally` block ensures all hardware is turned off even if an error occurs mid-shot.

---

<a name="entity-reference"></a>
## 5. Entity Reference

### Switches (from custom component)

All have the `crop_steering_` prefix in their actual entity ID.

| Entity ID | Default | Purpose |
|-----------|---------|---------|
| `switch.crop_steering_system_enabled` | ON | Master kill switch. OFF = emergency stop all hardware. |
| `switch.crop_steering_auto_irrigation_enabled` | ON | Enables automatic irrigation decisions. Manual shots still work when OFF. |
| `switch.crop_steering_ec_stacking_enabled` | OFF | EC stacking mode: builds EC when below target instead of diluting. |
| `switch.crop_steering_analytics_enabled` | OFF | Enables analytics tracking. |
| `switch.crop_steering_zone_N_enabled` | ON | Enables zone N for irrigation. OFF = zone skipped in all decisions. |
| `switch.crop_steering_zone_N_manual_override` | OFF | **Absolute lockout.** ON = no irrigation of any kind on this zone. |

### Selects (from custom component)

| Entity ID | Options | Default | Purpose |
|-----------|---------|---------|---------|
| `select.crop_steering_crop_type` | Cannabis_Athena, Cannabis_Hybrid, Cannabis_Indica, Cannabis_Sativa, Tomato, Lettuce, Basil, Custom | Cannabis_Athena | Active crop profile |
| `select.crop_steering_growth_stage` | Vegetative, Generative, Transition | Vegetative | Current growth stage — changes EC targets and dryback aggressiveness |
| `select.crop_steering_steering_mode` | Vegetative, Generative | Vegetative | Steering mode |
| `select.crop_steering_irrigation_phase` | P0, P1, P2, P3 | P0 | System-wide phase override — applies to zones set to "Auto" |
| `select.crop_steering_zone_N_group` | Ungrouped, Group A/B/C/D | Ungrouped | Zone grouping for coordinated irrigation |
| `select.crop_steering_zone_N_priority` | Critical, High, Normal, Low | Normal | Zone priority for irrigation scheduling |
| `select.crop_steering_zone_N_crop_profile` | Follow Main, Cannabis_Athena, etc. | Follow Main | Per-zone crop profile override |
| `select.crop_steering_zone_N_phase_override` | Auto, P0, P1, P2, P3 | Auto | Per-zone phase lock. Non-Auto = permanent hold until set back to Auto. |

### Numbers (from custom component)

All have the `crop_steering_` prefix. Listed by category.

**Substrate & Hardware:**

| Entity ID | Range | Default | Unit |
|-----------|-------|---------|------|
| `number.crop_steering_substrate_volume` | 1–200 | 10.0 | L |
| `number.crop_steering_dripper_flow_rate` | 0.1–50 | 1.2 | L/hr |
| `number.crop_steering_drippers_per_plant` | 1–6 | 2 | — |
| `number.crop_steering_field_capacity` | 20–100 | 70.0 | % |
| `number.crop_steering_max_ec` | 1–20 | 9.0 | mS/cm |
| `number.crop_steering_lights_on_hour` | 0–23 | 12 | hour |
| `number.crop_steering_lights_off_hour` | 0–23 | 0 | hour |

**P0 Parameters:**

| Entity ID | Range | Default | Unit |
|-----------|-------|---------|------|
| `number.crop_steering_veg_dryback_target` | 20–80 | 50.0 | % |
| `number.crop_steering_gen_dryback_target` | 15–70 | 40.0 | % |
| `number.crop_steering_p0_min_wait_time` | 5–300 | 30.0 | min |
| `number.crop_steering_p0_max_wait_time` | 30–600 | 120.0 | min |
| `number.crop_steering_p0_dryback_drop_percent` | 2–40 | 15.0 | % |

**P1 Parameters:**

| Entity ID | Range | Default | Unit |
|-----------|-------|---------|------|
| `number.crop_steering_p1_target_vwc` | 30–95 | 65.0 | % |
| `number.crop_steering_p1_initial_shot_size` | 0.1–20 | 2.0 | % substrate |
| `number.crop_steering_p1_shot_increment` | 0.05–10 | 0.5 | % substrate |
| `number.crop_steering_p1_max_shot_size` | 2–50 | 10.0 | % substrate |
| `number.crop_steering_p1_time_between_shots` | 1–60 | 15.0 | min |
| `number.crop_steering_p1_max_shots` | 1–30 | 6.0 | — |
| `number.crop_steering_p1_min_shots` | 1–20 | 3.0 | — |

**P2 Parameters:**

| Entity ID | Range | Default | Unit |
|-----------|-------|---------|------|
| `number.crop_steering_p2_vwc_threshold` | 25–85 | 60.0 | % |
| `number.crop_steering_p2_shot_size` | 0.5–30 | 5.0 | % substrate |
| `number.crop_steering_p2_ec_high_threshold` | 0.5–3.0 | 1.2 | ratio |
| `number.crop_steering_p2_ec_low_threshold` | 0.2–2.0 | 0.8 | ratio |

**P3 Parameters:**

| Entity ID | Range | Default | Unit |
|-----------|-------|---------|------|
| `number.crop_steering_p3_emergency_vwc_threshold` | 20–65 | 40.0 | % |
| `number.crop_steering_p3_emergency_shot_size` | 0.1–15 | 2.0 | % substrate |
| `number.crop_steering_p3_veg_last_irrigation` | 15–360 | 120.0 | min |
| `number.crop_steering_p3_gen_last_irrigation` | 30–600 | 180.0 | min |

**EC Targets (Vegetative):**

| Entity ID | Range | Default | Unit |
|-----------|-------|---------|------|
| `number.crop_steering_ec_target_flush` | 0.1–15 | 0.8 | mS/cm |
| `number.crop_steering_ec_target_veg_p0` | 0.5–15 | 3.0 | mS/cm |
| `number.crop_steering_ec_target_veg_p1` | 0.5–15 | 3.0 | mS/cm |
| `number.crop_steering_ec_target_veg_p2` | 0.5–15 | 3.2 | mS/cm |
| `number.crop_steering_ec_target_veg_p3` | 0.5–15 | 3.0 | mS/cm |

**EC Targets (Generative):**

| Entity ID | Range | Default | Unit |
|-----------|-------|---------|------|
| `number.crop_steering_ec_target_gen_p0` | 0.5–20 | 4.0 | mS/cm |
| `number.crop_steering_ec_target_gen_p1` | 0.5–20 | 5.0 | mS/cm |
| `number.crop_steering_ec_target_gen_p2` | 0.5–20 | 6.0 | mS/cm |
| `number.crop_steering_ec_target_gen_p3` | 0.5–20 | 4.5 | mS/cm |

**Per-Zone Numbers (N = 1–6):**

| Entity ID | Range | Default | Unit |
|-----------|-------|---------|------|
| `number.crop_steering_zone_N_plant_count` | 1–200 | 4 | — |
| `number.crop_steering_zone_N_max_daily_volume` | 0–500 | 20.0 | L |
| `number.crop_steering_zone_N_shot_size_multiplier` | 0.1–5.0 | 1.0 | multiplier |
| `number.crop_steering_zone_N_dryback_target` | 0–80 | 0 | % |
| `number.crop_steering_zone_N_p1_target_vwc` | 0–95 | 0 | % |
| `number.crop_steering_zone_N_p2_vwc_threshold` | 0–85 | 0 | % |
| `number.crop_steering_zone_N_p3_emergency_vwc` | 0–65 | 0 | % |

A value of **0** on any per-zone target means "use the system-wide default."

### Buttons (from custom component)

| Entity ID | Purpose |
|-----------|---------|
| `button.crop_steering_zone_N_trigger_shot` | Press to fire one manual irrigation shot on zone N using P2 shot size parameters. Blocked if manual override is ON. |

### Sensors (created by AppDaemon)

These are written by the AppDaemon app at runtime. They do NOT have the naming conflict — they use exactly the entity ID shown.

| Entity ID | Purpose |
|-----------|---------|
| `sensor.crop_steering_app_status` | System status: `safe_idle`, `irrigating`, `error` |
| `sensor.crop_steering_app_current_phase` | Comma-separated zone phase summary (e.g., `Z1:P2, Z2:P1`) |
| `sensor.crop_steering_app_next_irrigation` | Timestamp of next estimated irrigation |
| `sensor.crop_steering_zone_N_phase` | Current phase for zone N |
| `sensor.crop_steering_zone_N_daily_water_app` | Daily water usage for zone N (L) |
| `sensor.crop_steering_zone_N_weekly_water_app` | Weekly water usage for zone N (L) |
| `sensor.crop_steering_zone_N_irrigation_count_app` | Number of irrigations today for zone N |
| `sensor.crop_steering_zone_N_last_irrigation_app` | Timestamp of last irrigation for zone N |
| `sensor.crop_steering_zone_N_health_score` | Zone health 0–1 (VWC + EC in range) |
| `sensor.crop_steering_zone_N_efficiency` | Zone irrigation efficiency 0–1 |
| `sensor.crop_steering_zone_N_safety_status` | `safe`, `approaching_saturation`, `over_saturated`, `approaching_ec_limit`, `ec_limit_exceeded` |
| `sensor.crop_steering_ai_heartbeat` | AI oversight status with zone summary attributes |
| `sensor.crop_steering_ai_last_action` | Last corrective action taken by AI |
| `sensor.crop_steering_system_health_score` | Overall system health 0–100 |
| `sensor.crop_steering_system_safety_status` | `safe`, `warning`, `unsafe` |
| `sensor.crop_steering_sensor_health` | Number of healthy sensors |
| `sensor.crop_steering_daily_water_usage` | Total daily water across all zones (L) |
| `sensor.crop_steering_fused_vwc` | Kalman-filtered average VWC |
| `sensor.crop_steering_fused_ec` | Kalman-filtered average EC |
| `sensor.crop_steering_dryback_percentage` | Current dryback % from peak |
| `sensor.crop_steering_current_decision` | Last decision: `irrigate` or `wait` with reason |
| `sensor.crop_steering_ml_irrigation_need` | ML-predicted irrigation need 0–1 |
| `sensor.crop_steering_ml_confidence` | ML model confidence 0–1 |
| `sensor.crop_steering_water_efficiency` | Water use efficiency metric |
| `sensor.crop_steering_system_efficiency` | Overall system efficiency % |

### Events

| Event | Data | Purpose |
|-------|------|---------|
| `crop_steering_trigger_zone_shot` | `{zone, source}` | Fired by trigger shot button |
| `crop_steering_reset_emergency` | `{zone}` (optional) | Clear emergency lockout for zone or all |
| `crop_steering_manual_irrigation` | `{zone, duration}` | Request manual irrigation |
| `crop_steering_phase_transition` | `{target_phase, reason, forced}` | Request phase change |
| `crop_steering_manual_override` | `{zone, action, timeout_minutes}` | Override control |

---

<a name="configuration"></a>
## 6. Configuration

### crop_steering.env

The primary configuration file. Located at `/config/crop_steering.env`. Parsed during HA integration setup.

**Zone definition (per zone):**
```
ZONE_1_SWITCH=switch.irrigation_table_1_valve
ZONE_1_VWC_SENSORS=sensor.substrate_1_substrate_1_vwc_coco_coir
ZONE_1_EC_SENSORS=sensor.substrate_1_substrate_1_pwec
ZONE_1_PLANT_COUNT=4
ZONE_1_MAX_DAILY_VOLUME=20.0
ZONE_1_SHOT_MULTIPLIER=1.0
```

Zones are auto-detected by scanning for `ZONE_N_SWITCH` entries. You can have up to 24 zones.

**Multi-sensor support:** Use comma-separated lists for zones with multiple probes:
```
ZONE_1_VWC_SENSORS=sensor.probe_a_vwc,sensor.probe_b_vwc,sensor.probe_c_vwc
```
The system averages all valid readings.

**Legacy format** (still supported):
```
ZONE_1_VWC_FRONT=sensor.probe_a
ZONE_1_VWC_BACK=sensor.probe_b
```

### apps.yaml

AppDaemon configuration at `/addon_configs/.../apps/apps.yaml`. Defines the master app with hardware, sensor, timing, and threshold config.

Key settings:
```yaml
master_crop_steering:
  module: crop_steering.master_crop_steering_app
  class: MasterCropSteeringApp
  hardware:
    pump_master: null          # No pump — pressure switch auto-starts
    main_line: switch.irrigation_mainline
    zone_valves:
      1: switch.irrigation_table_1_valve
      2: switch.irrigation_table_2_valve
      # ... through 6
  sensors:
    vwc:
      - sensor.substrate_1_substrate_1_vwc_coco_coir
      # ... through 6
    ec:
      - sensor.substrate_1_substrate_1_pwec
      # ... through 6
    environmental:
      temperature: sensor.irrigation_room_1_temp
      humidity: sensor.irrigation_room_1_rh
      vpd: sensor.irrigation_room_1_vpd
  timing:
    phase_check_interval: 60     # Decision loop interval (seconds)
    ml_prediction_interval: 300  # ML update interval (seconds)
    sensor_health_interval: 120  # Sensor health check interval (seconds)
  thresholds:
    emergency_vwc: 40.0          # Below this = emergency irrigation
```

### Lights Schedule

Set via `number.crop_steering_lights_on_hour` and `number.crop_steering_lights_off_hour` in the dashboard. These are system-wide (not per-zone). Current setup: **08:00 on, 20:00 off** (set in `.env` as `LIGHTS_ON_TIME` and `LIGHTS_OFF_TIME`).

The AppDaemon app also checks `sun.sun` entity elevation as a fallback for lights-on detection.

---

<a name="dashboard-layout"></a>
## 7. Dashboard Layout

The dashboard is at `/config/dashboards/crop_steering.yaml`, path `crop-steering/crop-steering`. It uses the HA sections view with max 4 columns.

### Row 1 — System Controls + Infrastructure + Valves + AI Status

Top row gives you the master switches (system enabled, auto irrigation, EC stacking, analytics), crop type/growth stage selects, lights schedule, infrastructure switches (mainline, mains water, manifold, tank fill, waste, recirculation), all 6 zone valves with last-changed timestamps, and AI status sensors.

### Row 2 — Live Sensors + Phase Override + Trigger Shots

All 6 VWC readings, all 6 EC readings, per-zone phase override selects (Auto/P0/P1/P2/P3), and per-zone trigger shot buttons.

### Row 3 — System Health + Manual Override + Zone Safety + AI Oversight

System health score, sensor health, daily water, fused VWC/EC, dryback percentage. Manual override switches for all 6 zones. Per-zone safety status. AI heartbeat and last action.

### Row 4 — Water Usage + Zone Health

Daily water per zone, irrigation count per zone, zone health scores, zone efficiency scores.

### Row 5 — Phase Parameters (P0, P1, P2, P3)

Four columns, one per phase. All tunable parameters for each phase.

### Row 6 — EC Targets + Hardware Config

Vegetative EC targets (P0–P3), generative EC targets (P0–P3), max EC, substrate volume, dripper flow rate, drippers per plant, field capacity, lights schedule.

### Row 7 — Zone Tuning

One card per zone (6 total). Each card has: group, priority, crop profile, shot multiplier, plant count, max daily volume, and the 4 per-zone target overrides (dryback, P1 VWC, P2 threshold, P3 emergency — all default 0 = use system).

### Row 8 — Current Zone Phases + Zone Efficiency

Read-only zone phase sensors and efficiency scores.

### Row 9 — Sensor Reliability + Sensor Health

Per-sensor reliability scores and health status from the sensor fusion module.

### Row 10 — Instruction Manual

Embedded markdown card with operational reference.

---

<a name="zone-management"></a>
## 8. Zone Management

### Zone Enable vs Manual Override

These are two different switches with different purposes:

| | `zone_N_enabled` | `zone_N_manual_override` |
|---|---|---|
| **Purpose** | Include/exclude zone from system | **Absolute safety lockout** |
| **Effect when OFF/ON** | Zone skipped in decisions | ALL irrigation blocked — including emergency |
| **Use case** | Zone not in use, no plants | Maintenance, flushing, investigating a problem |
| **Affects emergency?** | Zone still gets emergency shots | **No. Nothing waters this zone.** |

**Manual override is an absolute lockout.** When it's ON, the zone cannot be irrigated by any mechanism — not automatic, not emergency, not manual trigger shots. It is checked at three levels:

1. **Zone selection** — overridden zones excluded from emergency candidate selection
2. **Decision evaluation** — overridden zones skipped in phase requirement evaluation
3. **Valve actuation** — defense-in-depth check right before the valve opens

### Zone Groups

Zones can be assigned to Group A, B, C, or D (or Ungrouped). Groups coordinate irrigation:

- If >= 50% of zones in a group need water, ALL zones in that group irrigate
- Only 1 zone can irrigate at a time (pressure protection) — group zones are queued
- Group conflicts prevent a zone from irrigating if another zone in the same group is already watering

### Zone Priority

Priority affects which zone waters first when multiple zones need irrigation:

| Priority | Score | Effect |
|----------|-------|--------|
| Critical | 4 | Always served first |
| High | 3 | Served before Normal/Low |
| Normal | 2 | Default |
| Low | 1 | Served last |

Zone selection uses a composite score: **Priority (40%) + VWC Need (40%) + Phase Urgency (20%)**. Phase urgency: P1=0.9 (highest), P3=0.8, P2=0.6, P0=0.1 (lowest).

### Per-Zone Crop Profile

Each zone can follow the main system crop profile or have its own. Options: Follow Main, Cannabis_Athena, Cannabis_Indica_Dominant, Cannabis_Sativa_Dominant, Cannabis_Balanced_Hybrid, Tomato_Hydroponic, Lettuce_Leafy_Greens, Custom.

---

<a name="phase-parameters"></a>
## 9. Phase Parameters — What Each One Does

### P0 (Morning Dryback)

| Parameter | What It Controls |
|-----------|-----------------|
| `veg_dryback_target` (50%) | How much of the peak VWC the substrate should lose during dryback in vegetative mode. Higher = more aggressive dryback. |
| `gen_dryback_target` (40%) | Same but for generative mode. Lower target = less dryback = more generative steering. |
| `p0_min_wait_time` (30 min) | Minimum time to wait in P0 regardless of dryback progress. Prevents premature exit. |
| `p0_max_wait_time` (120 min) | Maximum time in P0. Forces exit to P1 even if dryback target not met. |
| `p0_dryback_drop_percent` (15%) | Minimum absolute VWC drop required (e.g., from 60% to 51% = 9% drop). Alternative exit condition. |

### P1 (Ramp-Up)

| Parameter | What It Controls |
|-----------|-----------------|
| `p1_target_vwc` (65%) | VWC target. P1 ends when this is reached and min shots are done. |
| `p1_initial_shot_size` (2%) | First shot size as % of substrate volume. 2% of 10L = 200mL. |
| `p1_shot_increment` (0.5%) | Each subsequent shot increases by this much. Shot 1 = 2%, Shot 2 = 2.5%, Shot 3 = 3%, etc. |
| `p1_max_shot_size` (10%) | Shots never exceed this size. |
| `p1_time_between_shots` (15 min) | Cooldown between P1 shots. Allows substrate to absorb and sensors to stabilize. |
| `p1_min_shots` (3) | Minimum shots before P1 can exit, even if VWC target is met. Ensures adequate rehydration. |
| `p1_max_shots` (6) | Maximum shots. P1 exits after this many even if target not reached. |

### P2 (Maintenance)

| Parameter | What It Controls |
|-----------|-----------------|
| `p2_vwc_threshold` (60%) | VWC below this triggers a maintenance shot. |
| `p2_shot_size` (5%) | Shot size as % of substrate volume. |
| `p2_ec_high_threshold` (1.2) | EC ratio above this = too salty. Shot size increased 1.5x to flush. |
| `p2_ec_low_threshold` (0.8) | EC ratio below this = too dilute. Shot size decreased 0.7x to conserve. |

### P3 (Pre-Lights-Off)

| Parameter | What It Controls |
|-----------|-----------------|
| `p3_emergency_vwc_threshold` (40%) | VWC below this triggers an emergency shot even during P3. |
| `p3_emergency_shot_size` (2%) | Size of emergency shots during P3. Kept small to maintain dryback. |
| `p3_veg_last_irrigation` (120 min) | Minutes before lights-off for last irrigation in vegetative mode. |
| `p3_gen_last_irrigation` (180 min) | Minutes before lights-off for last irrigation in generative mode. |

---

<a name="ec-targets"></a>
## 10. EC Targets and Ratio Logic

The system uses **EC ratio** (current_ec / target_ec) to adjust irrigation behavior. Each phase and growth stage has its own EC target.

### How EC Ratio Works

| EC Ratio | Meaning | System Response |
|----------|---------|-----------------|
| < 0.8 | EC too low — nutrients diluted | Reduce shot size (conserve nutrients) |
| 0.8 – 1.2 | Optimal range | Normal operation |
| > 1.2 | EC too high — salt buildup | Increase shot size (flush) |
| > 2.0 | Emergency (P3) | Emergency shot regardless of phase |
| > 2.5 | Emergency (P0) | Flush shot even during dryback |

### EC Stacking Mode

When `switch.crop_steering_ec_stacking_enabled` is ON, the system reverses its EC behavior: instead of diluting when EC is high, it tries to **build** EC when it's below target (deficit > 0.5 mS/cm). This is used when you want to push EC higher intentionally.

### Default EC Targets

| Phase | Vegetative | Generative |
|-------|-----------|------------|
| P0 | 3.0 | 4.0 |
| P1 | 3.0 | 5.0 |
| P2 | 3.2 | 6.0 |
| P3 | 3.0 | 4.5 |
| Flush | 0.8 | 0.8 |

---

<a name="per-zone-targets"></a>
## 11. Per-Zone Targets

Each zone has 4 override parameters. **Set to 0 to use the system-wide default.** Any value > 0 overrides the system default for that zone only.

| Parameter | System Default Entity | Per-Zone Entity |
|-----------|----------------------|-----------------|
| Dryback target | `number.crop_steering_veg_dryback_target` | `number.crop_steering_zone_N_dryback_target` |
| P1 target VWC | `number.crop_steering_p1_target_vwc` | `number.crop_steering_zone_N_p1_target_vwc` |
| P2 VWC threshold | `number.crop_steering_p2_vwc_threshold` | `number.crop_steering_zone_N_p2_vwc_threshold` |
| P3 emergency VWC | `number.crop_steering_p3_emergency_vwc_threshold` | `number.crop_steering_zone_N_p3_emergency_vwc` |

**Example:** Zone 4 has a weaker root system and dries out faster. Set `zone_4_p2_vwc_threshold` to 65 (instead of system default 60) so it gets watered sooner. Leave all other zones at 0 to use defaults.

---

<a name="manual-override"></a>
## 12. Manual Override

### Absolute Lockout

When `switch.crop_steering_zone_N_manual_override` is ON:

- No automatic irrigation
- No emergency irrigation
- No manual trigger shots
- No ML-triggered irrigation
- **Nothing opens that valve**

This is a safety feature for maintenance — flushing substrate, unplugging a zone, fixing a leak, investigating a sensor.

### How It's Detected

The system checks for manual override through 4 layers (in order):

1. **In-memory dict** — AppDaemon's internal tracking
2. **Switch state cache** — populated by `listen_state` callbacks
3. **AppDaemon state cache** — `get_state()` call
4. **HA REST API** — direct HTTP call to HA as final fallback

This multi-layer approach exists because AppDaemon cannot reliably read custom component entity states via `get_state()`.

### Timed Overrides

You can set a timed override via the `crop_steering_manual_override` event with `action: enable_with_timeout` and `timeout_minutes`. The override auto-disables when the timer expires and sends a notification.

### Override Active > 24 Hours Warning

The AI heartbeat flags any zone with manual override active for more than 24 hours as a potential forgotten override.

---

<a name="emergency-irrigation"></a>
## 13. Emergency Irrigation

### When It Fires

Emergency irrigation triggers when any fused VWC reading drops below `emergency_vwc` (default 40%). This runs independently of the normal decision loop — it fires from the VWC sensor update callback.

### Emergency Flow

1. 120-second startup grace period (no emergencies right after boot)
2. 300-second cooldown between emergency shots
3. Select zone with lowest VWC from sensor fusion cache
4. Skip zones with manual override ON
5. Skip zones with active emergency lockout
6. Check effective VWC ceiling (for non-responding sensors)
7. Fire 60-second emergency shot

### Escalating Backoff

If a zone gets 4+ emergency shots in 30 minutes without VWC responding:

| Abandonment Count | Lockout Duration |
|-------------------|-----------------|
| 1st | 2 hours |
| 2nd | 4 hours |
| 3rd | 8 hours |
| 4th+ | **Permanent** (manual reset required) |

### VWC Response Tracking

After emergency shots, the system checks if VWC actually rose. If the average lift across 3+ shots is less than 1%, it sets an `effective_vwc_ceiling` at `max_observed_vwc + 2%`. This prevents endless watering of a zone where the sensor is positioned badly or the dripper is blocked.

### Resetting Emergency Lockouts

Fire the `crop_steering_reset_emergency` event:
- With `{zone: N}` to reset a specific zone
- Without a zone to reset all zones

This clears the abandonment count, lockout timer, and effective VWC ceiling.

---

<a name="ai-heartbeat"></a>
## 14. AI Heartbeat

Runs every 15 minutes. Checks 6 anomaly conditions per zone and takes corrective action.

### Anomaly Checks

| # | Condition | Auto-Correction |
|---|-----------|-----------------|
| 1 | Phase stuck in P0 > 4 hours during lights-on | Force transition to P1 |
| 2 | VWC sensor stale > 15 minutes | Log warning, flag zone as `sensor_stale` |
| 3 | VWC not responding to irrigation (3+ shots, <1% avg lift) | Set effective VWC ceiling |
| 4 | EC trending up across 3 consecutive heartbeats (>1.0 mS/cm rise) | Log warning |
| 5 | > 20 irrigations today | Log warning |
| 6 | Manual override active > 24 hours | Log warning (possible forgotten override) |

### Published Sensors

- `sensor.crop_steering_ai_heartbeat` — state: anomaly count. Attributes: zone summary, anomalies list, actions taken.
- `sensor.crop_steering_ai_last_action` — last corrective action description.

### History

The heartbeat keeps a rolling buffer of 96 reports (24 hours at 15-minute intervals). EC trend detection uses a per-zone buffer of 12 readings (3 hours).

---

<a name="safety-layers"></a>
## 15. Safety Layers

Every irrigation shot passes through these checks in order. Any failure blocks the shot.

| # | Check | Threshold |
|---|-------|-----------|
| 1 | `switch.crop_steering_system_enabled` must be ON | — |
| 2 | `switch.crop_steering_auto_irrigation_enabled` must be ON (auto shots only; manual shots bypass) | — |
| 3 | `switch.crop_steering_zone_N_enabled` must be ON | — |
| 4 | `switch.crop_steering_zone_N_manual_override` must be OFF | — |
| 5 | `switch.crop_steering_tank_filling` must be OFF (conflict prevention) | — |
| 6 | Field capacity not exceeded | VWC < `field_capacity` (default 80%) |
| 7 | Max EC not exceeded | EC < `max_ec` (default 9.0 mS/cm) |
| 8 | Daily volume limit not reached | < `zone_N_max_daily_volume` (default 20L) |
| 9 | Extreme saturation backup | VWC < 90% |
| 10 | Extreme EC backup | EC < 15.0 mS/cm |
| 11 | Frequency limit | > 10 minutes since last zone irrigation |
| 12 | Daily count limit | < 50 irrigations per zone per day |
| 13 | Phase-specific safety | P0: blocked unless emergency VWC. P1: blocked if VWC > target+10%. P3: blocked if VWC > emergency+5%. |
| 14 | Zone conflicts | Max 1 concurrent irrigating zone. Group conflicts checked. |
| 15 | Already irrigating | Only one irrigation sequence at a time (async lock) |

### Watchdog

A 60-second watchdog checks for state mismatches:
- `irrigation_in_progress=True` but all hardware OFF → resets flag
- Hardware ON but `irrigation_in_progress=False` → emergency stop

### Sensor Fail-Safe

If ALL VWC sensors go offline while irrigation hardware is ON, the system executes an emergency stop. (120-second startup grace period to allow sensors to connect.)

### Clean Shutdown

When AppDaemon terminates, `terminate()` synchronously turns off the pump, main line, and all zone valves.

---

<a name="sensor-fusion"></a>
## 16. Sensor Fusion

The `IntelligentSensorFusion` module processes all sensor readings before they reach the decision logic.

### What It Does

1. **Outlier detection** — Rejects readings that are physically impossible (VWC outside 0–100, EC outside 0–20) or statistically extreme (>4 sigma from mean). Uses minimum deviation thresholds to avoid rejecting valid data when readings are stable: VWC needs >5% deviation from mean before statistical checks apply, EC needs >1.0 mS/cm.

2. **Reliability scoring** — Each sensor gets a 0–1 reliability score based on outlier rate, data consistency, temporal stability, and recent performance.

3. **Health classification** — `excellent`, `good`, `degraded`, `faulty`, `offline` (no data for 30+ minutes).

4. **Weighted fusion** — When multiple sensors exist per zone, values are averaged weighted by reliability. Excellent sensors get 1.2x weight, degraded sensors get 0.8x.

5. **Kalman filtering** — Smooths fused values to reduce noise. Separate filters per sensor type (VWC and EC are never mixed).

### Sensor Data Freshness

The system considers sensor data stale after 600 seconds (10 minutes). Stale readings are not used for zone VWC/EC calculations. The AI heartbeat flags sensors stale after 900 seconds (15 minutes).

---

<a name="crop-profiles"></a>
## 17. Crop Profiles

### Available Profiles

| Profile | Genetics | Dryback Range | EC Range | Best For |
|---------|----------|---------------|----------|----------|
| Cannabis_Athena | Hybrid | 15–25% | 3.0–9.0 | Athena nutrient line, balanced growth |
| Cannabis_Indica_Dominant | Indica | 12–22% | 2.8–8.0 | Dense, short plants; more moisture-tolerant |
| Cannabis_Sativa_Dominant | Sativa | 18–30% | 3.2–9.5 | Tall, stretchy plants; more aggressive dryback |
| Cannabis_Balanced_Hybrid | Hybrid | 15–25% | 3.0–8.5 | General-purpose hybrid |
| Tomato_Hydroponic | Vegetable | 8–15% | 2.0–4.5 | High-frequency, low-EC |
| Lettuce_Leafy_Greens | Leafy | 5–10% | 1.2–2.5 | Very high frequency, very low EC |

### Growth Stages

Each profile has parameters for 3 growth stages:
- **Vegetative** — Higher VWC targets, lower EC, more frequent irrigation
- **Early Flower** — Moderate settings, transition period
- **Late Flower** — Lower VWC targets, higher EC, less frequent irrigation (generative stress)

Change the growth stage via `select.crop_steering_growth_stage`. This affects all zones using that profile.

### Adaptive Learning

The crop profile system tracks irrigation performance (efficiency, VWC response, target achievement) and slowly adjusts parameters over time:
- Poor efficiency (<0.6) → raises VWC targets or dryback target
- Good efficiency (>0.8) with high hit rate → lowers dryback target slightly
- Poor plant response (<0.4) → lowers EC baseline
- Excellent response (>0.8) → raises EC baseline slightly

Adaptation rate is intentionally slow (0.1 learning rate with 0.8 momentum smoothing). Requires minimum 10 samples before adapting.

---

<a name="persistent-state"></a>
## 18. Persistent State

The system saves state to a JSON file every 5 minutes and on every irrigation event. On restart, it restores:

- **Zone phases** — Each zone returns to its saved phase. If the saved state doesn't make sense (e.g., lights are on but zone is in P3), it's corrected.
- **P0/P1 tracking** — Peak VWC, dryback progress, P1 shot count and timing.
- **Water usage** — Daily totals restored if same day; weekly totals if within 7 days.
- **Manual overrides** — Active overrides restored with remaining timeout. Expired overrides are discarded.
- **Last irrigation time** — Used for cooldown calculations.

The state file has a 10MB size limit. Corrupt JSON files are backed up with a `.corrupt.timestamp` extension.

### Downtime Recovery

On restart, the system logs how long it was down and validates all zone phases against the current light schedule. Zones in the wrong phase for the current time are corrected automatically.

---

<a name="failure-modes"></a>
## 19. Failure Modes and Troubleshooting

### Symptoms and Causes

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Zone not watering at all | Manual override ON, zone disabled, or emergency lockout | Check `switch.crop_steering_zone_N_manual_override` (OFF?) and `switch.crop_steering_zone_N_enabled` (ON?). Fire `crop_steering_reset_emergency` event if locked out. |
| Zone getting too many shots | VWC not rising after irrigation (blocked dripper, bad sensor position) | Check sensor placement. System will auto-lockout after 4 rapid shots. Reset with `crop_steering_reset_emergency` event after fixing. |
| All zones stuck in P3 | Lights schedule wrong, or `_should_zone_start_p3()` calculating early transition | Check `number.crop_steering_lights_on_hour` and `number.crop_steering_lights_off_hour`. Verify they match your actual lights schedule. |
| All zones stuck in P0 | Dryback target too aggressive, or VWC not dropping | Lower `veg_dryback_target` or increase `p0_max_wait_time`. Check if sensors are reading correctly. AI heartbeat will force P0→P1 after 4 hours. |
| Phase changes not taking effect | Per-zone phase override not set to "Auto" | Check `select.crop_steering_zone_N_phase_override` — must be "Auto" for automatic transitions. |
| System-wide phase change only affects some zones | Zones with non-"Auto" phase override are excluded | System-wide phase changes via `select.crop_steering_irrigation_phase` only apply to zones set to "Auto". |
| Dashboard shows "Entity not found" | Entity naming mismatch | Custom component entities have `crop_steering_` prefix. Dashboard may reference unprefixed names. |
| AppDaemon logs "0/15 switches warmed" | REST API can't read entity states at startup | Check AppDaemon plugin config has valid HA token. The system will still work via `listen_state` callbacks after entities report their first state change. |
| "No active crop profile" in logs | Profile not selected or failed to load | System auto-falls back to Cannabis_Athena/vegetative with hardcoded defaults. Not critical. |
| EC-based flush during P0 | EC ratio exceeded 2.5x target | This is by design — extreme EC overrides dryback to prevent root damage. |
| P1 exits early without reaching VWC target | Max shots reached (default 6) | Increase `p1_max_shots` or increase `p1_max_shot_size`. Check if shots are actually raising VWC (dripper flow, substrate saturation). |

### AppDaemon Logs

The master app logs to the `crop_steering_master` log (configured in `apps.yaml`). Key log messages to watch:

- `"Zone N: Transitioning P0 -> P1"` — phase change (INFO)
- `"Emergency irrigation: Zone N"` — emergency shot fired (WARNING)
- `"Zone N abandoned: escalating backoff"` — emergency lockout (WARNING)
- `"ABSOLUTE LOCKOUT"` — manual override blocking irrigation (INFO)
- `"AI Heartbeat:"` — 15-minute oversight report (INFO)
- `"Warmed switch cache: X/15"` — startup cache status (INFO)
- `"All sensors offline while irrigation active"` — fail-safe triggered (ERROR)

### Restarting

- **Restart HA** — needed after changing custom component files or `crop_steering.env`. All entity states persist across restarts.
- **Restart AppDaemon** — needed after changing `master_crop_steering_app.py` or other AppDaemon modules. State is restored from persistent file. 120-second startup grace period prevents false emergencies.

---

<a name="known-issues"></a>
## 20. Known Issues

### Entity Naming Mismatch

The custom component produces entity IDs with the `crop_steering_` prefix (e.g., `switch.crop_steering_system_enabled`). The AppDaemon app and dashboard reference some entities without this prefix (e.g., `switch.system_enabled`). The AppDaemon app works around this with dual-naming lookups in the switch cache warm, but the dashboard cards may show "Entity not found" for custom component entities that it references without the prefix.

### get_state() Returns None

AppDaemon's `get_state()` cannot see custom component entities. The system works around this by:
1. Using `listen_state` callbacks to populate an in-memory cache
2. Falling back to the HA REST API via `_check_ha_entity_state()`
3. Warming the switch cache at startup

This means entity values are not available until the first state change after AppDaemon starts, or until the REST API cache warm completes.

### P3 Early Transition

The `_should_zone_start_p3()` calculation can trigger too early if the predicted dryback rate is very slow. A substrate volume of 10L with a dryback target of 50% and a slow rate (e.g., 0.2%/hour) calculates 250 hours needed — which exceeds any lights-on period and causes immediate P3 transition. This typically self-corrects once the dryback detector has enough data for accurate rate prediction.

### Duplicate Method Definitions

`_get_phase_icon()`, `_get_zone_group()`, and `_get_zone_priority()` are defined twice in the master app. The second definition overrides the first. No functional impact, but the icon set differs between the two `_get_phase_icon()` definitions.

### Hardcoded Irrigation Count

`_get_irrigation_count_24h()` returns a hardcoded value of 8 instead of querying actual history. This affects ML training sample quality but not irrigation decisions.

### Hardcoded Lights-Off Fallback

`_get_lights_off_time()` has a hardcoded 22:00 fallback instead of reading from the `lights_off_hour` entity. The main phase transition logic does read from the entity correctly.

---

<a name="hardware-map"></a>
## 21. Hardware Map

### Current Installation

| Component | Entity ID | Physical |
|-----------|-----------|----------|
| Main Line Valve | `switch.irrigation_mainline` | GroundWork mainline solenoid |
| Zone 1 Valve | `switch.irrigation_table_1_valve` | Table 1 solenoid |
| Zone 2 Valve | `switch.irrigation_table_2_valve` | Table 2 solenoid |
| Zone 3 Valve | `switch.irrigation_table_3_valve` | Table 3 solenoid |
| Zone 4 Valve | `switch.irrigation_table_4_valve` | Table 4 solenoid |
| Zone 5 Valve | `switch.irrigation_table_5_valve` | Table 5 solenoid |
| Zone 6 Valve | `switch.irrigation_table_6_valve` | Table 6 solenoid |
| Pump | None (auto-start) | Constant pressure switch |
| Zone 1 VWC | `sensor.substrate_1_substrate_1_vwc_coco_coir` | GroundWork substrate probe |
| Zone 1 EC | `sensor.substrate_1_substrate_1_pwec` | GroundWork substrate probe (pore water EC) |
| Zone 2 VWC | `sensor.substrate_2_substrate_2_vwc_coco_coir` | GroundWork substrate probe |
| Zone 2 EC | `sensor.substrate_2_substrate_2_pwec` | GroundWork substrate probe |
| Zone 3 VWC | `sensor.substrate_3_substrate_3_vwc_coco_coir` | GroundWork substrate probe |
| Zone 3 EC | `sensor.substrate_3_substrate_3_pwec` | GroundWork substrate probe |
| Zone 4 VWC | `sensor.substrate_4_substrate_4_vwc_coco_coir` | GroundWork substrate probe |
| Zone 4 EC | `sensor.substrate_4_substrate_4_pwec` | GroundWork substrate probe |
| Zone 5 VWC | `sensor.substrate_5_substrate_5_vwc_coco_coir` | GroundWork substrate probe |
| Zone 5 EC | `sensor.substrate_5_substrate_5_pwec` | GroundWork substrate probe |
| Zone 6 VWC | `sensor.substrate_6_substrate_6_vwc_coco_coir` | GroundWork substrate probe |
| Zone 6 EC | `sensor.substrate_6_substrate_6_pwec` | GroundWork substrate probe |
| Room Temp | `sensor.irrigation_room_1_temp` | GroundWork gateway sensor |
| Room Humidity | `sensor.irrigation_room_1_rh` | GroundWork gateway sensor |
| Room VPD | `sensor.irrigation_room_1_vpd` | GroundWork gateway sensor |
| Mains Water | `switch.irrigation_mains_water` | Mains water valve (infrastructure) |
| Manifold | `switch.irrigation_manifold` | Tank filling/mixing manifold |
| Tank Fill | `switch.irrigation_tank_fill_valve` | Tank fill valve |
| Waste Valve | `switch.irrigation_waste_valve` | Waste/drain valve |
| Recirculation | `switch.irrigation_recirculation_valve` | Recirculation valve |

### Irrigation Sequence Timing

| Step | Duration |
|------|----------|
| Main line open → zone valve open | 1 second |
| Zone valve open → irrigation duration | Varies by phase/shot size |
| Zone valve close → main line close | 1 second |
| Main line close → pump stop | 1 second |
| Post-irrigation sensor stabilization | 30 seconds |

### Shot Duration Calculation

Duration in seconds = `(shot_size_percent / 100) * substrate_volume_L * 1000 / (dripper_flow_rate_Lph * drippers_per_plant * 1000 / 3600)`

With defaults (10L substrate, 2 L/hr drippers, 2 drippers/plant):
- 2% shot (P1 initial) = 180 seconds (3 minutes)
- 5% shot (P2 maintenance) = 450 seconds (7.5 minutes)
- 10% shot (P0 EC flush) = 900 seconds (15 minutes)

### Water Volume Calculation

Per shot: `plant_count * drippers_per_plant * dripper_flow_rate * (duration_seconds / 3600) * shot_multiplier`

With defaults (4 plants, 2 drippers, 2 L/hr, multiplier 1.0):
- 180s shot = 0.8L
- 450s shot = 2.0L
- 900s shot = 4.0L

### Notifications

Notifications are sent via `notify.mobile_app_damians_iphone` (configured in `.env` as `NOTIFICATION_SERVICE`). Events that trigger notifications:
- Emergency lockout escalation
- Manual override enabled/disabled/timeout
- Critical EC levels
- AI heartbeat anomalies (critical only)
