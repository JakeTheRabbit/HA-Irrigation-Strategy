# Crop Steering System - .env Configuration Guide

## Overview

The Crop Steering System now supports **two configuration methods**:

1. **📄 .env File Configuration (Recommended)** - Fast, bulk setup with automatic zone detection
2. **🖥️ UI Configuration** - Manual setup through Home Assistant interface

You can mix both: Use .env for initial setup, then tweak parameters via UI!

---

## Quick Start with .env File

### Step 1: Create crop_steering.env

Copy the `crop_steering.env` file to your Home Assistant config directory:

```bash
# Location: /config/crop_steering.env
# Or on Docker: /addon_configs/a0d7b954_appdaemon/crop_steering.env
```

###Step 2: Configure Your Zones

The system **automatically detects zones** by looking for `ZONE_N_SWITCH` entries:

```ini
# Minimum configuration for 3 zones:
ZONE_1_SWITCH=switch.irrigation_relay_1
ZONE_2_SWITCH=switch.irrigation_relay_2
ZONE_3_SWITCH=switch.irrigation_relay_3
```

**That's it!** The system automatically detects 3 zones.

### Step 3: Add Sensors

For each zone, add VWC and EC sensors:

```ini
# Zone 1 sensors
ZONE_1_VWC_FRONT=sensor.vwc_r1_front
ZONE_1_VWC_BACK=sensor.vwc_r1_back
ZONE_1_EC_FRONT=sensor.ec_r1_front
ZONE_1_EC_BACK=sensor.ec_r1_back

# Zone 2 sensors
ZONE_2_VWC_FRONT=sensor.vwc_r2_front
# ... and so on
```

### Step 4: Add Hardware

```ini
PUMP_SWITCH=switch.water_pump
MAIN_LINE_SWITCH=switch.main_valve
```

### Step 5: Install Integration

1. Go to Settings → Devices & Services → Add Integration
2. Search for "Crop Steering"
3. Choose "Load from crop_steering.env file"
4. Done! System configures automatically

---

## Dynamic Zone Detection

**Add as many zones as you want!** Just follow the naming pattern:

```ini
# 6 zones? No problem!
ZONE_1_SWITCH=switch.relay_1
ZONE_2_SWITCH=switch.relay_2
ZONE_3_SWITCH=switch.relay_3
ZONE_4_SWITCH=switch.relay_4
ZONE_5_SWITCH=switch.relay_5
ZONE_6_SWITCH=switch.relay_6
```

The system automatically:
- Detects number of zones
- Creates entities for each zone
- Validates entity IDs
- Reports missing sensors

**No need to specify `num_zones` - it's automatic!**

---

## Complete .env Template

```ini
# ================================================================
# ZONE CONFIGURATION (Add as many as needed!)
# ================================================================

# Zone 1
ZONE_1_SWITCH=switch.irrigation_relay_1
ZONE_1_VWC_FRONT=sensor.vwc_zone_1_front
ZONE_1_VWC_BACK=sensor.vwc_zone_1_back
ZONE_1_EC_FRONT=sensor.ec_zone_1_front
ZONE_1_EC_BACK=sensor.ec_zone_1_back
ZONE_1_PLANT_COUNT=4
ZONE_1_MAX_DAILY_VOLUME=20.0
ZONE_1_SHOT_MULTIPLIER=1.0

# Zone 2
ZONE_2_SWITCH=switch.irrigation_relay_2
ZONE_2_VWC_FRONT=sensor.vwc_zone_2_front
ZONE_2_VWC_BACK=sensor.vwc_zone_2_back
ZONE_2_EC_FRONT=sensor.ec_zone_2_front
ZONE_2_EC_BACK=sensor.ec_zone_2_back
ZONE_2_PLANT_COUNT=4
ZONE_2_MAX_DAILY_VOLUME=20.0
ZONE_2_SHOT_MULTIPLIER=1.0

# ... Add ZONE_3, ZONE_4, etc. as needed

# ================================================================
# HARDWARE (REQUIRED)
# ================================================================
PUMP_SWITCH=switch.water_pump
MAIN_LINE_SWITCH=switch.main_valve
WASTE_SWITCH=

# ================================================================
# SUBSTRATE PROPERTIES
# ================================================================
SUBSTRATE_VOLUME_LITERS=10.0
DRIPPER_FLOW_RATE_LPH=2.0
DRIPPERS_PER_PLANT=2
SUBSTRATE_FIELD_CAPACITY=70.0
SUBSTRATE_MAX_EC=9.0

# ================================================================
# IRRIGATION PARAMETERS
# ================================================================

# P0 Phase - Morning Dryback
P0_VEG_DRYBACK_TARGET=50
P0_GEN_DRYBACK_TARGET=40
P0_MIN_WAIT_TIME=30
P0_MAX_WAIT_TIME=120

# P1 Phase - Ramp-Up
P1_INITIAL_SHOT_SIZE_PERCENT=2.0
P1_SHOT_SIZE_INCREMENT=0.5
P1_MAX_SHOT_SIZE_PERCENT=10.0
P1_TIME_BETWEEN_SHOTS=15
P1_TARGET_VWC=65
P1_MAX_SHOTS=10
P1_MIN_SHOTS=3

# P2 Phase - Maintenance
P2_SHOT_SIZE_PERCENT=2.0
P2_VWC_THRESHOLD=60
P2_EC_HIGH_THRESHOLD=1.2
P2_EC_LOW_THRESHOLD=0.8

# P3 Phase - Pre-Lights-Off
P3_VEG_LAST_IRRIGATION=120
P3_GEN_LAST_IRRIGATION=180
P3_EMERGENCY_VWC_THRESHOLD=40
P3_EMERGENCY_SHOT_SIZE_PERCENT=2.0

# ================================================================
# EC TARGETS
# ================================================================

# Vegetative
EC_TARGET_VEG_P0=3.0
EC_TARGET_VEG_P1=3.0
EC_TARGET_VEG_P2=3.2
EC_TARGET_VEG_P3=3.0

# Generative
EC_TARGET_GEN_P0=4.0
EC_TARGET_GEN_P1=5.0
EC_TARGET_GEN_P2=6.0
EC_TARGET_GEN_P3=4.5

# ================================================================
# FEATURES
# ================================================================
ENABLE_EC_STACKING=false
ENABLE_ANALYTICS=true
ENABLE_ML_FEATURES=false
```

