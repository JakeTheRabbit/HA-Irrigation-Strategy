# Multi-Room Crop Steering — Design Spec

- **Date:** 2026-06-29
- **Status:** Design (brainstorm complete, converged). Not yet planned/implemented.
- **Provenance:** Collaborative brainstorm + a full-repo review (4 parallel readers → synthesis) + a 3-pass dual-model adversarial review (Claude + GPT-5.5). Convergence reached on pass 3 (`still_blocking: []`).
- **Repos:** `HA-Irrigation-Strategy` (monorepo: HA integration `custom_components/crop_steering`, pure `crop-steering-engine`, `addons/f2_control` add-on) and `f2-control` (published add-on mirror).

---

## 1. Goal

The most capable open-source crop-steering system: **multiple independent rooms**, each with **multiple zones**, running a **pluggable feed/steering program** (with the **Athena** feed program as the flagship importable profile), with stage/phase application drivable from **four sources** — manual, scheduled auto-advance, an LLM via API, and follow-another-zone — all behind a single fail-closed safety boundary, presented through a commercial-grade multi-room dashboard with a draggable grow timeline.

Built by evolving the existing repos, keeping the pure `decide()` engine. Shipped in phases (hobbyist-installable → operator features → flagship).

## 2. Key decisions (with the brainstorm trail)

| # | Decision | Notes |
|---|----------|-------|
| D1 | **HA-native foundation** | Integration + `f2-control` add-on + pure `crop_steering_engine`. |
| D2 | **Architecture = B (engine-owns-state)** | *Reversed from an earlier "extend in place only".* The add-on/engine owns programs, overrides, timeline, committed snapshots, and runtime state in its own durable store. HA = sensor-read + valve-write + config wizard + UI. Removes the HA-recorder/state scale ceiling; makes true hundreds-of-zones viable. `decide()` stays pure. |
| D3 | **Rooms are fully independent machines** | Each room owns its pump, mainline, solenoids, VWC/EC probes, lights, feed water + EC/pH gate, kill switch, and state. Nothing shared by default (duplicate-hardware detection + per-entity locks guard the exception). |
| D4 | **Config authored in the HA config-flow wizard** | Hardware config lives in HA config entries (durable). A **versioned roster** (schema_version + generation + checksum + per-room `enabled`) is published for the engine via a config service/endpoint, not a giant sensor-attrs blob. |
| D5 | **Pluggable program schema; split Nutrient vs Steering** | `NutrientProgram` (feed EC/pH/components by stage — Athena = flagship import preset) is distinct from `SteeringProgram` (P0–P3 targets, dryback strategy, shots, windows, steering intent). |
| D6 | **Program = a draggable grow timeline of stages** | Stages are day-span blocks; auto-advance walks the timeline by grow-day. Drill room → zone → stage to edit setpoints. |
| D7 | **Per-setpoint override with explicit revert** | Every setpoint is *program-controlled* or under a *manual hold* with a revert trigger. Unified with apply-timing (§6). |
| D8 | **Four phase/stage application sources + arbitration** | manual / scheduled-auto / LLM-API / follow-zone, resolved into one committed snapshot with per-field attribution. |
| D9 | **Single tier; hydraulic sensors optional** | No hobbyist/commercial split. Flow/pressure/leak are optional first-class hooks. |
| D10 | **Strict backward compatibility** | The existing single-room F2 install upgrades transparently; old `/data/state.json` loads; entity changes additive. |

## 3. Terminology (locked)

- **Stage** — a block on the grow timeline (e.g. Veg, Transition/Stretch, Bulk, Ripen, Flush). Macro, day-scale.
- **Phase** — the intra-day irrigation state machine: **P0** (morning dryback) → **P1** (ramp) → **P2** (maintenance) → **P3** (pre-lights-off). Micro, minute-scale.
- **Room** — an independent irrigation machine (own hardware, lights, feed, kill).
- **Zone** — an irrigated group within a room (own valve + VWC/EC sensors), runs its own P0–P3 cycle.
- **Grow-day** — photoperiod-anchored day index (lights-on / flip date, **not** midnight).
- **Dryback** — `dryback_vwc_points_from_peak`: percentage **points** of VWC below the daily peak (matches the existing engine). Optionally also expose `dryback_pct_of_peak` with explicit formula. No rounding.

## 4. Architecture (B — engine-owns-state)

