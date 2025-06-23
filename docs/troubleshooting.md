# 🔧 Troubleshooting Guide

This comprehensive guide helps resolve common issues with the Advanced AI Crop Steering System.

## 🚨 Emergency Procedures

### Immediate Actions for Critical Issues

#### System Not Irrigating During Emergency

**Symptoms:**
- VWC below 35% (critical level)
- No automatic irrigation response
- Plants showing stress signs

**Immediate Actions:**
1. **Manual irrigation**: Turn on pump and zones manually
2. **Check hardware**: Verify pump and valve operation
3. **Disable automation**: Prevent conflicting commands
4. **Monitor plants**: Watch for recovery signs

**Diagnostic Steps:**
```bash
# Check system status
# Go to Developer Tools > States
sensor.crop_steering_system_state: should be "active"

# Check emergency thresholds
sensor.crop_steering_fused_vwc: should show current VWC
sensor.crop_steering_ml_irrigation_need: should be >0.9

# Manual hardware test
service: switch.turn_on
target:
  entity_id: switch.f1_irrigation_pump_master_switch
```

#### Runaway Irrigation (Won't Stop)

**Symptoms:**
- Irrigation running continuously
- VWC above target ranges
- System not responding to automation

**Immediate Actions:**
1. **Emergency stop**: Turn off main electrical supply
2. **Manual shutoff**: Close manual valves if available
3. **Disable system**: Turn off crop steering automation
4. **Check for hardware faults**: Inspect relays and valves

**Recovery Steps:**
```bash
# Emergency shutdown all irrigation
service: switch.turn_off
target:
  entity_id: 
    - switch.f1_irrigation_pump_master_switch
    - switch.espoe_irrigation_relay_1_2
    - switch.f1_irrigation_relays_relay_1
    - switch.f1_irrigation_relays_relay_2
    - switch.f1_irrigation_relays_relay_3

# Disable automation
service: switch.turn_off
target:
  entity_id: switch.crop_steering_system_enabled
```

## 🔍 Diagnostic Procedures

### System Health Check

Use this checklist to diagnose system status:

#### 1. Integration Status
```bash
# Check integration is loaded
# Settings > Devices & Services > Crop Steering System
# Should show "Configured" status

# Verify entities exist
# Developer Tools > States
# Filter by "crop_steering" - should show multiple entities
```

#### 2. AppDaemon Status
```bash
# Check AppDaemon logs
tail -f /addon_configs/a0d7b954_appdaemon/logs/appdaemon.log

# Look for startup messages:
# "Master Crop Steering Application with Advanced AI Features initialized!"
# "Advanced AI modules initialized successfully"

# Check specific app logs
tail -f /addon_configs/a0d7b954_appdaemon/logs/crop_steering_master.log
tail -f /addon_configs/a0d7b954_appdaemon/logs/crop_steering_dashboard.log
```

#### 3. Sensor Validation
```bash
# Check all sensors are reporting
# Developer Tools > States
# Look for recent timestamps and valid values:

sensor.vwc_r1_front: 45-70% (valid range)
sensor.ec_r1_front: 2.0-8.0 mS/cm (valid range)
sensor.grow_room_temperature: 15-35°C (valid range)

# Check for "unavailable" or "unknown" states
```

#### 4. Hardware Status
```bash
# Test hardware manually
# Developer Tools > Services

# Test pump
service: switch.turn_on
target:
  entity_id: switch.f1_irrigation_pump_master_switch

# Verify pump actually turns on (check physical hardware)
# Turn off after test:
service: switch.turn_off
target:
  entity_id: switch.f1_irrigation_pump_master_switch
```

## 🤖 AI System Issues

### ML Models Not Learning

**Symptoms:**
- ML confidence stays below 0.6
- No model retraining messages in logs
- Predictions remain at 0.5 (default)

**Causes:**
1. **Insufficient training data**: Less than 50 samples
2. **Poor data quality**: Too many outliers or missing values
3. **Feature extraction issues**: Sensor data not being processed
4. **Python dependencies missing**: ML libraries not installed

**Solutions:**

**Check training data:**
```python
# Access through AppDaemon logs
# Look for messages like:
# "ML models retrained - R² performance: 0.850"
# "Training samples: X" (should be >50)

# Check ML status entity
sensor.crop_steering_ml_confidence: should improve over time
sensor.crop_steering_ml_model_accuracy: should increase with training
```

