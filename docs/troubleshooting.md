# 🔧 Troubleshooting Guide

Resolve common issues with the Crop Steering System. This is a **rule-based irrigation
controller** (not AI/ML), so troubleshooting focuses on sensor readings, hardware control,
the feed-water gate, and the two layers:

- **Integration** (`custom_components/crop_steering/`) — entities + config-flow wizard.
  Never touches hardware.
- **f2-control add-on** (`addons/f2_control/`) — the **live engine**. A single Python
  process that polls HA every 60 s, runs P0→P1→P2→P3, and drives the pump/valves. Gated by
  the kill switch `input_boolean.f2_control_enabled` (**OFF = safe**, reads/computes but never
  actuates).

> A public **[Troubleshooting wiki page](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/wiki/Troubleshooting)**
> also exists and may be more current. This file is the in-repo copy.

---

## 🚦 Read first — the F2-specific gotchas

These are the issues that actually bite on the live system. Start here.

### Add-on change "isn't taking effect" → **Rebuild, not Restart**

The add-on's `Dockerfile` bakes the Python into the image at build time
(`COPY f2_control /app`). A plain **Restart re-runs the old baked code** — it only re-reads
the Configuration options. After editing anything under `addons/f2_control/`:

1. Copy the changed files to `/addons/f2_control/` on the HA host.
2. Open the add-on → **⋮ → Rebuild** (re-COPYs the code, then restarts).

There is **no API rebuild** with a long-lived token (`hassio.addon_rebuild` 400s; the
Supervisor proxy 401s) — the operator must Rebuild in the UI. Never claim an engine code
change is live off a restart.

*Interim:* the running image still reads `substrate_l` / `flow_lps` from the **Configuration**
options, so editing those + Save corrects shot sizing without a rebuild.

### "Repository not found" when adding the add-on → use the **dedicated repo**

In the Add-on Store → ⋮ → **Repositories**, add:

```
https://github.com/JakeTheRabbit/f2-control
```

**Do NOT** add this monorepo's URL or a `.../addons/f2_control` subfolder — this repo nests
the add-on in a subfolder, so HA can't read it and you get
`remote: Not Found / repository '…/addons/f2_control/' not found`. The dedicated `f2-control`
repo has `repository.yaml` at its root precisely to give a clean one-click URL.

*(Dev/offline alternative: copy `addons/f2_control/` onto the host at `/addons/f2_control/`,
then Add-on Store → ⋮ → Reload — it appears under **Local add-ons**.)*

### Pump short-cycles (shots only seconds long) → **substrate volume units**

The recurring F2 failure. Live shot duration is:

```
dur = shot% × (substrate_volume × plant_count) ÷ (plant_count × drippers_per_plant × dripper_flow_rate ÷ 3600)
```

`number.crop_steering_zone_X_substrate_volume` must be the **PER-PLANT block size** — the
engine multiplies it by `plant_count` itself. Enter a zone-total volume by mistake and every
shot comes out `plant_count` times too short, so the pump short-cycles.

**Verify from the live pump, not from "deployed".** A file copy proves nothing about the
running container. Pull the pump's on-period from history and read the actual seconds:

```
GET /api/history/period/<start>?filter_entity_id=switch.veg_main_pump
```

F2 reference: 36 plants/zone, 6 L block/plant, 1 dripper @ 4 L/h → zone flow 0.04 L/s,
zone substrate 216 L, a 6 % shot ≈ **324 s** (~5–6 min). If your shots are seconds, the
substrate/flow config is wrong.

### Engine is "holding" / not watering → usually **expected**, check the reason

The engine deliberately holds for several reasons. The hold reason is published on each
zone's phase sensor:

```
# Developer Tools > States
sensor.crop_steering_zone_X_phase   → attribute "reason"  (why this zone is/ isn't firing)
sensor.crop_steering_app_status     → safe_idle | irrigating | error
```

Common **legitimate** holds (not bugs):

