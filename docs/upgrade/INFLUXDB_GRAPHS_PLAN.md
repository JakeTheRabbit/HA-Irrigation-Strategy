# InfluxDB-backed graphs — upgrade plan

> **Status:** plan — not implemented. Targets the existing
> `agency-sensor-analytics-card.js` Lovelace card (~1,280 lines) at
> `/config/custom_components/agency_sensor_analytics/www/`.

The card you already use across `dashboards/legacyag/*.yaml` and the
existing `sensor-analytics` dashboard is good — synced hover/zoom/pan,
threshold-aware overview tiles, dual-panel layout, configurable
timeframes. The only problem at scale: it pulls from
`/api/history/period/<start_iso>?filter_entity_id=...` which queries
HA's recorder. For default SQLite recorder, queries over 7+ days slow
down sharply once the database hits a few GB.

This document plans switching the data fetch path to query InfluxDB
directly while keeping every existing dashboard YAML unchanged.

## Why not just use Grafana?

You can — Grafana iframe panels are the de-facto answer for InfluxDB
data in HA. But:

- iframes break the synced-hover-across-cards UX you already have.
- Grafana's auth model (separate user, separate session) is annoying.
- You'd need to maintain two dashboard surfaces (HA + Grafana) and
  keep them in sync as you add sensors.
- The existing card already has the look you want.

So the plan is to keep the card, just change where it fetches data.

## What changes (one function in the card)

Looking at `agency-sensor-analytics-card.js`, line 583:

```js
const response = await this._callApi(path);
```

with `path` built at line 613:

```js
return `history/period/${encodeURIComponent(...)}?${params.toString()}`;
```

and `_callApi` at line 616:

```js
async _callApi(path) {
  if (typeof this._hass?.callApi === "function") {
    return this._hass.callApi("GET", path);
  }
  ...
}
```

Two new code paths:

1. **`_callInfluxApi(entities, range)`** — issues a Flux query over
   the InfluxDB v2 API. Returns the same shape `parseHistoryResponse`
   already accepts.
2. A small data-source switch up top:

```js
this._dataSource = config.data_source || "ha_history";
// "ha_history" (default) | "influxdb"
```

Per-card config gains optional InfluxDB parameters:

```yaml
type: custom:agency-sensor-analytics-card
data_source: influxdb
influxdb:
  url: !secret influxdb_url
  org: legacy_ag
  bucket: home_assistant
  token: !secret influxdb_token
  measurement_map:                    # optional — defaults work for HA's standard measurement names
    sensor.gw_room_1_temp: "°C"
    sensor.gw_room_1_rh: "%"
```

## Flux query template

For each requested entity over a given range:

```flux
from(bucket: "home_assistant")
  |> range(start: <iso>, stop: <iso>)
  |> filter(fn: (r) => r._measurement == "<unit_or_class>"
                       and r.entity_id == "<entity_id>")
  |> filter(fn: (r) => r._field == "value")
  |> aggregateWindow(every: <bucket_size>, fn: mean, createEmpty: false)
  |> yield(name: "mean")
```

The `<bucket_size>` is computed client-side from the requested range
to keep the response under ~2,000 points per entity (matches the
card's existing `MAX_POINTS` cap):

| Range | Bucket |
|---|---|
| ≤ 1 h | 30 s |
| ≤ 6 h | 2 m |
| ≤ 24 h | 5 m |
| ≤ 7 d | 30 m |
| ≤ 30 d | 2 h |
| > 30 d | 6 h |

Server-side downsampling means a 90-day query returns 360 points per
entity, ~36 KB per series — feels instant.

## How HA's InfluxDB integration writes data

HA's official InfluxDB integration writes one measurement per
`unit_of_measurement` (or `device_class` if no unit), with the
entity_id as a tag and the value as a `value` field. So the Flux
query above works against vanilla HA→InfluxDB exports without any
custom continuous-query setup.

For sensors without units (binary sensors, selects), HA writes
`measurement = "state"` with the state string in field `state`. The
card's binary-state series (e.g. `binary_sensor.gw_lights_on`,
`binary_sensor.crop_steering_anomaly_active`) need a small
field-name translation in the Flux template.

## Auth & secrets

InfluxDB v2 uses long-lived API tokens. Store in `secrets.yaml`:

```yaml
influxdb_url: "http://192.168.50.10:8086"
influxdb_token: "your-read-only-token"
```

The card reads them via standard HA `!secret` resolution — no extra
plumbing.

For network safety: create a **read-only** token scoped to the
`home_assistant` bucket. The card never writes.

## Migration path (existing dashboards keep working)

The data-source switch is per-card. So:

1. Ship the card update with `data_source` defaulting to `ha_history`
   (current behaviour).
2. Pick one dashboard to migrate (the long-window views like
   "RootSense per-zone — last 7 d" and the run-report dashboard
   benefit most). Add `data_source: influxdb` to those cards.
3. Compare side-by-side for a week.
4. Once happy, flip `data_source: influxdb` everywhere — or change
   the default at the top of the card.

No dashboard YAML rewrites needed unless you want to take advantage
of InfluxDB-only features (e.g. `aggregateWindow` with custom
functions, multi-bucket queries).

## Effort estimate

- Read-only InfluxDB query implementation in the card: ~200 lines of
  JS, half a focused day.
- Field-name translation for non-numeric sensors: another ~50 lines.
- Smoke test against 30-day windows on real F1 data: half a day.
- Documentation update for `dashboards/legacyag/README.md`: trivial.

**Total: ~1.5 focused days.**

## Out of scope for this plan

- **Writing** to InfluxDB from the card (it stays read-only).
- Replacing HA's recorder with InfluxDB (not necessary; HA's
  InfluxDB integration is a write-mirror, the recorder still serves
  things like `last-changed`, history entity attribute panels, etc.).
- Grafana iframe alternatives (intentional — see Why-Not-Grafana
  above).
- Cross-bucket queries (multi-room federation) — that's a v3.1
  problem.

## When to actually do this

Useful triggers:
- HA UI feels sluggish loading 7+ day views.
- You want to keep more than ~30 days of history (recorder is
  configured for 10-30 days typically).
- You want to share the card outside the F1 install (other tenants
  point at their own InfluxDB).

Until any of those bite, the existing HA-history fetch is fine.
