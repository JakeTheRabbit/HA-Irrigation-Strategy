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

> ⚠️ **The engine is the f2-control add-on — NOT AppDaemon.** (AppDaemon is a retired
> rollback; don't install it.) And it's a **local** add-on: you copy its folder onto the
> host. **Do not** add this GitHub URL in the Add-on Store and **do not** `git clone` the
> `addons/f2_control` subfolder — this repo is a code monorepo, not an add-on repository,
> so the URL/clone gives `remote: Not Found / repository '…/addons/f2_control/' not found`.

#### 5a: Copy the add-on onto the HA host
1. Get the files: GitHub → green **Code** → **Download ZIP** (or
   `git clone https://github.com/JakeTheRabbit/HA-Irrigation-Strategy.git`).
2. Copy the **`addons/f2_control/`** folder onto the host so the path is **`/addons/f2_control/`**:
   - **Samba/SMB:** `\\YOUR_HA_IP\addons\` → drop `f2_control` in.
   - **SSH/Terminal:** `cp -r HA-Irrigation-Strategy/addons/f2_control /addons/`
   It must contain `config.yaml`, `Dockerfile`, `run.sh`, and the `f2_control/` Python package.

#### 5b: Install + configure
1. **Settings → Add-ons → Add-on Store → ⋮ (top-right) → Reload.** *F2 Control* now shows
   under **Local add-ons**.
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

### Step 4: Install AppDaemon Apps (Optional)
Same as HACS Step 5 above

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

**4. Check AppDaemon (if installed)**
- Go to **Settings → Add-ons → AppDaemon 4**
- Click the **"Log"** tab
- Look for: `Master Crop Steering Application initialized`
- **If you see errors:** Double-check your token and configuration

### 🚨 Troubleshooting Quick Fixes

**Problem: "I don't see Crop Steering in Add Integration"**
- ✅ **Solution:** Restart Home Assistant and wait 2-3 minutes
- ✅ **Check:** Settings → System → Logs for any error messages

**Problem: "AppDaemon won't start or shows errors"**
- ✅ **Check your token:** Go to your Profile → Long-Lived Access Tokens
- ✅ **Verify URL:** Should be `http://192.168.1.XXX:8123` (use your HA IP)
- ✅ **Check timezone:** Must match your Home Assistant timezone
- ✅ **Remember:** The integration works fine without AppDaemon for manual control

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

3. **Test manual control:**
   - Try the service `crop_steering.execute_irrigation_shot`
   - Set zone=1, duration_seconds=30 for a quick test

### 🤖 If You Installed AppDaemon
**Your system will now:**
- Automatically transition through phases each day (P0→P1→P2→P3)
- Make smart irrigation decisions based on your sensors
- Provide professional monitoring dashboards
- Run completely autonomously

**Just watch it work!** 📊

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