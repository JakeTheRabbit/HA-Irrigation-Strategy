# Testing

This repo ships an automated test suite plus a manual checklist for the live system. CI
runs the automated suite on every push and pull request
(`.github/workflows/ci-validate.yml`); you can run the same thing locally before pushing.

## Prerequisites

- **Python 3.11+**
- One-off: `pip install ruff==0.5.5 black==24.4.2 yamllint==1.35.1 pytest`

The integration is dependency-free and the pure engine has no third-party deps, so the
tests need nothing else. (The add-on container's own runtime dep, `requests`, is stubbed
in the state test so it runs offline.)

## How to run

From the repo root:

```bash
bash tests/run_ci.sh
```

That mirrors CI: lint + format + yaml and both pytest suites. Run the pieces individually
if you prefer:

```bash
# Pure decision engine — the active control core
PYTHONPATH=crop-steering-engine/src python -m pytest crop-steering-engine/tests -q

# Integration helpers + add-on state migration + version consistency
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -q
```

## What it tests

### 1. Pure decision core — `crop-steering-engine/tests/test_core.py`
The `decide()` function with no HA and no I/O: phase transitions (P0→P1→P2→P3), the
anti-lockout high-EC flush, the sensor-independent minimum-daily-water floor, EC steering,
and `validate_params()` clamping. This is the bug class that has actually bitten the grow,
testable offline.

### 2. Integration calculation helpers — `tests/test_calculations.py`
The pure helpers in `custom_components/crop_steering/calculations.py` (no hardware needed;
input_boolean/number simulate pumps/sensors).

### 3. In-place upgrade / state migration — `tests/test_state_migration.py`
**Why it matters:** the add-on persists per-zone runtime state to `/data/state.json` and is
live-installed on many boxes. A version bump must load an **older** state file transparently.
These tests lock that contract: a missing file, corrupt JSON, missing keys, an unknown
legacy key, a bad timestamp, and a zone absent from the file must all be tolerated — new
fields fall back to fresh defaults, never an error, never a wipe. Plus a save→load
round-trip.

### 4. Version consistency — `tests/test_version_consistency.py`
The integration version must match across `manifest.json`, the latest released `CHANGELOG.md`
heading, and the README badge, so a release can't ship a stale number. (The f2-control
add-on has its own version line in `addons/f2_control/config.yaml`, synced to the dedicated
add-on repo by `scripts/publish_addon.sh`.)

### 5. Lint / format / YAML — ruff, black (scoped to `custom_components/` + `tests/`), yamllint
Plus, on GitHub only: **hassfest** and **HACS validation** of the integration.

## Manual verification checklist (live Home Assistant)

The automated suite can't drive real hardware. Before trusting a change on the grow:

- [ ] **Dry run.** With the kill switch `input_boolean.f2_control_enabled` **OFF**, start the
      add-on and watch a photoperiod in the log — it decides but **no valve opens**.
- [ ] **Shot length is real.** Verify a fired shot's duration from the live pump history
      (`switch.<pump>` `/api/history/period`), not from "deployed" — a file copy proves
      nothing about the running container.
- [ ] **State persists.** Confirm `/data/state.json` survives an add-on **restart** (phase
      and daily counters carry over).
- [ ] **Upgrade in place.** After a version **Update / Rebuild**, the engine resumes from the
      existing `state.json` with no re-setup and no wiped counters.
- [ ] **Feed-gate hold.** Out-of-range feed pH/EC (or a tank fill/dose) blocks watering and
      alerts — that is correct behavior, not a bug.

## A change isn't done until

The relevant automated tests pass **and** any change to persisted state, add-on options, or
integration entities has a test proving an **older install still loads** (see §4). New
behavior gets a new test. See `CLAUDE.md` → *Compatibility & data* for the rules these tests
enforce.
