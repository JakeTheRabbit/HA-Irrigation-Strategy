# Crop Steering for Home Assistant

A Home Assistant irrigation controller for crop steering: it waters each zone of a room through the four daily phases (P0 dryback, P1 ramp-up, P2 maintenance, P3 overnight) by what the zone's own moisture and EC probes read. A zone whose moisture probe stops giving a usable reading is still watered, with a working zone's shots or on a timed safety schedule, until the probe reads again. It also gives you a native workspace to plan each zone, map your sensors and switches, and review every change before it is applied.

**[Open the interactive demo](https://jaketherabbit.github.io/HA-Irrigation-Strategy/dashboard.html?demo=1)** · [Install](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/INSTALL.md) · [Feature checklist](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/FEATURE_MATRIX.md)

The demo runs in your browser with sample rooms, sensor data and editable plans. No login or Home Assistant is needed, and your changes stay in your browser. Its recipes and runs are clearly labelled synthetic examples, not growing recommendations.

![Release](https://img.shields.io/badge/Release-2.19.5-green)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.10+-41BDF5)
![License](https://img.shields.io/badge/License-MIT-green)

![Crop Steering operator workspace](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/main/img/operator-dashboard.png)

> **Safety.** This software switches real pumps and valves on unattended crops. Commission each room with the engine switched off, check every mapped switch and probe, and run a catch test before you let it water. It does not replace hardware fail-safes: use normally-closed valves, and a float switch or timer that stops a pump on its own. The [feature checklist](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/FEATURE_MATRIX.md) says what has been tested and what has not.

## What you need

| | |
| --- | --- |
| **Home Assistant** | **2024.10.0 or newer.** Every change is tested on 2024.10.0 and on 2026.9.3. Older versions are not supported. |
| **Python** | Whatever your Home Assistant runs on: the integration adds no Python packages of its own. Home Assistant OS, Supervised and Container bring their own Python. Only a Core (virtual environment) install chooses it: 2024.10 needs Python 3.12, and 2026.9 needs Python 3.14.2 or newer. |
| **Controller app** | Home Assistant OS or Supervised, where it installs from the app store (amd64, aarch64 or armv7) and brings its own Python 3.12. Container and Core have no app store: run the controller separately ([install guide](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/INSTALL.md)). |
| **HACS** | 1.6.0 or newer for the guided download, or copy `custom_components/crop_steering` in by hand. |
| **MCP connector** (optional) | Node.js 22 or newer, on the machine that runs your LLM client. |
| **Account** | A Home Assistant administrator for **Rooms & setup**, and to change plans, recipes and run records. |

## Install

Crop Steering is two parts, and autonomous watering needs both: the **integration** (installed with HACS) holds your rooms, settings, entities and plans; the **controller app** (installed from the Home Assistant app store) decides every shot and drives the pumps and valves.

1. **Download the integration with HACS.**
   [![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=JakeTheRabbit&repository=HA-Irrigation-Strategy&category=integration)
   Download **Crop Steering**, then restart Home Assistant.
2. **Add Crop Steering** and name your first room.
   [![Open your Home Assistant instance and start setting up Crop Steering.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=crop_steering)
3. **Add the controller app repository**, then install and start **Crop Steering Controller**.
   [![Open your Home Assistant instance and add this app repository.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FJakeTheRabbit%2FHA-Irrigation-Strategy)
4. Open **Crop Steering** in the sidebar. Map your pumps, valves and probes in **Rooms & setup**, then check the readings in **Sensors**. Keep the engine switched off until the installation checks pass.

The buttons only open the right screen: Home Assistant still asks you to confirm each download, install and restart. Updates arrive the same way: HACS offers the integration, and on Home Assistant OS or Supervised the app store offers the controller app. With Container or Core you run the controller yourself, so update it to the matching version by hand. Always install the matching pair named in the [changelog](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/CHANGELOG.md). The [installation and upgrade guide](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/INSTALL.md) covers manual installs, upgrades and rollback.

## See the room at a glance

Overview shows the controller's state, each zone's valve and last recorded irrigation, and the room's water use per zone and per plant. The graphical tank panel shows fill level, pump and filling status, the last recorded fill, EC, pH and temperature, from the tank sensors you map in **Rooms & setup**. Readings that aren't mapped, or are unavailable, are labelled as such.

![Graphical tank and pump status](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/main/img/tank-status.png)

## One irrigation plan: Today and Schedule

**Irrigation plan → Today** shows the targets the controller is using now, and lets you edit them when no schedule owns the room. **Schedule** is a dated plan for each zone: choose a room, a zone and a day or week, and a steering slider moves the zone between your vegetative and generative profiles, redrawing the VWC and EC curve with the targets behind it.

Save your own plans in the **Recipe library** and reuse them as drafts. Loading a recipe keeps each zone's start date; saving and arming still go through the normal review. [Recipe library →](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/RECIPE_LIBRARY.md)

![Combined VWC and EC planning graph with per-zone day and week controls](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/main/img/grow-plan.png)

![Reusable user-authored plans in the recipe library](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/main/img/recipe-library.png)

## Set targets against what the zone actually does

The graph you drag targets on draws the zone's own probe underneath them: recorded VWC for this grow-day and the one before, recorded pore EC, and the current reading with today's peak and trough. The VWC axis scales to the readings, so a zone sitting at 31% against a 40% target is obvious.

The day is drawn the way the controller runs it. P0 keeps drying after lights-on, P1 climbs one step per shot, P2 fires a shot each time VWC falls to its threshold, and P3 dries down overnight. Shot timing comes from the zone's measured dry-down rate, so the line is a projection, not a schedule: the controller always waters by the probe. If the targets can't be reached at that zone's dry-down, the graph shows it.

![Today's targets with the recorded zone and the projected day on one graph](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/main/img/plan-graph.png)

A history panel below shows 24 hours, 72 hours or 7 days of the same probes, with each setpoint drawn as a line and a note beside any target that sits outside what the probe reads.

![Recorded VWC and pore EC history with setpoint lines](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/main/img/sensor-history.png)

## See each change before applying it

Edits are drafts until you review them. A changed target moves its draft line on the graph straight away while the saved one stays visible; review and apply when you are ready.

![Draft and saved targets beside the plan graph, with the review bar](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/main/img/manual-setpoints.png)

**Compare runs** lines up recorded days, weeks, months or a whole run with an earlier run at the same grow age, or with a saved target reference. How far back it can go depends on your Home Assistant Recorder retention.

![Recorded VWC and EC comparison against a previous run and target reference](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/main/img/run-comparison.png)

Water cards show litres per zone, the average per plant today and the estimated water per runtime. For example, 42 plants with one 4 L/h dripper each get an estimated 133 mL per plant, 5.6 L per zone, in 120 seconds. These are estimates from your flow settings: they don't measure uptake or runoff.

## Switch an empty room off

Each room has a **Room on / off** control. Off means nothing is growing: no watering of any kind, emergency shots included, and no watering alerts. Readings stay visible. Switching it back on starts a clean day in order, never part-way through a phase, and keeps the recorded water history.

![A room switched off: readings shown, no irrigation and no alerts](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/main/img/room-off.png)

## Auto Setpoints (off by default)

The controller learns each zone from its own shots: the ceiling the probe actually reaches, what a shot lifts it, and how fast it dries with the lights on and off. With **Auto Setpoints** switched on for a room, it uses that to keep the zone's targets reachable: when two P1 shots in a row stop raising VWC, it hands over to P2 and carries the reached peak forward as the P1 target, holds it for three days, then tries one point higher. It changes only that zone's own targets, in small bounded steps, and never while a dated plan owns the room. Fields it manages carry an **Auto** badge.

An optional check by an AI model on Cloudflare Workers AI can veto a change when the evidence looks like a probe or delivery fault. Watering never waits on it, and no answer means no change.

## Set up rooms and sensors

Add or archive rooms and zones, map the Home Assistant entities you already have, and enter each zone's pot size, plants and drippers.

![Room and zone setup with sensor mapping](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/main/img/rooms-setup.png)

<details>
<summary>The dashboard on a phone</summary>

![Mobile room overview with responsive navigation](https://raw.githubusercontent.com/JakeTheRabbit/HA-Irrigation-Strategy/main/img/mobile-overview.png)

</details>

## One workspace

| Page | Purpose |
| --- | --- |
| Overview | Room condition, controller status, recorded VWC/EC and daily water per zone and per plant |
| Zones | Per-zone readings, active phase, targets and enable controls |
| Irrigation plan → Today / Schedule | Today: the current targets on a graph with the zone's recorded VWC/EC and the projected day. Schedule: per-zone dated plans, profiles and curves |
| Compare runs | Recorded day, week, month and run-to-date history, lined up with a previous run or a target reference |
| Insights | Sensor coverage, equipment mapping and dripper catch-test calculations |
| Activity | Controller and state activity, with what it can and can't show |
| Sensors | Probe availability, values, units and freshness |
| Rooms & setup | Add, configure, archive and restore rooms and zones; map existing Home Assistant entities |
| Settings / Help & tools | Connection, room on/off, theme, how each workflow works, and every error code with its causes and fixes |

The workspace opens in the Home Assistant sidebar and takes on your Home Assistant theme. Its scripts, styles and fonts are bundled, so it loads nothing from the internet.

## How steering works

Each zone runs P0 morning dryback, P1 ramp-up, P2 maintenance and P3 overnight, always in that order. P1 doesn't end on a clock: it runs until the target is reached after at least the minimum number of shots, or the maximum is reached. Dryback is relative to the detected peak: a 60% VWC peak with a 10% dryback target means 54% VWC.

A grow plan steers each zone on a 0–100% scale between a vegetative and a generative profile that you define, scheduled per zone. Pot size and dripper flow set how much water a shot is and how long it runs; they don't decide what the crop needs.

Plans are saved as drafts, reviewed, and armed for the next lights-on. Arming never switches the engine or a pump on. [Planning guide →](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/GROW_PLANS.md)

Every alert from the controller app, and every Crop Steering card in **Settings → Repairs**, ends with a code such as CS-101 (the controller's regular status summary has none). **Help & tools → Error codes** explains each one: what it means, what happens to watering meanwhile, and what to do.

## Documentation

- [Install, upgrade and rollback](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/INSTALL.md)
- [Step-by-step user guide](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/USER_GUIDE.md)
- [Daily operation and whole-grow planning](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/GROW_PLANS.md)
- [Troubleshooting](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/troubleshooting.md)
- [Error codes (CS-101 and the rest): causes and fixes](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/ERROR_CODES.md)
- [Validated feature checklist and limitations](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/FEATURE_MATRIX.md)
- [Entity reference](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/ENTITIES.md)
- [Home Assistant sidebar and menu button](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/HA_SIDEBAR.md)
- [Connect an LLM with the MCP server](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/MCP.md) (optional: it can read rooms, readings and plans and prepare changes for you to review; it never operates equipment)
- [Current screenshots](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/SCREENSHOTS.md)
- [Architecture and repository map](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/REPOSITORY_MAP.md) · [Development and testing](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/TESTING.md) · [Contributing](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/CONTRIBUTING.md)

This project waters by moisture and EC. It does not dose nutrients or control climate.

## Support

Report a problem or ask a question in [GitHub issues](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/issues). Include the error code if you have one, your integration and controller app versions (both shown in the Crop Steering sidebar), and what the controller app's log says.

## License

[MIT](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/LICENSE)
