# Dynamic Zone Configuration Guide

## Overview

The Crop Steering System now supports dynamic zone configuration, allowing you to configure anywhere from 1 to 6 irrigation zones based on your actual setup. The system automatically creates all necessary entities and adjusts its operation based on your configured zones.

## Key Features

### 🚀 Dynamic Zone Support
- Configure 1-6 zones based on your actual hardware
- Automatic entity creation for each configured zone
- Zone-specific sensors, switches, and analytics
- Intelligent zone selection for optimal irrigation

### 🔧 Flexible Configuration
- Load zones from `crop_steering.env` file
- Manual configuration through UI setup wizard
- Per-zone sensor configuration (front/back VWC and EC)
- Zone enable/disable switches for seasonal adjustments

### 📊 Per-Zone Monitoring
- Individual VWC and EC readings per zone
- Zone status indicators
- Last irrigation tracking
- Zone-specific analytics and history

## Configuration Methods

### Method 1: Automatic Configuration (Recommended)

1. **Edit crop_steering.env**
   ```bash
   # Configure your zones in crop_steering.env
   ZONE_1_SWITCH=switch.zone_1_valve
   ZONE_1_VWC_FRONT=sensor.z1_vwc_front
   ZONE_1_VWC_BACK=sensor.z1_vwc_back
   ZONE_1_EC_FRONT=sensor.z1_ec_front
   ZONE_1_EC_BACK=sensor.z1_ec_back
   
   # Add more zones as needed
   ZONE_2_SWITCH=switch.zone_2_valve
   # ... etc
   ```

2. **Use Configuration Helper**
   ```bash
   python zone_configuration_helper.py
   ```
   This interactive script helps you configure zones easily.

3. **Add Integration**
   - Go to Settings → Devices & Services
   - Click "Add Integration"
   - Search for "Crop Steering"
   - Select "Load from crop_steering.env"

### GUI Setup Benefits

- **No command line access required**
- **Entity validation during setup**
- **Auto-complete for entity selection**
- **Preview sensor values during configuration**
- **Step-by-step guided setup**
- **Sensor configuration for each zone**
- **Environmental sensor support**

## Created Entities

For each configured zone, the system creates:

### Switches
- `switch.crop_steering_zone_X_enabled` - Enable/disable zone
- `switch.crop_steering_zone_X_manual_override` - Manual control mode

### Sensors
- `sensor.crop_steering_vwc_zone_X` - Average VWC for the zone
- `sensor.crop_steering_ec_zone_X` - Average EC for the zone
- `sensor.crop_steering_zone_X_status` - Zone operational status
- `sensor.crop_steering_zone_X_last_irrigation` - Last irrigation timestamp

### Global Sensors
- `sensor.crop_steering_configured_avg_vwc` - Average VWC across all zones
- `sensor.crop_steering_configured_avg_ec` - Average EC across all zones

## Zone Selection Logic

The system intelligently selects which zone to irrigate based on:

1. **Zone Enable Status** - Only enabled zones are considered
2. **VWC Need Score** - Zones with lower VWC get higher priority
3. **Sensor Reliability** - Zones with consistent sensor readings preferred
4. **Last Irrigation Time** - Prevents over-watering single zones

### Selection Algorithm
```python
need_score = (70 - avg_vwc) / 70  # Lower VWC = higher score
reliability_score = 1 - (sensor_variance / 10)  # Lower variance = higher score
zone_score = need_score * 0.7 + reliability_score * 0.3
```

## Service Updates

### execute_irrigation_shot
Now accepts dynamic zone numbers:
```yaml
service: crop_steering.execute_irrigation_shot
data:
  zone: 2  # Any configured zone (1-6)
  duration_seconds: 300
  shot_type: P2
```

## AppDaemon Integration

The AppDaemon modules automatically detect and use configured zones:

- **master_crop_steering_app.py** - Uses zone configuration from env file
- **intelligent_sensor_fusion.py** - Validates sensors for each zone
- **advanced_crop_steering_dashboard.py** - Displays all configured zones

## Troubleshooting

### Missing Zone Entities
If zone entities aren't created:
1. Check `crop_steering.env` has correct entity IDs
2. Verify referenced entities exist in Home Assistant
3. Restart Home Assistant after configuration changes

### Zone Not Irrigating
If a specific zone won't irrigate:
1. Check zone is enabled: `switch.crop_steering_zone_X_enabled`
2. Verify zone has valid VWC and EC sensor readings
3. Check zone valve entity is responding to commands
4. Review logs for zone selection reasoning

### Sensor Validation Errors
If getting sensor errors:
1. Ensure sensor entities return numeric values
2. Check sensor units (VWC: %, EC: mS/cm)
3. Verify sensors aren't returning 'unavailable' or 'unknown'

## Best Practices

### Sensor Placement
- Use both front and back sensors when possible
- Place sensors at root level in substrate
- Ensure good sensor-to-substrate contact
- Calibrate sensors before use

### AppDaemon v15+ File Locations
- **AI Modules**: `/addon_configs/a0d7b954_appdaemon/apps/crop_steering/`
- **Configuration**: `/addon_configs/a0d7b954_appdaemon/appdaemon.yaml`
- **Apps Config**: `/addon_configs/a0d7b954_appdaemon/apps/apps.yaml`
- **Samba Access**: `\\YOUR_HA_IP\addon_configs\a0d7b954_appdaemon`

### Zone Configuration
- Start with fewer zones and expand as needed
- Group plants with similar water needs in same zone
- Consider different growth stages when zoning
- Use zone enable switches for seasonal changes

### Monitoring
- Check zone status sensors daily
- Monitor per-zone VWC/EC trends
- Adjust thresholds based on zone performance
- Use manual override for testing

## Example Configurations

### Single Zone Setup
```env
ZONE_1_SWITCH=switch.greenhouse_valve
ZONE_1_VWC_FRONT=sensor.teros12_moisture
ZONE_1_EC_FRONT=sensor.teros12_ec
```

### Three Zone Setup
```env
# Veg Table
ZONE_1_SWITCH=switch.veg_table_valve
ZONE_1_VWC_FRONT=sensor.veg_vwc_1
ZONE_1_VWC_BACK=sensor.veg_vwc_2
ZONE_1_EC_FRONT=sensor.veg_ec_1

# Flower Room 1
ZONE_2_SWITCH=switch.flower1_valve
ZONE_2_VWC_FRONT=sensor.f1_vwc_front
ZONE_2_VWC_BACK=sensor.f1_vwc_back
ZONE_2_EC_FRONT=sensor.f1_ec_front
ZONE_2_EC_BACK=sensor.f1_ec_back

# Flower Room 2
ZONE_3_SWITCH=switch.flower2_valve
ZONE_3_VWC_FRONT=sensor.f2_vwc_front
ZONE_3_EC_FRONT=sensor.f2_ec_front
```

## AppDaemon v15+ Compatibility

The system is fully compatible with AppDaemon v15+ directory changes:

- **Updated paths** automatically detected
- **Migration tools** available for upgrading
- **Backward compatibility** with older AppDaemon versions
- **Fix script** handles both old and new directory structures

See [AppDaemon v15+ Migration Guide](appdaemon_v15_migration.md) for detailed migration instructions.

## Future Enhancements

- Zone grouping for simultaneous irrigation
- Zone-specific crop profiles
- Individual zone scheduling
- Zone priority configuration
- Water usage tracking per zone