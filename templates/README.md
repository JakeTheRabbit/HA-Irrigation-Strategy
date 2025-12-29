# Crop Steering Configuration Templates

Pre-configured `.env` templates for quick setup based on your zone count.

## Available Templates

### 🌱 [crop_steering.2zone.env](crop_steering.2zone.env)
**Perfect for:**
- Small home grows
- Single tent setups
- Testing the system
- First-time users

**What you get:**
- Minimal configuration (2 zones)
- Essential parameters only
- Athena method defaults
- Quick setup in under 5 minutes

---

### 🌿 [crop_steering.4zone.env](crop_steering.4zone.env)
**Perfect for:**
- Medium grows
- Multiple tent setups
- Small commercial operations
- Veg + Flower rooms

**What you get:**
- Standard configuration (4 zones)
- Environmental sensor integration
- Full parameter set
- Production-ready defaults

---

### 🌳 [crop_steering.6zone.env](crop_steering.6zone.env)
**Perfect for:**
- Large commercial grows
- Multi-room facilities
- Research operations
- Maximum flexibility

**What you get:**
- Advanced configuration (6 zones)
- All sensors and features
- Scalable to unlimited zones
- Enterprise-grade setup

---

## Quick Start Guide

### 1. Choose Your Template

Pick the template that matches your zone count (or closest match):

```bash
# For 2 zones
cp templates/crop_steering.2zone.env crop_steering.env

# For 4 zones
cp templates/crop_steering.4zone.env crop_steering.env

# For 6 zones
cp templates/crop_steering.6zone.env crop_steering.env
```

### 2. Edit Entity IDs

Open `crop_steering.env` and replace placeholder entity IDs with your actual Home Assistant entities:

```ini
# BEFORE (placeholder):
ZONE_1_SWITCH=switch.irrigation_relay_1
PUMP_SWITCH=switch.water_pump

# AFTER (your actual entities):
ZONE_1_SWITCH=switch.esphome_zone_1_valve
PUMP_SWITCH=switch.tasmota_pump_relay
```

**Find your entity IDs:**
- Go to: Developer Tools → States in Home Assistant
- Search for: "switch", "sensor"
- Copy the full entity ID (e.g., `switch.my_device_name`)

### 3. Validate Configuration

Before installing, verify your entity IDs exist:

```bash
# In Home Assistant
Developer Tools → States → Search for each entity ID
```

### 4. Install Integration

```bash
# 1. Copy your edited file to Home Assistant config
cp crop_steering.env /config/crop_steering.env

# 2. In Home Assistant UI:
Settings → Devices & Services → Add Integration
Search: "Crop Steering"
Choose: "Load from crop_steering.env file"
Click: "Submit"
```

### 5. Verify Installation

Check that entities were created:
```
Settings → Devices & Services → Crop Steering
Should see: 100+ entities created
```

---

## Customization Tips

### Adding More Zones

Any template can be extended with additional zones:

```ini
# Add Zone 7 to the 6-zone template:
ZONE_7_SWITCH=switch.irrigation_relay_7
ZONE_7_VWC_FRONT=sensor.vwc_zone_7_front
ZONE_7_VWC_BACK=sensor.vwc_zone_7_back
ZONE_7_EC_FRONT=sensor.ec_zone_7_front
ZONE_7_EC_BACK=sensor.ec_zone_7_back
ZONE_7_PLANT_COUNT=4
ZONE_7_MAX_DAILY_VOLUME=20.0
ZONE_7_SHOT_MULTIPLIER=1.0
```

**No limit on zones!** The system automatically detects all `ZONE_N_SWITCH` entries.

### Removing Zones

Delete or comment out zones you don't need:

```ini
# --- ZONE 4 (Not using this zone) ---
# ZONE_4_SWITCH=switch.irrigation_relay_4
# ZONE_4_VWC_FRONT=sensor.vwc_zone_4_front
# ... etc
```

### Skipping Zone Numbers

Gaps in numbering are OK:

```ini
ZONE_1_SWITCH=switch.relay_1  # Veg room
ZONE_2_SWITCH=switch.relay_2  # Veg room
ZONE_5_SWITCH=switch.relay_5  # Flower room
ZONE_6_SWITCH=switch.relay_6  # Flower room

# Result: 4 zones detected (1, 2, 5, 6)
```

---

## Parameter Tuning Guide

### Substrate Volume Conversion

```ini
# Convert gallon pots to liters:
1 gallon  = 3.8 liters
3 gallon  = 11.4 liters
5 gallon  = 19 liters
7 gallon  = 26.5 liters
10 gallon = 38 liters
15 gallon = 57 liters

SUBSTRATE_VOLUME_LITERS=19.0  # For 5 gallon pots
```

### Dripper Flow Rate Testing

Measure your actual flow rate:

```bash
# 1. Run dripper into measuring cup for 60 seconds
# 2. Measure volume collected (ml)
# 3. Multiply by 60 to get liters per hour

Example:
60 seconds = 33ml collected
33ml × 60 = 1980ml/hour = 1.98 LPH

DRIPPER_FLOW_RATE_LPH=2.0
```

### Phase Timing Adjustments

**Vegetative Stage:**
```ini
P0_VEG_DRYBACK_TARGET=50   # Less stress (45-55%)
P1_TARGET_VWC=65           # Higher moisture (60-70%)
P3_VEG_LAST_IRRIGATION=120 # 2 hours before lights off
```

**Generative Stage:**
```ini
P0_GEN_DRYBACK_TARGET=40   # More stress (35-45%)
P1_TARGET_VWC=60           # Lower moisture (55-65%)
P3_GEN_LAST_IRRIGATION=180 # 3 hours before lights off
```

### EC Target Ranges

**Cannabis - Athena Method:**
```ini
# Early Veg (Week 1-2)
EC_TARGET_VEG_P2=2.8

# Late Veg (Week 3-4)
EC_TARGET_VEG_P2=3.2

# Early Flower (Week 1-3)
EC_TARGET_GEN_P2=5.0

# Mid Flower (Week 4-6)
EC_TARGET_GEN_P2=6.0

# Late Flower (Week 7+)
EC_TARGET_GEN_P2=4.5  # Fade
```

**Other Crops:**
```ini
# Tomatoes
EC_TARGET_VEG_P2=2.5
EC_TARGET_GEN_P2=4.0

# Lettuce
EC_TARGET_VEG_P2=1.8
EC_TARGET_GEN_P2=2.2
```

---

## Common Entity Naming Patterns

### ESPHome Devices
```ini
ZONE_1_SWITCH=switch.esphome_irrigation_zone_1
PUMP_SWITCH=switch.esphome_water_pump
ZONE_1_VWC_FRONT=sensor.esphome_vwc_1_front
```

### Tasmota Devices
```ini
ZONE_1_SWITCH=switch.tasmota_relay1
PUMP_SWITCH=switch.tasmota_pump
```

### Shelly Devices
```ini
ZONE_1_SWITCH=switch.shelly_zone1
PUMP_SWITCH=switch.shelly_pump
```

### Generic Home Assistant
```ini
ZONE_1_SWITCH=switch.irrigation_zone_1
PUMP_SWITCH=switch.main_pump
```

---

## Validation Checklist

Before installing, verify:

- [ ] All `ZONE_N_SWITCH` entity IDs exist in Home Assistant
- [ ] `PUMP_SWITCH` and `MAIN_LINE_SWITCH` are correct
- [ ] VWC sensor entity IDs match your sensors (if using)
- [ ] EC sensor entity IDs match your sensors (if using)
- [ ] Light entity and schedule are correct (if using)
- [ ] Substrate volume is in **liters** (not gallons!)
- [ ] Dripper flow rate is accurate (test with timer)
- [ ] All entity IDs start with correct domain (`switch.`, `sensor.`, `light.`)

---

## Troubleshooting

### "File not found: crop_steering.env"

**Solution:** Copy the file to the correct location
```bash
# On Home Assistant OS / Docker:
cp crop_steering.env /config/crop_steering.env

# On Home Assistant Core:
cp crop_steering.env ~/.homeassistant/crop_steering.env
```

### "No zones detected"

**Solution:** Ensure at least one `ZONE_N_SWITCH` entry exists
```ini
# Minimum required:
ZONE_1_SWITCH=switch.irrigation_relay_1
```

### "Entity not found" warnings

**Solution:** Verify entity IDs in Developer Tools
```
Developer Tools → States → Search for entity ID
If not found:
1. Check device is online
2. Check entity ID spelling
3. Check entity is not disabled
```

### Integration won't load

**Solution:** Check Home Assistant logs
```
Settings → System → Logs
Filter: "crop_steering"
Look for parsing errors or invalid entity formats
```

---

## Next Steps

1. **Test with Test Helpers:** The integration creates input_boolean and input_number entities for testing without real hardware
2. **Configure AppDaemon:** Install AppDaemon add-on for autonomous automation
3. **Tune Parameters:** Use the UI to adjust phase parameters as your crop develops
4. **Monitor Logs:** Watch AppDaemon logs to understand system behavior

---

## Support

- **Full Documentation:** [ENV_CONFIGURATION_GUIDE.md](../ENV_CONFIGURATION_GUIDE.md)
- **Installation Warnings:** [INSTALLATION_WARNINGS.md](../INSTALLATION_WARNINGS.md)
- **Issue Tracker:** https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/issues
- **Main README:** [README.md](../README.md)

---

**Need a custom zone count?** Start with the closest template and add/remove zones as needed. The system automatically detects any number of zones!
