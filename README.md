# Crop Steering

![Release](https://img.shields.io/badge/Release-3.17.0-blue)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.10+-41BDF5)
![HACS](https://img.shields.io/badge/HACS-Custom-orange)
![License](https://img.shields.io/badge/License-MIT-green)

**Crop Steering waters a grow room automatically from Home Assistant.** It reads the moisture (VWC) and
pore EC of each zone every minute, decides when a zone needs a shot and how big, and runs your pump and
valves with safety checks on every step. An optional AI assistant gives a second opinion on the
decisions that need judgement; code keeps control of every physical action.

> **3.18 (the parity release) is a big upgrade.** Watering keeps its targets and limits, but almost every
> dashboard page is new and many new features wait for you to set them up. Do not update a room that is
> in a grow unless you have a few clear hours afterwards, and never in the hour before lights-on. Read
> [Upgrading to 3.18](docs/UPGRADING-TO-PARITY.md) first. To let an AI assistant help with the
> configuration session, follow [Set up an install with an AI assistant](docs/AI-SETUP.md).

![All rooms across both demo rooms, grouped by room with current VWC, pore EC, water delivery and feed supply](img/all-zones.png)

[Try the demo](https://jaketherabbit.github.io/HA-Irrigation-Strategy/dashboard.html?demo=1) ·
[Free beginner course](https://jaketherabbit.github.io/HA-Irrigation-Strategy/learn/) ·
[Install](docs/INSTALL.md) · [User guide](docs/USER_GUIDE.md) · [All documents](docs/README.md)

## Safety first

This software runs real pumps and valves on live plants, when nobody is in the room.

> **WARNING:** Do not use the software as an emergency stop. Use the physical shutdown procedure of your
> installation. The **Watering** switch and **Room in use** do not isolate the electrical power.

> **CAUTION:** Install valves that close when the power is lost, and a float switch or timer that can
> stop a pump without the software.

What protects the plants and the equipment:

- **Kill switch.** Each room's **Watering** switch (`switch.crop_steering_<prefix>engine_enabled`, shown
  as "Engine Enabled") stops every shot in the room, rescue shots included. A new room starts with it off.
- **Holds.** The controller holds a zone or a room, and says why with a CS code, when a valve or pump does
  not read off, a probe is dead, the tank is at its minimum, the feed is out of range or a limit number
  cannot be read. A hold never switches anything on.
- **Read-back.** The controller reads back every valve and pump it switches. Target, timer program, alert
  rule and preset changes show a review of old and new values first, and the saved value is read back
  after.

Before the first automatic shot: configure the room with **Watering** off, check each probe and switch,
and do a catch test (measure what the drippers deliver in a known time).

## What you need

| Item | Requirement |
| --- | --- |
| **Home Assistant** | **2024.10.0 or newer.** Each change is tested on 2024.10.0 and on 2026.9.3. |
| **The controller as an app** | Home Assistant OS or Supervised, with the app store (amd64, aarch64 or armv7). The app brings its own Python 3.12. |
| **The controller as a container** | Home Assistant Container or Core has no app store. Use Docker with Compose v2 on amd64 or arm64. |
| **HACS** | Version 1.6.0 or newer for the guided download. You can also copy `custom_components/crop_steering` into Home Assistant manually. |
| **Hardware** | A switch that Home Assistant can control for the valve of each zone. Also a switch for the pump and the main-line valve, if the room has them. One moisture probe for each zone. EC probes and tank sensors are optional, but we recommend them. |
| **An Anthropic API key** (optional) | Only for the AI assistant. Without a key, the controller uses its rules only. |
| **An MCP connector** (optional) | Node.js 22 or newer, on the computer of your AI client. |
| **Account** | A Home Assistant administrator, to configure rooms and change plans. |

## Install

Crop Steering has two parts with the same version number. Install and update them together.

| Part | Install with | What it does |
| --- | --- | --- |
| **The integration** | HACS | Keeps rooms, zones, settings, plans and history, and adds the **Crop Steering** page to the sidebar. It never runs equipment. |
| **The controller** | The Home Assistant app store, or Docker | Reads the probes each minute, decides each shot and runs the pump and valves with all the safety checks. |

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=JakeTheRabbit&repository=HA-Irrigation-Strategy&category=integration)
[![Open your Home Assistant instance and add this app repository.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FJakeTheRabbit%2FHA-Irrigation-Strategy)
[![Open your Home Assistant instance and add Crop Steering.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=crop_steering)

The full steps, the Docker container and the checks after install are in [INSTALL.md](docs/INSTALL.md).
Then map the room in **Equipment › Setup: pumps & valves** with **Watering** off ([user guide](docs/USER_GUIDE.md#setup-pumps--valves)).

> **CAUTION:** Never run two controllers (an app and a container, or two apps) for one room. Both would
> run the same pump and valves.

## What it does

- **Waters by the plants, not a clock.** Four phases each grow-day: P0 morning dryback, P1 ramp, P2
  maintenance, P3 overnight dryback. Shots are sized from pot size, plant count and dripper flow.
- **Steers a whole grow.** A grow plan moves each zone between vegetative and generative targets, day by
  day or week by week ([grow plans](docs/GROW_PLANS.md)).
- **Timer programs** for zones that should run on a schedule instead of steering ([timers and modes](docs/features/timers-and-modes.md)).
- **Pump sharing.** A saved water supply lets rooms on one pump take turns, and flow meters check each
  shot and watch for leaks ([water supply](docs/features/water-supply.md)).
- **Presets and copy.** Save a room's or zone's settings and copy them to others, with a preview of every
  difference ([presets](docs/features/presets-and-copy.md)).
- **History you can act on.** One event journal behind the Timeline, Explorer and Changes; an
  administrator can put one change back ([history](docs/features/history-and-changes.md)).
- **Alerts.** Built-in CS codes, your own threshold rules, an inbox per room and quiet hours per phone
  ([alerts](docs/features/alerts.md), [notifications](docs/NOTIFICATIONS.md)).
- **Calibration.** Moisture probe offsets matched to a handheld meter, 2-point feed pH/EC calibration and
  dosing pump calibration ([calibration](docs/features/calibration.md)).
- **Dosing.** Batch-tank dosing, pH correction and stock tanks ([dosing](docs/DOSING.md)).
- **System status.** Every mapped device online, offline or silent, with 7-day uptime ([system status](docs/features/system-status.md)).

## The AI assistant

The AI assistant is optional. The controller can ask Claude, with your own Anthropic API key and a daily budget, questions such as "is
the substrate full?" or "is this probe stuck?". Each answer is only a request: code checks it against hard
limits before anything changes, and nothing waits for the assistant. It never runs a pump or valve, never
starts a shot and never stops a safety action. Without a key the controller uses its rules only. Details:
[the AI assistant](docs/AI_ASSISTANT.md).

A separate, optional MCP connector lets an AI client read your install and prepare configuration changes
for you to review ([AI setup](docs/AI-SETUP.md), [MCP reference](docs/MCP.md)).

## Documents

| For | Read |
| --- | --- |
| Updating to 3.18 | [Upgrading to 3.18](docs/UPGRADING-TO-PARITY.md) · [one section per Upgrade report row](docs/UPGRADING.md) |
| Installing | [Install, upgrade and roll back](docs/INSTALL.md) |
| Daily use | [User guide](docs/USER_GUIDE.md) · [Dashboards and display](docs/features/dashboards-and-display.md) |
| Problems | [Troubleshooting](docs/troubleshooting.md) · [Error codes](docs/ERROR_CODES.md) |
| Everything else | [Documentation index](docs/README.md) |

## Support

Report a problem in [GitHub issues](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/issues). Include
the alert code if you have one, both version numbers (the Crop Steering sidebar shows them) and the
controller log.

## License

[MIT](LICENSE). Sources and attribution: [references](docs/REFERENCES.md).