```
┌────────────────────────────────────────────────────────────────────┐
│ HA INTEGRATION  (custom_components/crop_steering)                    │
│  • config-flow WIZARD: per-room hardware → HA config entries (truth) │
│  • publishes versioned ROSTER (config service/endpoint)              │
│  • number.*/select.*/switch.* = HA-native EDIT + DISPLAY surface     │
│      (edits flow as INTENT; engine writes effective values back)     │
│  • crop_steering.* services = intent-only seam (manual + LLM)        │
└───────────────┬──────────────────────────────────┬─────────────────┘
        sensor reads (batched)            intents (services / API)
                ▼                                  ▼
┌────────────────────────────────────────────────────────────────────┐
│ f2-control ADD-ON  (the brain of record)                            │
│                                                                      │
│  ENGINE STORE (durable, /data): programs, overrides, timeline,      │
│     committed snapshots+generations, runtime counters, faults       │
│                                                                      │
│  SOURCE LAYER → ARBITRATION → EFFECTIVE-SNAPSHOT BUILDER             │
│     sources: manual | scheduled-auto | LLM | follow-zone            │
│     → one committed per-zone snapshot {stage,phase,setpoints,        │
│        per-field source attribution, generation}                    │
│                                                                      │
│  RoomRunner per room (own lights/feed/pump/mainline/kill/zones)     │
│     reads committed snapshot → decide() (PURE, unchanged)           │
│                                                                      │
│  ┌──────────── SINGLE SAFETY COMMAND GATE ────────────┐            │
│  │ sole actuation path; fail-closed: kill, room ARMED, │            │
│  │ feed EC/pH, staleness, daily-cap, max-shot, min-off,│            │
│  │ interlock, valve-close readback, hydraulic faults   │            │
│  └──────────────────────┬──────────────────────────────┘            │
│   per-room irrigation scheduler (concurrency/prime/settle/queue)    │
│  Supervisor: per-room deadlines + watchdog + cancellable IO         │
└───────────────┬──────────────────────────────────┬─────────────────┘
         valve/pump writes                    serves web dashboard
                ▼                                  ▼
            HARDWARE (per room)            multi-room UI + timeline
```

**Why B (vs extend-in-place):** state lives in the engine, not HA's recorder/state machine, so zone count scales with engine loop budget (batched HA sensor reads remain the only HA-side cost), not with HA entity/recorder limits. The committed-snapshot model and single-owner persistence (below) are natural under B.

## 5. Components

### 5.1 RoomRunner
Today's `Controller` refactored to one instance per room. Owns its prefix/`room_id`, hardware map (pump, mainline, valves), zones, lights, feed gate, kill switch, and per-room slice of state. The supervisor (`Controller`) holds N RoomRunners with **per-room deadlines, watchdogs, cancellable IO, and bounded queues** — a hung or slow room fails closed without blocking others. `decide()` is called per zone, unchanged.

### 5.2 Safety command gate (single actuation path)
All sources and the timeline emit **intent only**. The gate is the *only* code that touches hardware. It enforces, fail-closed: kill switch, room ARMED, feed EC/pH band + grace, sensor staleness (every input carries `observed_at`), daily-volume cap, max-shot, min-off, pump/mainline interlock, valve-close readback, and hydraulic faults when sensors exist. Unknown state → closed.

**Service compatibility matrix (M1):** every existing write path is classified and tested — `transition_phase`, `execute_irrigation_shot`, `custom_shot`, `apply_recipe`, `save_recipe`, `set_manual_override`, raw `number.set_value`, dashboard controls → each becomes **intent-only** (routed to gate/resolver), **rejected-if-called-direct**, or **read-only/deprecated**. Tests prove nothing actuates or changes an effective setpoint except through the gate/resolver.

### 5.3 Arbitration + effective-snapshot builder
One builder per zone produces a **committed snapshot** `{stage, phase, setpoints}` with **per-field attribution** `{effective, base, source, source_generation, expiry, reason, observed_at}`. A cross-field consistency validation runs after all sources resolve; an invalid combination falls back to the previous safe snapshot (never a partial apply). Default priority: **manual hold > LLM hold > follow > scheduled-auto > program base**. The engine consumes the committed snapshot (M2), **not** raw `number.*`; partial/uncommitted generations are ignored (no half-applied stage). `decide()` itself is unchanged and pure — only the RoomRunner IO shell's *source* of params/setpoints moves from live `number.*` reads to the committed snapshot.

