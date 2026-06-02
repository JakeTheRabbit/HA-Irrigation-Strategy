# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## What this is

An autonomous **4-phase crop-steering irrigation** system for Home Assistant. Two
layers:

1. **HA integration** (`custom_components/crop_steering/`) — entities, config-flow
   wizard, pure calculations, service events. Never touches hardware.
2. **AppDaemon engine** (`appdaemon/apps/crop_steering/`) — the autonomous
   coordinator that reads entities, runs the per-zone P0→P1→P2→P3 logic, and drives
   the hardware.

There is **one engine**: `master_crop_steering_app.py` (+ its supporting libs). It
does irrigation only — no climate control.

> Start with `docs/SYSTEM_OVERVIEW.md` for the whole-stack mental model, then
> `README.md`. `ENTITIES.md` is the entity reference.

## Dev commands

```bash
# Lint / format / yaml
ruff check . && black --check . && yamllint -s .

# Tests (integration calculation helpers)
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -v

# AppDaemon logs (supervised HA)
#   ha addons logs a0d7b954_appdaemon     (or: docker logs addon_a0d7b954_appdaemon -f)
```

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` dodges a broken hydra/omegaconf plugin in some
local Python installs. CI is unaffected.

## Architecture

### 1. HA integration — `custom_components/crop_steering/`
- ~100 entities (numbers, switches, selects, sensors) via a config-flow UI; no YAML.
- Services: `transition_phase`, `execute_irrigation_shot`, `check_transition_conditions`, `set_manual_override`.
- Pure, testable helpers in `calculations.py`.

### 2. AppDaemon engine — `appdaemon/apps/crop_steering/`
- `master_crop_steering_app.py` — the coordinator. Phase transitions, hardware
  sequencing, dryback detection, sensor fusion, source-water gating, daily caps,
  emergency rescue, drain-through detection, the autonomous EC-stacking loop
  (`_ec_stack_dryback`, gated by `switch.crop_steering_ec_stacking_enabled`), the
  `_ai_heartbeat` self-correction loop, the `_watchdog_check` hardware watchdog, and the
  activity feed
  (`sensor.crop_steering_activity_log`).
- Supporting libs it imports: `phase_state_machine.py`, `advanced_dryback_detection.py`,
  `intelligent_sensor_fusion.py`, `intelligent_crop_profiles.py`,
  `ml_irrigation_predictor.py`, `base_async_app.py`.
- `apps.yaml` declares the app and holds the per-site hardware + sensor map.

### Critical files
- `custom_components/crop_steering/config_flow.py` — setup wizard.
- `custom_components/crop_steering/{sensor,number,switch,select}.py` — entity platforms.
- `custom_components/crop_steering/calculations.py` — pure helpers (tested).
- `custom_components/crop_steering/const.py` — constants, single source of truth.
- `appdaemon/apps/crop_steering/master_crop_steering_app.py` — the engine.
- `appdaemon/apps/apps.yaml` — app declaration + hardware/sensor map.

## Phase logic (P0–P3)

```
P0 (Morning dryback): after lights-on, wait for an X% VWC DROP FROM PEAK → P1
P1 (Ramp-up):         progressive shots to the per-zone target → P2
P2 (Maintenance):     top-up when VWC drops below the per-zone threshold → P3
P3 (Pre-lights-off):  emergency-only; dry back overnight → P0 at lights-on
```

- A "grow-day" is one **photoperiod**. The daily water + shot counters reset at the
  **P3→P0 transition (lights-on)**, not at calendar midnight.
- Lights-off forces any P1/P2 zone to P3 (no zone strands mid-cycle overnight).
- **Dryback semantics:** every "dryback" value is a *% point drop from peak VWC*
  (dries-back-by, never dries-back-to).

## Hardware control sequence

```
Safety checks → Pump prime (2s) → Mainline (1s) → Zone valve → Irrigate → Shutdown (reverse)
```

Valve close is read-back verified; failure triggers an emergency pump stop. Lives
entirely in `master_crop_steering_app.py`.

## Key entity patterns

- Global: `crop_steering_<param>` (e.g. `number.crop_steering_p2_shot_size`).
- Per-zone: `crop_steering_zone_X_<param>`.
- Sensors: `sensor.crop_steering_<metric>`; services: `crop_steering.<action>`.
- Per-zone manual phase pin: `input_select.crop_steering_zone_X_phase_control` (Auto / P0–P3).
- The engine reads switches/numbers by `entity_id` — renaming a friendly-name in HA
  or the dashboard does not affect it.

## Notes

- **Dependencies:** integration = pure HA + voluptuous (no external deps). Engine =
  scipy + numpy (already in the AppDaemon container).
- **Testing:** `tests/test_calculations.py` covers the integration calc helpers; no
  real hardware needed (input_boolean/number simulate pumps/sensors).
- **Deploying engine changes:** copy the changed module(s) to the AppDaemon apps dir
  and restart AppDaemon (the add-on watches files, but a clean restart is more
  predictable). Integration changes: Developer Tools → YAML → Reload Custom Components.
- **Commit style:** conventional commits (`feat:`/`fix:`/`docs:`/`chore:`) with a
  `Co-Authored-By: Claude` trailer when written via Claude Code. One active branch:
  `main`. Retired branches are kept as `archive/*` tags.

> **Historical note.** An earlier experimental "intelligence" layer (RootSense
> substrate AI + ClimateSense climate control, under `intelligence/`) was never
> deployed and was retired from `main` to keep the repo matched to what actually
> runs. It is recoverable from the `archive/pre-doc-cleanup-2026-06` tag. A few inert
> `…_intelligence_*_enabled` entities still exist in the integration; the engine
> ignores them.
