# ClimateSense — Environmental Control Platform (Plan)

> **Status:** plan — not implemented. Sibling to RootSense; consumes
> the same architectural patterns (pillars + bus + SQLite store +
> module-enable switches + intent slider).
>
> **Why a sibling, not a fork:** RootSense steers what happens *in
> the substrate*. ClimateSense steers what happens *in the air*.
> Both feed into the same canopy. Keeping them as parallel platforms
> with a shared coordinator avoids one omega-controller that knows
> about everything, and lets you enable either side independently.

This document plans an environmental-control system that:

1. Reads a **setpoints timeline** (the operator-facing recipe) for
   day temp / night temp / day RH / night RH / VPD / CO₂ / DLI /
   PPFD / photoperiod across the entire grow.
2. Drives HVAC, dehumidifier, CO₂ valve, lighting dimmers and
   schedules to chase those targets with PID-style closed loops and
   tolerance bands.
3. Coordinates with RootSense so substrate decisions account for
   what the climate is doing (and vice versa).
4. Exposes an HA-native dashboard view that mirrors the
   `legacy.ag/dashboard-setpoints/timeline` pattern.

## High-level architecture

```
                   ┌──────────────────────────────┐
                   │   SETPOINTS TIMELINE         │
                   │   (recipe.yaml + UI editor)  │
                   │   per phase / per week       │
                   └──────────────┬───────────────┘
                                  │
                ┌─────────────────┴─────────────────┐
                │                                   │
                ▼                                   ▼
    ┌─────────────────────┐             ┌─────────────────────┐
    │  RootSense          │             │  ClimateSense       │
    │  (substrate)        │             │  (air)              │
    │                     │             │                     │
    │  4 pillars +        │             │  4 pillars +        │
    │  anomaly + bus      │             │  anomaly + bus      │
    └─────────┬───────────┘             └─────────┬───────────┘
              │                                   │
              └────────────┬──────────────────────┘
                           ▼
              ┌────────────────────────────┐
              │   Coordinator (existing)   │
              │   safety gates +           │
              │   cross-system arbitration │
              └────────────┬───────────────┘
                           ▼
                   HARDWARE (HA services)
```

## ClimateSense pillars

Mirror RootSense's structure so the codebase stays consistent.

### Pillar 1 — Climate Sensing (`intelligence/climate/sensing.py`)

- Reads air temp, RH, CO₂, PPFD, leaf-surface temp (if IR sensor
  exists), airflow, room pressure differential.
- Cross-zone fusion: median + IQR outlier rejection (same approach
  as the substrate sensor fusion).
- Computes derived metrics: VPD (already covered by `agronomic.py` —
  ClimateSense will read that sensor rather than duplicate), DLI
  running total, predicted DLI at lights-off, average leaf-air
  delta-T.
- Publishes:
  - `sensor.climate_room_avg_temp_c`
  - `sensor.climate_room_avg_rh_pct`
  - `sensor.climate_room_co2_ppm`
  - `sensor.climate_room_dli_today_mol`
  - `sensor.climate_room_dli_predicted_mol`
  - `sensor.climate_room_leaf_air_dt_c`
  - `binary_sensor.climate_anomaly_active`

### Pillar 2 — Setpoints Timeline (`intelligence/climate/timeline.py`)

The operator-facing recipe. A single YAML file at
`config/recipes/<recipe_name>.yaml` defines the entire grow:

