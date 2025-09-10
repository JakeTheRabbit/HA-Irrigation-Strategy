# Comprehensive Troubleshooting Guide

**Resolve issues quickly and get your crop steering system back to optimal operation.** This guide covers everything from installation problems to advanced system diagnostics.

## 🚨 Emergency Procedures

### Critical Issue: System Won't Stop Irrigating

**Immediate Actions**:
1. **Turn off main system**: Set `switch.crop_steering_system_enabled` to OFF
2. **Disable auto irrigation**: Set `switch.crop_steering_auto_irrigation_enabled` to OFF  
3. **Manually stop pump**: Turn off `switch.your_pump_entity`
4. **Close all valves**: Turn off all `switch.zone_X_valve` entities
5. **Check physical hardware**: Inspect relays and valves for stuck positions

**Investigation Steps**:
1. Check for automation loops in AppDaemon logs
2. Look for sensor reading errors causing false triggers
3. Verify manual override states
4. Review recent configuration changes

### Critical Issue: No Irrigation During Emergency

**Symptoms**: VWC below 35%, plants showing severe stress, no automatic response

**Immediate Actions**:
1. **Manual irrigation**: 
   ```yaml
   service: crop_steering.execute_irrigation_shot
   data:
     zone: 1
     duration_seconds: 60
     shot_type: "P3_emergency"
   ```
2. **Check system status**: Verify all enable switches are ON
3. **Override if needed**: Enable manual override and irrigate manually
4. **Investigation**: Check logs for safety blocks or system errors

## 🔍 System Diagnostics

### Quick Health Check

Run this diagnostic checklist:

**1. Integration Status**
- Go to Settings → Devices & Services → Crop Steering System
- Status should show "Connected" with no errors
- All configured zones should be visible

**2. Entity Verification**
```bash
# Check these key entities exist and have recent values:
sensor.crop_steering_current_phase         # Should show P0/P1/P2/P3
sensor.crop_steering_configured_avg_vwc    # Should be 0-100%
sensor.crop_steering_configured_avg_ec     # Should be 0-8 mS/cm
switch.crop_steering_system_enabled        # Should be controllable
```

**3. AppDaemon Status (if using automation)**
- Settings → Add-ons → AppDaemon 4 → Log
- Look for: "Master Crop Steering Application initialized"
- No error messages about missing entities or configuration

**4. Hardware Test**
```yaml
# Test pump manually
service: switch.turn_on
target:
  entity_id: switch.your_pump_entity

# Wait 5 seconds, then turn off
service: switch.turn_off
target:
  entity_id: switch.your_pump_entity
```

## 🛠️ Installation Issues

### Integration Not Found After Install

**Symptoms**: Can't find "Crop Steering" when adding integration

**Solutions**:
1. **Restart Home Assistant** and wait 2-3 minutes
2. **Check installation**:
   - HACS: Verify download completed successfully
   - Manual: Verify files copied to correct location
3. **Check logs**: Settings → System → Logs for integration errors
4. **Clear browser cache** and try again

### HACS Installation Problems

**Repository not found**:
1. Verify URL: `https://github.com/JakeTheRabbit/HA-Irrigation-Strategy`
2. Ensure category is set to "Integration"
3. Try adding repository again with exact URL

**Download fails**:
1. Check internet connection
2. Verify GitHub is accessible
3. Try manual installation as fallback

### Entity Names Don't Match

**Symptoms**: Integration shows warnings about missing entities

**Solutions**:
1. **Find correct entity names**:
   - Go to Developer Tools → States
   - Search for your pump, valve, and sensor entities
2. **Reconfigure integration**:
   - Settings → Devices & Services → Crop Steering → Configure
   - Update all entity mappings to match exactly
3. **Verify entity types**:
   - Switches for pumps/valves
   - Sensors for VWC/EC readings

## 🌡️ Sensor Problems

### VWC Sensor Issues

**Readings Show "Unknown" or "None"**:
1. **Check entity exists**: Developer Tools → States
2. **Verify entity name**: Must match configuration exactly  
3. **Check sensor status**: Entity should show numeric value, not "unavailable"
4. **Physical check**: Verify sensor power and connections

**Erratic or Impossible Readings**:
```yaml
# VWC should be 0-100%. If seeing values like:
# - Negative numbers: Calibration issue
# - >100%: Calibration issue  
# - Constant 0 or 100: Sensor failure
# - Rapid fluctuations: Electrical interference
```

**Solutions**:
1. **Recalibrate sensor** with known dry/wet states
2. **Check power supply** stability
3. **Improve sensor placement** for stable readings
4. **Replace sensor** if hardware failure suspected