### 5.4 Programs + timeline
- `NutrientProgram` and `SteeringProgram` as separate, versioned, import/export JSON objects (`schema_version`). Athena ships as a flagship `NutrientProgram` preset; schema names are vendor-neutral.
- A **grow timeline** per room (zones inherit; a zone may override). Stages have day-spans; the UI drags boundaries. **Per-zone grow-day anchor override** for staggered tables — allowed only where the shared room photoperiod and **feed-domain** compatibility pass.
- **Feed-domain model:** zones sharing a fertigation source must share a compatible `NutrientProgram`/feed target; otherwise require separate fertigation channels with flush/mix semantics. Enforced at config + apply.
- **Steering intent** per stage = generative | balanced | vegetative → derived concrete targets (dryback, shot count/size, P1/P2 thresholds, cutoff).
- **Substrate profile per zone:** media type, block/slab/container volume, emitter count/flow, FC/saturation reference, valid VWC range, dryback limits, EC sensor type — constrains setpoints and dryback meaning.
- **Rootzone EC (minimal now):** hard bounds + max feed-EC delta-per-apply + substrate-EC display + an explicit rule that no source auto-raises feed EC to chase substrate EC (the engine already closed-loops EC via the P2 dryback lever). Full rootzone-EC strategy model deferred.

### 5.5 Central setpoint registry
One definition per setpoint: unit, min, max, safe default, max-delta-per-apply, phase applicability, substrate applicability, runtime-editable flag. Every writer (manual, timeline, LLM, recipe) is clamped by it.

### 5.6 Per-setpoint override
`{value, source, revert_trigger, expiry}` over the registry. Revert triggers: `on_enter_phase | on_exit_phase | on_any_phase_change | on_stage_change | at_time(HH:MM) | manual_clear`. Persisted in the engine store; exposed via services `set_override` / `clear_override` / `list_overrides` and a compact per-room diagnostics sensor (not one entity per setpoint). Naming: **program-controlled** vs **manual hold**.

### 5.7 Sources
- **Manual** — per-zone stage/phase/setpoint edits via UI/services (intent → gate).
- **Scheduled auto-advance** — grow-day crosses a timeline boundary → next stage applied at a safe boundary (pre-lights-on, before P0), reconciled with the existing lights-on P3→P0 reset; `last_applied_grow_day` prevents repeat-apply.
- **LLM via API (minimal now):** existing services accept `actor / source / reason / ttl / idempotency_key`, gate-checked and audited. Deferred: dedicated LLM UX, least-priv token, allowlist, advanced rate-limit/bounds policy. The orphaned `CONFIG.AI` stub is removed.
- **Follow-zone:** `zone_N_follow` (target + optional lag); an **acyclic per-room graph** (reject cycles and cross-room); precedence vs `pick_sibling` blind-probe failover is defined; the follower still runs its own safety gates + staleness; UI surfaces leader/lag/last-applied-generation.

### 5.8 Persistence ownership (single owner per datum)
- **HA config entries** own hardware config.
- **Engine store** (`/data`) owns programs, overrides, timeline, committed snapshots + generations, runtime counters, faults, `last_applied_grow_day`.
- Startup reconciliation with deterministic precedence; divergence resolved, never silently merged.

### 5.9 Dashboard
New multi-room shell: room/facility picker, dynamic zone count, the real draggable grow timeline, the override/source view, per-zone phase + which-source-set-it. Talks to the add-on's web API (it already serves the dashboard). The existing single-facility F2 dashboard (hardcoded zones `[1,2,3]`, `f2_row_*`) is kept as legacy; the multi-room UI is a rewrite, not a parameter flip.

## 6. The apply-timing model (core UX)

When a user edits program/setpoint values, *when* it takes effect depends on what they edit:

- **Future stage** → draft only; applies when the timeline reaches it.
- **Past stage** → recorded only; no live effect.
- **Current stage / phase** → the system asks **how to apply**:
  - **Apply now** (commit immediately as a new generation), or
  - **At next daily phase change** (choose P0 / P1 / P2 / P3), or
  - **At next stage change** (e.g. stretch → bulk → ripen).

This selector is the same mechanism as the per-setpoint override revert trigger — one "when" taxonomy for both applying program changes and reverting holds. All applies are draft → diff → bounded-validate → atomic commit (new generation).

## 7. Safety

- **Single gate** (§5.2), fail-closed, sole actuation path.
- **Commissioning / arm (hardware axis):** a room's hardware must pass a dry-run (entity existence, kill/pump/mainline/feed present, valve test pulse, stale check, sane caps) and be explicitly **ARMED** before any valve can fire. This is distinct from the apply-timing model (§6), which governs *setpoint* application, not whether hardware is live.
- **Physical fail-safe (M3):** software fail-closed is necessary but not sufficient. Commissioning verifies pump-relay-default-off, normally-closed valves, an independent watchdog/heartbeat that drops outputs if the controller dies, and a manual E-stop independent of HA. If HA is unavailable the add-on cannot send "close", so this must be covered by hardware; the system states this requirement explicitly.
- **Generation-change quiesce:** on roster/program generation change, freeze new starts, finish-or-abort current per safety rules, close affected actuators, then reload. The close/stop path is never refused.
- **Daily-volume cap:** cumulative shot volume persisted per zone + feed-domain with a last-reset grow-day/lights-on anchor; missing/corrupt cap state → fail closed or operator ack (never silently reset and overwater).
- **Hydraulic feedback (optional):** flow/pressure/leak/tank/pump-current entity hooks; commissioning checks valve readback (if available), flow-no-flow (if configured), leak hard-fault (if configured). Absent = degrades to electrical readback only.
- **HA-unavailable/restart:** heartbeat + stale timestamps; on failure/stale-critical → close/stop (via the hardware fail-safe), persist fault, require safe-recovery criteria or manual ack.

