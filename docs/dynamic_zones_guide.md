# Dynamic Zone Configuration Guide

## Overview

The Crop Steering integration supports a **variable number of irrigation zones**.
You declare zones in your `crop_steering.env` file (or the setup wizard) and the
integration auto-detects the count, then creates every per-zone entity for you.
There is no fixed zone limit in practice — the config-flow allows 1–24 zones and
the `.env` parser simply counts the `ZONE_N_SWITCH` entries it finds.

The live engine (the **f2-control add-on**) reads those same per-zone entities and
runs the P0→P1→P2→P3 phase logic **independently for every configured zone, every
cycle**. Zones are not chosen by a scoring algorithm — each one is evaluated on its
own readings on each ~60 s poll.

> This guide is the per-zone reference. For end-to-end setup see
> `docs/AGENT_INSTALL.md` and the README; for the entity catalogue see `ENTITIES.md`.

## How zone count is detected

The integration scans `crop_steering.env` for keys matching `ZONE_<N>_SWITCH`.
Every distinct `<N>` that has a valid switch (and at least one VWC and one EC
sensor) becomes a zone. Zone numbers may be sparse — `ZONE_1`, `ZONE_3`, `ZONE_5`
is detected as 3 zones. The detected count is stored as `num_zones` and drives how
many of each per-zone entity get created.

`custom_components/crop_steering/env_parser.py` is the single source of truth for
this parsing.

## Configuration methods

### Method 1: Load from crop_steering.env (recommended)

1. Copy `crop_steering.env.example` to `/config/crop_steering.env`.
2. Fill in your hardware, zones, and per-zone sensors.
3. Add the **Crop Steering System** integration and choose
   **"Load from crop_steering.env file"**.
4. The integration parses the file, reports how many zones it detected, and
   creates all entities.

### Method 2: Setup wizard (manual UI entry)

Add the integration and pick **Advanced Setup** instead, then enter the zone count
and map pump / main line / per-zone valve and sensor entities by hand. The `.env`
path is preferred because it auto-detects the zone count and is easy to re-edit.

## Per-zone .env keys

Required per zone:

```env
ZONE_1_SWITCH=switch.irrigation_relay_1
```

Sensors — two accepted formats:

```env
# Flexible (preferred): comma-separated list of any length; all valid
# readings are averaged.
ZONE_1_VWC_SENSORS=sensor.z1_vwc_a,sensor.z1_vwc_b,sensor.z1_vwc_c
ZONE_1_EC_SENSORS=sensor.z1_ec_a,sensor.z1_ec_b

# Legacy front/back pair (still supported):
ZONE_1_VWC_FRONT=sensor.vwc_zone_1_front
ZONE_1_VWC_BACK=sensor.vwc_zone_1_back
ZONE_1_EC_FRONT=sensor.ec_zone_1_front
ZONE_1_EC_BACK=sensor.ec_zone_1_back
```

If both formats are present, `VWC_SENSORS` / `EC_SENSORS` win. A zone is skipped
(with a warning in the log) if it has no switch, no VWC sensor, or no EC sensor.

Optional per-zone tunables (defaults shown):

```env
ZONE_1_PLANT_COUNT=4          # plants in the zone — scales shot volume
ZONE_1_MAX_DAILY_VOLUME=20.0  # liters/day safety cap
ZONE_1_SHOT_MULTIPLIER=1.0    # per-zone shot-size adjustment factor
```

## Entities created per zone

For each configured zone `X`, the integration creates:

### Switches
- `switch.crop_steering_zone_X_enabled` — enable / disable the zone
- `switch.crop_steering_zone_X_manual_override` — manual control mode
- `switch.crop_steering_zone_X_dripper_protection` — blocked-dripper guard
  (ON = abandon emergency irrigation for the row after repeated failed shots)

### Sensors
- `sensor.crop_steering_vwc_zone_X` — averaged VWC for the zone
- `sensor.crop_steering_ec_zone_X` — averaged EC for the zone
- `sensor.crop_steering_zone_X_status` — zone operational status
- `sensor.crop_steering_zone_X_last_irrigation` — last irrigation timestamp
- `sensor.crop_steering_zone_X_daily_water_usage` — liters today
- `sensor.crop_steering_zone_X_weekly_water_usage` — liters this week
- `sensor.crop_steering_zone_X_irrigation_count_today` — shot count today

### Per-zone selects / numbers
- `select.crop_steering_zone_X_phase_control` — Auto / P0 / P1 / P2 / P3 manual pin
- `select.crop_steering_zone_X_steering_mode` — Vegetative / Generative
- Per-zone `number.crop_steering_zone_X_*` tunables (substrate volume, thresholds)

