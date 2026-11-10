# First-run setup

Do this after you install both parts of Crop Steering ([Install, upgrade and roll back](INSTALL.md)). Keep the "Watering" switch of each room off until this procedure tells you to set it to on.

This software operates real pumps and valves on live plants. It operates them when nobody is in the room.

> **WARNING:** Do not use the software as an emergency stop. Use the physical shutdown procedure of your installation. The "Watering" switch and the "Room in use" control do not isolate the electrical power.

> **WARNING:** Isolate the electrical power before you do work on a pump, a valve or the wiring. Water and mains power near each other can cause an electric shock.

> **CAUTION:** Install valves that close when the power is lost. Install a float switch or a timer that can stop a pump without the software. The software does not replace these physical safety devices.

> **CAUTION:** Keep the "Watering" switch off until each probe and each switch of the room is correct. A wrong valve or a wrong probe can flood a zone or let it dry out.

## Examine the installation

Do these checks with the kill switches (the "Watering" switch of each room) still off:

1. Make sure that each room opens in the sidebar.
2. Make sure that the controller heartbeat of the room is current.

## Set up a room

A Home Assistant administrator does the setup in **Equipment › Setup: pumps & valves**. Pair the devices in Home Assistant first. The setup maps entities that exist. It does not pair devices.

1. Select a room, or select **Add room**. Give the room a clear name.
2. Tell the setup how the room is plumbed: zone valves only, or a pump and valves. The setup does not guess from empty fields.
3. Map the room pump and the main-line valve, if the room has them.
4. Map the valve of each zone. A valve must read closed before you save.
5. Select one or more VWC probes and EC probes for each zone.
6. Enter the plant count of each zone.
7. Enter the substrate volume for each plant, in litres. You can also select a pot or a rockwool preset.
8. Enter the number of drippers for each plant.
9. Enter the flow of each dripper, in litres per hour. Use the value from the data sheet of the dripper for now. You measure the flow with the catch test in [Before the first watering](#before-the-first-watering).
10. Map the optional room equipment, the tank displays and the feed probes.
11. Make sure that the kill switch and the equipment of the room are off.
12. Select **Review configuration**, then **Save configuration**.
13. Wait for **Mapping acknowledged**. A saved setup and an accepted setup are different states.
14. Examine the room's Today page. Make sure that **Equipment › Probes & offsets** shows the correct entities and units.
15. Set the lights-on and lights-off hours of the room.
16. Examine the water limits, the shot sizes and the rescue floor of each zone.

The setup checks the entity types, the units, duplicate valves and revision conflicts. It also checks that the equipment of the room reads off.

The [user guide](USER_GUIDE.md#setup-pumps--valves) gives each field of the setup.

## Before the first watering

A watering (the dashboard calls it a shot) switches the pump, the main line and one zone valve in order, then closes them and counts the water.

The controller gives a test shot only while the "Watering" switch of the room is on. While that switch is on, the controller can also start automatic shots. To do a test shot with no automatic shots, set each zone to **Off** first. Do the three procedures below in order.

### 1. Stop the automatic shots in each zone

1. Open **Irrigation › Timer programs › Irrigation mode**.
2. Select **Off** for a zone. The page shows "Zone N gets no shots at all, rescue shots included."
3. Select the button **Switch … to Off**. The button shows the name of the zone. The first selection only shows what will change. This button sends the change.
4. Make sure that the zone shows "Off: no shots at all, rescue shots included."
5. Do steps 2 to 4 for each zone of the room.

> **CAUTION:** A zone that is set to **Off** gets no automatic shots. This includes the rescue shots. The controller sends no alert for a zone that is set to **Off**. If plants are in the zone, give them water by hand until you set the zone to **Steering** or **Timer**.

### 2. Do a test shot and a catch test in each zone

Do this procedure for one zone at a time. You need a measuring cup and a stopwatch.

1. Put each dripper of the zone in the substrate or in a container.
2. Put one dripper in the measuring cup.
3. In Home Assistant, open the device of the zone. Set **Zone N manual shot length** to 60 seconds or more. The default of 10 seconds is too short to measure accurately.
4. Set the "Watering" switch in the top bar to on. Examine the review, then confirm it.
5. Select **Test shot** for the zone. On a new room, the button is **Test shot · …**, with the name of the zone, in **Equipment › Setup: pumps & valves**, in the **Configure this room** panel. On a room that is already set up, the button is on the zone page, in the **Hardware** panel. Examine the review, then confirm it. The zone page shows that panel only while the switch **Hardware panel on zone pages** of the room is on. An administrator sets that switch in Home Assistant.
6. Wait for the shot. The controller usually starts it in approximately one minute. If no shot starts in 10 minutes, select **Test shot** again.
7. Start the stopwatch when water comes out of the dripper. Stop it when the water stops.
8. Make sure that water came out of the drippers of this zone only.
9. Write down the time on the stopwatch, in seconds, and the water in the cup, in millilitres. Do not use the manual shot length as the time: a limit of the room or the zone can stop the shot early.
10. On a new room, answer **Yes** to "Did water come out?" in the **Configure this room** panel.

If no water comes out, open the zone page. **Why / next action** shows the check that holds the shot. **All next-shot conditions** shows each check.

> **CAUTION:** Do a catch test before the first automatic shot. The controller calculates the water totals on the dashboard from the settings and the valve time. Only a catch test or a flow meter shows the water that the plants got.

### 3. Save the measured dripper flow

The setup does not save a change of the dripper flow while the "Watering" switch is on.

If the room shares a pump or a main-line valve with a different room, the setup also refuses the save while the "Watering" switch of that room is on. Make sure that no plants in that room need water. Then set that switch to off too. Set it to on again after step 6.

1. Set the "Watering" switch in the top bar to off.
2. Open **Equipment › Setup: pumps & valves**.
3. For each zone, open **Calculate dripper flow**. Enter the time and the millilitres that you wrote down.
4. Use the result as the dripper flow of the zone.
5. Select **Review configuration**, then **Save configuration**.
6. Wait for **Mapping acknowledged**. This can take 5 minutes. Do not set the "Watering" switch to on before it shows. If you do, the controller gives no shots (alert CS-201).
7. On a new room, select **Switch on** in the **Configure this room** panel. This marks the setup as complete. It does not start the water.

## Turn automatic watering on

1. Set the "Watering" switch in the top bar to on. Each zone is still set to **Off**, so no automatic shot starts.
2. Open **Irrigation › Timer programs › Irrigation mode**.
3. Select **Steering** for one zone, then select the button **Switch … to Steering**. If a timer program waters the zone, use **Timer**.
4. Look at the first automatic shots of the zone. Each shot shows on the day chart of the zone page.
5. Do steps 3 and 4 for each other zone. A zone that stays on **Off** gets no water and sends no alert.

> **CAUTION:** When the room is off or the "Watering" switch is off, the controller gives no shots. This includes the rescue shots. Make sure that no plants need water before you set either switch to off.

**Next →** [User guide](USER_GUIDE.md): each page of the dashboard and a daily routine.
