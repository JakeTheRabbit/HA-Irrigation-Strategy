# Engine code review — findings & status

A full logic review of the AppDaemon engine (`appdaemon/apps/crop_steering/`,
~7,500-line `master_crop_steering_app.py` plus its libs), 2026-06-10.

**Verdict:** the engine is fundamentally sound. The P0→P1→P2→P3→P0 state machine
is clean, the hardware sequence is correctly guarded (valve read-back → emergency
stop, flood guard, runaway-shot watchdog, `finally`-block force-off), and almost
every safety check fails *closed*. The recently fixed P2 EC-ratio path converges
rather than diverges. The items below are the follow-ups the review surfaced.

## Fixed

| ID | File:line | What | Status |
|----|-----------|------|--------|
| **B1** | `master_crop_steering_app.py` `_check_phase_transitions` | A zone in **P0** at lights-off had no path to P3 (the force only matched P1/P2) and stranded in a daytime phase overnight. The lights-off→P3 force is now hoisted above the per-phase chain and covers any daytime phase. | ✅ `cb2a707` |
| **C5** | `_update_zone_vwc_capacity` | The learned field-capacity max ratcheted up to any reading, unbounded — a stuck-high probe could raise it until the over-water safety block was effectively disabled. Now capped at a 95% saturation ceiling. | ✅ `cb2a707` |

## Open — decisions, not mechanical fixes

### B2 — the ML prediction layer is dead code (and mis-advertised)
`ml_irrigation_predictor.py` `predict_irrigation_need()` returns keys
(`irrigation_need`, `confidence`, `model_status`, …) that **none** of its
consumers read. Every consumer in `master_crop_steering_app.py` looks for keys
the predictor never emits:
- `_get_ml_irrigation_predictions` gates on `prediction_available` → never present → always `None`.
- `_make_irrigation_decision` reads `model_confidence` → absent.
- `_evaluate_ml_decision` reads `analysis.max_irrigation_need` / `irrigation_urgency` → absent.
- `_update_ml_predictions` publishes `analysis.max_irrigation_need` → always 0.

**Net:** ML never influences a decision and `sensor.crop_steering_ml_*` publish
0/garbage. It fails safe — the deterministic phase logic carries everything — but
the "machine-learning irrigation prediction" claimed in the README/CLAUDE.md is
**non-functional**. The system is a deterministic threshold + EC-stacking engine.

**Decision needed:** either (a) reconcile the key contract and make ML actually
contribute, or (b) formally retire the ML path and stop advertising it. Until
then the docs have been corrected to describe the engine as deterministic.

### Dead / duplicate code to remove (all 0 call sites unless noted)
A cleanup pass on these would materially shrink the file and remove
"which of these duplicate defs actually runs?" confusion. Deferred because the
engine has no in-repo test harness and changes deploy supervised to a live grow.

- `_get_phase_icon` defined **twice** (the later def shadows the earlier — one is dead).
- `_get_zone_group` and `_get_zone_priority` each defined **twice** (later wins).
- `_select_emergency_zone` — superseded by `_select_emergency_zone_from_integration` (the only one called).
- `_should_zone_start_p3_simple` — 0 call sites.
- `_calculate_optimal_p3_timing`, `_calculate_historical_p3_timing` — 0 call sites (the live path uses `_should_zone_start_p3`).
- `_check_phase_transitions` stub — a disabled `pass` no-op still scheduled on a 300 s timer; remove the stub + its `run_every`.
- `_get_irrigation_count_24h` — hardcoded placeholder returning a constant; only feeds the dead ML path.
- `MLIrrigationPredictor` alias in `ml_irrigation_predictor.py` — unused.

### Lower-severity logic concerns (review, not urgent)
- **C1** — one *global* `min_irrigation_interval` cooldown gates a multi-zone system; after any zone fires, others can't be evaluated for ~5 min. Fine on a single-manifold 3-zone rig, a scaling smell beyond that.
- **C3** — the EC-stack rescue band (`ec ≥ max_ec − 1.0`) and the hard max-EC block (`ec ≥ max_ec`) leave a 1.0 mS/cm seam: an EC observed *at/above* the ceiling still can't get a dilution shot. Consider letting an explicit `dilute` shot bypass only the max-EC block (never field-capacity) when VWC has headroom.
- **C10** — a dead EC probe silently disables EC steering *and* the per-zone max-EC software pre-check for that zone (every consumer guards `if ec is None`). Unlike VWC, there's no failover/alert. Add a stale-EC advisory.
- **Default drift** — the same logical threshold has different hardcoded fallbacks across paths (P3 emergency VWC 40 vs 45; field-capacity 60 vs 70 vs 80). These only bite when the HA number entity is missing, but they should be unified to one source of truth.

## Doc corrections made
- README/CLAUDE no longer claim functional ML; the engine is described as a deterministic threshold + EC-stacking controller with an (inert) ML scaffold.
- The "lights-off forces any zone to P3" invariant is now actually true (B1).
