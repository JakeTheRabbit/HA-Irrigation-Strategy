## Symptom -> lever (ACTS = an answer you may give, via its decision; ADVISES = say it, a person decides)
Symptom entries carry no evidence class of their own: they are product-rule, drawn from the decision rules and engine facts they cite.
- Settled pore EC running high, sustained. First rule out: Feed EC near or above pore EC (cannot dilute), or the zone not draining. Levers: ACTS p2_shot_size up (via setpoints: bigger_shots); ACTS p2_threshold up (via setpoints: sooner_rewater); ACTS EC steer steer (via salt: salts_accumulating, salt_front_passing); ADVISES ec_target_p2 down; ADVISES feed EC down. Never: Raise max_ec to stop a flush.
- Pore EC low or washing out, generative push wanted. First rule out: Over-flushing: check runoff share and maintenance shot size. Levers: ACTS p2_shot_size down (via setpoints: smaller_shots); ACTS p2_threshold down (via setpoints: later_rewater); ADVISES stacking_on on. Never: Raise dryback_target to stack EC: it does not deepen the overnight dryback (DRY-02).
- Overnight dryback too small for the stage (too vegetative). First rule out: Compare the observed overnight dryback (code's figure) with the arc band; a late top-up or a zone held wet by P2 until lights-off. P0's timeout is not this symptom. Levers: ACTS P2 -> P3 (day's last shot) earlier (via dusk: enter_p3_now); ACTS p2_threshold down (via setpoints: later_rewater). Never: Raise dryback_target to deepen the overnight dryback: it does not set it, and a larger value can switch the predictive P3 off (DRY-02).
- Overnight dryback too large, plants stressed or wilting. First rule out: Missed shot or demand change (light, VPD, CO2, airflow). Levers: ADVISES P2 -> P3 (day's last shot) later; ACTS p2_threshold up (via setpoints: sooner_rewater); ADVISES p3_emergency_floor up. Never: Lower dryback_target to shrink the overnight dryback: it does not set it (DRY-02).
- P1 ends only at maximum shots (never reads full). First rule out: Target above the achievable peak (compare detected Vmax), blocked dripper, wrong flow or substrate config. With Auto Setpoints on the target is the zone's highest reading of the grow-day before, so a ramp that keeps stopping at maximum shots fell short of yesterday's peak: delivery or probe first. Levers: ACTS P1 -> P2 earlier (via ramp: slab_full); ADVISES p1_target down.
- Zone drying fast in P2, frequent top-ups. First rule out: Shot-size units misconfigured (substrate per plant x plant count vs zone flow): check the pump on-seconds against the expected duration. Levers: ACTS p2_shot_size up (via setpoints: bigger_shots); ACTS p2_threshold up (via setpoints: sooner_rewater).
- Over-watered: the zone stays near its peak through P2, its observed overnight dryback runs under the arc's band, runoff runs above the stage's band, or (Auto Setpoints off) VWC sits over the grower's field capacity for long spells. First rule out: Dripper stuck open or a valve not closing; with Auto Setpoints off, field_capacity set above the true full mark. With it on, field capacity is the zone's own highest reading, so reading at it, over_saturated or approaching_saturation is the zone at its own peak, not over-watering (CT-14). Levers: ACTS p2_threshold down (via setpoints: later_rewater); ACTS p2_shot_size down (via setpoints: smaller_shots); ADVISES p1_target down. Never: Notch drier on an over_saturated or approaching_saturation label alone while Auto Setpoints is on: each new high reads that way by construction (CT-14).
- Cross-zone under-drinker. First rule out: Probe reading low but alive, valve or dripper partly blocked, delivery fault. Lead with investigate. Levers: ADVISES investigate; ADVISES p2_shot_size up.
- Daily budget reached. First rule out: Is it runoff waste? Levers: ACTS p2_shot_size down (via setpoints: smaller_shots); ACTS p2_threshold down (via setpoints: later_rewater); ADVISES max_daily_volume up.
- Runoff high while VWC barely rises. First rule out: Channeling, a dry core or poor block contact. Levers: ADVISES investigate.
- Pore EC rising right after a flush. First rule out: Feed dilutive and the zone draining? Levers: ACTS p2_shot_size up (via setpoints: bigger_shots); ACTS EC steer steer (via salt: salt_front_passing).
- P0 ends on its timeout every morning. First rule out: dryback_target larger than the drop a morning gives (the integration's defaults are); that is the setting, not a fault. Levers: ACTS P0 -> P1 earlier (via dawn: start_ramp_now); ADVISES dryback_target down; ADVISES p0_max_wait_min.
- Probe stuck high or not answering the shots. First rule out: Are shots firing and landing? Do the sibling zones rise? Levers: ACTS probe trust set aside (via probe: no); ADVISES investigate. Never: Call a probe sound because no other reading disagrees: on a default install, past the morning ramp, nothing else waters a zone whose probe keeps reading high (PRB-08).
- EC steer chasing a target it cannot reach, or a jumpy EC reading. First rule out: Has pore EC ever been near the target on this feed? Do the EC readings move with the moisture? Levers: ACTS EC steer decay (via salt: target_unreachable, probe_suspect); ADVISES ec_target_p2.

## Engine parameter -> setting
Engine parameter (ZoneParams) -> the integration setting it is read from. Setting keys are product keys, not site entity ids. Mode-split settings resolve by the zone's steering mode (vegetative or generative). The brain moves only p2_shot_size and the base p2_vwc_threshold, one notch a grow-day (ACT-07). With the room's Auto Setpoints switch on (opt-in, and always on when a notch is asked) code also writes field_capacity and p1_target_vwc from the zone's own highest readings and shifts p2_vwc_threshold and p3_emergency_vwc_threshold with field capacity (CT-12, CT-13). Every other row is the grower's setting, and the brain's view of any row it does not notch is advice.
- p1_target: p1_target_vwc (with Auto Setpoints on, set by code to the zone's highest reading of the grow-day before)
- p2_threshold: p2_vwc_threshold (with Auto Setpoints on, shifted with field capacity), plus the controller's EC offset whenever pore EC is known (the offset moves only while EC stacking is on, and keeps applying after stacking is switched off until the lights-on reset) (clamped to rescue floor + 3 .. min(p1_target, field_capacity) - 1)
- p2_shot_size: p2_shot_size (% of substrate)
- p1_initial: p1_initial_shot_size (% of substrate)
- p1_incr: p1_shot_size_increment (% per shot)
- p1_max_shots: p1_maximum_shots
- p1_min_shots: p1_minimum_shots
- p1_time_between_min: p1_time_between_shots (min)
- dryback_target: vegetative_dryback_target | generative_dryback_target (relative %; compared with P0's drop since lights-on and in the predictive P3 test, never with the overnight dryback; the integration's separate p0_dryback_drop_percent is not read by the controller)
- p0_max_wait_min: p0_maximum_wait_time (min)
- ec_target_p0/p1/p2: ec_target_veg_p0..p2 | ec_target_gen_p0..p2
- p3_emergency_floor: p3_emergency_vwc_threshold (the rescue floor; with Auto Setpoints on, shifted with field capacity, down as well as up, and lowered to stay 3 points under the threshold)
- p3_emergency_shot: p3_emergency_shot_size
- max_daily_volume: max_daily_volume (L per zone per grow-day)
- min_daily_volume: no integration setting: a per-zone helper the install creates by hand (min_daily_ml_per_plant) x the zone's plant_count / 1000. Absent on a fresh install, so the floor is 0 (off); the controller also sets it to 0 for a zone whose table is backing up
- field_capacity: field_capacity (with Auto Setpoints on, set by code to the zone's highest reading of this grow-day or the one before)
- max_ec: maximum_ec
- stacking_on: ec_stacking_enabled (room switch)
- watchdog_hours: watchdog_hours
- drown_ceiling: an optional per-zone number min_floor_drown_ceiling the install creates by hand (the integration creates none); default 90
- p2_min_interval_min: fixed 10 min (no setting)
- min_floor_finish_h: fixed 3 h (no setting)
