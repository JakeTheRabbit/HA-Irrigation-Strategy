# RootSense v3.0 — Intelligent Crop Steering Upgrade Plan

> Branch: `feat/intelligent-crop-steering`
> Target release: Crop Steering v3.0.0 ("RootSense")
> Status: Planning + scaffolding (this commit)
> Scope: Evolve `JakeTheRabbit/HA-Irrigation-Strategy` from a rule-based 4-phase
> controller into a fully adaptive, agronomically aware crop-steering platform
> running entirely inside Home Assistant + AppDaemon.

---

## 0. Suggested system name

**RootSense** — a four-module intelligence platform layered on top of the
existing Crop Steering integration. The name signals the substrate-first,
sensor-driven foundation while leaving room for canopy/agronomic modules.

The four pillars map 1:1 to the user's brief:

| # | Pillar                       | Module package                                        |
|---|------------------------------|-------------------------------------------------------|
| 1 | Root Zone Intelligence       | `intelligence/root_zone.py`                           |
| 2 | Adaptive Irrigation          | `intelligence/adaptive_irrigation.py`                 |
| 3 | Agronomic Intelligence       | `intelligence/agronomic.py`                           |
| 4 | Irrigation Orchestration     | `intelligence/orchestration.py` + `anomaly.py`        |

Each pillar is a standalone AppDaemon app, opt-in via `apps.yaml`, sharing a
single in-memory bus (`RootSenseBus`) and a SQLite-backed analytics store
(`rootsense.db`) under `appdaemon/apps/crop_steering/state/`.

---

## 1. Executive summary

The current system (`v2.3.1`) is a solid rule-based controller with a 6,263-line
`master_crop_steering_app.py` doing dryback detection, sensor fusion, phase
state machine, ML prediction, and hardware sequencing in one process. It works,
but it is monolithic, the "ML" is a hand-rolled trend tracker, and decisions
are ultimately driven by static thresholds tuned through HA `number` entities.

RootSense v3.0 turns the controller into an adaptive platform:

- **Field capacity is learned, not configured.** A saturation-event detector
  watches every irrigation shot, classifies the substrate's response, and
  publishes a per-zone, per-medium `field_capacity_observed` sensor that the
  controller uses instead of the static `DEFAULT_FIELD_CAPACITY = 70.0`.
- **Cultivator intent replaces hard-coded steering modes.** A single
  `number.crop_steering_steering_intent` (-100 = pure generative, +100 = pure
  vegetative) continuously re-derives every shot-size, dryback target, and EC
  threshold via interpolation between calibrated profiles.
- **The 4-phase machine becomes data-driven.** P0/P1/P2/P3 stay as semantic
  labels for the operator, but transitions are computed from learned dryback
  rate, transpiration estimate, and remaining photoperiod — not fixed durations.
- **Whole-run analytics.** Every shot, dryback, EC drift, and runoff event is
  written to a local SQLite store. A nightly "agronomic report" event is
  emitted for the dashboard with per-cultivar, per-phase aggregates.
- **Cross-cutting anomaly detection.** A dedicated `anomaly.py` runs every
  minute, comparing each zone against (a) its own rolling baseline and (b) its
  peers in the same room/cultivar group, surfacing emitter blockages, EC drift,
  sensor flat-lines, and undetected drybacks before they become yield losses.
- **Fully local.** Everything runs in AppDaemon with `numpy`, `scipy`, and
  `scikit-learn` (already on the AppDaemon container). No outbound calls.
- **Backward compatible.** Existing entities, services, packages, and the
  ESPHome/MQTT sensor topology stay. Each new module is opt-in; users can
  enable Root Zone Intelligence first, leave the rest disabled, and incrementally
  adopt.

---

## 2. Feature mapping

