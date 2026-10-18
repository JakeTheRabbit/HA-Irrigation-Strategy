# Course plan: Crop Steering from Zero

## The promise

By the end, the learner can answer: **What is happening in this zone, what does this setting change, and how do I check that the system did what I intended?**

Teach an adult with no assumed horticultural, software or electrical vocabulary. Use ordinary language first, introduce the technical term second, then use that term consistently. Never make the learner feel foolish for replaying a lesson. No plant-stage, nutrient or sensor knowledge is assumed.

The course covers container/substrate irrigation and the Crop Steering program. Crop physiology, fertiliser formulation, professional electrical installation, automated dosing and advanced AI configuration are outside the beginner core. They get clearly labelled pointers, not hidden prerequisites.

## Routes and learning gates

```text
Everyone: A. Understand the root zone → B. Understand a watering day
                                           │
                  ┌────────────────────────┴─────────────────────┐
                  │                                              │
        Build your first system                       Use an existing system
          C1: kit and water path                       Local installer handover
          C2a: Pi OR C2b: x86-64                       Verify room/zone labels,
          C3–C7: install, map, test                     physical stop and records
                  └────────────────────────┬─────────────────────┘
                                           │
                           D. Operate, plan and investigate
```

An operator can study D in the demo before receiving a physical handover. Live operation waits for that handover. Builders may inspect and assemble a shopping list during A/B, but perform their first controller-driven water test only after C6/C7 checks. No plant needs to be deliberately stressed to complete this course.

| Gate | Learner must demonstrate | Evidence |
| --- | --- | --- |
| G1: measurement | Explain VWC, capacity and two ways of expressing dryback; identify the EC measurement type | Workbook 1–5 and teach-back |
| G2: graph | Locate time, both axes, shots, night, reference and actual data; identify a stale trace | Workbook 6–7 |
| G3: equipment | Trace the real water path and identify physical isolation, output owner and correct room/zone | Completed setup record and local handover |
| G4: commissioning | Prove the intended outlet waters, flow is measured, and water stops; verify readiness and acknowledged mapping | Supervised C7 record; no demo substitute for physical proof |
| G5: operation | Preview, review, apply and read back a change in the demo; explain plan activation and control scope | Workbook 8–10 and observer check |
| G6: diagnosis | Respond correctly to stale moisture, a contradictory tank display and water continuing after a software stop | Workbook 11–13 |

All safety/control-scope items must be correct before independent operation. Other wrong answers receive an explanation and a retry with a different example. Completion is a practical skills check, not a professional certification or a count of videos watched.

## The lesson pattern

1. **Show the problem:** one real object or one uncluttered screen, before new vocabulary.
2. **Explain one idea:** combine a drawing with spoken explanation; reveal the parts progressively.
3. **Predict:** a short pause with a concrete choice or number. Put the pause symbol on screen; allow real time to think.
4. **Reveal and explain:** explain why the answer follows, including the common wrong answer.
5. **Do:** copy one demonstrated task, complete a partly filled example, then attempt an independent task.
6. **Recall:** one question from an earlier lesson, with feedback. Revisit key ideas the next day and about a week later where feasible.

These are design choices informed by research on worked examples, retrieval, spacing and visual explanation. The exact intervals and lesson lengths are proposed for this course, not a universally proven formula. See the [evidence ledger](PRODUCTION-AND-SOURCES.md).

## Playlist A — What is happening inside the pot?

Prerequisite: none. Use a spare unplanted container, tray, measuring jug and simple cross-section drawings. Approximate total: 25–35 minutes.

