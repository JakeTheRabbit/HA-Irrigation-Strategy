# Agent install runbook

A precise, ordered runbook for an AI agent (Claude Code or similar, with shell +
file access to the Home Assistant config) to install and set up this crop-steering
system end to end. A human can follow it too.

> **Safety contract — read first.** This system drives pumps and valves on a live
> grow. The agent may install software, create entities, and write config freely.
> It must **never** open a valve, run the pump, or arm autonomous irrigation without
> the operator's explicit, per-action go. Every step that can move water is marked
> **🚦 GATE** — stop and get a yes before doing it. When unsure, surface the decision;
> do not guess.

The system has **two layers**:
- **Integration** (`custom_components/crop_steering/`) — creates the entities + setup
  wizard. Touches no hardware.
- **Engine** (`appdaemon/apps/crop_steering/`) — the AppDaemon app that reads those
  entities + live sensors, runs P0→P1→P2→P3, and drives hardware.

They talk only through HA entities. Install the integration first, then the engine.

---

## 0 · Pre-flight — confirm the ground truth

Do not assume; verify each and report findings before proceeding.

1. **Home Assistant version ≥ 2024.3.0.** Check Settings → About, or the API:
   `GET /api/config` → `version`.
2. **Install method available.** Prefer HACS (Settings → Devices & Services → HACS).
   If absent, plan a manual copy into `/config/custom_components/`.
3. **AppDaemon 4 add-on.** Settings → Add-ons. If not installed, it will be installed
   in step 4. (Supervised/HA-OS only — Core installs run AppDaemon separately.)
4. **The hardware exists in HA as entities.** This is the critical pre-req. The engine
   needs, at minimum, per zone: a valve `switch.*`, a VWC `sensor.*`, an EC `sensor.*`;
   and shared: a pump `switch.*` and a mainline `switch.*`. Enumerate what's there:
   - List candidate switches: `GET /api/states` → filter `entity_id` starting `switch.`
     and matching pump/valve/zone/row/relay names.
   - List candidate moisture/EC sensors: filter `sensor.*` with `vwc`/`moisture`/`ec`/
     `pwec`/`sdi12` in the id, and check `attributes.unit_of_measurement` (`%`, `mS/cm`).
   - **Build a hardware map** and show it to the operator for confirmation. Do not invent
     entity ids — if a zone's probe isn't found, say so.

Output of this step: a confirmed table of `{role → entity_id}` for pump, mainline, and
each zone's valve + VWC + EC. Everything downstream depends on it being correct.

---

## 1 · Install the integration

**HACS path:** HACS → Integrations → ⋮ → Custom repositories → add
`https://github.com/JakeTheRabbit/HA-Irrigation-Strategy` as category *Integration* →
install **"Crop Steering System"** → restart HA.

**Manual path:** copy `custom_components/crop_steering/` into `/config/custom_components/`
→ restart HA.

Verify the restart completed (`GET /api/` returns 200) before continuing.

---

## 2 · Write the `.env` (the room description)

The integration is configured from a single file, `/config/crop_steering.env`.

1. Start from a template in `templates/` (`crop_steering.2zone.env`,
   `…4zone.env`, `…6zone.env`) closest to the zone count.
2. Fill it from the **confirmed hardware map** in step 0 — zone count, the pump,
   mainline, each zone's valve switch, and each zone's VWC/EC sensor entity ids.
   Keys and their meanings are documented in `ENV_CONFIGURATION_GUIDE.md`; the parser
   is `custom_components/crop_steering/env_parser.py` (it auto-detects the zone count
   from the per-zone keys).
3. Set the physical truths that convert "shot size %" into valve seconds:
   `substrate_volume` (L), `dripper_flow_rate` (L/h), `drippers_per_plant`. Wrong
   values here make every shot the wrong size — get them from the operator, don't guess.

Write the file, then echo it back (mask any tokens) for operator confirmation.

---

## 3 · Run the config flow

Settings → Devices & Services → **Add Integration** → **Crop Steering System**.

- Choose **"Load from crop_steering.env file"** (the recommended path; manual UI entry
  is the fallback if no `.env`).
- If it reports missing entities, the `.env` references ids that don't exist — go back
  to step 0/2 and fix the mapping rather than ticking "ignore missing".

---

## 4 · Verify the integration (no hardware moved yet)

Confirm the entities exist and are sane:

- `GET /api/states/number.crop_steering_p1_target_vwc` → a numeric state with unit `%`.
- Count the `crop_steering_*` entities (expect ~32 global numbers + ~32 per zone, plus
  switches/selects/sensors — a 3-zone install lands around ~195 entities).