| Current capability (v2.3.x)                                    | New capability (v3.0)                                                                  | Implementation approach                                                                                       |
|----------------------------------------------------------------|----------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------|
| `DEFAULT_FIELD_CAPACITY = 70.0` constant                       | Per-zone, per-cultivar **observed field capacity** with confidence score               | `root_zone.FieldCapacityObserver` analyses every saturation→drainage event, EWMA-smoothed per zone            |
| `AdvancedDrybackDetector` (peaks/valleys, hand-rolled)         | Same detector, **plus** dryback velocity, dryback "shape" classification, runoff link  | Wrap existing detector; add `DrybackEpisode` dataclass persisted to SQLite                                    |
| Static dashboard cards for VWC/EC                              | **Multi-metric historical visualisation** (VWC, EC, substrate temp, runoff EC, shots) | New `dashboards/rootsense_history.yaml` + ApexCharts cards + `recorder` includes for new sensors              |
| `STEERING_MODES = ["Vegetative", "Generative"]` select         | **Cultivator-intent slider** (`number.crop_steering_steering_intent`, −100…+100)       | New number entity in `number.py`; profiles interpolated in `adaptive_irrigation.IntentResolver`               |
| Hard-coded P0 dryback default (`50` veg / `40` gen) with ambiguous "to-or-by?" naming | **Two operator-facing P0 "dries-back-by" sliders**: `number.crop_steering_veg_p0_dryback_drop_pct` (range 2–40, default 12) and `number.crop_steering_gen_p0_dryback_drop_pct` (range 2–50, default 22). Always semantically "% drop from peak VWC". | Endpoints added to `number.py` & `const.py`; `IntentResolver` reads both sliders live every tick and writes the interpolated value to `number.crop_steering_p0_dryback_drop_percent` (the entity the existing P0 exit predicate already consumes) and to `sensor.crop_steering_p0_dryback_drop_pct_current` for dashboards. Legacy `..._dryback_target` entities kept as aliases. |
| Fixed P1 shot ramp, fixed P2 5% shots                          | **Dynamic shot size** computed from dryback velocity, intent, and field capacity       | `adaptive_irrigation.ShotPlanner` replaces hard-coded percentages                                             |
| `SimplifiedIrrigationPredictor` (trend extrapolation)          | **Continuous optimisation loop** with reward = (target dryback hit ± runoff EC error)  | `adaptive_irrigation.OptimisationLoop` — bandit-style adjustment of shot size and interval                    |
| No transpiration model                                         | **VPD + DLI-driven transpiration estimate** per zone                                   | `agronomic.TranspirationModel` (Penman–Monteith approximation, calibrated against measured ΔVWC)              |
| Per-phase logs only                                            | **Whole-run analytics** (per phase, per zone, per cultivar)                            | SQLite store + nightly aggregation in `agronomic.RunAnalytics`                                                |
| Manual override switch per zone                                | **On-demand custom irrigation events with full logging**                               | New service `crop_steering.custom_shot` with `intent`, `volume_ml`, `target_runoff_pct`                       |
| `50_alerts_watchdogs.yaml` (max-runtime watchdog only)         | **Cross-cutting anomaly detection** (emitter, EC drift, sensor flat-line, peer drift) | `anomaly.AnomalyScanner` runs every 60 s, fires `crop_steering_anomaly` events with severity + remediation    |
| Single `master_crop_steering_app.py` (6.3k lines)              | **Modular intelligence apps** + thin coordinator                                       | Move logic into `intelligence/` package; keep master app as event router                                      |
| GUI config via `config_flow.py`                                | **Same**, plus per-pillar enable/disable toggles                                       | Extend `config_flow.py` with options-flow step for module enable/disable                                      |
| AppDaemon `requirements`: `scipy`, `numpy`                     | **Add** `scikit-learn==1.5.*` (locally, no compilation needed on Linux wheels)         | `appdaemon.yaml` `python_packages:`                                                                           |

---

## 3. Step-by-step implementation plan

The plan is broken into five phases. Each phase is independently mergeable, has
its own test plan, and ships behind feature flags so existing users can opt in.

### Status (live)

