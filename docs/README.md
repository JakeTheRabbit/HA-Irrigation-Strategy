# Documentation

Start with the row that matches what you are doing. Updating an existing install to 3.18? Read
[Upgrade to 3.18: the plan](UPGRADING-TO-PARITY.md) before anything else.

## Getting started

| Document | What it covers |
| --- | --- |
| [System map](SYSTEM_MAP.md) | How any device reaches Crop Steering through Home Assistant, what each part does, and the lines that are never crossed. |
| [Roadmap](../ROADMAP.md) | What comes next, by priority and without dates. |
| [Install, upgrade and roll back](INSTALL.md) | The integration, the controller app or container, and the checks after install. |
| [Upgrade to 3.18: the plan](UPGRADING-TO-PARITY.md) | The plan for update day: what is carried across, what needs you, a first-hour checklist and how to go back. |
| [3.18 upgrade report, line by line](UPGRADING.md) | One section per row of the 3.18 Upgrade report, with services and fields. |
| [Set up an install with an AI assistant](AI-SETUP.md) | Connect the MCP server, start read-only, and let an assistant prepare changes you approve. |
| [Moving from the first AI edition](MOVING_FROM_JEV.md) | A one-time move of a room from `HA-Crop-Steering-Jev`. |
| [Crop Steering Academy](ACADEMY.md) | The free beginner course. |

## Using it

| Document | What it covers |
| --- | --- |
| [User guide](USER_GUIDE.md) | Every page of the dashboard and a daily routine. |
| [Dashboards and display](features/dashboards-and-display.md) | The menu, every page and its address, units and clock, wall and tablet dashboards. |
| [Timer programs and irrigation modes](features/timers-and-modes.md) | **Watering by** steering, timer or off; timer programs; skipping one shot. |
| [Water supply, pump queue and flow checks](features/water-supply.md) | Pump flow and sharing, CS-214, flow meters, CS-318 and CS-319. |
| [Presets and copying settings](features/presets-and-copy.md) | Saving, applying and copying settings, with preview and read-back. |
| [History, changes and putting things back](features/history-and-changes.md) | The event journal, History › Changes, revert, Irrigation › Timeline and History › Explorer. |
| [Alerts](features/alerts.md) | Threshold alert rules, the alerts inbox, acknowledging and quiet hours. |
| [Calibration](features/calibration.md) | Moisture probe offsets, feed pH/EC 2-point calibration, dosing pump prime and calibrate. |
| [System status](features/system-status.md) | Device health, silent probes, 7-day uptime and the controller heartbeat. |
| [Grow plans](GROW_PLANS.md) · [Recipe library](RECIPE_LIBRARY.md) | Planning a grow and the browser recipe library. |
| [Batch-tank dosing](DOSING.md) | Dosing pumps, batches, pH correction and stock tanks. |
| [Notifications](NOTIFICATIONS.md) | Who gets which alert on which phone. |
| [The AI assistant](AI_ASSISTANT.md) | Each judge, the envelope, the options and the costs. |
| [Long history](LONG_HISTORY.md) | Optional InfluxDB history. |

## Reference

| Document | What it covers |
| --- | --- |
| [Entity reference](ENTITIES.md) | Every entity the integration creates and the controller publishes. |
| [Error codes](ERROR_CODES.md) | Every CS code: meaning, effect on shots, causes and fixes (generated from `error-codes.json`). |
| [Troubleshooting](troubleshooting.md) | Symptoms and what to check. |
| [MCP](MCP.md) | The MCP tools, proposals and the API v2 answer envelope. |
| [Feature matrix](FEATURE_MATRIX.md) | What is implemented, tested and verified on hardware. |
| [Home Assistant sidebar](HA_SIDEBAR.md) | The sidebar panel and its limits. |
| [AI instructions](AI_INSTRUCTIONS.md) · [Restored options](AI_RESTORED_MODES.md) | What the AI assistant is told. |
| [References](REFERENCES.md) | Sources and attribution. |

## For developers

| Document | What it covers |
| --- | --- |
| [System overview](SYSTEM_OVERVIEW.md) · [Repository map](REPOSITORY_MAP.md) | Who owns what. |
| [Testing](TESTING.md) · [Releasing](RELEASING.md) | Checks and the release process. |
| [Screenshots](SCREENSHOTS.md) | The current dashboard screenshots. |
| [Contributing](../CONTRIBUTING.md) | How to send a change. |

`docs/dev/` holds design specs and plans for developers; it is not operator documentation.
