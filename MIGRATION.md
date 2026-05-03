# Migrating from v2.3.x to v3.0 ("RootSense")

This guide explains how to upgrade an existing v2.3.x install to RootSense
v3.0 with **zero breaking changes**. The new pillars are opt-in; you stay
on the same controller you have today until you explicitly enable them.

## What changes vs. v2.3.x

| Area | Behaviour after upgrade |
|---|---|
| Existing entities (`number.*`, `select.*`, `sensor.*`, `switch.*`) | All retained. |
| Existing services (`crop_steering.transition_phase`, `execute_irrigation_shot`, `set_manual_override`, `check_transition_conditions`) | Unchanged. |
| `master_crop_steering_app.py` | Untouched. Phase state machine, dryback detector, sensor fusion, hardware sequencing all still active. |
| Dashboards (`dashboards/crop_steering.yaml` etc.) | Continue to work as-is. |
| New entities | All created on integration reload but their producers (the AppDaemon pillars) are gated behind switches that default OFF. |

## Step-by-step

### 1. Pull v3.0

```bash
cd /c/Github/HA-Irrigation-Strategy
git pull origin main
```

### 2. Reload the integration

Settings → Devices & Services → Crop Steering → ⋮ → Reload.

The new entities appear in HA but produce no values yet — the AppDaemon
pillars are still disabled.

You should now see:

- `number.crop_steering_steering_intent` (default 0)
- `number.crop_steering_veg_p0_dryback_drop_pct` (default 12)
- `number.crop_steering_gen_p0_dryback_drop_pct` (default 22)
- `select.crop_steering_steering_mode_derived` (default Balanced)
- 5 × `switch.crop_steering_intelligence_*_enabled` (all OFF)

### 3. (Optional) Enable HA packages for the recorder includes

If your `configuration.yaml` doesn't already enable packages, add:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Then restart HA. This activates `packages/rootsense/00_recorder.yaml`
which keeps the new RootSense sensors in HA's history database.

### 4. Add the AppDaemon pillars to `apps.yaml`

Open `appdaemon/apps/apps.yaml` and append the blocks from
`docs/upgrade/apps.example.yaml`. Restart AppDaemon.

You can enable some pillars and not others — each block is independent.
A safe rollout order is:

1. **`rootsense_root_zone`** first (read-only — derives sensors from
   existing VWC/EC, cannot fire shots).
2. **`rootsense_anomaly`** next (also read-only — surfaces alerts via
   `binary_sensor.crop_steering_anomaly_active`).
3. **`rootsense_adaptive`** once you trust the intent slider's derived
   values for at least one full P0 → P3 cycle.
4. **`rootsense_agronomic`** (transpiration + nightly run report).
5. **`rootsense_orchestrator`** last — this one *can* call services that
   reach hardware via `crop_steering.execute_irrigation_shot`.

### 5. Toggle pillar switches in the UI

For each pillar you've added to `apps.yaml`, switch the corresponding
`switch.crop_steering_intelligence_*_enabled` to ON. The pillar starts
publishing values within one tick (60 s for root zone, 30 s for
orchestrator emergency check, 5 min for agronomic transpiration).

### 6. (Optional) Load the new dashboard

`dashboards/rootsense_history.yaml` is a three-tab Lovelace dashboard
(Intent / Substrate / Anomalies) that uses HA's built-in `history-graph`
card. You can either:

- Add a new dashboard pointing at this file, or
- Cherry-pick views into your existing `crop_steering.yaml`.

## Cultivator-intent slider — what changes

The single most operator-facing change. Previously you switched between
two `select.crop_steering_steering_mode` options ("Vegetative" /
"Generative"). Now there's a `number.crop_steering_steering_intent`
slider:

- **+100** — pure vegetative bias (high VWC target, more shots, low EC).
- **0** — balanced midpoint (default).
- **-100** — pure generative bias (large dryback, fewer big shots, high EC).

The IntentResolver reads this every tick and re-publishes:

- `number.crop_steering_p1_target_vwc`
- `number.crop_steering_p2_vwc_threshold`
- `number.crop_steering_p0_dryback_drop_percent` (interpolated from your
  veg/gen sliders)
- `number.crop_steering_p1_initial_shot_size`
- `number.crop_steering_ec_target_flush`

Your veg/gen endpoint values now live in two operator-facing sliders:

- `number.crop_steering_veg_p0_dryback_drop_pct`
- `number.crop_steering_gen_p0_dryback_drop_pct`

Both are *"% drop from peak VWC"* — i.e. how much the substrate dries
back **by**, never what VWC it dries back **to**.

## Rollback

Disabling all `switch.crop_steering_intelligence_*_enabled` switches
immediately stops the new pillars from publishing or acting. Removing
the AppDaemon `apps.yaml` blocks and restarting AppDaemon takes the
modules offline entirely. The integration's new entities can be
disabled individually in the entity registry if you prefer them
hidden.

`git checkout v2.3.1` returns the entire codebase to pre-RootSense.

## Troubleshooting

**Q: I enabled `rootsense_root_zone` but `sensor.crop_steering_zone_1_field_capacity_observed` says "unknown".**

Field capacity needs at least 2 saturation events to publish the
first value. If your zones aren't currently being saturated (e.g. you
configured P1 conservatively), the sensor stays unknown. Trigger a
manual `crop_steering.execute_irrigation_shot` to seed it.

**Q: Why is my P0 phase exiting much earlier than before?**

If you previously had `number.crop_steering_veg_dryback_target` set
to 50, that legacy default was too aggressive under the
"% drop from peak" semantic. The v3.0 default is 12. Your existing
saved value is preserved, but if the entity is at the new default,
P0 will exit after a 12 % drop instead of 50 %.

**Q: The orchestrator isn't suppressing zones during anomalies.**

Confirm both `switch.crop_steering_intelligence_orchestrator_enabled`
and `switch.crop_steering_intelligence_anomaly_enabled` are ON. The
orchestrator only listens to anomaly events; the scanner has to be
running to emit them.

## Versioning

`SOFTWARE_VERSION` in `custom_components/crop_steering/const.py` will
bump from `2.3.1` → `3.0.0` when Phase 5 closes (final release of
RootSense). Until then it stays at `2.3.1` and the v3 work is treated
as `[Unreleased]` in `CHANGELOG.md`.