```yaml
recipe: "Athena_Hybrid_Indoor_v3"
phases:
  - name: "Transplant week 1"
    days: 7
    photoperiod_hours: 18
    targets:
      day_temp_c:    {value: 25.5, tolerance: 1.0}
      night_temp_c:  {value: 23.0, tolerance: 1.5}
      day_rh_pct:    {value: 72, tolerance: 5}
      night_rh_pct:  {value: 65, tolerance: 5}
      vpd_kpa:       {value: 0.7, tolerance: 0.2}
      co2_ppm:       {value: 600, tolerance: 100}
      ppfd_target:   {value: 350, ramp_minutes: 30}

  - name: "Veg week 2-3"
    days: 14
    photoperiod_hours: 18
    targets:
      day_temp_c:    {value: 27.0, tolerance: 1.0}
      night_temp_c:  {value: 23.5, tolerance: 1.5}
      day_rh_pct:    {value: 65, tolerance: 5}
      night_rh_pct:  {value: 60, tolerance: 5}
      vpd_kpa:       {value: 0.95, tolerance: 0.2}
      co2_ppm:       {value: 1000, tolerance: 100}
      ppfd_target:   {value: 700, ramp_minutes: 45}

  - name: "Early flower week 1-2"
    days: 14
    photoperiod_hours: 12
    crop_steering_intent: -10        # gentle generative bias
    targets:
      day_temp_c:    {value: 26.5, tolerance: 1.0}
      night_temp_c:  {value: 21.0, tolerance: 1.5}
      day_rh_pct:    {value: 58, tolerance: 4}
      night_rh_pct:  {value: 52, tolerance: 4}
      vpd_kpa:       {value: 1.15, tolerance: 0.15}
      co2_ppm:       {value: 1300, tolerance: 100}
      ppfd_target:   {value: 900, ramp_minutes: 45}

  # … through ripening + flush
```

The timeline reader publishes:

- `sensor.climate_recipe_active_phase` — phase name + day-in-phase
  in attributes.
- `sensor.climate_target_day_temp_c`, `..._night_temp_c`,
  `..._day_rh_pct`, etc. — current setpoint per metric, with
  attributes `{tolerance, ramp_minutes, source_phase, day_in_phase}`.
- `select.climate_active_recipe` — operator can swap recipes.
- `number.climate_grow_day_offset` — hand-set "what day are we on"
  if the grow started before HA had this running.

The timeline is also what publishes the
`crop_steering_steering_intent` value when a phase declares one
(only if `switch.climate_drives_intent_enabled` is on — keeps
RootSense fully manual unless explicitly delegated).

### Pillar 3 — Climate Control (`intelligence/climate/control.py`)

PID-with-deadband closed loops driving HA service calls:

- **Temp loop**: target = day_temp_c during photoperiod, else
  night_temp_c. Output → HVAC mode/setpoint via
  `climate.set_temperature` and/or `switch.heating_pad`,
  `switch.ac_unit`. Deadband prevents short-cycling.
- **RH loop**: target = day_rh_pct / night_rh_pct. Output →
  dehumidifier (`switch.dehumidifier`) and humidifier
  (`switch.humidifier`) with hysteresis.
- **CO₂ loop**: gated by photoperiod (lights must be on AND room
  not in flush mode). Output → CO₂ regulator solenoid valve.
  Hard cap on injection time per minute.
- **VPD pseudo-loop**: not a control loop — VPD is the *result* of
  temp + RH. Used as a quality gate: if measured VPD diverges from
  target by > tolerance for > N minutes despite temp/RH being on
  target, fire `climate_vpd_divergence` anomaly.
- **DLI manager**: tracks running PPFD-integral. If predicted DLI
  will undershoot by > 5%, the controller bumps PPFD by ≤10% for
  the remaining photoperiod. If overshoot, dim. Hard upper cap from
  the recipe.

Each loop has hard guardrails — temp can never command HVAC to set
above `number.climate_emergency_temp_max_c`, dehumidifier never
runs while heater is also on, CO₂ never injects with vents open.

### Pillar 4 — Photoperiod & Lights Manager (`intelligence/climate/lights.py`)

- Reads photoperiod from active recipe phase.
- Drives `switch.grow_lights_master` (or per-rack switches) on the
  schedule.
- Sunrise/sunset PPFD ramps with configurable duration.
- Fires `climate_lights_on` and `climate_lights_off` events that
  RootSense's existing photoperiod logic already listens for.
- Day-counter integration: lights-on count drives recipe phase
  progression unless the operator manually advances.

### Cross-cutting — Climate Anomaly Scanner

Same pattern as RootSense's `anomaly.py`:

- `temp_excursion`: > tolerance for > 5 min during photoperiod.
- `rh_excursion`: > tolerance for > 5 min.
- `co2_low_during_photoperiod`: < target − tolerance for > 10 min.
- `vpd_divergence`: VPD off target while temp/RH are on target.
- `dli_undershoot`: predicted DLI < target × 0.95.
- `sensor_disagreement`: peer sensors in same room > 2σ apart.

