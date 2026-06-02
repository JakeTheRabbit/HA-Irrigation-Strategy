# System Overview — Crop-Steering Irrigation Engine

> **Read this first.** Single source of truth for how the system fits together:
> Home Assistant entities → AppDaemon engine → hardware. If something doesn't
> match this doc, the doc wins until it's updated.

## What this is

An autonomous **4-phase crop-steering irrigation controller** for Home Assistant.

- A **Home Assistant integration** (`custom_components/crop_steering/`) provides the
  entity surface and a config-flow setup wizard.
- An **AppDaemon app** (`appdaemon/apps/crop_steering/master_crop_steering_app.py`)
  reads those entities, runs the per-zone phase logic, and drives the irrigation
  hardware safely.

It is **irrigation only** — VWC/EC-driven shot scheduling across the daily
P0 → P1 → P2 → P3 cycle. It does **not** control climate (temp / RH / CO₂); that is
left to whatever environment automations the site already runs.

**Deployed today on the F2 veg room: 3 zones (rows), a shared pump + mainline, one
valve per row.**

## Architecture

```
┌─ HARDWARE ─────────────────────────────────────────────────────┐
│  Pump · mainline solenoid · one valve per zone                  │
│  Per-zone substrate VWC + pore-water EC sensors                 │
│  Source-water pH + EC sensors (irrigation-quality gate)         │
└────────────────────────────┬───────────────────────────────────┘
                             │  HA switch./sensor. entities
┌────────────────────────────▼───────────────────────────────────┐
│  HOME ASSISTANT INTEGRATION   custom_components/crop_steering/   │
│   · config-flow setup wizard (no YAML editing)                  │
│   · ~100 entities: number./switch./select./sensor.crop_steering_* │
│   · calculations.py — pure, unit-tested shot/threshold helpers  │
│  Provides the entity surface and fires service events.          │
│  Does NOT touch hardware.                                       │
└────────────────────────────┬───────────────────────────────────┘
                             │  reads entity state / listens for events
┌────────────────────────────▼───────────────────────────────────┐
│  APPDAEMON ENGINE   appdaemon/apps/crop_steering/               │
│   master_crop_steering_app.py — the autonomous coordinator      │
│     · per-zone P0 → P1 → P2 → P3 state machines                 │
│     · sensor fusion + dryback detection                         │
│     · source-water pH/EC gate · daily volume/shot caps          │
│     · emergency rescue · drain-through detection                │
│     · _ai_heartbeat self-correction · _watchdog_check safety    │
│     · activity feed → sensor.crop_steering_activity_log         │
│   + libs: phase_state_machine · advanced_dryback_detection ·    │
│     intelligent_sensor_fusion · intelligent_crop_profiles ·     │
│     ml_irrigation_predictor · base_async_app                    │
│  The ONLY layer that drives hardware.                           │
└────────────────────────────┬───────────────────────────────────┘
                             ▼  pump prime → mainline → zone valve → irrigate → shutdown
                        HARDWARE (back to top)
```

## 1. The P0–P3 daily cycle

A "grow-day" is one **photoperiod** (lights-on → lights-on). Each zone walks the
four phases independently:

| Phase | Name | What it does | Exit |
|---|---|---|---|
| **P0** | Morning dryback | After lights-on, wait for the substrate to dry back by a target % from its overnight peak. | dryback target hit, or max wait → P1 |
| **P1** | Ramp-up | Progressive shots to bring VWC up to the per-zone target. | target reached / max shots / wall-clock timeout → P2 |
| **P2** | Maintenance | Threshold-based top-ups — shoot when VWC drops below the per-zone P2 threshold (EC ratio can shift it). | a few hours before lights-off → P3 |
| **P3** | Pre-lights-off / overnight | Emergency-only irrigation; the substrate is allowed to dry back through the dark period. | **lights-on → P0** |

