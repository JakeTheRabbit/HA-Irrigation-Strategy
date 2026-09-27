# Entity Reference: Complete Schema

Every entity the Crop Steering System creates, what it does, its range/options, and
its default. Generated against the live deployed system (3-zone example; per-zone
entities scale with your zone count, `N` = 1…zones).

**Conventions**
- **Global** entities set the system-wide default: `…crop_steering_<param>`.
- **Per-zone** entities override the global for one zone: `…crop_steering_zone_N_<param>`.
  Most phase/EC/dryback setpoints exist in **both** forms: the engine uses the
  per-zone value for that zone and falls back to the global otherwise.
- The engine reads these by `entity_id`. Renaming a friendly-name in HA or on a
  dashboard does not affect it.

---

## 1. Numbers: global setpoints (`number.crop_steering_*`)

### P0: morning dryback
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `p0_dryback_drop_percent` | 2-40 | 15 | % | How far VWC must drop from the overnight peak before P0 ends and P1 begins. |
| `p0_maximum_wait_time` | 30-600 | 120 | min | Hard ceiling: forces P0 → P1 if the dryback target is never reached. |

### P1: ramp-up
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `p1_initial_shot_size` | 0.1-20 | 2 | % | Size of the first ramp shot (% of substrate volume). |
| `p1_shot_size_increment` | 0.05-10 | 0.5 | % | How much each successive shot grows. |
| `p1_minimum_shots` | 1-20 | 3 | - | Minimum shots before P1 may exit. |
| `p1_maximum_shots` | 1-30 | 6 | - | After this many shots P1 exits to P2 even if the target wasn't hit. |
| `p1_target_vwc` | 5-95 | 60 | % | VWC that ends the ramp and moves the zone to P2. |
| `p1_time_between_shots` | 1-60 | 5 | min | Spacing between ramp shots. |

### P2: maintenance
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `p2_vwc_threshold` | 5-85 | 55 | % | Shoot a maintenance top-up when VWC falls below this. |
| `p2_shot_size` | 0.5-30 | 5 | % | Size of a P2 maintenance shot. |
| `p2_ec_high_threshold` | 0.5-3.0 | 1.2 | ×target | EC ratio above which the threshold is raised (water more to flush salts). |
| `p2_ec_low_threshold` | 0.2-2.0 | 0.8 | ×target | EC ratio below which the threshold is lowered. |

### P3: pre-lights-off / overnight
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `p3_emergency_vwc_threshold` | 20-65 | 40 | % | Overnight emergency floor: a rescue shot fires below this. |
| `p3_emergency_shot_size` | 0.1-15 | 2 | % | Size of an emergency rescue shot. |

### EC targets: vegetative & generative (per phase)
| Entity | Range | Default | Unit |
|---|---|---|---|
| `ec_target_veg_p0` / `_p1` / `_p2` / `_p3` | 0.5-15 | 3.0 / 3.0 / 3.2 / 3.0 | mS/cm |
| `ec_target_gen_p0` / `_p1` / `_p2` / `_p3` | 0.5-20 | 4.0 / 5.0 / 6.0 / 4.5 | mS/cm |

The active EC target = the row for the current phase **and** the zone's steering mode.
`sensor.crop_steering_ec_ratio` = current EC ÷ this target.

### EC & safety limits
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `irrigation_ec_min` | 0-20 | 2.3 | mS/cm | Source-water EC gate (low bound). Irrigation blocked below it. `0` disables. |
| `irrigation_ec_max` | 0-20 | 3.5 | mS/cm | Source-water EC gate (high bound). |
| `irrigation_ph_min` | 3.0-9.0 | 5.8 | pH | Source-water pH gate (low bound). |
| `irrigation_ph_max` | 3.0-9.0 | 6.2 | pH | Source-water pH gate (high bound). |
| `maximum_ec` | 1-20 | 9.0 | mS/cm | Hard substrate-EC cutoff: no shot above it (salt-burn guard). |
| `max_shot_duration` | 5-3600 | 900 | s | Longest a single shot may run. The controller refuses to water a room whose cap is missing or below 5 s (CS-203). |
| `watchdog_hours` | 0-12 | 3 | h | Lights-on backstop: a zone below its P2 trigger that has had no water for this long gets a watchdog shot, or an urgent alert (CS-207) when watering is blocked. `0` turns it off. |

### Substrate & schedule
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `substrate_volume` | 1-200 | 6 | L | Substrate volume per plant: converts shot % → mL → valve seconds. |
| `dripper_flow_rate` | 0.1-50 | 4 | L/hr | Per-dripper flow: the other half of the % → seconds conversion. |
| `drippers_per_plant` | 1-6 | 1 | - | Drippers feeding each plant. |
| `field_capacity` | 5-100 | 60 | % | VWC at/above which irrigation is blocked (over-water guard / P1 clamp). |
| `vegetative_dryback_target` | 5-80 | 50 | % | Overnight dryback target in vegetative mode. |
| `generative_dryback_target` | 5-70 | 40 | % | Overnight dryback target in generative mode. |
| `lights_on_hour` | 0-23 | 10 | hour | Photoperiod start: P3→P0 + daily-counter reset fire here. |
| `lights_off_hour` | 0-23 | 22 | hour | Photoperiod end: zones move to P3. |

