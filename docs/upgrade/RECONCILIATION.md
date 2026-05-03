# RootSense plan ↔ Gap-analysis reconciliation

Two upgrade documents now coexist on this branch:

- `ROOTSENSE_v3_PLAN.md` — full design and 5-phase roadmap (this PR series).
- `GAP_ANALYSIS_2026-05.md` — module gap snapshot + prioritised To-Do list.

They are complementary, not competing. The gap analysis is the *tracker*;
the RootSense plan is the *design*. This file says where each gap-analysis
item lands in the RootSense phase plan, so we don't double-implement or
forget anything.

## Cross-reference table

| Gap-analysis item | Priority | Where it lands in RootSense plan |
|---|---|---|
| Isolate pure calculations from HA runtime for stable unit tests | P0 | Done — `calculations.py` + `tests/conftest.py` (PR #6, codex). Foundation for `tests/intelligence/*` in Phase 1. |
| Consolidated gap analysis & implementation backlog document | P0 | Done — `GAP_ANALYSIS_2026-05.md`. RootSense plan links to it as the live tracker. |
| Update README with link to gap analysis & execution order | P0 | Done — codex commit. README also gets a RootSense section in Phase 5. |
| Per-module enable/disable entities for all intelligence modules, exposed in blueprints | P1 | **Phase 1** — added now: 5 `switch.crop_steering_intelligence_*_enabled` entities + recorder includes. Blueprints in Phase 5. |
| Incident report generator (markdown/json) from anomaly events with remediation steps | P1 | **Phase 4** — `agronomic.RunAnalytics` already plans to roll up anomalies into the nightly run report's remediation block; gap-analysis ask is just to also serialise the same data as a standalone markdown/json artifact. Will reuse the same code. |
| Validation suite for climate↔substrate model drift and confidence thresholds | P1 | **Phase 3** — paired with `agronomic.ClimateSubstrateModel` and the VPD-ceiling sensor. |
| Replay/simulation mode for historical day runs | P2 | **Phase 4 → 5** — extend `OptimisationLoop` with a "shadow" mode that consumes the SQLite store instead of live events. Useful both for rollout and for tuning. |
| Deterministic integration tests for phase transitions and emergency shots | P2 | **Phase 1 onwards** — covered incrementally. Each phase ships unit tests in `tests/intelligence/`; integration tests using the existing test-helper harness arrive in Phase 5. |
| Dashboards for anomaly root-cause timelines and comparative zone diagnostics | P2 | **Phase 4** — anomaly-history dashboard + peer-zone comparison view, alongside `dashboards/rootsense_history.yaml`. |

## Execution order, after this commit

1. **Phase 1** (this PR, in progress) — RootZone wiring, module-enable switches, recorder includes.
2. **Phase 2** — Adaptive Irrigation: cultivator-intent slider goes live, `OptimisationLoop` arms in shadow mode.
3. **Phase 3** — Agronomic: transpiration sensors, VPD ceiling, climate-substrate validation suite.
4. **Phase 4** — Orchestration coordinator takes hardware control; anomaly incident-report generator surfaces in HA UI.
5. **Phase 5** — Blueprints, dashboards, MIGRATION.md, version bump to 3.0.0.

The gap-analysis P0 items are complete. Everything else from the gap
analysis is folded into RootSense Phases 1-4 above.
