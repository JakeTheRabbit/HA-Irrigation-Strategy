# Crop Steering for Home Assistant

A Home Assistant irrigation controller with a native operator workspace: see the room, plan each zone, map sensors, and review changes before applying them.

**[Open interactive demo](https://jaketherabbit.github.io/HA-Irrigation-Strategy/dashboard.html?demo=1)** · [Install](docs/INSTALL.md) · [Feature checklist](docs/FEATURE_MATRIX.md)

The demo opens directly in your browser with sample rooms, sensor data and editable plans. No login or Home Assistant installation is required; demo changes stay in your browser.

The demo includes clearly labelled synthetic recipes and current/previous runs for exploring comparisons. They demonstrate the software; they are not production recommendations.

![Release](https://img.shields.io/badge/Release-2.16.1-green)
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

## See the room at a glance

Overview shows the controller state, mapped valve on/off report and last recorded irrigation for every zone. The graphical tank panel shows fill percentage, pump status, filling status, last recorded fill, EC, pH and temperature.

Map tank sensors in **Rooms & setup**. Display-only tank quality mappings are separate from feed-water safety gates. Last fill uses a recorded fill timestamp (timestamp sensor or a date-and-time helper), never a sensor update time. Unmapped or unavailable readings are labelled explicitly.

![Graphical tank and pump status](img/tank-status.png)

The recorded 8 September **2.16.0** live check showed F2 tank **42%**, **3.06 mS/cm EC**, **pH 5.66** and **17.9 °C**, plus an explicit recorded-fill source and timezone-aware last-irrigation times. Reviewed MCP tank-mapping proposals applied and read back in both rooms at setup revision **1**; healthy controller reports acknowledged revision **1**. The native HA sidebar was hidden in the panel, and the Home Assistant button reopened it. These are dated observations, not current readings or proof of physical delivery.

## One irrigation plan: Today and Schedule

**Irrigation plan** brings current targets and dated planning together. **Today** shows editable current targets when no schedule owns the room; an active schedule shows its effective targets and graph as read-only, with fallback manual inputs hidden. **Schedule** edits the dated plan for each zone.

The unified navigation and overnight curves are published and verified live in **2.16.1 / controller 0.13.3**. Both Today and Schedule opened in the native HA panel, all 398 existing control values matched the pre-upgrade snapshot, and the installed dashboard files matched the public demo. See the [release verification](docs/audits/2026-09-08-unified-plan.md). Existing `#/strategy` and `#/grow-plan` bookmarks continue to open Today and Schedule respectively.

In **Irrigation plan → Schedule**, choose a room, zone and day or week. The steering slider updates the VWC/EC planning curve and shows the targets behind it.

Save your own plans in **Irrigation plan → Schedule → Recipe library** and reuse them as local drafts. The library is kept in this browser, separated by room and demo/live mode. Loading retains the current zone start dates; saving and arming still use the normal review workflow. [Recipe library and reference sources →](docs/RECIPE_LIBRARY.md)

![Combined VWC and EC planning graph with per-zone day and week controls](img/grow-plan.png)

![Reusable user-authored plans in the recipe library](img/recipe-library.png)

## See each change before applying it

**Irrigation plan → Today** keeps the full-day VWC/EC graph beside the current targets. With no active schedule, raising the P3 emergency threshold moves its draft line immediately while the saved reference remains visible. Review and apply when ready. When a schedule owns the room, Today displays its effective targets and graph without exposing fallback manual controls; use **Schedule** for dated plan changes.

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

| Page                               | Purpose                                                                                                                                             |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Overview                           | Room condition, controller status, recorded VWC/EC and daily water per zone/per plant                                                               |
| Zones                              | Per-zone readings, active phase, targets and enable controls                                                                                        |
| Irrigation plan → Today / Schedule | Today shows current editable targets or the active schedule’s read-only effective targets; Schedule edits per-zone dated plans, profiles and curves |
| Compare runs                       | Retained day/week/month/run-to-date history, previous-run alignment and captured target references                                                  |
| Insights                           | Sensor coverage, equipment mapping and local dripper catch-test calculations                                                                        |
| Activity                           | Available controller/state activity with explicit evidence limits                                                                                   |
| Sensors                            | Probe availability, values, units and freshness                                                                                                     |
| Rooms & setup                      | Add, configure, archive and restore rooms/zones; search and map existing HA entities                                                                |
| Settings / Help                    | Connection, inherited HA theme, workflow explanations and limitations                                                                               |

The React/shadcn workspace inherits Home Assistant colors and typography in its same-origin sidebar panel. It bundles Roboto, scripts and styles locally. Standalone use supports light/dark themes; no CDN is needed. Old dashboard addresses redirect into the new workspace.

## How steering works

The legacy mode selects separate dryback and EC references. A grow plan replaces those two discrete choices with a **0–100% interpolation between explicit vegetative and generative endpoint profiles**, separately scheduled for each zone. Pot size and dripper flow determine estimated water volumes and run times; they cannot determine suitable crop targets by themselves.

The controller runs P0 morning dryback, P1 ramp-up, P2 maintenance and P3 overnight/rescue phases. Dryback is relative to the detected peak: a 60% VWC peak with a 10% dryback target means 54% VWC. The updated planning graph joins the daytime references through lights-off and overnight to the next lights-on. Its dashed EC line interpolates between configured phase anchors; it does not predict salt concentration or the physical EC trajectory. Missing inputs remain gaps. Both curves are planning illustrations, not forecasts of measured plant response.

Plans are saved as drafts, reviewed, and armed for the next local lights-on boundary. Arming never enables pumps or the engine. The controller consumes one versioned plan snapshot; a missing or stale required snapshot holds irrigation. [Planning guide →](docs/GROW_PLANS.md)

## Documentation

To connect an LLM, install the optional [MCP connector](docs/MCP.md). It can inspect rooms, readings, mappings, plans and runs, then prepare specific configuration proposals. Writes require explicit opt-in and review; it does not operate equipment or activate plans.

- [Install, upgrade and rollback](docs/INSTALL.md)
- [Step-by-step user guide](docs/USER_GUIDE.md)
- [Connect an LLM with the MCP server](docs/MCP.md)
- [Home Assistant sidebar and menu button](docs/HA_SIDEBAR.md)
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