| Phase | State | Landed |
|---|---|---|
| Phase 0 — Foundation | ✅ done | `bb97e5d` |
| Phase 1 — Root Zone Intelligence | ✅ done | `8da1c6d` (sensors, dryback tracker, module-enable switches, recorder includes); `dashboards/rootsense_history.yaml` added in the polish commit |
| Phase 2 — Adaptive Irrigation | ✅ done | `24d4391` (intent slider, custom_shot service, derived steering-mode select, IntentResolver test suite) |
| Phase 3 — Agronomic Intelligence | ⬜ next | scaffold present (`intelligence/agronomic.py`) — needs sensor calibration + run-report event consumer |
| Phase 4 — Orchestration & Anomaly | 🟡 partial | scaffold present and gated; needs hardware-control takeover + anomaly incident-report generator |
| Phase 5 — Docs / migration / release | 🟡 partial | README RootSense section added; `MIGRATION.md` and `SOFTWARE_VERSION = 3.0.0` bump still pending |

### Phase 0 — Foundation (this commit)

**Goal:** new directory layout, shared infrastructure, no behaviour change.

Files added in this PR:

- `appdaemon/apps/crop_steering/intelligence/__init__.py`
- `appdaemon/apps/crop_steering/intelligence/bus.py` — `RootSenseBus`, in-process pub/sub
- `appdaemon/apps/crop_steering/intelligence/store.py` — SQLite analytics store
- `appdaemon/apps/crop_steering/intelligence/root_zone.py` — Pillar 1 scaffold
- `appdaemon/apps/crop_steering/intelligence/adaptive_irrigation.py` — Pillar 2 scaffold
- `appdaemon/apps/crop_steering/intelligence/agronomic.py` — Pillar 3 scaffold
- `appdaemon/apps/crop_steering/intelligence/orchestration.py` — Pillar 4 scaffold
- `appdaemon/apps/crop_steering/intelligence/anomaly.py` — cross-cutting scanner
- `docs/upgrade/ROOTSENSE_v3_PLAN.md` — this document
- `blueprints/automation/crop_steering/rootsense_intent.yaml` — operator-facing intent blueprint
- `CHANGELOG.md` entry under `## [Unreleased]`

The scaffolds are runnable AppDaemon apps that log "ready" on startup but do
not control hardware. `apps.yaml` is **not** modified yet — opting in is
documented but not automatic, so existing installs are unaffected.

### Phase 1 — Root Zone Intelligence (PR #2)

1. **Field-capacity observer** (`root_zone.FieldCapacityObserver`)
   - Subscribes to `crop_steering_irrigation_shot` events.
   - For each shot, captures pre-shot VWC and post-shot peak (peak detected
     within `shot_response_window_sec`, default 600 s).
   - When successive shots produce <0.5% additional VWC rise, declares the
     zone *saturated* and records the peak as a candidate field-capacity
     observation.
   - Maintains an EWMA per (zone, cultivar) and exposes
     `sensor.crop_steering_zone_{n}_field_capacity_observed` with attributes
     `confidence`, `sample_count`, `last_updated`.
   - Confidence ≥ 0.8 → controller switches from `DEFAULT_FIELD_CAPACITY` to
     observed value automatically. The integration's `const.py`
     `DEFAULT_FIELD_CAPACITY` becomes a fallback only.

2. **Dryback episodes** (`root_zone.DrybackEpisode`)
   - Wraps the existing `AdvancedDrybackDetector`.
   - Persists each episode (`peak_vwc`, `valley_vwc`, `pct`, `duration_min`,
     `slope`, `phase`, `ec_at_peak`, `ec_at_valley`, `vpd_avg`,
     `light_dli_partial`) to SQLite for the analytics module.
   - Emits `crop_steering_dryback_complete` events with the full payload.

3. **Substrate analytics sensors** — new template/derived sensors (computed in
   the AppDaemon module, published via `mqtt.publish` for dashboard use):
   - `sensor.crop_steering_zone_{n}_dryback_velocity_pct_per_hr`
   - `sensor.crop_steering_zone_{n}_substrate_porosity_estimate`
   - `sensor.crop_steering_zone_{n}_ec_stack_index` (cumulative drift)

4. **Multi-metric history dashboard** — `dashboards/rootsense_history.yaml`
   with ApexCharts overlays for VWC + EC + shots + photoperiod marker.

5. **Recorder includes** — extend the irrigation package
   (`packages/irrigation/00_core.yaml`) with explicit `recorder.include` for
   the new sensors so the new history dashboard works without extra setup.

