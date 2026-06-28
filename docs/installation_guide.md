# Installation Guide

Plain-English, start-to-finish setup for the Crop Steering System — written so you can follow it even if you are new to Home Assistant. Every step tells you exactly what to click **and why it matters**, so you are never guessing.

> **Prefer pictures?** There is a click-by-click visual version with Home Assistant screenshots and numbered callouts here:
> **https://jaketherabbit.github.io/HA-Irrigation-Strategy/install.html**
> This page is the full written reference; use whichever you like.

Set aside about **30–45 minutes**. Nothing you do touches your plants until the very last step, so you can work through it calmly.

---

## First, understand what you are installing (this makes every step obvious)

The system is **two separate pieces**. You install both, and they do very different jobs:

| Piece | What it is | What it does | Touches hardware? |
|---|---|---|---|
| **The integration** | `custom_components/crop_steering` — installed through HACS | The "brain's notepad". It creates ~100 Home Assistant entities (settings, sensors, switches) and a setup wizard. It does calculations only. | **No — never.** |
| **The f2-control add-on** | `addons/f2_control` — installed from the Add-on Store | The "engine". A small program that reads your sensors every 60 seconds, decides when to water, and actually drives the pump and valves. | **Yes — it is the only thing that opens a valve.** |

**Why two pieces?** Safety and clarity. The integration is completely safe to install and explore — it cannot move a drop of water. The engine that *can* move water is separate, and even after you install it, it stays locked behind a **kill switch** until you deliberately arm it. So you can build the whole thing, look around, and confirm everything is correct **before** anything ever turns on.

> **Upgrading from an older release?** Older releases shipped a different engine; this version uses the f2-control add-on — no action needed beyond installing the add-on (Step 4).

---

## What you need before you start

**Home Assistant:**
- A running Home Assistant on **HA OS** or **Supervised**.
  - **Why this matters:** the engine is an *add-on*, and add-ons only exist on HA OS / Supervised installs (they need the Supervisor). If you run HA in a plain Docker container or Core install, you can still use the integration for manual control, but you cannot install the add-on engine.
- **HACS** installed (the Home Assistant Community Store). If you do not have it: https://hacs.xyz/docs/setup/download
  - **Why:** HACS is the easiest way to install the integration and get update notifications.
- You should be comfortable doing three things: open **Settings**, **restart** Home Assistant, and look up a value in **Developer Tools → States**.

**Hardware (already added to Home Assistant as entities):**
- A **water pump** you can switch on/off (a `switch.` entity).
- A **main-line valve** (a `switch.`).
- One **zone valve** per growing area (a `switch.` each).
- Per zone, at least one **moisture (VWC) sensor** and one **nutrient (EC) sensor** (`sensor.` entities).
- Your **grow lights** (so the system knows day vs night).
  - **Why hardware first:** this system *steers* existing hardware. It does not talk to relays or probes directly — it talks to the Home Assistant entities you already have for them. If your pump isn't a working `switch.` in HA yet, set that up first.

---

## The steps at a glance

1. Install the integration (HACS).
2. Create your room's map — the `crop_steering.env` file.
3. Add the integration in Home Assistant (load your map).
4. Install the engine (the f2-control add-on).
5. Configure the add-on.
6. Create the kill switch.
7. Start the engine and verify — **nothing waters yet.**
8. Set your hardware numbers (so shot sizes are correct).
9. Arm it — go live.

Do them in order. Each one builds on the last.

---

## Step 1 — Install the integration (via HACS)

**Why:** this creates all the `crop_steering` entities — the settings and readouts the rest of the system depends on. On its own it touches no hardware.

