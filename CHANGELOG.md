# Changelog

All notable changes to Crop Steering will be documented in this file.

**Two views per release.** Each version leads with **🌱 In plain English** — what changed and why it
matters, written so anyone can follow it without knowing the internals — followed by **🔧 Technical
notes**, the entity- and code-level detail for developers and AI agents working on the repo.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.18.1] - 2026-10-28

3.18.1 — simpler README and first-run guide, one docs index, internal notes archived, bug report form; dashboard: readable Today strip on phones (#236), decluttered daily plan card (#239).

Pair: **controller 3.18.1**. **C1: documentation and two dashboard display fixes.** The controller, engine, integration runtime, entities, add-on options and persisted state are unchanged; the dashboard bundle changes only how two screens are drawn. **Approved rehearsal, no staging soak:** the owner approved releasing and promoting this candidate on 2026-10-27, and on 2026-10-28 approved including the two dashboard display fixes (docs/RELEASING.md step 5, `approved-rehearsal`). No staging photoperiod and no visual check on a staging room is claimed.

### 🌱 In plain English

- **Readable Today strip on a phone.** Each watering (the dashboard calls it a shot) is a thin tick on a phone instead of a pile of pills, and the hour labels no longer overlap the "now" marker.
- **A tidier daily plan card.** The chart key keeps Recorded, Target and Draft; the rest is explained in the workings, and the phase table folds in with them.
- **Simpler documentation.** A shorter README and first-run guide, one documentation index, internal notes moved to an archive, and a bug report form on GitHub.
- **Nothing else changes on your box.** Updating changes no setting and no watering behaviour.

### 🔧 Technical notes

- #236 `fix(dashboard)`: below 720 px a shot on the Today strip is a 3 px tick (was an 8 px minimum block); the axis drops an hour label within 18% of the span of the "now" chip (`frontend/src/components/shot-timeline.css`, `frontend/src/pages/today.tsx`).
- #239 `fix(dashboard)`: the plan card's previous grow-day peak and low move to the Earlier days toggle's tooltip; the chart key keeps Recorded, Target and Draft; the on-chart "Re-water" label is removed; the phase table folds into "Phase by phase, and how this is worked out"; gauge footers wrap (`frontend/src/components/planning-curve.tsx`, `frontend/src/styles.css`, `frontend/src/components/hmi.css`, `frontend/scripts/verify-steering-visuals.mjs`). The three committed `dashboard.html` bundles are rebuilt from `frontend/src`.
- Docs (#234, #237, #238, #240, #241, #242, #243): short README, `docs/FIRST_RUN.md`, `docs/README.md` as the one index, internal notes under `docs/archive/` and `docs/dev/` (moved pages keep a "This page moved" stub), 2.x changelog sections in `docs/archive/CHANGELOG-2.x.md`, `.github/ISSUE_TEMPLATE/bug_report.yml`, `ROADMAP.md` and `docs/SYSTEM_MAP.md`. #240 changed only path comments in `addons/f2_control/f2_control/guards.py`, `zone_history.py` and `frontend/src/lib/parity-types.ts`.
- CI (#233, #235, #244): GitHub Actions bumped, Dependabot targets `testing`, the Academy browser test waits for the new video group before seeking.
- No change to controller, engine or integration code, entity ids, add-on options or `/data/state.json`.

## [3.18.0] - 2026-10-24

**⚠️ This is a very large upgrade.** Almost every page of the dashboard is new or
rebuilt: timer programs, presets, alert rules, a new History section, feed and pump calibration, pump
supply sharing, quiet hours and an Upgrade report.

**If you are running this on a live grow, do NOT just click update** unless you have time for a big
configuration session straight after. Watering will not stop, but there is a lot to set up and check.

**Get your AI to configure it from the new docs.** Point your AI assistant (Claude, ChatGPT, or any
assistant connected through the Crop Steering MCP server) at the new documentation and have it work
through the Upgrade report with you, one line at a time, asking you before each save.

**Your settings come across as far as they can.** The update keeps every zone watering and dosing
exactly as before, and carries your current settings into the new features wherever it can do that
without guessing. Nothing new that waters or doses is switched on for you.

- **Carried across:** every zone keeps watering by steering; each recipe stage you had edited is
  copied as a preset; a "before 3.18 update" preset of your current settings is saved as a rollback
  point; temperatures in °F if Home Assistant uses °F; every notification recipient; your pH up/down
  pumps keep their role; your earlier setting changes, stock moves, calibrations and dosing records
  are imported into History; a room with no feed EC probe keeps the old 3.0 mS/cm assumption so it
  flushes as before.
- **Needs you:** the irrigation supply (each pump's real flow, how many zones it feeds at once, its
  flow meter: nothing is saved until you save it); the 2-point feed pH and EC probe calibration;
  the solution and a pump calibration for each nutrient pump; ppm instead of mS/cm if that is how
  you work; automations that still use a retired entity; grow-plan recipes saved only in your
  browser (export them). Optional: alert rules, quiet hours, camera, CO2 and light panels, new
  dashboards.
- Each room's **Upgrade report** lists exactly what was carried and what needs you: Crop Steering →
  Settings → System status, and a card in Home Assistant's Settings → Repairs.

**What it looks like.** Screenshots of the 3.18 dashboard running on its built-in demo data (sample
rooms, not a real facility); the phone view is in the dark theme.

- **Status: all rooms.** Every room and every zone on one page: phase, moisture and water today.

  ![Status, all rooms](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/v3.18.0/docs/screens/status-all-rooms-desktop-light.png)

- **Zone page.** One zone in full: moisture, EC, what it is waiting for and every shot today.

  ![Zone page](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/v3.18.0/docs/screens/zone-desktop-light.png)

- **Timeline.** The day's phases and shots for a room on one line, so you can see what happened when.

  ![Irrigation timeline](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/v3.18.0/docs/screens/irrigation-timeline-desktop-light.png)

- **Timer programs.** Each zone can water by steering (as before), by timer programs, or be off.

  ![Timer programs](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/v3.18.0/docs/screens/timer-programs-desktop-light.png)

- **Grow plan & presets.** Save a room's or a zone's targets, phase timing and limits, and copy them to other rooms or zones.

  ![Grow plan and presets](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/v3.18.0/docs/screens/grow-plan-presets-desktop-light.png)

- **History: explorer.** Any reading, any room, any period, on one chart.

  ![History explorer](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/v3.18.0/docs/screens/history-explorer-desktop-light.png)

- **History: changes.** Every setting change, who made it and when, including what the upgrade carried across.

  ![History of changes](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/v3.18.0/docs/screens/history-changes-desktop-light.png)

- **Feed & dosing.** Each dosing pump with its solution, its stock tank and its doses.

  ![Feed and dosing](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/v3.18.0/docs/screens/feed-dosing-desktop-light.png)

- **Feed pH/EC calibration.** A guided 2-point calibration at the tank; nothing changes until you commit it.

  ![Feed probe calibration](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/v3.18.0/docs/screens/feed-calibration-desktop-light.png)

- **Setup: pumps & valves.** Your pumps, main line and valves, and the new pump supply: real flow and zones at once.

  ![Setup, pumps and valves](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/v3.18.0/docs/screens/setup-pumps-valves-desktop-light.png)

- **Alert rules.** Your own notifications, with a preview of how often each would have fired.

  ![Alert rules](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/v3.18.0/docs/screens/alert-rules-desktop-light.png)

- **System status.** The health of every part, and each room's Upgrade report.

  ![System status](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/v3.18.0/docs/screens/system-status-desktop-light.png)

- **AI assistant.** The exact instructions it works from, your room notes and what it costs.

  ![AI assistant settings](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/v3.18.0/docs/screens/ai-assistant-desktop-light.png)

- **On your phone.** Every page works on a phone in the grow room.

  ![Phone view](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/v3.18.0/docs/screens/status-all-rooms-phone-dark.png)

**Update the integration BEFORE the add-on.** Update Crop Steering in HACS first and restart Home
Assistant, then update the Crop Steering controller app. The integration runs the upgrade and writes
the Upgrade report; the 3.18 controller reads what it writes.

**Upgrade guide and AI setup.**

- [3.18 upgrade report, line by line](docs/UPGRADING.md): one section per Upgrade report line, written so an AI can
  follow it step by step.
- [Upgrade to 3.18: the plan](docs/UPGRADING-TO-PARITY.md): what stays the same, a first-hour
  checklist and how to go back.
- [Set up an install with an AI assistant](docs/AI-SETUP.md): start read-only and approve each change,
  and [Configure Crop Steering through MCP](docs/MCP.md): connect an assistant to your Home Assistant.
- [User guide](docs/USER_GUIDE.md), [AI assistant](docs/AI_ASSISTANT.md) and the
  [Crop Steering Academy](https://jaketherabbit.github.io/HA-Irrigation-Strategy/learn/).

Pair: **controller 3.18.0**. **C3: the parity release.** The controller, the engine, the integration,
entities, add-on behaviour, persisted state and the dashboard all change. **Approved rehearsal, no
staging soak:** the owner approved releasing and promoting this candidate without the staging soak
on 2026-10-23 (docs/RELEASING.md step 5, `approved-rehearsal`). It passed CI (including the real Home
Assistant tier on the newest and oldest supported versions, the add-on image builds and the controller
container smoke), a 216-visit route sweep of the dashboard and a final code review. **Nothing in this
release has been run on real plumbing**: no staging photoperiod, no catch test and no fault drills.

### 🌱 In plain English

**New in 3.18 (the parity release)**

- **Timer programs and watering modes.** Each zone waters by steering (as before), by timer
  programs, or is off.
- **Pump sharing and flow checks.** Say how much each pump really delivers and how many zones it can
  feed at once; shots queue instead of starving each other. A flow meter checks each shot's water
  against what was asked for, and the controller looks for leaks.
- **Calibration.** A guided 2-point feed pH and EC probe calibration, and a prime-and-calibrate wizard
  for each dosing pump. Nothing changes until you commit it.
- **Presets and copy.** Save a room's or a zone's targets, phase timing and limits as a preset and
  copy them to other rooms or zones. Grow-plan recipes saved in your browser import as presets in one
  click.
- **History.** An explorer for any reading over any period, a change journal of every setting change
  (who, when, and what the upgrade carried across) with put back and undo, and a compare view.
- **Alerts.** Your own alert rules, tested against yesterday before you save them, an alerts inbox and
  quiet hours per phone.
- **Display and dashboards.** Display units (ppm or mS/cm, °F or °C), and dashboards made from
  templates.
- **System status.** The health of every part and each room's Upgrade report in one place.
- **Feed & dosing.** Every dosing pump with its solution, stock tank and doses; dosing refusals are
  recorded with their reason.
- **The upgrade itself.** Your settings carried across where that was safe, with a report of the rest.

**Fixed**

- A shot that fails after its valve opened now counts the water it delivered.
- The controller reads the pump, the main-line valve and the zone valve back ON at the start of every
  shot. A dead relay or an offline plug now cancels the shot with an alert instead of counting water
  that never flowed, and a zone that keeps failing backs off.
- P0 now waits for the plants to start drinking after lights-on. Only a zone at its rescue floor skips
  the wait (#195). Rooms that skipped P0 every morning now take their first shot later, up to the
  zone's P0 maximum wait.
- A zone with a dead moisture probe gets its minimum daily water again, only with the lights on and
  outside P0. Its fallback timer shot no longer fires at night or outside P1/P2.
- With no feed EC probe and no recipe feed EC, the controller no longer invents a feed EC of 3.0 on a
  new room; such a room gets one card saying EC flushing is off. Rooms that had it before the update
  keep the 3.0 assumption (see the Upgrade report).
- A failed read of the shot-length cap no longer lifts it to 900 s, an unreadable feed EC/pH band
  holds the shots, and a failed Home Assistant read or write is never taken as a real value.
- An error in one room's pass no longer stops the other rooms, and a shot-start error can no longer
  wedge the controller.
- Lights-on and lights-off set to the same hour are not used.
- A setpoint the controller failed to write is no longer credited to it in History.
- The phase sensor never makes up a phase, and the controller says so when it has no next-shot
  estimate.
- One source of truth for the derived watering values (shot length, adjusted re-water point, EC ratio,
  room averages, shots today). Settings that only fed retired sensors are hidden, and Repairs names any
  automation that still uses one.
- The dashboard shows the controller's own dryback, peak and next shot, its own limits, EC band and
  tank marks, reads water volumes in the unit Home Assistant reports, shows every time on Home
  Assistant's clock, and its links land where they say.
- All rooms is a visual page with slabs and tanks, without duplicate pickers.
- The dosing form uses the room's own dose limits.
- `apply_recipe` and `save_recipe` act on one room, and the Recipe stage select shows a stage only once
  it is applied.
- Long-term history reads the sensors from this room's archived runs.
- The MCP server accepts what the integration accepts (pumps, valves, probe units).

**Deprecated.** The named-stage recipe system (the Recipe stage and Irrigation phase selects, and the
`apply_recipe` and `save_recipe` services) is marked as going away in **a future major release**. It
still works; the first use after a restart raises a Repairs notice saying what to use instead.

**Documentation.** A shorter README, a [documentation index](docs/README.md), one page per new feature
in [docs/features](docs/README.md#use-it-every-day), the system map and ranked system audit, and help text that
follows the 3.18 page names.

### 🔧 Technical notes

- **Upgrade migration:** `custom_components/crop_steering/migration.py`, a run-once, versioned ledger
  (`crop_steering.migration` store) per room and site. Every seeded value is journaled as
  `config.changed` with actor `migration`; old stores are read only. The report is served by
  `crop_steering.migration_report` and raised as the Repairs issue `upgrade_report_3_18` (CS-616)
  while a room has a "Needs you" line. M15 keeps controller 3.17.0's 3.0 mS/cm feed EC for a room with
  no feed EC probe and no recipe feed EC. Row by row: [docs/UPGRADING.md](docs/UPGRADING.md).
- **Parity backend (#230):** one ordered GuardChain for every shot check, with dosing refusals through
  it and journalled; pump capacity and an exclusive-valve queue; timer programs and per-zone watering
  modes (an unparseable `timers_config` falls back to the engine under each zone's mode); timed pump
  prime and calibration runs; metered-vs-commanded water reconcile per shot (`flow.py`, baseline from
  the pass's own reading, never a read before the pump opens) and CS-319 leak detection; calibrated
  feed probes for the source-water gate, mix check and pH correct; journal outbox and backfill;
  integration APIs for site, timers, presets and copy, alert rules and inbox, changes, timeline, system
  status, dashboards, probe offsets and calibration. New error codes CS-612, CS-615, CS-616.
- **Parity dashboard (#230):** Feed & dosing, Pumps & valves, Prime & calibrate a pump, Feed
  calibration, Stock, Water & flow, Timer programs, History explorer/changes/compare, Alerts,
  Notifications, System status and AI pages. Bundles rebuilt deterministically (three copies
  byte-identical). Route sweep: every page × desktop/phone × light/dark × 3.18/3.17 demo backends,
  216 of 216 visits clean.
- **Fix pull requests merged through #229:** #196 All rooms visual slabs and tanks; #197 shot error
  after the valve opened counts its water; #198 docs follow 3.17 section names; #199 water volumes in
  Home Assistant's unit; #200 dosing form uses room dose limits; #201 failed shot-cap read no longer
  lifts the cap (CS-203); #202 unreadable feed EC/pH band holds shots; #203 blind fallback shot only
  with lights on, in P1/P2; #204 one room's error no longer stops the others (CS-212); #205
  `apply_recipe`/`save_recipe` scoped to one room; #206 recipe stage select shows a stage once applied;
  #207 `current_phase` never invents a phase; #208 pump, main line and valve read back ON at shot start
  (CS-302/303/304, backoff after 3 cancelled shots); #209 equal lights-on/off hours unused; #210
  shot-start error cannot wedge the controller (CTL-032); #211 controller's own dryback, peak and next
  shot on the dashboard; #212 system map and ranked audit; #213 Academy local URL; #214 MCP accepts
  pumps, valves, probe units; #215 failed Home Assistant read/write never a real value; #216 blind-zone
  minimum daily water and no invented feed EC (CTL-031, CTL-008, CS-907); #217 every dashboard and
  Academy browser check on pull requests; #218 no next-shot estimate said so; #219 dashboard links land
  where they say; #220 `history_long` reads this room's archived runs; #221 recipe system deprecated
  (CS-613), stage applied once, dashboard follows the controller's steering mode; #222 one source of
  truth for derived watering values (`shot_length.py`, CS-614); #223 failed setpoint write takes back
  its claim (CTL-035); #224 actions pinned to commits, honest `run_ci.sh`, faster container smoke;
  #225 dashboard one source for limits, bands, time and readability; #226 README and feature matrix;
  #227 P0 bypass only at the rescue floor (#195); #228 help text catch-up.
- **Deprecation (#221):** new `deprecations.py` (`note_deprecated`): a log warning on every use and
  one Repairs issue (`deprecated_<key>`, CS-613) per Home Assistant run. `apply_recipe` no longer
  calls `select.select_option` (INT-003); `buildRoom` picks the EC target family as the controller's
  `_veg()` does (INT-014).
- **Documentation:** new `docs/README.md`, `docs/UPGRADING-TO-PARITY.md`, `docs/AI-SETUP.md`,
  `docs/features/*.md`; `docs/ENTITIES.md` gains the 3.18 entities. The screenshots in `docs/screens/`
  are captured from the compiled demo with the clock pinned
  (`node frontend/scripts/capture-screens.mjs`, then `python scripts/optimise_screens.py`).
- Rolling back to 3.17.0, and what 3.17.0 does not read after the update, is covered in
  [Upgrading to 3.18](docs/UPGRADING-TO-PARITY.md).

## [3.17.0] - 2026-10-21

Pair: **controller 3.17.0**. **C1: dashboard navigation.** Controller, engine, integration runtime, entities, options and persisted state are unchanged. The dashboard bundle was hot-deployed to the owner's Work HA add-on before release, at the owner's request; no photoperiod soak is claimed.

### 🌱 In plain English

- **Get to any zone in one click.** The menu lists every room with its state, and every zone under it with its phase and moisture. Choosing a room keeps you in the section you are in; choosing a zone opens its page, in any room.
- **Built for a phone in the grow room.** The five sections sit in a bar along the bottom of the screen, where a thumb reaches them, and a tap anywhere on a zone card opens the zone.
- **Links remember the room.** The address now holds the room you have open, so a bookmark, a shared link or a reload brings you back to the same room.
- **Clearer names.** Overview is now **Status** (with **All rooms** and **Room**), and Settings & help is now **Settings**. Old links still work.
- **Water at room level.** Each room on All rooms shows its water today: total litres and litres per plant.

### 🔧 Technical notes

- New `frontend/src/components/room-tree.tsx` (+ css): rooms from `facilityRooms`, zones with phase, VWC and stale/paused flags; desktop sidebar and the phone sheet. `App.tsx` gains `openRoom` (keeps the section) and a fixed `.bottom-nav` at ≤720 px; the selected room is written to `?room=` as its short alias (`resolveRequestedRoom`), else its id.
- `page-tabs.tsx` labels: Status / All rooms / Room / Settings. Routes, hashes and legacy redirects are unchanged. `all-zones.tsx`: room water total and per-plant average over zones reporting both; whole-card zone tap via a stretched title button.
- Docs, `docs/error-codes.json` labels (regenerated `ERROR_CODES.md`), screenshots (27, plus `img/mobile-all-rooms.png`) and browser checks follow the new names; `verify-dashboard.mjs`'s static server reads a file before writing headers.
- No change to `addons/f2_control/f2_control/`, `crop-steering-engine/`, integration Python, entity ids, add-on options or `/data/state.json`.

## [3.16.1] - 2026-10-20

Pair: **controller 3.16.1**. **C0: teaching documentation and website.** Controller, engine, integration runtime, dashboard bundle, entities, options and persisted state are unchanged. Published at the owner's request; no soak is required for C0 and none is claimed.

### 🌱 In plain English

- **Learn crop steering from zero.** A free beginner course, the Crop Steering Academy, now ships with the project and on the project website: 24 short captioned lesson videos, five longer chaptered parts, exercises with feedback and full transcripts.
- **Water, roots and air first.** The lessons build from physical basics to VWC, capacity, dryback, EC, reading the graphs, equipment, setup and day-to-day operation.
- **Nothing changes on your box.** Updating changes no setting, no irrigation behaviour and no screen in the dashboard.

### 🔧 Technical notes

- New `www/learn/` academy (catalogue, player, navigation, quiz progress export/import) and `docs/training/` course sources; GitHub Pages builds and installs checksum-pinned narration and video from the `course-media-2026.10.19-r3` pre-release.
- Course production scripts (`scripts/render_*`, `scripts/package_course_videos.py`, `scripts/pilot_timing.py`) and their Python/Node/browser tests. Release packaging workflow and Pages workflow updated for the academy; no runtime workflow gate changed.
- No change to `addons/f2_control/`, `custom_components/crop_steering/` code, `crop-steering-engine/`, entity ids, add-on options or `/data/state.json`. Version fields advance together only to keep `main` on a tagged pair.

## [3.16.0] - 2026-10-18

Pair: **controller 3.16.0**. **C1: dashboard and operator guidance.** Controller and integration runtime behavior are unchanged. Published at the owner's request after the live UI rehearsal; no full photoperiod or physical water-delivery soak is claimed.

### 🌱 In plain English

- **See every room together.** All zones is the landing page, with moisture, pore EC, last irrigation, water totals and each room's feed supply. Choose another starting page in Settings > Display.
- **Plan and adjust irrigation in one workspace.** Current day and Calendar share the combined moisture/EC canvas. On a desktop, the graph stays beside the target controls.
- **Find each setting in one place.** Equipment owns room and zone setup, History owns recorded evidence and grow records, and Capabilities points to each setting's editor.
- **Keep your work while you navigate.** Draft warnings protect unsaved target and setup edits; refused setup saves explain what must be resolved.
- **Use the updated guides and demo.** The README, public demo, tutorials and screenshots follow the new navigation. Water delivery remains labelled by source and average per plant is not measured uptake.

### 🔧 Technical notes

- Browser-local landing preference; explicit bookmarks and legacy links retain precedence. All-room landing reads the existing controller snapshot and never issues actuator commands.
- Canonical configuration ownership, read-only capability directory, hydraulic conflict checks and stock level preservation; existing backend validation, revision and actuation guards retained.
- Irrigation retains current-day and schedule ownership, one visible planning canvas, pending drafts and shared zone focus. A collapsed stage guide preserves the full-grow reference.
- Existing settings, entity IDs, room mappings, controller algorithms and persisted state format are unchanged. Both package versions advance together; rebuild the controller to retain its packaged dashboard update.
- Setup validation test uses a loopback-only resolver to avoid a process-long pycares thread in the oldest supported Home Assistant test harness. No production resolver or controller changes.

## [3.15.0] - 2026-10-17

Pair: **controller 3.15.0**. Restored controls, operating history and editable AI context. Promoted under the owner's approved rehearsal instruction; no real-plumbing soak is claimed.

### 🌱 In plain English

**Read this first. Unreadable waste-rule settings now hold irrigation instead of silently turning the rule off. A pH dosing fault stays latched through an unavailable enable switch; only a confirmed switch-off clears it.**

- **Choose the controls you need in Features.** Phase timing, safety, sensing, dosing and display settings have one searchable catalogue. New optional modes keep the existing behavior until selected.
- **See more of the room.** Choose cards or a table, camera and light readings, probe panels, plant-stress indicators and history overlays. Extra readings require mapped sensors.
- **Keep a record of each grow.** Save cultivar labels, grow-day summaries, harvest weight and the operating history. An optional Influx connection extends sensor history; Recorder remains the default.
- **Read the instructions the AI actually receives.** Review its shipped instructions, add room context, see the saved revision, and choose instruction cache durations. Estimated cache savings are labelled as estimates.
- **Use optional runoff and dosing checks.** Shared-sump runoff is a water-balance estimate, not a measured figure for each zone. Corrected AI tool schemas avoid one cause of rejected requests; all answers remain checked before use.

### 🔧 Technical notes

- Restored phase/safety packs #170/#164, sensing/runoff #167/#177, dosing #168; neutral defaults, additive state migration and fail-closed readback retained. Last known waste policy persists across restart; only a truly absent legacy setting defaults Off. pH enable unknown/unavailable no longer clears the fault latch (#179).
- Features registry and grow-day summary #165/#166/#172, Display settings and zone/history panels #169/#173/#174, feature metadata and optional DLI mapping #181. Sensor mappings are display-only unless explicitly described by a control feature.
- Per-zone cultivar labels #175, grow/harvest records #176, optional admin-only InfluxQL/Flux connection and bounded long-history reads #178 with Recorder fallback. No live Influx credentials or physical runoff calibration are included.
- Prompt contract corrections #171 and capability-conditioned restored-mode brief #182. AI Instructions #180 publishes the exact live block hashes and revisioned room context, with reviewed save/rollback/readback and room cache TTL controls. Substrate and stage remain existing room settings; shipped doctrine replacement is not included.
- Provider schema mitigation #183 stops strict grammar compilation for answer_choice alone. Four other tools, including set_values, remain strict; local vote and setpoint validation is unchanged.

## [3.14.0] - 2026-10-16

Pair: **controller 3.14.0**. #154, #160 and #162. Released by the owner's decision without a staging soak (approved rehearsal).

### 🌱 In plain English

**Read this first. It changes what the AI assistant is asked on rooms that update:**

- **The AI assistant is now Claude only, and it is asked every question by default, including the P1 ramp.** A judge list copied from the old assistant is read as "all", and the log says once which judges that adds. The first AI route (Cloudflare / TypeSafe) is gone: a room that used it moves to Claude when it has an Anthropic key, and runs on its rules when it has none. The powers checklist is still where you turn each power on or off.

What else you get:

- **History explorer on the zone page.** Pick a date range (today, the grow-day, 3, 7 or 14 days, this run, or your own), tick any sensor in the room, see the phases and shots, and lay the previous run over it for the same days of the run.
- **Clearer cards.** The daily plan, zone cards and Today show one status line, four gauges and one advisory, with the previous grow-day, a short key and the reference dryback band. The longer explanations sit under "How this is worked out". A reading of 1% or less is shown as a probe gap, not as a dry zone.
- "Jev" now reads "AI assistant" everywhere you see it. Entity ids do not change.

### 🔧 Technical notes

- #162: `jev/` -> `brain/`, `jev_bridge` -> `brain_bridge`; new option `ai_judges` (default `all`), `jev_judges` read as a fallback while `ai_judges` is the default, and a list that names only judges from the move is read as all; `jev_*` tuning options renamed `ai_*` with the old value used while the new one is at its default; Cloudflare/TypeSafe transports removed (old keys accepted, unused); CS-712 "First AI route removed" card once per release; docs/AI_ASSISTANT.md (docs/JEV.md is a stub). Old installs 2.25.1 to 3.11.1 proven in tests_ha.
- #160: zone page History explorer (range in the URL, per-unit axes, day-by-day history downsampled to about 720 points per sensor, previous run aligned by grow day and lights-on); the room descriptor publishes mapped room temperature, humidity and VPD sensors when mapped.
- #154: HMI cards (status line, gauges, one advisory chip with Apply to draft, projection table); VWC <= 1% is a probe gap, left out of lines, peak, dryback and statistics.

## [3.13.0] - 2026-10-16

Pair: **controller 3.13.0**. Everything in 3.12.2 (which was tagged but never promoted) plus #156, #157, #158 and #159. Released by the owner's decision without a staging soak (approved rehearsal).

### 🌱 In plain English

**Read these first. They change when water flows on rooms that update:**

- **P1 now ends when the ramp stalls under its target.** If two ramp shots in a row do not raise the moisture, the zone moves to P2, and for the rest of that grow-day its re-water point sits just under what the zone reached, so P2 does not keep chasing a level the slab cannot hold. A probe in doubt (water bypass, a table that does not drain, a reading that does not move) keeps the old behaviour. With the AI assistant on, it is asked first and may hand over one shot sooner.
- **The AI assistant has powers you can tick, per room.** The six it already used stay on. Two new ones are off until you turn them on: "Set targets from what's achievable" (it sets field capacity, peak, re-water, rescue floor and dryback target itself, limited only by each setting's own range) and "Tune shot sizes". Every value it writes is read back and logged with its reason and the result it expects.

What else you get:

- **The AI assistant knows the goal and the rules.** Each night it gets a scorecard per zone for the last five grow-days and its own earlier changes with what followed, and its cached prompt carries the rules and a description of how the controller works, built from the code.
- **A run progress strip at the top of Today:** day X of N, days done and left, harvest date, the grow plan and stage, and the feed recipe with this week's EC, on a bar split into the plan's phases.
- **Compare runs has charts** for each grow week (from 3.12.2), a missing hold switch is named (CS-210), and the AI's "why" names the kill switch and holds.

### 🔧 Technical notes

- #158: engine P1 below-target stall exit (`p1_stall_shots`, default 2; rise judged by `p1_rise` on settled readings); controller state gains `p1_flat` and `p1_stall` (old state loads as 0/None); day-scoped re-water via `auto_setpoints.p2_band`; envelope allows a stall hand-over below the ceiling; ramp judge asked at the first non-rising shot.
- #156: per-room `switch.crop_steering_<prefix>ai_power_<key>` (missing switch = its default); `set_targets_from_achievable` and `tune_shot_sizes` on the Claude route only, values clamped only to each entity's range and logged; goal scorecard, rules POW-01..10 and `jev.controller_brief` in the cached system block; cache reads logged.
- #157: dashboard run progress strip from `runs_get`, `strategy_get`, the AI stage and the dosing feed attribute; no integration change.
- #159: a push to testing no longer cancels the previous Validate run.
- 3.12.2 content: #149, #150, #151, #152, #153.

## [3.12.2] - 2026-10-16

Pair: **controller 3.12.2**. Five changes, #149 to #153. Released by the owner's decision without a staging soak (approved rehearsal).

### 🌱 In plain English

- **Compare runs now has charts.** For each grow week the two runs sit on top of each other: moisture peak and trough, dryback, pore EC, water per plant and shots a day.
- **A hold switch that does not exist now says so by name.** The room still stops watering (fail-closed), and the controller names every missing hold entity at start and on a repairs card (CS-210), so you can fix the list.
- **The AI assistant's "why" answers now name the kill switch and the holds** when they are the reason a zone did not water.
- **If you copied an old judges list, the controller tells you once** which newer judges it leaves out, and suggests "all".
- The docs describe the current AI assistant and the move to 3.12.0 or later.

### 🔧 Technical notes

- #152: Compare runs charts per grow week (VWC peak/trough, dryback from daily peak and trough, pore EC high/low, water per plant per day, shots per day from the shots-today counter), all from Home Assistant history; Dryback and Shots a day also become table columns. Stacks at 390 px; axe clean in light and dark.
- #149: a hold entity missing from Home Assistant is named in the shot block message, a start-up warning and a repairs card (CS-210), proven in tests_ha. Behaviour stays fail-closed.
- #151: the why-evidence includes the kill switch and every hold entity with its state.
- #150: one log line when `jev_judges` omits newer judges; "all" already selects every judge.
- #153: docs/JEV.md describes the current assistant (TypeSafe and Cloudflare marked deprecated); MOVING_FROM_JEV says 3.12.0.
- No state-file or option change; an old install loads unchanged.

## [3.12.1] - 2026-10-16

Pair: **controller 3.12.1**. One change, #147. Released by the owner's decision without a staging soak (approved rehearsal).

### 🌱 In plain English

- **The AI assistant can now use an Anthropic-compatible router.** Set the new `anthropic_base_url` option to the router's address, and the controller sends the AI questions there with your router key. Leave it blank to use Anthropic directly, as before. If the router does not answer, the controller uses its rules for that decision.

### 🔧 Technical notes

- New add-on option `anthropic_base_url` (blank by default; an old options file loads unchanged). With it set, a requests-based client reads the first JSON object of each reply (a trailing `data: [DONE]` line is ignored) and maps a suffixed tool name back only to a tool the request offered. `anthropic_model` then also accepts `<prefix>/<model>`, billed at that model's price row. Failure classes, the budget and key handling are unchanged.

## [3.12.0] - 2026-10-16

Pair: **controller 3.12.0**. This release brings the Jev edition (3.11.1) into this repository and adds 13 groups of
changes on top of it. It was released by the owner's decision without a staging soak (approved rehearsal).

### 🌱 In plain English

**Read these first. They change when water flows on rooms that update:**

- **P3 rescue shots now wait 10 minutes between shots in every zone.** Set "P3 time between shots" to 0 to go back to no gap.
- **If a room's settings cannot be read since start, the zones that need them for shot size wait (CS-402) instead of watering on built-in values.**
- **If a hold switch you set up becomes unavailable, its room now stops watering until it is back. Before, an unavailable hold switch was ignored.**
- **On the first start after this update, each room holds watering for about 3 minutes while the controller checks that no second controller drives it.**
- **The EC PID option is gone. Rooms that had it on now use the normal step rule for EC.**
- **Auto setpoints no longer moves the rescue floor, keeps the P0 dryback, and moves the field-capacity ladder at most 1 point a grow-day.**
- **On a room that runs a grow plan, a dead or flat EC probe no longer keeps every zone on yesterday's targets. At lights-on every zone with a working moisture probe moves to the new day.**
- **When a zone's moisture probe comes back during the day, the zone carries on from where its day is. It does not start the morning ramp again.**

What else you get:

- **It works on any Home Assistant.** No built-in room names, entity ids or site numbers. One table of defaults and units. A valve, pump or main line can be a switch, an input_boolean or a valve.
- **Run the controller as an app or as a plain Docker container** (Home Assistant Container and Core).
- **An optional AI assistant (Claude Haiku).** It decides only inside the safety limits, and the controller goes back to its rules when the AI is off, out of budget or not available. Put the Anthropic key and a daily budget in the app options.
- **The controller checks that each room runs its grow plan** and tells you in one line, with a CS-713 card when it does not.
- **Safety:** a max-run latch, fail-closed holds, a settled P1 rise, guarded probe combining, a test shot button, and a stopped heartbeat.
- **Dosing and the reservoir:** dosing runs on the main loop, tank level and reservoir minimum, feed schedule by week, and two-point probe calibration.
- **The setup wizard checks itself**, and the dashboard has a first-run tour, a stale-data banner and a targets editor.
- **All text is in Simplified Technical English**, and every setting has an "About" tip that tells you what it does, what it changes and what to check.
- **Moving from the Jev edition:** follow docs/MOVING_FROM_JEV.md once.

### 🔧 Technical notes

- Intake: Jev 3.11.1 fast-forwarded (#132), with a guard so a 2.25.1 install that only set Cloudflare keys does not start the Jev brain.
- Families: groundwork (#133), any Home Assistant (#134), doctrine pack and substrate per room (#135), standalone Docker (#136), safety ports (#137), engine ports and substrate profiles (#138), change log, read-back, overlays, re-notify and shot-landed check (#139), notifications (#140), dosing and reservoir (#141), setup wizard and dashboard (#142), Claude Haiku brain (#143), brain judges and plan adherence (#144), ASD-STE100 text and tooltips (#145).
- New codes: CS-312 (max-run latch), CS-313 (undrivable actuator), CS-503 (probe unit), CS-609 (second controller), CS-610, CS-611, CS-708 to CS-713.
- Image: requests and the Anthropic SDK closure installed from hashed requirement files; armv7 skips the SDK and runs rules.
- Every family passed the full CI (lint, integration, controller, real Home Assistant on the newest and oldest supported versions, container smoke, dashboard browser workflows).

## [3.11.1] - 2026-10-06

Pair: **controller 3.11.1**. Class **C3**. One pull request, #42, the fix to 3.11.0's first live afternoon on F2
(6 October 2026), which left zone 2 with its re-water point under its rescue floor. The controller changes; the
integration carries the version and What's new.

### 🌱 In plain English

- **The four moisture setpoints stay in line.** When field capacity falls, the re-water point and the rescue floor
  fall with it. A value under the lowest a setting allows is now held at that lowest value, and the four are written
  in an order that keeps them in line after every write. On 6 October zone 2's new rescue floor, 17.9, was refused
  under its minimum of 20 after its re-water point had already moved to 25.4.
- **Nothing moves until a lights-on has kept the day before's highest reading.** Updated after lights-on, 3.11.0
  used the day in progress instead, and zone 2's field capacity followed a ramp that had stopped at its shot limit
  down from 67.5 to 51.4.

### 🔧 Technical notes

- Controller (#42): `_follow_fc` clamps each value to `setpoint_supervisor.BOUNDS` and to the per-zone number's own
  `min` and `max`; it writes top-down when field capacity rises and bottom-up when it falls, and the first refused
  write stops the rest. `_auto_write` returns whether it wrote and records its de-duplication only on success.
  `_vwc_maxima` has no stand-in: `(None, None)` until `peak_prev` exists.
- No state-file, option or entity change.

## [3.11.0] - 2026-10-06

Pair: **controller 3.11.0**. Class **C3**. One pull request, #40, the owner's rules for a zone's P1 and its setpoints
(6 October 2026): the P1 target is the highest reading of the grow-day before, field capacity rises with the sensor
and what sits under it moves with it, the 2-points-a-day limit is gone, and P1 ends when a shot at the target no
longer raises the zone's highest reading. The engine and the controller change; the integration carries the version
and What's new.

### 🌱 In plain English

- **Tomorrow's P1 target is today's highest reading.** At lights-on the controller keeps the grow-day's highest VWC
  reading, and that is the new day's P1 target, however far it is from the old one. The limit of 2 points a day is
  gone.
- **Field capacity rises with the sensor.** It is the higher of today's and yesterday's highest readings, so it goes
  up the same day the probe reads higher. When it moves by a point or more, the P2 re-water point and the rescue
  floor move by the same points.
- **P1 ends when the slab stops taking water.** The ramp runs to the P1 target, then gives one more shot. If that
  shot did not raise the zone's highest reading by half a point, the slab is full and the zone goes to P2. If it
  did, another shot follows, until one does not. The maximum P1 shots still cap it.
- **Pore EC no longer holds P1 open.** P2's dilute shots correct a high pore EC.

### 🔧 Technical notes

- Engine (#40, both copies): `ZoneSnapshot.p1_reached`, `p1_peak_before_shot`, `p1_extra_shots`; `P1_RISE_PTS`
  0.5. P1 fires `p1_ramp` below the ceiling and `p1_extra` (cap-exempt) at or over it, and hands over at the
  maximum shots, or once an extra shot is in, a full P1 interval has passed and the peak rose by less than 0.5
  ("P1 full: ..."). The EC exits, the P1 flush and the budget-spent exit are gone.
- Controller (#40): zone key `peak_prev` (kept at lights-on); `_vwc_maxima` / `_follow_fc` write field capacity =
  max(today's peak, `peak_prev`) and the P1 target = `peak_prev`, and move the re-water threshold and rescue floor
  with field capacity. The learner writes neither, its 2-point limit (`DAY_RISE_PTS`, `day_ceiling`, `p1_entry`,
  `stale_target`) and 3.10.0's settled-reading tracker are removed, and so is `p1_ec_gate`. The P1 rule's state
  (`p1_reached`, `p1_peak_before`, `p1_extra`) is latched, counted and persisted. A zone on the blind path keeps its peak at lights-on too. Until the first lights-on
  after the update, the grow-day in progress stands in for the day before only once its P1 is over.
- State file: four new zone keys; a 3.10.0 file loads with them empty and its retired learner keys are dropped;
  3.10.0 ignores the new keys after a rollback.

## [3.10.0] - 2026-10-06

Pair: **controller 3.10.0**. Class **C3**. Two pull requests, both asked for by the owner for F2 zone 2 on 5 and 6
October 2026: #37, a zone with high pore EC is flushed whenever its table drains, whatever its moisture reading; and
#38, field capacity follows the sensor. Both change the controller only; the integration carries the version, the
error-code text and What's new.

### 🌱 In plain English

- **High EC gets flushed.** On 5 October F2 zone 2's pore EC sat at 7 against a target of 4.5 and its plants were
  yellowing, yet it got no flush all day. Every flush needed the moisture reading under field capacity minus 2, and
  zone 2's probe reads far above its field capacity. Now a high-EC zone is flushed whenever the feed is weaker than its
  slab and its table is draining. The daily water limit and the 45 minutes each flush gets to drain still apply. A
  table that is not draining (the "moisture rising with no water" alert) now holds flushes as well as the daily
  minimum.
- **Field capacity follows the probe.** It is now the zone's highest reading 20 minutes or more after a shot, today or
  yesterday, and never lower than the P1 target + 2. When the probe reads higher, field capacity goes up the same day.
  Until now it was only ever the P1 target + 2, which may rise 2 points a day, so zone 2 sat at 63 to 68 after every
  shot against a field capacity of 54. It also follows on a zone watering without its probe.
- **Everything under field capacity moves with it.** When the probe moves field capacity by a point or more, the P1
  target, the P2 re-water point and the rescue (P3 emergency) floor move by the same points, so the dryback under
  full stays the size it was set. P0 and the overnight dryback are percentages of the day's peak and follow by
  themselves. Zone 2: field capacity 54 to 68, P1 target 52 to 65.5, re-water 27.5 to 41.5, rescue 20 to 34.

### 🔧 Technical notes

- Engine (#37, both copies): `ZoneSnapshot.backed_up`. The capped EC corrections (`p0_ec_flush`, `p1_flush`,
  `p2_dilute`) need dilutive feed and `not backed_up`; the cap-exempt `flush_high_ec` and `p2_rescue` keep
  `vwc < field_capacity - 2`. A dilutive zone that reads full falls through to the capped rules instead of the early
  BLOCK return. In P2, a rescue that cannot fire no longer skips the dilute.
- Controller (#37): the CS-310 hold also passes `backed_up=True`. Catalog text for CS-310 and CS-311, ERROR_CODES.md
  and the dashboard bundles follow.
- Controller (#38): `auto_setpoints.track_full` (learner keys `full_date`, `full_day`, `full_prev`) is fed every loop
  from the probe, before Jev's probe judge can set it aside. `field_capacity(target, seen)` is
  `max(target + 2, seen)` within 40 to 90, written by the learner pass and, for blind zones, by `_follow_fc`. Until
  anything is tracked, the last `plateau_hist` value seeds it. When `seen` (not the target + 2 floor) moves field
  capacity by `FC_SHIFT_MIN` (1 point) or more, the P1 target, `p2_vwc_threshold` and `p3_emergency_vwc_threshold`
  move by the same points (never above the learner's peak, nor within 2 of field capacity; nothing but field
  capacity when the ladder is or would be inverted), and the learner's `day_ceiling` and `p1_entry` move with the
  target so its brake does not pull it back. Jev's bridge re-centres the Setpoints judge's range on the moved
  threshold.
- State file: three new learner keys. A 3.9.0 file loads with them empty; 3.9.0 ignores them after a rollback.

## [3.9.0] - 2026-10-05

Pair: **controller 3.9.0**. Class **C3**. Eight pull requests, merged into `testing` together at the owner's
request ("complete and merge all the pull requests"): three controller changes (#31 each zone's plateau and
nights, #32 Jev's availability, #34 one writer per setpoint with a ratchet guard), one integration change (#35
stock tanks drawn from what their pumps run), three dashboard changes (#28, #29, #33) and the dryback planner's
design (#30). That is more than the one C2 or C3 change a candidate normally carries (docs/RELEASING.md, step
3); the owner chose to release them together, and the release audit records it.

### 🌱 In plain English

- **Zones get their P1 targets kept up to date again.** Since 26 September, in a room where Jev manages
  setpoints, nothing moved a zone's P1 target or field capacity. F2 zone 2's probe read 15 to 20 points higher
  after the 29 September sump flood, so every morning started above its ramp target and P1 never ramped. Now
  Jev keeps the P2 shot size and re-water point, and the Auto setpoints learner keeps the P1 target and field
  capacity, with two brakes so it cannot ratchet a zone up again: a target rises at most 2 points a day, and only
  after that day's ramp reached it; a zone that starts its ramp above its target goes to 2 points over where the
  ramp began, never straight to an old learned peak.
- **Jev is there more often.** When TypeSafe fails, Jev retries, then asks through Cloudflare (once its account
  and token are set in the app). An unsure answer gets a second look with more evidence. A judge whose calls keep
  not working out for a zone acts there only when it is sure twice in a row. The daily budget defaults to 5,000
  calls, with a warning at 80 %; a box keeps the budget it already has until its owner changes it.
- **Each zone remembers its plateau and its nights.** Every morning the app's log and the activity feed say how
  each zone landed overnight: where P1 ended, how fast it dried at night and how far it dropped in P0. No
  watering decision changes; the dryback planner will use this.
- **Stock tanks go down when their pump runs.** A stock tank linked to a dosing pump now loses what that pump
  actually pumped, whoever started it. What was pumped before the update was never taken off, so after updating,
  read each linked tank's level off its side once and save it with **Set level**.
- **Charts.** Equipment › Tank & pump has a chart of the tank's level over 24 hours, 3 days or 7 days with every
  shot, pump run and fill on it. On the zone chart each key entry switches its layer on and off, a cursor bar
  shows where a reading is taken, the reading sits under the chart, and yesterday's line is drawn even on a day
  the room was switched off for a while.

### 🔧 Technical notes

- Controller (#34): `auto_setpoints` ratchet guard (learner keys `day_ceiling`, `p1_entry`, `stale_target`; a
  stale target goes to `min(p1_entry + 2, learned peak + 1)`, otherwise up at most 2 over the grow-day's ceiling
  after a `reached` or believed `plateau` outcome) and the lever split (`jev_bridge.judge_levers`: with the
  Setpoints judge running, the learner writes the P1 target, field capacity and rescue floor, never
  `p2_shot_size` or `p2_vwc_threshold`). `zone_N_auto_setpoints.managed_by` is now a map of entity to writer.
- Controller (#31): per-zone plateau and night history in the state file, logged each morning as
  "Zn night: landed ...". `decide()` and its inputs are unchanged. A history that loads with wrong types is
  dropped, and the hooks never block a decision, a shot count or a phase change.
- Controller (#32): Jev routes (TypeSafe direct, then Cloudflare `/ai/run`), 3 tries within 60 s per route on a
  429, a 5xx or a timeout; questions older than 5 minutes dropped unasked; second looks under 0.7 or on split
  phrasings (up to 2); the stricter gate after 3 calls in a row that did not work out (two agreeing calls at 0.8),
  read from the ledger; CS-706 (budget at 80 %) and CS-707 (a judge on the stricter gate). New options
  `jev_budget_warn_pct`, `jev_retries`, `jev_reask_max`, `jev_unsure_below`, `jev_strict_after`,
  `jev_strict_prob`; `jev_daily_calls` defaults to 5000.
- Integration (#35): `StockStore` follows each linked pump's power and dosing entities and draws seconds run x
  calibrated flow once per run (key `pump:<id>:<start>`); `stock_draw` leaves pump-linked tanks alone (new
  `linked` answer field); a fill that draws no tank is no longer logged.
- Dashboard (#28, #29, #33): `dayTrace` keeps a day the room was switched off during (marked `roomOff`); chart
  layer toggles, cursor bar, readout line and stored chart preferences; the Tank & pump level chart
  (`tank-level.tsx`), with `controller.timeline` allowing the selected room's tank and pump entities. Bundles
  rebuilt.
- Docs (#30): the dryback planner and Jev line-steering design, its roadmap, and the plans for steps 1 and 2.
- State file: three history keys (#31) and three learner keys (#34). A 3.8.0 file loads with all of them empty;
  3.8.0 ignores them after a rollback (the history is lost, nothing else).

## [3.8.0] - 2026-09-30

Pair: **controller 3.8.0**. Class **C3**. One pull request: #26, critical alerts for tables backing up: moisture
rising with no water (CS-310) and a sump pump standing still (CS-311). Backtested on F2's readings from 22 to 30
September; checked by the controller, lean, engine, real Home Assistant, dashboard and browser suites, with the
new rules mutation-checked.

### 🌱 In plain English

- **A table that isn't draining is now an emergency.** When a zone's moisture keeps rising while no water goes
  in (its valve shut, by the controller and by hand), the slabs are sitting in runoff: the table, its drain or
  the sump is backed up. Crop Steering says so straight away, as a critical alert, and stops that zone's daily
  minimum from adding more water until it drains.
- **A sump pump that stops is an emergency too.** Name the sump pump's power sensor in the controller app
  (`sump_power_sensor`) and Crop Steering warns when it hasn't run for three hours while the room is on. On
  28 September F2's sump pump stopped for 41 hours; Zone 2 filled from below the next day.

### 🔧 Technical notes

- Controller (#26): `_watch_backup` (CS-310: a 3-point rise within 60 minutes, the valve shut for that time and
  45 minutes before, waits 45 minutes after a start; holds `min_daily_volume` while flagged, clears an hour after
  the rise stops) and `_watch_sump` (CS-311: no reading over 20 W in `ha_history` for `sump_silent_hours`, read
  every 5 minutes, nothing on no evidence); new options `sump_power_sensor`, `sump_silent_hours`.
- docs/error-codes.json: CS-310 and CS-311 (critical); both in the notification catalog's emergency and hardware
  kinds; ERROR_CODES.md regenerated; dashboard bundles rebuilt.

## [3.7.0] - 2026-09-30

Pair: **controller 3.7.0**. Class **C3**. One pull request: #24, the minimum water per plant per day spread
evenly over the day instead of all at lights-on. Checked by the engine, controller, lean and real Home Assistant
suites, with the pacing mutation-checked.

### 🌱 In plain English

- **Every plant gets its minimum, whatever its probe says.** A zone whose probe sits in a wet spot reads wetter
  than its slab and was barely watered (one zone got 0.41 L a plant in a day). The daily minimum per plant
  (the zone's "min daily mL per plant" helper) now waters it through the day.
- **Spread out, not dumped.** It waits for the morning dryback, catches up during the ramp if the zone is
  behind, and spaces the rest through the day so the whole minimum is in three hours before lights-off, before
  the evening dryback. Every shot the zone gets counts toward it.
- Nothing else changes: the drown ceiling and the 10-minute spacing still hold it back, and the daily limit
  can't block it.

### 🔧 Technical notes

- Engine (#24, both copies): `floor_share` (a straight line from lights-on to `min_floor_finish_h`, 3 h, before
  lights-off); the floor never fires in P0 and is due only while `daily_vol` is under
  `min_daily_volume * floor_share`; `ZoneSnapshot.hours_since_lights_on` (None = front-stacked as before);
  `ZoneParams.min_floor_finish_h` (bounded 0 to 12).
- Controller (#24): passes `hours_since_lights_on` in the snapshot.
- Tests: `crop-steering-engine/tests/test_min_daily_pacing.py` (the line, behind/ahead, never in P0, catch-up
  after the finish, a simulated day with a probe stuck wet: 5 evenly spaced shots, all in by 19:00).

## [3.6.0] - 2026-09-30

Pair: **controller 3.6.0**. Class **C3**. One pull request: #22, who gets which phone push (a checkbox per phone
for each kind of alert, the rooms it covers, the pushes routed by the integration), with three new pushes: no
watering for a while, a zone changing phase, Jev moving a setting. An adversarial review of the alert path
found two ways a critical push could be lost and a loop that could stall; all fixed with tests (11 of 11
mutation-checked). Checked by the lean, controller, real Home Assistant, dashboard and browser suites.

### 🌱 In plain English

- **Choose who gets what.** Settings & help › Notifications lists the site's phones with a checkbox for each kind of
  alert: emergencies, hardware lockouts, sensors and drift, watering stopped, phase changes, stock tanks, dosing,
  Jev, setup. Each phone can cover every room or only some, and has a **Send a test** button. Staff can change
  their own phone's boxes; an administrator can change everyone's.
- **New things to be told about.** A room that is on, with its lights on and a zone in P1 or P2, that has watered
  nothing for 3 hours (you pick 1 to 12); a zone moving from one phase to the next; Jev moving a zone's shot size
  or re-water point.
- **Nothing is lost.** Until a phone is set up, every push goes where it always did. If the routing can't be
  reached, a push goes there too. An emergency that no phone's row covers for its room goes to every phone that
  gets emergencies, or to the phone set in the controller app when none does. Tapping any push opens Crop
  Steering.

### 🔧 Technical notes

- Integration (#22): `notify_catalog.py` (the nine kinds; code → kinds, unknown codes by severity) and
  `notify_api.py` (one site-wide store `crop_steering.notify`; services `notify_get`, `notify_save`,
  `notify_test`, `notify`; `sensor.crop_steering_notify_config`; phones listed from mobile_app registrations with
  their owner; each phone sent to at once with an 8 s limit; `data.tag`, the panel link and, for emergencies,
  high-priority keys on mobile_app services only; an emergency no row covers goes to every phone that takes
  emergencies; Repairs cards CS-601 to CS-608 pushed when raised; a store that can't be read is logged, and
  a kind a newer version saved is dropped rather than the whole setup).
- Controller (#22): `_alert` routes through `crop_steering.notify` when a phone is set up and falls back to
  `notify_service` when the call fails or an emergency reaches nobody (never both); the setup sensor is read by
  the loop, never waited on by an alert; phase changes and Jev's setpoint moves queued, one push per room and
  kind, sent after the loop's shots within 10 s; CS-209 idle watchdog (clock rebuilt after a restart); a pump
  whose turn_on errored (CS-302) and a batch's mix pump that did not start (CS-805) are switched off before
  their alert.
- Dashboard (#22): Settings & help › Notifications (grid on a computer, a card per phone on a phone, what each
  kind covers, add a phone, review before save, rooms nobody gets emergencies for).
- docs/NOTIFICATIONS.md is the contract.

## [3.5.0] - 2026-09-28

Pair: **controller 3.5.0**. Class **C3**. One pull request: #19, batch-tank dosing (a page per room's tank, single
doses and whole batches through the controller, stock tanks drawn by what was dosed). Not run on hardware; checked
by the lean, controller, real Home Assistant, dashboard and browser suites.

### 🌱 In plain English

- **Dosing, from the Crop Steering page.** Each room has Equipment › Dosing for its own batch tank: dose any
  nutrient pump by the mL, or make a whole batch (fill until the float says full, mix, dose each nutrient in the
  recipe's order, mix again, record the fill). Watering is held while a batch runs, and Stop works at any point.
- **The pumps' own boards still time every dose.** Crop Steering checks each dose started and finished, cuts a
  pump's power if it runs past its time, refuses an uncalibrated pump or a dose longer than 20 minutes, and after a
  restart switches all dosing hardware off and tells you, never carrying on by itself.
- **Stock tanks that follow the doses.** Link each pump to a stock tank and every dose takes what was actually
  dosed off its level; each pump shows a small bottle with the litres and batches left.
- Nothing happens until a room's dosing is set up, and your existing Home Assistant dosing scripts are untouched.

### 🔧 Technical notes

- Integration (#19): `dosing.py`/`dosing_api.py` (store `crop_steering.dosing.<entry_id>`; services `dosing_get`,
  `dosing_save`, `dosing_request`; `sensor.crop_steering_<prefix>dosing_config`); `stock_draw` (idempotent), linked
  tanks skipped by the fill rule and by a hand-recorded batch; the stock sensor's tanks gain `id` and `pump`.
- Controller (#19): `dosing_runner.py` (one thread; write-ahead `/data/dosing_state.json`; stuck hardware held and
  re-sent until it reads off; restart recovery; SIGTERM switches irrigation off first; alerts CS-801 to CS-807;
  `sensor.crop_steering_<prefix>dosing`); `_blocked` holds a batch's rooms; app `timeout: 30`.
- Dashboard (#19): Equipment › Dosing (pump drawings, dose form, live telemetry, batch steps and recipe, stock
  strip and bottles, history, setup); one stock colour rule on both pages.
- docs/DOSING.md is the contract; an adversarial safety review's 24 findings are fixed with tests.

## [3.4.2] - 2026-09-28

Pair: **controller 3.4.2**. Class **C3**. One pull request: #18, a pump plug that reports OFF late is sent OFF
again, not held. Not run on hardware; checked by the controller and lean suites.

### 🌱 In plain English

- **No more false "hardware fault" from a slow pump plug.** On 28 September F2 stopped watering at 11:18
  because the pump's Zigbee plug took about 10 seconds to report it had switched off, and the controller only
  waited 6. Now anything that has not reported OFF is told again and given 10 more seconds before the room is
  held. A valve that is really stuck open is still caught within 16 seconds.

### 🔧 Technical notes

- Controller (#18): `_confirm_switches` re-sends `switch.turn_off` to whatever does not read `off` after the first
  6 s window and reads back for `CONFIRM_RETRY_S` (10 s) more; every close path (normal close, a shot cut short,
  error cleanup, an interrupted shot's reconcile) uses it. Two new regression tests reproduce the live fault.

## [3.4.1] - 2026-09-28

Pair: **controller 3.4.1**. Class **C1**. Two pull requests: #15 (C1), the demo shows Jev's re-water range as the
controller bands it; #16 (C0), the README explains the Jev edition from scratch, with a screenshot of every page
where Jev shows. Nothing the controller reads changes. Not run on hardware; checked by the dashboard and browser
suites.

### 🌱 In plain English

- **A front page for newcomers.** The README now starts from zero: what crop steering is and the words it uses,
  how the controller and Jev work together, the eleven questions Jev answers, what it can never do, every
  dashboard page that shows Jev with a current screenshot, letting Jev move setpoints and every way to take them
  back, and what it costs. Its install buttons, and the install guide's, add this repository instead of the
  original.
- **The demo's Jev range is the real one.** The demo showed Jev allowed 1.5 points either side of the re-water
  point. The controller allows 2 under and 1 over, and the demo now shows that.

### 🔧 Technical notes

- Dashboard (#15): the demo's `setpoints.range.p2_vwc_threshold` is `[59, 62]`, what `setpoints.band()` gives for
  its numbers; the browser checks follow; bundles rebuilt.
- Docs (#16): README rewritten with nine new `img/jev-*.png`, and the water use, stock tanks and setup screenshots
  retaken; the `docs/INSTALL.md` buttons point at this repository; the app's `DOCS.md` describes Jev and its
  options; `docs/JEV.md` names the 3.4.0 pages.

## [3.4.0] - 2026-09-28

Pair: **controller 3.4.0**. Class **C3**. Two pull requests: #12 (C3), Jev's data for the simplified dashboard and no
Pore EC question while EC stacking is off; #13 (C1), the dashboard rebuilt around what each page is for, from 11
pages to 5. Not run on hardware; checked by the lean, controller, dashboard and browser suites.

### 🌱 In plain English

- **A dashboard built around what you want to know.** The menu is now Today, Plan, History, Equipment and Settings &
  help, plus a page per zone. Today fits one screen: the room in one line, then a card per zone that is flagged
  only when it needs you, with the reason, and what Jev changed. Each zone has its own page with the day chart,
  its probes, its targets and what Jev thinks of it. Plan is a compact targets table (about a third of its old
  length) with the flower laid out by stage; History is one timeline of shots, phases, setting changes, alerts and
  Jev's decisions; Equipment holds the probes, stock tanks, tank and pump, and setup. Every feature is still there.
- **Less noise from Jev.** It no longer asks about pore EC while the room's EC stacking is off, where its answers
  changed nothing; each check on an earlier decision shows as a ✓ or ✗ on that decision; and the day's call count
  no longer resets when the controller restarts.

### 🔧 Technical notes

- Controller (#12): the salt judge needs `stacking_on`; journal outcome entries carry `of` (the decision's time) and
  the action in words; `/data/jev_usage.json` keeps the day's calls, tokens and errors; each zone's Jev sensor
  publishes `setpoints` (the operator's values, Jev's range, current values, last move, pause, managed).
- Dashboard (#13): five-entry menu with legacy redirects, room status and safety switches in the header, `today`
  and `zone` pages, History (timeline merging the activity log and Jev's journal), Plan (targets table with Jev's
  ranges, schedule by stage), Equipment (probe health, stock headline, tank and pump, setup), Settings & help;
  attention rules, timeline merge, redirects and chart scaling tested; bundles rebuilt.

## [3.3.0] - 2026-09-28

Pair: **controller 3.3.0**. Class **C3**. Two pull requests: #7 (C3), Athena's Grow Guide Handbook as a second cited
source in Jev's doctrine; #10 (C1), the dashboard's grow day redrawn in Athena's chart language and Jev's decisions
shown live. Not run on hardware; checked by the lean, controller, dashboard and browser suites and against the
real Jev (17 of 17).

### 🌱 In plain English

- **A grow day you can read at a glance.** "Today's grow day" follows Athena's charts: the stage and its targets on
  one line at the top, then a card per zone with its numbers (moisture, pore EC against the stage's range, water
  today, shots, what comes next, last night's dryback against the target) and one clean chart: the light cycle,
  the phases P0-P3, field capacity, the runoff zone for the zone's steering, moisture with every shot on the line,
  pore EC with the stage's range, and Jev's decisions marked where they happened.
- **Jev's decisions, live.** The latest five sit under the charts and every decision is on the Activity page: what
  Jev answered and how sure it was, what it asked for, and what the controller did (acted, refused and why, advice,
  nothing), with how earlier actions turned out.
- **Jev knows Athena's crop-steering guide too.** Alongside your own GrowLabs pages, every question now carries
  Athena's handbook: when the first shot should come after lights-on, why the ramp uses small shots, how bigger or
  smaller maintenance shots move root-zone EC, Athena's drybacks and targets for each stage, runoff targets, where
  the probe goes and how to check it against caught runoff. Your pages still come first, and where the two differ
  your stage arc wins.

### 🔧 Technical notes

- `jev/doctrine.py` (#7): Athena's Grow Guide Handbook (metric, Precision Irrigation Strategy, pp. 33-41) as a second
  cited source, 24 rules after the owner's in ramp, dryback, maintenance, EC, stage, probe, closed loop and slab
  (123 in all); the last dryback rule says the owner's arc leads where the two differ.
- Dashboard (#10): an Athena-style SVG chart per zone (light band, phase columns and badges, FC line, runoff zone by
  steering, maintenance band over P1/P2, rescue floor over P3, VWC with shot dots and projection, pore EC on a right
  axis with the stage band, Jev markers), a numbers row per zone, a stage line from the room's Jev sensor, a y-axis
  fitted to the zone, 7-8 legend items; `lib/jev-log.ts` and `components/jev-log.tsx` (compact list on the
  Overview, full panel with filters on Activity), `jev`/`jev_log` among the watched sensors so a first post shows
  live. Bundles rebuilt (three identical copies).

## [3.2.0] - 2026-09-28

Pair: **controller 3.2.0**. Class **C3**. One pull request (#6): the Setpoints judge. Once a night Jev may move one
of a zone's own maintenance settings one notch, inside a range around the operator's value, while the room's Auto
setpoints switch is on. The integration's code is unchanged; its version moves with the pair. Not run on hardware;
checked by the lean and controller suites and against the real Jev (17 of 17).

### 🌱 In plain English

- **Jev adjusts tomorrow's maintenance watering.** Once a night, after lights-off, it looks at how much each zone
  drank against the rest of the room, how its shots held, and where its root-zone EC sits against today's stage,
  and picks one small step (slightly smaller or bigger shots, or re-watering slightly later or sooner) or leaves it
  alone. Only while the room's Auto setpoints switch is on.
- **Your values stay in charge.** It only moves the zone's own P2 shot size and re-water threshold, 0.5 at a time,
  never more than a small range from what you set (and never a shot under 3 %). Change a value yourself and yours
  becomes the new centre. If a zone needs a rescue shot after a change, the change is undone and Jev leaves that
  zone alone for two days.
- **The old Auto Setpoints learner stands aside** while Jev runs, so a zone never has two hands on its settings.

### 🔧 Technical notes

- `jev/judges/setpoints.py` (P3, the first 3 h after lights-off, once a grow-day): smaller_shots / bigger_shots /
  later_rewater / sooner_rewater / keep. Evidence includes water per plant against the room's median zone and pore
  EC against the stage's range, with code stating which way each calls for (Athena: EC rises with smaller shots);
  it acts when both phrasings pick the same lever and that lever, or its direction, holds 60 %.
- Envelope `setpoint`: the room switch on and no grow plan, not paused, one change a grow-day, one 0.5 notch,
  inside `band()` (shot ±1 % of the operator's value, never under 3 %; threshold 2 under to 1 over, at least 4 above
  the rescue floor and 2 under the ramp ceiling), and the value unchanged since Jev was asked.
- `jev/setpoint_memory.py` (`/data/jev_setpoints.json`): the operator's values, Jev's writes, a pending write,
  the last move, a pause. `jev_bridge.py`: `setpoint_view` (read only in P3), `apply_setpoint`, `guard_setpoints`
  (a P3 rescue shot within 30 h: put back, pause 48 h, CS-404). `controller._auto_tick`: the base learner never
  writes nor asks its old per-hour judge while the judge runs.

## [3.1.0] - 2026-09-28

Pair: **controller 3.1.0**. Class **C3**. One pull request (#5): every decision Jev makes is journalled with what the
controller did with it, and published for the dashboard's live Jev log. The integration's code is unchanged; its
version moves with the pair. Not run on hardware; checked by the lean and controller suites.

### 🌱 In plain English

- **Follow Jev live.** Every answer Jev gives is recorded with what the controller did about it: acted, refused
  (and why), nothing to do, or waiting, plus how earlier actions turned out and whether an alert went to the phone
  or stayed a card. The newest 30 per room are published for the dashboard's Jev log, and the room's Jev sensor
  carries today's stage of flower as numbers for the day chart.

### 🔧 Technical notes

- `jev/journal.py`: `/data/jev_journal.jsonl` (the last 400 decisions, kept across restarts). `jev/brain.py`
  journals each new answer once with its result on that pass, a later admission of a standing answer, and each
  outcome; journalling never raises into the pass.
- `jev_bridge.py`: `sensor.crop_steering_<prefix>jev_log` (state: the newest decision in one line; `entries`: the
  last 30, newest first, free text capped under the recorder's 16 KB), `stage` on
  `sensor.crop_steering_<prefix>jev` (day of flower, stage, steering, pore EC range, dryback points, runoff %),
  and an alert's push-or-card call journalled whenever it changes.

## [3.0.1] - 2026-09-27

Pair: **controller 3.0.1**. Class **C3**. One pull request (#3): Jev's zones judge compares each zone's water per
plant with the room's median zone, itself included, so only the odd zone out gets the CS-702 alert. Found on the
work HA on 3.0.0's first live evening. An advice-only judge: no water decision changes. The integration's code is
unchanged; its version moves with the pair. Not run on hardware; checked by the lean and controller suites (four new
tests that fail on 3.0.0) and against the real Jev (14 of 14).

### 🌱 In plain English

- **Only the odd zone out is flagged.** The check of each zone's water per plant compared every zone with its
  thirstiest neighbour, so when one zone had far more water than the rest, the others were flagged too and told of
  a valve or dripper fault they did not have (F2, 27 Sep: zone 1 had 2477 mL a plant, zones 2 and 3 about 1000,
  and all three were flagged). Each zone is now compared with the room's middle zone.

### 🔧 Technical notes

- `jev/judges/zones.py` `_ratio`: the comparison is `statistics.median` of every zone in the room, this zone
  included (it was `others[len(others) // 2]`, the larger of two sorted siblings). A room of two zones compares each
  zone with the other, as before. The evidence (`compared_with`, `share_of_that`) and the CS-702 message say what
  the zone was compared with.

## [3.0.0] - 2026-09-27

**The Jev edition.** Pair: **controller 3.0.0**. Class **C3**. This repository starts from Crop Steering 2.25.1 and
adds TypeSafe Jev, a typed-decision model, as the judge of every decision the engine made with a fixed rule, inside a
deterministic envelope. With no Jev key, or Jev off, slow or down, the engine runs exactly as 2.25.1. Not run on
hardware; checked by the lean, controller, engine, real-Home-Assistant and browser suites, and against the real Jev
(14 of 14 situations answered as an experienced grower would). What it is and what "truly insane and amazing" means
here: docs/JEV.md.

### 🌱 In plain English

- **Jev judges ten decisions** the engine used to make by fixed rules: when the morning ramp starts and when it is
  done, why pore EC moved and how to steer it, when the day's watering stops, whether a probe tells the truth,
  whether each shot landed, whether an overnight low is a probe fault, why one zone drinks differently, whether the
  zone is on the stage's arc for today's day of flower, and which alerts buzz a phone.
- **The owner's own crop-steering doctrine** (his GrowLabs wiki: TEROS-12, closed loop, flowering stages, rockwool,
  one steering law, slab strategy, ripening) is written into every question, with the stage arc for each day of flower.
- **Code keeps everything physical.** Jev never opens a valve, sizes a shot, crosses the daily floor or cap, or stops
  a rescue. It can bring a phase forward, set a lying probe aside (on the dead-probe path), choose the EC steer's mode
  and raise advice; each of those passes a code check first. A zone steered vegetative is never stopped early.
- **A council, not a coin toss:** every question is asked in two phrasings, and Jev acts only when both lead to the
  same action.
- **Everything is shown:** a Jev sensor per zone and per room, and a log of what acted and how it turned out.
- **Two ways to reach Jev:** a TypeSafe API key, or a Cloudflare Workers AI account and token.

### 🔧 Technical notes

- **Runtime (`addons/f2_control/f2_control/jev/`):** `client` (a background asker with a daily budget; TypeSafe direct
  or Cloudflare), `council` (two phrasings, `firm_in` action groups), `context`, `envelope`, `ledger`
  (`/data/jev_ledger.jsonl`), `brain` (decides once per answer, re-admits the standing directive each pass), `triage`,
  `doctrine` (99 cited rules, the slab-guide stage arc). Judges: dawn, ramp, salt, dusk, probe, shot, night, zones,
  stage. `jev_bridge.py` feeds the controller's pass; the controller calls it in `_loop_room`, `_advance_shot_counters`
  and `_alert`, each inside a try that leaves the base engine's decision.
- **New alerts:** CS-701 water not reaching a zone, CS-702 a zone's water per plant out of line, CS-703 an overnight
  low that looks like a probe fault, CS-704 a probe Jev set aside, CS-705 a zone off its stage's arc.
- **Options:** `typesafe_api_key`, `jev_enabled`, `jev_judges`, `jev_daily_calls`, `jev_flower_start`,
  `jev_flower_days` (with the existing `cf_*`). Sensors: `sensor.crop_steering_<prefix>zone_N_jev`,
  `sensor.crop_steering_<prefix>jev`.
- **Upgrade from the original:** a different repository, so the controller app moves once, carrying `/data/state.json`
  and its options (docs/INSTALL.md); the integration keeps its domain and entity ids. No state-file change.

## Older releases

Releases 2.13.0 to 2.25.1 are in [docs/archive/CHANGELOG-2.x.md](docs/archive/CHANGELOG-2.x.md). Releases before 2.13.0 (up to July 2026) are in the git history of this file.
