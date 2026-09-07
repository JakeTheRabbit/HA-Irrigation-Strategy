# Steering and whole-grow planning

## What the two modes actually do

The legacy controller reads mode-specific morning dryback and P0/P1/P2 EC references. Switching vegetative/generative selects those references; it does not automatically create a complete recipe or calculate suitable targets from your pot size.

The grow planner defines two explicit endpoints in each profile. The slider blends every configured parameter between them: 0 is the vegetative endpoint, 100 the generative endpoint, and 50 is halfway, rounded to each actual HA parameter's step. Profiles can differ in VWC targets, dryback, EC targets, shot sizes and other supported settings. These are operator-defined endpoints, not universal crop prescriptions. Existing installations seed endpoints from their current values, so identical endpoints intentionally produce no change until edited.

A more vegetative irrigation approach generally keeps water more available; generative approaches can use greater dryback and different root-zone EC. Appropriate values depend on substrate, cultivar, crop stage, climate and actual measurements. See Grodan's [crop steering introduction](https://www.grodan101.com/siteassets/downloads/grow-guide/chapter-3---introduction-to-crop-steering.pdf) and [precision irrigation guide](https://www.grodan101.com/siteassets/downloads/grow-guide/chapter-4---precision-irrigation.pdf). This software does not claim a yield or potency percentage from those inputs.

## Build a grow

1. Select the room, then **Grow plan**. Set each zone's grow start date.
2. Open **Endpoint profiles**. Review both endpoint columns; duplicate a profile when a zone needs different bounds. A shared profile affects every schedule block referencing it.
3. In **Schedule & curve**, select a zone row and week. Set its profile and steering slider. Switch to **Days** for exceptions. Editing a range splits existing blocks and preserves surrounding days.
4. Review the combined planning curve and hydraulic estimates below. The same selected date, zone and interpolated parameters drive both the curve and preview.
5. Choose **Review & save**. Resolve validation issues, inspect the per-zone preview and save the draft. Export JSON for a portable backup or another draft.
6. After adding or archiving zones in setup, use **Update zones from setup** in the draft planner. This keeps existing active-zone schedules, removes archived assignments and seeds new zones from current settings. Export the old draft first if you need those assignments. Review and save the reconciled draft.
7. **Arm plan** after the controller reports support. Activation happens at the next eligible local lights-on boundary. Active plans must be disarmed before editing. Disarm transfers control back to manual setpoints at a boundary.

The calendar supports grow days 1–366 per zone, distinct start dates and complete contiguous schedule ranges. Missing/finished/invalid schedules are visible and hold managed zones rather than inventing targets. Each room stores its plan in HA persistent storage with optimistic revision checks. Restart recovery uses the stored plan and controller latch.

## Read the combined graph

- **VWC axis:** percent substrate water content. P1 target, P2 trigger and the P3 emergency floor come from the selected interpolated profile.
- **EC axis:** root-zone conductivity in mS/cm. P0/P1/P2 references are distinct from the supply tank's feed EC. There is no independent scheduled P3 EC target; that segment is omitted.
- **Morning dryback:** relative to the peak. Formula: (peak − current VWC) / peak × 100. A peak of 60% and a dryback target of 10% gives a 54% VWC reference, a drop of six percentage points.
- **Phase windows:** show configured wait/shot timing where supplied. Approximate layout windows are explained beneath the chart when a parameter is missing. Actual phase transitions depend on sensor conditions.
- **Overnight:** P3 shows only the conditional emergency floor; it does not invent an overnight VWC/EC trend or routine watering schedule.
- **Shot band:** illustrates nominal retained shot volume; drainage and actual substrate response can differ.

Change a slider, profile value or supported graph handle and the preview updates immediately. Graph handles edit the selected profile's endpoints as explained in the UI; check shared profile references. Editing the graph does not directly write irrigation hardware.

This is a setpoint planning schematic. It does not predict uptake, runoff, salt balance or the exact times of future shots. **Overview → history** separately plots recorded VWC and EC on one timeline using HA Recorder data, with independent units/axes and explicit missing-data states.

## Pot and dripper sizing

Nominal shot volume = substrate L/plant × plants × shot percent / 100.

Nominal flow = plants × drippers/plant × L/hour/dripper / 3600.

Estimated duration = shot litres / flow litres/second, before the controller's explicit duration cap. Plant count cancels in duration for uniform per-plant irrigation but still determines total water volume. Actual catch tests, hydraulic pressure and sensor calibration remain necessary.

**Insights** provides a local catch-test calculator, probe coverage/freshness diagnostics and an equipment map. These tools expose assumptions instead of claiming to tune a crop automatically.

## Current boundaries

Plans steer irrigation targets, not tank dosing or environmental equipment. Legacy manual shot and phase override services may emit events without being consumed by this controller; the workspace does not advertise them as working actuator commands. Closed-loop crop-response learning, measured flow reconciliation and automatic recipe optimisation remain future work. See the [feature matrix](FEATURE_MATRIX.md).
