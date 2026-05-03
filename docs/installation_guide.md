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

### 🔧 Optional But Recommended
**AppDaemon Add-on** - Enables full automation:
- Automatic phase transitions throughout the day
- Smart sensor data processing
- Professional monitoring dashboards
- Advanced irrigation decisions

**Without AppDaemon:** You get manual control and basic monitoring
**With AppDaemon:** You get full autonomous operation

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

#### 5a: Install AppDaemon Add-on
1. **Go to Settings → Add-ons → Add-on Store**
2. **Search for "AppDaemon 4"**
3. **Click on AppDaemon 4** and click **INSTALL**
4. **DON'T START IT YET** - we need to configure it first

#### 5b: Get the Automation Files
**Option A: Download via GitHub (Easiest)**
1. Go to https://github.com/JakeTheRabbit/HA-Irrigation-Strategy
2. Click the green **"Code"** button → **"Download ZIP"**
3. Extract the ZIP file on your computer
4. Look for the `appdaemon/apps/` folder

**Option B: Use Git (Advanced Users)**
```bash
git clone https://github.com/JakeTheRabbit/HA-Irrigation-Strategy.git
```

#### 5c: Copy Files to AppDaemon
**Find your AppDaemon folder:**
- **File Manager:** Browse to `/addon_configs/a0d7b954_appdaemon/apps/`
- **Samba/SMB:** `\\YOUR_HA_IP\addon_configs\a0d7b954_appdaemon\apps\`
- **SSH/Terminal:** `/addon_configs/a0d7b954_appdaemon/apps/`

**Copy these files:**
From the downloaded files, copy:
```
appdaemon/apps/apps.yaml → /addon_configs/a0d7b954_appdaemon/apps/
appdaemon/apps/crop_steering/ → /addon_configs/a0d7b954_appdaemon/apps/crop_steering/
```

#### 5d: Configure AppDaemon
1. **Edit the main config file:** `/addon_configs/a0d7b954_appdaemon/appdaemon.yaml`
2. **Add your Home Assistant details:**
   ```yaml
   appdaemon:
     latitude: YOUR_LATITUDE
     longitude: YOUR_LONGITUDE
     elevation: YOUR_ELEVATION
     time_zone: YOUR_TIMEZONE
     plugins:
       HASS:
         type: hass
         ha_url: http://YOUR_HA_IP:8123
         token: YOUR_LONG_LIVED_ACCESS_TOKEN
   ```

**Need a token?**
- Go to your Profile in Home Assistant (click your username)
- Scroll down to "Long-Lived Access Tokens"
- Click "CREATE TOKEN"
- Copy the token and paste it in the config

#### 5e: Start AppDaemon
1. **Go to Settings → Add-ons → AppDaemon 4**
2. **Click "START"**
3. **Wait 30 seconds, then check the log**
4. **Look for:** "Master Crop Steering Application initialized"

✅ **Success Check:** If you see that message, automation is working!

### Step 6: Enable RootSense v3 Intelligence (Optional)

The system has a four-pillar intelligence platform layered on top of the
4-phase controller. **All pillars are opt-in and default OFF.** You can
enable them one at a time, in any order, and disable any pillar instantly
without breaking the rest of the system. Read `MIGRATION.md` in the repo
root for the full rollout playbook.

#### 6a: Add the AppDaemon pillars to `apps.yaml`

Open `appdaemon/apps/apps.yaml` and append the blocks from
`docs/upgrade/apps.example.yaml` in the repo. Each block is independent.
Recommended safe rollout order:

1. **`rootsense_root_zone`** (read-only — derives substrate sensors)
2. **`rootsense_anomaly`** (read-only — surfaces alerts)
3. **`rootsense_adaptive`** (cultivator-intent slider goes live)
4. **`rootsense_agronomic`** (transpiration + nightly run report)
5. **`rootsense_orchestrator`** (last — can call hardware-touching services)

Restart AppDaemon after editing `apps.yaml`.

#### 6b: Enable HA packages for the recorder includes (if not already)

If your `configuration.yaml` doesn't already enable packages, add:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Then restart Home Assistant. This activates `packages/rootsense/00_recorder.yaml`
which keeps the new RootSense sensors in HA's history database.

#### 6c: Toggle the pillar switches in the UI

For each pillar you've added to `apps.yaml`, find its corresponding
switch in HA and turn it on:

- `switch.crop_steering_intelligence_root_zone_enabled`
- `switch.crop_steering_intelligence_anomaly_enabled`
- `switch.crop_steering_intelligence_adaptive_enabled`
- `switch.crop_steering_intelligence_agronomic_enabled`
- `switch.crop_steering_intelligence_orchestrator_enabled`

The pillar starts publishing values within one tick (60 s for root zone,
30 s for orchestrator emergency check, 5 min for agronomic transpiration).

#### 6d: (Optional) Load the multi-metric dashboard

`dashboards/rootsense_history.yaml` is a three-tab Lovelace dashboard
(Intent / Substrate / Anomalies) using HA's built-in `history-graph`
card. Add it as a new dashboard or cherry-pick views into your existing
one.

✅ **Success Check:** With `rootsense_root_zone` enabled, you should see
`sensor.crop_steering_zone_1_dryback_velocity_pct_per_hr` populate within
2-3 minutes once VWC samples accumulate in its rolling buffer.

#### 6e: Get familiar with the cultivator intent slider

The single dial that drives every derived parameter in v3:
**`number.crop_steering_steering_intent`**, range -100 to +100.

- **+100** — pure vegetative bias (high VWC target, more shots, low EC)
- **0** — balanced midpoint (default — preserves v2.x behaviour)
- **-100** — pure generative bias (large dryback, fewer big shots, high EC)

The IntentResolver reads this every tick and re-publishes the derived
P1 target VWC, P2 threshold, P0 dryback drop %, shot size, and EC target
into their respective number entities.

---

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