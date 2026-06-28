# Crop Steering for Home Assistant — System Guide

> **Nicely formatted version:** [`SYSTEM_GUIDE.html`](https://jaketherabbit.github.io/HA-Irrigation-Strategy/SYSTEM_GUIDE.html)
> (diagrams + flowcharts). This markdown is the same content for GitHub readers.

An autonomous **four-phase crop-steering irrigation** controller for Home Assistant. It runs the
daily **P0 → P1 → P2 → P3** cycle per zone from live VWC/EC probes, sequences your pump and valves
safely, and steers each zone vegetative or generative. Self-hosted, no subscription. **Irrigation
only — it does not control climate.**

---

## What it is — two layers

| Layer | What it does | Touches hardware? |
|---|---|---|
| **Integration** (`custom_components/crop_steering/`) | The data layer. A config-flow setup wizard, ~100 entities (number / switch / select / sensor), per-zone sensor fusion, and pure calculation helpers. | **No — ever** |
| **f2-control add-on** (`addons/f2_control/`) | The engine. A single synchronous Python process that polls HA over REST every 60 s, builds a snapshot, calls `decide()`, sequences the hardware, republishes status, and pings your phone. Gated by a hard kill switch. | **Yes — the only thing that opens a valve** |
| **crop-steering-engine** (`crop-steering-engine/`) | The pure `decide()` core the add-on imports — phase logic + EC steering + safety, with no HA and no I/O, unit-tested offline. | No |

The feedback loop is the whole point: **sensors → entities → engine decision → hardware → substrate
changes → sensors.** Every poll can trigger a re-evaluation, per zone, independently.

---

## The daily cycle

A "grow-day" is one photoperiod (lights-on → lights-on). Each zone walks four phases on its own clock,
driven by how far the **substrate** actually dried back — not the wall clock.

| Phase | What happens | Moves on when |
|---|---|---|
| **P0 · Morning dryback** | Hold all water. Record peak VWC and wait for a target % dryback — this sets up the day. | Dryback target hit, or max wait elapses → P1 |
| **P1 · Ramp-up** | Progressive shots, each larger, until VWC reaches the zone target. The morning rehydrate. | Target reached · max shots · timeout → P2 |
| **P2 · Maintenance** | Threshold top-ups whenever VWC dips below the EC-adjusted threshold. The EC ratio nudges the threshold. | ~3 h before lights-off (or lights-off) → P3 |
| **P3 · Overnight dryback** | Planned watering stops; dry back through the dark. Emergency-only if VWC hits the zone floor. | Lights-on → daily counters reset → P0 |

> **One rule worth knowing:** every "dryback" number is a *percentage-point drop from the peak* (how
> far it dries back **by**, never the value it dries back **to**), and the daily water/shot counters
> roll over at **lights-on**, not midnight.

The **size and aggressiveness of that curve is how you steer** — `Vegetative` keeps VWC high and EC
low; `Generative` allows deeper drybacks and higher EC. Set it per zone; a −100…+100 intent slider
interpolates the P0 dryback target between the two.

---

## The safety gate chain

Every shot, in any phase, clears this chain before a valve opens. Any failure blocks the shot and
logs the reason (and surfaces it on the dashboard):

1. **Kill switch ON** — `input_boolean.f2_control_enabled`; OFF blocks everything.
2. **System & zone enabled, override OFF** — master + auto-irrigation + this zone enabled, manual override off.
3. **Not dosing / fill / flush** — a tank job or manual flush/fill hands the pump to the operator.
4. **Source pH/EC in range** — feed within band; fail-closed if a configured feed probe is dead past its grace window.
5. **Daily volume cap OK** — under the per-zone daily budget; emergency rescue shots are exempt.
6. **Pore-EC under hard max** — or a *dilutive flush* (high EC flushes rather than locking out).

Field capacity is **not** a hard pre-shot gate — it's the ceiling the P1 ramp targets and a
precondition for EC flushes. A hard anti-drown ceiling (~90 % VWC) is what blocks a flood. The
hardware sequence itself is **fail-closed**: pump → mainline → zone valve with valve-close read-back;
a failed call aborts the shot, emergency-stops the pump, and is **not** counted.

---

## Full feature list

### Autonomous P0–P3 engine
- **Four-phase daily cycle, per zone** — independent P0→P1→P2→P3, timed to the substrate not the clock.
- **Dryback detection** — peak tracking + a dryback-rate slope drives the P0 wait and the predictive P3 start.
- **EC steering** — the live EC ÷ target ratio nudges the P2 VWC threshold to hit your EC, not just moisture.
- **Optional PID EC loop** — a real Kp/Ki/Kd controller (anti-windup, clamped) on pore-EC error, behind one switch.
- **Vegetative / Generative steering** — per zone, with a −100…+100 cultivator intent slider.
- **Live shot sizing from real hardware** — run-time computed from substrate volume × per-zone flow; published as `sensor.crop_steering_p1/p2/p3_shot_duration_seconds`.
- **Per-zone manual override** — take one zone out of the auto phase logic without touching the others.

### Sensors & fusion
- **Multi-probe sensor fusion** — the integration fuses each zone (average + outlier reject) to one `sensor.crop_steering_vwc_zone_N` / `ec_zone_N` the engine steers on; one flaky probe can't fire or block a shot.
- **Per-zone status** — Optimal · Dry · Saturated · Sensor Error · Disabled, plus all-zone averages.
- **EC ratio & adjusted-threshold sensors** — see *why* the engine is feeding when it is.
- **Water-usage tracking** — per-zone daily/weekly litres, shot count, global daily usage.

### Safety & anti-lockout
- **Hard kill switch** — OFF = read/decide/notify, never actuate; safe-offs all hardware on shutdown.
- **Source-water quality gate** — pH + EC band, grace window, fail-closed on a dead feed probe.
- **Fail-closed hardware sequencing** — valve-close read-back; a fault aborts + emergency-stops + isn't counted.
- **Anti-lockout high-EC flush** — high pore-EC flushes (if feed dilutive) rather than silently locking out.
- **Daily volume cap** — a budget, not a wall; emergency rescue exempt.
- **Max shot-duration cap** — default 900 s; a config fat-finger can't flood the room.
- **Anti-short-cycle interval** — EC-correction shots can't machine-gun the pump.
- **Minimum daily water floor** *(optional)* — guaranteed mL/plant/day, sensor-independent.
- **Lights-on watering watchdog** — forces a shot if an enabled zone gets no water for `watchdog_hours` (default 3) while dry.
- **Cross-zone under-drink flag** — a zone drinking < 40 % of the room median is alerted.
- **Blocked-dripper protection** — abandons repeated emergency shots at a blocked dripper, per zone.
- **Setup health checks** — misconfiguration surfaces as self-clearing fix-it cards in Settings → Repairs.

### Setup & configuration
- **No-YAML config-flow wizard** — entity-picker dropdowns; every field has a tooltip.
- **`crop_steering.env` auto-load** — zone-count auto-detect, missing-entity warnings.
- **1–24 zones.**
- **Global + per-zone tuning** — every P0–P3 setpoint, EC targets by phase/mode, field capacity, max EC, watchdog, substrate/dripper facts.
- **Crop type / growth stage / per-zone crop profile** — drives sensible default EC targets.
- **Reconfigure without reinstall** — Configure → Edit zones & hardware.
- **Configure once** — the add-on reads lights hours + zone count from the integration.
- **Transparent in-place upgrades** — state persists across restart/rebuild; old installs load with safe defaults.

### Multi-room
- **Fully isolated additional rooms** — add the integration again per room; entities namespaced `crop_steering_<room>_*`, own Repairs cards. *(Per-room dashboard scoping is on the roadmap.)*

### Dashboards & operator surface
- **Operator console in the sidebar** — served over HA ingress; tabs Overview · Substrate · Zones · Steering · Analyze · Climate · Floorplan.
- **Mobile vitals page**, **Live / Demo toggle**, **click-to-fix advisories** (the feed-lockout diagnostic names the exact gate), **30-min phone vitals + alerts**, and **service events for automation**.

---

## What it does *not* do

- **No climate control.** It is irrigation only — it reads climate sensors for context (the dashboard shows VPD/CO₂/DLI) but does not drive AC, dehumidifiers or lights.
- **No machine-learning / adaptive self-tuning.** No ML predictor, Kalman fusion, adaptive `Vmax` detection or crop-profile AI. An experimental "intelligence" layer that aimed at those was retired; the integration still exposes a few inert `*_intelligence_*` switches the live engine ignores. `sensor.crop_steering_ai_heartbeat` is a liveness ping, not a self-tuning brain.
- **No per-zone `?room=` dashboard scoping yet.** Rooms are isolated at the entity level; scoping a dashboard to a named room is on the roadmap.

---

## The dashboards

The add-on serves these over HA ingress as a sidebar panel (Live), and they also run standalone on
mock data (Demo). The `crop_steering_*` entities are generic; a new facility maps its own
sensors/valves — see [`docs/DASHBOARDS.md`](docs/DASHBOARDS.md) for the full gap analysis and the
populate-for-your-facility guide.

| Page | What it is | Mode |
|---|---|---|
| `f2.html` | Flagship operator console (Overview · Substrate · Zones · Steering · Analyze · Climate · Floorplan) | Live + Demo |
| `overview.html` | Mobile one-pager | Live + Demo |
| `crop_steering.html` | Earlier full console (superseded, still live) | Live + Demo |
| `crop_steering_tune.html` | Setpoint Tune editor | Live |
| `setpoints.html` | Grow recipe planner | localStorage |
| `system-map.html` | 3D system map (architecture) | Static |
| `floorplan/index.html` | 3D facility floor plan | Static |

---

*Engine logic is unit-tested in `crop-steering-engine/tests/`. Integration helpers in `tests/`.
MIT licensed.*
