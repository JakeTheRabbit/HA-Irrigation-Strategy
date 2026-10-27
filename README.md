# Crop Steering

![Release](https://img.shields.io/badge/Release-3.18.0-blue)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.10+-41BDF5)
![HACS](https://img.shields.io/badge/HACS-Custom-orange)
![License](https://img.shields.io/badge/License-MIT-green)

**Crop Steering waters each zone of a grow room from what its probes read, inside Home Assistant. It refuses to water when something is wrong, and it shows you every watering.**

![All rooms across both demo rooms, grouped by room with current VWC, pore EC, water delivery and feed supply](img/all-zones.png)

[Try the demo](https://jaketherabbit.github.io/HA-Irrigation-Strategy/dashboard.html?demo=1) · [Is it for me?](https://cropsteering.growlabs.nz/is-it-for-me) · [Free Academy](https://jaketherabbit.github.io/HA-Irrigation-Strategy/learn/) · [Website](https://cropsteering.growlabs.nz)

> **Updating from 3.17 or earlier?** Read [Upgrade to 3.18: the plan](docs/UPGRADING-TO-PARITY.md) first: integration first, then the controller, and never in the hour before lights-on.

## What it does

- **Why.** A timer waters at fixed times, whatever the plants did overnight. Crop steering lets the substrate dry back by a set amount, then brings it back up, so you choose whether the plants lean vegetative or generative.
- **It watches.** Moisture (VWC) and pore EC probes in each zone, the feed tank and the lights. Several probes in one zone become one reading, and a probe that goes quiet is left out.
- **It decides.** Each day runs in [four phases](docs/GROW_PLANS.md#the-words-youll-see): P0 morning dryback, P1 ramp, P2 maintenance and P3 overnight dryback. You set targets per zone, or a plan for the whole grow, and the engine sizes each watering (the dashboard calls it a shot) from how fast that zone is drying.
- **It stays safe.** A fixed list of checks runs before every watering. Every pump and valve switch is read back, and one that does not answer stops watering and raises an alert. A daily water limit and a maximum shot duration mean a stuck probe cannot keep a valve open all day.
- **You see it.** All rooms, then a room, then a zone with every watering on its day chart. History compares runs. It works on a phone, and alerts with a code go to the phones you choose.
- **You change it.** Edits stay a draft until you review and apply them, and each value is read back so you see what the controller now holds.

Every feature: [website Features](https://cropsteering.growlabs.nz/features) · What is tested: [Feature matrix](docs/FEATURE_MATRIX.md)

## Is it for you?

It suits you if:

- You grow in containers, in rooms you can split into zones with one valve each.
- You run Home Assistant, or are willing to.
- You want watering decided by probe readings, with a record of every shot.
- You are comfortable running self-hosted software and testing it on one zone first.

It is not a fit if:

- You need a vendor support contract or certified hardware.
- You want one system to also run climate, lights, tasks and compliance records.
- You need several zones watered at the same moment.
- Your EC meter only reports in ppm.

[Take the 1-minute fit check](https://cropsteering.growlabs.nz/is-it-for-me) · [Supported hardware](https://cropsteering.growlabs.nz/hardware)

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

## Safety first

- Do not use the software as an emergency stop. Use the physical shutdown procedure of your installation. The "Watering" switch does not isolate the electrical power.
- Install valves that close when the power is lost, and a float switch or a timer that can stop a pump without the software.
- Start on one zone with the "Watering" switch off, and do a catch test before the first watering ([First-run setup](docs/FIRST_RUN.md#before-the-first-watering)). More: [Safety](https://cropsteering.growlabs.nz/safety).

## Install

Crop Steering has two parts. Automatic watering needs both parts. The two parts have the same version number. Install and update them together.

| Part | Install with | What it does |
| --- | --- | --- |
| **The integration** | HACS | It keeps your rooms, zones, settings, plans and history. It adds the **Crop Steering** page to the Home Assistant sidebar. It does not operate equipment. |
| **The controller** | The Home Assistant app store, or Docker | It reads your probes each minute and decides each shot. It operates the pump and the valves with all the safety checks. It asks the AI assistant when that is set. |

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=JakeTheRabbit&repository=HA-Irrigation-Strategy&category=integration)
[![Open your Home Assistant instance and add Crop Steering.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=crop_steering)
[![Open your Home Assistant instance and add this app repository.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FJakeTheRabbit%2FHA-Irrigation-Strategy)

The buttons open the correct screen. Home Assistant still asks you to confirm each step. Docker: see [INSTALL › Home Assistant Container or Core](docs/INSTALL.md#home-assistant-container-or-core). Every step: [Install, upgrade and roll back](docs/INSTALL.md).

**Next →** [First-run setup](docs/FIRST_RUN.md)

## The AI assistant

The AI assistant is optional. Without it, the controller uses its rules, and the rules are always safe. It uses Claude from Anthropic with your own API key, or an Anthropic-compatible router that you control (`anthropic_base_url`). Anthropic bills you for its use.

- It never operates a pump, a valve or the main line. It never starts a shot.
- It never stops a safety action: the daily minimum and maximum water, the rescue shot, a flush for high EC, or the watchdog.
- When the AI assistant is off, slow, out of budget or not sure, the controller uses its rules only.

[The AI assistant in full: each judge, the envelope and the options](docs/AI_ASSISTANT.md)

## Upgrade

- [Upgrade to 3.18: the plan](docs/UPGRADING-TO-PARITY.md): the order, a first-hour checklist and how to go back.
- [INSTALL › Upgrading an existing installation](docs/INSTALL.md#upgrading-an-existing-installation) and [Restore a prior version](docs/INSTALL.md#restore-a-prior-version). One-time moves: [from the f2-control mirror](docs/INSTALL.md#moving-a-controller-installed-from-f2-control) and [from the first AI edition](docs/MOVING_FROM_JEV.md).

## Troubleshooting

A notification or a Repairs card ends with a code, for example **CS-101**. Find the code in **Settings › Help** or in [Error codes](docs/ERROR_CODES.md). Symptoms and what to check: [Troubleshooting](docs/troubleshooting.md).

## Documents

- [All documents, by task](docs/README.md)
- [User guide: each page of the dashboard](docs/USER_GUIDE.md)
- [Install, upgrade and roll back](docs/INSTALL.md)
- [The AI assistant](docs/AI_ASSISTANT.md)
- [How it all connects: the system map](docs/SYSTEM_MAP.md) · [Roadmap](ROADMAP.md)
- [Contributing](CONTRIBUTING.md)

## Support

Report a problem or ask a question in [GitHub issues](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/issues). The [bug report form](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/issues/new?template=bug_report.yml) asks for these items:

- The alert code, if you have one.
- The two version numbers. The Crop Steering sidebar shows them.
- The log of the controller.

## License

[MIT](LICENSE)

## References and acknowledgements

Athena's grow guide, handbook and educational resources informed this project's crop-steering and irrigation-strategy work. See the [Athena Commercial Handbook](https://growershub.athenaag.com/athena-handbook-v41iwrqr), [Precision Irrigation Strategy](https://support.athenaag.com/hc/en-us/articles/25975395644315-Precision-Irrigation-Strategy) and our [references and attribution notes](docs/REFERENCES.md).

This is an independent project, with no implied Athena endorsement. Project examples and software behaviour are identified separately from Athena's published guidance.
