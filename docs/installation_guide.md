# Installation Guide

This guide covers two installation methods: HACS (recommended) or manual installation.

## Prerequisites

### Required Add-ons
1. **AppDaemon 4** (optional but recommended for advanced features)
   - Settings → Add-ons → Add-on Store
   - Search "AppDaemon 4" and install
   - Don't start yet - we'll configure it after installation

### Hardware Requirements
- VWC sensors (moisture sensors) - at least 1 per zone
- EC sensors (nutrient sensors) - at least 1 per zone  
- Irrigation pump controlled by Home Assistant
- Main line valve (solenoid)
- Zone valves (1-6 zones supported)
- Grow lights controlled by Home Assistant

## Method 1: HACS Installation (Recommended)

### Step 1: Add Custom Repository
1. Open HACS in your sidebar
2. Click **Integrations**
3. Click the 3-dot menu (⋮) → **Custom repositories**
4. Add:
   - Repository: `https://github.com/JakeTheRabbit/HA-Irrigation-Strategy`
   - Category: `Integration`
5. Click **ADD**

### Step 2: Install the Integration
1. In HACS → Integrations, search for "Crop Steering"
2. Click on it and press **DOWNLOAD**
3. Restart Home Assistant

### Step 3: Configure the Integration
1. Go to Settings → Devices & Services
2. Click **+ ADD INTEGRATION**
3. Search for "Crop Steering"
4. Choose your setup method:
   - **Advanced Setup** (recommended) - Configure zones and sensors through GUI
   - **Basic Setup** - Just switches, no sensors
   - **Load from file** - If you have an existing crop_steering.env

### Step 4: Install AppDaemon Apps (Optional for Automation)
**What AppDaemon adds:**
- Automatic phase transitions (P0→P1→P2→P3)
- Sensor fusion (multiple sensors per zone)
- Automated irrigation decisions
- Analytics and monitoring dashboards

**Without AppDaemon you get:**
- Manual control of all zones
- All entities (sensors, switches, controls)
- Services for manual irrigation
- Basic monitoring

If you want full automation:

1. Navigate to the AppDaemon apps directory:
   - Path: `/addon_configs/a0d7b954_appdaemon/apps/`
   - Samba: `\\YOUR_HA_IP\addon_configs\a0d7b954_appdaemon\apps\`

2. Copy these files from this repository (folder `appdaemon/apps/`):
   ```
   appdaemon/apps/
   ├── apps.yaml
   └── crop_steering/
       ├── master_crop_steering_app.py
       ├── base_async_app.py
       ├── phase_state_machine.py
       ├── intelligent_sensor_fusion.py
       ├── advanced_dryback_detection.py
       ├── intelligent_crop_profiles.py
       └── ml_irrigation_predictor.py
   ```

3. Configure AppDaemon:
   - Edit `/addon_configs/a0d7b954_appdaemon/appdaemon.yaml`
   - Add your Home Assistant URL and Long-Lived Access Token
   - Update timezone and location

4. Start AppDaemon add-on

## Method 2: Manual Installation

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
Same as HACS Step 3 above - use the GUI to configure

### Step 4: Install AppDaemon Apps (Optional)
Same as HACS Step 4 above

## Configuration

### GUI Configuration (Recommended)
When you add the integration and select "Advanced Setup":

1. **Choose number of zones** (1-6)
2. **Configure hardware**:
   - Pump switch entity
   - Main line valve entity
   - Zone valve entities
3. **Configure sensors per zone** (all optional):
   - Front VWC sensor
   - Back VWC sensor
   - Front EC sensor
   - Back EC sensor
4. **Configure environmental sensors** (optional):
   - Temperature sensor
   - Humidity sensor
   - VPD sensor

### Legacy Configuration (crop_steering.env)
If you have an existing setup, you can load from your crop_steering.env file by selecting "Load from file" during setup.

## Verify Installation

### Check Integration
1. Go to Settings → Devices & Services
2. You should see "Crop Steering System" with all your zones

### Check Entities
In Developer Tools → States, filter by "crop_steering" to see:
- `sensor.crop_steering_system_state`
- `sensor.crop_steering_current_phase`
- `switch.crop_steering_zone_X_enabled` (for each zone)
- And many more!

### Check AppDaemon (if installed)
1. Go to AppDaemon add-on → Log
2. Look for "Master Crop Steering Application initialized"

## Troubleshooting

### Integration Not Showing
- Ensure you restarted Home Assistant after installation
- Check logs for errors: Settings → System → Logs

### AppDaemon Errors
- **Without AppDaemon**: You get manual control only (switches, sensors, manual services)
- **With AppDaemon**: You get full automation (automatic phase transitions, sensor fusion, analytics)
- If AppDaemon fails to start, check your token and URL in appdaemon.yaml
- The integration works fine without AppDaemon for manual irrigation control

### Missing Entities
- Entities are created based on your configuration
- If you configured 3 zones, you'll only see entities for zones 1-3

## Next Steps

1. **Configure your crop profile**: Settings → Devices & Services → Crop Steering → Configure
2. **Set up automations**: The system runs automatically once configured
3. **Monitor operation**: Check the phase transitions and irrigation events
4. **Join the community**: Report issues on GitHub if you encounter problems

That's it! Your crop steering system is now installed and ready to optimize your irrigation.