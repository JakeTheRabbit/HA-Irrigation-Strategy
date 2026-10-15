# Error codes

<!-- Generated from docs/error-codes.json by scripts/render_error_codes.py. Edit the JSON. -->

Every alert from the Crop Steering controller app, and every Crop Steering card under
**Settings → Repairs**, ends with a code such as **CS-101** (the controller's regular status
summary has none). Find the code below for what it
means, what happens to watering meanwhile, the likely causes and what to do. The same list is
in the Crop Steering sidebar under **Help & tools → Error codes**.

Most notifications are raised again, at most every 30 minutes, for as long as their cause lasts,
and after 5 minutes when their code changes. A few are said once: CS-301 once per fault
(dismissing it does not clear the hold), CS-403 once each time the controller app starts and
CS-405 at start-up. Most stay in Home Assistant until you dismiss them, even after their cause
has gone; the controller withdraws CS-201, CS-209, CS-308 and CS-309 itself, and switching a room's
*Room Active* off clears its notifications.
A room whose *Room Active* switch is off (nothing growing) raises no watering notifications; a
setup change (CS-201) and a hardware hold (CS-301, CS-308, CS-309) are still reported.

| Codes | About |
| --- | --- |
| CS-1xx | **Sensors**: A moisture or EC reading the controller cannot use. |
| CS-2xx | **Watering held**: Something is stopping shots in a room or a zone. |
| CS-3xx | **Pumps and valves**: A switch did not do what it was told, or a shot was cut. |
| CS-4xx | **Settings**: A setting is missing, out of range, or read from somewhere new. |
| CS-5xx | **Checks across zones**: Advice from comparing a room's zones. |
| CS-6xx | **Repairs cards**: Raised by the integration, under Settings → Repairs. |
| CS-7xx | **Jev**: Jev's judgements about a zone (advice, a probe it set aside), and how Jev itself is doing: its calls running low, a judge on the stricter gate (docs/JEV.md). |
| CS-8xx | **Dosing**: Batch-tank dosing: a dose or a batch that did not end as it should (docs/DOSING.md). |

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
| [CS-208](#cs-208) | A retired switch is off, so watering was switched off | Warning | Notification |
| [CS-209](#cs-209) | No watering for a while | Warning | Notification |
| [CS-301](#cs-301) | CRITICAL hardware fault, watering stopped | Critical | Notification |
| [CS-302](#cs-302) | Shot cancelled, the pump didn't switch on | Warning | Notification |
| [CS-303](#cs-303) | Shot cancelled, the main-line valve didn't switch on | Warning | Notification |
| [CS-304](#cs-304) | Shot cancelled, the zone valve didn't switch on | Warning | Notification |
| [CS-305](#cs-305) | Shot stopped early | Information | Notification |
| [CS-306](#cs-306) | Shot shortened to the safety limit | Warning | Notification |
| [CS-307](#cs-307) | Shot stopped early, something else closed the feed | Warning | Notification |
| [CS-308](#cs-308) | CRITICAL, an interrupted shot's hardware is still ON | Critical | Notification |
| [CS-309](#cs-309) | An interrupted shot's hardware may still be ON | Warning | Notification |
| [CS-310](#cs-310) | Moisture rising with no water: the table is not draining | Critical | Notification |
| [CS-311](#cs-311) | The sump pump has not run | Critical | Notification |
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
| [CS-605](#cs-605) | Settings not where the controller looks for them | Warning | Repairs card |
| [CS-606](#cs-606) | Grow strategy plan is holding irrigation | Critical | Repairs card |
| [CS-607](#cs-607) | Grow strategy plan has not moved on to today | Warning | Repairs card |
| [CS-608](#cs-608) | Stock tanks running low | Warning | Repairs card |
| [CS-701](#cs-701) | Water isn't reaching this zone | Warning | Notification |
| [CS-702](#cs-702) | This zone's water per plant is out of line with the others | Information | Notification |
| [CS-703](#cs-703) | Overnight low reading looks like a probe fault | Warning | Notification |
| [CS-704](#cs-704) | Jev set this zone's probe aside | Warning | Notification |
| [CS-705](#cs-705) | The zone is off the stage's arc | Information | Notification |
| [CS-706](#cs-706) | Jev has used most of today's calls | Warning | Notification |
| [CS-707](#cs-707) | Jev is on the stricter gate for this zone | Warning | Notification |
| [CS-801](#cs-801) | A dosing pump ran past its time and was switched off | Critical | Notification |
| [CS-802](#cs-802) | A dose could not be confirmed, or ended early | Warning | Notification |
| [CS-803](#cs-803) | A dose or batch was interrupted by a restart | Warning | Notification |
| [CS-804](#cs-804) | The batch tank could not be filled | Warning | Notification |
| [CS-805](#cs-805) | The mixing pump did not start | Warning | Notification |
| [CS-806](#cs-806) | Dosing was stopped, or needs a check | Warning | Notification |
| [CS-807](#cs-807) | A dose was not taken off its stock tank | Warning | Notification |

## Sensors (CS-1xx)

<a id="cs-101"></a>

### CS-101: Moisture reading hasn't changed

*Warning · Notification*

**What it means.** The zone's moisture reading has stayed exactly the same for more than 20 minutes. A working probe in a cube with a plant drinking from it moves all the time, so the controller cannot tell this one from a probe that has stopped updating or been pulled out, and does not steer by it.

**Watering meanwhile.** Carries on without the probe while the engine is on. If another zone in the room has a working probe, this zone gets the same shots as that zone; otherwise it gets one shot every 90 minutes (the app's blind_fallback_min option), within its daily water limit. Phase changes that go by moisture wait until the reading moves.

**Likely causes**

- No plant in the cube, or a plant too small to drink much yet: nothing takes water out, so the number never moves. Expected on a bench test or a new install.
- The probe has been pulled out of the cube, or is lying in a tray.
- The cube is soaked and the probe is pinned at its highest reading.
- The probe's own integration has stopped updating and keeps showing its last value.

**Suggested fixes**

- With no plant in, or a plant not yet drinking: nothing to fix. Watering goes back to normal by itself once the reading changes; the notification stays until you dismiss it.
- If the room is empty, switch its Room Active switch off: an empty room gets no watering and no notifications until it is switched back on.
- Check the probe is pushed fully into the cube.
- Open the sensor's history in Home Assistant. A flat line for hours while plants are drinking means the probe or its integration has stopped: reconnect or restart it.

<a id="cs-102"></a>

### CS-102: Moisture sensor not reporting

*Warning · Notification*

**What it means.** The zone's moisture sensor reads 'unavailable' or 'unknown', isn't a number, can't be found in Home Assistant at all, or carries a time in the future. The notification says which.

**Watering meanwhile.** For its first 15 minutes out the zone waits: a probe back within that is a blip (Home Assistant restarting, a sensor reconnecting), so nothing is watered or notified. Then it carries on without the probe while the engine is on: the same shots as a zone whose probe is working, or one shot every 90 minutes (the app's blind_fallback_min option) within the daily water limit if there is none. Phase changes that go by moisture wait for the probe.

**Likely causes**

- The probe is offline: no power, a flat battery, or out of Wi-Fi or Zigbee range.
- Home Assistant restarted and the probe's integration took more than 15 minutes to load.
- The probe was renamed or removed, so the sensor mapped to the zone no longer exists.
- Home Assistant's clock is ahead of the controller app's, so the reading looks as if it comes from the future (the notification says so).

**Suggested fixes**

- Find the sensor named in the notification under Settings → Developer tools → States and check what it reads.
- Check the probe's device is powered and online.
- In Crop Steering → Rooms & setup, check the zone's moisture sensor is the probe you expect.
- If the notification says the reading is stamped in the future, set the clocks of the Home Assistant host and the controller app right.

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

**What it means.** A changed setup was saved for the room (in Rooms & setup or Configure), or the controller is taking the room's setup on again after a restart. It only takes a setup on while every pump and valve it would drive is OFF, and, for a changed setup, the engine switch too. The notification lists the ones that are still on.

**Watering meanwhile.** Nothing in the room is watered until the controller has taken on the new setup.

**Likely causes**

- The setup was saved while the engine switch was on.
- A pump or valve was left on, or reads 'unavailable'.
- The controller app restarted while a pump was running (tank circulation, for example) or a switch still read 'unavailable'.

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

**What it means.** The room's maximum shot length must be a number of at least 5 seconds, and it isn't. A value set here is never replaced by a default, because a default could flood a room. Only when neither Maximum shot duration setting exists at all (an older install, or one whose ids have moved, CS-605) does the controller use 900 seconds, without this notification.

**Watering meanwhile.** No shot is started in the room.

**Likely causes**

- The setting reads 'unavailable', because the integration hasn't loaded.
- It has been set below 5 seconds.

**Suggested fixes**

- Check the Crop Steering integration is loaded (Settings → Devices & services).
- Set Maximum shot duration to at least 5 seconds.
- If Repairs shows CS-605, follow it: until the setting is back where the controller looks, shots are capped at 900 seconds.

<a id="cs-204"></a>

### CS-204: Shot size can't be worked out, not watering

*Critical · Notification*

**What it means.** The controller sizes every shot from the zone's pot size (litres per plant), plant count, drippers per plant and dripper flow. One of them is set to zero or less, or to something that isn't a number, so it can't tell how long to run. A setting that is missing or reads 'unavailable' doesn't cause this: the controller uses its built-in values instead (CS-402).

**Watering meanwhile.** The zone is not watered.

**Likely causes**

- Pot size, drippers per plant or dripper flow is set to 0 or less.
- The controller app's flow_lps or substrate_l option is 0 or less, and the zone's own setting is missing, so the option is used.

**Suggested fixes**

- Set the zone's pot size, plant count, drippers per plant and dripper flow in Crop Steering → Rooms & setup.
- Check the controller app's flow_lps and substrate_l options are above 0.

<a id="cs-205"></a>

### CS-205: Daily water limit reached

*Information · Notification*

**What it means.** The zone has had its daily water limit (max daily volume), counted from lights-on. A shot that would cross it gets only what is left; once too little is left for the shortest shot, routine shots stop.

**Watering meanwhile.** Routine top-ups and EC-correction shots stop until lights-on starts the next day. The morning ramp, the overnight emergency shot, the no-water-for-hours safety shot and high-EC flushes still run. The exception is a zone with no usable moisture reading (CS-101, CS-102, CS-103): every shot it gets is copied or timed and none is exempt, so it gets no more water at all until lights-on, the overnight emergency shot included. Its notification says so.

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

**Watering meanwhile.** The zone is held: no shot runs, the overnight emergency shot, the no-water-for-hours safety shot and the minimum daily volume included, and the urgent CS-207 is not raised for it. The hold lifts by itself once a flush could help (a weaker feed, or the cube drying back).

**Likely causes**

- The feed EC is as high as, or higher than, the root zone.
- The cube is at field capacity, so more water would only run off.
- The EC probe reads high (calibration, or a probe that has dried out).

**Suggested fixes**

- Check the feed EC in the tank (the sensor in the controller app's feed_ec_sensor option) and bring it down if it is high; a feed probe that reads high has the same effect.
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

<a id="cs-208"></a>

### CS-208: A retired switch is off, so watering was switched off

*Warning · Notification*

**What it means.** System Enabled and Auto Irrigation Enabled are retired: the room's Watering switch (its engine switch) is the one switch that stops watering. One of the two is still off, so the controller switched watering off in its place. It does so again, within a minute, while that switch stays off.

**Watering meanwhile.** Stopped in the room, as if watering had been switched off in Settings: no shot starts, and a shot that was running stops within a few seconds. The controller keeps reading the probes and following the phases.

**Likely causes**

- System Enabled or Auto Irrigation Enabled was switched off, by a person or an automation, before these switches were retired.
- An automation still switches one of them off to stop watering.

**Suggested fixes**

- Switch the named switch back on in Home Assistant (it is hidden: Settings → Entities, with hidden entities shown), then switch watering on in Crop Steering → Settings → Watering.
- Change an automation that switches System Enabled or Auto Irrigation Enabled off to switch the room's Watering switch (its engine switch) off instead.

<a id="cs-209"></a>

### CS-209: No watering for a while

*Warning · Notification*

**What it means.** A room that is on, with its lights on and at least one zone in P1 or P2, has had no shot in any of its zones for the number of hours set under Settings & help → Notifications (3 unless changed, 1 to 12). A zone in P0, the morning dry-back, or in P3 does not count: no water is expected then. The notification says why when the controller can tell: watering switched off, a hold with its reason, or no zone calling for water.

**Watering meanwhile.** Nothing changes: this only tells you. It is said again each time the same number of hours passes, and clears itself at the next shot in the room, or once the lights go off or no zone is in P1 or P2.

**Likely causes**

- Watering was switched off in the room (its engine switch) and not switched back on.
- A hold stops every shot: a batch being made, a hardware hold after a pump or valve fault (CS-301), a zone switched off or under manual override, the source-water gate, a pump or valve that reads neither on nor off. The notification names it.
- Nothing called for water: every zone in P1 or P2 read wetter than the point where it is watered, for example a probe out of its cube or stuck high, or a re-water point set too low for the plants.

**Suggested fixes**

- Read the reason in the notification. Clear the hold it names, or switch watering back on in Crop Steering → Settings → Watering.
- If nothing called for water, compare each zone's moisture reading with its re-water point on the zone's page, and check the probes are in their cubes.
- Change after how many hours this is said, or who gets it, under Crop Steering → Settings & help → Notifications.

## Pumps and valves (CS-3xx)

<a id="cs-301"></a>

### CS-301: CRITICAL hardware fault, watering stopped

*Critical · Notification*

**What it means.** A pump or valve did not confirm it had switched OFF: after a shot, after a shot was cancelled before its water started (CS-302, CS-303, CS-304), after a shot something else cut short (CS-307), or while an interrupted shot was being closed (CS-308). It may still be running. The controller latches a hold on that hardware, remembered across restarts.

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
- The notification is said once per fault, not every 30 minutes, and dismissing it does not clear the hold: check the hardware even if the card is gone.

<a id="cs-302"></a>

### CS-302: Shot cancelled, the pump didn't switch on

*Warning · Notification*

**What it means.** Home Assistant returned an error when the controller switched the pump on.

**Watering meanwhile.** That shot was cancelled and not counted. The controller switches off the pump, main line and valve and checks they read OFF: if it can't confirm that (Home Assistant unreachable, or a switch offline), it latches a hardware hold (CS-301) and nothing on that hardware is watered until the hold is cleared. Otherwise the next shot is tried as normal.

**Likely causes**

- Home Assistant could not be reached (restarting, or a network fault), or returned an error for the command.
- A switch that reads 'unavailable' doesn't raise this: no shot starts while any switch on its feed path reads neither on nor off. The zone's status names the offline switch, and the zone is watered once it reads again.

**Suggested fixes**

- Switch the pump on and off by hand in Home Assistant to check it responds.
- Check the pump mapped in Crop Steering → Rooms & setup.
- If CS-301 was raised too, follow it.

<a id="cs-303"></a>

### CS-303: Shot cancelled, the main-line valve didn't switch on

*Warning · Notification*

**What it means.** Home Assistant returned an error when the controller switched the main-line valve on. The controller then switched off what the shot may have opened.

**Watering meanwhile.** That shot was cancelled and not counted. The controller switches off the pump, main line and valve and checks they read OFF: if it can't confirm that (Home Assistant unreachable, or a switch offline), it latches a hardware hold (CS-301) and nothing on that hardware is watered until the hold is cleared. Otherwise the next shot is tried as normal.

**Likely causes**

- Home Assistant could not be reached (restarting, or a network fault), or returned an error for the command.
- A switch that reads 'unavailable' doesn't raise this: no shot starts while any switch on its feed path reads neither on nor off. The zone's status names the offline switch, and the zone is watered once it reads again.

**Suggested fixes**

- Switch the valve on and off by hand in Home Assistant to check it responds.
- Check the main-line valve mapped in Crop Steering → Rooms & setup.
- If CS-301 was raised too, follow it.

<a id="cs-304"></a>

### CS-304: Shot cancelled, the zone valve didn't switch on

*Warning · Notification*

**What it means.** Home Assistant returned an error when the controller switched the zone's valve on. The controller then switched off what the shot may have opened.

**Watering meanwhile.** That shot was cancelled and not counted. The controller switches off the pump, main line and valve and checks they read OFF: if it can't confirm that (Home Assistant unreachable, or a switch offline), it latches a hardware hold (CS-301) and nothing on that hardware is watered until the hold is cleared. Otherwise the next shot is tried as normal.

**Likely causes**

- Home Assistant could not be reached (restarting, or a network fault), or returned an error for the command.
- A switch that reads 'unavailable' doesn't raise this: no shot starts while any switch on its feed path reads neither on nor off. The zone's status names the offline switch, and the zone is watered once it reads again.

**Suggested fixes**

- Switch the valve on and off by hand in Home Assistant to check it responds.
- Check the zone's valve mapped in Crop Steering → Rooms & setup.
- If CS-301 was raised too, follow it.

<a id="cs-305"></a>

### CS-305: Shot stopped early

*Information · Notification*

**What it means.** A shot was stopped part-way because the engine switch was turned off, Room Active or the zone itself was switched off, or manual override was turned on while it ran. The notification names the switch. The valve and anything upstream were switched off; if they don't all read OFF, CS-301 is raised as well.

**Watering meanwhile.** The water delivered before the stop is counted. The next shot is decided as normal.

**Likely causes**

- Someone turned the engine switch, Room Active or the zone off, or manual override on, during a shot.
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

**What it means.** A shot never finished cleanly: the controller stopped, crashed or lost Home Assistant part-way through it, or a switch did not confirm OFF at the end of it. The controller then switched off what that shot had opened, and at least one of those switches still does not read OFF. It also latches a hardware hold (CS-301) and tries again every loop.

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

**What it means.** A shot never finished, and a switch it opened can't be read, or Home Assistant gives no time for its last change or no history since the shot began, so the controller can't tell whether a person has switched it since. It leaves it alone on purpose: people run this hardware by hand too, for hand-watering and tank circulation. Once it can tell, the controller switches off what it can prove this shot opened, including a switch whose change time moved only because Home Assistant restarted or the switch reconnected (its history shows it ON since the shot opened it). A switch a person turned off and on again since, or that was on before the shot, is left on, and the notification is withdrawn.

**Watering meanwhile.** No new shot starts in this room until the interrupted one is settled. The controller checks again every loop.

**Likely causes**

- The switch's device is offline or reads 'unavailable'.
- Its integration reports no time for the switch's last change.
- Home Assistant keeps no history for the switch: it is excluded from the recorder, or Home Assistant has only just started.

**Suggested fixes**

- Check the switch the notification names, and the plumbing, now. Switch it off by hand if water is running.
- Bring its device back online.
- If the switch is excluded from Home Assistant's recorder, include it: its history is how the controller tells a restart from a person.
- Don't wait for the notification to go away: once the switch and its history read again, the controller closes what it can prove this shot opened and leaves anything else ON.

<a id="cs-310"></a>

### CS-310: Moisture rising with no water: the table is not draining

*Critical · Notification*

**What it means.** A zone's moisture reading rose by 3 points or more within an hour while no water went in: its valve was not open, by the controller or by hand, during the rise or in the 45 minutes before it. Water is reaching the slabs from below: the table or its drain is blocked, or the sump is not pumping, and the slabs are sitting in runoff. The notification says how far the reading rose, over how long, and when the zone last had water.

**Watering meanwhile.** The zone's daily minimum and its EC flushes are held while this lasts, so the controller never pours water into a flooded table; a zone reading this wet gets no routine shots anyway. It is said again every 30 minutes while the reading keeps rising, and clears itself once the reading has stopped rising for an hour.

**Likely causes**

- A table's drain or drain line is blocked: substrate, roots or debris in the outlet.
- The sump pump is not pumping (failed, without power, its float stuck), so the sump fills and backs up into the tables.
- A shared gutter or drain is backed up and runoff from other tables flows into this one.
- Less likely: the probe was moved into a wetter spot, or water was put on by hand without the zone's valve (a hose).

**Suggested fixes**

- Go to the room now: look for standing water on the table, and check its drain outlets, the sump and the sump pump.
- Clear the blockage and make sure the sump pumps out. The reading starts falling once the table drains.
- Don't water the zone by hand until the table has drained.
- If nothing is backed up, check the probe hasn't been moved or knocked into a wetter spot.

<a id="cs-311"></a>

### CS-311: The sump pump has not run

*Critical · Notification*

**What it means.** The power reading of the sump pump the room's tables drain to (the controller app's sump_power_sensor option) has shown no run for the hours set in sump_silent_hours (3 unless changed) while the room is on. A sump pump that normally runs every hour or two has stopped: runoff has nowhere to go, the sump fills and backs up into the tables, and the slabs end up sitting in it. The notification names the sensor.

**Watering meanwhile.** Nothing changes: this only tells you. It is said again every 30 minutes while the pump stays still, and clears itself at its next run. Once a zone's moisture starts rising with no water, CS-310 follows and holds that zone's daily minimum and EC flushes.

**Likely causes**

- The sump pump has failed, or its float is stuck.
- The pump has no power: its plug is switched off or tripped.
- Nothing reaches the sump: the tables' drains or the line to the sump are blocked.
- The power plug is offline, so no run can be seen (its reading is unavailable).

**Suggested fixes**

- Check the sump now: its water level, the pump, its float and its power.
- Clear what stops the water reaching or leaving the sump, and watch the pump run.
- If the plug is offline, bring it back: until then the pump's runs can't be seen.
- Set sump_silent_hours longer only if the pump really runs less often than that.

## Settings (CS-4xx)

<a id="cs-401"></a>

### CS-401: Setting outside the engine's range

*Warning · Notification*

**What it means.** A setting accepts a wider range than the engine will use, and it is set outside the engine's range. The notification names the setting, its value and the range; a check that compares two settings (a minimum above its maximum) names both.

**Watering meanwhile.** Carries on, using the nearest value inside the range.

**Likely causes**

- The setting was set to an extreme value, for example a field capacity of 95 % where the engine allows up to 90 %.

**Suggested fixes**

- Set it inside the range shown. The notification then stops.
- Where two settings are compared, change either one. The minimum daily volume is worked out from mL per plant and plant count.

<a id="cs-402"></a>

### CS-402: Settings missing, running on built-in values

*Critical · Notification*

**What it means.** Settings the controller reads by their exact entity ids can't be read in Home Assistant (missing, or not a number for three loops running), so it uses its built-in values for them. The notification lists them, and says when the daily water limit or plant count is among them.

**Watering meanwhile.** Carries on, on built-in values, which may not suit the room. If the daily water limit or plant count is among them, keep the engine off until they are back.

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

**What it means.** The controller app used to take the lights on and off hours from its own options. It now reads them from the integration, and the two disagree. The app's option is still used when the integration's hours can't be read and haven't been since the controller app started; a loop that can't read them keeps the hours read before.

**Watering meanwhile.** Carries on, on the integration's hours.

**Likely causes**

- An installation from before the integration had its own lights hours.

**Suggested fixes**

- If the integration's hours are right, set the controller app's lights_on_hour and lights_off_hour options to the same hours, so that case can't move lights-on or lights-off.
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

- On a room made by the wizard, do NOT create the helper. The room's own switch is Engine Enabled. The card came from a controller app started before setup; integration 2.19.2 and newer don't raise it for such a room. Update the integration; the card clears once the controller has picked the room up.
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

**What it means.** A zone has no moisture probe mapped, so it can't be steered by moisture.

**Watering meanwhile.** As for CS-102: while the engine is on the zone is still watered, with the same shots as a zone whose probe is working, or one shot every 90 minutes within its daily water limit if there is none. Don't hand-water it on the assumption that the controller won't.

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

*Warning · Repairs card*

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

### CS-606: Grow strategy plan is holding irrigation

*Critical · Repairs card*

**What it means.** The room's grow plan is holding the steering of the zones it manages: the plan is in error, the controller cannot use it, or a zone the plan runs is not scheduled today. The card gives the reason.

**Watering meanwhile.** Those zones get only the overnight emergency, watchdog and minimum-daily shots, and a zone with a dead probe its timed schedule, until the hold clears. Routine steering waits.

**Likely causes**

- The plan went into error, for example because its zones no longer match the room.
- The controller reports that it cannot use the plan.
- A zone the plan runs is not scheduled today.

**Suggested fixes**

- Open Plan › Schedule in the Crop Steering sidebar and read the reason.
- If it stays in error, fix the cause, then disarm the plan and arm it again.

<a id="cs-607"></a>

### CS-607: Grow strategy plan has not moved on to today

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

<a id="cs-608"></a>

### CS-608: Stock tanks running low

*Warning · Repairs card*

**What it means.** One or more of the room's stock tanks is at or below its low mark. Each batch tank the room makes takes its dose from every stock tank.

**Watering meanwhile.** Carries on. Batches made from an empty stock tank will be short of that nutrient.

**Likely causes**

- Batches have drawn the stock down to its low mark.
- A tank was refilled but Refilled was not pressed, so its level is still the old one.

**Suggested fixes**

- Refill the tank, then press Refilled on Crop Steering → Stock tanks.
- Or set the level you read off the tank. The card clears itself once every tank is above its low mark.

## Jev (CS-7xx)

<a id="cs-701"></a>

### CS-701: Water isn't reaching this zone

*Warning · Notification*

**What it means.** Jev's Shot judge found, for two shots in a row, no sign that the water reached this zone: moisture did not rise, while the controller counted the litres.

**Watering meanwhile.** Carries on as normal. The litres counted may not be what arrived.

**Likely causes**

- A closed hand valve, a kinked or blocked line, or blocked drippers.
- A tank or dosing hold that closed the feed path during the shot.
- The zone's valve does not open although it reads on.

**Suggested fixes**

- Check the zone's valve, line and drippers during the next shot.
- Do a catch test on one dripper.

<a id="cs-702"></a>

### CS-702: This zone's water per plant is out of line with the others

*Information · Notification*

**What it means.** The zone's water per plant today is under 70 % or over 140 % of the room's other zones, and Jev's Zones judge names the likely reason in the message.

**Watering meanwhile.** Carries on as normal. This is advice only.

**Likely causes**

- Plants that drink less or more.
- The probe sits in a wetter or drier spot than the roots.
- A valve, dripper or line problem.
- Shots that do not land.

**Suggested fixes**

- Compare the zone's settings and plants with its siblings'.
- Check the probe's position, and do a catch test on this zone and a neighbour.

<a id="cs-703"></a>

### CS-703: Overnight low reading looks like a probe fault

*Warning · Notification*

**What it means.** The zone's moisture is falling toward the P3 emergency floor overnight, and Jev's Night judge reads it as a probe fault rather than drying.

**Watering meanwhile.** Carries on: the P3 rescue shot still fires as normal.

**Likely causes**

- A probe that stepped or stopped moving.
- A probe knocked out of place.

**Suggested fixes**

- Check the probe in the morning, before the ramp starts.

<a id="cs-704"></a>

### CS-704: Jev set this zone's probe aside

*Warning · Notification*

**What it means.** Jev judged twice in a row, and the controller's own check confirmed, that the zone's moisture probe is not tracking the substrate (stuck, channeling, out of the block, on the wrong zone or drifting).

**Watering meanwhile.** Carries on without the probe, as for a dead probe: the zone copies a healthy sibling's shots, or waters on its timer, within its daily limit. The probe counts again as soon as Jev judges it tracks.

**Likely causes**

- A probe pulled part-way out of the block, or sitting in a channel.
- A probe mapped to the wrong zone.
- A probe that has stopped measuring but still reports.

**Suggested fixes**

- Check the probe's placement and wiring, and which zone it is mapped to in Rooms & setup.

<a id="cs-705"></a>

### CS-705: The zone is off the stage's arc

*Information · Notification*

**What it means.** Jev's daily Stage judge compared the zone with the owner's stage arc for today's day of flower (steering, dryback, pore EC) and found it off, naming what and what the doctrine says.

**Watering meanwhile.** Carries on as normal. This is advice only: nothing is changed.

**Likely causes**

- The zone's steering mode or settings are for another stage.
- The overnight dryback or the pore EC has drifted outside the stage's band.
- The stage's move-on signs have appeared.

**Suggested fixes**

- Compare the zone's settings with the stage (docs/JEV.md, the owner's stage arc), and change them if the stage has moved on.
- Check jev_flower_start points at the right flip date.

<a id="cs-706"></a>

### CS-706: Jev has used most of today's calls

*Warning · Notification*

**What it means.** Jev has been asked the warning share (80 % by default) of its daily call budget, across every room. Once the budget is spent, Jev is not asked again until midnight.

**Watering meanwhile.** Carries on as normal. Once the budget is spent, the engine's own rules decide every zone until midnight.

**Likely causes**

- More zones or judges than the budget was set for.
- Many second looks: Jev was often unsure today.
- The budget option is still at an older, lower value.

**Suggested fixes**

- Raise jev_daily_calls in the app's options, then restart the app.
- Check reasks_today and errors_today on the Jev sensor: many of either show what used the calls.

<a id="cs-707"></a>

### CS-707: Jev is on the stricter gate for this zone

*Warning · Notification*

**What it means.** Several of one Jev judge's calls in a row for this zone (three by default) did not work out when they were checked. Until two in a row do, that judge acts only when both phrasings agree at 0.8 or more (the default) and a second look gives the same answer.

**Watering meanwhile.** Carries on. Jev keeps judging the zone; whenever it is not sure enough, the engine's own rules act, as they do without Jev.

**Likely causes**

- A probe or sensor misleading the judge.
- Conditions the judge has not met before, such as a new stage or a changed room.
- A setting that works against the judge's calls.

**Suggested fixes**

- Read the zone's Jev log on the dashboard: the calls and how each was checked.
- Check the zone's probe and settings.

## Dosing (CS-8xx)

<a id="cs-801"></a>

### CS-801: A dosing pump ran past its time and was switched off

*Critical · Notification*

**What it means.** A dose was still running at its deadline: 1.25 times the time its volume takes at the pump's calibrated flow, plus 20 seconds, and never more than 21 minutes. The controller switched the pump's power off, read it back (sending the off again once if it did not read off) and ended the dose as "ran past its time". The tank may hold more nutrient than was asked for. When the power still does not read off, the off is sent again every 2 seconds, the room's watering is held until it reads off, and this notification comes again every 30 minutes.

**Watering meanwhile.** A single dose holds no watering, so watering carries on, unless the pump's power does not read off: then the room is held until it does. In a batch, the batch stops too (CS-806), and the rooms it held water again once its hardware reads off.

**Likely causes**

- The pump's firmware did not stop its motor at the volume it was given.
- The pump's flow calibration (mL/s) is well above what it really pumps, so the dose was expected sooner.
- The pump's dosing sensor stayed on dosing although the motor had stopped.

**Suggested fixes**

- Check the batch tank's EC before it is used: it may hold more than was asked for.
- Check the pump's firmware and dosing sensor, and recalibrate its flow.
- If the power switch feeds the pump's board, switch it back on once it is fixed: the controller never switches a dosing pump on.
- If its power does not read off, switch the pump off on the device or at its socket: the room waters again once it reads off.

<a id="cs-802"></a>

### CS-802: A dose could not be confirmed, or ended early

*Warning · Notification*

**What it means.** The controller set the pump's volume and pressed its start, but could not confirm the dose: the pump's dosing sensor never read dosing within the dose's expected time plus 15 seconds (a dose too short to be caught between two reads counts only when Home Assistant's recorder shows it dosing), or it read unavailable or unknown during the dose (a pump that restarts mid-dose drops its dose). Whether the pump dosed, and how much, is not known, and nothing is taken off its stock tank. Or the dose ended in less than half its expected time ("ended early"): what ran, the seconds it ran times its flow, is taken off its stock tank.

**Watering meanwhile.** A single dose holds no watering, so watering carries on. In a batch, the batch stops too (CS-806), and the rooms it held water again once its hardware reads off.

**Likely causes**

- The pump is offline, or its start button or script did nothing.
- The dosing sensor shows dosing in a way the setup does not recognise: a text sensor whose dosing state does not start with the dosing prefix, for instance.
- The pump's firmware refused the volume it was given.
- The pump restarted or dropped off the network during the dose.
- The pump's firmware ended the dose early, or its flow calibration is well below what it pumps.

**Suggested fixes**

- Check the pump is online and what its dosing sensor shows during a dose, and set the dosing prefix to match.
- Check the batch tank's EC before dosing again: the dose may or may not have gone in.

<a id="cs-803"></a>

### CS-803: A dose or batch was interrupted by a restart

*Warning · Notification*

**What it means.** The controller app stopped (an update, a restart, a crash or a power cut) while a dose or a batch was running, or its record of what was running (dosing_state.json) could not be read at start. At its next start it holds the watering of the rooms the dose or batch held, and switches off every dosing pump's power, the fill valve, the mix pump and the mix valves of that room (with a record it could not read: of every room with dosing set up), again every 2 seconds until every one reads off; a switch that reads unavailable or unknown is not off. Only then is the batch's hold turned off and the rooms released. The notification names what does not read off and comes again every 30 minutes until it does. The controller never resumes a dose or a batch; the volume number a dose changed is put back.

**Watering meanwhile.** The rooms the dose or batch held stay held until its dosing hardware reads off; then watering carries on.

**Likely causes**

- The controller app was updated, restarted or stopped during a dose or a batch.
- Home Assistant or the host restarted.
- dosing_state.json could not be read at start (it is kept as dosing_state.json.bad).

**Suggested fixes**

- Check the batch tank: what was dosed before the stop is in it, and the dosing history lists it. Dose the rest by hand or make a fresh batch.
- Update or restart the controller app between batches.
- If a switch stays unavailable, bring its device back or switch it off at its socket: the rooms water again once it reads off.

<a id="cs-804"></a>

### CS-804: The batch tank could not be filled

*Warning · Notification*

**What it means.** A batch could not fill the tank: the fill valve did not read on within 10 seconds of being opened, the tank's full sensor read nothing usable (as the fill began, or for 15 seconds while it filled), or it did not read full within the fill timeout. The controller closed the fill valve and read it back, and the batch stops (CS-806). A batch is refused before anything moves while the full sensor can't be read.

**Watering meanwhile.** The rooms the batch held water again; the fill valve was closed.

**Likely causes**

- The water supply is off or slow, or the fill valve did not open.
- The full sensor is stuck or offline, or reports a state other than the one set as full.
- The fill timeout is shorter than a fill takes.
- The fill valve is offline or its relay did not switch.
- The full sensor went offline.

**Suggested fixes**

- Check the water supply, the fill valve, and what the full sensor reads when the tank is full.
- Raise the fill timeout in the dosing setup if a fill takes longer.

<a id="cs-805"></a>

### CS-805: The mixing pump did not start

*Warning · Notification*

**What it means.** A batch opened the mix valves and switched the mix pump on, but the pump did not read on, or its power sensor did not read the minimum power within 20 seconds. The batch stops (CS-806).

**Watering meanwhile.** The rooms the batch held water again, once its hardware reads off.

**Likely causes**

- The mix pump did not start, or its plug did not switch.
- The power sensor is offline or slow to report.
- The minimum power is set above what the pump draws.

**Suggested fixes**

- Check the mix pump, its plug, and what the power sensor reads while it runs.
- Set the minimum power below what the pump draws, or to 0 to skip the check.

<a id="cs-806"></a>

### CS-806: Dosing was stopped, or needs a check

*Warning · Notification*

**What it means.** A batch ended before it finished: someone stopped it, a step failed (CS-801, CS-802, CS-804 and CS-805 come first and say which), its hold did not read on, a shot in a room it holds was still running after 10 minutes, a switch did not read off, or it ran past its watchdog (the wait for a shot, the fill timeout, premix, postmix and every dose's deadline, plus 10 minutes). The notification names the step, the reason and what was dosed. Every dosing pump's power, the fill valve, the mix pump and the mix valves were switched off; the hold is released only once they read off, and the tank's fill time is not stamped. The same code says when a single dose was stopped but its pump's power does not read off, a dose was stopped by an error in the controller, the volume number of a pump could not be put back after a dose, a finished batch could not stamp its fill time or release its hold, dosing in a room keeps failing, or the dosing thread stopped and was started again or stopped answering. Whatever does not read off holds its rooms, and the notification comes again every 30 minutes, until it does.

**Watering meanwhile.** The rooms a stopped batch held water again once its hardware and its hold read off; until then they stay held. A dose whose pump does not read off holds its room the same way. Otherwise watering carries on.

**Likely causes**

- Someone stopped the batch.
- A fill, mix or dose that failed.
- A switch of the batch, or of a room it holds, that did not read off.
- A pump's volume number that did not take the value it was put back to.
- The filled-at or hold entity did not take its command.
- An error in the controller (its log names it).

**Suggested fixes**

- Check the batch tank before making another batch: the notification lists what was dosed before it stopped.
- Fix the cause it names, then make the batch again.
- When it says a volume number could not be put back, set it back by hand before the next batch.
- When it names an error in the controller, check the controller app's log.

<a id="cs-807"></a>

### CS-807: A dose was not taken off its stock tank

*Warning · Notification*

**What it means.** A dose drew from the stock tank linked to its pump, but Home Assistant did not take the draw: the tank is not one of the room's stock tanks any more, Home Assistant refused it (an HTTP 4xx answer), or it had not taken it 24 hours after the dose. The draw was dropped and is kept in the room's dosing history; the tank's level is now higher than what is in it.

**Watering meanwhile.** Carries on as normal: only the stock level is wrong.

**Likely causes**

- The stock tank was removed after the pump was linked to it.
- Crop Steering's stock service refused the call, or was missing at that moment (an old integration, or a reload).
- Home Assistant could not be reached for a day.

**Suggested fixes**

- Set the tank's level in Stock tanks (Set level) to what is in it.
- Check the pump's stock tank in the dosing setup.