**Reset ML models if needed:**
```python
# This would need to be done through AppDaemon
# Check logs for reset confirmation
# ML models will restart learning from scratch
```

**Verify AppDaemon dependencies:**
```bash
# Dependencies are automatically managed by the AppDaemon add-on
# Check AppDaemon logs for any missing dependency errors
# Restart AppDaemon add-on if needed through Home Assistant UI
```

### Sensor Fusion Problems

**Symptoms:**
- Fused VWC/EC values showing as None
- High outlier rates (>30%)
- Sensor health degrading rapidly

**Causes:**
1. **Sensor calibration drift**: Sensors reading incorrectly
2. **Electrical interference**: EMI affecting readings
3. **Network issues**: Sensors disconnecting frequently
4. **Threshold settings**: Fusion parameters too sensitive

**Solutions:**

**Check sensor health:**
```bash
# Review sensor health report
sensor.crop_steering_sensor_health: shows healthy sensor count

# Check individual sensor reliability
# Look for entities like:
sensor.vwc_r1_front_reliability: should be >0.7
```

**Calibrate sensors:**
```bash
# Cross-validate sensors against known standards
# All VWC sensors in same substrate should read similarly
# EC sensors should match when measuring same solution

# Check for obvious outliers:
sensor.vwc_r1_front: 45%
sensor.vwc_r1_back: 67%  # Potential calibration issue
```

**Adjust fusion parameters:**
```python
# If sensors are frequently marked as outliers
# Increase outlier threshold in sensor fusion settings
# This would be done through AppDaemon configuration
```

### Dryback Detection Issues

**Symptoms:**
- No dryback events detected
- Confidence scores below 0.5
- Irrigation timing seems random

**Causes:**
1. **Insufficient VWC variation**: Too much irrigation, no dryback
2. **Noisy sensor data**: Too much fluctuation to detect patterns
3. **Short data history**: Not enough data for pattern recognition
4. **Incorrect calibration**: Sensors not accurately tracking substrate moisture

**Solutions:**

**Verify dryback is occurring:**
```bash
# Check VWC trends manually
# VWC should show declining patterns between irrigations
# Look for sawtooth pattern: irrigation spike → gradual decline

# Check current dryback status
sensor.crop_steering_dryback_percentage: should show >0 when drying
binary_sensor.crop_steering_dryback_in_progress: should cycle on/off
```

**Improve data quality:**
```bash
# Reduce irrigation frequency temporarily
# Allow longer dryback periods (20-30 minutes between shots)
# Ensure stable environment (minimal disturbances)
```

**Check detection parameters:**
```python
# Dryback detection requires:
# - Minimum 10 data points
# - Clear peak/valley patterns
# - Stable sensor readings
```

## 🔌 Hardware Troubleshooting

### Sensor Issues

#### VWC Sensor Problems

**Erratic Readings:**
```bash
Symptoms: Wild fluctuations, impossible values
Causes: Poor calibration, substrate movement, electrical interference
Solutions:
- Recalibrate in known moisture levels
- Ensure stable sensor placement
- Check electrical connections
- Move away from electrical interference sources
```

**Stuck Readings:**
```bash
Symptoms: Same value for extended periods
Causes: Sensor failure, poor connection, calibration drift
Solutions:
- Check physical connections
- Test sensor with multimeter
- Replace if confirmed faulty
- Verify power supply voltage
```

**Inconsistent Between Sensors:**
```bash
Symptoms: Large differences between sensors in same zone
Causes: Different calibrations, uneven substrate, placement issues
Solutions:
- Cross-calibrate all sensors
- Ensure uniform substrate mixture
- Check sensor placement depth/position
- Replace outlier sensors
```

#### EC Sensor Problems

**High Noise/Fluctuation:**
```bash
Symptoms: Constant variation, noisy readings
Causes: Temperature effects, poor electrical isolation, flow issues
Solutions:
- Enable temperature compensation
- Check electrical grounding
- Ensure steady solution flow
- Clean sensor electrodes
```

