# Learner workbook

Name: __________  Date: __________  Route: demo / existing system / builder

You can pause, repeat and use a calculator. Explain your answer as if you were helping a friend. The numbers below are fictional teaching examples, **not crop recommendations**. Do not copy them into a live grow.

## A small glossary

| Term | Plain meaning |
| --- | --- |
| Substrate / medium | The material around the roots, such as coco or stone wool |
| VWC | Water volume divided by the total volume of the measured sample, expressed as a percentage |
| Saturation | A condition where pore spaces are filled with water; solids remain part of the total sample |
| Container capacity | Water retained after a defined drainage procedure in a particular medium/container |
| Field-capacity reference | The program's configured reference; establish what physical condition and method it represents |
| Dryback | A reduction in water content over an interval; check whether the field means percentage points or a relative percentage |
| EC | Electrical conductivity; information about dissolved ions under the measurement conditions, not a complete nutrient analysis |
| Feed EC | EC of the supplied nutrient solution |
| Bulk EC | Conductivity measured across the bulk medium; water content and the medium affect it |
| Pore-water EC | Conductivity of water in the pore space, measured or estimated by a specified method |
| Runoff / extract EC | Conductivity of the collected sample from a stated procedure; not automatically equal to pore-water EC |
| Zone | A group managed as one irrigation unit; it still needs checks for variation within it |
| Entity | A named reading or control in Home Assistant |
| Setpoint / target | A configured reference used in a control rule, not a measurement of the crop |
| Draft | A change you are editing before it is applied |
| Readback | Checking the values/status reported after a change, rather than assuming the request succeeded |
| Heartbeat | A recent report showing the Controller is communicating; not proof that water physically flowed or stopped |
| P0 / P1 / P2 / P3 | This program's morning dryback / ramp-up / maintenance / overnight phases |
| Vegetative / generative bias | A management direction; not simply a switch between the plant's growth stages |

## 1. Explain a reading

The probe shows 60% VWC.

- What fraction of the measured sample's total volume is water? __________
- Is the rest all air? Why? __________
- Does the plant have exactly 60% of its usable water left? __________
- Does one reading establish that every pot in the zone is equally wet? __________

## 2. Capacity cards

Match each description to **saturation**, **drained container capacity**, or **configured reference**.

1. Pore spaces filled with water: __________
2. Number entered in the software: __________
3. Water retained after the stated drainage protocol: __________

Name three conditions you should record when establishing a container reference: __________

## 3. Dryback — first copy, then complete, then try alone

Worked example: 60% VWC falls to 45%.

```text
Drop in percentage points = 60 − 45 = 15 points
Relative dryback = (60 − 45) ÷ 60 × 100 = 25%
```

Finish this example: 50% falls to 40%.

```text
Drop = 50 − ____ = ____ points
Relative dryback = ____ ÷ 50 × 100 = ____%
```

Try alone: the peak is 60% and a field specifies **10% relative dryback**. What VWC corresponds to that reference? __________

Explain why calling a 60-to-45 drop “15% dryback” is ambiguous: __________

## 4. Label the EC sample

Put **feed**, **bulk substrate**, **pore-water**, or **runoff/extract** beside each measurement.

1. A cup sampled from the supply tank: __________
2. TEROS 12's bulk conductivity measurement in the medium: __________
3. Conductivity of water in pore space, using an identified valid method: __________
4. Solution collected by a stated drainage/extraction procedure: __________

Can a high EC number alone tell you exactly which nutrient is excessive? __________

## 5. Trust the sensor?

The line is smooth, but its last timestamp was several hours ago. Another representative probe is changing. What do you check before changing irrigation targets? __________

## 6. Read a combined graph

On a demo graph, point to or write down:

| Item | Your observation |
| --- | --- |
| Selected room and zone | |
| Time interval and night shading | |
| VWC line, axis and unit | |
| EC line, axis, unit and measurement type | |
| One irrigation event | |
| A saved reference versus a draft or actual trace | |
| Last reading / controller report age | |

The EC and VWC lines cross. Does this mean the readings have equal values? __________