### Global (across all configured zones)
- `sensor.crop_steering_configured_avg_vwc` — average VWC across all zones
- `sensor.crop_steering_configured_avg_ec` — average EC across all zones

See `ENTITIES.md` for the full list.

## How zones run

The f2-control add-on polls HA every ~60 s and, for **each** configured zone:

1. Skips the zone if `switch.crop_steering_zone_X_enabled` is OFF.
2. Reads the zone's averaged VWC/EC and its current phase.
3. Runs that zone's P0→P1→P2→P3 logic and decides whether a shot is due.
4. If a shot is due, runs the hardware sequence (pump → main line → zone valve)
   with fail-closed safety checks.

All actuation is gated by the global kill switch `input_boolean.f2_control_enabled`
(OFF = safe, no hardware writes). Each zone is independent — there is no
"pick one zone to irrigate" arbitration.

## Requesting a manual shot

`crop_steering.execute_irrigation_shot` accepts any configured zone number:

```yaml
service: crop_steering.execute_irrigation_shot
data:
  zone: 2
  duration_seconds: 300
  shot_type: P2            # P1 | P2 | P3_emergency (optional)
```

The integration fires the irrigation event; the f2-control add-on performs the
actual hardware sequence with its safety checks. The integration never drives
hardware directly.

## Troubleshooting

### Missing zone entities
1. Confirm each zone has a valid `ZONE_N_SWITCH` plus at least one VWC and one EC
   sensor — zones missing any of these are silently skipped (check the log).
2. Verify the referenced entity IDs exist in Home Assistant.
3. Reload the integration (Developer Tools → YAML → Reload Custom Components) or
   restart HA after editing `.env`.

### Zone not irrigating
1. Check `switch.crop_steering_zone_X_enabled` is ON.
2. Confirm `input_boolean.f2_control_enabled` is ON (the global kill switch).
3. Verify the zone's VWC/EC sensors return numeric values (not `unavailable` /
   `unknown`).
4. Confirm the zone valve entity responds to commands.
5. Check the add-on log for that zone's phase decision.

### Sensor validation errors
1. Sensors must return numeric values; check units (VWC %, EC mS/cm).
2. Averaging ignores `unavailable` / `unknown` readings but a zone with **no**
   valid VWC or EC will be skipped.

## Best practices

### Sensor placement
- Use multiple VWC/EC sensors per zone where possible (the `VWC_SENSORS` /
  `EC_SENSORS` list format averages them).
- Place sensors at root level in the substrate with good substrate contact.
- Calibrate sensors before use.

### Zone configuration
- Group plants with similar water needs into the same zone.
- Set `ZONE_N_PLANT_COUNT` accurately — it scales shot volume; a wrong count makes
  shots too short and short-cycles the pump.
- Use the per-zone enable switch for seasonal changes.

### Monitoring
- Watch per-zone status and VWC/EC trends.
- Use manual override / `execute_irrigation_shot` for testing a single zone.

## Example configurations

### Single zone
```env
PUMP_SWITCH=switch.veg_main_pump
MAIN_LINE_SWITCH=switch.espoe_irrigation_relay_2_3

ZONE_1_SWITCH=switch.greenhouse_valve
ZONE_1_VWC_SENSORS=sensor.teros12_moisture
ZONE_1_EC_SENSORS=sensor.teros12_ec
ZONE_1_PLANT_COUNT=36
```

### Three zones
```env
PUMP_SWITCH=switch.veg_main_pump
MAIN_LINE_SWITCH=switch.espoe_irrigation_relay_2_3

ZONE_1_SWITCH=switch.f2_row1
ZONE_1_VWC_FRONT=sensor.veg_vwc_1
ZONE_1_VWC_BACK=sensor.veg_vwc_2
ZONE_1_EC_FRONT=sensor.veg_ec_1
ZONE_1_PLANT_COUNT=36

ZONE_2_SWITCH=switch.f2_row2
ZONE_2_VWC_SENSORS=sensor.f1_vwc_front,sensor.f1_vwc_back
ZONE_2_EC_SENSORS=sensor.f1_ec_front,sensor.f1_ec_back
ZONE_2_PLANT_COUNT=36

ZONE_3_SWITCH=switch.f2_row3
ZONE_3_VWC_FRONT=sensor.f2_vwc_front
ZONE_3_EC_FRONT=sensor.f2_ec_front
ZONE_3_PLANT_COUNT=36
```
