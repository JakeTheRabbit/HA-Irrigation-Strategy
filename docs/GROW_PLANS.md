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

## See changes while editing manual setpoints

Open **Manual setpoints** and select a zone. The daily graph stays beside the phase controls on a wide screen. The saved reference and draft are shown separately: changing the P3 emergency floor moves its line immediately, while the saved line remains for comparison. Changing a mode uses that mode's dryback and EC values. A shared room value is used only when the controller has no zone-specific value.

Graph edits and form edits share one draft. Invalid fields remain visibly invalid; they do not become zero or silently fall back to a different room. Review and apply still controls when values reach Home Assistant. An active plan owns its targets, so manual fallback fields remain locked until its normal handoff.

## Compare a run with targets or a previous run

Use **Compare runs** for recorded VWC/EC history over a day, week, month, a run so far, or a selected date range. Register each run's name and start/end dates. The run record preserves zone identity, mapped sensors and a timestamped reference configuration. Previous runs align by elapsed grow age so a partial current run is not compared with a complete previous run.

Targets are reference lines, not a claim that those values were used historically. Adding an older run today captures today's reference configuration unless an existing saved reference is available. Historical readings remain limited by Home Assistant Recorder retention. Missing periods stay missing. This view does not change irrigation, arm a plan or fabricate earlier data.

## Pot and dripper sizing

Nominal shot volume = substrate L/plant × plants × shot percent / 100.

Nominal flow = plants × drippers/plant × L/hour/dripper / 3600.

Estimated duration = shot litres / flow litres/second, before the controller's explicit duration cap. Plant count cancels in duration for uniform per-plant irrigation but still determines total water volume. Actual catch tests, hydraulic pressure and sensor calibration remain necessary.

Effective water per plant (mL) = effective runtime seconds × drippers per plant × L/hour per dripper ÷ 3600 × 1000.

Effective zone water (L) = water per plant (mL) × plants ÷ 1000.

For 42 plants with one 4 L/hour dripper each, 120 seconds is about **133 mL/plant and 5.6 L/zone**. A 60-second duration limit gives about **67 mL/plant and 2.8 L/zone**. The UI shows the requested and effective run time separately. Daily recorded water uses controller estimates; average per plant assumes equal distribution. These values do not measure crop uptake, runoff or unequal emitters.

The P1 maximum-shot budget is conditional. P2 maintenance and P3 emergency shots depend on sensor feedback, so a guaranteed whole-day total cannot be inferred from target values alone. Historical controller totals are preserved; new shot accounting uses effective duration after caps and minimum timing.

**Insights** provides a local catch-test calculator, probe coverage/freshness diagnostics and an equipment map. These tools expose assumptions instead of claiming to tune a crop automatically.

## Current boundaries

Plans steer irrigation targets, not tank dosing or environmental equipment. Legacy manual shot and phase override services may emit events without being consumed by this controller; the workspace does not advertise them as working actuator commands. Closed-loop crop-response learning, measured flow reconciliation and automatic recipe optimisation remain future work. See the [feature matrix](FEATURE_MATRIX.md).