The **daily water + shot counters reset at the P3→P0 transition (lights-on)** — the
real grow-day boundary — not at calendar midnight (which would split one
photoperiod's data across two dates).

> **Dryback semantics:** every "dryback" value is a *percentage-point drop from peak
> VWC* — how much it dries back **by**, not the VWC it dries back **to**.

### EC stacking (autonomous, P2)

When `switch.crop_steering_ec_stacking_enabled` is on, the engine closes a loop on
**substrate EC** during P2 (`_ec_stack_dryback`): it nudges each zone's
`p2_vwc_threshold` to drive smoothed pore-EC toward that zone's phase target
(`…_ec_target_{veg|gen}_p2`). Deeper dryback concentrates salts (EC rises); a pore-EC
*drop* is read as runoff and deepens the dryback further. EWMA-smoothed, 30-min cooldown,
bounded by the P3 emergency floor and the `min(p1_target, adaptive-cap)` ceiling. This is
the generative salt lever, run hands-off — the F2 heartbeat oversees it, doesn't drive it.

## 2. Hardware control sequence

```
Safety checks → Pump prime (2 s) → Mainline open (1 s) → Zone valve open → Irrigate → Shutdown (reverse order)
```

Every shot is read-back verified — if a valve fails to close, the engine
emergency-stops the pump. Shot *duration* is derived from the requested shot
*size* (% of substrate volume) and the per-zone dripper flow rate.

## 3. Safety layers (all in the engine)

- **`_ai_heartbeat`** — periodic self-correction: force-advances a phase stuck > 4 h,
  flags stale sensors, and flags a zone that takes water without VWC rising
  (drain-through / channelling).
- **`_watchdog_check`** — hardware watchdog: catches a valve/pump stuck on or a
  runaway shot and emergency-stops.
- **Source-water gate** — irrigation is blocked while source pH/EC are outside the
  operator-set bounds (won't feed bad water).
- **Daily caps** — per-zone max daily **volume** and **shot count**; emergency
  rescue is exempt so a wilting zone is never denied water by a budget.
- **Emergency rescue + abandonment** — a zone below its emergency VWC floor gets
  rescue shots; if repeated shots don't raise VWC it backs off and alerts
  (blocked dripper / draining row).

## 4. Entity conventions

| Pattern | Example | Meaning |
|---|---|---|
| `number.crop_steering_<param>` | `number.crop_steering_p2_shot_size` | Global setpoint |
| `number.crop_steering_zone_X_<param>` | `number.crop_steering_zone_2_p1_target_vwc` | Per-zone setpoint |
| `switch.crop_steering_zone_X_<param>` | `switch.crop_steering_zone_1_enabled` | Per-zone control |
| `select.crop_steering_zone_X_<param>` | `select.crop_steering_zone_3_steering_mode` | Per-zone mode |
| `sensor.crop_steering_<metric>` | `sensor.crop_steering_zone_1_vwc` | Derived/diagnostic sensor |
| `input_select.crop_steering_zone_X_phase_control` | — | Per-zone manual phase pin (Auto / P0–P3) |

The engine reads switches/numbers by `entity_id`; renaming the *friendly name* in HA
or the dashboard does not affect it.

## 5. F2 deployment specifics

| Role | Entity |
|---|---|
| Pump | `switch.veg_main_pump` |
| Mainline solenoid | `switch.espoe_irrigation_relay_2_3` ("Veg Mainline") |
| Zone valves | `switch.f2_row1` · `switch.f2_row2` · `switch.f2_row3` |
| Zone VWC (fused) | `sensor.crop_steering_zone_1..3_vwc` |
| Zone EC | `sensor.crop_steering_zone_1..3_ec` |
| Source-water pH / EC | `sensor.aquaponics_kit_f4f618_ph` · `sensor.atlas_legacy_1_ec` |

Hardware wiring + the F2 sensor map live in `appdaemon/apps/apps.yaml`.

## 6. Dashboards

The live F2 dashboard is a 6-tab Lovelace layout (Overview / Trends / Zones /
Controls / Setpoints / Diagnostics) built from the `crop_steering_*` entities. The
**Activity** card reads `sensor.crop_steering_activity_log`, a rolling
human-readable feed the engine publishes on every watered / blocked / phase event.

## 7. Reference docs in this repo

| Doc | Read when… |
|---|---|
| `README.md` | First look at the repo |
| `CLAUDE.md` | Working on the code |
| `ENTITIES.md` | Looking up what an entity does |
| `docs/installation_guide.md` | Fresh install |
| `docs/operation_guide.md` | Daily operator routine |
| `docs/troubleshooting.md` | Something's wrong |
| `docs/SYSTEM_OVERVIEW.md` | **(this doc)** the whole-stack mental model |

> **Note on the integration entity surface.** The HA integration still defines a
> handful of entities from an earlier experimental "intelligence" layer (a
> steering-intent slider and `…_intelligence_*_enabled` switches). That pillar code
> is **not** part of the deployed engine — it lived in `intelligence/` and was
> retired from `main` (recoverable from the `archive/pre-doc-cleanup-2026-06` tag).
> Those entities are inert; the engine ignores them.
