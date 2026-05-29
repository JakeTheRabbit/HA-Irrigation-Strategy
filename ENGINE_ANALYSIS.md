# Crop Steering AppDaemon Engine — Technical Analysis & Feature Documentation

**Subject:** `appdaemon/apps/crop_steering/` — the AppDaemon "crop steering" irrigation engine
**Audience:** the owner/engineer deciding whether to **fix or replace** this engine
**Method:** full read of all 7 modules (≈7,000 lines) plus the README. Every defect below is cited as `file:line`.
**Date of analysis:** 2026-05-25

> **Top-line verdict (full detail in §7):** The engine is an ambitious, feature-rich design wrapped around a **broken core control loop**. The central state object is non-writable (a `@property` returning a throwaway dict), so phase state never persists; a daytime guard forces every zone back to P0; the P3 transition throws every time it is called; a safety check fails *open*; and several cross-module method calls reference methods that do not exist. These are not edge cases — they sit directly on the happy path, which is consistent with the owner's report that *"it has never actually run correctly."* The analytics, profiles, sensor-fusion, and dryback modules are individually salvageable, but the orchestrator (`master_crop_steering_app.py`) needs a near-total rewrite of its phase/state layer. **Recommendation: keep the four leaf modules, rewrite the orchestrator.**

---

## 1. Overview

This is the **automation brain** for a Home Assistant precision-irrigation system aimed at cannabis "crop steering" (the Athena-style P0→P3 methodology), but generalized to other crops. It runs as an **AppDaemon 4 app** alongside a separate Home Assistant custom integration (`crop_steering`).

In plain language, the engine is supposed to:

1. **Read** moisture (VWC %) and nutrient (EC, mS/cm) sensors that the HA integration exposes per zone (`sensor.crop_steering_zone_N_vwc` / `_ec`), plus tunable parameters (`number.crop_steering_*`), mode selectors (`select.*`), and enable/override switches (`switch.*`).
2. **Decide**, for each of up to 6 independent zones, which of four daily irrigation phases it is in and whether it needs water *right now*:
   - **P0 – Morning dryback:** after lights-on, withhold water and let the substrate dry a target % from its peak (root stimulation).
   - **P1 – Ramp-up:** progressively larger irrigation "shots" to rehydrate to a target VWC.
   - **P2 – Maintenance:** threshold-based irrigation through the bulk of the day, with EC-ratio adjustments.
   - **P3 – Pre-lights-off:** stop regular irrigation, allow only emergency shots, dry back into the night.
3. **Drive hardware** safely by calling `switch.turn_on` / `switch.turn_off` in a pump → main-line → zone-valve sequence (and the reverse to shut down).
4. **Layer "AI" on top:** multi-scale dryback peak detection, IQR-based sensor fusion with confidence scoring, a lightweight irrigation-need predictor, and strain-specific crop profiles with adaptive learning.
5. **Publish** ~40+ derived sensors back to HA (phases, water usage, health scores, predictions, safety status) and **listen** to integration events (`crop_steering_irrigation_shot`, `crop_steering_phase_transition`, `crop_steering_manual_override`).

The HA integration provides the entities and fires events; **this AppDaemon engine is the autonomous decision-maker and the only component that actually toggles pumps and valves.** Without it, the integration is passive (manual control + display only). The README frames the AppDaemon suite as "optional but recommended"; in practice, all autonomous behavior lives here.

---

## 2. Architecture

### 2.1 Two-layer design

```
┌─────────────────────────────────────────────────────────────────┐
│ HOME ASSISTANT (custom_components/crop_steering)  — NOT in scope  │
│   • Entities: sensors / numbers / selects / switches (~100+)      │
│   • Config-flow UI; per-zone sensor & hardware mapping            │
│   • Services: transition_phase, execute_irrigation_shot,          │
│     check_transition_conditions, set_manual_override              │
│   • Fires events on the HA event bus                              │
└───────────────▲───────────────────────────────┬──────────────────┘
                │ state reads / event listens    │ switch.turn_on/off
                │                                 ▼
┌───────────────┴───────────────────────────────────────────────────┐
│ APPDAEMON ENGINE (appdaemon/apps/crop_steering) — THIS ANALYSIS     │
│                                                                     │
│   master_crop_steering_app.py  ── MasterCropSteeringApp (5,241 ln)  │
│        │  orchestrates everything; owns the decision loops          │
│        ├── base_async_app.py        BaseAsyncApp (entity I/O)       │
│        ├── phase_state_machine.py   ZoneStateMachine (P0–P3 FSM)    │
│        ├── advanced_dryback_detection.py  AdvancedDrybackDetector   │
│        ├── intelligent_sensor_fusion.py   IntelligentSensorFusion   │
│        ├── ml_irrigation_predictor.py     SimplifiedIrrigationPredictor│
│        └── intelligent_crop_profiles.py   IntelligentCropProfiles   │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 Module map

| File | Lines | Class | Role |
|---|---|---|---|
| `master_crop_steering_app.py` | 5,241 | `MasterCropSteeringApp(BaseAsyncApp)` | Orchestrator: config, listeners, timers, decision loops, hardware sequencing, all HA sensor publishing, services. |
| `base_async_app.py` | 269 | `BaseAsyncApp(hass.Hass)` | Sync/async-safe wrappers for `get_state`/`set_state`/`call_service`, entity cache, type coercion helpers. |
| `phase_state_machine.py` | 377 | `ZoneStateMachine`, `ZoneState`, `P0/1/2/3Data`, enums | Per-zone finite-state machine with validated transitions, callbacks, and per-phase dataclasses. |
| `advanced_dryback_detection.py` | 517 | `AdvancedDrybackDetector` | Pure-Python peak/valley detection on a VWC ring buffer; dryback % + a linear-extrapolation prediction. |
| `intelligent_sensor_fusion.py` | 620 | `IntelligentSensorFusion` | IQR outlier rejection, per-sensor reliability/health scoring, reliability-weighted fusion, scalar Kalman smoothing. |
| `ml_irrigation_predictor.py` | 486 | `SimplifiedIrrigationPredictor` (alias `MLIrrigationPredictor`) | Weighted-feature + sigmoid "irrigation need" score with correlation-driven weight updates. No real ML deps. |
| `intelligent_crop_profiles.py` | 796 | `IntelligentCropProfiles` | 6 built-in crop/strain profiles × 3 growth stages; adaptive parameter learning; recommendations. |

### 2.3 Intended data flow (one sensor update)

```
VWC sensor changes
   → _on_vwc_sensor_update()                      [master:987]
       → sensor_fusion.add_sensor_reading(...)    [fusion:118]   (outlier reject, weight, fuse, Kalman)
       → dryback_detector.add_vwc_reading(...)    [dryback:170]  (peak/valley, dryback %, confidence)
       → _update_dryback_entities / _update_sensor_fusion_entities (publish to HA)
       → run_in(_run_emergency_check, fused_vwc)  [master:1019]  (emergency irrigation path)

