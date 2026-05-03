# Control Theory — design rationale

> **What this is:** the *why* behind the architecture in
> `intelligence/climate/`. Companion to `SEQUENCE_OF_OPERATIONS.md`
> (the *what*) and to the running code (the *how*).

## The problem in one sentence

Maintain plant-relevant environmental setpoints across a multi-month
indoor cannabis grow, using consumer-grade Home Assistant + AppDaemon
plus mid-tier commercial actuators (mini-split AC, parallel
dehumidifiers, ultrasonic humidifier, CO₂ solenoid, sealed room with
emergency exhaust), safely and repeatably.

## The four sub-problems hiding in that sentence

| Sub-problem | What it really is | Where it's solved |
|---|---|---|
| Setpoint authority | Recipe → day/night → intent slider precedence | `timeline.py` + `leaf_vpd.solve_target_rh()` |
| Actuator dispatch | Given a target, what physical device should do what | `control/<actuator>.py` |
| Conflict resolution | Two actuators want opposite things | `control/coordinator.py` |
| Failure handling | Sensor flatlines, actuator runs without convergence, comms loss | `control/watchdog.py` + Tier 1 hardwired |

The architecture treats each as an independent layer.

## Layered architecture (commercial BMS pattern)

```
TIER 1  HARDWIRED SAFETY            (physical relays, outside HA)
TIER 2  REAL-TIME CONTROL           (per-actuator, 30 s tick)
TIER 3  SUPERVISORY                 (recipe, coordinator, 1 min tick)
TIER 4  WATCHDOG                    (safety overrides, every tick)
TIER 5  OBSERVABILITY               (SQLite store + bus + dashboards)
```

Direct lift from how Johnson Controls, Siemens, Argus, and Aroya
build their controllers. Same layering; just smaller.

## Why bang-bang with hysteresis, not PID

For binary or quasi-binary actuators (relays, compressor cycling,
solenoids):

- **PID requires tuned gains.** Gains depend on room thermal mass +
  actuator capacity + ambient temperature, all of which vary.
  Mistuned PID either oscillates or under-shoots.
- **PID needs a continuous control variable.** Compressors are not
  continuous — they're either pumping refrigerant or they aren't.
  PID gives you a fractional duty-cycle output that you'd then have
  to PWM the relay against, which wears the contacts.
- **Bang-bang with hysteresis** has no integral term to wind up, no
  derivative to noise-amplify, no gains to tune. The hysteresis
  band IS the deadband — operator can read it directly off the
  config.
- **Industry agrees.** Argus Controls, TrolMaster, Aroya, and every
  rooftop HVAC unit ever built uses bang-bang for compressor staging.
  PID lives where it should: continuous variable-speed actuators
  (VFD fans, modulating valves, dimmable lights).

We use PID nowhere in this codebase. If F1 ever adds a variable-speed
exhaust fan or a modulating CO₂ valve, that's the right place to
introduce a small PI loop.

## Why leaf VPD as the supervisory variable

Plants regulate stomatal opening on the vapor-pressure deficit at
the leaf surface. Under good transpiration the leaf sits 1-3 °C
below air temp, so leaf VPD is meaningfully lower than air VPD.
Operators who chase air RH (or air VPD) are chasing a proxy.

Mathematically:

```
SVP(T)        = 0.6108 · exp(17.27·T / (T + 237.3))     [kPa, Tetens]
AVP_air       = SVP(T_air) · (RH/100)
leaf_VPD      = SVP(T_leaf) − AVP_air
```

Inverted to solve for required RH at given target leaf VPD:

```
target_RH = (SVP(T_leaf) − target_leaf_VPD) / SVP(T_air) · 100
```

The recipe declares `leaf_vpd_kpa` per phase. The control layer
solves for required RH each tick (cheap — pure math). The dehu and
humid loops chase that derived value, not the recipe's
`day_rh_pct`. The latter is fallback-only for installs without a
leaf-temp sensor.

If the math demands physically unattainable RH (< 30 % or > 90 %),
we clip and raise `climate_unattainable_rh_target`. That's a recipe
inconsistency, not a control failure.

## Why hardware calibration is first-class

Real example from F1: command `climate.gw_ac_1` to 27 °C, room
settles at 29 °C. Causes:

- AC unit's internal sensor sits at return-air, ~1-2 °C below canopy.
- Lights add ~3-5 °C of radiant load the unit's sensor doesn't see.
- The unit's internal deadband is ~1 °C.

Software fix: `cool_offset_c: -2.0`. The control loop calls
`HVACCalibration.commanded_setpoint(target=27, current=29)` which
returns 25. Per-direction (cool vs heat) because units typically
overshoot one direction more than the other.

This is the *only* per-installation tuning needed. The control law
is generic; the offsets capture every site-specific quirk.

## Why staged dehumidification with lead-lag rotation

F1 has 2 dehus on independent contactor pairs. Best practice for
parallel actuators:

