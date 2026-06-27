# Setpoints, Steering Bias & the Athena Stage Reference

> **Status banner — read this first.**
>
> This doc has two parts. **§1–§3 describe what is IMPLEMENTED today** and gives you a
> stage-by-stage table of *starting setpoints to dial into the live per-zone entities by
> hand*. **§4 onward is a PROPOSED design** for an automatic recipe engine that would write
> those setpoints for you each grow-day — that engine is **NOT built**. None of the
> `select.crop_steering_grow_stage` / `select.crop_steering_recipe_mode` /
> `switch.crop_steering_auto_setpoints` / `input_datetime.crop_steering_flip_date` /
> `sensor.crop_steering_setpoint_plan` entities exist in the integration or the add-on.
> Nothing in this repo auto-applies a recipe. Treat §4+ as a roadmap, not a feature.
>
> **What actually drives setpoints today:** *you* set the per-zone `number.crop_steering_*`
> entities (see §1). The live **f2-control add-on** reads those numbers every 60 s and runs
> P0→P1→P2→P3 against them. It does **not** change them. The only "automatic" choice the
> engine makes is veg-vs-generative EC target selection, from the `growth_stage` /
> `zone_N_steering_mode` selects you set — see §2.

---

## 1. How setpoints work today (implemented)

There is no auto-setpoint-writer. The operator owns every setpoint; the engine consumes
them. The relevant live layers:

- **HA integration** (`custom_components/crop_steering/`) — defines the entities and pure
  calcs. Never touches hardware.
- **f2-control add-on** (`addons/f2_control/`) — the live engine. Polls HA REST every 60 s,
  reads the setpoint numbers, runs per-zone P0→P1→P2→P3, drives hardware. Gated by the kill
  switch `input_boolean.f2_control_enabled` (OFF = safe, no actuation).

### Per-zone setpoint entities (live, you edit these)

Each of these exists **globally** (`number.crop_steering_<param>`) and **per zone**
(`number.crop_steering_zone_N_<param>`); a set per-zone value overrides the global for that
zone. Confirmed in `custom_components/crop_steering/number.py`:

| Setpoint (entity key) | What it sets |
|---|---|
| `p0_dryback_drop_percent` | Morning dryback: % point VWC drop from peak before P0→P1 |
| `veg_p0_dryback_drop_pct` / `gen_p0_dryback_drop_pct` | Mode-specific P0 dryback defaults (Athena veg 12 / gen 22) |
| `p1_target_vwc` | P1 ramp-to VWC target |
| `p2_vwc_threshold` | P2 maintenance floor — top up when VWC drops below this |
| `p2_shot_size` | P2 top-up shot size (% of substrate) |
| `field_capacity` | VWC ceiling |
| `p3_emergency_vwc_threshold` | P3 emergency floor |
| `ec_target_veg_p0..p3` / `ec_target_gen_p0..p3` | Per-phase pore-EC targets, one row per steering mode |
| `maximum_ec` | EC ceiling / guardrail |

> **Dryback semantics (matches CLAUDE.md):** every dryback value is a **% point drop from
> the post-irrigation peak VWC** (dries-back-*by*, not dries-back-*to*). All VWC values are
> % of substrate volume.

### Minimum daily-water floor (live)

`input_number.crop_steering_zone_N_min_daily_ml_per_plant` — a per-zone floor read live by
the add-on (`controller.py`): `mL/plant × plant_count → zone-litre floor`. If the day's
delivered volume is short of the floor the engine makes it up, bounded by the anti-drown VWC
cap (`number.crop_steering_zone_N_min_floor_drown_ceiling`). Set to 0 to disable. This is the
real, live way to guarantee a daily minimum — not a recipe feature.

### The Cultivator-Intent dial (live, but not a recipe applier)

`number.crop_steering_steering_intent` — a single −100 (pure generative) … +100 (pure
vegetative) dial, default 0 = balanced. The derived view `select.crop_steering_steering_mode_derived`
(Generative / Mixed-generative / Balanced / Mixed-vegetative / Vegetative) reflects it. This
biases derived parameters; it does **not** stamp a stage recipe onto the setpoint entities.

---

## 2. Steering bias today (implemented)

The live engine picks **vegetative vs generative EC targets per zone** from the selects you
set (`controller.py::_veg`):

