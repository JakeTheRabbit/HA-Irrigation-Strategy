# Entity Reference — Complete Schema

Every entity the Crop Steering System creates, what it does, its range/options, and
its default. Generated against the live deployed system (3-zone example; per-zone
entities scale with your zone count, `N` = 1…zones).

**Conventions**
- **Global** entities set the system-wide default: `…crop_steering_<param>`.
- **Per-zone** entities override the global for one zone: `…crop_steering_zone_N_<param>`.
  Most phase/EC/dryback setpoints exist in **both** forms — the engine uses the
  per-zone value for that zone and falls back to the global otherwise.
- The engine reads these by `entity_id`. Renaming a friendly-name in HA or on a
  dashboard does not affect it.

---

## 1. Numbers — global setpoints (`number.crop_steering_*`)

### P0 — morning dryback
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `p0_dryback_drop_percent` | 2–40 | 15 | % | How far VWC must drop from the overnight peak before P0 ends and P1 begins. |
| `p0_minimum_wait_time` | 5–300 | 30 | min | Earliest P0 may exit, even if the dryback target is already met. |
| `p0_maximum_wait_time` | 30–600 | 120 | min | Hard ceiling — forces P0 → P1 if the dryback target is never reached. |

### P1 — ramp-up
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `p1_initial_shot_size` | 0.1–20 | 2 | % | Size of the first ramp shot (% of substrate volume). |
| `p1_shot_size_increment` | 0.05–10 | 0.5 | % | How much each successive shot grows. |
| `p1_maximum_shot_size` | 2–50 | 10 | % | Cap on the ramp shot size. |
| `p1_minimum_shots` | 1–20 | 3 | — | Minimum shots before P1 may exit. |
| `p1_maximum_shots` | 1–30 | 6 | — | After this many shots P1 exits to P2 even if the target wasn't hit. |
| `p1_target_vwc` | 5–95 | 60 | % | VWC that ends the ramp and moves the zone to P2. |
| `p1_time_between_shots` | 1–60 | 5 | min | Spacing between ramp shots. |

### P2 — maintenance
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `p2_vwc_threshold` | 5–85 | 55 | % | Shoot a maintenance top-up when VWC falls below this. |
| `p2_shot_size` | 0.5–30 | 5 | % | Size of a P2 maintenance shot. |
| `p2_ec_high_threshold` | 0.5–3.0 | 1.2 | ×target | EC ratio above which the threshold is raised (water more to flush salts). |
| `p2_ec_low_threshold` | 0.2–2.0 | 0.8 | ×target | EC ratio below which the threshold is lowered. |

### P3 — pre-lights-off / overnight
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `p3_emergency_vwc_threshold` | 20–65 | 40 | % | Overnight emergency floor — a rescue shot fires below this. |
| `p3_emergency_shot_size` | 0.1–15 | 2 | % | Size of an emergency rescue shot. |
| `p3_veg_last_irrigation` | 15–360 | 120 | min | Minutes before lights-off after which veg zones take no planned shots. |
| `p3_gen_last_irrigation` | 30–600 | 180 | min | Same, for generative zones. |

### EC targets — vegetative & generative (per phase)
| Entity | Range | Default | Unit |
|---|---|---|---|
| `ec_target_veg_p0` / `_p1` / `_p2` / `_p3` | 0.5–15 | 3.0 / 3.0 / 3.2 / 3.0 | mS/cm |
| `ec_target_gen_p0` / `_p1` / `_p2` / `_p3` | 0.5–20 | 4.0 / 5.0 / 6.0 / 4.5 | mS/cm |
| `ec_target_flush` | 0.1–15 | 0.8 | mS/cm |

The active EC target = the row for the current phase **and** the zone's steering mode.
`sensor.crop_steering_ec_ratio` = current EC ÷ this target.

### EC & safety limits
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `irrigation_ec_min` | 0–20 | 2.3 | mS/cm | Source-water EC gate (low bound). Irrigation blocked below it. `0` disables. |
| `irrigation_ec_max` | 0–20 | 3.5 | mS/cm | Source-water EC gate (high bound). |
| `irrigation_ph_min` | 3.0–9.0 | 5.8 | pH | Source-water pH gate (low bound). |
| `irrigation_ph_max` | 3.0–9.0 | 6.2 | pH | Source-water pH gate (high bound). |
| `maximum_ec` | 1–20 | 9.0 | mS/cm | Hard substrate-EC cutoff — no shot above it (salt-burn guard). |
| `blocked_dripper_max_shots_30min` | 1–20 | 4 | — | Emergency shots in 30 min before a zone is flagged/backed-off as a blocked/draining dripper. |

