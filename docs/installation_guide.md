# 🚀 Installation Guide - Beginner Friendly

This step-by-step guide will walk you through installing the Crop Steering System, even if you're new to Home Assistant. We'll cover everything you need to know!

## 📋 What You'll Need Before Starting

### ✅ Required Items
**Home Assistant Setup:**
- Home Assistant installed and running (any installation method works)
- Access to Home Assistant web interface
- Basic familiarity with Home Assistant (know how to navigate to Settings)

**Physical Hardware:**
- At least 1 moisture sensor (VWC) per growing area
- At least 1 nutrient sensor (EC) per growing area  
- Water pump that can be controlled by Home Assistant
- Solenoid valve for main water line
- Individual zone valves (up to 6 zones supported)
- Grow lights controlled by Home Assistant

### 🔧 The engine — the f2-control add-on
The **f2-control add-on** (`addons/f2_control/`, installed in Step 5) is what makes it
autonomous — automatic phase transitions, sensor fusion, the safe hardware sequence, and
the 30-min vitals. *(AppDaemon is a retired rollback; you don't install it.)*

**Integration only:** entities + manual control + dashboards. **+ the f2-control add-on:**
full autonomous P0→P1→P2→P3 operation. Supervised / HA-OS only (add-ons need the Supervisor).

### 🏠 Home Assistant Knowledge Check
Before proceeding, make sure you can:
- Navigate to Settings → Devices & Services
- Restart Home Assistant when needed
- Find entities in Developer Tools → States

**New to Home Assistant?** Check out the [official documentation](https://www.home-assistant.io/getting-started/) first!

## 🎯 Installation Methods

**Choose Your Method:**

### Method 1: HACS Installation (Easiest - Recommended)
✅ **Best for beginners**  
✅ **Automatic updates**  
✅ **One-click installation**

### Step 1: Install HACS (If Not Already Installed)
**Already have HACS?** Skip to Step 2!

**Don't have HACS yet?**
1. Follow the official HACS installation guide: https://hacs.xyz/docs/setup/download
2. This usually involves downloading a script and running it
3. Restart Home Assistant
4. HACS will appear in your sidebar

### Step 2: Add Our Repository to HACS
1. **Open HACS** from your Home Assistant sidebar
2. **Click "Integrations"** tab at the top
3. **Click the three dots (⋮)** in the top right
4. **Select "Custom repositories"**
5. **Fill out the form:**
   - Repository URL: `https://github.com/JakeTheRabbit/HA-Irrigation-Strategy`
   - Category: Select `Integration`
6. **Click "ADD"**

✅ **Success Check:** You should see a confirmation that the repository was added

### Step 3: Download the Integration
1. **Stay in HACS → Integrations**
2. **Search for "Crop Steering"** in the search box
3. **Click on "Crop Steering System"** when it appears
4. **Click "DOWNLOAD"** (blue button)
5. **Wait for download** (you'll see a progress indicator)
6. **When complete, restart Home Assistant:**
   - Settings → System → Restart (red "Restart" button)
   - Wait 2-3 minutes for restart to complete

✅ **Success Check:** After restart, continue to Step 4

### Step 4: Add the Integration to Your System
1. **Navigate to Settings → Devices & Services**
2. **Click the blue "+ ADD INTEGRATION" button** (bottom right)
3. **Search for "Crop Steering"** and select it
4. **Choose your setup method** (pick what matches your situation):

   **🌟 Advanced Setup (Recommended for most users):**
   - Configure zones and sensors through easy forms
   - Best for complete systems with sensors
   
   **🔧 Basic Setup:**
   - Just creates switches for manual control
   - Good for testing or simple setups
   
   **📁 Load from file:**
   - Only if you have an existing crop_steering.env file
   - For users upgrading from older versions

**Follow the setup wizard** - it will ask you step-by-step for:
- Number of zones (1-6)
- Your pump and valve entities
- Your sensor entities (if any)

✅ **Success Check:** You should see "Crop Steering System" in your device list

### Step 5: Add Full Automation (Optional but Recommended)

**🤔 Do I need this step?**
- **Skip if:** You want manual control only
- **Do this if:** You want the system to run automatically

**What you get with automation:**
- ✅ Automatic phase transitions throughout the day (P0→P1→P2→P3)
- ✅ Smart decisions about when to water
- ✅ Professional monitoring dashboards
- ✅ Combines data from multiple sensors intelligently
- ✅ No daily maintenance required

> ⚠️ **The engine is the f2-control add-on — NOT AppDaemon** (AppDaemon is a retired rollback).

#### 5a: Add the add-on (pick one)
**Easiest — one-click by URL:** Settings → Add-ons → Add-on Store → ⋮ (top-right) →
**Repositories** → paste **`https://github.com/JakeTheRabbit/f2-control`** → **Add**. *F2 Control*
now appears in the store.
> Add that **dedicated add-on repo** URL — not this monorepo's URL or a `.../addons/f2_control`
> subfolder (HA can't read those; that's the `remote: Not Found` error).

**Or — local copy (dev/offline):** GitHub → **Code → Download ZIP** (or clone the repo), copy
the **`addons/f2_control/`** folder onto the host so the path is **`/addons/f2_control/`**
(*Samba:* `\\YOUR_HA_IP\addons\`; *SSH:* `cp -r HA-Irrigation-Strategy/addons/f2_control /addons/`),
then Add-on Store → ⋮ → **Reload** → it shows under **Local add-ons**.

#### 5b: Install + configure
1. Open **F2 Control** in the store → **Install** (first build takes ~a minute).
2. Open it → **Install** (the first build takes ~a minute).
3. **Configuration** tab: set `lights_on_hour` / `lights_off_hour`, your `notify_service`,
   and (if they differ from defaults) the feed EC/pH sensor ids and the pump / mainline /
   valve map. Shot sizing is read live from the integration's per-zone `substrate_volume`
   (PER-PLANT block) / `plant_count` / `drippers_per_plant` / `dripper_flow_rate` numbers —
   set those to your real hardware or shots come out the wrong length.

#### 5c: Kill switch + start
1. Create the kill switch `input_boolean.f2_control_enabled` (a Helper, or deploy
   `addons/f2_control/f2_control_package.yaml` to `/config/packages` → Developer Tools →
   **YAML → reload**). **OFF = safe** — the add-on reads/computes/notifies but never opens a valve.
2. No token to manage — the add-on gets its HA token automatically (`homeassistant_api: true`).
3. **Start** the add-on. Log shows `starting | kill-switch … | token present: True`. Leave
   the kill switch **OFF** until you've watched a photoperiod, then flip it ON to go live.

> **Updating later — Rebuild, NOT Restart.** The Dockerfile bakes the Python into the image
> at build (`COPY f2_control /app`). After changing any file, copy it to `/addons/f2_control/`
> again and use the add-on's **⋮ → Rebuild** — a plain Restart re-runs the old baked code.

✅ **Success Check:** `sensor.crop_steering_ai_heartbeat` shows attribute `engine: f2-control`
with a fresh `last_beat`, and `sensor.crop_steering_app_status` is live (e.g. `safe_idle`).

## Method 2: Manual Installation (Advanced Users)

⚠️ **Use HACS instead if possible** - it's much easier and provides automatic updates!

### Step 1: Download the Repository
1. Go to https://github.com/JakeTheRabbit/HA-Irrigation-Strategy
2. Click **Code** → **Download ZIP**
3. Extract the ZIP file

### Step 2: Copy Integration Files
1. Copy the `custom_components/crop_steering` folder to your Home Assistant:
   - Destination: `/config/custom_components/crop_steering/`
   
2. The structure should look like:
   ```
   /config/
   └── custom_components/
       └── crop_steering/
           ├── __init__.py
           ├── manifest.json
           ├── config_flow.py
           ├── sensor.py
           ├── switch.py
           ├── number.py
           ├── select.py
           └── (other files)
   ```

3. Restart Home Assistant

### Step 3: Add the Integration
Same as HACS Step 4 above - use the GUI to configure

### Step 4: Install the f2-control add-on (for autonomy)
Same as Step 5 above (copy `addons/f2_control/` to `/addons/`, Reload, Install).

## 🎛️ System Configuration

### 🎯 Basic Configuration (Required)
The setup wizard will walk you through this:

**Zone Setup:**
- How many growing areas do you have? (1-6 zones)
- Each zone can have its own sensors and controls

**Hardware Mapping:**
- **Water Pump:** The entity that turns your pump on/off
- **Main Valve:** The solenoid that controls your main water line
- **Zone Valves:** Individual valves for each growing area

*Don't know your entity names?* Check Developer Tools → States

### 🌡️ Sensor Configuration (Optional)
For each zone, you can add:

**Moisture Monitoring:**
- **Front VWC Sensor:** Moisture sensor at front of growing area
- **Back VWC Sensor:** Second moisture sensor for better accuracy

**Nutrient Monitoring:**
- **Front EC Sensor:** Nutrient/salt level sensor at front
- **Back EC Sensor:** Second EC sensor for better accuracy

**Environmental Sensors (system-wide):**
- **Temperature Sensor:** Air temperature
- **Humidity Sensor:** Relative humidity
- **VPD Sensor:** Vapor Pressure Deficit (if available)

**💡 Pro Tip:** You can always add more sensors later by reconfiguring the integration

### Legacy Configuration (crop_steering.env)
If you have an existing setup, you can load from your crop_steering.env file by selecting "Load from file" during setup.

## ✅ Test Your Installation

### 🔍 Quick System Check

**1. Check Integration Status**
- Go to **Settings → Devices & Services**
- Look for **"Crop Steering System"** device
- Should show green "Connected" status
- Click on it to see all your zones

**2. Verify Entities Were Created**
- Go to **Developer Tools → States**
- Type **"crop_steering"** in the filter box
- You should see many entities like:
  - `sensor.crop_steering_current_phase`
  - `switch.crop_steering_system_enabled`
  - `switch.crop_steering_zone_1_enabled` (for each zone)
  - `number.crop_steering_p1_target_vwc`
  - And many more!

**3. Test Basic Control**
- Find `switch.crop_steering_system_enabled`
- Try turning it OFF and ON
- The state should change immediately

**4. Check the f2-control add-on**
- Go to **Settings → Add-ons → F2 Control** → **"Log"** tab
- Look for: `starting | kill-switch … | token present: True`, then clean per-tick lines
- Confirm `sensor.crop_steering_ai_heartbeat` shows `engine: f2-control` with a fresh `last_beat`
- **If you changed add-on files:** you must **⋮ → Rebuild** (a Restart runs the old code)

### 🚨 Troubleshooting Quick Fixes

**Problem: "I don't see Crop Steering in Add Integration"**
- ✅ **Solution:** Restart Home Assistant and wait 2-3 minutes
- ✅ **Check:** Settings → System → Logs for any error messages

**Problem: "The F2 Control add-on won't start or shows errors"**
- ✅ **Check the kill switch helper exists:** `input_boolean.f2_control_enabled` must be created
- ✅ **Check the log** for the failing line; a traceback usually points at a missing entity id
- ✅ **Changed a file but nothing changed?** Use **⋮ → Rebuild**, not Restart (the image bakes the code)
- ✅ **Remember:** the integration works fine without the add-on for manual control + dashboards

**Problem: "I only see some of my zones"**
- ✅ **This is normal:** Entities are only created for the zones you configured
- ✅ **Want more zones?** Reconfigure the integration to add them

**Problem: "My sensors show 'Unknown' or 'None'"**
- ✅ **Check entity names:** Go to Developer Tools → States and verify your sensor entity names
- ✅ **Check sensor status:** Make sure your physical sensors are working

## 🎉 You're Done! What's Next?

### 🌱 First-Time Setup
1. **Choose your crop profile:**
   - Settings → Devices & Services → Crop Steering System → Configure
   - Select your plant type (Cannabis, Tomato, Lettuce, etc.)
   - Choose growth stage (Vegetative or Generative)

2. **Set your light schedule:**
   - Look for `number.crop_steering_lights_on_hour` entity
   - Set when your lights turn on (0-23 hours)
   - Set when lights turn off with `number.crop_steering_lights_off_hour`

3. **Confirm the engine is alive (no hardware moves):**
   - `sensor.crop_steering_ai_heartbeat` shows attribute `engine: f2-control`, updating.
   - `sensor.crop_steering_app_status` is a live state (e.g. `safe_idle`).
   - Keep the kill switch `input_boolean.f2_control_enabled` **OFF** until you've watched a photoperiod.

### 🤖 With the f2-control add-on armed
Once you flip the kill switch `input_boolean.f2_control_enabled` **ON**, the system will:
- Automatically transition through phases each day (P0→P1→P2→P3)
- Make smart irrigation decisions from your sensors + the feed-water safety gate
- Republish the `crop_steering_*` status surface for the dashboards
- Run autonomously — **one-line rollback is flipping the kill switch OFF**

**Then watch the first real cycle: shots should land and VWC should rise.** 📊

### 📚 Learn More
- **[Operation Guide](operation_guide.md)** - How to use your system day-to-day
- **[Dashboard Guide](dashboard_guide.md)** - Understanding the monitoring interface
- **[Troubleshooting Guide](troubleshooting.md)** - Solutions to common issues

### 🆘 Need Help?
- **GitHub Issues:** https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/issues
- **Home Assistant Forum:** Search for "Crop Steering"
- **Discord:** Join the Home Assistant Discord and ask in #custom-components

### 🎯 Pro Tips
- **Start conservative:** Use smaller shot sizes and longer intervals initially
- **Monitor closely:** Watch how your plants respond for the first few days
- **Adjust gradually:** Small parameter changes work better than big ones
- **Use test helpers:** The system creates test entities you can use for learning

**Congratulations! Your advanced crop steering system is ready to optimize your garden! 🌿🚰**