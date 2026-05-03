# Changelog

All notable changes to the Advanced Automated Crop Steering System will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] - 3.0.0-dev "RootSense"

### Changed (ClimateSense — layered control refactor + leaf VPD supervisory variable)

The monolithic `control.py` (~290 lines) is replaced with a layered
package mirroring commercial-BMS architecture:

```
intelligence/climate/
  leaf_vpd.py              ← pure math (Tetens + RH inversion)
  control/
    actions.py             ← Action / ActionKind dataclasses
    hvac.py                ← bang-bang + calibration + mode-switch + IR refresh
    dehumidifier.py        ← lead-lag staging + rotation + demand persistence
    humidifier.py          ← bang-bang with min-off
    co2.py                 ← pulse cadence + lights-on lead time + adaptive
    exhaust.py             ← emergency + scheduled refresh + watchdog
    coordinator.py         ← cross-actuator conflict resolution
    watchdog.py            ← Tier 4 safety (sensor staleness, runaway, emergency)
    app.py                 ← thin AppDaemon adapter
```

### Added (corrected for F1 reality)
- **Leaf VPD as the supervisory variable.** The recipe declares
  `leaf_vpd_kpa` per phase; the control layer reads current leaf temp
  + air temp + air RH and inverts the Tetens equation to derive the
  required RH to hit target leaf VPD. The dehu/humid loops chase the
  *derived* RH, not the recipe's `day_rh_pct` (kept as fallback for
  installs without a leaf-temp sensor).
- 22 unit tests covering Tetens math against published tables,
  round-trip property tests on the RH inversion, and 6 cannabis-phase
  envelope checks (transplant through ripening) where solved RH must
  fall within published cultivation chart bands.

### Added (control patterns from commercial cultivation HVAC)
- **HVAC mode-switching** with cooldown — controller never flips
  cool↔heat more often than `mode_change_cooldown_min` (default 30 min).
  IR-blaster insurance: re-issue last setpoint every `refresh_interval_min`
  to recover from lost IR commands.
- **Lead-lag dehumidifier rotation.** F1 has 2 dehu units (4 relays as
  contactor pairs). Lead engages first on demand persistence; lag only
  joins if RH stays high `stage_persistence_min` after that. Reverse
  order on release (lag off first). Lead/lag swap every 7 days for wear
  leveling.
- **Demand persistence** — every actuator requires the deviation to last
  3-5 min before staging on; prevents reacting to door-open spikes.
- **AC↔dehu cooperation** — coordinator defers staging the LAG dehu
  while AC is already cooling AND temp is above target (AC cooling
  is already condensing water out via condensation).
- **Adaptive CO₂ pulse cadence** — extends/shortens pulse_off based on
  observed ΔCO₂ during the previous rest period; clamped to
  [pulse_off_min_seconds, pulse_off_max_seconds].
- **Lights-on lead time for CO₂** — solenoid won't inject until lights
  have been on for `lights_on_lead_min` (default 30 min) so stomata are
  open and CO₂ uptake is real.
- **Tier 4 watchdog** — runs every tick. Flags stale sensors (no update
  in 90 s), force-closes any actuator that exceeds its
  `actuator_max_runtime_min`, and re-asserts emergency exhaust + CO₂
  cutoff regardless of what other layers are doing.
- **Exhaust controller** — emergency-only by default (room is sealed).
  Triggers on temp > 32 °C OR CO₂ > 1800 ppm; releases when both are
  back in safe range. Optional scheduled refresh window.
- **Severity-tiered actions** — every Action carries a severity (normal /
  safety / emergency). Coordinator drops normal-severity proposals when a
  critical anomaly is active; safety/emergency always emit.

### Added (operator-facing docs)
- `docs/upgrade/SEQUENCE_OF_OPERATIONS.md` — the operator-readable
  contract describing exactly what every actuator does, when, and why.
  Sections cover authority hierarchy, sensors, supervisory variable,
  per-actuator sequences, cross-actuator rules, failure modes, and
  loss-of-comms safe state.
- `docs/upgrade/CONTROL_THEORY.md` — design rationale. Why bang-bang
  not PID, why leaf VPD not air RH, why hardware calibration is
  first-class, why staged with lead-lag rotation, why coordinator over
  master controller, why severity-tiered actions, what this design
  will NOT do.

