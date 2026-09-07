# Visible setpoints, run comparisons and water accounting

Release: integration 2.14.0 with controller 0.13.0. Validation date: 8 September 2026.

## Implemented behavior

- Manual phase controls share a local draft with the full-day VWC/EC graph. Saved controller curves remain visible. P3 emergency-floor edits move that line without fabricating a new daytime moisture response. Mode-dependent targets, exact native bounds, room/zone isolation, invalid fields and active-plan ownership are covered.
- Compare day, week, calendar month, run-to-date or custom dates. Prior runs align by grow age and stop at the same elapsed progress. Current configured or captured daily targets repeat at local lights-on, with DST-aware placement and explicit missing/overnight segments.
- Run metadata persists per integration entry, uses canonical room and zone identity, bounded imports and revision conflicts. Renaming/backdating does not overwrite the original captured reference. These references are not historical records of every target actually applied. Sensor readings remain in HA Recorder.
- Zone water totals include all configured plants; daily mL per plant is an average. Pot capacity is labelled separately. Local runtime and phase calculators show configured requests, engine parameter clamps and effective duration/volume. P1 budgets are conditional, with no invented P2/P3 shot counts.
- Controller accounting uses the flow captured before a shot and actual elapsed runtime. Duration caps, truncation, minimum time, partial aborts and in-flight sizing changes are covered. Existing persistent totals are preserved; no retrospective correction is fabricated.
- Missing daily producer data remains unknown rather than falsely reporting zero. An actual zero remains valid.

## Validation

- Frontend: 131 unit tests, TypeScript and bundled production build pass.
- Integration/repository: 222 tests pass, one existing optional fixture test skipped.
- Actual controller module with fake HA and deterministic time: 89 tests pass.
- Pure decision core: 54 tests pass; vendored runtime core is unchanged.
- Browser suites exercise all eleven routes, strict mocked-HA contracts, reviewed writes, saved/draft graph geometry, hydraulic arithmetic, run lifecycle/comparison/export, setup, draft guards, keyboard accessibility, native theme inheritance and 390px mobile layouts.
- Ruff, Black and YAML checks pass. Generated dashboards match across integration, controller and web distribution.

Independent review reproduced and fixed four comparison defects: stale Recorder carry-in counted as fresh readings; targets captured from a newer unpublished snapshot; wrong legacy mode fallback; native timeout requests exceeding intended concurrency. Further review fixed daily false-zero fallback, per-shot sizing races, phase parameter clamp disclosure and keyboard/definition-list accessibility.

A fast edit followed immediately by browser Back exposed a navigation race. Dirty-state reporting now uses layout effects so the parent guard is ready before the next browser event. The original browser regression passes without an added wait.

Browser evidence is reproducible using docs/TESTING.md. Current product screenshots are in img/manual-setpoints.png and img/run-comparison.png, alongside refreshed overview/planner/setup captures. Detailed local machine reports remain under output/playwright and output/live-upgrade/visible-steering.

## Boundaries

Planning curves illustrate configured targets; they are not predictions of uptake, EC accumulation or future shot times. Missing Recorder retention cannot be reconstructed. Sparse observations remain isolated points; long unavailable gaps are not connected. Litres are controller/configured-flow estimates, not metered delivery, runoff or crop uptake. This release does not automatically register real runs, arm recipes or change current setpoints.

## In-place installation verification

The published 2.14.0 integration and 0.13.0 controller were installed through HACS and the existing Supervisor app identity on 8 September 2026. GitHub validation, installation, release packaging and Pages deployment all passed.

Before the upgrade, both integration entries, current controls, the controller image and persistent state were backed up. An unsaved browser plan was exported separately and its original tab retained. Both engines were paused and mapped pumps/mainlines/valves read OFF before replacing software. Home Assistant restarted once; both room entries loaded successfully.

Readback matched all 303 existing numeric settings and all 397 captured controls after restoring the previous engine states. Integration data/options, shot counters, daily volume, last-shot/reset records and retained controller state matched their backups. Installed controller Python, decision core and both dashboard copies matched the published source. Both room heartbeats resumed healthy. No recipe was armed and no run dates were invented.

The installed UI loaded recorded VWC and EC for a seven-day window and displayed the daily target reference, range summaries and coverage counts. The public demo loaded independently. These checks validate software and retained data, not physical water delivery.

The UI check identified an older `maximum_shot_duration` entity name which the new calculator did not recognise. Compatibility remediation and its follow-up release are tracked separately; the initial 2.14.0 calculator correctly left that effective estimate unavailable.
