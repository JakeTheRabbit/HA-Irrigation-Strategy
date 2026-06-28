# Changelog — Crop Steering add-on

The full project changelog (integration + add-on) lives at
<https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/CHANGELOG.md>.

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
  gated by the kill switch. Replaces the retired AppDaemon engine.