**Multiple Sensors Don't Match**:
```yaml
# Example: Zone 1 front shows 45%, back shows 75%
# Difference >15% indicates problem

# Check individual sensors:
sensor.zone_1_vwc_front: 45%
sensor.zone_1_vwc_back: 75%  

# System average may be unreliable:
sensor.crop_steering_vwc_zone_1: 60%
```

**Solutions**:
1. **Calibrate sensors** to same standards
2. **Check placement**: Ensure both sensors in similar soil conditions
3. **Verify sensor type**: Different sensor types may need different calibration

### EC Sensor Issues

**High Noise/Fluctuation**:
- Enable temperature compensation if available
- Check electrical grounding and shielding
- Ensure steady solution flow past sensor
- Clean sensor electrodes regularly

**Readings Drift Over Time**:
- Calibrate monthly with standard solutions (1.413 mS/cm and 12.88 mS/cm)
- Clean electrodes with appropriate cleaning solutions
- Replace probe electrodes (typically every 12-24 months)

**Temperature Compensation Issues**:
```yaml
# EC should automatically adjust for temperature
# If not working:
# 1. Check temperature sensor entity
# 2. Verify calibration includes temperature compensation
# 3. EC typically increases 2% per °C above 25°C
```

## ⚙️ System Configuration Issues

### Wrong Phase Behavior

**System Stuck in P0**:
1. **Check dryback settings**:
   - `p0_dryback_drop_percent`: May be too high (try 10-15%)
   - `p0_max_wait_time`: System will give up eventually
2. **Check VWC readings**: May not be dropping as expected
3. **Manual transition**: Force to P1 to test other phases

**System Skips Phases**:
1. **Check timing settings**:
   - Light schedule may be wrong
   - Phase durations may be too short
2. **Check AppDaemon**: Phase transitions require AppDaemon for automation
3. **Review logs**: Look for transition logic in AppDaemon logs

**Phases Change Too Fast/Slow**:
- **Too fast**: Increase minimum wait times, check thresholds
- **Too slow**: Decrease wait times, adjust targets to be more achievable

### Irrigation Frequency Issues

**Too Much Irrigation**:
1. **Reduce shot sizes**:
   - `p1_initial_shot_size`: Reduce from 2% to 1.5%
   - `p2_shot_size`: Reduce from 5% to 3-4%
2. **Raise thresholds**:
   - `p2_vwc_threshold`: Increase from 60% to 65%
3. **Check flow rates**: Verify dripper flow rate setting is accurate

**Too Little Irrigation**:
1. **Increase shot sizes**: Raise percentages gradually
2. **Lower thresholds**: Decrease VWC threshold to trigger more often
3. **Check for safety blocks**: Review logs for rejected irrigation attempts

### EC Behavior Problems

**EC Ratio Always High (>1.3)**:
```yaml
# Indicates nutrients more concentrated than target
# System should increase irrigation to flush

# Check:
sensor.crop_steering_ec_ratio: 1.5  # Too high
sensor.crop_steering_configured_avg_ec: 3.8  # Current reading
# vs target for current phase/mode

# Solutions:
# 1. Enable EC stacking if disabled
# 2. Increase shot sizes for flushing  
# 3. Lower nutrient concentration in reservoir
# 4. Check EC sensor calibration
```

**EC Ratio Always Low (<0.7)**:
```yaml
# Indicates nutrients more diluted than target
# System should reduce irrigation frequency

# Solutions:
# 1. Increase nutrient concentration in reservoir
# 2. Check for water leaks diluting nutrients
# 3. Verify EC sensor calibration
# 4. Adjust EC targets for growth stage
```

## 🔌 Hardware Troubleshooting

### Pump Issues

**Pump Won't Start**:
1. **Check relay activation**:
   - Listen for relay click when switching
   - Measure voltage at relay output
2. **Check pump power**:
   - Verify correct voltage (12V/24V/120V/240V)
   - Test pump with direct power connection
3. **Check pump condition**:
   - Look for binding or blockages
   - Verify impeller moves freely
   - Check for airlocks in lines

**Pump Runs But No Flow**:
1. **Check pump prime**: May need priming after installation
2. **Check valve positions**: Main valve must be open
3. **Look for air leaks**: In suction lines especially
4. **Check filters**: May be clogged
5. **Verify head pressure**: Pump may be undersized for system

### Valve Problems

**Valve Won't Open**:
1. **Check power**: Measure voltage at valve terminals
2. **Test valve manually**: Some valves have manual override
3. **Listen for solenoid**: Should hear click when energizing
4. **Check coil resistance**: Typically 20-200 ohms
5. **Look for debris**: In valve seat or mechanism

**Valve Won't Close**:
1. **Check return spring**: May be broken or weak
2. **Clean valve seat**: Debris may prevent sealing
3. **Check power**: Valve may need power to stay closed
4. **Replace diaphragm**: May be torn or warped