Periodic loop (every `phase_check_interval` s)
   → _irrigation_decision_loop()                  [master:1149]
       → _check_all_zone_phase_transitions()      [master:3528]  (P0→P1→P2→P3 per zone)
       → _get_current_system_state()              [master:1194]  (fused VWC/EC + env + phases)
       → crop_profiles.get_current_parameters()   [profiles:452]
       → _get_ml_irrigation_predictions()         [master:1287]
       → _make_irrigation_decision()              [master:1341]  (emergency / cooldown / phase / dryback / ML / profile)
       → _execute_intelligent_irrigation()        [master:1942]
           → _select_optimal_zone()               [master:1995]  (priority + grouping + VWC need)
           → _execute_irrigation_shot()           [master:2081]  (override + safety checks → pump→main→valve sequence)
```

A **separate** timer also runs `_check_phase_transitions()` [master:3067] every 300 s, which contains a *different* (and broken — see §6) per-zone transition implementation. The engine therefore has **two competing phase-transition engines** (`_check_phase_transitions` and `_check_all_zone_phase_transitions`) with subtly different rules, both wired up at startup (`_setup_timers` [master:344] registers `_check_phase_transitions`; `_irrigation_decision_loop` calls `_check_all_zone_phase_transitions`).

### 2.4 How configuration is loaded

`_load_configuration()` [master:180] builds a dict from AppDaemon's `apps.yaml` args:

```python
config = {
    'hardware':  self.args.get('hardware', {}),
    'sensors':   self.args.get('sensors', {}),
    'timing':    self.args.get('timing', {}),
    'thresholds':self.args.get('thresholds', {}),
    'notification_service': self.args.get('notification_service', 'notify.persistent_notification'),
}
```

Critically, **the sub-keys are not given defaults.** Downstream code hard-indexes them:

- `_setup_listeners()` [master:313–321] iterates `self.config['sensors']['vwc']`, `['ec']`, and `['environmental'].values()`.
- `_setup_timers()` [master:351,358,365] indexes `self.config['timing']['phase_check_interval']`, `['ml_prediction_interval']`, `['sensor_health_interval']`.
- The decision loop indexes `self.config['thresholds']['emergency_vwc']` [master:1357], `['min_irrigation_interval']` [master:1369], `['critical_ec']` [master:1066].
- Hardware sequencing indexes `self.config['hardware']['pump_master']`, `['main_line']`, `['zone_valves'][zone]` [master:2183–2185].

So the engine's behavior is **entirely dependent on a fully-populated `apps.yaml`** whose schema is not validated and not defaulted. If any of those keys is missing, `initialize()` raises `KeyError` and the app fails to start. **No `apps.yaml` ships in the repository** (confirmed: there is no `appdaemon/**/*.yaml`), so the runtime config contract is undocumented in-tree. There are also two distinct config namespaces in play: the AppDaemon `apps.yaml` (hardware/sensors/timing/thresholds) and the HA integration's `number.*`/`select.*`/`switch.*` entities (per-phase targets, EC targets, lights hours), which the engine reads directly by entity-id.

Note the `sensors` config is expected to be **flat lists** keyed by `vwc`/`ec`/`environmental` (e.g. `_get_current_system_state` does `for sensor in self.config['sensors']['vwc']`), while `_validate_required_entities` [master:510] expects *positional* per-zone lists keyed `vwc_front`/`vwc_back`/`ec_front`/`ec_back`/`temp`. These two readers disagree about the shape of `config['sensors']`, so at most one of them can be satisfied by a given `apps.yaml`.

### 2.5 Per-zone identity convention

Zone-to-sensor association is done by **substring matching on the entity id**, and the convention is inconsistent across methods:

- `_get_zone_average_vwc` [master:2317] matches `f'r{zone}'` only.
- `_get_zone_vwc` [master:2625] matches `_zone_{n}_`, `_z{n}_`, `_r{n}_`, or `zone{n}`.
- `_get_zone_ec` [master:2711] matches `r{n}`, `z{n}`, or `zone_{n}`.
- `_select_zone_by_vwc_fallback` [master:2047] matches `r{zone}` or `z{zone}`.

A sensor named `sensor.vwc_r1` matches zone 1 in some methods but **also matches the substring in other contexts**, and naming like `r11` would match both zone 1 (`r1`) and zone 11. This is fragile and a likely source of "wrong zone" behavior in multi-zone setups.

---

## 3. Per-module breakdown

### 3.1 `base_async_app.py` — `BaseAsyncApp`

**Purpose:** A thin base class over `appdaemon.plugins.hass.hassapi.Hass` providing "async-safe" entity access with a TTL cache.

**Key methods:**
- `get_entity_value(entity_id, attribute, default)` [base:29] — cached `get_state`; explicitly checks `hasattr(result, '__await__')` to detect "we accidentally got a coroutine/Task" and falls back to default.
- `async_get_entity_value(...)` [base:82] — `await get_state(...)` variant for async callbacks.
- `get_float_value` / `get_bool_value` / `get_string_value` [base:112,132,157] — type-coercion wrappers with the same Task-object guard.
- `set_entity_value` / `async_set_entity_value` [base:175,200] — `set_state` wrappers that clear the cache for the entity first.
- `entity_exists` / `entity_exists_sync` [base:219,229] — existence check via "did we get a non-None, non-Task value."
- `call_service_sync` / `call_service_async` [base:244,258].

**What it actually does / notable points:**
- The repeated `hasattr(x, '__await__')` checks throughout the codebase (dozens of call sites) are a **symptom**: the author was fighting AppDaemon's sync/async boundary and never resolved it cleanly. AppDaemon already handles sync↔async for `get_state`; the defensive guards paper over uncertainty rather than fixing the root cause.
- `entity_exists_sync` returns `True` for any entity with a truthy state and `False` for `None`/`unknown`/`unavailable`. This conflates "doesn't exist" with "exists but is unavailable," which feeds the over-broad warnings in `_validate_required_entities`.
- The 60-second cache (`cache_timeout`) means the decision loop can act on **stale sensor values up to a minute old** — a real concern for a control loop that also runs on sensor-change callbacks expecting freshness.

**Assessment: functional**, if over-engineered for the problem. This module is the least broken.

### 3.2 `phase_state_machine.py` — `ZoneStateMachine` and friends

**Purpose:** A clean, well-structured per-zone finite state machine — arguably the best-designed file in the suite.

**Key types:**
- `IrrigationPhase` enum [psm:16] — P0/P1/P2/P3 with string values.
- `PhaseTransition` enum [psm:24] — LIGHTS_ON, DRYBACK_COMPLETE, DRYBACK_TIMEOUT, RAMP_UP_COMPLETE, LIGHTS_OFF_APPROACHING, MANUAL_OVERRIDE, EMERGENCY.
- Per-phase dataclasses `P0Data`/`P1Data`/`P2Data`/`P3Data` [psm:47–102] carrying phase-specific state (peak VWC, shot history, irrigation counts, etc.).
- `ZoneState` [psm:104] — aggregates current phase, history, the four phase-data objects, and water-usage counters.
- `ZoneStateMachine` [psm:141] — the machine itself.

**Key methods / behavior:**
- `VALID_TRANSITIONS` table [psm:145] defines legal `(transition → target)` edges per phase. P0→P1 only; P1→P2 or P3; P2→P3 or P0; P3→P0. Manual overrides allow more.
- `can_transition()` [psm:202] and `transition()` [psm:218] — validate, run exit callbacks, stamp exit time, switch phase, init new phase data, run enter + transition callbacks. **Thread-safe** via an `RLock`.
- `register_on_enter/on_exit/transition` [psm:280–298] — callback hooks (the master app uses these to log and to seed peak VWC).
- `update_p0_dryback`, `update_p1_progress`, `record_p1_shot`, `record_p2_irrigation`, `record_p3_emergency` [psm:312–349] — mutate the active phase's dataclass.
- `get_state_summary()` [psm:364] — serializable snapshot.

**Notable algorithm:** dryback % is `((peak − current)/peak)·100` [psm:317]; dryback rate is %/min over the phase duration.

**Assessment: functional and well-designed in isolation** — but see §6. The master app **does not use it as the source of truth** because of the `@property` bug, and it calls non-existent methods (`force_phase`, `try_transition_to`) on it. The class is good; its integration is broken.

### 3.3 `advanced_dryback_detection.py` — `AdvancedDrybackDetector`

**Purpose:** Detect irrigation peaks and dryback valleys in the VWC time-series, compute current dryback %, and predict time-to-target.

**Key methods:**
- Hand-rolled numeric helpers: `_mean`, `_std`, `_min`, `_max`, `_find_peaks`, `_apply_savgol_filter` (actually a moving average), `_moving_average`, `_polyfit` (degree-1 linear regression) [dryback:26–129]. **No numpy/scipy** despite the README/CLAUDE.md claiming `scipy.signal.find_peaks`.
- `add_vwc_reading(vwc, ts)` [dryback:170] — append to ring buffer; once enough points, run `_detect_peaks_valleys`, update dryback status & confidence, return a status dict.
- `_detect_peaks_valleys()` [dryback:209] — smooth, compute an adaptive threshold (`std·3`), find peaks above mean+threshold and valleys via inverted signal; keep only "recent" (within last 20 samples) and confidence ≥ 0.7.
- `_calculate_peak_confidence()` [dryback:308] — weighted blend of prominence, local variance, slope consistency, amplitude.
- `_analyze_dryback_status()` [dryback:352] — uses the most recent peak; declares dryback "in progress" if current < peak and 5 min < age < 8 h.
- `get_dryback_prediction(target_percentage)` [dryback:428] — linear-extrapolates remaining time from a 30-minute trend.

**Notable issues:**
- **Peak detection only sees the last 20 samples** (`idx >= len(self.vwc_history) - 20`, [dryback:250,262]). With the master app feeding **all zones' VWC into one shared detector** (see §3.7), the buffer mixes zones and the 20-sample recency window is dominated by whichever zone updated most recently. The single shared instance is a design error: dryback is inherently per-zone.
- The confidence gate (≥0.7) plus the "recent 20" gate means peaks are frequently rejected; in practice `current_dryback` often stays 0.
- `get_dryback_prediction` is the correct method name — but the orchestrator calls `predict_target_dryback_time` (does not exist) at [master:3317] (bug §6f).

**Assessment: functional as a standalone library, misintegrated.** The math is plausible; the single-instance, all-zones-mixed wiring undermines it.

### 3.4 `intelligent_sensor_fusion.py` — `IntelligentSensorFusion`

**Purpose:** Combine multiple VWC (and separately EC) sensors into one trusted value with outlier rejection, reliability scoring, and smoothing.

**Key methods:**
- Numeric helpers `_percentile`, `_mean`, `_std`, `_correlation` [fusion:17–62].
- `add_sensor_reading(sensor_id, value, ts, sensor_type)` [fusion:118] — store, update reliability, detect outlier, update health, fuse same-type sensors, return a rich dict.
- `_detect_outlier()` [fusion:170] — absolute range check by type (VWC 0–100, EC 0–20), then IQR bounds with an **adaptive multiplier** (tighter for stable data, looser for variable), plus a z-score>3.5 "extreme" check and a temporal-jump check.
- `_update_sensor_reliability()` [fusion:243] — blends outlier rate, rolling-std consistency, reading-interval stability, recent performance into a 0–1 score.
- `_update_sensor_health()` [fusion:313] — maps reliability + outlier rate + staleness to `offline`/`faulty`/`degraded`/`good`/`excellent`.
- `_perform_sensor_fusion(sensor_type, ts)` [fusion:336] — selects active same-type sensors (fresh ≤10 min, not offline/faulty, reliability ≥ threshold), does reliability-weighted fusion, then a **scalar Kalman filter** [fusion:480].
- `get_fused_vwc()` / `get_fused_ec()` [fusion:578,589] — re-run fusion on demand.

**Notable points & issues:**
- **Type separation is correct** — VWC and EC are never mixed (keyed by `sensor_types`), and the author left a "CRITICAL" comment about it [fusion:352]. Good.
- **One global Kalman state** [fusion:110] is shared across *both* VWC and EC fusion calls (`self.kalman_state`). `get_fused_vwc()` then `get_fused_ec()` will pump EC measurements through a filter that was just primed with VWC, and vice-versa. The Kalman output is therefore meaningless when both types are queried in sequence (which the decision loop does at [master:1257–1258]).
- New sensors default to reliability 0.8 [fusion:251]; with `min_sensors_required=2` and `confidence_threshold=0.6`, fusion can silently fall back to a single best sensor or return `None`.

**Assessment: largely functional**, with one real bug (shared Kalman state across signal types). Recoverable with a per-type filter.

### 3.5 `ml_irrigation_predictor.py` — `SimplifiedIrrigationPredictor`

**Purpose:** Produce a 0–1 "irrigation need" score from features, with optional online weight adaptation. Explicitly **not** real ML (no numpy/sklearn) — a sigmoid over a weighted sum.

**Key methods:**
- `add_training_sample(features, outcome, ts)` [ml:108] — extract a 4-element feature vector, compute a target 0–1, store; retrain every `update_frequency` samples once ≥ `min_training_samples`.
- `predict_irrigation_need(features, horizon)` [ml:155] — returns `{'irrigation_need', 'confidence', 'horizon_minutes', 'prediction_components', 'model_status', 'training_samples'}`.
- `_extract_features()` [ml:208] — VWC component, dryback component, time-since-last component, EC component.
- `_mathematical_predict()` [ml:282] — weighted sum → sigmoid `1/(1+e^-(x·8−4))`.
- `_update_model()` [ml:324] — recompute feature weights from |correlation| with targets; estimate an R²-like accuracy.

**Critical integration mismatch (see §6h):** The master app expects a **completely different return contract** than this module provides:
- `_get_ml_irrigation_predictions` checks `predictions.get('prediction_available', False)` [master:1313] — this key is **never returned** by `predict_irrigation_need`, so the master app *always* treats predictions as unavailable and discards them.
- `_make_irrigation_decision` reads `ml_predictions.get('model_confidence')` [master:1392] and `_evaluate_ml_decision` reads `ml_predictions.get('analysis', {})['max_irrigation_need']` and `['irrigation_urgency']` [master:1905–1908]. None of `model_confidence`, `analysis`, `max_irrigation_need`, or `irrigation_urgency` exist in the predictor's output.
- `_update_ml_predictions` [master:3702–3709] reads the same non-existent `analysis`/`model_confidence` keys when publishing ML sensors.
- `_add_ml_training_sample` [master:3658–3662] passes `features`/`outcome` shaped differently than `_extract_features`/`_calculate_irrigation_target` expect, then checks `result['status'] == 'retrained'` and `result['performance']['ensemble']['r2']` — but `add_training_sample` returns `{'success', 'samples', 'model_trained'}`, never `'status'`/`'performance'`. (It returns `success`, so this branch silently no-ops; if it ever returned a dict without `'status'`, the `result['status']` access would also need care.)

**Net effect:** the ML layer is **dead weight** — wired in, consuming CPU, but its output is never consumed because of the contract mismatch, and its training feed is malformed.

**Assessment: the module works standalone; its integration is non-functional.**

### 3.6 `intelligent_crop_profiles.py` — `IntelligentCropProfiles`

**Purpose:** Strain/crop-specific parameter sets and adaptive learning.

**Key methods:**
- `_create_base_profiles()` [profiles:62] — six built-ins: `Cannabis_Athena`, `Cannabis_Indica_Dominant`, `Cannabis_Sativa_Dominant`, `Cannabis_Balanced_Hybrid`, `Tomato_Hydroponic`, `Lettuce_Leafy_Greens`. Each has `vegetative`/`early_flower`/`late_flower` parameter blocks (VWC min/max, dryback target, EC baseline/max, P1/P2/P3 thresholds), environmental ranges, and adaptation rates.
- `select_profile(name, stage)` [profiles:402], `get_current_parameters()` [profiles:452] — return active params with adaptations + (stubbed) environmental adjustments applied.
- `update_performance(result, env)` [profiles:509] + `_learn_adaptations()` [profiles:549] — adjust VWC/EC/dryback targets based on rolling efficiency/response metrics, with momentum smoothing.
- `create_custom_profile`, `get_profile_recommendations`, `import/export`, `save/load` [profiles:611–796].

**Notable mismatches:**
- **Profile-name mismatch with the integration.** The README lists integration `crop_type` options as `Cannabis_Athena, Cannabis_Hybrid, Cannabis_Indica, Cannabis_Sativa, Tomato, Lettuce, Basil, Custom`, but this module's keys are `Cannabis_Indica_Dominant`, `Cannabis_Sativa_Dominant`, `Cannabis_Balanced_Hybrid`, `Tomato_Hydroponic`, `Lettuce_Leafy_Greens`. Only `Cannabis_Athena` overlaps. So selecting most crop types in HA returns `{'status':'error', ...}` and the engine logs a failure and keeps defaults.
- `_apply_environmental_adjustments` [profiles:502] is an explicit stub (returns params unchanged). The "environmental adaptation" feature does not exist yet.
- `get_current_parameters()` returns keys like `vwc_target_min`, `dryback_target`, `p2_vwc_threshold` — but the per-zone phase evaluators (`_evaluate_zone_p2_needs` etc.) **ignore the profile** and read HA `number.*` entities directly. The profile params are only consulted in the lightly-used `_evaluate_profile_decision` / `_evaluate_dryback_decision` fallbacks. So profiles barely influence real decisions.

**Assessment: functional library, weakly integrated.** The data is plausible; the wiring is shallow, and the name mismatch breaks 7 of 8 crop types.

### 3.7 `master_crop_steering_app.py` — `MasterCropSteeringApp`

**Purpose:** The orchestrator. 5,241 lines. Owns config, listeners, six periodic timers, the decision loops, per-zone phase logic, EC logic, hardware sequencing, water tracking, persistence, analytics, safety, services, and ~40 published sensors.

**Lifecycle:**
- `initialize()` [master:98] — load config, create one `ZoneStateMachine` per zone (default **P2**), register callbacks, init the 4 advanced modules, set up listeners + timers, load persistent state, schedule sensor creation and periodic save.
- `_setup_listeners()` [master:309] — VWC/EC/env sensor `listen_state`; system toggle, phase select, crop-type select; events for manual irrigation, irrigation shot, manual override, phase transition, set override.
- `_setup_timers()` [master:344] — `_irrigation_decision_loop`, `_update_ml_predictions`, `_monitor_sensor_health`, `_update_performance_analytics`, `_update_analytics_system`, **and** `_check_phase_transitions`.
- `terminate()` [master:5200] — synchronous emergency stop of all hardware.

**Decision pipeline:** `_irrigation_decision_loop` [master:1149] → `_make_irrigation_decision` [master:1341] which evaluates, in order: emergency VWC, irrigation cooldown, phase requirements (`_evaluate_phase_requirements` [master:1411], which fans out to `_evaluate_zone_p0/p1/p2/p3_needs`), dryback target, ML, and profile fallback. The phase evaluators are the most substantive working logic in the file (EC ratios, progressive shot sizing, EC stacking, flush thresholds).

**Hardware sequencing:** `_execute_irrigation_shot` [master:2081] is the real actuator — a long gauntlet of override/enable/tank/safety checks, then `pump on → sleep 2s → main on → sleep 1s → zone on → sleep(duration) → zone off → main off → pump off`, post-VWC sampling, water-usage update, persistence, and event firing. It also contains **site-specific F2 interlocks** [master:2143–2160] hard-coded to entities `input_boolean.nutrient_dosing_active` and `binary_sensor.veg_tank_full_float_tank_level_full` — these are not generic and not configurable.

**Notable algorithms:** progressive P1 shot sizing [master:2893], EC-adjusted shot sizing [master:2854], P2 EC-ratio dilution/conservation [master:2804], priority+VWC+phase zone scoring [master:4344], emergency-zone abandonment after 4 shots/30 min [master:3955].

**Assessment: this is where the engine is broken.** See §6. The orchestrator is enormous, contains duplicate definitions, two competing transition engines, dead ML wiring, and the central state-persistence bug.

---

## 4. Complete feature inventory

Legend: ✅ functional · ⚠️ partially working / fragile · ❌ broken or dead (present but non-functional) · 🧩 stub.

### Phase control & steering
- ❌ **4-phase daily state machine (P0→P1→P2→P3).** The `ZoneStateMachine` is sound, but the orchestrator's writes to phase state are discarded (§6a) and its transition logic is broken (§6b, §6c). Phases do not progress in normal operation.
- ⚠️ **Per-zone independent steering (1–6 zones).** Per-zone machines, schedules, profiles, groups, priorities all exist; undermined by the same state bug.
- ✅ **Vegetative vs generative mode** per zone (`_zone_is_vegetative` [master:1528]) selecting EC targets.
- ⚠️ **Per-zone vs global parameter override** (`_get_zone_number` [master:1521]) — works mechanically, depends on entities existing.
- ❌ **Two parallel phase-transition engines** (`_check_phase_transitions` [master:3067] and `_check_all_zone_phase_transitions` [master:3528]) with different rules, both active.

### Dryback
- ⚠️ **Multi-scale peak/valley detection** (`AdvancedDrybackDetector`). Works standalone; fed a single shared, zone-mixed buffer (§3.3).
- ⚠️ **Dryback % + confidence scoring** — computed, published to `sensor.crop_steering_dryback_percentage` and `binary_sensor.crop_steering_dryback_in_progress`.
- ❌ **Dryback-time prediction** — `get_dryback_prediction` exists, but the consumer calls the wrong name `predict_target_dryback_time` (§6f), so `_calculate_optimal_p3_timing` throws.
- ✅ **P0 rate-based early exit** (`_should_p0_exit_based_on_rate` [master:3255]) — pure-Python projection of time-to-target. Logic is reasonable (but only reachable if P0 is ever properly entered, which §6b prevents in daytime).

### Sensor processing
- ✅ **IQR outlier rejection with adaptive multiplier** (`_detect_outlier` [fusion:170]).
- ✅ **Absolute range sanity (VWC 0–100, EC 0–20)** [fusion:183–192].
- ✅ **Per-sensor reliability + health scoring** (offline/faulty/degraded/good/excellent).
- ✅ **Reliability-weighted multi-sensor fusion** with single-best fallback.
- ⚠️ **Kalman smoothing** — present but shares one state across VWC and EC (§3.4 bug).
- ✅ **Front/back averaging per zone** (multiple `_get_zone_*` averaging helpers) — though by fragile substring matching (§2.5).
- ✅ **Sensor health monitoring loop** + per-sensor `*_health` sensors [master:3720].

### "AI"/ML
- ❌ **ML irrigation-need prediction** — the predictor works standalone, but the orchestrator reads keys it never returns (`prediction_available`, `model_confidence`, `analysis`, `max_irrigation_need`), so predictions are always discarded (§6h). Effectively dead.
- ❌ **Online ML training from outcomes** — `_add_ml_training_sample` passes malformed features/outcome and checks non-existent return keys (§6h).
- 🧩 **`_get_irrigation_count_24h`** returns a hard-coded `8` [master:2593].

### Crop profiles
- ⚠️ **6 built-in crop/strain profiles × 3 stages** — data present; only `Cannabis_Athena` matches the integration's selectable names (§3.6).
- ⚠️ **Adaptive parameter learning** (`_learn_adaptations`) — implemented with momentum, but fed by `_update_crop_profile_performance` which may rarely trigger and whose `target_achieved`/`plant_response_score` are crude proxies.
- 🧩 **Environmental adaptation** — explicit stub [profiles:502].
- ✅ **Custom profile create / import / export / save-load**.
- ✅ **Profile recommendations by genetics + environment**.

### EC-based steering
- ✅ **EC-ratio threshold steering** (`_evaluate_ec_irrigation_need` [master:2737]) — dilute when high, hold when low.
- ✅ **EC stacking mode** (gradually build EC) gated by `switch.crop_steering_ec_stacking_enabled`.
- ✅ **P2 EC-ratio dilution/conservation shot sizing** (`_evaluate_p2_ec_ratio_irrigation` [master:2804]).
- ✅ **EC-adjusted shot sizing** (`_calculate_ec_adjusted_shot_size` [master:2854]) — up to 2× for severe high EC.
- ✅ **Per-phase EC targets** (veg/gen P0–P3) read from `number.*` entities.
- ✅ **Emergency EC flush** in P0/P3 at extreme ratios (>2.0 / >2.5) [master:1797,1858].

### Shot sizing & hardware
- ✅ **Progressive P1 shot sizing** (initial + increment·count, capped, × zone multiplier) [master:2893].
- ✅ **Fixed P2 shot size** with EC adjustments.
- ✅ **P3 emergency shot sizing**.
- ✅ **Pump → main → zone-valve sequencing** with prime/stabilize delays and reverse shutdown [master:2222–2244].
- ✅ **Pre/post-VWC sampling & efficiency estimate** per shot.
- ⚠️ **Duration vs. shot-size unit confusion:** decisions compute a `shot_size` *percentage*, but `_execute_irrigation_shot` takes a *duration in seconds*; the multi-zone path passes a flat `duration: 30` [master:1513] and ignores the computed shot sizes, and P1 shot recording back-estimates "2% per minute" [master:2279]. The careful shot-size math is largely **not actually applied to valve open time.**

### Safety & limits
- ⚠️ **Pre-irrigation safety checks** (field capacity, max EC, daily volume, extreme saturation/EC, frequency, phase-specific) [master:4972] — comprehensive **but fails OPEN on exception** (§6d).
- ✅ **Irrigation lock** (`self.irrigation_in_progress`) preventing overlap [master:2084].
- ✅ **Emergency stop** (async [master:2353] + sync-on-terminate [master:5200]).
- ✅ **Emergency irrigation on critically low VWC** with 5-min cooldown [master:2392].
- ✅ **Blocked-dripper abandonment** (≥4 emergency shots/30 min → 2 h lockout) [master:3955].
- ✅ **Critical-EC notification** [master:2567].
- ✅ **Concurrency cap** of 1 irrigating zone [master:4412].
- ✅ **Site-specific tank/dosing interlocks** (hard-coded F2 entities) [master:2143].

### Zones: grouping & priority
- ✅ **Zone groups (A–D / Ungrouped)** with ">50% of group needs water → irrigate whole group" [master:1476].
- ✅ **Zone priorities (Critical/High/Normal/Low)** with numeric scoring and sorting.
- ✅ **Priority + VWC-need + phase-urgency composite zone selection** [master:4344].
- ✅ **Group conflict coordination** (block group if a member is already irrigating) [master:4322].

### Water tracking & persistence
- ✅ **Per-zone daily/weekly water totals + irrigation counts** with day/week reset logic [master:600].
- ✅ **Daily volume limit warning** [master:639].
- ⚠️ **State persistence to JSON** (atomic write, corruption backup, version field) [master:729] — but writes derive from the broken `@property` (§6a), so persisted phase data is effectively whatever the property reconstructs, and `last_reset` serialization causes HA `set_state` 400s (§6e).
- ⚠️ **Restart recovery / state validation** [master:783,911] — reads back into `self.zone_phases` (a property → discarded, §6a) and into `self.zone_phase_data` (also a property → discarded).

### HA integration surface (published by the engine)
- ✅ Phase summary `sensor.crop_steering_app_current_phase`; per-zone `sensor.crop_steering_zone_N_phase`.
- ✅ `sensor.crop_steering_app_next_irrigation` (timestamp).
- ✅ Dryback: `sensor.crop_steering_dryback_percentage`, `binary_sensor.crop_steering_dryback_in_progress`.
- ⚠️ ML: `sensor.crop_steering_ml_irrigation_need`, `_ml_confidence` (populated from non-existent keys → 0).
- ✅ Water: `sensor.crop_steering_zone_N_daily_water_app`, `_weekly_water_app`, `_irrigation_count_app`, `_last_irrigation_app`.
- ✅ Health/analytics: `sensor.crop_steering_sensor_health`, `_system_health_score`, `_system_efficiency`, `_water_efficiency`, per-zone `_health_score`/`_efficiency`/`_safety_status`, `_system_safety_status`.
- ✅ Decision/state: `sensor.crop_steering_current_decision`, `_system_state`.
- ✅ Fused values: `sensor.crop_steering_fused_vwc`/`_ec`, per-sensor `*_reliability`.

### Events & services consumed
- ✅ Listens: `crop_steering_irrigation_shot`, `crop_steering_manual_irrigation`, `crop_steering_manual_override`, `crop_steering_phase_transition`, `crop_steering_set_manual_override`.
- ❌ **Phase-transition service handler** `_on_phase_transition_service` [master:4147] calls `machine.force_phase(...)` [master:4172] and `machine.try_transition_to(...)` [master:4176] — **neither method exists** on `ZoneStateMachine` (it only has `transition`/`can_transition`). Every forced/normal service-driven transition raises `AttributeError`. So the HA `transition_phase` service path into AppDaemon is broken.
- ✅ Manual override enable/timeout/permanent/disable with notifications [master:4035–4145].

### Notifications
- ✅ Configurable `notification_service`; alerts for critical EC, abandonment, override events. (Minor: `notify.` → `notify/` replacement is done inconsistently — `.replace('.', '/')` in one place [master:2575], `.replace('notify.','notify/')` in others [master:3981].)

---

## 5. Code-quality & architecture assessment

**Strengths**
- **The leaf modules are reasonably clean and self-contained.** `phase_state_machine.py`, `intelligent_sensor_fusion.py`, `advanced_dryback_detection.py`, `ml_irrigation_predictor.py`, and `intelligent_crop_profiles.py` each have a coherent single responsibility, docstrings, and no AppDaemon coupling — they're unit-testable in principle.
- **Zero hard external dependencies.** All numeric work (percentiles, std, regression, peak-finding, Kalman, sigmoid) is hand-rolled in stdlib Python, so it runs on HA OS AppDaemon without compiled wheels. (The README/CLAUDE.md claims scipy/numpy; the code does not use them. The *claim* is wrong, but the dependency-free reality is a genuine strength.)
- **Genuine domain depth.** EC-ratio steering, EC stacking, progressive shot sizing, per-phase EC targets, dryback rate projection, group/priority orchestration, and blocked-dripper abandonment show real crop-steering knowledge.
- **Defensive I/O and persistence hygiene** — atomic state writes with corruption backup; broad try/except so a single bad sensor rarely crashes a loop; emergency stop on terminate.

**Weaknesses**
- **Size & single-responsibility collapse.** `master_crop_steering_app.py` is **5,241 lines in one class** with ~120 methods spanning config, control, hardware, analytics, persistence, safety, and HA-sensor authoring. It is past the point any single engineer can hold in their head, which is exactly how the duplicate-definition and contract-mismatch bugs survived.
- **Duplicate method definitions (later silently shadows earlier):**
  - `_get_phase_icon` defined twice — [master:406] and [master:3626] (different icon sets!).
  - `_get_zone_group` defined twice — [master:416] and [master:4244].
  - `_get_zone_priority` defined twice — [master:425] and [master:4261].
  - `_should_zone_start_p3` defined twice with **different signatures** — [master:3385] (3 args) and [master:3595] (1 arg). This one is load-bearing and breaks P3 (§6c).
  In Python the last definition wins; the earlier ones are dead, and call sites written against the earlier signature break.
- **The `@property`-returning-a-fresh-dict anti-pattern (the headline bug, §6a).** `zone_phases` [master:51] and `zone_phase_data` [master:57] are read-only computed properties. Dozens of call sites do `self.zone_phases[z] = 'P1'`, `self.zone_phase_data[z]['p0_start_time'] = now`, `self.zone_phases.update(...)` — all mutate a throwaway object and are discarded. This single anti-pattern poisons phase progression, P0 peak/timer tracking, P1 shot history, restart recovery, and persistence.
- **Two competing control loops.** `_check_phase_transitions` and `_check_all_zone_phase_transitions` implement overlapping, divergent transition rules and both run. Even after fixing §6, they will fight.
- **Cross-module contract drift.** The ML predictor (§6h) and crop-profile names (§3.6) are integrated against APIs that don't match. This is the classic failure mode of building modules in isolation and never running the integrated whole — corroborating "never actually run correctly."
- **Fails-open safety.** The exception path of the master safety check returns `{'blocked': False}` [master:5047] — on any unexpected error the system *permits* irrigation. For a system that drives pumps onto live plants, safety must fail **closed**.
- **`set_state` payload bugs (§6e).** Datetime/date objects and bare dates are pushed into HA attributes/state, which HA rejects (HTTP 400). Many published sensors silently fail to update.
- **Error handling that hides failures.** Almost every method is wrapped in `try/except Exception` that logs and returns a benign default. Combined with the cache and the broad catches, **a broken control path looks like a quiet, healthy system** — there is no loud failure, which is why this is hard to diagnose from the outside.
- **Testability: effectively zero.** No tests in-tree; the orchestrator can only be exercised inside a live AppDaemon+HA with a fully-populated `apps.yaml` (which isn't in the repo). The leaf modules *could* be tested but aren't.
- **Async/sync confusion.** Pervasive `hasattr(x,'__await__')` guards, `run_in(..., 0)` to fire async wrappers, and mixed sync/async `set_state` paths indicate the AppDaemon execution model was never pinned down.
- **Hard-coded site specifics.** The F2 tank/dosing interlocks [master:2143] and "fallback to Zone 3" [master:2440,2522] are baked into what is otherwise meant to be a generic, redistributable engine.

---

## 6. Known critical bugs (verified against the code)

Each item was checked against the source. The audit's seven are all confirmed; additional findings follow.

### (a) `zone_phases` / `zone_phase_data` are `@property`s returning fresh dicts → all writes are silently discarded — **CONFIRMED, CRITICAL**

- `zone_phases` property [master:51–55] returns a **new** `{zone_id: machine.get_phase_string()}` dict each access.
- `zone_phase_data` property [master:57–96] returns a **new** legacy-format dict each access (reconstructed from the state machines, with most fields hard-set to `None`/`0`).

There are no setters. Yet the code writes to them everywhere, e.g.:
- `self.zone_phases[zone_num] = 'P0'` [master:928], `= 'P1'` [master:942], `= 'P3'` [master:947], `= phase` [master:906].
- `self.zone_phases.update(state_data['zone_phases'])` [master:819].
- `self.zone_phase_data[zone_num]['p0_start_time'] = now` [master:932], `[zone_num]['p0_peak_vwc'] = zone_vwc` [master:933].
- `self.zone_phase_data[zone_num] = {...}` in restore [master:838] and `_initialize_p0_phase` mutates `self.zone_phase_data[zone_num]` [master:3234].
- `_update_p1_progression_after_irrigation` / `_reset_p1_progression` mutate `zone_data = self.zone_phase_data[zone_num]` [master:2919,2947].

**Every one of these mutates a temporary object that is immediately garbage-collected.** Consequences:
- P0 start-time and peak-VWC are never stored → `_should_zone_exit_p0` always sees "P0 not initialized," re-initializes, and returns `False` [master:3181–3184] → **P0 never completes via dryback.**
- `_initialize_p0_phase` does `zone_data = self.zone_phase_data[zone_num]` then writes — discarded.
- P1 shot history written to `zone_phase_data` is lost (the parallel `ZoneStateMachine.record_p1_shot` path does persist into the machine, but the analytics/efficiency code reads the *property* version, which is empty).
- Restart recovery and `_save_persistent_state` operate on the property → persisted phase timing is effectively void.

This is the single most damaging defect: **the orchestrator's notion of per-zone phase state is write-only-to-nowhere.** Anything the master app tries to remember about a phase (outside the state machine itself) evaporates on the next line.

### (b) `_check_phase_transitions` forces any zone back to P0 whenever lights are on → zones can't progress past P0 in daytime — **CONFIRMED, CRITICAL**

In `_check_phase_transitions` [master:3095–3099]:

```python
if lights_on and current_phase != 'P0':
    target_phase = 'P0'
    reason = f"Zone {zone_num}: Lights on - starting morning dryback phase"
