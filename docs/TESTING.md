# Testing

This repo ships an automated test suite plus a manual checklist for the live system. CI
runs the automated suite on pushes to main and pull requests targeting main
(`.github/workflows/ci-validate.yml`); you can run the same thing locally before pushing.

## Prerequisites

- **Python 3.11+**
- One-off: `pip install ruff==0.5.5 black==24.4.2 yamllint==1.35.1 pytest requests pyyaml`
- **Node.js 24** for the dashboard; `npm ci --prefix frontend` installs the pinned dependencies.

The integration and pure engine have no third-party runtime dependencies. Controller tests use a fake HA transport; no test needs production credentials or live hardware.

## How to run

From the repo root:

```bash
bash tests/run_ci.sh
```

That runs the backend checks: lint, format, YAML, vendored engine identity, repository hygiene and all three Python suites. Run the pieces individually
if you prefer:

```bash
# Pure decision engine — the active control core
PYTHONPATH=crop-steering-engine/src python -m pytest crop-steering-engine/tests -q

# Integration helpers + add-on state migration + version consistency
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -q

# Real add-on controller with fake HA and deterministic clocks
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest addons/f2_control/tests -q
```

## The real-Home-Assistant tier (`tests_ha/`)

The three suites above are fast because they never load Home Assistant: `tests/` drives the
integration against hand-written stubs in which voluptuous, the selectors and the config-flow
base class are no-ops. That has a cost. The stubs cannot see a schema Home Assistant rejects, a
Home Assistant API that does not exist in an older version, or an entity id Home Assistant
assigns, and each of those has shipped: a wizard that discarded every answer on its last screen,
entities registered as `sensor.engine_config` that the controller never looks for, and a sidebar
panel that raised `AttributeError` on every Home Assistant older than 2026.5 (the stub test
assigned the missing function onto its own stub).

`tests_ha/` loads the integration in an actual Home Assistant core
([pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component)):
real config entries, entity registry, restore state, schema validation and serialisation.

```bash
# Python 3.13+. A separate virtualenv keeps the lean prerequisites above lean.
pip install -r requirements-test-ha.txt
python -m pytest tests_ha -q          # NOT with PYTEST_DISABLE_PLUGIN_AUTOLOAD
```

`bash tests/run_ci.sh` runs it too when the package is installed (set `HA_PYTHON` to point at a
separate virtualenv) and says so when it is skipped. CI always runs it.

| File | Scenario |
| --- | --- |
| `test_real_flow.py` | **Fresh install.** The wizard through the real flow manager for a one-switch room; the registered id of every entity; an existing registry keeps its ids. |
| `test_setup_entry.py` | **The entry itself.** It loads on a Home Assistant without `frontend.async_panel_exists`; another owner's sidebar path is left alone; the wizard's lights hours and sizing reach the entities. |
| `test_install_to_controller.py` | **Fresh install, both layers.** That install is handed to the *real add-on controller*, which must find the room from the descriptor alone, adopt it, and fire a shot sized and scheduled from the wizard's answers. The only tests that cross the integration / controller seam. |
| `test_upgrade_in_place.py` | **In-place upgrade with seeded data.** Starts the new code on top of a snapshot of an old install. Nothing tuned may move, no entity may change id, and the controller must carry on with the kill switch ON and no disarm cycle. |
| `test_configure.py` | **Configure.** Editing a parameter reaches the engine; a mapping can be removed; an untouched save keeps every mapping. |

**Seeded fixtures** live in `tests_ha/fixtures/`. Each is a room *as an old version actually wrote
it*, with an `_about` note saying which era it models: its config entry, the states of its
devices, and the values its operator had tuned (with the attributes that version stored beside
them). To cover another kind of old install, add a snapshot there rather than hand-building one
in a test. `entry_2_17_wizard.json` is a pumped two-zone room from the 2.17 wizard;
`entry_env_era.json` is from the env-file era (legacy front/back probe pairs, no setup revision,
a probe with no unit, bookkeeping keys in `entry.options`).

**Only the web server is stood in for.** The manifest depends on `frontend` and `http` for the
sidebar panel; `conftest.py` marks both as set up and gives `hass.http` a mock, and the panel
registration then runs against the real frontend module. It used to be replaced with a no-op,
which is how the pre-2026.5 `AttributeError` got past this tier. Do not stub out more than the
thing a test genuinely cannot have.

`tests_ha/` is a separate directory on purpose: `tests/conftest.py` registers fake
`homeassistant` modules, which would shadow the real package.

