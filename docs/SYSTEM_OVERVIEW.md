# System Overview — F1 Grow Room Control Stack

> **Read this first.** Single source of truth for how every layer of
> the F1 grow-room controller fits together: hardware → HA entities →
> control logic → dashboards. If something doesn't match this doc,
> the doc wins until updated.

## TL;DR

```
┌────────────────────────────────────────────────────────────────┐
│  HARDWARE                                                      │
│  6 tables · VWC/EC sensors · pump · mainline · table valves    │
│  1+ AC units · 4 dehu relays · humidifier · CO₂ solenoid       │
│  Room temp/RH/CO₂/VPD sensor · lights · leak + tank sensors    │
└──────────────────────────┬─────────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────────┐
│  HA ENTITY LAYER (template + integration entities)             │
│  switch.gw_*    sensor.gw_*    input_number.gw_*               │
│  climate.gw_ac_1 (and underlying climate.ac_1_ac_1_2)          │
│  number.crop_steering_*  switch.crop_steering_*                │
│  sensor.crop_steering_*                                        │
└──────────────────────────┬─────────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────────┐
│  CONTROL LAYER                                                 │
│                                                                │
│  ┌─────────────────────┐    ┌─────────────────────┐            │
│  │  GREEN WAVE PACK    │    │  CROP_STEERING      │            │
│  │  (legacy YAML       │    │  custom_components/ │            │
│  │   automations)      │    │  crop_steering/     │            │
│  │                     │    │                     │            │
│  │  Bang-bang dehu/    │    │  Calculations,      │            │
│  │  humid/CO2 with     │    │  entities, services │            │
│  │  hysteresis         │    │  (no hardware)      │            │
│  └──────────┬──────────┘    └──────────┬──────────┘            │
│             │                          │                       │
│             └──────────┬───────────────┘                       │
│                        ▼                                       │
│             ┌────────────────────┐                             │
│             │  APPDAEMON         │                             │
│             │  master app + 4-   │                             │
│             │  phase state       │                             │
│             │  machine           │                             │
│             │  (legacy)          │                             │
│             └──────────┬─────────┘                             │
│                        │                                       │
│      ┌─────────────────┴─────────────────┐                     │
│      ▼                                   ▼                     │
│  ┌──────────────────┐            ┌──────────────────┐          │
│  │  ROOTSENSE v3    │            │  CLIMATESENSE    │          │
│  │  intelligence/   │            │  intelligence/   │          │
│  │                  │            │  climate/        │          │
│  │  5 pillars,      │  ◄ bus ►   │  5 pillars,      │          │
│  │  each opt-in     │            │  each opt-in     │          │
│  │  via switch      │            │  via switch      │          │
│  └────────┬─────────┘            └─────────┬────────┘          │
│           │                                │                   │
│           └──────────┬─────────────────────┘                   │
│                      ▼                                         │
│            ┌────────────────────┐                              │
│            │ Orchestrator       │                              │
│            │ (in RootSense)     │                              │
│            │ - safety gates     │                              │
│            │ - cross-system     │                              │
│            │   coordination     │                              │
│            └─────────┬──────────┘                              │
│                      │                                         │
│                      ▼ HA service calls only                   │
└──────────────────────┬─────────────────────────────────────────┘
                       │
                       ▼
                  HARDWARE (back to top)
```

## 1. Hardware inventory (F1 Room 1)

### Sensing
| Quantity | What | Entities |
|---|---|---|
| 6 | Substrate VWC sensors (one per table) | `sensor.gw_table_1..6_vwc` |
| 6 | Substrate EC sensors (one per table) | `sensor.gw_table_1..6_ec` |
| 1 | Room air temperature | `sensor.gw_room_1_temp` |
| 1 | Room relative humidity | `sensor.gw_room_1_rh` |
| 1 | Room CO₂ ppm | `sensor.gw_room_1_co2` |
| 1 | Room VPD (derived) | `sensor.gw_room_1_vpd` |
| 1 | Lights state (binary) | `binary_sensor.gw_lights_on` |
| 1 | Water-leak detector | `binary_sensor.gw_leak` |
| 1 | Reservoir tank-low | `binary_sensor.gw_tank_low` |

