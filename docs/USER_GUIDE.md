# User guide

The menu has five entries. **Today** says whether the room is OK and which zone needs you. **Plan** holds the zones' **Targets** and the grow plan's **Schedule**. **History** holds the **Timeline**, **Water use** and **Compare runs**. **Equipment** holds **Probes**, **Stock tanks**, **Tank & pump**, **Dosing** and **Setup**. **Settings & help** holds **Settings**, **Notifications** and **Help**. Every zone has its own page, opened from its card on Today. Select the room before editing; zone numbers belong to that room.

Old bookmarks still work and open the page that holds their content now:

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

New installation? Start with [Install, upgrade and rollback](INSTALL.md). To try the interface without connecting equipment, open the [interactive demo](https://jaketherabbit.github.io/HA-Irrigation-Strategy/dashboard.html?demo=1).

## What each action changes

| Action                                   | Where the change goes                                                  |
| ---------------------------------------- | ---------------------------------------------------------------------- |
| Edit targets (Plan › Targets)            | Local draft until reviewed and applied.                                |
| Apply reviewed changes                   | Existing HA setpoint entities; inspect readback.                       |
| Substrate, sizing, safety numbers        | Equipment › Setup; reviewed and applied the same way.                  |
| Review & save a grow plan                | HA's stored draft plan; separate from arming.                          |
| Arm plan                                 | Requests the eligible boundary activation; does not enable the engine. |
| Save a library recipe                    | This browser/site/room library; no HA write.                           |
| Save a run record (Settings › Run records) | Run metadata and its captured reference; no irrigation activation.   |
| Save configuration (Equipment › Setup)   | HA room/zone setup; wait for controller acknowledgement.               |
| Dose, make a batch, stop (Equipment › Dosing) | A request the controller carries out; the page switches nothing.  |
| Save the dosing setup (Equipment › Dosing) | HA's stored dosing setup for the room; the controller reads it.      |
| Save notifications (Settings & help › Notifications) | HA's stored notification setup for the whole site; the next push follows it. |
| Send a test (Settings & help › Notifications) | One push to that phone; nothing is saved.                     |

## Try the demo

The demo is an isolated software demonstration. Its readings, history, example plans and run records are synthetic; they are not a recommended configuration or evidence from a real grow. A demo tab cannot connect to live Home Assistant. It keeps the time of day: open it at night and the zones are in P3 with the pump resting.

1. Open **Today** and switch rooms with the chips in the top bar. Read the room's line, the zone cards and what Jev changed. Open a zone from its card.
2. On the zone's page, point at the chart's shots and Jev's marks, choose **Compare with** yesterday or a typical day, and read the probes and controls.
3. Open **Plan › Targets**, choose a zone and change its rescue level or re-water point. Compare the moving draft line with the saved reference, then use the review dialog to inspect the change.
4. Open **Plan › Schedule**. Read the flower by stage, then open **Advanced** to change a week's steering balance, inspect an endpoint profile, or open **Recipes** and preview **Demo • steady schedule** or **Demo • week-by-week changes**. Loading a recipe affects a local draft; the normal review/save remains separate.
5. Open **History**: filter the **Timeline**, read **Water use**, and open **Compare runs** to line up the demo's current run with the previous one by grow week.
6. Open **Equipment › Setup** to try entity search, room/zone names and mapping review. Demo actions do not call your HA server.
7. Open **Equipment › Dosing**: dose a pump, make a batch and stop it. The demo's pumps, valves and float move as real ones would, faster than real time.
8. Open **Settings & help › Notifications**: tick a kind of alert for a phone, save it through the review, and send a test (the demo sends nothing). Add `&notify-user=callum` to the address to open it as Callum, who is not an administrator.

A production recipe library starts empty. Demo recipes are interface examples and are stored separately from production libraries. Existing demo libraries, including deliberately empty or corrupt ones, are left unchanged.

Use **Settings › Sample workspace › Reset demo session…** and review the confirmation to restore the sample rooms, readings, run records and planner drafts. This discards unsaved demo work and session changes to runs/room settings. All saved recipe libraries and live connection data are retained; reset does not restore recipes you deliberately removed. Export any session work you want to keep first.

## The top bar

On every page the top bar shows each room as a chip with a dot and a word (watering, holding, not watering, stale, room off); the selected room's chip is pressed, and another room's chip opens that room. Beside them: how old the selected room's latest controller report is, **Recent activity** (the latest records in a panel beside any page, with **Open the timeline**), refresh, and the room's two safety switches, **Watering** and **Room**. Each switch asks for a review first. Neither is an emergency stop: use the installation's established physical shutdown procedure for an emergency.

## Today

Today is one screen on a laptop and about two on a phone.

- **The room's line**: watering on or off, the stage and day of flower (when the controller publishes Jev's stage arc), the steering, the stage's pore EC band, the lights, the phase the zones are in, and the open alerts. **N alerts** (or **N notes** for information such as a grow plan in control) opens the list. A room that is not watering says which switch stopped it, with a button to that switch in Settings.
- **The tanks**, one line, only when a feed or stock tank is low or out of range.
- **A card per zone**: its phase, moisture with the day's line and a bar against the rescue level, re-water point and peak, pore EC, water per plant against the room, the last shot, and what comes next. A card is flagged, with the reason in a line, only when the zone needs you:

| Flag                                             | When                                                                                    |
| ------------------------------------------------ | --------------------------------------------------------------------------------------- |
| Pore EC under or over the stage's band           | The zone's pore EC is outside the band of today's stage.                                 |
| Water per plant against the room                 | More than 140 % or less than 70 % of the room's median zone, once the day has started.   |
| Under the re-water point with no shot (critical) | In P2, moisture has sat under the re-water point for over an hour without a shot.        |
| A probe unusable or left out                     | A moisture probe cannot be used (critical); a pore EC probe or a probe left out (warning). |
| The zone's own alert                             | A notice the controller raised for this zone.                                            |
| A rescue shot                                    | One fired in the last 12 hours.                                                          |
| Jev's setpoints paused                           | Jev put a change back after a rescue and waits before trying again.                      |

- **What Jev changed today**, in a room running Jev: up to three changes, newest first, with **History** for the rest.

## A zone's page

Open a zone from its card on Today (or `#/zone/N`); the switcher at the top moves between zones.

- **Today in numbers**: moisture and how fast it is drying, pore EC against the stage's band, water today (the zone's total and each plant's share, in the order Settings › Appearance chooses) with its share of the daily water limit (amber from 80 %: routine shots stop at the limit), shots and the last one's time, and the overnight dryback (last night's, or tonight's so far) against Athena's target for the stage. **Next** says what comes next in a few words.
- **The day's chart**, from lights-on to the next lights-on, in the language of Athena's irrigation phase chart: the light cycle on top, Jev's decisions just below it (filled: code acted on it; outline: advice, no action or refused), P0 to P3 in columns with their badges along the bottom, field capacity as a dashed red line with the runoff zone of the zone's steering, the maintenance band from the re-water point to the peak target, the rescue floor overnight, VWC in blue with every shot as a dot where it started (a ring where a shot was held), the expected rest of the day dashed, and pore EC on the right-hand axis with the stage's band beside it. The VWC axis fits today's readings and the zone's targets. **Compare with** adds yesterday's line or the typical day of the last seven (the choice is remembered in the browser). Point at or tap the chart for the details of a shot, a decision, a phase or a moment.
- **Jev on this zone**: which judges act on it now, the P2 shot size and re-water point Jev may move and within what range (yours, and now), its last change, and its latest decisions here with a tick or a cross where it checked how they worked. **History** opens the timeline on this zone.
- **Targets**: the zone's targets as the controller uses them, by phase, with Jev's range beside the values it manages. **Edit in Plan** opens them on Plan › Targets.
- **Probes**: each probe behind the zone's moisture and pore EC, its reading, and whether the zone's reading uses it (see [Probes](#probes)).
- **Controls**: what the controller waits for next by its own numbers (for example: shot when VWC < 61 % (now 58 %) · dilution if pwEC > 3.84 · P3 by 20:36), **Pause zone scheduling** / **Enable zone scheduling**, and **Move to a phase**. Paused, the zone gets no water at all, not even a rescue shot, and a shot already running in it stops within a few seconds. A phase chosen by hand is reviewed first; the controller moves the zone within a minute and carries on from there (lights-off still moves it to P3 and lights-on to P0). Today's water and shot counts stay.
- **History**: the zone's readings over **Yesterday** or **7 days**; **Recorded behaviour against the targets** (typical peak, trough and dryback over days) opens on request.

## Plan › Targets

When no grow plan owns the room, Targets edits the current targets. An armed grow plan replaces the inputs with its read-only targets; if its required snapshot is missing or stale, the targets show as unavailable rather than falling back to the manual values.

1. Select a room, open **Plan › Targets**, and choose a zone (or **Room** for shared timing).
2. The zone's targets are one table by phase: P0 morning dryback, P1 ramp-up, P2 maintenance and P3 overnight dryback. Each setting's **?** says what it is, when it acts, what it affects, and what the Athena Handbook says. Where Jev manages a value, its range sits beside it. With Jev's Setpoints judge on the room, the **Auto** switch says what it lets Jev do: Jev manages the P2 shot size and re-water point. The same switch lets the engine's own learner keep the P1 target and field capacity in step with the peak the zone reaches, at most 2 points higher a day and only after the day's ramp reached the target.
3. The other steering mode's own targets (its P3 dryback and EC targets) are one tap down. Substrate, plants, drippers, flow and safety limits are on **Equipment › Setup**.
4. Type a value, or drag a target on the day's chart beside the table. Both edit the same local draft and respect the HA field's limits and step; the saved reference stays drawn for comparison, and the dark lines are what the zone's probe recorded.
5. Select **Review changes**, inspect every before/after value, then apply. Only this step sends the reviewed values to HA. Readback errors and unapplied values remain visible; do not assume a partially failed batch succeeded. Drafts survive a refresh and a room change asks before discarding them.

Room changes can be previewed against a selected zone. A zone's own value takes precedence over a room fallback where the controller supports it. Missing or invalid inputs remain missing/invalid instead of becoming an invented curve.

## Plan › Schedule

**This flower by stage** leads the page: the stages of this flower (flower setting, flower bulk, finish) with their flower days and weeks, what moves each on, steering, pore EC range, Athena's overnight dryback (40–50 % of the peak while setting, 30–40 % in the bulk, 40–50 % in the finish; as points of true water content under it) and runoff, today's week marked and when the next stage starts. Day 1 is the first day of 12/12; the arc is the one Jev steers by. **Validate preview** and **Arm plan** stay in view under it.

The planner schedules user-defined profiles by zone and grow day, under **Advanced**. The balance slider interpolates between the profile's explicit vegetative and generative endpoints; it does not select a built-in agronomic prescription. Equal endpoints intentionally produce equal targets at every slider position.

1. Open **Advanced › Endpoint profiles**. Inspect both endpoints and select the correct **Zone limits**. Duplicate a profile when you need an independent copy. A shared profile affects all schedule blocks referring to it.
2. Open **Advanced › Steering balance**. Select a zone and set **Zone grow start date**. Each zone can have its own start date.
3. Select a day or week in the grid, or type a balance (0–100 % generative) into it: Enter applies, Esc cancels, arrows move. The panel beside the grid shows the setpoints at that balance next to both endpoints and the balance either side. Assign the block's **Endpoint profile**. Days 1–366 are supported; range edits preserve surrounding assignments by splitting existing blocks.
4. Inspect **Zone schedule blocks** for coverage. Fill missing days and resolve overlap, parameter or zone-assignment errors.
5. Choose **Review & save** to validate and persist the draft in HA. **Validate preview** checks an unchanged stored draft. **Export** downloads a portable plan; **Reload stored plan** retrieves the stored revision once local edits are saved or discarded.
6. If you intend the controller to use the plan, review **Arm plan** separately. The controller must report support. Activation occurs at the eligible local lights-on boundary; arming does not enable the engine or pump.

An active/armed plan cannot be edited as a draft. **Disarm plan** requests the normal boundary handoff back to manual targets; wait for **draft** status before editing. The UI reports unsupported controllers, stale required snapshots and unfinished handoffs instead of claiming activation succeeded. Saving, arming and disarming a plan need a Home Assistant administrator login; any other login can open the plan and its previews, and is refused when it tries to change them.

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

**Timeline** is one list of the controller's records and Jev's decisions, newest first, by day. Jev's actions show by default; **All Jev decisions** adds every answer (with how sure it was, what it asked for, and what code did: acted, refused and why, advice, no action, waiting). A tick or a cross beside a decision is Jev's later check of whether it worked. A setpoint you changed by hand is marked yours; Jev only noted it. Filter by zone (or the room only), by type (water, phase, setpoints, alerts, Jev) and by words; **Export CSV** downloads what the filters show. It is not an immutable audit of every physical shot.

**Water use** shows litres per zone today, this grow week, since the grow start and estimated for the whole grow, with a bar for each grow week and, under it, today's water per zone and per plant. It counts grow-days from lights-on to lights-on and reads Home Assistant's long-term statistics, which Home Assistant keeps indefinitely; opened outside Home Assistant it can only read recorded history, as far back as the recorder keeps it. The grow start is the zone's grow plan start date when the plan is armed or has been saved; without one it is inferred (the first day with water after at least five grow-days without any), and the panel says which. A day Home Assistant did not record is flagged, never counted as zero.

**Compare runs** lines the run in progress up against an earlier one by grow week:

1. Choose **This run**, **Compare with** and the **Zone**. The latest ended run is chosen to start with.
2. Read the weeks table: each week's typical day as moisture low–high, pore EC low–high and water per plant a day, this run's figure with the compared run's under it. **Biggest differences** names up to three weeks where they differ by more than a few points of moisture, a few tenths of pore EC or a fifth of the water per plant.
3. **Full-resolution chart, with a target reference** (one tap down) draws the recorded VWC and EC for **Day**, **Week · 7 days**, **Calendar month**, **Run to date** or **Custom dates**. Choose a **Target reference**: **Current configured daily plan**, **Saved run daily reference**, or **Current phase reference**, and read its capture/source note. Use **Refresh history** to advance the window.
4. **Data quality: daily ranges and history coverage** (one tap down) shows each day's recorded range as bars on one scale, the compared run grey, and where the weekly figures come from.

Run records themselves are kept in **Settings › Run records** (**Run records** on Compare runs goes there): **Add run** with the actual name, start date and optional end date, then **Save run record**. This saves metadata and a timestamped reference configuration; it does not arm irrigation. **Export metadata** backs up run definitions and reference snapshots, not Recorder readings. **Archive** and **Restore** keep the registered run's identity. Saving, archiving and importing run records need a Home Assistant administrator login; any login can view them. Registering last month's run today captures today's reference configuration: it cannot recover last month's setpoints or expired Recorder data. Each room supports up to 100 run records; a completed run covers 1–366 inclusive calendar days.

## Equipment

### Probes

At the top: how many probes are OK, whether the controller is reporting, and Jev's state. Then each zone's probes, name first with the entity ID under it, with the reading, when it last reported, the last six hours, whether the zone's reading uses it, and its health:

| Health           | Meaning                                                                                              |
| ---------------- | ---------------------------------------------------------------------------------------------------- |
| OK               | Reporting, in range, and moving as a probe should.                                                   |
| Silent / Not reporting | The integration says it stopped reporting (or the zone's own reading went stale); since when. |
| Out of range     | A reading the integration's range (0–100 % VWC, 0–20 mS/cm EC) says cannot be real.                  |
| No reading       | Unavailable, unknown or not a number.                                                                |
| Unchanged for    | The same reading for over 3 h (moisture) or 6 h (pore EC): likely stuck.                             |
| Left out         | The integration combined the zone's other probes without it, and says why.                           |

An older integration publishes only each zone's combined reading, which then stands in for its probes. Each zone's valve is shown beside its probes. **Room map** and **Controller internals** (every sensor of the room with its reading, the last hours and its availability, searchable and filterable) are one tap down. **Map probes** opens Setup.

### Stock tanks

**Next to run out** leads: the tank with the fewest batches left. Each tank shows its level against its low mark (amber within half again of it, red at it), with **Refilled**, **Set level** and the batches left. A tank linked to a dosing pump (in **Equipment › Dosing › Dosing setup**) says **Drawn by** that pump **as it doses**, with its recent draws: Crop Steering takes what the pump actually ran off it, whoever started the dose (the controller, an automation, or someone at the doser), and the tank's fills no longer count against it; its batches left are at the pump's recipe amount. **Record a batch** takes the recipe's doses off every tank; recent draws are one tap down. **Edit stock tanks** adds, renames and removes tanks.

### Tank and pump

**Equipment › Tank & pump** draws the feed tank's level, EC, pH and temperature with a last-day line beside EC and pH, the pump's state, and the last recorded fill. **History** opens both readings over 24 hours, 7 days or 30 days with the feed-water gate drawn where the room gates on those probes. Choose **Map sensors**, or open **Equipment › Setup › Shared room hardware**. These are explicit mappings; the dashboard does not guess that a room-temperature or feed-water probe is a tank probe.

**Tank level and watering**, under the tank, draws the level over 24 hours, 3 days or 7 days with what moved it: each zone's shots as dots on the line, the pump's runs and the tank filling as bars above it, and each recorded fill as a dashed line. Hover or tap a mark to see what it was: the zone, how long its valve was open and about how many litres that is at the configured flow, or how long the pump ran or the tank filled. The list under the chart names every event in the range. It reads Home Assistant's recorder, as a zone's Today chart does, and keeps up as new readings arrive. The level is what the mapped level sensor reports, and the chart says plainly that the dashboard cannot tell whether that sensor measures the water or works it out, for example from pump run time since the last fill. Shots are valve open times, the pump and filling bars are the switches' own reports, and a recorded fill is a newer time on the last-fill record: a restart recording the same time again is not a fill.

| Setup label             | Configuration key         | Select                                                                                                                |
| ----------------------- | ------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Room pump               | `pump_switch`             | The room pump's actual HA switch. The controller descriptor publishes this as `pump`.                                 |
| Tank fill level (%)     | `water_level_sensor`      | A percentage sensor, 0-100. A litres value is not a percentage.                                                       |
| Tank EC (display)       | `tank_ec_sensor`          | A tank conductivity sensor in mS/cm or dS/m accepted by setup.                                                        |
| Tank pH (display)       | `tank_ph_sensor`          | A pH sensor.                                                                                                          |
| Tank temperature        | `tank_temperature_sensor` | A tank-water temperature sensor in °C, °F or K; its unit is retained.                                                 |
| Tank filling status     | `tank_fill_entity`        | A fill-valve switch or binary sensor whose on/off state represents fill activity.                                     |
| Last recorded tank fill | `tank_last_fill_sensor`   | A timestamp sensor with a dated, timezone-aware state, or an `input_datetime` helper with both date and time enabled. |

**Tank EC (display)** and **Tank pH (display)** only populate the panel. **Feed-water EC** and **Feed-water pH** are separate mappings used by configured control gates. Mapping a tank display does not enable those gates or nutrient dosing.

**Last recorded fill** has the meaning supplied by your existing recording automation: for example, a verified full-float event or an operator's explicit “mark filled” action. A full date/time helper uses its timestamp attribute; a sensor's `last_changed`, an automation's `last_triggered`, a fill-mode enable flag and a dosing interlock are not equivalent to a fill record. The panel does not create a fill-recording automation for you. A percentage source may itself be an estimate; drawing it as a tank does not turn it into a measured level. Tank readings and switch reports do not prove dose completion, water quality suitability or physical delivery.

Unmapped inputs show **Not mapped**; invalid readings show **Unavailable**, **Check units** or **Out of range**. An unknown pump is not shown as off and an unknown tank is not drawn empty. When disconnected, the panel identifies retained readings as last received.

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

An HA administrator uses **Equipment › Setup**. Pair devices and expose their entities in HA first; this workspace maps existing entities.

1. Choose an existing room or **Add room**. Give it a clear name. Names may change without changing its stable identity. Say how the room is plumbed (zone valves only, or a pump and valves); nothing is guessed from empty fields.
2. Map **Room pump** and **Mainline valve** where the plumbing has them, then each active zone's valve. Search by friendly name or exact entity ID; inspect the displayed value/unit before selecting.
3. Select one or more VWC and EC probes per zone. **Clear mapping** removes the selected mapping; **Done** closes the picker. Multiple valid readings are combined by the integration, which leaves out a probe that is not reporting or out of range and says so (see [Probes](#probes)).
4. Enter plant count, substrate litres **per plant** (or choose a pot or rockwool preset), drippers **per plant**, and flow in litres/hour **per dripper**. **Units** in Settings switch volume and flow to US gallons and GPH for typing; values are saved in litres. A zone's catch test works out the flow per dripper from a timed catch and fills only the draft.
5. Map optional room equipment, tank displays and any feed-water safety probes as separate roles. Explicitly map shared equipment only where appropriate; never reuse a zone valve accidentally.
6. Stop affected engines and verify the implicated irrigation equipment is OFF. **Review configuration** shows the changes and blockers; **Save configuration** persists the setup after backend validation.
7. Wait for controller acknowledgement of the saved setup revision. A saved configuration and an adopted configuration are different states. Then verify **Today** and **Equipment › Probes** before restoring the prior scheduling state.

Zone and room removal archives stable IDs. **Restore zone** or **Restore room** reactivates the same identity after review; archived slots are not silently reused for different hardware. Adding/archiving a zone may require updating a draft grow plan's assignments.

Under the rooms, **substrate, sizing and safety limits** are the numbers the controller works with, per zone and for the room: full saturation (with a suggestion from the zone's learned or typical daily peak, used only in the draft), substrate and hardware sizing, and, one tap down, the safety limits (daily water limit, maximum substrate EC, watchdog and the like). Each change is reviewed before it is written. **Water & calibration** (one tap down) shows what a shot of each phase delivers in litres per zone and millilitres per plant, the runtime and its caps, and a catch-test calculator that tries a measured flow in that calculation only; it does not write calibration or operate irrigation.

## Settings & help

**Settings** holds:

- **Home Assistant connection**. The native HA sidebar normally uses your existing HA session. An explicit URL and a long-lived access token also work for a standalone tab; the token is kept for that tab session and is never put in the URL. A hosted HTTPS page may be unable to access a local HTTP HA server because of browser origin/security rules; use the native sidebar for the normal installation.
- **Room on / off**: switch the room off when nothing is growing in it. Off, the controller does not water it and raises no alerts for it, and a shot already running stops within a few seconds. On within a day it carries on where it was; on after longer, daily counters and learned phase state reset for a fresh run.
- **Watering**: the room's engine switch ("Engine Enabled" in Home Assistant on a room made by the setup wizard). With watering off the controller opens no valve in the room and a shot already running stops within a few seconds; it keeps reading the probes and following the phases. A new room starts with watering off.
- **Every zone's scheduling**: one switch for every zone of the room, as the header toggle of a Home Assistant entities card. It is on while any zone is on. Off pauses every zone; on switches every zone on, a zone you paused yourself included. Each zone still has its own switch on its page, and like them this one asks for a review first.
- **Run records**: see [History](#history).
- **Appearance**: **Home Assistant / system** inherits the HA theme when embedded on the same origin, or the device theme in standalone mode; **Light** and **Dark** are explicit overrides. Cross-origin embedding cannot read the host theme. **Water today, shown as** chooses whether a zone's page leads with the zone's total, the default, or each plant's share (the zone's water today divided by its plant count from Setup, as if every plant got the same). The choice is the room's, kept in Home Assistant (`select.crop_steering_<prefix>water_today_view`): everyone who opens a zone's page sees water that way, and the controller's vitals notification follows it. Today compares the zones per plant either way; water use over the grow stays in litres per zone.
- **Units**: how pot volume and dripper flow are shown and typed in this browser.
- **Sample workspace**, in the demo only.

Inside a compatible same-origin HA shell, the workspace temporarily collapses HA's sidebar. Use **Home Assistant** at the bottom of the workspace navigation, or the house button labelled **Open Home Assistant menu** in the top bar, to reopen HA's menu. Leaving the workspace restores the prior temporary state; it does not change the saved HA sidebar preference. Standalone and unsupported embeddings keep normal navigation. See [Home Assistant sidebar](HA_SIDEBAR.md) for compatibility limits.

After an update, the first person to open the dashboard sees **What's new**: the main changes of every release this installation had not yet shown, in a few plain lines each, with a link to the full release notes. It shows once for everyone, never on a new installation, and **Help › What's new** opens the latest releases again at any time.

**Help** lists every error code an alert or Repairs card can end with (such as CS-101), searchable, with what it means, what happens to watering meanwhile, likely causes and fixes; `#/help?code=CS-101` opens one. Its glossary explains VWC, pore EC, dryback, the four phases, steering and runoff.

For an existing timed zone hold, Home Assistant exposes the `crop_steering.set_manual_override` action. The action refuses a signed-in user who is not an administrator (automations can still call it); the switch itself follows Home Assistant's own user permissions. Its timeout defaults to 60 minutes and accepts 1-1440 minutes; specify the intended zone and room slug (omit the room for the legacy default room). Clearing the hold is distinct from enabling zone/room scheduling. Turning its switch on directly creates an indefinite hold. See the action's fields in HA and the [entity reference](ENTITIES.md).

## Settings & help › Notifications

Every alert is still a Home Assistant notification, as before. This page chooses who gets a phone push for what, for the whole site: a row per phone, a checkbox per kind of alert, and a push goes only to the phones whose row ticks its kind. An alert that falls under two ticked kinds reaches that phone once. [Notifications](NOTIFICATIONS.md) describes what the integration, the controller and this page each do.

- **The grid**: each row is a phone, named by whose it is and the device; a notify service that is not one of the site's phones, such as a group, shows its name (`notify.family`). Each column is a kind of alert: Emergencies, Hardware lockouts, Sensors and drift, Watering stopped, Phase changes, Stock tanks, Dosing, Jev, and Setup and settings. Open a column's heading for what it covers: its alert codes with their titles (each opens Help), and the pushes that are not alerts, a zone changing phase and Jev moving a setting.
- **Rooms**: **All**, or the rooms you choose. Taking the last chosen room out covers every room again.
- **High priority for emergencies**: critical alerts reach that phone as high-priority, time-sensitive pushes.
- **Send a test**: one push to that phone, and beside the button whether it went.
- **Watering stopped**: "Tell me when a room has watered nothing for 3 hours with the lights on", from 1 to 12 hours. The controller then raises CS-209 for the room and pushes it to the phones that tick Watering stopped, again every so many hours while it lasts; the next shot ends it. The clock runs only while a zone is in P1 or P2, not in the morning dryback or overnight.
- **Add a phone** (administrators): one of the site's phones not listed yet, or any notify service by its name. A new row starts with Emergencies ticked for every room. The bin beside a row removes it.

Changes are a draft until **Review and save**: the review lists what changes for each phone, and nothing is saved before it. If someone else saved meanwhile, the page reads their setup again with your changes kept on top, and asks you to check them and save again. A room no row sends emergencies to is named above the grid: "Nobody gets emergencies for Flower 1". Its emergencies are not lost meanwhile: they go to every phone that gets emergencies, or to the controller app's `notify_service` option when none does. Tapping any push opens Crop Steering.

A Home Assistant administrator changes every row, adds and removes phones and sets the threshold. Anyone else sees every row but ticks only their own phone's, and tests only that phone: "Only an administrator can change other people's phones". On a phone, the grid is a card per phone with the same checkboxes.

With no phone listed, every push goes to the controller app's `notify_service` option, the way it always has, so an installation that never opens this page behaves as before.

## A daily routine

1. Open **Today**. A room that is watering with no flagged card needs nothing; read what Jev changed.
2. Open any flagged zone from its card: its numbers, the day's chart and **Controls** say what happened and what the controller waits for.
3. Change targets on **Plan › Targets** only through the review; check the readback.
4. Once a day or after a change, glance at **Equipment › Probes** and **Stock tanks**.

## What the numbers mean

- **Water per zone and per plant**: zone water is the controller's delivered estimate for all the zone's plants; per plant divides it by the plant count. Substrate litres describe the combined pot capacity; they are not water delivered. Runtime estimates multiply dripper flow by run time and respect the controller's duration limit.
- **Dryback** is relative to the peak: (peak VWC − current VWC) ÷ peak VWC × 100. A 60 % peak and a 10 % dryback target mean 54 % VWC, not 50 %. Athena's overnight dryback targets are set the same way.
- **Steering balance**: 0 % uses the vegetative endpoint, 100 % the generative one, and values between blend their explicit parameters. Pot size and dripper flow convert shot percentages to volume and time.
- **Planning versus history**: the day's projected curve is drawn from targets; recorded history comes from Home Assistant's Recorder. Neither an event acknowledgement nor a modelled curve proves physical delivery.
- **Run comparisons** align runs by grow age and stop the previous run at the current one's age. A saved target reference shows when it was captured; backdating a run does not recreate old targets or readings removed by Recorder retention.
- **When changes take effect**: target writes use fresh bounds and state readback. Grow plans are saved as drafts, explicitly armed, then activated at a local lights-on boundary; disarming an active plan retains its targets until the next boundary. Mapping changes require disarmed engines and hardware OFF; saving configuration confirms Home Assistant storage, and the controller's revision acknowledgement comes after.
- **What is not claimed**: this controller does not regulate room climate or predict yield or potency. Historical manual-shot and phase-event services have no verified execution consumer in the shipped polling engine and are not exposed as operating buttons. Missing or stale readings stay unavailable.

## Understand the graphs and water figures

| View                          | What it shows                                                                                                            | What it does not establish                                                                  |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------- |
| A zone's day chart            | Today's recorded VWC, pore EC, shots, phases and Jev's decisions, with the expected rest of the day dashed.              | Exact future shot times, uptake, runoff or EC accumulation.                                 |
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

| Symptom                                        | Next step                                                                                                                                                                   |
| ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| No rooms or missing workspace services         | Verify the integration loaded, the controller version matches, and the current HA account can access the entities/services. Refresh after upgrading.                        |
| Tank **Not mapped**                            | Set that exact optional display mapping. A similarly named feed or ambient probe is not an implicit fallback.                                                               |
| Last irrigation/fill is missing                | Check the event-producing source and its dated timestamp format. A state update time cannot substitute for the event.                                                       |
| A reading shows **Check units**                | Inspect the actual HA unit and choose/repair the appropriate entity. Do not relabel an unrelated quantity to pass validation.                                               |
| A probe is **Left out** or **Silent**          | Check the probe on Equipment › Probes: its last report, its reading and the integration's reason. The zone reads its other probes meanwhile.                                |
| Setup is saved but adoption is pending         | Inspect heartbeat/setup blockers; keep affected engines off until the controller acknowledges the revision.                                                                 |
| Slider appears to do nothing                   | Inspect both selected endpoint columns. Equal endpoints are deliberately equal at every balance.                                                                            |
| Targets are read-only                          | Inspect the grow plan or connection state. An armed plan shows its effective read-only targets; use Schedule and the normal boundary handoff before manual editing.         |
| Cannot load a recipe                           | Check active-zone IDs, current limits, plan state, connection and explicit replacement acknowledgement.                                                                     |
| Comparison is blank                            | Check selected run/zone, recorded sensor IDs, dates, Recorder retention and coverage notices. Registering metadata cannot recreate readings.                                |
| A pause was confirmed but equipment remains on | Pause affects scheduling. Inspect the active shot and use the site's established physical shutdown procedure if necessary.                                                  |

For source/test evidence and outstanding commissioning limits, use the [feature matrix](FEATURE_MATRIX.md) and [troubleshooting guide](troubleshooting.md). Software validation does not prove physical delivery or a complete live recipe handoff.