- **Feed gate out of band** — source-water EC/pH outside the operator bounds
  (`number.crop_steering_irrigation_ec_min/max`, `…_ph_min/max`). Reason reads e.g.
  `source-water EC 1.4 out of [2.3,3.5]` or `source-water pH 6.7 out of [5.8,6.2]`.
- **Probe dead (fail-closed)** — feed EC/pH probe stale beyond the grace window:
  `source-water EC dead >30min — holding (fail-closed)`. The engine won't feed blind.
- **Tank filling / dosing** — any of `input_boolean.nutrient_dosing_active`,
  `input_boolean.f2_fill_mode`, `input_boolean.f2_flush_mode`, `switch.tank_filling` is ON →
  reason `dosing/fill (...)`. Expected while the tank refills or doses.
- **Kill switch off** — `input_boolean.f2_control_enabled` OFF → `f2-control disabled
  (kill switch off)`. This is the safe default; flip ON only when armed (see AGENT_INSTALL §7).
- **System / auto / zone disabled, or manual override** — one of
  `switch.crop_steering_system_enabled`, `…_auto_irrigation_enabled`,
  `…_zone_X_enabled` is OFF, or `…_zone_X_manual_override` is ON.

If the reason is a feed gate or a fill/dose flag, that's the engine working correctly — fix
the feed or wait for the tank, don't "fix" the engine.

### Integration entities missing after an update

- Integration code change → Developer Tools → YAML → **Reload Custom Components** (or restart HA).
- If entities still don't appear, the integration failed to load: Settings → System → Logs,
  filter `crop_steering`. Entities are only created for **configured zones** — to add zones,
  reconfigure the integration (below).

---

## 🚨 Emergency Procedures

### System not irrigating during an emergency

**Symptoms:** VWC below the emergency floor (`number.crop_steering_p3_emergency_vwc_threshold`,
default ~35–40 %); no automatic response; plants stressed.

**Immediate actions:**
1. **Check the kill switch:** `input_boolean.f2_control_enabled` must be **ON** to actuate.
2. **Check enables:** `switch.crop_steering_system_enabled`, `…_auto_irrigation_enabled`,
   and `switch.crop_steering_zone_X_enabled` all ON; `…_zone_X_manual_override` OFF.
3. **Check the hold reason:** `sensor.crop_steering_zone_X_phase` → `reason` (often a feed
   gate or a fill/dose flag — see above).
