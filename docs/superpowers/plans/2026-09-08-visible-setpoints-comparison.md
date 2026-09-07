# Visible setpoints, run comparisons and delivery quantities

The user requested implementation: show a reactive full-day VWC/EC graph while editing parameters, compare actual days/weeks/months/runs with targets and previous runs, and show clear zone and per-plant water quantities. Standing user instructions authorize sensible reversible decisions without another approval round. Work remains on main as requested; private untracked rescue pages remain untouched.

## Scope and acceptance

1. Manual setpoints: selected zone/mode controls share values with the graph. P3 emergency floor moves when its number changes. Saved and draft targets can be distinguished. Phase controls and the graph remain usable together at desktop and mobile widths. Draft review/write safeguards remain intact.
2. Run comparisons: persistent room-scoped run metadata with names/dates and captured sensor/target references. Day, week, month, run-to-date and date-range views. Previous runs align by grow age and do not include later growth than the current selection. Recorded VWC and EC retain independent units and gaps. No target reference is presented as historical control evidence or predicted crop response.
3. Water: zone-total recorded daily estimate, average per plant, configured runtime-to-volume estimates for a plant and the complete zone, effective duration limits and a local runtime calculator. Substrate capacity is explicitly distinct. P2/P3 shot counts and whole-day delivery are not invented.
4. Controller accounting correction: retain commanded durations and gates, but account for their effective duration after cap/truncation/minimum. Existing saved totals are preserved; no retrospective correction without records.

## Work ownership

- Manual editor and planning visualization: live_code_reconciliation.
- Run metadata/history/comparison UI: branch_feature_audit.
- Delivery mathematics and water UI: controller_issue_fixes.
- Navigation, accounting regression, integration tests, documentation and publication: root.

## Validation

Use domain regressions for mode/room isolation, invalid and missing inputs, date/timezone boundaries, request cancellation, reference provenance, Recorder gaps, numeric cap arithmetic and partial aborted shots. Exercise the compiled dashboard for P3 line reactivity, saved overlay, zone scope, comparison navigation and 390px accessibility. Run frontend tests/build/browser workflows, backend tests/lint and packaging/version checks before publication. Live read-only checks must distinguish software deployment from physical water delivery. Installation must preserve current settings and engine states.