1. **Trim and respond:** start small, escalate on persistent demand.
   Don't fire both units the moment RH crosses target+5 %. That
   over-dries on transient spikes (operator opens door for 30 sec).
2. **Demand persistence:** lead unit doesn't fire until RH has been
   high for 3 min. Lag doesn't fire until RH stayed high another
   5 min after lead engaged.
3. **Reverse staging on release:** lag turns off first, lead second.
   Keeps the same unit doing the "trim" work while RH settles.
4. **Lead-lag rotation:** swap which unit is "lead" every 7 days.
   Evens compressor wear across both units. Industry-standard for
   parallel pumps, parallel chillers, parallel air-handlers.

Hardware contactors enforce a 2-min cooldown between off→on of the
same dehu (compressor protection). Software does not duplicate this
— rely on the hardware. Software DOES enforce a min `demand_persistence`
to prevent acting on transient sensor spikes.

## Why AC↔dehu coordination matters

AC and dehu both cool air and condense water out as a side-effect.
Run them at full simultaneously and you over-cool. Coordinator rule:

> If AC is actively cooling AND room temp is also high, the AC is
> already removing water. Defer staging the LAG dehu — re-evaluate
> next tick.

Lead dehu is allowed to engage; we just don't pile on. Within a
couple of ticks the room cools (AC + lead dehu doing their jobs),
temp falls into the deadband, and the AC↔dehu coordination rule
no longer suppresses anything.

## Why the watchdog is its own tier

If watchdog logic lived inside the per-actuator controllers, a bug
in one controller could prevent its own runaway protection from
firing. The watchdog is a separate function called from the
coordinator, not from the actuators. Its actions are dispatched
ahead of any normal-control proposals, regardless of severity.

A real watchdog test case (from the test suite): a dehu unit with
`is_on=True` and `last_on_at` 90 minutes ago. Even if the per-actuator
controller for whatever reason still wants it on, the watchdog emits
a `SWITCH_OFF` action with severity=safety, and the coordinator
issues that to hardware before any normal proposal.

## Why coordinator over master controller

A master controller (one big function that knows about every
actuator) is simpler to write but very hard to test. Each per-actuator
function in this codebase is a pure(-ish) function:

```python
def propose_dehu(*, current_rh, target_rh, cal, state, now) -> list[Action]
```

You can drive it with synthetic state and assert on the returned
actions, without HA, AppDaemon, or any I/O. The unit test suite
runs in 0.4 s for 123 cases.

The coordinator is also pure: takes proposals and constraints,
returns final ordered actions. Testable.

The AppDaemon adapter (`control/app.py`) is the only impure layer —
it reads HA state, dispatches service calls, mutates state on
successful dispatch. Keep it thin.

## Why "every action carries a reason"

The `Action` dataclass requires a human-readable `reason` string.
Every dispatch logs it:

```
DISPATCH [normal] hvac_setpoint on climate.gw_ac_1 — target=27.0°C current=29.1°C → commanded=25.0°C (offset applied)
```

This is the audit trail. Six months from now when you ask "why did
the AC change setpoint at 14:32 yesterday", grep for the timestamp
and see exactly what triggered it. Industrial controllers all have
this; consumer HA does not by default.

## What this design will NOT do

- **PID anywhere.** See "Why bang-bang" above.
- **Predict beyond the next tick.** No model-predictive control,
  no thermal-mass forecasting, no transpiration prediction in the
  control loop. Each tick: read sensors, compute action, dispatch.
  Predictive logic (pre-cool before lights-on, etc.) is supervisory-
  layer concern, not controller-layer.
- **Adjust calibration offsets automatically.** Tempting but risky.
  Auto-calibration of `cool_offset_c` based on observed convergence
  is a v3.x future feature. Today, operator sets it; controller
  uses it.
- **Replace HA's automations or the GW pack wholesale.** ClimateSense
  is opt-in pillar by pillar. Until each switch is flipped ON, the
  legacy GW pack drives the room. This means there's a transition
  period where both could fire — manage it by enabling pillars one
  at a time and disabling the corresponding GW automations as you
  go (out of scope for the controller; operator runbook).

## What you can change without touching this file

| Change | Where | Tests required |
|---|---|---|
| Recipe phase targets | `config/recipes/<name>.yaml` | None |
| HVAC calibration offsets | `hardware_f1.yaml` → `hvac.primary` | None |
| Dehu rotation period | `hardware_f1.yaml` → `dehumidifier.rotation_period_days` | None |
| Watchdog runtime caps | `hardware_f1.yaml` → `safety.actuator_max_runtime_min` | None |
| RH on/off thresholds | per-actuator `propose_*()` defaults | Yes — update test_control_loops.py |

If you change the *structure* of any of those — new fields in YAML,
new state-machine logic, new conflict-resolution rules — update this
file and SEQUENCE_OF_OPERATIONS.md as part of the same commit.
