## How this controller works (generated from the code)

### 1. The phase machine, per zone, each 60 s pass
- Phases: P0 -> P1 -> P2 -> P3. A grow-day is one photoperiod: lights-on (number lights_on_hour) starts it, lights-off (number
  lights_off_hour) ends it. The daily water and shot counters reset at the P3 -> P0 change at lights-on.
- Lights-off forces any zone not in P3 to P3. P3 -> P0 at lights-on (or on a new grow-day when a light edge was
  missed); a zone in P1 or P2 on a new grow-day also restarts at P0 with its own budget.
- P0 -> P1 when the first of these holds: moisture at or under the re-water point (p2_vwc_threshold); the dryback
  reaches its target (vegetative_dryback_target or generative_dryback_target by the zone's steering mode, plus
  p0_additional_dryback); P0 has lasted p0_maximum_wait_time minutes. Dryback is relative to the peak:
  (peak - VWC) / peak x 100.
- P1 (the ramp): shots of p1_initial_shot_size, growing by p1_shot_size_increment, every p1_time_between_shots
  minutes, until moisture reaches min(p1_target_vwc, field_capacity); then one more shot, and P1 hands over to P2
  when a shot no longer raises the zone's highest reading by p1_rise_pts (the rise rule), after
  p1_maximum_extra_shots extra shots, at p1_maximum_shots, or at the target with the daily budget spent. P1 has no
  time exit: a gated zone waits in P1 and resumes.
- P2 (maintenance): a shot of p2_shot_size when moisture falls under the re-water point (with the EC steer's offset
  baked in, clamped between rescue + 3 and the ramp ceiling - 1), at most every p2_time_between_shots minutes. P2 ->
  P3 early only when a dryback started now would end by lights-on (predictive P3), otherwise at lights-off.
- P3 (night): only a rescue shot of p3_emergency_shot_size when moisture falls under the rescue floor
  (p3_emergency_vwc_threshold), at most every p3_time_between_shots minutes.
- A probe that stops reading (stale, flat, out of range) makes the zone blind after 15 minutes: it copies a
  healthy sibling's shots or, with none, gets a timed shot every blind_fallback_min minutes inside its daily cap. When
  the probe reads again the zone resumes from its own reading in the phase it is in.

### 2. Shot sizing
- Shot litres = substrate litres per plant x plants x shot % / 100. Flow L/s = plants x drippers per plant x L/h per
  dripper / 3600. Duration = litres / flow, then the room's safety cap on a shot's length. Positive flow is required:
  no hidden clamp.
- Daily caps: max_daily_volume per zone (rescue and the safety shots are exempt: flush_high_ec, min_daily, p0_ec_flush, p1_extra, p1_flush, p1_ramp, p2_dilute, p2_rescue, p2_timed, p2_topup, p3_emergency, p3_hold, watchdog); the minimum-daily floor
  and the lights-on watchdog (watchdog_hours) still fire.

### 3. Gates and safety layers, in order, each fail-closed
1. The room's kill switch (engine switch) and any hold entity: off or unreadable, no valve opens.
2. The source-water gate: feed pH and EC inside their bands, a dead probe holds the shot.
3. Hardware sequencing: pump prime (pump_prime_time), main line (main_line_lead_time), zone valve, then the reverse;
   valve close is read back, and a failed read-back stops the pump and aborts the shot.
4. The max-run latch: shots that keep running into the room's longest shot latch the zone (CS-312).
5. The duplicate-controller lease: another controller's heartbeat holds the room for 180 s.
6. The EC step rule: in P2 the EC steer moves the re-water offset by steps, at most once per ec_min_interval minutes.
7. Plan adherence: an armed grow plan owns the room's targets; drift from it raises CS-713.

### 4. The settings: each zone's own number for the setting, else the room's, else the controller's built-in value shown here

