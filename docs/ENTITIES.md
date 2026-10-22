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
| `p0_dryback_drop_percent` | 2-40 | 15 | % | An old setting that stays for older rooms and recipes. The controller does not read this setting. The P0 dryback comes from the P0 extra dryback of each zone (`zone_N_p0_additional_dryback`, section 2). |
| `p0_minimum_wait` | 0-240 | 0 | min | Morning dryback minimum wait (default 0, off). Nothing but the re-water bypass ends P0 before this time after lights-on: not the dryback target, the stall exit, the maximum wait or the AI assistant. |
| `p0_maximum_wait_time` | 30-600 | 120 | min | The longest time that the morning dryback (P0) lasts after lights-on. At this time, the zone goes to P1, also when the dryback is not complete. |

### P1: ramp
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `p1_initial_shot_size` | 0.1-20 | 2 | % | The size of the first ramp shot, as a percentage of the substrate volume. Each later ramp shot adds the ramp shot increase to the shot before it. |
| `p1_shot_size_increment` | 0.05-10 | 0.5 | % | The size that each ramp shot adds to the shot before it, as a percentage of the substrate volume. The third ramp shot is the first ramp shot plus two times this value. |
| `p1_minimum_shots` | 1-20 | 3 | - | The number of ramp shots that P1 must give before it can end because the substrate is full. P1 can still end at the maximum ramp shots, at the maximum extra shots, or with the daily water limit spent. |
| `p1_maximum_shots` | 1-30 | 6 | - | The highest number of shots in P1. At this number, the zone goes to P2 at any VWC. |
| `p1_rise_pts` | 0.1-5 | 0.5 | % | After P1 reaches its peak target, it gives extra shots. P1 gives another extra shot only while each one raises the settled VWC (the median of the last 10 minutes) by at least this value. When the controller knows the gain of the zone, the necessary rise is the larger of this value and 0.3 times the expected rise. |
| `p1_maximum_extra_shots` | 1-30 | 3 | - | The highest number of extra shots that P1 gives after VWC reaches the peak target. At this number, the zone goes to P2. Extra shots count toward the daily water limit and toward `p1_maximum_shots`, which ends P1 first (raise both for more extra shots), and P1 gives no extra shot while the zone does not drain (CS-310). |
| `p1_target_vwc` | 20-100 | 65 | % | Peak target: the VWC at which the ramp (P1) stops the ramp shots. The ramp stops at this value or at field capacity, whichever is lower. Then P1 gives extra shots until a shot no longer raises VWC enough. |
| `p1_time_between_shots` | 1-60 | 15 | min | The minimum time between ramp shots. A ramp shot or an extra P1 shot starts only when this time has passed since the last shot. |

