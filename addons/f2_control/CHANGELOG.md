# Unreleased

- **C1, dashboard only.** The dashboard the app serves (`www/public/dashboard.html`) is rebuilt with the Overview's grow-day timeline and the Overview changes in the integration's changelog. No change to options, the state file or irrigation.
- **C3. A shot that something else cuts short ends there, and only its water is counted.** 23 Sep, 11:25: the batch tank ran empty 4 s into a 170 s shot, the dosing hold came on and a guard closed the feed path, and the controller waited out and counted all 170 s. `_wait_shot` now also ends a shot when a `hold_entities` entity reads ON or the shot's own valve reads OFF after being seen ON, with the same bounded reads and ≤2 s cadence; the kill switch, room switch and override are read first and still win. `_close_cut_short` switches off the shot's valve and main line unless they read OFF, and its pump unless it reads OFF or a hold is ON. It reads back only what it switched off, clears `shot_inflight` as a normal close does, and never latches a hardware hold for a feed path somebody else closed. Counted time: the valve's `last_changed` when it falls inside the shot, else when the interruption was seen; the shot counts as a kill-switch abort does. One debounced alert names the entity and the seconds delivered against planned. Not run on hardware. No change to options or the state file.

# 0.16.5

Pair with integration 2.19.5. **C3.** Owner-approved rehearsal release without a staging soak (23 Sep 2026); not run on hardware before release. No change to add-on options or the state file.

- **A held grow plan never stops an emergency, watchdog or minimum-daily shot.** Each zone the plan holds is decided with the engine's new `ZoneSnapshot.steering_held`, so `decide()` returns the rescue behind a routine shot; `_blocked` and the shot preflight let `PLAN_HOLD_EXEMPT` kinds (`p3_emergency`, `watchdog`, `min_daily`, and for a blind zone `blind_fallback` and `blind_copy_rescue`) through the plan hold, and every other gate still applies. A held zone that is not firing shows the hold as its block. No change to options or the state file. Pairs with the integration's plan fixes in the same release (a plan no longer holds a room all day over a missed lights-on).
- **Zone status has one writer.** The controller publishes each zone's label, with its reason, on `sensor.crop_steering_<prefix>zone_N_status_app` (`Room off` included) and no longer writes `zone_N_status`, which the integration now mirrors from it. With an older integration, `zone_N_status` shows that integration's fixed-threshold label until it is updated. No change to options, the state file or irrigation.

# 0.16.4

Pair with integration 2.19.4. **C1.** No controller code change: the dashboard served by the app is the 2.19.4 build (controller-health status line, live updates instead of polling). No change to options, the state file or irrigation.

# 0.16.3

Pair with integration 2.19.3. **C3.** Owner-approved rehearsal release without a staging soak (23 Sep 2026); not run on hardware before release. No change to add-on options.