- drippers_per_plant: 1
- ec_flush_target: 0
- ec_min_interval: 10
- ec_target_gen_p0: 4
- ec_target_gen_p1: 5
- ec_target_gen_p2: 6
- ec_target_veg_p0: 4
- ec_target_veg_p1: 5
- ec_target_veg_p2: 6
- field_capacity: 70 (range 40-100)
- generative_dryback_target: 20
- main_line_lead_time: 1
- max_daily_volume: 150
- maximum_ec: 9
- p0_additional_dryback: 0
- p0_maximum_wait_time: 45 (range 5-240)
- p0_minimum_wait_time: 0
- p1_initial_shot_size: 2 (range 0.5-15)
- p1_maximum_extra_shots: 3
- p1_maximum_shots: 12 (range 1-40)
- p1_minimum_shots: 0
- p1_rise_pts: 0.5
- p1_shot_size_increment: 0.5 (range 0-5)
- p1_target_vwc: 60 (range 20-100)
- p1_time_between_shots: 15 (range 1-120)
- p2_ec_high_threshold: 1.2
- p2_end_hours_before_off: 0
- p2_shot_size: 5 (range 0.5-20)
- p2_time_between_shots: 0
- p2_timed_first_hours: 0
- p2_timed_interval_min: 60
- p2_timed_shot_size: 0
- p2_vwc_threshold: 45 (range 10-100)
- p3_emergency_shot_size: 2
- p3_emergency_vwc_threshold: 40 (range 10-65)
- p3_time_between_shots: 10
- plant_count: 0
- pump_prime_time: 2
- vegetative_dryback_target: 20
- watchdog_hours: 3

### 5. What the AI assistant may write, and what moves downstream

