# Crop Steering Feature List and TODO

This is the public-facing feature and roadmap summary for the Home Assistant Crop Steering project.

## Core Features

- Home Assistant custom integration for crop-steering setup, entities, sensor fusion, calculations, recipes, and diagnostics.
- Home Assistant add-on (`f2-control`) that performs the live irrigation decisions and is the only layer that actuates valves.
- Pure Python decision engine in `crop-steering-engine/`, with offline tests and no Home Assistant dependency.
- Per-zone P0/P1/P2/P3 phase machine with independent VWC, EC, dryback, emergency floor, and shot targets.
- Multi-room support: add the integration once per room, keep isolated hardware maps, per-room kill switches, and per-room state.
- Multi-probe VWC/EC fusion per zone, including list-based probe mapping and fallback support for older front/back mappings.
- Source-water gate for reservoir pH and EC, with fail-closed behavior when configured probes are unavailable.
- Fail-closed hardware sequencing with pump/mainline/zone valve ordering and valve-close readback.
- Daily volume caps, maximum shot-duration caps, emergency rescue handling, and lights-on watchdog protection.
- Live shot sizing from real substrate volume, plant count, drippers per plant, and dripper flow rate.
- Named-stage recipes for Veg, Transition, Bulk, and Ripen setpoint bundles.
- Vmax advisory sensors that report the field-capacity ceiling each zone actually reaches.
- Operator dashboards served by the add-on over Home Assistant ingress, plus standalone demo mode.
- Mobile-friendly one-page overview for quick checks and manual controls.
- Activity feed and setup health checks that surface actionable operator problems.
- GitHub Pages demo pages and checked-in screenshots for evaluating the UI before installing.

## Recent Fixes in This Branch

- Reload config entries when integration options are changed, so edited zone/hardware settings are applied without restarting Home Assistant.
- Merge `entry.options` over `entry.data` during setup, so option-flow changes are not reloaded into stale base config.
- Remove the dead `irrigation_efficiency` sensor descriptor that always produced `unknown`.
- Keep the previously removed `dryback_percentage` placeholder out of the integration-owned descriptors so the add-on remains the owner of that engine-published sensor.
- Add regression tests for options-over-data config merging and dead placeholder sensor descriptors.

## Screenshots

| Status | Zones | Plan |
|---|---|---|
| ![Status](../img/demo-status.png) | ![Zones](../img/demo-zones.png) | ![Plan](../img/demo-plan.png) |

| Tune | Climate | Operate |
|---|---|---|
| ![Tune](../img/demo-tune.png) | ![Climate](../img/demo-climate.png) | ![Operate](../img/demo-operate.png) |

## TODO

- Add add-on build/schema validation to CI so the active actuator package is tested as directly as the integration and pure engine.
- Keep tightening config-flow coverage around full hardware mapping, old installs, and option-flow edits.
- Replace any remaining standalone dashboard long-lived-token workflows with ingress-first or tokenless patterns where possible.
- Continue reducing hardcoded facility defaults so the public install path stays generic.
- Add richer Home Assistant Repairs checks for missing probes, unavailable fused sensors, kill-switch setup, and add-on heartbeat state.
- Add browser-level dashboard regression checks for the main demo tabs.
- Publish a clearer release checklist covering monorepo changes, the dedicated `f2-control` add-on repo sync, screenshots, and changelog updates.
- Expand docs for first-day commissioning, safe dry-run validation, and how to verify the first live irrigation cycle.
