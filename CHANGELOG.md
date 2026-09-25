# Changelog

All notable changes to the Advanced Automated Crop Steering System will be documented in this file.

**Two views per release.** Each version leads with **🌱 In plain English** — what changed and why it
matters, written so anyone can follow it without knowing the internals — followed by **🔧 Technical
notes**, the entity- and code-level detail for developers and AI agents working on the repo.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.22.0] - 2026-09-25

Pair: **controller 2.22.0**. Its code is unchanged: the app serves the new dashboard. Class **C2**:
stock tanks add integration entities, services and a Repairs card. Every other change is class
**C1** (dashboard only, nothing the controller or the integration reads) or **C0** (CI).
**Owner-approved rehearsal release** (the owner, 25 September 2026), no staging soak; see the
release audit. Not run on hardware; checked by the lean, controller, real-Home-Assistant and
browser suites.

### 🌱 In plain English

- **Stock tanks.** A new Stock tanks page keeps track of the nutrient concentrates each batch tank
  is dosed from. Give each one its size, how much goes into one batch and a low mark. Every batch
  tank made takes its dose from every stock tank: it is counted when the tank's last-fill time
  moves on, or with **Record a batch** in a room without that sensor. The dose can follow a
  doser's own dose setting. At the low mark a Repairs card (CS-608) and an Overview notice say
  about how many batches are left, and `sensor.crop_steering_<room>stock_low` rises above 0 for a
  phone alert. **Refilled** or **Set level** clears it.
- **The Overview reads at a glance.** Each zone shows how fast it is drying, in VWC points per
  hour with a line of its last two hours; water today against its daily limit (amber from 80 %,
  red once spent); moisture against the current phase's target; and green or red valve pills.
  The four room numbers get one small bar per zone and an average per zone.
- **The same visuals on every page:** Zones, the zone sheet, Sensors (with a six-hour line for
  every numeric sensor), Activity, Insights, Compare runs, Rooms & setup and Settings. Colour only
  ever means a state.
- **Water use per zone** on the Zones page: today, this week, since the grow started and an
  estimate for the whole grow, with a bar of litres per grow week. It reads Home Assistant's
  long-term statistics, which it keeps for good.
- **Type the balance into the whole-grow table.** On the Schedule page, click a week or a day,
  type 0 to 100 (% generative) and press Enter. Under the table: the setpoints that balance gives,
  how far it moves from the week before and to the week after, the zone's readings today and the
  balance across the grow. Nothing is saved until Review & save.
- **The tank card graphs its EC and pH.** A 24-hour line beside each value, and a History panel
  over 24 hours, 7 days or 30 days. Where the controller checks feed water on a probe, its limits
  are drawn too.
- **No false "Controller not running" while it waters.** The dashboard now waits 10 minutes, the
  integration's own limit, before calling the controller silent. While a zone valve has been open
  no longer than the room's maximum shot, it says **Watering** instead.
- **The sidebar page updates itself.** Its address carries the version, so a browser fetches the
  new dashboard after an update instead of showing the old one for hours.
- **The online demo follows each release** (CI).

### 🔧 Technical notes

- **Stock tanks (#91, C2).** `stock.py` holds the pure rules (`clean_tanks`, `dose_ml`, `draw`,
  `refill`, `parse_fill`, `new_batch`, `batches_left`). `stock_api.py`'s `StockStore` keeps each
  room's tanks in `Store(hass, 1, "crop_steering.stock.<entry_id>")`, revisioned behind a lock;
  a change becomes the room's data only after the save succeeds, and corrupt stored data is
  reported, never overwritten. Batches are counted from `async_track_state_change_event` on the
  room's `tank_last_fill_sensor`: the first time seen is a baseline and only a strictly newer one
  counts. Services `stock_get` (read-only) and `stock_save`, `stock_refill`, `stock_record_batch`
  (admin, `expected_revision`). `sensor.crop_steering_<prefix>stock_low` (count of low tanks,
  tanks as attributes, not polled). Repairs `stock_low` is in `health.ISSUE_IDS` and survives a
  room switched off. Error code CS-608.
