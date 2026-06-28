# Changelog — Crop Steering add-on

The full project changelog (integration + add-on) lives at
<https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/CHANGELOG.md>.

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