### Substrate & schedule
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `substrate_volume` | 1–200 | 6 | L | Substrate volume per plant — converts shot % → mL → valve seconds. |
| `dripper_flow_rate` | 0.1–50 | 4 | L/hr | Per-dripper flow — the other half of the % → seconds conversion. |
| `drippers_per_plant` | 1–6 | 1 | — | Drippers feeding each plant. |
| `field_capacity` | 5–100 | 60 | % | VWC at/above which irrigation is blocked (over-water guard / P1 clamp). |
| `vegetative_dryback_target` | 5–80 | 50 | % | Overnight dryback target in vegetative mode. |
| `generative_dryback_target` | 5–70 | 40 | % | Overnight dryback target in generative mode. |
| `lights_on_hour` | 0–23 | 10 | hour | Photoperiod start — P3→P0 + daily-counter reset fire here. |
| `lights_off_hour` | 0–23 | 22 | hour | Photoperiod end — zones move to P3. |

---

## 2. Numbers — per-zone overrides (`number.crop_steering_zone_N_*`)

Every zone gets its own copy of the setpoints below. The engine uses the zone's value
for that zone. (3 zones × 32 = 96 entities on a 3-zone system.)

**Per-zone copies of the global setpoints:** `p0_dryback_drop_percent`,
`p0_minimum_wait_time`, `p0_maximum_wait_time`, `p1_initial_shot_size`,
`p1_shot_size_increment`, `p1_maximum_shot_size`, `p1_minimum_shots`,
`p1_maximum_shots`, `p1_target_vwc`, `p1_time_between_shots`, `p2_vwc_threshold`,
`p2_shot_size`, `p2_ec_high_threshold`, `p2_ec_low_threshold`,
`p3_emergency_vwc_threshold`, `p3_emergency_shot_size`, `p3_veg_last_irrigation`,
`p3_gen_last_irrigation`, `vegetative_dryback_target`, `generative_dryback_target`,
and all eight `ec_target_veg_pX` / `ec_target_gen_pX` plus `ec_target_flush`. Ranges
match the globals above.

**Per-zone only (no global equivalent):**
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `zone_N_plant_count` | 1–50 | — | — | Plants in the zone — scales total water volume. |
| `zone_N_max_daily_volume` | 0–200 | 200 | L | Hard daily water cap for the zone (emergency rescue is exempt). |
| `zone_N_shot_size_multiplier` | 0.1–5 | 1.0 | × | Scales every shot for this zone (a weak/strong row trim). |

---

## 3. Switches

### Global (`switch.crop_steering_*`)
| Entity | What it does |
|---|---|
| `system_enabled` | Master on/off. Off = no irrigation at all. |
| `auto_irrigation_enabled` | Enables the autonomous decision loop (off = manual-only). |
| `ec_stacking_enabled` | When on, the system builds EC when below target instead of diluting (push EC up intentionally). |
| `analytics_enabled` | Enables the analytics/efficiency sensors + history tracking. |

### Per-zone (`switch.crop_steering_zone_N_*`)
| Entity | What it does |
|---|---|
| `zone_N_enabled` | Include/exclude the zone from automation. |
| `zone_N_manual_override` | Absolute lockout — **nothing** opens that valve (auto, emergency, manual). For maintenance. |
| `zone_N_dripper_protection` | When on, the zone is allowed to abandon/back-off after repeated unresponsive emergency shots (blocked-dripper protection). |

---

## 4. Selects

### Global (`select.crop_steering_*`)
| Entity | Options | What it does |
|---|---|---|
| `steering_mode` | Vegetative · Generative | System-wide veg/gen bias (picks which EC + dryback targets apply). |
| `growth_stage` | Vegetative · Generative · Transition | Current growth stage — shifts EC targets + dryback aggressiveness. |
| `crop_type` | Cannabis_Athena · _Hybrid · _Indica · _Sativa | Crop profile preset. |
| `irrigation_phase` | P0 · P1 · P2 · P3 · Manual | System phase indicator / manual phase set. |

### Per-zone (`select.crop_steering_zone_N_*`)
| Entity | Options | What it does |
|---|---|---|
| `zone_N_steering_mode` | Vegetative · Generative | Per-zone veg/gen bias. |
| `zone_N_crop_profile` | Follow Main · Cannabis_Athena · _Indica_Dominant · … · Custom | Per-zone crop preset (Follow Main = use system default). |
| `zone_N_priority` | Critical · High · Normal · Low | Ordering when multiple zones want water at once. |
| `zone_N_group` | Ungrouped · Group A–D | Logical grouping for multi-zone coordination. |