### Actuation
| Quantity | What | Entities |
|---|---|---|
| 1 | Pump (irrigation) | (driven via mainline) |
| 1 | Mainline solenoid | `switch.gw_mainline` (template → underlying hardware switch) |
| 1 | Mains water solenoid | `switch.gw_mains_water` |
| 1 | Manifold solenoid | `switch.gw_manifold` |
| 6 | Per-table valves (KC868 E16S relay outputs) | `switch.gw_table_1..6_valve` |
| 4 | Dehumidifier relays | `switch.gw_dehumidifier_relay_1..4` |
| 1 | Humidifier | `switch.gw_humidifier` |
| 1 | CO₂ solenoid | `switch.gw_co2` |
| 1+ | AC unit / heat pump (better_thermostat) | `climate.gw_ac_1` → underlying `climate.ac_1_ac_1_2` etc |

### The hardware-calibration problem

> **You set the heat-pump to 27 °C. The room measures 29 °C.**

This is **not** a bug — it's normal commercial-HVAC behaviour. Causes:

- Heat pumps measure return-air at the unit, not the canopy.
- Lights add radiant heat that the unit's sensor doesn't see.
- The unit's deadband + idle-fan behaviour creates a steady-state offset.
- Mini-split sensors are biased ~1-3 °C below actual canopy temp at full-load.

**Solution: a per-actuator calibration table.** ClimateSense never
sends a target setpoint directly — it sends `target − offset`. The
offset is operator-tunable per actuator and per direction (heating
vs cooling — a unit that overshoots in cool mode often undershoots
in heat mode).

See §4 below for the actual data structure.

## 2. Entity-layer convention

Three name-spaces coexist by design — they're allowed to overlap so
the abstraction layers can be swapped independently.

| Prefix | Owner | Purpose |
|---|---|---|
| `*.gw_*` | Green Wave grow pack (YAML packages) | Site-stable abstraction over physical hardware. Templates that point at the actual `switch.table_1`, `climate.ac_1_ac_1_2`, etc. Operators tune **`input_number.gw_*` targets** here. |
| `*.crop_steering_*` | This integration (`custom_components/crop_steering/`) | Crop-steering controller state, derived metrics, RootSense intelligence sensors, intent slider, and per-pillar enable switches. |
| `climate.*`, raw `switch.*`, `sensor.*` | Underlying HA integrations (better_thermostat, AC Infinity, KC868, ESPHome, etc.) | The actual hardware. Never referenced directly by control logic — always via the `gw_*` template wrapper. |

This is why the GW pack has things like
`switch.gw_table_1_valve` mapping to `switch.table_1` — if the
underlying KC868 relay number changes, you update one mapping file,
not every automation.

## 3. Control-layer responsibilities

### 3.1 Green Wave pack (`packages/green_wave/`)

**Status:** live in production on F1.

- `00_core.yaml` — emergency stop script, notification group, pack-level constants.
- `10_mapping.yaml` — template switches/sensors that wrap underlying hardware.
- `20_model.yaml` — operator-tunable `input_number` / `input_boolean` / `input_datetime` helpers for targets, schedules, enables.
- `30_irrigation.yaml` — interval-window irrigation (legacy, before crop steering took over).
- `40_environment.yaml` — bang-bang temp / RH / CO₂ control with hysteresis. **Drives dehumidifier relays + humidifier + CO₂ solenoid only.** Does **not** drive the AC unit — that's a gap ClimateSense fills.
- `50_alerts_watchdogs.yaml` — valve max-runtime watchdogs, sensor-unavailable alerts, leak/tank emergency stops.

### 3.2 Crop Steering integration (`custom_components/crop_steering/`)

**Status:** v2.3.1 stable + v3.0-dev RootSense additions on `main`.

The HA-side integration. Does **not** touch hardware directly.

- Provides the entity surface (~120+ entities depending on zone count).
- Calculates derived sensors (shot durations, EC ratio, threshold adjustments).
- Registers services that fire events for AppDaemon to act on.
- Houses `ShotCalculator` and other pure helpers in `calculations.py`.

### 3.3 AppDaemon — legacy controller (`appdaemon/apps/crop_steering/master_crop_steering_app.py`)

**Status:** untouched in v3 work. Still the only thing that talks to
hardware.

- Owns the 4-phase state machine (P0 → P1 → P2 → P3).
- Sequences hardware safely (pump prime → main valve → zone valve → irrigate → shutdown).
- Listens to integration events, decides shots, validates safety, executes.
- Exposes diagnostic sensors back to HA.

### 3.4 AppDaemon — RootSense v3 substrate intelligence (`intelligence/`)

