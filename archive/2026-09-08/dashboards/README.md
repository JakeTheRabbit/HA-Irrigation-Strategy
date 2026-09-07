# Dashboards — read this before importing

These YAML dashboards (`crop_steering.yaml`, `crop_steering_console*.yaml`,
`irrigation.yaml`, `co2_environment.yaml`) are the **original F2 facility's** dashboards,
kept as a worked reference. **They are NOT portable** and will show "entity not found"
on a fresh install: they hardcode that facility's probe/hardware entity ids
(`sensor.substrate_*`, `sensor.environmentals_*`, `switch.f2_row*`, camera/weather
entities, etc.) that the integration does **not** create, and several are laid out for
exactly 3 zones.

## Get a portable dashboard instead

Use the generator — it reads YOUR Home Assistant, covers **every** `crop_steering`
entity for whatever zone count you configured (1–24), and contains no facility-specific
ids:

```bash
HA_TOKEN=<long-lived token> python scripts/build_lovelace.py
# per-room (multi-room installs):
HA_TOKEN=... CROP_STEERING_PREFIX=veg_ python scripts/build_lovelace.py
```

Paste the generated `crop_steering_lovelace.yaml` into **Settings → Dashboards → + Add
Dashboard → Edit raw configuration**. Some cards use the HACS **card-mod** frontend
resource — install it from HACS first if you copy the F2 files above.

The integration exposes these portable, per-zone entities the generator builds on:
`sensor.crop_steering_[<room>_]vwc_zone_N`, `..._ec_zone_N`, the `number.*` setpoints,
`switch.*` toggles and `select.*` modes.
