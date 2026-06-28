# Crop Steering

Autonomous, professional **crop steering** for Home Assistant — the kind of substrate-driven
irrigation control that commercial controllers (AROYA, TrolMaster) charge thousands for, on the
hardware and platform you already own. It runs the full daily **P0 → P1 → P2 → P3** dryback
cycle per zone, off your live VWC/EC probes, sequences the pump and valves safely, and steers
each zone toward a **vegetative** or **generative** response.

> *("F2" in older versions was just one grow room. This drives any number of zones.)*

## Features

- **Autonomous 4-phase cycle (P0–P3) per zone** — morning dryback → ramp-up → maintenance →
  overnight dry-back, timed to the *substrate*, not the clock. Each zone runs independently.
- **Multi-probe sensor fusion** — map as many VWC/EC probes per zone as you like; the engine
  averages them and rejects outliers (no single lying probe starves a zone).
- **Configure once, in the UI** — lights hours, zone count and sensors are read from the Crop
  Steering integration. Nothing to keep in sync here.
- **Hard kill switch** — gated by `input_boolean.f2_control_enabled`. **OFF = safe**: it reads,
  decides and notifies but never opens a valve. One flick to stop everything.
- **Safety-first hardware** — source-water feed gate (pH + EC, fail-closed on a dead probe),
  pump → mainline → valve sequence with **valve-close read-back** (emergency pump stop on
  fault), per-zone daily volume cap, and a flood-guard shot-duration cap.
- **Minimum daily water floor** — guarantee a per-plant minimum each day regardless of what a
  sensor says.
- **EC steering** — auto-stacks substrate EC toward a per-stage target (optional PID).
- **Operator dashboards in the sidebar** — the full console (Status / Zones / Tune / Climate /
  Operate / Plan) plus a mobile vitals page, served straight from the add-on over Home
  Assistant ingress. Toggle **Show in sidebar** on the Info tab. A **Demo** mode (mock data)
  lets you look around with nothing connected.
- **Phone vitals + alerts** — a periodic summary and urgent alerts to your notify service.
- **Survives restarts and updates** — per-zone runtime state persists; upgrades load in place,
  never wiping your progress.

## Quick start

1. **Install the companion integration** first (HACS → *Crop Steering System*) and map your
   zones + sensors in its UI. See the
   [full install guide](https://jaketherabbit.github.io/HA-Irrigation-Strategy/install.html).
2. **Create the kill switch** helper `input_boolean.f2_control_enabled` (Settings → Devices &
   Services → Helpers → Toggle). Leave it **OFF**.
3. On the **Configuration** tab, set your `notify_service`. Lights/zones come from the
   integration automatically.
4. **Start** the add-on. The **Log** shows `starting … | token present: True`.
5. Open the **Crop Steering** sidebar panel → use **Demo** to look around, or **Live** for your
   real data.
6. Watch a photoperiod with the kill switch **OFF**, then flip it **ON** to go live.

## Links

- **Documentation & install guide:** <https://github.com/JakeTheRabbit/HA-Irrigation-Strategy>
- **Wiki (troubleshooting, configuration):** <https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/wiki>
- **Changelog:** see the *Changelog* link on the Info tab.

## Updating

Use the add-on's **Update** button (or **⋮ → Rebuild**). The code is baked into the image at
build time, so a plain *Restart* keeps the old code — Update/Rebuild loads the new version.