Same `crop_steering_anomaly` event format reused, with `code`
prefixed `climate_*` so existing handlers route correctly.

## The setpoints timeline UI

Two paths, depending on how much custom dev you want.

### Path A — Lovelace + ApexCharts (no custom dev)

Use `custom:apexcharts-card` (HACS) to render the timeline:

- X-axis: days since grow start (from `number.climate_grow_day_offset`).
- Y-axes: temp/RH/CO₂/PPFD overlaid as separate series.
- Reference lines at each phase boundary.
- The card reads a single sensor with the rendered timeline as
  attributes (`sensor.climate_recipe_timeline`); the timeline
  reader pre-formats the data into the shape ApexCharts wants.

To **edit** the timeline, you'd still hand-edit the recipe YAML
under `config/recipes/`. Quick to ship; not as nice as a draggable
UI.

### Path B — Custom Lovelace card (matches `legacy.ag` look)

A small React/Lit card that:

- Reads `sensor.climate_recipe_timeline` for the current state.
- Renders a Gantt-style timeline with draggable setpoint nodes.
- Posts edits back via a new HA service
  `crop_steering.recipe_edit_setpoint` with a JSON patch payload.
- Saves the edited recipe to `config/recipes/<name>.yaml` via the
  integration's file writer (limited to that directory).

Path B mirrors the `legacy.ag/dashboard-setpoints/timeline` UX.
~3-5 days of TypeScript + Lit work, plus a small file-writer
service in the HA integration.

**Recommendation: ship Path A first**, gather a season's worth of
operator feedback, then build Path B if hand-editing the YAML
becomes the bottleneck.

## Coordinator changes

The existing `IrrigationOrchestrator` becomes the entry-point for
arbitration — already bus-aware. New responsibilities:

- Subscribe to climate anomalies as well as substrate ones.
- Cross-system rules:
  - "If `climate_temp_excursion` is active in a zone's room, defer
    non-emergency irrigation in that zone."
  - "If `vpd_divergence` is active and a P0 dryback is in progress,
    log a note in the next dryback episode (the resulting plant
    behaviour will be confounded)."
  - "If lights just came on and `dli_undershoot` predicted for
    today, allow `intent_change` proposals from the LLM advisor
    that bias toward more frequent shots."

A new optional pillar `intelligence/cross_system_coordinator.py`
encapsulates these rules so the orchestrator stays slim.

## Phase plan

The plan parallels RootSense's 5-phase structure:

| Phase | What |
|---|---|
| **C0 — Foundation** | New package `intelligence/climate/`, scaffolds for the 4 pillars + recipe schema validator + recipe loader. No control yet. |
| **C1 — Sensing** | Climate sensor fusion + derived sensors. Read-only. |
| **C2 — Timeline + setpoint sensors** | Recipe loader publishes target sensors. Lovelace ApexCharts card (Path A). Operator can see the recipe but no controllers run yet. |
| **C3 — Control loops** | PID temp + RH + CO₂ + DLI loops live, with hard guardrails. Default OFF. Per-loop enable switches. |
| **C4 — Cross-system coordinator** | Orchestrator subscribes to climate anomalies; cross-system rules implemented. |
| **C5 — Custom Lovelace card (optional)** | Path B — draggable timeline, recipe-edit service. |

Each phase ships behind module-enable switches:

- `switch.climate_intelligence_sensing_enabled`
- `switch.climate_intelligence_timeline_enabled`
- `switch.climate_intelligence_control_enabled`
- `switch.climate_intelligence_lights_enabled`
- `switch.climate_intelligence_anomaly_enabled`

Default OFF. Operator opts in pillar by pillar exactly like
RootSense.

## Testing strategy

Reuse the `tests/intelligence/` pattern:

- `tests/intelligence/test_recipe_loader.py` — schema validation,
  phase progression math, ramp interpolation.
- `tests/intelligence/test_climate_pid.py` — closed-loop simulation
  with synthetic temp/RH responses.