| ID / YouTube title | Outcome and demonstration | Mistake to address | Pause task / completion check |
| --- | --- | --- | --- |
| A1 — Before the buttons: water, roots and air | Explain why the root zone needs both water and air; show solids, water and air in a container drawing. Introduce steering as managing conditions, not forcing a guaranteed result. | More water is always better; steering means maximum stress. | Point to the three components and describe one thing a sensor cannot tell us. |
| A2 — VWC: what does 60% actually mean? | Define volumetric water content using ten equal volumes; connect the drawing to a probe reading. | VWC is percent plant-available water, or the rest is all air. | Explain 60% in your own words, then name a limitation of one probe. |
| A3 — When is a pot full? Capacity versus saturation | Demonstrate drainage in spare medium; distinguish saturation, drained container capacity and the app's field-capacity reference. | Highest reading ever observed is the right target; every medium should reach 100%. | Label three states and list what must stay consistent during a capacity check. |
| A4 — Dryback without the confusing maths | Work 60% to 45%: 15 percentage points, 25% relative dryback. Show subtraction first, relative calculation second. | Fifteen points and 15% relative dryback mean the same thing. | Complete a faded example, then independently calculate 50% to 40%. |
| A5 — EC: what it measures, and which EC you are looking at | Compare feed, bulk substrate, pore-water and runoff/extract readings using labelled sample locations. | EC is an exact nutrient analysis; all EC readings are interchangeable. | Match four labels to the water path; state why a TEROS 12 bulk EC value is not automatically pore-water EC. |
| A6 — Can you trust that reading? | Inspect timestamp, units, placement, agreement between representative probes, medium calibration and an independent check. | A convincing-looking line proves the whole zone is healthy. | Spot a frozen timestamp and explain the next safe check before changing a target. |

Do not add target recipes to these lessons. The objective is measurement literacy. Finish A with G1; repeat errors using a new example, rather than replaying the entire playlist as punishment.

## Playlist B — Understand a whole watering day

Prerequisite: A/G1. Approximate total: 22–30 minutes. Build a single graph over the playlist rather than introducing a crowded dashboard at once.

| ID / YouTube title | Outcome and demonstration | Mistake to address | Pause task / completion check |
| --- | --- | --- | --- |
| B1 — Read water and EC on the same graph | Read time, separate VWC/EC axes, night shading and irrigation events. Add the planned reference and actual trace separately. | Crossing lines mean equal values; dashed EC is a prediction. | Identify which line and axis answer a question; predict what moving the rescue threshold changes. |
| B2 — P0 to P3: build the day one phase at a time | Explain morning dryback, ramp-up, maintenance and overnight using this program's phase names. Show that actual transitions and shots depend on conditions. | All phases switch at the illustrative graph's exact times; the overnight floor is an ordinary target to chase. | Put phase cards in order and explain the purpose of one phase without quoting a target. |
| B3 — Vegetative and generative: a bias, not a magic switch | Explain steering direction within crop development, interaction with climate/light and why suitable endpoints require local evidence. Preview the configured endpoint slider. | Generative always means flower stage; moving the slider invents safe settings from pot size. | Explain why identical endpoints change nothing, and name two reasons the same recipe can behave differently. |
| B4 — How much water did each plant get? | Convert dripper flow and runtime to per-plant and per-zone delivery; distinguish measured flow, estimates, runoff and uptake. | Zone litres are per-plant litres; a 2% substrate-volume shot guarantees a two-point VWC rise. | Calculate the worked example in the workbook and explain why conditional shots prevent a guaranteed daily total. |

Finish with G2. Optional sidebar: temperature, humidity and light change water demand. Define VPD only as a description of atmospheric drying demand at this stage; do not introduce another numeric target recipe. Water loss includes drainage and evaporation/transpiration, not only root uptake.

## Playlist C — Build and prove one zone

Prerequisite: A/B, or a knowledgeable installer following the hardware route. Only watch **one** host video. Approximate total along one route: 45–65 minutes; physical setup, firmware and checks take additional time.