### Added (corrected hardware reality for F1)
- `hardware_f1.yaml` updated to match operator description:
  - 2 dehu units (was incorrectly described as 4 separate dehus); each
    is a contactor pair driving run + fan relays.
  - Wet-tip contactors with built-in 2-min hardware cooldown — software
    no longer enforces min_off (the contactors do).
  - 2× 9 kW IR-controlled AC presented as a single climate entity
    with HVAC mode-switching support.
  - Exhaust system added (emergency + scheduled refresh).
  - Leaf-temp sensor present — primary supervisory variable.

### Tests
- 32 new tests in `test_control_loops.py` (HVAC, dehu, humidifier, CO2,
  exhaust, coordinator, watchdog).
- 22 new tests in `test_leaf_vpd.py` (Tetens, AVP, leaf VPD, RH solver,
  cannabis-phase envelopes).
- Total intelligence tests: 95. Full suite: **123 passing.**

### Added (ClimateSense — environmental control sibling)
- New `appdaemon/apps/crop_steering/intelligence/climate/` package — five
  pillars mirroring RootSense exactly (sensing, timeline, control,
  lights, anomaly) plus a hardware calibration module.
- **Hardware calibration is first-class.** A YAML file
  (`hardware_f1.yaml` shipped) captures per-actuator quirks like
  "set heat pump to 27 °C, room reads 29 °C". Control loops
  command `target + offset` so the room actually hits target. Tests
  confirm the math is right and the file shape is forward-compatible
  with new keys.
- Recipe-driven setpoints. A YAML at `/config/recipes/<name>.yaml`
  describes per-phase targets across the entire grow (temp / RH /
  CO₂ / VPD / PPFD / photoperiod). The shipped `athena_f1_default.yaml`
  is a 7-phase ~84-day Athena cannabis recipe. The timeline pillar
  resolves "what are my targets right now" from day-in-grow + day/night
  state and publishes per-metric `sensor.climate_target_*` entities.
- Closed-loop control: bang-bang temp with calibration offset and
  deadband, RH with hysteresis matching the existing
  `40_environment.yaml` defaults (drop-in replacement once enabled),
  pulse-injection CO₂ with hard cap and lights-off safety, optional
  lights manager with PPFD ramps.
- Climate anomaly scanner: temp/RH/VPD excursions, CO₂ low during
  photoperiod, CO₂ overshoot, DLI undershoot prediction, sensor
  unavailability. Reuses the existing `crop_steering_anomaly` event
  format with `code` prefixed `climate_*`.
- 6 new switches in the integration: 5 module-enable switches mirroring
  RootSense's pattern, plus `..._climate_drives_intent_enabled` to let
  the recipe optionally drive the cultivator-intent slider.
- New number entity `number.crop_steering_climate_grow_day_offset` —
  operator hand-sets day-in-grow.
- 12 new unit tests covering hardware calibration math (cool/heat
  offsets, deadband, clipping, real F1 file load, forward-compat key
  filtering) and recipe loader (phase-for-day resolution, ramp
  defaults, validation rejection of empty phases, intent extraction).
- Total intelligence test count: **51** (was 39); full suite **79**.

### Added (Documentation)
- `docs/SYSTEM_OVERVIEW.md` — single source of truth for how the
  whole stack fits together. Hardware → entities → control →
  dashboards. Includes the heat-pump calibration explanation and a
  full reference doc index.