- `select.crop_steering_zone_N_steering_mode` (`Vegetative` / `Generative`) — per zone.
- Falls back to the global `select.crop_steering_growth_stage` if the zone one is unset.

A zone in vegetative mode uses the `ec_target_veg_p*` row; generative uses `ec_target_gen_p*`.
That is the full extent of automatic steering: a row selection, driven by a select you
control. There is no automatic stage progression and nothing writes the VWC/dryback numbers
for you.

> **Known live quirk:** `growth_stage`, `steering_mode`, and the nutrient/phase fields are
> independent selects and can read inconsistently (e.g. `growth_stage=Vegetative` while a
> dashboard shows a "Stretch" label). Today that's resolved by you keeping them consistent.
> A single-source-of-truth resolver is part of the *proposed* design in §4, not built.

---

## 3. Athena stage reference — starting setpoints to dial in by hand

This is the useful, durable part of this doc: a stage-by-stage register of **starting
setpoints you type into the live per-zone `number.crop_steering_*` entities** (§1). They are
*starting points to dial in for your substrate/cultivar*, not gospel, and **nothing applies
them automatically** — you enter them.

### Stages (coco, ~9–10 week flower — adjust week boundaries to your run)

| # | Stage | Weeks (from flip) | Steering bias | Intent |
|---|---|---|---|---|
| 0 | Propagation | clones/seedlings | Neutral, very gentle | Establish roots; minimal stress |
| 1 | Vegetative | veg period | **Vegetative** | Build structure; high hydration, small dryback |
| 2 | Stretch / early flower | wk 1–3 | **Generative** | Control stretch, set flower sites; bigger dryback, EC climbs |
| 3 | Bulk | wk 3–6 | **Vegetative-bias** | Maximise size; stable high VWC, high EC |
| 4 | Ripen | wk 6–8 | **Generative** | Density & finish; larger dryback, EC stacks |
| 5 | Flush | final ~7 days | Neutral | Drop EC, maintain VWC |

### Starting setpoint profile per stage (dial these into the live entities)

| Setpoint (live entity key) | Prop | Veg | Stretch | Bulk | Ripen | Flush |
|---|---|---|---|---|---|---|
| Steering mode (`growth_stage`/`zone_N_steering_mode`) | Veg | Veg | **Gen** | Veg | **Gen** | Veg |
| `p0_dryback_drop_percent` | 5 | 10 | 18 | 14 | 22 | 12 |
| Overnight dryback target | 8 | 12 | 22 | 16 | 28 | 14 |
| `p1_target_vwc` | 62 | 65 | 58 | 64 | 55 | 62 |
| `p2_vwc_threshold` | 58 | 60 | 50 | 58 | 46 | 56 |
| `field_capacity` (ceiling) | 65 | 68 | 66 | 68 | 64 | 66 |
| `p3_emergency_vwc_threshold` | 45 | 42 | 38 | 42 | 36 | 42 |
| `p2_shot_size` (%) | 3 | 5 | 4 | 5 | 4 | 5 |
| Active EC target (mS/cm) | 1.8 | 2.8 | 4.0 | 5.5 | 6.0 | 0.8 |
| Last shot before lights-off (min) | 60 | 45 | 90 | 45 | 120 | 45 |

How to read the shape:
- **Vegetative stages** (Veg, Bulk): high `p2_vwc_threshold`, small dryback, lower EC, shots
  fire sooner → less stress, more vegetative growth.
- **Generative stages** (Stretch, Ripen): lower `p2_vwc_threshold` (let it dry further),
  bigger dryback, higher EC, last shot earlier so it dries overnight → more stress.
- **EC** climbs through bulk/ripen, then **Flush** drops to the flush target.
- **EC is per-phase.** The live entities are `ec_target_veg_p0..p3` / `ec_target_gen_p0..p3`.
  The "Active EC target" above is the headline P2 value; set P0/P1 ≈ that, P3 ≈ target × 0.95,
  in the row matching the stage's steering mode.
- **Per-zone:** enter these on each `zone_N_*` entity. Scale a zone by its
  `number.crop_steering_zone_N_shot_size_multiplier` if rows differ.

> **Whose number does the engine read?** Before driving a dryback target, confirm against
> `addons/f2_control/` which entity the live engine actually consumes and its units
> (drop-from-peak vs target-VWC) — dryback is *% point drop from peak* per CLAUDE.md. Don't
> dial a value into an entity the engine ignores.

