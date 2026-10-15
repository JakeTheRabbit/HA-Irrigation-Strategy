# User guide

The menu has five items:

- **Today** tells you if the room is correct and which zone needs you.
- **Plan** has the **Targets** of the zones and the **Schedule** of the grow plan.
- **History** has the **Timeline**, **Water use** and **Compare runs**.
- **Equipment** has **Probes**, **Stock tanks**, **Tank and feed**, **Dosing** and **Setup**.
- **Settings & help** has **Settings**, **Notifications** and **Help**.

Each zone has its own page. Open it from the card of the zone on **Today**. Select the room before you change a value. The zone numbers belong to that room.

Old bookmarks open the page that now has their content:

| Old address                            | Opens                                   |
| -------------------------------------- | --------------------------------------- |
| `#/overview`, `#/zones`                | Today                                   |
| `#/strategy`                           | Plan › Targets                          |
| `#/grow-plan`                          | Plan › Schedule                         |
| `#/activity`                           | History › Timeline                      |
| `#/compare`                            | History › Compare runs                  |
| `#/sensors`, `#/insights`              | Equipment › Probes                      |
| `#/stock`                              | Equipment › Stock tanks                 |
| `#/setup`                              | Equipment › Setup                       |
| `#/settings`, `#/help`, `#/help?code=` | Settings, Help (and the code it names)  |
| a retired dashboard's `?view=`         | the page that replaced that view        |

