# First-run setup review — 2026-09-21

Reviewed and fixed locally against `main` @ `cfb10cc` (2.18.0 / controller 0.15.1). Every finding was reproduced with the integration loaded by a real Home Assistant core (2026.2.3, `pytest-homeassistant-custom-component`, Python 3.13) before it was fixed. No live Home Assistant access, no deployment, no hardware command. Physical water delivery and a live Supervisor update were not exercised.

Released as integration **2.18.1** / controller **0.15.2**.

## Why this review happened

A first-time grower with a single-switch tent (one smart plug driving the pump) reached the last screen of the setup wizard, was told `switch.gt1_irrigation_switch must read OFF before changing setup`, and lost everything typed. 2.18.0 fixed that report. This review asked the next question: what else does a newcomer hit that the test suite cannot see?

The answer turned on one fact. Every integration test in `tests/` runs against hand-written stubs in which voluptuous, the selectors and the config-flow base class are no-ops. They are fast, and they cannot see a schema Home Assistant rejects, a Home Assistant API that does not exist in an older version, or an entity id Home Assistant assigns. 2.18.0 added `tests_ha/`, which can. It had one blind spot, below.

## Findings

Each was reproduced on 2.18.0 first. "Seen as" is what the operator experiences.

### 1. The config entry fails to set up on Home Assistant older than 2026.5

- **Seen as:** the wizard completes, then the integration shows "Failed to set up". No entities, no dashboard.
- **Cause:** `setup_panel.py` called `frontend.async_panel_exists` unconditionally, inside `async_setup_entry`. That helper was added in core **2026.5.0**. Checked directly against `home-assistant/core`: absent from tags 2024.3.0, 2025.1.0, 2026.2.3, 2026.3.0 and 2026.4.0; present in 2026.5.0 and `dev`. `hacs.json` and INSTALL.md advertise 2024.3.
- **Why both test tiers were green:** `tests/test_setup_panel.py` assigns `frontend.async_panel_exists = lambda ...` onto its own stub, so it passes against an API the test supplied. `tests_ha/conftest.py` replaced the whole panel registration with a no-op, so the line never ran there either. One test is even named `test_ha_2024_3_legacy_static_path_registration_is_still_supported`.
- **Fix:** `_panel_exists()` uses the helper when present, otherwise `PANEL in hass.data[frontend.DATA_PANELS]`. That is the helper's own body, and the key has existed since before 2024.3.
- **Kept fixed by:** `tests_ha` now stands in for the web server only and runs the registration against the real frontend module. With the fix reverted that tier fails (checked). `tests_ha/test_setup_entry.py` removes the helper explicitly, so the case stays covered once CI's Home Assistant has it.

### 2. The wizard's lights-on and lights-off hours are ignored

- **Seen as:** setup is told lights-on at 6. `number.crop_steering_lights_on_hour` reads 12. The grow-day, the P3→P0 counter reset and the overnight dry-back run on the wrong clock, silently.
- **Cause:** `PARAM_TO_ENTITY_KEY` in `number.py` had no entry for either key, so both entities seeded from `DEFAULT_VALUES` (12 and 0).
- **Fix:** two lines.
- **In-place upgrade:** a seed only applies to an entity being created for the first time; an existing entity restores its own last value. Pinned by `tests_ha/fixtures/entry_2_17_wizard.json`, where setup recorded 10–22 and the operator later set 8–20: 8–20 survives.

### 3. Configure → Edit parameters changes nothing the engine reads

- **Seen as:** change P1 target from 65 to 61, save, "Options successfully saved". The number entity still reads 65, and so does the controller.
- **Cause:** the step wrote `entry.data["parameters"]` and reloaded. Those parameters only seed a number entity the first time it is created; on reload each `RestoreEntity` restored its previous state over the new seed. The form also showed the value recorded at setup, not the live one.
- **Fix:** set the live number entities first, then update the entry, so the reload restores the value just written. Defaults come from the live entities. The OFF check and its abort are unchanged, and nothing is written when it refuses.

### 4. In Configure, a mapping can be swapped but never removed

- **Seen as:** clear the room-temperature sensor (or a tank probe, or a pump), save, reopen: it is back.
- **Cause:** `_hardware_schema._ent` prefilled with `default=`. The frontend omits an emptied field and voluptuous re-applies the default.
- **Fix:** prefill with `description={"suggested_value": ...}`. The form still opens showing the mapping, so an untouched save cannot wipe it (tested), and the field can be cleared. More pressing since 2.18.0 made the pump and main-line optional: removing one has to work.

### 5. Wizard answers that feed nothing, and a tooltip that says otherwise

`waste_switch`, `light_entity`, `notification_service`, `humidity_sensor` and `vpd_sensor` are collected and stored, and have **no runtime consumer** anywhere in the integration's platforms, the add-on or the engine. The waste-valve tooltip nevertheless said it is "forced closed during a shot so feed reaches the plants". A grower with a recirculating system who believes that sends feed to waste.

