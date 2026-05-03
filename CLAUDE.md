# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## System Overview

Advanced Crop Steering System for Home Assistant. Currently shipping
`v2.3.1` of the rule-based 4-phase controller, with `[Unreleased] - 3.0.0-dev
"RootSense"` work landed on `main`. RootSense layers a four-pillar adaptive
intelligence platform on top of the existing controller — every pillar is
opt-in via a switch, default OFF, so existing v2.x installs are unaffected on
upgrade.

**Read this first:**
- `docs/SYSTEM_OVERVIEW.md` — the unified mental model of the whole stack.
- `docs/upgrade/ROOTSENSE_v3_PLAN.md` — substrate intelligence design.
- `docs/upgrade/CLIMATESENSE_PLAN.md` — environmental control design.
- `docs/upgrade/RECONCILIATION.md` — maps gap-analysis items onto plan phases.
- `docs/upgrade/LLM_ADVISOR_NOTES.md` — salvage notes from the archived
  `llm-integration` branch (now reachable via tag `archive/llm-integration-v0.1`).
- `MIGRATION.md` — operator-facing v2.3.x → v3.0 upgrade guide.

## Development Commands

### Linting & Validation
```bash
ruff check .
black --check .
yamllint -s .
# Full CI validation:
ruff check . && black --check . && yamllint -s .
```

### Testing
```bash
# Integration calculations (28 tests):
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_calculations.py -v

# RootSense intelligence pillars (39 tests):
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/intelligence/ -v

# Full suite:
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -v
```

The `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` env var dodges a broken
hydra/omegaconf plugin in some local Python installs. CI is unaffected.

### Home Assistant runtime
```bash
# Reload integration without restart (after code changes):
# Developer Tools → YAML → Reload Custom Components

# Monitor events (Developer Tools → Events → Listen):
# Existing v2.x events:
#   crop_steering_phase_transition
#   crop_steering_irrigation_shot
#   crop_steering_transition_check
#   crop_steering_manual_override
# RootSense v3 events:
#   crop_steering_custom_shot
#   crop_steering_dryback_complete
#   crop_steering_field_capacity_observed
#   crop_steering_anomaly
#   crop_steering_run_report

# View AppDaemon logs:
docker logs addon_a0d7b954_appdaemon -f
```

## Architecture

### Three-Layer System Design

1. **Home Assistant Integration** (`custom_components/crop_steering/`)
   - Provides 100+ entities (sensors, numbers, switches, selects).
   - Config flow UI for setup; no YAML editing required.
   - Services: `transition_phase`, `execute_irrigation_shot`,
     `check_transition_conditions`, `set_manual_override`,
     `custom_shot` (RootSense v3).
   - Pure helpers split out into `calculations.py` for testability.

2. **AppDaemon — legacy controller** (`appdaemon/apps/crop_steering/`)
   - `master_crop_steering_app.py` — the original autonomous coordinator.
     Phase transitions, hardware sequencing, dryback detection, sensor fusion.
     Untouched in the v3 work.
   - `phase_state_machine.py`, `advanced_dryback_detection.py`,
     `intelligent_sensor_fusion.py`, `intelligent_crop_profiles.py`,
     `ml_irrigation_predictor.py` — supporting libraries the master app uses.

3. **AppDaemon — RootSense v3 intelligence pillars**
   (`appdaemon/apps/crop_steering/intelligence/`)
   - `base.py` — `IntelligenceApp` mixin with module-enable gating + helpers.
   - `bus.py` — in-process pub/sub (`RootSenseBus`).
   - `store.py` — SQLite analytics store at
     `appdaemon/apps/crop_steering/state/rootsense.db`.
   - `root_zone.py` — Pillar 1: substrate analytics, FC detection, dryback
     episode tracker.
   - `adaptive_irrigation.py` — Pillar 2: intent slider, profile interpolation,
     bandit shot-size optimisation.
   - `agronomic.py` — Pillar 3: Penman-Monteith transpiration, VPD ceiling,
     nightly run reports.
   - `orchestration.py` — Pillar 4: `crop_steering.custom_shot` event handler,
     emergency rescue, EC flush.
   - `anomaly.py` — cross-cutting scanner (emitter blockage, EC drift, sensor
     flat-line, peer-group VWC deviation).

Each pillar gates itself behind its `switch.crop_steering_intelligence_*_enabled`
entity. Default OFF.

### Critical Files
- `custom_components/crop_steering/config_flow.py` — integration setup wizard.
- `custom_components/crop_steering/sensor.py` — calculated sensor entities.
- `custom_components/crop_steering/calculations.py` — pure helpers (testable).
- `custom_components/crop_steering/services.py` — service handlers + event firing.
- `custom_components/crop_steering/const.py` — constants, single source of truth.
- `custom_components/crop_steering/number.py` — number entities including
  RootSense intent slider and dryback drop sliders.
- `custom_components/crop_steering/switch.py` — switches including the 5
  RootSense module-enable switches.
- `appdaemon/apps/crop_steering/master_crop_steering_app.py` — legacy coordinator.
- `appdaemon/apps/crop_steering/intelligence/*.py` — RootSense pillars.
- `appdaemon/apps/apps.yaml` — AppDaemon app declarations.
- `docs/upgrade/apps.example.yaml` — example apps.yaml additions for opting into
  the RootSense pillars.
- `packages/rootsense/00_recorder.yaml` — HA recorder includes for RootSense sensors.
- `dashboards/rootsense_history.yaml` — three-tab Lovelace dashboard.

