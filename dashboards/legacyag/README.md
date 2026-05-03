# Legacy Ag F1 dashboard suite

Five linked Lovelace dashboards that cover the entire F1 grow room
(climate + substrate + intelligence + setpoints) using one consistent
visualisation style — the `custom:agency-sensor-analytics-card` you
already have installed at
`/config/custom_components/agency_sensor_analytics/www/agency-sensor-analytics-card.js`.

## Files

| File | Title | Purpose |
|---|---|---|
| `00_overview.yaml` | F1 Overview | Landing page — at-a-glance status of room climate, irrigation summary, RootSense health |
| `10_climate.yaml` | F1 Climate | Temp / RH / CO₂ / VPD time series + controls (dehumidifiers, humidifier, CO₂ solenoid) |
| `20_substrate.yaml` | F1 Substrate | Per-table VWC/EC time series + RootSense substrate intelligence sensors |
| `30_intelligence.yaml` | F1 Intelligence | RootSense pillar status, anomalies, intent slider, custom shots |
| `40_setpoints.yaml` | F1 Setpoints | All targets in one view — temp/RH/CO₂/VPD/VWC/EC bands with current vs target |

A shared "nav" markdown header at the top of every dashboard links to
all five so you can jump between them in one click.

## Installing

Add to your `configuration.yaml`:

```yaml
lovelace:
  mode: storage
  dashboards:
    f1-overview:
      mode: yaml
      title: F1 Overview
      icon: mdi:view-dashboard-variant
      show_in_sidebar: true
      filename: dashboards/legacyag/00_overview.yaml
    f1-climate:
      mode: yaml
      title: F1 Climate
      icon: mdi:thermometer
      show_in_sidebar: true
      filename: dashboards/legacyag/10_climate.yaml
    f1-substrate:
      mode: yaml
      title: F1 Substrate
      icon: mdi:water-percent
      show_in_sidebar: true
      filename: dashboards/legacyag/20_substrate.yaml
    f1-intelligence:
      mode: yaml
      title: F1 Intelligence
      icon: mdi:brain
      show_in_sidebar: true
      filename: dashboards/legacyag/30_intelligence.yaml
    f1-setpoints:
      mode: yaml
      title: F1 Setpoints
      icon: mdi:target
      show_in_sidebar: true
      filename: dashboards/legacyag/40_setpoints.yaml
```

Restart HA. Five new entries appear in your sidebar.

## Entity assumptions

The dashboards use the entity names from your live F1 config:

- **Climate**: `sensor.gw_room_1_temp`, `..._rh`, `..._co2`, `..._vpd`
- **Substrate**: `sensor.gw_table_1..6_vwc`, `..._ec`
- **Aggregates**: `sensor.gw_average_vwc`, `sensor.gw_average_ec`
- **Targets**: `input_number.gw_temp_target_day`, `..._temp_target_night`,
  `..._rh_target_day`, `..._rh_target_night`, `..._co2_*`
- **Switches**: `switch.gw_dehumidifier_relay_1..4`, `..._humidifier`,
  `..._co2`, `..._mainline`
- **Enables**: `input_boolean.gw_environment_enabled`, `..._co2_enabled`,
  `..._irrigation_enabled`, `..._maintenance_mode`
- **RootSense (this repo)**: `number.crop_steering_steering_intent`,
  `sensor.crop_steering_zone_*_field_capacity_observed`, etc.

If you ever rename any of these, search the dashboard YAML for the old
name and replace.

## InfluxDB upgrade path (future)

`agency-sensor-analytics-card.js` currently fetches via HA's history
API (`/api/history/period/...`). If you want graphs that hit InfluxDB
directly for fast queries over month+ windows, the swap is a single
fetch function in the card — see `docs/upgrade/INFLUXDB_GRAPHS_PLAN.md`
for the change.
