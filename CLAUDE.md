# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## What this is

An autonomous **4-phase crop-steering irrigation** system for Home Assistant. Two
runtime layers plus the React/shadcn operator workspace:

1. **HA integration** (`custom_components/crop_steering/`) — entities, config-flow
   wizard, pure calculations, service events. Never touches hardware.
2. **f2-control add-on** (`addons/f2_control/`) — the live autonomous coordinator.
   A single synchronous Python process that polls HA over REST every 60 s, imports
   the pure `crop-steering-engine` package, runs the per-zone P0→P1→P2→P3 logic,
   and drives the hardware. Gated by kill switch
   `input_boolean.f2_control_enabled` (OFF = safe, no actuation).

The native UI source is frontend/src. Setup and strategy APIs persist revisioned data; active plans override canonical targets atomically at a local lights-on boundary. See docs/REPOSITORY_MAP.md and docs/GROW_PLANS.md.

> Start with `docs/SYSTEM_OVERVIEW.md` for the whole-stack mental model, then
> `README.md`. `docs/ENTITIES.md` is the entity reference.

## Dev commands

```bash
# Lint / format / yaml (matches CI; black is scoped — the add-on is
# deployed file-for-file to the live box and stays exempt from reformatting)
ruff check . && black --check custom_components/ tests/ && yamllint .

# Tests — integration calculation helpers (lean: hand-written HA stubs, no Home Assistant)
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -v

# Tests — the integration inside a REAL Home Assistant: fresh install, that install handed to
# the real add-on controller, and in-place upgrades from seeded snapshots of old installs.
# Needs `pip install -r requirements-test-ha.txt` (Python 3.13+); see docs/TESTING.md.
python -m pytest tests_ha -q

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
  no external runtime dependency.
- Responsibilities: phase transitions, hardware sequencing, dryback detection,
  source-water gate (pH + EC, fail-closed on dead probe), fail-closed hardware writes
  (aborts shot on valve/pump fault), P2 EC-correction min-interval (anti-short-cycle),
  optional PID EC loop (`input_boolean.crop_steering_ec_pid_enabled`), daily caps,
  sensor-fusion republish, 30-min operator vitals.
- Shot volume is substrate litres per plant x plants x shot fraction. Duration is shot litres divided by total flow L/s (plants x drippers/plant x L/h/dripper / 3600), followed by the explicit safety cap. Validate positive flow without a hidden clamp.
- Add-on config: `addons/f2_control/config.yaml`. Options set via Supervisor UI.

### Critical files
- `custom_components/crop_steering/config_flow.py` — setup wizard.
- `custom_components/crop_steering/{sensor,number,switch,select}.py` — entity platforms.
- `custom_components/crop_steering/calculations.py` — pure helpers (tested).
- `custom_components/crop_steering/const.py` — constants, single source of truth.
- `addons/f2_control/f2_control/controller.py` — live engine IO shell (read → decide → drive).
- `crop-steering-engine/src/crop_steering_engine/core.py` — pure `decide()` core imported by the add-on.

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
- **Dryback semantics:** controller dryback_target is a relative percent of detected peak: (peak - VWC) / peak * 100. At 60% peak and 10% target, the reference is 54% VWC. Rate calculations use VWC percentage points/hour; convert units explicitly.

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
- **Testing:** see `docs/TESTING.md`; run `bash tests/run_ci.sh` (mirrors CI). Anything that touches the
  config flow, entity ids/platforms or the integration-controller contract must be proven in `tests_ha/`
  (a real Home Assistant), not only against the stubs in `tests/`: the stubs cannot see a schema HA
  rejects, an HA API missing from an older version, or an entity id HA assigns, and all three have
  shipped. In `tests_ha/` stand in only for what a test genuinely cannot have (the web server), never
  for the code under test. An in-place-upgrade claim needs a seeded snapshot in `tests_ha/fixtures/`.
  Suites: the pure
  `decide()` core (`crop-steering-engine/tests`), the lean harness, integration calc helpers
  (`tests/test_calculations.py`), the add-on **state-migration / in-place-upgrade** contract
  (`tests/test_state_migration.py`), and **version consistency** (`tests/test_version_consistency.py`).
  Any change to persisted state, add-on options, or entities needs a test proving an OLD install still loads.
- **Branches and pull requests:** follow `CONTRIBUTING.md`. **One change, one branch, one pull
  request, into `testing`.** `main` is what production rooms run: never open a pull request into
  it, never push to it, never push to `testing`, never merge a pull request, never promote a
  release. Those are a person's decisions. Do not bundle unrelated fixes, do not reformat what
  you did not change, and do not change a version number outside a `release/x.y.z` branch. A
  feature that crosses layers is built as one commit per layer. Generated files (the dashboard
  bundle, the vendored engine copy) change only together with their source; CI proves they match.
- **Releasing:** follow `docs/RELEASING.md`. The controller is built on each box from the git
  branch that box tracks, and a box installed from the plain repository address tracks `main`
  for life, so for the part that drives the pump **a push that changes `version:` on `main` IS a
  release to production**. Candidates are cut as pre-releases from `testing`, soak on a staging
  room on real plumbing, and only then is `main` fast-forwarded to that exact commit. A version
  number is never reused for different code, and from 2.21.0 the integration and the controller
  app carry one number (`manifest.json`, `const.py` and the app's `config.yaml` move together).
  The **Promote** workflow must be dispatched from `main`; default to its read-only dry run. The
  local equivalent is
  `python .github/scripts/promotion.py --repo <owner>/HA-Irrigation-Strategy --tag vX.Y.Z`.
  It requires exact-candidate `Validate` success, `testing` still at the tag, fast-forward
  ancestry and version-specific approved audit assets. Do not infer readiness or promotion
  authorization from CI or a rehearsal. The writing job uses trusted `main` code and rechecks
  all gates before advancing `main`, then flips the matching pre-release. If that flip fails,
  report that `main` already advanced and retry through the workflow; never rewind production.
- **Deploying changes:** publish a versioned integration release and matching controller
  app release. The controller app is installed only from this repository
  (`addons/f2_control`); the old `JakeTheRabbit/f2-control` mirror is retired and gets
  nothing. Existing app installations update in place to preserve their Supervisor
  identity and `/data`; one still installed from the mirror moves once, carrying
  `/data/state.json` and its options (`docs/INSTALL.md`). A plain restart
  does not change a baked controller image. Use Supervisor Update for a published
  release (or Rebuild for local source), then verify the running image and modules.
  Restart HA after integration updates; see `docs/INSTALL.md` for the current path.
- **Commit style:** conventional commits (`feat:`/`fix:`/`docs:`/`chore:`) with a
  `Co-Authored-By: Claude` trailer when written via Claude Code. Two long-lived branches:
  `main` (production) and `testing` (staging); everything else is a short-lived proposal.
  Retired branches are kept as `archive/*` tags.
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
in `docs/TESTING.md`. A change to state/options/entities isn't done until a test shows an old
install still loads.

## Operational verification

- Preserve current live setpoints, mapping, enable flags, app options and persistent
  controller state before updating. Historical facility examples are not live truth.
- Verify installed versions, running module hashes, integration entry state,
  controller heartbeat, and restored settings after activation. A copied file or
  successful restart alone does not prove a software update.
- Verify physical delivery separately. Pump or valve ON history shows an electrical
  state; only independent flow measurement or a catch test proves delivered water.
- Shot sizing uses both zone-total substrate and zone-total dripper flow, derived
  from per-plant pot size, plant count and drippers. Keep the units explicit.

> **Historical note.** An earlier experimental "intelligence" layer (RootSense
> substrate AI + ClimateSense climate control, under `intelligence/`) was never
> deployed and was retired from `main` to keep the repo matched to what actually
> runs. It is recoverable from the `archive/pre-doc-cleanup-2026-06` tag. A few inert
> `…_intelligence_*_enabled` entities still exist in the integration; the engine
> ignores them.