```

Because this timer fires every 300 s [master:383] for the *entire photoperiod*, **any zone that manages to reach P1/P2/P3 while the lights are on is yanked straight back to P0 on the next tick.** The `elif` branches that would advance P0→P1→P2→P3 [master:3101–3124] are only reached when `current_phase` is already the matching phase, but this top `if` resets it first. Combined with (a) and (c), daytime phase progression is impossible. (P0 is meant to be a *transient* morning state, not the whole day.)

Note `_validate_restored_state` [master:944–947] has the same flawed assumption in the other direction: "If lights are OFF, zone should be in P3," forcing P3 at startup whenever lights are off.

### (c) `_should_zone_start_p3` defined twice (1-arg shadows 3-arg) → the P3 transition call throws → P3 never entered — **CONFIRMED, CRITICAL**

- First definition (3 args): `async def _should_zone_start_p3(self, zone_num, lights_on_time, lights_off_time)` [master:3385].
- Second definition (1 arg): `async def _should_zone_start_p3(self, zone_num)` [master:3595]. **This one wins** (defined later in the class body).

But `_check_phase_transitions` calls it with **three** arguments:

```python
should_transition = await self._should_zone_start_p3(zone_num, lights_on_time, lights_off_time)   # [master:3116]
```

At runtime the bound method is the 1-arg version, so this call raises `TypeError: _should_zone_start_p3() takes 2 positional arguments but 4 were given`. That exception is swallowed by the surrounding `try/except` [master:3130], so **the P2→P3 transition simply never happens** (and the whole `_check_phase_transitions` pass for that zone aborts). The *other* transition engine, `_check_all_zone_phase_transitions`, calls the 1-arg version correctly [master:3581], so the two callers can't both be right against one signature — a direct artifact of the duplicate definition.

### (d) `_check_irrigation_safety_limits` exception path returns `{'blocked': False}` (fails OPEN) — **CONFIRMED, CRITICAL (safety)**

`_check_irrigation_safety_limits` [master:4972] ends with:

```python
except Exception as e:
    self.log(f"❌ Error checking irrigation safety limits: {e}", level='ERROR')
    # Default to allowing irrigation on error to prevent system lockup
    return {'blocked': False, 'reason': 'safety_check_error', 'message': ...}   # [master:5047–5052]
