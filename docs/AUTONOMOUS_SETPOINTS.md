# Autonomous Setpoint Configuration — Design Guide

> **Status: design for review.** Nothing here is implemented yet. Read it, mark it up,
> then we build it in the phases at the end. Numbers in the recipe table are *starting
> points to dial in*, not gospel.

## 1. What we're actually building (and what we're deliberately not)

The ask: *"make the AI configure the setpoints based off the day it is, the type of
steering required, and the other inputs that are enabled to support it."*

What that should be, for a **live regulated medicinal grow**, is an **autonomous
agronomic recipe engine**:

> Each grow-day it looks at *where the crop is in its life cycle*, *what steering bias
> that stage calls for*, and *which supporting signals are available and trusted*, then
> writes the appropriate setpoints into the existing `number.crop_steering_*` entities —
> clamped to safe bounds, rate-limited, fully logged, and overridable.

What it is **not**, and why:

| Tempting | Why we're not doing it (yet) |
|---|---|
| A black-box ML model that "learns" setpoints | Unauditable, needs a lot of clean labelled data, and a wrong guess waters real plants. Indefensible in a regulated facility. |
| Changing safety limits automatically | The EC cap, pH/EC source gate, and daily volume caps are the *guardrails*. The recipe steers **within** them; it never relaxes them. |
| Big mid-day setpoint swings | Setpoints change **once per grow-day at lights-on**, and ramp over days — never lurching mid-cycle. |

The "AI" here is a **deterministic, explainable recipe** plus an optional **bounded
adaptive trim** (Phase 2) that nudges a few targets based on observed plant response.
That is the responsible, dial-in-able version of "the AI sets the setpoints," and it's
exactly how AROYA/Athena-style "crop registers" actually work under the hood.

---

## 2. The three inputs it reads

### A. "What day it is" — the grow anchor

The system currently has **no concept of grow age** (batch/plant-date is *not tracked* —
the dashboards say so explicitly). We have to give it one. Two options:

| Option | How | Pros / cons |
|---|---|---|
| **Flip-date anchor** *(recommended)* | New `input_datetime.crop_steering_flip_date` (the day you flipped to 12/12, or the grow start). Engine computes **week = floor((today − flip_date)/7)** and maps week → stage. | Set once per grow, fully automatic afterwards. Survives restarts. |
| **Manual stage select** | New `select.crop_steering_grow_stage` you advance by hand (Propagation / Veg / Stretch / Bulk / Ripen / Flush). | Dead simple, no date math, but relies on you remembering to advance it. |

**Recommendation:** do **both** — derive the stage from the flip date, but expose the
`grow_stage` select as a manual override that, when not set to `Auto`, wins. Best of both:
hands-off normally, manual when you're doing something non-standard.

### B. "Type of steering required" — the steering intent

Each stage has a **default steering bias** (vegetative ⇄ generative). The recipe sets
`select.crop_steering_steering_mode` and `select.crop_steering_growth_stage` from the
stage automatically — *but* a new `select.crop_steering_steering_intent`
(`Auto / Force Vegetative / Force Generative / Hold`) lets you bias it without fighting
the recipe. `Hold` freezes all setpoints where they are (useful while you investigate
something).

> This also **fixes the live conflict** the dashboards keep flagging
> (`growth_stage=Vegetative` vs `growth_phase=Stretch` vs `nutrient_phase=Bloom`): the
> recipe engine becomes the **single source of truth** that sets all the steering
> selects together, so they can't drift apart.

### C. "Other inputs enabled to support it" — capability gates

The recipe should only attempt what the available, trusted data can support, and
**degrade gracefully** otherwise. Before each run it checks:

| Capability | Signal it needs | If missing → fallback |
|---|---|---|
| Per-zone steering | `sensor.crop_steering_zone_N_vwc/ec` fresh & trusted (`sensor_health`, fusion conf) | Fall back to room-average targets; skip aggressive per-zone drybacks |
| EC stacking (ripen) | `switch.crop_steering_ec_stacking_enabled` on **and** source EC headroom | Cap EC targets at the non-stacking ceiling |
| Source-water aware feed | `sensor.atlas_legacy_1_ec` (source EC) fresh | Use absolute EC targets, don't subtract source EC |
| Climate-aware (Phase 2) | `sensor.veg_scd41_*`, computed VPD | Skip transpiration-linked trims |
| Dosing interlock | `input_boolean.nutrient_dosing_active` | Never re-write setpoints while dosing |