**Drift Over Time:**
```bash
Symptoms: Gradual reading changes, calibration loss
Causes: Electrode fouling, reference drift, aging
Solutions:
- Regular calibration with standards
- Clean electrodes with appropriate solutions
- Replace aging sensors
- Use high-quality calibration solutions
```

### Irrigation Hardware

#### Pump Issues

**Pump Won't Start:**
```bash
Check: Power supply, relay operation, pump condition
Test: Manual relay activation, voltage at pump
Solutions:
- Verify 24VAC supply
- Test relay with multimeter
- Check pump for mechanical binding
- Inspect wiring connections
```

**Pump Runs But No Pressure:**
```bash
Check: Prime status, valve positions, blockages
Test: Manual valve operation, flow observation
Solutions:
- Prime pump system
- Check for air leaks
- Clear blockages in lines
- Verify valve operations
```

#### Valve Problems

**Valve Won't Open:**
```bash
Check: Power supply, solenoid condition, manual override
Test: Voltage at valve, manual activation
Solutions:
- Check 24VAC supply to valve
- Test solenoid coil resistance
- Use manual override if available
- Replace faulty solenoid
```

**Valve Won't Close:**
```bash
Check: Debris in valve seat, spring failure, electrical issues
Test: Manual closure, power cycling
Solutions:
- Clean valve seat and diaphragm
- Check return spring
- Power cycle valve
- Replace if mechanically failed
```

## 📡 Network and Connectivity

### Sensor Communication Issues

**Sensors Going Offline:**
```bash
Symptoms: "unavailable" or "unknown" states
Causes: WiFi issues, power problems, device failures
Solutions:
- Check WiFi signal strength
- Verify power supply stability
- Restart sensor devices
- Check Home Assistant device status
```

**Intermittent Connections:**
```bash
Symptoms: Sporadic data loss, reconnection messages
Causes: Network congestion, interference, marginal signal
Solutions:
- Improve WiFi coverage
- Reduce 2.4GHz interference
- Use dedicated IoT network
- Consider wired connections
```

### Home Assistant Integration

**Entities Not Updating:**
```bash
Check: Integration status, entity configuration, polling intervals
Test: Manual entity refresh, restart integration
Solutions:
- Restart Crop Steering integration
- Check entity polling frequency
- Verify entity names in configuration
- Check Home Assistant logs for errors
```

**AppDaemon Communication:**
```bash
Check: AppDaemon connection to HA, token validity, network access
Test: AppDaemon logs, manual API calls
Solutions:
- Verify long-lived access token
- Check network connectivity
- Restart AppDaemon
- Review AppDaemon configuration
```

## ⚙️ Configuration Issues

### Integration Configuration

**Wrong Entity Names:**
```bash
Symptoms: Entities not found, integration errors
Check: Entity IDs in Home Assistant, spelling/case sensitivity
Solutions:
- Use Developer Tools > States to find correct names
- Update integration configuration
- Check for entity naming changes
- Verify entity domains (sensor, switch, etc.)
```

**Missing Configuration Options:**
```bash
Symptoms: Expected settings not available, limited functionality
Check: Integration version, configuration completeness
Solutions:
- Update to latest integration version
- Reconfigure integration from scratch
- Check for configuration schema changes
- Review installation documentation
```

### AppDaemon Configuration

**Apps Not Loading:**
```bash
Check: apps.yaml syntax, module paths, dependencies
Test: AppDaemon startup logs, manual app loading
Solutions:
- Validate YAML syntax
- Check file permissions
- Verify Python dependencies
- Review module import paths
```

**Incorrect Parameters:**
```bash
Symptoms: Unexpected behavior, poor performance
Check: Parameter values, units, ranges
Solutions:
- Review parameter documentation
- Use recommended default values
- Gradually adjust from defaults
- Monitor system response to changes
```

## 📊 Performance Issues

### System Running Slowly

**High CPU Usage:**
```bash
Causes: Frequent updates, complex calculations, insufficient resources
Solutions:
- Reduce update intervals
- Limit data history retention
- Optimize sensor polling
- Upgrade hardware if needed
```

**Memory Issues:**
```bash
Symptoms: System slowdowns, app crashes, swap usage
Causes: Large data sets, memory leaks, insufficient RAM
Solutions:
- Reduce data retention periods
- Clear old training data
- Restart AppDaemon periodically
- Add more RAM if possible
```