---

## UI Configuration After .env Load

Once loaded from .env, you can reconfigure via UI:

### Reload from .env
Settings → Devices & Services → Crop Steering → Configure → Reload from .env

**Use this after editing .env file to pick up changes!**

### Edit Parameters
Settings → Devices & Services → Crop Steering → Configure → Edit Parameters

Adjust:
- Substrate volume
- Dripper flow rate
- P1/P2 thresholds
- Shot sizes

### Edit Features
Settings → Devices & Services → Crop Steering → Configure → Edit Features

Toggle:
- EC Stacking
- Analytics
- ML Features

### Edit via Number Entities
All parameters are also exposed as `number.*` entities:
- `number.crop_steering_substrate_volume`
- `number.crop_steering_p1_target_vwc`
- `number.crop_steering_p2_vwc_threshold`
- ... and 50+ more!

**Changes via entities take effect immediately!**

---

## Hybrid Configuration Workflow

**Best practice:**

1. **Initial Setup**: Use .env file for bulk configuration
2. **Testing**: Use UI or number entities to tweak parameters
3. **Finalize**: Update .env file with tested values
4. **Reload**: Use "Reload from .env" to apply

**Benefits:**
- Fast bulk setup with .env
- Quick tweaking with UI
- Version control your .env file
- Easy backup and restore

---

## Entity Validation

The system validates all entity IDs during setup:

```
✅ Valid: Entities found in Home Assistant
⚠️ Warning: Missing entities listed (can proceed)
❌ Error: Critical entities missing (blocked)
```

Missing entities are logged:
```
ZONE_1_VWC_FRONT: sensor.vwc_zone_1_front (not found)
PUMP_SWITCH: switch.water_pump (not found)
```

---

## Zone Naming Patterns

The parser looks for this exact pattern:

```ini
ZONE_<NUMBER>_SWITCH=<entity_id>
```

**Valid:**
```ini
ZONE_1_SWITCH=switch.relay_1  ✅
ZONE_10_SWITCH=switch.relay_10  ✅
ZONE_100_SWITCH=switch.relay_100  ✅
```

**Invalid:**
```ini
Zone_1_Switch=switch.relay_1  ❌ (wrong case)
ZONE1_SWITCH=switch.relay_1  ❌ (missing underscore)
ZONE_ONE_SWITCH=switch.relay_1  ❌ (not a number)
```

**Gaps are OK:**
```ini
ZONE_1_SWITCH=switch.relay_1  ✅
ZONE_3_SWITCH=switch.relay_3  ✅  (Zone 2 skipped)
ZONE_5_SWITCH=switch.relay_5  ✅
```
Result: 3 zones detected (1, 3, 5)

---

## Troubleshooting

### .env File Not Found
**Error:** "File not found: /config/crop_steering.env"

**Solution:**
1. Create `crop_steering.env` in HA config directory
2. Or use Manual UI configuration instead

### No Zones Detected
**Error:** "No zones detected in crop_steering.env file"

**Solution:**
Add at least one `ZONE_N_SWITCH` entry:
```ini
ZONE_1_SWITCH=switch.my_relay
```

### Missing Entities
**Warning:** "Entity ID not found: sensor.vwc_zone_1"

**Solution:**
1. Check entity ID spelling in Developer Tools → States
2. Fix entity ID in .env file
3. Reload integration: Configure → Reload from .env

### Parse Errors
**Error:** "Failed to parse crop_steering.env file"

**Solution:**
- Check for syntax errors (KEY=VALUE format)
- Remove special characters from values
- Use quotes for values with spaces

---

## Advanced: Multiple Configurations

**Production:**
```bash
/config/crop_steering.env  # Used by integration
```

**Testing:**
```bash
/config/crop_steering.test.env  # Backup
```

Switch between configs:
1. Rename files
2. Reload integration via UI

---

## Migration from Manual Config

If you started with manual UI configuration:

1. Export current settings to .env format
2. Create /config/crop_steering.env with exported values
3. Delete integration
4. Re-add integration with "Load from .env" option

---

## Summary

| Feature | .env Method | UI Method |
|---------|-------------|-----------|
| Initial Setup | ✅ Fast | ⚠️ Slow |
| Zone Detection | ✅ Automatic | ❌ Manual count |
| Bulk Changes | ✅ Easy | ❌ One-by-one |
| Quick Tweaks | ⚠️ Edit + Reload | ✅ Instant |
| Version Control | ✅ Git-friendly | ❌ No |
| Backup/Restore | ✅ Copy file | ⚠️ Complex |

**Recommendation:** Use .env for setup, UI for tweaking!

---

## Next Steps

1. Copy crop_steering.env to /config/
2. Edit zone and sensor entity IDs
3. Install integration (choose ".env" option)
4. Verify in Settings → Devices & Services
5. Tweak parameters via UI as needed

Need help? See [INSTALLATION_WARNINGS.md](INSTALLATION_WARNINGS.md)