### Phase 2 — Adaptive Irrigation Intelligence (PR #3)

1. **Cultivator intent** — new `number.crop_steering_steering_intent`
   (range −100 … +100, step 5, default 0).
   - −100 = "pure generative" (large dryback target, larger less-frequent shots,
     higher EC ceiling).
   - +100 = "pure vegetative" (small dryback target, more shots, lower EC).
   - Runtime-editable via the existing GUI.

2. **Profile interpolation** (`adaptive_irrigation.IntentResolver`)
   - Loads two endpoint profiles per cultivar from `intelligent_crop_profiles.py`
     and interpolates every parameter:
     `value = lerp(profile_gen[k], profile_veg[k], (intent + 100) / 200)`
   - Re-publishes derived parameters (P1 target VWC, P2 threshold, dryback
     drop %, EC target, shot size) every time the intent slider moves.
   - Existing `select.crop_steering_steering_mode` becomes a derived select
     showing `Vegetative` / `Generative` / `Mixed (intent=+25)`.

   **P0 dryback is fully operator-controlled.** No code path uses a hard-coded
   number for "what % to dry back by". The two endpoints are read live every
   tick from `number.crop_steering_veg_p0_dryback_drop_pct` and
   `number.crop_steering_gen_p0_dryback_drop_pct`, and only fall back to
   `DEFAULT_VEG_P0_DRYBACK_DROP_PCT` / `DEFAULT_GEN_P0_DRYBACK_DROP_PCT` from
   `const.py` if the entities are unavailable. Both values are *drops* from
   peak VWC — never absolute VWC targets. The interpolated current target is
   exposed as `sensor.crop_steering_p0_dryback_drop_pct_current` and pushed
   into the legacy `number.crop_steering_p0_dryback_drop_percent` entity that
   the master app's P0-exit predicate already reads, so no other code change
   is needed for the new semantic to take effect.

3. **Shot planner** (`adaptive_irrigation.ShotPlanner`)
   - On each P1/P2 shot decision, computes shot volume from:
     - observed field capacity
     - current VWC vs target
     - dryback velocity (recovery shot vs maintenance shot)
     - cultivator intent (bias toward dryback or rebound)
   - Issues `crop_steering.custom_shot` rather than a hard-coded percentage.

4. **Continuous optimisation loop** (`adaptive_irrigation.OptimisationLoop`)
   - Reward function `r = -(|observed_dryback − target_dryback|) − 0.5 * |ec_runoff − ec_feed * target_ratio|`
   - One-armed bandit (Thompson sampling, conjugate normal-gamma prior, all in
     `numpy` — no scikit-learn needed for this part) tunes shot-size delta
     and inter-shot interval per zone, persisting posterior in SQLite.
   - Hard guardrails: no shot >2× field-capacity volume, no inter-shot interval
     <`min_shot_spacing_sec` (default 90 s).

5. **Phase-machine refactor** — `phase_state_machine.py` keeps its API but
   its transition predicates now consult `OptimisationLoop` for "should we
   move to P3" / "is P0 dryback complete" instead of fixed durations.

### Phase 3 — Agronomic Intelligence (PR #4)

1. **Transpiration model** (`agronomic.TranspirationModel`)
   - Penman–Monteith style approximation:
     `ET_h = (0.408 * Δ * (Rn) + γ * (900/(T+273)) * u * (es-ea)) / (Δ + γ * (1 + 0.34*u))`
     where `Rn` is derived from PPFD or lux sensor, `es-ea` from VPD,
     `u` defaults to `room_air_movement_m_s` number entity.
   - Calibrates a per-zone gain factor against measured `ΔVWC * substrate_volume_L`
     during P0 (no irrigation interferes there).
   - Publishes `sensor.crop_steering_zone_{n}_transpiration_ml_per_hr`.

2. **Climate–substrate interaction** (`agronomic.ClimateSubstrateModel`)
   - Rolling Pearson correlation between VPD and dryback velocity per cultivar.
   - Identifies "VPD ceiling" — the VPD above which substrate dryback
     accelerates non-linearly — and exposes
     `sensor.crop_steering_cultivar_{c}_vpd_ceiling_kpa`.

