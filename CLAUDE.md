# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## What this is

An autonomous **4-phase crop-steering irrigation** system for Home Assistant. Two
layers:

1. **HA integration** (`custom_components/crop_steering/`) — entities, config-flow
   wizard, pure calculations, service events. Never touches hardware.
2. **f2-control add-on** (`addons/f2_control/`) — the live autonomous coordinator.
   A single synchronous Python process that polls HA over REST every 60 s, imports
   the pure `crop-steering-engine` package, runs the per-zone P0→P1→P2→P3 logic,
   and drives the hardware. Gated by kill switch
   `input_boolean.f2_control_enabled` (OFF = safe, no actuation).

AppDaemon (`appdaemon/apps/crop_steering/`) is **retired** — kept only as a manual
rollback. `master_crop_steering_app.py` is not deployed. Do not add features there.

> Start with `docs/SYSTEM_OVERVIEW.md` for the whole-stack mental model, then
> `README.md`. `ENTITIES.md` is the entity reference.

## Dev commands

```bash
# Lint / format / yaml (matches CI; black is scoped — the add-on is
# deployed file-for-file to the live box and stays exempt from reformatting)
ruff check . && black --check custom_components/ tests/ && yamllint .

# Tests — integration calculation helpers
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -v

# Tests — crop-steering-engine package
PYTHONPATH=crop-steering-engine/src python -m pytest crop-steering-engine/tests -q

# f2-control add-on logs (supervised HA)
#   ha addons logs <f2_control_slug>     (or: docker logs addon_<slug> -f)
```

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` dodges a broken hydra/omegaconf plugin in some
local Python installs. CI is unaffected.

## Architecture

### 1. HA integration — `custom_components/crop_steering/`
- ~100 entities (numbers, switches, selects, sensors) via a config-flow UI; no YAML.
- Services: `transition_phase`, `execute_irrigation_shot`, `check_transition_conditions`, `set_manual_override`.
- Pure, testable helpers in `calculations.py`.

### 2. f2-control add-on — `addons/f2_control/` (live engine)
- Single synchronous Python process; polls HA REST API every 60 s.
- Imports `crop-steering-engine` (pure Python package at `crop-steering-engine/src/`);
  no AppDaemon dependency.
- Responsibilities: phase transitions, hardware sequencing, dryback detection,
  source-water gate (pH + EC, fail-closed on dead probe), fail-closed hardware writes
  (aborts shot on valve/pump fault), P2 EC-correction min-interval (anti-short-cycle),
  optional PID EC loop (`input_boolean.crop_steering_ec_pid_enabled`), daily caps,
  sensor-fusion republish, 30-min operator vitals.
- Shot duration computed live: `substrate_volume × shot_fraction ÷ (plant_count ×
  drippers_per_plant × dripper_flow_rate)` — substrate/flow config must be accurate.
- Add-on config: `addons/f2_control/config.yaml`. Options set via Supervisor UI.

### 3. AppDaemon — `appdaemon/apps/crop_steering/` (retired rollback)
- `master_crop_steering_app.py` and its supporting libs are **not deployed**.
- Kept for emergency manual rollback only. Do not add features here.

### Critical files
- `custom_components/crop_steering/config_flow.py` — setup wizard.
- `custom_components/crop_steering/{sensor,number,switch,select}.py` — entity platforms.
- `custom_components/crop_steering/calculations.py` — pure helpers (tested).
- `custom_components/crop_steering/const.py` — constants, single source of truth.
- `addons/f2_control/` — live engine (add-on root).
- `crop-steering-engine/src/` — pure engine package imported by the add-on.
- `appdaemon/apps/crop_steering/master_crop_steering_app.py` — retired; rollback only.

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

Valve close is read-back verified; failure triggers an emergency pump stop and aborts
the shot. Lives in the f2-control add-on (`addons/f2_control/`).

## Key entity patterns

- Global: `crop_steering_<param>` (e.g. `number.crop_steering_p2_shot_size`).
- Per-zone: `crop_steering_zone_X_<param>`.
- Sensors: `sensor.crop_steering_<metric>`; services: `crop_steering.<action>`.
- Per-zone manual phase pin: `input_select.crop_steering_zone_X_phase_control` (Auto / P0–P3).
- The engine reads switches/numbers by `entity_id` — renaming a friendly-name in HA
  or the dashboard does not affect it.

## Notes

- **Dependencies:** integration = pure HA + voluptuous (no external deps). Engine
  (`crop-steering-engine`) = pure Python, no scipy/numpy; f2-control add-on container
  installs its own deps from `addons/f2_control/requirements.txt`.
- **Testing:** `tests/test_calculations.py` covers the integration calc helpers; no
  real hardware needed (input_boolean/number simulate pumps/sensors).
- **Deploying engine changes:** copy changed modules to `addons/f2_control/` on the
  live box and restart the f2-control add-on from Supervisor (clean restart is more
  predictable than file-watch). Integration changes: Developer Tools → YAML → Reload
  Custom Components. For `crop-steering-engine` package changes, update the package
  source and restart the add-on.
- **Commit style:** conventional commits (`feat:`/`fix:`/`docs:`/`chore:`) with a
  `Co-Authored-By: Claude` trailer when written via Claude Code. One active branch:
  `main`. Retired branches are kept as `archive/*` tags.

> **Historical note.** An earlier experimental "intelligence" layer (RootSense
> substrate AI + ClimateSense climate control, under `intelligence/`) was never
> deployed and was retired from `main` to keep the repo matched to what actually
> runs. It is recoverable from the `archive/pre-doc-cleanup-2026-06` tag. A few inert
> `…_intelligence_*_enabled` entities still exist in the integration; the engine
> ignores them.
