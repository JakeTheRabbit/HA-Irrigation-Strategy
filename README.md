# Crop Steering for Home Assistant

A Home Assistant irrigation controller with a native operator workspace: see the room, plan each zone, map sensors, and review changes before applying them.

**[Open interactive demo](https://jaketherabbit.github.io/HA-Irrigation-Strategy/dashboard.html?demo=1)** · [Install](docs/INSTALL.md) · [Feature checklist](docs/FEATURE_MATRIX.md)

The demo opens directly in your browser with sample rooms, sensor data and editable plans. No login or Home Assistant installation is required; demo changes stay in your browser.

![Release](https://img.shields.io/badge/Release-2.14.0-green)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.3+-41BDF5)
![License](https://img.shields.io/badge/License-MIT-green)

> Read the [validated feature matrix](docs/FEATURE_MATRIX.md) for tested behavior and installation/commissioning limits. Install matching integration and controller versions; a demo is not proof of physical water delivery.

![Crop Steering operator workspace](img/operator-dashboard.png)

## Start here

1. [Add the integration repository to HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=JakeTheRabbit&repository=HA-Irrigation-Strategy&category=integration), download it, and restart Home Assistant.
2. [Add Crop Steering in Devices & services](https://my.home-assistant.io/redirect/config_flow_start/?domain=crop_steering). Choose manual setup and name the first room.
3. [Add the controller app repository](https://my.home-assistant.io/redirect/supervisor_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FJakeTheRabbit%2FHA-Irrigation-Strategy), then install and start **Crop Steering Controller**.
4. Open **Crop Steering** in the sidebar. Use **Rooms & setup** to map equipment and probes, then **Sensors** to verify readings. Keep the engine off until the installation checks pass.

Home Assistant owns the install/restart confirmations; these links take you directly to the relevant screens. They do not bypass HACS, Supervisor or hardware commissioning. [Complete installation and upgrade guide →](docs/INSTALL.md)

## Plan the whole grow

Choose a room, zone and day or week. The steering slider updates the VWC/EC planning curve and shows the targets behind it.

![Combined VWC and EC planning graph with per-zone day and week controls](img/grow-plan.png)

## See each change before applying it

Manual setpoints keep the full-day VWC/EC graph beside the selected phase. Raise the P3 emergency threshold and its line moves immediately; the saved line remains visible behind your draft. Review and apply when ready.

![Manual P3 editing with saved and draft VWC/EC curves](img/manual-setpoints.png)

**Compare runs** aligns recorded day/week/month/run-to-date readings with an earlier run at the same grow age, or with a captured target reference. History availability depends on your Home Assistant Recorder retention. Registering an old run now does not recover its old setpoints.

![Recorded VWC and EC comparison against a previous run and target reference](img/run-comparison.png)

Water cards show **zone litres for all plants**, **average mL per plant today**, and **estimated water per runtime**. Total substrate capacity is labelled separately. For example, 42 plants with one 4 L/h dripper each receive an estimated 133 mL per plant / 5.6 L per zone over 120 seconds; a 60-second cap halves that. These estimates require correct flow settings and do not measure uptake or runoff.

## Set up rooms and sensors

Add or archive rooms and zones, map existing Home Assistant entities, and enter each zone's substrate, plants and drippers.

![Room and zone setup with sensor mapping](img/rooms-setup.png)

<details>
<summary>View the mobile dashboard</summary>

<img src="img/mobile-overview.png" alt="Mobile room overview with responsive navigation" width="390">

</details>

## One workspace

| Page | Purpose |
| --- | --- |
| Overview | Room condition, controller status, recorded VWC/EC and daily water per zone/per plant |
| Zones | Per-zone readings, active phase, targets and enable controls |
| Grow plan | Per-zone day/week schedule, steering slider, endpoint profiles and a reactive VWC/EC planning curve |
| Manual setpoints | Phase-focused controls beside reactive saved/draft VWC/EC curves, with water estimates and reviewed writes |
| Compare runs | Retained day/week/month/run-to-date history, previous-run alignment and captured target references |
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
- [Live upgrade verification](docs/audits/2026-09-08-live-upgrade.md)
- [Branch consolidation and archived features](docs/audits/2026-09-08-branch-consolidation.md)
- [Development and testing](docs/TESTING.md)
- [Entity reference](docs/ENTITIES.md)

The integration owns configuration, entities and plans. The companion controller owns irrigation decisions and equipment sequencing. Both are needed for autonomous irrigation. This project does not dose nutrients or control climate.

Old facility YAML, package examples, environment templates, full dashboards and superseded guides are retained with hashes in [archive/2026-09-08](archive/2026-09-08/README.md). Stable entity IDs and the existing controller slug remain compatible.
