# F1 Sequence of Operations

> **What this is:** the operator-readable contract that says exactly
> what each actuator does, when, and why. Borrowed from commercial
> HVAC practice (every BMS install has one). Code is the
> implementation; this is the spec.
>
> **If you find code disagreeing with this doc, the doc wins until
> reviewed and updated.**

## 0. Authority hierarchy

Higher levels always win:

```
1. HARDWIRED SAFETY            (physical relays, not software)
2. WATCHDOG                    (Tier 4 — runs every tick, can override anything)
3. OPERATOR MAINTENANCE MODE   (input_boolean.gw_maintenance_mode = ON → no automation)
4. ACTIVE ANOMALY (critical)   (climate_emergency_temp, climate_emergency_co2)
5. RECIPE TARGETS              (timeline pillar)
6. INTENT SLIDER               (cultivator bias on top of recipe)
7. DEFAULTS                    (const.py / hardware_f1.yaml)
```

## 1. Sensors

| Quantity | Source | Stale threshold |
|---|---|---|
| Air temp | `sensor.gw_room_1_temp` | 90 s |
| Air RH | `sensor.gw_room_1_rh` | 90 s |
| Air VPD | `sensor.gw_room_1_vpd` | (display only) |
| CO₂ | `sensor.gw_room_1_co2` | 90 s |
| Leaf temp (IR) | `sensor.gw_room_1_leaf_temp` | 90 s — when present, leaf VPD is the supervisory variable |
| Lights | `binary_sensor.gw_lights_on` | — |
| Leak | `binary_sensor.gw_leak` | — |
| Tank low | `binary_sensor.gw_tank_low` | — |

If any of {temp, RH, CO₂} is stale > 90 s, the watchdog raises
`climate_sensor_stale:<label>`. The control loop refuses to act on
the affected metric until a fresh reading arrives.

## 2. Supervisory variable: LEAF VPD

Plants regulate stomata on leaf-VPD, not air-VPD. With a leaf-temp
sensor present:

1. Recipe declares `leaf_vpd_kpa` per phase (e.g. mid-flower 1.20 kPa).
2. The control layer reads current leaf temp + air temp + air RH.
3. `solve_target_rh(target_leaf_vpd, leaf_temp, air_temp)` returns the
   air RH that — given current temperatures — produces the target
   leaf VPD.
4. The dehu/humid controllers chase the **derived** RH, not the
   recipe's `day_rh_pct` (which is a fallback for leafless installs).

If the math demands an unattainable RH (< 30 % or > 90 %), the
controller chases the clipped value AND raises
`climate_unattainable_rh_target`. Operator either (a) widens the
tolerance, or (b) addresses the leaf-air ΔT (transpiration too low /
leaves too cool relative to air).

## 3. HVAC — 2× 9 kW IR-controlled mini-split

Treated as one logical entity (`climate.gw_ac_1` controls both via
IR blaster).

```
TICK = 30 s
COOL when:  current_temp > target + 0.5 °C
HEAT when:  current_temp < target - 0.5 °C
HOLD  when: |current - target| ≤ 0.5 °C  (deadband)

COMMANDED setpoint = target + offset(direction)
  cool_offset_c = -2.0   (compensates for +2 °C bias)
  heat_offset_c =  0.0

SETTLE WINDOW: do not issue a new setpoint within 8 min of the last
MODE COOLDOWN: do not flip cool↔heat within 30 min of last flip
IR REFRESH:   re-issue last-known-good setpoint every 30 min (insurance against lost IR)
RANGE CLIP:   commanded clipped to [16 °C, 30 °C]
```

## 4. Dehumidifier — 2 units (wet-tip contactors, 2-min HW cooldown)

Each unit = 2 relays (run + fan). Lead-lag staged.

```
TICK = 30 s
LEAD on  when: RH > target + 5 % sustained for ≥ 3 min
LAG on   when: RH still > target + 5 % a further 5 min after lead engaged
LAG off  when: RH < target − 2 %
LEAD off when: lag is off AND RH < target − 2 %

ROTATION: lead/lag swap every 7 days (wear leveling)
HW COOLDOWN: 2 min, enforced by contactor (not by software)
WATCHDOG: any unit on > 120 min continuous → force off + raise climate_actuator_runaway
```

## 5. Humidifier — 1 ultrasonic

```
TICK = 30 s
ON  when: RH < target − 5 % sustained, AND humidifier off > 60 s
OFF when: RH > target + 2 %
MUTEX: dehu and humidifier never both on. Coordinator drops humid_on
       if dehu_on is also proposed.
```

## 6. CO₂ — pulse-injection solenoid

```
TICK = 30 s
ENABLE PRECONDITIONS (all required):
  - lights on
  - lights have been on for ≥ 30 min  (stomata)
  - room temp 22-30 °C                 (CO₂ efficacy zone)
  - input_boolean.gw_co2_enabled = ON

PULSE CYCLE (when enabled):
  injection: 60 s ON
  rest:      pulse_off_s (adaptive, 120-600 s, default 240 s)
    - if last rest period saw ΔCO₂ > 100 ppm → extend rest by 20 %
    - if last rest period saw ΔCO₂ < 30 ppm  → shorten rest by 20 %
    - clamped to [120 s, 600 s]
  off when: CO₂ ≥ target − 50 ppm

HARD SAFETY (always):
  - CO₂ > 1800 ppm → solenoid emergency-close, severity=emergency
  - lights off     → solenoid forced closed
  - watchdog       → solenoid on > 30 min → force off + climate_actuator_runaway
```

