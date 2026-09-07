# Final local validation — 8 September 2026

Scope: the working tree on feat/f2-two-room, based on commit972ae2be6307258c0a5a219ba1f0f414833beaac. This includes the new operator workspace, setup lifecycle, strategy storage/runtime, controller audit fixes, packaging and documentation. Changes are local and uncommitted; no live Home Assistant writes, deployment, restart, engine enable or physical irrigation test was performed.

## Results

| Check | Result |
| --- | --- |
| Integration and controller suites | 177 passed |
| Canonical pure decision engine | 48 passed |
| Frontend unit tests | 55 passed |
| TypeScript and production build | Passed; self-contained HTML in all three distribution locations |
| General demo/browser workflows | 17 groups passed; all ten routes, accessibility, mobile layout, drafts and navigation |
| Mocked HA browser workflows | 10 groups passed; room identity, readback, partial failure, stale/offline states and redirects |
| Extended workspace browser workflows | 9 groups passed; planning, setup, strict service responses, plan-zone sync, native theme inheritance and automatic status refresh with draft protection |
| Ruff | Passed repository-wide, excluding historical archive/generated dependency output |
| Black | Passed integration and tests |
| YAML structural lint | Passed |
| Active-source whitespace check | Passed with CR-at-EOL allowed for Windows files; historical archive bytes are preserved, including original trailing blank lines |
| Engine source/vendor parity | Byte-identical |
| Compiled dashboard distribution parity | Byte-identical in web, controller ingress and integration |
| Integration zip packaging | Created locally; CRC and bundled dashboard verified |

Commands are documented in TESTING.md. Browser artifacts are generated under output/playwright; the installable integration-only zip is output/releases/crop-steering-integration-unreleased-2026-09-08.zip. It requires the matching new controller for autonomous grow plans and is not a published release.

## Independent review

The strategy review found and resolved durable disarm/restart replay, stale later-zone decisions, archived default-room startup and low-flow sizing discrepancies. Follow-ups added a batch hold for changed strategy decisions, exact active-zone coverage, engine-bound catalog parity and unit-correct predictive dryback timing.

The workspace review found and resolved strict disarm payload mismatch, error-state editing, setup draft retention after room changes, mapping-dialog accessibility, stale plan zone lists and misleading overnight graph semantics. The extended browser suite verifies real response shapes rather than treating demo success as backend proof.

See [strategy review](2026-09-08-strategy-review.md), [strategy implementation](2026-09-08-strategy.md), [workspace review](2026-09-08-workspace-review.md), [setup](2026-09-08-setup.md), [theme/chart](2026-09-08-theme-chart.md) and [Insights](2026-09-08-insights.md).

## Delivery and limits

The canonical application is dashboard.html. Fourteen older entry names redirect to current routes with room/demo context preserved. The root app-repository descriptor is present; the old facility config was archived under a filename that Supervisor will not discover as an app. Original full dashboards/guides/tools are retained in archive/2026-09-08 with provenance. User-owned aigrow-ops.html copies remain untouched.

CI now builds the frontend, runs browser workflows and rebuilds the dashboard before release packaging. Real hassfest/HACS validation, Supervisor image build/install, HA timer behavior across daylight-saving boundaries and physical water-delivery commissioning were not run locally. Live HA theme behavior was exercised in a same-origin browser fixture, not a deployed integration.

Read [the validated feature matrix](../FEATURE_MATRIX.md) before treating any historical capability claim as working. Manual-shot/phase-event execution, climate/tank actuation, yield/potency prediction and autonomous recipe optimisation are not advertised as implemented physical controls.
