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
- **Defaults** are the entity-default column of one table,
  `crop-steering-engine/src/crop_steering_engine/defaults.py`: what a new entity starts at and
  what setup offers a new room. A restored or operator-set value always wins over it. The
  table's other column is what the controller uses when neither the zone's nor the room's
  setting can be read (around a Home Assistant restart, or a setting an older integration
  lacks); for some settings it differs from the entity default, and it is kept at the values
  installed controllers already use.
- **Sizing** (substrate litres, plant count, drippers per plant, dripper flow) starts at generic
  values, not any one room's. Setup shows them pre-filled for you to check, and the room's
  setup reports each one still at its generic value (`sizing_generic`) until it is changed.

---

## 1. Numbers: global setpoints (`number.crop_steering_*`)

### P0: morning dryback
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `p0_dryback_drop_percent` | 2-40 | 15 | % | Kept for older rooms and recipes; the controller does not read it. P0's own dryback is the per-zone `zone_N_p0_additional_dryback` (section 2). |
| `p0_maximum_wait_time` | 30-600 | 120 | min | Hard ceiling: forces P0 → P1 if the dryback target is never reached. |

### P1: ramp-up
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `p1_initial_shot_size` | 0.1-20 | 2 | % | Size of the first ramp shot (% of substrate volume). |
| `p1_shot_size_increment` | 0.05-10 | 0.5 | % | How much each successive shot grows. |
| `p1_minimum_shots` | 1-20 | 3 | - | Minimum shots before P1 may exit. |
| `p1_maximum_shots` | 1-30 | 6 | - | After this many shots P1 exits to P2 even if the target wasn't hit. |
| `p1_rise_pts` | 0.1-5 | 0.5 | % | Once P1 reads its target it gives one more shot, and another while each raises the settled moisture reading (the median of the last 10 minutes) by at least this much, or by 0.3 of what the zone's learned gain says the shot should give if that is more. |
| `p1_maximum_extra_shots` | 1-10 | 3 | - | The most extra shots P1 gives after reading its target; at this many it moves to P2. Extra shots count toward the daily water limit, and none is given while the table is not draining (CS-310). |
| `p1_target_vwc` | 20-100 | 65 | % | VWC that ends the ramp and moves the zone to P2. |
| `p1_time_between_shots` | 1-60 | 15 | min | Spacing between ramp shots. |

### P2: maintenance
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `p2_vwc_threshold` | 10-100 | 60 | % | Shoot a maintenance top-up when VWC falls below this. |
| `p2_shot_size` | 0.5-30 | 5 | % | Size of a P2 maintenance shot. |
| `p2_time_between_shots` | 0-60 | 0 | min | Minutes from the last shot before a maintenance top-up may go, so it reaches the probe before moisture is judged again. EC corrections keep their own spacing. `0` turns the gap off. |
| `ec_min_interval` | 1-120 | 10 | min | Minutes from the last shot before an EC correction (a flush or a dilute) or the minimum-daily floor may go, so each shot drains and is read again before the next. A correction judged on a settled reading still waits at least 45. |
| `p2_ec_high_threshold` | 0.5-3.0 | 1.2 | ×target | EC ratio above which the threshold is raised (water more to flush salts). |
| `p2_ec_low_threshold` | 0.2-2.0 | 0.8 | ×target | EC ratio below which the threshold is lowered. |

