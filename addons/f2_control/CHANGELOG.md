# Changelog — Crop Steering add-on

The full project changelog (integration + add-on) lives at
<https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/CHANGELOG.md>.

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