The principle: **the recipe picks the richest profile the inputs can actually support,
and is honest in the log about what it down-graded and why.**

---

## 3. The recipe model — the agronomic core

A grow is split into **stages**, each with a steering bias and a **setpoint profile**.
The engine interpolates between adjacent stages day-by-day so nothing jumps.

### Stages (coco, ~9–10 week flower — adjust week boundaries to your run)

| # | Stage | Weeks (from flip) | Steering bias | Intent |
|---|---|---|---|---|
| 0 | Propagation | clones/seedlings | Neutral, very gentle | Establish roots; minimal stress |
| 1 | Vegetative | veg period | **Vegetative** | Build structure; high hydration, small dryback |
| 2 | Stretch / early flower | wk 1–3 | **Generative** | Control stretch, set flower sites; bigger dryback, EC climbs |
| 3 | Bulk | wk 3–6 | **Vegetative-bias** | Maximise size; stable high VWC, high EC |
| 4 | Ripen | wk 6–8 | **Generative** | Density & finish; larger dryback, EC stacks |
| 5 | Flush | final ~7 days | Neutral | Drop EC, maintain VWC |

### Setpoint profile per stage (starting values — *dial these in*)

> **Dryback %** = percentage-**point drop from the post-irrigation peak VWC**
> (dries-back-*by*, not to). All VWC values are % of substrate volume.

| Setpoint (entity) | Prop | Veg | Stretch | Bulk | Ripen | Flush |
|---|---|---|---|---|---|---|
| Steering mode | Veg | Veg | **Gen** | Veg | **Gen** | Veg |
| `p0_dryback_drop_percent` (morning dryback → P1) | 5 | 10 | 18 | 14 | 22 | 12 |
| Overnight dryback target | 8 | 12 | 22 | 16 | 28 | 14 |
| `p1_target_vwc` (ramp-to) | 62 | 65 | 58 | 64 | 55 | 62 |
| `p2_vwc_threshold` (maintenance floor) | 58 | 60 | 50 | 58 | 46 | 56 |
| `field_capacity` (ceiling) | 65 | 68 | 66 | 68 | 64 | 66 |
| `p3_emergency_vwc_threshold` | 45 | 42 | 38 | 42 | 36 | 42 |
| `p2_shot_size` (%) | 3 | 5 | 4 | 5 | 4 | 5 |
| Active EC target (mS/cm) | 1.8 | 2.8 | 4.0 | 5.5 | 6.0 | 0.8 |
| `p3_veg_last_irrigation` (min before off) | 60 | 45 | 90 | 45 | 120 | 45 |

Notes on the shape:
- **Vegetative stages** (Veg, Bulk): high `p2_vwc_threshold`, small dryback, lower EC,
  shots fire sooner → less stress, more vegetative growth.
- **Generative stages** (Stretch, Ripen): lower `p2_vwc_threshold` (let it dry further),
  bigger dryback, higher EC, last shot earlier so it dries overnight → more stress.
- **EC** climbs through bulk/ripen, then **Flush** drops to the flush target.
- The engine already exposes per-phase EC targets (`ec_target_veg_p0..p3`,
  `ec_target_gen_p0..p3`); the recipe writes the **per-phase row** for the active mode,
  not a single number — the "Active EC target" above is the headline P2 value; P0/P1/P3
  scale from it (e.g. P0 ≈ target, P1 ≈ target, P3 ≈ target×0.95).
- Per-zone: each zone's override = room profile × that zone's
  `shot_size_multiplier`, and a per-zone trim if a zone reads consistently off (Phase 2).

