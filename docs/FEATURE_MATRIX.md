# Validated feature matrix

Validation date: 8 September 2026. The workspace is published and an existing two-room, six-zone Home Assistant installation has been upgraded through HACS and Supervisor. Automated tests cover source, compiled browser artifacts and mocked HA. Live checks cover startup, retained settings, controller adoption and the native dashboard. Physical water delivery and a complete grow-day recipe handoff have not been commissioned. See the [live upgrade record](audits/2026-09-08-live-upgrade.md).

| Feature | Result | Evidence and limits |
| --- | --- | --- |
| Native Home Assistant appearance | Implemented; locally tested | Same-origin iframe inherits theme variables and reacts to host theme changes. Roboto and its license are bundled. Explicit light/dark overrides and standalone fallback are supported. Cross-origin inheritance is unavailable by browser design. |
| All advanced pages in one workspace | Implemented; browser tested | Eleven routes share navigation, room context, responsive layout and draft protection. Historical URLs redirect to current routes; archived full dashboards are not active product pages. |
| Combined recorded VWC + EC history | Implemented; browser tested | Independent axes/units, zone selection, HA Recorder data and honest missing-history states. Sensor history requires Recorder retention. |
| Manual preview beside phase controls | Implemented; browser and unit tested | Numeric edits and draggable targets share one local draft; saved VWC/EC and P3 floor remain visible. Exact HA bounds, mode mapping, active-plan read-only state, room/zone isolation and mobile layout are checked. |
| Run comparison with daily target overlays | Implemented; browser, unit and metadata-service tested | Day/week/month/run-to-date/custom Recorder ranges; previous run aligned to grow age; repeated full-day target references clipped at now. Stored references are timestamped, not a historical setpoint audit. Retention gaps, stale carry-in, daylight saving, request cancellation and room scope are covered. |
| Reactive combined planning curve | Implemented; browser and unit tested | Selected day/zone profile drives both lines and controls. P0 reference/drop, P1 targets/cadence, P2 target/band, P3 emergency floor. No invented overnight trend or crop-response forecast. |
| Continuous vegetative/generative steering | Implemented; both legacy modes tested | Explicit endpoint profiles interpolate and quantize against HA parameter bounds/steps; canonical scheduled dryback/EC overrides work regardless of the old mode select. Endpoints need grower review. |
| Different setpoints per zone | Live preservation verified | The 2.14.0 upgrade retained all 303 captured numeric settings and 397 total captured controls after engine-state restoration. Room/zone sizing and mappings are preserved. See the [visible-steering audit](audits/2026-09-08-visible-steering.md). |
| Whole-grow day/week schedule | Implemented; browser and unit tested | Days1–366, independent zone start dates, inclusive range splitting, weekly overview, daily exceptions, import/export and explicit plan-zone synchronization after setup changes. |
| User-authored recipe library | Unit and compiled browser tests pass | Starts empty; named plan copies remain separate by room and demo/live mode. Loading is a local draft operation with zone/date protection and existing validation/review. Import bounds, storage corruption and HTTP LAN UUIDs are covered. No source-guide numerical presets are included. See [library and references](RECIPE_LIBRARY.md). |
| Persistent plans and safe activation | Implemented; fake-HA tests and independent review | Draft storage, revision conflicts, preview, explicit arming, next lights-on activation/disarm, coherent expiring snapshots and durable required-plan holds. Live draft reads and controller capability are verified. Recipe activation and a full lights-on handoff remain uncommissioned. |
| Room and zone creation/removal | Implemented; flow/API/browser tested | Removal archives stable IDs; restoration preserves identifiers. No automatic renumbering or reuse. Engines and implicated equipment must be readable OFF for mapping mutations. |
| Sensor mapping | Implemented; locally tested | Search existing HA entities by name/ID and inspect readings/units; multi-probe VWC/EC selection. Backend validates domains, units and conflicting valve roles. Device pairing/firmware provisioning is external. |
| Installation shortcuts and sidebar | Live in-place upgrade verified | HACS download, Supervisor app update, HA restart, both room entries loading and the automatic native sidebar passed. First installation on a blank HA instance remains untested. |
| Water per zone, plant and proposed runtime | Implemented; unit/browser/controller tested | Total zone litres, average mL per plant and substrate capacity are distinct. Runtime and phase estimates include engine bounds, duration caps, minimum time and truncation; P1 budgets remain conditional. New counters freeze configured flow per shot and use elapsed runtime, including partial aborts. Old totals are preserved. Missing producer data remains unknown. |
| Catch-test calculator | Implemented; unit/browser tested | Catch-test output is a local proposal; no automatic calibration write or proof of flow. |
| Sensor diagnostics and equipment map | Implemented; browser tested | Measured values, freshness/coverage and configured devices; no unsupported yield/potency score. |
| Reviewed manual setpoint writes | Implemented; mocked-HA browser tested | Explicit selected-room scope, bounds/steps, service calls and readback; partial failures retain drafts. Active plans lock conflicting manual target edits. |
| Source-water/interlock/volume/duration gates | Implemented; controller regressions | Includes request-latency duration accounting, blind-path caps, shared-hardware fault latch and recovery. Physical valve/pump behavior remains unverified. |
| Missing or invalid EC | Implemented; controller/core regressions | Unscaled base VWC watering, suspended EC learning/offset application and degraded status. Salt protection is unverified until EC returns. Configured feed-water gates still apply. |
| Sensor fusion | Implemented; arithmetic mean | Finite readings are averaged. No automatic outlier rejection or probe weighting is claimed. |
| Timed manual override | Implemented; lifecycle/service tests | Per-room/zone deadline expires and survives graceful restart/reload. Retrigger/direct switch changes cancel obsolete callbacks. Noncanonical entity IDs are rejected because the controller consumes canonical IDs. Abrupt power-loss persistence follows HA RestoreEntity checkpoints. |
| Weekly water usage | Implemented; migration/rollover tests | Seven grow-day controller delivery estimates, including partial aborts; old/missing history is marked incomplete. External irrigation and measured flow are not included. |
| Activity view and CSV export | Implemented with evidence limits | Exports available controller/state information. This is not a complete immutable history of all physical irrigation events. |
| Legacy manual-shot/phase-override events | Not validated as actuator commands | Existing services can publish events; this controller is not proven to consume those events. The new UI does not claim these are working physical controls. |
| Tank dosing and climate actuation | Not implemented by this controller | EC values are root-zone references, not tank dosing commands. Environment controls remain external HA workflows. |
| Yield/potency prediction or autonomous crop optimisation | Not implemented | Removed misleading claims from the active UI. Neither setpoints nor a schematic establish expected yield. |
| Live deployment | Verified with stated limits | Running controller source matches the published package. Saved counters and learned state are retained, heartbeats and setup acknowledgements are healthy, and prior engine states were restored. No new recipe was armed and no physical irrigation test was triggered. |