**Status:** Phases 0-2 shipped; Phases 3-5 in progress.

Five opt-in pillars, all gated by their own `switch.crop_steering_intelligence_*_enabled`:

- `root_zone.py` — substrate analytics, FC detection, dryback episode tracker.
- `adaptive_irrigation.py` — cultivator-intent slider, profile interpolation, bandit shot-size optimisation.
- `agronomic.py` — Penman-Monteith transpiration, VPD ceiling, nightly run reports.
- `orchestration.py` — `crop_steering.custom_shot` event handler, emergency rescue, EC flush.
- `anomaly.py` — emitter blockage, EC drift, sensor flat-line, peer-zone deviation.

Plus shared infra:
- `bus.py` — in-process pub/sub (`RootSenseBus`).
- `store.py` — local SQLite (`appdaemon/apps/crop_steering/state/rootsense.db`).
- `base.py` — `IntelligenceApp` mixin with module-enable gating.

### 3.5 AppDaemon — ClimateSense environmental intelligence (`intelligence/climate/`)

**Status:** SCAFFOLDED IN THIS COMMIT (sensing + timeline ship next, control loops after).

Five opt-in pillars, mirroring RootSense exactly:

- `sensing.py` — climate sensor fusion, derived metrics (DLI running total, leaf-air ΔT).
- `timeline.py` — recipe loader, per-phase target resolution, day/night switching, ramp interpolation.
- `control.py` — temp / RH / CO₂ closed loops with **hardware calibration offsets baked in**.
- `lights.py` — photoperiod manager, sunrise/sunset PPFD ramps, DLI tracking.
- `anomaly.py` — temp/RH/VPD/CO₂/DLI excursions, peer-sensor disagreement.

Five opt-in switches, default OFF:

- `switch.crop_steering_intelligence_climate_sensing_enabled`
- `switch.crop_steering_intelligence_climate_timeline_enabled`
- `switch.crop_steering_intelligence_climate_control_enabled`
- `switch.crop_steering_intelligence_climate_lights_enabled`
- `switch.crop_steering_intelligence_climate_anomaly_enabled`

## 4. Hardware-calibration data model

A single YAML file, `appdaemon/apps/crop_steering/intelligence/climate/hardware_f1.yaml`,
captures every per-actuator quirk:

```yaml
room: F1
hvac:
  primary:
    entity: climate.gw_ac_1                  # the GW template; resolves to underlying via input_text.gw_ac_unit_1
    cool_offset_c: -2.0                       # set 27 → actual reads 29 → command 25
    heat_offset_c: +0.0                       # heating doesn't drift in this unit
    min_setpoint_c: 16.0
    max_setpoint_c: 30.0
    settle_minutes: 8                          # don't act on a fresh command for this long
    deadband_c: 0.5                            # both sides
dehumidifier:
  relays: [switch.gw_dehumidifier_relay_1, switch.gw_dehumidifier_relay_2,
           switch.gw_dehumidifier_relay_3, switch.gw_dehumidifier_relay_4]
  stagger_seconds: 10                          # already in 40_environment.yaml — preserved
  min_off_seconds: 120
humidifier:
  entity: switch.gw_humidifier
  min_off_seconds: 120
co2:
  solenoid: switch.gw_co2
  pulse_on_seconds: 60
  pulse_off_seconds: 240
  hard_max_ppm: 1800                            # safety cap, no override
  off_at_lights_off: true
sensors:
  temp_primary: sensor.gw_room_1_temp
  rh_primary: sensor.gw_room_1_rh
  co2: sensor.gw_room_1_co2
  vpd: sensor.gw_room_1_vpd
  lights_on: binary_sensor.gw_lights_on
  leak: binary_sensor.gw_leak
  tank_low: binary_sensor.gw_tank_low
```

**The calibration is the only file that needs editing per install.**
Control loops are generic. When the operator says "set to 27 but it
reads 29", they update `cool_offset_c: -2.0` and the loop adapts
immediately.

