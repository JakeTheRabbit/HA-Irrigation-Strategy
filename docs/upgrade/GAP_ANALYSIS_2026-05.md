# HA Crop Steward — Gap Analysis (May 3, 2026)

## Executive Summary
The repository already contains substantial groundwork for AROYA-like capabilities (root-zone analytics, adaptive irrigation, anomaly hooks, and orchestration modules). However, several gaps remain before production parity: module-level configurability is only partial, second-brain incident workflows are incomplete, and testability is weak outside a Home Assistant runtime.

## Current vs Target Gaps

| Target Module | Current State | Gap | Priority |
|---|---|---|---|
| SUBSTR AIT (root-zone intelligence) | `intelligence/root_zone.py` + dryback modules present | Field-capacity detection needs explicit calibration workflow + dashboard surfacing | High |
| AUTOM AIT (adaptive strategy) | `intelligence/adaptive_irrigation.py` + orchestration available | Intent-driven control loop exists but needs clearer operator controls and guardrail observability | High |
| CULTIV AIT (agronomic intelligence) | `intelligence/agronomic.py` present | Climate-substrate KPIs and transpiration confidence metrics need expanded validation/reporting | Medium |
| IRRIG AIT (irrigation intelligence) | Orchestrator and custom shots implemented | Manual override UX and feed/runoff reconciliation need tighter guided workflows | High |
| Second Brain | `intelligence/anomaly.py` + event bus | No full incident report pipeline/remediation playbooks surfaced in docs/UI | High |

## Production Readiness Gaps (Cross-cutting)
1. **Testing isolation gap**: unit tests depended on Home Assistant imports during collection, blocking CI and local validation.
2. **Roadmap clarity gap**: no single consolidated phase-by-phase implementation tracker tied to the AROYA-equivalent architecture.
3. **Operator handoff gap**: README lacked explicit “what is done / what remains” guidance for production deployments.

## To-Do (Prioritized)

### P0 – Immediate
- [x] Isolate pure calculations from HA runtime for stable unit tests.
- [x] Add consolidated gap analysis and implementation backlog document.
- [x] Update README with direct link to gap analysis and execution order.

### P1 – Near-term
- [ ] Add per-module enable/disable entities for all intelligence modules and ensure they are exposed in blueprints.
- [ ] Implement incident report generator (markdown/json) from anomaly events with recommended remediation steps.
- [ ] Add validation suite for climate↔substrate model drift and confidence thresholds.

### P2 – Hardening
- [ ] Add replay/simulation mode for historical day runs.
- [ ] Add deterministic integration tests for phase transitions and emergency shots.
- [ ] Add dashboards for anomaly root-cause timelines and comparative zone diagnostics.

## Notes
- All recommendations preserve local-only operation and backward compatibility expectations.
- This document is intended to be the authoritative upgrade tracker for the AROYA-equivalent rollout.