Only the wording is changed here. `tests/test_translations.py` fails the day any of the five gains a consumer, which is the prompt to put the behaviour back into its tooltip. **Whether the controller should drive the waste valve is a product decision, and given what that tooltip promised it is the one to look at first.**

### 6. Smaller

- `feed_ec_sensor` and `feed_ph_sensor` had **no label at all** on either mapping form: the wizard showed the raw key. These are the source-water safety probes.
- All 24 `zone_N_name` and `zone_N_active` fields had labels and no tooltip.
- Abort reasons `not_env_config` and `reload_failed` had no translation and showed as raw keys.
- Room-wide `substrate_volume` had a minimum of 1.0 and `drippers_per_plant` a maximum of 6, where `setup_api.SIZING` and the per-zone entities allow 0.1 and 20. A 0.65 L rockwool cube could be set up and then never adjusted.
- The `blocked_dripper_*` entities have no consumer in the controller or engine either. Not changed; noted because it bears on the next section.

### 7. The controller test suites were not hermetic

`Controller.__init__` hardcoded `/data/state.json` and reads it, and on adopting a setup **writes** it, before a test can repoint `_state_path`. GitHub runners have no `/data`, so CI was green. On any machine where `/data` exists and is writable (a devcontainer, the add-on's own container, the box this review ran on) the suite wrote a real file there and leaked it into the next test: six false failures in `test_setup_resume.py`. Fixed with an `F2_STATE_PATH` seam (unset on every live install), autouse fixtures in all three conftests, a restart rig that points the constructor at the previous process's file *before* constructing, and guard tests.

## Raised for a decision, not changed: an unmapped pump

Since 2.18.0 the pump and main-line valve are optional end to end and `_blocked()` needs only the zone valve. It is the simplest thing that makes a one-switch tent work, and it asks the newcomer nothing extra. The cost: the controller can no longer tell a room that has no pump from a room whose pump is not mapped.

Demonstrated with the real controller on 2.18.0, a pumped room whose descriptor has `pump: ""`:

```
main-line on → 1 s → valve on → 30 s → valve off → main-line off        shots = 1, daily_vol = 1.5 L
```

The pump never runs, the valve opens with nothing behind it, and the shot is recorded as delivered, so the daily cap and the water history count water that never arrived. Nothing in the controller or engine reacts to shots that produce no moisture response. With Auto Setpoints on, the zone would read *frozen* with a delivery-or-probe reason, which is a status and not a notification. Before 2.18.0 the same room held with "no hardware mapped".

This does not happen through a transient glitch: it takes a saved setup with the pump empty, through the OFF gate and adoption like any other. The realistic routes are a newcomer who has a pump and presses Submit on a hardware step where every field is optional, a field cleared in *Rooms & setup*, and a `setup_save` proposed over MCP that omits it.

Options, smallest first:

- **A. Guard the transition.** Keep inference. When a room whose adopted setup had a pump (or main-line) publishes a descriptor without one, hold and alert until the operator confirms. Controller-only; covers a cleared field and an MCP proposal; does not cover a newcomer who never mapped the pump.
- **B. Ask once.** The room declares how water reaches its valves (`valves_only` / `pump_valves` / `mainline_valves` / `pump_mainline_valves`): one required wizard question with no default, checked both ways at save, published in the descriptor. Rooms saved under 2.18.0 are offered the layout their mapped switches imply. The only option that catches the newcomer, because it is the only one where "no pump" is something a person said. A working implementation exists on `ChillingSilence:feat/first-run-wizard` (PR #45).
- **C. Say so.** Done in 2.18.1 as the uncontroversial half: the pump tooltip now states that an empty pump means the controller will never run one and will count the shot as delivered. A health check that raises a repair when shots are counted and VWC does not respond would complete it.

**Decided 2026-09-21: B**, rebuilt on the 2.18 code as its own change (`feat/declared-plumbing`; see *Unreleased* in the changelog), this time including the React *Rooms & setup* page that #45 never touched. The demonstration above is now a test in both tiers (`addons/f2_control/tests/test_declared_plumbing.py`, `tests_ha/test_declared_plumbing.py`): declared, that room is held, the valve stays shut and nothing is counted. Two things differ from #45's version, both for existing installs. A room that never declared keeps 2.18's inference exactly, where #45 treated it as three-switch, which would have held every one-switch tent set up under 2.18.0. And nothing is inferred into storage: a room becomes declared only when a person saves the question. Option A remains worth doing for rooms that never open the form. Still true: **not run on hardware.**

## What was not verified

Physical delivery; a live HACS / Supervisor update; any Home Assistant other than 2026.2.3 (the core tags in finding 1 were read, not run). The React *Rooms & setup* panel was not reviewed.

## Reproducing

```bash
pip install -r requirements-test-ha.txt               # Python 3.13+
python -m pytest tests_ha -q                           # 30 tests, about two seconds
```

To see a finding fail, revert its fix and re-run: for example `git checkout v2.18.0 -- custom_components/crop_steering/setup_panel.py` fails `tests_ha` on entry setup.