3. **Whole-run analytics** (`agronomic.RunAnalytics`)
   - Aggregates SQLite store nightly at `lights_off + 1h`.
   - Emits `crop_steering_run_report` event with: shots/zone, total mL/zone,
     mean dryback %, dryback variance, EC drift, anomalies, transpiration
     totals.
   - Dashboard card subscribes via `event` trigger.

4. **Cultivar registry** — extend `intelligent_crop_profiles.py` with calibrated
   defaults for Cannabis Athena / Hybrid / Indica / Sativa endpoint profiles
   for the IntentResolver.

### Phase 4 — Orchestration & Anomaly Detection (PR #5)

1. **Coordinator** (`orchestration.Coordinator`)
   - Replaces the decision loop currently inside
     `master_crop_steering_app.py`. Master app shrinks to ~500 lines: it owns
     hardware sequencing and event routing only.
   - Subscribes to all `RootSenseBus` topics, arbitrates between modules.
     E.g., if `anomaly.scanner` raises a `valve_stuck` event the coordinator
     suppresses any pending shot to that zone.

2. **On-demand custom shots** — new HA service
   `crop_steering.custom_shot`:
   ```yaml
   target_zone: 1
   intent: "rescue" | "rebalance_ec" | "test_emitter" | "free_text"
   volume_ml: 250
   target_runoff_pct: 15        # optional, planner will stop early if reached
   tag: "operator_morning_check"  # logged for analytics
   ```
   The service writes a row into the analytics store, fires
   `crop_steering_custom_shot`, and the orchestration coordinator schedules it
   through normal safety gates.

3. **Emergency irrigation guardrails**
   - Existing emergency rescue at `VWC < 40` is preserved.
   - Added: `ec_runoff > 1.5 * ec_feed` triggers a `flush_shot` (10 % FC volume)
     with a hard cap of one flush per 4 h per zone.
   - Added: `vwc_flat_for > 30 min during photoperiod` raises an anomaly,
     does **not** auto-irrigate (likely sensor failure), notifies operator.

4. **Anomaly scanner** (`anomaly.AnomalyScanner`, runs every 60 s)
   - Per-zone rules:
     - `emitter_blockage`: shot fired but ΔVWC over `shot_response_window_sec`
       < 0.3% on >2 consecutive shots.
     - `ec_drift_high`: 6-h rolling mean EC > 1.3× target.
     - `vwc_flat_line`: stddev over last 30 min < 0.05% during photoperiod.
     - `dryback_undetected`: 4 h since last detected peak during photoperiod.
   - Peer-comparison rules (zones in same room with same cultivar):
     - `peer_vwc_deviation`: zone VWC > 2σ from peer mean for 15 min.
     - `peer_ec_deviation`: zone EC > 2σ from peer mean for 30 min.
   - Each anomaly fires `crop_steering_anomaly` with payload
     `{zone, code, severity, evidence, remediation}`, written to SQLite, and
     surfaces on a `binary_sensor.crop_steering_anomaly_active`.

5. **Incident reports** — `agronomic.RunAnalytics` correlates anomalies that
   occurred during a run and adds them to the nightly report, generating a
   markdown remediation block (e.g. "Zone 3 emitter blocked at 14:32 — recommended
   actions: 1) inspect dripper line; 2) test emitter pressure; 3) re-run
   `crop_steering.custom_shot zone=3 intent=test_emitter volume_ml=50`").

### Phase 5 — Documentation, Migration, Release (PR #6)

- `docs/upgrade/ROOTSENSE_v3_PLAN.md` (this file) → split into per-pillar
  user docs in `docs/intelligence/`.
- `MIGRATION.md` — step-by-step from v2.3.x to v3.0 (no data loss; intent
  slider defaults to 0 = legacy "Vegetative" behaviour for first 7 days).
- `CHANGELOG.md` — versioned entry per PR.
- Update `manifest.json` and `const.py` `SOFTWARE_VERSION` to `3.0.0`.

---

## 4. Blueprint examples