## Improvements that are now practical

- Plan every zone across the grow without rewriting daily setpoints by hand.
- See what a steering change means before saving, including actual hydraulic assumptions.
- Use one curve for planning and a separate combined history for measured behavior.
- Keep room/zone identities stable as a facility changes.
- Detect unsupported/stale control snapshots and setup adoption gaps instead of displaying false success.
- Check dripper output locally and review the proposed correction before changing configuration.

## Valuable next additions

Measured-flow reconciliation is the strongest next step: compare commanded litres with independent water-meter deltas and identify blocked/leaking lines. Next, align recorded shot events with VWC/EC history, then quantify planned versus observed dryback over repeated days beyond the available visual comparisons. Reliable measurements would support proposal-only recipe adjustments and cultivar-specific profiles. Those features require clean real observations and have not been claimed as implemented here.

## Evidence

- [Visual editing, water and run comparison validation](audits/2026-09-08-visible-steering.md)
- [Live upgrade and retained settings](audits/2026-09-08-live-upgrade.md)
- [Release corrections and validation](audits/2026-09-08-release-validation.md)
- [Branch feature consolidation](audits/2026-09-08-branch-consolidation.md)
- [Final validation record](audits/2026-09-08-validation.md)
- [Setup API/flow and sidebar](audits/2026-09-08-setup.md)
- [Strategy implementation and runtime contracts](audits/2026-09-08-strategy.md)
- [Strategy independent review](audits/2026-09-08-strategy-review.md)
- [Workspace independent review](audits/2026-09-08-workspace-review.md)
- [Theme/history/planning chart](audits/2026-09-08-theme-chart.md)
- [Insights and calibration](audits/2026-09-08-insights.md)

Reproduce the checks using [TESTING.md](TESTING.md). Machine-readable browser results and screenshots are generated in the ignored output/playwright folder. The archive retains older reports as dated historical evidence.