### P3: pre-lights-off / overnight
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `p3_emergency_vwc_threshold` | 10-65 | 40 | % | Overnight emergency floor: a rescue shot fires below this. |
| `p3_emergency_shot_size` | 0.1-15 | 2 | % | Size of an emergency rescue shot. |
| `p3_time_between_shots` | 0-60 | 10 | min | Minutes from the last shot before an emergency rescue may go, so it reaches the probe before moisture is judged again. The first rescue of a night still goes at once. `0` turns the gap off. |

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
| `irrigation_ec_min` | 0-20 | 0 | mS/cm | Source-water EC gate (low bound). Irrigation blocked below it. `0` disables. |
| `irrigation_ec_max` | 0-20 | 0 | mS/cm | Source-water EC gate (high bound). |
| `irrigation_ph_min` | 3.0-9.0 | 5.5 | pH | Source-water pH gate (low bound), used only when a feed pH probe is mapped. A room set up before 5.5-6.5 became the default keeps its own band. |
| `irrigation_ph_max` | 3.0-9.0 | 6.5 | pH | Source-water pH gate (high bound). |
| `maximum_ec` | 1-20 | 9.0 | mS/cm | Hard substrate-EC cutoff: no shot above it (salt-burn guard). |
| `max_shot_duration` | 5 to the room's limit | 900 | s | Longest a single shot may run. The limit follows the zones' size: the time the slowest zone's drippers take to deliver its whole substrate, never under 900 s. The controller refuses to water a room whose cap is missing or below 5 s (CS-203). |
| `sump_power_threshold_w` | 1-10000 | 20 | W | The sump pump counts as running while its power plug (the controller app's `sump_power_sensor` option) reads above this, after the reading is put into watts. No run for `sump_silent_hours` raises CS-311. |
| `pump_prime_time` | 0-20 | 2 | s | How long the pump runs before the main line (or, with no main line, the zone valve) opens. Raise it for a pump that takes longer to reach pressure. |
| `main_line_lead_time` | 0-10 | 1 | s | How long the main-line valve is open before the zone valve opens. |
| `watchdog_hours` | 0-12 | 3 | h | Lights-on backstop: a zone below its P2 trigger that has had no water for this long gets a watchdog shot, or an urgent alert (CS-207) when watering is blocked. `0` turns it off. |

### Substrate & schedule
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `substrate_volume` | 1-200 | 10 | L | Substrate volume per plant: converts shot % → mL → valve seconds. |
| `dripper_flow_rate` | 0.1-50 | 1.2 | L/hr | Per-dripper flow: the other half of the % → seconds conversion. |
| `drippers_per_plant` | 1-6 | 2 | - | Drippers feeding each plant. |
| `field_capacity` | 40-100 | 70 | % | VWC at/above which irrigation is blocked (over-water guard / P1 clamp). |
| `vegetative_dryback_target` | 5-80 | 35 | % | Overnight dryback target in vegetative mode. |
| `generative_dryback_target` | 5-70 | 45 | % | Overnight dryback target in generative mode. |
| `lights_on_hour` | 0-23 | 12 | hour | Photoperiod start: P3→P0 + daily-counter reset fire here. |
| `lights_off_hour` | 0-23 | 0 | hour | Photoperiod end: zones move to P3. |

---

## 2. Numbers: per-zone overrides (`number.crop_steering_zone_N_*`)

Every zone gets its own copy of the setpoints below. The engine uses the zone's value
for that zone. (3 zones × 27 = 81 entities on a 3-zone system.)

**Per-zone copies of the global setpoints:** `p0_dryback_drop_percent`,
`p0_maximum_wait_time`, `p1_initial_shot_size`, `p1_shot_size_increment`,
`p1_minimum_shots`, `p1_maximum_shots`, `p1_rise_pts`, `p1_maximum_extra_shots`, `p1_target_vwc`,
`p1_time_between_shots`,
`p2_vwc_threshold`, `p2_shot_size`, `p2_time_between_shots`, `ec_min_interval`, `p3_emergency_vwc_threshold`,
`p3_emergency_shot_size`, `p3_time_between_shots`, `vegetative_dryback_target`, `generative_dryback_target`,
`ec_target_veg_p0` to `_p2`, `ec_target_gen_p0` to `_p2`, `field_capacity`,
`maximum_ec` and `watchdog_hours`. Ranges match the globals above.

**Per-zone only (no global equivalent):**
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `zone_N_plant_count` | 1-50 | 4 | - | Plants in the zone: scales total water volume. |
| `zone_N_p0_additional_dryback` | 0-40 | 3 on a room set up from this release, 0 on a room updated in place | % | P0 ends once moisture is this far below the highest reading since lights-on, the small extra dryback before the first shot. `0` is off: P0 waits for the dryback target, as before. Its other exits (the maximum wait, the maintenance trigger) are unchanged. |
| `zone_N_max_daily_volume` | 0 to the zone's limit | 20 | L | Daily water budget for the zone. The limit is 4 times the zone's substrate (plants x litres per plant), never under 20 L; a value already above it is kept and listed in Repairs (CS-611). Top-ups and EC-correction shots stop at it, and a shot that would cross it gets only what is left; rescues (watchdog, P3 emergency, high-EC flushes) and the P1 ramp are exempt. |
| `zone_N_min_daily_ml_per_plant` | 0-10000 | 0 (off) | mL | Minimum daily water per plant. From lights-on (never in P0), paced to finish 3 h before lights-off, the zone is watered up to this times its plant count whatever the probe reads, so a probe that reads wet cannot starve the plants (and a correct probe is watered anyway). Stops once moisture is 5 points above the zone's field capacity, and never past the daily limit. A new entity takes the value of the old `input_number` helper of the same name. |
| `zone_N_substrate_volume` / `zone_N_drippers_per_plant` / `zone_N_dripper_flow_rate` | as the globals | from setup | - | Created only when setup sizes the zone itself; otherwise the room-wide value applies. |

---

## 3. Switches

### Global (`switch.crop_steering_*`)
| Entity | What it does |
|---|---|
| `room_active` | Room on/off (default on). Off = nothing is growing: no irrigation of any kind for this room, including emergency shots and the no-probe fallback schedule, no alerts, repair issues cleared. Per room: `switch.crop_steering_<prefix>room_active`. |
| `auto_setpoints` | Auto Setpoints (default off). On = the controller may rewrite this room's per-zone VWC targets from what it has learned, (the P1 target is the zone's highest reading of the grow-day before; field capacity the higher of today's and the day before's highest readings, and when it moves the re-water threshold moves by the same points; each at most 1 point a grow-day, and the rescue floor never moves), never while a dated plan owns the room. With Jev's Setpoints judge running, the judge moves each zone's P2 shot size and re-water threshold and the learner keeps the P1 target and field capacity: one writer per number ([JEV.md](JEV.md#who-writes-which-setpoint)). Off = it still learns and reports, and writes nothing. Per room: `switch.crop_steering_<prefix>auto_setpoints`. |
| `notify_predictions` | Include Predictions in Notifications (default on, an upgraded room included). On = the controller's vitals report says, under each zone, what it will do next (the dashboard's Next: line). Off = just the readings. Per room: `switch.crop_steering_<prefix>notify_predictions`; Settings › Notifications on the dashboard. A controller reading an integration without it includes them. |
| `system_enabled` / `auto_irrigation_enabled` | **Retired**, hidden, named "(retired)". `engine_enabled` is the one switch that stops watering. They stay for controllers from 2.24.0 or before, which hold every shot while one reads off and treat a missing one as off. A newer controller switches the room's kill switch off while one of them reads off, and says so (CS-208). |
| `max_run_latch` | Max-Run Latch: on in a room set up since it was added, off in a room set up before it. On = a zone whose last 3 shots in a row were all cut to the room's maximum shot length gets no more shots until its Repairs card (CS-312) is fixed; the fix adds one to this switch's `resets` attribute, which the controller watches. Off = the same card only reports, and nothing stops. Per room: `switch.crop_steering_<prefix>max_run_latch`. |
| `ec_stacking_enabled` | When on, the system builds EC when below target instead of diluting (push EC up intentionally). |
| `engine_enabled` | The room's kill switch ("Watering" in the dashboard's Settings), created off. Off = the controller waters nothing in this room, and a shot already running stops within a few seconds. Created for named rooms and new default rooms; an older default room keeps the helper its setup names. |