### 4.1 `blueprints/automation/crop_steering/rootsense_intent.yaml`

A blueprint so growers can wire the cultivator intent slider to a remote, NFC
tag, voice command, or schedule without writing YAML.

```yaml
blueprint:
  name: RootSense — Cultivator Intent Setter
  description: >
    Set the global crop-steering intent (-100 = pure generative,
    +100 = pure vegetative). Use a schedule helper, button, voice command,
    or any trigger to bias the controller's behaviour without touching
    individual thresholds.
  domain: automation
  input:
    trigger_event:
      name: Trigger
      description: What should set the intent?
      selector:
        trigger:
    target_intent:
      name: Target intent
      description: -100 (generative) … +100 (vegetative)
      default: 0
      selector:
        number:
          min: -100
          max: 100
          step: 5
          mode: slider
    notify_target:
      name: Notification target (optional)
      default: ""
      selector:
        text:

trigger: !input trigger_event

action:
  - service: number.set_value
    target:
      entity_id: number.crop_steering_steering_intent
    data:
      value: !input target_intent
  - if:
      - condition: template
        value_template: "{{ notify_target | length > 0 }}"
    then:
      - service: notify.send_message
        target:
          entity_id: !input notify_target
        data:
          message: >
            Crop-steering intent set to {{ states('number.crop_steering_steering_intent') }}.
```

### 4.2 `blueprints/automation/crop_steering/rootsense_anomaly_handler.yaml`

```yaml
blueprint:
  name: RootSense — Anomaly Handler
  description: >
    Listen for crop_steering_anomaly events and route them. Severities map
    to your preferred notification target, and the remediation steps are
    included verbatim in the message.
  domain: automation
  input:
    severity_min:
      name: Minimum severity
      default: warning
      selector:
        select:
          options: [info, warning, critical]
    info_target:
      name: Info notification target
      default: ""
      selector: { text: {} }
    warning_target:
      name: Warning notification target
      default: ""
      selector: { text: {} }
    critical_target:
      name: Critical notification target
      default: ""
      selector: { text: {} }

trigger:
  - platform: event
    event_type: crop_steering_anomaly

variables:
  severity: "{{ trigger.event.data.severity }}"
  zone: "{{ trigger.event.data.zone }}"
  code: "{{ trigger.event.data.code }}"
  remediation: "{{ trigger.event.data.remediation | default('See dashboard for details.') }}"
  target: >
    {% if severity == 'critical' %}{{ critical_target }}
    {% elif severity == 'warning' %}{{ warning_target }}
    {% else %}{{ info_target }}{% endif %}

condition:
  - condition: template
    value_template: >
      {% set order = {'info': 0, 'warning': 1, 'critical': 2} %}
      {{ order[severity] >= order[severity_min] }}
  - condition: template
    value_template: "{{ target | length > 0 }}"

action:
  - service: notify.send_message
    target:
      entity_id: "{{ target }}"
    data:
      title: "🌱 RootSense — {{ severity | upper }}: Zone {{ zone }} {{ code }}"
      message: |
        {{ trigger.event.data.evidence }}

        Recommended actions:
        {{ remediation }}
```

---

## 5. Testing & validation

The existing `tests/` directory uses `pytest` with HA fixtures. The new
modules are pure-Python and easy to unit-test in isolation.

### Unit tests (PR-local)

- `tests/intelligence/test_field_capacity_observer.py`
  - Feed a synthetic shot → VWC-rise series, assert FC observation
    converges to ground truth within 5 shots.
- `tests/intelligence/test_intent_resolver.py`
  - Sweep intent −100 → +100, assert all derived parameters monotonic.
- `tests/intelligence/test_shot_planner.py`
  - Property test: planner never requests volume > 2× FC, never <50 mL.
- `tests/intelligence/test_optimisation_loop.py`
  - Simulated environment: 100 P0/P1 cycles, assert reward improves
    over time vs static baseline.
- `tests/intelligence/test_anomaly_scanner.py`
  - Inject blocked-emitter scenario (shots with ΔVWC ≈ 0), assert
    `emitter_blockage` event fires within 3 shots.