```

On *any* error in the safety evaluation, irrigation is **permitted**. The helper checks `_check_irrigation_frequency_safety` [master:5088] and `_check_phase_specific_safety` [master:5128] do the same. For a system that opens valves and runs a pump onto plants, this is backwards: a safety check that errors should **block** (fail closed). The same fail-open philosophy appears in `_check_zone_conflicts` [master:4421] and `_coordinate_group_irrigation` [master:4342] ("Allow irrigation on error to prevent system lockup").

### (e) `set_state` HTTP 400s from non-serializable datetime/date in state & attributes — **CONFIRMED**

HA's `set_state` requires JSON-serializable values and ISO-8601 strings for timestamp device-classes. The engine passes raw `datetime`/`date` objects:

- `_update_zone_water_sensors` sets `last_reset` to `str(zone_data.get('last_reset_daily', datetime.now().date()))` [master:661,673,683] — a **bare date string** like `2026-05-25`, while the sensor has no consistent device-class and HA expects either a number/string state with serializable attributes. A bare date in a `device_class: timestamp` context is rejected (needs full ISO-8601 datetime).
- Numerous analytics/zone sensors push **dict attributes that themselves contain `datetime` objects**, e.g. `_calculate_zone_analytics` returns `'last_irrigation': <datetime>` [master:4591] and `'last_shot_time'` / `'vwc_at_start'` in `_get_p1_progression_status` [master:4963], which are then handed straight to `set_entity_value(..., attributes=zone_data)` [master:4821]. Raw `datetime` is not JSON-serializable → HA returns **HTTP 400** and the state update is dropped.
- `get_state_summary`/decision attributes similarly risk embedding non-serializable values.

Net effect: a meaningful fraction of the published sensors silently fail to update, so the dashboard shows stale/zero data even when the loop runs.

### (f) `predict_target_dryback_time` called but the method is `get_dryback_prediction` — **CONFIRMED**

`_calculate_optimal_p3_timing` [master:3317]:

```python
prediction = await self.dryback_detector.predict_target_dryback_time(target_dryback)
```

`AdvancedDrybackDetector` has **no** `predict_target_dryback_time`. The real method is `get_dryback_prediction(target_percentage)` [dryback:428], and it is **synchronous** (not awaitable). So this line raises `AttributeError` (and even if the name were fixed, `await` on a non-coroutine would raise `TypeError`). The surrounding try/except [master:3346] swallows it and falls back to historical timing — so the ML-optimized P3 timing feature is dead, and `_calculate_optimal_p3_timing` is itself only reachable from code paths that the P3 bugs (b)/(c) already block.

### (g) `current_state['current_phase']` KeyError — **CONFIRMED**

`_get_current_system_state` [master:1270–1281] returns a dict whose phase information is under the key **`zone_phases`** (a dict), with **no** `current_phase` key. But `_get_ml_irrigation_predictions` does:

```python
features = { ... 'current_phase': current_state['current_phase'], ... }   # [master:1297]
```

This raises `KeyError: 'current_phase'`. It's caught by the method's try/except [master:1319] and returns `None`, so **ML predictions are never produced** even before the contract mismatch in (h) would discard them. (There is no system-wide "current phase" concept anyway, since phases are per-zone.)

### (h) ML predictor return-contract mismatch → predictions always discarded, training feed malformed — **ADDITIONAL, HIGH**

(Detailed in §3.5.) `predict_irrigation_need` returns `irrigation_need`/`confidence`/`model_status` [ml:190–202], but consumers check `prediction_available` [master:1313], `model_confidence` [master:1392,3709], and `analysis.max_irrigation_need`/`irrigation_urgency` [master:1905–1908,3702–3715]. None exist → ML output is always treated as unavailable/zero. `_add_ml_training_sample` [master:3636] passes a feature dict missing the keys `_extract_features` reads (`vwc_trend_15min`, `dryback_percentage`, `time_since_last_irrigation`, `ec_ratio`) and checks `result['status']=='retrained'` / `result['performance']['ensemble']['r2']`, which `add_training_sample` never returns. The ML subsystem is wired but inert.

### (i) Phase-transition service calls non-existent state-machine methods — **ADDITIONAL, HIGH**

`_on_phase_transition_service` [master:4147] calls `machine.force_phase(phase)` [master:4172] and `machine.try_transition_to(phase)` [master:4176]. `ZoneStateMachine` defines neither (only `transition`, `can_transition`, `force_*` do not exist). Every invocation of the HA `crop_steering.transition_phase` service that reaches AppDaemon raises `AttributeError` (swallowed at [master:4182]). The manual phase-select path `_on_phase_change` [master:1105] uses the correct `_transition_zone_to_phase` instead, so manual phase changes via the *select entity* may work while the *service* does not.

### (j) Config sub-keys hard-indexed without defaults → `initialize()` KeyError if `apps.yaml` incomplete — **ADDITIONAL, MEDIUM**

(Detailed in §2.4.) `_load_configuration` defaults only the top-level keys to `{}`; `_setup_listeners`/`_setup_timers`/decision loop then index `config['sensors']['vwc']`, `config['timing']['phase_check_interval']`, `config['thresholds']['emergency_vwc']`, etc. A missing sub-key crashes startup. Additionally, the two readers of `config['sensors']` disagree on shape (flat lists vs. positional `*_front`/`*_back` lists), so a single valid config can't satisfy both `_validate_required_entities` and the runtime sensor reads.

### (k) Single shared `AdvancedDrybackDetector` and Kalman state across all zones / both signal types — **ADDITIONAL, MEDIUM**

One detector instance receives every zone's VWC [master:1006] (zone-mixed buffer, §3.3), and the fusion module's single Kalman state is shared between VWC and EC fusion (§3.4). Both make the "advanced" outputs unreliable in any multi-zone or VWC+EC deployment.

### (l) Shot-size percentage vs. valve-duration-seconds conflation — **ADDITIONAL, MEDIUM**

Phase evaluators compute `shot_size` as a substrate-volume **percentage**, but `_execute_irrigation_shot(zone, duration, ...)` interprets its second argument as **seconds**. The multi-zone decision passes a flat `duration: 30` [master:1513] and never converts the computed percentages into seconds, and P1 shot recording reverse-estimates "2% per minute" [master:2279]. The progressive/EC-adjusted shot math therefore rarely affects real water delivered. (The HA integration does compute durations in its sensors, but the AppDaemon executor doesn't consume them.)

### (m) `self.start_time` never set — **ADDITIONAL, LOW**

`_calculate_system_analytics` reads `getattr(self, 'start_time', now)` [master:4516]; `start_time` is never assigned in `initialize()`, so "uptime" is always ~0. Harmless (defensive getattr) but indicative of unfinished wiring.

---

## 7. Recommendations

### 7.1 Fix vs. replace

**Recommendation: keep the four leaf modules; rewrite the orchestrator's control/state core.**

- The **leaf modules** (`phase_state_machine.py`, `intelligent_sensor_fusion.py`, `advanced_dryback_detection.py`, `ml_irrigation_predictor.py`, `intelligent_crop_profiles.py`) and `base_async_app.py` are individually sound and worth keeping. Their bugs are at the *seams* (wrong instance lifetimes, wrong method names, mismatched return contracts), not in their internal logic.
- The **orchestrator** (`master_crop_steering_app.py`) is where the engine is fundamentally broken. The central state object is non-writable, there are two competing transition engines, the safety check fails open, several cross-module calls target non-existent methods, and ~5,000 lines hide all of it behind blanket exception handling. The defects are structural, not incidental.

A from-scratch *rewrite of the whole thing* is **not** warranted — that would throw away the genuinely good domain logic (EC steering, dryback math, profiles, fusion). But the orchestrator should be **substantially rewritten** around the existing `ZoneStateMachine` as the *single source of truth* for phase state, deleting the `zone_phases`/`zone_phase_data` properties and the duplicate transition engine entirely.

**This is a "rebuild the spine, keep the organs" situation, not a "salvage as-is" and not a "greenfield."** Be aware the surface area is large: expect the orchestrator rewrite to be the dominant cost. If the owner's tolerance for that is low, a clean greenfield orchestrator (≈800–1,200 lines) that imports the four leaf modules is a defensible alternative and may be faster than excavating the current 5,241-line file.

### 7.2 If fixing — priority order

**P0 — Make it controllable at all (without these, nothing works):**
1. **Eliminate the `@property` state anti-pattern (§6a).** Make `ZoneStateMachine` the single source of truth. Delete `zone_phases`/`zone_phase_data` properties; replace every read with `machine.get_phase_string()` and every write with a real `transition(...)`/state-machine mutation. Rework persistence to serialize/deserialize the machines.
2. **Remove the daytime P0 reset (§6b)** and collapse the **two transition engines** into one. Keep `_check_all_zone_phase_transitions` (it uses the state machine correctly) and delete `_check_phase_transitions`, or merge deliberately. P0 must be a transient morning state.
3. **Resolve the duplicate `_should_zone_start_p3` (§6c)** — one definition, one signature, all callers aligned. Likewise de-duplicate `_get_phase_icon`/`_get_zone_group`/`_get_zone_priority`.
4. **Make safety fail CLOSED (§6d).** Every safety/conflict exception path must return `{'blocked': True}`.

**P1 — Make it correct & observable:**
5. **Fix `set_state` payloads (§6e):** `.isoformat()` all datetimes, drop bare dates for timestamp sensors, sanitize attribute dicts to JSON-serializable values.
6. **Fix the dead cross-module calls (§6f, §6g, §6h, §6i):** rename `predict_target_dryback_time` → `get_dryback_prediction` (and don't `await` it); remove/repair `current_state['current_phase']`; unify the ML predictor return contract with its consumers (or remove the ML layer entirely until needed); replace `force_phase`/`try_transition_to` with `transition()`.

**P2 — Make it robust & generic:**
7. **Define and validate `apps.yaml` schema (§6j):** provide defaults for all sub-keys, validate at startup, fail loudly with a clear message; reconcile the two disagreeing shapes of `config['sensors']`. Ship a documented sample `apps.yaml`.
8. **Per-zone dryback detectors (§6k)** and a **per-signal-type Kalman state** in fusion.
9. **Resolve shot-size-% vs. duration-seconds (§6l):** compute valve seconds from substrate volume × shot% ÷ flow rate, and actually pass that into `_execute_irrigation_shot`.
10. **Reconcile crop-profile names** with the integration's selectable values (§3.6).
11. **De-hard-code site specifics** (F2 interlocks, "Zone 3 fallback") into config.

**P3 — Make it maintainable:**
12. Split the orchestrator into modules (config, control loop, hardware, analytics, persistence, services).
13. Replace blanket `try/except Exception: log+default` with targeted handling so failures are visible.
14. Add unit tests for the leaf modules (easy wins) and an integration harness with a mock `apps.yaml`.

### 7.3 Practical note for the owner

The reason this "has never run correctly" is now concrete: with bugs (a), (b), and (c) all on the daytime happy path, **a zone can never progress P0→P1→P2→P3 while the lights are on**, the orchestrator can't remember any phase timing, and the P3 transition throws on every call — all while the blanket exception handling keeps the logs looking calm. The good news is that the hard part (the domain logic and the state-machine design) already exists and is decent. The work is in **rebuilding the orchestrator's spine** so those organs are actually connected to live hardware.

---

*Analysis produced by reading every line of the 7 modules listed plus the README. No source `.py` files were modified. Line numbers reference the files as they exist at the time of writing.*