**Network Latency:**
```bash
Symptoms: Delayed responses, timeouts, communication errors
Causes: Network congestion, poor WiFi, interference
Solutions:
- Optimize network infrastructure
- Use wired connections where possible
- Reduce network traffic
- Upgrade network equipment
```

### AI Performance Issues

**Slow ML Processing:**
```bash
Causes: Large datasets, complex models, insufficient CPU
Solutions:
- Reduce model complexity
- Limit training data size
- Increase retrain intervals
- Use more powerful hardware
```

**Poor Prediction Accuracy:**
```bash
Causes: Insufficient training, poor data quality, wrong parameters
Solutions:
- Allow longer learning period
- Improve sensor calibration
- Increase training data quantity
- Adjust model parameters
```

## 🛠️ Maintenance Procedures

### Regular Maintenance Schedule

#### Daily Checks
- **System status**: Verify all components active
- **Sensor readings**: Check for reasonable values
- **Irrigation events**: Confirm proper operation
- **Error logs**: Review for any issues

#### Weekly Maintenance
- **Sensor calibration**: Cross-check sensor accuracy
- **Performance review**: Analyze efficiency metrics
- **Data backup**: Export important system data
- **Hardware inspection**: Visual check of all components

#### Monthly Procedures
- **Deep calibration**: Full sensor recalibration
- **Software updates**: Check for system updates
- **Performance optimization**: Tune system parameters
- **Documentation update**: Record any changes

### Preventive Measures

**Sensor Longevity:**
- **Regular cleaning**: Keep sensors free of debris
- **Stable environment**: Minimize vibration and temperature swings
- **Quality power**: Use stable, clean power supplies
- **Proper installation**: Follow manufacturer guidelines

**System Reliability:**
- **Backup configuration**: Export system settings regularly
- **Redundancy**: Use multiple sensors where possible
- **Monitoring**: Set up comprehensive alerting
- **Documentation**: Keep detailed change logs

## 📞 Getting Help

### Self-Service Resources

**Documentation:**
- [Installation Guide](installation_guide.md)
- [AI Operation Guide](ai_operation_guide.md)
- [Dashboard Guide](dashboard_guide.md)

**Diagnostic Tools:**
- Home Assistant logs
- AppDaemon logs
- Integration device page
- Developer Tools

### Community Support

**GitHub Issues:**
- [Report bugs](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/issues)
- Search existing issues
- Provide detailed error logs
- Include system configuration

**Forums:**
- Home Assistant Community
- AppDaemon Discord
- Reddit r/homeassistant

### Professional Support

**Paid Support Options:**
- System diagnosis and optimization
- Custom configuration assistance
- Hardware troubleshooting
- Training and education

**When to Seek Professional Help:**
- Repeated hardware failures
- Persistent software issues
- Performance optimization needs
- Custom feature requirements

## 📋 Quick Reference

### Common Entity Names
```yaml
System Status:
- sensor.crop_steering_system_state
- sensor.crop_steering_current_phase
- sensor.crop_steering_current_decision

AI Status:
- sensor.crop_steering_ml_confidence
- sensor.crop_steering_ml_irrigation_need
- sensor.crop_steering_sensor_health

Measurements:
- sensor.crop_steering_fused_vwc
- sensor.crop_steering_fused_ec
- sensor.crop_steering_dryback_percentage

Hardware:
- switch.f1_irrigation_pump_master_switch
- switch.espoe_irrigation_relay_1_2
- switch.f1_irrigation_relays_relay_1
```

### Emergency Contacts
```yaml
# Replace with your actual contact information
System Administrator: your-admin@email.com
Hardware Technician: tech-support@company.com
Emergency Shutdown: Physical main breaker location
```

### Log File Locations
```bash
Home Assistant: /config/home-assistant.log
AppDaemon: /addon_configs/a0d7b954_appdaemon/logs/appdaemon.log
Crop Steering: /addon_configs/a0d7b954_appdaemon/logs/crop_steering_master.log
Dashboard: /addon_configs/a0d7b954_appdaemon/logs/crop_steering_dashboard.log
```

---

**Remember**: Most issues can be resolved by checking logs, verifying configuration, and ensuring all components are properly connected and calibrated. When in doubt, start with the basics and work systematically through the diagnostic procedures.