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
- **Testing:** see `TESTING.md`; run `bash tests/run_ci.sh` (mirrors CI). Suites: the pure
  `decide()` core (`crop-steering-engine/tests`), the lean harness, integration calc helpers
  (`tests/test_calculations.py`), the add-on **state-migration / in-place-upgrade** contract
  (`tests/test_state_migration.py`), and **version consistency** (`tests/test_version_consistency.py`).
  Any change to persisted state, add-on options, or entities needs a test proving an OLD install still loads.
- **Deploying engine changes:** copy changed modules to `addons/f2_control/` on the
  live box, then **Rebuild** the add-on from Supervisor (⋮ → Rebuild) — the Dockerfile
  `COPY f2_control /app` bakes the code into the image at build time, so a plain
  **restart reuses the old image and does NOT pick up code changes** (it only re-reads
  the config.yaml options). Rebuild = re-COPY + restart. (Interim without a rebuild:
  the running build's shot sizing reads the add-on Configuration options `substrate_l`/
  `flow_lps`, so editing those + Save corrects shot length on the old image.) Integration
  changes: Developer Tools → YAML → Reload Custom Components. For `crop-steering-engine`
  package changes, update the package source and Rebuild the add-on.
- **Commit style:** conventional commits (`feat:`/`fix:`/`docs:`/`chore:`) with a
  `Co-Authored-By: Claude` trailer when written via Claude Code. One active branch:
  `main`. Retired branches are kept as `archive/*` tags.
- **Changelog = dual view.** Every release in `CHANGELOG.md` leads with **🌱 In plain English** (anyone
  can follow it) then **🔧 Technical notes** (entity/code detail). Keep both when adding a release.

## Compatibility & data — never break a live install

This system is live-installed on many boxes, old and new. Every change must upgrade them
**transparently in place** AND work **zero-setup** on a fresh install. Do not tailor a change
to one facility and break others.

**State & storage.** The add-on persists per-zone runtime state to **`/data/state.json`**
(HA-managed, **non-ephemeral** — survives restart and Rebuild): phase, peak VWC, shot/daily
counters, EC offset/integral, timestamps. Writes are atomic (`tmp` + `os.replace`).
`/data/options.json` holds the user's add-on config (HA-managed). The engine keeps **no
database** and writes nothing outside `/data`; the integration stores its config in the HA
config entry. There is no schema to migrate by hand.

**In-place upgrade (mandatory).**
- `Controller._load_state` already tolerates a missing file, corrupt JSON, missing keys,
  unknown legacy keys, bad timestamps, and zones absent from the file (they seed fresh).
  **Keep it that way.** Adding a state field → add it to `_fresh_zone` with a safe default and
  read it with `.get(k)` / `is not None`; never assume it exists in an old file.
- Adding an add-on option → give it a neutral default and read it `o.get("key", default)` so an
  old `options.json` without the key still works. Never require the operator to wipe state,
  re-run setup, reconfigure, or hand-migrate a schema.
- Integration entity changes → additive. Renaming/removing an entity an old install relies on
  is breaking; avoid or migrate.

**Fresh install (mandatory).** Works with no extra layers — no manual DB/schema step, no
required post-install migration. Defaults sane out of the box.

**Stay generic.** F2-specific values are **defaults/overrides, never hardcoded assumptions**:
entity ids (`switch.veg_main_pump`, `sensor.atlas_legacy_1_ec`, …), 36 plants, 6 L block,
4 L/hr, lights 10–22, feed band EC 2.3–3.5 / pH 5.8–6.2. A change that only works because of
F2's exact names or numbers is a bug. (**Resolved in add-on v0.8.0:** `feed_ec_sensor` /
`feed_ph_sensor` are now optional add-on options with **empty** defaults — unset = that half
of the source-water gate is disabled (dosing/fill holds still apply), never a fallback to an
F2 entity id; `substrate_l` / `flow_lps` defaults are now generic last-resort placeholders
(5 L / 0.02 L/s). **F2 must set `feed_ec_sensor: sensor.atlas_legacy_1_ec` and
`feed_ph_sensor: sensor.aquaponics_kit_f4f618_ph` in its add-on Configuration** or its
source-water gate goes dark after the v0.8.0 rebuild.)

**Prove it.** `tests/test_state_migration.py` locks the backward-compatible load and
`tests/test_version_consistency.py` keeps versions aligned. Run `bash tests/run_ci.sh`; detail
in `TESTING.md`. A change to state/options/entities isn't done until a test shows an old
install still loads.

## Hard-won operational notes (read before touching the live F2 engine)

- **Deploy = Rebuild, never Restart.** A plain restart re-runs the *baked* image (stale code); only a
  **Rebuild** re-COPYs `addons/f2_control/`. There is **no API rebuild** with the HA long-lived token —
  `hassio.addon_rebuild` 400s and the Supervisor proxy 401s (needs the in-container `SUPERVISOR_TOKEN`).
  So: stage the files, then the operator must Rebuild in the UI. **Never claim an engine change is live
  off a restart.** (`hassio.addon_restart` *does* work for restarting; it just won't load new code.)
- **Verify shot length from the live pump, not from "deployed".** A shot's *duration* is the only proof a
  sizing change took — pull `switch.veg_main_pump` history (`/api/history/period`) and read the on-period
  seconds. File-copied + md5-matched proves nothing about the running container.
- **Shot sizing is per-plant, scaled to the row.** `dur = shot% × substrate_l ÷ flow_lps`. `flow_lps` is
  ZONE-total (`plant_count × drippers_per_plant × dripper_flow_rate ÷ 3600`), so `_substrate_l` must also
  be ZONE-total = per-plant block × `plant_count`. Enter `…zone_N_substrate_volume` as the **PER-PLANT
  block**; the engine multiplies by `plant_count`. Get the units wrong and shots are plant_count-times too
  short → the pump short-cycles (the recurring F2 failure). The old build also reads `substrate_l`/
  `flow_lps` from the add-on **Configuration options** — an interim way to correct sizing without a rebuild.
- **F2 facts:** 3 zones × 36 plants; 6 L block/plant; 1 dripper/plant @ 4 L/hr → zone flow 0.04 L/s, zone
  substrate 216 L, a 6 % shot ≈ 324 s. Lights 10:00–22:00. Feed gate EC 2.3–3.5 / pH 5.8–6.2 — the engine
  correctly holds while the tank is filling/dosing or feed is out of band (don't mistake that for a bug).

> **Historical note.** An earlier experimental "intelligence" layer (RootSense
> substrate AI + ClimateSense climate control, under `intelligence/`) was never
> deployed and was retired from `main` to keep the repo matched to what actually
> runs. It is recoverable from the `archive/pre-doc-cleanup-2026-06` tag. A few inert
> `…_intelligence_*_enabled` entities still exist in the integration; the engine
> ignores them.