> ⚠️ **Prerequisite to resolve before driving dryback.** The system currently has *three
> disagreeing* dryback figures (`sensor.crop_steering_dryback_target`=15,
> `number.crop_steering_vegetative_dryback_target`=50, `sensor.dryback_percentage_vwc`=100,
> and `sensor.crop_steering_dryback_percentage`=`unknown`). Before the recipe writes
> dryback, we must confirm **which entity the engine actually reads** and **its units**
> (drop-from-peak vs target-VWC). This is a one-hour code check in
> `master_crop_steering_app.py`; flagged so we don't automate a wrong number.

---

## 4. Architecture — where it lives and how it writes

```
                 once per grow-day, ~5 min after lights-on (after the P3→P0 reset)
                 + immediately on a manual stage / intent change
                                   │
        ┌──────────────────────────▼───────────────────────────┐
        │  Recipe engine (new module in the AppDaemon app)       │
        │  autonomous_setpoints.py                               │
        │   1. resolve stage  (flip_date → week → stage, or      │
        │      manual grow_stage override)                       │
        │   2. resolve steering intent (stage default ± override)│
        │   3. check capability gates (what data is trusted)     │
        │   4. interpolate the day's target setpoint set         │
        │   5. CLAMP to each entity's min/max + safety envelope  │
        │   6. RATE-LIMIT vs current (max step/day per setpoint)  │
        │   7. skip any setpoint under a manual "hold"           │
        │   8. PREVIEW (sensor) ── or ── APPLY (number.set_value)│
        │   9. log every change to the activity feed             │
        └────────────────────────────────────────────────────────┘
```

- **Lives in the engine**, not an HA automation — the engine already owns the setpoints,
  the activity log, the safety checks, and the lights-on/P0 hook. A new
  `autonomous_setpoints.py` module + one `run_daily` callback is the clean fit.
- **Cadence: once per grow-day at lights-on.** Setpoints are stable all day; the recipe
  only re-plans when the grow-day rolls over (or you change stage/intent). It never
  edits a setpoint while a zone is mid-irrigation or while dosing is active.
- **Writes via the normal `number.set_value` service** — the same entities you edit by
  hand — so the dashboard, history, and engine all see the change identically.

---

## 5. Safety & guardrails (non-negotiable)

1. **Clamp to entity bounds.** Every write is clamped to the number entity's own
   `min`/`max`/`step`. A recipe value out of range is impossible to apply.
2. **The safety envelope is never auto-changed.** `maximum_ec`, the source pH/EC gate,
   `*_max_daily_volume`, `blocked_dripper_max_shots_30min` are guardrails — the recipe
   reads them as ceilings and **clamps its EC/volume targets under them**; it never
   widens them.
3. **Rate-limit.** Each setpoint has a max step/day (e.g. EC ±0.3, VWC thresholds ±3,
   dryback ±3). Big stage transitions ramp over several days instead of lurching.
4. **Manual hold wins.** A per-setpoint (or global) "manual hold" — if you edited a
   setpoint in the last N hours, or pinned it, the recipe leaves it alone and says so.
5. **Don't touch mid-cycle.** No writes while `irrigation_in_progress`, while
   `nutrient_dosing_active`, or within the startup grace window.
6. **Fail-safe on missing data.** If the stage can't be resolved or key inputs are
   untrusted, the recipe **holds last-known-good** and raises a watch-level note — it
   never guesses.
7. **Full audit trail.** Every change logs `who(recipe)/what/old→new/why(stage,reason)`
   to `sensor.crop_steering_activity_log` and a dedicated
   `sensor.crop_steering_last_recipe_change`. Essential for a regulated facility.
8. **Master switch, default OFF.** `switch.crop_steering_auto_setpoints` — nothing
   writes until you arm it, and it's independent of the irrigation arm switches.

---

## 6. Human-in-the-loop — review before it acts

Three apply modes via a new `select.crop_steering_recipe_mode`:

| Mode | Behaviour |
|---|---|
| **Off** | Recipe doesn't run. Manual control as today. |
| **Preview** *(start here)* | Recipe computes the day's plan and publishes it to a **preview sensor** — *but writes nothing*. You see exactly what it *would* set vs current, with the reason, on a dashboard "Recipe" card. |
| **Auto-apply** | Recipe applies, with all the guardrails above. |

