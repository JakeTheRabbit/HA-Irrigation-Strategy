# Daily Operation Guide

**Master the day-to-day monitoring and management** of your crop steering system. This guide covers dashboard interpretation, routine maintenance, and optimization techniques.

> **Prerequisites**: Complete [getting started guide](01-getting-started.md) and have your system running for at least 24 hours.

## Dashboard Overview

### Key Indicators to Monitor

**System Status Panel**
```yaml
# Critical indicators:
sensor.crop_steering_current_phase         # P0/P1/P2/P3/Manual
switch.crop_steering_system_enabled        # Master on/off
switch.crop_steering_auto_irrigation_enabled  # Automation on/off
sensor.crop_steering_next_irrigation_time  # When next shot expected
```

**Zone Health Summary** (per zone)
```yaml
sensor.crop_steering_zone_1_status         # Optimal/Dry/Saturated/Error
sensor.crop_steering_vwc_zone_1            # Current moisture %
sensor.crop_steering_ec_zone_1             # Current nutrients mS/cm
sensor.crop_steering_zone_1_last_irrigation # Last irrigation time
```

**System Performance**
```yaml
sensor.crop_steering_configured_avg_vwc    # Average moisture across zones
sensor.crop_steering_configured_avg_ec     # Average nutrients across zones
sensor.crop_steering_ec_ratio              # Current/target EC ratio
sensor.crop_steering_water_usage_daily     # Daily water consumption
```

### Understanding Phase Displays

**Phase Indicator Colors** (if using custom dashboard):
- 🟡 **P0 (Dryback)**: Waiting for substrate to dry - normal in morning
- 🟢 **P1 (Ramp-Up)**: Building moisture back up - progressive shots
- 🔵 **P2 (Maintenance)**: Normal operation - threshold-based irrigation
- 🟠 **P3 (Pre-Lights-Off)**: Winding down - emergency irrigation only
- 🔴 **Manual**: Automation disabled - manual control active

## Daily Monitoring Routine

### Morning Check (Within 1 hour of lights-on)

1. **Verify system status**:
   - All enable switches should be ON
   - Current phase should be P0 (Dryback)
   - No error messages or warnings

2. **Check overnight conditions**:
   - Review VWC drop from previous night
   - Ensure P3 phase operated correctly
   - Look for any emergency irrigation events

3. **Sensor validation**:
   ```yaml
   # Reasonable ranges for healthy system:
   VWC: 30-80% (varies by growth stage)
   EC: 1.5-4.0 mS/cm (varies by nutrients)
   EC Ratio: 0.7-1.3 (close to 1.0 ideal)
   ```

### Midday Check (During P2 phase)

1. **Monitor irrigation frequency**:
   - P2 shots should occur when VWC drops below threshold
   - Frequency varies by growth stage and environmental conditions
   - Typically every 30-180 minutes in P2

2. **Check water usage**:
   - Daily usage should be consistent day-to-day
   - Sudden increases may indicate leaks or sensor issues
   - Sudden decreases may indicate blockages

3. **Observe plant response**:
   - Plants should appear healthy and unstressed
   - Slight wilting before irrigation is normal in generative mode
   - Excessive wilting indicates inadequate irrigation

### Evening Check (Before lights-off)

1. **Verify P3 transition**:
   - System should enter P3 phase 60-90 minutes before lights-off
   - Irrigation frequency should decrease significantly
   - Emergency threshold should be lower (typically 35-40% VWC)

2. **Review daily performance**:
   - Total water usage for the day
   - Number of irrigation events per zone
   - Any alarms or unusual events

## Interpreting Sensor Readings

### VWC (Moisture) Patterns

**Normal Daily Pattern**:
```
Morning:    65% → Dryback → 50% (P0)
Mid-morning: 50% → Ramp-up → 65% (P1)
Day:        65% ↔ 60% ↔ 65% (P2 maintenance)
Evening:    65% → Gradual decline overnight
```

**Concerning Patterns**:
- **Rapid VWC loss**: May indicate leaks or sensor calibration issues
- **VWC not recovering**: Insufficient irrigation or blockages
- **VWC too stable**: Over-irrigation or sensor stuck
- **Erratic readings**: Sensor placement or calibration issues

### EC (Nutrient) Trends

**Healthy EC Patterns**:
- Stable readings throughout the day
- Gradual increase as nutrients concentrate
- EC ratio staying between 0.8-1.2

**Problem Indicators**:
```yaml
EC Ratio > 1.3:  # Nutrients too concentrated
  Action: Increase irrigation frequency or shot size
  
EC Ratio < 0.7:  # Nutrients too diluted  
  Action: Decrease irrigation frequency or increase nutrient strength

EC fluctuating wildly:  # Sensor or mixing issues
  Action: Check sensor calibration and nutrient delivery system
```

## Routine Adjustments

### Environmental Response

**Hot/Dry Days**:
- VWC may drop faster than normal
- May need to temporarily lower P2 threshold by 5%
- Monitor for emergency irrigation in P3

**Cool/Humid Days**:
- VWC may stay elevated longer
- Consider raising P2 threshold by 5%
- Reduce P0 dryback requirement slightly

**Seasonal Changes**:
- Adjust targets gradually as plants mature
- Monitor for changing water consumption patterns
- Update growth stage settings as appropriate

### Growth Stage Transitions

**Switching to Generative Mode**:
1. Lower VWC targets by 5-10%
2. Increase EC targets by 0.5-1.0 mS/cm
3. Extend P3 duration (more time before lights-off)
4. Monitor plant stress levels closely

