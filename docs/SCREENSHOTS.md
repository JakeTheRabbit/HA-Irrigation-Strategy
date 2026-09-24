# Current workspace screenshots

[Open the interactive demo](https://jaketherabbit.github.io/HA-Irrigation-Strategy/dashboard.html?demo=1).

Captured on 25 September 2026 from the compiled application with isolated demo data and inherited Home Assistant dark-theme variables. These are current UI examples, not photographs or live facility readings.

## Overview

![Overview](../img/operator-dashboard.png)

## Tank and pump

![Graphical tank level, pump/fill reports and water-quality readings](../img/tank-status.png)

## Irrigation plan: Schedule and combined VWC/EC curve

![Zone planning and steering controls](../img/grow-plan.png)

## Irrigation plan: Today, with the recorded zone and the projected day

![Targets, recorded VWC/EC and the projected P0-P3 day on one graph](../img/plan-graph.png)

## Recorded sensor history beside the setpoints

![24 h / 72 h / 7 d probe history with setpoint lines, peaks and troughs](../img/sensor-history.png)

## Irrigation plan: Today beside the plan graph

![Saved and draft targets with the review bar](../img/manual-setpoints.png)

## Room switched off

![Room off: readings shown, no irrigation and no alerts](../img/room-off.png)

## Recorded run comparisons

![Compare VWC and EC over the same grow age](../img/run-comparison.png)

## User-authored recipe library

![Save and reuse your own plans as local drafts](../img/recipe-library.png)

## Rooms and sensor mapping

![Room setup](../img/rooms-setup.png)

## Mobile overview

![Mobile room overview](../img/mobile-overview.png)

Reproduce these captures with `node frontend/scripts/verify-workspace.mjs` and `node frontend/scripts/verify-steering-visuals.mjs` after building the frontend. Historical screenshots are kept in the `archive/2026-09-08/released-workspace` tag, under archive/2026-09-08/img.
