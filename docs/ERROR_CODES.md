# Error codes

<!-- Generated from docs/error-codes.json by scripts/render_error_codes.py. Edit the JSON. -->

Every notification from the Crop Steering controller app, and every Crop Steering card under
**Settings → Repairs**, ends with a code such as **CS-101**. Find the code below for what it
means, what happens to watering meanwhile, the likely causes and what to do. The same list is
in the Crop Steering sidebar under **Help & tools → Error codes**.

A notification is raised again, at most every 30 minutes, for as long as its cause lasts.
A room whose *Room Active* switch is off (nothing growing) raises none for that room.

| Codes | About |
| --- | --- |
| CS-1xx | **Sensors**: A moisture or EC reading the controller cannot use. |
| CS-2xx | **Watering held**: Something is stopping shots in a room or a zone. |
| CS-3xx | **Pumps and valves**: A switch did not do what it was told, or a shot was cut. |
| CS-4xx | **Settings**: A setting is missing, out of range, or read from somewhere new. |
| CS-5xx | **Checks across zones**: Advice from comparing a room's zones. |
| CS-6xx | **Repairs cards**: Raised by the integration, under Settings → Repairs. |

## All codes

| Code | What it says | Severity | Shown as |
| --- | --- | --- | --- |
| [CS-101](#cs-101) | Moisture reading hasn't changed | Warning | Notification |
| [CS-102](#cs-102) | Moisture sensor not reporting | Warning | Notification |
| [CS-103](#cs-103) | Moisture reading out of range | Warning | Notification |
| [CS-104](#cs-104) | Root-zone EC not available | Warning | Notification |
| [CS-201](#cs-201) | Setup change waiting, not watering | Critical | Notification |
| [CS-202](#cs-202) | Plumbing and switches disagree, not watering | Critical | Notification |
| [CS-203](#cs-203) | Maximum shot length not valid, not watering | Critical | Notification |
| [CS-204](#cs-204) | Shot size can't be worked out, not watering | Critical | Notification |
| [CS-205](#cs-205) | Daily water limit reached | Information | Notification |
| [CS-206](#cs-206) | Root-zone EC too high, not watering | Warning | Notification |
| [CS-207](#cs-207) | URGENT, drying out and not being watered | Critical | Notification |
| [CS-301](#cs-301) | CRITICAL hardware fault, watering stopped | Critical | Notification |
| [CS-302](#cs-302) | Shot cancelled, the pump didn't switch on | Warning | Notification |
| [CS-303](#cs-303) | Shot cancelled, the main-line valve didn't switch on | Warning | Notification |
| [CS-304](#cs-304) | Shot cancelled, the zone valve didn't switch on | Warning | Notification |
| [CS-305](#cs-305) | Shot stopped early | Information | Notification |
| [CS-306](#cs-306) | Shot shortened to the safety limit | Warning | Notification |
| [CS-307](#cs-307) | Shot stopped early, something else closed the feed | Warning | Notification |
| [CS-308](#cs-308) | CRITICAL, an interrupted shot's hardware is still ON | Critical | Notification |
| [CS-309](#cs-309) | An interrupted shot's hardware may still be ON | Warning | Notification |
| [CS-401](#cs-401) | Setting outside the engine's range | Warning | Notification |
| [CS-402](#cs-402) | Settings missing, running on built-in values | Critical | Notification |
| [CS-403](#cs-403) | Lights hours now come from the integration | Information | Notification |
| [CS-404](#cs-404) | Automatic targets paused | Warning | Notification |
| [CS-405](#cs-405) | Timezone mismatch, the day may be shifted | Warning | Notification |
| [CS-501](#cs-501) | Much less water than the other zones | Information | Notification |
| [CS-601](#cs-601) | Kill switch helper missing | Critical | Repairs card |
| [CS-602](#cs-602) | Engine not running | Warning | Repairs card |
| [CS-603](#cs-603) | Zone with no moisture sensor | Warning | Repairs card |
| [CS-604](#cs-604) | Zone sensor unavailable | Warning | Repairs card |
| [CS-605](#cs-605) | Settings not where the controller looks for them | Critical | Repairs card |
| [CS-606](#cs-606) | Grow plan is holding irrigation | Critical | Repairs card |
| [CS-607](#cs-607) | Grow plan hasn't moved on to today | Warning | Repairs card |

## Sensors (CS-1xx)

<a id="cs-101"></a>

### CS-101: Moisture reading hasn't changed

*Warning · Notification*

**What it means.** The zone's moisture reading has stayed exactly the same for more than 20 minutes. A working probe in a cube with a plant drinking from it moves all the time, so the controller cannot tell this one from a probe that has stopped updating or been pulled out, and does not steer by it.

**Watering meanwhile.** Carries on without the probe while the engine is on. If another zone in the room has a working probe, this zone gets the same shots as that zone; otherwise it gets one shot every 90 minutes, within its daily water limit. Phase changes that go by moisture wait until the reading moves.

**Likely causes**

- No plant in the cube, or a plant too small to drink much yet: nothing takes water out, so the number never moves. Expected on a bench test or a new install.
- The probe has been pulled out of the cube, or is lying in a tray.
- The cube is soaked and the probe is pinned at its highest reading.
- The probe's own integration has stopped updating and keeps showing its last value.

**Suggested fixes**

- With no plant in, or a plant not yet drinking: nothing to fix. The notification stops by itself once the reading changes.
- If the room is empty, switch its Room Active switch off: an empty room gets no watering and no notifications until it is switched back on.
- Check the probe is pushed fully into the cube.
- Open the sensor's history in Home Assistant. A flat line for hours while plants are drinking means the probe or its integration has stopped: reconnect or restart it.

<a id="cs-102"></a>

### CS-102: Moisture sensor not reporting

*Warning · Notification*

**What it means.** The zone's moisture sensor reads 'unavailable' or 'unknown', isn't a number, or can't be found in Home Assistant at all. The notification says which.

**Watering meanwhile.** Carries on without the probe while the engine is on: the same shots as a zone whose probe is working, or one shot every 90 minutes within the daily water limit if there is none. Phase changes that go by moisture wait for the probe.

**Likely causes**

- The probe is offline: no power, a flat battery, or out of Wi-Fi or Zigbee range.
- Home Assistant has just restarted and the probe's integration hasn't loaded yet.
- The probe was renamed or removed, so the sensor mapped to the zone no longer exists.

**Suggested fixes**

- Find the sensor named in the notification under Settings → Developer tools → States and check what it reads.
- Check the probe's device is powered and online.
- In Crop Steering → Rooms & setup, check the zone's moisture sensor is the probe you expect.

<a id="cs-103"></a>

### CS-103: Moisture reading out of range

*Warning · Notification*

**What it means.** The zone's moisture sensor reports a number that can't be a moisture reading (below 0 % or above 100 %), so the controller ignores it.

**Watering meanwhile.** Carries on without the probe while the engine is on, as for CS-102.

**Likely causes**

- The probe is faulty or badly calibrated.
- The sensor mapped to the zone isn't a moisture percentage: a raw count, a voltage, or a different reading from the same device.

**Suggested fixes**

- Check the probe's calibration in its own integration.
- In Crop Steering → Rooms & setup, check the zone's moisture sensor is the moisture reading in %, not another entity from the same device.

<a id="cs-104"></a>

### CS-104: Root-zone EC not available

*Warning · Notification*

**What it means.** There is no usable root-zone EC reading for the zone: it is missing, unavailable, out of range, or hasn't changed for 20 minutes.

**Watering meanwhile.** Carries on by moisture alone. EC-based shot sizing and EC learning are paused, and salt build-up can't be checked or flushed.

**Likely causes**

- No EC probe is mapped to the zone.
- The EC probe is offline, or reads the same number for more than 20 minutes (a cube with no plant in it, as for CS-101).

**Suggested fixes**

- Map an EC probe to the zone in Crop Steering → Rooms & setup, if the zone has one.
- Check the probe is online and its reading moves.

## Watering held (CS-2xx)

<a id="cs-201"></a>

### CS-201: Setup change waiting, not watering

*Critical · Notification*

**What it means.** A changed setup was saved for the room (in Rooms & setup or Configure), and the controller only takes on a new setup while the engine switch and every pump and valve it would drive are OFF. The notification lists the ones that are still on.

**Watering meanwhile.** Nothing in the room is watered until the controller has taken on the new setup.

**Likely causes**

- The setup was saved while the engine switch was on.
- A pump or valve was left on, or reads 'unavailable'.

**Suggested fixes**

- Turn off everything the notification lists.
- Wait for the notification to clear, up to 5 minutes.
- Turn the engine switch back on.

<a id="cs-202"></a>

### CS-202: Plumbing and switches disagree, not watering

*Critical · Notification*

**What it means.** The room was set up as having a pump (or a main-line valve) and none is mapped, or the other way round. Rather than open a valve with no pump behind it, and count a shot that delivered nothing, the controller holds.

**Watering meanwhile.** Nothing in the room is watered until they agree.

**Likely causes**

- The pump or main-line switch was cleared from the room's setup, or its device was removed.
- The plumbing chosen in setup isn't the room's real plumbing.
- The integration is newer than the controller app and uses a plumbing layout the app doesn't know yet.

**Suggested fixes**

- In Crop Steering → Rooms & setup, map the missing switch, or change the plumbing to what the room really has. The detail in the notification says which.
- If it names a layout the controller doesn't know, update the controller app.
- The hold clears by itself once the corrected setup is taken on (see CS-201).

<a id="cs-203"></a>

### CS-203: Maximum shot length not valid, not watering

*Critical · Notification*

**What it means.** The room's maximum shot length must be a number of at least 5 seconds, and it isn't. It is never replaced by a default, because a default could flood a room.

**Watering meanwhile.** No shot is started in the room.

**Likely causes**

- The setting reads 'unavailable', because the integration hasn't loaded.
- It has been set below 5 seconds.

**Suggested fixes**

- Check the Crop Steering integration is loaded (Settings → Devices & services).
- Set Maximum shot duration to at least 5 seconds.

<a id="cs-204"></a>

### CS-204: Shot size can't be worked out, not watering

*Critical · Notification*

**What it means.** The controller sizes every shot from the zone's pot size (litres per plant), plant count, drippers per plant and dripper flow. One of them is missing, zero or unreadable, so it can't tell how long to run.

**Watering meanwhile.** The zone is not watered.

**Likely causes**

- Pot size, drippers per plant or dripper flow is 0 or empty.
- A setting reads 'unavailable', because the integration hasn't loaded.

**Suggested fixes**

- Set the zone's pot size, plant count, drippers per plant and dripper flow in Crop Steering → Rooms & setup.
- Check the Crop Steering integration is loaded.

<a id="cs-205"></a>

### CS-205: Daily water limit reached

*Information · Notification*

**What it means.** The zone has had its daily water limit (max daily volume), counted from lights-on. A shot that would cross it gets only what is left; once too little is left for the shortest shot, routine shots stop.

**Watering meanwhile.** Routine top-ups and EC-correction shots stop until lights-on starts the next day. The morning ramp, the overnight emergency shot, the no-water-for-hours safety shot and high-EC flushes still run.

**Likely causes**

- The plants really are using that much: the limit is too low for their size.
- Shots are delivering more than planned (dripper flow set lower than it really is), so the limit is reached early.
- The probe keeps reading dry, so the controller keeps asking for water (a probe in a dry spot, or water not reaching it).

**Suggested fixes**

- Do a catch test to check the real flow, and correct the dripper flow setting.
- Check the probe is in the cube and the drippers reach it.
- Raise the zone's max daily volume only once the above are right.

<a id="cs-206"></a>

### CS-206: Root-zone EC too high, not watering

*Warning · Notification*

**What it means.** Root-zone EC is above the zone's maximum, and a flush can't bring it down right now: the feed is no weaker than what is in the root zone, or the cube is already saturated.

**Watering meanwhile.** The zone is held. It clears by itself once a flush could help (a weaker feed, or the cube drying back).

**Likely causes**

- The feed EC is as high as, or higher than, the root zone.
- The cube is at field capacity, so more water would only run off.
- The EC probe reads high (calibration, or a probe that has dried out).

**Suggested fixes**

- Check the feed EC in the tank and bring it down if it is high.
- Check the EC probe against a hand-held meter.
- Check the zone's maximum EC setting is what you intend.

<a id="cs-207"></a>

### CS-207: URGENT, drying out and not being watered

*Critical · Notification*

**What it means.** The zone is below its watering trigger and hasn't been watered for longer than its watchdog time (3 hours by default), but something is blocking every shot. The notification names what is blocking.

**Watering meanwhile.** Blocked, by the reason the notification names.

**Likely causes**

- The engine switch is off. On a new install this is expected: the reminder is that nothing will be watered until it is on.
- Auto irrigation or the zone is switched off, or manual override is on.
- A hold: a setup change waiting (CS-201), plumbing that disagrees (CS-202), a hardware fault (CS-301), an external hold (dosing, a fill, a flush), or the source-water EC or pH out of range. A grow plan's hold (CS-606) does not stop this safety shot.

**Suggested fixes**

- Read 'Blocked by' in the notification and deal with that.
- If the room is off on purpose, water by hand or turn the engine on.
- If nothing is growing, switch the room's Room Active switch off: an empty room gets no watering and no notifications.

## Pumps and valves (CS-3xx)

<a id="cs-301"></a>

### CS-301: CRITICAL hardware fault, watering stopped

*Critical · Notification*

**What it means.** A pump or valve did not confirm it had switched OFF: after a shot, after a shot something else cut short (CS-307), or while an interrupted shot was being closed (CS-308). It may still be running. The controller latches a hold on that hardware, remembered across restarts.

**Watering meanwhile.** Stopped on that hardware, in every room that shares it, until the hold is cleared.

**Likely causes**

- The switch's device went offline in the middle of a shot.
- A relay or valve is stuck on.
- The switch reports its state late, or not at all.

**Suggested fixes**

- Check the pump and valves now, and switch them off by hand if they are running.
- Turn off the engine switch of this room and of every room sharing the hardware.
- The hold clears once all of them read OFF; then turn the engine back on.
- If the notification says the fault could not be saved, do not restart the controller until it is repaired.

<a id="cs-302"></a>

### CS-302: Shot cancelled, the pump didn't switch on

*Warning · Notification*

**What it means.** Home Assistant returned an error when the controller switched the pump on.

**Watering meanwhile.** That shot was cancelled and not counted. The next shot is tried as normal.

**Likely causes**

- The pump's switch is offline or 'unavailable'.
- The mapped entity no longer exists.

**Suggested fixes**

- Switch the pump on and off by hand in Home Assistant to check it responds.
- Check the pump mapped in Crop Steering → Rooms & setup.

<a id="cs-303"></a>

### CS-303: Shot cancelled, the main-line valve didn't switch on

*Warning · Notification*

**What it means.** Home Assistant returned an error when the controller switched the main-line valve on. The pump was switched off again.

**Watering meanwhile.** That shot was cancelled and not counted. The next shot is tried as normal.

**Likely causes**

- The main-line valve's switch is offline or 'unavailable'.
- The mapped entity no longer exists.

**Suggested fixes**

- Switch the valve on and off by hand in Home Assistant to check it responds.
- Check the main-line valve mapped in Crop Steering → Rooms & setup.

<a id="cs-304"></a>

### CS-304: Shot cancelled, the zone valve didn't switch on

*Warning · Notification*

**What it means.** Home Assistant returned an error when the controller switched the zone's valve on. Anything upstream was switched off again.

**Watering meanwhile.** That shot was cancelled and not counted. The next shot is tried as normal.

**Likely causes**

- The valve's switch is offline or 'unavailable'.
- The mapped entity no longer exists.

**Suggested fixes**

- Switch the valve on and off by hand in Home Assistant to check it responds.
- Check the zone's valve mapped in Crop Steering → Rooms & setup.

<a id="cs-305"></a>

### CS-305: Shot stopped early

*Information · Notification*

**What it means.** A shot was stopped part-way because the engine switch was turned off or manual override was turned on while it ran. The valve is closed.

**Watering meanwhile.** The water delivered before the stop is counted. The next shot is decided as normal.

**Likely causes**

- Someone turned the engine switch off, or manual override on, during a shot.
- An automation did.

**Suggested fixes**

- Nothing, if it was meant.
- Otherwise, find what switched it (the switch's logbook shows who or what).

<a id="cs-306"></a>

### CS-306: Shot shortened to the safety limit

*Warning · Notification*

**What it means.** The planned shot would run longer than the room's maximum shot length, so it was cut to that limit and delivered less than planned.

**Watering meanwhile.** Carries on, but each such shot delivers less than planned.

**Likely causes**

- Dripper flow or drippers per plant set too low, so the controller thinks it needs a long run.
- Pot size set too high.
- A maximum shot length too short for the room.

**Suggested fixes**

- Check the zone's pot size, drippers per plant and dripper flow; a catch test gives the real flow.
- If they are right, raise Maximum shot duration.

<a id="cs-307"></a>

### CS-307: Shot stopped early, something else closed the feed

*Warning · Notification*

**What it means.** During a shot, one of the room's holds (dosing, a tank fill, a flush) came on, or the zone's valve was switched off by something other than the controller. The controller checks for this about every 2 seconds during a shot. The shot ended there: the controller closed its own valve and main line if they were still open, and left the pump alone if a hold is using it.

**Watering meanwhile.** Only the seconds the valve was open are counted. The next shot is decided as normal.

**Likely causes**

- A dosing or tank-fill automation took the tank or its pump part-way through a shot (on 23 September a batch tank ran empty 4 seconds into a shot).
- A guard automation or a person switched the zone's valve off.
- The valve's device dropped off the network.

**Suggested fixes**

- Nothing, if it was meant.
- If it happens often, schedule dosing and tank fills away from shot times.
- Otherwise, find what switched the valve: its logbook shows who or what.

<a id="cs-308"></a>

### CS-308: CRITICAL, an interrupted shot's hardware is still ON

*Critical · Notification*

**What it means.** A shot never finished: the controller stopped, crashed or lost Home Assistant part-way through it. On the next start it switched off what that shot had opened, and at least one of those switches still does not read OFF. It also latches a hardware hold (CS-301) and tries again every loop.

**Watering meanwhile.** Stopped on that hardware (CS-301). Water may still be running through the switch that reads ON.

**Likely causes**

- A relay or valve is stuck on.
- The switch's device is offline, so its state cannot change.

**Suggested fixes**

- Check the switch the notification names, and the plumbing, now. Switch it off by hand if water is running.
- Then follow CS-301 to clear the hold.

<a id="cs-309"></a>

### CS-309: An interrupted shot's hardware may still be ON

*Warning · Notification*

**What it means.** A shot never finished, and a switch it opened can't be read (or Home Assistant gives no time for its last change), so the controller can't tell whether a person has switched it since. It leaves it alone on purpose: people run this hardware by hand too, for hand-watering and tank circulation.

**Watering meanwhile.** No new shot starts in this room until the interrupted one is settled. The controller checks again every loop.

**Likely causes**

- The switch's device is offline or reads 'unavailable'.
- Its integration reports no time for the switch's last change.

**Suggested fixes**

- Check the switch the notification names, and bring its device back online.
- Once it reads ON or OFF again, the controller settles the old shot by itself.

## Settings (CS-4xx)

<a id="cs-401"></a>

### CS-401: Setting outside the engine's range

*Warning · Notification*

**What it means.** A setting accepts a wider range than the engine will use, and it is set outside the engine's range. The notification names the setting, its value and the range.

**Watering meanwhile.** Carries on, using the nearest value inside the range.

**Likely causes**

- The setting was set to an extreme value, for example a field capacity of 95 % where the engine allows up to 90 %.

**Suggested fixes**

- Set it inside the range shown. The notification then stops.

<a id="cs-402"></a>

### CS-402: Settings missing, running on built-in values

*Critical · Notification*

**What it means.** Settings the controller reads by their exact entity ids don't exist in Home Assistant, so it uses its built-in values for them, the daily water limit and plant count included. The notification lists them.

**Watering meanwhile.** Carries on, on built-in values, which may not suit the room. Keep the engine off until they are back.

**Likely causes**

- The Crop Steering integration hasn't loaded, or has been removed.
- An entity id was changed in Settings.
- The room was created while Home Assistant was still running an older integration, so its settings were registered under other ids (see CS-605).

**Suggested fixes**

- Check the integration is loaded, and reload it.
- If Repairs shows CS-605, follow it.
- Change back any entity id you edited.

<a id="cs-403"></a>

### CS-403: Lights hours now come from the integration

*Information · Notification*

**What it means.** The controller app used to take the lights on and off hours from its own options. It now reads them from the integration, and the two disagree.

**Watering meanwhile.** Carries on, on the integration's hours.

**Likely causes**

- An installation from before the integration had its own lights hours.

**Suggested fixes**

- If the integration's hours are right, nothing to do.
- If not, set the integration's Lights on hour and Lights off hour.

<a id="cs-404"></a>

### CS-404: Automatic targets paused

*Warning · Notification*

**What it means.** Automatic setpoints adjust a zone's targets from how its morning ramp goes. This morning's ramp didn't look like water reaching the probe, so automatic adjustment is paused for the zone. The notification says what looked wrong.

**Watering meanwhile.** Carries on with the current targets. The next morning's ramp is judged again.

**Likely causes**

- A blocked dripper, a kinked line, or a valve not opening.
- The probe has moved, or isn't where the drippers wet the cube.
- Shots too small to lift the reading.

**Suggested fixes**

- Check the zone's drippers and lines, and do a catch test.
- Check the probe's position in the cube.

<a id="cs-405"></a>

### CS-405: Timezone mismatch, the day may be shifted

*Warning · Notification*

**What it means.** The controller app's clock is on a different time zone from Home Assistant. Lights on and off, dryback and the daily reset all go by the app's clock.

**Watering meanwhile.** Carries on, but the whole grow-day is shifted by the difference.

**Likely causes**

- An old controller app build without time zone data.
- Home Assistant's time zone was changed after the app started.

**Suggested fixes**

- Update, or rebuild, the controller app, then restart it.
- Check Home Assistant's time zone under Settings → System → General.

## Checks across zones (CS-5xx)

<a id="cs-501"></a>

### CS-501: Much less water than the other zones

*Information · Notification*

**What it means.** The zone has been given far less water today (under 40 %) than the middle of the room's other zones.

**Watering meanwhile.** Carries on as normal. This is advice only.

**Likely causes**

- Smaller plants, or plants that drink less.
- The probe sits in a wetter spot than the roots, so the zone seldom asks for water.
- A valve or dripper problem.

**Suggested fixes**

- Compare the plants, and check the probe's position.
- Do a catch test on this zone and a neighbour.

## Repairs cards (CS-6xx)

<a id="cs-601"></a>

### CS-601: Kill switch helper missing

*Critical · Repairs card*

**What it means.** The integration can't find the switch the controller uses to decide whether it may water this room.

**Watering meanwhile.** Nothing in the room is watered while the switch is missing.

**Likely causes**

- An installation from before the setup wizard, whose helper input_boolean.f2_control_enabled was deleted.
- On a room made by the wizard: the controller app was started before the integration was set up, and still reports its built-in name.

**Suggested fixes**

- On a room made by the wizard, do NOT create the helper. The room's own switch is Engine Enabled. Update the integration; the card clears once the controller has picked the room up.
- Only on a room really gated by input_boolean.f2_control_enabled: create it under Settings → Devices & services → Helpers → Toggle, and leave it OFF until you are ready to water.

<a id="cs-602"></a>

### CS-602: Engine not running

*Warning · Repairs card*

**What it means.** The controller app reports a heartbeat every minute, and the integration hasn't seen one for more than 10 minutes. The integration only creates the settings; the app is what waters.

**Watering meanwhile.** No automatic watering while the controller app isn't running.

**Likely causes**

- The controller app isn't installed, isn't started, or has stopped.
- The app can't reach Home Assistant.

**Suggested fixes**

- Start the controller app and read its log.
- If you only water by hand, ignore this.

<a id="cs-603"></a>

### CS-603: Zone with no moisture sensor

*Warning · Repairs card*

**What it means.** A zone has no moisture probe mapped, so it can't be steered.

**Watering meanwhile.** The zone can't be watered by moisture.

**Likely causes**

- The zone was set up without a probe, or its probe was cleared.

**Suggested fixes**

- Map a moisture probe to the zone in Crop Steering → Rooms & setup (or Configure).

<a id="cs-604"></a>

### CS-604: Zone sensor unavailable

*Warning · Repairs card*

**What it means.** The zone's combined moisture sensor reads unavailable, because the probe behind it isn't reporting. The controller raises CS-102 for the same zone.

**Watering meanwhile.** As for CS-102.

**Likely causes**

- The probe is offline, renamed, or removed.

**Suggested fixes**

- Check the probe under Settings → Developer tools → States, and the zone's mapping in Rooms & setup.

<a id="cs-605"></a>

### CS-605: Settings not where the controller looks for them

*Critical · Repairs card*

**What it means.** The controller finds each setting by its exact entity id, and the settings listed on the card are registered under other ids. It runs on its built-in values for them (CS-402).

**Watering meanwhile.** Carries on, on built-in values. Keep the engine off until this is fixed.

**Likely causes**

- An entity id was edited in Settings.
- The room was created while Home Assistant was still running an older integration after a HACS update, before a restart.

**Suggested fixes**

- One or two listed: change the id back under Settings → Devices & services → Entities → the entity → the cog.
- Nearly all listed: delete the Crop Steering entry, restart Home Assistant, and add it again.
- Nothing is renamed for you: an id you chose on purpose is yours to keep.

<a id="cs-606"></a>

### CS-606: Grow plan is holding irrigation

*Critical · Repairs card*

**What it means.** The room's grow plan is holding the steering of the zones it manages: the plan is in error, the controller cannot use it, or a zone the plan runs is not scheduled today. The card gives the reason.

**Watering meanwhile.** Those zones get only the overnight emergency, watchdog and minimum-daily shots, and a zone with a dead probe its timed schedule, until the hold clears. Routine steering waits.

**Likely causes**

- The plan went into error, for example because its zones no longer match the room.
- The controller reports that it cannot use the plan.
- A zone the plan runs is not scheduled today.

**Suggested fixes**

- Open Irrigation plan → Schedule in the Crop Steering sidebar and read the reason.
- If it stays in error, fix the cause, then disarm the plan and arm it again.

<a id="cs-607"></a>

### CS-607: Grow plan hasn't moved on to today

*Warning · Repairs card*

**What it means.** At lights-on the plan could not apply the new day. It keeps its last valid targets (a plan waiting to start stays armed) and tries again every minute.

**Watering meanwhile.** Carries on: the controller keeps steering on the last valid targets.

**Likely causes**

- The controller was not reporting at lights-on.
- A probe was stale at lights-on.
- The lights-on hour could not be read.

**Suggested fixes**

- Usually nothing: it clears by itself once the cause is fixed.
- If it stays, check the controller app is running and the probes are reporting.