- **Panel cache (#89).** `setup_panel.py` registers `dashboard.html?v=<SOFTWARE_VERSION>`.
- **Mini visuals (#90, #95).** `lib/dryback.ts` (`drybackTrend`: a least-squares slope after a
  5-minute settle, at least a 10-minute span, a 2-hour window) and
  `components/mini-visuals.tsx` (`MiniBars`, `Meter`, `Sparkline`, `.pill`), used on every page.
  Sensors asks Home Assistant for all its lines in one history request.
- **Water use (#94).** `lib/water-use.ts` and `components/water-use.tsx`:
  `recorder/statistics_during_period` (hourly) inside Home Assistant, REST history when opened
  standalone. Grow-days start at lights-on; a grow-day's total is its counter's peak after the
  reset. The start comes from the plan when it is armed or saved, else the first day with water
  after at least five dry grow-days.
- **Whole-grow table (#93).** Each cell is an input: a whole number 0 to 100, applied on Enter or
  blur, Esc cancels, arrows and Tab move. `grow-plan.ts` gains `columnRange`, `rangeBlock`,
  `parseBalance` and `setpointRows`; `replaceRange` rejoins matching neighbours. Read-only while a
  plan is armed or active.
- **Tank history (#96).** `lib/tank-history.ts` and `components/tank-history.tsx`. The dashboard's
  history reads also allow the room descriptor's `tank_ec_sensor` and `tank_ph_sensor`, up to
  720 hours, one day per request with two in flight. Gate lines only while `feed_ec_sensor` /
  `feed_ph_sensor` are mapped, as `controller.py` applies them.
- **Watering, not silent (#98).** `HEARTBEAT_STALE_MS` goes from 5 to 10 minutes. `shotRunning()`
  (a mapped zone valve ON for no longer than the room's `max_shot_duration`, else 900 s) turns
  the stale `-controller` notice into an info "Watering" and the status line into Watering.
- **Demo (#92, C0).** `promote.yml` dispatches `pages.yml` on `main` after its apply step.
- The three dashboard bundles are rebuilt from the merged source.

## [2.21.0] - 2026-09-25

Pair: **controller 2.21.0**, one number for both halves from this release on. Class **C3**: the
controller and the integration change; the engine does not. **Owner-approved rehearsal release** (the
owner, 25 September 2026), no staging soak; see the release audit.

The Overview timeline is class **C1**: dashboard only, nothing the controller or the integration
reads. Not run on hardware; checked read-only against a live room's recorded history. A shot cut
short by something else is class **C3** (irrigation behaviour, controller only). Not run on
hardware; the 23 September event is replayed in the controller suite. A shot interrupted by a
Home Assistant restart is class **C3** (controller only). Not run on hardware; the restart is
replayed in the controller suite.

The dashboard changes below are class **C1**: dashboard only, nothing the controller or the
integration reads. Not run on hardware; checked by the browser contract scripts.

### 🌱 In plain English

- **The Overview shows the day, first.** Its moisture and EC chart is replaced by the room's
  grow-day, at the top of the page under today's totals, from lights-on to the next lights-on, one row per zone on one time axis: lights-off shaded, the
  phase each zone was in, every shot (the valve opening, as wide as it was open), what held a zone
  back and for how long (a spent daily budget hatched red, *blocked 13:31–22:00*; a gate such as a
  dosing hold or the kill switch outlined amber), and every setpoint change, from what to what.
  Point at or tap any of it for the details; the same events are listed in words below.
- **What comes next is marked as an estimate.** The rest of the day is drawn dashed: P2 until
  lights-off and P3 from there. For a zone in P2 whose moisture has been falling steadily since
  its last shot settled, the dry-down is drawn to its re-water threshold: *next shot ≈ 14:20*.
  With too little recent data, a shot running or a hold open, it says why there is no estimate
  instead of guessing. A zone in P1 shows its next shot from the ramp's interval, one in P0 the
  latest time P1 can start; how long P0 and P1 last is not drawn, because nobody knows.
- **One line per zone:** its phase and for how long, P1 shots so far against the ramp's maximum,
  litres used against the daily budget, and the next expected shot. Moisture is scaled to the
  day's own readings, not 0–100 %; zones are named, never told apart by colour alone; red, amber
  and green only ever mean a state. The age of the newest reading is shown, and it fits a phone.
- **No new polling.** The day's history is read once when the Overview opens (inside Home
  Assistant over its own connection) and kept current from the updates the dashboard already
  receives.
- Insights keeps its moisture and EC chart.
- **Headings say what the page is, once.** The Overview is titled after its room (*Flower 1
  overview*). The sentences under page headings that only repeated them are gone; Today's targets
  and Scheduled targets keep theirs, because they say how a schedule and a draft behave.
- **The Overview is the room now.** Water per zone and per plant is on Zones, which already had
  it; the zones table keeps each zone's water today. The scheduling summary is gone: the status
  line at the top of every page already says whether the room is watering and why not. Recent
  activity opens beside any page from the top bar, and the daily workflow is now a linked daily
  routine at the top of Help & tools.
- **The Overview is shorter and balanced.** Under the grow day, the zones sit beside the tank
  instead of below it (on a phone they stack as before). The tank card has the same space above
  the tank and *Tank EC* as beside them, where before they sat flush under the heading, and shows
  the level, EC, pH and temperature with the pump, filling and last fill in one row, and one
  short line on what the pump and fill readings do not prove. The zones
  table carries each zone's target under its moisture and fits without scrolling sideways. The
  sentences under panel titles and the captions under today's totals moved into tooltips. At
  1440 px wide the Overview is under two screens tall; it was more than three.
- **A calmer look.** No text smaller than 12 px anywhere (118 places were 7–11 px, and the
  plan graph's labels 10.5–11 px), page and panel titles and today's totals in one semibold weight, no divider under every panel title, no shaded band behind
  table headers, neutral status chips with a coloured dot, and a quieter menu. Colours still
  follow your Home Assistant theme.
- **A shot that something else cuts short now ends there, and only the water it gave is counted.**
  On 23 September at 11:25 the batch tank ran empty 4 seconds into a zone 1 shot. The dosing
  automation took the tank and its pump, and the feed guard closed the valve and main line. The
  controller did not notice: it waited out the full 170 seconds and counted about 7.9 litres for
  about 0.2 litres delivered. It now checks during every shot, about every 2 seconds: when one
  of its holds (dosing, a tank fill, a flush) comes on, or the zone's valve is switched off by
  something else, the shot ends there and only the seconds the valve was open are counted. It
  closes its own valve and main line if they are still open, never touches a pump a hold is
  using, and sends one alert saying what ended the shot. A feed path closed by somebody else is
  not a hardware fault. Nothing is switched off on a timer, and the kill switch and manual
  override work as before.

- **A shot interrupted by a Home Assistant restart is closed, not left running.** If Home Assistant
  restarted (an update, a power blip to the host, a crash) or a valve's device reconnected while a
  shot was open, the valve kept running: after a restart Home Assistant says every switch changed
  just then, so the controller took its own open valve for someone hand-watering and left it on,
  with no alert. It now reads the valve's history: ON since the shot opened it, with only the
  restart in between, is the shot's and is closed (valve first, then the main line and pump, as
  always). A valve someone switched off and on again, or had on before the shot, is still left
  alone. If Home Assistant has no history for it, nothing is switched and the *may still be ON*
  notification (CS-309) says so, every loop until it can tell.

### 🔧 Technical notes

- New `frontend/src/lib/day-timeline.ts` (pure, tested): `growDay()` (lights-on to the next
  lights-on in the browser's time zone, as `foldRecorded` folds days), `phaseBands()`,
  `valveShots()`, `alignBands()`, `zoneBlocks()`, `setpointChanges()`, `levels()`, `readings()`,
  `dryDown()` (least squares over the last hour from 15 minutes after the last shot ended: at
  least five readings over at least 15 minutes, falling at least 0.1 %/h), `nextShot()` and
  `appendLive()`.
- Shots are the zone valve's on→off intervals (valves from the room's `engine_config`). The
  controller posts a loop's decision and phases after that loop's shots, so a shot is named by
  the first `current_decision` row after its valve closed (its `fired` entry,
  `Z<n> <phase> <reason>`), and a phase change posted by the same loop starts at the shot
  (`alignBands`). Holds are the zone's `current_decision` `blocked` entries, one interval per
  unbroken run of the same hold (numbers in the text may change): `daily-cap` is the budget,
  `BLOCK` a refusal, anything else a gate.
- Loading: `Controller.timeline(request)`. Inside Home Assistant, `history/history_during_period`
  on `hass.connection` (`live.ts` `liveHistory`): states without attributes and
  `minimal_response`, and the decision sensor with attributes and
  `significant_changes_only: false`. Standalone, `GET history/period` in chunks of 40 entities
  (`client.ts`). Limited to the selected room's entities and mapped valves, and to one grow-day.
  Loaded once per room and grow-day; `appendLive()` then adds each subscribed (standalone: each
  polled) change.
- Demo: `demoDay()` generates a grow-day on the demo probes' own day shape (P0, six P1 shots, P2
  top-ups, P3), shifted per probe, with a feed-EC hold on Flower 2 zone 2 ended by a feed-band
  change and Flower 1 zone 3 held since it was disabled.
- `pages/overview.tsx` renders `components/day-timeline.tsx` in place of `HistoryChart`, which
  stays on Insights, directly under the totals strip and above the tank and zones.
- `Heading.description` is optional. `pages/overview.tsx` titles itself `${room.name} overview`
  (plain *Overview* when no room is discovered). `.page-heading` margin 30/25 → 20/20 px (16/16 on
  a phone).
- New `components/activity-panel.tsx`: a top-bar button on every page opens a right-hand sheet
  with the room's last ten events (`EventList`) and a link to Activity. The Overview loses its
  Recent activity panel, the daily workflow card (now `ol.daily-routine` in Help's intro), the
  `DailyWaterSummary` table (still on Zones) and the `room-summary` block; their CSS goes with
  them.
- `.overview-grid` (zones `7fr`, tank `3fr`; one column under 1200 px). `ZoneTable({ compact })`:
  no *VWC reference* or arrow column and no zone icon, the target under moisture (its label
  wraps), `LastIrrigation({ compact })` without the date line. `components/tank-status.tsx` rewritten compact: a 100×120 drawing whose
  shape touches its box, `dl.tank-quality` and `dl.tank-equipment`, one 20 px inset; the hooks
  and value strings are unchanged. `Metrics` shows only the *waiting for controller data*
  caption. `DayTimeline` loses its heading paragraph. `verify-tank-status.mjs` holds the tank's
  top inset to its left inset.
- `styles.css` set its type and chrome twice: the original rules, then a later "Home
  Assistant-native density" block overriding them (`h1` 26/400 over 28/650, `h2` 20/400 over
  17/650, panel heading padding, table sizes, metric weight, nav weights). Each is now set once,
  in the original rules, and several changed: `h1` 24px/600, `h2` 16px/600, table text 13px with
  no header band, today's totals at weight 600; the later block keeps only the theme mappings. New `:root` tokens
  `--text-xs`…`--text-2xl` (12–24 px) and `--space-2`…`--space-6`. New `lib/type-scale.test.ts`
  fails any stylesheet under `frontend/src` that sets text below 12 px, a relative size without
  a 12 px floor (`.unit` is now `max(0.52em, 12px)`), or chart text below 12 px (the plan graph's
  `fontSize` 10.5/11 → 12). `.status-good` is a
  neutral pill (it leaves the `--primary-strong` contrast list); `nav button.active` has a
  neutral fill with a 2 px accent bar.
  The Overview's compact zones table keeps ages and units on one line at the larger table
  text; phone-only panel title sizes (18/20 px) are gone.
- **Controller** (`controller.py`), a shot cut short from outside: in every round `_wait_shot` also
  reads each `hold_entities` entity (ON as `_blocked` reads it, the shared `ON_STATES`) and the
  shot's own valve, with the same bounded reads and sleeps of at most 2 s between rounds, after the kill
  switch, `room_active` and manual override, which therefore still win. It returns
  `(elapsed, None | ("abort", entity) | ("external", entity))` instead of `(elapsed, bool)`. The
  valve reading OFF counts only once it has been seen ON in that shot: right after `turn_on`, Home
  Assistant can still show the old OFF (a Zigbee report can lag 1.6 s). `_execute_shot` hands an
  external stop to the new `_close_cut_short`, which switches off the shot's valve and main line
  unless they read OFF, and its pump unless it reads OFF or a hold is ON (the `_inflight_plan`
  rule). It reads back only what it switched off: a switch of its own that will not close still
  latches the hardware hold and keeps the record for the reconciler. Otherwise it clears
  `shot_inflight` as the normal close does. The error cleanup, which switches off all three, never
  runs for such a shot. Counted time: the valve's `last_changed` when it reads OFF and that falls
  between the valve opening and the detection, else the detection. Counters as for a kill-switch
  abort: the shot counts, with the volume delivered. One alert, `cutshort_<room>_z<n>` (*shot
  stopped early, something else closed the feed*, CS-307), debounced like the others, names the
  entity and the seconds delivered against planned. No change to add-on options, the state file,
  entities or the normal shot.
- **Controller** (`controller.py`), an interrupted shot after a Home Assistant restart: when a
  switch the in-flight record names reads ON with `last_changed` outside `INFLIGHT_OPEN_WINDOW_S`,
  `_inflight_plan` no longer hands it to a person on that alone. New `ha_history()` reads
  `GET history/period/<start>` (`minimal_response`, `no_attributes`, `end_time` now) from the
  window's start, and the pure `_on_since_shot()` decides: ON inside the window with only
  `unavailable`/`unknown` after it is the shot's (closed as before, with the line-in-use and hold
  rules unchanged); ON before the window, first ON after it, or an OFF after the shot opened it is a
  person's (left, record closed); no readable history, or a row it can't read, is `unsure` (CS-309,
  record kept, retried every loop). CS-309's catalog entry and alert text say so. The add-on test
  rig gains `FakeHA.ha_history` and an autouse fixture so no test reaches a real history endpoint.


## [2.19.5] - 2026-09-23

Pair: **controller 0.16.5**. Class **C3**: engine, controller and integration. **Owner-approved rehearsal
release** (the owner, 23 September 2026), no staging soak; see the release audit.

The irrigation changes (engine and controller) are class **C3**; the plan, setup and Repairs changes
are class **C2**. The zone status change is class **C3** (controller and integration).

### 🌱 In plain English

- **A grow plan never stops a starving zone from being watered.** While a room's grow plan is held
  (in error, out of date, or missing after a restart) the controller held every shot on every zone
  the plan runs, for as long as the hold lasted. Now the overnight emergency shot, the lights-on
  watchdog and the minimum daily volume still water those zones; only the routine steering waits
  for the plan. A zone with a dead probe keeps its timed safety schedule too. The kill switch,
  a hardware fault, the zone switches, bad feed water and the daily budget still stop them, as
  before.
- **A missed minute at lights-on no longer holds a room all day.** A plan moved on to the new day
  only in the two minutes after lights-on. If Home Assistant was restarting then, or the
  controller or a probe was a few minutes late, the plan went into error and held every zone
  until the next lights-on. Now it applies the new day at the first minute it can, and keeps the
  previous day's targets until then. Changing the lights-on hour while a plan runs, or a lights-on
  hour that falls in the daylight-saving jump, no longer puts it in error either.
- **Zones cannot be changed under a running plan.** Setup now refuses to add or archive zones, or
  to archive the room, while its plan is armed or running, instead of saving the change and
  putting the plan in error. Disarm the plan first.
- **Repairs says when a plan is holding.** A card appears for every hold (the plan in error, the
  controller unable to use it, a zone the plan does not steer today), and a warning while a plan
  has not moved on to today, each with the reason.
- **The zone status sensor has one writer.** The zone status in Home Assistant had two authors
  taking turns about twice a minute: the integration, with a fixed 40 % moisture threshold
  (*Dry - Needs Water*), and the controller, with its phase-aware label (*Overnight dryback*). The
  controller now publishes its label on a separate entity, and the zone status shows exactly that,
  with its reason. When the controller has not reported for 10 minutes the zone status says
  *Controller not reporting* instead of guessing from a threshold. Cards and automations keep the
  same entity. Until the controller is updated too, the zone status shows the older controller's
  own label, as before, and is no longer fought over.

### 🔧 Technical notes

- **Engine** (`crop_steering_engine/core.py`, and the vendored copy): new
  `ZoneSnapshot.steering_held` (default `False`, so every caller is unchanged). When it is set,
  `decide()` skips the per-phase steering rules and the anti-lockout flush (it steers to
  `max_ec`, a plan setpoint) and fires only the P3 emergency, the watchdog and the minimum-daily
  floor; the high-EC blocks still apply and phases still move. Holding only the routine decision
  in the controller was not enough: a zone drying in P2 is a top-up first, so the watchdog behind
  it never came up.
- **Controller** (`controller.py`): `_snapshot` sets `steering_held` from `strategy_block`.
  `PLAN_HOLD_EXEMPT` = `p3_emergency`, `watchdog`, `min_daily`, `blind_fallback`,
  `blind_copy_rescue`; `_blocked(room, zone, reason)` lets those kinds through the plan hold (and
  logs it), and `_execute_shot(plan_exempt=True)` skips the plan preflight for them. The blind
  decisions are typed: FALLBACK is `blind_fallback`; COPY is `blind_copy_rescue` when the
  sibling's shot is one of the rescues, else `blind_copy`; none is exempt from the daily budget.
  A held zone that is not firing publishes the hold as its `block`, so the zone status and
  `current_decision` still show it.
- **Integration, plan** (`strategy.py`): `tick` applies the latest lights-on on the first tick
  that can (`_advance`), not only within 120 s of it. `activate` / `disarm` record
  `armed_at` / `disarm_at`, which take effect at the first lights-on after them by the current
  `lights_on_hour` (`_due`), so a changed hour re-anchors them; a day already applied is never
  applied again (`grow_day >= day`), and a later hour never takes the plan back a day. Lights-on
  is built per local date and compared in UTC (`_lights_on`, `_boundary`, `_next_boundary`): an
  hour inside a daylight-saving gap is the instant the clocks jump to, and `now - boundary` no
  longer compares wall clocks across a change. A recoverable fault (stale heartbeat, flag, zone
  switch or probe at lights-on, a failing hydraulic preview, an unreadable `lights_on_hour`,
  storage) keeps the last valid snapshot published and sets `degraded_reason` (a plan sensor
  attribute and a `strategy_get` response field), retried every tick. Only zones that no longer
  match the plan (or an archived room) are an error (`_Hold`), stored once instead of every
  minute. `async_init` no longer turns a missed lights-on into an error. The response's
  `armed_after` / `disarm_after` are computed from `armed_at` / `disarm_at` by the current hour.
- **Integration, setup** (`setup_api.py`): `safety_blockers` adds `_plan_blocker`: with a
  proposal, a change of the active zone set or archiving the room is refused while the plan is
  armed, active, disarming or in error. A change back to the plan's own zones is allowed.
  `remove_setup` passes its archive as the proposal. Covers `save_setup`, `remove_setup`, the
  options flow's zone map and `.env` reload.
- **Integration, Repairs** (`health.py`): `strategy_hold` (ERROR: plan status `error`, or a fresh
  heartbeat's `strategy_error`; WARNING: a zone the active plan does not steer today) and
  `strategy_degraded` (WARNING: `degraded_reason`), with `{reason}`; both cleared with the room's
  other cards when it is switched off. Translations in `strings.json` and `translations/en.json`.
- **Existing installs:** no state-file, option or entity-id change. A plan document stored by an
  older version (no `armed_at` / `disarm_at`) keeps working from its `armed_after` /
  `disarm_after`, and one stored in error with "Lights-on boundary was missed" applies its day on
  the first tick. An older controller with this integration sees fewer holds; this controller
  with an older integration still waters the rescues through its holds.
- **Tests:** `crop-steering-engine/tests/test_steering_held.py`,
  `addons/f2_control/tests/test_plan_hold_never_stops_rescues.py`,
  `tests/test_plan_never_holds_a_room_all_day.py` (stale heartbeat or probe at lights-on, Home
  Assistant down across it, the lights-on hour moved later and earlier, the Pacific/Auckland gap
  on 27 September 2026, a zone change while armed), new cards in `tests/test_health.py`, and
  `tests_ha/test_plan_holds.py` (the options flow refusing a zone change under an armed plan and
  saving it under a draft; every hold, and a plan that could not apply its day, in the real
  Repairs registry). `test_active_store_survives_reload_without_midday_reapplication` now asserts
  the stored snapshot stays active with a `degraded_reason` where it asserted the error, and
  `test_disarm_waits_for_next_boundary_and_survives_missed_boundary_restart` that the missed
  release is made on the first tick.
- **Zone status, one writer** (class C3: controller and integration). The controller publishes
  `sensor.crop_steering_<prefix>zone_N_status_app` (state: the `zone_status_label`; attributes
  `reason`, `friendly_name`, `engine`), `Room off` included, and no longer writes `zone_N_status`.
  The integration's `zone_N_status` (`CropSteeringZoneStatusSensor`, same unique id and entity id)
  mirrors it through `zone_status.mirrored_status`: the label and its reason, or
  `Controller not reporting` when the app entity is missing, `unknown`/`unavailable`, or its
  `last_reported` (else `last_updated`) is more than 10 minutes old, the engine-offline repair's
  limit. It is not polled: it updates on the app entity's `state_changed` and checks staleness
  every minute, and writes only when what it shows changes, so a 0.16.x controller still writing
  `zone_N_status` is left alone rather than overwritten every 30 s. With a controller from this
  release and an older integration, `zone_N_status` shows that integration's threshold label.
  `VWC_DRY_THRESHOLD` / `VWC_SATURATED_THRESHOLD` removed from `const.py`. The label and reason
  are now recorded on both entities; exclude `sensor.crop_steering_*_status_app` from the
  recorder to keep one copy. Tests: `tests/test_zone_status.py`,
  `addons/f2_control/tests/test_zone_status_one_owner.py`,
  `tests_ha/test_zone_status_one_owner.py` (an older controller's writes are not fought; with this
  controller there is exactly one writer). The two add-on tests that asserted the controller
  writing `zone_N_status` now assert `zone_N_status_app`.

## [2.19.4] - 2026-09-23

Pair: **controller 0.16.4** (no controller code change: it serves the 2.19.4 dashboard). Class **C1**:
dashboard only, nothing the controller or the integration reads. **Owner-approved rehearsal release** (the owner,
23 September 2026), no staging photoperiod; see the release audit.

### 🌱 In plain English

- **The dashboard says when the controller is not running.** After a Home Assistant restart with
  the controller app stopped, its heartbeat simply disappears, and the dashboard looked normal:
  only a heartbeat that was present but old raised a yellow warning. A room that is switched on
  now raises a red *Controller not running* notice whenever the heartbeat is missing, unreadable
  or more than five minutes old, and its zone phases and statuses are marked *Stale*.
- **A status line on every page, for every room.** It says whether the room is watering, holding
  and why, or not watering and what to do about it (engine switched off, a setup change waiting to
  be adopted, stuck hardware, a grow plan hold, the controller stopped), and how old the
  controller's last report is: amber after two minutes, red after ten. Phones show it too.
- **Red notices are never pushed off the Overview.** Notices are ordered red, then yellow, then
  information. The Overview showed the first three in the order they were raised, so an
  information notice could hide a red one; every red notice is shown now. Zones with the same
  problem share one notice.
- **Zone status follows the controller.** Two writers share the zone status sensor. While the
  controller is running, the dashboard shows the controller's phase-aware status, and it never
  shows the integration's fixed-threshold *Dry - Needs Water* during P3, where drying back
  overnight is the plan.
- **The dashboard no longer downloads all of Home Assistant twice a minute.** Inside Home
  Assistant it fetched every entity (3.3 MB on a large install) every 30 seconds for each open
  tab, twice more for every change you applied, and kept going in a hidden tab. It now downloads
  once when it opens, then receives only changes to the few hundred entities it shows, as they
  happen, over Home Assistant's own connection. Opened on its own, outside Home Assistant, it
  still checks every 30 seconds, but not while the tab is hidden, and at once when you come back.
  Recorded sensor history loads its window once, then only the newest readings each minute.

### 🔧 Technical notes

- Dashboard (class C1, nothing the controller or integration reads): new
  `frontend/src/lib/controller-health.ts`. `readHeartbeat` dates a beat by the heartbeat's
  `last_updated` (UTC, the clock the integration's health check uses), falling back to the naive
  local `last_beat`; missing, unreadable (no usable time, or `unknown`/`unavailable`) and older
  than 5 min all count as not running. `controllerZoneLabel` mirrors `zone_status_label` in
  `crop_steering_engine/core.py`, rebuilt from the zone phase and its `reason` and
  `current_decision` `fired`/`blocked`; it is used while the heartbeat is fresh and the status
  sensor holds the integration's value (no `reason` attribute).
- `model.ts`: `buildRoom` raises `<room>-controller` (critical) in place of
  `<room>-stale-heartbeat` (warning), sets `Zone.stale`, merges identical per-zone notices into
  one (`zones-1-2-3-sensors`, no `zoneId`) and sorts alerts critical > warning > info. New
  `roomStatus()` (the status line, rendered by `components/status-line.tsx` above
  `RoomOffBanner`) and `leadingNotices()` (Overview: every critical, then up to three).
- Demo: heartbeats carry `last_beat` and are restamped on each demo refresh; each demo room
  publishes `app_status` and `current_decision`; demo zone statuses carry a `reason` like the
  controller's.
- Dashboard (class C1, nothing the controller or integration reads): new
  `frontend/src/lib/live.ts`. Inside the Home Assistant iframe (parent `hass.connection`),
  `/api/states` is fetched once for discovery (again only on Refresh, after a Setup or plan change,
  and on a websocket reconnect), then `subscribe_entities` covers `watchedEntities()`: every
  `*.crop_steering_*` entity, what room descriptors and heartbeats point at (kill switches, pumps,
  valves, tank and feed sensors), and the controller's per-zone sensors even before it has posted
  them. `applyEntityUpdate()` applies the compressed events; updates are published in 250 ms
  batches. A socket down for two 30 s ticks shows the offline banner; a refused subscription
  falls back to polling. Standalone: `whileVisible()` polls every 30 s only while the page is
  visible and refreshes on `visibilitychange`/`focus` (at most once per 10 s).
- Writes no longer fetch all states before and after: the preflight and the readback read only
  the written entities (`GET /api/states/<id>`) and merge them, never over a newer state.
- `sensor-context`: the 72–168 h window loads once; each minute `historySpan()` asks only for the
  time since the last load plus two minutes, and `mergeSeries()` folds it in.
- Known limit: a room or zone created from Home Assistant's own integration pages, not this
  dashboard's Setup, appears after Refresh, a reload or a Home Assistant reconnect.

## [2.19.3] - 2026-09-23

Pair: **controller 0.16.3**. **Owner-approved rehearsal release, no staging soak**: the owner
approved releasing on 23 September 2026 ("do all of it now") after the F2 dry tails of 21-22 September; the
release audit on the GitHub release names what was and was not exercised. Update with the engine off, read
the controller log, then watch the first shots.

The irrigation changes (controller and engine) are class **C3**, from the F2 history of 21-22 September
2026 and the review of it.
**Not run on hardware.** No add-on option changes. The state file gains three additive keys that the
previous controller ignores, so it can still read the file after a rollback.

### 🌱 In plain English

- **A room deleted and set up again starts fresh.** Home Assistant keeps the last state of a removed
  entity for seven days, and a re-created room inherited the deleted one's settings, its room on/off
  switch and its kill switch: a room deleted while armed came back armed. Now a room only takes back
  values saved after it was created. An existing room restarts exactly as before.
- **The controller adopts a re-created room afresh.** It used to go on driving the room that no longer
  existed: with a different valve in the new room, arming it would have watered through the **old**
  valve. The integration now says which room it is, and a new room is adopted through the usual gate
  (kill switch and hardware OFF first).
- **Setup shows the version that is running, and waits for a restart.** After a HACS download Home
  Assistant keeps running the old code until it restarts; setup now says which version is running and
  will not create a room on stale code. *Configure* is never blocked.
- **Tested against the Home Assistant you run.** The real-Home-Assistant tests now run on HA 2026.9.3
  (Python 3.14) and on the oldest version supported, now **2024.10.0** (2024.3 never passed).
- **One repository.** The controller app is now installed only from this repository. The old
  `f2-control` mirror, which a release script pushed a copy to, is retired: it gets no more
  releases, and nothing in this repository writes to it. A controller installed from the mirror
  moves once; [docs/INSTALL.md](docs/INSTALL.md) has the steps, which carry its learned state and
  settings across. Never run the old and the new app at the same time.
- **Only an administrator can change plans, recipes and run records.** The Crop Steering sidebar
  is open to every Home Assistant login, and until now so was everything it can change: any
  login, a staff phone or the hallway kiosk, could arm a plan with a future start date (which
  holds every zone), disarm the plan that is running, or replace every room's recipe. Through
  the Crop Steering actions, which is what the sidebar uses, saving, arming and disarming plans,
  changing run records and recipes, holding a zone, forcing a phase and requesting a shot now
  need an administrator's login, as room setup already did. Everyone else can still open the
  sidebar and look. **Automations are not affected**: they run with no login of their own, even
  when a person set them off. A script that someone who is not an administrator starts from a
  dashboard is refused, like that person. Not changed: the room's own switches, selectors and
  numbers (a zone's hold switch, the phase selector, a setpoint) are Home Assistant entities and
  still follow Home Assistant's own permissions, so an ordinary login can still change those.
- **A zone that has used its day's water can still be rescued.** On 22 September Zone 1 had no water
  from 14:06 until lights-off with its moisture under the re-water line: the daily limit was reached
  by midday, and the limit also stopped the "no water for 3 hours" safety shot. That safety shot, the
  overnight emergency shot and the high-EC flushes now always pass the daily limit. Routine top-ups and
  EC-correction shots stop at it, and a shot that would cross it gets only what is left, not a ten
  minute shot with two litres of budget remaining.
- **The morning ramp always finishes, and never waits all day.** P1 runs in full whatever it is set
  to: it stops at its target or its maximum number of shots, not at the daily limit. Once the zone is
  full and only pore EC is keeping the ramp open, a spent budget ends the ramp instead of holding the
  zone in P1 with nothing it is allowed to fire.
- **Pore EC is read when it means something.** For the first 45 minutes after a shot the probe reads
  the fresh water passing it (6 to 8 mS/cm during the 22 September ramps, on zones that read about 4.5
  when left alone). Every EC decision now uses the last reading taken at least 45 minutes after a shot,
  so a passing spike no longer keeps the ramp flushing, doubles a shot or fires a flush, and an EC
  flush waits for the next such reading before it is repeated.
- **No safety shot at lights-on.** The whole night counted as "3 hours without water", so every zone
  got a safety shot the moment the lights came on, before its morning dry-back. The dry-back now comes
  first, as intended.
- **A restart after lights-on starts a proper day.** If the controller was not running when the lights
  went off (a reboot left it stopped), it came back in yesterday's P2 with yesterday's water already
  counted, and watered nothing all day. It now starts the day at P0 with its own budget.
- **A shot interrupted by a crash is closed at the next start, and nothing else is.** Before opening
  anything the controller writes down what a shot is about to open. If it dies mid-shot, or loses Home
  Assistant during the close, its next loop closes exactly that valve, main line and pump. **It never
  switches anything off on a timer or on suspicion.** The tank is circulated for well over 20 minutes to
  heat it, and zones are hand-watered with the valves and main line open: anything a person has
  switched since the shot started is theirs and is left alone, together with everything upstream of
  it; the pump is left alone while a hold (dosing, fill, flush, circulation) is on or another valve on
  the line is open; and nothing at all is touched while the room's kill switch is off.
- **Stopping or updating the app no longer switches everything off.** It used to switch off every pump
  and valve it knew, which ended tank circulation and hand-watering whenever the app was stopped,
  updated or restarted. Now it closes only the shot it has running, by the same rules as above, and
  counts the water that shot gave. With no shot running it switches nothing off. A pump that reports
  OFF a second late no longer latches a false hardware hold after a failed shot either (the
  15 September problem, on the one path the earlier fix missed).
- **A critical alert raised while Home Assistant is unreachable is not lost.** It is raised again until
  Home Assistant has it; the 30-minute quiet period starts only then.

### 🔧 Technical notes

- #49 `room.restored_state_is_ours(entry, last_state)` (`last_state.last_updated >= entry.created_at`,
  lenient when either is missing or naive) gates restore in the number, switch and select platforms.
- #50 the descriptor gains `entry_id` (not a fingerprint key); `Controller._is_another_room` re-opens
  adoption when it changes; first sight is remembered and changes nothing; `_setup` gains optional
  `entry_id`.
- #51 `config.step.user`/`room` and `options.step.init` show `SOFTWARE_VERSION`; `async_step_user` aborts
  `restart_required` while the on-disk `manifest.json` differs (read in the executor).
- #56 Validate: `Real Home Assistant` legs pinned (HA 2026.9.3 / plugin 0.13.366 / Python 3.14; HA
  2024.10.0 / Python 3.12) with a version assertion; `tests/run_ci.sh` ends `PARTIAL` (exit 1 unless
  `--allow-skip`) when that tier is skipped; minimum in `hacs.json`, README and INSTALL raised to 2024.10.0.
- `addons/f2_control/config.yaml` `url` points at this repository (metadata only; version unchanged).
- Removed `scripts/prepare_addon_release.py`, `scripts/publish_addon.sh` and
  `tests/test_addon_release.py`, the publisher for the mirror. The add-on's web root is already
  written by `frontend/scripts/package.mjs` and checked by `tests/test_dashboard_layout.py` and
  the Validate bundle check, so nothing it verified goes unchecked.
- New section in `docs/INSTALL.md`: moving an app from `4d457e60_f2_control` (mirror) to
  `6db5faba_f2_control` (this repository), copying `/data/state.json` and the options.
- New `custom_components/crop_steering/admin.py` `async_require_admin`: the one administrator
  check, extracted from `setup_api.py`. It now also runs before every state-changing service:
  `strategy_save`, `strategy_activate`, `strategy_disarm`, `runs_save`, `runs_archive`,
  `runs_import`, `save_recipe`, `apply_recipe`, `set_manual_override`, `transition_phase`,
  `execute_irrigation_shot` and `custom_shot`. Read-only services stay open: `strategy_get`,
  `strategy_preview`, `runs_get`, `check_transition_conditions`. New services are checked by
  default (the read-only ones are listed, not the others). Entity services on the integration's
  own entities (`switch.crop_steering_zone_N_manual_override`, `select.crop_steering_irrigation_phase`,
  `select.crop_steering_recipe_stage`, the numbers, the engine switch) are not covered; Home
  Assistant's entity permissions govern those, and its Users group may control every entity.
- Semantics are those of Home Assistant's own admin services: `context.user_id` empty passes, an
  unknown user id or a non-admin is refused. `setup_*` keep their stricter rule (no user is
  refused too) and their message. The panel stays `require_admin=False`.
- Refusals raise `HomeAssistantError("crop_steering.<service> requires an authenticated Home
  Assistant administrator")`, the type setup already used, not `Unauthorized`: over the REST API
  the console uses, `Unauthorized` is a bare 401 that the http ban middleware counts as a failed
  login (notification, then an IP ban at `login_attempts_threshold`).
- `services.yaml` says so on each checked service. Tests: `tests/test_admin_only.py` (every
  service; administrator, non-administrator, unknown user and no user) and
  `tests_ha/test_non_admin_user.py` (a real Users-group account, and a real automation it sets
  off). The `tests/` call stand-ins for `services.py` now carry a no-user context, as a real
  `ServiceCall` always has one.
- **Typed decisions (engine).** `decide()` still returns `(phase, p2_threshold, fire, size, reason)`;
  `reason` is a `Reason(str)` with `.kind` and `.cap_exempt` (`CAP_EXEMPT`). Exempt: `flush_high_ec`,
  `p1_ramp`, `p2_rescue`, `p3_emergency`, `watchdog`. Not exempt: `p0_ec_flush`, `p1_flush`, `p2_dilute`,
  `p2_topup`, `min_daily`. Non-firing: `idle`, `block_high_ec`, `hold_high_ec`, `block_daily_cap`. This
  replaces the substring test (`"flush" in ir`) that made every "P1 flush/runoff" shot an emergency.
- **Cap -> watchdog.** A non-exempt shot cancelled by the cap becomes the watchdog shot (`p2_shot_size`,
  kind `watchdog`) when the watchdog is due: lights on, not P0, more than `watchdog_hours` since the last
  shot, VWC under the P2 threshold. The watchdog no longer fires in P0.
- **P1 completion over budget.** P1 at `min(p1_target, field_capacity)` with `p1_minimum_shots` in and
  `daily_vol >= max_daily_volume` goes to P2: `P1 complete at ceiling; EC flush over daily budget`.
- **P0 EC flush** gated like the other flushes (feed below pore EC, VWC < FC - 2, `p2_min_interval_min`);
  not exempt.
- **New grow-day in any phase.** P1/P2 with `lights_on and new_grow_day` goes to P0 (`new grow-day -> P0
  (reset)`) and the existing P0 bookkeeping resets the counters. From P1/P2 this needs a dated
  `last_daily_reset` older than the grow-day start, so a fresh zone is never restarted mid-day. Blind
  zones follow the same rule in `_blind_time_transition`.
- **Settled EC.** New last field `ZoneSnapshot.ec_settled` (default `None`); every EC rule uses it when
  present. `EC_SETTLE_MIN = 45`. `_settled_ec` takes the fused reading as settled 45 min after the last
  shot ended (a switch-on anchor is not a shot), holds the last settled value in between, and passes
  `None` while the probe reads nothing valid. Only settled readings feed `ec_smooth`, so the EC step /
  PID. An EC correction acting on a settled value (anti-lockout, P0/P1 flush, P2 rescue/dilute) also
  waits 45 min after the last shot: a held value can never re-fire a cap-exempt flush every 10 minutes.
  The P1 EC-gate helper and the Jev evidence in `_auto_tick` use the same value. Published as
  `ec_settled` on `sensor.crop_steering_<room>zone_N_safety_status`.
- **EC offset at lights-on.** `_loop_room` clears `ec_offset`, the integral and the previous error
  before it builds the parameters for the tick that starts the zone's day.
- **Budget clipping (controller).** `_act_zone` cuts a non-exempt shot to the remaining budget at the
  zone's flow; under `MIN_SHOT_S` (5 s) it does not fire and publishes `BLOCK daily-cap (x L left)`.
  When less than a minimum shot is left, `_loop_room` decides again with the budget spent, so the
  watchdog rescue and P1 completion apply at the margin too. Copied and blind-schedule decisions are
  plain text and never exempt.
- **Write-ahead shot record.** `_execute_shot` saves `_shot_inflight` (zone, valve, mainline, pump,
  `started` in UTC) in the room's state block before opening anything and clears it once the close
  reads back OFF. `_reconcile_inflight` runs at the top of every loop, so at start-up: it closes a
  recorded switch only if Home Assistant's `last_changed` is within `INFLIGHT_OPEN_WINDOW_S` (-5 s to
  +60 s) of `started`, walking valve -> main line -> pump and stopping at the first switch that changed
  outside it; it leaves the main line and pump while another valve on the line is on, the pump while
  any `hold_entities` is on, and everything while the room's kill switch is not ON. A close that is not
  confirmed latches the hardware hold and alerts, and is retried each loop. A new shot in that room
  waits until the record is settled. `ha_get` returns `HAState`, a tuple that unpacks as before and
  carries `last_changed`.
- **Stopping the app.** `_safe_off` (SIGTERM / SIGINT: stop, update, restart) no longer switches off
  every mapped switch. It closes only a room's `_shot_inflight`, by the same `_inflight_plan` rules, and
  with no shot in flight it switches nothing off. The shot running in this process is closed whatever
  its kill switch reads; an older interrupted shot is left to the operator while its kill switch is not
  ON, as in the loop. What cannot be closed and read back OFF stays recorded for the next start. State
  is still saved on the way out.
- **Alerts.** `_alert` starts the 30-minute debounce, and sends the phone push, only once
  `persistent_notification.create` succeeds. A latched hardware hold this process has not announced is
  announced from `_recover_hardware_faults`.
- **Shot cleanup and stop.** The error-cleanup read-back uses `_confirm_switches` (1 s, then every
  0.5 s to 6 s). A `SystemExit` mid-shot counts `nominal_l * elapsed / duration` before re-raising
  (up to the end of the stop's close, like the normal close counts to its acknowledgement), and skips
  the error cleanup, which would otherwise switch the rest off.
- **State file.** Additive: `_shot_inflight` in a room block, `ec_settled` and `ec_settled_at` per zone.
  The previous controller (0.16.2) loads the new file: it ignores the new keys, keeps the room-block one
  when it saves and drops the two zone keys. An old file loads with the new keys at their defaults; a
  damaged record is ignored and logged.
- **Tests.** Engine: `crop-steering-engine/tests/test_day_structure.py` (32). Controller:
  `test_grow_day_and_budget.py` (15) and `test_interrupted_shot.py` (22). In `test_auto_setpoints.py`
  the plateau hand-over margin is now one 20-minute ramp interval instead of 0.5 h: the base run no
  longer includes the P0 lights-on watchdog shot that delayed it. `test_declared_plumbing.py`: a mapped
  pump is closed on exit when a shot of this controller left it on, and left alone otherwise (it
  asserted the old blanket switch-off). `fake_ha.FakeHA` reports
  `last_changed`. The `tests_ha/` tier was not run locally, and no `tests_ha/` test or seeded fixture was
  added for this change yet.

## [2.19.2] - 2026-09-21

Pair: **controller 0.16.2**. Class **C3**. Everything here comes from two reviews by use: the first
real install on a one-zone tent, set up from a phone, and an independent review of 2.19.1 upstream.
Nine small changes, each its own pull request with its own tests (#15 to #23). **This candidate
carries more than one behaviour change** (two C3, four C2), which
[docs/RELEASING.md](docs/RELEASING.md) says a candidate should not; they were bundled by decision
of the person running the only staging room, and a failed soak would have to be bisected across
them. The defects were seen on real hardware; **the fixes have not run on hardware** before
release. Update with the engine off, read the controller log, then watch the first shot.

### 🌱 In plain English

- **Set things up in either order.** If the controller app was started before the integration was
  set up (the order the app store invites), a one-zone tent was shown Zones 2 and 3 that do not
  exist, each complaining "no hardware mapped", and a minute after setup Settings > Repairs told you
  to create a kill-switch helper by hand. Both are gone. The controller now waits for a room,
  invents nothing, and picks the room up by itself within a minute, with no restart. **If you saw
  that Repairs card: do not create the helper.** A room made by the wizard has its own kill
  switch, *Engine Enabled*; the helper would be a second one that does nothing.
- **A zone is called what you called it.** Name a zone "GT1" and its device in Home Assistant was
  still "Zone 1" or "Crop Steering Zone 1", depending on which part of the integration got there
  first. It is now the name you typed, and renaming the zone in Configure renames the device. A
  device you renamed yourself in Home Assistant keeps your name. No entity id changes.
- **Switching a room on no longer creates an irrigation event.** New switch-on timestamps are
  marked explicitly and displayed as unknown until an irrigation is recorded. Older unmarked
  timestamps are preserved: zero daily counters or missing history cannot establish whether an
  old timestamp represented irrigation or switch-on. Electrical operation does not prove water delivery.
- **The menu scrolls on a phone.** On a small screen the lower half of the side menu (including
  *Help & tools* and the version numbers) could not be reached.
- **Configure > Edit parameters no longer locks out a room that steers dry.** The number entities
  accept a P1 target and a P2 threshold as low as 5 %, the form insisted on 30 % and 25 %, and
  since 2.18.1 it opens on your current values. A room at P1 20 % could not submit the form even
  unchanged. The form now has exactly the limits of the entities it edits.
- **Assistants using the MCP tools can change how a room is plumbed.** A room that had declared
  its plumbing could never gain or lose its pump through them: the tools did not know the
  question existed. The plumbing and the pump or main-line mapping now travel together in one
  reviewed proposal, and a proposal that contradicts the declared plumbing is refused at preview.
- **Two holes in the release checks are closed.** A release pull request could also change a
  default, a dependency or an add-on permission inside the three files that hold the version
  numbers; and a controller-only release was accepted that could then never be promoted. Every
  release now raises the integration's number, a controller-only fix included.

### 🔧 Technical notes

- **Zones are never invented** (#17, **C3**). The shipped add-on options carry `num_zones: 3`,
  documented as "only used if Home Assistant isn't reachable at startup" but also used when Home
  Assistant answered and the integration simply was not set up yet. New
  `_default_zone_ids(options, descriptor) -> (ids, provisional)`: the descriptor's authoritative
  `active_zone_ids` / `num_zones` first, then fused sensors (provisional without a descriptor), else a
  hand-mapped `hardware` option keeps `num_zones`, else no zones when Home Assistant answers, else
  the documented fallback. While provisional the controller rediscovers every loop and re-resolves
  zones, enable flag and feed sensors. A state file that already holds phantom zones still loads.
  It also stops the controller's pre-setup `zone_N_status` states pushing the integration's own
  status sensor onto `sensor.crop_steering_zone_1_status_2` on a first install.
- **Last irrigation is an event** (#18, **C3**). New per-zone state field `last_shot_is_anchor`
  (additive: `_fresh_zone` default `False`; an old file without it retains its existing timestamp,
  because daily counters reset and history expires). `_room_switched_on` still stamps `last_shot`
  so the blind-probe schedule counts from switch-on; `zone_N_last_irrigation_app` publishes
  `unknown` while the flag is set, including for a room that is off. No option or entity change.
  Final review added regression coverage for partial sensor startup, legacy numeric strings and
  malformed excluded-volume values, and genuine irrigation timestamps after daily rollover.
- **The kill-switch repair judges the right switch** (#19, **C2**). `health._kill_switch()` trusted
  the heartbeat's `enable_flag` over the room's own descriptor. While the heartbeat reports an older
  `setup_revision` than the descriptor (both plain ints), the engine holds every zone anyway and
  adoption moves it to the descriptor's flag, so that flag is the one judged. An up-to-date engine
  is believed as before (custom add-on `enable_flag`), a deleted legacy helper is still reported,
  and a controller too old to report a revision is believed as before.
- **Zone device name** (#16, **C2**). `room.zone_device_name(entry, zone_num)`, used by the button,
  number and select platforms, which used to register the same device under two different names.
  The room device is left alone.
- **Edit parameters limits** (#20, **C2**). The four fields read `native_min_value` /
  `native_max_value` from `NUMBER_DESCRIPTIONS`. Only the lower limits of `p1_target_vwc` (30 -> 5)
  and `p2_vwc_threshold` (25 -> 5) actually move.
- **MCP plumbing** (#21, **C2**, `mcp-server/` only). `plumbing` in the strict input schema; the
  room carries `plumbing` ("" = never declared) and `plumbing_inferred`; `config()` includes the
  layout only when declared, which puts it in the payload, the comparison snapshot and the readback
  digest, and never declares one on the operator's behalf. New
  `tests_ha/test_mcp_setup_contract.py` sends that payload to the real `setup_save`.
- **Sidebar scroll** (#15, **C1**). `.desktop-sidebar` / `.mobile-sidebar` get `overflow-y: auto` and
  `overscroll-behavior: contain`, their children `flex-shrink: 0`; checked in `verify-live.mjs` at
  390x640 and 1280x480. The committed bundle is rebuilt from that source.
- **Release guards** (#22, #23, **C0**). `without_version()` compares each version file with only its
  version field blanked, and `check_pull_request` takes the files' text as a required argument; a
  release that does not change the integration version is refused, and a release branch is named
  for the integration version. Both take effect once promoted, because GitHub reads the workflow
  from `main`.
- **Upgrade in place.** No add-on option and no entity id changes. One additive state-file field
  (`last_shot_is_anchor`). A room that never declared its plumbing still publishes byte-for-byte
  the descriptor it did, and the controller's saved setup fingerprint still matches, so an update
  resumes without a disarm cycle. Every change above is tested both on a fresh install and from the
  seeded snapshots of old installs in `tests_ha/fixtures/`.
- **Documented, not changed.** A probe whose reading has not changed for 20 minutes is treated as
  dead and the zone goes onto the blind schedule. That is deliberate (a probe pulled out of its
  cube leaves a plant that will need saving), and it also fires on a bench test with no plant in
  the cube. [docs/troubleshooting.md](docs/troubleshooting.md) now says so, along with the three
  first-install symptoms fixed above.

## [2.19.1] - 2026-09-21

Pair: **controller 0.16.1**. Class **C3** by the table, because the controller is touched, though
what changes there is one new attribute on a sensor it already publishes: no change to irrigation
behaviour, options, the state file or any entity id. **Not run on hardware** before release: update
with the engine off, then check the sidebar reads 2.19.1 and 0.16.1.

### 🌱 In plain English

- **Crop Steering has its icon.** Adding the integration, the integrations page and HACS all showed
  a grey "icon not available" box. The integration now carries its own icon and logo, with
  versions that stay readable on a dark theme. Needs Home Assistant 2026.3 or newer; older
  versions carry on showing the placeholder, and nothing else changes for them.
- **You can see what you are running without leaving the dashboard.** The sidebar, under *Help &
  tools*, now shows the integration version and the controller version. Both come from the parts
  that are actually running, not from the page, so it cannot show a version you have not got, and
  a half that is too old to say (or a controller that is not running) reads "not reported".
  After an update it is the quickest check that both halves really moved.

### 🔧 Technical notes

- New `custom_components/crop_steering/brand/` (`icon`, `logo`, `@2x`, and `dark_` variants), which
  Home Assistant 2026.3+ serves for a custom integration with no manifest change. Built from
  `img/crop-steering-logo.png` by `scripts/make_brand_images.py`: the icon is the emblem alone (it is
  shown at about 40 px), the logo keeps the wordmark, dark variants sit on a white rounded tile,
  all reduced to 256 colours with alpha (10-53 KB each). `tests/test_brand_images.py` pins names
  and sizes from the PNG headers. Class **C1**: nothing the controller reads.
- Versions in the sidebar. The integration publishes `integration_version` in each room's
  `engine_config` descriptor (from `SOFTWARE_VERSION`, already tied to `manifest.json` by the version
  tests). The controller publishes `controller_version` in each room's `ai_heartbeat` and logs it on
  start; it reads the number from the `config.yaml` it was built from, which the Dockerfile now
  copies into the image as `/app/addon.yaml`. **No number is duplicated anywhere**, so a release
  has nothing extra to bump; the tests fail if the report and `config.yaml` disagree or the
  Dockerfile stops shipping the file. The descriptor attribute is proven not to enter the
  controller's setup fingerprint, so an integration update still resumes without a disarm cycle.
  Class **C3** by the table (the controller and its Dockerfile are touched), though the change is
  one new attribute on a sensor the controller already publishes: no state-file, option or
  entity-id change.

## [2.19.0] - 2026-09-21

Pair: **controller 0.16.0**. It also carries 2.18.1 / controller 0.15.2, which was never published by
itself. Class **C3**. Released without a staging soak by decision of the two people who run it; see
[the record](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/v2.18.1/docs/audits/2026-09-21-release-2.18.1.md). **Not run on hardware** before release: treat
the first update of each box as the first run. Engine off, update, check the log, watch the first shot.

### 🌱 In plain English

- **Setup now asks how your room is plumbed, and holds you to the answer.** 2.18.0 worked it out
  from what you left empty: no pump chosen meant "this room has no pump". That is right for a tent
  on one smart plug. It is silently wrong for a room that *does* have a pump and whose pump was
  never chosen, or was cleared by mistake: the controller opened the valve, ran no pump, and
  counted the water as delivered while the plants got none. The wizard and **Rooms & setup** now
  ask the question outright (zone valves only; a pump, then zone valves; a main-line valve, then
  zone valves; or all three), and the switches you choose have to match your answer.
- **If they ever stop matching, the room is held, with a reason.** A room that says it has a pump
  and has none mapped is not watered, nothing is counted as delivered, and you get a notification
  saying what to fix. It used to look healthy until the plants wilted.
- **Nothing changes for a room that is already set up.** It carries on exactly as it does today,
  and an update does not need the kill switch cycled. Open **Rooms & setup** (or *Configure*) when
  it suits you: it shows what your current switches imply and asks you to confirm. From then on
  the protection above applies to that room too.

### 🔧 Technical notes

- New optional `plumbing` in a room's setup and, **only when declared**, in the engine descriptor:
  `valves_only`, `pump_valves`, `mainline_valves`, `pump_mainline_valves`
  (`custom_components/crop_steering/plumbing.py`; the controller carries the same table and a test
  reads both). `prepare_setup` refuses a save whose mapped switches contradict a declared layout,
  both ways, for an active room. Once declared it can be changed, not withdrawn; a client that does
  not send it keeps the stored value.
- Controller: `plumbing_hold()` gates `_blocked` and, as a last line of defence, `_execute_shot`.
  A contradiction or a layout the controller does not know holds the room, alerts
  (`f2_plumbing_<room>`, at most every 30 minutes), opens nothing and counts nothing. A mapped
  switch the declaration disowns is still safed on exit and still has to read OFF for adoption.
- **Upgrade in place:** an undeclared room publishes byte-for-byte the descriptor it did (key set
  pinned in `tests/test_plumbing.py`), and `plumbing` joins the setup fingerprint only when present,
  so the fingerprint saved by controller 0.15.x still matches and the room resumes without a disarm
  cycle. Proven in `tests_ha/` from seeded snapshots: a one-switch tent recorded by running upstream
  2.18.0's own wizard (`fixtures/entry_2_18_one_switch_tent.json`, fingerprint computed by
  controller 0.15.1's code) and the 2.17 pumped room. Declaring later is an ordinary setup change
  (new revision, adopted with the kill switch and hardware OFF).
- Wizard and Configure: a required list question at the top of the hardware step; no prefill for a
  new room; Configure prefills the declared layout or what the saved switches imply. Clearing the
  pump of a room declared with one is refused in the form. Rooms & setup asks only when
  `setup_read` reports the `plumbing` capability, so a newer dashboard served by the add-on beside
  an older integration neither asks nor sends it.
- Not changed: the env-file path (rooms configured that way stay undeclared until saved through a
  form), add-on options, the state file format, every entity id.
- **Not run on hardware.** Everything above is proven against a real Home Assistant and the real
  controller code with a fake switch layer. No physical pump or valve has been driven by this build.

## [2.18.1] - 2026-09-21

Pair with controller **0.15.2** (0.15.1 plus a test-only seam; irrigation behaviour is unchanged). Bug fixes only. Nothing an operator has set moves: every fix below was checked against seeded snapshots of older installs. Each was reproduced on 2.18.0 inside a real Home Assistant before it was fixed; the write-up is [docs/audits/2026-09-21-first-run-review.md](docs/audits/2026-09-21-first-run-review.md).

**🌱 In plain English**

- **The integration starts on older Home Assistant.** On anything before Home Assistant 2026.5 the setup wizard finished and the integration then showed "Failed to set up": no entities, no dashboard. It lists 2024.3 as supported, and now it is.
- **Your lights times are used.** The wizard asks when your lights turn on and off, stored the answer, and then always ran on 12 and 0. The grow-day, the morning dry-back and the overnight phase now follow the hours you typed. If you already set them on a dashboard, those are kept.
- **"Edit parameters" does something.** Changing a value under Configure said "saved" and quietly put the old value back. It now changes what the controller reads, and the form opens on the current value rather than the one from the day you installed.
- **A sensor or pump can be removed, not just swapped.** Under Configure you could replace a mapping but never clear it: it came straight back. That matters more now that a pump is optional.
- **Boxes that did nothing say so.** The waste-valve box promised the valve is "forced closed during a shot". The controller has never operated it, so if your plumbing relies on that, arrange it yourself. The grow-light, notification, humidity and VPD boxes are likewise marked as recorded only.
- **The pump box says what leaving it empty means.** Since 2.18.0 an empty pump is accepted and the controller then never runs one: it opens the zone switch and counts the shot as delivered. That is right for a one-switch tent and wrong for a room that has a pump, so the box now says so where you choose it.
- **Every box is explained.** The feed EC and feed pH pickers showed their raw names (`feed_ec_sensor`) with no label at all, and each zone's name and "in use" box had no help text. Two Configure messages showed as raw keys.
- **Small pots can be adjusted.** A 0.65 L rockwool cube was accepted by setup and then could not be edited, because the setting's minimum was 1 L.

**🔧 Technical notes**

- `setup_panel`: `frontend.async_panel_exists` was added in Home Assistant **2026.5.0** (absent from core tags 2024.3.0, 2025.1.0, 2026.2.3, 2026.3.0, 2026.4.0) and was called unconditionally inside `async_setup_entry`: `AttributeError`, entry state `SETUP_ERROR`. `_panel_exists()` uses the helper when it exists and otherwise `PANEL in hass.data[frontend.DATA_PANELS]`, which is what the helper does. Neither test tier could see it: `tests/test_setup_panel.py` assigns the function onto its own stub, and `tests_ha/conftest.py` replaced the whole panel registration with a no-op. `tests_ha` now stands in for the web server only and runs the registration against the real frontend module; with the fix reverted, that tier fails.
- `number.PARAM_TO_ENTITY_KEY` gains `lights_on_hour` / `lights_off_hour`. A seed only applies to an entity being created for the first time (`RestoreEntity` wins afterwards); pinned by a seeded upgrade where setup recorded 10-22, the operator set 8-20, and 8-20 survives.
- `OptionsFlowHandler.async_step_edit_parameters` calls `number.set_value` on the live entities before `_update`, so the reload restores the value just written; defaults come from the live entities. The OFF check and its abort are unchanged, and nothing is written when it refuses.
- `_hardware_schema._ent` prefills with `description={"suggested_value": ...}` instead of `default=`. The frontend omits an emptied field and voluptuous re-applied the default. `test_native_hardware_schema_retains_explicit_tank_telemetry` now asserts the same intent (the form opens showing the mapping) and additionally that the field can be cleared.
- Translations: `options.abort.not_env_config` / `reload_failed`; labels and tooltips for `feed_ec_sensor` / `feed_ph_sensor` on both mapping forms; tooltips for all 24 `zone_N_name` / `zone_N_active`; truthful text for `waste_switch`, `light_entity`, `notification_service`, `humidity_sensor`, `vpd_sensor` (no runtime consumer in the integration, the add-on or the engine) and for `pump_switch`.
- Global `substrate_volume` minimum 1.0 -> 0.1 and `drippers_per_plant` maximum 6 -> 20, matching `setup_api.SIZING` and the per-zone entities.
- Tests, lean: `tests/test_translations.py` (every abort reason, error key and menu entry has a message in the flow that raises it; every mapping-form field has a label and a tooltip; hassfest's own key, quoted-placeholder and orphan-tooltip patterns; a field with no runtime consumer may not promise behaviour, and fails the day one gains a consumer). An honest pre-2026.5 case in `tests/test_setup_panel.py`.
- Tests, real Home Assistant (`tests_ha/`, 4 -> 30): `test_setup_entry.py`, `test_configure.py`, `test_upgrade_in_place.py` driven by seeded snapshots in `tests_ha/fixtures/` (a 2.17 wizard room and an env-file era room: tuned values, an operator-renamed entity, a unit-less probe, and controller 0.14's saved setup fingerprint resuming with the kill switch ON), and `test_install_to_controller.py`, which hands a freshly installed room to the **real add-on controller** and requires it to find, adopt and water it.
- Controller test seam: `F2_STATE_PATH` (see the add-on changelog). Docs: `docs/TESTING.md` describes the real-Home-Assistant tier, the fixtures and running hassfest without Docker.
- Not changed, raised for a decision: an unmapped pump is read as "this room has no pump" (2.18.0). See the audit for a demonstration and three options.

## [2.18.0] - 2026-09-21

Pair with controller **0.15.1** (0.15.0 plus one fix: a room switched off stays off while Home Assistant restarts).

**🌱 In plain English**

- **The setup wizard no longer throws your work away.** If something was wrong at the end (a valve that was on, a probe in the wrong unit, a mistyped entity), the wizard closed and every zone, sensor and size you had entered was gone. It now shows the same step again with everything still filled in and says what to fix. Problems are reported on the step where you entered them, not three screens later, and the message says whether the entity is on, unreachable or does not exist instead of always "must read OFF".
- **A brand-new install is found by the controller.** On a fresh install Home Assistant named most of this integration's entities from their labels (`number.p1_target_vwc`, `sensor.engine_config`) instead of the `crop_steering_` ids the controller and dashboard read, so a new room was never discovered and never watered. New installs and new rooms now register under the documented ids. Existing rooms are untouched: Home Assistant keeps the ids it already holds. If you first installed on 2.17 or earlier and your room was never found, update, then remove the room and add it again.
- **A tent with one switch works.** A room whose only hardware is one smart plug or solenoid per zone saved fine and then never watered, because the controller insisted on a separate pump and main-line valve. A zone now needs only its valve; pump and main-line are used when you have them. Every safety check still applies to whatever hardware the room has.
- **Probes in other units are converted, not rejected.** Pore EC in µS/cm and moisture reported as a 0-1 volume fraction are accepted and converted to mS/cm and percent, including mixed probes in one zone and the source-water EC probe. `ppm` is still refused, with the reason: the 500 or 700 scale is not something a sensor reports.
- **The Cloudflare judge now looks after P2.** With Auto Setpoints on and a Cloudflare token in the controller's options, the `typesafe/jev` model is asked once an hour during P2 whether pore EC should be flushed or stacked and whether the peak still fits. It may nudge that zone's P2 shot size (1-4 % of substrate) and hold the working peak up to 2 points above or below the learned one: one small step per lever per grow-day, never while a dated plan owns the room. It cannot fire, size or delay a shot. If a guard trips (probe not believable, water not landing) or Cloudflare does not answer within 5 seconds, nothing changes. The zone's Auto Setpoints status shows what it said and what it changed today.
- **Less typing, fewer wrong numbers in Rooms & setup.** Choose litres or US gallons and L/h or GPH (always saved as metric); pick a common block or pot with its litres shown; work out real dripper flow from a catch test; and see the zone's learned peak as a suggestion beside field capacity. Suggestions are never applied for you.

**🔧 Technical notes**

- `config_flow`: `_retry_form` re-shows a step through `add_suggested_values_to_schema` with `errors.base = setup_invalid`; the zones step validates with `prepare_setup` and `safety_blockers` before moving on; the reconfigure zone map does the same. `safety_blockers` messages keep "must read OFF" and append the cause.
- Controller: pump and mainline are optional in discovery, late mapping, setup adoption, the per-zone gate and `_execute_shot`; lead times are skipped with the hardware they belong to, the close read-back and the hardware-fault latch cover the actuators that exist. The three-switch sequence and its timing are unchanged (tested).
- Controller `_auto_tick`: hourly P2 consult (`auto_setpoints.jev_due` / `jev_verdict`), `p2_shot_size` joins `managed` while the judge is configured, `working_peak = learned peak + peak_adj` drives the P1 target and the P2 threshold. New status attributes `jev_last`, `jev_changed_today`, `working_peak_adjust`. Learned state restores across restarts.
- New `units.py`: exact conversions only (`µS/cm`, Greek-mu `μS/cm`, `uS/cm` -> mS/cm; `m³/m³` -> %). Unknown or missing units pass through unchanged so older installs keep their readings. The controller converts the source-water EC probe the same way before its 0-20 sanity range.
- `number`, `select`, `sensor` and `button` set `self.entity_id` from the object id they already computed. Home Assistant ignores `_attr_object_id` (the 2.17.1 switch fix, now everywhere): in a real Home Assistant 75 of a one-zone room's 134 entities registered under label-derived ids. Found by the new real-HA test job; a permanent test asserts every entity lands on the id its code asks for.
- CI: a `real-home-assistant` job runs `tests_ha/` in a real Home Assistant (`pytest-homeassistant-custom-component`, Python 3.13): the wizard end to end for a one-switch room, and the registered id of every entity. The sidebar panel is stubbed there (it needs the frontend wheel and a web server). The stub suite could not see the 2.17.0 entity-id bug; this can.

## [2.17.2] - 2026-09-20

Documentation only; no code change. Pair with controller **0.14.0** (unchanged).

- Feature matrix: rows for the 2.17 features with what is tested and what was exercised live on 20 September (room off, restart-safe setup, patient read-back), what was not (the full P1 ramp through a live lights-on, Auto Setpoints writing live), and an updated live deployment row.
- Planning guide: "Read the combined graph" now describes the projected P0-P3 day, the overnight lines and the P2 threshold note, replacing text from before 2.16.1.
- Entity reference: `room_active`, `auto_setpoints` and the per-zone `auto_setpoints` sensor.
- User guide, sidebar guide and the controller's documentation tab no longer describe the Today / Schedule navigation as awaiting verification or use the old page names.

## [2.17.1] - 2026-09-20

Pair with controller **0.14.0** (unchanged).

- Fix: the new Room Active and Auto Setpoints switches registered under ids made from their labels (`switch.crop_steering_room_active_off_empty_room_no_irrigation_no_alerts`), which the controller and dashboard never look for, so the room on/off control did nothing on a fresh 2.17.0 install. Switches now suggest `switch.crop_steering_<prefix><key>` when first registered. Found on the first live install, where the four entities were renamed in the entity registry.
- If you installed 2.17.0: rename the two switches per room to `switch.crop_steering_<prefix>room_active` and `switch.crop_steering_<prefix>auto_setpoints` in Settings > Entities (an entity already registered keeps its id), or remove them and restart on 2.17.1.

## [2.17.0] - 2026-09-20

Pair with controller **0.14.0**.

**🌱 In plain English**

- **Room on/off.** Each room has a Room Active switch. Turn it off when nothing is growing: no irrigation (scheduled, emergency or blind-probe fallback), no alerts, no repair issues, and the room's open notifications are dismissed. Turn it back on and the room starts a clean cycle from the overnight phase; water history is kept.
- **P1 always runs in full.** The ramp no longer ends on a clock. However late the first shot lands, P1 fires its shots in order until the target is recovered (after at least the new minimum shot count) or the maximum shot count is reached. Only then does P2 start.
- **See the sensor where you set the target.** The Today graph you drag targets on now draws that zone's recorded VWC and pore EC underneath them (this grow-day and the previous one), with now, peak and trough above it, on an axis scaled to the readings instead of 0-100 %. A deeper 24 h / 72 h / 7 d history panel sits below, and setpoint fields warn when a target sits outside what the probe reads.
- **The whole day is drawn the way it runs.** P0 keeps drying after lights-on, P1 climbs one step per shot (all of them), P2 fires a shot each time VWC falls to its threshold, and P3 dries down overnight to the next lights-on. Timing uses the zone's own measured dry-down rate, so it is a projection, not a schedule. Hover any riser for its time and size.
- **A restart no longer strands irrigation.** The controller used to forget which setup it had accepted whenever it restarted, then refuse to water until the kill switch was turned off and on again, without saying so. On 2026-09-20 a host reboot cost F2 two hours of its morning ramp that way. It now remembers the setup it accepted and carries on after a restart if nothing changed (pump, mainline and valves must still read off). A genuinely changed setup still needs the off-and-on, and now says so with a notification naming exactly what has to read off. The first start after this upgrade still needs one off-and-on, because the old build saved nothing to remember.
- **A slow pump report no longer stops the room.** After a shot the controller checks that pump, mainline and valve all read off. It used to look once, a second later, and a Zigbee plug that answered in 1.6 seconds latched a false hardware hold that stopped F2 for 16 hours. It now looks at 1 second as before and then keeps re-reading for up to 6, so a late report passes and a genuinely stuck valve still latches within the same minute.
- **When P2 shows no sawtooth, the graph says why.** The engine fires a P2 shot only once VWC has dried down to the P2 threshold. A threshold far under the P1 target spends the whole window drying, so the graph now draws the threshold across P2, says how many points and hours away it is, and names the threshold that gives shots from the start of P2.
- **Auto Setpoints (off by default).** The controller learns each zone's real ceiling, what a shot lifts it, and how fast it dries. When a P1 ramp stops rising for two shots it hands over to P2 and carries the achieved peak forward as the P1 target, then probes 1 point higher after 3 days. It only ever rewrites per-zone target numbers; the engine still decides every shot.

**🔧 Technical notes**

- `switch.crop_steering_<prefix>room_active` (default on) and `switch.crop_steering_<prefix>auto_setpoints` (default off). `health.py` clears the room's repair issues while the room is off; the controller publishes `app_status: room_off` and a `room_active` heartbeat attribute.
- Engine core: P1 time exit removed; `ZoneParams.p1_min_shots` (from `number.…p1_minimum_shots`, clamped to `p1_max_shots`). Both vendored copies stay byte-identical.
- New pure modules in the controller: `auto_setpoints` (learner), `setpoint_supervisor` (bounded, stepped, ladder-safe writes), `curve_tracker` (day planner), `engine_twin` (test twin around the real `decide()`), `jev_policy` (optional Cloudflare `typesafe/jev` judge, consulted only on a plateau; any failure returns no verdict and never blocks irrigation).
- Gain is learned only from ramp shots fired at least 2 points under the ceiling; dryback rates fold in once per grow-day as that day's mean. Near-ceiling top-ups no longer shrink the P2 band.
- Publishes `sensor.crop_steering_<prefix>zone_<N>_auto_setpoints` (off / learning / tracking / frozen) with learned_peak, gain, day_rate, night_rate, p1_outcome, hold_days, frozen_reason, last_change, jev, managed.
- Add-on options `cf_account_id`, `cf_api_token`, `cf_gateway_id` (all optional). Auto Setpoints never writes while a dated plan owns the room.
- Dashboard: `foldRecorded`, `smoothRecorded`, `dryRates`, `projectDay` and `planningAxis` in `frontend/src/lib/planning-curve.ts`; the dryback target is measured from the projected peak (as the engine measures it from the recorded one) rather than from field capacity. Lines carry a scale-free `data-planning-values` signature because the axis now follows the data.
- Fix: the live history request had no `end_time`, so Home Assistant returned only the first 24 h of a 72 h or 7 d window.
- Controller: the adopted `setup_revision` is saved per room with a fingerprint of what was adopted (`_setup` in `/data/state.json`: pump, mainline, valves, enable flag, active zones, feed sensors). Same revision and fingerprint after a restart is resumed without the engine flag reading off; hardware must still read off. Malformed or missing records keep the full fail-safe. A pending setup raises `f2_setup_<room>` (debounced, dismissed on adoption, silent for archived rooms), and the per-zone hold line carries `[blocked: ...]` in every phase.
- Controller `_confirm_switches`: first read at 1 s, then every 0.5 s to a 6 s deadline (`CONFIRM_FIRST_READ_S`, `CONFIRM_POLL_S`, `CONFIRM_TIMEOUT_S`). Regression tests cover a 1.6 s report (no latch) and a pump that never reports off (latches, bounded).
- Dashboard: `p2Advice` explains a missing or late P2 sawtooth; nominal dry-down is now 2 / 1 points per hour (lights on / off) until a zone has history, replacing 0.7 / 0.35 taken from one low-light week.

## [2.16.1] - 2026-09-08

- Replace competing Manual setpoints and Grow plan navigation with Irrigation plan: Today and Schedule.
- Show effective active schedule targets in Today; hide misleading fallback controls while a schedule owns the room.
- Connect VWC and dashed EC planning references across lights-off and overnight to the next lights-on. Missing EC anchors remain gaps; overnight EC is an interpolation, not a prediction.
- Keep emergency-floor edits and saved-reference overlays independent. Preserve legacy routes and unsaved-draft navigation guards.
- Bundle the same dashboard in controller 0.13.3; no controller decision changes.

## [2.16.0] - 2026-09-08

- Add a local MCP connector for LLM-assisted configuration with reviewed, room-scoped proposals and opt-in writes.
- Seed the isolated demo with synthetic named recipes and current/previous runs; live libraries remain unseeded.
- Temporarily collapse the Home Assistant sidebar while embedded, with persistent desktop/mobile menu access and restore on leaving.

- Add graphical room tank level, pump and fill status, tank EC/pH/temperature, and recorded fill completion time to Overview.
- Show controller state, mapped valve status and last irrigation time in zone tables, mobile cards and details.
- Add optional room-specific tank telemetry mappings, separate from feed-water safety gates. Unknown data stays unknown; level changes are never presented as fill events.
- Pair with controller 0.13.2 for the bundled dashboard and timezone-aware irrigation event publication.

## [2.15.0] - 2026-09-08

- Add an empty, room-scoped library for saving and reusing user-authored plans as local drafts. Browser storage is separate for live and demo; loading preserves the current zone start dates and uses existing plan validation/review.
- Support the legacy same-room `maximum_shot_duration` entity alongside the canonical name in the controller and runtime calculator. Canonical entities take precedence; invalid configured values do not silently acquire another room's cap.
- Pair with controller 0.13.1. No crop-guide numerical presets or publisher endorsement are included.

## [2.14.0] - 2026-09-08

**🌱 In plain English.** See the whole day while editing setpoints: the draft VWC/EC curves and P3 emergency floor move immediately beside the saved reference. Compare retained readings over a day, week, month or run-to-date with another run at the same grow age. Water cards distinguish total zone delivery, average per plant and pot capacity, with a local runtime calculator.

**🔧 Technical notes — integration 2.14.0, controller 0.13.0.**

- Add phase-focused manual editing, bounds-aware graph handles, saved/draft overlays and read-only active-plan previews.
- Add room-scoped, revisioned run metadata with captured target references and Recorder comparisons. Recorded history remains subject to retention; a reference captured today is not a historical target audit.
- Add explicit all-plant daily zone litres, per-plant averages, nominal phase-shot volumes and capped runtime estimates. P1 series budgets are conditional; daily adaptive shot counts are not predicted.
- Count new delivered litres from configured flow and elapsed runtime, including duration caps, fractional-second truncation, minimum runtimes and partial aborts. Freeze sizing per shot to prevent in-flight configuration edits changing its recorded volume. Existing totals are preserved.
- Keep all edits local until reviewed; comparison registration and runtime calculators do not activate irrigation.

## [2.13.2] - 2026-09-08

- Show each room's configured name in the workspace instead of a generic sensor label.
- Package the corrected workspace in controller 0.12.1; irrigation logic is unchanged from 0.12.0.
- Document the verified in-place upgrade, preserved settings and consolidated branches.

## [2.13.1] - 2026-09-08

**🌱 In plain English.** Fix a startup failure when multiple rooms load at once. Every room can now share the native sidebar reliably. Controller 0.12.0 remains the matching version.

**🔧 Technical notes.** Serialize sidebar/static-path registration across concurrent config-entry setup. Live installation exposed the duplicate-panel exception; deterministic concurrent-startup and retry tests cover the correction.

## [2.13.0] - 2026-09-08

**🌱 In plain English.** One Home Assistant native workspace brings room setup, current readings and whole-grow planning together. The combined VWC/EC planning graph follows each zone's selected day, week and steering profile. Existing installations keep their room identities, setpoints and hydraulic settings.

**🔧 Technical notes — integration 2.13.0, controller 0.12.0.**

- Replace the dashboard family with one React/shadcn operator workspace using inherited Home Assistant themes, bundled fonts and responsive layouts.
- Add reactive combined VWC/EC planning curves, recorded dual-axis history and per-zone day/week recipes with continuous steering between explicit endpoint profiles.
- Add durable plan storage, revisioned preview/save/arm/disarm services and atomic expiring controller snapshots applied at local lights-on boundaries.
- Add reviewed room/zone lifecycle and searchable sensor mapping with stable IDs, archived restoration, per-zone sizing and controller adoption status.
- Add local catch-test calculations, sensor diagnostics and equipment maps; remove unsupported yield/potency claims from the active UI.
- Correct duration accounting, volume-cap bypasses, shared-hardware fault recovery, relative-dryback timing conversion, low-flow sizing and stale sequential-plan decisions.
- Bundle the dashboard in the integration with automatic sidebar registration, publish app-repository metadata, consolidate install/operation instructions, and archive superseded assets with provenance.
- Resolve setup hydraulics from the current room/zone number entities so a rename or mapping edit preserves live plant counts, pot size and dripper settings.
- Archive unused facility examples, environment templates and disabled workflows; add current README screenshots and a public interactive demo link.
- Preserve base VWC shot sizes while EC is unknown, suspend EC adaptation, and expose degraded EC status (#37).
- Reject nonfinite or invalid/stale/future-dated feed readings; describe arithmetic sensor averaging and relative dryback accurately (#38, #39).
- Persist timed manual override deadlines across restart/reload and cancel obsolete callbacks on retrigger/manual changes (#40).
- Track rolling seven grow-day delivery estimates with explicit partial-history coverage; missing weekly sources remain unknown (#41).
- Audit all branch tips and retain recoverable archives; use tracked-only controller release packaging.
- See docs/FEATURE_MATRIX.md for validation evidence and live commissioning limits.

## Older releases

Releases before 2.13.0 (up to July 2026) are in the git history of this file.
