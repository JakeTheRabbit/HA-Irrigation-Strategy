# Home Assistant Forum Post Draft

Title:

```text
Crop Steering: a Home Assistant irrigation integration and add-on for sensor-driven grow rooms
```

Post:

````markdown
Hi everyone,

I have been building a Home Assistant crop-steering system for automated irrigation in controlled grow rooms, and I wanted to share it with the community.

Repository:
https://github.com/JakeTheRabbit/HA-Irrigation-Strategy

Live demo:
https://jaketherabbit.github.io/HA-Irrigation-Strategy/f2.html?demo

Dedicated add-on repository:
https://github.com/JakeTheRabbit/f2-control

## What it does

The project has two main parts:

- A Home Assistant custom integration that creates the crop-steering entities, setup flow, setpoints, sensor fusion, recipes, and diagnostics.
- A Home Assistant add-on that runs the live control loop. It polls Home Assistant, decides whether each zone needs irrigation, sequences the pump/mainline/valves, republishes status sensors, and serves the dashboard over ingress.

The integration does not actuate hardware. The add-on is the only layer that opens valves, and it is gated by a kill switch.

## Main features

- Per-zone P0/P1/P2/P3 crop-steering phases.
- Multi-probe VWC and EC fusion per zone.
- Source-water pH/EC gate with fail-closed behavior.
- Pump/mainline/valve sequencing with valve-close readback.
- Daily volume caps, maximum shot-duration caps, emergency rescue, and lights-on watchdog protection.
- Live shot sizing from substrate volume, plant count, drippers per plant, and dripper flow rate.
- Named-stage recipes for Veg, Transition, Bulk, and Ripen.
- Multi-room support with isolated hardware maps and per-room kill switches.
- Operator dashboard served through Home Assistant ingress, with a standalone demo mode.
- Mobile-friendly overview page.
- Activity feed and health checks to make misconfiguration visible.

## Screenshots

Status:
![Status](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/main/img/demo-status.png)

Zones:
![Zones](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/main/img/demo-zones.png)

Plan timeline:
![Plan](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/main/img/demo-plan.png)

Tune editor:
![Tune](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/main/img/demo-tune.png)

Climate:
![Climate](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/main/img/demo-climate.png)

Operate:
![Operate](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/main/img/demo-operate.png)

## Install shape

The integration is installed as a custom repository in HACS.

The add-on is installed through the Home Assistant Add-on Store by adding this repository URL:

```text
https://github.com/JakeTheRabbit/f2-control
```

The safe setup path is:

1. Install the integration.
2. Map your zones, moisture probes, EC probes, valves, pump, mainline, lights, and substrate facts.
3. Install the add-on.
4. Keep the kill switch off while verifying sensors and hardware.
5. Start the add-on and watch the first live cycles before leaving it unattended.

## Current TODO

- Add add-on build/schema validation to CI.
- Keep improving the config flow for full hardware mapping and old-install upgrades.
- Add browser-level dashboard regression checks.
- Continue replacing standalone token workflows with ingress-first patterns.
- Improve first-day commissioning docs and release checklist.

This is aimed at people already using Home Assistant for irrigation hardware and who want sensor-driven steering rather than fixed timer schedules. Feedback from HA users, add-on maintainers, and anyone running irrigation automations would be useful.
````