### Per-zone (`switch.crop_steering_zone_N_*`)
| Entity | What it does |
|---|---|
| `zone_N_enabled` | The zone's own switch ("zone scheduling" on the dashboard). Off = the controller waters nothing in this zone, not even a rescue shot, and a shot already running in it stops within a few seconds. |
| `zone_N_manual_override` | Absolute lockout: **nothing** opens that valve (auto, emergency, manual). For maintenance. |
| `zone_N_p3_dryback_hold` | Off by default. On = overnight (P3), each time the zone dries to the day's peak less its dryback target it gets a shot the size of its emergency shot, `p3_time_between_shots` apart, instead of drying on to the emergency level. It steers: a held plan stops it and the daily water limit holds it; the emergency shot still runs beneath it. |

---

## 4. Selects

### Global (`select.crop_steering_*`)
| Entity | Options | What it does |
|---|---|---|
| `steering_mode` | Vegetative · Generative | System-wide veg/gen bias (picks which EC + dryback targets apply). |
| `growth_stage` | Vegetative · Generative · Transition | Current growth stage: shifts EC targets + dryback aggressiveness. |
| `irrigation_phase` | P0 · P1 · P2 · P3 | A manual phase indicator, read by `current_phase` and `ec_ratio`. The controller keeps each zone's phase itself and does not read it. |
| `recipe_stage` | Veg · Transition · Bulk · Ripen · Custom | Picking a stage applies its setpoints to the zones. |
| `drainage` | unknown · flood_table · free_drain | How the room's runoff leaves it, asked on the first page of setup. A table that is not draining (CS-310) is watched for in every room except a free-draining one, so a `free_drain` room never has its daily minimum or EC flushes held for it. A room set up before this reads `unknown`, watched as before. |
| `water_today_view` | Zone total · Per plant | How Water today reads for the room: each zone's total, or its water and daily limit divided by its plant count. The dashboard shows it that way for everyone (Settings → Appearance), and the controller's vitals notification follows it. Zone total by default. |
| `substrate` | generic · rockwool · coco | What the room grows in. Published in the room's `engine_config` descriptor and read by the controller, which takes a change with no disarm cycle. `generic` by default, and on every upgraded room, and runs exactly as before. `rockwool` and `coco` choose the substrate profile in the engine's defaults table: the controller's EC settle time, P1 rise, P0 flush, shot scaling by EC and Auto setpoints bounds, and the starting VWC bands and dryback targets of any setting that has no value yet (a value the room already holds never moves). |

