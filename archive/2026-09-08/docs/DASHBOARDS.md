# Dashboards — what's wired, what's not, and how to populate them

The repo ships a set of standalone HTML dashboards under `www/`. This is an honest map of **what each
one does, what's actually hooked up, what's hardcoded to the reference facility (F2), and exactly what
a new user must wire to light them up with their own data.**

> **TL;DR:** the **crop-steering core** of the dashboards (zones, phases, VWC/EC, setpoints, advisories)
> is **generic** — it reads `crop_steering_*` entities and works on any facility the moment the
> integration is configured. The **climate / camera / tank / source-water tiles** and the whole
> `home.html` facility console are **hardcoded to F2's entity IDs** and need remapping. See
> [Populate for your facility](#populate-for-your-facility).

---

## How the dashboards are served

Three ways, same files:

1. **HA add-on ingress (the normal way).** With the f2-control add-on installed, Home Assistant serves
   the dashboards behind its own authenticated reverse proxy and shows a **Crop Steering** entry in the
   sidebar. Nothing to copy, no token to paste, never exposed to your LAN. The add-on assembles
   `www/public/` from `www/` at build time.
2. **`/local/` path (manual copy).** Drop a file into `/config/www/` and open `/local/f2.html` while
   logged into HA. The page reads the short-lived token HA's frontend stores in your browser
   (`localStorage.hassTokens`); it falls back to a `CONFIG.LL_TOKEN` long-lived token only if you set
   one (keep that **blank in the repo** — a committed token on a public page is full HA control for any
   visitor).
3. **GitHub Pages (demo only).** Every page is published to `jaketherabbit.github.io/HA-Irrigation-Strategy/…`.
   On a `github.io` host (or with `?demo`) the page auto-enters **demo mode** — `seedDemo()` fills every
   value with baked-in "perfect grow" mock data and makes **no** network call. This is the showcase; it
   never talks to a real HA.

---

## Dashboard inventory & status

| Page | What it is | Status | Reads | Writes |
|---|---|---|---|---|
| `f2.html` | Flagship operator console — Overview · Substrate · Zones · Steering · Analyze · Climate · Floorplan | **Wired** (core) / **partial** (climate, tank, camera hardcoded to F2) | ~150 entities: generic `crop_steering_*` + F2-specific `f2_*`, `atlas_*`, `veg_main_pump`, SCD41, tank, camera | zone toggles, setpoint `number.*`, phase/kill switches |
| `overview.html` | Mobile one-pager — Steer / Controls / Dosing | **Wired** (zone count hardcoded to 3) | `crop_steering_zone_N_*`, global state | phase pin select, `zone_N_enabled` |
| `crop_steering.html` | Earlier full console (superseded by `f2.html`, still live) | **Wired** | `crop_steering_*` per-zone + global | per-zone switches, inline `number.*` edits |
| `crop_steering_tune.html` | Visual P0–P3 setpoint matrix editor | **Wired** (writes immediately, no undo; 3-zone layout) | `number.crop_steering_zone_N_*` | the same `number.*` via sliders |
| `setpoints.html` | Week-by-week grow recipe planner | **localStorage** (optional push-to-HA) | localStorage; optional `number.*` sync | optional `number.*` push |
| `system-map.html` | 3D architecture diagram (three.js) | **Static** (no live data) | — | — |
| `crop_steering_rules.html` | Rules-audit reference table | **Static** snapshot (live values if a token is pasted) | optional `crop_steering_*` | — |
| `irrigation-manual.html`, `install.html` | Written manuals | **Static** docs | — | — |
| `floorplan/index.html` | 3D facility floor plan (three.js, Vite bundle) | **Static** (needs `./assets/` built) | — | — |
| `home.html` | **F2 facility** command console (doors, power, cameras, alarms) | **F2-specific reference** — not a crop-steering dashboard | ~60 F2 entity IDs | facility switches/locks |
| `index.html` | Hub landing page linking all of the above | **Static** | — | — |

---

## Gap analysis — what works out of the box vs what needs wiring

**Works on any facility once the integration is set up (no dashboard editing):**

- Everything that reads `crop_steering_*`: per-zone VWC/EC/phase/status/dryback, the fused sensors,
  the setpoint editors, water-usage tiles, advisories, the feed-lockout diagnostic, the kill switch
  and zone toggles. The integration's setup wizard maps *your* sensors into the zones and publishes
  the generic `crop_steering_vwc_zone_N` / `ec_zone_N` the dashboards read — so the **Overview /
  Zones / Steering** tabs populate with real data immediately.

**Hardcoded to F2 — blank until you remap (in `f2.html`):**

- **Source-water tiles** — `sensor.atlas_legacy_1_ec`, `sensor.aquaponics_kit_f4f618_ph`.
- **Climate tab** — the SCD41 sensors `sensor.f2_scd41_env3_dlight_poe_*` (temp / RH / CO₂ / PPFD / DLI),
  `sensor.f2_target_rh_for_vpd`, and the back-left hotspot probe.
- **Hardware tiles** — `switch.veg_main_pump`, `sensor.veg_main_pump_power`,
  `switch.espoe_irrigation_relay_2_*`, `switch.f2_row1/2/3`.
- **Tank tiles** — `sensor.f2_tank_level`, `sensor.f2_tank_litres_remaining`,
  `sensor.200l_tank_space_remaining`, `sensor.tank_percentage_full`.
- **Camera** — `camera.flower2_cam_clear`.

**Other known limits:**

- **Zone count is hardcoded to 3** (`[1,2,3]`) in `f2.html`, `overview.html`, `crop_steering.html`,
  `crop_steering_tune.html`. A 2- or 6-zone facility needs those loops widened.
- **Setpoint edits write immediately** — no staging/undo. A slip is a manual correction.
- **No WebSocket** — pages poll REST every ~30 s, so live values lag up to 30 s.
- **`home.html` is an F2 facility console** (security, three-phase power via one specific Shelly EM3,
  doors, alarm `alarm_control_panel.alarmo`, cameras). Treat it as a *worked example* of a facility
  dashboard, not a generic one.
- **`floorplan/index.html`** needs its Vite `./assets/` bundle built/deployed or the 3D canvas is blank.

---

## Populate for your facility

### 1. Install both layers, configure the integration
Install the integration (HACS) and the add-on (Add-on Store), then run the integration's **setup
wizard** and map your real VWC/EC sensors and valves into each zone. This creates the generic
`crop_steering_*` entities the dashboards read. **At this point the Overview / Zones / Steering tabs
already show your real data** — no dashboard editing needed for the crop-steering core.

### 2. Open the dashboard from the add-on (Live)
Use the **Crop Steering** sidebar entry (add-on ingress). It authenticates with your HA login —
nothing to paste. The mobile app works too. (If you instead copy a file to `/config/www/`, open
`/local/f2.html`; for a LAN page outside HA, generate a long-lived token in
**Profile → Security** and set `CONFIG.LL_TOKEN` **at deploy time only** — never commit it.)

### 3. Remap the F2-hardcoded tiles (only if you want Climate / camera / tank / source-water)
These live in the `CONFIG` / entity map near the top of `f2.html`. Copy `www/f2.html`, search for each
F2 entity ID in the list above, and replace it with yours:

| Tile | Replace this | With your… |
|---|---|---|
| Source-water EC / pH | `sensor.atlas_legacy_1_ec` · `sensor.aquaponics_kit_f4f618_ph` | reservoir EC / pH probes (or set them in the add-on's `feed_ec_sensor` / `feed_ph_sensor` too) |
| Climate | `sensor.f2_scd41_env3_dlight_poe_*`, `sensor.f2_target_rh_for_vpd` | your temp / RH / CO₂ / PPFD / DLI sensors |
| Pump | `switch.veg_main_pump`, `sensor.veg_main_pump_power` | your pump switch + power sensor |
| Zone valves | `switch.f2_row1/2/3`, `switch.espoe_irrigation_relay_2_*` | your valve switches |
| Tank | `sensor.f2_tank_*`, `sensor.200l_tank_space_remaining` | your tank-level sensor(s) |
| Camera | `camera.flower2_cam_clear` | your camera entity |

If your zone count isn't 3, widen the `[1,2,3]` loops to your range. Test in HA-embed mode first
(`/local/f2_yours.html` while logged in) before relying on it.

### 4. Demo vs Live
`?demo` (or a `github.io` host) forces mock data. To run a **live** dashboard on a Pages-style host you
must remove the `github.io` hostname check in the page's `DEMO` detection and require an explicit
`?demo` flag — otherwise it will always show mock data.

### Deployment checklist
- [ ] Integration configured — zones mapped to your real VWC/EC sensors and valves
- [ ] Add-on installed, its `feed_ec_sensor` / `feed_ph_sensor` / lights / notify set in Configuration
- [ ] Kill switch `input_boolean.f2_control_enabled` exists (OFF while you test)
- [ ] Dashboard opened via the add-on sidebar (Live) — Overview/Zones/Steering show real data
- [ ] (Optional) F2-hardcoded climate/tank/camera tiles remapped in your copy of `f2.html`
- [ ] (Optional) zone-count loops widened if you don't run 3 zones
- [ ] No `CONFIG.LL_TOKEN` committed to any public copy
- [ ] Add-on **Rebuilt** (not just Restarted) after any code change
