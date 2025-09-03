# 🔧 Troubleshooting Guide

This guide helps resolve common issues with the Crop Steering System. Since this is a **rule-based irrigation controller** (not AI/ML), troubleshooting focuses on sensor readings, hardware control, and system logic.

## 🚨 Emergency Procedures

### Immediate Actions for Critical Issues

#### System Not Irrigating During Emergency

**Symptoms:**
- VWC below emergency threshold (default 35%)
- No automatic irrigation response
- Plants showing stress signs

**Immediate Actions:**
1. **Manual irrigation**: Use service `crop_steering.execute_irrigation_shot`
2. **Check system enabled**: Verify `switch.crop_steering_system_enabled` is ON
3. **Check zone enabled**: Verify `switch.crop_steering_zone_X_enabled` is ON  
4. **Check manual override**: Ensure `switch.crop_steering_zone_X_manual_override` is OFF

**Quick Manual Irrigation:**
```yaml
# In Developer Tools > Services
service: crop_steering.execute_irrigation_shot
data:
  zone: 1
  duration_seconds: 60
  shot_type: "P3_emergency"
```

#### Runaway Irrigation (Won't Stop)

**Symptoms:**
- Irrigation running continuously
- VWC above target ranges
- System not responding to commands

**Immediate Actions:**
1. **Turn off system**: Set `switch.crop_steering_system_enabled` to OFF
2. **Turn off pump**: Manually turn off your pump entity
3. **Turn off valves**: Manually turn off all valve entities
4. **Check hardware**: Inspect physical relays and valves

## 🔍 System Diagnostic Checklist

### 1. Integration Status Check
```bash
# Go to Settings > Devices & Services
# Look for "Crop Steering System" - should show "Connected"
# Click on device to see all entities
```

### 2. Basic Entity Check  
```bash
# Go to Developer Tools > States
# Filter by "crop_steering"
# Verify these key entities exist and have recent timestamps:

sensor.crop_steering_current_phase: "P0" | "P1" | "P2" | "P3" | "Manual"
sensor.crop_steering_configured_avg_vwc: 45-70% (reasonable range)
sensor.crop_steering_configured_avg_ec: 2.0-8.0 mS/cm
switch.crop_steering_system_enabled: on | off
```

### 3. AppDaemon Status Check (if using automation)
```bash
# Go to Settings > Add-ons > AppDaemon 4 > Log
# Look for: "Master Crop Steering Application initialized"
# If errors, check your AppDaemon configuration
```

### 4. Hardware Test
```yaml
# Test your hardware entities manually:
# Developer Tools > Services

# Test pump
service: switch.turn_on
target:
  entity_id: switch.YOUR_PUMP_ENTITY

# Verify pump actually turns on physically
# Turn off after test
service: switch.turn_off  
target:
  entity_id: switch.YOUR_PUMP_ENTITY
```

## 🌡️ Sensor Issues

### VWC Sensor Problems

**Readings Show "Unknown" or "None":**
- Check entity exists: Developer Tools > States
- Verify entity name matches your configuration
- Check physical sensor connections
- Verify sensor is powered and communicating

**Erratic/Impossible Readings:**
- Check sensor calibration (should read 0-100%)
- Ensure stable sensor placement in substrate
- Look for electrical interference sources
- Verify consistent power supply

**Multiple Sensors Don't Match:**
```bash
# For zone with front/back sensors:
sensor.crop_steering_vwc_zone_1: 55% (averaged value)

# Individual sensors should be reasonably close:
YOUR_FRONT_VWC_SENSOR: 53%
YOUR_BACK_VWC_SENSOR: 57%

# Large differences (>15%) indicate calibration or placement issues
```

### EC Sensor Problems

**High Noise/Fluctuation:**
- Enable temperature compensation if available
- Check electrical grounding and isolation
- Ensure steady solution flow past sensor
- Clean sensor electrodes regularly

**Readings Drift Over Time:**
- Calibrate sensors monthly with standard solutions
- Clean electrodes with appropriate solutions
- Replace aging sensors (typically 2-3 years)

## ⚙️ System Configuration Issues

### Wrong Entity Names

**Symptoms:** Integration shows errors, sensors read as None
**Solution:**
1. Go to Developer Tools > States
2. Find correct entity names for your hardware
3. Reconfigure integration: Settings > Devices & Services > Crop Steering > Configure
4. Update entity names to match exactly

### Missing Zones

**Symptoms:** Only see some zones, missing expected entities
**Solution:**
1. Entities are only created for configured zones
2. To add zones: Reconfigure integration
3. Increase zone count and add hardware entities

### Phase Not Changing

**Without AppDaemon:**
- Phases must be changed manually using service `crop_steering.transition_phase`
- Or by setting `select.crop_steering_irrigation_phase` directly

**With AppDaemon:**
- Check AppDaemon is running and logs show no errors
- Verify light schedule: `number.crop_steering_lights_on_hour` and `lights_off_hour`
- Check that system isn't in manual override

## 🔌 Hardware Troubleshooting  

### Pump Issues

**Pump Won't Start:**
1. Check power supply (typically 24VAC)
2. Test pump entity manually: `switch.YOUR_PUMP_ENTITY`
3. Verify relay is working (hear click when switching)
4. Check physical pump for binding or blockages

**Pump Runs But No Flow:**
1. Check pump prime/pressure
2. Look for air leaks in lines
3. Verify valve positions (main valve open)
4. Clear any blockages in irrigation lines