### Per-zone (`select.crop_steering_zone_N_*`)
| Entity | Options | What it does |
|---|---|---|
| `zone_N_set_phase` | Keep · P0 · P1 · P2 · P3 | Moves the zone to a phase by hand. The controller applies a pick once, within a minute, and sets it back to Keep; its own rules carry on from that phase. Today's water and shot counts stay; P1 ramps from its first shot, and P0 measures its dry-back from the moisture at the move. |
| `zone_N_steering_mode` | Vegetative · Generative | Per-zone veg/gen bias. |
| `zone_N_vwc_method`, `zone_N_ec_method` | Median · Average · Lowest · Highest | How the zone's probes become its moisture reading, and apart its EC reading. Median by default. A probe far from the others is left out first; Lowest and Highest need three probes that agree, and with fewer the zone steers on the median and the controller raises CS-502. |
| `ec_type_<probe>` (one per mapped EC probe, named after the probe's entity id) | unknown · pore · bulk | What the probe measures: pore EC (the water in the substrate's pores) or bulk EC (substrate and water together, which reads lower). unknown by default, which fuses as before. A zone with both a pore and a bulk probe never combines the two: it steers on its pore probes, and on its bulk probes only while no pore probe reports, when the controller raises CS-504. |

### Per-zone buttons (`button.crop_steering_zone_N_*`)
| Entity | What it does |
|---|---|
| `zone_N_test_shot` | Asks the controller for a 10-second test shot in the zone, to check that watering works. It acts at its next pass (within a minute) on a press under 10 minutes old, through every check a shot passes except a held grow plan. Its water counts toward the day's; it is not one of the day's shots. The `crop_steering.test_shot` service presses it by room id. |

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
| `ai_heartbeat` | - | Self-correction loop status (`healthy` / anomaly), or `stopped` once the controller app has been stopped, updated or restarted (attribute `stopped_at`). Attribute `controller_version`: the controller app that is actually running (shown in the dashboard sidebar beside the descriptor's `integration_version`). |
| `engine_config` | - | The room's descriptor: what the controller reads to find and drive the room (valves, pump, main line, kill switch, zones, `setup_revision`). Attribute `integration_version`: the integration Home Assistant actually loaded. Attribute `entry_id`: WHICH room this is. A room that is deleted and set up again keeps its entity ids and starts its revision again at 1, so this is how a running controller tells it from the room it already adopted; it then adopts the new setup through the usual gate (kill switch and hardware OFF). Neither attribute enters the setup fingerprint. |
| `configured_avg_vwc` / `configured_avg_ec` | % / mS/cm | Means across every mapped zone probe. |
| `ec_ratio` | - | Current EC ÷ target EC. |
| `p1_shot_duration_seconds` / `p2_shot_duration_seconds` / `p3_shot_duration_seconds` | s | Seconds the controller runs each shot type for: each zone's pot size, drippers per plant and dripper flow, in whole seconds, at least 5 and within the room's maximum shot length. Shows the longest zone; the `zones` attribute has each zone's. |
| `p2_vwc_threshold_adjusted` | % | P2 threshold after EC-ratio adjustment. |
| `stock_low` | - | How many of the room's stock tanks are at or below their low mark (0 when none). Attribute `tanks`: each tank's `id`, `pump` (the id of the dosing pump linked to it, or null), `name`, `level_l`, `capacity_l`, `percent`, `low_l`, `dose_ml` (what one batch takes now), `batches_left` and `low`. Attribute `last_batch`: the newest batch counted. The tanks are kept by the integration (Crop Steering → Stock tanks, or the `stock_*` services); a room with a tank last-fill entity mapped loses one batch's dose from every tank at each newer fill time, except a tank linked to a dosing pump: that one loses what the pump actually runs, whoever starts it ([DOSING.md](DOSING.md), Stock tanks). Automate a phone alert on it going above 0. |
| `dosing_config` | - | The room's batch-tank dosing setup, which the controller app reads every 2 s ([DOSING.md](DOSING.md)). State: the setup's revision (unknown while the stored setup can't be read). Attributes `pumps`, `batch` and `request`, the one request left for the controller. Kept by the integration (Equipment › Dosing, or the `dosing_*` services), which never switches, presses or sets anything itself. |
| `notify_config` | - | Who gets which alerts on the phones ([NOTIFICATIONS.md](NOTIFICATIONS.md)): one for the whole site however many rooms, so never prefixed. State: the setup's revision (`unavailable`, with an `error` attribute, while the stored setup can't be read). Attributes `recipients` (how many phones are set up: with none, the controller app pushes every alert to its own `notify_service` option as it always did) and `idle_hours` (after how many hours without a shot a room with its lights on is reported, CS-209). Kept by the integration (Settings & help › Notifications, or the `notify_*` services), which writes it with the first room that loads and removes it with the last: it is not a registry entity. |
| `dosing` | - | Published by the controller: what the room's dosing is doing ([DOSING.md](DOSING.md), Status). State `idle` / `dosing` / `batch`, or `unavailable` while the room's dosing setup can't be read. Attributes `pumps` (each pump's state, flow, the dose running and its last dose), `batch` (the step, each step's state, the result), `handled` / `handled_result` (the last request taken and what came of it), `history` (the last 20 doses and batches) and `updated_at` (its last publish, at least once a minute). Not published for a room whose integration has no `dosing_config`. |
| `tank_level` | % | Published by the controller for a room with a tank level mapped ([USER_GUIDE.md](USER_GUIDE.md), Tank level for the controller): the level from the tank distance sensor and the room's full and empty distances, `unknown` with none mapped, no reading, or the sensor judged stuck. Attributes `stuck` (the drawdown check: the shots have drawn the water for a 5 % fall at the learned litres per 1 % and the level has not moved), `litres_per_pct` (learned, null until the level has fallen 5 % once with shots counted), `low` (the low float's answer, null when none is mapped or it is unavailable), `below_minimum` and `over_full` (the reservoir minimum's and the overfill guard's marks, [USER_GUIDE.md](USER_GUIDE.md), Reservoir minimum) and `minimum_pct` (8). Not published for a room with no tank level mapped. |