The dashed overnight EC line connects two references. Does that guarantee the measured EC will follow it? __________

## 7. Shot volume: per plant and per zone

Our fictional zone has **20 plants**, **5 L substrate per plant**, **two 4 L/h emitters per plant**. A shot runs for **45 seconds**.

```text
Per-plant flow = emitters per plant × L/h each
Per-plant delivery = per-plant L/h × seconds ÷ 3600
Zone delivery = per-plant delivery × plants
Shot as % of substrate volume = delivery L per plant ÷ substrate L per plant × 100
```

- Flow per plant: __________ L/h
- Delivery per plant: __________ L, or __________ mL
- Total zone delivery: __________ L
- Shot as a fraction of substrate volume: __________ %

Ten identical completed shots would estimate __________ L per zone and __________ L per plant. Does this prove actual equal delivery or plant uptake? __________

Does that shot fraction guarantee the same increase in VWC percentage points? __________

Why can't we guarantee a daily total just by counting the shots drawn on an illustrative planning graph? __________

## 8. Move a line without operating a real pump

Open the isolated demo. Select a room and zone in **Irrigation → Current day**. If a plan owns the targets and they are read-only, practise on a suitable manual demo zone rather than disabling a real plan.

1. Record the saved P3 emergency floor: __________
2. Nudge the local draft by one allowed step. Describe which reference moved: __________
3. Did the observed crop data move? __________
4. Open the review. State the field, unit, room, zone and before/after values: __________
5. Apply in the demo and inspect readback. Then restore the original example value through the same review.
6. Explain why this was a threshold edit, not a guaranteed shot: __________

You have practised the interaction, not established a suitable live threshold.

## 9. What does each action do?

Complete the table before checking the answers.

| Action | Effect / timing |
| --- | --- |
| Edit a Current day field | |
| Apply reviewed targets | |
| Save a library recipe | |
| Save a Calendar plan | |
| Arm a plan | |
| Disarm a running plan | |
| Save a run record | |
| Change an endpoint used by several schedule blocks | |
| Press the header Stop all | |

Which of these proves physical isolation? __________

## 10. Compare two runs fairly

In History, choose a zone and an available comparison. Write:

- Same grow age or different ages? __________
- Same units, measurement type and time coverage? __________
- Actual history, saved run reference or current illustrative reference? __________
- Delivery measured, runtime-estimated or unknown? __________
- One observation supported by the data: __________
- One causal claim the data cannot establish: __________

If I create a run record today with a start date last month, does that reconstruct last month's targets? __________

## 11–13. What would you do next?

**11. Stale moisture:** the last valid reading is old and irrigation is holding. A friend says to lower the threshold to make it water. Your response: __________

**12. Tank disagreement:** the dashboard reports 80% full, but the installed low-level indication conflicts. Your response: __________

**13. Water won't stop:** the app says OFF but you can still see flow. Your immediate response, then investigation: __________

## Your real-system handover and commissioning record

Complete with the responsible installer/operator. Leave unknowns explicitly unknown. A demo cannot pass physical tests.

| Record | Actual evidence / result / person / date |
| --- | --- |
| Room, zone and physical labels agree | |
| Water path and each output's single owner | |
| Physical emergency isolation and who can use it | |
| Electrical/plumbing suitability and installer | |
| Independent protections and safe test results | |
| HA / integration / Controller versions | |
| Timezone, configured lights-on/off and actual lighting agree; lights' owner identified | |
| Backup location and recovery procedure | |
| Probe model, medium, location, units and freshness | |
| EC type and conversion method if applicable | |
| Plant count, substrate L/plant, emitters/plant | |
| Mapping saved AND acknowledged | |
| Installer-approved equipment catch test with Controller Watering OFF: runtime; individual catch volumes/locations | |
| Measured flow and configuration correction | |
| Correct outlet waters; unintended outlets stay dry | |
| Actual cessation of flow; no unwanted siphon | |
| Unknown/failure behaviour checked by safe procedure | |
| All failed checks resolved before automatic operation | |
| Approved local targets; reviewed enable and supervised first Controller cycle; agreed final state | |