4. **Manual shot** (bypasses the phase logic, still goes through the engine's safety gates):

```yaml
# Developer Tools > Actions (Services)
action: crop_steering.execute_irrigation_shot
data:
  zone: 1
  duration_seconds: 60
  shot_type: "P3_emergency"
```

### Runaway irrigation (won't stop)

**Symptoms:** irrigation running continuously; VWC above target ranges.

**Immediate actions:**
1. **Flip the kill switch OFF:** `input_boolean.f2_control_enabled` → OFF (one-line rollback;
   the add-on safe-offs the hardware).
2. **Turn off the system:** `switch.crop_steering_system_enabled` → OFF.
3. **Manually turn off** the pump (`switch.veg_main_pump`) and valves (`switch.f2_row1..3`).
4. **Inspect hardware:** a stuck relay/solenoid keeps water flowing even with HA commanding OFF.

---

## 🔍 System Diagnostic Checklist

### 1. Integration loaded
Settings → Devices & Services → **Crop Steering System** shows *Connected*. Click the device
to see its entities.

### 2. Key entities exist with fresh timestamps
Developer Tools → States, filter `crop_steering`:

```
sensor.crop_steering_app_current_phase     "Z1:P2, Z2:P1, ..." (per-zone phases)
sensor.crop_steering_configured_avg_vwc    reasonable %, e.g. 45–70
sensor.crop_steering_configured_avg_ec     mS/cm, e.g. 2.0–8.0
switch.crop_steering_system_enabled        on | off
```

### 3. Engine (add-on) is alive
The add-on republishes its own heartbeat — check these update every loop (~60 s):

```
sensor.crop_steering_ai_heartbeat   "healthy",  attribute engine: f2-control, fresh last_beat
sensor.crop_steering_app_status     "safe_idle" | "irrigating" | "error"  (not "unknown")
sensor.crop_steering_activity_log   recent human-readable event line
```

Also check the add-on log (Settings → Add-ons → **F2 Control** → Log): it shows
`starting | kill-switch … | token present: True`, then per-tick decision lines and no
tracebacks. If the heartbeat is stale or `app_status` is `unknown`, the add-on isn't running
or can't reach HA — restart the add-on and re-check the log.

### 4. Hardware test (commands move water — do this deliberately)
```yaml
# Developer Tools > Actions
action: switch.turn_on
target:
  entity_id: switch.veg_main_pump   # or switch.f2_row1, etc.
# confirm it physically actuates, then:
action: switch.turn_off
target:
  entity_id: switch.veg_main_pump
```

The add-on's default hardware map (overridable via its `hardware` Configuration option):
pump `switch.veg_main_pump`, mainline `switch.espoe_irrigation_relay_2_3`, valves
`switch.f2_row1` / `switch.f2_row2` / `switch.f2_row3`.

---

## 🌡️ Sensor Issues

### VWC sensor problems

**Reads "Unknown" / "None":**
- Confirm the source entity exists (Developer Tools → States) and the id matches the config.
- Check physical sensor power and connections.

**Erratic / impossible readings:**
- Check calibration (should read 0–100 %).
- Stabilise sensor placement in the substrate; look for electrical interference.

**Front/back sensors disagree:** the integration averages them into
`sensor.crop_steering_vwc_zone_X`. Individual probes should be reasonably close — a gap > ~15 %
points to calibration or placement, not the engine.

### EC sensor problems
- **Noise/fluctuation:** check grounding/isolation, steady solution flow past the probe,
  clean electrodes.
- **Drift:** calibrate monthly with standard solutions; replace aging probes (~2–3 yr).

---

## ⚙️ Configuration Issues

### Wrong entity names
**Symptoms:** integration errors, sensors read None.
**Fix:** Developer Tools → States to find the correct ids → Settings → Devices & Services →
**Crop Steering → Configure** (or fix `/config/crop_steering.env` and reload the config flow)
so the referenced entity ids match exactly.

### Missing zones
Entities are only created for configured zones. To add zones, reconfigure the integration and
increase the zone count, supplying that zone's valve + VWC + EC entity ids.

### Phase not changing
The engine drives phases automatically. If a zone is stuck:
- Confirm the kill switch is ON and the zone isn't in `manual_override`.
- Check `sensor.crop_steering_zone_X_phase` → `reason`.
- Check the light schedule used by the add-on (`lights_on_hour` / `lights_off_hour` in its
  Configuration) — P3→P0 happens at lights-on.
- To pin a phase by hand: `input_select.crop_steering_zone_X_phase_control` (Auto / P0–P3),
  or fire `crop_steering.transition_phase`.

---

## 🔌 Hardware Troubleshooting

### Pump
**Won't start:** check power (typically 24 VAC); test the pump entity manually; listen for the
relay click; check for binding/blockage.
**Runs but no flow:** check prime/pressure; air leaks; mainline (`switch.espoe_irrigation_relay_2_3`)
actually open; clear blockages.

### Valves
**Won't open:** check power; test the valve entity; listen for the solenoid click.
**Won't close:** the engine read-back-verifies valve close and **emergency-stops the pump** if a
valve fails to close — so a "won't close" fault shows up as an aborted shot in the log. Check for
debris in the seat, power-cycle the valve, inspect the return spring, replace the solenoid if
mechanically failed.

---

## 📡 Sensors Going Offline

**Symptoms:** entities show `unavailable` / `unknown`.
- Check WiFi/signal at the sensor; power stability; restart the sensor device.
- A dead **feed** EC/pH probe makes the engine hold fail-closed (see "Engine is holding" above) —
  that's by design, but fix the probe to resume feeding.

---

## 📊 Performance & Logic Tuning

### Watering too often (VWC stays high)
- Raise the P2 threshold: `number.crop_steering_p2_vwc_threshold`.
- Reduce shot sizes: `number.crop_steering_p1_initial_shot_size`, `…_p2_shot_size`.
- Increase time between P1 shots: `number.crop_steering_p1_time_between_shots`.

### Not watering enough (VWC drops too low)
- Lower the P2 threshold; increase shot sizes.
- Reduce the dryback target (a *% drop from peak*, not a target VWC):
  `number.crop_steering_veg_dryback_target`.

### Wrong phase behaviour
- **P0 (morning dryback):** `number.crop_steering_p0_dryback_drop_percent`, `p0_min_wait_time`,
  `p0_max_wait_time`.
- **P1 (ramp-up):** `p1_target_vwc`, `p1_initial_shot_size`, `p1_shot_increment`, `p1_max_shots`.
- **P2 (maintenance):** `p2_vwc_threshold`, `p2_ec_high_threshold`, `p2_ec_low_threshold`.

---

## 🛠️ Maintenance

- **Daily:** enables on, no error messages, sensor values sane, phases progressing, watering
  frequency appropriate.
- **Weekly:** cross-check sensors, tune parameters to plant response, visual hardware check.
- **Monthly:** recalibrate sensors, back up the config, check for integration updates, clean
  electrodes.

---

## 🆘 When to Get Help

**Self-service first:**
1. Check this guide and the [wiki](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/wiki).
2. Read the logs: Settings → System → Logs (`crop_steering`) **and** the F2 Control add-on log.
3. Test hardware manually; verify entity ids and the feed gate.

**Community:**
- GitHub Issues: https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/issues
- Home Assistant Forum / Discord (`#custom-components`).

**Include when asking:** the problem vs. expected; HA version; zone count + hardware;
the `reason` attribute from `sensor.crop_steering_zone_X_phase`; relevant log lines from both
the integration and the add-on.

---

## 📋 Quick Reference

### Manual controls
```yaml
# Manual irrigation shot (goes through the engine's safety gates)
action: crop_steering.execute_irrigation_shot
data:
  zone: 1
  duration_seconds: 60
  shot_type: "P2"

# Change phase manually
action: crop_steering.transition_phase
data:
  target_phase: "P2"

# Manual override a zone (engine leaves it alone while overridden)
action: crop_steering.set_manual_override
data:
  zone: 1
  enable: true
```

### Entities to monitor
```yaml
# Engine status (published by the add-on)
sensor.crop_steering_app_status            # safe_idle | irrigating | error
sensor.crop_steering_app_current_phase     # per-zone phases
sensor.crop_steering_ai_heartbeat          # healthy + engine: f2-control
sensor.crop_steering_activity_log          # rolling event feed

# Per-zone (replace X)
sensor.crop_steering_zone_X_phase          # phase + "reason" attribute (why it held/fired)
sensor.crop_steering_zone_X_status
sensor.crop_steering_vwc_zone_X            # fused VWC

# Enables / kill switch
input_boolean.f2_control_enabled           # KILL SWITCH (OFF = safe)
switch.crop_steering_system_enabled
switch.crop_steering_auto_irrigation_enabled
```

### Key parameters
```yaml
number.crop_steering_p1_target_vwc
number.crop_steering_p2_vwc_threshold
number.crop_steering_p1_initial_shot_size
number.crop_steering_p2_shot_size
number.crop_steering_p3_emergency_vwc_threshold
number.crop_steering_irrigation_ec_min      # feed gate
number.crop_steering_irrigation_ec_max
number.crop_steering_irrigation_ph_min
number.crop_steering_irrigation_ph_max
```

---

**Remember:** rule-based logic, two layers. Most issues are config, hardware, sensor, or the
feed gate doing its job. When the engine "won't water," read the zone's `reason` attribute
first — it usually tells you exactly why.