The controller also publishes `sensor.f2_control_vitals`: the time of its last vitals report, with the report in the `vitals` attribute.

### Per-zone (`sensor.crop_steering_zone_N_*`)
| Entity | Unit | What it reports |
|---|---|---|
| `vwc_zone_N` | % | Fused substrate moisture (`zone_N_vwc` on older installs): the median of the zone's probes (the mean of two), carried across a probe dropping out without a step. Attributes: `probes` (how many are mapped), `used`, `excluded` (each set-aside probe with `no reading`, `out of range` or `not reporting`), `spread` (highest minus lowest probe used). |
| `ec_zone_N` | mS/cm | Fused pore-water EC (`zone_N_ec` on older installs), combined the same way, with the same attributes. |
| `zone_N_phase` | - | The zone's current phase (P0-P3). |
| `zone_N_auto_setpoints` | - | Published by the controller: `off` / `learning` / `tracking` / `frozen`. Attributes: `learned_peak`, `gain`, `day_rate`, `night_rate`, `p1_outcome` (`pending` / `reached` / `short` / `plateau` / `suspect`), `hold_days`, `frozen_reason`, `last_change`, `jev` (`disabled` / `ok` / `unavailable`), `jev_last` (the judge's latest hourly P2 answer), `jev_changed_today`, `working_peak_adjust`, `managed` (every number entity an automatic writer may rewrite on this zone: the learner's, plus the Setpoints judge's P2 shot size and re-water threshold while it runs, or the P2 shot size while the old hourly P2 check is configured), `managed_by` (each of those entities and the writer that owns it). |
| `zone_N_status` / `_status_app` | - | The controller's label for the zone, published on `zone_N_status_app` with a `reason` attribute and shown by `zone_N_status`, its only writer: `Drying back` / `Ramping` / `Optimal` / `Overnight dryback` (P0-P3, holding), `Flushing` / `Refilling` / `Topping up` / `Emergency` (watering), `Blocked: <why>`, `Blocked — EC/cap`, `Probe dead — copying`, `Room off`. `Controller not reporting` when the controller has not reported for 10 minutes. |
| `zone_N_waiting_for_app` | - | Published by the controller each minute: what would move the zone next, by the engine's own rules and numbers (`crop_steering_engine.waiting_for`), shown as the zone's "Next:" on the dashboard. State: the phase the list is for (`none`, with an empty list, while the zone has no usable probe or the room is off). Attribute `conditions`, one item per rule: `rule` (`p0_timeout` / `p0_bypass` / `p0_dryback`, `p1_ramp` / `p1_done` / `p1_max_shots`, `p2_topup` / `p2_dilute` / `lights_off`, `p3_emergency` / `p3_hold` / `lights_on`), `shot` (it fires a shot), `to` (the phase it moves to), then a reading test (`metric` `vwc` or `ec`, `op`, `value`, `now`) or a wait (`in_min`, minutes after `at`); `p1_done` adds `shots_left`, `ec_max`, `ec_now`; `p0_dryback` adds `dryback` (the % it waits for) and `peak` (the highest reading since lights-on it is measured from); `p2_topup` carries `in_min` too while a P2 time between shots is set; `p3_hold` (only while the zone's P3 Dryback Hold is on) adds `dryback`. Attribute `at`: when it was worked out. It lists the engine's routine rules, not a forecast: a held plan leaves out the shots it stops; the EC flushes, the watchdog, the daily minimum and P2's early move to P3 in the last three hours before lights-off are not listed; a gate or switch that holds watering is in `zone_N_status`. |
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

The pump, main line and each zone valve can be a `switch` or an `input_boolean` (switched with
`turn_on` / `turn_off`, read back `on` / `off`) or a `valve` (`valve.open_valve` /
`valve.close_valve`, read back `open` / `closed`). Every open, close and read-back goes through one
table in the controller (`ACTUATORS`), so a valve that does not read `closed` after a shot latches
the same hardware hold (CS-301) a switch that does not read `off` does. Setup refuses any other
domain; one mapped by hand holds its zone with CS-313 and is never sent a command.
