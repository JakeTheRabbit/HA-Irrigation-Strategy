# Current workspace screenshots

[Open the interactive demo](https://jaketherabbit.github.io/HA-Irrigation-Strategy/dashboard.html?demo=1).

Captured on 25 September 2026 from the compiled application with isolated demo data and inherited Home Assistant dark-theme variables. These are current UI examples, not photographs or live facility readings.

## Overview

![Overview](../img/operator-dashboard.png)

## Tank and pump

![Graphical tank level, pump/fill reports and water-quality readings](../img/tank-status.png)

## Tank EC and pH history

![The tank's EC and pH over 24 hours, 7 days or 30 days, with the feed-water limits](../img/tank-history.png)

## Water use per zone

![Today, this week, this grow and an estimate for the whole grow, with litres per grow week](../img/water-use.png)

## Stock tanks

![Nutrient stock tanks with their levels, low marks and batches left](../img/stock-tanks.png)

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

Reproduce these captures by building the frontend and running the browser checks in `frontend/scripts/` (`verify-workspace.mjs`, `verify-steering-visuals.mjs`, `verify-dashboard.mjs`, `verify-tank-status.mjs` and `verify-recipe-library.mjs`); each writes its screenshots into `img/`.