- Naming patterns to expect: global `*.crop_steering_<param>`, per-zone
  `*.crop_steering_zone_<N>_<param>`. Categories: P0–P3 phase params, per-phase EC
  targets (`ec_target_{veg,gen}_p0..p3`, `ec_target_flush`), dryback targets, safety
  guardrails (`maximum_ec`, `irrigation_ph/ec_min/max`), zone setup.

If these are present, the data layer is good. **No hardware has moved.**

---

## 5 · Install the engine (AppDaemon)

1. Install the **AppDaemon 4** add-on if absent. Its config dir on supervised HA is
   `/addon_configs/a0d7b954_appdaemon/` (slug `a0d7b954_appdaemon`).
2. Copy `appdaemon/apps/crop_steering/` → `…/a0d7b954_appdaemon/apps/crop_steering/`.
3. Copy `appdaemon/apps/apps.yaml` → `…/apps/apps.yaml` and **edit the `hardware:` and
   `sensors:` blocks** to the confirmed map from step 0 (pump, mainline, per-zone
   `zone_valves`, and the `vwc:` / `ec:` sensor lists in zone order). This file is where
   the engine learns the physical layout. `num_zones` must match.
4. Create a **long-lived token** (HA → Profile → Security → Long-Lived Access Tokens) and
   put it in `…/a0d7b954_appdaemon/secrets.yaml` as `ha_token:` (and `appdaemon_token:`
   if the `appdaemon.yaml` references it). **Never** write the token into any file under
   `/config/www/` or anything web-served, and never commit it.
5. Set `…/a0d7b954_appdaemon/appdaemon.yaml`: HA url `http://homeassistant:8123`,
   `token: !secret ha_token`, plus latitude/longitude/timezone.
6. Restart AppDaemon (the add-on watches files, but a clean restart is more predictable):
   `sudo docker restart addon_a0d7b954_appdaemon` if the `ha` CLI isn't authenticated in
   your shell.

---

## 6 · Verify the engine is alive

The engine publishes its own heartbeat sensors. Check (via API or Developer Tools → States):

- AppDaemon log shows `Master Crop Steering Application … initialized` and
  `Authenticated to Home Assistant`.
- `sensor.crop_steering_app_status` — a real state (e.g. `idle` / `irrigating`), not `unknown`.
- `sensor.crop_steering_ai_heartbeat` — `healthy`, updating.
- `sensor.crop_steering_activity_log` — a recent human-readable event line.
- Per-zone `sensor.crop_steering_zone_1_vwc` reads a live number (fusion is running).

If those are populated, both layers are connected and the engine is reading the room.

---

## 7 · 🚦 GATE — arm it safely (operator go required)

Everything to here is read/observe-only. Arming makes it actuate. Do this **with the
operator**, not autonomously:

1. **Observe before firing.** With `switch.crop_steering_system_enabled` ON but
   `switch.crop_steering_auto_irrigation_enabled` **OFF**, watch a full photoperiod: the
   activity feed + per-zone phase sensors show exactly what it *would* decide. Confirm the
   phases march P0→P1→P2→P3 and the reasons make sense.
2. **Bench-test one shot — 🚦 GATE.** Only on explicit go, fire a single small test shot
   via `crop_steering.custom_shot` (`target_zone`, small `volume_ml`, `intent:"test_emitter"`)
   and watch the sequence in the log: pump prime → mainline → zone valve → irrigate →
   shutdown (reverse), with the valve close read-back verified. Confirm the right valve moved.
3. **Tune the physical truths first**, then targets to *observed* VWC peaks/troughs (see the
   README "Implementation" section). A target the substrate can't reach makes a zone chase
   its tail.
4. **Enable autonomy — 🚦 GATE.** Only after 1–3 check out, turn on
   `switch.crop_steering_auto_irrigation_enabled`. Keep watching the first real cycles.

---

## Done-when checklist

- [ ] Integration entities present (`number.crop_steering_p1_target_vwc` reads a value).
- [ ] `.env` reflects the operator-confirmed hardware map + physical truths.
- [ ] Engine connected: `app_status` / `ai_heartbeat` / `activity_log` live; per-zone VWC reads.
- [ ] One supervised test shot fired the correct valve through the full safe sequence (gated).
- [ ] Autonomy enabled only on explicit operator go, first cycles observed.

Reference: `docs/installation_guide.md` (long-form), `docs/SYSTEM_OVERVIEW.md` (mental
model), `ENTITIES.md` (entity reference), `docs/troubleshooting.md` (when something's off).
