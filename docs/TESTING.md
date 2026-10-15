# Testing

This repo ships an automated test suite plus a manual checklist for the live system. CI
runs the automated suite on every push to `main` and `testing` and on every pull request
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
# Python 3.14.2+ (Home Assistant 2026.9 needs it). A separate virtualenv keeps the lean
# prerequisites above lean.
pip install -r requirements-test-ha.txt
python -m pytest tests_ha -q          # NOT with PYTEST_DISABLE_PLUGIN_AUTOLOAD
```

`bash tests/run_ci.sh` runs it too when the package is installed (set `HA_PYTHON` to point at a
separate virtualenv). When it is not, the run ends `PARTIAL: real Home Assistant tier skipped` and
exits non-zero, even if every other check passed; `bash tests/run_ci.sh --allow-skip` accepts that
partial run and exits zero, but still says PARTIAL rather than ALL CHECKS PASSED. CI always runs it.

### On Windows or macOS: in a container

Home Assistant only runs on Linux (it imports `fcntl`), so on Windows the tier cannot run natively,
and on macOS it needs the same Python 3.14.2+ setup as above. `tests_ha/Dockerfile` is a Linux box
with the production leg's Python and `requirements-test-ha.txt` installed; it is test tooling only
and nothing ships from it. With Docker, from the repository root:

```bash
# Once, and again whenever requirements-test-ha.txt changes (a few minutes; the build sends
# only that file to Docker).
docker build -f tests_ha/Dockerfile -t crop-steering-tests-ha .

# The whole tier against your working tree (committed, staged and new files; nothing git ignores).
git ls-files -co --exclude-standard -z | tar --null -T - -cf - | docker run --rm -i crop-steering-tests-ha