### Communication Issues

**ESPHome Device Offline**:
1. **Check WiFi signal**: Device may be too far from router
2. **Verify power**: Stable 5V/3.3V supply required
3. **Check for interference**: Other 2.4GHz devices
4. **Restart device**: Power cycle ESP32/ESP8266
5. **Check logs**: ESPHome logs show connection issues

**Entities Show "Unavailable"**:
1. **Check device status**: Settings → Devices & Services → ESPHome
2. **Verify entity names**: Must match ESPHome configuration
3. **Check Home Assistant connectivity**: Device must reach HA API
4. **Restart integration**: May need to reload ESPHome integration

## 📊 Performance Issues

### AppDaemon Problems

**AppDaemon Won't Start**:
1. **Check configuration**:
   ```yaml
   # Common issues in appdaemon.yaml:
   ha_url: http://192.168.1.100:8123  # Wrong IP
   token: your_long_lived_token_here   # Invalid token
   time_zone: America/New_York         # Wrong timezone
   ```

2. **Verify token**: Create new long-lived access token
3. **Check network**: AppDaemon must reach Home Assistant
4. **Review logs**: Settings → Add-ons → AppDaemon 4 → Log

**AppDaemon Starts But Crop Steering Not Working**:
1. **Check apps.yaml**: Verify crop steering app is enabled
2. **Check file locations**: Apps must be in correct directory
3. **Check entity dependencies**: AppDaemon needs all configured entities
4. **Review Python errors**: Look for import or syntax errors

### LLM Integration Issues (If Enabled)

**LLM Decisions Not Working**:
1. **Check API key**: Verify OpenAI key is valid and has credit
2. **Check budget**: May have exceeded daily spending limit
3. **Check confidence**: LLM decisions below threshold use rule-based logic
4. **Review logs**: AppDaemon logs show LLM API calls and responses

**High LLM Costs**:
1. **Check call frequency**: May be calling too often
2. **Verify caching**: Cache hit rate should be >50%
3. **Adjust model**: Use gpt-5-nano for routine decisions
4. **Set daily limits**: Strict budget controls prevent overspending

## 🔧 Maintenance Procedures

### Daily Checks
1. **System status**: All enable switches ON, no error messages
2. **Sensor readings**: Values within expected ranges
3. **Phase progression**: Should advance through daily cycle
4. **Irrigation events**: Appropriate frequency and duration

### Weekly Maintenance
1. **Sensor validation**: Cross-check readings for accuracy
2. **Parameter tuning**: Adjust based on plant response
3. **Hardware inspection**: Visual check of all components
4. **Performance review**: Analyze water usage and efficiency

### Monthly Procedures
1. **EC sensor calibration**: Use fresh standard solutions
2. **Configuration backup**: Export settings and entity mappings
3. **Software updates**: Check for integration updates in HACS
4. **Deep cleaning**: Clean sensor electrodes and housings

## 📋 Diagnostic Data Collection

### When Requesting Help

**Include this information**:
1. **System details**:
   - Home Assistant version
   - Integration version
   - AppDaemon version (if used)
   - Hardware setup (sensors, pumps, valves)

2. **Problem description**:
   - What should happen vs what actually happens
   - When problem started
   - What troubleshooting steps already tried

3. **Configuration**:
   - Number of zones
   - Entity mappings
   - Key parameter settings

4. **Logs**:
   ```bash
   # Collect these logs:
   # 1. Home Assistant Core logs (Settings → System → Logs)
   # 2. AppDaemon logs (if used)
   # 3. ESPHome logs (if used)
   # 4. Recent entity state changes
   ```

### Log Analysis

**Key things to look for**:
1. **Error messages**: Usually indicate specific problems
2. **Entity state changes**: Track irrigation events and sensor updates
3. **Service calls**: Verify commands are being executed
4. **Timing patterns**: Look for unexpected delays or rapid triggering

## 🆘 When to Get Help

### Self-Service First
1. **Follow this guide** systematically
2. **Check logs** for specific error messages
3. **Test basic functionality** (manual irrigation, sensor readings)
4. **Review recent changes** that might have caused issues

### Community Support
- **GitHub Issues**: https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/issues
- **Home Assistant Community Forum**: Search "Crop Steering"
- **Discord**: Home Assistant Discord server, #custom-components channel

### Emergency Support
If your plants are at risk:
1. **Switch to manual mode** immediately
2. **Use basic irrigation** to maintain plants
3. **Ask for urgent help** on Discord with "URGENT" in message
4. **Provide diagnostic data** as outlined above

---

**🔧 Remember**: Most issues are configuration-related rather than bugs. Work through this guide systematically, and don't hesitate to ask for help if you get stuck!