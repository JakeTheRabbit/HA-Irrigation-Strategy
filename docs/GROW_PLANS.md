# Steering and whole-grow planning

## The words you'll see

Container growers can apply small irrigation events called **shots**. Water content, EC, drainage and environmental conditions contribute to steering:

- **Vegetative steering** aims to support vegetative growth through a coordinated set of conditions.
- **Generative steering** aims to support reproductive development through a different coordinated set of conditions.

These describe an intended direction, not a guaranteed plant response. The slider blends your configured endpoints; pot size and dripper flow alone cannot establish safe targets. Start with the [academy](https://jaketherabbit.github.io/HA-Irrigation-Strategy/learn/) if the terms below are new.

A group of plants on one valve is a **zone**. The probes in the substrate give the numbers that the controller uses:

| Term | Meaning |
| --- | --- |
| **VWC** (moisture) | Water volume divided by total measured sample volume, usually expressed as a percentage. It is not percent plant-available water. |
| **Pore EC** | Conductivity of water in substrate pore spaces, in mS/cm. Identify the measurement type: feed, bulk substrate, pore-water and runoff/extract EC are not interchangeable. |
| **Dryback** | The decrease of VWC between shots, overnight or in the morning. |
| **Field capacity** | A configured reference in this program. Establish the appropriate drained container condition with a documented method; an entered value does not prove physical capacity. |
| **Shot** | One short delivery of water. Its size is a percentage of the substrate volume. |

Each grow-day has four phases:

| Phase | What occurs | Why |
| --- | --- | --- |
| **P0: morning dryback** | After lights-on, the controller uses configured timing and dryback conditions before ramp-up. | Sets the conditions for the first shot; it does not guarantee a root-growth response. |
| **P1: ramp** | The controller gives small shots, some minutes apart, until VWC reaches your peak target. | The ramp fills the substrate slowly. It does not flood the roots. |
| **P2: maintenance** | The controller gives a maintenance shot when VWC falls to your re-water point. | The maintenance shots keep the roots stable through the day. |
| **P3: overnight dryback** | The usual shots stop before lights-off. The controller gives only a rescue shot when a zone becomes too dry. | Much of the steering occurs during the overnight dryback. |

Targets can change with the growth stage and local evidence. Build a plan from reviewed endpoint profiles and calendar blocks, then verify the active targets. Library recipes and illustrated reference curves are starting points for review, not universally safe prescriptions or validated crop-response forecasts. The academy's planning lessons cover this in more depth.

## What the two modes actually do

The legacy controller reads mode-specific morning dryback and P0/P1/P2 EC references. Switching vegetative/generative selects those references; it does not automatically create a complete recipe or calculate suitable targets from your pot size.

The grow planner defines two explicit endpoints in each profile. The slider blends every configured parameter between them: 0 is the vegetative endpoint, 100 the generative endpoint, and 50 is halfway, rounded to each actual HA parameter's step. Profiles can differ in VWC targets, dryback, EC targets, shot sizes and other supported settings. These are operator-defined endpoints, not universal crop prescriptions. Existing installations seed endpoints from their current values, so identical endpoints intentionally produce no change until edited.

A more vegetative irrigation approach generally keeps water more available; generative approaches can use greater dryback and different root-zone EC. Appropriate values depend on substrate, cultivar, crop stage, climate and actual measurements. See Grodan's [crop steering introduction](https://www.grodan101.com/siteassets/downloads/grow-guide/chapter-3---introduction-to-crop-steering.pdf) and [precision irrigation guide](https://www.grodan101.com/siteassets/downloads/grow-guide/chapter-4---precision-irrigation.pdf). This software does not claim a yield or potency percentage from those inputs.

## Build a grow

1. Select the room, then **Irrigation › Grow plan & presets**. Set each zone's grow start date.
2. Open **Endpoint profiles**. Review both endpoint columns; duplicate a profile when a zone needs different bounds. A shared profile affects every schedule block referencing it.
3. In **Schedule & curve**, select a zone row and week. Set its profile and steering slider. Switch to **Days** for exceptions. Editing a range splits existing blocks and preserves surrounding days.
4. Review the combined planning curve and hydraulic estimates below. The same selected date, zone and interpolated parameters drive both the curve and preview.
5. Optionally give the plan a name (beside its status); the AI assistant's plan line shows it instead of the profile in force. Choose **Review & save**. Resolve validation issues, inspect the per-zone preview and save the draft. Export JSON for a portable backup or another draft.
6. After adding or archiving zones in setup, use **Update zones from setup** in the draft planner. This keeps existing active-zone schedules, removes archived assignments and seeds new zones from current settings. Export the old draft first if you need those assignments. Review and save the reconciled draft. Setup refuses to add or archive zones, or to archive the room, while its plan is armed or running: disarm it first.
7. **Arm plan** after the controller reports support. Activation happens at the next local lights-on after arming, by the room's lights-on hour at that time. Active plans must be disarmed before editing. Disarm transfers control back to manual setpoints at the next lights-on.

Each new day is applied at lights-on. If it cannot be applied then (Home Assistant restarting, the controller's heartbeat a few minutes late), the plan keeps the previous day's targets and applies the day at the first minute it can; Settings → Repairs shows *has not moved on to today* with the reason meanwhile. The plan never waits for a zone's root-zone EC probe: the engine waters a zone without one on moisture alone, with its EC rules paused. A zone whose moisture probe is stale keeps the targets it had while every other zone moves on to the new day, and gets the day as soon as its probe reads again (Repairs names the zone meanwhile). Only a room where no zone's moisture reads, or a plan's first day, waits for every zone.

The calendar supports grow days 1-366 per zone, distinct start dates and complete contiguous schedule ranges. Missing/finished/invalid schedules are visible and hold managed zones rather than inventing targets. A hold stops the plan's steering, never the zone's water safety: the overnight emergency shot, the lights-on watchdog and the minimum daily volume still water a held zone, and Repairs shows *holding irrigation* with the reason. Each room stores its plan in HA persistent storage with optimistic revision checks. Restart recovery uses the stored plan and controller latch.

## How the controller checks the plan is running

The plan is applied when the controller reads its targets, so an active plan's numbers are the ones the engine
uses. What can still go wrong is that the plan does not move on, does not start, ends, or is quietly ignored. Every
pass, under every brain (rules included), the controller compares what the plan expects since lights-on with what
the room is doing, using the integration's own preview of the plan, and says plainly when they differ: one
**CS-713** card per episode, and a one-line plan headline on the AI assistant panel ("Plan: Bulk · day 17 of 84
(week 3) · on track"). It checks for:

- today's plan day not in force for a zone (with the targets it changes and why it waits), or an armed plan that
  did not start;
- a plan saved and not armed for a whole day after its start dates, and a plan ending within three days;
- a setting the plan controls changed by hand or by an automation: while the plan runs that change has no effect,
  and it is **never overwritten**; the card says how to keep it (change the plan's days) or drop it;
- what comes back when a plan is disarmed, where it differs from today's plan;
- a steering select that disagrees with the plan's bias (under 40 % or over 60 % generative), lights hours
  read from somewhere other than the integration, and a grow light mapped in setup that reads on while the hours
  say off, or the reverse, for 15 minutes away from either edge (the engine follows the hours);
- a zone that did not start its day at lights-on, did not stop at lights-off, or stayed in its morning dryback past
  its maximum wait (each should never happen: please send the controller log), and a ramp that runs very long.

Under the Claude Haiku brain the assistant may pick which suggestion the line shows. When today's plan day is held by a stale probe, it is also asked whether that probe matters for watering today: only on a firm *no*, and only once the envelope's rules all pass (lights on and away from lights-off, no shot running, fresh readings elsewhere, once a day), the controller applies today's plan values, the plan's own, until the plan applies the day itself or the next lights-on. The plan, its revision and every setting are left as they are, and a CS-713 card says so. Turn it off by leaving `plan` out of `jev_judges`, or try it with `brain_dry_run`.

Nothing is checked in a room that is off, in the first 10 minutes after a start, or on plan data older than
six hours. A plan with the same lights-on and lights-off hour has no lights-on edge, so the checks that wait for one
are skipped.

## Read the combined graph

- **VWC axis:** percent substrate water content. P1 target, P2 trigger and the P3 emergency floor come from the selected interpolated profile.
- **EC axis:** root-zone conductivity in mS/cm. P0/P1/P2 references are distinct from the supply tank's feed EC. There is no independent scheduled P3 EC target: overnight, the dashed EC line interpolates from the last daytime reference to the next morning's. It is not a predicted salt response.
- **Morning dryback:** relative to the peak. Formula: (peak − current VWC) / peak × 100. A peak of 60% and a dryback target of 10% gives a 54% VWC reference, a drop of six percentage points.
- **Phase windows:** show configured wait/shot timing where supplied. Approximate layout windows are explained beneath the chart when a parameter is missing. Actual phase transitions depend on sensor conditions.
- **The day, phase by phase:** the VWC line is drawn the way the controller runs the day. P0 keeps drying after lights-on, P1 climbs one step per shot, P2 fires a shot each time VWC falls to its threshold, and P3 dries down overnight to the next lights-on. Shot timing comes from a dry-down rate: the zone's own measured rate on **Status › Room**, a stated nominal rate (2 points an hour with lights on, 1 with lights off) where no zone history is available, as on **Calendar**. The P3 emergency floor stays a separate line. If a P2 threshold sits far under the P1 target, few or no P2 shots project, and the graph says why and names the threshold that would give them.
- **Shot size on the graph:** each riser assumes the whole shot is retained unless the zone has a learned gain; drainage and actual substrate response can differ. Hover a riser for its time and size.

Change a slider, profile value or supported graph handle and the preview updates immediately. Graph handles edit the selected profile's endpoints as explained in the UI; check shared profile references. Editing the graph does not directly write irrigation hardware.

This is a projection from setpoints and a dry-down rate. It does not predict uptake, runoff or salt balance, and the engine fires on the probe, not on these times. **History › Explorer** plots each zone's recorded VWC and EC using HA Recorder data, with independent units/axes and explicit missing-data states.

## See changes while editing manual setpoints

Open **Irrigation → Current day** and select a zone. The daily graph stays beside the phase controls on a wide screen. The saved reference and draft are shown separately: changing the P3 emergency floor moves its line immediately, while the saved line remains for comparison. Changing a mode uses that mode's dryback and EC values. A shared room value is used only when the controller has no zone-specific value.

Graph edits and form edits share one draft. Invalid fields remain visibly invalid; they do not become zero or silently fall back to a different room. Review and apply still controls when values reach Home Assistant. When a schedule owns the room, Current day shows its effective targets read-only and hides manual fallback inputs. Use Calendar to edit dated targets.

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

**Equipment › Setup: pumps & valves** provides a local catch-test calculator, and **Equipment › Probes & offsets** shows probe coverage and freshness. These tools expose assumptions instead of claiming to tune a crop automatically.

## Recipe library

The library stores copies of plans you author. Live room libraries start empty and do not contain publisher-endorsed or guide-derived numerical recipes. The isolated demo seeds clearly labelled synthetic examples only when a demo room has no stored library; existing libraries are preserved.

Open **Irrigation › Grow plan & presets › Advanced › Recipes** to save a named copy of the current plan, inspect stored copies, or load one into the local draft. Loading a recipe retains the current zone start dates and requires compatible zone assignments. Existing unsaved work requires an explicit replacement review. Active plans remain protected by the normal draft/arm workflow.

Library storage belongs to this browser and this site, separated by room and demo/live mode. It is not an HA backup or shared multi-user database. Export important plans using the existing JSON export; use Import to bring an exported plan into the reviewed workflow. Clearing browser storage can remove local library entries. An unavailable or malformed library must be recovered explicitly rather than silently overwritten.

Loading or saving a local library item never calls an irrigation service. The normal **Review & save** action persists the draft in HA, and arming remains a separate action. Inspect the graph, assignments, dates and parameter validation before using a loaded draft.

## Current boundaries

For reusable copies of your own schedules, use **Recipe library**. It stores named plans in the current browser and room, supports export/import and loads only into the local draft while retaining current zone start dates. See [Recipe library](#recipe-library) and its [reference sources](REFERENCES.md#plan-library-reference-sources).

Plans steer irrigation targets, not tank dosing or environmental equipment. Closed-loop crop-response learning, measured flow reconciliation and automatic recipe optimisation remain future work. See the [feature matrix](FEATURE_MATRIX.md).