| ID / YouTube title | Outcome and demonstration | Mistake to address | Pause task / completion check |
| --- | --- | --- | --- |
| C1 — What you need: the smallest useful system | Lay out the functional bill of materials. Trace two possible water paths: pressurised supply/zone valve, or reservoir/pump/zone valve. Separate essentials, conditional items and later upgrades. | Every system needs a pump; an expensive probe alone makes a complete system. | Draw your actual water path, circle missing functions and assign an owner to each output. |
| C2a — Install Home Assistant on a Raspberry Pi | Follow the current official Pi HAOS procedure on a clearly identified spare storage device; show power, network and first boot. | Flashing is harmless to the selected storage; any phone charger is suitable. | Identify the exact target card before erase; reach first boot. |
| C2b — Install Home Assistant on an Intel NUC or x86-64 PC | Follow the official generic x86-64 HAOS route on supported dedicated hardware; show backup, firmware requirements and target disk verification. | Installing HAOS preserves the existing OS and files. | Identify the dedicated disk and recovery backup before erase; reach first boot. |
| C3 — Your first Home Assistant: names, entities and backups | Define an entity as one named reading/control; set local time, account access and a recoverable backup. | A device and an entity are the same; seeing a backup entry proves recovery. | Find one reading and one control, verify timezone, save a backup outside the host and explain recovery steps. |
| C4 — Connect probes and equipment safely | Prefer a documented compatible assembled sensor route; show HA discovery, units and freshness. Contrast optional verified DIY bridge. Demonstrate already professionally installed output controls using low-risk test loads first. | Probe wire colours establish compatibility; a relay's resistive rating proves it can start a pump. | Trace sensor and control paths; identify exact voltage/interface ratings and the person responsible for electrical work. |
| C5 — Install Crop Steering: integration and Controller | Install both compatible components using the current guide; show room creation, discovery, heartbeat and controller engines disabled during setup. | The HACS download alone runs irrigation; software OFF is physical isolation. | Show both versions, room identity and fresh controller report while outputs remain isolated. |
| C6 — Map one room and zone | Map the correct probe, valve, pump if applicable and units; enter plant count, substrate volume, drippers and measured flow. Set/check local room lights-on/off hours against the actual lighting. Review/save and wait for controller acknowledgement. | Similar names prove the right entity; timezone establishes the lighting schedule; saved means accepted. | Complete the setup record, verify lighting hours and demonstrate an acknowledged mapping with correct live values. |
| C7 — First water: catch, measure, stop, prove | Perform the staged commissioning procedure in the equipment guide: installer-approved equipment catch test with Controller Watering OFF, followed only after passing checks by a supervised enabled Controller cycle. Verify intended outlet, cessation of flow, no siphon and actual delivery. | Watering OFF permits a Controller test shot; a changed icon proves water stopped; one average proves equal delivery. | Pass G3/G4 with a local competent supervisor; otherwise disable Watering, isolate as required and resolve the failed check. |

No mains wiring tutorial, no bypass of a hold, and no “copy my probe wires” shortcut. Optional DIY sensor detail belongs in an appendix tied to the exact verified assembly, firmware and electrical interface. C is a shared route after the two alternative host lessons, rather than two duplicate installation courses.

## Playlist D — Use the program with confidence

Prerequisite: A/B. Use the demo for practice. Physical handover and completed commissioning are additional requirements before live operation. Approximate total: 30–45 minutes.

| ID / YouTube title | Outcome and demonstration | Mistake to address | Pause task / completion check |
| --- | --- | --- | --- |
| D1 — Find your room, zone and next action | Navigate Overview → All zones / Selected room; identify room scope, phase, latest irrigation, pump/tank information and data age. Set this browser's default view. | Header Stop all affects every room; unknown means OFF. | Select a named zone, read Why / next action and identify which room the controls affect. |
| D2 — Change one target and see the curve move | In Irrigation → Current day, change a draft P3 emergency floor in the demo. Compare saved/draft, inspect review, apply and check readback. If a plan owns targets, explain read-only state and go to Calendar. | Moving a reference line moves the measured crop; changing an emergency floor schedules ordinary irrigation. | Explain each action's consequence before clicking; restore the demo exercise value through review. |
| D3 — Plan days and weeks without losing control | Open Irrigation → Calendar; use distinct endpoints, profiles and dated zone blocks; inspect shared-profile scope, save, arm and next-lights-on activation. | Saving a recipe arms a plan; arming enables Watering; disarming is instant isolation. | In the demo, explain what is draft, what is stored and what will activate when. Do not arm a real plan for the exercise. |
| D4 — Compare reality with the plan | Use History → Timeline, Water use, Compare runs and Grows; match zone, run age, dates, units and data coverage. Distinguish available stored references from historical target evidence. | A current reference reconstructs past targets; estimated litres are plant uptake or measured totals. | Write one defensible observation and one conclusion the available data cannot support. |
| D5 — Troubleshoot before you change a recipe | Investigate stale probes, wrong-zone mapping, missing acknowledgement, tank contradictions and unexpected flow. Use physical shutdown for uncontrolled water, then logs/readback. | Fix a fault by lowering a safety threshold or forcing an output. | Choose the next action for the three workbook failure scenarios and explain why. |
| D6 — A five-minute daily check and a useful handover | Check freshness, phase/next action, delivery, tank/feed and exceptions; record one justified change with context and follow-up. Show a backup/update handover and bounded AI assistance. | An AI suggestion is verified plant evidence; one changed day proves causation. | Complete the daily record and teach a second person how to identify scope and physically stop the installation. |