**Switching to Vegetative Mode**:
1. Raise VWC targets by 5-10%
2. Decrease EC targets by 0.5-1.0 mS/cm
3. Reduce P3 duration
4. Increase P2 irrigation frequency

## Performance Optimization

### Weekly Review Process

**Data Collection** (every Sunday):
1. **Water usage**: Total consumption per zone
2. **Irrigation events**: Count and timing per zone
3. **Phase timing**: Average duration of each phase
4. **Sensor stability**: Check for drift or anomalies

**Analysis Questions**:
- Are zones using similar amounts of water?
- Is irrigation frequency appropriate for growth stage?
- Are phase transitions happening at expected times?
- Do sensor readings correlate with visual plant assessment?

### Parameter Tuning

**Common Adjustments**:

```yaml
# Too much water (plants look overwatered):
p2_shot_size: 5% → 4%           # Smaller shots
p2_vwc_threshold: 60% → 65%     # Irrigate less often
p1_target_vwc: 65% → 60%        # Lower target

# Too little water (plants look stressed):
p2_shot_size: 5% → 6%           # Larger shots  
p2_vwc_threshold: 60% → 55%     # Irrigate more often
p1_target_vwc: 65% → 70%        # Higher target

# EC management issues:
ec_target_veg_p2: 2.0 → 2.2     # Increase nutrient target
p2_ec_high_threshold: 1.3 → 1.2 # More aggressive flushing
```

**Testing Changes**:
1. Make one small change at a time
2. Monitor for 2-3 days before additional changes
3. Document what you changed and why
4. Track plant response and sensor data

## Manual Interventions

### When to Override

**Temporary Override Situations**:
- Maintenance requiring system shutdown
- Unusual environmental conditions
- Testing new parameters
- Emergency plant care

**Override Procedures**:

```yaml
# Temporary zone override (auto-disables after timeout)
service: crop_steering.set_manual_override
data:
  zone: 1
  timeout_minutes: 60
  enable: true

# Manual irrigation shot
service: crop_steering.execute_irrigation_shot
data:
  zone: 1
  duration_seconds: 90
  shot_type: "manual"

# Emergency system shutdown
switch.crop_steering_system_enabled: off
```

### Maintenance Windows

**Weekly Maintenance** (15 minutes):
1. Visual inspection of all plants
2. Check sensor placement and cleanliness
3. Verify dripper flow rates
4. Test manual irrigation on each zone

**Monthly Maintenance** (30 minutes):
1. Calibrate EC sensors with standard solutions
2. Clean all sensor probes
3. Check all electrical connections
4. Review and backup configuration settings

## Troubleshooting Common Issues

### Irrigation Not Happening

**Diagnostic Steps**:
1. **Check current phase**: System may be in P0 waiting for dryback
2. **Verify enables**: System, auto-irrigation, and zone enables must be ON
3. **Check thresholds**: VWC may be above irrigation threshold
4. **Review logs**: Look for safety blocks or error conditions

### Excessive Irrigation

**Diagnostic Steps**:
1. **Check sensor calibration**: May be reading low and triggering constantly
2. **Verify thresholds**: May be set too high causing frequent irrigation
3. **Look for leaks**: Physical leaks can cause constant VWC drop
4. **Check for automation loops**: AppDaemon issues can cause rapid triggering

### Sensor Problems

**VWC Sensor Issues**:
- **Readings stuck**: Check physical sensor placement and connections
- **Erratic readings**: Verify stable power supply and sensor calibration
- **No readings**: Check entity names and sensor power

**EC Sensor Issues**:
- **Drift over time**: Requires monthly calibration with standard solutions
- **Inconsistent readings**: Clean electrodes and check temperature compensation
- **Out of range values**: Verify calibration and check for sensor damage

## Advanced Monitoring

### Trend Analysis

**Weekly Trend Reports**:
- Plot daily water usage over time
- Track average VWC and EC by zone
- Monitor irrigation efficiency trends
- Look for seasonal patterns

**Performance Metrics**:
```yaml
# Efficiency calculations:
Water Efficiency = VWC gained / Liters used
Irrigation Efficiency = Target VWC achieved / Total shots
Phase Efficiency = Time in optimal VWC range / Total time
```

### Alert Configuration

**Recommended Alerts** (using Home Assistant automations):
- VWC below emergency threshold for >30 minutes
- EC ratio outside 0.6-1.4 range for >2 hours
- System disabled unexpectedly
- Daily water usage >150% of average
- Sensor offline for >15 minutes

### Data Export

**For Advanced Analysis**:
1. Use Home Assistant's built-in data export
2. Export daily summaries to CSV
3. Create custom dashboards in Grafana
4. Share data with crop steering community

## Best Practices

### Daily Habits
- Check system status within 1 hour of lights-on
- Monitor during transition periods (P0→P1, P2→P3)
- Note any unusual plant behavior or environmental conditions
- Document any manual interventions

### Documentation
- Keep a simple log of parameter changes
- Note environmental conditions affecting irrigation
- Track plant development stages
- Record any issues and their solutions

### Continuous Improvement
- Start conservative and adjust gradually
- Make only one change at a time
- Give changes 2-3 days to show effects
- Learn from the crop steering community

---

**📊 Daily Operation Mastery!** With consistent monitoring and gradual optimization, your crop steering system will become increasingly effective at maintaining optimal growing conditions.