- **`sensor.crop_steering_setpoint_plan`** — attributes hold the proposed setpoint set,
  the resolved stage/week/intent, the capability gates, and a human-readable diff
  (`p2_vwc_threshold 55 → 50 (Stretch, generative)`).
- A **"Recipe" view** on the dashboards shows: resolved stage + day, the steering intent,
  the proposed-vs-current diff, capability gates (green/grey), and the last applied change.
- You run **Preview for a full grow-day cycle**, sanity-check the numbers against this
  guide, *then* flip to Auto-apply. That's the "check it before we implement" loop, built
  into the runtime too.

---

## 7. Adaptive trim — Phase 2, optional

Once the deterministic recipe is trusted, add **small bounded feedback** so it self-corrects:

- **Dryback achieved vs target:** if a zone's measured overnight dryback is consistently
  >X off target for 3+ days → nudge that zone's dryback ±1–2% toward target.
- **EC trajectory:** if pore-EC drifts above/below the target band for 3+ days → nudge
  feed EC ±0.1–0.2 within bounds.
- **VWC tracking:** if P2 shots never bring VWC back to band → nudge `p2_shot_size` ±0.5.

All trims are **small, slow, tightly bounded, and logged**, and only run in Auto-apply.
This is where it earns the "AI" name without ever being a black box.

---

## 8. New entities required (small, additive)

| Entity | Type | Purpose |
|---|---|---|
| `switch.crop_steering_auto_setpoints` | switch | Master arm for the recipe engine (default off) |
| `select.crop_steering_recipe_mode` | select | Off / Preview / Auto-apply |
| `input_datetime.crop_steering_flip_date` | datetime | Grow anchor (flip/start date) |
| `select.crop_steering_grow_stage` | select | Auto / Propagation / Veg / Stretch / Bulk / Ripen / Flush (manual override) |
| `select.crop_steering_steering_intent` | select | Auto / Force Veg / Force Gen / Hold |
| `sensor.crop_steering_setpoint_plan` | sensor | Preview: proposed setpoints + reasons (attributes) |
| `sensor.crop_steering_grow_day` | sensor | Resolved day/week/stage (read-only) |
| `sensor.crop_steering_last_recipe_change` | sensor | Audit of the last applied change |

These are added the same way the existing entities are (integration `number/switch/select.py`
+ `const.py`), so they show up natively in HA and on every dashboard.

---

## 9. Implementation plan (phased — safe to stop after any phase)

- **Phase 0 — data + preview, zero writes.**
  Add the new entities. Build `autonomous_setpoints.py` with the recipe table and the
  resolve→clamp→diff pipeline, wired to the **preview sensor only**. Add the "Recipe"
  dashboard card. *Nothing changes your setpoints.* You watch the plan track the stages
  for a few days and confirm the numbers.
  *(Also do the one-hour dryback-semantics code check from §3.)*

- **Phase 1 — guarded auto-apply.**
  Enable `Auto-apply` behind the master switch: lights-on cadence, clamp, rate-limit,
  manual-hold, mid-cycle/dosing lockout, full logging. Run it on F2, watch the activity
  feed, keep the safety envelope manual.

- **Phase 2 — adaptive trim.**
  Add the bounded feedback nudges. Optionally bring in climate (VPD) gates.

**Testing at each phase:** in Preview, diff the proposed setpoints against this guide's
table for each stage; in Auto-apply, confirm every change is clamped, rate-limited, and
logged, and that manual edits + holds are respected.

---

## 10. Open questions for you before we build

1. **Grow anchor:** flip-date + auto stage, manual stage select, or both (recommended)?
2. **Stage boundaries / flower length:** the week ranges in §3 assume ~8-week flower —
   what's your actual schedule (and do you run a separate veg recipe)?
3. **Recipe values:** are the starting setpoints in the table in the right ballpark for
   your substrate/cultivar, or do you have an Athena/AROYA register you want me to encode?
4. **Per-zone:** one room recipe with per-zone multipliers, or genuinely independent
   per-zone recipes (e.g. different cultivars per row)?
5. **Dryback semantics:** OK to do the code check first so we drive the right entity?
6. **Scope to start:** Phase 0 (preview only) first, as recommended?