### Valve Problems

**Valve Won't Open:**
1. Check power supply to valve (typically 24VAC)
2. Test valve entity manually
3. Listen for solenoid click when activating
4. Use manual valve override if available

**Valve Won't Close:**
1. Check for debris in valve seat
2. Power cycle valve (off then on)
3. Inspect return spring mechanism
4. Replace solenoid if mechanically failed

## 📡 Network and Communication

### Sensors Going Offline

**Symptoms:** Entities show "unavailable" or "unknown"
**Solutions:**
- Check WiFi signal strength at sensor locations
- Verify power supply stability
- Restart sensor devices
- Check Home Assistant device status page

### AppDaemon Communication Issues

**Symptoms:** Automation not working, AppDaemon errors
**Solutions:**
- Verify long-lived access token is valid
- Check AppDaemon can reach Home Assistant (same network)
- Restart AppDaemon add-on
- Review AppDaemon configuration file

## 📊 Performance and Logic Issues

### Irrigation Too Frequent

**Symptoms:** System watering too often, VWC staying too high
**Solutions:**
- Increase P2 VWC threshold: `number.crop_steering_p2_vwc_threshold`  
- Reduce shot sizes: `number.crop_steering_p1_initial_shot_size`
- Increase time between shots: `number.crop_steering_p1_time_between_shots`

### Irrigation Not Frequent Enough

**Symptoms:** VWC dropping too low, plants stressed
**Solutions:**
- Lower P2 VWC threshold  
- Increase shot sizes
- Reduce dryback targets: `number.crop_steering_veg_dryback_target`

### Wrong Phase Behavior

**P0 (Morning Dryback) Issues:**
- Check dryback drop percentage: `number.crop_steering_p0_dryback_drop_percent`
- Verify min/max wait times: `p0_min_wait_time`, `p0_max_wait_time`

**P1 (Ramp-Up) Issues:**
- Adjust target VWC: `number.crop_steering_p1_target_vwc`
- Modify shot progression: `p1_initial_shot_size`, `p1_shot_increment`, `p1_max_shots`

**P2 (Maintenance) Issues:**
- Fine-tune VWC threshold: `p2_vwc_threshold`
- Adjust EC thresholds: `p2_ec_high_threshold`, `p2_ec_low_threshold`

## 🛠️ Maintenance Procedures

### Daily Checks
- **System Status**: All switches enabled, no error messages
- **Sensor Readings**: Values within expected ranges
- **Phase Transitions**: Automatic progression through daily cycle
- **Irrigation Events**: Appropriate watering frequency

### Weekly Maintenance  
- **Sensor Validation**: Cross-check sensors for accuracy
- **Parameter Tuning**: Adjust based on plant response
- **Hardware Inspection**: Visual check of pumps, valves, sensors
- **Performance Review**: Analyze irrigation efficiency

### Monthly Procedures
- **Sensor Calibration**: Recalibrate with known standards
- **System Backup**: Export configuration and settings
- **Software Updates**: Check for integration updates
- **Deep Clean**: Clean sensor electrodes and housings

## 🆘 When to Get Help

### Self-Service First
1. **Check this guide** for your specific issue
2. **Review logs**: Home Assistant logs and AppDaemon logs (if applicable)
3. **Test systematically**: Start with manual hardware tests
4. **Check configuration**: Verify entity names and settings

### Community Support
- **GitHub Issues**: https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/issues
- **Home Assistant Forum**: Search for "Crop Steering"
- **Discord**: Join Home Assistant Discord, ask in #custom-components

### Information to Provide When Asking for Help
1. **Describe the problem**: What's happening vs. what should happen
2. **System details**: Home Assistant version, AppDaemon version (if used)
3. **Configuration**: Number of zones, hardware types
4. **Error logs**: Copy relevant error messages
5. **Troubleshooting tried**: What you've already attempted

## 📋 Quick Reference Commands

### Manual Controls
```yaml
# Manual irrigation shot
service: crop_steering.execute_irrigation_shot
data:
  zone: 1
  duration_seconds: 60

# Change phase manually  
service: crop_steering.transition_phase
data:
  target_phase: "P2"
  
# Enable manual override
service: crop_steering.set_manual_override
data:
  zone: 1
  enable: true
```

### Key Entities to Monitor
```yaml
# System Status
sensor.crop_steering_current_phase
switch.crop_steering_system_enabled
switch.crop_steering_auto_irrigation_enabled

# Zone Status (replace X with zone number)
switch.crop_steering_zone_X_enabled
sensor.crop_steering_zone_X_status
sensor.crop_steering_vwc_zone_X

# Measurements  
sensor.crop_steering_configured_avg_vwc
sensor.crop_steering_configured_avg_ec
sensor.crop_steering_ec_ratio
```

### Important Parameters
```yaml
# VWC Targets
number.crop_steering_p1_target_vwc: 60%
number.crop_steering_p2_vwc_threshold: 58%

# Shot Sizes
number.crop_steering_p1_initial_shot_size: 5%
number.crop_steering_p2_shot_size: 3%

# Emergency Settings
number.crop_steering_p3_emergency_vwc_threshold: 35%
number.crop_steering_p3_emergency_shot_size: 8%
```

---

**Remember**: This system uses rule-based logic, not AI/ML. Most issues are related to configuration, hardware, or sensor problems. Start with the basics and work systematically through the diagnostic steps.