## Phase Logic (P0-P3 Cycle)

```
P0 (Morning Dryback): Wait for X% VWC DROP FROM PEAK → transition to P1
P1 (Ramp-Up): Progressive shots until target VWC → transition to P2
P2 (Maintenance): Threshold-based irrigation triggered by VWC or EC ratio
P3 (Pre-Lights-Off): Emergency-only irrigation, prepare for night
```

> **Dryback semantic** (RootSense v3 clarification): every "dryback" value
> in this codebase is a *percentage-point drop from peak VWC* — i.e. how
> much the substrate dries back **by**, never what VWC value it dries back
> **to**. Two operator-facing sliders feed the IntentResolver:
> `number.crop_steering_veg_p0_dryback_drop_pct` (default 12) and
> `..._gen_p0_dryback_drop_pct` (default 22). Defaults reflect Athena
> guidance.

## Hardware Control Sequence

```
Safety checks → Pump prime (2s) → Main line (1s) → Zone valve → Irrigate → Shutdown
```

Lives in `master_crop_steering_app.py`. RootSense pillars never touch hardware
directly — they propose shots via the `crop_steering.custom_shot` service,
which fires an event that `IrrigationOrchestrator` picks up, gates, and
forwards to `crop_steering.execute_irrigation_shot`.

## Sensor Processing

- **VWC/EC Averaging**: front/back sensor pairs per zone.
- **Outlier Detection**: IQR method (Q3 + 1.5*IQR) — currently bypassed in
  legacy code.
- **Dryback Detection (legacy)**: `scipy.signal.find_peaks` in
  `master_crop_steering_app`.
- **Dryback Detection (RootSense)**: a self-contained `DrybackTracker` state
  machine in `root_zone.py` that uses the rolling per-zone VWC buffer. Tested
  in `tests/intelligence/test_dryback_tracker.py`.
- **EC Ratio**: current EC ÷ target EC drives threshold adjustments.
- **Substrate Porosity Estimate (RootSense)**: `mL water / %VWC` — derived
  from rolling shot responses in the SQLite store.
- **EC Stack Index (RootSense)**: cumulative positive EC drift over a
  6-hour window.

## Key Entity Patterns

- Global: `crop_steering_<parameter>` (e.g. `crop_steering_p2_shot_size`).
- Per-zone: `crop_steering_zone_X_<parameter>`.
- Sensors: `sensor.crop_steering_<metric>`.
- Services: `crop_steering.<action>`.
- RootSense intent: `number.crop_steering_steering_intent` (-100..+100, step 5).
- RootSense module enables: `switch.crop_steering_intelligence_<pillar>_enabled`.

## Important Notes

### Dependencies
- **Integration**: zero external Python dependencies. Pure HA + voluptuous.
- **AppDaemon legacy modules**: scipy, numpy (already in AppDaemon container).
- **AppDaemon RootSense modules**: stdlib + numpy. SQLite via stdlib.
- **Home Assistant**: 2024.3.0+ required.

### Testing Approach
- Integration creates test helper entities automatically.
- Input_boolean simulates hardware (pumps, valves).
- Input_number simulates sensors (VWC, EC, temp).
- No real hardware required for development/testing.
- Tests in `tests/`:
  - `test_calculations.py` — integration calc helpers (28 tests).
  - `tests/intelligence/` — RootSense pillars (39 tests across 5 files).
- The `_appdaemon_stub.py` module installs a fake `appdaemon.plugins.hass.hassapi`
  so RootSense modules import cleanly without an AppDaemon runtime.

### Event-Driven Communication
- Integration fires events → AppDaemon listens → triggers automation.
- RootSense pillars communicate among themselves via `RootSenseBus` (in-process)
  to keep large payloads (full episodes, posteriors) off the HA event bus.
- HA still receives high-signal events: anomalies, run reports, custom shots.
- Hardware control happens in AppDaemon (legacy app), not in the integration.

### Development Workflow
1. Edit files in `custom_components/crop_steering/` or
   `appdaemon/apps/crop_steering/`.
2. **Integration changes**: Developer Tools → YAML → Reload Custom Components.
3. **AppDaemon changes**: restart AppDaemon (the add-on watches files but a
   clean restart is more predictable).
4. Test with manual service calls: Developer Tools → Services.
5. Monitor events: Developer Tools → Events → Listen to `crop_steering_*`.
6. Run unit tests with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/`.

### Common Development Tasks
- **Add new entity**: edit the relevant platform file (sensor.py, number.py,
  etc.), update `const.py` if needed.
- **Modify service**: edit `services.py`, update event payload if needed.
- **Change RootSense logic**: edit the relevant `intelligence/` module, restart
  AppDaemon. Add a unit test before touching production behaviour.
- **Update version**: edit `SOFTWARE_VERSION` in `const.py` and `manifest.json`
  (single source is `const.py`). Bump to `3.0.0` only when Phase 5 closes.

### Repo conventions
- Commit messages use conventional commits (`feat:`, `fix:`, `docs:`,
  `test:`) with a `Co-Authored-By: Claude` trailer when written via Claude Code.
- Branches that are merged via PR get deleted on origin to keep the branch list
  clean. Long-running exploration branches get archived as `archive/<name>-vX.Y`
  tags before deletion.
- Active branches: just `main`. The `feat/intelligent-crop-steering` branch was
  merged via PR #7 and deleted; the `llm-integration` branch was archived as
  tag `archive/llm-integration-v0.1`.