## Five-minute daily record

1. **Identity and freshness:** room/zone, date/time, sensor/controller ages.
2. **State:** phase, Why / next action, last irrigation, actual output status where confirmed.
3. **Water:** per-zone/per-plant delivery with source labelled measured/estimated; unexpected variation.
4. **Feed and context:** available tank/feed readings, contradictions, light/climate changes and physical observation.
5. **Decision:** no change / investigate / one justified adjustment. Record before/after, rationale, expected observation and when to check again. Verify readback if applied.

Change more than one thing only when justified; record it so later comparisons do not pretend to isolate a single cause.

## Answers and explanations

**1.** 60% of the sample volume. The remainder includes solids and air. It is not a direct percentage of usable water left; a local probe does not establish zone uniformity.

**2.** Saturation; configured reference; drained container capacity. Useful conditions include medium, container dimensions/height, starting treatment, drainage protocol, probe placement/calibration and repeated results. A software field is not a physical measurement.

**3.** 40; 10 points; 10; 20%. A 10% relative loss from 60 is 6 points, giving **54% VWC**. “15% dryback” could be mistaken for either 15 points or 15% of the peak, which would be 9 points here. State the convention.

**4.** Feed; bulk substrate; pore-water; runoff/extract. EC does not identify each nutrient's concentration or prove nutrition is balanced. A bulk-to-pore transformation needs identified assumptions and validity; do not silently rename the value.

**5.** Verify timestamps, entity availability, communications/power, units and probe condition/placement; inspect the actual medium and independent evidence as appropriate. Resolve unreliable data before interpreting it as crop response. Do not override protections to force watering.

**6.** No: two axes have different units/scales. No: the dashed overnight EC is a reference connection, not a validated prediction. Exact demo observations depend on session/time; assessment is correct identification, not a fixed screenshot number.

**7.** 8 L/h per plant; **0.1 L = 100 mL per plant**; **2 L per zone**; **2% of substrate volume**. Ten identical completed shots estimate **20 L per zone / 1 L per plant**. These are runtime/flow estimates unless independently measured; they are neither uptake nor proof of equal delivery. Water distribution, drainage, uptake and probe sampling prevent a guaranteed two-point VWC rise. Conditional P2/P3 events and actual conditions make a fixed daily prediction unjustified.

**8.** The draft threshold/reference moves. Recorded observations are not rewritten. A threshold is used by a rule; editing it does not guarantee a shot, and local edits require reviewed application before reaching HA. Always check the actual field's meaning.

**9.** A local draft; writes reviewed HA targets then requires readback; browser/site/room library only; stores a draft plan without arming; requests next-local-lights-on activation without enabling Watering; scheduled return to manual at next lights-on; stores run metadata/reference and starts no shots; affects all referencing blocks when that plan is later applied under its workflow; stops through software for the selected room. **None proves physical isolation.** An active plan owns its effective targets; Current day is read-only for those targets.

**10.** Accept an observation supported by the available trace/record, with coverage limitations. Do not infer a reconstructed historical target series from a newly saved current reference. A difference between runs does not isolate the cause when crop age, climate, media, calibration or other variables differ.

**11.** Investigate and restore trustworthy sensing; follow the installation's safe fallback procedure. Do not force a shot by lowering a safety threshold.

**12.** Treat the contradiction as unresolved. Verify physical level safely, instruments, level calibration and mappings. Do not assume the optimistic percentage proves a safe pump supply; use installed protections and isolation as required.

**13.** Use the installation's physical shutdown/isolation procedure immediately. Once safe, inspect valve sticking, siphon, output feedback/mapping and conflicting controllers with competent help. Software OFF is not proof of water cessation.

### Teach-back and delayed check

Tomorrow, explain VWC and draft/apply/arm to someone without looking at these answers. About a week later, calculate dryback using new numbers, identify a stale trace and walk through physical shutdown with your local supervisor. These are proposed practice intervals; adapt to availability while revisiting rather than cramming.
