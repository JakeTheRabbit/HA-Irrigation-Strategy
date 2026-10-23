# Error codes

<!-- Generated from docs/error-codes.json by scripts/render_error_codes.py. Edit the JSON. -->

Each alert from the Crop Steering controller app, and each Crop Steering card in
**Settings → Repairs**, ends with a code, for example **CS-101**. The regular status summary of
the controller has no code. Find the code below. It tells you what the alert means, what occurs
to the water, the probable causes and what to do. The same list is in the Crop Steering sidebar
under **Settings → Help → Error codes**.

A critical alert, or a warning about a zone that gets no water, comes again each 30 min while its
cause continues. Other warnings come again after 15 min, then less frequently. An information
alert comes once. When the code of an alert changes, the new alert comes after 5 min. CS-403 comes
once each time the controller app starts, and CS-405 comes at the start. A dismissed CS-301 alert
does not clear the hardware hold.

Most alerts stay in Home Assistant until you dismiss them, also after their cause stops. The
controller removes CS-201, CS-209, CS-210, CS-212, CS-308 and CS-309 itself. When you set *Room Active* of a room
to off, the controller removes the alerts of the room.
When *Room Active* is off (no plants in the room), the room gives no alerts about water. The
controller still reports a setup change (CS-201) and a hardware hold (CS-301, CS-308, CS-309).

| Codes | About |
| --- | --- |
| CS-1xx | **Probes**: A VWC or EC reading that the controller cannot use. |
| CS-2xx | **Shots held**: Something stops the shots of a room or a zone. |
| CS-3xx | **Pumps and valves**: A switch did not obey its command, or a shot stopped early. |
| CS-4xx | **Settings**: A setting is missing or out of range, or the controller reads it from a new source. |
| CS-5xx | **Zone comparisons**: Advice from a comparison of the zones of a room, and a probe that the controller sets aside because of its unit. |
| CS-6xx | **Repairs cards**: The integration makes these alerts in Settings → Repairs. |
| CS-7xx | **AI assistant**: Decisions of the AI assistant about a zone (advice, or a probe that it sets aside). Also the status of the AI assistant (docs/AI_ASSISTANT.md). For example, its calls or its AI budget are almost used or used, or its key is refused. Other examples are a retired route and a judge on the stricter gate. |
| CS-8xx | **Dosing**: Batch tank dosing: a dose or a batch that did not end correctly (docs/DOSING.md). Also pH auto-correct, and the light dimmed on dry substrate. |
| CS-9xx | **Reservoir and feed**: The tank that a room gets water from (docs/USER_GUIDE.md, "Reservoir minimum"). It is at its minimum, its level cannot be read, or it needs a refill before the next shots. Or a fill stopped above the full mark. Also a batch tank that needs a refill (docs/DOSING.md). |

## All codes

