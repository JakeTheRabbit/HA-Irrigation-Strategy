/**
 * The help behind each "About" button of the dashboard, in Simplified Technical English
 * (ASD-STE100): what an item is, the impact of a change, guidance, then any warning (a risk to
 * a person) or caution (a risk to the plants or the equipment). Each sentence says only what the
 * controller code does: change a sentence only together with that code.
 */

export interface SteCopy {
  tooltip: string;
  impact?: string;
  guidance?: string;
  warning?: string;
  caution?: string;
}

/** The help of each irrigation setting, by its parameter key. */
export const SETTING_COPY: Record<string, SteCopy> = {
  "ai_no_touch": {
    "guidance": "The default is Off, also on an upgraded room. Select a period before you take samples or visit the room. Select Off to end the pause early.",
    "impact": "Off: the AI assistant works as usual. 1 h: the pause ends 1 h after the choice. Until lights-on: the pause ends at the next lights-on. 24 h: the pause ends 24 h after the choice. At the end, the controller sets the select back to Off. The shots continue by the rules of the controller during the pause.",
    "tooltip": "Starts a no-touch period for the room, for example while a person takes samples. During the period, the AI assistant asks nothing and changes nothing in the room."
  },
  "ai_power_advance_phase": {
    "tooltip": "Starts the morning ramp or the night dryback early. Only forward, only near the end of the phase, never near the rescue floor."
  },
  "ai_power_ec_mode": {
    "tooltip": "Selects steer, hold or decay for the EC steer in maintenance. Only inside the EC limits of the controller."
  },
  "ai_power_nudge_setpoints": {
    "tooltip": "Moves the maintenance shot size or the re-water point by one 0.5 step a night, near your own value. Auto setpoints must be on."
  },
  "ai_power_plan_catch_up": {
    "tooltip": "Applies the values of today's plan day when a stale probe holds the plan. Once a day, only the values of the plan."
  },
  "ai_power_ramp_control": {
    "tooltip": "Ends the morning ramp when the slab is full. Only after the minimum ramp shots and near the peak target."
  },
  "ai_power_set_probe_aside": {
    "tooltip": "Sets aside a probe that does not follow the substrate. The zone then waters on its timer. Two firm answers and a code check are necessary."
  },
  "ai_power_set_targets_from_achievable": {
    "tooltip": "Sets the peak target, field capacity, re-water point, rescue floor and dryback target of each zone. When on, the AI assistant sets these targets itself. No limits apply other than each setting's own range."
  },
  "ai_power_tune_shot_sizes": {
    "tooltip": "Sets the ramp and maintenance shot sizes of each zone. When on, the AI assistant sets these targets itself. No limits apply other than each setting's own range."
  },
  "auto_irrigation_enabled": {
    "guidance": "Do not set this switch to off. Use the kill switch to stop the water of the room. If alert CS-208 shows, set this switch to on. Then set the kill switch to on using Watering in the header.",
    "impact": "On: no effect on a current controller. Off: a current controller sets the kill switch of the room to off and raises alert CS-208. A controller of version 2.24.0 or older holds every shot while this switch is off or missing.",
    "tooltip": "A retired switch that the integration keeps hidden. The kill switch is the one switch that stops the water of the room."
  },
  "auto_setpoints": {
    "caution": "CAUTION: Do not set this switch to on while a probe gives wrong readings. The setpoints can then move in the wrong direction.",
    "guidance": "The default is off. Set the switch to on only when the probes of each zone read correctly. After you set it to on, examine the auto setpoints sensor of each zone each day. If that sensor shows `frozen`, read its `frozen_reason` attribute.",
    "impact": "On: the field capacity of each zone follows the highest VWC of this grow-day or the grow-day before. On: the peak target follows the highest VWC of the grow-day before, and each of the two moves 1 point or less each grow-day. On: when field capacity moves, the re-water point moves by the same number of points. Off: the controller learns and reports, but writes no setpoint. The controller never changes the rescue floor, and it writes no set of values that puts the levels out of order. While an armed grow plan controls the room, the controller writes nothing. While the setpoints judge of the AI assistant runs, it owns the maintenance shot size and the re-water point. The learner then owns the rest.",
    "tooltip": "Lets the controller change the VWC setpoints of each zone from what it learns about the zone. The controller learns and reports also when this switch is off."
  },
  "drainage": {
    "caution": "CAUTION: Do not select free_drain for a flood table. The controller then does not see a table that does not drain, and the roots can stand in water.",
    "guidance": "Select free_drain when the runoff of the room drains freely to waste. Select flood_table when the plants stand on a table that drains. After the change, examine the alerts of the room.",
    "impact": "Free drain (`free_drain`): the controller does not watch the room for a table that does not drain (CS-310). It also removes a CS-310 card that the room has. Flood table (`flood_table`): the controller watches each zone for VWC that rises with no water. When it finds a backed-up zone, it holds the EC flushes and the extra ramp shots of that zone (CS-310). Unknown (`unknown`): the controller watches the room as for a flood table. A room configured before this select reads unknown.",
    "tooltip": "Tells how the runoff leaves the room. The setup asks for it on its first page."
  },
  "dripper_flow_rate": {
    "caution": "CAUTION: Do not set a dripper flow lower than the true flow. Each shot then runs too long and can flood the substrate.",
    "guidance": "Measure the true dripper flow with a catch test, and set that value. The default is 1.2 L/h. Do the catch test again after you change the drippers or the pump. A zone has its own value only when setup gave that zone its own flow. Then the zone value overrides the room value for that zone only. A value of 0 or a value that the controller cannot read stops the shots of that zone with a CS-204 alert.",
    "impact": "Increase: The controller calculates a higher zone flow, so each shot runs for less time. Decrease: Each shot runs for more time. A value that is not the true flow changes the water that each shot really gives.",
    "tooltip": "The litres per hour that one dripper gives. The controller uses it to calculate how long each shot runs."
  },
  "drippers_per_plant": {
    "caution": "CAUTION: Do not set more drippers than the plants have. Each shot then runs too short, and the plants get too little water.",
    "guidance": "Count the drippers on one plant, and set that number. The default is 2. If the controller cannot read a value, it uses 1. A zone has its own value only when setup gave that zone its own count. Then the zone value overrides the room value for that zone only. Do a catch test after a change.",
    "impact": "Increase: The zone flow increases, so each shot runs for less time. Decrease: Each shot runs for more time. A value that is not the true number changes the water that each shot really gives.",
    "tooltip": "The number of drippers on each plant. With the dripper flow and the plant count, it gives the zone flow. The shot time is the water of the shot divided by the zone flow."
  },
  "ec_min_interval": {
    "guidance": "The default is 10 min for a new room. The controller uses values from 1 min to 120 min for this wait. The generic substrate type has an EC settle time of 45 min, and other types can differ. Examine pore EC and runoff after each correction before you decrease it. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: EC corrections come less often, and each shot drains before the next. Decrease: EC corrections can come closer together. Small shots that do not drain can then stack EC and not dilute it.",
    "tooltip": "The minimum time from the last shot before an EC correction or a daily minimum shot can start. EC corrections are flushes and dilution shots. With a settled pore EC reading, the wait is also at least the EC settle time of the substrate type."
  },
  "ec_stacking_enabled": {
    "caution": "CAUTION: Do not use EC stacking when a zone has only bulk EC probes. Bulk EC reads lower than pore EC, so the salt can build too high.",
    "guidance": "The default is off. Set it to on only for a zone with a pore EC probe and a P2 EC target above 0. Set the EC type of each probe before you use EC stacking. After you set it to on, examine the zone EC each grow-day.",
    "impact": "On: every 30 min in P2, the controller moves the re-water point of the zone by 1 point or less. On: when pore EC is below 90% of the P2 EC target, the re-water point goes down, so the zone gets fewer shots. On: when pore EC is above 110% of the target, the re-water point goes up, so the zone gets more shots. The total move is 20% of the re-water point or less, and it returns to 0 at lights-on. Off: the controller does not move the re-water point for EC, and the AI assistant does not judge the EC steer.",
    "tooltip": "Lets the controller move the re-water point of each zone in maintenance (P2) to steer the pore EC to the P2 EC target."
  },
  "ec_target_gen_p0": {
    "guidance": "The default is 4.0 mS/cm. If the controller cannot read a value, it uses 4 mS/cm. The controller uses values from 0.5 mS/cm to 9 mS/cm, and it sends a CS-401 alert for a value outside this range. The multiple comes from the substrate type of the room, and the generic type uses 2.5. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: The P0 EC flush starts at a higher pore EC, so fewer morning flushes occur. Decrease: The P0 EC flush starts at a lower pore EC. The flush counts toward the daily water limit.",
    "tooltip": "The pore EC target in P0 for a zone in generative steering mode. In P0, the controller gives an EC flush when pore EC is above a multiple of this target and the feed EC is lower."
  },
  "ec_target_gen_p1": {
    "guidance": "The default is 5.0 mS/cm. If the controller cannot read a value, it uses 5 mS/cm. The controller uses values from 0.5 mS/cm to 9 mS/cm, and it sends a CS-401 alert for a value outside this range. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: Pore EC is lower against the target, so ramp shots get smaller and EC can stack. Decrease: Ramp shots get larger, with more runoff, which dilutes pore EC.",
    "tooltip": "The pore EC target in P1 for a zone in generative steering mode. The controller changes each ramp shot from half to twice its size, by pore EC against this target."
  },
  "ec_target_gen_p2": {
    "guidance": "The default is 6.0 mS/cm. If the controller cannot read a value, it uses 6 mS/cm. The controller uses values from 0.5 mS/cm to 9 mS/cm, and it sends a CS-401 alert for a value outside this range. Dilution shots are 1.5 times the maintenance shot size and count toward the daily water limit. Examine pore EC on the day chart for two grow-days after a change. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: Maintenance shots get smaller and dilution shots start later, so pore EC can rise. Decrease: Maintenance shots get larger and dilution shots start sooner, which dilutes pore EC.",
    "tooltip": "The pore EC target in P2 for a zone in generative steering mode. It changes the size of maintenance shots, and the controller gives dilution shots above 1.2 times this target. With EC stacking on, it also moves the re-water point."
  },
  "ec_target_gen_p3": {
    "guidance": "Do not use it. The integration keeps it hidden only so that an automation or a script that uses it still loads, and Repairs names each one that does (CS-614).",
    "tooltip": "A retired pore EC target for P3 in generative steering mode. Nothing reads it, and the controller does not steer EC in P3."
  },
  "ec_target_veg_p0": {
    "guidance": "The default is 3.0 mS/cm. If the controller cannot read a value, it uses 4 mS/cm. The controller uses values from 0.5 mS/cm to 9 mS/cm, and it sends a CS-401 alert for a value outside this range. The multiple comes from the substrate type of the room, and the generic type uses 2.5. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: The P0 EC flush starts at a higher pore EC, so fewer morning flushes occur. Decrease: The P0 EC flush starts at a lower pore EC. The flush counts toward the daily water limit.",
    "tooltip": "The pore EC target in P0 for a zone in vegetative steering mode. In P0, the controller gives an EC flush when pore EC is above a multiple of this target and the feed EC is lower."
  },
  "ec_target_veg_p1": {
    "guidance": "The default is 3.0 mS/cm. If the controller cannot read a value, it uses 5 mS/cm. The controller uses values from 0.5 mS/cm to 9 mS/cm, and it sends a CS-401 alert for a value outside this range. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: Pore EC is lower against the target, so ramp shots get smaller and EC can stack. Decrease: Ramp shots get larger, with more runoff, which dilutes pore EC.",
    "tooltip": "The pore EC target in P1 for a zone in vegetative steering mode. The controller changes each ramp shot from half to twice its size, by pore EC against this target."
  },
  "ec_target_veg_p2": {
    "guidance": "The default is 3.2 mS/cm. If the controller cannot read a value, it uses 6 mS/cm. The controller uses values from 0.5 mS/cm to 9 mS/cm, and it sends a CS-401 alert for a value outside this range. Dilution shots are 1.5 times the maintenance shot size and count toward the daily water limit. Examine pore EC on the day chart for two grow-days after a change. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: Maintenance shots get smaller and dilution shots start later, so pore EC can rise. Decrease: Maintenance shots get larger and dilution shots start sooner, which dilutes pore EC.",
    "tooltip": "The pore EC target in P2 for a zone in vegetative steering mode. It changes the size of maintenance shots, and the controller gives dilution shots above 1.2 times this target. With EC stacking on, it also moves the re-water point."
  },
  "ec_target_veg_p3": {
    "guidance": "Do not use it. The integration keeps it hidden only so that an automation or a script that uses it still loads, and Repairs names each one that does (CS-614).",
    "tooltip": "A retired pore EC target for P3 in vegetative steering mode. Nothing reads it, and the controller does not steer EC in P3."
  },
  "enabled": {
    "caution": "CAUTION: Do not leave a zone with plants off. The zone gets no water, not even a rescue shot.",
    "guidance": "The default is on. Keep the zone on while plants grow in it. Set the zone to off only when it has no plants. Set the zone to on before you put plants in it.",
    "impact": "On: the controller waters the zone by its rules. Off: the controller gives the zone no shot, not even a rescue shot or a test shot. Off: a shot that runs in the zone stops within a few seconds. If the controller cannot read the switch, it holds the zone.",
    "tooltip": "The on/off switch of one zone. The dashboard calls it zone scheduling."
  },
  "engine_enabled": {
    "caution": "CAUTION: Do not keep the kill switch at off while plants grow in the room. The plants get no water, not even a rescue shot.",
    "guidance": "Set the kill switch to on after the setup of the room is complete and a test shot works. Set it to off to stop all water in the room immediately. An older default room uses the helper that its setup names, not this switch.",
    "impact": "On: the controller waters the room by its rules. Off: the controller starts no shot in the room, rescue shots and test shots included. Off: a shot that runs stops within a few seconds. The kill switch does not disconnect the electrical power.",
    "tooltip": "The kill switch of the room. The dashboard shows it as Watering in the header. The integration creates it as off.",
    "warning": "WARNING: Isolate the electrical power before you work on a pump, a valve or the wiring. The kill switch stops the controller only and does not isolate the power."
  },
  "field_capacity": {
    "guidance": "The default is 70%. Set the VWC that your probe reads when the substrate is full and drains freely. Examine the ramp on the day chart: VWC that stops a rise after more shots shows field capacity. The integration accepts a peak target above field capacity, but the ramp does not go above field capacity. The zone safety status shows a full substrate at or above this value, and a warning within 5 points of it. When Auto setpoints is on, the controller moves this value with the highest readings of the zone. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: The ramp can reach a higher peak, and the re-water point can be higher. The daily minimum water can continue to a higher VWC. Decrease: The ramp stops at a lower VWC, with less runoff, which steers generative. The controller keeps the re-water point at least 1 point below the lower of field capacity and the peak target.",
    "tooltip": "The VWC at which the substrate is full and drains freely. The ramp stops at this level or at the peak target, whichever is lower. EC flushes that can go past the daily water limit need VWC more than 2 points below it."
  },
  "generative_dryback_target": {
    "caution": "CAUTION: Do not set a dryback that ends below the wilt point of the plants. A deep dryback can stress the plants and stop growth.",
    "guidance": "The default is 45% for a new room. A new room starts with the value of its substrate type. If the controller cannot read a value, it uses 20%. The controller uses values from 2% to 60%, and it sends a CS-401 alert for a value outside this range. The value applies only to zones in generative steering mode. Keep the end of the dryback above the rescue floor, because a rescue shot stops a dryback below it. Examine the overnight dryback on the day chart for two grow-days after a change. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: In the last 3 h before lights-off, the controller can move a zone to P3 earlier, for a deeper overnight dryback. When the P0 extra dryback is 0, the first shot also comes later. Decrease: P3 starts nearer to lights-off, and the substrate stays wetter.",
    "tooltip": "The dryback for a zone in generative steering mode, as a percentage of the peak. At a peak of 60% and a target of 10%, the dryback ends at 54% VWC. The controller uses it in P0 when the P0 extra dryback is 0, and to start P3 early."
  },
  "growth_stage": {
    "guidance": "The default is Vegetative. Keep it the same as the steering mode of the zones. Use the steering mode of each zone to steer.",
    "impact": "Vegetative: a zone with no readable steering mode uses the vegetative dryback target and EC targets. Generative or Transition: such a zone uses the generative dryback target and EC targets. When the steering mode of each zone reads correctly, a change here does not change the shots.",
    "tooltip": "The growth stage of the room: Vegetative, Generative or Transition. The controller reads it only when it cannot read the steering mode of a zone."
  },
  "irrigation_ec_max": {
    "caution": "CAUTION: Do not set an EC band that the feed cannot meet. All shots in the room then wait, and the plants can dry out.",
    "guidance": "The default is 0 (off). If the feed EC sensor gives no reading for longer than the grace time, all shots wait until it reads again. Set it a small amount above the feed EC of your recipe.",
    "impact": "Increase: The controller accepts a stronger feed. Decrease: Shots wait more often for a weaker feed. A value of 0 removes the upper limit.",
    "tooltip": "The highest feed EC at which the controller starts shots. While the feed EC is above this value, all shots in the room wait. It operates only when the controller app has a feed EC sensor."
  },
  "irrigation_ec_min": {
    "caution": "CAUTION: Do not set an EC band that the feed cannot meet. All shots in the room then wait, and the plants can dry out.",
    "guidance": "The default is 0 (off). If the feed EC sensor gives no reading for longer than the grace time, all shots wait until it reads again. Set it a small amount below the feed EC of your recipe.",
    "impact": "Increase: Shots wait more often for a stronger feed. Decrease: The controller accepts a weaker feed. A value of 0 removes the lower limit.",
    "tooltip": "The lowest feed EC at which the controller starts shots. While the feed EC is below this value, all shots in the room wait. It operates only when the controller app has a feed EC sensor."
  },
  "irrigation_ph_max": {
    "caution": "CAUTION: Do not set a pH band that the feed cannot meet. All shots in the room then wait, and the plants can dry out.",
    "guidance": "The default is 6.5 for a new room. If the feed pH sensor gives no reading for longer than the grace time, all shots wait until it reads again. Examine the feed pH after each tank change.",
    "impact": "Increase: The controller accepts feed with a higher pH. Decrease: Shots wait more often for the feed pH to fall. A value of 0 removes the upper limit.",
    "tooltip": "The highest feed pH at which the controller starts shots. While the feed pH is above this value, all shots in the room wait. It operates only when the controller app has a feed pH sensor."
  },
  "irrigation_ph_min": {
    "caution": "CAUTION: Do not set a pH band that the feed cannot meet. All shots in the room then wait, and the plants can dry out.",
    "guidance": "The default is 5.5 for a new room. If the feed pH sensor gives no reading for longer than the grace time, all shots wait until it reads again. Examine the feed pH after each tank change.",
    "impact": "Increase: Shots wait more often for the feed pH to rise. Decrease: The controller accepts feed with a lower pH. A value of 0 removes the lower limit.",
    "tooltip": "The lowest feed pH at which the controller starts shots. While the feed pH is below this value, all shots in the room wait. It operates only when the controller app has a feed pH sensor."
  },
  "irrigation_phase": {
    "caution": "DEPRECATED. The integration will remove this select in a future major release. The first time you choose a value, a notice appears in Repairs.",
    "guidance": "Do not use this select to move a zone. Use the Set phase select of the zone. The integration keeps it hidden only so that an automation or a script that uses it still loads, and Repairs names each one that does (CS-614).",
    "impact": "P0, P1, P2 or P3: a change sends the event `crop_steering_phase_transition` for automations. Nothing else reads the select.",
    "tooltip": "A retired manual phase marker for the room. The controller does not read it, and a change does not move a zone."
  },
  "main_line_lead_time": {
    "caution": "CAUTION: Do not set a long lead time for a pump that must not run against a closed valve. During this time, the pump runs while the zone valve is closed.",
    "guidance": "Keep the default of 1 s. The controller uses values from 0 s to 10 s. This time does not count toward the shot time.",
    "impact": "Increase: The main line has more time to fill before the zone valve opens, and each shot starts later. Decrease: The zone valve opens sooner after the main-line valve.",
    "tooltip": "The time that the main-line valve is open before the zone valve opens. The controller uses it only when the room has a main-line valve."
  },
  "manual_override": {
    "caution": "CAUTION: Set the override to off after the work. The zone gets no water while it is on, not even a rescue shot.",
    "guidance": "Set the override to on before you work on the valve, the drippers or the lines of the zone. Set the override to off when the work is complete. After you set it to off, examine the zone status.",
    "impact": "On: the controller gives the zone no shot of any type, rescue shots and test shots included, and stops a shot that runs. Off: the controller waters the zone by its rules. When you set it with this switch, the override stays on until you set it to off. When you set it with the `crop_steering.set_manual_override` service, it goes off after its timeout of 1 to 1440 min (default 60 min).",
    "tooltip": "A maintenance lockout for one zone. While it is on, the controller opens the valve of the zone for no shot.",
    "warning": "WARNING: Isolate the electrical power before you work on a pump or a valve. The override does not isolate power, and shots in other zones can start the pump of the room."
  },
  "max_daily_volume": {
    "caution": "CAUTION: Do not set the daily water limit too low. Maintenance shots then stop early, and the plants can dry until the watchdog shot.",
    "guidance": "The default is 20 L. If the controller cannot read a value, it uses 150 L. The controller uses at least 10 L. The integration refuses a value above 4 times the zone substrate volume, or above 20 L for a small zone. The daily total starts again at lights-on. Examine the daily water of the zone for some grow-days before you decrease it.",
    "impact": "Increase: A zone can get more maintenance shots in a grow-day before the shots stop. Decrease: Shots stop sooner, and the controller cuts the last shot to the water that is left.",
    "tooltip": "The most water that a zone gets in one grow-day, in litres. Maintenance shots, extra ramp shots, dilution shots and P0 EC flushes stop at this limit. Ramp shots, rescue shots, watchdog shots and high-EC flushes can go past it."
  },
  "max_run_latch": {
    "caution": "CAUTION: Examine a latched zone immediately. The zone gets no water, not even a rescue shot, until you release it.",
    "guidance": "Do not set the latch to off. New rooms have the latch on by default, and rooms configured before the latch existed have it off. When a zone latches, examine the drippers, the valve and the flow settings of the zone. Then fix the Repairs card CS-312 to release the zone.",
    "impact": "On: after 3 shots in a row at the maximum shot length, the zone gets no more shots, rescue shots included. The zone stays latched until you fix its Repairs card (CS-312). Off: the Repairs card reports the zone, and the zone continues to get water. When you set the switch to off, the controller releases a latched zone. If the controller cannot read the switch, a latched zone stays latched.",
    "tooltip": "Stops a zone when its last 3 shots in a row all ran to the maximum shot length of the room. The Repairs card CS-312 reports such a zone when the switch is on and when it is off."
  },
  "max_shot_duration": {
    "caution": "CAUTION: Do not set the longest shot much above the time of your largest correct shot. A shot from a wrong size setting can then run long and flood the substrate.",
    "guidance": "Keep the default of 900 s. Increase it only when CS-306 alerts show that correct planned shots are longer. Before a change, examine the substrate volume, the drippers per plant and the dripper flow. The integration refuses a value above the limit of the slowest zone. That limit is the time that the zone drippers need to give one full substrate volume, and at least 900 s. If the controller cannot read this value, it starts no shot and sends a CS-203 alert.",
    "impact": "Increase: Long planned shots run in full and give their planned water. Decrease: More shots stop early and give less water than planned, and the controller sends a CS-306 alert for each one.",
    "tooltip": "The longest time that a valve in this room stays open for one shot. The controller cuts a longer planned shot to this time, and that shot gives less water than planned."
  },
  "maximum_ec": {
    "caution": "CAUTION: Do not set the maximum EC at or below the feed EC. At or above this level, a zone with a feed EC that is not lower gets no shots, and the plants can dry out.",
    "guidance": "The default is 9.0 mS/cm. The controller uses values from 3 mS/cm to 15 mS/cm. Set it above the EC targets of all phases. Examine the feed EC before a change. A flush works only when the feed EC is lower than the pore EC. With no feed EC sensor and no recipe feed EC, the feed EC is unknown: the controller gives no flush and does not hold the zone for high EC, and it sends a CS-907 alert. The high-EC flush needs VWC more than 2 points below field capacity. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: Pore EC can rise higher before the controller flushes, so EC can stack more. Decrease: Flushes start at a lower pore EC, with more water and more runoff. In P2, a rescue flush starts 1 mS/cm below this value. These flushes can go past the daily water limit.",
    "tooltip": "The highest pore EC that the controller accepts in a zone. At or above this level, the controller gives a flush in any phase when the feed EC is lower than the pore EC. When the feed EC is not lower, or the zone does not drain, the zone gets no shot of any type."
  },
  "min_daily_ml_per_plant": {
    "caution": "CAUTION: Do not use this setting as the normal water plan. It waters when the probe shows a wet substrate, and it can keep the substrate too wet.",
    "guidance": "The default is 0 (off). The zone total is this value times the plant count. The controller limits the total to the daily water limit. The shots stop when VWC is 5 points above field capacity. Daily minimum shots use the maintenance shot size and wait for the EC correction interval. They do not start in P0, and every shot of the zone counts toward the minimum.",
    "impact": "Increase: The zone gets more water each grow-day, also when VWC is high, which can make the dryback smaller. Decrease: The zone gets less guaranteed water. A value of 0 stops the daily minimum.",
    "tooltip": "The least water that each plant gets in one grow-day, in millilitres. The controller gives it at any probe reading. It spreads the water through the day, so that it is complete 3 h before lights-off."
  },
  "notify_predictions": {
    "guidance": "The default is on, also on an upgraded room. Set it to off for a shorter vitals report.",
    "impact": "On: under each zone, the vitals report tells what the controller does next. Off: the vitals report gives only the readings. A controller that cannot find this switch includes the predictions.",
    "tooltip": "Adds the next step of each zone to the vitals report that the controller sends. The dashboard shows the same step as `Next:`."
  },
  "p0_additional_dryback": {
    "guidance": "A new room starts at 3%, and a room updated in place starts at 0 (off). The controller uses values from 0% to 40%. P0 also ends at the maximum wait time, or when VWC falls to the re-water point. Examine the time of the first shot on the day chart for two grow-days after a change.",
    "impact": "Increase: The first shot comes later, and the morning dryback is deeper, which steers generative. Decrease: The ramp starts sooner after lights-on.",
    "tooltip": "The dryback after lights-on before the first shot, as a percentage of the highest VWC since lights-on. At 3% and a highest VWC of 60%, P0 ends at 58.2% VWC. At 0, P0 uses the dryback target of the steering mode."
  },
  "p0_dryback_drop_percent": {
    "guidance": "Do not use this setting. To change the morning dryback, set the P0 extra dryback of the zone. Recipes can contain a value for this setting.",
    "impact": "Increase: The shots do not change. Decrease: The shots do not change.",
    "tooltip": "An old setting that stays for older rooms and recipes. The controller does not read it. The P0 dryback comes from the P0 extra dryback of each zone."
  },
  "p0_maximum_wait_time": {
    "guidance": "The default is 120 min for a new room. If the controller cannot read a value, it uses 45 min as the wait. The controller uses values from 5 min to 240 min, and it sends a CS-401 alert for a value outside this range. P0 also ends when VWC falls to the re-water point, or when the zone completes its P0 dryback. Examine the time of the first shot on the day chart after a change. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: The first shot can come later, so the morning dryback can be deeper, which steers generative. Decrease: The ramp starts sooner after lights-on, and the morning dryback is smaller.",
    "tooltip": "The longest time that the morning dryback (P0) lasts after lights-on. At this time, the zone goes to P1, also when the dryback is not complete."
  },
  "p1_initial_shot_size": {
    "caution": "CAUTION: Do not set a large first ramp shot. Ramp shots can go past the daily water limit, and a large shot can flood the substrate.",
    "guidance": "The default is 2%. The controller uses values from 0.5% to 15%. Keep ramp shots small so that the substrate wets evenly. For example, a 2% shot of a 5 L block is 100 mL for each plant. Examine the VWC rise after each ramp shot on the day chart. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: The ramp gives more water early and reaches the peak target in fewer shots, with more runoff from each shot. Decrease: The ramp wets the substrate more slowly, in more shots. The controller changes each ramp shot from half to twice its size, by pore EC against the P1 EC target.",
    "tooltip": "The size of the first ramp shot, as a percentage of the substrate volume. Each later ramp shot adds the ramp shot increase to the shot before it."
  },
  "p1_maximum_extra_shots": {
    "guidance": "The default is 3. The controller uses values from 1 to 30. Extra shots count toward the daily water limit and toward the maximum ramp shots: P1 ends at the maximum ramp shots first, so to give more extra shots, also increase the maximum ramp shots. P1 gives no extra shot while the zone does not drain (CS-310). The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: P1 can give more extra shots to fill the substrate, with more runoff. Decrease: P1 ends sooner after it reaches the peak target.",
    "tooltip": "The highest number of extra shots that P1 gives after VWC reaches the peak target. At this number, the zone goes to P2."
  },
  "p1_maximum_shots": {
    "guidance": "The default is 6. If the controller cannot read a value, it uses 12. Set it higher than the minimum ramp shots. When the minimum is higher, the controller uses this value as the minimum. Examine on the day chart whether the ramp reaches the peak target. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: The ramp can continue longer to reach the peak target, and ramp shots can go past the daily water limit. Decrease: The ramp can stop below the peak target, and P2 then gives maintenance shots below the re-water point. This value also stops the increase of the ramp shot size.",
    "tooltip": "The highest number of shots in P1. At this number, the zone goes to P2 at any VWC."
  },
  "p1_minimum_shots": {
    "guidance": "The default is 3. If the controller cannot read a value, it uses 0. Keep it at or below the maximum ramp shots. When it is higher, the controller uses the maximum ramp shots. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: P1 gives more shots before it ends, also when VWC is at the peak target. Decrease: P1 can end after fewer shots when the substrate is full.",
    "tooltip": "The number of ramp shots that P1 must give before it can end because the substrate is full. P1 can still end at the maximum ramp shots, at the maximum extra shots, or with the daily water limit spent."
  },
  "p1_rise_pts": {
    "guidance": "The default is 0.5 points. The controller uses values from 0.1 points to 5 points. When the controller knows the gain of the zone, the necessary rise is the larger of this value and 0.3 times the expected rise. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: P1 ends sooner, because a small rise ends it. Decrease: P1 gives more extra shots, which fill the substrate more and give more runoff.",
    "tooltip": "After P1 reaches its peak target, it gives extra shots. P1 gives another extra shot only while each one raises the settled VWC by at least this value. The settled VWC is the median of the last 10 minutes."
  },
  "p1_shot_size_increment": {
    "guidance": "The default is 0.5%. The controller uses values from 0% to 5%. Examine the VWC rise of the later ramp shots on the day chart after a change. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: Later ramp shots get larger faster, so the ramp gives more water in fewer shots. Decrease: Ramp shots stay nearer to the size of the first shot. The increase stops at the maximum number of ramp shots.",
    "tooltip": "The size that each ramp shot adds to the shot before it, as a percentage of the substrate volume. The third ramp shot is the first ramp shot plus two times this value."
  },
  "p1_target_vwc": {
    "guidance": "The default is 65%. If the controller cannot read a value, it uses 60%. Set it at or below field capacity, because the ramp does not go above field capacity. The integration refuses a change that puts the re-water point at or above the peak target. When Auto setpoints is on, the controller sets this value from the highest reading of the grow-day before. Examine the peak and the runoff on the day chart for two grow-days after a change. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: The ramp gives more water, the peak is higher and runoff increases, which steers vegetative. Decrease: The ramp ends sooner with less runoff, which steers generative. The controller keeps the re-water point at least 1 point below this value.",
    "tooltip": "The VWC at which the ramp (P1) stops the ramp shots. The ramp stops at this value or at field capacity, whichever is lower. Then P1 gives extra shots until a shot no longer raises VWC enough."
  },
  "p1_time_between_shots": {
    "guidance": "The default is 15 min for a new room. The controller uses values from 1 min to 120 min for this wait. A time of 15 min to 30 min lets the substrate wet gradually. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: Each shot has more time to soak in before the next, and the ramp takes longer. Decrease: Ramp shots come closer together, and the ramp reaches the peak sooner, with more runoff before the substrate absorbs the water.",
    "tooltip": "The minimum time between ramp shots. A ramp shot or an extra P1 shot starts only when this time has passed since the last shot."
  },
  "p2_ec_high_threshold": {
    "guidance": "Do not use it. The integration keeps it hidden only so that an automation or a script that uses it still loads, and Repairs names each one that does (CS-614). To move the re-water point with pore EC, use the EC stacking switch.",
    "tooltip": "A retired ratio of pore EC to the EC target. Nothing reads it. In P2, the controller gives dilution shots above 1.2 times the P2 EC target, or above the zone dilute ratio."
  },
  "p2_ec_low_threshold": {
    "guidance": "Do not use it. The integration keeps it hidden only so that an automation or a script that uses it still loads, and Repairs names each one that does (CS-614). To move the re-water point with pore EC, use the EC stacking switch.",
    "tooltip": "A retired ratio of pore EC to the EC target. Nothing reads it."
  },
  "p2_shot_size": {
    "caution": "CAUTION: Do not set a large maintenance shot. EC flushes use 1.5 times this size or more, and a large shot can flood the substrate.",
    "guidance": "The default is 5%. The controller uses values from 0.5% to 20%, and it sends a CS-401 alert for a value outside this range. Maintenance shots stop at the daily water limit. When the AI assistant controls the setpoints, it can change this value once a night, from 1% to 4%. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: Each maintenance shot gives more water and more runoff, which dilutes pore EC. Decrease: Shots give less runoff, which lets pore EC stack. The controller changes each maintenance shot from half to twice this size, by pore EC against the P2 EC target.",
    "tooltip": "The size of each maintenance shot, as a percentage of the substrate volume. Watchdog shots and daily minimum shots use this size. EC flushes and dilution shots use 1.5 times this size or more."
  },
  "p2_time_between_shots": {
    "guidance": "The default is 0 min (off). The controller uses values from 0 min to 120 min for this wait. Set a value when a zone gets two or more maintenance shots before VWC rises on the day chart. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: Maintenance shots come less often, so VWC can fall further below the re-water point. Decrease: Maintenance shots can come one after the other, before the probe shows the last shot. A value of 0 stops this wait.",
    "tooltip": "The minimum time from the last shot before a maintenance shot can start. It gives the water time to reach the probe before the controller reads VWC again. EC corrections use the EC correction interval."
  },
  "p2_vwc_threshold": {
    "guidance": "The default is 60%. If the controller cannot read a value, it uses 45%. Keep it at least 3 points above the rescue floor and below the peak target. The integration refuses a change that breaks this order. With EC stacking on, the controller lowers it by 1 point when pore EC is below 90% of the P2 EC target. It raises it by 1 point when pore EC is above 110% of that target. When Auto setpoints is on, the controller moves this value through the grow-day. Examine the daytime dryback on the day chart for two grow-days after a change. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: Maintenance shots come more often, and the daytime dryback is smaller, which steers vegetative. Decrease: The daytime dryback is larger, with fewer shots and less runoff, which steers generative and lets EC stack. The watchdog also uses this value.",
    "tooltip": "The VWC that starts a maintenance shot in P2. Each time the controller checks in P2, it gives a shot when VWC is below this value. In P0, VWC at or below this value ends the morning dryback."
  },
  "p3_dryback_hold": {
    "caution": "CAUTION: Do not use a small overnight dryback target with the hold on. The zone can then get many shots overnight and stay too wet.",
    "guidance": "The default is off. Set it to on when a zone dries too fast overnight and gets rescue shots most nights. Before you set it to on, examine the overnight dryback target and the rescue shot size of the zone. After the first night, examine the shots in the activity log.",
    "impact": "On: in P3, each time VWC falls below the hold level, the controller gives a shot of the rescue shot size. The hold level is the peak of the grow-day less the overnight dryback, as a percent of the peak. Example: a 30% dryback from an 86.5% peak gives 60.55%. On: the shots are at least the P3 time between shots apart. Off: in P3, the zone dries until VWC falls below the rescue floor, then it gets a rescue shot. The hold is steering, so a held grow plan and the daily water limit stop it. The rescue shot still runs below the hold.",
    "tooltip": "Holds the overnight dryback (P3) of the zone at its dryback target. The controller gives small shots overnight, so the zone does not dry to the rescue floor."
  },
  "p3_emergency_shot_size": {
    "caution": "CAUTION: Do not set a large rescue shot. Rescue shots have no daily water limit, and large shots overnight can flood the substrate.",
    "guidance": "The default is 2%. The controller uses values from 0.5% to 15%. Keep rescue shots small, so that one rescue shot does not end the overnight dryback. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: Each rescue shot gives more water and raises VWC more overnight. Decrease: Each rescue shot gives less water, and the zone can need more rescue shots.",
    "tooltip": "The size of each rescue shot, as a percentage of the substrate volume. Rescue shots can go past the daily water limit. With the P3 dryback hold on, hold shots also use this size."
  },
  "p3_emergency_vwc_threshold": {
    "caution": "CAUTION: Do not lower the rescue floor below the wilt point of the plants. Overnight, the substrate can then dry until the plants wilt.",
    "guidance": "The default is 40%. Set it above the VWC at which the plants wilt. Keep it below the end of the planned overnight dryback. The integration refuses a change that puts it less than 3 points below the re-water point. Auto setpoints does not move this value. Examine the night VWC on the day chart for rescue shots after a change. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: Rescue shots start at a higher VWC, which can stop the overnight dryback early. Decrease: The substrate can dry more overnight before a rescue shot. The re-water point must stay at least 3 points above this value.",
    "tooltip": "The overnight safety level of VWC. In P3, the controller gives a rescue shot each time VWC is below this level. Rescue shots can go past the daily water limit."
  },
  "p3_time_between_shots": {
    "guidance": "The default is 10 min. The first rescue shot of a night usually starts at once, because the last shot was long before. Set a value longer than the time that a shot needs to reach the probe. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: Rescue shots come less often, and VWC can stay below the rescue floor for longer. Decrease: Rescue shots can come one after the other, before the probe shows the last shot. A value of 0 stops this wait.",
    "tooltip": "The minimum time from the last shot before a rescue shot can start. It gives the water time to reach the probe before the controller reads VWC again. The time counts from the last shot of any type."
  },
  "plant_count": {
    "caution": "CAUTION: Do not set more plants than the zone has. The daily water limit and the daily minimum water then permit too much water.",
    "guidance": "Count the plants on the zone valve, and set that number. The default is 4. A wrong count gives wrong daily water totals and a wrong daily minimum water. The upper limit of the daily water limit also follows this count.",
    "impact": "Increase: The controller counts more litres for each shot, so the zone reaches its daily water limit sooner. The shot time does not change, because the zone flow increases by the same factor. Decrease: Each shot counts fewer litres, and the daily minimum water decreases.",
    "tooltip": "The number of plants in this zone. The water of a shot is the shot size, times the substrate per plant, times this number."
  },
  "pump_prime_time": {
    "caution": "CAUTION: Do not set a long prime time for a pump that must not run against closed valves. During this time, the pump runs while all valves are closed.",
    "guidance": "Keep the default of 2 s. Increase it only for a pump that needs more time to get pressure. The controller uses values from 0 s to 20 s. This time does not count toward the shot time.",
    "impact": "Increase: The pump has more time to get pressure, and the valves stay closed for longer at the start of each shot. Decrease: The valves open sooner after the pump starts.",
    "tooltip": "The time that the pump runs before the main-line valve opens. With no main-line valve, the zone valve opens after this time. The controller uses it only when the room has a pump."
  },
  "recipe_stage": {
    "caution": "DEPRECATED. Nothing in the dashboard uses this select, and the integration will remove it in a future major release. The first time you choose a value, a notice appears in Repairs. CAUTION: Examine the values of a stage before you select it. The controller uses the new setpoints for all zones at its next pass.",
    "guidance": "Examine the setpoints of the stage on the recipe page before you select it. After you select a stage, examine the setpoints of each zone.",
    "impact": "Each option writes its own set of setpoints from the recipe. The integration keeps each value inside the limits of its number. If the VWC setpoints of the stage put the levels of a zone out of order, the integration writes nothing. It then shows an error. Auto setpoints and the setpoints judge of the AI assistant can change the values after that.",
    "tooltip": "Selects a stage of the room recipe: Veg, Transition, Bulk, Ripen or Custom. When you select a stage, the integration writes the setpoints of that stage into the numbers of the room and of each zone."
  },
  "room_active": {
    "caution": "CAUTION: Do not set the room to off while plants are in the room. The plants then get no water, not even a rescue shot.",
    "guidance": "Keep the room on while plants grow in it. Set the room to off only when the room is empty. Set the room to on before you put plants in the room. After you set the room to on, examine the status of each zone on the dashboard.",
    "impact": "On: the controller waters the room by its rules and sends alerts. Off: the controller gives no shot of any type in the room, rescue shots included. Off: a shot that runs stops within a few seconds, and the controller removes the open alerts of the room. After less than 24 h off, the controller continues from where it stopped. After 24 h or more off, the controller starts a new run with each zone in P3.",
    "tooltip": "Tells the controller that plants grow in the room. When the room is off, the controller gives no shots and sends no alerts for the room."
  },
  "set_phase": {
    "caution": "CAUTION: Do not select P3 while the lights are on without a reason. The zone then stays in P3 until the next lights-on and gets no maintenance shots.",
    "guidance": "Keep the select at Keep for normal operation. Select a phase only to correct a zone that is in the wrong phase. After the move, examine the phase and the status of the zone.",
    "impact": "Keep: no change. P0: the zone goes to morning dryback, and the controller measures the dryback from the VWC at the move. P1: the zone goes to the ramp, and the ramp starts again from its first shot. P2: the zone goes to maintenance. P3: the zone goes to overnight dryback. The water and the shot count of the grow-day stay. After the move, the rules continue: lights-off moves the zone to P3, and lights-on moves it to P0.",
    "tooltip": "Moves the zone to a phase by hand. The controller applies the choice one time, within a minute, and then sets the select back to Keep."
  },
  "steering_mode": {
    "guidance": "The default is Vegetative. Set the steering mode of each zone. Before you change it, examine the dryback targets and EC targets of the new mode. After the change, examine the next dryback of the zone.",
    "impact": "Vegetative: the zone uses the vegetative dryback target and the vegetative EC targets. Generative: the zone uses the generative dryback target and the generative EC targets. The controller reads the select of each zone, and uses the growth stage of the room when it cannot read it. The dashboard shows the EC targets in the same order. The controller does not read the select of the room. The integration uses it only for the EC ratio sensor.",
    "tooltip": "Selects vegetative or generative steering. Each zone has its own steering mode, and the room has one more steering mode."
  },
  "substrate": {
    "guidance": "The default is generic, also on an upgraded room. Select the substrate that the room grows in. After the change, examine the setpoints of each zone.",
    "impact": "Generic: the controller runs as before. Rockwool: a setting with no value yet starts at 75% field capacity, 70% peak target, 65% re-water point and 40% rescue floor. Rockwool: the dryback targets start at 15% (vegetative) and 35% (generative). Coco: a setting with no value yet starts at 65% field capacity, 60% peak target, 55% re-water point and 30% rescue floor. Coco: the controller waits 60 min after a shot before it uses a pore EC reading. A value that the room already has does not change.",
    "tooltip": "Tells the controller what the room grows in: generic, rockwool or coco. The controller reads it from the room descriptor and uses a change without a disarm."
  },
  "substrate_volume": {
    "caution": "CAUTION: Do not set a substrate volume larger than the true volume. Each shot then gives too much water and can flood the substrate.",
    "guidance": "Set the true substrate volume of one plant, in litres. The default of 10 L is a generic value. Do a catch test after a change, and compare the delivered water with the planned water. A zone has its own value only when setup gave that zone its own size. Then the zone value overrides the room value for that zone only. If the controller cannot read a value, it uses the substrate option of the controller app.",
    "impact": "Increase: Each shot gives more litres and runs for more time, and the upper limits of the daily water limit and the longest shot increase. Decrease: Each shot gives fewer litres and runs for less time.",
    "tooltip": "The litres of substrate for each plant, for example the volume of one block or pot. All shot sizes are a percentage of this volume. The water of a shot is the shot size, times this volume, times the plant count."
  },
  "sump_power_threshold_w": {
    "caution": "CAUTION: Do not set this value below the standby power of the sump pump. The controller then cannot see a stopped pump, and runoff can collect under the slabs.",
    "guidance": "The default is 20 W. Read the standby power and the run power of the sump pump on its power plug. Set a value between these two values. The alert needs a sump power sensor in the controller app.",
    "impact": "Increase: Low power readings do not count as a run, so the alert can come while the pump operates at low power. Decrease: Small readings count as a run, so the controller can miss a stopped pump.",
    "tooltip": "The power above which the sump pump counts as on. If the sump pump draws no power above this value for the hours set in the controller app, the controller sends a CS-311 alert."
  },
  "system_enabled": {
    "guidance": "Do not set this switch to off. Use the kill switch to stop the water of the room. If alert CS-208 shows, set this switch to on. Then set the kill switch to on using Watering in the header.",
    "impact": "On: no effect on a current controller. Off: a current controller sets the kill switch of the room to off and raises alert CS-208. A controller of version 2.24.0 or older holds every shot while this switch is off or missing.",
    "tooltip": "A retired switch that the integration keeps hidden. The kill switch is the one switch that stops the water of the room."
  },
  "test_shot": {
    "caution": "CAUTION: Do not press the button many times on a wet zone. Each press gives one more 10 s shot.",
    "guidance": "Go to the zone before you press the button. Watch the drippers during the 10 s of the shot. Do a catch test to measure the water. If no shot comes, read the zone status.",
    "impact": "When you press the button, the controller opens the valve of the zone for 10 s. A press more than 10 min old has no effect. The test shot goes through each check of a normal shot, but a held grow plan does not stop it. The kill switch, the room switch, the zone switch and the manual override stop it.",
    "tooltip": "Asks the controller for a 10 s test shot in the zone, to check the water delivery. The controller acts at its next pass, within a minute.",
    "warning": "WARNING: Make sure that no person works on the lines, the pump or the valves before you press. The pump and the valve start within a minute."
  },
  "vegetative_dryback_target": {
    "caution": "CAUTION: Do not set a dryback that ends below the wilt point of the plants. A deep dryback can stress the plants and stop growth.",
    "guidance": "The default is 35% for a new room. A new room starts with the value of its substrate type. If the controller cannot read a value, it uses 20%. The controller uses values from 2% to 60%, and it sends a CS-401 alert for a value outside this range. The value applies only to zones in vegetative steering mode. Keep the end of the dryback above the rescue floor, because a rescue shot stops a dryback below it. Examine the overnight dryback on the day chart for two grow-days after a change. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: In the last 3 h before lights-off, the controller can move a zone to P3 earlier, for a deeper overnight dryback. When the P0 extra dryback is 0, the first shot also comes later. Decrease: P3 starts nearer to lights-off, and the substrate stays wetter.",
    "tooltip": "The dryback for a zone in vegetative steering mode, as a percentage of the peak. At a peak of 60% and a target of 10%, the dryback ends at 54% VWC. The controller uses it in P0 when the P0 extra dryback is 0, and to start P3 early."
  },
  "watchdog_hours": {
    "caution": "CAUTION: Do not set the watchdog interval to 0 while the controller waters the room. With no watchdog, a zone that gets no shots can dry out.",
    "guidance": "The default is 3 h. Keep the watchdog on. A watchdog shot has the size of the maintenance shot. When a hold stops a watchdog shot that is due, the controller sends a CS-207 alert. The controller reads the zone value first, so the zone value overrides the room value for that zone only.",
    "impact": "Increase: The controller waits longer before a watchdog shot, so a zone with a fault can dry more. Decrease: Watchdog shots come sooner, and they can go past the daily water limit. A value of 0 stops the watchdog.",
    "tooltip": "The longest time that a zone can go without a shot while the lights are on. When this time is past and VWC is below the re-water point, the controller gives a watchdog shot. The watchdog does not operate in P0."
  },
  "water_today_view": {
    "guidance": "The default is Zone total. Select Per plant to compare zones with different plant counts. This select changes only the display, not the shots.",
    "impact": "Zone total: shows the litres of each zone. Per plant: shows the water and the daily limit of each zone divided by its plant count. The dashboard shows the choice to all users, and the vitals report follows it. In the vitals report, a zone with no whole plant count stays in litres.",
    "tooltip": "Selects how the dashboard and the vitals report show the water today of each zone."
  }
};

