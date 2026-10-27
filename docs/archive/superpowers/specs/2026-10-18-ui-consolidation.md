# Buildable design proposal — approved 2026-10-18

Read [the duplication audit](2026-10-18-ui-duplication-audit.md) for all 31 findings, route coverage, owner assignments and non-merge boundaries. The source of truth is that ownership map. The original offline mockup is a throwaway interactive illustration, not a full implementation spec or controller simulation.

## Navigation and ownership

Today owns a short operational summary; zone details own one live chart and one explanation. Irrigation owns current and future crop targets, room lights schedule and automatic-setpoint enable. Current-day values show whether manual control, an armed schedule or bounded automation owns them. Calendar and current-day views are two contexts of the same workspace, not duplicate writers. Settings owns AI permissions/instructions, display, notifications and connection. Equipment owns room/zone hardware sizing, physical safety, sensing, runoff, calibration and nutrient equipment. History owns recorded evidence, events, water, run portfolio and comparisons.

## Editing model

Editing a scheduled day creates a draft associated with room, zone, grow day and revision. Changing a graph control changes its labelled planning reference immediately; recorded evidence is never rewritten. Saving a draft, reviewing changes and arming/applying a schedule are different actions. A one-day override must show its source, scope and expiry and respect existing controller permissions. Production implementation must retain the existing permitted writer and handoff rules.

Equipment changes stage locally, review before/after values and affected rooms, and retain drafts after a refused save. Pausing watering requires explicit action. Final save rechecks watering/hardware state and revision; it never silently turns watering back on. Room-in-use, individual/bulk zone enable and emergency stop remain distinct. Backend safety policies are unchanged.

## Chart model

Use one continuous lights-on-to-next-lights-on VWC/EC canvas, with separate axes, units, phase bands and day/night boundary. Emergency floor is a safety threshold: moving it moves that line; changing it must not fabricate a physical response. A valid controller/planning calculation may update a schematic target trajectory, clearly separated from recorded readings and expected-model uncertainty. Demo reference trajectories are illustrative only. Recorded traces end at the last real observation and gaps remain gaps. Previous runs align by explicit date or grow day; no future evidence is invented.

## Water model

Show zone total and average per plant together with their provenance. Runtime estimate uses dripper L/h × drippers/plant × seconds/3600 × plants, retaining per-event historical configuration where available. Do not label estimated delivery as uptake. Measurement versus estimate, historical plant counts and uncertain/missing data must remain visible.

## Approval and implementation

Recommendation is layout A (cards), with B available as a density preference using the same components. User approved layout A and the ownership map on 2026-10-18, adding All zones as the landing page and a browser default-view selector. Approval is for the navigation/ownership map and visual direction; production changes remain a separate implementation task. Before implementation, audit every registry-only control, choose the authoritative persistence writer, preserve existing APIs/guards, add old-route redirects and test the workflows described in the duplication audit. Mock-only deeper-form placeholders are not permission to remove those capabilities.