## 8. Backward compatibility & migration

- `state_schema_version`. Migration v1: flat `{zone:{}}` → `rooms.default.zones`; preserve unknown fields; seed new override/source/timeline/commissioning fields to inert/safe defaults; **never auto-clear safety lockouts**.
- `room_id` (stable) is separate from display name/slug. `default` is reserved forever with legacy un-prefixed entity aliases; legacy IDs are never auto-renamed.
- Tests cover empty / partial / corrupt / old / mixed state files (extends `tests/test_state_migration.py`), plus entity-registry migration and version consistency.
- A fresh install works zero-setup with sane defaults; F2's single-room install upgrades transparently.

## 9. Phasing

**Phase 1 (foundation + multi-room core):**
- B architecture skeleton: engine store, committed-snapshot builder, single safety gate, service compatibility matrix.
- RoomRunner refactor + per-room supervisor (deadlines/watchdog); duplicate-hardware detection + per-entity locks; per-room concurrency scheduler.
- Config wizard captures per-room hardware; versioned roster; commissioning/arm + physical fail-safe verification.
- Programs (Nutrient + Steering schema), stages, substrate profile, central setpoint registry, per-setpoint override with revert triggers, the apply-timing model.
- Sources: manual + scheduled auto-advance + follow-zone; LLM seam minimal (services accept actor/source/ttl/idempotency, gated + audited).
- State migration + tests. Small simulator (1–3 rooms / 3–12 zones; stale sensors, relay faults, HA latency, restart, migration, one shared-pump case). Append-only structured audit. Multi-room dashboard shell + draggable timeline + override/source view.

**Later:** full LLM policy framework (least-priv token, allowlist, rate-limit/bounds, dedicated UX); full rootzone-EC strategy model; shared-fertigation/RO/tank resource scheduler; 300-zone load test; full hydraulic fault-mode matrix; dashboard polish.

## 10. Reuse (build on, don't rewrite)

- Pure `crop-steering-engine/core.py` `decide()` + `pick_sibling` + `feed_grace_ok` + `cross_zone_outliers`.
- `addons/f2_control/controller.py` loop/sequencing/atomic `/data` persistence — generalize to per-room.
- `services.py` service/event seam (the manual + LLM application path).
- `recipe.py` `RecipeManager` (stage→setpoints application primitive).
- Per-room primitives: `room.py`, `config_flow.async_step_room`, `crop_steering_<slug>_*` namespacing, `tests/test_room.py`.
- `number.py` per-zone setpoint resolution (`PER_ZONE_STEERING_KEYS` + zone-then-global fallback).
- Dashboard components (`f2.html` cards, `setpoints.html` canvas/curve renderer, `crop_steering_rules.html` audit, `crop_steering_tune.html` overlay) and safety scaffolding (kill switch, feed gate, caps, dripper protection).

## 11. Risks

- **B refactor scope** — moving state ownership to the engine and routing all writes through the gate is the largest single change; the service compatibility matrix must be exhaustive or a legacy path recreates a bypass.
- **Batched HA sensor reads** remain the HA-side scale cost under B; measure the loop budget; fail a room closed if it misses its control deadline.
- **Follow-zone × pick_sibling** can interact (a follower that is also a blind-probe failover target) — define precedence explicitly; no cycles.
- **Apply-timing correctness** — editing current vs future/past stage must be unambiguous in the UI and engine; mis-targeted applies change live setpoints mid-grow.
- **Mixed-stage zones** in one room must pass photoperiod + feed-domain compatibility or they're disallowed.
- **Migration** of live installs is unforgiving — old `/data/state.json` must load and safety lockouts must survive.

## 12. Open items for implementation planning

- Exact transport for the versioned roster (HA service vs websocket vs local file) and the add-on web API surface for the dashboard.
- Engine store format (SQLite vs structured JSON in `/data`) and its own schema-version/migration.
- Precise priority/precedence table for arbitration including override expiry interplay.
- The draggable-timeline component (reuse `setpoints.html` canvas vs new) and its two-way sync to the engine store.
