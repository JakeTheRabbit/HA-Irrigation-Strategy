# First-run setup

Do this after you install both parts of Crop Steering ([Install, upgrade and roll back](INSTALL.md)). Keep the "Watering" switch of each room off until the last step.

This software operates real pumps and valves on live plants. It operates them when nobody is in the room.

> **WARNING:** Do not use the software as an emergency stop. Use the physical shutdown procedure of your installation. The "Watering" switch and the "Room in use" control do not isolate the electrical power.

> **WARNING:** Isolate the electrical power before you do work on a pump, a valve or the wiring. Water and mains power near each other can cause an electric shock.

> **CAUTION:** Install valves that close when the power is lost. Install a float switch or a timer that can stop a pump without the software. The software does not replace these physical safety devices.

> **CAUTION:** Keep the "Watering" switch off until each probe and each switch of the room is correct. A wrong valve or a wrong probe can flood a zone or let it dry out.

## Examine the installation

Do these checks with the kill switches (the "Watering" switch of each room) still off:

1. Make sure that each room opens in the sidebar.
2. Make sure that the controller heartbeat of the room is current.
3. Make sure that the mapping shows **Mapping acknowledged**.
4. Make sure that **Equipment › Probes & offsets** shows the correct entities and units.

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
9. Enter the flow of each dripper, in litres per hour. Use the catch test to measure it.
10. Map the optional room equipment, the tank displays and the feed probes.
11. Make sure that the kill switch and the equipment of the room are off.
12. Select **Review configuration**, then **Save configuration**.
13. Wait for **Mapping acknowledged**. A saved setup and an accepted setup are different states.
14. Examine the room's Today page and **Equipment › Probes & offsets**.
15. Set the lights-on and lights-off hours of the room.
16. Examine the water limits, the shot sizes and the rescue floor of each zone.

The setup checks the entity types, the units, duplicate valves and revision conflicts. It also checks that the equipment of the room reads off.

The [user guide](USER_GUIDE.md#setup-pumps--valves) gives each field of the setup.

## Before the first watering

A watering (the dashboard calls it a shot) switches the pump, the main line and one zone valve in order, then closes them and counts the water. Before the first one, do these steps:

1. Configure the room with the "Watering" switch off.
2. Examine each probe that the room uses.
3. Examine each switch that the room uses.
4. Do a catch test: measure the water that comes out of the drippers in a known time.

> **CAUTION:** Do a catch test before the first automatic shot. The controller calculates the water totals on the dashboard from the settings and the valve time. Only a catch test or a flow meter shows the water that the plants got.

## Turn watering on

Set the "Watering" switch in the top bar to on.

> **CAUTION:** When the room is off or the "Watering" switch is off, the controller gives no shots. This includes the rescue shots. Make sure that no plants need water before you set either switch to off.

**Next →** [User guide](USER_GUIDE.md): each page of the dashboard and a daily routine.