# Arguments go to pytest, so one file or one test works too:
git ls-files -co --exclude-standard -z | tar --null -T - -cf - | docker run --rm -i crop-steering-tests-ha tests_ha/test_real_flow.py -q
```

The same commands work in Git Bash, macOS Terminal and PowerShell 7 (Windows' own `tar` reads the
list). The tree goes in as a `tar` stream rather than a bind mount: each run starts clean, sees
exactly the files git would commit, and leaves nothing behind in the checkout. The image covers the
production leg only; the oldest-supported leg below stays in CI.

| File | Scenario |
| --- | --- |
| `test_real_flow.py` | **Fresh install.** The wizard through the real flow manager for a one-switch room; the registered id of every entity; an existing registry keeps its ids. |
| `test_setup_entry.py` | **The entry itself.** It loads on a Home Assistant without `frontend.async_panel_exists`; another owner's sidebar path is left alone; the wizard's lights hours and sizing reach the entities. |
| `test_install_to_controller.py` | **Fresh install, both layers.** That install is handed to the *real add-on controller*, which must find the room from the descriptor alone, adopt it, and fire a shot sized and scheduled from the wizard's answers. The only tests that cross the integration / controller seam. |
| `test_upgrade_in_place.py` | **In-place upgrade with seeded data.** Starts the new code on top of a snapshot of an old install. Nothing tuned may move, no entity may change id, and the controller must carry on with the kill switch ON and no disarm cycle. |
| `test_move_from_jev.py` | **A room moved from the Jev edition.** Runs the copy command `docs/MOVING_FROM_JEV.md` prints on a Jev 3.11.1 app's data folder, then starts the real controller on the copy with the old app's options: no disarm cycle, counters, phase, learner and dosing record kept, and the brain on wherever a Jev file or a TypeSafe key came across. Also checks the doc's app ids and that its copy list names every data file the controller keeps. |
| `test_configure.py` | **Configure.** Editing a parameter reaches the engine; a mapping can be removed; an untouched save keeps every mapping. |

**Seeded fixtures** live in `tests_ha/fixtures/`. Each is a room *as an old version actually wrote
it*, with an `_about` note saying which era it models: its config entry, the states of its
devices, and the values its operator had tuned (with the attributes that version stored beside
them). To cover another kind of old install, add a snapshot there rather than hand-building one
in a test. `entry_2_17_wizard.json` is a pumped two-zone room from the 2.17 wizard;
`entry_env_era.json` is from the env-file era (legacy front/back probe pairs, no setup revision,
a probe with no unit, bookkeeping keys in `entry.options`). `entry_3_8_learned_tent.json` is the
2.18 tent as a 3.8.0 box holds it, with the state file controller 3.8.0 wrote for a zone its Auto
Setpoints learner had learned (zone 2 of a production room on 4 Oct 2026). `entry_us_units_tent.json` is
that 2.18 tent in a Home Assistant set to US customary units in a northern-hemisphere time zone, its probes
reporting m³/m³ and μS/cm: derived from the recorded file rather than recorded itself, it proves both layers
read those units as percent and mS/cm. `entry_2_25_1_pumped_room.json` is a
pumped two-zone room as upstream 2.25.1 left it, recorded from that release's own wizard and
controller: its config entry, every entity id it registered, its app `/data/options.json` and the
`/data/state.json` its controller wrote. `entry_3_11_1_pumped_room.json` is the same kind of room as Jev
3.11.1 left it after two grow-days under its own controller with Auto setpoints on, recorded the same way:
its config entry, every entity id, the ladder its controller moved, and beside it the app's
`/data/options.json` on Cloudflare and on TypeSafe (`options_3_11_1_jev_cf.json`,
`options_3_11_1_jev_typesafe.json`), the `/data/state.json` with the learner and the hourly P2 check's
working peak (`state_3_11_1_learn_jev.json`), the `/data/jev_usage.json` (`jev_usage_3_11_1.json`) and the
dosing store (`dosing_3_11_1.json`). `data_3_11_1_files/` holds the rest of a 3.11.1 app's `/data`: the
ledger, journal and setpoint memory its brain wrote and the `dosing_state.json` its dosing runner wrote,
recorded by running 3.11.1's own controller, brain and dosing runner on its own test kit. The `options_<version>_*.json` files with a `data` folder
(`data_3_0_0_ledger/`, `data_3_2_0/`, `data_3_3_0_typesafe/`, `data_3_0_0_quiet/`,
`data_3_11_1_usage/`) are apps from 2.25.1 and the Jev line as each left `/data/options.json` and
`/data`, recorded by running that version's own controller: they prove the brain starts on Cloudflare
credentials only where a Jev file shows it has run.

**Only the web server is stood in for.** The manifest depends on `frontend` and `http` for the
sidebar panel; `conftest.py` marks both as set up and gives `hass.http` a mock, and the panel
registration then runs against the real frontend module. It used to be replaced with a no-op,
which is how the pre-2026.5 `AttributeError` got past this tier. Do not stub out more than the
thing a test genuinely cannot have.

`tests_ha/` is a separate directory on purpose: `tests/conftest.py` registers fake
`homeassistant` modules, which would shadow the real package.

### Which Home Assistant

CI runs this tier once for each Home Assistant the repository vouches for: a matrix in the Real
Home Assistant job of `.github/workflows/ci-validate.yml`. Each leg pins the
pytest-homeassistant-custom-component release that brings exactly one Home Assistant, then fails
unless `homeassistant.const.__version__` is that version, so an install that quietly resolves to
something else cannot pass.

| Leg (check name) | Python | Plugin release | Home Assistant | What it proves |
| --- | --- | --- | --- | --- |
| Production: `Real Home Assistant (setup wizard and entity ids)` | 3.14 | 0.13.366, from `requirements-test-ha.txt` | 2026.9.3 | What production runs. Branch protection requires this check on `testing` and `main`. |
| Oldest supported: the same name followed by ` - oldest supported Home Assistant` | 3.12 | 0.13.171, with `josepy==1.14.0` | 2024.10.0 | The minimum in `hacs.json`, the README badge and [INSTALL.md](INSTALL.md). |

The Python requirement follows Home Assistant: 2026.9 needs Python 3.14.2 or newer, and no plugin
release for 2026.3 or later installs on an older Python; 2024.10 runs on 3.12. Before the matrix the
job ran Python 3.13 with the plugin unpinned, so pip settled, without a word, on the newest release
that still installed there, and CI tested Home Assistant 2026.2.3 while production ran 2026.9.

Moving a leg:

- **Production.** Pin the plugin release whose `homeassistant==` requirement is the new version (its
  PyPI page lists it) in `requirements-test-ha.txt`, and set the leg's `homeassistant` to match
  (and `python`, if the new Home Assistant needs a newer one). Keep that leg's name exactly as it
  is: branch protection looks for it by name.
- **Oldest supported.** That version is a promise to users, and HACS reads the one in `hacs.json`
  as the minimum. Change the leg, `hacs.json`, the README badge and `INSTALL.md` together. Nothing
  older than 2024.10.0 passes today. Before 2024.9.0 the integration itself fails: it unloads a
  room through `ConfigEntries.async_loaded_entries`, which Home Assistant added in 2024.9.0, so on
  anything older unloading raises `AttributeError`, and every reload with it, including the one
  that applies a saved Configure form. On 2024.9.x the integration passes, but
  `test_non_admin_user.py` writes its automation as `triggers:` / `trigger: event` / `actions:`,
  the syntax Home Assistant introduced in 2024.10.0; the older `trigger:` / `platform: event` /
  `action:` form works on every version tested here, so rewriting that one automation would bring
  2024.9.0 back. The `josepy` pin works around the test environment, not the integration: josepy
  2.0 (2025) removed an API that the `acme` release pinned by Home Assistant 2024.10 still imports,
  so the leg installs the josepy of that time.

### hassfest, without Docker

hassfest runs in CI as a container action. It is an ordinary Python module in the core
repository, so it can be run locally against the Home Assistant already installed for `tests_ha`:

```bash
git clone --depth 1 --filter=blob:none --sparse -b 2026.9.3 https://github.com/home-assistant/core ha-core
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

