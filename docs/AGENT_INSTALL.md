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
- **Engine** (`addons/f2_control/`) — the **f2-control add-on**: a single synchronous
  Python process that reads those entities + live sensors, runs P0→P1→P2→P3, and drives
  the hardware. (AppDaemon `appdaemon/apps/crop_steering/` is the **retired** rollback —
  do not install it.)

They talk only through HA entities. Install the integration first, then the add-on.

> 📖 **Visual walkthrough:** for a click-by-click guide with HA screenshots + numbered callouts,
> open **`docs/INSTALL_GUIDE.html`** (live:
> <https://jaketherabbit.github.io/HA-Irrigation-Strategy/install.html>). This file is the text
> reference / agent runbook.

> **Installing the add-on — two ways (see §5).** *Easiest:* the **dedicated add-on repo** —
> in HA, Add-on Store → ⋮ → Repositories → add `https://github.com/JakeTheRabbit/f2-control`
> → *F2 Control* appears in the store → Install. *Dev/offline:* copy the `addons/f2_control/`
> folder onto the HA host under `/addons/` (local add-on), then Reload the store.
>
> **Do NOT** add *this* monorepo's URL or a `.../addons/f2_control` subfolder in the Add-on
> Store — this repo is a code monorepo with the add-on nested in a subfolder, so HA can't read
> it (that's the `remote: Not Found / repository '…/addons/f2_control/' not found` error). The
> `f2-control` repo above exists precisely to give a clean one-click URL.

---

## 0 · Pre-flight — confirm the ground truth

Do not assume; verify each and report findings before proceeding.

1. **Home Assistant version ≥ 2024.3.0.** Check Settings → About, or the API:
   `GET /api/config` → `version`.
2. **Install method available.** Prefer HACS (Settings → Devices & Services → HACS).
   If absent, plan a manual copy into `/config/custom_components/`.
3. **Add-on support.** Supervised / HA-OS install (Settings → Add-ons exists). The
   f2-control add-on is a local add-on you copy onto the host in §5 — AppDaemon is **not**
   needed. (HA Core, with no Supervisor, can't run add-ons — run the engine another way.)
4. **Samba or SSH access to the HA host** (the *Samba share* or *Advanced SSH & Web
   Terminal* add-on), so you can copy files into `/addons/` and `/config/` in §5.
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

## 5 · Install the engine (the f2-control add-on)

The engine runs as a Home Assistant add-on. Install it one of two ways:

**5.1a — One-click by URL (easiest).** Add-on Store → ⋮ (top-right) → **Repositories** →
paste **`https://github.com/JakeTheRabbit/f2-control`** → **Add**. *F2 Control* now appears
in the store. (That dedicated repo has `repository.yaml` at its root + the add-on at the top
level, so HA can read it. Do **not** add this monorepo's URL — HA can't read the nested
`addons/f2_control`.)

**5.1b — Local copy (dev / offline).** Put the repo's `addons/f2_control/` folder onto the
HA host so the path is **`/addons/f2_control/`** (it must contain `config.yaml`, `Dockerfile`,
`run.sh`, and the `f2_control/` Python package). *Samba:* the `addons` share maps to `/addons`.
*SSH/Terminal:* `cp -r /path/to/repo/addons/f2_control /addons/`. Then Add-on Store → ⋮ →
**Reload** — it shows under **Local add-ons**.

**5.2 — Install it.** Open **F2 Control** in the store (URL method: it's listed directly;
local-copy method: under **Local add-ons** after the Reload) → **Install** (the first build
takes a minute).

**5.3 — Configure it.** On the add-on's **Configuration** tab set:
- `lights_on_hour` / `lights_off_hour`, `notify_service` (e.g. `notify/mobile_app_xxx`).
- If your feed probes differ from the defaults, the feed EC/pH sensor entity ids.
- `substrate_l` / `flow_lps` are fallbacks only — the live shot size is read from the
  integration's per-zone `substrate_volume`, `plant_count`, `drippers_per_plant`,
  `dripper_flow_rate` number entities (set those from the operator's real hardware;
  wrong values make every shot the wrong length).

**5.4 — Token + kill switch.** The add-on has `homeassistant_api: true`, so it gets its
HA token automatically — no long-lived token to manage. Create the kill switch
`input_boolean.f2_control_enabled` (a Helper, or deploy
`addons/f2_control/f2_control_package.yaml` to `/config/packages` + reload). **OFF = safe**
— the add-on reads, computes and notifies but never opens a valve.

**5.5 — Start it.** **Start** the add-on; the log shows `starting | kill-switch … | token
present: True`. Leave the kill switch OFF until §7.

> **Updating the add-on later — Rebuild, NOT Restart.** The Dockerfile bakes the Python
> into the image at build (`COPY f2_control /app`). After changing any file under
> `addons/f2_control/`, copy it to `/addons/f2_control/` again and use the add-on's
> **⋮ → Rebuild** — a plain **Restart re-runs the old baked code** (it only re-reads the
> Configuration options). Rebuild re-copies the code and restarts.

---

## 6 · Verify the engine is alive

The engine publishes its own heartbeat sensors. Check (via API or Developer Tools → States):

- The **f2-control add-on log** shows `starting | kill-switch … | token present: True`,
  then per-tick decision lines — no tracebacks.
- `sensor.crop_steering_ai_heartbeat` — `healthy`, with attribute **`engine: f2-control`**
  and a `last_beat` that updates every loop (< ~4 min old).
- `sensor.crop_steering_app_status` — a real state (e.g. `safe_idle` / `irrigating`), not `unknown`.
- `sensor.crop_steering_activity_log` — a recent human-readable event line.
- Per-zone `sensor.crop_steering_zone_1_vwc` reads a live number (fusion is running).

If those are populated, both layers are connected and the engine is reading the room.

---

## 7 · 🚦 GATE — arm it safely (operator go required)

Everything to here is read/observe-only. Arming makes it actuate. Do this **with the
operator**, not autonomously:

1. **Observe before firing.** Keep the kill switch `input_boolean.f2_control_enabled`
   **OFF**. In this state the add-on still reads sensors, runs the full decision every
   loop, republishes the `crop_steering_*` status, and logs exactly what it *would* fire —
   but never opens a valve. Watch a full photoperiod: confirm the phases march P0→P1→P2→P3,
   the per-zone reasons make sense, and the feed gate holds when the tank is filling/dosing.
2. **Sanity-check shot sizing first — the #1 footgun.** Verify each zone's shot length is
   sane *before* arming. Live shot duration =
   `shot% × (substrate_volume × plant_count) ÷ (plant_count × drippers_per_plant × dripper_flow_rate ÷ 3600)`.
   Enter `substrate_volume` as the **PER-PLANT block size**; the engine scales it to the
   row. A 6 % shot of a 6 L block at 4 L/h ≈ 5–6 min. If your shots are seconds long, the
   substrate/flow config is wrong and it will short-cycle.
3. **Tune targets to *observed* VWC peaks/troughs** (see the README "Implementation"
   section). A target the substrate can't reach makes a zone chase its tail.
4. **Arm it — 🚦 GATE.** Only after 1–3 check out, flip `input_boolean.f2_control_enabled`
   **ON**. The add-on now actuates. Watch the first real cycle live: a fired shot raises VWC,
   the hardware sequence (pump → mainline → valve → shutdown, valve-close read-back) runs
   clean, nothing over-waters. **One-line rollback: flip the kill switch OFF.**

---

## Done-when checklist

- [ ] Integration entities present (`number.crop_steering_p1_target_vwc` reads a value).
- [ ] `.env` reflects the operator-confirmed hardware map + physical truths.
- [ ] f2-control add-on installed (local add-on), configured, started; log clean.
- [ ] Engine connected: `ai_heartbeat` shows `engine: f2-control` + a fresh `last_beat`;
      `app_status` live; per-zone VWC reads.
- [ ] Shot sizing sane: `substrate_volume` (per-plant), `plant_count`, dripper flow set —
      a 6 % shot computes to minutes, not seconds.
- [ ] Kill switch `input_boolean.f2_control_enabled` armed **ON** only on explicit operator
      go; first real cycle watched (VWC rises, hardware sequence + valve read-back clean).

Reference: `docs/installation_guide.md` (long-form), `docs/SYSTEM_OVERVIEW.md` (mental
model), `ENTITIES.md` (entity reference), `docs/troubleshooting.md` (when something's off).
