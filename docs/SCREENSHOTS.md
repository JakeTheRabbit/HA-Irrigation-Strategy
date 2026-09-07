# Current workspace screenshots

[Open the interactive demo](https://jaketherabbit.github.io/HA-Irrigation-Strategy/dashboard.html?demo=1).

Captured on 8 September 2026 from the compiled application with isolated demo data and inherited Home Assistant dark-theme variables. These are current UI examples, not photographs or live facility readings.

## Room overview

![Room overview](../img/operator-dashboard.png)

## Combined VWC and EC planning curve

![Zone planning and steering controls](../img/grow-plan.png)

## Manual setpoints beside the planning curve

![Saved and draft targets with P3 emergency floor editing](../img/manual-setpoints.png)

## Recorded run comparisons

![Compare VWC and EC over the same grow age](../img/run-comparison.png)

## Rooms and sensor mapping

![Room setup](../img/rooms-setup.png)

## Mobile overview

![Mobile room overview](../img/mobile-overview.png)

Reproduce these captures with `node frontend/scripts/verify-workspace.mjs` and `node frontend/scripts/verify-steering-visuals.mjs` after building the frontend. Historical screenshots live in archive/2026-09-08/img.