For a new installation, start with [Install, upgrade and rollback](INSTALL.md). To try the dashboard with no equipment, open the [interactive demo](https://jaketherabbit.github.io/HA-Irrigation-Strategy/dashboard.html?demo=1).

## What each action changes

| Action | Where the change goes |
| --- | --- |
| Change targets (Plan › Targets) | A local draft. Nothing goes to Home Assistant before the review. |
| Apply the reviewed changes | The setpoint entities in Home Assistant. Examine the readback. |
| Substrate, sizing and safety numbers | Equipment › Setup. The same review applies. |
| Review & save a grow plan | The stored draft plan in Home Assistant. This does not arm the plan. |
| Arm plan | A request to start the plan at the next lights-on. It does not set the kill switch to on. |
| Save a library recipe | The library of this browser, site and room. It writes nothing to Home Assistant. |
| Save a run record (Settings › Run records) | The run data and its reference. It starts no shots. |
| Save configuration (Equipment › Setup) | The setup of the room and its zones in Home Assistant. Wait until the controller accepts it. |
| Dose, make a batch, stop (Equipment › Dosing) | A request that the controller does. The page itself operates nothing. |
| Save the dosing setup (Equipment › Dosing) | The stored dosing setup of the room in Home Assistant. The controller reads it. |
| Save notifications (Settings & help › Notifications) | The stored notification setup of the whole site. The next push follows it. |
| Send a test (Settings & help › Notifications) | One push to that phone. Nothing is saved. |

## Try the demo

The demo is a software demonstration only. Its readings, history, plans and run records are sample data. They are not a recommended configuration, and they do not come from a real grow. A demo tab cannot connect to Home Assistant. The demo follows the time of day: at night, the zones are in P3 and the pump is off.

1. Open **Today**. Select a room with the chips in the top bar.
2. Read the room line, the zone cards and the changes of the AI assistant. Open a zone from its card.
3. On the page of the zone, point at the shots and the marks of the AI assistant on the chart.
4. Select **Compare with** yesterday or a typical day. Read the probes and the controls.
5. Open **Plan › Targets**. Select a zone, and change its rescue floor or its re-water point.
6. Compare the draft line with the saved reference. Then examine the change in the review.
7. Open **Plan › Schedule** and read the flower by stage.
8. Open **Advanced** to change the steering balance of a week, or to examine an endpoint profile.
9. Open **Recipes**, and preview **Demo • steady schedule** or **Demo • week-by-week changes**. A recipe loads into a local draft only.
10. Open **History**. Filter the **Timeline**, read **Water use**, and open **Compare runs**.
11. Open **Equipment › Setup**. Try the entity search, the room and zone names and the mapping review.
12. Open **Equipment › Dosing**. Dose a pump, make a batch and stop it. The demo moves faster than real time.
13. Open **Settings & help › Notifications**. Tick a kind of alert for a phone, save it through the review, and send a test.

The demo sends nothing to your Home Assistant server and no push to a phone. To see the Notifications page as a grower who is not an administrator, add `&notify-user=grower` to the address.

A production recipe library starts empty. The demo recipes are examples, and the dashboard keeps them apart from production libraries. It does not change the demo libraries that exist, also when they are empty or corrupt.

To restore the sample rooms, readings, run records and planner drafts, use **Settings › Sample workspace › Reset demo session…** and confirm. The reset discards the demo work that you did not save. It keeps all saved recipe libraries and the live connection data. It does not restore a recipe that you removed. Export the session work that you want to keep before the reset.

## The top bar

The top bar is on each page. It shows each room as a chip with a dot and a word: watering, holding, not watering, stale or room off. The chip of the selected room is pressed. Select the chip of a different room to open that room.

Next to the chips, the top bar shows these items:

- The age of the last report of the controller for the selected room.
- **Recent activity**: the newest records, in a panel next to the page, with **Open the timeline**.
- The refresh button.
- The two safety switches of the room, **Watering** and **Room**. Each switch shows a review before it changes.

> **WARNING:** Do not use the **Watering** switch or the **Room** switch as an emergency stop. In an emergency, use the physical shutdown procedure of your installation.

## Today

**Today** is one screen on a laptop and about two screens on a phone.

- **The room line** shows the **Watering** switch, the stage and the day of flower, and the steering mode. The stage shows only when the controller publishes the stage arc.
- The room line also shows the pore EC band of the stage, the lights, the phases of the zones and the open alerts.
- **N alerts** opens the list of alerts. **N notes** opens the list of notes, for example a grow plan in control.
- When the room gives no shots, the room line tells you which switch stopped them. A button opens that switch in Settings.
- **The tanks** show in one line only when a feed tank or a stock tank is low or out of range.
- **The card of each zone** shows its phase and its VWC, with the line of the day. A bar shows the VWC against the rescue floor, the re-water point and the peak.
- The card also shows the pore EC, the water for each plant against the room, the last shot and the next event.

A card has a flag, with the reason in one line, only when the zone needs you:

| Flag | When |
| --- | --- |
| Pore EC below or above the band of the stage | The pore EC of the zone is outside the band of the stage of today. |
| Water for each plant against the room | More than 140% or less than 70% of the median zone of the room, after the grow-day has started. |
| Below the re-water point with no shot (critical) | In P2, VWC stayed below the re-water point for more than one hour with no shot. |
| A probe that the zone cannot use, or leaves out | A VWC probe that the zone cannot use (critical). A pore EC probe that the zone cannot use, or a probe that the zone leaves out (warning). |
| An alert of the zone | An alert that the controller sent for this zone. |
| A rescue shot | A rescue shot in the last 12 hours. |
| Jev’s setpoint changes paused | The AI assistant put a change back after a rescue shot, and it waits before it tries again. |

- **AI assistant changes today** shows the last three changes of the AI assistant, newest first. **History** has the rest.

## A zone's page

Open a zone from its card on **Today**, or with the address `#/zone/N`. Use the switcher at the top to go to a different zone. The page has these parts.

**Today in numbers**

- The VWC and its dryback rate.
- The pore EC against the band of the stage.
- The water today: the total of the zone and the water for each plant, in the order that Settings › Appearance selects.
- The water today as a part of the daily water limit. It shows amber from 80%. The maintenance shots stop at the limit.
- The shots today and the time of the last shot.
- The overnight dryback, of last night or of tonight so far, against the reference dryback of the stage. The reference is a percentage of the peak of this zone.
- **Next**: the next event, in some words.

**The day chart**

The chart shows the grow-day, from lights-on to the next lights-on:

- The light cycle is at the top. The decisions of the AI assistant are below it. A filled mark is an action. An outline is advice, no action or a refusal.
- P0 to P3 are columns, with their badges at the bottom.
- A dashed red line shows field capacity, with the runoff zone of the steering mode above it.
- A band shows the maintenance range, from the re-water point to the peak target. The rescue floor shows overnight.
- A blue line shows VWC. A dot is the start of a shot. A ring is a shot that the controller held.
- A dashed line shows the expected rest of the day.
- The pore EC uses the scale at the right, with the band of the stage next to it.

The VWC scale fits the readings of today and the targets of the zone. **Compare with** adds the line of yesterday, or the typical day of the last seven days. The browser keeps this choice. Point at the chart, or tap it, to see the details of a shot, a decision, a phase or a time.

**AI assistant on this zone**

This panel shows the judges that act on the zone now. It shows the P2 shot size and the re-water point that the AI assistant can move, and their range. It also shows the last change and the newest decisions on this zone. A tick or a cross shows the later check of the result. **History** opens the timeline of this zone.

**Targets**

The targets of the zone, by phase, as the controller uses them. The range of the AI assistant shows next to the values that it controls. **Edit in Plan** opens them in Plan › Targets.

**Probes**

Each VWC probe and pore EC probe of the zone, with its reading. The panel also tells if the zone uses the probe (see [Probes](#probes)).

**Controls**

- The next conditions of the controller, from its own numbers. Example: shot when VWC < 61% (now 58%) · dilution if pwEC > 3.84 · P3 by 20:36.
- **Pause zone scheduling** and **Enable zone scheduling**: the switch of the zone. When the zone is paused, the controller gives the zone no shot, not even a rescue shot. A shot that runs in the zone stops within a few seconds.
- **Move to a phase**: moves the zone to a phase by hand, after a review. The controller moves the zone within a minute and then continues by its rules. Lights-off still moves the zone to P3, and lights-on moves it to P0. The water and the shot count of the grow-day stay.

> **CAUTION:** Do not pause a zone that has plants. The zone then gets no water, not even a rescue shot.

**History**

The readings of the zone for **Yesterday** or **7 days**. **Recorded behaviour against the targets** shows the typical peak, low point and dryback over some days. It opens when you select it.

## Plan › Targets

When no grow plan controls the room, **Targets** changes the current targets. An armed grow plan shows its own targets, and you cannot change them here. When the plan has no current snapshot, the targets show as unavailable. They do not go back to the manual values.

1. Select a room and open **Plan › Targets**.
2. Select a zone, or select **Room** for the timing that all zones use.
3. Read the targets of the zone. The table has one part for each phase: P0 morning dryback, P1 ramp, P2 maintenance and P3 overnight dryback.
4. Select the **?** of a setting to read what it does, when it acts and what it changes.
5. Type a value, or move a target on the day chart next to the table. Both change the same local draft.
6. Select **Review changes**. Examine each old value and each new value.
7. Apply the changes. Only this step sends the values to Home Assistant.
8. Examine the readback. A value that Home Assistant did not accept stays visible with its error.

The draft follows the limits and the step of each Home Assistant number. The chart shows the saved values as a reference. The dark lines show what the probes of the zone recorded. A draft stays after a refresh. When you change the room, the dashboard asks before it discards the draft.

The targets of the other steering mode (its P3 dryback and its EC targets) are one tap down. The substrate, the plants, the drippers, the flow and the safety limits are in **Equipment › Setup**.

When the AI assistant controls a value, its range shows next to the value. The **Auto** switch is the Auto setpoints switch of the room. When the Setpoints judge of the AI assistant runs, the AI assistant controls the P2 shot size and the re-water point. The Auto setpoints learner of the controller controls the peak target and field capacity. It moves each by 1 point or less each grow-day.

> **CAUTION:** Do not set the Auto switch to on while a probe gives wrong readings. The setpoints can then move in the wrong direction.

You can preview a change of the room against a selected zone. The value of a zone overrides the value of the room for that zone. A value that is missing or not correct stays missing on the chart. The dashboard does not make up a curve.

## Plan › Schedule

**This flower by stage** is at the top of the page. It shows the stages of this flower: flower set, flower bulk and finish. For each stage, it shows the flower days and weeks, and what starts the next stage. It also shows the steering mode, the pore EC range, the overnight dryback and the runoff. The overnight dryback is in points of true water content: 15 to 25 in flower set, 10 to 15 in flower bulk and 20 to 25 in the finish. The table marks the week of today and the start of the next stage. Day 1 is the first day of 12 hours on and 12 hours off. The AI assistant uses this stage arc. **Validate preview** and **Arm plan** stay below it.

The planner schedules user-defined profiles by zone and grow day, under **Advanced**. The balance slider interpolates between the profile's explicit vegetative and generative endpoints; it does not select a built-in agronomic prescription. Equal endpoints intentionally produce equal targets at every slider position.

1. Open **Advanced › Endpoint profiles**. Inspect both endpoints and select the correct **Zone limits**. Duplicate a profile when you need an independent copy. A shared profile affects all schedule blocks referring to it.
2. Open **Advanced › Steering balance**. Select a zone and set **Zone start date**. Each zone can have its own start date.
3. Select a day or week in the grid, or type a balance (0–100 % generative) into it: Enter applies, Esc cancels, arrows move. The panel beside the grid shows the setpoints at that balance next to both endpoints and the balance either side. Assign the block's **Endpoint profile**. Days 1–366 are supported; range edits preserve surrounding assignments by splitting existing blocks.
4. Inspect **Zone schedule blocks** for coverage. Fill missing days and resolve overlap, parameter or zone-assignment errors.
5. Choose **Review & save** to validate and persist the draft in HA. **Validate preview** checks an unchanged stored draft. **Export** downloads a portable plan; **Reload stored plan** retrieves the stored revision once local edits are saved or discarded.
6. To let the controller use the plan, select **Arm plan** and examine the review. The controller must report that it supports plans. The plan starts at the next local lights-on. The arm action does not set the kill switch to on, and it does not start the pump.

You cannot change an active or armed plan as a draft. **Disarm plan** asks the controller to go back to the manual targets at the next lights-on. Wait for the **draft** status before you change the plan. The dashboard reports a controller with no plan support, a stale snapshot and an incomplete handoff. It does not show the plan as active. Only a Home Assistant administrator can save, arm or disarm a plan. Other users can open the plan and its previews, but they cannot change them.

After adding or archiving zones in setup, use **Update zones from setup** in a draft plan. It preserves existing active-zone schedules, removes archived assignments, and initializes new zones from their current settings. Export the previous plan first if you need those removed assignments.

### Recipes

**Advanced › Recipes** is the recipe library. A library item is a reusable copy, separate from the HA plan currently controlling the room.

- **Save current as recipe** creates a named browser copy with optional notes/source URL.
- **Import recipe file** accepts the supported plan export format, validates it and lets you name the library copy.
- **Preview recipe** shows its zones, retained current start dates, schedule spans and inspectable profiles. **Load into local draft** requires the exact current active-zone IDs and preserves current start dates. Replacing unsaved planner work requires explicit acknowledgement.
- Loading is unavailable while active, armed, busy or disconnected. It does not save or arm the plan.
- **Export recipe** downloads a copy. **Remove recipe** asks for confirmation and removes only the browser copy.

Libraries are isolated by site, browser, room and demo/live mode. They are not a shared HA database. Limits are 20 recipes per room, 500 KB per plan and 2 MB per library. Export important copies before clearing browser data or moving to another browser. Corrupt data is retained with a recovery-download action; storage denial, quota and stale-tab conflicts are reported rather than silently overwritten. See [Recipe library](RECIPE_LIBRARY.md).

## History

**Timeline** is one list of the records of the controller and the decisions of the AI assistant, newest first, by day.

- The actions of the AI assistant show by default. **All Jev decisions** adds each answer. Each answer shows the confidence, the request and the action of the code: acted, refused with the reason, advice, no action or waiting.
- A tick or a cross next to a decision is the later check of the result.
- A setpoint that you changed is marked as yours. The AI assistant only records it.
- Filter by zone or by the room only, by type (water, phase, setpoints, alerts, Jev) and by words.
- **Export CSV** downloads the records that the filters show.

The timeline is not a full record of each physical shot.

**Water use** shows litres per zone today, this grow week, since the grow start and estimated for the whole grow, with a bar for each grow week and, under it, today's water per zone and per plant. It counts grow-days from lights-on to lights-on and reads Home Assistant's long-term statistics, which Home Assistant keeps indefinitely; opened outside Home Assistant it can only read recorded history, as far back as the recorder keeps it. The grow start is the zone's grow plan start date when the plan is armed or has been saved; without one it is inferred (the first day with water after at least five grow-days without any), and the panel says which. A day Home Assistant did not record is flagged, never counted as zero.

**Compare runs** lines the run in progress up against an earlier one by grow week:

1. Choose **This run**, **Compare with** and the **Zone**. The latest ended run is chosen to start with.
2. Read the weeks table. For each week, it shows the typical day: VWC low to high, pore EC low to high, and water for each plant in a day. The figure of this run is above the figure of the compared run. **Largest differences** names up to three weeks with a large difference. A large difference is more than a few points of VWC, a few tenths of pore EC, or a fifth of the water.
3. **Full-resolution chart, with a target reference** (one tap down) draws the recorded VWC and EC for **Day**, **Week · 7 days**, **Calendar month**, **Run to date** or **Custom dates**. Choose a **Target reference**: **Current configured daily plan**, **Saved run daily reference**, or **Current phase reference**, and read its capture/source note. Use **Refresh history** to advance the window.
4. **Data quality and history coverage** (one tap down) shows the recorded range of each day as bars on one scale. The compared run is grey. The section also shows the source of the weekly figures.

Run records themselves are kept in **Settings › Run records** (**Run records** on Compare runs goes there): **Add run** with the actual name, start date and optional end date, then **Save run record**. This saves metadata and a timestamped reference configuration; it does not arm irrigation. **Export metadata** backs up run definitions and reference snapshots, not Recorder readings. **Archive** and **Restore** keep the registered run's identity. Saving, archiving and importing run records need a Home Assistant administrator login; any login can view them. Registering last month's run today captures today's reference configuration: it cannot recover last month's setpoints or expired Recorder data. Each room supports up to 100 run records; a completed run covers 1–366 inclusive calendar days.

## Equipment

### Probes

The top of the page shows the number of correct probes, the report status of the controller and the status of the AI assistant. Below that, each zone shows its probes. Each probe shows these items:

- Its name, with the entity ID below it.
- Its reading, the time of its last report and its line of the last six hours.
- If the zone uses its reading.
- Its health.

| Health | Meaning |
| --- | --- |
| OK | The probe reports, the reading is in range, and the reading changes as a probe reading does. |
| Silent / Not reporting | The integration says that the probe stopped its reports, or the zone reading is stale. The page shows since when. |
| Out of range | The reading is outside the range of the integration (0 to 100% VWC, 0 to 20 mS/cm EC). It cannot be real. |
| No reading | The reading is unavailable, unknown or not a number. |
| Unchanged for | The reading did not change for more than 3 h (VWC) or 6 h (pore EC). The probe is probably stuck. |
| Left out | The integration combined the other probes of the zone without this probe. It gives the reason. |

An older integration publishes only the combined reading of each zone. The page then shows that reading in place of the probes. The valve of each zone shows next to its probes.

**Room map** and **All sensors of this room** are one tap down. **All sensors of this room** shows each sensor of the room with its reading, its last hours and its availability. You can search and filter it. **Map probes** opens **Setup**.

### Stock tanks

**Next to run out** leads: the tank with the fewest batches left. Each tank shows its level against its low mark (amber within half again of it, red at it), with **Refilled**, **Set level** and the batches left. A tank linked to a dosing pump (in **Equipment › Dosing › Dosing setup**) says **Drawn by** that pump **as it doses**, with its recent draws: Crop Steering takes what the pump actually ran off it, whoever started the dose (the controller, an automation, or someone at the doser), and the tank's fills no longer count against it; its batches left are at the pump's recipe amount. **Record a batch** takes the recipe's doses off every tank; recent draws are one tap down. **Edit stock tanks** adds, renames and removes tanks.

### Tank and feed

**Equipment › Tank and feed** shows the level, the EC, the pH and the temperature of the feed tank. EC and pH have a line of the last day. The page also shows the pump state and the last recorded fill. The old Tank & pump address still opens it. **History** opens both readings over 24 hours, 7 days or 30 days. It shows the feed-water gate where the room gates on those probes. Select **Map sensors**, or open **Equipment › Setup › Shared room hardware**. These are explicit mappings. The dashboard does not guess that a room-temperature or feed-water probe is a tank probe.

**Tank minimum**, under the tank, says in words what the [reservoir minimum](#reservoir-minimum) is doing: watering allowed, watering held at the minimum or on a level it can't read, or filling stopped over the full mark, with the alert code linked to Help. It shows the minimum and the level watering starts again at, about how many litres are left above the minimum once the litres per 1 % are learned, and the batch on the tank (the step running now, or how the last one ended) with a link to **Dosing**. A room with no tank level mapped for the controller says the minimum is off and links to setup.

**Tank level and shots**, under that, draws the level over 12 hours, 24 hours (the default), 3 days or 7 days. It also shows what moved the level:

- The shots of each zone are dots on the line. Across 7 days, the shots in the same hour share one dot.
- The pump runs and the tank fills are bars above the line.
- Each recorded fill is a dashed line.

Two levels go across the chart. One is the tank minimum, in a room whose tank level the controller reads. The other is the refill reminder, when the dosing setup reads its reminder on this level. Hover over a mark or tap it to see what it was. For a shot, it shows the zone, the valve open time and about how many litres that is at the configured flow. For the pump or a fill, it shows the run time. The list under the chart names each event in the range. The chart reads the Home Assistant recorder, as the Today chart of a zone does, and it updates when new readings come.

The level is the value that the mapped level sensor reports. The dashboard cannot tell if that sensor measures the water or calculates it, for example from the pump run time since the last fill. The chart says this. Shots are valve open times. The pump bars and fill bars are the reports of the switches. A recorded fill is a newer time on the last-fill record. A restart that records the same time again is not a fill.

| Setup label             | Configuration key         | Select                                                                                                                |
| ----------------------- | ------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Room pump               | `pump_switch`             | The room pump's actual HA switch, `input_boolean` or valve. The controller descriptor publishes this as `pump`.       |
| Tank fill level (%)     | `water_level_sensor`      | A percentage sensor, 0-100. A litres value is not a percentage.                                                       |
| Tank EC (display)       | `tank_ec_sensor`          | A tank conductivity sensor in mS/cm or dS/m accepted by setup.                                                        |
| Tank pH (display)       | `tank_ph_sensor`          | A pH sensor.                                                                                                          |
| Tank temperature        | `tank_temperature_sensor` | A tank-water temperature sensor in °C, °F or K; its unit is retained.                                                 |
| Tank filling status     | `tank_fill_entity`        | A fill-valve switch or binary sensor whose on/off state represents fill activity.                                     |
| Last recorded tank fill | `tank_last_fill_sensor`   | A timestamp sensor with a dated, timezone-aware state, or an `input_datetime` helper with both date and time enabled. |

**Tank EC (display)** and **Tank pH (display)** only populate the panel. **Feed-water EC** and **Feed-water pH** are separate mappings used by configured control gates. Mapping a tank display does not enable those gates or nutrient dosing.

**Last recorded fill** has the meaning supplied by your existing recording automation: for example, a verified full-float event or an operator's explicit “mark filled” action. A full date/time helper uses its timestamp attribute; a sensor's `last_changed`, an automation's `last_triggered`, a fill-mode enable flag and a dosing interlock are not equivalent to a fill record. The panel does not create a fill-recording automation for you. A percentage source may itself be an estimate; drawing it as a tank does not turn it into a measured level. Tank readings and switch reports do not prove dose completion, water quality suitability or physical delivery.

Unmapped inputs show **Not mapped**; invalid readings show **Unavailable**, **Check units** or **Out of range**. An unknown pump is not shown as off and an unknown tank is not drawn empty. When disconnected, the panel identifies retained readings as last received.

#### Tank level for the controller

The percentage sensor above only draws the tank. For the controller to read the tank's level, map a **tank distance sensor** (`tank_distance_sensor`: an ultrasonic or radar sensor reporting the distance down to the water), a **low float** (`tank_low_float`: a binary sensor), or both, through the setup API's `hardware`, with the room's `tank_level`:

| `tank_level` field | Meaning |
| --- | --- |
| `full_mm` | The distance sensor's distance down to the water when the tank is full, in millimetres. Required with a distance sensor. |
| `empty_mm` | The same when the tank is empty; further than `full_mm`. Required with a distance sensor. |
| `float_low_state` | `on` (the default) or `off`: the float's state that means the tank is low. |

The distance sensor's unit must be mm, cm, m, in or ft; it is converted to millimetres through the device-unit table, so the same tank reads the same level whatever unit its sensor reports. A sensor in any other unit, or none, is refused at mapping. The level is 0 % at `empty_mm` and 100 % at `full_mm`, and reads over 100 % above the full mark. The controller reads it once a loop and publishes it as `sensor.crop_steering_tank_level` ([ENTITIES.md](ENTITIES.md)); the reservoir minimum below acts on it. The batch tank's full float in the dosing setup is not a level and is not read here.

The sensor is trusted unless it is unavailable, because many sensors send a reading only when it changes, so a quiet tank's sensor can go hours without one. What the controller checks instead is the drawdown: it counts the litres the shots draw against the level's fall. Each time the level falls 5 %, it learns the litres drawn per 1 % of level from it. Once it knows them, shots that should have lowered the level by 5 % or more while it moved less than a quarter of that mean the sensor is stuck: its level is published as unknown, the log says why, and it is trusted again when it falls 5 % or a refill raises it. Until the tank has fallen 5 % once with the shots counted, a stuck sensor cannot be told from a full one. Mapping a level does not put the sensor behind the safety gate.

#### Reservoir minimum

When a tank level is mapped, the controller does not let the pump empty the tank, and does not let a fill overflow it. A room with no tank level mapped never gets these holds. After an update, no room has a tank level mapped until a person maps one. The full float of a batch tank does not count as a tank level.

| What | When | What occurs |
| --- | --- | --- |
| Minimum | The level is 8% or less, or the low float reads low. | The controller holds each zone (CS-901) until the level is 12% or more and the float does not read low. The two levels stop a level near 8% from starting and stopping the room each minute. |
| Level unknown | The distance sensor or the float gives no usable reading, or the drawdown check finds a stuck sensor. | The controller holds each zone (CS-902) until the sensor reads again. |
| Plan-ahead refill | One more round of shots would take the level to 8% or less, at the learned litres for each 1% of level. | CS-903 asks for a refill, and the shots continue. A shot that alone takes the level to 8% or less waits until the refill. The controller plans nothing before it learns the litres for each 1%. |
| Overfill guard | The level is 102% or more. | The controller closes the fill valve of a batch, and opens no fill valve, until the level is 98% or less (CS-904). The shots continue. |

> **CAUTION:** Keep the tank above 12%. At 8% or less, the room gets no shots, rescue shots included.

The controller keeps the minimum and overfill states in `/data/state.json`, with the drawdown check. After a restart with the level between two marks, the hold stays as it was. The tank level sensor shows them in its `below_minimum`, `over_full` and `minimum_pct` attributes.

### Dosing

**Equipment › Dosing** runs the room's batch tank: it doses one pump by hand, and it makes a batch (fill the tank, mix it, dose each nutrient in order, mix again). Each room has its own page for its own tank. The page switches nothing itself: every action is reviewed, then sent as a request that the controller carries out within a few seconds. A request the controller could not take within two minutes is dropped, so nothing starts later by surprise. The pumps' own firmware times each dose: Home Assistant sets the amount and presses start, and the controller switches a pump's power off only if it runs past its time.

- **The tank**, in one line: its level, whether the float reads full, EC, pH and temperature (from the room's tank mapping), and what the batch is doing.
- **Stock**: every stock tank a pump is linked to, in pump order, with its level, its litres and about how many batches it has left, its low mark drawn. **Stock tanks** opens them.
- **A card per pump**: the pump drawn (its rotor turns while it doses), its name and device, its state, its last dose, its calibrated flow in mL/s, and the stock tank it is linked to: drawn to scale, with its litres and about how many batches that is at its recipe amount (or doses at its last dose, when the recipe passes the pump by). The bottle turns amber, with **Low**, at the tank's low mark and red, with **Very low**, at half of it. A bar fills while it doses. Choose a card to dose that pump.

| State          | Meaning                                                                                  |
| -------------- | ---------------------------------------------------------------------------------------- |
| Idle           | Ready to dose.                                                                           |
| Dosing         | The controller or the pump itself says it is dosing.                                     |
| Not calibrated | Its flow reads nothing or 0 mL/s, so the controller will not start it. Calibrate it first. |
| Unavailable    | Greyed out with a question mark: the controller is not reporting, or one of the pump's entities is missing or unavailable. The card says which. |

- **Dose a pump**: type the mL, up to the pump's largest dose; the page says how long it takes at the pump's flow. **Start** opens the review. The dose goes into the tank as it is, and watering carries on. While it runs, the pump's **status** shows the target, the elapsed time and the mL so far, worked out from the time and the flow.
- **Make a batch**: the steps, each marked done, now, passed by or to come, beside the recipe with each pump's mL, the total and the time it takes. **Make a batch** opens the review. Watering is held in the room, and in any room whose pump or valves the batch uses, until the batch finishes or is stopped. A pump in the recipe that cannot dose now is named before you start: the batch would stop at its dose, after filling and mixing. An amount read from an entity that reads nothing is named too, and no batch is made: the controller would refuse it.
- **Stop dosing** and **Stop the batch** send one stop: every dosing pump in the room is switched off, and a running batch ends with the fill valve closed, the mixing pump off and watering released. It replaces any request still waiting.
- **History**: the last doses and batches, what each dosed and how it ended.
- **Dosing setup** (one tap down): each pump's dose volume, start, dosing state, power switch, calibrated flow and stock tank (one pump to a tank); the batch hardware (fill valve and float, mixing pump, valves and power, what to switch off before filling, the timings); and the recipe in dose order, each amount fixed or read from an entity at the start of each batch. A Home Assistant administrator edits it and saves it after a review; anyone else can read it.

A room without pumps says what dosing does, with **Set up dosing**. Dosing, batches and the setup need a Home Assistant administrator login; any login can watch. [Batch-tank dosing](DOSING.md) describes what the integration, the controller and this page each do.

### Setup

A Home Assistant administrator uses **Equipment › Setup**. Pair the devices and their entities in Home Assistant first. The setup maps entities that exist. It does not pair devices.

1. Select a room, or select **Add room**. Give the room a clear name. You can change the name later, and the room keeps its ID.
2. Tell the setup how the room is plumbed: zone valves only, or a pump and valves. The setup does not guess from empty fields.
3. Map the **Room pump** and the **Mainline valve**, if the room has them.
4. Map the valve of each active zone. Search by the friendly name or by the exact entity ID. Examine the value and the unit before you select an entity.
5. Select one or more VWC probes and EC probes for each zone. **Clear mapping** removes the selected mapping. **Done** closes the picker.
6. Enter the plant count of each zone.
7. Enter the substrate volume **for each plant**, in litres. You can also select a pot preset or a rockwool preset.
8. Enter the number of drippers **for each plant**, and the flow **of each dripper**, in litres per hour.
9. Map the optional room equipment, the tank displays and the feed probes. Each has its own role.
10. Set the kill switch of the affected rooms to off. Make sure that their pump, main-line valve and zone valves are off.
11. Select **Review configuration**. Examine the changes and the problems that stop the save.
12. Select **Save configuration**. The integration checks the setup before it saves it.
13. Wait until the controller accepts the saved setup revision. A saved setup and an accepted setup are different states.
14. Examine **Today** and **Equipment › Probes**. Then set the switches back to their earlier states.

A pump, a main-line valve or a zone valve can be a switch, an `input_boolean` helper or a valve entity. The setup refuses other types, for example a cover or a light. A valve must read closed, and a switch must read off, before the setup saves.

When a zone has more than one correct reading, the integration combines them. It leaves out a probe that does not report or is out of range, and it tells you why (see [Probes](#probes)).

**Units** in Settings changes the volume and the flow to US gallons and GPH for the input. The setup saves the values in litres. The catch test of a zone calculates the flow of each dripper from a timed catch. It changes only the draft.

> **CAUTION:** Do not map a zone valve to two zones. Map shared equipment only when the rooms really share it.

When you remove a zone or a room, the setup archives its ID. **Restore zone** or **Restore room** gives back the same ID, after a review. The setup does not use an archived ID for different hardware. When you add or archive a zone, update the zones of a draft grow plan.

Below the rooms, **substrate, sizing and safety limits** shows the numbers that the controller uses, for each zone and for the room:

- Full saturation, with a suggestion from the learned or typical daily peak of the zone. The suggestion goes only into the draft.
- The substrate size and the hardware size.
- One tap down, the safety limits: the daily water limit, the maximum EC, the watchdog and other limits.

Each change shows a review before the dashboard writes it. **Water & calibration**, one tap down, shows the water of a shot of each phase, in litres for each zone and millilitres for each plant. It also shows the run time, its limits and a catch-test calculator. The calculator uses a measured flow only in that calculation. It does not write a calibration, and it starts no shot.

## Settings & help

**Settings** holds:

- **Home Assistant connection**. The Home Assistant sidebar usually uses your current Home Assistant session. A separate browser tab can also use a URL and a long-lived access token. The tab keeps the token for its session only, and never puts it in the URL. A hosted HTTPS page can fail to connect to a local HTTP Home Assistant server, because of the security rules of the browser. For a normal installation, use the Home Assistant sidebar.
- **Room on or off** (`room_active`): tells the controller that plants grow in the room. When the room is off, the controller gives no shots of any type in the room, rescue shots included, and sends no alerts for it. A shot that runs stops within a few seconds. After less than 24 h off, the controller continues from where it stopped. After 24 h or more off, it starts a new run with each zone in P3.
- **Watering** (`engine_enabled`): the kill switch of the room. Home Assistant shows it as "Engine Enabled" on a room that the setup wizard made. When it is off, the controller starts no shot in the room, rescue shots and test shots included. A shot that runs stops within a few seconds. The controller continues to read the probes and follow the phases. A new room starts with the kill switch off.
- **Every zone's scheduling**: one switch for all the zones of the room. It is on while one or more zones are on. Off pauses each zone. On sets each zone to on, also a zone that you paused. Each zone also has its own switch on its page. This switch also shows a review before it changes.

> **WARNING:** Isolate the electrical power before you do work on a pump, a valve or the wiring. The kill switch stops the controller only. It does not isolate the power.

> **CAUTION:** Do not set the room or the kill switch to off while plants grow in the room. The plants then get no water, not even a rescue shot.
- **Run records**: see [History](#history).
- **Appearance**: **Home Assistant or system** uses the Home Assistant theme when the dashboard is embedded on the same origin. In standalone mode, it uses the device theme. **Light** and **Dark** override the theme. A cross-origin embed cannot read the theme of the host. **Water today display** selects how the page of a zone shows the water today: the zone total (the default), or the share of each plant. The share of each plant is the water today of the zone divided by its plant count from Setup. The room keeps the choice in Home Assistant (`select.crop_steering_<prefix>water_today_view`). Each person who opens the page of a zone sees water that way, and the vitals notification of the controller follows it. Today compares the zones for each plant in both cases. Water use over the grow stays in litres for each zone.
- **Units**: how pot volume and dripper flow are shown and typed in this browser.
- **Sample workspace**, in the demo only.

Inside a compatible same-origin HA shell, the workspace temporarily collapses HA's sidebar. Use **Home Assistant** at the bottom of the workspace navigation, or the house button labelled **Open Home Assistant menu** in the top bar, to reopen HA's menu. Leaving the workspace restores the prior temporary state; it does not change the saved HA sidebar preference. Standalone and unsupported embeddings keep normal navigation. See [Home Assistant sidebar](HA_SIDEBAR.md) for compatibility limits.

After an update, the first person to open the dashboard sees **What's new**: the main changes of every release this installation had not yet shown, in a few plain lines each, with a link to the full release notes. It shows once for everyone, never on a new installation, and **Help › What's new** opens the latest releases again at any time.

**Help** lists each alert code, for example CS-101. An alert or a Repairs card ends with one of these codes. You can search the list. For each code, Help tells what it means, its effect on the shots, the probable causes and the fixes. The address `#/help?code=CS-101` opens one code. The glossary of Help explains VWC, pore EC, dryback, the four phases, steering and runoff.

The manual override is a maintenance lockout for one zone. While it is on, the controller gives the zone no shot of any type, rescue shots and test shots included. It also stops a shot that runs in the zone.

- The switch `switch.crop_steering_zone_N_manual_override` sets the override. It stays on until you set it to off. The switch follows the user permissions of Home Assistant.
- The action `crop_steering.set_manual_override` sets a timed override. Its timeout is 1 to 1440 min, and the default is 60 min. Give the zone and the room slug. For the old default room, give no room. The action refuses a signed-in user who is not an administrator. An automation can still use it.

To release the override is not the same as to set the zone switch or the room switch to on. See the fields of the action in Home Assistant and the [entity reference](ENTITIES.md).

> **WARNING:** Isolate the electrical power before you do work on a pump or a valve. The override does not isolate the power. Shots in other zones can start the pump of the room.

> **CAUTION:** Set the override to off after the work. While it is on, the zone gets no water, not even a rescue shot.

## Settings & help › Notifications

Each alert is still a Home Assistant notification. This page selects who gets a phone push for each kind of alert, for the whole site. The grid has one row for each phone and one checkbox for each kind of alert. A push goes only to the phones whose row ticks its kind. An alert of two ticked kinds goes to that phone one time. [Notifications](NOTIFICATIONS.md) tells what the integration, the controller and this page each do.

- **The grid**: each row is a phone, with the name of its owner and the device. A notify service that is not a phone of the site, for example a group, shows its name (`notify.family`).
- Each column is a kind of alert: Emergencies, Hardware lockouts, Sensors and drift, Shots stopped, Phase changes, Stock tanks, Dosing, Jev, and Setup and settings.
- Open the heading of a column to see what it contains. It lists its alert codes with their titles, and each code opens Help. It also lists the pushes that are not alerts: a zone that changes phase, and a setting that the AI assistant moves.
- **Rooms**: **All**, or the rooms that you select. When you remove the last selected room, the row covers all rooms again.
- **High priority for emergencies**: critical alerts go to that phone as high-priority pushes.
- **Send a test**: one push to that phone. The page shows if the push went.
- **Shots stopped**: set **Alert after no shot for** (for example 3 hours with the lights on). The value is 1 to 12 hours.
- When that time passes, the controller sends CS-209 for the room to the phones that tick Shots stopped. It sends it again after the same time while no shot occurs. The next shot ends the alert.
- The time counts only while a zone is in P1 or P2. It does not count in the morning dryback or overnight.
- **Add a phone**: an administrator can add a phone of the site, or a notify service by its name. A new row starts with Emergencies ticked for all rooms. The bin next to a row removes it.

The changes stay in a draft until **Review and save**. The review lists the changes for each phone, and nothing is saved before it. If a different person saved in the meantime, the page reads that setup again and keeps your changes on top. Examine them, and save again.

Above the grid, the page names each room that no row sends emergencies to, for example "Nobody gets emergencies for Flower 1". The emergencies of that room go to each phone that gets emergencies. When no phone gets emergencies, they go to the `notify_service` option of the controller app. A tap on a push opens Crop Steering.

A Home Assistant administrator can change each row, add and remove phones, and set the time. Other users see each row, but they can tick and test only their own phone. They see "Only an administrator can change other people's phones". On a phone, the grid shows one card for each phone, with the same checkboxes.

When no phone is in the list, each push goes to the `notify_service` option of the controller app, as before. An installation that never opens this page thus works as before.

## A daily routine

1. Open **Today**. A room with shots in progress and no flagged card needs nothing.
2. Read **AI assistant changes today**.
3. Open each flagged zone from its card. Read its numbers, its day chart and its **Controls**.
4. Change targets only in **Plan › Targets**, through the review.
5. Examine the readback after each change.
6. Once each day, or after a change, examine **Equipment › Probes** and **Stock tanks**.

## What the numbers mean

- **Water for each zone and each plant**: the water of a zone is the calculated water for all the plants of the zone. The water for each plant is that value divided by the plant count. The litres of substrate are the volume of all the pots. They are not the water that the plants got. A run time estimate is the water divided by the zone flow, inside the longest shot limit of the controller.
- **Dryback** is a percentage of the peak: (peak VWC − current VWC) ÷ peak VWC × 100. A peak of 60% and a dryback target of 10% give 54% VWC, not 50%.
- **Steering balance**: 0% uses the vegetative endpoint and 100% uses the generative endpoint. A value between them mixes the values of the two endpoints. The pot size and the dripper flow change a shot size into a volume and a time.
- **Plan and history**: the dashboard draws the expected curve of the day from the targets. The recorded history comes from the Recorder of Home Assistant. A modelled curve does not show the water that the plants got. A confirmed event does not show it either.
- **Run comparisons** align the runs by grow age. They stop the earlier run at the age of the current run. A saved target reference shows when the dashboard recorded it. A run that you register later does not get back old targets, or readings that the Recorder removed.
- **When changes start**: a target change reads the limits of the number again, and then reads the value back. A grow plan is saved as a draft, then armed, then started at a local lights-on. When you disarm an active plan, its targets stay until the next lights-on. A mapping change needs disarmed rooms and all the equipment off. The save confirms the storage in Home Assistant. The controller accepts the revision after that.
- **What the controller does not do**: it does not control the climate of the room. It does not predict yield or potency. The old manual-shot and phase-event services have no confirmed use in the controller, so the dashboard does not show them as buttons. A missing or stale reading stays unavailable.

## Understand the graphs and water figures

| View                          | What it shows                                                                                                            | What it does not establish                                                                  |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------- |
| A zone's day chart            | Today's recorded VWC, pore EC, shots, phases and the decisions of the AI assistant, with the expected rest of the day dashed. | Exact future shot times, uptake, runoff or EC accumulation.                                 |
| Targets' day curve            | Configured targets, phase references and supported timing, with local draft changes where applicable.                    | A forecast of the physical VWC/EC trajectory.                                               |
| Recorded behaviour, history   | Retained HA Recorder measurements on separate VWC and EC axes.                                                           | Measurements from periods Recorder did not retain.                                          |
| Water delivered this grow-day | The controller's recorded estimate from its configured flow and elapsed shot runtime, including accounted partial shots. | Independent meter readings, uniform distribution, plant uptake or external irrigation.      |
| Water use estimate            | Water used so far plus the last 7 full grow-days' average for every grow-day left in the grow plan.                      | A forecast of plant uptake, or a total for a grow whose plan length is unknown.             |
| Average mL per plant          | Zone estimated water divided by configured plant count.                                                                  | A measurement from each emitter.                                                            |
| Total substrate capacity      | Substrate volume per plant multiplied by plant count.                                                                    | Water delivered or water retained.                                                          |
| Runtime/phase water preview   | A conditional calculation from supplied settings, showing requested versus effective runtime and caps.                   | A guaranteed daily total; feedback-dependent maintenance/emergency shot counts are unknown. |

The targets' day curve uses separate axes for VWC (%) and root-zone EC, joining configured references across lights-off and overnight to the next lights-on. VWC joins the daytime reference to the relative dryback endpoint; the P3 rescue floor remains a separate protection reference. Dashed EC interpolates from the last daytime anchor to the next morning anchor. There is no P3 EC setpoint or prediction of the physical EC/salt trajectory. Missing values remain gaps rather than being filled with guessed readings. A graph handle changes configuration in a draft, not physical equipment.

Use the catch test in **Equipment › Setup › Water & calibration** (or a zone's own catch test in its sizing) to enter an actual catch result and inspect the proposed dripper flow. Neither applies it by itself. Historical estimates are not retroactively corrected when flow settings change. For detailed software semantics, see [Steering and planning](GROW_PLANS.md).

## Connect an LLM with MCP

The optional [MCP connection guide](MCP.md) describes the local stdio server, supported clients, token configuration and exact tools. It is separate from the dashboard and does not need to be enabled for normal use.

The server uses `HA_URL` and `HA_TOKEN` from local configuration and starts read-only. Follow [MCP.md](MCP.md) for installation and your client's stdio command; do not paste the token into a chat message.

| Tools                                       | Purpose                                                                                                                |
| ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `list_rooms`                                | Discover real room IDs before selecting a scope.                                                                       |
| `get_room_configuration`, `get_room_status` | Inspect the selected room's mappings/configuration and current state.                                                  |
| `search_candidate_entities`                 | Find existing HA entities for a proposed mapping.                                                                      |
| `get_room_plan`, `get_room_runs`            | Read the room's stored plan and run records.                                                                           |
| `preview_setup`, `preview_plan`             | Prepare an exact setup change or draft-plan save and return its diff, room, revision, expiry and proposal token.       |
| `apply_proposal`                            | Apply only the previously reviewed proposal using its token, room ID and expected revision, then read back the result. |

A practical first request is: “List my rooms, inspect the selected room's mappings and report unavailable sources. Do not apply changes.” For editing, ask the model to prepare a proposal and show its entire diff before requesting approval.

Application is available only when you deliberately configure `CROP_STEERING_ALLOW_WRITES=true`. Proposals expire after ten minutes and are single-use; changed revisions or an expired proposal require a fresh preview/review. Existing-room setup can update names, mappings and sizing; plan writes save drafts only. Backend validation and equipment-OFF requirements still apply to setup.

Review the exact room, entities and revisions. A model's explanation is not evidence that HA accepted a change: inspect the tool's readback, and for setup wait for controller acknowledgement. Do not treat a failed or uncertain apply as permission to regenerate and apply a different proposal automatically.

The MCP server is not a generic HA actuator interface and does not enable engines, open valves or activate plans. Keep credentials in the local client/server configuration described in that guide, not in prompts, screenshots or repository files. Existing broadly privileged HA MCP integrations are separate products with different permissions.

## When something does not look right

| Symptom | What to do |
| --- | --- |
| No rooms, or the services of the dashboard are missing | Make sure that the integration loaded and that the controller has the same version. Make sure that your Home Assistant account can use the entities and the services. Refresh the page after an upgrade. |
| A tank shows **Not mapped** | Map that optional display. The dashboard does not use a feed probe or a room probe with a similar name in its place. |
| The last shot or the last fill is missing | Examine the source of the event and its date and time format. The update time of a state is not the time of the event. |
| A reading shows **Check units** | Examine the unit in Home Assistant, and select or repair the correct entity. Do not change the unit of a different quantity to pass the check. |
| A probe is **Left out** or **Silent** | Examine the probe in Equipment › Probes: its last report, its reading and the reason of the integration. The zone uses its other probes. |
| The setup is saved, but the controller has not accepted it | Examine the heartbeat and the setup problems. Keep the kill switch of the affected rooms off until the controller accepts the revision. |
| The slider does nothing | Examine the two selected endpoints. When they are equal, each balance gives the same values. |
| The targets are read-only | Examine the grow plan and the connection. An armed plan shows its targets as read-only. Disarm the plan in Schedule, and wait for the next lights-on, before you change targets. |
| A recipe does not load | Examine the active zone IDs, the limits, the plan state, the connection and the replacement confirmation. |
| A comparison is blank | Examine the selected run and zone, the recorded sensor IDs, the dates, the Recorder retention and the coverage notes. A run record does not make readings that the Recorder did not keep. |
| A pause is confirmed, but equipment stays on | A pause stops new shots. Examine the shot in progress. If necessary, use the physical shutdown procedure of your installation. |

For the test evidence and the known limits, see the [feature matrix](FEATURE_MATRIX.md) and the [troubleshooting guide](troubleshooting.md). A software test does not prove the water that the plants got.
