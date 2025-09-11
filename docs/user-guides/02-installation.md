# Complete Installation Guide

**Transform your Home Assistant into a professional crop steering system** with this comprehensive installation guide covering basic setup through full automation.

> **New to crop steering?** Start with our [Getting Started Guide](01-getting-started.md) to understand the system basics.

## Installation Overview

This guide covers three progressive installation levels:

1. **🚀 Quick Start (15 minutes)** - Basic integration for immediate testing
2. **⚙️ Complete Setup (2-4 hours)** - Full automation with AppDaemon  
3. **🔧 Hardware Integration** - Connect physical sensors and valves

Each level builds on the previous one, so you can stop at any point based on your needs.

---

## 🚀 Part 1: Quick Start Installation

**Get your system running in 15 minutes** for testing and manual operation.

### Prerequisites
- Home Assistant 2024.3.0+ running and accessible
- HACS installed (recommended) or ability to copy files manually

### Step 1: Install the Integration (5 minutes)

#### Option A: HACS Installation (Recommended)
1. **Open HACS** in your Home Assistant sidebar
2. **Go to Integrations** tab
3. **Click three dots (⋮)** → "Custom repositories"
4. **Add repository**:
   - URL: `https://github.com/JakeTheRabbit/HA-Irrigation-Strategy`
   - Category: `Integration`
5. **Click "ADD"**
6. **Search for "Crop Steering"** in HACS
7. **Download and install**
8. **Restart Home Assistant**

#### Option B: Manual Installation
1. Download the [latest release](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/releases)
2. Copy `custom_components/crop_steering/` to your HA config directory
3. Restart Home Assistant

### Step 2: Add the Integration (5 minutes)

1. **Navigate to** Settings → Devices & Services
2. **Click "+ ADD INTEGRATION"** (bottom right)
3. **Search for "Crop Steering"** and select it
4. **Choose setup method**:
   - **"Advanced Setup"** if you have sensors and hardware
   - **"Basic Setup"** for testing or manual control only

### Step 3: Basic Configuration (5 minutes)

#### If You Have Real Hardware:
1. **Set number of zones** (1-6)
2. **Map your entities**:
   - Pump switch: `switch.your_pump_entity`
   - Zone valves: `switch.zone_1_valve`, etc.
   - VWC sensors: `sensor.zone_1_vwc_front`, etc.
   - EC sensors: `sensor.zone_1_ec_front`, etc.

#### For Testing Without Hardware:
The integration creates test helper entities automatically:
- `input_boolean.water_pump_1`
- `input_boolean.zone_1_valve`
- `input_number.zone_1_vwc_front`
- `input_number.zone_1_ec_front`

### Step 4: Verify Quick Start Installation

#### Check Your New Entities
1. **Go to** Developer Tools → States
2. **Filter by** `crop_steering`
3. **You should see**:
   - `sensor.crop_steering_current_phase`
   - `switch.crop_steering_system_enabled`
   - `sensor.crop_steering_configured_avg_vwc`
   - Many more entities based on your zone count

#### Test Manual Control
1. **Try a test irrigation**:
   ```yaml
   # In Developer Tools > Services
   service: crop_steering.execute_irrigation_shot
   data:
     zone: 1
     duration_seconds: 30
   ```

2. **Watch your pump and valve entities** activate

### Quick Start Complete! ✅

You now have:
- ✅ Complete monitoring system with 100+ entities  
- ✅ Manual irrigation controls with safety interlocks  
- ✅ Shot duration calculations based on your configuration  
- ✅ Professional dashboard ready for customization  

**Next Steps:** Continue to Part 2 for full automation, or jump to [Daily Operation Guide](04-daily-operation.md) for manual operation.

---

## ⚙️ Part 2: Complete Setup with Full Automation

**Enable autonomous 4-phase operation** with advanced sensor validation and professional hardware sequencing.

### Prerequisites
- Part 1 (Quick Start) completed successfully
- AppDaemon available (Home Assistant add-on or standalone)
- 2-4 hours available for setup and testing

### Step 1: Install AppDaemon Add-on