A second-order calibration ("the offset itself drifts as the room
warms up") is a future extension — for now the linear offset model
is good to ±0.5 °C, which is well below the room's natural
fluctuation.

## 5. Recipe & timeline data model

`config/recipes/<name>.yaml`. Each recipe is a sequential list of
phases the room steps through over the entire grow:

```yaml
recipe: athena_f1_default
units:
  temp: c
  rh: pct
  co2: ppm
  vpd: kpa
phases:
  - name: "Veg week 1"
    days: 7
    photoperiod_hours: 18
    crop_steering_intent: 30          # vegetative bias for irrigation
    targets:
      day_temp_c:    {value: 26.5, tolerance: 1.0}
      night_temp_c:  {value: 22.5, tolerance: 1.5}
      day_rh_pct:    {value: 68, tolerance: 4}
      night_rh_pct:  {value: 62, tolerance: 4}
      vpd_kpa:       {value: 0.85, tolerance: 0.15}
      co2_ppm:       {value: 800, tolerance: 100}
      ppfd_target:   {value: 600, ramp_minutes: 30}
  # … through ripening + flush
```

The timeline pillar resolves "what are my targets *right now*" by:

1. Read `number.crop_steering_grow_day_offset` to know what day-in-grow we're on.
2. Walk the phase list; the first phase whose cumulative day-count exceeds the offset is active.
3. Pick day vs night targets based on `binary_sensor.gw_lights_on`.
4. Optionally interpolate between phases over a transition window
   (e.g. day 6 of veg → day 1 of bloom is a 24-h linear ramp).
5. Publish each target as a `sensor.climate_target_*` entity.

## 6. Orchestration & safety

The `IrrigationOrchestrator` (RootSense) is the single arbitration point for
hardware-touching actions. ClimateSense pillars **propose** changes via the
`RootSenseBus`; the orchestrator validates and routes.

Cross-system rules:

- Climate `temp_excursion` active → defer non-emergency irrigation in that room.
- Climate `vpd_divergence` while substrate is in P0 → annotate the dryback episode (the result will be confounded).
- Climate `dli_undershoot` predicted → bias toward more frequent shots.
- RootSense detects `emitter_blockage` in zone N → climate isn't affected, but the orchestrator suppresses zone N until cleared.
- Lights-off → CO₂ solenoid forcibly closed (already in `40_environment.yaml`, preserved).

## 7. Dashboards (`dashboards/legacyag/`)

Five linked Lovelace dashboards using `custom:agency-sensor-analytics-card`:

| File | View count | Purpose |
|---|---|---|
| `00_overview.yaml` | 1 | Landing page — at-a-glance status |
| `10_climate.yaml` | 3 | Temp&RH / CO₂ / VPD with measured-vs-target overlays |
| `20_substrate.yaml` | 2 | Per-table VWC&EC + RootSense per-zone intelligence |
| `30_intelligence.yaml` | 3 | Intent / Anomalies / Custom shot console |
| `40_setpoints.yaml` | 1 | Every operator target on one page (anchor for ClimateSense recipe view) |

All five share a markdown-nav header so they feel like one app.

The card pulls from HA's recorder history API today;
`docs/upgrade/INFLUXDB_GRAPHS_PLAN.md` covers the swap to InfluxDB
when long-window views start to lag.

## 8. Reference docs in this repo

| Doc | Read when… |
|---|---|
| `README.md` | First time anyone looks at the repo |
| `MIGRATION.md` | Upgrading an existing v2.3.x install to v3.0 |
| `CLAUDE.md` | Working on the code (in-repo dev guide) |
| `ENTITIES.md` | Looking up what an entity does |
| `docs/installation_guide.md` | Setting up a fresh install |
| `docs/operation_guide.md` | Daily operator routine |
| `docs/troubleshooting.md` | Something's wrong |
| `docs/SYSTEM_OVERVIEW.md` | **(this doc)** mental model of the whole stack |
| `docs/upgrade/ROOTSENSE_v3_PLAN.md` | Substrate intelligence design |
| `docs/upgrade/CLIMATESENSE_PLAN.md` | Environmental control design |
| `docs/upgrade/LLM_HEALTHCHECK_PLAN.md` | Future LLM advisor |
| `docs/upgrade/INFLUXDB_GRAPHS_PLAN.md` | Future graph backend swap |
| `docs/upgrade/RECONCILIATION.md` | Mapping codex's gap-analysis onto plan phases |
| `docs/upgrade/LLM_ADVISOR_NOTES.md` | Salvage notes from archived branch |
| `docs/upgrade/GAP_ANALYSIS_2026-05.md` | Codex's production-readiness gap audit |
| `docs/upgrade/apps.example.yaml` | Sample `apps.yaml` blocks for opting into pillars |
| `dashboards/legacyag/README.md` | Loading the dashboard suite |