| Code | What it says | Severity | Shown as |
| --- | --- | --- | --- |
| [CS-101](#cs-101) | Flat moisture reading | Warning | Notification |
| [CS-102](#cs-102) | Probe with no reading | Warning | Notification |
| [CS-103](#cs-103) | Moisture reading out of range | Warning | Notification |
| [CS-104](#cs-104) | EC reading not available | Warning | Notification |
| [CS-201](#cs-201) | Setup change on hold | Critical | Notification |
| [CS-202](#cs-202) | Pump or main-line mismatch | Critical | Notification |
| [CS-203](#cs-203) | Invalid maximum shot length | Critical | Notification |
| [CS-204](#cs-204) | Invalid shot size inputs | Critical | Notification |
| [CS-205](#cs-205) | Daily water limit reached | Information | Notification |
| [CS-206](#cs-206) | EC too high, zone held | Warning | Notification |
| [CS-207](#cs-207) | Dry zone, all shots blocked | Critical | Notification |
| [CS-208](#cs-208) | Retired switch is off | Warning | Notification |
| [CS-209](#cs-209) | No shots for some hours | Warning | Notification |
| [CS-210](#cs-210) | Hold entity missing | Warning | Notification |
| [CS-211](#cs-211) | Shots held for too long | Critical | Notification |
| [CS-212](#cs-212) | Controller error in room | Critical | Notification |
| [CS-301](#cs-301) | Hardware fault latch | Critical | Notification |
| [CS-302](#cs-302) | Pump command error | Warning | Notification |
| [CS-303](#cs-303) | Main-line valve command error | Warning | Notification |
| [CS-304](#cs-304) | Zone valve command error | Warning | Notification |
| [CS-305](#cs-305) | Early shot stop | Information | Notification |
| [CS-306](#cs-306) | Shot cut to maximum length | Warning | Notification |
| [CS-307](#cs-307) | Shot stopped by external change | Warning | Notification |
| [CS-308](#cs-308) | Interrupted shot, hardware on | Critical | Notification |
| [CS-309](#cs-309) | Interrupted shot, state unknown | Warning | Notification |
| [CS-310](#cs-310) | Table drain blocked | Critical | Notification |
| [CS-311](#cs-311) | No sump pump run | Critical | Notification |
| [CS-312](#cs-312) | Repeated maximum-length shots | Warning | Repairs card |
| [CS-313](#cs-313) | Device type not supported | Warning | Notification |
| [CS-314](#cs-314) | Sump water balance does not close | Warning | Notification |
| [CS-315](#cs-315) | Rescue shots not absorbed | Critical | Notification |
| [CS-316](#cs-316) | Waste valve not closed | Warning | Notification |
| [CS-317](#cs-317) | Pump runs with every valve shut | Warning | Notification |
| [CS-401](#cs-401) | Setting outside controller range | Warning | Notification |
| [CS-402](#cs-402) | Missing settings | Critical | Notification |
| [CS-403](#cs-403) | Lights hours from the integration | Information | Notification |
| [CS-404](#cs-404) | Automatic setpoints paused | Warning | Notification |
| [CS-405](#cs-405) | Time zone mismatch | Warning | Notification |
| [CS-501](#cs-501) | Low water compared to room | Information | Notification |
| [CS-502](#cs-502) | Too few probes in agreement | Warning | Notification |
| [CS-503](#cs-503) | Probe unit not accepted | Warning | Notification |
| [CS-504](#cs-504) | Zone EC from bulk EC | Warning | Notification |
| [CS-505](#cs-505) | Primary probe offline | Warning | Notification |
| [CS-601](#cs-601) | Kill switch helper missing | Critical | Repairs card |
| [CS-602](#cs-602) | No controller heartbeat | Warning | Repairs card |
| [CS-603](#cs-603) | Zone without a probe | Warning | Repairs card |
| [CS-604](#cs-604) | Combined moisture entity unavailable | Warning | Repairs card |
| [CS-605](#cs-605) | Settings at unexpected entity IDs | Warning | Repairs card |
| [CS-606](#cs-606) | Grow plan holds steering | Critical | Repairs card |
| [CS-607](#cs-607) | Grow plan day not applied | Warning | Repairs card |
| [CS-608](#cs-608) | Stock tanks low | Warning | Repairs card |
| [CS-609](#cs-609) | Second controller for room | Warning | Notification |
| [CS-610](#cs-610) | Engine Enabled not kill switch | Warning | Repairs card |
| [CS-611](#cs-611) | Settings above zone limit | Warning | Repairs card |
| [CS-613](#cs-613) | Deprecated feature in use | Warning | Repairs card |
| [CS-701](#cs-701) | No water at the zone | Warning | Notification |
| [CS-702](#cs-702) | Unusual water for each plant | Information | Notification |
| [CS-703](#cs-703) | Overnight probe fault suspected | Warning | Notification |
| [CS-704](#cs-704) | Probe set aside by AI | Warning | Notification |
| [CS-705](#cs-705) | Zone outside stage arc | Information | Notification |
| [CS-706](#cs-706) | AI call budget almost used | Warning | Notification |
| [CS-707](#cs-707) | Stricter gate for a judge | Warning | Notification |
| [CS-708](#cs-708) | AI budget used | Warning | Notification |
| [CS-709](#cs-709) | AI assistant not available | Warning | Notification |
| [CS-710](#cs-710) | Possible water bypass | Warning | Notification |
| [CS-711](#cs-711) | AI feed change proposal | Information | Notification |
| [CS-712](#cs-712) | First AI route removed | Information | Notification |
| [CS-713](#cs-713) | Room differs from grow plan | Warning | Notification |
| [CS-801](#cs-801) | Dosing pump overrun | Critical | Notification |
| [CS-802](#cs-802) | Dose not confirmed | Warning | Notification |
| [CS-803](#cs-803) | Dose interrupted by restart | Warning | Notification |
| [CS-804](#cs-804) | Batch tank fill failure | Warning | Notification |
| [CS-805](#cs-805) | Mix pump start failure | Warning | Notification |
| [CS-806](#cs-806) | Stopped batch or dose | Warning | Notification |
| [CS-807](#cs-807) | Stock draw not recorded | Warning | Notification |
| [CS-808](#cs-808) | Batch mix outside band | Warning | Notification |
| [CS-809](#cs-809) | Tank pH not corrected | Critical | Notification |
| [CS-810](#cs-810) | Lights dimmed on dry substrate | Warning | Notification |
| [CS-811](#cs-811) | Light dimmed too long | Critical | Notification |
| [CS-901](#cs-901) | Tank at minimum level | Critical | Notification |
| [CS-902](#cs-902) | Tank level not readable | Critical | Notification |
| [CS-903](#cs-903) | Refill needed before next shots | Warning | Notification |
| [CS-904](#cs-904) | Tank above full mark | Warning | Notification |
| [CS-905](#cs-905) | Estimated tank level low | Warning | Notification |
| [CS-906](#cs-906) | Batch tank low | Information | Notification |
| [CS-907](#cs-907) | EC flushing off, feed EC unknown | Warning | Notification |

## Probes (CS-1xx)

<a id="cs-101"></a>

### CS-101: Flat moisture reading

*Warning · Notification*

**What it means.** For more than 20 min, the moisture (VWC) reading of the zone does not change. The controller cannot tell a good probe from a probe that stopped or came out of the substrate. The controller does not steer the zone on this reading.

**Effect on water.** While the kill switch is on, the zone continues without its probe. The zone gets the same shots as a zone of the room with a probe that works. If no such zone exists, the zone gets one shot each 90 min (blind_fallback_min), inside its daily water limit. Phase changes that use VWC wait until the reading moves.

**Probable causes**

- No plant in the cube, or the plant is too small to drink much water. Nothing removes water, so the reading does not change. This is usual on a bench test or a new installation.
- The probe is out of the cube, or it is in a tray.
- The cube is full of water, and the probe stays at its highest reading.
- The integration of the probe stopped, and it continues to show its last value.

**What to do**

- Examine the cube first: a cube with no plant, or with a small plant, gives a flat reading.
- Make sure that the probe is fully in the cube.
- Open the history of the probe in Home Assistant.
- If the line is flat for hours while the plants drink, restart the probe or its integration.
- If the room has no plants, set "Room Active" to off.

<a id="cs-102"></a>

### CS-102: Probe with no reading

*Warning · Notification*

**What it means.** The moisture (VWC) entity of the zone reads "unavailable" or "unknown", is not a number, or is not in Home Assistant. It can also show a time in the future. The alert tells which.

**Effect on water.** For the first 15 min, the zone waits and the controller gives no shot and no alert. After 15 min, while the kill switch is on, the zone continues without its probe. The zone gets the same shots as a zone of the room with a probe that works. If no such zone exists, the zone gets one shot each 90 min (blind_fallback_min), inside its daily water limit. Phase changes that use VWC wait for the probe.

**Probable causes**

- The probe is offline: it has no power, its battery is flat, or it is out of Wi-Fi or Zigbee range.
- Home Assistant restarted, and the integration of the probe took more than 15 min to load.
- A person renamed or removed the probe, so the entity that is mapped to the zone does not exist.
- The clock of Home Assistant is ahead of the clock of the controller. The reading then seems to come from the future, and the alert tells you.

**What to do**

- Find the entity that the alert names in Developer tools → States, and read its state.
- Make sure that the probe device has power and is online.
- Check the range of its Wi-Fi or Zigbee link.
- In Crop Steering → Rooms and setup, make sure that the zone uses the correct probe.
- If the alert shows a time in the future, correct the clocks of the Home Assistant host and the controller.

<a id="cs-103"></a>

### CS-103: Moisture reading out of range

*Warning · Notification*

**What it means.** The moisture (VWC) entity of the zone gives a value below 0% or above 100%. The controller ignores this value.

**Effect on water.** The zone continues without its probe, the same as for a probe that does not report (CS-102).

**Probable causes**

- The probe is defective, or its calibration is incorrect.
- The entity that is mapped to the zone is not a VWC in %. It is a raw count, a voltage or a different reading of the same device.

**What to do**

- Check the calibration of the probe in its own integration.
- In Crop Steering → Rooms and setup, make sure that the zone uses the VWC entity in %.
- Do not map a raw count, a voltage or a different entity of the same device.

<a id="cs-104"></a>

### CS-104: EC reading not available

*Warning · Notification*

**What it means.** The zone has no usable EC reading. The EC entity is missing, unavailable or out of range, or it has not changed for 20 min.

**Effect on water.** The controller steers the zone on VWC only. The controller cannot measure the salt in the substrate, so it cannot correct the EC with a flush.

**Probable causes**

- No EC probe is mapped to the zone.
- The EC probe is offline, or its reading does not change for more than 20 min. A cube with no plant gives this result, as for CS-101.

**What to do**

- CAUTION: Do not ignore this alert for many days. Salt can build up in the substrate when the controller cannot read EC.
- If the zone has an EC probe, map it to the zone in Crop Steering → Rooms and setup.
- Make sure that the EC probe is online.
- Make sure that its reading changes. A cube with no plant gives a flat EC reading.

## Shots held (CS-2xx)

<a id="cs-201"></a>

### CS-201: Setup change on hold

*Critical · Notification*

**What it means.** The controller has a new setup for the room, or it loads the setup again after a restart. It applies a setup only when all the pumps and valves of the room are off. For a changed setup, the kill switch must also be off.

**Effect on water.** The room gets no shots until the controller applies the setup. If the hold continues, the substrate dries out.

**Probable causes**

- A person saved the setup while the kill switch was on.
- A pump or a valve stays on, or it reads "unavailable".
- The controller restarted while a pump ran (for example, to circulate a tank), or while a switch read "unavailable".

**What to do**

- CAUTION: Do not leave the room in this hold for a long time. The substrate dries out and the plants can wilt.
- Read the list of devices in the alert.
- Set each pump and valve in the list to off.
- If the alert names the kill switch (Engine Enabled), set it to off.
- Wait for the alert to clear.
- Set the kill switch to on again.

<a id="cs-202"></a>

### CS-202: Pump or main-line mismatch

*Critical · Notification*

**What it means.** The setup of the room has a pump or a main-line valve, but no entity is mapped to it. Or an entity is mapped, but the setup has none. The controller holds the room, so it does not open a valve with no pump.

**Effect on water.** The room gets no shots until the setup and the mapped entities agree.

**Probable causes**

- A person removed the pump or the main-line switch from the setup of the room, or removed its device.
- The plumbing in the setup is not the real plumbing of the room.
- The integration is newer than the controller, and it uses a plumbing layout that the controller does not know.

**What to do**

- CAUTION: Do not leave the room in this hold for a long time. The substrate dries out and the plants can wilt.
- Read the detail in the alert.
- In Crop Steering → Rooms and setup, map the missing switch.
- Alternatively, set the layout to the real pipes and pumps of the room.
- If the alert names a layout that the controller does not know, upgrade the controller. The hold clears when the controller applies the correct setup (CS-201).

<a id="cs-203"></a>

### CS-203: Invalid maximum shot length

*Critical · Notification*

**What it means.** The maximum shot length (Maximum shot duration) of the room is not a number, or it is less than 5 s. The controller does not replace a value that you set with a default, because a default can flood the room.

**Effect on water.** The room gets no shots until the value is correct. The controller uses 900 s only when no Maximum shot duration entity exists, and then it gives no alert.

**Probable causes**

- The setting reads "unavailable", because the integration did not load.
- The setting is less than 5 s.

**What to do**

- CAUTION: Do not leave the room in this hold for a long time. The substrate dries out and the plants can wilt.
- Make sure that the Crop Steering integration is loaded in Settings → Devices & services.
- Set Maximum shot duration to 5 s or more.
- If Repairs shows CS-605, do the steps of CS-605 first.

<a id="cs-204"></a>

### CS-204: Invalid shot size inputs

*Critical · Notification*

**What it means.** The controller calculates each shot from the substrate volume, the plant count, the drippers for each plant and the dripper flow. One of these values is zero, less than zero, or not a number.

**Effect on water.** The zone gets no shots. A missing or unavailable value does not cause this alert, because the controller then uses its built-in value (CS-402).

**Probable causes**

- The substrate volume, the drippers for each plant or the dripper flow is 0 or less.
- The flow_lps or substrate_l option of the controller is 0 or less, and the zone has no value of its own. The controller then uses the option.

**What to do**

- CAUTION: Do not leave the zone in this hold for a long time. The substrate dries out and the plants can wilt.
- In Crop Steering → Rooms and setup, set the substrate volume, plant count, drippers per plant and dripper flow of the zone.
- Make sure that each value is more than 0.
- Check that the flow_lps and substrate_l options of the controller are more than 0.

<a id="cs-205"></a>

### CS-205: Daily water limit reached

*Information · Notification*

**What it means.** The zone has received its daily water limit (max daily volume) since lights-on. A shot that crosses the limit gets only the remaining volume.

**Effect on water.** Maintenance shots and EC correction shots stop until the next lights-on. The ramp, the rescue shot, the watchdog shot and high-EC flushes continue. A zone with no usable VWC reading gets no more water until lights-on, rescue shots included.

**Probable causes**

- The plants use that much water: the limit is too low for their size.
- The shots give more water than the controller calculates, because the dripper flow setting is lower than the real flow. The zone then reaches the limit early.
- The probe continues to read dry, so the controller continues to ask for water. The probe can be in a dry spot, or the water does not get to it.

**What to do**

- CAUTION: Do not increase the limit before you do a catch test. If the dripper flow setting is too low, the substrate gets more water than the controller counts.
- Do a catch test to measure the real dripper flow.
- Correct the dripper flow setting.
- Make sure that the probe is in the cube and that the drippers reach it.
- Increase the max daily volume only after these checks.

<a id="cs-206"></a>

### CS-206: EC too high, zone held

*Warning · Notification*

**What it means.** The EC of the zone is above its maximum EC setting. A flush cannot decrease it now. The feed EC is not lower than the EC in the substrate, or the substrate is at field capacity.

**Effect on water.** The controller holds the zone and no shot runs, the rescue shot and the watchdog shot included. The hold stops when a flush can help again. Without action, the substrate can dry out.

**Probable causes**

- The feed EC is equal to or higher than the EC in the substrate.
- The cube is at field capacity, so more water only becomes runoff.
- The EC probe reads too high, because of its calibration or because the probe is dry.

**What to do**

- CAUTION: Do not leave the zone in this hold overnight without a check. The rescue shot does not run, so the substrate can dry out.
- Measure the feed EC in the tank.
- If the feed EC is high, decrease it.
- Check the feed EC probe (feed_ec_sensor) against a hand-held meter.
- Check the EC probe of the zone against a hand-held meter.
- Make sure that the maximum EC setting of the zone is correct.

<a id="cs-207"></a>

### CS-207: Dry zone, all shots blocked

*Critical · Notification*

**What it means.** The VWC of the zone is below its re-water point. The zone has had no shot for longer than its watchdog time (3 h by default). Something blocks every shot. The alert names the block.

**Effect on water.** The zone gets no water until the block clears. The plants can wilt and the substrate can dry out.

**Probable causes**

- The kill switch is off. On a new installation, this is usual: the alert tells you that no zone gets water until you set the kill switch to on.
- Auto irrigation or the zone switch is off, or manual override is on.
- A hold stops the shots. Examples are a setup change (CS-201), plumbing that does not agree (CS-202) and a hardware fault (CS-301). Other examples are an external hold (a dose, a fill or a flush) and the source-water gate. The hold of a grow plan (CS-606) does not stop this safety shot.

**What to do**

- CAUTION: Do not ignore this alert. The substrate of the zone is dry, and dry substrate can damage the roots.
- Read "Blocked by" in the alert.
- Remove the block that the alert names.
- If the kill switch is off on purpose, water the zone by hand.
- If the room has no plants, set "Room Active" to off.

<a id="cs-208"></a>

### CS-208: Retired switch is off

*Warning · Notification*

**What it means.** System Enabled and Auto Irrigation Enabled are retired. The kill switch ("Watering" on the dashboard) is now the only switch that stops water. One retired switch is off, so the controller sets the kill switch to off, and does this again while the retired switch stays off.

**Effect on water.** The room gets no shots. A shot in progress stops within some seconds. The controller continues to read the probes and to change the phases.

**Probable causes**

- A person or an automation set System Enabled or Auto Irrigation Enabled to off before these switches were retired.
- An automation still sets one of these switches to off to stop the water.

**What to do**

- CAUTION: Do not leave the room in this hold for a long time. The substrate dries out and the plants can wilt.
- In Settings → Entities, show the hidden entities.
- Set the retired switch that the alert names to on.
- In Crop Steering, use Watering in the header to review switching it on.
- Change each automation that sets a retired switch to off.
- Make it set the kill switch of the room to off instead.

<a id="cs-209"></a>

### CS-209: No shots for some hours

*Warning · Notification*

**What it means.** The room is on, its lights are on, and one or more zones are in P1 or P2. No zone of the room has had a shot for the number of hours that you set (3 h by default, 1 to 12 h). The alert gives the reason when the controller knows it.

**Effect on water.** The alert does not change the water. It comes again after each period of the same length. It clears at the next shot, at lights-off, or when no zone is in P1 or P2.

**Probable causes**

- A person set the kill switch of the room to off, and did not set it to on again.
- A hold stops each shot. Examples are a batch, a hardware hold after a pump or valve fault (CS-301), and a zone switch that is off. Other examples are manual override, the source-water gate, and a pump or valve that reads neither on nor off. The alert names the hold.
- No zone needed water: each zone in P1 or P2 read wetter than its re-water point. For example, a probe is out of its cube or stays high, or the re-water point is too low for the plants.

**What to do**

- CAUTION: Do not ignore this alert for many hours. The zones get no water, and the substrate can dry out.
- Read the reason in the alert.
- Remove the hold that it names.
- If the kill switch is off, set it to on.
- If no zone needs water, compare the VWC of each zone with its re-water point.
- Make sure that each probe is in its cube.
- To change the number of hours, go to Crop Steering → Settings → Notifications.

<a id="cs-210"></a>

### CS-210: Hold entity missing

*Warning · Notification*

**What it means.** The hold entities option of the controller app names one or more entities that Home Assistant does not have. The controller checks them when it starts, before it waters, also while the kill switch is off. The alert names each missing entity.

**Effect on water.** No room gets shots while a hold entity is missing, the same as while a hold is on. The status of each held zone tells which entity is missing. The alert clears by itself when each entity exists.

**Probable causes**

- The entity ID in the option has a typo.
- A person deleted or renamed the helper or switch that the option names.

**What to do**

- CAUTION: Do not leave the rooms in this hold for a long time. The substrate dries out and the plants can wilt.
- Compare each entity that the alert names with the entities in Settings → Entities.
- Correct or remove the entity in the hold entities option of the controller app, and restart the app.
- Or make the missing helper or switch with that entity ID.
- If you removed the entity from the option, dismiss the alert.

<a id="cs-211"></a>

### CS-211: Shots held for too long

*Critical · Notification*

**What it means.** A zone asked for water, and a hold stopped every shot for longer than the hours that you set (Shots held alert, 0 = off). A hold that a person sets on purpose (the kill switch, a zone switch, manual override) does not count. The alert names the hold.

**Effect on water.** The alert does not change the water. The zone gets no water until the hold clears. The alert comes again every 30 minutes, and clears at the next shot of the zone.

**Probable causes**

- The source-water gate holds the shots: the feed pH or feed EC is outside its band, or the feed probe is dead.
- A hardware hold after a pump or valve fault (CS-301), a hold entity that is on, or a batch or a dose that holds the room.
- A pump or valve that reads neither on nor off.

**What to do**

- CAUTION: Do not ignore this alert. The zone gets no water, and the substrate can dry out.
- Read the hold in the alert, and remove it.
- If the feed pH or EC is outside its band, correct the tank, or turn on pH auto-correct.
- If you cannot remove the hold soon, water the zone by hand.
- To change the hours, or to turn the alert off, set Shots held alert in the settings of the room.

<a id="cs-212"></a>

### CS-212: Controller error in room

*Critical · Notification*

**What it means.** An error stopped the controller in the pass of this room. The alert gives the error. The heartbeat and the status of the room show error. The other rooms continue.

**Effect on water.** The room gets no shots, also no rescue shots, until the error stops. The controller tries the room again each minute. The alert comes again every 30 minutes while the error continues, and clears after the next pass of the room without an error.

**Probable causes**

- A fault in the controller, for example a setting or a state of the room that it cannot use.
- An entity of the room that gives a value of a type that the controller does not expect.

**What to do**

- CAUTION: Do not leave the room in this state for a long time. The substrate dries out and the plants can wilt.
- Read the controller log near the time of the alert.
- Report the error with the log.
- Until the error stops, water the room by hand.

## Pumps and valves (CS-3xx)

<a id="cs-301"></a>

### CS-301: Hardware fault latch

*Critical · Notification*

**What it means.** A pump or a valve did not read back off after the controller closed it. The device can still be on. The controller latches a hold on that hardware, and the hold stays after a restart.

**Effect on water.** No shot starts on that hardware, in each room that shares it, until the hold clears. If the device is still on, water can flow without control and flood the zone.

**Probable causes**

- The device of the switch went offline during a shot.
- A relay or a valve stays on.
- The switch reports its state late, or does not report it.

**What to do**

- WARNING: Isolate the electrical power before you touch a pump, a valve or its wiring. Water near mains power can cause an electric shock.
- CAUTION: Examine the hardware now. A valve or a pump that stays on can flood the substrate and the floor.
- Go to the room now and examine the pump and the valves.
- If a pump or a valve is on, stop it by hand.
- Set the kill switch of each room that shares the hardware to off. The hold clears when all the pumps and valves read off.
- Then set each kill switch to on again.
- If the alert says that the controller could not save the fault, do not restart the controller. A dismissed alert does not clear the hold.

<a id="cs-302"></a>

### CS-302: Pump command error

*Warning · Notification*

**What it means.** The pump did not start. Home Assistant returned an error when the controller tried to start it, or took the command but the pump did not read on within 16 s. A device that already reads "unavailable" does not cause this alert, because no shot starts then.

**Effect on water.** The controller cancels the shot and does not count it. It closes the pump, the main-line valve and the zone valve, and reads them back. If they do not read off, it latches a hardware hold (CS-301). If they read off, the next shot runs as usual. After 3 such shots of a zone in a row (CS-302, CS-303 or CS-304), the controller tries that zone at most once every 30 min, rescue shots too, until its switches read on again. A Test Shot is not held.

**Probable causes**

- Home Assistant did not reply (it restarted, or the network has a fault), or it returned an error for the command.
- The device took the command but did not switch: a dead relay, or an offline Zigbee plug that still accepts commands. Or it reports its new state more than 16 s late.
- A switch that reads "unavailable" does not cause this alert. No shot starts while a switch on the feed path reads neither on nor off. The status of the zone names the offline switch. The zone gets water again when the switch reads again.

**What to do**

- WARNING: Make sure that no person works on the pump or its pipes before you start it by hand. A pump that starts suddenly can spray water near mains power.
- Start and stop the pump by hand in Home Assistant to test it.
- Make sure that the correct pump is mapped in Crop Steering → Rooms and setup.
- Check the network link between Home Assistant and the device.
- If a CS-301 alert also shows, do its steps.

<a id="cs-303"></a>

### CS-303: Main-line valve command error

*Warning · Notification*

**What it means.** The main-line valve did not open. Home Assistant returned an error when the controller tried to open it, or took the command but the main-line valve did not read on within 16 s. A device that already reads "unavailable" does not cause this alert, because no shot starts then.

**Effect on water.** The controller cancels the shot and does not count it. It closes the pump, the main-line valve and the zone valve, and reads them back. If they do not read off, it latches a hardware hold (CS-301). If they read off, the next shot runs as usual. After 3 such shots of a zone in a row (CS-302, CS-303 or CS-304), the controller tries that zone at most once every 30 min, rescue shots too, until its switches read on again. A Test Shot is not held.

**Probable causes**

- Home Assistant did not reply (it restarted, or the network has a fault), or it returned an error for the command.
- The device took the command but did not switch: a dead relay, or an offline Zigbee plug that still accepts commands. Or it reports its new state more than 16 s late.
- A switch that reads "unavailable" does not cause this alert. No shot starts while a switch on the feed path reads neither on nor off. The status of the zone names the offline switch. The zone gets water again when the switch reads again.

**What to do**

- Start and stop the main-line valve by hand in Home Assistant to test it.
- Make sure that the correct main-line valve is mapped in Crop Steering → Rooms and setup.
- Check the network link between Home Assistant and the device.
- If a CS-301 alert also shows, do its steps.

<a id="cs-304"></a>

### CS-304: Zone valve command error

*Warning · Notification*

**What it means.** The zone valve did not open. Home Assistant returned an error when the controller tried to open it, or took the command but the zone valve did not read on within 16 s, or by the end of a shorter shot (at least 6 s). A device that already reads "unavailable" does not cause this alert, because no shot starts then.

**Effect on water.** The controller cancels the shot. If every read of the valve was a definite off, no water went to the zone and the controller does not count the shot. If a read was anything else (unavailable, unknown, opening, or on too late), water may have flowed, so the controller counts the time from opening the valve to closing it. It closes the pump, the main-line valve and the zone valve, and reads them back. If they do not read off, it latches a hardware hold (CS-301). If they read off, the next shot runs as usual. After 3 such shots of a zone in a row (CS-302, CS-303 or CS-304), the controller tries that zone at most once every 30 min, rescue shots too, until its switches read on again. A Test Shot is not held.

**Probable causes**

- Home Assistant did not reply (it restarted, or the network has a fault), or it returned an error for the command.
- The device took the command but did not switch: a dead relay, or an offline Zigbee plug that still accepts commands. Or it reports its new state more than 16 s late.
- A switch that reads "unavailable" does not cause this alert. No shot starts while a switch on the feed path reads neither on nor off. The status of the zone names the offline switch. The zone gets water again when the switch reads again.

**What to do**

- Start and stop the zone valve by hand in Home Assistant to test it.
- Make sure that the correct zone valve is mapped in Crop Steering → Rooms and setup.
- Check the network link between Home Assistant and the device.
- If a CS-301 alert also shows, do its steps.

<a id="cs-305"></a>

### CS-305: Early shot stop

*Information · Notification*

**What it means.** A shot stopped before its end, because a person or an automation changed a switch. The switch can be the kill switch, "Room Active", the zone switch or manual override. The controller closed the valve and the hardware upstream of it.

**Effect on water.** The controller counts the water that the zone got before the stop. The next shot follows the usual rules. If a device does not read back off, the controller also raises CS-301.

**Probable causes**

- During a shot, a person set the kill switch, Room Active or the zone switch to off, or set manual override to on.
- An automation made this change.

**What to do**

- If the stop was on purpose, no action is necessary.
- If not, open the logbook of the switch that the alert names.
- Find the person or the automation that changed the switch.

<a id="cs-306"></a>

### CS-306: Shot cut to maximum length

*Warning · Notification*

**What it means.** The calculated shot was longer than the maximum shot length of the room. The controller cut the shot to the limit, so the zone got less water than planned.

**Effect on water.** Water continues, but each cut shot gives less water than the controller calculated. Three cut shots in sequence cause CS-312.

**Probable causes**

- The dripper flow or the drippers for each plant is set too low, so the controller calculates a long shot.
- The substrate volume is set too high.
- The maximum shot length is too short for the room.

**What to do**

- CAUTION: Do not increase Maximum shot duration before you do the catch test. A long shot with a wrong flow setting can flood the substrate.
- Check the substrate volume, drippers per plant and dripper flow of the zone.
- Do a catch test to measure the real flow.
- If the settings are correct, increase Maximum shot duration.

<a id="cs-307"></a>

### CS-307: Shot stopped by external change

*Warning · Notification*

**What it means.** During a shot, a hold of the room started (a dose, a tank fill or a flush). Or a different device or a person closed the zone valve. The shot stopped at that time. The controller closed its own valves, and did not stop the pump if a hold uses it.

**Effect on water.** The controller counts only the seconds that the valve was open. The next shot follows the usual rules.

**Probable causes**

- A dose or tank fill automation used the tank or its pump during a shot. For example, a batch tank became empty 4 s after the start of a shot.
- A guard automation or a person set the zone valve to off.
- The device of the valve went off the network.

**What to do**

- If the stop was on purpose, no action is necessary.
- If this occurs frequently, move the dose and tank fill times away from the shot times.
- Otherwise, open the logbook of the zone valve to find what closed it.
- Check the network link of the valve device.

<a id="cs-308"></a>

### CS-308: Interrupted shot, hardware on

*Critical · Notification*

**What it means.** A shot did not end correctly. The controller stopped or lost Home Assistant during the shot, or a device did not read back off. The controller tried to close the devices of the shot, and one or more still read on.

**Effect on water.** The controller latches a hardware hold (CS-301) and tries again on each loop. Water can still flow through the device that reads on.

**Probable causes**

- A relay or a valve stays on.
- The device of the switch is offline, so its state cannot change.

**What to do**

- WARNING: Isolate the electrical power before you touch a pump, a valve or its wiring. Water near mains power can cause an electric shock.
- CAUTION: Examine the hardware now. A valve or a pump that stays on can flood the substrate and the floor.
- Go to the room now.
- Examine the device that the alert names, and its pipes.
- If water flows, stop the device by hand.
- Then do the steps of CS-301 to clear the hold.

<a id="cs-309"></a>

### CS-309: Interrupted shot, state unknown

*Warning · Notification*

**What it means.** A shot did not end, and the controller cannot read a device that the shot opened. Or Home Assistant has no change time or history for that device. The controller does not close the device, because a person can also use it by hand.

**Effect on water.** No new shot starts in the room until the controller settles the interrupted shot. It checks again on each loop. When it can read the device, it closes only what the shot opened.

**Probable causes**

- The device of the switch is offline or reads "unavailable".
- Its integration gives no time for the last change of the switch.
- Home Assistant keeps no history for the switch. The recorder excludes the switch, or Home Assistant started a short time ago.

**What to do**

- WARNING: Isolate the electrical power before you touch a pump, a valve or its wiring. Water near mains power can cause an electric shock.
- CAUTION: Examine the hardware now. A valve or a pump that stays on can flood the substrate and the floor.
- Go to the room now.
- Examine the device that the alert names, and its pipes.
- If water flows, stop the device by hand.
- Connect the device to Home Assistant again.
- If the recorder excludes the device, include it again. The controller uses the history to tell a restart from a person.

<a id="cs-310"></a>

### CS-310: Table drain blocked

*Critical · Notification*

**What it means.** The VWC of a zone increased by 3 points or more in 1 h with no water from its valve. The valve was also closed for 45 min before the increase. Water comes from below, because the table or its drain is blocked or the sump does not pump. The controller does not monitor a room whose Drainage setting is free drain.

**Effect on water.** The controller holds the minimum daily volume and the EC flushes of the zone. The alert comes again each 30 min while the VWC increases, and clears after 1 h with no increase. Until the table drains, the roots sit in runoff.

**Probable causes**

- Substrate, roots or debris block the drain or the drain line of a table.
- The sump pump does not pump: it is defective, it has no power, or its float is stuck. The sump fills, and the water flows back into the tables.
- A shared gutter or drain is full, and runoff from other tables flows into this table.
- Less probable: a person moved the probe to a wetter spot, or gave water by hand without the zone valve (for example, with a hose).

**What to do**

- WARNING: Isolate the electrical power to the sump pump before you touch it. Water near mains power can cause an electric shock.
- CAUTION: Do not water the zone by hand until the table drains. More water can flood the table and damage the roots.
- Go to the room now.
- Look for water that stands on the table.
- Check the drain outlets, the sump and the sump pump.
- Remove the blockage.
- Make sure that the sump pumps the water out.
- If nothing is blocked, check that the probe did not move to a wetter spot.

<a id="cs-311"></a>

### CS-311: No sump pump run

*Critical · Notification*

**What it means.** The power reading of the sump pump (sump_power_sensor) shows no run for 3 h by default (sump_silent_hours). A run is a reading above the Sump Pump Run Threshold, 20 W by default. Without the pump, runoff fills the sump and flows back into the tables.

**Effect on water.** The alert does not change the water. It comes again each 30 min until the next pump run. If the VWC of a zone then increases with no water, CS-310 follows.

**Probable causes**

- The sump pump is defective, or its float is stuck.
- The pump has no power: its power plug is off, or it tripped.
- No water gets to the sump: the drains of the tables or the line to the sump are blocked.
- The power plug is offline, so the controller cannot see a run (the reading is unavailable).

**What to do**

- WARNING: Isolate the electrical power to the sump pump before you touch it. Water near mains power can cause an electric shock.
- CAUTION: Do not let the sump overflow. Runoff can flow back into the tables and flood the roots.
- Go to the room now.
- Check the water level in the sump.
- Check the pump, its float switch and its power plug.
- Remove what stops the water to or from the sump.
- If the power plug is offline, connect it again.
- Increase sump_silent_hours only if the pump really runs less frequently.

<a id="cs-312"></a>

### CS-312: Repeated maximum-length shots

*Warning · Repairs card*

**What it means.** The last 3 shots of a zone each needed more time than the maximum shot length of the room. The controller cut each shot (CS-306). This often shows a probe that reads dry, or a wrong substrate volume or dripper flow.

**Effect on water.** If the max-run latch switch of the room is on, the zone gets no more shots, rescue shots included, until you fix the Repairs card. If the latch switch is off, the card only reports. It clears after the next shot that the controller does not cut.

**Probable causes**

- The probe of the zone reads dry when the slab is not dry. The probe can be stuck, disconnected from the slab, or out of the substrate. Each shot is then calculated for a dry slab.
- The substrate volume, plant count, drippers for each plant or dripper flow of the zone is incorrect. The calculated shots are then much too long.
- Some drippers are blocked, so the water flows more slowly than the dripper flow setting.
- The maximum shot length of the room is shorter than the usual shots of this zone.

**What to do**

- CAUTION: Fix the card soon when the latch switch is on. The zone gets no water, and the substrate can dry out.
- Examine the zone: the slab, the probe and the drippers.
- Check the substrate volume, plant count, drippers per plant and dripper flow in Rooms and setup.
- If all are correct, increase the maximum shot length of the room.
- To water the zone again, open the card in Settings → Repairs and confirm it.

<a id="cs-313"></a>

### CS-313: Device type not supported

*Warning · Notification*

**What it means.** A zone valve, pump or main-line valve has a device type that the controller cannot open or close. The controller can use a switch, an input_boolean or a valve. The setup does not accept other types, so a person mapped this device by hand.

**Effect on water.** The zone gets no shots, and the controller sends no command to the device. Other zones continue.

**Probable causes**

- A person mapped a cover, a light, a fan or a different type of device as a zone valve, the pump or the main-line valve.
- The integration of the device shows it as a type that Crop Steering cannot operate.

**What to do**

- CAUTION: Do not leave the zone in this hold for a long time. The substrate dries out and the plants can wilt.
- In Crop Steering → Rooms and setup, map a switch, an input_boolean or a valve in its place.
- If the hardware exists only as a different device type, make a template switch for it in Home Assistant.
- Map the template switch. The zone gets water again from the next loop.

<a id="cs-314"></a>

### CS-314: Sump water balance does not close

*Warning · Notification*

**What it means.** With the runoff estimator at shown_alerts or ai, a grow-day whose sump litres (its runs times the litres per run) miss what a sealed room must send to the sump (the water fed minus the change of water in the substrate) by more than 30%. In a sealed room the water the plants transpire comes back as AC and dehumidifier condensate, so the two agree on a normal day.

**Effect on water.** The alert does not change the water. The runoff estimate is a room-wide hint and never waters or holds a zone.

**Probable causes**

- A leak: water leaves the room another way than the sump.
- The power plug of the sump pump missed a run, or reports too slowly to see each run.
- The float of the sump is stuck, so the pump runs at the wrong level.
- The litres per run (a bucket test, or the pump flow) are wrong.
- The room is not sealed: air is exchanged with outside, so condensate leaves with it.

**What to do**

- Look for water on the floor and at the drains of the tables.
- Check that the power plug of the sump pump reports often enough to see each run (every 30 s or less).
- Check the float of the sump.
- Measure the litres of one sump run with a bucket and set Sump litres per run.
- Set the runoff estimator to shadow if the room is not sealed.

<a id="cs-315"></a>

### CS-315: Rescue shots not absorbed

*Critical · Notification*

**What it means.** Rescue shots of a zone (P3 emergency or watchdog shots) did not raise its moisture, several in a row. Each rescue is judged 15 min after it, or at the next rescue if that comes first: it counts as a miss when the moisture rose less than 0.5 points. The alert comes at the number of misses that the room setting Rescue misses before alert gives (4 by default). The check runs only while the room select Rescue shots not absorbed is set to Alert.

**Effect on water.** The alert does not change the water. The rescue shots continue. The alert clears at the next rescue that raises the moisture.

**Probable causes**

- A dripper, a dripper line or a filter is blocked.
- The zone valve does not open, or the pump does not deliver.
- The probe is out of the substrate or does not touch it, so it cannot see the water.
- A line leaks before the drippers, so the water goes to the floor.

**What to do**

- CAUTION: Examine the zone now. A blocked line keeps the plants dry, and a leak puts the water on the floor.
- Look at the drippers of the zone during the next shot.
- Check the zone valve, the pump and the filters.
- Check that the probe sits fully in the substrate.
- If the probe is the problem, fix or replace it. The rescue shots continue meanwhile.

<a id="cs-316"></a>

### CS-316: Waste valve not closed

*Warning · Notification*

**What it means.** The room has a waste valve mapped and its waste valve rule is set. With Check closed, the waste valve does not read off. With Close for each shot, the controller set it to off before a shot and it did not read off, or the controller cannot switch or read it. An open waste valve sends the feed to waste while the controller counts it as given.

**Effect on water.** No shot starts in the room until the waste valve reads off. A shot that is running stops when the waste valve opens (CS-307).

**Probable causes**

- The waste valve is open, by hand or by an automation.
- The switch of the waste valve is offline.
- The waste valve or its relay is stuck open.

**What to do**

- Close the waste valve, or find what keeps it open.
- Check the switch of the waste valve in Home Assistant.
- If the plumbing does not need the waste valve closed for a shot, set the waste valve rule of the room to Off.

<a id="cs-317"></a>

### CS-317: Pump runs with every valve shut

*Warning · Notification*

**What it means.** The feed pump of the room (option pump_power_sensor) uses more power than the room setting Pump dead-head power, for 1 min, while every zone valve of the room reads off, and no shot, hold or batch uses the pump. A pump that runs against shut valves (dead-head) heats up and can be damaged.

**Effect on water.** The alert does not change the water. The controller does not switch the pump off. The alert clears when the pump stops or a valve opens.

**Probable causes**

- The pump was switched on by hand or by an automation with no valve open.
- The pump relay is stuck on.
- The Pump dead-head power setting is below the standby power of the pump.

**What to do**

- CAUTION: Check the pump now. A pump that runs dry or against shut valves can be damaged.
- Switch the pump off, or open the valve that it should feed.
- If the pump uses power when it is off, increase Pump dead-head power above that value.

## Settings (CS-4xx)

<a id="cs-401"></a>

### CS-401: Setting outside controller range

*Warning · Notification*

**What it means.** The entity accepts a wider range than the controller uses, and the value is outside the range of the controller. The alert names the setting, its value and the range. For a check of two settings, for example a minimum above its maximum, it names the two.

**Effect on water.** Water continues. The controller uses the nearest value inside its range.

**Probable causes**

- A person set the setting to an extreme value. For example, a field capacity of 95% when the controller accepts a maximum of 90%.

**What to do**

- Set the value inside the range that the alert shows.
- If the alert compares two settings, change one of them. The controller calculates the minimum daily volume from the mL for each plant and the plant count.

<a id="cs-402"></a>

### CS-402: Missing settings

*Critical · Notification*

**What it means.** The controller cannot read some settings by their entity IDs for 3 loops. It uses the last value that it read since its start, or its built-in value. The alert lists the settings.

**Effect on water.** All shots wait for 3 loops. Then water continues on the last value or the built-in value, which can be wrong for the room. A zone gets no shots, rescue shots included, if the controller has not read one of its water size settings since its start. These are the substrate volume, plant count, drippers per plant, dripper flow and daily water limit.

**Probable causes**

- The Crop Steering integration did not load, or a person removed it.
- A person changed an entity ID in Settings.
- A person made the room while Home Assistant still ran an older integration. The settings then got different entity IDs (CS-605).

**What to do**

- CAUTION: Do not let the controller run on built-in values for a long time. The built-in values can give too much or too little water for the room.
- Make sure that the Crop Steering integration is loaded.
- Reload the integration.
- If Repairs shows CS-605, do the steps of CS-605.
- Restore the original entity ID of each entity that you edited.

<a id="cs-403"></a>

### CS-403: Lights hours from the integration

*Information · Notification*

**What it means.** The controller now reads the lights-on and lights-off hours from the integration, not from its own options. The two sources do not agree.

**Effect on water.** Water continues on the hours of the integration. The controller uses its own options only when it has not read the hours of the integration since its start.

**Probable causes**

- The installation is from before the integration had its own lights hours.

**What to do**

- If the hours of the integration are correct, set lights_on_hour and lights_off_hour in the controller options to the same hours.
- If they are not correct, set Lights on hour and Lights off hour in the integration.

<a id="cs-404"></a>

### CS-404: Automatic setpoints paused

*Warning · Notification*

**What it means.** Automatic setpoints change the targets of a zone from the ramp of each morning. This morning the ramp did not show water at the probe, so the controller paused the automatic changes for the zone. The alert tells what was wrong.

**Effect on water.** Water continues on the current targets. The controller examines the ramp again the next morning.

**Probable causes**

- A dripper is blocked, a line is kinked, or a valve does not open.
- The probe moved, or it is not where the drippers wet the cube.
- The shots are too small to increase the reading.

**What to do**

- Check the drippers and the lines of the zone.
- Do a catch test.
- Check the position of the probe in the cube.
- Make sure that the shots are large enough to increase the VWC reading.

<a id="cs-405"></a>

### CS-405: Time zone mismatch

*Warning · Notification*

**What it means.** The clock of the controller uses a different time zone from Home Assistant. The controller uses its own clock for lights-on, lights-off, dryback and the daily reset.

**Effect on water.** Water continues, but the full grow-day moves by the time difference. Shots and phase changes occur at the wrong hours.

**Probable causes**

- An old build of the controller has no time zone data.
- A person changed the time zone of Home Assistant after the controller started.
- The TZ setting of a controller container is not the time zone of Home Assistant.

**What to do**

- Upgrade or rebuild the controller, then restart it.
- Check the time zone of Home Assistant in Settings → System → General.
- For a controller container, set TZ in the compose file to the time zone of Home Assistant.
- Alternatively, remove TZ from the compose file.
- Restart the container.

## Zone comparisons (CS-5xx)

<a id="cs-501"></a>

### CS-501: Low water compared to room

*Information · Notification*

**What it means.** Today the zone got less than 40% of the median daily water of the zones of the room. The controller makes this check only when that median is 5 L or more.

**Effect on water.** Water continues as usual. This alert is advice only.

**Probable causes**

- The plants are smaller, or they drink less.
- The probe is in a wetter spot than the roots, so the zone does not frequently need water.
- A valve or a dripper has a problem.

**What to do**

- Compare the plants of this zone with the plants of the other zones.
- Check the position of the probe.
- Do a catch test on this zone and on one adjacent zone.

<a id="cs-502"></a>

### CS-502: Too few probes in agreement

*Warning · Notification*

**What it means.** The zone steers its VWC or EC on its lowest or highest probe. This method needs 3 probes that agree. Fewer probes agree, so the zone uses their median, and it does not use a probe far from the others.

**Effect on water.** Water continues on the median of the remaining probes.

**Probable causes**

- A probe is out of its cube or in a puddle, and its reading is far from the other probes.
- A probe is offline or does not report.
- The zone has only one or two probes.

**What to do**

- Under Probes for the zone, check the probes that the reading does not use.
- If the zone has fewer than 3 probes, set its "From Probes" setting to Median.

<a id="cs-503"></a>

### CS-503: Probe unit not accepted

*Warning · Notification*

**What it means.** The moisture probe of the zone uses a unit that is not a percentage, and its value is outside 0 to 100. The controller sets the probe aside, so the zone has no VWC reading. The controller reads %, converts m³/m³, and reads a probe with no unit as % while its value is 0 to 100.

**Effect on water.** The same as for CS-102. After 15 min, while the kill switch is on, the zone continues without its probe. The zone gets the same shots as a zone of the room with a probe that works. If no such zone exists, the zone gets one shot each 90 min (blind_fallback_min), inside its daily water limit. Phase changes that use VWC wait for the probe.

**Probable causes**

- The entity that is mapped to the zone is a different reading of the same device: a raw count, a voltage or a temperature.
- The integration of the probe gives the VWC in an unusual unit.

**What to do**

- In Crop Steering → Rooms and setup, map the VWC entity of the probe in % or m³/m³.
- If the entity is the VWC entity, correct its unit in its own integration.

<a id="cs-504"></a>

### CS-504: Zone EC from bulk EC

*Warning · Notification*

**What it means.** The zone has pore EC probes and bulk EC probes, and the controller never mixes the two. No pore EC probe gives a usable reading, so the zone uses its bulk EC probes. Bulk EC reads lower than pore EC in the same slab.

**Effect on water.** Water continues. EC targets and flushes act on the lower bulk EC value until a pore EC probe reports again.

**Probable causes**

- A pore EC probe is offline, does not report, or reads out of range.
- A person set the EC type of a probe incorrectly: pore EC for a bulk EC probe, or bulk EC for a pore EC probe.

**What to do**

- CAUTION: Do not let the zone steer on bulk EC for a long time. The lower value can let salt build up in the substrate.
- Under Probes for the zone, check the pore EC probes that the reading does not use.
- In the EC Type setting of each probe, set the correct type: pore, bulk or unknown.

<a id="cs-505"></a>

### CS-505: Primary probe offline

*Warning · Notification*

**What it means.** The primary probe of the zone for VWC or EC gives no reading. The zone uses its other valid probes. The alert comes once, and clears when the primary probe reports again.

**Effect on water.** Water continues on the other probes of the zone.

**Probable causes**

- The cable of the probe is loose or cut, or its device has no power.
- The device of the probe is offline in Home Assistant.

**What to do**

- Check the cable and the power of the probe.
- Check its device in Home Assistant.
- Under Probes for the zone, choose a different primary probe, or none.

## Repairs cards (CS-6xx)

<a id="cs-601"></a>

### CS-601: Kill switch helper missing

*Critical · Repairs card*

**What it means.** The integration cannot find the kill switch that the controller uses for this room.

**Effect on water.** The room gets no shots while the kill switch is missing.

**Probable causes**

- The installation is from before the setup wizard, and a person deleted its helper input_boolean.f2_control_enabled.
- On a room that the setup wizard made: the controller started before the integration was configured, and it still reports its built-in name.

**What to do**

- CAUTION: Do not leave the room in this hold for a long time. The substrate dries out and the plants can wilt.
- On a room that the setup wizard made, do not make the helper. The kill switch of such a room is Engine Enabled.
- Upgrade the integration, and the card clears when the controller finds the room.
- Only for a room that uses input_boolean.f2_control_enabled, make that helper as a toggle in Settings → Devices & services → Helpers.
- Keep the helper off until you are ready to water.

<a id="cs-602"></a>

### CS-602: No controller heartbeat

*Warning · Repairs card*

**What it means.** The controller sends a heartbeat each minute. The integration has not received a heartbeat for more than 10 min. The integration only makes the settings, and the controller gives the water.

**Effect on water.** No automatic shots occur while the controller is stopped. The substrate can dry out.

**Probable causes**

- The controller app is not installed, is not started, or has stopped.
- The controller cannot connect to Home Assistant.
- A controller container is stopped, or Home Assistant does not accept its token.

**What to do**

- CAUTION: Do not leave the controller stopped for a long time. No automatic shots occur, and the substrate can dry out.
- Start the controller app.
- Read its log.
- For Home Assistant Container or Core, start the controller container.
- Read the container log.
- Check that Home Assistant accepts the token of the container.
- If you water by hand only, ignore this alert.

<a id="cs-603"></a>

### CS-603: Zone without a probe

*Warning · Repairs card*

**What it means.** No moisture probe is mapped to the zone, so the controller cannot steer it on VWC.

**Effect on water.** While the kill switch is on, the zone still gets shots. It gets the same shots as a zone with a probe that works, or one shot each 90 min inside its daily water limit.

**Probable causes**

- The zone was configured without a probe, or a person removed its probe.

**What to do**

- CAUTION: Do not water this zone by hand without a check. The controller continues to water it, and the substrate can flood.
- Map a moisture probe to the zone in Crop Steering → Rooms and setup.

<a id="cs-604"></a>

### CS-604: Combined moisture entity unavailable

*Warning · Repairs card*

**What it means.** The combined moisture entity of the zone reads unavailable, because the probe behind it does not report. The controller also raises CS-102 for the zone.

**Effect on water.** The same as for CS-102.

**Probable causes**

- The probe is offline, or a person renamed or removed it.

**What to do**

- Check the probe in Developer tools → States.
- Check the probe mapping of the zone in Crop Steering → Rooms and setup.

<a id="cs-605"></a>

### CS-605: Settings at unexpected entity IDs

*Warning · Repairs card*

**What it means.** The controller finds each setting by its exact entity ID. The settings on the card have different entity IDs. The controller uses its built-in values for them (CS-402).

**Effect on water.** Water continues on the built-in values, which can be wrong for the room.

**Probable causes**

- A person changed an entity ID in Settings.
- A person made the room after a HACS update and before a restart, while Home Assistant still ran the older integration.

**What to do**

- CAUTION: Do not set the kill switch to on until the entity IDs are correct. The built-in values can give too much or too little water.
- If the card lists one or two settings, restore each entity ID in Settings → Devices & services → Entities.
- If it lists almost all settings, delete the Crop Steering entry.
- Restart Home Assistant.
- Add the Crop Steering entry again. The integration does not rename an entity ID for you.

<a id="cs-606"></a>

### CS-606: Grow plan holds steering

*Critical · Repairs card*

**What it means.** The grow plan of the room holds the steering of its zones. The plan has an error, the controller cannot use it, or a zone of the plan has no schedule today. The card gives the reason.

**Effect on water.** Those zones get only the rescue shot, the watchdog shot and the minimum daily volume. A zone with no usable probe gets its timed shots. Usual steering waits until the hold clears.

**Probable causes**

- The plan has an error. For example, its zones are not the same as the zones of the room.
- The controller reports that it cannot use the plan.
- A zone of the plan has no schedule today.

**What to do**

- CAUTION: Do not leave the plan in this hold for many days. The zones get only safety shots, and the crop steering stops.
- Open Irrigation › Calendar in the Crop Steering sidebar.
- Read the reason.
- Correct the cause.
- If the error stays, disarm the plan and arm it again.

<a id="cs-607"></a>

### CS-607: Grow plan day not applied

*Warning · Repairs card*

**What it means.** At lights-on, the grow plan could not apply the new day. It keeps its last valid targets and tries again each minute. A plan that waits to start stays armed.

**Effect on water.** Water continues on the last valid targets.

**Probable causes**

- The controller did not report at lights-on.
- A probe gave an old reading at lights-on.
- The integration could not read the lights-on hour.

**What to do**

- Usually, no action is necessary, because the alert clears when the cause stops.
- If it stays, make sure that the controller runs.
- Make sure that the probes report.

<a id="cs-608"></a>

### CS-608: Stock tanks low

*Warning · Repairs card*

**What it means.** One or more stock tanks of the room are at or below their low mark. Each batch takes a dose from each stock tank.

**Effect on water.** Water continues. A batch from an empty stock tank does not get enough of that nutrient.

**Probable causes**

- The batches used the stock until it reached its low mark.
- A person refilled a tank but did not press Refilled, so the tank still shows its old level.

**What to do**

- WARNING: Wear gloves and eye protection when you touch the batch tank or the stock tanks. Concentrated nutrients and pH adjusters can injure the skin and the eyes.
- CAUTION: Do not make a batch from an empty stock tank. The batch then does not have enough of that nutrient.
- Refill the stock tank.
- Press Refilled on Crop Steering → Stock tanks.
- Alternatively, set the level that you read on the tank. The card clears when each tank is above its low mark.

<a id="cs-609"></a>

### CS-609: Second controller for room

*Warning · Notification*

**What it means.** Each controller writes its ID in the room heartbeat each minute. This controller found a heartbeat from a different controller, or from an old controller with no ID, less than 3 min ago.

**Effect on water.** This controller does not water or dose the room, and does not change its settings, until no other controller writes for 3 min in sequence. It refuses new dose and batch requests in that time. A stop still stops the pumps, and a dose or batch in progress continues to its end.

**Probable causes**

- This is the first start after an upgrade from a version before this check. The last heartbeat of the old version has no ID. The alert clears in about 3 min.
- Two controllers run this room: a controller app and a controller container, or two apps.
- A controller from before this check still runs. It never holds, so only this controller holds.

**What to do**

- CAUTION: Do not leave the room in this hold for a long time. The substrate dries out and the plants can wilt.
- After an upgrade, wait 3 min, and no other action is necessary.
- If the alert stays, stop the controller that you do not use.
- Remove that controller.
- Only one controller must run a room.

<a id="cs-610"></a>

### CS-610: Engine Enabled not kill switch

*Warning · Repairs card*

**What it means.** Each room has one kill switch, which must be on before the room gets water. The controller reports that the kill switch of this room is a different entity. Engine Enabled set to off does not stop water in this room.

**Effect on water.** Water continues under the kill switch that the card names. Engine Enabled does not start or stop the water.

**Probable causes**

- The installation is from before the setup wizard. Its kill switch is the entity in the enable_flag option of the controller (input_boolean.f2_control_enabled by default). It also has an Engine Enabled switch.
- The setup of the room, or the enable_flag option, names a different kill switch on purpose.

**What to do**

- CAUTION: Do not use Engine Enabled to stop water in this room. It does not stop the shots, and the substrate can flood.
- To stop water in this room, set the kill switch that the card names to off.
- Change each automation that sets Engine Enabled to off, so that it uses that kill switch.
- To make Engine Enabled the kill switch, follow "Moving a room's kill switch" in docs/INSTALL.md.

<a id="cs-611"></a>

### CS-611: Settings above zone limit

*Warning · Repairs card*

**What it means.** The limits of the daily water and the maximum shot length come from the size of each zone: its plants, substrate volume and dripper flow. These settings were above their limit before the limit started, so the integration keeps them as they are.

**Effect on water.** Water continues as before. The controller uses the settings as they are.

**Probable causes**

- A person increased a setting for a larger zone than the zone in the setup now.
- The plant count, the litres for each plant or the dripper flow of a zone is smaller than in the real zone.

**What to do**

- If the zone size is wrong, correct it in Rooms and setup, and the limit changes with it.
- If the size is correct, decrease the setting to its limit at the next change. The card clears when each setting is inside its limit.

<a id="cs-613"></a>

### CS-613: Deprecated feature in use

*Warning · Repairs card*

**What it means.** Something called a service or chose a select that the integration will remove. The Repairs card names it, says what to use instead and gives the release that removes it.

**Effect on water.** Water continues. The service or the select works as before until it is removed.

**Probable causes**

- A person, an automation or a script called apply_recipe or save_recipe, or chose a value in the Recipe stage or Irrigation phase select.

**What to do**

- Open the card and read what it names and what to use instead.
- Change the automation or script that makes the call. For a stage of the grow, set the targets of the room in the dashboard or use a grow plan. To move one zone to a phase, use its Set phase select.
- The card does not come back until Home Assistant restarts.

## AI assistant (CS-7xx)

<a id="cs-701"></a>

### CS-701: No water at the zone

*Warning · Notification*

**What it means.** The shot judge of the AI assistant found no sign of water at the zone for 2 shots in sequence. The VWC did not increase, but the controller counted the litres.

**Effect on water.** Water continues as usual. The litres that the controller counts can be more than the litres that the zone got, so the substrate can dry out.

**Probable causes**

- A hand valve is closed, a line is kinked or blocked, or the drippers are blocked.
- A tank hold or a dose hold closed the feed path during the shot.
- The zone valve does not open, but it reads on.

**What to do**

- CAUTION: Do the catch test soon. A blocked line can leave the zone dry while the controller counts water.
- During the next shot, check the zone valve, the line and the drippers.
- Do a catch test on one dripper.

<a id="cs-702"></a>

### CS-702: Unusual water for each plant

*Information · Notification*

**What it means.** Today the water for each plant in this zone is less than 70% or more than 140% of the other zones of the room. The zones judge of the AI assistant gives the probable cause in the alert.

**Effect on water.** Water continues as usual. This alert is advice only.

**Probable causes**

- The plants drink less or more.
- The probe is in a wetter or drier spot than the roots.
- A valve, a dripper or a line has a problem.
- The shots do not go into the substrate.

**What to do**

- Compare the settings and the plants of the zone with the other zones.
- Check the position of the probe.
- Do a catch test on this zone and on one adjacent zone.

<a id="cs-703"></a>

### CS-703: Overnight probe fault suspected

*Warning · Notification*

**What it means.** Overnight, the VWC of the zone falls toward the rescue floor. The night judge of the AI assistant reads this as a probe fault, not as dryback.

**Effect on water.** Water continues. The rescue shot still runs as usual.

**Probable causes**

- The probe reading changed suddenly in one step, or it stopped.
- A person or an object moved the probe from its position.

**What to do**

- Check the probe in the morning, before the ramp starts.

<a id="cs-704"></a>

### CS-704: Probe set aside by AI

*Warning · Notification*

**What it means.** The AI assistant judged twice in sequence that the moisture probe does not follow the substrate, and the check of the controller agreed. The probe can be stuck, out of the block, on the wrong zone, or it can drift.

**Effect on water.** The zone continues without the probe, as for a probe that does not report. It gets the same shots as a zone with a probe that works, or timed shots inside its daily limit. The probe counts again when the AI assistant judges that it follows the substrate.

**Probable causes**

- The probe is partly out of the block, or it is in a channel.
- The probe is mapped to the wrong zone.
- The probe does not measure, but it continues to report.

**What to do**

- Check the position and the wiring of the probe.
- In Rooms and setup, check the zone that the probe is mapped to.

<a id="cs-705"></a>

### CS-705: Zone outside stage arc

*Information · Notification*

**What it means.** Each day, the stage judge of the AI assistant compares the zone with the stage arc for this flower week. It examines the steering mode, the dryback and the pore EC. The alert names what is outside the arc and what the doctrine says.

**Effect on water.** Water continues as usual. This alert is advice only, and the controller changes nothing.

**Probable causes**

- The steering mode or the settings of the zone are for a different growth stage.
- The overnight dryback or the pore EC moved outside the band of the growth stage.
- The signs for the next growth stage are present.

**What to do**

- Compare the settings of the zone with the stage arc.
- If the growth stage has changed, change the settings.
- Check that ai_flower_start has the correct flip date.

<a id="cs-706"></a>

### CS-706: AI call budget almost used

*Warning · Notification*

**What it means.** The AI assistant has used the warning share of its daily call budget, 80% by default, for all rooms. When it uses the full budget, the controller does not ask it again until midnight.

**Effect on water.** Water continues as usual. After the budget is spent, the engine rules decide each zone until midnight.

**Probable causes**

- The budget is too low for the number of zones or judges.
- The AI assistant was frequently not sure today, and it asked again many times.
- The budget option is still at an older, lower value.

**What to do**

- Increase ai_daily_calls in the options of the controller.
- Restart the controller.
- Read reasks_today and errors_today on the AI assistant sensor to find what used the calls.

<a id="cs-707"></a>

### CS-707: Stricter gate for a judge

*Warning · Notification*

**What it means.** Some calls in sequence of one judge for this zone, 3 by default, were wrong when the controller checked them. Until 2 calls in sequence are correct, the judge acts only when its two questions agree at 0.8 or more. A second look must also give the same answer.

**Effect on water.** Water continues. When the judge is not sure enough, the engine rules act, as they do without the AI assistant.

**Probable causes**

- A probe or a sensor gives incorrect data to the judge.
- The judge has not seen the conditions before, for example a new growth stage or a changed room.
- A setting works against the decisions of the judge.

**What to do**

- Read the AI log of the zone on the dashboard.
- Check the probe and the settings of the zone.

<a id="cs-708"></a>

### CS-708: AI budget used

*Warning · Notification*

**What it means.** The AI assistant has spent its AI budget (anthropic_daily_budget_usd, US$1.00 by default) for this grow-day. The controller does not ask it again until the next lights-on.

**Effect on water.** Water continues. The engine rules, with the automatic setpoints, decide each zone until the next lights-on.

**Probable causes**

- The budget is too low for the number of rooms and zones.
- The AI assistant was frequently not sure today, and it asked again many times.
- The budget is 0. The AI assistant then never asks.

**What to do**

- Increase anthropic_daily_budget_usd in the options of the controller.
- Restart the controller.
- Check the projected cost on the AI assistant panel to see if the budget is enough for a usual day.

<a id="cs-709"></a>

### CS-709: AI assistant not available

*Warning · Notification*

**What it means.** The AI service refused the API key, does not know the selected model, or refused some requests in sequence. The AI assistant has stopped its questions.

**Effect on water.** Water continues on the engine rules. After refused requests, the AI assistant tries again after 1 h. After a refused key or model, it tries again after a controller restart.

**Probable causes**

- The Anthropic API key is revoked or incorrect, or it has no credit.
- The model in anthropic_model is not a model that this release has a price for.
- Anthropic refuses requests for a period.

**What to do**

- Check the API key in the console of the AI provider.
- Put a valid key in anthropic_api_key.
- Set anthropic_model to claude-haiku-5-5, the default.
- Restart the controller.
- Read the state of the AI assistant panel and the controller log.

<a id="cs-710"></a>

### CS-710: Possible water bypass

*Warning · Notification*

**What it means.** Shots on this zone make the probe increase and then fall back quickly. Or the zone uses less than 40% of the typical water for each plant in the room. The 40% check counts only when the room uses a tenth of the substrate volume of a plant each day, or more. The channel judge of the AI assistant then gives the probable cause.

**Effect on water.** Water continues as usual. This alert is advice only. More water does not correct water that does not go into the substrate.

**Probable causes**

- The water flows down past the probe, or through the block and out of the drain, and does not wet the block.
- A block is dry and hard, or the drippers are not on the block.
- A dripper is slow, a valve is partly closed, or a line is restricted.
- The plants use less water than the adjacent plants.

**What to do**

- Do a catch test on some drippers of the zone.
- Make sure that the drippers sit in the blocks.
- Make sure that the water wets the full block.
- Make sure that the probe is firm in a typical spot.

<a id="cs-711"></a>

### CS-711: AI feed change proposal

*Information · Notification*

**What it means.** In a room with a feed EC sensor, the AI assistant examines the feed once each grow-day, 1 h after lights-on. It compares the feed EC and feed pH with their bands, and the pore EC of each zone with its target. When its two questions agree firmly, it proposes a feed change or a check.

**Effect on water.** The water and the dose do not change. The AI assistant never writes a feed, dose or other value. A person decides.

**Probable causes**

- Across the room, the pore EC is above or below the targets of the zones, while the feed is in its band.
- The feed pH is outside its band.
- The feed EC is outside its band, gives no reading, or is not the EC that the recipe makes.

**What to do**

- Read the proposal and the pore EC of each zone.
- Decide if the feed must change.
- If the card asks for it, check the dosing system and the source water before you change the recipe.

<a id="cs-712"></a>

### CS-712: First AI route removed

*Information · Notification*

**What it means.** The options of the controller still name the first AI route of the AI assistant, or keep its Cloudflare or TypeSafe settings. This release removed that route. An installation that used it now uses Claude when it has an Anthropic API key, with every judge, and the rules of the controller when it has none.

**Effect on water.** The water does not change. Claude judges the decisions inside the same safety limits, or the engine rules water the room.

**Probable causes**

- The installation was upgraded from a release that used the first AI route.

**What to do**

- To use the AI assistant, set brain_provider to claude_haiku and add an Anthropic API key.
- Remove the old Cloudflare and TypeSafe options. The controller does not use them.
- To stop the AI assistant, set brain_provider to rules.

<a id="cs-713"></a>

### CS-713: Room differs from grow plan

*Warning · Notification*

**What it means.** The controller compared the grow plan with what the room does, and found a difference. Examples are a plan day not applied, a plan not armed, a manual setting change, or a phase that did not change. The card says which difference and what to do.

**Effect on water.** Water continues on the targets in force, and the card only reports. The controller never writes over a setting that a person changed by hand.

**Probable causes**

- The probe of a zone stopped reporting, and the zone stays on the targets of an earlier day.
- A person saved the plan but did not arm it, or the plan is armed and waits for a reading.
- The last day in the schedule of the plan is near.
- A person or an automation changed a setting while the plan runs.
- The steering select or the lights hours do not agree with the plan.
- The controller has a fault (this is rare).

**What to do**

- Follow the suggestion on the card.
- If the card names a probe, repair the probe or remove its mapping.
- Arm, extend or disarm the plan as the card shows.
- Make a change in the days of the plan, not in the setting.
- Set the steering select to agree with the plan.
- Check the lights hours.
- If a phase did not change, send the controller log.

## Dosing (CS-8xx)

<a id="cs-801"></a>

### CS-801: Dosing pump overrun

*Critical · Notification*

**What it means.** A dose ran past its deadline. The deadline is 1.25 times the expected dose time plus 20 s, and 21 min at most. The controller set the pump power to off and read it back.

**Effect on water.** The batch tank can contain more nutrient than requested. A single dose does not stop the water, unless the pump power does not read off. Then the room gets no shots until it reads off. In a batch, the batch also stops (CS-806).

**Probable causes**

- The firmware of the pump did not stop the motor at the given volume.
- The flow calibration of the pump (mL/s) is much higher than the real flow, so the controller expected the end of the dose sooner.
- The dose sensor of the pump continued to show a dose after the motor stopped.

**What to do**

- WARNING: Isolate the electrical power before you touch a pump, a valve or its wiring. Water near mains power can cause an electric shock.
- CAUTION: Do not use the batch tank before you measure its EC. Too much nutrient can damage the roots.
- Measure the EC of the batch tank before you use it.
- Check the firmware and the dose sensor of the pump.
- Calibrate the flow of the pump again.
- If the pump power does not read off, stop the pump at the device or at its socket.
- When the pump is repaired, set its power switch to on again.

<a id="cs-802"></a>

### CS-802: Dose not confirmed

*Warning · Notification*

**What it means.** The controller started a dose but could not confirm it. The dose sensor of the pump did not show a dose in time, or it read unavailable or unknown during the dose. Alternatively, the dose ended in less than half its expected time.

**Effect on water.** For a dose that is not confirmed, the controller does not know the volume, and does not subtract it from the stock tank. For a dose that ended early, it subtracts the volume that ran. A single dose does not stop the water, but in a batch the batch also stops (CS-806).

**Probable causes**

- The pump is offline, or its start button or script did nothing.
- The dose sensor shows a dose in a form that the setup does not know. For example, the state of a text sensor does not start with the dosing prefix.
- The firmware of the pump refused the given volume.
- The pump restarted or went off the network during the dose.
- The firmware of the pump stopped the dose early, or its flow calibration is much lower than the real flow.

**What to do**

- CAUTION: Do not dose again before you measure the EC of the batch tank. Some of the dose can already be in the tank.
- Make sure that the pump is online.
- Examine the dose sensor during a dose.
- Set the dosing prefix to agree with the sensor state.
- Measure the EC of the batch tank before the next dose.

<a id="cs-803"></a>

### CS-803: Dose interrupted by restart

*Warning · Notification*

**What it means.** The controller stopped during a dose or a batch, or it could not read its dose record (dosing_state.json) at start. At the next start, it holds the water of the rooms that the dose or batch held. It sets all the dosing hardware of the room to off, and repeats this until each device reads off.

**Effect on water.** The held rooms get no shots until all the dosing hardware reads off. The controller never continues an interrupted dose or batch. The alert comes again each 30 min while a device does not read off.

**Probable causes**

- A person upgraded, restarted or stopped the controller during a dose or a batch.
- Home Assistant or the host restarted.
- The controller could not read dosing_state.json at start. It keeps the file as dosing_state.json.bad.

**What to do**

- WARNING: Wear gloves and eye protection when you dose by hand. Concentrated nutrients and pH adjusters can injure the skin and the eyes.
- CAUTION: Do not dose the full volume again. The tank already contains part of the dose, and too much nutrient can damage the roots.
- Examine the batch tank, because it contains what the controller dosed before the stop.
- Read the dosing history.
- Dose the remaining volume by hand, or make a new batch.
- Upgrade or restart the controller only between batches.
- If a device stays unavailable, connect it again or stop it at its socket.

<a id="cs-804"></a>

### CS-804: Batch tank fill failure

*Warning · Notification*

**What it means.** A batch could not fill the tank. The fill valve did not read on within 10 s, or the full sensor gave no usable reading. Or the tank did not read full before the fill timeout. The controller closed the fill valve, read it back and stopped the batch (CS-806).

**Effect on water.** The rooms that the batch held get water again. The fill valve is closed.

**Probable causes**

- The water supply is off or slow, or the fill valve did not open.
- The full sensor is stuck or offline, or it reports a state that is not the full state of the setup.
- The fill timeout is shorter than the time of a fill.
- The fill valve is offline, or its relay did not switch.
- The full sensor went offline.

**What to do**

- CAUTION: Make sure that the fill valve is closed. A fill valve that stays open can overflow the tank.
- Check the water supply.
- Check the fill valve.
- Check what the full sensor shows when the tank is full.
- If a fill takes longer than the fill timeout, increase the fill timeout in the dosing setup.

<a id="cs-805"></a>

### CS-805: Mix pump start failure

*Warning · Notification*

**What it means.** A batch opened the mix valves and started the mix pump. The pump did not read on, or its power sensor did not show the minimum power within 20 s. The batch stopped (CS-806).

**Effect on water.** The rooms that the batch held get water again when its hardware reads off.

**Probable causes**

- The mix pump did not start, or its power plug did not switch.
- The power sensor is offline, or it reports slowly.
- The minimum power is set above the power of the pump.

**What to do**

- WARNING: Isolate the electrical power before you touch a pump, a valve or its wiring. Water near mains power can cause an electric shock.
- Check the mix pump and its power plug.
- Read the power sensor while the pump runs.
- Set the minimum power below the power of the pump.
- To skip the power check, set the minimum power to 0.

<a id="cs-806"></a>

### CS-806: Stopped batch or dose

*Warning · Notification*

**What it means.** A batch stopped before its end, or a dose needs a check. The cause can be a person, a failed step, a device that did not read off, or the batch watchdog. The alert names the step, the reason and what the controller dosed.

**Effect on water.** The controller sets all the dosing pumps, the fill valve, the mix pump and the mix valves to off. The rooms that the batch held get water again when its hardware and its hold read off. The alert comes again each 30 min until then.

**Probable causes**

- A person stopped the batch.
- A fill, a mix or a dose failed.
- A switch of the batch, or of a room that the batch holds, did not read off.
- The volume number of a pump did not go back to its earlier value.
- The filled-at entity or the hold entity did not accept its command.
- The controller has an error. Its log names the error.

**What to do**

- WARNING: Wear gloves and eye protection when you touch the batch tank or the stock tanks. Concentrated nutrients and pH adjusters can injure the skin and the eyes.
- CAUTION: Do not make a full new batch before you examine the tank. The tank can already contain part of the dose.
- Examine the batch tank before you make a new batch.
- Read what the controller dosed before the stop.
- Correct the cause that the alert names.
- Make the batch again.
- If the alert says that a volume number was not restored, set it by hand before the next batch.
- If the alert names a controller error, read the controller log.

<a id="cs-807"></a>

### CS-807: Stock draw not recorded

*Warning · Notification*

**What it means.** A dose took nutrient from a stock tank, but Home Assistant did not record the draw. The tank is not linked to the room, Home Assistant refused the draw, or 24 h passed. The dosing history of the room keeps the draw.

**Effect on water.** Water continues as usual. The level of the stock tank shows more than the tank contains.

**Probable causes**

- A person removed the stock tank after the pump was linked to it.
- The stock service of Crop Steering refused the call, or it was not available at that time (an old integration, or a reload).
- The controller could not connect to Home Assistant for 24 h.

**What to do**

- In Stock tanks, use Set level to enter the real level of the tank.
- Check the stock tank of the pump in the dosing setup.

<a id="cs-808"></a>

### CS-808: Batch mix outside band

*Warning · Notification*

**What it means.** After the mix of a batch stopped, the controller waited 5 min and read the tank with the feed EC and feed pH probes. A reading was outside the EC or pH band of the room, or a probe gave no usable reading. The controller does not mark the batch good.

**Effect on water.** The mix check never holds the water. The source-water gate holds the water by itself when the feed probe reads outside its band. The controller refuses an automatic batch until a batch made by hand passes the check.

**Probable causes**

- A recipe quantity, a stock tank or a dosing pump is incorrect.
- A fill gave too much or too little water.
- The feed EC or feed pH band is for a different growth stage.
- A feed probe is offline, needs calibration, or reports in ppm.

**What to do**

- WARNING: Wear gloves and eye protection when you touch the batch tank or the stock tanks. Concentrated nutrients and pH adjusters can injure the skin and the eyes.
- CAUTION: Correct the batch before you water from it. A wrong feed EC or feed pH can damage the roots.
- Measure the tank with a hand-held meter.
- Correct the tank with single doses or fresh water.
- Check the recipe, the stock tanks and the EC and pH bands.
- Calibrate the feed probe, or connect it again.
- Set the probe to report mS/cm or µS/cm, not ppm.
- Make the next batch by hand.

<a id="cs-809"></a>

### CS-809: Tank pH not corrected

*Critical · Notification*

**What it means.** pH auto-correct is on, and the batch tank read outside the feed pH band of the room. A correction did not bring the tank into the band: a dose did not move the pH, the pH went past the other side of the band, the probe could not be read after the mix, the doses were not enough, or the correction stopped. Or the controller could not start a correction (for example no pump has the pH role, there is no mixing pump, or the doses of the day are used).

**Effect on water.** The source-water gate holds the shots while the feed pH is outside its band. After a failed correction, pH auto-correct is locked for this tank: it doses no more until a person switches it off and on again, or the tank is filled again.

**Probable causes**

- The pH probe needs calibration, or it is dirty or offline.
- The pH pump is empty, blocked, or not calibrated.
- The pH adjuster is too weak or too strong for the dose size.
- No dosing pump has the pH up or pH down role, or the tank has no mixing pump.

**What to do**

- WARNING: Wear gloves and eye protection when you touch the batch tank or a pH adjuster. pH adjusters can injure the skin and the eyes.
- Measure the tank with a hand-held meter, and correct it by hand.
- Calibrate or clean the pH probe.
- Check the pH pump, its stock and its calibration.
- Change the dose length or the number of doses in the pH auto-correct settings of the room.
- Switch pH auto-correct off and on again to unlock it.

<a id="cs-810"></a>

### CS-810: Lights dimmed on dry substrate

*Warning · Notification*

**What it means.** Dimming on dry substrate is on. A zone read under the dry floor with the lights on, and the controller dimmed the light of the room. Or the controller set the light back, or another controller changed the light while it was dimmed, so the controller no longer dims or restores it.

**Effect on water.** The alert does not change the water. A dimmed light slows the drying of the substrate. The controller never switches a light off or on, and never dims below 30%.

**Probable causes**

- A hold stops the shots of a zone, the tank is empty, or a dripper is blocked.
- The dry floor is too high for the substrate.
- Another automation or a person changed the light while it was dimmed.

**What to do**

- Find out why the zone is dry, and water it.
- Check the brightness of the light.
- Change the dry floor, the dim level or the delay in the settings of the room, or switch dimming off.

<a id="cs-811"></a>

### CS-811: Light dimmed too long

*Critical · Notification*

**What it means.** The light of the room stayed dimmed for the longest time that you set (4 h by default), and the controller set it back. Or the light did not come back to its brightness when the controller asked.

**Effect on water.** The alert does not change the water. The zone that was dry is probably still dry.

**Probable causes**

- A hold stops the shots of a zone for a long time.
- The light is offline, or does not accept a brightness.

**What to do**

- CAUTION: Do not ignore this alert. The substrate of the zone is dry.
- Find out why the zone is dry, and water it by hand if needed.
- Check the light, and set its brightness by hand.

## Reservoir and feed (CS-9xx)

<a id="cs-901"></a>

### CS-901: Tank at minimum level

*Critical · Notification*

**What it means.** The tank level of this room is 8% or less, or its low float switch reads low. This check works only when a tank level entity is mapped in Rooms and setup.

**Effect on water.** The controller holds each zone of the room, so the pump does not run dry. Water starts again when the tank is at 12% or more and the float switch does not read low.

**Probable causes**

- The tank became empty, because nobody refilled it in time. CS-903 tells you before the refill is necessary.
- A fill did not occur, or it stopped early.
- The full and empty distances of the tank are incorrect, so the level reads lower than the real level.

**What to do**

- CAUTION: Do not start the pump by hand while the tank is at its minimum. The pump can run dry and break.
- Refill the tank.
- Check the full and empty distances of the tank in Crop Steering → Rooms and setup.
- Check the low state of the float switch.

<a id="cs-902"></a>

### CS-902: Tank level not readable

*Critical · Notification*

**What it means.** The tank level of this room gives no usable reading, or the distance sensor seems stuck. The shots took enough water to decrease the level, but the reading did not change. The controller cannot know how much water remains.

**Effect on water.** The controller holds each zone of the room until the level reads again, or until a stuck sensor moves. This hold prevents a pump that runs dry.

**Probable causes**

- The sensor has no power, or it lost its connection to Home Assistant.
- The distance sensor is stuck: an object is in its beam, it has condensation, or its reading stays high.

**What to do**

- CAUTION: Do not remove the tank level only to start the water again. Without a level, the pump can run dry.
- Check the sensor, its power and its position.
- Make sure that Home Assistant shows a reading.
- Remove condensation or objects from the sensor beam.
- If the room must water without a tank level, remove the level entity in Crop Steering → Rooms and setup.

<a id="cs-903"></a>

### CS-903: Refill needed before next shots

*Warning · Notification*

**What it means.** One more set of shots, the last shot of each zone, takes the tank to its 8% minimum or below. The controller calculates this from the litres for each 1% that the tank showed, and needs a distance sensor for it.

**Effect on water.** Water continues. A shot that takes the tank to its minimum waits until you refill the tank. The card clears when the tank has enough water for a full set of shots.

**Probable causes**

- The tank level decreases, as it does between refills.

**What to do**

- Refill the tank, or start a batch.

<a id="cs-904"></a>

### CS-904: Tank above full mark

*Warning · Notification*

**What it means.** The tank level reads 102% or more of its full distance.

**Effect on water.** Water continues. The controller closes the fill valve of a batch, and does not open it until the level reads 98% or less.

**Probable causes**

- The fill valve did not close, or it leaks.
- The full distance of the tank is set too far down, so a full tank reads more than 100%.

**What to do**

- CAUTION: Examine the tank and the fill valve now. A fill valve that leaks can overflow the tank.
- Make sure that the fill valve closes fully.
- Check the full distance of the tank in Crop Steering → Rooms and setup.

<a id="cs-905"></a>

### CS-905: Estimated tank level low

*Warning · Notification*

**What it means.** The room has no tank level sensor, and a Tank size (estimate) above 0. From the litres that the shots used since the tank was last filled, the tank is at or below the room setting Estimated tank low alert (20% by default). The litres come from the dripper flow settings, not from a measurement.

**Effect on water.** The alert does not change the water. The estimate never holds a shot.

**Probable causes**

- The tank level decreases, as it does between refills.
- The tank was filled and Tank filled was not pressed.
- The dripper flow settings are higher than the real flow.

**What to do**

- Refill the tank, then press Tank filled.
- If the estimate is often wrong, check the dripper flow settings, or map a tank level sensor in Rooms and setup.

<a id="cs-906"></a>

### CS-906: Batch tank low

*Information · Notification*

**What it means.** The batch tank of the room read at or below its refill reminder level (remind_pct) 3 times, 1 min apart. Nothing refills the tank automatically.

**Effect on water.** Water continues as usual. The reminder clears when the level is 5 points above the reminder level. It comes again each day while the level stays low.

**Probable causes**

- The shots of the room took water from the batch tank since the last fill.

**What to do**

- Refill the tank by hand, or make a batch.
- To stop the reminders, set the refill reminder to 0% in the dosing setup.

<a id="cs-907"></a>

### CS-907: EC flushing off, feed EC unknown

*Warning · Notification*

**What it means.** The room has no feed EC probe, and the feed recipe in use declares no feed EC. The controller does not know the EC of the feed water.

**Effect on water.** The zones get water on their VWC only. The controller does not flush high pore EC and does not hold a zone for high EC, because it cannot tell if the feed can decrease the pore EC. The alert comes once and goes when the room gets a feed EC.

**Probable causes**

- No feed EC probe is set for the room in the controller app options (feed_ec_sensor).
- The feed recipe in use has no EC, or the room has no dosing setup.

**What to do**

- CAUTION: Do not ignore this alert for many days. Salt can build up in the substrate when the controller cannot flush.
- Set the feed EC on the feed recipe in use (Crop Steering → Dosing), or set a feed EC probe in the controller app options.
