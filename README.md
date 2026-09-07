# Crop Steering for Home Assistant

A Home Assistant irrigation controller with a native operator workspace: see the room, plan each zone, map sensors, and review changes before applying them.

![Release](https://img.shields.io/badge/Release-2.12.0-green)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.3+-41BDF5)
![License](https://img.shields.io/badge/License-MIT-green)

> The workspace and grow-plan changes described here are unreleased source changes. The guided installer uses the published main/release version until this branch is merged. Read the [validated feature matrix](docs/FEATURE_MATRIX.md) for local test evidence and outstanding live verification.

![Crop Steering operator workspace](img/operator-dashboard.png)

## Start here

1. [Add the integration repository to HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=JakeTheRabbit&repository=HA-Irrigation-Strategy&category=integration), download it, and restart Home Assistant.
2. [Add Crop Steering in Devices & services](https://my.home-assistant.io/redirect/config_flow_start/?domain=crop_steering). Choose manual setup and name the first room.
3. [Add the controller app repository](https://my.home-assistant.io/redirect/supervisor_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FJakeTheRabbit%2FHA-Irrigation-Strategy), then install and start **Crop Steering Controller**.
4. Open **Crop Steering** in the sidebar. Use **Rooms & setup** to map equipment and probes, then **Sensors** to verify readings. Keep the engine off until the installation checks pass.

Home Assistant owns the install/restart confirmations; these links take you directly to the relevant screens. They do not bypass HACS, Supervisor or hardware commissioning. [Complete installation and upgrade guide →](docs/INSTALL.md)

![Reactive combined VWC and EC grow planner](img/grow-plan.png)

## One workspace

| Page | Purpose |
| --- | --- |
| Overview | Room condition, controller status, combined recorded VWC and EC history |
| Zones | Per-zone readings, active phase, targets and enable controls |
| Grow plan | Per-zone day/week schedule, steering slider, endpoint profiles and a reactive VWC/EC planning curve |
| Manual setpoints | Review and apply existing controller parameters when a grow plan is not in control |
| Insights | Sensor coverage, equipment mapping and local dripper catch-test calculations |
| Activity | Available controller/state activity with explicit evidence limits |
| Sensors | Probe availability, values, units and freshness |
| Rooms & setup | Add, configure, archive and restore rooms/zones; search and map existing HA entities |
| Settings / Help | Connection, inherited HA theme, workflow explanations and limitations |

The React/shadcn workspace inherits Home Assistant colors and typography in its same-origin sidebar panel. It bundles Roboto, scripts and styles locally. Standalone use supports light/dark themes; no CDN is needed. Old dashboard addresses redirect into the new workspace.

## How steering works

The legacy mode selects separate dryback and EC references. A grow plan replaces those two discrete choices with a **0–100% interpolation between explicit vegetative and generative endpoint profiles**, separately scheduled for each zone. Pot size and dripper flow determine estimated water volumes and run times; they cannot determine suitable crop targets by themselves.

The controller runs P0 morning dryback, P1 ramp-up, P2 maintenance and P3 overnight/rescue phases. Dryback is relative to the detected peak: a 60% VWC peak with a 10% dryback target means 54% VWC. The planning graph connects configured VWC and EC targets over the day. It is a schematic, not a forecast of measured plant response.

Plans are saved as drafts, reviewed, and armed for the next local lights-on boundary. Arming never enables pumps or the engine. The controller consumes one versioned plan snapshot; a missing or stale required snapshot holds irrigation. [Planning guide →](docs/GROW_PLANS.md)

## Documentation

- [Install, upgrade and rollback](docs/INSTALL.md)
- [Daily operation and whole-grow planning](docs/GROW_PLANS.md)
- [Validated feature matrix and limitations](docs/FEATURE_MATRIX.md)
- [Architecture and repository map](docs/REPOSITORY_MAP.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Current screenshots](docs/SCREENSHOTS.md)
- [Development and testing](TESTING.md)
- [Entity reference](ENTITIES.md)

The integration owns configuration, entities and plans. The companion controller owns irrigation decisions and equipment sequencing. Both are needed for autonomous irrigation. This project does not dose nutrients or control climate.

Legacy full dashboards, superseded guides and one-off tools are retained with provenance in [archive/2026-09-08](archive/2026-09-08/README.md). Stable entity IDs and the existing controller slug remain compatible.
