# HA-Irrigation-Strategy: feature-parity plan against Growlink and AROYA

Sources: Gemini watched-notes for #01–19, #21, #24, #25. Transcripts for #20, #22, #26–43. User screenshot of the AROYA irrigation Calendar. Every other video is known by title only, and items that come only from a title are tagged *(title only — confirm)*. Video numbers refer to `playlist.txt`. HA-IS status comes from the supplied inventory, checked against `docs/FEATURE_MATRIX.md`, `USER_GUIDE.md` and `MCP.md`.

## 1. Summary

- **Where we already beat them:** HA-IS runs a closed-loop P0–P3 engine. Copilot computes a fixed timer schedule and its suggestions take 24 h to apply (#08, #09). HA-IS also has multi-probe fusion with probe health, EC stack/dilute/flush, a source-water gate, a rescue floor, read-back-verified config, daily water caps and a bounded AI judge with a ledger. Batch protections are deeper (mix check, mix-pump power check, dead-head alert, stock drawdown), and there is no per-data-point subscription (#19).
- **Biggest in-scope gaps:**
  1. No multi-room irrigation timeline or calendar (Growlink valve chart #06, AROYA Calendar).
  2. No pump-capacity or exclusive-valve guard (#06, #07).
  3. Feed pH/EC calibration is recorded but not applied (#46, #47 title).
  4. No guided pump prime/calibrate routine (#43; #44, #45 title).
  5. No generic threshold alert builder (#21).
  6. No standalone timer programs outside the phase engine (#04, #06).
  7. No change history (#06).
  8. No custom dashboards (#53 title).
- Inline/direct injection (NDK #24–#47) is the one large hardware-dependent gap. It is optional and comes last.
- Every new item below is specified as `crop_steering.*` services plus entities, so AiGrow can drive it without the panel.

## 2. Parity matrix

Status key: **Have**, **Partial** or **Missing**.

### Irrigation

| Feature | Growlink / AROYA | HA-IS | Gap notes |
|---|---|---|---|
| Target-based crop-steering program (P0–P3 dryback, shot size, FC, target EC) | Copilot #08, #09 | Have | Ours is closed-loop. Copilot generates timers. |
| Absolute vs relative VWC (% of FC) entry | #08, #09 | Partial | Targets are absolute. A display/entry toggle is cheap. |
| Steering intent pre-populates targets | #08, #09 | Have | Veg↔gen slider. |
| Shot sizing from emitter flow × count × substrate | #08 | Have | Ours uses substrate volume. Catch test exists. |
| Overnight failsafe (VWC < X → water, re-evaluate) | #08 | Have | Rescue floor / P3 emergency shot. |
| Autopilot AI adjustments + Suggestions tab | #06, #08, #09 | Have | Learner + AI judge with envelope. |
| Suggestion & change history per program | #06 (clock icon) | Missing | `FEATURE_MATRIX` says there is no historical setpoint audit. |
| Simple / One-off / Recycle timers, time-of-day window (All/Day/Night/Custom), sync time | #04, #06; #66, #69 *(title only — confirm)* | Partial | Only P2 timed-with-guards and the test shot. No free-standing timer program. |
| Valve chart: all scheduled events on a timeline, hover detail | #06 | Missing | Calendar covers grow plans, not shot events. |
| Irrigation calendar: rooms × zone-range rows, lights band, done/upcoming/error/warning colours, now line, 12/24/48 h zoom, error banner | AROYA screenshot; #77 *(title only — confirm)* | Missing | Highest-visibility gap. |
| Pump-capacity warning when concurrent valves exceed pump | #06 (narration) | Missing | Safety. |
| "Valve (Exclusive)" output type | #07 | Missing | Interlock against two zones on one pump. |
| Blueprints (targets change across the cycle) | #09, #16 | Have | Grow plans (days 1–366, draft→arm). |
| Presets / copy rule groups | #51, #52 *(title only — confirm)* | Partial | Recipe library is browser-local only. |
| Dosing recipe attached to irrigation program | #08 | Partial | Feed recipes run per room and are not tied to a program. |
| Push config + result count ("1 success, 0 errors") | #04, #11 | Have | Read-back verification. |

### Substrate and feed sensors

| Feature | Growlink / AROYA | HA-IS | Gap notes |
|---|---|---|---|
| Sensor average/aggregate as program input | #08 ("Substrate Moisture Avg"); #63 *(title only — confirm)* | Have | Fusion with outlier drop beats a plain average. |
| Per-sensor offset ("Adjustment") to match a handheld | #13 | Partial | Fusion offsets are internal. No user offset with audit. |
| Substrate equation per probe (TDR: Rockwool vs All Other Soilless) | #18 | Missing | Matters only where raw permittivity is exposed. |
| Probe placement guidance | #23 *(title only — confirm)* | Missing | Help content. |
| Sensor input calibration (mobile) | #68 *(title only — confirm)* | Partial | Two-point record only. |
| Feed pH probe calibration | #40 (sample spigot); #46 *(title only — confirm)* | Partial | Recorded, not applied. |
| Feed EC probe calibration | #47 *(title only — confirm)* | Partial | Recorded, not applied. |
| Inline flow meter feeding the controller | #35, #40 | Missing | We have catch test and commanded litres, but no meter reconciliation. |
| History query: ranges, data-point picker, zoom, chart cards | #16 | Have | Timeline, Compare, CSV. |
| Units: EC vs PPM (500 scale), °C/°F, 12/24 h | #17 | Partial | L/gal toggle exists. No PPM. |

### Dosing and fertigation

| Feature | Growlink / AROYA | HA-IS | Gap notes |
|---|---|---|---|
| Dosing recipes | #14; #65 *(title only — confirm)* | Have | 12 recipes + weekly schedule. |
| Batch tank autofill from level sensor + recipe | #14 | Have | Fill→premix→dose→postmix. |
| Batch tank overfill protection | #56 *(title only — confirm)* | Have | 102% cutoff, fill timeout. |
| Batch tank dry-run protection | #59 *(title only — confirm)* | Have | Reservoir min 8/12%, dead-head alert. |
| Pump config: head model + dial → max GPH; solution type (nutrient / pH up / pH down) | #43 | Partial | Calibrated flow entity only. No pump catalogue. |
| Pump priming routine | #44 *(title only — confirm)* | Missing | |
| Pump calibration routine | #45 *(title only — confirm)* | Missing | |
| pH targeting algorithm | #43 | Have | Opt-in pH auto-correct with lockouts. |
| Inline/direct injection skid (flow-proportional injectors, blend tank, pH/EC monitor loop) | #24, #40, #43 | Missing | We dose by batch only. |
| Continuous outflow pH/EC monitoring | #40 | Partial | Post-batch mix check only. |

### Alerts

| Feature | Growlink / AROYA | HA-IS | Gap notes |
|---|---|---|---|
| Threshold alert: sensor, above/below, threshold, time window, min duration, recipients, push | #21 | Missing | We only have coded CS-xxx alerts. |
| Controller offline > 20 min → email | #01, #03; #50 *(title only — confirm)* | Have | Offline/stale heartbeat. |
| Module offline count | #16, #17, #18 | Have | Probe silent / left-out. |
| Alert inbox | #17 | Partial | HA notifications + Repairs. No unified inbox entity. |
| Email + SMS gateway + push | #21; #75 *(title only — confirm)* | Partial | Per-phone push routing exists. Email depends on HA notify. |

### Dashboards, devices, mobile

| Feature | Growlink / AROYA | HA-IS | Gap notes |
|---|---|---|---|
| Rooms overview: health, modules online, alerts | #07, #16, #17 | Have | Status › All rooms. |
| Custom real-time dashboards | #53 *(title only — confirm)* | Missing | |
| Days-until-harvest / stage / plant count tiles | #06, #08 | Partial | Plan day exists. No DTH entity. |
| System status page | #49 *(title only — confirm)* | Partial | Heartbeat + Repairs. |
| Device list, rename, device type, "Not In Use" | #07; #60, #72, #73 *(title only — confirm)* | Have | Setup wizard mapping. |
| Modbus expansion modules (addressing, auto-discovery) | #10 | Missing | Everything goes through HA entities. |
| 4–20 mA pH/EC, pulse flow-meter wiring | #32, #35 | Partial | Possible via HA/ESPHome. Not documented. |
| Firmware update from portal | #64 *(title only — confirm)* | Partial | ESPHome/HA handle it. Out of our lane. |
| Mobile dashboard / timers / schedules | #69, #70, #74 *(title only — confirm)* | Have | Phone bottom bar. |

### Excluded (AiGrow)

- Users, roles, passwords, ownership: #01, #02, #54, #58.
- Subscription and billing: #19.
- Manual tasks: #57, #67, #71.
- Climate rules: dehumidifier #05, humidifier #15, CO2 #20, heating #61, cooling #62, BACnet HVAC #55, room setpoints drawer #16.
- Lighting: schedules #11, temperature override #12, lighting shutdown temp #03.
- Climate sensor offsets: #13. The offset pattern is reused for substrate/feed probes in G9.
- FloEnvy plant/batch tracking and harvest scale: #02, #17, #22.
- NDK plumbing and assembly: #25–#29, #31, #33, #34, #37–#39, #42, #76. These are hardware-only, with no software feature.

## 3. Gap backlog

**G1 Pump-capacity and exclusive-valve guard.** S/M.
- **Build:** Per pump/source, add `max_flow_lph` and `max_concurrent_zones`, plus a per-zone `exclusive_group`. The controller queues a shot instead of overlapping it. Add `sensor.crop_steering_<room>_pump_load_pct`, `binary_sensor.<room>_shot_queued`, and alert CS-code "shot delayed: pump capacity". The setup save rejects configs whose worst-case zone sum exceeds the pump.
- **Why:** Growlink only warns visually (#06). We can prevent pressure collapse and uneven shots outright.
- **Dependencies:** Zone dripper flow, which already exists.
- **AiGrow surface:** Setup keys via `crop_steering.setup_save`. Queue state as entities.
- **Accept:** A test with 2 zones × 60% capacity runs them serially, logs the queue, and fires no overlap.

**G2 Applied feed pH/EC calibration.** M.
- **Build:** The two-point record becomes slope/offset applied to the feed pH/EC readings. Publish `sensor.<room>_feed_ph_corrected` and keep the raw value. Add a guided wizard (buffer 4/7, 1.413/2.77 mS) with stability detection. Add `calibration_due` binary_sensor + CS alert after N days. Add services `crop_steering.calibration_start/capture/commit/revert`.
- **Why:** The mix check and pH auto-correct currently trust an uncorrected probe (#40 spigot workflow; #46, #47 *(title only — confirm)*).
- **Dependencies:** None.
- **AiGrow surface:** Services + corrected entities.
- **Accept:** With a known offset injected, the corrected value lands within ±0.05 pH; revert restores raw; the due alert fires on schedule.

**G3 Guided pump prime and calibration.** M.
- **Build:** A pump catalogue for model/dial → nominal flow (#43, H.E. Anderson A3/P1/P2/H4), plus `solution_type` (nutrient / pH up / pH down / additive). Services:
  - `crop_steering.pump_prime(pump, seconds)`: interlocked, with mix pump off and room dosing locked.
  - `crop_steering.pump_calibrate(pump, seconds)` + `pump_calibration_commit(ml_measured)`, which writes the calibrated flow and keeps history.
  - Wizard on Equipment › Dosing.
- **Why:** Today the user has to hand-build a flow entity (#44, #45 *(title only — confirm)*).
- **Dependencies:** Existing dosing protections.
- **AiGrow surface:** Services, `sensor.<pump>_calibrated_ml_min`, `<pump>_last_calibrated`.
- **Accept:** A 30 s calibration with 150 ml entered gives 300 ml/min, and the next dose uses it.

**G4 Measured-flow reconciliation.** M.
- **Build:** An optional feed flow-meter entity per room or zone (pulse/L via ESPHome; #35, #40). Compare commanded vs metered litres per shot. Add `sensor.<zone>_flow_ratio` and CS alerts "blocked line" (<80%) and "leak/stuck valve" (>120%, or flow with no valve open). This is already listed as the top next step in FEATURE_MATRIX.
- **Why:** It is the only independent proof that water reached the plants.
- **Dependencies:** G1 queue, so that per-shot attribution is clean.
- **AiGrow surface:** Entities + alert events.
- **Accept:** A simulated 50% meter shortfall raises the blocked-line alert within one shot.

**G5 Irrigation calendar / timeline.** L.
- **Build:** A new page, Irrigation › Timeline, modelled on AROYA:
  - Day picker and week strip, 12/24/48 h zoom, now line.
  - One row per room, expandable to zones or zone ranges.
  - Lights-on band.
  - Event blocks: grey done, blue planned, red error, orange warning.
  - Error banner "N schedules with errors" with axis markers.
  - Filter by room/stage, search by zone or device ID.
- **Backend:** `crop_steering.timeline_get(start, end, rooms)` returns past shots (Recorder), planned shots (engine projection + G7 timers), errors and lights windows. The page holds no logic.
- **Why:** One glance shows the facility's watering day, including pump overlap and missed shots (#06; AROYA screenshot; #77 *(title only — confirm)*).
- **Dependencies:** A shot-event log (exists), an engine projection API, and G1 for overlap flags.
- **AiGrow surface:** `timeline_get` is the contract AiGrow renders.
- **Accept:** Demo mode renders 6 rooms × 48 h, done/planned blocks match the Recorder, an induced CS error appears red with the banner count, and the phone width works.

**G6 Irrigation-scoped threshold alert rules.** M.
- **Build:** Rule store `crop_steering.alert_rules`. Each rule has:
  - source (zone VWC/EC/temp, feed pH/EC, tank level, stock, flow ratio, controller heartbeat)
  - above/below, threshold
  - window: All / Lights-on / Lights-off / Custom
  - min duration, routing via the existing per-phone matrix, active toggle
- **UI:** A plain-sentence summary and a threshold visual, as in #05, #14 and #21.
- **Services:** `alert_rule_set/delete/test`.
- **Entities:** `binary_sensor.crop_steering_rule_<id>`.
- Climate sensors are not offered as sources.
- **Why:** Growers want their own lines, e.g. "tank < 30% for 10 min" (#21; #50 *(title only — confirm)*).
- **Dependencies:** The notifications stack.
- **AiGrow surface:** CRUD services + binary sensors.
- **Accept:** A rule with a 2 min min-duration does not fire on a 1 min spike, fires on a 3 min breach, and the test push arrives.

**G7 Free-standing timer programs.** M.
- **Build:** Per zone or zone group, timer types One-off (start, duration), Recycle (duration, interval) and Simple (duration, frequency), with a window (All/Lights-on/Lights-off/Custom) and a sync time (#04, #06). Timers run through the same guards as the engine: kill switch, daily max, pump queue (G1), source-water gate.
- **Mode:** `select.<zone>_irrigation_mode` = steering / timer / off.
- **Services:** `timer_program_set/delete`.
- **Why:** Mothers, veg, clones and growers with no probes need plain timers (#66, #69 *(title only — confirm)*).
- **Dependencies:** G1.
- **AiGrow surface:** Program CRUD + mode select.
- **Accept:** "08:00–12:00 every 30 min for 2 min" produces 8 shots on the timeline (G5) and stops at the daily max.

**G8 Change history.** M.
- **Build:** An append-only log of every setpoint, plan, recipe and setup change with source (user / learner / AI judge / MCP), old→new and reason. Expose `crop_steering.history_changes(room, since)` and a "History › Changes" view. Add a per-program clock icon, as in #06.
- **Why:** "Why did zone 3 change?" is answerable today only from the AI ledger.
- **Dependencies:** None.
- **AiGrow surface:** Query service.
- **Accept:** A learner nudge and a manual edit both appear with correct attribution after a restart.

**G9 Substrate/feed probe offset and calibration curve.** M.
- **Build:** A per-probe user offset (VWC/EC/temp) with a "match handheld" helper (#13 pattern). Add an optional per-probe equation (linear/quadratic raw→VWC) with substrate presets such as rockwool and coco/soilless (#18). Offsets are logged to G8.
- **Why:** Mixed probe fleets and drift.
- **Dependencies:** Fusion keeps its own internal step offsets.
- **AiGrow surface:** Setup keys + `sensor.<probe>_vwc_corrected`.
- **Accept:** Entering handheld 52% vs probe 49% sets +3 and the fused value moves without a step alert.

**G10 Server-side presets and copy.** S/M.
- **Build:** Move the recipe library and steering presets into the integration store. Add `preset_save/apply` and `copy_config(from_room|zone, to, sections)` (#51, #52 *(title only — confirm)*). Preview before apply.
- **Why:** Presets are lost per browser today, and AiGrow needs them centrally.
- **Accept:** A preset saved on desktop appears on the phone. Copy previews a diff and writes with read-back.

**G11 Custom irrigation dashboards.** L.
- **Build:** Do not build a dashboard engine. Ship a Lovelace card pack (zone gauge, dryback chart, tank/stock, timeline strip) bound to existing entities, plus a "Create dashboard" button that writes an HA dashboard from a template (#53 *(title only — confirm)*).
- **Why:** Growers want wall/tablet views. HA already has the editor.
- **Dependencies:** G5 for the timeline strip.
- **AiGrow surface:** Entities only, so nothing new.
- **Accept:** The generated dashboard renders for 2 rooms, and the card resource has `?v=` bumped.

**G12 Inline/direct injection mode.** L.
- **Build:** A dosing mode `inline` in which injector pulses or ml/L track a metered water flow (G4). There is a mixing-chamber delay, a monitor-loop pH/EC check with abort-to-flush on deviation, and an optional air-pressure sensor for air-driven injectors (#40, #42, #43).
- **Why:** This is the NDK model (#24–#47) and needs no batch tank.
- **Dependencies:** G2, G3, G4. It also needs hardware we do not have.
- **AiGrow surface:** Dosing mode select + `inline_status` sensor.
- **Accept:** On a test rig, outflow EC stays within ±0.1 mS of target across a flow step change.

**G13 Modbus and sensor onboarding kit.** M.
- **Build:** Documented, tested HA Modbus / ESPHome templates for common DIN I/O (e.g. Metz BMT modules, #10), 4–20 mA pH/EC transmitters (#32, #35) and pulse flow meters. Add a setup-wizard check that flags unit/scale mismatches.
- **Why:** Commercial skids use these parts.
- **Accept:** A template-based EC transmitter maps in the wizard and passes range checks.

**G14 Probe placement guidance.** S.
- **Build:** A Help page and an inline Probes-page panel covering depth, distance from dripper and pot geometry (#23 *(title only — confirm)*). Link it from the probe-health "out of range" alerts.
- **Accept:** The link is reachable from the alert.

**G15 Units: PPM 500/700, °F.** S. A display-only preference (#17) with the store kept in mS/cm and °C. **Accept:** A round-trip shows no drift.

**G16 Grow summary entities.** S.
- **Build:** `sensor.<room>_grow_day`, `_days_to_harvest`, `_stage`, all from the plan (#06, #08).
- **Why:** AiGrow and dashboards need them.
- **Accept:** The values match the plan calendar.

**G17 System status page.** S.
- **Build:** One page with controller, add-on, every mapped entity's last-seen, % online, and open CS alerts. Add `sensor.crop_steering_system_health` (#16, #17; #49 *(title only — confirm)*).
- **Accept:** Unplugging one probe drops % online within one loop.

## 4. Phased roadmap

- **Phase 1, safety and dosing truth:** G1 pump guard, G2 applied pH/EC calibration, G3 prime/calibrate, G14 placement help. These are low UI risk and close every dosing/tank safety hole the competitors cover.
- **Phase 2, visibility and control:** G4 flow reconciliation, G5 timeline/calendar, G6 alert rules, G7 timer programs, G8 change history, G17 status page. G5 depends on G1 and G7 projections, so build `timeline_get` first and the page second.
- **Phase 3, fleet ergonomics:** G9 probe curves/offsets, G10 server presets/copy, G11 dashboard pack, G15 units, G16 grow entities.
- **Phase 4, hardware-dependent:** G12 inline injection and G13 Modbus kit, only when a skid is on the bench.

## 5. Not yet reviewed (title only)

Confirm these when the quota resets. Videos marked [excl] fall in excluded topics; review them only to confirm nothing irrigation-relevant is hidden in them.

- **Sensors:** #23 Substrate sensors in round pots
- **NDK dosing:**
  - #44 Priming the Pumpers
  - #45 Calibrating the Pumpers
  - #46 Calibrating the pH probe
  - #47 Calibrating the EC Probe
- **Mobile:**
  - #48 Mobile Sensor Triggers
  - #68 Mobile Sensor Input Calibration
  - #69 Mobile Timers
  - #70 Mobile Schedules
  - #72 Mobile Devices Tab
  - #73 Mobile Hardware Tab
  - #74 Mobile Dashboard
  - #75 Mobile Alerts
- **Portal:**
  - #49 System Status
  - #50 Offline Alerts
  - #51 Copying Rule Groups
  - #52 Presets
  - #53 Custom Real Time Dashboards
  - #56 Batch Tank Overfill Protection
  - #59 Batch Tank Dry Run Protection
  - #60 Devices Tab
  - #63 Sensor Aggregate
  - #64 Updating Controller Firmware
  - #65 Dosing Recipe
  - #66 Simple Timer Program
- **Hardware:** #76 DIN Rail Mount
- **AROYA:** #77 AROYA Platform Overview. Only the Calendar screenshot was reviewed.
- **[excl]:**
  - #54 User Roles
  - #55 BACnet HVAC
  - #57 Manual Task Overrides
  - #58 Password reset
  - #61 Heating
  - #62 Cooling
  - #67 Manual Tasks
  - #71 Mobile Manual Tasks

## 6. Where HA-IS is ahead (keep, don't regress)

- **Closed-loop phase engine** with dryback/peak detection. Copilot output is a static timer list that needs 24 h to apply changes (#09).
- **Multi-probe fusion:** median/mean, outlier drop, silent probe set aside, step-free offsets, probe health (silent/stuck/out-of-range). Growlink offers a single sensor or a plain average (#08).
- **EC stacking, dilute and flush**, the source-water pH/EC gate, and **daily min/max water per zone**.
- **Rescue floor with AI back-off**, and AI judge with envelope, budget and ledger. Autopilot is opaque (#08).
- **Read-back-verified config writes:** Growlink reports only success/error counts (#04).
- **Timed manual override**, room kill switch and zone pause.
- **Grow plans:** draft → arm at lights-on, exceptions.
- **Batch dosing depth:** post-mix EC/pH check, mix-pump power check, dead-head alert, switch read-back, stock drawdown and low-stock alerts.
- **Analytics:** CWSI, root-zone temp, run comparison aligned to grow age, runoff estimator, CSV.
- **Alerting and access:**
  - CS-coded alerts with HA Repairs, per-phone routing
  - Local-first: no per-data-point billing (#19), no cloud dependency for control
  - MCP server for assistant-driven, previewed config changes