- **A room deleted and set up again is adopted afresh** (#50): the descriptor's `entry_id` changing re-opens adoption through the usual gate (kill switch and hardware OFF); first sight changes nothing, so a running room resumes without a disarm cycle.
- Installed only from `JakeTheRabbit/HA-Irrigation-Strategy`; the `f2-control` mirror is retired. `url` in `config.yaml` now points here. No change to options, the state file or irrigation.

- **The daily limit is a budget with typed exemptions.** The watchdog, P3 emergency and high-EC flushes (anti-lockout, P2 rescue) pass it, and so does the P1 ramp, which always runs in full. Top-ups, P1/P2/P0 EC-correction shots and the min-daily floor stop at it. A shot that would cross it is cut to what is left (under 5 s: held, `BLOCK daily-cap (x L left)`). The "flush" in a reason's text no longer makes a shot exempt.
- **A zone over budget and starving gets the watchdog shot** instead of nothing (22 Sep: Z1 dry 14:06-22:00). No watchdog in P0: the night no longer counts as "no water" at lights-on.
- **P1 at its ceiling, held open only by pore EC, completes once the budget is spent.**
- **Pore EC is settled EC.** Every EC rule uses the last reading taken 45 minutes after a shot, held in between; EC corrections wait for the next settled reading. Only settled readings feed the EC offset step / PID. Published as `ec_settled` on each zone's safety status.
- **A new grow-day resets a zone found in P1/P2** (the controller was not running across lights-off), and yesterday's EC offset is cleared before the first tick of the day.
- **Interrupted shots.** Each shot writes down what it will open before opening it; the next loop closes exactly that, only while the room's kill switch is ON and only switches ON continuously since the shot opened them. Anything a person has switched since (hand-watering, tank circulation), everything upstream of it, the main line and pump while another valve on the line is open, and the pump while a hold is on, are left alone. Nothing is switched off on a timer.
- **Stopping the app closes only what is in flight.** SIGTERM (stop, update, restart) used to switch off every mapped pump and valve; it now closes only the shot running, by the same rules, and counts its water. With no shot running it switches nothing off, so tank circulation and hand-watering carry on through an update. The error-cleanup read-back is as patient as the normal one (no false hold from a late Zigbee OFF report); alerts are only silenced once Home Assistant has them, and a hardware hold latched while it was unreachable is announced once it is back.
- State file: additive `_shot_inflight` (room block), `ec_settled` / `ec_settled_at` (zone). An old file loads; the 0.16.2 controller loads the new one.

# 0.16.2

Pair with integration 2.19.2. **C3.** Found on the first real install (a one-zone tent); the fixes themselves were not run on hardware before release.

- **Zones are never invented.** Started before the integration was set up, the controller fell back to the shipped `num_zones: 3` and reported zones 2 and 3 of a one-zone tent as "no hardware mapped". It now has no zones until a room exists, checks every loop, and picks the room up by itself: no restart needed. The log says so: *"the Crop Steering integration has not published a room yet..."*. `num_zones` is still the fallback when Home Assistant cannot be reached at start, and a hand-mapped `hardware` option still keeps its zone count. A state file that already holds the phantom zones loads as before.
- **Switch-on is no longer an irrigation event.** New switch-on timestamps are explicitly marked by `last_shot_is_anchor` and published as `unknown` until an irrigation is recorded, also for a room that is off. An old file without the flag keeps its timestamp: zero daily counters or missing history cannot establish whether an old timestamp was switch-on or irrigation. Electrical operation alone does not prove water delivery.
- Final review fixes keep the descriptor's complete zone list when HA sensors appear gradually, preserve old irrigation timestamps after daily rollover, and keep legacy numeric-string/malformed excluded-volume state loadable. Regression tests cover each case.
- The dashboard served by the app is the 2.19.2 build (the side menu scrolls on small screens).
- No change to add-on options. No change to what a working install waters, or when.

# 0.16.1

Pair with integration 2.19.1. Not run on hardware before release.

- The controller reports its own version: `controller_version` in every room's `ai_heartbeat`, and in the first log line (`f2-control 0.16.x starting | rooms ...`). The dashboard's sidebar shows it next to the integration's. It is read from the `config.yaml` the image was built from (copied in as `/app/addon.yaml`), so there is no second number to keep in step.
- No change to irrigation behaviour, options or the state file.

# 0.16.0

Pair with integration 2.19.0. **C3.** Released without a staging soak by decision of its two operators; not run on hardware before release.

- A room can DECLARE its plumbing (`plumbing` in the engine descriptor, set in the integration's setup). Declared: the mapped pump and main-line have to match it, or the room is held with a reason, nothing opens and nothing is counted. This closes the 2.18.0 case where a pumped room with no pump mapped was watered with the valve open and no pump, and the shot counted as delivered.
- **Never declared (every existing install): no change**, and no disarm cycle after the update. The layout joins the saved setup fingerprint only when it is present, so the fingerprint 0.15.x saved still matches.
- A layout this controller does not know (a newer integration) is held, not guessed.
- No change to add-on options or to the state file.

# 0.15.2

Pair with integration 2.18.1. No change to irrigation behaviour, options or saved state.

- Test seam: the state file location can be overridden with the `F2_STATE_PATH` environment variable. **Unset, as on every install, it is `/data/state.json` exactly as before.** The constructor reads that file, and on adopting a setup writes it, before a test can redirect it; GitHub runners have no `/data`, so CI never noticed, but on any machine where `/data` exists and is writable (a devcontainer, this add-on's own container) the test suite wrote a real file there and leaked it into the next test.
- Bundles nothing new; the dashboard is the 2.18.0 build.

# 0.15.1

- A room switched off stays off while Home Assistant restarts. The room's on/off switch reads unavailable for a moment during a core restart, and unavailable used to mean on: an empty room began a fresh run and raised its probe alerts again. The controller now keeps the last value it read (also across its own restart) and only treats a switch it has never seen as on, which is what keeps integrations older than the switch watering.

# 0.15.0

Pair with integration 2.18.0. Existing options, engine flags, room IDs, counters and learned state are kept.
Updating from 0.14.0 resumes by itself; no kill-switch cycle is needed.

- A zone needs only its valve. Pump and main-line valve are optional, so a room with one smart plug or solenoid per zone irrigates. Lead times are skipped with the hardware they belong to; the close read-back and the hardware-fault latch cover whatever the room has. Three-switch rooms run exactly as before.
- The source-water EC probe may report µS/cm; it is converted to mS/cm before the sanity range and the gate. Previously such a probe read as out of range and the gate blocked every shot without saying why.
- The Cloudflare judge manages P2. With Auto Setpoints on and `cf_account_id` + `cf_api_token` set, `typesafe/jev` is asked once per clock hour during P2 (lights on, no dated plan). It may move the zone's `p2_shot_size` within 1-4 % and hold the working peak within 2 points of the learned one: one bounded step per lever per grow-day. A tripped guard, a low-confidence answer, or no answer in 5 s changes nothing; irrigation never waits on it. Status attributes `jev_last`, `jev_changed_today`, `working_peak_adjust`.
- Bundles the 2.18.0 dashboard (setup helpers in Rooms & setup).

# 0.14.0

Pair with integration 2.17.0. Existing options, engine flags, room IDs, counters and learned state are kept.
**After this update, turn the engine kill switch off and on once**: the previous build saved no record of the
setup it had accepted, so this first start has nothing to resume from. Later restarts and reboots carry on by themselves.

- Room on/off: `switch.crop_steering_<prefix>room_active` off means no irrigation of any kind and no alerts for that room.
- P1 no longer ends on a clock. It runs until the target is recovered after `p1_minimum_shots`, or `p1_maximum_shots` is reached.
- Auto Setpoints (off by default): learns each zone's ceiling, gain and dry-down; on a P1 plateau hands over to P2 and carries the achieved peak forward. Optional Cloudflare `typesafe/jev` check via the new `cf_*` options.
- The accepted setup revision is saved with a fingerprint, so an unchanged setup resumes after a restart with the kill switch left on (hardware must read off). A pending setup raises a notification naming what must read off.
- Switch read-back after a shot re-reads for up to 6 s instead of once at 1 s: a late Zigbee report no longer latches a false hardware hold.
- Bundles the 2.17.0 dashboard (recorded sensor data and the projected P0-P3 day on the Today graph).

# 0.13.3

- Combine daily targets and dated plans under Irrigation plan, with Today and Schedule views.
- Join schematic VWC and EC references through the night and into the next day.
- Show effective scheduled targets instead of disabled manual fallback fields when a schedule owns the room.
- Dashboard-only correction; controller decisions and stored settings are unchanged.

# 0.13.2

- Bundle graphical tank/pump telemetry and current zone state with last irrigation timestamps.
- Publish irrigation event timestamps with an explicit timezone offset.
- Include synthetic demo recipes/runs and the Home Assistant sidebar recovery button.

# Changelog — Crop Steering add-on

The full project changelog (integration + add-on) lives at
<https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/CHANGELOG.md>.

## 0.13.1

- Read the same-room legacy maximum-shot-duration entity when the canonical entity is absent, matching the dashboard calculator and reviewed edits. Reject an invalid existing duration cap before actuation.
- Bundle the user-authored recipe library and pair with integration 2.15.0. Existing room identities, options and persistent controller data remain compatible.

## 0.13.0

- Pair with integration 2.14.0 for reactive manual setpoint previews, run comparisons and clear zone/per-plant water calculations.
- Calculate new delivery counters from configured zone flow and elapsed valve runtime, including capped/truncated/minimum shots and partial aborts. Snapshot sizing before each shot so a mid-shot configuration edit cannot rewrite its volume.
- Keep existing options, engine flags, room IDs, learned state and old daily/weekly totals. Delivery remains a flow-based estimate, not a meter reading.

## 0.12.1

- Correct room names in the bundled workspace when HA descriptor sensors share a generic friendly name.
- Pair with integration 2.13.2. Irrigation decisions, options and persistent state format are unchanged from 0.12.0.

## 0.12.0

Update the Crop Steering integration to 2.13.0 before updating this controller. Existing options, enable flags, room IDs and persistent runtime data are retained.

- Serve the native dashboard with per-zone day/week grow plans and a combined VWC/EC planning graph.
- Read versioned setup and strategy snapshots, with explicit configuration acknowledgement and safe holds for invalid required plans.
- Correct low-flow sizing, elapsed duration accounting, volume caps, stale sequential decisions and shared-hardware recovery.
- Remove historical package examples from the installation bundle; sensor and equipment mapping belongs to the integration.

- Missing pore EC keeps base VWC shot sizing and pauses EC offset/PID adaptation, with a visible degraded status.
- Feed EC/pH and pore readings require finite values and valid, fresh, timezone-aware timestamps (60 seconds future-skew tolerance).
- Weekly delivery estimates persist seven grow-day buckets, include interrupted delivery and expose incomplete legacy history.

## 0.11.0

> **⚠️ Update the Crop Steering integration BEFORE rebuilding this add-on.** The engine now reads
> the default room's pump/mainline/valves from the integration's `sensor.crop_steering_engine_config`.
> On an old integration that doesn't publish it, the default room **holds safe (no watering)** until
> the integration is updated (the engine re-checks every 5 minutes and resumes on its own).

- **Portability:** default-room hardware comes from the integration's engine_config descriptor —
  the hardcoded F2 pump/valve fallback is gone. An unmapped room holds safe with a clear
  "no hardware mapped" reason instead of actuating another install's entities.
- **Kill switch works mid-shot:** shots are delivered in ≤2 s slices that re-check the kill switch
  and the zone's manual override; an abort closes the valve immediately and counts only the water
  actually delivered.
- **`notify_service` default is now empty** — unset means persistent notifications only (no more
  default pointing at the developer's phone). If you had it set explicitly, nothing changes.
- **Dosing/fill/flush holds are now the `hold_entities` option (empty default).** The previously
  hardcoded F2 hold entities (`input_boolean.nutrient_dosing_active`, `input_boolean.f2_fill_mode`,
  `input_boolean.f2_flush_mode`, `switch.tank_filling`) are no longer checked automatically —
  add yours to `hold_entities` in the Configuration tab or that gate stays off.
- **Live room discovery:** rooms added in the integration UI join within `rediscover_seconds`
  (default 300 s) without an add-on restart, fail-safe OFF.
- **Missing-setpoint alerts:** if a `number.crop_steering_*` setpoint entity disappears (per-zone
  AND global) for 3+ loops, you get one rate-limited alert + a vitals line instead of the engine
  silently running built-in defaults.
- **Timezone hardening:** tzdata baked into the image; startup logs the effective local time and
  alerts if the container clock disagrees with Home Assistant's configured zone.
- Heartbeat sensors publish the room's `enable_flag` (used by the integration's Repairs health
  checks); vitals title uses the new `instance_name` option.

## 0.10.5
- **Fix: zones could freeze in P2 if the fused-sensor entity_id didn't match.** The engine read
  each zone's probe at `sensor.crop_steering_<room>vwc_zone_N` / `ec_zone_N`, but on a box first set
  up under an older integration the HA registry keeps the legacy id `..._zone_N_vwc` / `_zone_N_ec`
  forever. The mismatch made every zone read as "blind" → `decide()` was skipped → the P0-P3 phase
  machine stopped (it never even forced P3 at lights-off), and the zones sat on a blind timer. The
  engine now resolves each fused sensor under **both** naming conventions (and `_detect_zones` counts
  either), so it finds the probe regardless of which id the registry assigned.
- **Hardening — a dead probe can no longer strand the daily cycle.** A blind zone still honours the
  time-based phase forces (lights-off → P3, P3 → P0 at the new photoperiod) even while VWC-driven
  steering is paused, so it can't freeze overnight. The "probe dead" alert now **repeats** (every
  ~30 min while blind) with the exact entity_id the engine is looking for, instead of firing once and
  going silent.

## 0.10.4
- **Engine Log panel now works.** It used to tail `/local/f2_engine.log`, which the add-on can't write
  (no `/config` map) — so it was always empty. It now reads the engine's published decision feed
  (`sensor.crop_steering_activity_log`), room-scoped, and only re-renders when the feed changes (also
  removes the 4s render churn).
- **"Next" on the irrigation-frequency card.** The engine now publishes a per-zone next-shot estimate
  `sensor.crop_steering_<room>_prediction_zone_N_next_irrigation_hours` (P2: time for VWC to dry to the
  re-water threshold at the current dryback rate; "—" when not computable).
- **Safety (HA-down observability):** the shot CLOSE sequence now checks every `turn_off` and reads the
  valve back HA-aware — a failed/unconfirmed close (e.g. HA unreachable mid-shot) raises a CRITICAL
  alert instead of silently reading as "closed". The shot is still counted (water was delivered) so the
  daily cap stays honest. NOTE: software cannot close a valve when HA is down — the hardware fail-safe
  (NC valves, pump-relay default-off, an independent watchdog) is the real guarantee.

## 0.10.3
- **Diagnostic:** f2.html logs one `[f2-perf]` console line per 30s tick (JS heap, DOM-node count +
  delta, Chart-instance count) to pinpoint the dashboard lag. Open the console, filter `[f2-perf]`,
  leave it until it lags, and watch which number climbs. Harmless; removed once the leak is found.

## 0.10.2
- **Fix: per-zone "Volume fed vs daily cap" + "Irrigation frequency" tiles were blank (—).** The engine
  now publishes `sensor.crop_steering_<room>_zone_N_daily_water_app` (litres fed today) and
  `..._irrigation_count_app` (shots today) — the data was already tracked in zone state, just not
  republished. Resets at the lights-on (P3→P0) rollover like the other daily counters. (Per room.)

## 0.10.1
- **Per-room dashboards (`?room=<slug>`).** The operator console (`f2.html`) and the mobile one-pager
  (`overview.html`) now scope to an additional room with `?room=f1` etc. — every `crop_steering_*`
  read/write is routed to that room's entities (two chokepoints, no per-id edits), the kill-switch
  button controls the **room's** kill switch, and a badge shows which room you're viewing. No `?room=`
  (default room) is unchanged.

## 0.10.0
- **Multi-room engine.** One add-on now drives **every** configured room, not just the first.
  Refactored around a `Room` abstraction; each room is a fully self-contained control loop with its
  own pump/mainline/valves, reservoir pH/EC feed gate, photoperiod, kill switch and durable state,
  namespaced `crop_steering_<slug>_*`. Additional rooms are discovered from the integration's published
  `sensor.crop_steering_<prefix>engine_config` descriptors and come up **fail-safe OFF**
  (`switch.crop_steering_<slug>_engine_enabled`, default off). The default room is byte-identical to
  before. `/data/state.json` is nested by room; an old flat single-room file still loads transparently.

## 0.9.1
- New logo (cannabis leaf + green growth chart + rising arrow, with the Home Assistant and Python
  marks). Updated the add-on icon and logo.

## 0.9.0
- **Vmax advisory.** The engine now watches each zone's morning P1 wet-up and publishes the detected
  field-capacity ceiling as `sensor.crop_steering_zone_N_vmax_detected` (with a confidence attribute).
  Advisory only — it does **not** change any irrigation decision. Pairs with the integration's
  named-stage recipes (2.10.0).
- Re-synced the vendored `crop_steering_engine` with the canonical source.

## 0.8.3
- Use the original Open Crop Steering logo artwork (leaf + water-drop in a green ring) for the
  add-on icon and logo, instead of the redrawn version.

## 0.8.2
- New logo (cannabis leaf + growth chart), matching the project mark.

## 0.8.1
- Fix: the dripper flow rate + drippers/plant now drive shot length even if a per-zone plant
  count is unset (it used to fall back to a generic flow value). Plant count cancels out of the
  duration maths, so it no longer gates the dripper settings.

## 0.8.0
- Generic out of the box: the source-water pH/EC feed gate is now **optional**. Set
  `feed_ec_sensor` / `feed_ph_sensor` to your reservoir probes to enable it; leave them blank to
  disable it (dosing / tank-fill holds still apply). Removed the hardcoded F2 probe defaults; the
  substrate/flow fallbacks are neutral placeholders.

## 0.7.0
- Renamed **F2 Control → Crop Steering** with a new logo. Proper description + feature list
  (Documentation tab) and this changelog. The dashboards are served as a sidebar panel
  (toggle **Show in sidebar** on the Info tab).

## 0.6.0
- **Configure once**: lights hours and zone count are now read from the integration, so the
  add-on options for them are just fallbacks. Ends the "lights out of sync" class of bug.

## 0.5.0
- The engine reads each zone's **fused** sensor (`sensor.crop_steering_vwc_zone_N` /
  `ec_zone_N`), so you can add **any number of probes per zone** in the integration UI and the
  engine uses all of them (averaged, outliers rejected). Removed the hardcoded zone sensors.

## 0.4.0
- Bundled the operator **dashboards into the add-on**, served over Home Assistant **ingress**
  (sidebar panel) with a Live/Demo chooser — no more copying `f2.html` to `/config/www`.

## 0.3.0
- Friendlier title + **custom icon**; help **tooltips** on every Configuration option.

## 0.2.0
- First standalone add-on release: pure crop-steering engine + REST IO + 30-min vitals,
  gated by the kill switch. Replaces the retired legacy engine.