## 7. Exhaust — emergency / scheduled refresh only

Room is sealed by default. Exhaust runs only for:

```
EMERGENCY:
  - room temp > 32 °C → exhaust ON, severity=emergency, plus alert
  - room CO₂ > 1800 ppm → exhaust ON, severity=emergency, plus alert
  - exhaust runs until temp < 31 °C AND CO₂ < 1700 ppm

SCHEDULED (optional, off by default):
  - if scheduled_enabled and lights on
  - run for scheduled_duration_min (default 5 min)
  - period = scheduled_period_min  (default 240 min = every 4 h)

WATCHDOG: exhaust on > 30 min → force off + raise climate_actuator_runaway
```

## 8. Lights

Driven by recipe phase `photoperiod_hours` and operator-set
`lights_on_hour` (default 08:00). Lights state is the binary sensor
`binary_sensor.gw_lights_on` — the control layer treats it as truth.

Optional sunrise/sunset PPFD ramp via `dimmer_entity` over
`ramp_minutes` (default 30).

## 9. Cross-actuator rules (Coordinator, Tier 3)

In order of evaluation:

1. **Tier-4 watchdog** actions ALWAYS emit (override everything).
2. **Maintenance mode** (`gw_maintenance_mode = ON`) → only watchdog
   actions emit; everything else is suppressed.
3. **Active critical anomaly** (`climate_emergency_temp` or
   `climate_emergency_co2`) → only safety/emergency-severity actions
   emit; normal control suppressed.
4. **Dehu ↔ Humid mutex** — both proposed ON → drop humid_on.
5. **AC ↔ Dehu cooperation** — if AC is actively cooling AND room
   temp is above target, defer staging the LAG dehu (AC is already
   condensing water out via cooling).
6. **Order of dispatch**: HVAC mode → HVAC setpoint → exhaust → dehu
   → humid → CO₂.

## 10. Failure modes & operator responses

| Anomaly | Auto response | Operator action |
|---|---|---|
| `climate_emergency_temp` (> 32 °C) | Exhaust ON, all heaters off | Check AC, doors, lights |
| `climate_emergency_co2` (> 1800 ppm) | Solenoid hard-close, exhaust ON | Check regulator, ventilate |
| `climate_temp_excursion` (> ±1 °C, 5 min) | Continue normal control + log | Check HVAC, calibration |
| `climate_rh_excursion` (> ±5 %, 5 min) | Continue normal control + log | Check dehu/humid, sensor |
| `climate_vpd_divergence` | Log only (recipe inconsistency) | Adjust recipe target |
| `climate_unattainable_rh_target` | Chase clipped value, log | Widen tolerance or address leaf-air ΔT |
| `climate_sensor_stale` | Halt loop for affected metric | Check sensor connection |
| `climate_actuator_runaway` | Force off the offending actuator | Inspect for stuck relay / sensor |

## 11. Loss-of-comms safe state

If AppDaemon dies or HA restarts:

- **HVAC**: holds last commanded setpoint (better_thermostat default).
- **Dehumidifiers**: hold current state. Watchdogs DO NOT run if
  AppDaemon is down — operator-tier responsibility. UPS recommended.
- **Humidifier**: holds current state.
- **CO₂**: holds current state. **THIS IS THE BIGGEST RISK.**
  Recommend a hardware timer in series with the solenoid that
  force-closes after N minutes regardless of software state.
- **Exhaust**: holds current state.
- **Lights**: holds current state (HA's automation handles photoperiod
  separately if configured at the HA layer; AppDaemon is only
  optional for advanced ramping).
- **Irrigation**: defaults closed (existing valve max-runtime
  watchdog at the GW pack layer in `50_alerts_watchdogs.yaml`).

## 12. What is hardwired vs software

| Concern | F1 today | Recommended addition |
|---|---|---|
| High-temp limit | Software watchdog (Tier 4) | Add a thermal cutoff aquastat in series with AC contactor |
| CO₂ ppm cap | Software watchdog | Add a hardware CO₂ alarm + emergency-shut solenoid in series |
| Water leak | `binary_sensor.gw_leak` → existing GW alert automation | Already adequate if leak detector is hardwired to a relay |
| UPS | (assumed) | Required for safe loss-of-comms behaviour |
| Smoke/fire | n/a | Out of scope for cultivation controls — house alarm system |

## 13. How to change something in this document

1. Edit this file.
2. Update the corresponding code under `appdaemon/apps/crop_steering/intelligence/climate/control/`.
3. Update or add a unit test in `tests/intelligence/test_control_loops.py` (or `test_leaf_vpd.py` for VPD math).
4. Run `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/intelligence/`.
5. Commit both this file and the code in the same change so the doc
   never drifts from implementation.