1. Open **HACS** from the Home Assistant sidebar.
2. Click the three-dot menu **(⋮)** in the top-right → **Custom repositories**.
3. In the dialog:
   - **Repository:** `https://github.com/JakeTheRabbit/HA-Irrigation-Strategy`
   - **Type:** `Integration`
   - Click **Add**.
   - **Why this URL:** this is the main project repository, added as an *Integration* in HACS. (The add-on in Step 4 uses a *different* URL in a *different* place — don't mix them up.)
4. Close the dialog. Search HACS for **Crop Steering System** → open it → **Download**.
5. **Restart Home Assistant:** **Settings → System → Restart**. Wait 2–3 minutes.
   - **Why restart:** Home Assistant only loads new integration code on a restart.

**You are done with Step 1 when:** Home Assistant comes back up with no errors in **Settings → System → Logs**.

---

## Step 2 — Create your room's map (`crop_steering.env`)

**Why this is the important step:** this file is how the system learns *your* hardware — which switch is which valve, which sensor is in which zone. The setup wizard in Step 3 has a "Manual" option, but **the manual option only asks how many zones you have — it does not collect your entity names.** The `.env` file is the real way to map everything, and it is much faster than clicking through forms.

1. Grab a starter template that matches your zone count from the repo's **`templates/`** folder:
   - `templates/crop_steering.2zone.env`, `crop_steering.4zone.env`, or `crop_steering.6zone.env`.
   - (Or copy `crop_steering.env.example` and trim it.)
2. Save it on your Home Assistant as **`/config/crop_steering.env`**.
   - Use the **Samba**, **Studio Code Server**, or **File editor** add-on to put a file in `/config`.
3. Edit it so every line points at **your** real entity IDs. Look IDs up in **Developer Tools → States** if unsure. The keys you fill in:

   ```ini
   # --- per zone (repeat the block for each zone you have) ---
   ZONE_1_SWITCH=switch.your_zone_1_valve      # the valve for this zone
   ZONE_1_VWC_FRONT=sensor.your_vwc_1_front    # moisture sensor(s)
   ZONE_1_VWC_BACK=sensor.your_vwc_1_back      # optional 2nd VWC (leave blank if none)
   ZONE_1_EC_FRONT=sensor.your_ec_1_front      # nutrient (EC) sensor(s)
   ZONE_1_EC_BACK=sensor.your_ec_1_back        # optional 2nd EC
   ZONE_1_PLANT_COUNT=36                        # plants in this zone (used for water math)
   ZONE_1_MAX_DAILY_VOLUME=20.0                 # safety cap, litres/day for this zone

   # --- shared hardware ---
   PUMP_SWITCH=switch.your_water_pump           # turns on before any shot
   MAIN_LINE_SWITCH=switch.your_main_valve      # main line solenoid
   WASTE_SWITCH=                                # optional recirc/waste valve, blank if none

   # --- lights (so it knows day vs night) ---
   LIGHT_ENTITY=light.your_grow_lights
   LIGHTS_ON_TIME=10:00
   LIGHTS_OFF_TIME=22:00

   # --- optional room sensors ---
   TEMPERATURE_SENSOR=sensor.your_room_temp
   HUMIDITY_SENSOR=sensor.your_room_humidity
   ```

   - **Why each part:** the `ZONE_n_*` lines map each zone's valve and probes. `PLANT_COUNT` feeds the watering math (more plants = more water per shot). `MAX_DAILY_VOLUME` is a per-zone safety ceiling. `PUMP_SWITCH` / `MAIN_LINE_SWITCH` are the shared plumbing the engine sequences before each shot. The lights tell the system when the grow-day starts and ends.
   - A blank value (e.g. `ZONE_1_VWC_BACK=`) just means "I don't have that one" — perfectly fine.

**You are done with Step 2 when:** `/config/crop_steering.env` exists and every filled-in entity ID matches something real in **Developer Tools → States**.

---

## Step 3 — Add the integration in Home Assistant

**Why:** this reads your `.env` map and actually builds the per-zone entities for your specific setup.

1. Go to **Settings → Devices & Services**.
2. Click **+ Add Integration** (bottom-right) → search **Crop Steering** → select it.
3. When asked how to set up, choose **Load from crop_steering.env file**.
   - **Why this option:** it reads the map you just made and auto-detects however many zones your file defines (well past 6 if you need them). The other option, "Manual", only sets a zone count and leaves the hardware unmapped, so you'd end up with a half-configured system.
4. Submit. The integration creates all the `crop_steering_*` entities for your zones.

**You are done with Step 3 when:** **Settings → Devices & Services** shows a **Crop Steering System** device, and in **Developer Tools → States** a filter for `crop_steering` lists many entities (for example `sensor.crop_steering_current_phase`, `switch.crop_steering_zone_1_enabled`, `number.crop_steering_p1_target_vwc`).

> At this point the system is fully installed as a **monitor and manual-control** layer. It still cannot move water — there is no engine yet. That's next.

---

## Step 4 — Install the engine (the f2-control add-on)

**Why:** the integration never drives hardware. The f2-control add-on is the program that actually waters — it runs the daily P0→P1→P2→P3 cycle and sequences your pump and valves.

**The easy way — add it by URL:**

1. Go to **Settings → Add-ons → Add-on Store**.
2. Click the three-dot menu **(⋮)** top-right → **Repositories**.
3. Paste this URL and click **Add**, then close the dialog:
   ```
   https://github.com/JakeTheRabbit/f2-control
   ```
4. **F2 Control** now appears in the store. Open it → **Install** (the first build takes about a minute).

> **Use that exact URL.** It is the dedicated add-on repository. Do **not** paste the main project URL from Step 1, and do **not** paste a `.../addons/f2_control` sub-folder link. Home Assistant cannot read those and will say `remote: Not Found / repository '…/addons/f2_control/' not found`. The `f2-control` repository exists precisely to give you one clean, working URL.

**Alternative — local copy (only for offline or development):** download the project ZIP, copy the **`addons/f2_control/`** folder onto the host so the path is **`/addons/f2_control/`** (via Samba `\\YOUR_HA_IP\addons\`, or SSH `cp -r HA-Irrigation-Strategy/addons/f2_control /addons/`), then **Add-on Store → ⋮ → Reload** — it appears under **Local add-ons**.

**You are done with Step 4 when:** F2 Control shows **Installed** with **Configuration**, **Log**, and **Info** tabs.

---

## Step 5 — Configure the add-on

**Why:** the engine needs to know your light hours (to time the daily cycle) and where to send alerts. These live on the add-on's own **Configuration** tab.

1. Open **F2 Control → Configuration**.
2. Set:
   - **`lights_on_hour` / `lights_off_hour`** — the hour (0–23) your lights turn on and off (e.g. `10` and `22`).
     - **Why:** this is what the engine uses to decide when the grow-day starts (lights-on resets the daily counters) and when to wind down for the night. The engine reads these here, not from the integration.
   - **`notify_service`** — your phone's notify service, e.g. `notify/mobile_app_your_phone`.
     - **Why:** so it can text you vitals and alerts. Find yours in **Developer Tools → Actions** by typing `notify.`.
   - Leave the rest at their defaults unless you know you need to change them:
     - `enable_flag` (`input_boolean.f2_control_enabled`) — the kill switch you create in Step 6.
     - `substrate_l` / `flow_lps` — **fallback** sizing values only; the engine reads your real per-zone hardware numbers live (see Step 8), so these are rarely used.
     - `loop_seconds` (60), `notify_min` (30 minutes between routine vitals).
3. Click **Save**.

> There is **no token to paste.** The add-on gets its Home Assistant access automatically (`homeassistant_api: true`).

**You are done with Step 5 when:** Configuration is saved with your light hours and notify service.

---

## Step 6 — Create the kill switch

**Why:** this is your master safety switch. While it is **OFF**, the engine still reads sensors, makes decisions, and sends notifications — but it **never opens a valve**. This is what lets you start and watch the engine with zero risk before going live. **OFF = safe.**

Pick one method:

- **Easy (UI):** **Settings → Devices & Services → Helpers → + Create Helper → Toggle.** Name it so its entity ID becomes exactly **`input_boolean.f2_control_enabled`**.
- **Or (file):** copy **`addons/f2_control/f2_control_package.yaml`** into your `/config/packages/` folder, then **Developer Tools → YAML → Reload** (this also defines the same helper).

**Leave it OFF.**

**You are done with Step 6 when:** `input_boolean.f2_control_enabled` exists (check **Developer Tools → States**) and is **off**.

---

## Step 7 — Start the engine and verify (nothing waters yet)

**Why:** before trusting it with your plants, confirm the two layers are actually talking. With the kill switch OFF, this is completely safe — it's a dry run.

1. **F2 Control → Info → Start.**
2. Open the **Log** tab. You should see a line like:
   the startup lines include `kill-switch input_boolean.f2_control_enabled` and
   `token present: True`, then calm per-zone lines every minute.
   - **Why this proves it works:** "token present: True" means it can reach Home Assistant; the kill-switch line confirms it sees your safety switch; the per-zone lines mean it is reading sensors and deciding (but not acting, because the switch is OFF).
3. Confirm in **Developer Tools → States**:
   - `sensor.crop_steering_ai_heartbeat` has the attribute **`engine: f2-control`** and a fresh `last_beat`.
   - `sensor.crop_steering_app_status` shows a live state (e.g. `safe_idle`).

**You are done with Step 7 when:** the heartbeat shows `engine: f2-control` and updates, and the log is clean. Both layers are now connected.

---

## Step 8 — Set your hardware numbers (so shot sizes are correct)

**Why this matters a lot:** a "shot" is a percentage of your substrate volume, delivered at your drip rate. If the substrate and flow numbers don't match your real hardware, the engine calculates the **wrong duration** — and the classic failure is shots coming out far too short, so the pump rapid-cycles and moisture never rises.

Set these numbers (in **Developer Tools → States**, or on the dashboard) to your real hardware. Most are **system-wide** (one value for the whole system); only plant count is per zone:

- **`number.crop_steering_substrate_volume`** (system-wide) — the **per-plant** block/cube size in litres (for example a 6 L rockwool block = `6`). The engine multiplies this by each zone's plant count to get that zone's total, so enter the **per-plant** figure, not the whole-zone total.
- **`number.crop_steering_zone_N_plant_count`** (per zone) — plants in zone N (also set from your `.env`).
- **`number.crop_steering_drippers_per_plant`** (system-wide) — emitters per plant (often `1`).
- **`number.crop_steering_dripper_flow_rate`** (system-wide) — flow per dripper in litres/hour (e.g. a 4 L/hr Netafim = `4`).

**Worked example (so you can sanity-check yours):** 36 plants, a 6 L block each, one 4 L/hr dripper each →
zone substrate = 6 × 36 = **216 L**; zone flow = 36 × 1 × 4 ÷ 3600 = **0.04 L/s**; a 6% maintenance shot = 0.06 × 216 ÷ 0.04 = **about 324 seconds (~5.4 minutes)**.
If your computed shot is a few seconds instead of minutes, your substrate/flow numbers are wrong — fix them before arming.

For the full math, EC targets, and per-stage recipe values, see the **[Operation Guide](operation_guide.md)** and the project wiki's *Configuration & Recipes* page.

**You are done with Step 8 when:** a maintenance shot computes to a sensible duration (minutes, not seconds) for your layout.

---

## Step 9 — Arm it (go live)

**Why the caution:** this is the only step that can move water. Do it deliberately, and watch the first cycle.

1. **Watch one full photoperiod with the kill switch still OFF.** The engine logs what it *would* do. Confirm the decisions look sane (it transitions phases, and the shots it wants are sensible sizes).
   - **Why:** a free dress-rehearsal. If anything looks wrong, you fix it with zero risk.
2. When you're satisfied, turn **`input_boolean.f2_control_enabled` ON**.
3. **Watch the first real cycle.** You should see the pump prime, the main line and a zone valve open, a shot run, and **VWC rise** afterward.

> **Instant rollback:** if anything looks wrong at any time, flip **`input_boolean.f2_control_enabled` OFF**. The engine immediately stops opening valves. That one switch is your stop button, forever.

**You are done when:** a real shot has fired, moisture rose in response, and you're comfortable leaving it running.

---

## Updating the engine later — Rebuild, not Restart

When a new version ships (or you change any add-on file), use the add-on's **⋮ → Rebuild**, or click **Update** when Home Assistant offers it.

**Why:** the add-on bakes its Python code into its container image at **build** time (`Dockerfile COPY`). A plain **Restart re-runs the old baked code** and silently ignores your change. **Rebuild** re-copies the new code, then restarts. If you ever change a file and "nothing happened," this is almost always why.

---

## Troubleshooting quick fixes

**"I don't see Crop Steering when I click Add Integration."**
Restart Home Assistant and wait 2–3 minutes (new integrations only load on restart). Check **Settings → System → Logs** for errors.

**"Adding the add-on says repository not found."**
You pasted the wrong URL. In **Add-on Store → ⋮ → Repositories**, use exactly `https://github.com/JakeTheRabbit/f2-control` — not the main project URL and not a sub-folder.

**"The add-on won't start."**
Make sure the kill-switch helper `input_boolean.f2_control_enabled` exists (Step 6). Read the **Log** tab — a traceback usually names a missing entity ID; fix it in your `.env` and reload the integration.

**"I changed an add-on file but nothing changed."**
Use **⋮ → Rebuild**, not Restart (see above).

**"The pump fires constantly / shots are only a few seconds."**
Your substrate/flow numbers are off (Step 8). The most common mistake is entering `substrate_volume` as the whole-zone total instead of the **per-plant** block size. Confirm a real shot is minutes, not seconds.

**"It's not watering even though a zone is dry."**
This is often correct, not a bug: the engine holds while the feed water is out of range (pH/EC) or while the tank is filling/dosing. Check `sensor.crop_steering_zone_N_phase`'s reason attribute and your feed pH/EC. Full details in the **[Troubleshooting Guide](troubleshooting.md)**.

**"Some sensors show Unknown / None."**
Verify the entity IDs in your `.env` match real, working entities in **Developer Tools → States**.

---

## Manual installation (advanced — skip if you used HACS)

If you can't use HACS:

1. Download the project ZIP from https://github.com/JakeTheRabbit/HA-Irrigation-Strategy → **Code → Download ZIP**.
2. Copy **`custom_components/crop_steering`** to **`/config/custom_components/crop_steering/`** so it contains `__init__.py`, `manifest.json`, `config_flow.py`, and the platform files.
3. Restart Home Assistant, then continue from **Step 2** above.
4. Install the engine exactly as in **Step 4** (the local-copy alternative).

---

## Learn more

- **[Operation Guide](operation_guide.md)** — running it day to day: arming, the monitoring checklist, and tuning.
- **[Troubleshooting Guide](troubleshooting.md)** — when something is off.
- **Project wiki** — Installation, Configuration & Recipes, Safety, Phase Logic, and FAQ pages.

**That's it.** You installed the data layer, mapped your room, installed the engine, proved it works safely, and armed it with a one-flick stop switch. Welcome to autonomous crop steering.