Test data names no real site. Where a test builds its own rooms and people it uses neutral ones: `Room A`, `Room B` with prefix `room_b_`, or a room named after a grow stage (`veg`), and `Alex`. Two kinds of test keep other names on purpose. The old `?room=f1` / `?room=f2` links (to the room with prefix `f1_` and to the default room) and the older integration's `system_` sensors (read for the `f1_` room only) are product behaviour, so the tests that prove them (`verify-live.mjs`, `model.test.ts`, `review-regressions.test.ts`, `test_dashboard_layout.py`) use those names. Assertions that read the demo's own rooms, staff and phones (the phone constants in `notify.test.ts`, every browser check that opens the demo page with `?demo=1`, which is all of `verify-dashboard.mjs` and parts of the other `verify-*.mjs` suites, and the demo-backed unit tests that select its `f1_` room) still use the names the demo ships today; they change in the same pull request that renames the demo.

The workspace suite also covers day/week scheduling, reactive VWC/EC previews, profile editing, setup lifecycle, strict response-bearing service contracts, invalid/expired snapshots and draft preservation. Integration tests use a minimal HA fixture, not a running HA instance. HACS/hassfest and an actual Supervisor image build run in CI, not in the local browser harness.

## What it tests

### MCP connector

```sh
npm ci --prefix mcp-server
npm test --prefix mcp-server
```

The MCP suite uses a local fake HA server and the official MCP client. It checks protocol initialization, tool discovery, scoped reads and reviewed proposals, write opt-in, stale revisions, replay/expiry, failed readback and transport errors. It does not require credentials or actuate equipment. Live read-only checks are recorded separately from any configuration writes.

### 1. Pure decision core: `crop-steering-engine/tests/test_core.py`
The `decide()` function with no HA and no I/O: phase transitions (P0→P1→P2→P3), the
anti-lockout high-EC flush, the sensor-independent minimum-daily-water floor, EC steering,
and `validate_params()` clamping. This is the bug class that has actually bitten the grow,
testable offline.