### Integration tests (HA + AppDaemon)

- The repo already has the "Crop Steering Test Helpers" device with
  `input_boolean` valves and `input_number` sensors. Extend with:
  - `input_number.test_dripper_blockage` (0…1 fraction) — when nonzero,
    the test sensor harness damps simulated VWC rise. Confirms
    end-to-end anomaly path.
  - `input_select.test_steering_intent_target` — automation flicks intent
    every minute and asserts derived numbers update within one tick.

### Field validation (pre-release)

Three-tier rollout:

1. **Shadow mode (week 1):** modules read sensors and write log events
   only. No service calls. Operator compares logged decisions to the
   live v2.3 controller.
2. **Co-pilot mode (week 2):** intent slider active, but every shot is
   gated on `input_boolean.crop_steering_rootsense_arm`. Operator
   approves the first 100 shots manually; auto-arms once 95 % approval
   rate is reached.
3. **Full autonomy (week 3+):** orchestration module has full control;
   master app is the hardware-only layer. Anomaly notifications go to
   operator's preferred channel.

### CI

- `ruff check . && black --check . && yamllint -s .` (existing).
- New: `pytest tests/intelligence/ -v --cov=appdaemon/apps/crop_steering/intelligence --cov-fail-under=80`.

---

## Companion plans (sibling work tracked separately)

- **`LLM_HEALTHCHECK_PLAN.md`** — frontier-LLM advisor that consumes a
  15-min compact report and proposes intent/shot adjustments. Token
  minimisation strategy: gated triage rules + prompt caching + JSON-
  schema'd output + tiered model routing. Targets RootSense v3.3.
- **`CLIMATESENSE_PLAN.md`** — environmental control sibling. Setpoints
  timeline (recipe-driven temp/RH/CO₂/DLI/photoperiod), PID closed-loop
  control, climate anomaly scanner. Mirrors RootSense's pillar
  architecture and shares the bus/store. Optionally drives
  `crop_steering_steering_intent` from the recipe.

## 6. Future roadmap (post-v3.0)

- **v3.1 — Multi-room federation.** Treat each grow room as a
  `RootSenseDomain`; share cultivar field-capacity observations between
  rooms growing the same strain to bootstrap new transplants faster.
- **v3.2 — Recipe library.** Export/import a full crop-steering recipe
  (intent schedule + cultivar profile + EC ramp + photoperiod) as a
  single YAML; pin to a strain in the cultivar registry.
- **v3.3 — Local LLM advisor.** Optional integration with a locally
  hosted model (Ollama, LM Studio) that ingests the nightly run report
  and produces a plain-English summary + suggested intent adjustment for
  the next 24 h. Off by default; no data leaves the LAN.
- **v3.4 — Vision-based canopy module.** Optional Frigate integration:
  a daily canopy-density estimate from a top-down camera feeds the
  transpiration model's leaf-area-index term.
- **v3.5 — Runoff conductivity controller.** Closed-loop on runoff EC
  via a feed-EC dosing pump (Atlas Scientific or similar) — extends the
  current EC monitoring into active control.

---

## 7. Risks & mitigations

| Risk                                                   | Mitigation                                                                              |
|--------------------------------------------------------|-----------------------------------------------------------------------------------------|
| Adaptive loop misbehaves and drowns/dries plants       | Hard guardrails in `ShotPlanner`; co-pilot-mode rollout; unchanged emergency rescue     |
| New SQLite store grows unbounded                       | Daily VACUUM; 90-day rolling retention by default; configurable                         |
| Sensor outages confuse field-capacity observer         | Observer requires both VWC sensors (front+back) reporting & in-range; otherwise skip    |
| Existing users on v2.3 are surprised by behaviour     | All new pillars opt-in; intent defaults to 0; `MIGRATION.md` walks through 7-day phase  |
| AppDaemon container missing scikit-learn               | Used only in `OptimisationLoop`; module logs and degrades to fixed-step search if absent |

---

*End of plan. The accompanying scaffolds in
`appdaemon/apps/crop_steering/intelligence/` are runnable but inert; they will
be wired in during PRs #2–#5 above.*