- `appdaemon/apps/crop_steering/intelligence/climate/hardware_f1.yaml`
  — F1-specific calibration file with the heat pump's `cool_offset_c:
  -2.0` documented inline.

### Added (Dashboards)
- New `Recipe` view in `dashboards/legacyag/40_setpoints.yaml` —
  active phase + day-in-grow + DLI today/predicted + the 5
  ClimateSense module switches + measured-vs-recipe-target overlay.
- Recorder package extended with all `sensor.climate_target_*`
  globs and the new ClimateSense switches/numbers.

### Added (Phase 2 — Adaptive Irrigation goes live)
- `number.crop_steering_steering_intent` — single -100..+100 dial that drives
  every derived parameter via the IntentResolver.
- `select.crop_steering_steering_mode_derived` — Generative / Mixed-generative
  / Balanced / Mixed-vegetative / Vegetative bucketing of the intent slider.
- `crop_steering.custom_shot` HA service. Pure event-router with full schema
  validation. Orchestrator listens for the resulting event and applies safety
  gates.
- `IntentResolver._publish_derived_mode()` keeps the derived select in sync
  with the intent slider on every tick.
- 9 unit tests for IntentResolver (lerp endpoints, profile-dict consistency
  guard, every profile key has an entity mapping, intent=0/±100 produce
  correct values, live read of dryback sliders, 11-point bucketing matrix,
  derived sensor attributes). 13 tests total in `tests/intelligence/`, all
  green.

### Added (Test coverage + migration doc)
- 26 additional unit tests across `tests/intelligence/`:
  - `test_anomaly_scanner.py` (8) — emitter blockage, EC drift,
    flat-line gating by photoperiod, peer-deviation, no-double-fire.
  - `test_orchestrator.py` (7) — emergency rescue, flush trigger and
    cooldown, anomaly suppression, custom-shot event routing.
  - `test_agronomic.py` (11) — VPD math against published Athena
    chart values, Penman-Monteith monotonicity, transpiration envelope
    sanity, VPD ceiling publishing.
- Total intelligence test count: **39 passing** (was 13).
- Two real bugs caught and fixed in the process: missing
  `_dryback_window` init in `AgronomicIntelligence` reproduced via
  fixture, and an over-loose peer-deviation test data set that didn't
  actually exercise the 2σ rule.
- `tests/intelligence/_appdaemon_stub.py` — shared AppDaemon stub
  module so individual test files don't duplicate ~50 lines each.
- `MIGRATION.md` — operator-facing v2.3.x → v3.0 upgrade guide with
  step-by-step rollout sequence, rollback path, and troubleshooting.

### Added (Linked F1 dashboard suite)
- Five linked Lovelace dashboards under `dashboards/legacyag/`,
  built on the existing `custom:agency-sensor-analytics-card` that
  the live F1 install already uses. Replaces the earlier
  history-graph-card prototype (`rootsense_history.yaml`) which
  has been removed.
  - `00_overview.yaml` — landing page, room climate + substrate
    + RootSense status at a glance.
  - `10_climate.yaml` — three views (Temp & RH / CO₂ / VPD) with
    measured-vs-target overlays and full actuator control panels.
  - `20_substrate.yaml` — two views (per-table VWC & EC / RootSense
    per-zone intelligence). 7-day FC + dryback velocity + porosity
    + EC stack.
  - `30_intelligence.yaml` — three views (Intent / Anomalies /
    Custom shot console). Includes one-click test-emitter and
    rescue-shot buttons.
  - `40_setpoints.yaml` — single page collecting every operator
    target, plus measured-vs-target time series for climate and
    substrate. Anchor for the future ClimateSense recipe timeline.
- A shared markdown nav block at the top of every dashboard links
  the five together for one-click switching.

### Added (Plans)
- `docs/upgrade/INFLUXDB_GRAPHS_PLAN.md` — how to swap the
  agency-sensor-analytics-card's data fetch from HA's recorder
  history API to InfluxDB v2 Flux queries. ~1.5 focused-days work.
  Default stays HA-history; per-card opt-in via `data_source: influxdb`.

### Added (Polish)
- `ENTITIES.md` updated end-to-end with new RootSense entities and the
  dryback semantic clarification ("% drop from peak", not "VWC value to
  dry to").
- `README.md` gains a RootSense v3 section with module status table and
  opt-in steps.
- `.gitignore` excludes `appdaemon/apps/crop_steering/state/` (local
  SQLite) and a stray nested clone directory.

### Added (Phase 1 — Root Zone Intelligence wiring)
- New shared base `appdaemon/apps/crop_steering/intelligence/base.py` provides
  module-enable gating and common helpers for all five pillars.
- 5 module-enable switches in the integration so each pillar is independently
  toggleable from the HA UI:
  - `switch.crop_steering_intelligence_root_zone_enabled`
  - `switch.crop_steering_intelligence_adaptive_enabled`
  - `switch.crop_steering_intelligence_agronomic_enabled`
  - `switch.crop_steering_intelligence_orchestrator_enabled`
  - `switch.crop_steering_intelligence_anomaly_enabled`
  Default OFF — existing v2.x installs are unaffected on first upgrade.
- `RootZoneIntelligence` now publishes three live derived sensors per zone
  (previously stubs):
  - `sensor.crop_steering_zone_{n}_dryback_velocity_pct_per_hr`
  - `sensor.crop_steering_zone_{n}_substrate_porosity_estimate_ml_per_pct`
  - `sensor.crop_steering_zone_{n}_ec_stack_index`
- Local dryback-episode tracker (`DrybackTracker`) detects peak/valley pairs
  from the rolling per-zone VWC buffer, persists each episode to
  `rootsense.db`, publishes `dryback.complete` on the bus, and fires the HA
  `crop_steering_dryback_complete` event.
- Recorder includes package: `packages/rootsense/00_recorder.yaml` ensures
  the new sensors and module switches are kept in HA's history database.
- Reconciliation document `docs/upgrade/RECONCILIATION.md` mapping the gap
  analysis P1/P2 items to RootSense plan phases.
- Unit tests: `tests/intelligence/test_dryback_tracker.py` covers the
  episode tracker state machine (4 cases, all green).

### Added (Phase 0 — scaffolding only, no behaviour change)
- New `appdaemon/apps/crop_steering/intelligence/` package containing the four
  RootSense intelligence pillars as opt-in AppDaemon apps:
  - `root_zone.py` — automated field-capacity detection, dryback episodes,
    substrate analytics sensors.
  - `adaptive_irrigation.py` — cultivator-intent slider, profile interpolation,
    bandit-based shot-size optimisation.
  - `agronomic.py` — Penman-Monteith transpiration estimate, VPD ceiling per
    cultivar, nightly run reports.
  - `orchestration.py` — coordinator with `crop_steering.custom_shot` service,
    emergency rescue, EC flush guardrails.
  - `anomaly.py` — cross-cutting anomaly scanner (emitter blockage, EC drift,
    sensor flat-line, peer-group VWC deviation).
- Shared infrastructure:
  - `bus.py` — in-process pub/sub (`RootSenseBus`).
  - `store.py` — local SQLite analytics store (`rootsense.db`).
- `docs/upgrade/ROOTSENSE_v3_PLAN.md` — full upgrade plan, feature mapping,
  testing strategy, and future roadmap.
- `docs/upgrade/apps.example.yaml` — example AppDaemon app declarations.

### Fixed
- Testability hardening: moved `ShotCalculator` into new pure helper module `custom_components/crop_steering/calculations.py` so unit tests no longer require a Home Assistant runtime during import.

### Documentation
- Added `docs/upgrade/GAP_ANALYSIS_2026-05.md` with a full module-by-module gap analysis, prioritized production backlog, and explicit To-Do sequence.
- Updated README with a dedicated "Upgrade Gap Analysis & To-Do" section linking to the new tracker document.

### Changed
- **P0 dryback is now unambiguously "% drop from peak VWC"**, surfaced as two
  independent operator-facing number entities:
  - `number.crop_steering_veg_p0_dryback_drop_pct` (range 2–40, default 12).
  - `number.crop_steering_gen_p0_dryback_drop_pct` (range 2–50, default 22).
  Defaults follow Athena cannabis guidance (small drop in vegetative growth,
  larger drop in generative). Both values are read live by the IntentResolver
  every tick — neither is hard-coded. The interpolated current target is
  pushed to the existing `number.crop_steering_p0_dryback_drop_percent`
  entity that the legacy P0-exit predicate already consumes, and exposed as
  `sensor.crop_steering_p0_dryback_drop_pct_current` for dashboards.
- Legacy entities `number.crop_steering_veg_dryback_target` and
  `number.crop_steering_gen_dryback_target` are retained as aliases. Their
  default values are corrected from `50` / `40` (which were too aggressive
  under the "drop %" semantic) to the new `12` / `22`. Their min ranges are
  widened to `2` so existing installs that already configured them lower
  continue to load without validation errors.
- `DEFAULT_VEG_P0_DRYBACK_DROP_PCT` / `DEFAULT_GEN_P0_DRYBACK_DROP_PCT`
  added to `custom_components/crop_steering/const.py` as the single source
  of truth.

### Notes
- Existing apps (`master_crop_steering_app.py`, `phase_state_machine.py`,
  detectors, profiles) are untouched in this commit.
- Modules are not added to `apps.yaml` automatically; existing installs are
  unaffected. See `docs/upgrade/apps.example.yaml` to opt in.
- Full migration to v3.0 happens incrementally across PRs #2–#5 per the plan.

## [2.3.1] - 2025-01-03

### 🔧 Critical Fixes & Documentation Overhaul
- **CRITICAL FIX** - Reconstructed corrupted `config_flow.py` that prevented integration loading
- **Documentation Accuracy** - Complete rewrite of all .md files to reflect actual system capabilities
- **Code Quality** - Major refactoring with 85% reduction in code duplication
- **Dependency Clarity** - Fixed misleading "zero dependencies" claims (AppDaemon required for automation)

### 📚 Documentation Updates
- **README.md** - Updated to v2.3.1, corrected dependency information
- **installation_guide.md** - Complete beginner-friendly rewrite with step-by-step instructions
- **dashboard_guide.md** - Rewritten for actual AppDaemon YAML dashboard system
- **troubleshooting.md** - Updated for rule-based system (removed AI/ML references)
- **Removed** - `ai_operation_guide.md` (contained incorrect AI/ML information)

### 💡 System Clarification
- **Rule-Based Logic** - System uses sophisticated rule-based irrigation logic, not AI/ML
- **Statistical Analysis** - Uses scipy.stats for trend analysis and sensor validation
- **AppDaemon Requirement** - AppDaemon needed for automatic phase transitions and advanced features
- **Core Integration** - Works standalone for manual control, AppDaemon adds automation

### 🏗️ Code Quality Improvements
- **Helper Classes** - Introduced `ShotCalculator` to eliminate code duplication
- **Constants** - Replaced magic numbers with named constants in `const.py`
- **Version Consistency** - Standardized version strings across all files
- **Import Optimization** - Fixed missing imports and standardized patterns

### ⚠️ Truth in Documentation
- **No More AI Claims** - Removed all references to machine learning and AI capabilities
- **Accurate Feature List** - Documentation now reflects actual implemented features
- **Realistic Expectations** - Clear distinction between manual and automated operation modes
- **Beginner Focus** - All guides rewritten for new users with no assumptions

---

## [2.3.0] - 2024-12-26

### 🚀 Major Features
- **Full GUI Configuration** - Complete zone and sensor setup through Home Assistant UI
- **Zero Dependencies** - Removed ALL external Python packages (numpy, pandas, scipy, plotly)
- **Clean Architecture** - Removed all redundant scripts and command line tools
- **Fixed Phase Logic** - P3 now correctly persists through entire lights-off period
- **System-wide Light Controls** - Removed illogical per-zone light controls

### 🗑️ Removed (Cleanup)
- `fix_appdaemon_requirements.sh` - No longer needed, zero dependencies
- `requirements.txt` - System uses only standard Python libraries
- `configure_crop_steering.py` - Replaced by GUI configuration
- `advanced_crop_steering_dashboard.py` - Uses YAML dashboards instead
- Command line dependency for zone configuration

### ✨ Improvements
- **GUI Config Flow** - Advanced setup with sensor configuration for each zone
- **YAML Dashboards** - AppDaemon native dashboards without Plotly
- **Async/Await Fixes** - Proper coroutine handling in AppDaemon
- **Sensor Fusion** - Fixed VWC/EC mixing issue
- **State Machine** - Clean phase management implementation

### 📝 Documentation
- Updated README to v2.3.0 with GUI configuration
- Removed all references to deprecated scripts
- Added proper crop steering terminology explanations
- Marked zone_configuration_helper.py as deprecated

### ⚠️ Breaking Changes
- None - existing configurations continue to work

## [2.1.1] - 2024-12-21

### 🔄 AppDaemon v15+ Compatibility Update
- **Updated all documentation** for AppDaemon v15+ directory changes
- **Fixed file paths** from `/config/appdaemon/` to `/addon_configs/a0d7b954_appdaemon/`
- **Enhanced fix script** to auto-detect AppDaemon version and paths
- **Added migration guide** for upgrading from AppDaemon v14 to v15+
- **Updated installation instructions** with correct Samba share paths

### 📝 Documentation Updates
- `docs/installation_guide.md` - Updated for AppDaemon v15+ paths
- `docs/appdaemon_v15_migration.md` - NEW comprehensive migration guide
- `docs/dynamic_zones_guide.md` - Added AppDaemon v15+ compatibility notes
- `fix_appdaemon_requirements.sh` - Enhanced to handle both old and new paths
- `README.md` - Updated setup instructions for AppDaemon v15+

### 🔧 Technical Changes
- **Auto-detection** of AppDaemon directory structure in scripts
- **Backward compatibility** maintained for AppDaemon v14 and earlier
- **Improved error messages** for missing AppDaemon directories
- **Updated Samba share paths** in all documentation

### ⚠️ Important Notes
- **If using AppDaemon v15+**: Files are now in `/addon_configs/a0d7b954_appdaemon/`
- **Samba access**: Use `\\YOUR_HA_IP\addon_configs\a0d7b954_appdaemon`
- **Migration required**: Run updated scripts to move files to correct locations

---

## [2.1.0] - 2024-12-21

### 🚀 Major Features Added
- **Dynamic Zone Configuration** - Support for 1-6 irrigation zones (previously hardcoded to 3)
- **Interactive Zone Setup Tool** - `zone_configuration_helper.py` for easy zone configuration
- **AppDaemon Compatibility Fix** - `fix_appdaemon_requirements.sh` resolves scikit-learn installation issues
- **Flexible Entity Creation** - Automatic generation of sensors and switches per configured zone

### ✨ New Components
- `zone_config.py` - Zone configuration parser and validator
- `zone_configuration_helper.py` - Interactive setup wizard
- `fix_appdaemon_requirements.sh` - AppDaemon compatibility fix script
- `docs/dynamic_zones_guide.md` - Complete zone configuration documentation
- `services.yaml` - Proper service documentation

### 🔧 Enhancements
- **Config Flow Improvements** - Two setup modes: automatic (from env file) or manual (UI wizard)
- **Service Updates** - Dynamic zone validation in irrigation services
- **Entity Scaling** - All components now create entities per configured zone
- **Error Handling** - Improved validation and graceful error handling
- **Documentation** - Updated all guides for v2.1.0 features

### 🐛 Bug Fixes
- Fixed hardcoded zone iteration in AppDaemon modules
- Resolved entity creation for zones 2+ (previously only zone 1 worked)
- Fixed service validation to accept configured zones instead of hardcoded 1-3
- Removed obsolete package references in config flow
- Fixed sensor averaging to use actual configured sensors

### 🏗️ Architecture Changes
- **Zone Detection** - Dynamic zone discovery from configuration
- **Entity Generation** - Runtime entity creation based on zone count
- **AppDaemon Integration** - Removed hardcoded zone loops
- **Configuration Management** - Centralized zone config through new parser

### 📊 Per-Zone Entities Created
For each configured zone:
- `switch.crop_steering_zone_X_enabled` - Zone enable/disable
- `switch.crop_steering_zone_X_manual_override` - Manual control
- `sensor.crop_steering_vwc_zone_X` - Average VWC for zone
- `sensor.crop_steering_ec_zone_X` - Average EC for zone  
- `sensor.crop_steering_zone_X_status` - Zone operational status
- `sensor.crop_steering_zone_X_last_irrigation` - Last irrigation timestamp

### 🔄 Migration Notes
- Existing 3-zone setups continue working without changes
- New installations can configure any number of zones 1-6
- Zone configuration now centralized in `crop_steering.env`
- Helper scripts automate setup process

### ⚠️ Breaking Changes
- None - fully backward compatible with existing installations

### 🔮 Future Enhancements
- Zone grouping for simultaneous irrigation
- Zone-specific crop profiles
- Individual zone scheduling
- Water usage tracking per zone

---

## [2.0.0] - 2024-12-15

### 🚀 Major Release - Complete System Overhaul
- **New Architecture** - Integration + AppDaemon AI modules (replaced package-based approach)
- **Advanced AI Features** - Machine learning, sensor fusion, dryback detection
- **Professional Dashboard** - Real-time Plotly visualizations
- **Quality Assurance** - Complete code validation and optimization
- **Production Ready** - Comprehensive testing and error handling

### ✨ AI Features
- **Machine Learning Engine** - Predictive irrigation with ensemble models
- **Intelligent Sensor Fusion** - Multi-sensor validation with outlier detection
- **Advanced Dryback Detection** - Peak detection algorithms
- **Intelligent Crop Profiles** - Strain-specific optimization

### 🏗️ Architecture
- **Home Assistant Integration** - Native HA integration with config flow
- **AppDaemon AI Modules** - Advanced machine learning and automation
- **Configuration Management** - File-based hardware configuration
- **Real-time Dashboard** - Professional monitoring interface

### 📚 Documentation
- Complete installation guide for beginners
- AI operation guide
- Dashboard usage guide  
- Troubleshooting documentation

---

## [1.x] - Legacy Versions
Previous package-based implementations. See git history for details.