### 2. Integration calculation helpers: `tests/test_calculations.py`
The pure helpers in `custom_components/crop_steering/calculations.py` (no hardware needed;
input_boolean/number simulate pumps/sensors).

### 3. In-place upgrade / state migration: `tests/test_state_migration.py`
**Why it matters:** the add-on persists per-zone runtime state to `/data/state.json` and is
live-installed on many boxes. A version bump must load an **older** state file transparently.
These tests lock that contract: a missing file, corrupt JSON, missing keys, an unknown
legacy key, a bad timestamp, and a zone absent from the file must all be tolerated: new
fields fall back to fresh defaults, never an error, never a wipe. Plus a save→load
round-trip.

### 4. Version consistency: `tests/test_version_consistency.py`
The integration version must match across `manifest.json`, the latest released `CHANGELOG.md`
heading, and the README badge, so a release can't ship a stale number. (The f2-control
add-on has its own version line in `addons/f2_control/config.yaml`; boxes build the add-on
from this repository, so there is no second copy to keep in step.)

`tests/test_repo_identity.py` does the same for the repository's own address: the app store
listing, the app's link, the manifest, HACS, the README, docs and the dashboard all name this
repository, and every Home Assistant redirect they use is one my.home-assistant.io serves.

### 5. Lint / format / YAML: ruff, black (scoped to `custom_components/` + `tests/`), yamllint
Plus, on GitHub only: **hassfest** and **HACS validation** of the integration.

### 6. Controller safety regressions: `addons/f2_control/tests/test_safety_regressions.py`

Deterministic fake clocks and HA responses reproduce request-latency overruns, blind fallback/copy budget bypass, failed hardware closure and error cleanup, persisted shared-hardware holds, explicit recovery, and temporarily absent room descriptors. Tests verify preserved state/counters across restart and rediscovery.

New flow accounting regressions cover runtime caps, integer truncation, minimum durations, partial aborts and sizing edits during delivery. Existing totals are retained.

### 7. Frontend adapter and lifecycle: `frontend/src/lib/*.test.ts`

Room isolation and canonical identity, sensor freshness, supported entity/parameter validation, finite bounds and steps, write readback, partial batches, request deadlines, stale response cancellation, explicit demo isolation, and recorded history routing.

Run comparison tests cover room-scoped persistent metadata, revision conflicts, immutable captured references, Recorder retention gaps, cancellation, grow-age alignment and daylight-saving boundaries. The compiled visual suite verifies P3 line movement, saved/draft isolation, invalid-edit blocking, explicit zone/per-plant water and comparison workflows.

Run `node frontend/scripts/verify-recipe-library.mjs` after building to check named library saves on HTTP-style crypto capabilities, export/import, current-date preservation, explicit dirty-draft replacement, room isolation, removal confirmation, corruption recovery export and desktop/mobile accessibility. This suite also runs in CI and captures `img/recipe-library.png` from isolated demo data.

### 8. Error codes: `tests/test_error_codes.py`

`docs/error-codes.json` is the one list of `CS-xxx` codes. Every code the controller raises or a Repairs card shows is in it, `docs/ERROR_CODES.md` is exactly what it writes, and no code is defined twice: once in the list, on at most one Repairs card in `strings.json` and in `translations/en.json`, and once in each shipped dashboard.

A number is never handed out twice. Every code after the ones 3.11.1 shipped is first reserved in the test's `RESERVED` table, against the branch of the pull request that will add it (JSON has no comments, and `ERROR_CODES.md` is generated, so neither can hold a reservation). That pull request adds the code to the list together with the integration commit that puts it in a notification kind (`tests/test_notify_catalog.py`). A code nobody reserved fails the test until its reservation is added.