1. **Navigate to** Settings → Add-ons → Add-on Store
2. **Search for "AppDaemon 4"**
3. **Install AppDaemon 4** (don't start yet)

### Step 2: Configure AppDaemon

1. **Get your access token**:
   - Go to your Home Assistant Profile (click your username)
   - Scroll to "Long-Lived Access Tokens"
   - Click "CREATE TOKEN"
   - Copy the token (you'll need it in the next step)

2. **Edit AppDaemon configuration**:
   - Go to Settings → Add-ons → AppDaemon 4 → Configuration
   - Replace the configuration with:
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

### Step 3: Download Automation Files

**Option A: GitHub Download**
1. Go to https://github.com/JakeTheRabbit/HA-Irrigation-Strategy
2. Click **"Code"** → **"Download ZIP"**
3. Extract and locate the `appdaemon/apps/` folder

**Option B: Git Clone**
```bash
git clone https://github.com/JakeTheRabbit/HA-Irrigation-Strategy.git
```

### Step 4: Copy Automation Files

1. **Access AppDaemon folder**:
   - Via File Manager: `/addon_configs/a0d7b954_appdaemon/apps/`
   - Via Samba: `\\\\YOUR_HA_IP\\addon_configs\\a0d7b954_appdaemon\\apps\\`

2. **Copy these files**:
   ```
   appdaemon/apps/apps.yaml → /addon_configs/a0d7b954_appdaemon/apps/
   appdaemon/apps/crop_steering/ → /addon_configs/a0d7b954_appdaemon/apps/crop_steering/
   ```

### Step 5: Start AppDaemon

1. **Go to** Settings → Add-ons → AppDaemon 4
2. **Click "START"**
3. **Wait 30 seconds**
4. **Check the log** for: "Master Crop Steering Application initialized"

### Complete Setup Verification

#### System Health Check
1. **Check integration status**:
   - Settings → Devices & Services → Crop Steering System
   - Should show "Connected" status

2. **Verify AppDaemon**:
   - Settings → Add-ons → AppDaemon 4 → Log
   - Look for successful initialization messages

3. **Test automation**:
   - Try manual phase transition
   - Test irrigation shot
   - Monitor for automatic phase changes

### Complete Setup Complete! ✅

You now have:
- ✅ **Fully autonomous 4-phase operation**  
- ✅ **Advanced sensor validation and analytics**  
- ✅ **Professional hardware sequencing**  
- ✅ **Comprehensive safety systems**  
- ✅ **Historical tracking and optimization**  

**Next Steps:** Continue to Part 3 for hardware integration, or jump to [Daily Operation Guide](04-daily-operation.md) to learn the interface.

---

## 🔧 Part 3: Hardware Integration

**Connect physical sensors and valves** for a fully functional precision irrigation system.

### Prerequisites
- Parts 1 & 2 completed (integration and automation working)
- Physical hardware available (sensors, pumps, valves)
- Basic electronics knowledge for sensor connections

### Hardware Requirements

#### Essential Components
**Water System**
- Water pump (12V/24V DC or 240V AC with relay control)
- Main line solenoid valve (optional but recommended)
- Zone-specific solenoid valves (1-6 zones)
- Pressure-compensating drippers or micro-sprinklers
- Water reservoir/tank with level monitoring

**Sensors (Per Zone)**
- VWC (Volumetric Water Content) sensors
- EC (Electrical Conductivity) sensors
- Temperature sensors (optional)

**Control Hardware**
- Relay board or individual relays for pump/valve control
- Microcontroller (ESP32/ESP8266 recommended)
- Power supplies for sensors and control systems

#### Recommended Sensor Types

**VWC Sensors**
- **Capacitive soil moisture sensors** (preferred)
  - More durable than resistive types
  - Better long-term accuracy
  - Examples: DFRobot SEN0193, Adafruit STEMMA

- **TDR (Time Domain Reflectometry) sensors** (professional grade)
  - Highest accuracy
  - Industrial reliability
  - Examples: Stevens HydraProbe, Campbell Scientific CS616

**EC Sensors**
- **Analog EC probes** with temperature compensation
  - Examples: DFRobot SEN0169, Atlas Scientific EC probe
  - Require calibration with standard solutions

- **All-in-one sensors** (EC + temperature)
  - Convenient single-probe solution
  - Built-in temperature compensation

### System Architecture

#### Typical Setup Diagram
```
[Water Tank] → [Pump] → [Main Valve] → [Zone Valves] → [Drippers]
     ↓              ↓           ↓            ↓
[Level Sensor] [Pump Relay] [Main Relay] [Zone Relays]
     ↓              ↓           ↓            ↓
[ESP32/ESP8266] ← [Relay Board] ← [Home Assistant]
     ↓
[VWC/EC Sensors per Zone]
```

#### Power Requirements

**12V DC System (Recommended)**
- Easy to work with and safe
- Common voltage for drip irrigation components
- Requires 12V power supply (minimum 5A)

**24V AC System (Professional)**
- Standard for commercial irrigation
- More robust for longer wire runs
- Requires 24VAC transformer

### ESPHome Configuration

#### Basic ESP32 Configuration
```yaml
# crop_steering.yaml
esphome:
  name: crop-steering-controller
  platform: ESP32
  board: esp32dev

wifi:
  ssid: "YourWiFiNetwork"
  password: "YourWiFiPassword"

api:
  password: "your_api_password"

ota:
  password: "your_ota_password"

logger:

# VWC Sensors
sensor:
  - platform: adc
    pin: GPIO36
    name: "Zone 1 VWC Front"
    id: zone1_vwc_front
    update_interval: 30s
    filters:
      - calibrate_linear:
          - 0.0 -> 0.0    # Dry reading
          - 3.3 -> 100.0  # Wet reading
    unit_of_measurement: "%"
    device_class: humidity

  - platform: adc
    pin: GPIO39
    name: "Zone 1 EC Front"
    id: zone1_ec_front
    update_interval: 30s
    filters:
      - calibrate_linear:
          - 0.0 -> 0.0    # Calibration point 1
          - 3.3 -> 5.0    # Calibration point 2
    unit_of_measurement: "mS/cm"

# Pump and Valve Controls
switch:
  - platform: gpio
    pin: GPIO2
    name: "Water Pump 1"
    id: water_pump_1

  - platform: gpio
    pin: GPIO4
    name: "Main Water Valve"
    id: main_water_valve

  - platform: gpio
    pin: GPIO5
    name: "Zone 1 Valve"
    id: zone_1_valve
```

### Sensor Calibration

#### VWC Sensor Calibration
1. **Dry Calibration**:
   - Remove sensor from soil
   - Let dry completely
   - Record raw ADC value (should be near 0)

2. **Wet Calibration**:
   - Submerge sensor in water
   - Record raw ADC value (should be near maximum)

3. **Apply Calibration**:
   ```yaml
   filters:
     - calibrate_linear:
         - [dry_value] -> 0.0
         - [wet_value] -> 100.0
   ```

#### EC Sensor Calibration
1. **Use Standard Solutions**:
   - Calibration solution 1: 1.413 mS/cm
   - Calibration solution 2: 12.88 mS/cm

2. **Two-Point Calibration**:
   ```yaml
   filters:
     - calibrate_linear:
         - [low_reading] -> 1.413
         - [high_reading] -> 12.88
   ```

### Physical Installation

#### Sensor Placement
**VWC Sensors**
- Install at root zone depth (typically 10-15cm)
- Place 5-10cm from plant stem
- Use front and back positions for averaging
- Ensure good soil contact

**EC Sensors**
- Install near VWC sensors for correlation
- Same depth as VWC sensors
- Keep probe clean and calibrated
- Replace sensing elements annually

#### Dripper Layout
**Optimal Dripper Placement**
- 2-4 drippers per plant
- Evenly spaced around plant
- Flow rate: 1-4 L/hr per dripper
- Pressure compensating preferred

**Flow Rate Calculations**
```
Duration (seconds) = (Pot Volume × Shot %) ÷ (Flow Rate × Drippers) × 3600
```

Example:
- 10L pot, 5% shot, 2×2L/hr drippers
- Duration = (10 × 0.05) ÷ (2 × 2) × 3600 = 450 seconds

### Integration with Home Assistant

#### Device Discovery
Once ESPHome device is running:
1. **Go to** Settings → Devices & Services
2. **ESPHome devices** should auto-discover
3. **Configure and adopt** the device
4. **All sensors and switches** become available as entities

#### Update Integration Configuration
1. **Reconfigure the integration**:
   - Settings → Devices & Services → Crop Steering System → Configure
   - Update entity mappings to match your hardware

2. **Set physical parameters**:
   - Pot volume in liters
   - Dripper flow rate in L/hr
   - Number of drippers per plant

3. **Configure light schedule**:
   - Set `lights_on_hour` (0-23)
   - Set `lights_off_hour` (0-23)

### Hardware Testing

#### Test Individual Components
```yaml
# Test pump
service: switch.turn_on
target:
  entity_id: switch.water_pump_1

# Test valve
service: switch.turn_on
target:
  entity_id: switch.zone_1_valve
```

#### Verify Sensor Readings
- Check sensors provide reasonable values
- VWC: 0-100%
- EC: 0-8 mS/cm typically
- Sensors update regularly (every 30-60 seconds)

### Hardware Integration Complete! ✅

You now have:
- ✅ **Physical sensors providing real-time data**
- ✅ **Automated pump and valve control**
- ✅ **Precise water delivery calculations**
- ✅ **Professional irrigation sequencing**
- ✅ **Complete autonomous operation**

---

## System Tuning & Optimization

### Growth Parameters

**Vegetative Stage**
- Higher VWC targets (65-70%)
- Lower EC targets (1.5-2.0 mS/cm)
- More frequent irrigation

**Generative/Flowering Stage**
- Lower VWC targets (55-60%)
- Higher EC targets (2.5-3.5 mS/cm)
- Controlled stress for better production

### Phase Settings

**P0 (Morning Dryback)**
- `p0_dryback_drop_percent`: 15-20%
- `p0_min_wait_time`: 30 minutes
- `p0_max_wait_time`: 180 minutes

**P1 (Ramp-Up)**
- `p1_initial_shot_size`: 2%
- `p1_shot_increment`: 0.5%
- `p1_target_vwc`: 65% (veg) or 60% (gen)

**P2 (Maintenance)**
- `p2_vwc_threshold`: 60% (veg) or 55% (gen)
- `p2_shot_size`: 5%

**P3 (Pre-Lights-Off)**
- `p3_veg_last_irrigation`: 60 minutes
- `p3_gen_last_irrigation`: 90 minutes
- `p3_emergency_vwc_threshold`: 40%

---

## Installation Troubleshooting

### Common Installation Issues

**Integration not found after install?**
- Restart Home Assistant and wait 2-3 minutes
- Check Settings → System → Logs for errors
- Clear browser cache and try again

**HACS installation problems?**
- Verify URL: `https://github.com/JakeTheRabbit/HA-Irrigation-Strategy`
- Ensure category is set to "Integration"
- Try manual installation as fallback

**AppDaemon won't start?**
- Check your token is valid
- Verify Home Assistant URL is correct
- Ensure timezone matches HA

**No automatic irrigation?**
- Check current phase (may be in P0 waiting)
- Verify system and auto irrigation switches are ON
- Review thresholds vs current VWC

For detailed troubleshooting, see our [Troubleshooting Guide](05-troubleshooting.md).

---

## What You've Accomplished

Depending on how far you've progressed:

### ✅ Quick Start (Part 1)
- Complete integration with 100+ entities
- Manual irrigation controls with safety systems
- Professional monitoring dashboard
- **Time investment:** 15 minutes

### ✅ Complete Setup (Part 2)  
- Fully autonomous 4-phase operation
- Advanced analytics and safety systems
- Professional automation sequences
- **Time investment:** 2-4 hours

### ✅ Hardware Integration (Part 3)
- Real-time sensor monitoring
- Automated hardware control
- Precision irrigation delivery
- **Time investment:** 4-8 hours

## Next Steps

### For Daily Operation
- **[Daily Operation Guide](04-daily-operation.md)** - Learn to monitor and maintain your system
- **[Dashboard Guide](03-configuration.md)** - Set up monitoring displays

### For Advanced Features
- **[LLM Integration](../advanced-features/llm-integration.md)** - Add AI decision assistance
- **[Smart Learning System](../advanced-features/smart-learning-system.md)** - Enable adaptive optimization

### For Troubleshooting
- **[Troubleshooting Guide](05-troubleshooting.md)** - Comprehensive problem-solving resource

---

**🎉 Congratulations!** You now have a professional-grade crop steering system. Take time to monitor the first few cycles and adjust parameters as needed for optimal results with your specific plants and environment.