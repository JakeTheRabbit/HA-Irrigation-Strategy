# Current workspace screenshots

[Open the interactive demo](https://jaketherabbit.github.io/HA-Irrigation-Strategy/dashboard.html?demo=1).

Captured on 18 October 2026 from `www/dashboard.html?demo=1`, with isolated sample data, a fixed 15:50 local clock and the light theme. These are current UI examples, not photographs or live facility readings.

## Overview: all zones

![All rooms and zones grouped by room](../img/all-zones.png)

## Overview: selected room

![Overview](../img/operator-dashboard.png)

## Tank and pump

![Graphical tank level, pump/fill reports and water-quality readings](../img/tank-status.png)

## Tank EC and pH history

![The tank's EC and pH over 24 hours, 7 days or 30 days, with the feed-water limits](../img/tank-history.png)

## Tank level and watering

![The tank's level over 24 hours with each zone's shots, the pump's runs, the tank filling and each recorded fill](../img/tank-level.png)

## Water use per zone

![Today, this week, this grow and an estimate for the whole grow, with litres per grow week](../img/water-use.png)

## Stock tanks

![Nutrient stock tanks with their levels, low marks and batches left](../img/stock-tanks.png)

## Irrigation: Calendar and combined VWC/EC curve

![Zone planning and steering controls](../img/grow-plan.png)

## Irrigation: Current day, recorded evidence and projected day

![Targets, recorded VWC/EC and the projected P0-P3 day on one graph](../img/plan-graph.png)

## History: recorded sensor explorer

![History explorer with recorded VWC and pore EC, range selection and previous-run overlays](../img/sensor-history.png)

## Irrigation: Current day beside the plan graph

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

Reproduce every published screenshot with `node frontend/scripts/capture-readme.mjs` after building the frontend. The script reads only the checked-out compiled demo, blocks external and Home Assistant API requests, and fails on browser runtime errors. It writes all 26 screenshots to `img/` and records their route, selector, viewport and source SHA-256 in [the screenshot manifest](../img/screenshots.json). The logo is a brand asset and is not a dashboard capture.

The stable filenames are shared by README, this gallery and the website. Copy the images from this publication set when refreshing the website. Never use screenshots from `output/ha-ui-deploy`, real Home Assistant sessions or private facility data. Browser verification scripts also create test evidence and may overwrite individual images; run the publication capture last, after verification, to publish one consistent set.