---

## 2. Numbers: per-zone overrides (`number.crop_steering_zone_N_*`)

Every zone gets its own copy of the setpoints below. The engine uses the zone's value
for that zone. (3 zones × 23 = 69 entities on a 3-zone system.)

**Per-zone copies of the global setpoints:** `p0_dryback_drop_percent`,
`p0_maximum_wait_time`, `p1_initial_shot_size`, `p1_shot_size_increment`,
`p1_minimum_shots`, `p1_maximum_shots`, `p1_target_vwc`, `p1_time_between_shots`,
`p2_vwc_threshold`, `p2_shot_size`, `p3_emergency_vwc_threshold`,
`p3_emergency_shot_size`, `vegetative_dryback_target`, `generative_dryback_target`,
`ec_target_veg_p0` to `_p2`, `ec_target_gen_p0` to `_p2`, `field_capacity`,
`maximum_ec` and `watchdog_hours`. Ranges match the globals above.

**Per-zone only (no global equivalent):**
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `zone_N_plant_count` | 1-50 | - | - | Plants in the zone: scales total water volume. |
| `zone_N_max_daily_volume` | 0-200 | 200 | L | Daily water budget for the zone. Top-ups and EC-correction shots stop at it, and a shot that would cross it gets only what is left; rescues (watchdog, P3 emergency, high-EC flushes) and the P1 ramp are exempt. |
| `zone_N_substrate_volume` / `zone_N_drippers_per_plant` / `zone_N_dripper_flow_rate` | as the globals | from setup | - | Created only when setup sizes the zone itself; otherwise the room-wide value applies. |

---

## 3. Switches

### Global (`switch.crop_steering_*`)
| Entity | What it does |
|---|---|
| `room_active` | Room on/off (default on). Off = nothing is growing: no irrigation of any kind for this room, including emergency shots and the no-probe fallback schedule, no alerts, repair issues cleared. Per room: `switch.crop_steering_<prefix>room_active`. |
| `auto_setpoints` | Auto Setpoints (default off). On = the controller may rewrite this room's per-zone VWC targets from what it has learned, in bounded steps, never while a dated plan owns the room. Off = it still learns and reports, and writes nothing. Per room: `switch.crop_steering_<prefix>auto_setpoints`. |
| `system_enabled` / `auto_irrigation_enabled` | **Retired**, hidden, named "(retired)". `engine_enabled` is the one switch that stops watering. They stay for controllers from 2.24.0 or before, which hold every shot while one reads off and treat a missing one as off. A newer controller switches the room's kill switch off while one of them reads off, and says so (CS-208). |
| `ec_stacking_enabled` | When on, the system builds EC when below target instead of diluting (push EC up intentionally). |
| `engine_enabled` | The room's kill switch ("Watering" in the dashboard's Settings), created off. Off = the controller waters nothing in this room, and a shot already running stops within a few seconds. Created for named rooms and new default rooms; an older default room keeps the helper its setup names. |

### Per-zone (`switch.crop_steering_zone_N_*`)
| Entity | What it does |
|---|---|
| `zone_N_enabled` | Include/exclude the zone from automation. |
| `zone_N_manual_override` | Absolute lockout: **nothing** opens that valve (auto, emergency, manual). For maintenance. |

---

## 4. Selects

### Global (`select.crop_steering_*`)
| Entity | Options | What it does |
|---|---|---|
| `steering_mode` | Vegetative · Generative | System-wide veg/gen bias (picks which EC + dryback targets apply). |
| `growth_stage` | Vegetative · Generative · Transition | Current growth stage: shifts EC targets + dryback aggressiveness. |
| `irrigation_phase` | P0 · P1 · P2 · P3 | A manual phase indicator, read by `current_phase` and `ec_ratio`. The controller keeps each zone's phase itself and does not read it. |
| `recipe_stage` | Veg · Transition · Bulk · Ripen · Custom | Picking a stage applies its setpoints to the zones. |

### Per-zone (`select.crop_steering_zone_N_*`)
| Entity | Options | What it does |
|---|---|---|
| `zone_N_set_phase` | Keep · P0 · P1 · P2 · P3 | Moves the zone to a phase by hand. The controller applies a pick once, within a minute, and sets it back to Keep; its own rules carry on from that phase. Today's water and shot counts stay; P1 ramps from its first shot, and P0 measures its dry-back from the moisture at the move. |
| `zone_N_steering_mode` | Vegetative · Generative | Per-zone veg/gen bias. |

---

## 5. Sensors (read-only)

