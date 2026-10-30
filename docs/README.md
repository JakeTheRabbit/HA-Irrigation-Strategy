# Documentation

New here? Start with the website's [Is it for me?](https://cropsteering.growlabs.nz/is-it-for-me) and the [demo](https://jaketherabbit.github.io/HA-Irrigation-Strategy/dashboard.html?demo=1).

## Start here

| Document | What it covers |
| --- | --- |
| [Crop Steering Academy](ACADEMY.md) | The free beginner course. |
| [Learner workbook](training/crop-steering-from-zero/WORKBOOK.md) | Glossary, calculations, graph exercises, setup record, daily routine and explained answers. |
| [Feature matrix](FEATURE_MATRIX.md) | What is implemented, tested and verified on hardware. |
| [System map](SYSTEM_MAP.md) | How any device reaches Crop Steering through Home Assistant, what each part does, and the lines that are never crossed. |
| [Roadmap](../ROADMAP.md) | What comes next, by priority and without dates. |
| [Screenshots](SCREENSHOTS.md) | The current dashboard screenshots. |

## Set up

| Document | What it covers |
| --- | --- |
| [Equipment and setup](training/crop-steering-from-zero/EQUIPMENT-AND-SETUP.md) | Functional kit, compatibility sheet, water/control paths and staged commissioning. |
| [Install, upgrade and roll back](INSTALL.md) | The integration, the controller app or container, and the checks after install. |
| [First-run setup](FIRST_RUN.md) | Examine the install, set up a room, and the checks before the first watering. |
| [Water supply, pump queue and flow checks](features/water-supply.md) | Pump flow and sharing, CS-214, flow meters, CS-318 and CS-319. |
| [Calibration](features/calibration.md) | Moisture probe offsets, feed pH/EC 2-point calibration, dosing pump prime and calibrate. |
| [Batch-tank dosing](DOSING.md) | Dosing pumps, batches, pH correction and stock tanks. |
| [Long history](LONG_HISTORY.md) | Optional InfluxDB history. |

## Use it every day

| Document | What it covers |
| --- | --- |
| [User guide](USER_GUIDE.md) | Every page of the dashboard and a daily routine. |
| [Dashboards and display](features/dashboards-and-display.md) | The menu, every page and its address, units and clock, the Home Assistant sidebar, wall and tablet dashboards. |
| [Grow plans](GROW_PLANS.md) | Planning a grow and the browser recipe library. |
| [Timer programs and irrigation modes](features/timers-and-modes.md) | **Watering by** steering, timer or off; timer programs; skipping one shot. |
| [Presets and copying settings](features/presets-and-copy.md) | Saving, applying and copying settings, with preview and read-back. |
| [History, changes and putting things back](features/history-and-changes.md) | The event journal, History › Changes, revert, Irrigation › Timeline and History › Explorer. |
| [Alerts](features/alerts.md) | Threshold alert rules, the alerts inbox, acknowledging and quiet hours. |
| [Notifications](NOTIFICATIONS.md) | Who gets which alert on which phone. |
| [System status](features/system-status.md) | Device health, silent probes, 7-day uptime and the controller heartbeat. |

## Upgrade

| Document | What it covers |
| --- | --- |
| [Upgrade to 3.18: the plan](UPGRADING-TO-PARITY.md) | The plan for update day: what is carried across, what needs you, a first-hour checklist and how to go back. |
| [3.18 upgrade report, line by line](UPGRADING.md) | One section per row of the 3.18 Upgrade report, with services and fields. |

## Fix a problem

| Document | What it covers |
| --- | --- |
| [Troubleshooting](troubleshooting.md) | Symptoms and what to check. |
| [Error codes](ERROR_CODES.md) | Every CS code: meaning, effect on shots, causes and fixes (generated from `error-codes.json`). |

## AI assistant (optional)

| Document | What it covers |
| --- | --- |
| [The AI assistant](AI_ASSISTANT.md) | Each judge, the envelope, the options and the costs. |
| [AI instructions](AI_INSTRUCTIONS.md) | What the AI assistant is told, including the restored options. |
| [Set up an install with an AI assistant](AI-SETUP.md) | Connect the MCP server, start read-only, and let an assistant prepare changes you approve. |
| [MCP](MCP.md) | The MCP tools, proposals and the API v2 answer envelope. |
| [Crop Steering MCP](../mcp-server/README.md) | The MCP server itself. |

## Reference

| Document | What it covers |
| --- | --- |
| [Entity reference](ENTITIES.md) | Every entity the integration creates and the controller publishes. |
| [System overview](SYSTEM_OVERVIEW.md) | Who owns what. |
| [Crop Steering Controller](../addons/f2_control/DOCS.md) | The controller app's own page. |
| [References](REFERENCES.md) | Sources and attribution, including the recipe library's reference sources. |

**Legacy: one-time moves**

| Document | What it covers |
| --- | --- |
| [Moving from the first AI edition](MOVING_FROM_JEV.md) | A one-time move of a room from `HA-Crop-Steering-Jev`. |

---

## For contributors

| Document | What it covers |
| --- | --- |
| [Contributing](../CONTRIBUTING.md) | How to send a change. |
| [Testing](TESTING.md) · [Releasing](RELEASING.md) | Checks and the release process. |
| [Repository map](REPOSITORY_MAP.md) | Who owns what. |
| [dev/](dev/) | Developer notes: the [unified schema](dev/architecture/2026-10-22-unified-schema.md), the [developer system map](dev/system-map.md), the [system audit](dev/audits/system-audit.md) and the [Academy developer notes](dev/academy.md). |
| Academy authoring | [Course plan](training/crop-steering-from-zero/COURSE-PLAN.md) · [R4 writing guide](training/crop-steering-from-zero/R4-WRITING-GUIDE.md) · [R4 rebuild record](training/crop-steering-from-zero/COURSE-REBUILD-2026-10-20-R4.md) · [Production and evidence](training/crop-steering-from-zero/PRODUCTION-AND-SOURCES.md) |

## Archive

[archive/](archive/) holds finished plans, specs, audits and records. They are kept, not maintained.

| Folder | What it holds |
| --- | --- |
| [archive/superpowers/](archive/superpowers/) | Design plans, specs, mockups and the UI verification record, all shipped. |
| [archive/audits/](archive/audits/) | The 2026-09-21 first-run review. |
| [archive/academy/](archive/academy/) | Earlier Academy editions: the R3 rebuild record, the original delivery, the pilot repair, the pilot scripts and the storyboard. |
| [CHANGELOG-2.x.md](archive/CHANGELOG-2.x.md) | Releases 2.13.0 to 2.25.1. |