---

## 4. PROPOSED (not built): an automatic stage→setpoint recipe engine

> **Everything below is a design proposal. None of it is implemented.** No entity, module,
> or service named here exists in the integration or the add-on. If built, it would live in
> the **f2-control add-on** (`addons/f2_control/`), *not* in AppDaemon — AppDaemon is retired
> (rollback only). This section is kept as a roadmap of what "make the AI set the setpoints"
> could responsibly mean.

The idea: each grow-day, look at where the crop is in its life cycle, what steering bias the
stage calls for, and which supporting signals are trusted, then **write** the §3 starting
values into the live `number.crop_steering_*` entities — clamped, rate-limited, logged, and
overridable. A deterministic, explainable recipe (the §3 table encoded), not a black-box ML
model. Explicitly *not* in scope even if built: auto-changing safety limits, or big mid-day
swings (a recipe would re-plan once per grow-day at lights-on and ramp over days).

### Inputs it would read

- **Grow anchor** — a new `input_datetime.crop_steering_flip_date`; week = `floor((today −
  flip_date)/7)` → stage. Plus a manual `select.crop_steering_grow_stage` override.
- **Steering intent** — a `select.crop_steering_steering_intent` (`Auto / Force Veg / Force
  Gen / Hold`). Note this would be a *select*, distinct from the live
  `number.crop_steering_steering_intent` −100..+100 dial that exists today (§1).
- **Capability gates** — only attempt what trusted data supports (per-zone VWC/EC freshness,
  EC-stacking switch + source-EC headroom, source-water EC sensor, dosing interlock); degrade
  gracefully and log what it down-graded.

### How it would write, and the guardrails

A new add-on module would, once per grow-day ~5 min after lights-on (after the P3→P0 reset)
and on a manual stage/intent change: resolve stage → resolve intent → check gates →
interpolate the day's targets → **clamp** to each entity min/max + safety envelope →
**rate-limit** vs current → skip any held setpoint → preview or apply via `number.set_value`
→ log every change. Non-negotiables if built:

1. **Clamp to entity bounds** — out-of-range values can't apply.
2. **Never auto-widen the safety envelope** — `maximum_ec`, source pH/EC gate, daily-volume
   caps are ceilings the recipe clamps *under*, never relaxes.
3. **Rate-limit** — max step/day per setpoint; stage transitions ramp over days.
4. **Manual hold wins** — a pinned or recently-edited setpoint is left alone.
5. **No mid-cycle writes** — not during irrigation, dosing, or the startup grace window.
6. **Fail-safe on missing data** — hold last-known-good, raise a note, never guess.
7. **Full audit trail** — `who(recipe)/what/old→new/why` to the activity log.
8. **Master arm, default OFF** — a `switch.crop_steering_auto_setpoints`, plus a
   `select.crop_steering_recipe_mode` (Off / Preview / Auto-apply) so it can publish a
   proposed-vs-current plan to a preview sensor before it's ever allowed to write.

### Proposed new entities (none exist yet)

`switch.crop_steering_auto_setpoints`, `select.crop_steering_recipe_mode`,
`input_datetime.crop_steering_flip_date`, `select.crop_steering_grow_stage`,
`select.crop_steering_steering_intent`, `sensor.crop_steering_setpoint_plan`,
`sensor.crop_steering_grow_day`, `sensor.crop_steering_last_recipe_change`.

### Optional later: bounded adaptive trim

Once a deterministic recipe were trusted, small bounded feedback could self-correct (dryback
achieved vs target, EC trajectory, VWC tracking) — small, slow, tightly bounded, logged,
Auto-apply only. Still a roadmap item, not built.

---

## 5. Open questions if this is ever built

1. Grow anchor: flip-date + auto stage, manual stage select, or both?
2. Stage boundaries / flower length for your actual schedule?
3. Are the §3 starting setpoints in the right ballpark for your substrate/cultivar, or is
   there an Athena/AROYA register to encode?
4. One room recipe with per-zone multipliers, or independent per-zone recipes?
5. Confirm which entity/units the live engine reads for dryback before any auto-write.
6. Start in Preview (no writes) for a full grow-day before Auto-apply?