/** The help of each dashboard control, by its label in lower case. `{x}` is a value that the
 * control fills in. */
export const UI_COPY = {
  "about {x}": {
    "impact": "Opens help. It changes no setting.",
    "label": "About {x}",
    "tooltip": "Opens help about the setting {x}."
  },
  "add": {
    "impact": "Changes the draft only. Review and save the notifications to use the change.",
    "label": "Add",
    "tooltip": "Adds the phone to the notification draft."
  },
  "add a pump to the recipe": {
    "impact": "The change stays in the dosing draft until you save it.",
    "label": "Add pump to recipe",
    "tooltip": "Adds the pump that you select to the batch recipe."
  },
  "add room": {
    "impact": "Makes a draft only. The room is not saved until you save the draft.",
    "label": "Add room",
    "tooltip": "Makes a new room draft with one zone."
  },
  "amount (ml)": {
    "caution": "CAUTION: Do not dose more than the recipe quantity. Too much concentrate can increase the feed EC and cause damage to the plants.",
    "guidance": "Examine the stock tank level and the batch tank level before you dose. Examine the feed EC and the feed pH after the dose.",
    "impact": "Opens a review of the dose. The pump starts only when you confirm the review.",
    "label": "Quantity (mL)",
    "tooltip": "The quantity that the pump doses into the batch tank, in mL.",
    "warning": "WARNING: Do not touch the nutrient concentrates or the acids without gloves and eye protection. These chemicals can cause injury to the skin and the eyes."
  },
  "ask": {
    "guidance": "Ask about one decision in each question. Read the answer in the list under the question. Only an administrator can ask.",
    "impact": "The integration sends the question to the controller.",
    "label": "Ask",
    "tooltip": "Sends your question to the AI assistant."
  },
  "back": {
    "guidance": "Use Back to change the values before you send the request.",
    "impact": "The controller gets no request.",
    "label": "Back",
    "tooltip": "Closes the review and sends nothing to the controller."
  },
  "catch-test calibration": {
    "guidance": "Use a dripper that is typical of the zone.",
    "impact": "The result changes this calculation only. It changes no setting.",
    "label": "Catch-test calibration",
    "tooltip": "A catch test measures the water from one dripper over a known time. The dashboard uses the result in this calculation only."
  },
  "choose a zone to compare": {
    "guidance": "Select one or more zones, or select \"Show all zones\".",
    "label": "Select a zone to compare",
    "tooltip": "The chart shows no zone."
  },
  "collected water per dripper · ml": {
    "label": "Water from one dripper · mL",
    "tooltip": "The volume of water that one dripper gave in the catch test, in mL."
  },
  "collection time · minutes": {
    "label": "Catch test time · min",
    "tooltip": "The time that you collected the water from the dripper, in minutes."
  },
  "compare with": {
    "label": "Compare with",
    "tooltip": "The reference that the chart shows next to the current data. On the grow-day chart, this is yesterday, a typical day from the median of 7 days, or none."
  },
  "daily vwc & ec plan": {
    "guidance": "Drag a target, or use the exact controls. Review the draft before you save it.",
    "impact": "A change on this chart goes into the draft of the selected day and zone.",
    "label": "Daily VWC and EC plan",
    "tooltip": "The VWC and EC targets of each phase, from lights-on to the next lights-on."
  },
  "demo brain state": {
    "impact": "Changes the sample view only. It changes no setting.",
    "label": "Sample AI state",
    "tooltip": "Selects a sample state of the AI assistant. This control shows only with sample readings."
  },
  "dose entity (optional)": {
    "label": "Dose entity (optional)",
    "tooltip": "A number, input_number or sensor entity that gives the mL of this tank for each batch. When it has no value, the fixed dose applies."
  },
  "dryback drivers": {
    "guidance": "The rate is in percentage points each hour. The dryback target of the controller is a percent of the peak. Do not compare the two numbers directly.",
    "impact": "Shows recorded values only. It changes nothing.",
    "label": "Dryback drivers",
    "tooltip": "Each point is one zone and one night: the drop of VWC from lights-off to lights-on, in percentage points each hour, against the mean of the climate value for that night. A night with a shot is not shown."
  },
  "end date · blank while ongoing": {
    "label": "End date · empty if open",
    "tooltip": "The last day of the run. Keep it empty while the run continues."
  },
  "endpoint profile": {
    "impact": "Changes the local draft only.",
    "label": "Endpoint profile",
    "tooltip": "Select the endpoint profile for the selected days of this zone."
  },
  "equipment lanes": {
    "impact": "Shows recorded states only. It changes nothing.",
    "label": "Equipment today",
    "tooltip": "Each mapped device of the room on one time axis, from lights-on: a bar shows when the device was on. The shaded part is lights-off."
  },
  "every zone in {x}": {
    "caution": "CAUTION: Do not pause every zone while plants are in the room. A paused zone gets no water, also no rescue shot.",
    "guidance": "Examine the list of zones in the review before you confirm.",
    "impact": "On: opens a review to start every zone, also a paused zone. Off: opens a review to pause every zone.",
    "label": "Every zone in {x}",
    "tooltip": "One switch for all zones of {x}. It is on when one or more zones are on."
  },
  "export recipe {x}": {
    "impact": "Downloads a file. It changes no setting.",
    "label": "Export recipe {x}",
    "tooltip": "Downloads the recipe {x} as a JSON file."
  },
  "from date": {
    "label": "Start date",
    "tooltip": "The first date of a custom range."
  },
  "got it": {
    "impact": "Closes the window. It changes no setting.",
    "label": "Close",
    "tooltip": "Closes the list of new changes."
  },
  "hardware panel": {
    "caution": "CAUTION: Make sure that the drippers are in the substrate or in a container before a test shot. Loose drippers can flood the area.",
    "impact": "The list changes nothing. The test shot opens the valve of this zone for 10 s when Watering is on.",
    "label": "Hardware",
    "tooltip": "The valve of this zone, the pump, the main line, the lights and the tank fill of the room: on or off now, and since when. The test shot is a 10 s shot through the safety checks of the controller."
  },
  "history could not load": {
    "guidance": "Select \"Retry history\". If the problem continues, examine the connection to Home Assistant.",
    "label": "History did not load",
    "tooltip": "The dashboard did not get the recorded history from Home Assistant."
  },
  "history range": {
    "label": "History range",
    "tooltip": "The time range of the recorded history on the chart."
  },
  "home assistant url": {
    "label": "Home Assistant URL",
    "tooltip": "The address of Home Assistant. Leave it empty to use the current address and session."
  },
  "how is this room plumbed?": {
    "label": "Room plumbing",
    "tooltip": "Select how the pump and the valves of the room connect."
  },
  "import grow plan": {
    "guidance": "Examine the endpoints and the zone assignments before you save the draft. All zones in the file must be zones of this room.",
    "impact": "Loads the plan as a local draft only. Nothing is saved or armed.",
    "label": "Import grow plan",
    "tooltip": "Select a JSON file of a grow plan."
  },
  "import recipe file": {
    "impact": "Opens the recipe so that you can save it in the library of this browser. Home Assistant does not change.",
    "label": "Import recipe file",
    "tooltip": "Reads a recipe from a JSON file of 500 KB or less."
  },
  "import run metadata": {
    "guidance": "Use an export file of this room only.",
    "impact": "The integration adds the runs to the run records of this room.",
    "label": "Import run metadata",
    "tooltip": "Reads run records from a version 1 export file of this room. The maximum file size is 2 MB."
  },
  "import targets": {
    "guidance": "Review the changes before you apply them.",
    "impact": "Loads the targets as a draft only. Nothing is written to the controller.",
    "label": "Import targets",
    "tooltip": "Select a JSON file of targets."
  },
  "include what each zone does next": {
    "impact": "On: the vitals report shows the next shot and the next phase of each zone. Off: the report does not show them.",
    "label": "Next action of each zone",
    "tooltip": "Select if the vitals report shows the next action of each zone."
  },
  "install the controller app": {
    "guidance": "Keep Watering off in each room while you map the hardware.",
    "label": "Install the controller app",
    "tooltip": "Add the repository to the Supervisor and install the controller app."
  },
  "level read off the tank (l)": {
    "label": "Tank level (L)",
    "tooltip": "Type the level that you read on the stock tank, in litres."
  },
  "load into local draft": {
    "guidance": "Review the draft in the planner before you save it.",
    "impact": "Only the local draft changes. The live settings stay the same until you review and save the draft in the planner.",
    "label": "Load into local draft",
    "tooltip": "Puts the recipe into the local draft of the planner."
  },
  "long-lived access token": {
    "label": "Long-lived access token",
    "tooltip": "A Home Assistant token for this tab only. The dashboard does not put it in a URL."
  },
  "make a batch": {
    "caution": "CAUTION: Do not start a batch when the batch tank is full. The tank can overflow.",
    "guidance": "Examine the batch tank, the stock tanks and the recipe before you start. Examine the feed EC and the feed pH after the batch.",
    "impact": "The batch starts only after you confirm the review. The review shows the steps of the batch.",
    "label": "Make a batch",
    "tooltip": "Opens a review of a new batch: the steps, the recipe and the expected time.",
    "warning": "WARNING: Do not touch the nutrient concentrates or the acids without gloves and eye protection. These chemicals can cause injury to the skin and the eyes."
  },
  "map, verify and start": {
    "guidance": "Make sure that the controller accepts the mapping. Set Watering to on in the header only after you examine the hardware.",
    "label": "Map, verify and start",
    "tooltip": "Select the valves and the probes, and type the pot and dripper values. Then review your grow plan."
  },
  "ml": {
    "label": "mL",
    "tooltip": "The volume of this pump in the batch recipe, in mL."
  },
  "move {x} earlier": {
    "impact": "The change stays in the dosing draft until you save it.",
    "label": "Move {x} earlier",
    "tooltip": "Moves {x} one position earlier in the batch recipe."
  },
  "move {x} later": {
    "impact": "The change stays in the dosing draft until you save it.",
    "label": "Move {x} later",
    "tooltip": "Moves {x} one position later in the batch recipe."
  },
  "move {x} to {x}?": {
    "caution": "CAUTION: Examine the VWC before you move a zone to P1. In P1 the zone starts its ramp again and can get too much water.",
    "guidance": "Lights-off still moves the zone to P3, and lights-on moves it to P0.",
    "impact": "The controller moves the zone at its next check, in one minute or less. The water and shot counts of the grow-day stay the same.",
    "label": "Move {x} to {x}?",
    "tooltip": "Review the phase change before you send it."
  },
  "name": {
    "label": "Name",
    "tooltip": "The name of the item, as the dashboard shows it. For a dosing pump, the maximum length is 40 characters."
  },
  "no lights schedule": {
    "guidance": "Set the lights-on and lights-off hours of this room.",
    "label": "No lights schedule",
    "tooltip": "The room has no lights-on and lights-off hours, so the dashboard cannot draw the grow-day."
  },
  "no probes mapped for this zone": {
    "guidance": "Map a VWC probe and an EC probe in Rooms and setup.",
    "label": "No probes for this zone",
    "tooltip": "This zone has no VWC probe and no EC probe."
  },
  "no retained history in this range": {
    "guidance": "Examine the Recorder retention, the probes that count and the selected dates.",
    "label": "No history in this range",
    "tooltip": "Home Assistant has no recorded history for the dates that you selected. The chart does not make a curve without data."
  },
  "no tank level is mapped": {
    "guidance": "Map the level sensor of the tank, in %, in Rooms and setup.",
    "label": "No tank level sensor",
    "tooltip": "The room has no mapped tank level sensor."
  },
  "note (optional)": {
    "label": "Note (optional)",
    "tooltip": "A short note about this check. The maximum length is 200 characters."
  },
  "notes (optional)": {
    "label": "Notes (optional)",
    "tooltip": "Notes about the recipe. The maximum length is 1000 characters."
  },
  "notify service": {
    "label": "Notify service",
    "tooltip": "The Home Assistant notify service of the phone, for example notify.mobile_app_phone."
  },
  "open home assistant menu": {
    "impact": "Opens a menu. It changes no setting.",
    "label": "Open Home Assistant menu",
    "tooltip": "Opens the sidebar menu of Home Assistant."
  },
  "open navigation": {
    "impact": "Opens a menu. It changes no setting.",
    "label": "Open navigation",
    "tooltip": "Opens the list of dashboard pages on a small screen."
  },
  "plan name (optional)": {
    "label": "Plan name (optional)",
    "tooltip": "A name for the grow plan, 100 characters maximum. The AI assistant shows it on its plan line."
  },
  "preview day": {
    "label": "Preview day",
    "tooltip": "The grow-day that the planner shows, from 1 to 366."
  },
  "preview room changes in": {
    "label": "Preview room changes in",
    "tooltip": "Select the zone that shows the preview of the room changes."
  },
  "probe read (": {
    "label": "Probe value ({x})",
    "tooltip": "The value that the probe showed in this reference solution, in {x}."
  },
  "probes": {
    "guidance": "When the controller does not report, open this page to find the probe that is old.",
    "impact": "Opens the Probes page. It changes no setting.",
    "label": "Probes",
    "tooltip": "The page that shows each probe of the room, its readings and the age of its readings."
  },
  "profile name": {
    "label": "Profile name",
    "tooltip": "The name of the endpoint profile."
  },
  "readings": {
    "impact": "Changes the view only. It changes no setting.",
    "label": "Readings",
    "tooltip": "Shows the readings under the chart or on the chart."
  },
  "recent activity": {
    "impact": "Opens a panel. It changes no setting.",
    "label": "Recent activity",
    "tooltip": "Opens a panel with the 10 latest records of the controller."
  },
  "recipe name": {
    "label": "Recipe name",
    "tooltip": "The name of the recipe. The maximum length is 80 characters."
  },
  "record a batch": {
    "guidance": "If a fill entity counts the batches, record a batch only when that entity did not count it.",
    "impact": "Decreases the level of each stock tank by its dose for one batch. Tanks linked to a dosing pump do not change.",
    "label": "Record a batch",
    "tooltip": "Records a batch that you made by hand."
  },
  "record a run": {
    "guidance": "Record the real start date of the run. A run record cannot get back history that the Recorder deleted.",
    "impact": "Opens History, Grows at the run records. It does not change data.",
    "label": "Record a run",
    "tooltip": "Opens the run records in History, Grows, where you can record a run with its start date."
  },
  "recorded history could not load": {
    "guidance": "Select \"Retry history\". If the problem continues, examine the connection to Home Assistant.",
    "label": "Recorded history did not load",
    "tooltip": "The dashboard did not get the recorded history from Home Assistant."
  },
  "reference (": {
    "label": "Reference ({x})",
    "tooltip": "The known value of the reference solution, in {x}."
  },
  "reference rows": {
    "guidance": "Give the low and the high value of each band. A band with one value only is not kept.",
    "impact": "The room climate on a zone page shows a value in colour when it is outside the band of today.",
    "label": "Reference only",
    "tooltip": "Bands for the climate and the feed, for this profile. They drive nothing. The controller does not get them."
  },
  "refilled": {
    "guidance": "Use this only after you fill the tank to its capacity. For a different level, type the level that you read.",
    "impact": "Sets the level of the stock tank to its capacity and records the refill time.",
    "label": "Refilled",
    "tooltip": "Records that you filled the stock tank."
  },
  "refresh controller data": {
    "impact": "The dashboard reads the data again. It changes no setting.",
    "label": "Refresh controller data",
    "tooltip": "Reads the latest data of the controller again."
  },
  "remove recipe": {
    "guidance": "Export the recipe first to keep a copy.",
    "impact": "The dashboard deletes the recipe from this browser only. Home Assistant does not change.",
    "label": "Remove recipe",
    "tooltip": "Removes the recipe from the library of this browser."
  },
  "remove recipe {x}": {
    "impact": "Opens a confirmation. Nothing changes until you confirm.",
    "label": "Remove recipe {x}",
    "tooltip": "Opens a confirmation to remove the recipe {x} from the library of this browser."
  },
  "remove this room": {
    "guidance": "Set Watering to off and stop the hardware before you archive the room.",
    "label": "Remove this room",
    "tooltip": "Archive the room. The room keeps its IDs and configuration."
  },
  "remove {x}": {
    "guidance": "Make sure that another phone gets the emergency alerts before you save.",
    "impact": "Changes the draft only. After you save, the phone gets no more pushes from Crop Steering.",
    "label": "Remove {x}",
    "tooltip": "Removes this phone from the notification draft."
  },
  "retry": {
    "impact": "The dashboard reads the data again. It changes no setting.",
    "label": "Retry",
    "tooltip": "Reads the data again."
  },
  "retry history": {
    "impact": "The dashboard reads the history again. It changes no setting.",
    "label": "Retry history",
    "tooltip": "Reads the recorded history from Home Assistant again."
  },
  "review watering": {
    "caution": "CAUTION: Do not keep the kill switch at off while plants are in the room. The plants get no water, also no rescue shot.",
    "guidance": "Read the before and after values in the review before you confirm.",
    "impact": "On: the controller can give shots again. Off: the controller gives no shots.",
    "label": "Review the kill switch",
    "tooltip": "Confirms a change of the kill switch (\"Watering\") of the room.",
    "warning": "WARNING: Do not use this switch as an emergency stop. Use the physical shut-off of the installation."
  },
  "review zone scheduling": {
    "caution": "CAUTION: Do not keep a zone paused when plants are in it. The plants get no water.",
    "impact": "Paused: the zone gets no water, not a rescue shot, and a shot that runs now stops in a few seconds. Started: the controller waters the zone from its next check.",
    "label": "Review zone switch",
    "tooltip": "Review the change to the zone switch before you send it."
  },
  "room": {
    "impact": "The dashboard shows the readings and the settings of the room that you select. It changes no setting.",
    "label": "Room",
    "tooltip": "The room that the dashboard shows. Each room has its own lights, zones and kill switch."
  },
  "room camera": {
    "impact": "Shows an image only. It changes no setting.",
    "label": "Room camera",
    "tooltip": "A still image from the camera of the room. The image changes each 30 s while the page is open."
  },
  "room climate": {
    "guidance": "A value shows in colour only when it is outside the band of the grow plan for today.",
    "impact": "Shows values only. It changes no setting.",
    "label": "Room climate",
    "tooltip": "The air temperature, humidity and VPD of the room, from the sensors in Equipment › Setup. The dew point comes from the air temperature and the humidity."
  },
  "room configuration": {
    "label": "Room",
    "tooltip": "Select the room to configure."
  },
  "room day lanes": {
    "impact": "Shows recorded states only. It changes nothing.",
    "label": "Zones today",
    "tooltip": "Each zone on one time axis, from lights-on: the colour shows the phase, a mark shows a shot."
  },
  "room name": {
    "label": "Room name",
    "tooltip": "The name of the room on the dashboard."
  },
  "room on / off": {
    "caution": "CAUTION: Do not set the room to off when plants are in it. The plants get no water and no alerts.",
    "guidance": "This is not an emergency stop. Use the kill switch of the hardware for an emergency.",
    "impact": "Off: the controller does not water the room and sends no alerts for it. On after more than one day: the counters and the phase data reset.",
    "label": "Room on or off",
    "tooltip": "Set the room to off when no plants are in it. Set it to on for the next crop."
  },
  "root-zone temperature": {
    "impact": "Shows a value only. The controller does not use it.",
    "label": "Root-zone temperature",
    "tooltip": "The temperature in the substrate of this zone, from the probe in Equipment › Setup."
  },
  "run name": {
    "label": "Run name",
    "tooltip": "The name of the run. The maximum length is 80 characters."
  },
  "run records": {
    "impact": "Opens History, Grows at the run records. It does not change data.",
    "label": "Run records",
    "tooltip": "Opens the run records in History, Grows."
  },
  "run time · seconds": {
    "label": "Run time · s",
    "tooltip": "The time that the dripper ran into the cup, in seconds."
  },
  "safety limits:": {
    "guidance": "Read these limits before you change a shot size.",
    "label": "Safety limits",
    "tooltip": "The limits that hold, shorten or add a shot."
  },
  "save level": {
    "impact": "Writes the new level of the stock tank. The level cannot be more than the capacity.",
    "label": "Save level",
    "tooltip": "Saves the level that you read on the stock tank."
  },
  "save the check": {
    "guidance": "Examine the two reference values and the two probe values before you save.",
    "impact": "The integration records the check. The check changes no probe reading.",
    "label": "Save the check",
    "tooltip": "Saves this probe check in the calibration history."
  },
  "save to library": {
    "guidance": "Export the recipe to keep a copy for a different browser.",
    "impact": "The recipe goes into the storage of this browser only. Home Assistant does not change.",
    "label": "Save to library",
    "tooltip": "Saves the recipe in the library of this browser for this room."
  },
  "send a test to {x}": {
    "guidance": "Examine the phone after the test. If the test was not sent, read the reason on the dashboard.",
    "impact": "Sends one test notification. It does not change the settings.",
    "label": "Send a test to {x}",
    "tooltip": "Sends a test notification to this phone."
  },
  "settings the ai changed that go back by themselves": {
    "caution": "CAUTION: Examine the old value and the new value before you keep a change. A wrong setpoint can give too much or too little water.",
    "guidance": "Select \"Keep\" to keep a change. Select \"Undo\" to return to the old value now.",
    "impact": "Keep and Undo each open a review. The setting changes only after you confirm the review.",
    "label": "Temporary AI changes",
    "tooltip": "The settings that the AI assistant changed for a short time. Each setting returns to its old value by itself."
  },
  "source url (optional)": {
    "label": "Source URL (optional)",
    "tooltip": "The web address where the recipe came from."
  },
  "start date": {
    "label": "Start date",
    "tooltip": "The first day of the run."
  },
  "steering balance": {
    "guidance": "Save and arm the plan to use the change. Examine the VWC and the dryback for some grow-days after the change.",
    "impact": "Increase: the targets move to the generative endpoint. Decrease: the targets move to the vegetative endpoint.",
    "label": "Steering balance",
    "tooltip": "The balance between the vegetative and the generative endpoints, in % generative."
  },
  "substrate preset": {
    "guidance": "Examine the volume after you select a preset.",
    "impact": "The preset puts its volume in the substrate volume field. Custom lets you type the volume.",
    "label": "Substrate preset",
    "tooltip": "Selects a typical substrate volume for each plant."
  },
  "take the tour again": {
    "impact": "Shows the tour. It does not change data.",
    "label": "Show the tour again",
    "tooltip": "Starts the dashboard tour again."
  },
  "take {x} out of the recipe": {
    "guidance": "Examine the order and the volumes of the recipe before you save.",
    "impact": "The change stays in the dosing draft until you save it.",
    "label": "Remove {x} from the recipe",
    "tooltip": "Removes {x} from the batch recipe."
  },
  "tank ec and ph are not mapped": {
    "guidance": "Map the EC sensor and the pH sensor of the tank in Rooms and setup.",
    "label": "No feed EC or pH",
    "tooltip": "The room has no mapped EC sensor or pH sensor for the tank."
  },
  "target reference": {
    "label": "Target reference",
    "tooltip": "Select the targets that the chart shows as reference lines."
  },
  "tell me when a room has watered nothing for": {
    "impact": "Increase: the alert comes later. Decrease: the alert comes sooner.",
    "label": "Alert after no shot for",
    "tooltip": "The time without a shot that starts the alert."
  },
  "test shot": {
    "caution": "CAUTION: Make sure that the drippers are in the substrate or in a container before a test shot. Loose drippers can flood the area.",
    "guidance": "Watch a dripper while the shot runs.",
    "label": "Test shot",
    "tooltip": "A 10 s shot through the safety checks of the controller. The kill switch (\"Watering\") must be on for the test shot."
  },
  "the grow day could not load": {
    "guidance": "Select \"Retry\". If the problem continues, examine the connection to Home Assistant.",
    "label": "Grow-day did not load",
    "tooltip": "The dashboard did not get the data for the grow-day."
  },
  "the tank level is not charted": {
    "guidance": "Map a tank level sensor that reports in %.",
    "label": "Tank level not on chart",
    "tooltip": "The tank level sensor does not report in %, so the dashboard does not draw it."
  },
  "the tank level sensor is missing": {
    "guidance": "Examine the entity ID in Rooms and setup.",
    "label": "Tank level sensor missing",
    "tooltip": "Home Assistant does not have the mapped tank level entity."
  },
  "the tank’s history could not load": {
    "guidance": "Select \"Retry\". If the problem continues, examine the connection to Home Assistant.",
    "label": "Tank history did not load",
    "tooltip": "The dashboard did not get the tank history from Home Assistant."
  },
  "this run": {
    "label": "This run",
    "tooltip": "The run that you compare with a past run."
  },
  "through date": {
    "label": "End date",
    "tooltip": "The last date of a custom range. The range includes this date."
  },
  "try a valve-open runtime · seconds": {
    "impact": "The dashboard calculates the water for this time. It opens no valve and changes no setting.",
    "label": "Example valve-open time · s",
    "tooltip": "A valve-open time, in seconds, for this calculation only."
  },
  "type the room name to confirm": {
    "caution": "CAUTION: Make sure that no plants are in the room before you archive it. An archived room gets no water.",
    "impact": "When the name is correct, you can archive the room.",
    "label": "Type the room name",
    "tooltip": "Type the room name to confirm that you archive this room."
  },
  "unsaved draft": {
    "guidance": "Review and save the change, or discard it.",
    "label": "Unsaved draft",
    "tooltip": "You changed this setting, but you did not save the change."
  },
  "update zones from setup": {
    "guidance": "Disarm the plan and wait for the draft status before you update the zones. Examine the endpoints of each new zone before you save.",
    "impact": "Changes the local draft only. You must save the draft before you arm the plan.",
    "label": "Update zones from setup",
    "tooltip": "Adds the zones of the room setup to the plan draft and removes the archived zones."
  },
  "use 60% …": {
    "guidance": "Examine the suggestion before you use it.",
    "impact": "Only the draft changes. The setting changes after you review and save the draft.",
    "label": "Use {x} …",
    "tooltip": "Puts the suggested value into the local draft of this field."
  },
  "vegetative and generative endpoints": {
    "guidance": "Set the endpoints for your substrate, cultivar and growth stage.",
    "label": "Vegetative and generative endpoints",
    "tooltip": "The setpoints at 0% and at 100% generative. The steering balance sets a value between these endpoints."
  },
  "water caught from one dripper · ml": {
    "label": "Water from one dripper · mL",
    "tooltip": "The water that one dripper gave in the catch test, in mL."
  },
  "water records could not load": {
    "guidance": "Select \"Retry\". If the problem continues, examine the connection to Home Assistant.",
    "label": "Water records did not load",
    "tooltip": "The dashboard did not get the water records from Home Assistant."
  },
  "water today, shown as": {
    "impact": "Changes the display for all users of this room. It does not change the shots.",
    "label": "Water today display",
    "tooltip": "Select how the zone pages show the water of today. The vitals notification uses the same unit."
  },
  "watering": {
    "caution": "CAUTION: Do not keep Watering off for a long time when plants are in the room. The plants get no shots, not a rescue shot.",
    "guidance": "A new room starts with Watering off. Examine the hardware before you set Watering to on.",
    "impact": "Off: the controller opens no valve in the room, and a shot that runs now stops in a few seconds. On: the controller gives shots again.",
    "label": "Watering",
    "tooltip": "The kill switch of the room. It lets the controller water the room."
  },
  "what the ai assistant may do": {
    "guidance": "Only a Home Assistant administrator can change these switches.",
    "impact": "On: the AI assistant can make this change. Off: the AI assistant only advises. It does not change that part.",
    "label": "What the AI assistant may do",
    "tooltip": "When a power is off, the AI assistant only advises. It does not change that part."
  },
  "work out dripper flow from a catch test": {
    "guidance": "Start and stop the water yourself. Let one dripper run into a cup with a scale for a known time.",
    "impact": "The calculator does the arithmetic only.",
    "label": "Calculate dripper flow",
    "tooltip": "A calculator that gives the dripper flow from a catch test. It does not open a valve or start a pump."
  },
  "zone": {
    "label": "Zone",
    "tooltip": "The name of the zone."
  },
  "zone grow start date": {
    "impact": "Changes the local draft only.",
    "label": "Zone start date",
    "tooltip": "The date of grow-day 1 for this zone."
  },
  "zone limits": {
    "label": "Zone limits",
    "tooltip": "Select the zone whose limits apply to the profile values."
  }
} as const satisfies Record<string, SteCopy & { label: string }>;

export type UiCopyKey = keyof typeof UI_COPY;