### 9. Device units: `tests/test_unit_table.py`, `addons/f2_control/tests/test_device_units.py`, `tests_ha/test_probe_units.py`, `addons/f2_control/tests/test_dosing_units_and_actuators.py`, `tests_ha/test_dosing_units_and_actuators.py`

Every number read from a device goes through the one device-unit table (`UNITS` in the defaults module). The lean test pins the table: exact conversions (and the same arithmetic each layer used before), `ppm` and `ppt` refused, an unknown or missing unit read as the steering unit only while plausible, and the integration accepting and refusing exactly the units it did. The controller test proves the loop's reads (zone moisture and EC, feed EC and pH, the sump plug) convert, that a feed EC probe in `ppm` or `ppt` reads as 3.11.1 read it (so the source-water gate holds no room it did not hold), that a moisture probe set aside for its unit takes the dead-probe path with the same decisions as a dead probe (CS-503), that a plug in watts gives the CS-311 verdicts it always did, and it carries the **coverage guard**: one loop against a fake Home Assistant with every device mapped, failing if any device entity is fetched other than through `_device` or `_device_history` (`_fused_id` and `_detect_zones` only ask whether an entity exists). A new device read adds its rows to the table and its entity to that test. The real-Home-Assistant test shows upgraded 2.25.1 and 3.11.1 rooms reading every probe (the feed probe in `ppm` or `ppt` too) exactly as before, a kW sump plug compared in watts, and, on a fresh install, a zone whose only probe reports in an unknown unit: the integration's zone reading names the probe and unit (`unit_set_aside`), and the controller waters the zone blind and raises CS-503 naming them.

The dosing runner reads through the same table and drives through the controller's actuator table. Its controller test replays a dose, a dose that runs past its time and a whole batch on switch, input_boolean and light hardware and compares every command and read-back with the ones 3.11.1 sent (`addons/f2_control/tests/fixtures/dosing_calls_3_11_1.json`, recorded by running that code); a unitless or mL/s flow keeps 3.11.1's limits and no dose that finished under them is refused or cut; a kW mix plug, an mL/min flow, an L volume number and a `valve.` fill or mix valve work; and its own **coverage guard** fails if a dosing number is fetched other than through the runner's `_device`, an actuator read other than through `_hw_state`, or an actuator sent a command other than its domain's from `_on`, `_switch_off` or `_send_off`. The real-Home-Assistant test doses the 3.11.1 room's own dosing store with exactly 3.11.1's calls.

## Manual verification checklist (live Home Assistant)

The automated suite can't drive real hardware. Before trusting a change on the grow:

- [ ] **Dry run.** With the kill switch `input_boolean.f2_control_enabled` **OFF**, start the
      add-on and watch a photoperiod in the log: it decides but **no valve opens**.
- [ ] **Shot length is real.** Verify a fired shot's duration from the live pump history
      (`switch.<pump>` `/api/history/period`), not from "deployed": a file copy proves
      nothing about the running container.
- [ ] **State persists.** Confirm `/data/state.json` survives an add-on **restart** (phase
      and daily counters carry over).
- [ ] **Upgrade in place.** After a version **Update / Rebuild**, the engine resumes from the
      existing `state.json` with no re-setup and no wiped counters.
- [ ] **Feed-gate hold.** Out-of-range feed pH/EC (or a tank fill/dose) blocks watering and
      alerts: that is correct behavior, not a bug.

## Tests are not a release

A green build says the code does what its tests expect. It says nothing about a pump on a
smart plug at 3 am. What has to happen between a green build and a production room - the
staging soak on the `testing` branch, the fault drills, promotion to `main`, rollback - is in
[RELEASING.md](RELEASING.md). How a change gets in to begin with - one change, one branch, one
pull request - is in [CONTRIBUTING.md](../CONTRIBUTING.md).

## A change isn't done until

The relevant automated tests pass **and** any change to persisted state, add-on options, or
integration entities has a test proving an **older install still loads** (see §4). New
behavior gets a new test. See `CLAUDE.md` → *Compatibility & data* for the rules these tests
enforce.