### System (`sensor.crop_steering_*`)
| Entity | Unit | What it reports |
|---|---|---|
| `activity_log` | - | Rolling human-readable feed (last ~40 watered/blocked/phase events); full feed in the `feed` attribute. |
| `app_current_phase` | - | Published by the controller: each zone's phase (e.g. `Z1:P3, Z2:P3, Z3:P3`). |
| `current_phase` | - | The same, as the integration shows it: `app_current_phase`, else the `irrigation_phase` select. |
| `current_decision` | - | What the controller decided this cycle. |
| `app_status` | - | The controller's state for the room (`active` / `safe_idle` / …). |
| `system_safety_status` | - | `safe` / fault. |
| `ai_heartbeat` | - | Self-correction loop status (`healthy` / anomaly). Attribute `controller_version`: the controller app that is actually running (shown in the dashboard sidebar beside the descriptor's `integration_version`). |
| `engine_config` | - | The room's descriptor: what the controller reads to find and drive the room (valves, pump, main line, kill switch, zones, `setup_revision`). Attribute `integration_version`: the integration Home Assistant actually loaded. Attribute `entry_id`: WHICH room this is. A room that is deleted and set up again keeps its entity ids and starts its revision again at 1, so this is how a running controller tells it from the room it already adopted; it then adopts the new setup through the usual gate (kill switch and hardware OFF). Neither attribute enters the setup fingerprint. |
| `configured_avg_vwc` / `configured_avg_ec` | % / mS/cm | Means across every mapped zone probe. |
| `ec_ratio` | - | Current EC ÷ target EC. |
| `p1_shot_duration_seconds` / `p2_shot_duration_seconds` / `p3_shot_duration_seconds` | s | Computed valve seconds for each shot type. |
| `p2_vwc_threshold_adjusted` | % | P2 threshold after EC-ratio adjustment. |
| `stock_low` | - | How many of the room's stock tanks are at or below their low mark (0 when none). Attribute `tanks`: each tank's `name`, `level_l`, `capacity_l`, `percent`, `low_l`, `dose_ml` (what one batch takes now), `batches_left` and `low`. Attribute `last_batch`: the newest batch counted. The tanks are kept by the integration (Crop Steering → Stock tanks, or the `stock_*` services); a room with a tank last-fill entity mapped loses one batch's dose from every tank at each newer fill time. Automate a phone alert on it going above 0. |

The controller also publishes `sensor.f2_control_vitals`: the time of its last vitals report, with the report in the `vitals` attribute.

### Per-zone (`sensor.crop_steering_zone_N_*`)
| Entity | Unit | What it reports |
|---|---|---|
| `vwc_zone_N` | % | Fused substrate moisture (`zone_N_vwc` on older installs). |
| `ec_zone_N` | mS/cm | Fused pore-water EC (`zone_N_ec` on older installs). |
| `zone_N_phase` | - | The zone's current phase (P0-P3). |
| `zone_N_auto_setpoints` | - | Published by the controller: `off` / `learning` / `tracking` / `frozen`. Attributes: `learned_peak`, `gain`, `day_rate`, `night_rate`, `p1_outcome` (`pending` / `reached` / `short` / `plateau` / `suspect`), `hold_days`, `frozen_reason`, `last_change`, `jev` (`disabled` / `ok` / `unavailable`), `jev_last` (the judge's latest hourly P2 answer), `jev_changed_today`, `working_peak_adjust`, `managed` (the number entities it may rewrite; includes `p2_shot_size` while the judge is configured). |
| `zone_N_status` / `_status_app` | - | The controller's label for the zone, published on `zone_N_status_app` with a `reason` attribute and shown by `zone_N_status`, its only writer: `Drying back` / `Ramping` / `Optimal` / `Overnight dryback` (P0-P3, holding), `Flushing` / `Refilling` / `Topping up` / `Emergency` (watering), `Blocked: <why>`, `Blocked — EC/cap`, `Probe dead — copying`, `Room off`. `Controller not reporting` when the controller has not reported for 10 minutes. |
| `zone_N_safety_status` | - | `safe` / fault. |
| `zone_N_daily_water_usage` / `_daily_water_app` | L | Water today (resets at lights-on). |
| `zone_N_weekly_water_usage` / `_weekly_water_app` | L | Rolling 7-day water. |
| `zone_N_irrigation_count_today` / `_irrigation_count_app` | - | Shot count today. |
| `zone_N_last_irrigation` / `_last_irrigation_app` | - | Last shot timestamp. |
| `zone_N_vmax_detected` | % | Advisory: the highest moisture the zone reached in its P1 wet-up, with a `confidence` attribute. Nothing tunes from it. |
| `prediction_zone_N_next_irrigation_hours` | h | Hours to the next P2 shot, published only when it can be worked out. |

> Note: a few `…_app` sensors are engine-published mirrors of the integration sensors;
> prefer the engine `…_app` value when the two differ.

---

## 6. Hardware (your own switches/sensors: mapped in Rooms & setup, not created here)

The pump, mainline solenoid, per-zone valve switches, and the raw VWC/EC + source-water
sensors are **your** existing HA entities. Map them in the Crop Steering sidebar under
**Rooms & setup**: the controller drives what the room's setup maps, and with nothing mapped
it holds every zone and says so. (The controller also reads a `hardware` map from its options
file, for tests and hand-built development setups only: the app's Configuration tab doesn't
offer it, and Supervisor rejects it as an unknown option.)
