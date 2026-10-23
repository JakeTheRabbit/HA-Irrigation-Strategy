# User guide

New to VWC, EC or crop steering? Start with the free [Crop Steering Academy](https://jaketherabbit.github.io/HA-Irrigation-Strategy/learn/). It includes narrated lessons, equipment/setup routes and isolated practice. [Course and progress guide](ACADEMY.md).

Updating from 3.17? Read [Upgrading to 3.18](UPGRADING-TO-PARITY.md) first: almost every page is new.
[Dashboards and display](features/dashboards-and-display.md) lists every page with its address.

The menu has five sections, and under them a live list of rooms and zones (see [Getting around](#getting-around)):

- **Status**: **All rooms**, every configured room and zone together.
- **Irrigation**: **Timeline**, **Current day**, **Timer programs** and **Grow plan & presets**.
- **History**: **Explorer**, **Water & flow**, **Compare runs** and **Changes**.
- **Equipment**: **Probes & offsets**, **Feed & dosing**, **Stock**, **Pump calibration**, **Feed pH/EC calibration** and **Setup: pumps & valves**.
- **Settings**: **Alert rules**, **Notifications**, **System status**, **AI assistant**, **Dashboards & display** and **Help**.

Some pages have no menu entry: **Today** (one room; click the room in the room list), each zone's page
(click the zone), **Grows** (from **Run records** on Compare runs), **Dryback drivers** and
**Capabilities** (from System status). Select the room before you change a value. The zone numbers
belong to that room.

> **Note:** **Pump calibration** and **Feed pH/EC calibration** show "Coming in this release" in this
> build. Feed-probe calibration is on **Probes & offsets** until then ([Calibration](features/calibration.md)).

Old bookmarks and notification links open the page that now has their content:

| Old address | Opens |
| --- | --- |
| `#/overview` | Today (the room) |
| `#/zones` | Status › All rooms |
| `#/strategy` | Irrigation › Current day |
| `#/grow-plan` | Irrigation › Grow plan & presets |
| `#/activity`, `#/log`, `#/logs`, `#/history/timeline` | History › Explorer |
| `#/compare` | History › Compare runs |
| `#/sensors`, `#/insights` | Equipment › Probes & offsets |
| `#/equipment/tank`, `#/equipment/feed` | Equipment › Feed & dosing |
| `#/stock` | Equipment › Stock |
| `#/setup` | Equipment › Setup: pumps & valves |
| `#/settings`, `#/help`, `#/help?code=` | Settings › Dashboards & display, Help (and the code it names) |
| a retired dashboard's `?view=` | the page that replaced that view |

For a new installation, start with [Install, upgrade and rollback](INSTALL.md). To try the dashboard with no equipment, open the [interactive demo](https://jaketherabbit.github.io/HA-Irrigation-Strategy/dashboard.html?demo=1).

## What each action changes

| Action | Where the change goes |
| --- | --- |
| Change targets (Irrigation › Current day) | A local draft. Nothing goes to Home Assistant before the review. |
| Apply the reviewed changes | The setpoint entities in Home Assistant. Examine the readback. |
| Substrate, sizing and safety numbers | Equipment › Setup: pumps & valves. The same review applies. |
| Review & save a grow plan | The stored draft plan in Home Assistant. This does not arm the plan. |
| Arm plan | A request to start the plan at the next lights-on. It does not set the kill switch to on. |
| Save a library recipe | The library of this browser, site and room. It writes nothing to Home Assistant. |
| Save a run record (History › Grows) | The run data and its reference. It starts no shots. |
| Save configuration (Equipment › Setup: pumps & valves) | The setup of the room and its zones in Home Assistant. Wait until the controller accepts it. |
| Dose, make a batch, stop (Equipment › Feed & dosing) | A request that the controller does. The page itself operates nothing. |
| Save the dosing setup (Equipment › Feed & dosing) | The stored dosing setup of the room in Home Assistant. The controller reads it. |
| Save notifications (Settings › Notifications) | The stored notification setup of the whole site. The next push follows it. |
| Send a test (Settings › Notifications) | One push to that phone. Nothing is saved. |
| Save a timer program or change **Watering by** (Irrigation › Timer programs) | The room's timer store, or the zone's `select.crop_steering_<prefix>zone_<n>_irrigation_mode`. A review comes first and the saved value is read back. See [Timer programs](features/timers-and-modes.md). |
| Apply a preset or copy settings (Irrigation › Grow plan & presets) | The setting entities of the target room or zones. A preview lists every difference first; each write is read back. See [Presets](features/presets-and-copy.md). |
| Save an alert rule (Settings › Alert rules) | The site's rule store. A rule only notifies; it never touches watering. See [Alerts](features/alerts.md). |
| Put a change back (History › Changes) | The setting or store section the change touched, back to its old value. Administrators only. See [History](features/history-and-changes.md#putting-a-change-back-revert). |
| Save the supply (Equipment › Setup: pumps & valves) | The site's water supply. Saving one turns on pump sharing. See [Water supply](features/water-supply.md). |
| Skip a planned shot (Irrigation › Timeline) | The room's timer store: that one planned shot of the zone is not given. |

## Try the demo

The demo is a software demonstration only. Its readings, history, plans and run records are sample data. They are not a recommended configuration, and they do not come from a real grow. A demo tab cannot connect to Home Assistant. The demo follows the time of day: at night, the zones are in P3 and the pump is off.

1. Open **Status › All rooms** to see every room. Select a zone in the menu or on its card, or select a room in the menu to open its Today page.
2. Read the room line and zone cards. Open a zone and read **Why / next action**.
3. On the page of the zone, point at the shots and the marks of the AI assistant on the chart.
4. Select **Compare with** yesterday or a typical day. Read the probes and the controls.
5. Open **Irrigation › Current day**. Select a zone, and change its rescue floor or its re-water point.
6. Compare the draft line with the saved reference. Then examine the change in the review.
7. Open **Irrigation › Grow plan & presets** and read the flower by stage.
8. Open **Advanced** to change the steering balance of a week, or to examine an endpoint profile.
9. Open **Recipes**, and preview **Demo • steady schedule** or **Demo • week-by-week changes**. A recipe loads into a local draft only.
10. Open **History**. Read the **Explorer**, **Water & flow**, **Compare runs** and **Changes**.
11. Open **Equipment › Setup: pumps & valves**. Try the entity search, the room and zone names and the mapping review.
12. Open **Equipment › Feed & dosing**. Dose a pump, make a batch and stop it. The demo moves faster than real time.
13. Open **Settings › Notifications**. Tick a kind of alert for a phone, save it through the review, and send a test.

The demo sends nothing to your Home Assistant server and no push to a phone. To see the Notifications page as a grower who is not an administrator, add `&notify-user=grower` to the address.

A production recipe library starts empty. The demo recipes are examples, and the dashboard keeps them apart from production libraries. It does not change the demo libraries that exist, also when they are empty or corrupt.

To restore the sample rooms, readings, run records and planner drafts, use **Settings › Dashboards & display › More display options › Reset demo session…** and confirm. The reset discards the demo work that you did not save. It keeps all saved recipe libraries and the live connection data. It does not restore a recipe that you removed. Export the session work that you want to keep before the reset.

## Getting around

- **Desktop:** the menu lists the five sections, then **Rooms**: **All rooms**, each room with its state, and each zone with its phase and VWC. Select a room to open it in the section you are in; select a zone to open its page. The open room or zone is marked.
- **Phone:** the five sections are in a bar along the bottom of the screen. The menu button at the top left opens the rooms and zones. On **All rooms**, tap anywhere on a zone card to open the zone.
- **Phone page tabs:** in a section with more than one page, a row of tabs above the page lists that section's pages.
- **Links:** the address holds the selected room (`?room=`) and the page (`#/zone/2`), so a bookmark, a shared link or the back button returns to the same place.

## The top bar

The top bar is on each page. It shows each room as a chip with a dot and a word: watering, holding, not watering, stale or room off. The chip of the selected room is pressed. Select the chip of a different room to open that room.

Next to the chips, the top bar shows these items:

- The age of the last report of the controller for the selected room.
- **Recent activity**: the newest records, in a panel next to the page. **Open the timeline** opens History › Explorer.
- The refresh button.
- The **Watering** control and **Stop all** action for the selected room. Each change shows a review. **Room in use** lives in **Equipment › Setup: pumps & valves**.

> **WARNING:** Do not use the **Watering** switch or the **Room in use** control as an emergency stop. In an emergency, use the physical shutdown procedure of your installation.

## Status

**All rooms** is organised room → zones → sensors. Each room carries its run, water drunk today (per plant and total), climate, feed tank and stock tanks. Each zone card shows its phase and automation state (Automated, Watering now, Paused, Watering off, Offline, Room off), water per plant, VWC, dryback, pore EC and root-zone temperature, and lists each of its sensors with its readings. Problems show in place: on the room, zone, sensor or tank. A zone being watered glows; one out of the automation is greyed. The header switches act only on the room named beside them.

**Today** is one room's summary. It has no menu entry: click the room in the room list. Choose **Settings › Dashboards & display › Where the app opens** to change this browser’s landing page. Bookmarks and notification links take precedence.

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
| AI assistant setpoint changes paused | The AI assistant put a change back after a rescue shot, and it waits before it tries again. |

- **History › Changes** holds every setting change and who made it, and **History › Explorer** the readings and the AI decisions. The zone’s **Why / next action** panel explains its current decision.

## A zone's page

Open a zone from its card on **Status › All rooms** or Today, from the room list, or with the address `#/zone/N`. Use the switcher at the top to go to a different zone. The page has these parts.

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

**Why / next action**

One panel combines the controller’s reason, shot conditions and AI explanation. Expand its details for proposals, permitted ranges, applied changes and later outcomes. **History** opens the timeline with this zone selected.

**Targets**

The targets of the zone, by phase, as the controller uses them. The range of the AI assistant shows next to the values that it controls. **Edit in Plan** opens them in Irrigation › Current day.

**Probes**

Each VWC probe and pore EC probe of the zone, with its reading. The panel also tells if the zone uses the probe (see [Probes](#probes--offsets)).

**Controls**

- The next conditions of the controller, from its own numbers. Example: shot when VWC < 61% (now 58%) · dilution if pwEC > 3.84 · P3 by 20:36.
- **Pause zone scheduling** and **Enable zone scheduling**: the switch of the zone. When the zone is paused, the controller gives the zone no shot, not even a rescue shot. A shot that runs in the zone stops within a few seconds.
- **Move to a phase**: moves the zone to a phase by hand, after a review. The controller moves the zone within a minute and then continues by its rules. Lights-off still moves the zone to P3, and lights-on moves it to P0. The water and the shot count of the grow-day stay.

> **CAUTION:** Do not pause a zone that has plants. The zone then gets no water, not even a rescue shot.

**History**

**Explore recorded history and comparisons** opens **History › Explorer**, keeping the selected zone. History owns the full sensor explorer, previous-run comparisons and event records; the zone page keeps one operational day chart.

## Irrigation › Timeline

Every room at once, one row per zone, over 12, 24 or 48 hours: done, failed and partial shots, shots
that waited for a shared pump, planned and expected shots, skipped slots and the lights windows. Tap a
block for the water ("X L arrived of Y L": metered against commanded, with a flow meter), the VWC before
and expected, the reason and any alert code. Planned blocks come only from the controller.
**Skip this shot** skips one planned shot: one timer slot, or 15 minutes from a steering shot's time. See
[Irrigation › Timeline](features/history-and-changes.md#irrigation--timeline).

## Irrigation › Timer programs

Each zone has **Watering by**: **Steering** (the engine, as always), **Timer** (the room's timer programs
only, plus the safety shots) or **Off** (no shots at all, rescue shots included). A timer program waters
its zones in a window: every N minutes, N times a day or once. Each change shows a review, then the
saved value is read back. See [Timer programs and irrigation modes](features/timers-and-modes.md).

> **CAUTION:** **Watering by: Off** stops rescue shots too. A zone on **Timer** that no running program
> covers gets only the safety shots.

## Irrigation › Current day

When no grow plan controls the room, **Targets** changes the current targets. An armed grow plan shows its own targets, and you cannot change them here. When the plan has no current snapshot, the targets show as unavailable. They do not go back to the manual values.

1. Select a room and open **Irrigation › Current day**.
2. Select a zone, or select **Room** for the timing that all zones use.
3. Read the targets of the zone. The table has one part for each phase: P0 morning dryback, P1 ramp, P2 maintenance and P3 overnight dryback.
4. Select the **?** of a setting to read what it does, when it acts and what it changes.
5. Type a value, or move a target on the day chart next to the table. Both change the same local draft.
6. Select **Review changes**. Examine each old value and each new value.
7. Apply the changes. Only this step sends the values to Home Assistant.
8. Examine the readback. A value that Home Assistant did not accept stays visible with its error.

The draft follows the limits and the step of each Home Assistant number. The chart shows the saved values as a reference. The dark lines show what the probes of the zone recorded. A draft stays after a refresh. When you change the room, the dashboard asks before it discards the draft.

The targets of the other steering mode (its P3 dryback and its EC targets) are one tap down. The substrate, the plants, the drippers, the flow and the safety limits are in **Equipment › Setup: pumps & valves**.

When the AI assistant controls a value, its range shows next to the value. The **Auto** switch is the Auto setpoints switch of the room. When the Setpoints judge of the AI assistant runs, the AI assistant controls the P2 shot size and the re-water point. The Auto setpoints learner of the controller controls the peak target and field capacity. It moves each by 1 point or less each grow-day.

> **CAUTION:** Do not set the Auto switch to on while a probe gives wrong readings. The setpoints can then move in the wrong direction.

You can preview a change of the room against a selected zone. The value of a zone overrides the value of the room for that zone. A value that is missing or not correct stays missing on the chart. The dashboard does not make up a curve.

## Irrigation › Grow plan & presets

The page heading still says **Calendar**. Presets and copying settings between rooms and zones are on the same page: see [Presets and copying settings](features/presets-and-copy.md).

Expand **Stage guide** to read **This flower by stage**. It shows the stages of this flower: flower set, flower bulk and finish. For each stage, it shows the flower days and weeks, and what starts the next stage. It also shows the steering mode, the pore EC range, the overnight dryback and the runoff. The overnight dryback is in points of true water content: 15 to 25 in flower set, 10 to 15 in flower bulk and 20 to 25 in the finish. The table marks the week of today and the start of the next stage. Day 1 is the first day of 12 hours on and 12 hours off. The AI assistant uses this stage arc. **Validate preview** and **Arm plan** stay below it.

Under **Advanced**, the planner gives each zone a profile for each grow-day. You make these profiles. The balance slider sets a value between the vegetative endpoint and the generative endpoint of the profile. The slider does not select a crop recipe that is built in. When the two endpoints are equal, each position of the slider gives the same targets.

1. Open **Advanced › Endpoint profiles**.
2. Examine the two endpoints, and select the correct **Zone limits**.
3. To get an independent copy of a profile, duplicate it. A change to a profile changes each schedule block that uses that profile.
4. Open **Advanced › Steering balance**.
5. Select a zone, and set its **Zone start date**. Each zone can have a different start date.
6. Select a day or a week in the grid, or type a balance (0–100 % generative) in the grid. In the grid, Enter applies the value, Esc cancels it and the arrow keys move the selection. The panel next to the grid shows the setpoints at that balance, the two endpoints and the balance on each side.
7. Assign the **Endpoint profile** of the block. The grid accepts days 1–366. When you change a range, the planner splits the blocks that exist and keeps the days around the range.
8. Examine **Zone schedule blocks** for the days that they cover.
9. Fill the missing days. Correct the overlaps and the errors of the parameters and the zone assignments.
10. Select **Review & save** to validate the draft and save it in Home Assistant. **Validate preview** checks a stored draft that has no local changes. **Export** downloads a plan file that you can move. **Reload stored plan** gets the stored revision again after you save or discard the local changes.
11. To let the controller use the plan, select **Arm plan** and examine the review. The controller must report that it supports plans. The plan starts at the next local lights-on. The arm action does not set the kill switch to on, and it does not start the pump.

You cannot change an active or armed plan as a draft. **Disarm plan** asks the controller to go back to the manual targets at the next lights-on. Wait for the **draft** status before you change the plan. The dashboard reports a controller with no plan support, a stale snapshot and an incomplete handoff. It does not show the plan as active. Only a Home Assistant administrator can save, arm or disarm a plan. Other users can open the plan and its previews, but they cannot change them.

After you add or archive zones in Setup, select **Update zones from setup** in a draft plan. The update keeps the schedules of the active zones that exist, and removes the assignments of the archived zones. It gives each new zone a profile with the current settings of that zone. If you need the assignments that the update removes, export the plan before the update.

### Recipes

**Advanced › Recipes** is the recipe library. A recipe in the library is a copy that you can use again. It is not the plan in Home Assistant that controls the room now.

- **Save current as recipe** saves a copy with a name in this browser. You can add notes and a source URL.
- **Import recipe file** reads a plan file in the export format and validates it. Then you give the copy a name.
- **Preview recipe** shows the zones, the current start dates that the recipe keeps, the schedule spans and the profiles.
- **Load into local draft** needs the same active zone IDs as the room has now. It keeps the current start dates. Before it replaces planner work that you did not save, you must confirm.
- You cannot load a recipe while the plan is active or armed, while the dashboard is busy, or while it is not connected. A load does not save or arm the plan.
- **Export recipe** downloads a copy. **Remove recipe** asks you to confirm, and then removes only the copy in the browser.

Each library is for one site, one browser, one room and one mode (demo or live). It is not a shared database in Home Assistant. The limits are 20 recipes for each room, 500 KB for each plan and 2 MB for each library. Export the important copies before you clear the browser data or move to a different browser. When the stored data is corrupt, the dashboard keeps it and gives a download to recover it. The dashboard reports a refused storage, a full storage and a conflict with an old tab, and it does not overwrite the data. See [Recipe library](RECIPE_LIBRARY.md).

## History

**Explorer** shows the room's readings on stacked charts under its phase and shot lanes, with one
crosshair, the last run beside it and **Export CSV** of what is charted. Pick a zone in the room list to
add its probes, its targets and its other grows. **AI assistant decisions** lists what the AI assistant
did, each with how it turned out. See [History › Explorer](features/history-and-changes.md#history--explorer).

**Changes** lists every setting change by day: who made it and why, the old and new value, and how it
turned out. An administrator can put one change back. See
[History › Changes](features/history-and-changes.md#history--changes).

The shots themselves are on **Irrigation › Timeline**.

**Water & flow** (the page heading says **Water use**) shows the litres of each zone for today, this grow week and the time since the grow start. It also shows an estimate for the whole grow. It has a bar for each grow week. Under the bars, it shows the water of today for each zone and for each plant. A grow-day is from lights-on to the next lights-on.

The page reads the long-term statistics of Home Assistant, which Home Assistant keeps with no time limit. When you open the page outside Home Assistant, it can read only the recorded history, for the time that the recorder keeps it. The grow start is the start date of the grow plan of the zone, when the plan is armed or saved. Without a plan, the page calculates the grow start: the first day with water after five or more grow-days with no water. The panel shows which source it uses. A day that Home Assistant did not record has a flag, and the page does not count it as zero.

**Compare runs** compares the run in progress with an earlier run, by grow week:

1. Select **This run**, **Compare with** and the **Zone**. At the start, the page selects the last run that ended.
2. Read the weeks table. For each week, it shows the typical day: VWC low to high, pore EC low to high, and water for each plant in a day. The figure of this run is above the figure of the compared run. **Largest differences** names up to three weeks with a large difference. A large difference is more than a few points of VWC, a few tenths of pore EC, or a fifth of the water.
3. Open **Full-resolution chart, with a target reference** (one tap down). It draws the recorded VWC and EC for **Day**, **Week · 7 days**, **Calendar month**, **Run to date** or **Custom dates**.
4. Select a **Target reference**: **Current configured daily plan**, **Saved run daily reference**, or **Current phase reference**.
5. Read the note of the reference about its capture and its source.
6. To move the window forward, select **Refresh history**.
7. Open **Data quality and history coverage** (one tap down). It shows the recorded range of each day as bars on one scale. The compared run is grey. The section also shows the source of the weekly figures.

The run records are in **History › Grows**. **Run records** on Compare runs opens them. To record a run, do these steps:

1. Select **Add run**.
2. Type the actual name, the start date and, if you know it, the end date.
3. Select **Save run record**.

The save records the metadata and a reference configuration with a time stamp. It does not arm a plan, and it starts no shot. **Export metadata** makes a backup of the run definitions and the reference snapshots. It does not include the readings of the Recorder. **Archive** and **Restore** keep the identity of the run. To save, archive or import run records, you must be a Home Assistant administrator. Each signed-in user can read them.

When you record the run of last month today, the record gets the reference configuration of today. It cannot get back the setpoints of last month, or Recorder data that Home Assistant removed. Each room can have up to 100 run records. A run that ended covers 1–366 calendar days, the first day and the last day included.

## Equipment

### Probes & offsets

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

**Offsets and curves.** A moisture probe can take an offset matched to a handheld meter, and a probe that
reports permittivity can take a generic curve. Both change the VWC the zone steers on. Feed-water pH/EC
calibration is on this page too. See [Calibration](features/calibration.md).

**Room map** and **All sensors of this room** are one tap down. **All sensors of this room** shows each sensor of the room with its reading, its last hours and its availability. You can search and filter it. **Map probes** opens **Setup: pumps & valves**.

### Stock

**Next to run out** is at the top. It is the tank with the fewest batches left. Each tank shows its level against its low mark. The level is red at or below the low mark, and amber at or below 1.5 times the low mark. Each tank also shows **Refilled**, **Set level** and the number of batches left.

A stock tank can have a link to a dosing pump in **Equipment › Feed & dosing › Dosing setup**. That tank shows **Drawn by** that pump **as it doses**, with its recent draws. The integration takes from the tank the volume that the pump ran: the run time of the motor multiplied by the calibrated flow. This applies to each dose of the pump, from the controller, from an automation or from a person at the doser. A fill of the batch tank does not take from a linked tank. The batches left of a linked tank use the dose of its pump in the recipe.

**Record a batch** takes the doses of one batch from the stock tanks. The recent draws are one tap down. **Edit stock tanks** adds, renames and removes tanks.

### Feed & dosing

#### The tank

**Equipment › Feed & dosing** shows the level, the EC, the pH and the temperature of the feed tank. EC and pH have a line of the last day. The page also shows the pump state and the last recorded fill. The old Tank & pump address still opens it. **History** opens the two readings over 24 hours, 7 days or 30 days. When the room uses those probes for the source-water gate, it also shows the gate. To map the sensors, select **Map sensors**, or open **Equipment › Setup: pumps & valves › Shared room hardware**. Each mapping is explicit. The dashboard does not guess that a room-temperature probe or a feed probe is a tank probe.

**Tank minimum** is under the tank. It tells in words what the [reservoir minimum](#reservoir-minimum) does now:

- The room can water.
- The shots are held at the minimum, or because the controller cannot read the level.
- The fill is stopped above the full mark.

The panel shows the alert code, with a link to Help. It shows the minimum and the level at which the shots start again. When the controller knows the litres for each 1% of level, the panel shows about how many litres are above the minimum. It also shows the batch in the tank (the step that runs now, or how the last batch ended), with a link to **Dosing**. When the room has no tank level mapped for the controller, the panel says that the minimum is off, and gives a link to Setup.

**Tank level and shots**, under that, draws the level over 12 hours, 24 hours (the default), 3 days or 7 days. It also shows what moved the level:

- The shots of each zone are dots on the line. Across 7 days, the shots in the same hour share one dot.
- The pump runs and the tank fills are bars above the line.
- Each recorded fill is a dashed line.

Two levels go across the chart. One is the tank minimum, in a room whose tank level the controller reads. The other is the refill reminder, when the dosing setup reads its reminder on this level. Hover over a mark or tap it to see what it was. For a shot, it shows the zone, the valve open time and about how many litres that is at the configured flow. For the pump or a fill, it shows the run time. The list under the chart names each event in the range. The chart reads the Home Assistant recorder, as the Today chart of a zone does, and it updates when new readings come.

The level is the value that the mapped level sensor reports. The dashboard cannot tell if that sensor measures the water or calculates it, for example from the pump run time since the last fill. The chart says this. Shots are valve open times. The pump bars and fill bars are the reports of the switches. A recorded fill is a newer time on the last-fill record. A restart that records the same time again is not a fill.

| Setup label             | Configuration key         | Select                                                                                                                |
| ----------------------- | ------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Room pump               | `pump_switch`             | The actual switch, `input_boolean` or valve of the room pump in Home Assistant. The controller descriptor publishes it as `pump`. |
| Tank fill level (%)     | `water_level_sensor`      | A percentage sensor, 0-100. A value in litres is not a percentage.                                                    |
| Tank EC (display)       | `tank_ec_sensor`          | A conductivity sensor of the tank, in mS/cm or dS/m, that the setup accepts.                                          |
| Tank pH (display)       | `tank_ph_sensor`          | A pH sensor.                                                                                                          |
| Tank temperature        | `tank_temperature_sensor` | A temperature sensor in the tank water, in °C, °F or K. The setup keeps its unit.                                     |
| Tank filling status     | `tank_fill_entity`        | A fill-valve switch or binary sensor that is on while the tank fills.                                                 |
| Last recorded tank fill | `tank_last_fill_sensor`   | A timestamp sensor with a date and a time zone, or an `input_datetime` helper that has the date and the time.         |

**Tank EC (display)** and **Tank pH (display)** only fill the panel. **Feed-water EC** and **Feed-water pH** are different mappings, which the source-water gate uses when you configure it. A mapping of a tank display does not start the source-water gate or the nutrient dosing.

**Last recorded fill** has the meaning that your recording automation gives it. For example, it can be the event of a full float that you verified, or a "mark filled" action of an operator. The panel uses the timestamp attribute of a date and time helper. These items are not a fill record: the `last_changed` of a sensor, the `last_triggered` of an automation, a flag that starts a fill mode, and a dosing interlock. The panel does not make a fill-record automation for you.

A percentage source can itself be an estimate. When the panel draws it as a tank, it does not become a measured level. Tank readings and switch reports do not prove that a dose is complete or that the water quality is correct. They do not prove that the plants got the water.

An input that is not mapped shows **Not mapped**. A reading that is not valid shows **Unavailable**, **Check units** or **Out of range**. The panel does not show an unknown pump as off, and it does not draw an unknown tank as empty. When the dashboard is not connected, the panel shows the readings that it kept as the last readings that it received.

#### Tank level for the controller

The percentage sensor above only draws the tank. To let the controller read the level of the tank, map one or both of these sensors:

- A **tank distance sensor** (`tank_distance_sensor`): an ultrasonic or radar sensor that gives the distance down to the water.
- A **low float** (`tank_low_float`): a binary sensor.

Map them in the `hardware` of the setup API, with the `tank_level` of the room:

| `tank_level` field | Meaning |
| --- | --- |
| `full_mm` | The distance from the distance sensor down to the water when the tank is full, in millimetres. Necessary with a distance sensor. |
| `empty_mm` | The same distance when the tank is empty. It must be more than `full_mm`. Necessary with a distance sensor. |
| `float_low_state` | `on` (the default) or `off`: the state of the float that shows a low tank. |

The unit of the distance sensor must be mm, cm, m, in or ft. The controller converts it to millimetres through the device-unit table, so the level is the same for each unit of the sensor. The setup refuses a sensor with a different unit or with no unit. The level is 0% at `empty_mm` and 100% at `full_mm`. Above the full mark, the level is more than 100%. The controller reads the level one time in each loop and publishes it as `sensor.crop_steering_tank_level` ([ENTITIES.md](ENTITIES.md)). The reservoir minimum below uses this level.

The full float of the batch tank in the dosing setup is not a level, and the controller does not read it here.

The controller trusts the sensor unless it is unavailable. Many sensors send a reading only when it changes, so the sensor of a quiet tank can send no reading for some hours. Thus the controller does a drawdown check: it compares the litres that the shots take with the decrease of the level. Each time the level decreases by 5% or more, the controller learns the litres for each 1% of level.

When the controller knows this value, it can find a stuck sensor. The litres of the shots can be equal to 5% or more of level. If the level then decreased by less than a quarter of that, the sensor is stuck. The controller then publishes the level as unknown and writes the reason in the log. It trusts the sensor again when the level decreases by 5% or more, or when a refill increases the level by 2% or more. Before the level decreases by 5% one time with the shots counted, the controller cannot tell a stuck sensor from a full tank.

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

#### Pumps and batches

**Equipment › Feed & dosing** operates the batch tank of the room. It doses one pump by hand, and it makes a batch: it fills the tank, mixes it, doses each nutrient in order, and mixes it again. Each room has its own page for its own tank. The page itself switches nothing. You examine each action in a review, and then the page sends it as a request. The controller does the request within a few seconds.

The controller does not act on a request that is older than two minutes, so nothing starts later without warning. The firmware of each pump controls the time of each dose: Home Assistant sets the volume and presses start. The controller sets the power of a pump to off only when you stop the dose, or when the pump runs past its time.

- **The tank**, in one line: its level, the state of the full float, the EC, the pH, the temperature and the step of the batch. The readings come from the tank mapping of the room.
- **Stock**: each stock tank that has a link to a pump, in pump order. Each tank shows its level, its litres, about how many batches it has left, and its low mark. **Stock tanks** opens them.
- **A card for each pump**: a picture of the pump, its name and device, its state, its last dose, its calibrated flow in mL/s, and its linked stock tank. The rotor of the picture turns while the pump doses. The card draws the stock tank to scale, with its litres and the number of batches at the recipe volume of the pump. When the recipe does not use the pump, the card shows the number of doses at the last dose. The bottle is amber, with **Low**, at the low mark of the tank, and red, with **Very low**, at half of the low mark. To dose a pump, select its card.

| State          | Meaning                                                                                  |
| -------------- | ---------------------------------------------------------------------------------------- |
| Idle           | Ready to dose.                                                                           |
| Dosing         | The controller or the pump itself says that the pump doses.                              |
| Not calibrated | Its flow reads nothing, or less than 0.05 mL/s. The controller does not start it. Calibrate the pump first. |
| Unavailable    | Grey, with a question mark. The controller does not report, or an entity of the pump is missing or unavailable. The card tells which. |

- **Dose a pump**: type the mL, up to the largest dose of the pump. The page shows the time that the dose takes at the flow of the pump. **Start** opens the review. The dose goes into the tank as it is, and the shots continue. While the dose runs, the **status** of the pump shows the target, the time since the start and the mL so far. The page calculates the mL from the time and the flow.
- **Make a batch**: the steps of the batch, each marked done, now, passed by or to come. Next to the steps is the recipe, with the mL of each pump, the total and the time. **Make a batch** opens the review. The controller holds the shots in the room until the batch ends or stops. It also holds the shots in each room whose pump, main-line valve or valves the batch uses. It holds the shots in each room that shares the pump or the main-line valve too. Before you start, the page names each pump in the recipe that cannot dose now. It also names each volume that comes from an entity that reads nothing. In these two conditions, the controller refuses the batch before anything moves.
- **Stop dosing** and **Stop the batch** send one stop. The controller sets the power of each dosing pump of the room to off. A batch that runs then ends: the controller sets the fill valve, the mixing pump and the mixing valves to off, and then releases the shots. The stop replaces a request that still waits.
- **History**: the last doses and batches, what each dosed and how it ended.
- **Dosing setup** (one tap down): for each pump, its dose volume, start, dosing state, power switch, calibrated flow and stock tank (one pump for each tank). The batch hardware: the fill valve and the float, the mixing pump, the valves and the power, the equipment to switch off before the fill, and the times. The recipe, in dose order: each volume is fixed, or read from an entity at the start of each batch. A Home Assistant administrator edits the setup and saves it after a review. Other users can read it.

**Prime and calibrate a pump**: a timed run into a measuring jug, then commit the measured volume as the pump's flow. See [Calibration](features/calibration.md#dosing-pump-prime-and-calibrate).

A room with no pumps tells what dosing does, and shows **Set up dosing**. To dose, make a batch or change the setup, you must be a Home Assistant administrator. Each signed-in user can watch the page and stop the dosing. [Batch-tank dosing](DOSING.md) tells what the integration, the controller and this page each do.

### Setup: pumps & valves

A Home Assistant administrator uses **Equipment › Setup: pumps & valves**. Pair the devices and their entities in Home Assistant first. The setup maps entities that exist. It does not pair devices.

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
14. Examine the room's Today page and **Equipment › Probes & offsets**. Then set the switches back to their earlier states.

A pump, a main-line valve or a zone valve can be a switch, an `input_boolean` helper or a valve entity. The setup refuses other types, for example a cover or a light. A valve must read closed, and a switch must read off, before the setup saves.

When a zone has more than one correct reading, the integration combines them. It leaves out a probe that does not report or is out of range, and it tells you why (see [Probes](#probes--offsets)).

**Units** in Settings changes the volume and the flow to US gallons and GPH for the input. The setup saves the values in litres. The catch test of a zone calculates the flow of each dripper from a timed catch. It changes only the draft.

> **CAUTION:** Do not map a zone valve to two zones. Map shared equipment only when the rooms really share it.

**Supply** (optional) declares each irrigation pump's real flow, how many zones it can feed at once, its
flow meters and zone groups that must never run together. Once saved, rooms on one pump take turns and
the flow checks run. Measure the pump's real flow with a bucket first. See
[Water supply](features/water-supply.md).

When you remove a zone or a room, the setup archives its ID. **Restore zone** or **Restore room** gives back the same ID, after a review. The setup does not use an archived ID for different hardware. When you add or archive a zone, update the zones of a draft grow plan.

Below the rooms, **substrate, sizing and safety limits** shows the numbers that the controller uses, for each zone and for the room:

- Full saturation, with a suggestion from the learned or typical daily peak of the zone. The suggestion goes only into the draft.
- The substrate size and the hardware size.
- One tap down, the safety limits: the daily water limit, the maximum EC, the watchdog and other limits.

Each change shows a review before the dashboard writes it. **Water & calibration**, one tap down, shows the water of a shot of each phase, in litres for each zone and millilitres for each plant. It also shows the run time, its limits and a catch-test calculator. The calculator uses a measured flow only in that calculation. It does not write a calibration, and it starts no shot.

## Settings

**Alert rules** (the first page of Settings): your own threshold rules, built as sentences and replayed
over yesterday before you save. A rule only notifies. See [Alerts](features/alerts.md#alert-rules).

**System status**: every mapped device online, offline or silent, with its last report and 7-day uptime,
each room's controller heartbeat, and the open alerts with **Acknowledge**. See
[System status](features/system-status.md).

**Dashboards & display** holds connection, appearance, units and display preferences, and makes wall,
tablet and dosing-station dashboards ([Dashboards and display](features/dashboards-and-display.md)). Other controls have one owner:

- **Home Assistant connection**. The Home Assistant sidebar usually uses your current Home Assistant session. A separate browser tab can also use a URL and a long-lived access token. The tab keeps the token for its session only, and never puts it in the URL. A hosted HTTPS page can fail to connect to a local HTTP Home Assistant server, because of the security rules of the browser. For a normal installation, use the Home Assistant sidebar.
- **Room in use**, in **Equipment › Setup: pumps & valves** (`room_active`): tells the controller that plants grow in the room. When the room is off, the controller gives no shots of any type in the room, rescue shots included, and sends no alerts for it. A shot that runs stops within a few seconds. After less than 24 h off, the controller continues from where it stopped. After 24 h or more off, it starts a new run with each zone in P3.
- **Watering**, in the header (`engine_enabled`): the kill switch of the room. Home Assistant shows it as "Engine Enabled" on a room that the setup wizard made. When it is off, the controller starts no shot in the room, rescue shots and test shots included. A shot that runs stops within a few seconds. The controller continues to read the probes and follow the phases. A new room starts with the kill switch off.
- **Zone scheduling** lives on each zone’s detail page. Its switch shows a review before it changes.

> **WARNING:** Isolate the electrical power before you do work on a pump, a valve or the wiring. The kill switch stops the controller only. It does not isolate the power.

> **CAUTION:** Do not set the room or the kill switch to off while plants grow in the room. The plants then get no water, not even a rescue shot.
- **Run records** live in **History › Grows**: see [History](#history).
- **Appearance**: **Home Assistant or system** uses the Home Assistant theme when the dashboard is embedded on the same origin. In standalone mode, it uses the device theme. **Light** and **Dark** override the theme. A cross-origin embed cannot read the theme of the host. **Water today display** selects how the page of a zone shows the water today: the zone total (the default), or the share of each plant. The share of each plant is the water today of the zone divided by its plant count from Setup. The room keeps the choice in Home Assistant (`select.crop_steering_<prefix>water_today_view`). Each person who opens the page of a zone sees water that way, and the vitals notification of the controller follows it. Today compares the zones for each plant in both cases. Water use over the grow stays in litres for each zone.
- **Where the app opens**: this browser’s landing page. **Display** holds the optional room panels. **Capabilities** is a read-only searchable directory of current values, with links to the workspace that edits each setting.
- **Units**: the room's EC unit (mS/cm, ppm 500 or ppm 700), temperature (°C or °F) and clock (12 or 24 hours), and the units this browser uses for the substrate volume and the dripper flow. Display only: stored values, the API and the MCP tools stay in mS/cm and °C.
- **Reset demo session…**, in the demo only.

In a compatible Home Assistant shell on the same origin, the workspace collapses the Home Assistant sidebar for a time. To open the Home Assistant menu again, select **Home Assistant** at the bottom of the workspace menu. You can also select the house button **Open Home Assistant menu** in the top bar. When you leave the workspace, the sidebar goes back to its earlier state. The workspace does not change the saved sidebar setting of Home Assistant. In standalone mode, and in an embedding that is not supported, the menu does not change. For the limits, see [Home Assistant sidebar](HA_SIDEBAR.md).

After an update, the first person who opens the dashboard sees **What's new**. It shows the main changes of each release that this installation did not show before, in some plain lines for each release. It also gives a link to the full release notes. It shows one time for all users, and it does not show on a new installation. **Help › What's new** shows the latest releases again at any time.

**Help** lists each alert code, for example CS-101. An alert or a Repairs card ends with one of these codes. You can search the list. For each code, Help tells what it means, its effect on the shots, the probable causes and the fixes. The address `#/help?code=CS-101` opens one code. The glossary of Help explains VWC, pore EC, dryback, the four phases, steering and runoff.

The manual override is a maintenance lockout for one zone. While it is on, the controller gives the zone no shot of any type, rescue shots and test shots included. It also stops a shot that runs in the zone.

- The switch `switch.crop_steering_zone_N_manual_override` sets the override. It stays on until you set it to off. The switch follows the user permissions of Home Assistant.
- The action `crop_steering.set_manual_override` sets a timed override. Its timeout is 1 to 1440 min, and the default is 60 min. Give the zone and the room slug. For the old default room, give no room. The action refuses a signed-in user who is not an administrator. An automation can still use it.

To release the override is not the same as to set the zone switch or the room switch to on. See the fields of the action in Home Assistant and the [entity reference](ENTITIES.md).

> **WARNING:** Isolate the electrical power before you do work on a pump or a valve. The override does not isolate the power. Shots in other zones can start the pump of the room.

> **CAUTION:** Set the override to off after the work. While it is on, the zone gets no water, not even a rescue shot.

## Settings › Notifications

Each alert is still a Home Assistant notification. This page selects who gets a phone push for each kind of alert, for the whole site. The grid has one row for each phone and one checkbox for each kind of alert. A push goes only to the phones whose row ticks its kind. An alert of two ticked kinds goes to that phone one time. [Notifications](NOTIFICATIONS.md) tells what the integration, the controller and this page each do.

- **The grid**: each row is a phone, with the name of its owner and the device. A notify service that is not a phone of the site, for example a group, shows its name (`notify.family`).
- Each column is a kind of alert: Emergencies, Hardware lockouts, Sensors and drift, Shots stopped, Phase changes, Stock tanks, Dosing, AI assistant, and Setup and settings.
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

Quiet hours per phone are new in 3.18. This page does not edit them yet, and a save from it keeps them.
Set them with `crop_steering.notify_save` ([Quiet hours](features/alerts.md#quiet-hours)).

## A daily routine

1. Open **Status › All rooms**. A room with shots in progress and no flagged card needs nothing. Check **Settings › System status** for anything offline or silent.
2. Read **AI assistant changes today**.
3. Open each flagged zone from its card. Read its numbers, its day chart and its **Controls**.
4. Change targets only in **Irrigation › Current day**, through the review.
5. Examine the readback after each change.
6. Once each day, or after a change, examine **Equipment › Probes & offsets** and **Equipment › Stock**.

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
| A zone's day chart            | The recorded VWC, pore EC, shots and phases of today, and the decisions of the AI assistant. A dashed line shows the expected rest of the day. | The exact times of future shots, the uptake, the runoff or the EC that builds up.           |
| Targets' day curve            | The configured targets, the phase references and the timing, with the local draft changes.                              | A forecast of the physical VWC and EC.                                                      |
| Recorded behaviour, history   | The measurements that the HA Recorder kept, on separate VWC and EC axes.                                                 | Measurements from the periods that the Recorder did not keep.                               |
| Water delivered this grow-day | The estimate that the controller records from its configured flow and the run time of each shot, partial shots included. | Meter readings, an equal distribution, plant uptake or water from other sources.            |
| Water use estimate            | The water used so far, plus the average of the last 7 full grow-days for each grow-day that is left in the grow plan.   | A forecast of plant uptake, or a total for a grow with no known plan length.                |
| Average mL per plant          | The estimated water of the zone divided by the configured plant count.                                                   | A measurement from each dripper.                                                            |
| Total substrate capacity      | The substrate volume for each plant multiplied by the plant count.                                                       | The water that the plants got, or the water that the substrate kept.                        |
| Runtime/phase water preview   | A calculation from the settings. It shows the requested run time against the effective run time and the limits.         | A daily total. The number of maintenance shots and rescue shots depends on the probes, so it is not known. |

The day curve of the targets has separate axes for VWC (%) and EC. It joins the configured references across lights-off and the night to the next lights-on. The VWC line joins the reference of the day to the end point of the relative dryback. The P3 rescue floor stays a separate protection reference. The dashed EC line goes from the last anchor of the day to the anchor of the next morning.

There is no P3 EC setpoint, and no prediction of the physical EC or salt. A missing value stays a gap, and the dashboard does not fill it with a guess. A handle on the graph changes the configuration in a draft. It does not change the physical equipment.

To enter the result of a real catch test, use the catch test in **Equipment › Setup: pumps & valves › Water & calibration**. Then examine the proposed dripper flow. Sizing and the catch test share this Setup workspace. The calculation changes only the draft; review and apply the flow before it becomes configuration. When the flow settings change, the old estimates do not change. For the details of the software, see [Steering and planning](GROW_PLANS.md).

## Connect an LLM with MCP

To set up an install with an assistant step by step, follow [AI setup](AI-SETUP.md). The optional [MCP connection guide](MCP.md) tells about the local stdio server, the supported clients, the token configuration and the tools. The server is separate from the dashboard. You do not need it for normal use.

The server gets `HA_URL` and `HA_TOKEN` from the local configuration. It starts in read-only mode. To install the server and get the stdio command of your client, follow [MCP.md](MCP.md). Do not paste the token into a chat message.

| Tools                                       | Purpose                                                                                                                |
| ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `list_rooms`                                | Finds the real room IDs before you select a scope.                                                                     |
| `get_room_configuration`, `get_room_status` | Reads the mappings, the configuration and the current state of the selected room.                                      |
| `search_candidate_entities`                 | Finds HA entities that exist, for a proposed mapping.                                                                  |
| `get_room_plan`, `get_room_runs`            | Reads the stored plan and the run records of the room.                                                                 |
| `preview_setup`, `preview_plan`             | Prepares an exact setup change or a save of a draft plan. Returns its diff, room, revision, expiry and proposal token.  |
| `apply_proposal`                            | Applies only the proposal that you reviewed, with its token, room ID and expected revision. Then reads back the result. |

A good first request is: “List my rooms. Examine the mappings of the selected room and report the sources that are unavailable. Do not apply changes.” For a change, tell the model to prepare a proposal. Tell the model to show the full diff before it asks for your approval.

The server can apply a proposal only when you set `CROP_STEERING_ALLOW_WRITES=true`. A proposal expires after ten minutes, and you can use it only one time. When the revision changes or the proposal expires, make a new preview and review. For a room that exists, a setup change can change the names, the mappings and the sizing. A plan write saves only a draft. The validation of the backend, and the rule that the equipment must be off, still apply to the setup.

Examine the exact room, entities and revisions. The explanation of a model does not prove that HA accepted a change. Examine the readback of the tool. For a setup change, wait until the controller accepts it. When an apply fails or its result is not certain, do not let the model make and apply a different proposal automatically.

The MCP server is not a general interface that operates HA equipment. It does not set the kill switch to on, open valves or start plans. Keep the credentials in the local client and server configuration that the guide describes. Do not put them in prompts, screenshots or repository files. Other HA MCP integrations with wide permissions are separate products with different permissions.

## When something does not look right

| Symptom | What to do |
| --- | --- |
| No rooms, or the services of the dashboard are missing | Make sure that the integration loaded and that the controller has the same version. Make sure that your Home Assistant account can use the entities and the services. Refresh the page after an upgrade. |
| A tank shows **Not mapped** | Map that optional display. The dashboard does not use a feed probe or a room probe with a similar name in its place. |
| The last shot or the last fill is missing | Examine the source of the event and its date and time format. The update time of a state is not the time of the event. |
| A reading shows **Check units** | Examine the unit in Home Assistant, and select or repair the correct entity. Do not change the unit of a different quantity to pass the check. |
| A probe is **Left out** or **Silent** | Examine the probe in Equipment › Probes & offsets and Settings › System status: its last report, its reading and the reason of the integration. The zone uses its other probes. |
| The setup is saved, but the controller has not accepted it | Examine the heartbeat and the setup problems. Keep the kill switch of the affected rooms off until the controller accepts the revision. |
| The slider does nothing | Examine the two selected endpoints. When they are equal, each balance gives the same values. |
| The targets are read-only | Examine the grow plan and the connection. An armed plan shows its targets as read-only. Disarm the plan in Grow plan & presets, and wait for the next lights-on, before you change targets. |
| A recipe does not load | Examine the active zone IDs, the limits, the plan state, the connection and the replacement confirmation. |
| A comparison is blank | Examine the selected run and zone, the recorded sensor IDs, the dates, the Recorder retention and the coverage notes. A run record does not make readings that the Recorder did not keep. |
| A pause is confirmed, but equipment stays on | A pause stops new shots. Examine the shot in progress. If necessary, use the physical shutdown procedure of your installation. |

For the test evidence and the known limits, see the [feature matrix](FEATURE_MATRIX.md) and the [troubleshooting guide](troubleshooting.md). A software test does not prove the water that the plants got.