### P2: maintenance
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `p2_vwc_threshold` | 10-100 | 60 | % | Re-water point: the VWC that starts a maintenance shot in P2. Each time the controller checks in P2, it gives a shot when VWC is below this value. In P0, VWC at or below this value ends the morning dryback. |
| `p2_shot_size` | 0.5-30 | 5 | % | The size of each maintenance shot, as a percentage of the substrate volume. Watchdog shots and daily minimum shots use this size. EC flushes and dilution shots use 1.5 times this size or more. |
| `p2_time_between_shots` | 0-60 | 0 | min | The minimum time from the last shot before a maintenance shot can start. It gives the water time to reach the probe before the controller reads VWC again. EC corrections use the EC correction interval. `0` stops this wait. |
| `p2_timed_interval_min` | 5-720 | 60 | min | Timed P2 (read only while the zone's `zone_N_p2_mode` is Timed or Timed with guards): the time from the last shot to the next timed P2 shot. Missed slots never stack. Timed shots count toward the daily water limit and stop under a held grow plan. |
| `p2_timed_shot_size` | 0-20 | 0 | % | The size of a timed P2 shot, as a percentage of the substrate volume. `0` uses `p2_shot_size`. |
| `p2_timed_first_hours` | 0-24 | 0 | h | No timed P2 shot before this many hours after lights-on. |
| `p2_end_hours_before_off` | 0-12 | 0 | h | P2 ends this many hours before lights-off (default 0, off): P1 and P2 go to P3 at that time, whatever the VWC, and the predictive P3 is not used. In P3 the rescue shots, the watchdog and the minimum daily water still run. |
| `ec_min_interval` | 1-120 | 10 | min | The minimum time from the last shot before an EC correction (a flush or a dilution shot) or a daily minimum shot can start. With a settled pore EC reading, the wait is at least the EC settle time of the substrate type (45 min for generic). |
| `ec_flush_target` | 0-9 | 0 | mS/cm | EC flush target (default 0, off). After an EC flush fires, P2 gives more dilute shots until the settled pore EC is at or below this value, never below the feed EC + 0.2. The shots count toward the daily water limit, wait the EC correction interval, and need a dilutive feed, a draining table and VWC below field capacity - 2. Lights-off ends the flush. |
| `p2_ec_high_threshold` | 0.5-3.0 | 1.2 | ×target | A ratio of pore EC to the EC target. The integration uses it only for the `p2_vwc_threshold_adjusted` sensor. The controller does not read this setting. The ratio at which P2 dilutes is `p2_dilute_ratio`. To move the re-water point with pore EC, use `ec_stacking_enabled`. |
| `p2_dilute_ratio` | 1.0-3.0 | 1.2 | ×target | P2 dilute EC ratio. Read only while `use_p2_ec_thresholds` is on: then P2 gives a dilute shot when pore EC is above this ratio times the P2 EC target, instead of 1.2. |
| `p2_ec_low_threshold` | 0.2-2.0 | 0.8 | ×target | A ratio of pore EC to the EC target. The integration uses it only for the `p2_vwc_threshold_adjusted` sensor. The controller does not read this setting. To move the re-water point with pore EC, use `ec_stacking_enabled`. |

### P3: pre-lights-off / overnight
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `p3_emergency_vwc_threshold` | 10-65 | 40 | % | Rescue floor: the overnight safety level of VWC. In P3, the controller gives a rescue shot each time VWC is below this level. Rescue shots can go past the daily water limit. |
| `p3_emergency_shot_size` | 0.1-15 | 2 | % | The size of each rescue shot, as a percentage of the substrate volume. Rescue shots can go past the daily water limit. With the P3 dryback hold on, hold shots also use this size. |
| `p3_time_between_shots` | 0-60 | 10 | min | The minimum time from the last shot before a rescue shot can start. It gives the water time to reach the probe before the controller reads VWC again. The time counts from the last shot of any type. `0` stops this wait. |

### EC targets: vegetative & generative (per phase)
| Entity | Range | Default | Unit |
|---|---|---|---|
| `ec_target_veg_p0` / `_p1` / `_p2` / `_p3` | 0.5-15 | 3.0 / 3.0 / 3.2 / 3.0 | mS/cm |
| `ec_target_gen_p0` / `_p1` / `_p2` / `_p3` | 0.5-20 | 4.0 / 5.0 / 6.0 / 4.5 | mS/cm |

The active EC target is the row for the current phase **and** the steering mode of the zone.
`sensor.crop_steering_ec_ratio` is the current EC divided by this target.
The controller does not read `ec_target_veg_p3` or `ec_target_gen_p3`. The integration shows them
only in the EC ratio sensor during P3.

### EC & safety limits
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `irrigation_ec_min` | 0-20 | 0 | mS/cm | The lowest feed EC at which the controller starts shots. While the feed EC is below this value, all shots in the room wait. It operates only when the controller app has a feed EC sensor. `0` removes the lower limit. |
| `irrigation_ec_max` | 0-20 | 0 | mS/cm | The highest feed EC at which the controller starts shots. While the feed EC is above this value, all shots in the room wait. It operates only when the controller app has a feed EC sensor. `0` removes the upper limit. |
| `irrigation_ph_min` | 3.0-9.0 | 5.5 | pH | The lowest feed pH at which the controller starts shots. While the feed pH is below this value, all shots in the room wait. It operates only when the controller app has a feed pH sensor. A room configured before 5.5 to 6.5 became the default keeps its own band. |
| `irrigation_ph_max` | 3.0-9.0 | 6.5 | pH | The highest feed pH at which the controller starts shots. While the feed pH is above this value, all shots in the room wait. It operates only when the controller app has a feed pH sensor. |
| `maximum_ec` | 1-20 | 9.0 | mS/cm | The highest pore EC that the controller accepts in a zone. At or above this level, the controller gives a flush in any phase when the feed EC is lower than the pore EC. When the feed EC is not lower, or the zone does not drain, the zone gets no shot of any type. The high-EC flush needs VWC more than 2 points below field capacity. Nearer to field capacity, the zone loses only that flush, and the other shot rules continue. |
| `max_shot_duration` | 5 to the room's limit | 900 | s | The longest time that a valve in this room stays open for one shot. The controller cuts a longer planned shot to this time (CS-306). The limit of the setting is the time that the slowest zone needs to give one full substrate volume, and at least 900 s. If the controller cannot read this value, or it is below 5 s, it starts no shot (CS-203). |
| `sump_power_threshold_w` | 1-10000 | 20 | W | The power above which the sump pump counts as on. The power sensor is the `sump_power_sensor` option of the controller app. If the sump pump draws no power above this value for `sump_silent_hours`, the controller sends a CS-311 alert. |
| `sump_litres_per_run` | 0-500 | 0 | L | The runoff estimator's pit volume: the litres one sump run empties, from a bucket test. 0 is unknown: the estimator then uses the pump flow times the run time, else the sealed-room closure, and never invents litres. |
| `sump_pump_flow_lpm` | 0-500 | 0 | L/min | The sump pump's flow, used with its run time when the litres per run are 0. 0 is unknown. |
| `runoff_attribution_min` | 15-240 | 90 | min | The longest delay from a shot to its runoff reaching the sump that the runoff estimator tries; it learns the delay that fits best. |
| `hvac_run_power_w` | 1-10000 | 50 | W | An AC or dehumidifier mapped by its power sensor counts as running above this, for the runoff estimator. |
| `cwsi_lower_baseline` / `cwsi_upper_baseline` | -15 to 15 | 0 | °C | The plant-stress card's CWSI baselines, your own: the leaf minus air temperature of a well-watered canopy (lower) and of one that has stopped transpiring (upper). The card shows CWSI only when upper is above lower; both 0 (the default) is off. Display only: the controller does not read them. |
| `ph_correct_dose_s` | 1-30 | 5 | s | pH auto-correct: one dose, in seconds of the pH pump's calibrated flow (whole mL, never above its largest dose). Used only while `ph_auto_correct` is on ([DOSING.md](DOSING.md#ph-auto-correct)). |
| `ph_correct_max_tries` | 1-3 | 2 | | pH auto-correct: the most doses in one correction. |
| `ph_correct_mix_min` | 2-30 | 5 | min | pH auto-correct: the mixing after each dose before the tank is read again. |
| `ph_correct_daily_max` | 1-10 | 3 | | pH auto-correct: the most doses in one day. |
| `ph_correct_margin` | 0-0.5 | 0.1 | pH | pH auto-correct: how far inside the feed pH band a correction stops. |
| `dry_dim_floor_vwc` | 1-60 | 15 | % | Dimming on dry substrate: a zone under this VWC counts as dry. Used only while `dry_dim` is on ([DOSING.md](DOSING.md#light-dimming-on-dry-substrate)). |
| `dry_dim_level_pct` | 30-90 | 50 | % | Dimming on dry substrate: the brightness the light is dimmed to. Never below 30 %, never off. |
| `dry_dim_after_min` | 1-120 | 10 | min | Dimming on dry substrate: how long a zone stays dry, with the lights on, before the light is dimmed. |
| `dry_dim_max_h` | 0.5-12 | 4 | h | Dimming on dry substrate: the longest the light stays dimmed; then it is set back and a critical alert says so (CS-811). |
| `held_alert_hours` | 0-72 | 0 | h | Shots held alert: a zone that asked for water and was held this long with no shot raises CS-211 (critical). A hold a person set (kill switch, zone switch, manual override) does not count. `0` turns the alert off. |
| `pump_prime_time` | 0-20 | 2 | s | The time that the pump runs before the main-line valve opens. With no main-line valve, the zone valve opens after this time. The controller uses it only when the room has a pump. |
| `main_line_lead_time` | 0-10 | 1 | s | The time that the main-line valve is open before the zone valve opens. The controller uses it only when the room has a main-line valve. |
| `watchdog_hours` | 0-12 | 3 | h | The longest time that a zone can go without a shot while the lights are on. When this time is past and VWC is below the re-water point, the controller gives a watchdog shot. When a hold stops the shot, it sends an urgent alert (CS-207). The watchdog does not operate in P0. `0` stops the watchdog. |
| `setpoint_max_step_per_day` | 0-50 | 1 | % | Max setpoint move per day: the most that the automatic writers move field capacity, the peak target or the re-water point of a zone in one grow-day, in VWC points. `0` = no limit. Following the probe's own highest readings feeds a drifting or flooded probe back into the setpoints: above about 3, one bad reading can move the re-water point, and the water, a long way in a day. `setpoint_step_limit_applies_to` says which writers it holds. |

### Substrate & schedule
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `substrate_volume` | 1-200 | 10 | L | The litres of substrate for each plant, for example the volume of one block or pot. All shot sizes are a percentage of this volume. The water of a shot is the shot size, times this volume, times the plant count. |
| `dripper_flow_rate` | 0.1-50 | 1.2 | L/hr | The litres per hour that one dripper gives. The controller uses it to calculate how long each shot runs. A value of 0, or a value that the controller cannot read, stops the shots of that zone (CS-204). |
| `drippers_per_plant` | 1-6 | 2 | - | The number of drippers on each plant. With the dripper flow and the plant count, it gives the zone flow. The shot time is the water of the shot divided by the zone flow. |
| `field_capacity` | 40-100 | 70 | % | The VWC at which the substrate is full and drains freely. The ramp stops at this level or at the peak target, whichever is lower. EC flushes that can go past the daily water limit need VWC more than 2 points below it. |
| `vegetative_dryback_target` | 5-80 | 35 | % | The dryback for a zone in vegetative steering mode, as a percentage of the peak. At a peak of 60% and a target of 10%, the dryback ends at 54% VWC. The controller uses it in P0 when the P0 extra dryback is 0, and to start P3 early. |
| `generative_dryback_target` | 5-70 | 45 | % | The dryback for a zone in generative steering mode, as a percentage of the peak. At a peak of 60% and a target of 10%, the dryback ends at 54% VWC. The controller uses it in P0 when the P0 extra dryback is 0, and to start P3 early. |
| `lights_on_hour` | 0-23 | 12 | hour | The hour, from 0 to 23, when the lights come on. The grow-day starts at this hour. The zones move from P3 to P0, and the daily water and shot counters of each zone reset. |
| `lights_off_hour` | 0-23 | 0 | hour | The hour, from 0 to 23, when the lights go off. At lights-off, the controller moves each zone to P3, the overnight dryback. |

---

## 2. Numbers: per-zone overrides (`number.crop_steering_zone_N_*`)

Every zone gets its own copy of the setpoints below. The engine uses the zone's value
for that zone. (3 zones × 27 = 81 entities on a 3-zone system.)

**Per-zone copies of the global setpoints:** `p0_dryback_drop_percent`,
`p0_maximum_wait_time`, `p1_initial_shot_size`, `p1_shot_size_increment`,
`p1_minimum_shots`, `p1_maximum_shots`, `p1_rise_pts`, `p1_maximum_extra_shots`, `p1_target_vwc`,
`p1_time_between_shots`,
`p2_vwc_threshold`, `p2_shot_size`, `p2_time_between_shots`, `ec_min_interval`, `p3_emergency_vwc_threshold`,
`p0_minimum_wait`, `ec_flush_target`, `p2_dilute_ratio`, `p2_timed_interval_min`, `p2_timed_shot_size`,
`p2_timed_first_hours`, `p2_end_hours_before_off`,
`p3_emergency_shot_size`, `p3_time_between_shots`, `vegetative_dryback_target`, `generative_dryback_target`,
`ec_target_veg_p0` to `_p2`, `ec_target_gen_p0` to `_p2`, `field_capacity`,
`maximum_ec` and `watchdog_hours`. Ranges match the globals above.

**Per-zone only (no global equivalent):**
| Entity | Range | Default | Unit | What it does |
|---|---|---|---|---|
| `zone_N_plant_count` | 1-50 | 4 | - | The number of plants in this zone. The water of a shot is the shot size, times the substrate for each plant, times this number. |
| `zone_N_p0_additional_dryback` | 0-40 | 3 on a room set up from this release, 0 on a room updated in place | % | P0 extra dryback: the dryback after lights-on before the first shot, as a percentage of the highest VWC since lights-on. At 3% and a highest VWC of 60%, P0 ends at 58.2% VWC. At `0`, P0 uses the dryback target of the steering mode. P0 also ends at the maximum wait time, or when VWC falls to the re-water point. |
| `zone_N_max_daily_volume` | 0 to the zone's limit | 20 | L | The most water that a zone gets in one grow-day, in litres. Maintenance shots, extra ramp shots, dilution shots and P0 EC flushes stop at this limit, and the last shot gets only what is left. Ramp shots, rescue shots, watchdog shots and high-EC flushes can go past it. The limit of the setting is 4 times the substrate of the zone (plants x litres for each plant), and at least 20 L. A value already above it stays, and Repairs lists it (CS-611). |
| `zone_N_min_daily_ml_per_plant` | 0-10000 | 0 (off) | mL | The least water that each plant gets in one grow-day, in millilitres. The controller gives it at any probe reading, from lights-on (never in P0), and spreads it so that it is complete 3 h before lights-off. The shots stop when VWC is 5 points above field capacity, and never go past the daily water limit. A new entity takes the value of the old `input_number` helper of the same name. |
| `zone_N_substrate_volume` / `zone_N_drippers_per_plant` / `zone_N_dripper_flow_rate` | as the globals | from setup | - | Created only when setup sizes the zone itself; otherwise the room-wide value applies. |

---

## 3. Switches

### Global (`switch.crop_steering_*`)
| Entity | What it does |
|---|---|
| `room_active` | Room on/off (default on). Tells the controller that plants grow in the room. Off: the controller gives no shot of any type in the room, rescue shots included, and sends no alerts for the room. A shot that runs stops within a few seconds. Per room: `switch.crop_steering_<prefix>room_active`. |
| `auto_setpoints` | Auto setpoints (default off). Lets the controller change the VWC setpoints of each zone from what it learns about the zone. On: field capacity follows the highest VWC of this grow-day or the grow-day before. The peak target follows the highest VWC of the grow-day before. Each moves 1 point or less each grow-day. When field capacity moves, the re-water point moves by the same number of points. The controller never changes the rescue floor, and writes nothing while an armed grow plan controls the room. While the Setpoints judge of the AI assistant runs, it owns the P2 shot size and the re-water point. The learner owns the rest ([JEV.md](JEV.md#who-writes-which-setpoint)). Off: the controller learns and reports, but writes no setpoint. Per room: `switch.crop_steering_<prefix>auto_setpoints`. |
| `notify_predictions` | Predictions in notifications (default on, also on an upgraded room). Adds the next step of each zone to the vitals report of the controller. The dashboard shows the same step as `Next:`. Off: the vitals report gives only the readings. A controller that cannot find this switch includes the predictions. Per room: `switch.crop_steering_<prefix>notify_predictions`. |
| `water_vpd_insight` | Water vs VPD (default off, also on an upgraded room). On: the controller keeps each zone's grow-day records (litres, the median dryback rate in quiet lights-on windows, the mean lights-on VPD from the room's VPD sensor, or from its temperature and humidity) and publishes `zone_N_water_response_app`. Read only: nothing it records changes a shot or a setting. Per room. |
| `plant_stress_card` | Plant stress card (default off). On: the dashboard shows leaf minus air temperature, leaf VPD and, with your own baselines, CWSI on Today and the zone page, where a leaf temperature sensor is mapped in setup (the room's, or the zone's own). Hidden with the lights off. Display only. Per room. |
| `record_grow_days` | Record grow days (default off, also on an upgraded room). On: at each lights-on the controller sends a summary of the grow-day that ended for every zone (moisture peak, trough and mean, pore EC, feed EC and pH, P1 plateau, P0 and night dryback, shots by kind, litres, rescues, alerts, the targets in force, and each probe behind the zone) to the room's grow-day store, read with `crop_steering.grow_days_get`. It only records: it never changes watering. Summaries Home Assistant does not take are kept by the controller, the newest 14 grow-days. Per room: `switch.crop_steering_<prefix>record_grow_days`. |
| `system_enabled` / `auto_irrigation_enabled` | **Retired**, hidden, named "(retired)". The kill switch (`engine_enabled`) is the one switch that stops the water of the room. While one of these switches is off, a current controller sets the kill switch of the room to off and raises alert CS-208. A controller of version 2.24.0 or older holds every shot while one of them is off or missing. |
| `max_run_latch` | Max-run latch: on in a room configured since it was added, off in an older room. Stops a zone when its last 3 shots in a row all ran to the maximum shot length of the room. On: the zone gets no more shots, rescue shots included, until you fix its Repairs card (CS-312). The fix adds one to the `resets` attribute of this switch, which the controller watches. Off: the Repairs card reports the zone, and the zone continues to get water. Per room: `switch.crop_steering_<prefix>max_run_latch`. |
| `ec_stacking_enabled` | EC stacking (default off). Lets the controller move the re-water point of each zone in maintenance (P2) to steer the pore EC to the P2 EC target. On: every 30 min in P2, the re-water point moves by 1 point or less. It goes down when pore EC is below 90% of the target, and up when pore EC is above 110%. The total move is 20% of the re-water point or less, and it returns to 0 at lights-on. |
| `p0_stall_exit` | P0 stall exit (default off). After 30 min of P0, the ramp starts when the dryback is slower than 0.1 VWC points an hour, or would not reach its target before `p0_maximum_wait_time` at its measured rate. Never while the probe is in doubt (a flat or bypassed reading) or the table is not draining. |
| `use_p2_ec_thresholds` | Use P2 EC ratios (default off). On: P2 dilutes when pore EC is above the zone's `zone_N_p2_dilute_ratio` times the P2 EC target. Off: above 1.2 times, as always. |
| `engine_enabled` | The kill switch of the room ("Watering" in the Settings of the dashboard). The integration creates it as off. Off: the controller starts no shot in the room, rescue shots and test shots included, and a shot that runs stops within a few seconds. The kill switch does not disconnect the electrical power. The integration creates it for named rooms and new default rooms. An older default room uses the helper that its setup names. |
| `ph_auto_correct` | pH auto-correct (default off, also on an upgraded room). On: a batch tank that reads outside the feed pH band for 5 minutes is mixed and dosed by the pump with that pH role, a few small doses at most, and read again after each. A failed correction locks it (CS-809) until you switch it off and on again. It never loosens the source-water gate ([DOSING.md](DOSING.md#ph-auto-correct)). Per room: `switch.crop_steering_<prefix>ph_auto_correct`. |
| `dry_dim` | Dim lights on dry substrate (default off, also on an upgraded room). On: while a zone reads under `dry_dim_floor_vwc` with the lights on, the room's mapped light (a dimmable `light.*` only) is dimmed to `dry_dim_level_pct`, and its brightness is restored when the zones recover, at lights-off, when this switch or the kill switch goes off, after `dry_dim_max_h` and after a restart ([DOSING.md](DOSING.md#light-dimming-on-dry-substrate)). Per room: `switch.crop_steering_<prefix>dry_dim`. |

### Per-zone (`switch.crop_steering_zone_N_*`)
| Entity | What it does |
|---|---|
| `zone_N_enabled` | The on/off switch of one zone ("zone scheduling" on the dashboard). Off: the controller gives the zone no shot, not even a rescue shot or a test shot. A shot that runs in the zone stops within a few seconds. If the controller cannot read the switch, it holds the zone. |
| `zone_N_manual_override` | A maintenance lockout for one zone. On: the controller gives the zone no shot of any type, rescue shots and test shots included, and stops a shot that runs. Set with this switch, the override stays on until you set it to off. Set with the `crop_steering.set_manual_override` service, it goes off after its timeout. The override does not isolate the electrical power. |
| `zone_N_p3_dryback_hold` | P3 dryback hold (default off). Holds the overnight dryback (P3) of the zone at its dryback target. On: in P3, each time VWC falls below the peak of the grow-day less the dryback target, the zone gets a shot. The shot has the rescue shot size, and the shots are at least `p3_time_between_shots` apart. The hold is steering, so a held grow plan and the daily water limit stop it. The rescue shot still runs below the hold. |

---

## 4. Selects

### Global (`select.crop_steering_*`)
| Entity | Options | What it does |
|---|---|---|
| `steering_mode` | Vegetative · Generative | The steering mode of the room: Vegetative or Generative. Each zone has its own steering mode (`zone_N_steering_mode`). The controller reads the select of each zone, and the growth stage when it cannot read it. The integration uses this room select for the EC ratio sensor and for a zone with no select of its own. |
| `growth_stage` | Vegetative · Generative · Transition | The growth stage of the room. The controller reads it only when it cannot read the steering mode of a zone. Vegetative then uses the vegetative targets, and Generative or Transition the generative targets. When the steering mode of each zone reads correctly, a change here does not change the shots. |
| `irrigation_phase` | P0 · P1 · P2 · P3 | A manual phase marker for the room. The controller does not read it, and a change does not move a zone. The `ec_ratio` sensor uses it to find its EC target. To move a zone, use `zone_N_set_phase`. |
| `recipe_stage` | Veg · Transition · Bulk · Ripen · Custom | Selects a stage of the room recipe. When you select a stage, the integration writes the setpoints of that stage into the numbers of the room and of each zone. Each value stays inside the limits of its number. If the VWC setpoints of the stage put the levels of a zone out of order, the integration writes nothing and shows an error. |
| `drainage` | unknown · flood_table · free_drain | Tells how the runoff leaves the room. The setup asks for it on its first page. `free_drain`: the controller does not watch the room for a table that does not drain (CS-310), and removes a CS-310 card that the room has. `flood_table`: the controller watches each zone for VWC that rises with no water. It holds the EC flushes and the extra ramp shots of a backed-up zone (CS-310). `unknown`: the controller watches the room as for a flood table. A room configured before this select reads `unknown`. |
| `water_today_view` | Zone total · Per plant | Selects how the dashboard and the vitals report show the water today of each zone. Zone total (default): the litres of each zone. Per plant: the water and the daily limit of each zone divided by its plant count. The dashboard shows the choice to all users (Settings → Appearance). It changes only the display, not the shots. |
| `substrate` | generic · rockwool · coco | Tells the controller what the room grows in. The controller reads it from the room descriptor (`engine_config`) and uses a change without a disarm. `generic` (default, also on an upgraded room): the controller runs as before. `rockwool` and `coco` set the starting VWC setpoints and dryback targets of a setting that has no value yet. With `coco`, the controller waits 60 min after a shot before it uses a pore EC reading. A value that the room already has does not change. |
| `ai_no_touch` | Off · 1 h · Until lights-on · 24 h | Pause AI changes: starts a no-touch period for the room, for example while a person takes samples. During the period, the AI assistant asks nothing and changes nothing in the room, and the shots continue by the rules of the controller. The `no_touch_until` value of the brain panel tells when the period ends, and the `since` attribute when it started. At the end, the controller sets the select back to Off. Off by default, also on an upgraded room. |
| `setpoint_step_limit_applies_to` | Auto setpoints · Auto setpoints and AI | Which automatic writers `setpoint_max_step_per_day` holds. Auto setpoints (default): the follower of the highest readings only, as before. Auto setpoints and AI: the Auto setpoints learner and the AI assistant's targets power too, on one shared ledger, so the first writer of the day uses the allowance. |
| `runoff_estimator` | off · shadow · shown_alerts · ai | The runoff estimate from the sump's water balance (off by default, also on an upgraded room). `shadow`: the controller records the sump runs (its `sump_power_sensor` option), the run time of each AC and dehumidifier mapped in setup and the water fed, fits them, and publishes `runoff_estimate_app`. `shown_alerts`: also CS-314 when a grow-day's sump litres miss the water fed minus the substrate's change by more than 30% (a sealed room). `ai`: also gives the AI assistant the estimate as a room-wide hint with its error band. Room-wide and per grow-day; no mode waters from it. |
| `shot_check` | off · table · table_and_alert | The controller's own check of each shot (off by default, also on an upgraded room). `table`: `zone_N_shot_log_app` lists the zone's last 8 shots with the VWC rise their litres should give, the rise seen and the pore EC change, and a verdict, shown on the zone page; with the AI assistant on, its shot judge's answer sits beside it. `table_and_alert`: also CS-701 after two counted shots in a row with no sign of water, only while the AI assistant is off (flush and P3 shots, and shots within 1 point of field capacity, do not count). Never changes a shot. |

### Per-zone (`select.crop_steering_zone_N_*`)
| Entity | Options | What it does |
|---|---|---|
| `zone_N_set_phase` | Keep · P0 · P1 · P2 · P3 | Moves the zone to a phase by hand. The controller applies the choice one time, within a minute, and then sets the select back to Keep. The water and the shot count of the grow-day stay. P1 starts the ramp again from its first shot, and P0 measures the dryback from the VWC at the move. After the move, the rules continue: lights-off moves the zone to P3, and lights-on moves it to P0. |
| `zone_N_p2_mode` | Moisture · Timed · Timed with guards | How the zone waters in P2. Moisture (default): a maintenance shot when VWC falls below the re-water point, as always. Timed: a shot every `p2_timed_interval_min`, whatever the VWC. Timed with guards: as Timed, but a slot is skipped while VWC is at or above the peak target (or field capacity - 2), and the maintenance shot still fires below the re-water point. The EC rescue and dilute shots come first in every mode. |
| `zone_N_steering_mode` | Vegetative · Generative | The steering mode of the zone: Vegetative or Generative. Vegetative: the zone uses the vegetative dryback target and EC targets. Generative: the zone uses the generative dryback target and EC targets. |
| `zone_N_vwc_method`, `zone_N_ec_method` | Median · Average · Lowest · Highest | How the zone's probes become its moisture reading, and apart its EC reading. Median by default. A probe far from the others is left out first; Lowest and Highest need three probes that agree, and with fewer the zone steers on the median and the controller raises CS-502. |
| `ec_type_<probe>` (one per mapped EC probe, named after the probe's entity id) | unknown · pore · bulk | Tells what the EC probe measures. Pore EC is the EC of the water in the pores of the substrate. Bulk EC is the EC of the substrate and the water together, and reads lower. `unknown` (default): the probe combines with the other probes as before. A zone never combines pore EC and bulk EC readings. It steers on its pore probes, and on its bulk probes only while no pore probe reports. The controller then raises alert CS-504. |

### Per-zone buttons (`button.crop_steering_zone_N_*`)
| Entity | What it does |
|---|---|
| `zone_N_test_shot` | Asks the controller for a test shot in the zone, to check the water delivery: 10 s, or the zone's `zone_N_manual_shot_seconds`. The controller acts at its next pass, within a minute, on a press less than 10 min old. The test shot goes through each check of a normal shot, but a held grow plan does not stop it. The `crop_steering.test_shot` service presses it by room ID. |

### Safety and operations (each starts at what the room did before)
| Entity | Default | What it does |
|---|---|---|
| `button.crop_steering_stop_all` | - | Stop all. Sets the kill switch to off, then the pump, the main-line valve, the waste valve and every zone valve of the room to off, and reads each back. Works with the controller app stopped. Never switches anything on. A device that stays on raises CS-308. The `crop_steering.stop_all` service does the same by room ID. |
| `number.crop_steering_zone_N_manual_shot_seconds` | 10 s | How long the zone's Test Shot waters (5-3600 s). Still cut to `max_shot_duration` and to the day's water budget left. |
| `select.crop_steering_waste_valve_rule` | Off | Off: the controller does not read the mapped waste valve. Check closed: no shot starts while it reads open (CS-316). Close for each shot: the controller switches it off and reads it back before each shot, and the shot does not start if it stays open. It never opens it. |
| `switch.crop_steering_rescue_past_dead_feed_probe` | off | On: while the feed EC or pH probe is dead, a P3 emergency or watchdog rescue still passes the source-water gate. Routine shots still hold, an out-of-band feed reading still holds every shot, and every other hold applies. |
| `select.crop_steering_rescue_miss_action`, `number.crop_steering_rescue_miss_count` | Off, 4 | Alert: CS-315 after this many rescue shots in a row that did not raise the moisture. It never stops water. |
| `number.crop_steering_pump_deadhead_watts` | 20 W | With the controller app's `pump_power_sensor` option: CS-317 when the pump draws more than this for 1 min with every zone valve off and no shot, hold or batch. Alert only. |
| `number.crop_steering_tank_size_l`, `number.crop_steering_tank_estimate_low_pct`, `button.crop_steering_tank_filled` | 0 (off), 20 % | With no tank level sensor mapped: the tank level estimated from the shots' water since Tank filled (or a batch that filled it), on `sensor.crop_steering_tank_level` with `source: estimate`. CS-905 at or below the low %. It never holds a shot. |

---

## 5. Sensors (read-only)

### System (`sensor.crop_steering_*`)
| Entity | Unit | What it reports |
|---|---|---|
| `activity_log` | - | Shows the newest event of the controller: a shot, a hold or a phase change. The `feed` attribute gives the recent events. |
| `app_current_phase` | - | Shows the phase of each zone, as the controller keeps it. Example: `Z1:P3, Z2:P3, Z3:P3`. |
| `current_phase` | - | Shows the phase of the room as the integration sees it. It copies `app_current_phase` from the controller. When the controller has published nothing, or nothing for more than 10 minutes, it shows `unknown` and a `reason` attribute; it never shows a default phase. |
| `current_decision` | - | Shows what the controller decided in its last pass for the room: the first shot, else the first hold. The `fired` and `blocked` attributes give all zones. |
| `app_status` | - | Shows the state of the controller for the room: `safe_idle` (no shot runs), `irrigating` (a shot runs), `error` (a hardware fault or a fail-closed hold stops the room) or `room_off`. |
| `system_safety_status` | - | Shows the worst safety label of the zones of the room: `safe`, `warning` or `unsafe`. The attributes give the number of zones in each group. |
| `ai_heartbeat` | - | Shows that the controller runs. The controller writes `healthy` at each pass, and `stopped` when the app stops, updates or restarts (attribute `stopped_at`). Attribute `controller_version`: the version of the controller app that runs. The dashboard sidebar shows it next to the `integration_version` of the descriptor. Attribute `write_failures`: the state writes to Home Assistant that failed since the controller started; the app log names each entity, at most once an hour. |
| `engine_config` | - | The descriptor of the room. The controller reads it to find and drive the valves, the pump, the main line, the kill switch and the zones (`setup_revision`). Attribute `integration_version`: the integration that Home Assistant loaded. Attribute `entry_id`: tells one room from a room that a person deleted and configured again, which starts its revision again at 1. Neither attribute enters the setup fingerprint. |
| `configured_avg_vwc` / `configured_avg_ec` | % / mS/cm | Show the mean VWC and the mean EC of all the probes that the room maps, in all zones. The controller does not steer on them. |
| `ec_ratio` | - | Shows the mean EC of all zone probes divided by the EC target of the room. The integration makes it for display, and the controller does not read it. The target comes from the `irrigation_phase` select and the steering mode of the room. |
| `p1_shot_duration_seconds` / `p2_shot_duration_seconds` / `p3_shot_duration_seconds` | s | Show how many seconds the first ramp shot, a maintenance shot and a rescue shot run. The integration calculates them from the substrate volume, the shot size, the drippers per plant and the dripper flow. The values are in whole seconds, at least 5 s and not more than the maximum shot length of the room. Each shows the longest zone, and the `zones` attribute gives each zone. |
| `p2_vwc_threshold_adjusted` | % | Shows the re-water point of the room with a fixed change of 5 points for the EC ratio (`p2_ec_high_threshold`, `p2_ec_low_threshold`). The integration makes it for display, and the controller does not read it. The controller uses its own EC steer, which `ec_stacking_enabled` controls. |
| `stock_low` | - | Shows how many stock tanks of the room are at or below their low mark (0 when no tank is low). Attribute `tanks`: each tank's `id`, `pump` (the ID of the dosing pump linked to it, or null), `name`, `level_l`, `capacity_l`, `percent`, `low_l`, `dose_ml` (what one batch takes now), `batches_left` and `low`. Attribute `last_batch`: the newest batch that the integration counted. The integration keeps the tanks (Crop Steering → Stock tanks, or the `stock_*` services; [DOSING.md](DOSING.md), Stock tanks). Make an automation that sends a phone alert when the value goes above 0. |
| `dosing_config` | - | The batch-tank dosing setup of the room, which the controller reads ([DOSING.md](DOSING.md)). The state is the revision of the setup, or `unknown` while the integration cannot read the stored setup. Attributes `pumps`, `batch` and `request` (the one request that waits for the controller). The integration keeps it (Equipment › Dosing, or the `dosing_*` services), and never starts a pump itself. |
| `brain_questions` | - | Keeps the last five questions of the room to the AI assistant, from Ask why or the `brain_ask` service. The state is the number of questions kept. Attribute `questions`: each one's `id`, `question` (300 characters or less), `zone` (or null for the room), `at` and `by`. The integration only keeps the questions, and the controller asks the AI assistant. |
| `brain_answers` | - | Shows the answers of the AI assistant to `brain_questions`, the last five. An answer never changes a setting. State: `asking` while a question waits, `answered`, or `none`. Attribute `answers`: each one's `id` (the ID of the question), `question`, `zone`, `asked_at`, `answered_at`, `answer`, `grounded_in` and `cannot_answer`; also `pending`, `asked_today` and `daily_limit` (20 for each room each day). Only the `claude_haiku` AI assistant answers. With a different `brain_provider`, each answer gives the reason. |
| `notify_config` | - | Shows who gets which alerts on the phones, for the whole site ([NOTIFICATIONS.md](NOTIFICATIONS.md)), so it has no room prefix. State: the revision of the setup (`unavailable`, with an `error` attribute, while the integration cannot read the stored setup). Attribute `recipients`: the number of phones. With no phones, the controller sends each alert to its own `notify_service` option. Attribute `idle_hours`: the hours with the lights on and no shot before alert CS-209. The integration keeps it (Settings › Notifications, or the `notify_*` services). It is not a registry entity. |
| `dosing` | - | Shows what the dosing of the room does: `idle`, `dosing` or `batch`, or `unavailable` while the controller cannot read the dosing setup ([DOSING.md](DOSING.md), Status). The controller publishes it when it changes, and at least one time each minute (`updated_at`). Attributes `pumps`, `batch`, `handled` / `handled_result` (the last request and its result) and `history` (the recent doses and batches). Not published for a room whose integration has no `dosing_config`. |
| `tank_level` | % | Shows the level of the tank that the room waters from, in percent ([USER_GUIDE.md](USER_GUIDE.md), Tank level for the controller). The controller calculates it from the tank distance sensor and the full and empty distances of the room. It is `unknown` with no sensor mapped, with no reading, or with a stuck sensor. Attributes `stuck`, `litres_per_pct` (learned, null until the level has fallen 5% one time with shots counted), `low` (the low float), `below_minimum`, `over_full` and `minimum_pct` (8) ([USER_GUIDE.md](USER_GUIDE.md), Reservoir minimum). Not published for a room with no tank level mapped. |

The controller also publishes `sensor.f2_control_vitals`: the time of its last vitals report, with the report in the `vitals` attribute.

### Per-zone (`sensor.crop_steering_zone_N_*`)
| Entity | Unit | What it reports |
|---|---|---|
| `vwc_zone_N` | % | Shows the VWC of the zone, made from its probes by the method of the zone (`zone_N_vwc` on older installs). The controller steers the zone on this reading. When a probe stops, the reading does not step. Attributes: `probes` (the number mapped), `used`, `excluded` (each probe left out, with `no reading`, `out of range` or `not reporting`) and `spread` (the highest probe less the lowest probe used). |
| `ec_zone_N` | mS/cm | Shows the pore EC of the zone (`zone_N_ec` on older installs). The integration makes it from the probes in the same way as the zone VWC, with the same attributes. A zone with pore EC and bulk EC probes never combines the two. |
| `zone_N_phase` | - | Shows the phase of the zone, P0 to P3, as the controller keeps it. The `reason` attribute gives the reason of the last decision. |
| `zone_N_auto_setpoints` | - | Shows what the Auto setpoints learner does for the zone: `off`, `learning`, `tracking` or `frozen` (with `frozen_reason`). Attributes: `learned_peak`, `gain`, `day_rate`, `night_rate`, `p1_outcome` (`pending` / `reached` / `short` / `plateau` / `suspect`), `hold_days`, `frozen_reason`, `last_change`, `working_peak_adjust`, `managed` (each number that an automatic writer can change on this zone) and `managed_by` (the writer of each). The attributes `jev` (always `disabled`), `jev_last` and `jev_changed_today` (always empty) stay for one release. |
| `zone_N_status` / `_status_app` | - | Show the label that the controller gives the zone, with the reason in the `reason` attribute. The controller publishes `zone_N_status_app`, and `zone_N_status` copies it. `Drying back`, `Ramping`, `Optimal` and `Overnight dryback` show a zone that waits in P0, P1, P2 or P3. `Flushing`, `Refilling`, `Topping up` and `Emergency` show a shot. `Blocked: <why>` and `Blocked — EC/cap` show what holds the zone. `Probe dead — copying` shows a zone with no usable probe. `Room off` shows that the room is off. `Controller not reporting` shows no report from the controller for 10 min. |
| `zone_N_waiting_for_app` | - | Published by the controller each minute: what would move the zone next, by the engine's own rules and numbers (`crop_steering_engine.waiting_for`), shown as the zone's "Next:" on the dashboard. State: the phase the list is for (`none`, with an empty list, while the zone has no usable probe or the room is off). Attribute `conditions`, one item per rule: `rule` (`p0_timeout` / `p0_bypass` / `p0_dryback`, `p1_ramp` / `p1_done` / `p1_max_shots`, `p2_topup` / `p2_dilute` / `lights_off`, `p3_emergency` / `p3_hold` / `lights_on`), `shot` (it fires a shot), `to` (the phase it moves to), then a reading test (`metric` `vwc` or `ec`, `op`, `value`, `now`) or a wait (`in_min`, minutes after `at`); `p1_done` adds `shots_left`, `ec_max`, `ec_now`; `p0_dryback` adds `dryback` (the % it waits for) and `peak` (the highest reading since lights-on it is measured from); `p2_topup` carries `in_min` too while a P2 time between shots is set; `p3_hold` (only while the zone's P3 Dryback Hold is on) adds `dryback`. Attribute `at`: when it was worked out. It lists the engine's routine rules, not a forecast: a held plan leaves out the shots it stops; the EC flushes, the watchdog, the daily minimum and P2's early move to P3 in the last three hours before lights-off are not listed; a gate or switch that holds watering is in `zone_N_status`. Attribute `gates`: every pre-shot gate in the controller's order, each `key`, `label`, `state` (`pass` or `hold`) and `detail`, read without side effects; its first `hold` is what holds the zone's next shot. |
| `zone_N_safety_status` | - | Shows the safety label of the zone from its VWC and its pore EC: `safe`, `approaching_saturation`, `over_saturated`, `approaching_ec_limit`, `ec_limit_exceeded` or `ec_unknown`. |
| `zone_N_daily_water_usage` / `_daily_water_app` | L | Show the litres that the zone got in this grow-day. The value returns to 0 at lights-on, not at midnight. |
| `zone_N_weekly_water_usage` / `_weekly_water_app` | L | Show the litres that the zone got in the last seven grow-days. The `coverage` and `history_complete` attributes show if the history is complete. |
| `zone_N_irrigation_count_today` / `_irrigation_count_app` | - | Show the number of shots that the zone got in this grow-day. The count returns to 0 at lights-on. |
| `zone_N_last_irrigation` / `_last_irrigation_app` | - | Show the time of the last shot of the zone. |
| `zone_N_vmax_detected` | % | Shows the highest VWC that the zone reached in its ramp (P1), with a `confidence` attribute. It is advice only, and no setting changes from it. |
| `runoff_estimate_app` (room) | % | With the runoff estimator on: the runoff % of the water fed, room-wide, or `learning` / `unresolvable` / `no_sump` with `why` (unresolvable while CS-311 or CS-310 is active). Attributes: `band_pct`, `r2`, `drain_delay_min`, `litres_per_run` and its source, `litres_per_hour` per AC and dehumidifier, `baseline_l_per_h`, today's `sump_today_l`, `runoff_today_l` and `transpiration_today_l`, today's 6-hour `blocks`, and the last grow-days with their `closure_error_pct`. |
| `zone_N_dryback_app` | % | The zone's live dryback: (peak - VWC) / peak x 100, the relative % the controller steers on. Attributes: `peak_vwc`, `dryback_points` (the same drop in VWC points), `rate_points_per_h` (VWC points lost per hour; `null`, not 0.0, while the controller has no rate: fewer than three readings since the last shot; it is worked out from those readings only), `drying_back` (losing water with no shot in the last 20 min). The peak is the highest VWC since the last lights-on. `unknown` without a usable probe. |
| `zone_N_water_response_app` | points/h per kPa | With Water vs VPD on: how much faster the zone dries in quiet lights-on windows per kPa more VPD, fitted over its last 14 grow-days. `unknown` until 7 grow-days with a VPD spread of 0.2 kPa. Attributes: `r`, `n_days`, `days` (the records), `words`. An observation, not a cause. |
| `zone_N_shot_log_app` | - | With the shot check on: the zone's last 8 shots (attribute `shots`, newest first, units in the keys) and the newest verdict as the state. Kept in memory: after a restart it fills again with the next shots. |
| `prediction_zone_N_next_irrigation_hours` | h | Shows the hours until the next maintenance shot of the zone, from the VWC, the re-water point and the dryback rate. The controller publishes it every pass: `0` when a shot is due now, `unknown` with a `reason` attribute whenever it has no current estimate (not in P2, no dryback rate yet, none since the last shot, VWC not falling), so an old estimate never stands. Read it as a number only when the state is numeric. |

> Note: a few `…_app` sensors are engine-published mirrors of the integration sensors;
> prefer the engine `…_app` value when the two differ.

---

## 6. Hardware (your own switches/sensors: mapped in Rooms and setup, not created here)

The pump, mainline solenoid, per-zone valve switches, and the raw VWC/EC + source-water
sensors are **your** existing HA entities. Map them in the Crop Steering sidebar under
**Rooms and setup**: the controller drives what the room's setup maps, and with nothing mapped
it holds every zone and says so. (The controller also reads a `hardware` map from its options
file, for tests and hand-built development setups only: the app's Configuration tab doesn't
offer it, and Supervisor rejects it as an unknown option.)

The pump, main line and each zone valve can be a `switch` or an `input_boolean` (switched with
`turn_on` / `turn_off`, read back `on` / `off`) or a `valve` (`valve.open_valve` /
`valve.close_valve`, read back `open` / `closed`). Every open, close and read-back goes through one
table in the controller (`ACTUATORS`), so a valve that does not read `closed` after a shot latches
the same hardware hold (CS-301) a switch that does not read `off` does. Setup refuses any other
domain; one mapped by hand holds its zone with CS-313 and is never sent a command.
