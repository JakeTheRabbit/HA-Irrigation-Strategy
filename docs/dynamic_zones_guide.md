# Dynamic Zone Configuration Guide

## Overview

The Crop Steering System supports dynamic zone configuration, allowing you to configure anywhere from 1 to 6 irrigation zones based on your actual setup. The system automatically creates all necessary entities and adjusts its operation based on your configured zones.

## Key Features

### 🚀 Dynamic Zone Support
- Configure 1-6 zones based on your actual hardware
- Automatic entity creation for each configured zone
- Zone-specific sensors, switches, and analytics
- Intelligent zone selection for optimal irrigation

### 🔧 Flexible Configuration
- Recommended: Configure through the GUI setup wizard
- Optional: Load zones from an existing `crop_steering.env` file
- Per-zone sensor configuration (front/back VWC and EC)
- Zone enable/disable switches for seasonal adjustments

### 📊 Per-Zone Monitoring
- Individual VWC and EC readings per zone
- Zone status indicators
- Last irrigation tracking
- Zone-specific analytics and history

## Configuration Methods

### Method 1: GUI Configuration (Recommended)

1. Go to Settings → Devices & Services
2. Add the “Crop Steering System” integration
3. Choose “Advanced Setup”
4. Configure hardware and zones:
   - Pump and main line entities
   - Zone valve entities
   - Optional per-zone sensors: VWC (front/back), EC (front/back)
5. Finish and reload Home Assistant if prompted

### Method 2: Load from crop_steering.env (Existing setups)

1. Place `crop_steering.env` in your Home Assistant config directory
2. Start the integration setup and choose “Load from file”
3. The integration will parse zones and sensors from the file

Example entries:
```env
ZONE_1_SWITCH=switch.zone_1_valve
ZONE_1_VWC_FRONT=sensor.z1_vwc_front
ZONE_1_VWC_BACK=sensor.z1_vwc_back
ZONE_1_EC_FRONT=sensor.z1_ec_front
ZONE_1_EC_BACK=sensor.z1_ec_back

ZONE_2_SWITCH=switch.zone_2_valve
# ... etc
```

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

1. Zone Enable Status
2. VWC Need Score
3. Sensor Reliability
4. Last Irrigation Time

Selection Algorithm:
```python
need_score = (70 - avg_vwc) / 70
reliability_score = 1 - (sensor_variance / 10)
zone_score = need_score * 0.7 + reliability_score * 0.3
```

## Services

### execute_irrigation_shot
Accepts dynamic zone numbers:
```yaml
service: crop_steering.execute_irrigation_shot
data:
  zone: 2
  duration_seconds: 300
  shot_type: P2
```

## AppDaemon Integration

The AppDaemon modules automatically detect and use configured zones:
- `master_crop_steering_app.py` – uses zone configuration from env/GUI
- `intelligent_sensor_fusion.py` – validates sensors per zone
- `advanced_dryback_detection.py` – dryback and trend analysis
- `intelligent_crop_profiles.py` – profile parameters

## Troubleshooting

### Missing Zone Entities
1. Ensure entity IDs are correct in GUI or env file
2. Verify referenced entities exist in Home Assistant
3. Restart Home Assistant after configuration changes

### Zone Not Irrigating
1. Check `switch.crop_steering_zone_X_enabled`
2. Verify zone sensors return numeric values
3. Confirm zone valve entity responds to commands
4. Review logs for zone selection details

### Sensor Validation Errors
1. Ensure sensor entities return numeric values
2. Check sensor units (VWC: %, EC: mS/cm)
3. Verify sensors aren’t `unavailable` or `unknown`

## Best Practices

### Sensor Placement
- Use both front and back sensors when possible
- Place sensors at root level in substrate
- Ensure good sensor-to-substrate contact
- Calibrate sensors before use

### AppDaemon v15+ File Locations
- AI Modules: `/addon_configs/a0d7b954_appdaemon/apps/crop_steering/`
- Configuration: `/addon_configs/a0d7b954_appdaemon/appdaemon.yaml`
- Apps Config: `/addon_configs/a0d7b954_appdaemon/apps/apps.yaml`
- Samba Access: `\\YOUR_HA_IP\addon_configs\a0d7b954_appdaemon`

### Zone Configuration
- Start with fewer zones and expand as needed
- Group plants with similar water needs in same zone
- Consider growth stages when zoning
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
ZONE_1_SWITCH=switch.veg_table_valve
ZONE_1_VWC_FRONT=sensor.veg_vwc_1
ZONE_1_VWC_BACK=sensor.veg_vwc_2
ZONE_1_EC_FRONT=sensor.veg_ec_1

ZONE_2_SWITCH=switch.flower1_valve
ZONE_2_VWC_FRONT=sensor.f1_vwc_front
ZONE_2_VWC_BACK=sensor.f1_vwc_back
ZONE_2_EC_FRONT=sensor.f1_ec_front
ZONE_2_EC_BACK=sensor.f1_ec_back

ZONE_3_SWITCH=switch.flower2_valve
ZONE_3_VWC_FRONT=sensor.f2_vwc_front
ZONE_3_EC_FRONT=sensor.f2_ec_front
```

## AppDaemon v15+ Compatibility

Fully compatible with AppDaemon v15+ directory changes.