- `tests/intelligence/test_climate_anomaly.py` — same shape as
  `test_anomaly_scanner.py`.
- `tests/intelligence/test_dli_manager.py` — DLI integration math,
  undershoot detection.

All pure-Python, all stub the AppDaemon hassapi via the existing
`_appdaemon_stub.py`.

## Hardware abstraction

The recipe targets are nominal. Each install needs a one-time
mapping from the abstract action to the user's specific entities:

```yaml
# config/climate_hardware.yaml
heating:
  primary: switch.heat_mat_room1
  secondary: climate.minisplit_room1
cooling:
  primary: climate.minisplit_room1
dehumidify:
  primary: switch.quest_dehu_room1
humidify:
  primary: switch.ultrasonic_humidifier_room1
co2:
  injector: switch.co2_solenoid_room1
  flow_rate_lpm: 5
lights:
  primary: switch.gavita_master_room1
  dimmer: number.gavita_dimmer_pct_room1
  ppfd_max: 1100
sensors:
  temp_primary: sensor.sht41_room1_temp
  temp_secondary: sensor.sht41_room1b_temp
  rh_primary: sensor.sht41_room1_rh
  rh_secondary: sensor.sht41_room1b_rh
  co2: sensor.scd41_room1_co2
  ppfd: sensor.apogee_room1_ppfd
```

This file is the only thing that needs to change between
installations. The control logic stays generic.

## Integration with the LLM advisor

Once both ClimateSense and the LLM advisor (`LLM_HEALTHCHECK_PLAN.md`)
exist, the 15-min report includes climate state too:

```json
{
  "ts": "2026-04-26T15:30:00Z",
  "phase": "P2",
  "intent": -10,
  "recipe_phase": "Early flower week 1",
  "recipe_day": 9,
  "climate": {
    "temp_c": 26.5, "temp_target": 26.5, "temp_status": "on_target",
    "rh_pct": 62, "rh_target": 58, "rh_status": "high",
    "vpd_kpa": 0.92, "vpd_target": 1.15, "vpd_status": "low",
    "co2_ppm": 1280, "co2_target": 1300,
    "dli_today_mol": 16.2, "dli_target": 38.0, "predicted": 37.4
  },
  "substrate": { /* per-zone */ },
  "anomalies": ["climate_rh_excursion:room=1"]
}
```

The LLM can now propose actions that span both systems:
"increase dehumidifier output for next 30 min AND lower
intent slider by 5 to compensate for slower transpiration".

## Naming convention

For consistency with RootSense:

- Domain in HA entity IDs: continue using `crop_steering` for
  shared things, introduce `climate_steering` (or just `climate`)
  for the new pillar set.
- Events: `climate_steering_*` (e.g. `climate_steering_anomaly`,
  `climate_steering_phase_advance`).
- AppDaemon module path: `intelligence/climate/` parallel to the
  existing `intelligence/` substrate modules.

This keeps a clear visual split when scrolling entity lists or
reading logs.

## What this is NOT

- Not a replacement for HA's existing climate / thermostat
  integrations — ClimateSense calls them. If you have a Mitsubishi
  mini-split exposed via the HA `climate` domain, ClimateSense
  drives `climate.set_temperature`, it does not implement the
  thermostat itself.
- Not a recipe library. We ship one example Athena recipe; users
  build their own under `config/recipes/`.
- Not a replacement for grow-room HVAC sequencing logic that lives
  in dedicated commercial controllers. A homelab-grade environment
  controller. For commercial deployments use this as the
  observability + advisory layer and a hardware controller as the
  bottom-most safety floor.

## Effort estimate

Rough order-of-magnitude, in focused-session days:

| Phase | Effort |
|---|---|
| C0 — Foundation | 1 |
| C1 — Sensing | 1 |
| C2 — Timeline + ApexCharts card | 2 |
| C3 — Control loops | 3 |
| C4 — Coordinator integration | 1 |
| C5 — Custom Lovelace card | 4-5 |
| Tests + docs | 2 |
| **Total without C5** | **10** |
| **Total with C5** | **14-15** |

Consider doing this in parallel with finishing RootSense Phases 3-5
since the architectural work is shared.