### Product behaviours the teacher must preserve

- The graph is a **reference illustration**, not a validated crop-response forecast. The overnight dashed EC joins references; there is no independent scheduled P3 EC target. Actual data and target references need different labels and styling.
- Morning dryback is relative to the peak in this program; inspect the field's label/unit instead of assuming every dryback field uses the same convention.
- The legacy mode select chooses mode-specific dryback/EC references; the planner slider interpolates operator-configured endpoints. Neither automatically designs a safe recipe from pot size.
- Current day is the manual target editor when no plan owns the targets. Calendar defines dated targets; it is not a second independent set of simultaneously active controls.
- Local edit → reviewed apply → HA readback are separate. Plan save → arm → next local lights-on activation are separate. Arming does not enable Watering. Disarming returns control at the next lights-on; it is not an emergency stop.
- Active plans must be disarmed before editing. Describe the scheduled handover before doing it. Profile edits can affect multiple referenced blocks/zones.
- A plan hold is not physical isolation: safety watering may still occur. Header Watering and Stop all act on the selected room and do not replace physical isolation.
- Production recipe libraries start empty. Saving a library recipe writes to this browser/site/room library, not active HA targets. Saving a run record starts no shots and does not reconstruct earlier targets.
- EC may be absent: the engine can run moisture-based watering while EC rules are paused. Don't describe an EC probe as a universal software prerequisite. Unknown/stale data are not zero or OFF.
- Runtime-derived delivery is an estimate unless a suitable verified measurement supports it. Per-plant delivery is an average based on count. None of these is measured plant uptake.

These statements are based on the reviewed local [user guide](../../USER_GUIDE.md), [grow-plan documentation](../../GROW_PLANS.md) and [installation guide](../../INSTALL.md). They must be retested before filming a new release.

## Initial YouTube release and production order

**Pilot first:** record A1, A2 and A3 using the scripts. Test them with 3–5 people who cannot already explain VWC. Observe their answers without coaching; use the measures in the production guide. Revise confusing explanations before recording the rest. This is a usability pilot, not a statistically representative trial.

**First public batch:** a 60–90 second trailer, A1–A6 and C1. This gives newcomers a complete foundation and an honest equipment overview before asking them to buy or configure anything. Five scripts are supplied in this pack; A4–A6 and the trailer still need full spoken scripts, recording and editing. Every remaining episode has an objective, demonstration and assessed task above.

**Next batches:** B → C's remaining setup lessons → D. Release each coherent playlist with its worksheet and corrected captions. A learner should not have to find an unpublished lesson to complete a published playlist. Keep the existing hardware tutorial available as a reference while videos are produced.

Proposed weekly learning rhythm: two foundation sessions with practice between them; one graph session; one separate installation session for builders; two operating sessions. Installation duration depends on equipment readiness. Do not rush physical checks to meet a video runtime.

## Optional follow-on courses

After demonstrated competence: multi-zone uniformity, substrate-specific calibration, advanced climate interpretation, verified water meters/runoff balance, nutrient/dosing safety, recipe evaluation and bounded AI/MCP configuration. These require their own equipment and prerequisites. They are not prerequisites hidden inside a beginner lesson.

Recipe collections can later be taught as attributed, context-specific examples. Do not present Athena, another author's book or a grower's recipe as validated for every medium, cultivar, sensor and water source. This beginner pack deliberately teaches how to evaluate a recipe before copying it.