### hassfest, without Docker

hassfest runs in CI as a container action. It is an ordinary Python module in the core
repository, so it can be run locally against the Home Assistant already installed for `tests_ha`:

```bash
git clone --depth 1 --filter=blob:none --sparse -b 2026.2.3 https://github.com/home-assistant/core ha-core
git -C ha-core sparse-checkout set script          # about 5 MB; match the tag to your installed HA
cd ha-core && python -m script.hassfest --action validate \
    --integration-path ../custom_components/crop_steering      # needs `ruff` on PATH
```

The translation rules most easily broken by a new form field or message are also pinned, with
hassfest's own patterns, in `tests/test_translations.py`, where a failure takes seconds: keys
(including a dropdown's option *values*) must be lowercase slugs; no placeholder inside single
quotes, because ICU MessageFormat treats `'{unit}'` as an escape and shows the literal text; and
a tooltip needs a label.

### Hermetic controller state

The controller persists to `/data/state.json`. Its constructor reads that file, and on adopting
a setup writes it, before a test can redirect it. GitHub runners have no `/data`; a devcontainer
or the add-on's own container does, and there the suites used to write a real file and leak it
into the next test. All three conftests now set `F2_STATE_PATH` per test. Unset, as on every
live install, the path is `/data/state.json`.

## Dashboard checks

From the repository root:

```sh
npm ci --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
# One-time browser installation (Windows scripts can also use installed Chrome):
cd frontend
npx playwright install chromium
cd ..
node frontend/scripts/verify-dashboard.mjs
node frontend/scripts/verify-live.mjs
node frontend/scripts/verify-workspace.mjs
node frontend/scripts/verify-steering-visuals.mjs
node frontend/scripts/verify-recipe-library.mjs
node frontend/scripts/verify-tank-status.mjs
node frontend/scripts/verify-ha-shell.mjs
```

The browser scripts start loopback servers. Demo workflows reject API/external traffic; mocked-HA workflows intercept all API calls. The checks cover all eleven pages, desktop/mobile navigation, accessibility, drafts, partial failures, readback, room identity, stale probes, and legacy route compatibility. Screenshots and JSON results are written to `output/playwright/`. This frontend job also runs in GitHub CI. The Python packaging tests verify that the HA and add-on artifacts match and retain room/demo navigation.

The workspace suite also covers day/week scheduling, reactive VWC/EC previews, profile editing, setup lifecycle, strict response-bearing service contracts, invalid/expired snapshots and draft preservation. Integration tests use a minimal HA fixture, not a running HA instance. HACS/hassfest and an actual Supervisor image build run in CI, not in the local browser harness.

## What it tests

### MCP connector

```sh
npm ci --prefix mcp-server
npm test --prefix mcp-server
```

The MCP suite uses a local fake HA server and the official MCP client. It checks protocol initialization, tool discovery, scoped reads and reviewed proposals, write opt-in, stale revisions, replay/expiry, failed readback and transport errors. It does not require credentials or actuate equipment. Live read-only checks are recorded separately from any configuration writes.

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

### 6. Controller safety regressions — `addons/f2_control/tests/test_safety_regressions.py`

Deterministic fake clocks and HA responses reproduce request-latency overruns, blind fallback/copy budget bypass, failed hardware closure and error cleanup, persisted shared-hardware holds, explicit recovery, and temporarily absent room descriptors. Tests verify preserved state/counters across restart and rediscovery.

New flow accounting regressions cover runtime caps, integer truncation, minimum durations, partial aborts and sizing edits during delivery. Existing totals are retained.

### 7. Frontend adapter and lifecycle — `frontend/src/lib/*.test.ts`

Room isolation and canonical identity, sensor freshness, supported entity/parameter validation, finite bounds and steps, write readback, partial batches, request deadlines, stale response cancellation, explicit demo isolation, and recorded history routing.

Run comparison tests cover room-scoped persistent metadata, revision conflicts, immutable captured references, Recorder retention gaps, cancellation, grow-age alignment and daylight-saving boundaries. The compiled visual suite verifies P3 line movement, saved/draft isolation, invalid-edit blocking, explicit zone/per-plant water and comparison workflows.

Run `node frontend/scripts/verify-recipe-library.mjs` after building to check named library saves on HTTP-style crypto capabilities, export/import, current-date preservation, explicit dirty-draft replacement, room isolation, removal confirmation, corruption recovery export and desktop/mobile accessibility. This suite also runs in CI and captures `img/recipe-library.png` from isolated demo data.

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