- power nudge_setpoints:
  - p2_shot_size (P2): range 0.5-20 (and the entity's own min/max); a maintenance shot, % of the substrate; bigger shots drain more and dilute pore EC, smaller let it stack; under 3 % shots machine-gun
  - p2_vwc_threshold (P0, P2): range 10-100 (and the entity's own min/max); a maintenance shot fires under it (plus the EC steer's offset); raising it waters more often with a shallower dryback, lowering it fewer shots and a deeper dryback; P0 jumps to P1 when moisture falls to it
- power set_targets_from_achievable:
  - field_capacity (P1): range 40-100 (and the entity's own min/max); caps the ramp's ceiling (min(P1 target, field capacity)); the saturation labels read against it; under Auto setpoints it follows the zone's highest readings unless the AI owns it
  - p1_target_vwc (P1, P2): range 20-100 (and the entity's own min/max); the ramp aims here (with field capacity, the lower of the two); raising it lengthens the ramp and adds ramp shots; the P2 band sits between the re-water point and it; tomorrow's P0 dryback is measured from the peak it produces
  - p2_vwc_threshold (P0, P2): range 10-100 (and the entity's own min/max); a maintenance shot fires under it (plus the EC steer's offset); raising it waters more often with a shallower dryback, lowering it fewer shots and a deeper dryback; P0 jumps to P1 when moisture falls to it
  - p3_emergency_vwc_threshold (P3): range 10-65 (and the entity's own min/max); the rescue floor: a rescue shot fires under it at night; it sits at least 3 points under the re-water point (Home Assistant refuses an order that breaks it)
  - vegetative_dryback_target (P0, P3): the relative dryback (peak - VWC) / peak x 100 P0 waits for when the zone is steered vegetative; larger means a later first shot
  - generative_dryback_target (P0, P3): the same for a zone steered generative
- power tune_shot_sizes:
  - p1_initial_shot_size (P1): range 0.5-15 (and the entity's own min/max); the first ramp shot, % of the substrate; each next ramp shot adds p1_shot_size_increment; bigger reaches the peak in fewer shots but risks runoff
  - p2_shot_size (P2): range 0.5-20 (and the entity's own min/max); a maintenance shot, % of the substrate; bigger shots drain more and dilute pore EC, smaller let it stack; under 3 % shots machine-gun

### 6. The AI assistant's powers (one switch per power in each room, ai_power_<key>)

- advance_phase (default on): start the morning ramp or the night dryback early (dawn, dusk)
- ramp_control (default on): end the morning ramp (ramp)
- set_probe_aside (default on): set a probe aside (probe)
- ec_mode (default on): choose the EC steer's mode (salt)
- nudge_setpoints (default on): move the maintenance shot size or re-water point one notch (setpoints)
- plan_catch_up (default on): apply today's plan day while a stale probe holds it (plan)
- set_targets_from_achievable (default off): set a zone's field capacity, peak target, re-water point, rescue floor and dryback target itself (targets)
- tune_shot_sizes (default off): set a zone's ramp and maintenance shot sizes itself (shotsize)
- Off: the judge still asks and its answer is advice in the decision log. On: it acts through the envelope; set_targets_from_achievable and tune_shot_sizes write the values set as given, clamped only to each setting's range. Dry run (brain_dry_run): every acting answer is journalled 'would act', nothing is written.

### 7. Error codes: what each means, and what the controller does

- CS-101 Flat moisture reading: For more than 20 min, the moisture (VWC) reading of the zone does not change. Does: While the kill switch is on, the zone continues without its probe.
- CS-102 Probe with no reading: The moisture (VWC) entity of the zone reads "unavailable" or "unknown", is not a number, or is not in Home Assistant. Does: For the first 15 min, the zone waits and the controller gives no shot and no alert.
- CS-103 Moisture reading out of range: The moisture (VWC) entity of the zone gives a value below 0% or above 100%. Does: The zone continues without its probe, the same as for a probe that does not report (CS-102).
- CS-104 EC reading not available: The zone has no usable EC reading. Does: The controller steers the zone on VWC only.
- CS-201 Setup change on hold: The controller has a new setup for the room, or it loads the setup again after a restart. Does: The room gets no shots until the controller applies the setup.
- CS-202 Pump or main-line mismatch: The setup of the room has a pump or a main-line valve, but no entity is mapped to it. Does: The room gets no shots until the setup and the mapped entities agree.
- CS-203 Invalid maximum shot length: The maximum shot length (Maximum shot duration) of the room is not a number, or it is less than 5 s. Does: The room gets no shots until the value is correct.
- CS-204 Invalid shot size inputs: The controller calculates each shot from the substrate volume, the plant count, the drippers for each plant and the dripper flow. Does: The zone gets no shots.
- CS-205 Daily water limit reached: The zone has received its daily water limit (max daily volume) since lights-on. Does: Maintenance shots and EC correction shots stop until the next lights-on.
- CS-206 EC too high, zone held: The EC of the zone is above its maximum EC setting. Does: The controller holds the zone and no shot runs, the rescue shot and the watchdog shot included.
- CS-207 Dry zone, all shots blocked: The VWC of the zone is below its re-water point. Does: The zone gets no water until the block clears.
- CS-208 Retired switch is off: System Enabled and Auto Irrigation Enabled are retired. Does: The room gets no shots.
- CS-209 No shots for some hours: The room is on, its lights are on, and one or more zones are in P1 or P2. Does: The alert does not change the water.
- CS-210 Hold entity missing: The hold entities option of the controller app names one or more entities that Home Assistant does not have. Does: No room gets shots while a hold entity is missing, the same as while a hold is on.
- CS-301 Hardware fault latch: A pump or a valve did not read back off after the controller closed it. Does: No shot starts on that hardware, in each room that shares it, until the hold clears.
- CS-302 Pump command error: Home Assistant returned an error when the controller tried to start the pump. Does: The controller cancels the shot and does not count it.
- CS-303 Main-line valve command error: Home Assistant returned an error when the controller tried to start the main-line valve. Does: The controller cancels the shot and does not count it.
- CS-304 Zone valve command error: Home Assistant returned an error when the controller tried to start the zone valve. Does: The controller cancels the shot and does not count it.
- CS-305 Early shot stop: A shot stopped before its end, because a person or an automation changed a switch. Does: The controller counts the water that the zone got before the stop.
- CS-306 Shot cut to maximum length: The calculated shot was longer than the maximum shot length of the room. Does: Water continues, but each cut shot gives less water than the controller calculated.
- CS-307 Shot stopped by external change: During a shot, a hold of the room started (a dose, a tank fill or a flush). Does: The controller counts only the seconds that the valve was open.
- CS-308 Interrupted shot, hardware on: A shot did not end correctly. Does: The controller latches a hardware hold (CS-301) and tries again on each loop.
- CS-309 Interrupted shot, state unknown: A shot did not end, and the controller cannot read a device that the shot opened. Does: No new shot starts in the room until the controller settles the interrupted shot.
- CS-310 Table drain blocked: The VWC of a zone increased by 3 points or more in 1 h with no water from its valve. Does: The controller holds the minimum daily volume and the EC flushes of the zone.
- CS-311 No sump pump run: The power reading of the sump pump (sump_power_sensor) shows no run for 3 h by default (sump_silent_hours). Does: The alert does not change the water.
- CS-312 Repeated maximum-length shots: The last 3 shots of a zone each needed more time than the maximum shot length of the room. Does: If the max-run latch switch of the room is on, the zone gets no more shots, rescue shots included, until you fix the Repairs card.
- CS-313 Device type not supported: A zone valve, pump or main-line valve has a device type that the controller cannot open or close. Does: The zone gets no shots, and the controller sends no command to the device.
- CS-401 Setting outside controller range: The entity accepts a wider range than the controller uses, and the value is outside the range of the controller. Does: Water continues.
- CS-402 Missing settings: The controller cannot read some settings by their entity IDs for 3 loops. Does: All shots wait for 3 loops.
- CS-403 Lights hours from the integration: The controller now reads the lights-on and lights-off hours from the integration, not from its own options. Does: Water continues on the hours of the integration.
- CS-404 Automatic setpoints paused: Automatic setpoints change the targets of a zone from the ramp of each morning. Does: Water continues on the current targets.
- CS-405 Time zone mismatch: The clock of the controller uses a different time zone from Home Assistant. Does: Water continues, but the full grow-day moves by the time difference.
- CS-501 Low water compared to room: Today the zone got less than 40% of the median daily water of the zones of the room. Does: Water continues as usual.
- CS-502 Too few probes in agreement: The zone steers its VWC or EC on its lowest or highest probe. Does: Water continues on the median of the remaining probes.
- CS-503 Probe unit not accepted: The moisture probe of the zone uses a unit that is not a percentage, and its value is outside 0 to 100. Does: The same as for CS-102.
- CS-504 Zone EC from bulk EC: The zone has pore EC probes and bulk EC probes, and the controller never mixes the two. Does: Water continues.
- CS-505 Primary probe offline: The primary probe of the zone for VWC or EC gives no reading. Does: Water continues on the other probes of the zone.
- CS-601 Kill switch helper missing: The integration cannot find the kill switch that the controller uses for this room. Does: The room gets no shots while the kill switch is missing.
- CS-602 No controller heartbeat: The controller sends a heartbeat each minute. Does: No automatic shots occur while the controller is stopped.
- CS-603 Zone without a probe: No moisture probe is mapped to the zone, so the controller cannot steer it on VWC. Does: While the kill switch is on, the zone still gets shots.
- CS-604 Combined moisture entity unavailable: The combined moisture entity of the zone reads unavailable, because the probe behind it does not report. Does: The same as for CS-102.
- CS-605 Settings at unexpected entity IDs: The controller finds each setting by its exact entity ID. Does: Water continues on the built-in values, which can be wrong for the room.
- CS-606 Grow plan holds steering: The grow plan of the room holds the steering of its zones. Does: Those zones get only the rescue shot, the watchdog shot and the minimum daily volume.
- CS-607 Grow plan day not applied: At lights-on, the grow plan could not apply the new day. Does: Water continues on the last valid targets.
- CS-608 Stock tanks low: One or more stock tanks of the room are at or below their low mark. Does: Water continues.
- CS-609 Second controller for room: Each controller writes its ID in the room heartbeat each minute. Does: This controller does not water or dose the room, and does not change its settings, until no other controller writes for 3 min in sequence.
- CS-610 Engine Enabled not kill switch: Each room has one kill switch, which must be on before the room gets water. Does: Water continues under the kill switch that the card names.
- CS-611 Settings above zone limit: The limits of the daily water and the maximum shot length come from the size of each zone: its plants, substrate volume and dripper flow. Does: Water continues as before.
- CS-701 No water at the zone: The shot judge of the AI assistant found no sign of water at the zone for 2 shots in sequence. Does: Water continues as usual.
- CS-702 Unusual water for each plant: Today the water for each plant in this zone is less than 70% or more than 140% of the other zones of the room. Does: Water continues as usual.
- CS-703 Overnight probe fault suspected: Overnight, the VWC of the zone falls toward the rescue floor. Does: Water continues.
- CS-704 Probe set aside by AI: The AI assistant judged twice in sequence that the moisture probe does not follow the substrate, and the check of the controller agreed. Does: The zone continues without the probe, as for a probe that does not report.
- CS-705 Zone outside stage arc: Each day, the stage judge of the AI assistant compares the zone with the stage arc for this flower week. Does: Water continues as usual.
- CS-706 AI call budget almost used: The AI assistant has used the warning share of its daily call budget, 80% by default, for all rooms. Does: Water continues as usual.
- CS-707 Stricter gate for a judge: Some calls in sequence of one judge for this zone, 3 by default, were wrong when the controller checked them. Does: Water continues.
- CS-708 AI budget used: The AI assistant has spent its AI budget (anthropic_daily_budget_usd, US$1.00 by default) for this grow-day. Does: Water continues.
- CS-709 AI assistant not available: The AI service refused the API key, does not know the selected model, or refused some requests in sequence. Does: Water continues on the engine rules.
- CS-710 Possible water bypass: Shots on this zone make the probe increase and then fall back quickly. Does: Water continues as usual.
- CS-711 AI feed change proposal: In a room with a feed EC sensor, the AI assistant examines the feed once each grow-day, 1 h after lights-on. Does: The water and the dose do not change.
- CS-712 First AI route removed: The options of the controller still name the first AI route of the AI assistant, or keep its Cloudflare or TypeSafe settings. Does: The water does not change.
- CS-713 Room differs from grow plan: The controller compared the grow plan with what the room does, and found a difference. Does: Water continues on the targets in force, and the card only reports.
- CS-801 Dosing pump overrun: A dose ran past its deadline. Does: The batch tank can contain more nutrient than requested.
- CS-802 Dose not confirmed: The controller started a dose but could not confirm it. Does: For a dose that is not confirmed, the controller does not know the volume, and does not subtract it from the stock tank.
- CS-803 Dose interrupted by restart: The controller stopped during a dose or a batch, or it could not read its dose record (dosing_state.json) at start. Does: The held rooms get no shots until all the dosing hardware reads off.
- CS-804 Batch tank fill failure: A batch could not fill the tank. Does: The rooms that the batch held get water again.
- CS-805 Mix pump start failure: A batch opened the mix valves and started the mix pump. Does: The rooms that the batch held get water again when its hardware reads off.
- CS-806 Stopped batch or dose: A batch stopped before its end, or a dose needs a check. Does: The controller sets all the dosing pumps, the fill valve, the mix pump and the mix valves to off.
- CS-807 Stock draw not recorded: A dose took nutrient from a stock tank, but Home Assistant did not record the draw. Does: Water continues as usual.
- CS-808 Batch mix outside band: After the mix of a batch stopped, the controller waited 5 min and read the tank with the feed EC and feed pH probes. Does: The mix check never holds the water.
- CS-901 Tank at minimum level: The tank level of this room is 8% or less, or its low float switch reads low. Does: The controller holds each zone of the room, so the pump does not run dry.
- CS-902 Tank level not readable: The tank level of this room gives no usable reading, or the distance sensor seems stuck. Does: The controller holds each zone of the room until the level reads again, or until a stuck sensor moves.
- CS-903 Refill needed before next shots: One more set of shots, the last shot of each zone, takes the tank to its 8% minimum or below. Does: Water continues.
- CS-904 Tank above full mark: The tank level reads 102% or more of its full distance. Does: Water continues.
- CS-906 Batch tank low: The batch tank of the room read at or below its refill reminder level (remind_pct) 3 times, 1 min apart. Does: Water continues as usual.
