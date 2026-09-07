# Validated feature matrix

Validation date: 8 September 2026. This describes the unreleased working tree. **Local verification** means automated tests against source, compiled browser artifacts and fake/mocked HA. It does not mean the changes are installed on a running HA system or that physical water delivery has been verified.

| Feature | Result | Evidence and limits |
| --- | --- | --- |
| Native Home Assistant appearance | Implemented; locally tested | Same-origin iframe inherits theme variables and reacts to host theme changes. Roboto and its license are bundled. Explicit light/dark overrides and standalone fallback are supported. Cross-origin inheritance is unavailable by browser design. |
| All advanced pages in one workspace | Implemented; browser tested | Ten routes share navigation, room context, responsive layout and draft protection. Historical URLs redirect to current routes; archived full dashboards are not active product pages. |
| Combined recorded VWC + EC history | Implemented; browser tested | Independent axes/units, zone selection, HA Recorder data and honest missing-history states. Sensor history requires Recorder retention. |
| Reactive combined planning curve | Implemented; browser and unit tested | Selected day/zone profile drives both lines and controls. P0 reference/drop, P1 targets/cadence, P2 target/band, P3 emergency floor. No invented overnight trend or crop-response forecast. |
| Continuous vegetative/generative steering | Implemented; both legacy modes tested | Explicit endpoint profiles interpolate and quantize against HA parameter bounds/steps; canonical scheduled dryback/EC overrides work regardless of the old mode select. Endpoints need grower review. |
| Different setpoints per zone | Implemented; locally tested | Per-zone profiles, active targets and pot/dripper sizing; room-level parameters remain shared where appropriate. |
| Whole-grow day/week schedule | Implemented; browser and unit tested | Days1–366, independent zone start dates, inclusive range splitting, weekly overview, daily exceptions, import/export and explicit plan-zone synchronization after setup changes. |
| Persistent plans and safe activation | Implemented; fake-HA tests and independent review | Draft storage, revision conflicts, preview, explicit arming, next lights-on activation/disarm, coherent expiring snapshots and durable required-plan holds. Actual HA timer/restart commissioning remains outstanding. |
| Room and zone creation/removal | Implemented; flow/API/browser tested | Removal archives stable IDs; restoration preserves identifiers. No automatic renumbering or reuse. Engines and implicated equipment must be readable OFF for mapping mutations. |
| Sensor mapping | Implemented; locally tested | Search existing HA entities by name/ID and inspect readings/units; multi-probe VWC/EC selection. Backend validates domains, units and conflicting valve roles. Device pairing/firmware provisioning is external. |
| Installation shortcuts and sidebar | Implemented; package/registration tests | HACS/config-flow/app-repository links and automatic integration sidebar. HA confirmations, integration restart, published source and hardware mapping are still required. A complete live HACS/Supervisor install was not run. |
| Delivery preview and catch-test calculator | Implemented; unit/browser tested | Pot/plant/dripper math, nominal and capped duration, actual low-flow parity. Catch-test output is a local proposal; no automatic calibration write or proof of flow. |
| Sensor diagnostics and equipment map | Implemented; browser tested | Measured values, freshness/coverage and configured devices; no unsupported yield/potency score. |
| Reviewed manual setpoint writes | Implemented; mocked-HA browser tested | Explicit selected-room scope, bounds/steps, service calls and readback; partial failures retain drafts. Active plans lock conflicting manual target edits. |
| Source-water/interlock/volume/duration gates | Implemented; controller regressions | Includes request-latency duration accounting, blind-path caps, shared-hardware fault latch and recovery. Physical valve/pump behavior remains unverified. |
| Activity view and CSV export | Implemented with evidence limits | Exports available controller/state information. This is not a complete immutable history of all physical irrigation events. |
| Legacy manual-shot/phase-override events | Not validated as actuator commands | Existing services can publish events; this controller is not proven to consume those events. The new UI does not claim these are working physical controls. |
| Tank dosing and climate actuation | Not implemented by this controller | EC values are root-zone references, not tank dosing commands. Environment controls remain external HA workflows. |
| Yield/potency prediction or autonomous crop optimisation | Not implemented | Removed misleading claims from the active UI. Neither setpoints nor a schematic establish expected yield. |
| Live production readiness | Not yet verified | No deployment, restart, engine enable, live setpoint write or physical irrigation test was performed during this refactor. |

## Improvements that are now practical

- Plan every zone across the grow without rewriting daily setpoints by hand.
- See what a steering change means before saving, including actual hydraulic assumptions.
- Use one curve for planning and a separate combined history for measured behavior.
- Keep room/zone identities stable as a facility changes.
- Detect unsupported/stale control snapshots and setup adoption gaps instead of displaying false success.
- Check dripper output locally and review the proposed correction before changing configuration.

## Valuable next additions

Measured-flow reconciliation is the strongest next step: compare commanded litres with independent water-meter deltas and identify blocked/leaking lines. Next, align recorded shot events with VWC/EC history, then compare planned versus observed dryback over repeated days. Reliable measurements would support proposal-only recipe adjustments and cultivar-specific profiles. Those features require clean real observations and have not been claimed as implemented here.

## Evidence

- [Final validation record](audits/2026-09-08-validation.md)
- [Setup API/flow and sidebar](audits/2026-09-08-setup.md)
- [Strategy implementation and runtime contracts](audits/2026-09-08-strategy.md)
- [Strategy independent review](audits/2026-09-08-strategy-review.md)
- [Workspace independent review](audits/2026-09-08-workspace-review.md)
- [Theme/history/planning chart](audits/2026-09-08-theme-chart.md)
- [Insights and calibration](audits/2026-09-08-insights.md)

Reproduce the checks using [TESTING.md](../TESTING.md). Machine-readable browser results and screenshots are generated in the ignored output/playwright folder. The archive retains older reports as dated historical evidence.