---

## 5. Phase control (`input_select.crop_steering_*`)

| Entity | Options | What it does |
|---|---|---|
| `zone_N_phase_control` | Auto · P0 · P1 · P2 · P3 | Per-zone manual phase pin. **Auto** = engine controls the phase; any other value pins the zone there until set back to Auto. |

---

## 6. Sensors (read-only)

### System (`sensor.crop_steering_*`)
| Entity | Unit | What it reports |
|---|---|---|
| `activity_log` | — | Rolling human-readable feed (last ~40 watered/blocked/phase events); full feed in the `feed` attribute. |
| `current_phase` / `app_current_phase` | — | Combined per-zone phase string (e.g. `Z1:P3, Z2:P3, Z3:P3`). |
| `current_decision` | — | What the engine decided this cycle (`irrigate` / `wait` / …). |
| `app_next_irrigation` / `next_irrigation_time` | — | Predicted next shot time. |
| `system_state` / `app_status` | — | `active` / `safe_idle` / … |
| `system_safety_status` | — | `safe` / fault. |
| `system_health_score` | — | 0–100 composite health. |
| `system_uptime` | — | Engine uptime. |
| `ai_heartbeat` | — | Self-correction loop status (`healthy` / anomaly). |
| `system_efficiency` / `water_efficiency` | — | Efficiency metrics. |
| `average_vwc_all_zones` / `average_ec_all_zones` | % / mS/cm | Cross-zone means. |
| `fused_vwc` / `fused_ec` | — | Sensor-fused VWC/EC. |
| `sensor_health` / `sensor_fusion_confidence` | % / — | Sensor-fusion quality. |
| `ec_ratio` | — | Current EC ÷ target EC. |
| `ec_baseline` | mS/cm | Reference EC baseline. |
| `dryback_percentage` / `dryback_target` | % | Current dryback + active target. |
| `dryback_detection_accuracy` | — | Dryback-detector confidence. |
| `ml_model_accuracy` | — | Predictor confidence. |
| `p1_shot_duration` / `p2_shot_duration` / `p3_emergency_shot_duration` | s | Computed valve seconds for each shot type. |
| `p2_vwc_threshold_adjusted` | % | P2 threshold after EC-ratio adjustment. |
| `vwc_target_min` / `vwc_target_max` | % | Active VWC band. |
| `daily_water_usage` / `daily_water_usage_app` | L | Total water today. |
| `prediction_estimated_daily_water_need` | L | Predicted daily demand. |
| `irrigation_efficiency` | % | Water-to-uptake efficiency. |

### Per-zone (`sensor.crop_steering_zone_N_*`)
| Entity | Unit | What it reports |
|---|---|---|
| `zone_N_vwc` | % | Fused substrate moisture. |
| `zone_N_ec` | mS/cm | Fused pore-water EC. |
| `zone_N_phase` | — | The zone's current phase (P0–P3). |
| `zone_N_status` | — | `Optimal` / `Dry - Needs Water` / `Saturated` / `Disabled` / `Sensor Error`. |
| `zone_N_safety_status` | — | `safe` / fault. |
| `zone_N_health_score` / `zone_N_efficiency` | — | Per-zone health/efficiency. |
| `zone_N_daily_water_usage` / `_daily_water_app` | L | Water today (resets at lights-on). |
| `zone_N_weekly_water_usage` / `_weekly_water_app` | L | Rolling 7-day water. |
| `zone_N_irrigations_today` / `_irrigation_count_app` | — | Shot count today. |
| `zone_N_last_irrigation` / `_last_irrigation_app` | — | Last shot timestamp. |
| `prediction_zone_N_next_irrigation_hours` | h | Predicted hours to next shot. |

> Note: a few `…_app` sensors are engine-published mirrors of the integration sensors;
> prefer the engine `…_app` value when the two differ.

---

## 7. Hardware (your own switches/sensors — mapped via the add-on `hardware` option, not created here)

The pump, mainline solenoid, per-zone valve switches, and the raw VWC/EC + source-water
sensors are **your** existing HA entities. You map them to the engine via the f2-control
add-on's `hardware` Configuration option (`pump` / `mainline` / per-zone `valves`), which
defaults to the F2 entities (`switch.veg_main_pump`, `switch.espoe_irrigation_relay_2_3`,
`switch.f2_row1`–`f2_row3`); the engine drives those switches and reads the sensors.

> **Inert legacy entities:** the integration may still create a steering-intent slider
> and a few `…_intelligence_*_enabled` switches from a retired experimental layer. The
> deployed engine ignores them.
