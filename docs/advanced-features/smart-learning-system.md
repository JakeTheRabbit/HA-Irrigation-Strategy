# Smart Learning System Setup Guide

**Transform your crop steering system into an intelligent, adaptive platform** that optimizes water delivery for each zone using zero additional hardware - just smarter software!

> **Prerequisites**: Complete [installation guide](../user-guides/02-installation.md) with working automation before enabling learning features.

## 🎯 What This System Does

### Intelligent Learning Features
- **Field Capacity Detection**: Discovers true saturation point for each zone
- **Efficiency Optimization**: Learns how much water each zone actually absorbs
- **Channeling Detection**: Identifies when water finds easy paths through substrate
- **Adaptive Shot Sizing**: Calculates optimal irrigation duration based on learned patterns
- **Zone Personalities**: Each zone learns its unique characteristics over time

### How It Works Without Flow Sensors
Your pressure-compensating drippers (1.2 L/hr each) provide **exact** water measurement:
- **Input Calculation**: `1.2 L/hr × 8 drippers × duration = precise delivery`
- **Efficiency Measurement**: `VWC change ÷ theoretical change = substrate efficiency` 
- **Field Capacity Detection**: `When efficiency drops below 30% = FC reached`

**This is more accurate than cheap flow sensors!**

---

## 📋 Installation Steps

### Step 1: File Installation
```bash
# 1. Copy the learning system files to your AppDaemon apps directory
cp smart_irrigation_learning.py /config/appdaemon/apps/crop_steering/
cp learning_dashboard.py /config/appdaemon/apps/crop_steering/

# 2. Update your AppDaemon configuration
# Edit /config/appdaemon/apps/apps.yaml (already configured in this repo)

# 3. Restart AppDaemon
# Home Assistant → Settings → Add-ons → AppDaemon → Restart
```

### Step 2: System Configuration
Edit the configuration in `apps.yaml` for your specific setup:

```yaml
smart_irrigation_learning:
  # ADJUST THESE VALUES FOR YOUR SYSTEM
  zones: [1, 2, 3, 4, 5, 6]  # Your active zones
  dripper_rate: 1.2           # L/hr per dripper (confirm your specs)
  drippers_per_plant: 2       # Count your drippers
  plants_per_zone: 4          # Count your plants
  substrate_volume: 3.0       # Liters per plant (measure this!)
```

### Step 3: Verify Entity Names
Ensure your VWC sensor entity names match what the system expects:

**Expected Entity Names:**
```
sensor.crop_steering_zone_1_vwc  (preferred - from integration)
OR
sensor.zone_1_vwc_front and sensor.zone_1_vwc_back (fallback)
```

**If your entities are named differently**, edit the `get_zone_vwc()` function in the learning system to match your names.

---

## 🚀 First Run: Zone Characterization

### Phase 1: Field Capacity Detection (Week 1)

Run field capacity detection for each zone. This will take 20-60 minutes per zone:

#### Manual Service Calls
```yaml
# In Home Assistant Developer Tools → Services
service: crop_steering.detect_field_capacity
data:
  zone_id: 1
```

#### Automatic Learning
The system runs daily learning routines at 6 AM. It will automatically detect field capacity for zones that don't have it yet.

#### What Happens During FC Detection
1. System delivers small water shots (30 seconds each)
2. Waits 2 minutes for absorption between shots
3. Measures VWC increase vs. water delivered
4. When efficiency drops below 30%, FC is reached
5. Stores FC value and efficiency curve in database

### Phase 2: Efficiency Characterization (Week 2)

After field capacity is known, characterize efficiency at different moisture levels:

```yaml
service: crop_steering.characterize_zone_efficiency
data:
  zone_id: 1
```

This takes 2-4 hours per zone but provides detailed efficiency curves for optimal shot sizing.

---

## 📊 Dashboard Monitoring

### New Home Assistant Entities
The system creates monitoring entities for each zone:

```
sensor.crop_steering_zone_1_learning_status      # "learned" or "needs_learning"
sensor.crop_steering_zone_1_field_capacity       # FC percentage (e.g., 68.5%)
sensor.crop_steering_zone_1_avg_efficiency       # Recent efficiency average
sensor.crop_steering_zone_1_recommendation       # Current recommendation

sensor.crop_steering_learning_progress            # Overall system progress
sensor.crop_steering_total_irrigations_logged    # Total tracked irrigations
```

### Create Dashboard Cards
Add these to your Home Assistant dashboard:

```yaml
# Learning Progress Card
type: entities
title: Learning System Status
entities:
  - sensor.crop_steering_learning_progress
  - sensor.crop_steering_total_irrigations_logged

# Zone Intelligence Grid
type: grid
cards:
  - type: entities
    title: Zone 1 Intelligence
    entities:
      - sensor.crop_steering_zone_1_learning_status
      - sensor.crop_steering_zone_1_field_capacity
      - sensor.crop_steering_zone_1_avg_efficiency
      - sensor.crop_steering_zone_1_recommendation
  # Repeat for zones 2-6...
```

---

## 🎛️ Using the Learning System

### Available Services

#### 1. Detect Field Capacity
```yaml
service: crop_steering.detect_field_capacity
data:
  zone_id: 1  # Required
```

#### 2. Characterize Efficiency Curve
```yaml
service: crop_steering.characterize_zone_efficiency
data:
  zone_id: 1  # Required
```

#### 3. Calculate Optimal Shot Size
```yaml
service: crop_steering.calculate_optimal_shot
data:
  zone_id: 1
  target_vwc_increase: 5.0  # Optional, default 5%
```

#### 4. Get Zone Intelligence
```yaml
service: crop_steering.get_zone_intelligence
data:
  zone_id: 1
```

### Automation Examples

#### Smart Irrigation Automation
```yaml
automation:
  - alias: "Smart Irrigation Zone 1"
    trigger:
      - platform: numeric_state
        entity_id: sensor.zone_1_vwc_average
        below: 55
    condition:
      - condition: state
        entity_id: sensor.crop_steering_zone_1_learning_status
        state: "learned"
    action:
      - service: crop_steering.calculate_optimal_shot
        data:
          zone_id: 1
          target_vwc_increase: 5
      - wait_for_trigger:
          - platform: event
            event_type: crop_steering_optimal_shot_calculated
      - service: crop_steering.execute_irrigation_shot
        data:
          zone: 1
          duration_seconds: "{{ trigger.event.data.optimal_duration_seconds }}"
          shot_type: "smart_auto"
```

#### Learning Progress Notifications
```yaml
automation:
  - alias: "Learning Complete Notification"
    trigger:
      - platform: numeric_state
        entity_id: sensor.crop_steering_learning_progress
        above: 90
    action:
      - service: notify.mobile_app
        data:
          message: "🧠 Crop steering system learning is 90% complete! Your zones are now optimized."
```

---

## 📈 Expected Learning Timeline

### Week 1: Field Capacity Detection
- **Day 1-3**: Run FC detection on all zones (can do multiple simultaneously)
- **Day 4-7**: Monitor initial efficiency tracking
- **Results**: Know exact FC for each zone, stop overwatering

### Week 2: Efficiency Optimization 
- **Day 8-10**: Run efficiency characterization on 2-3 zones
- **Day 11-14**: Complete remaining zones, fine-tune parameters
- **Results**: Optimal shot sizing, 15-25% water reduction

### Month 1: Pattern Recognition
- **Week 3-4**: System learns seasonal patterns, substrate aging effects
- **Results**: Predictive irrigation, automatic parameter adjustment

### Expected Improvements
- **Water Efficiency**: 15-30% reduction in water usage
- **Plant Health**: More consistent moisture levels, reduced stress
- **Automation**: 85%+ autonomous operation with intelligent decisions
- **Troubleshooting**: Early detection of channeling, sensor issues, equipment problems

---

## 🔧 Troubleshooting

### Common Issues

#### "VWC sensor unavailable" errors
```python
# Check entity names in the get_zone_vwc() function
# Update to match your sensor naming:
avg_vwc = self.get_state(f"sensor.YOUR_ZONE_{zone_id}_vwc")
```

#### "Cannot execute irrigation" errors  
```python
# Verify your crop steering integration services are working
# Test manually first:
service: crop_steering.execute_irrigation_shot
data:
  zone: 1
  duration_seconds: 30
```

#### Learning takes too long
```yaml
# Adjust learning parameters in apps.yaml:
shot_test_duration: 15        # Shorter test shots
absorption_wait_time: 60      # Wait less between measurements
```

#### Database errors
```bash
# Check AppDaemon has write permission to create database
ls -la /config/appdaemon/apps/crop_steering/
# Should create: zone_intelligence.db
```

### Logs and Debugging
```bash
# Check AppDaemon logs
tail -f /config/appdaemon/appdaemon.log

# Look for learning system messages:
grep "Smart Irrigation Learning" /config/appdaemon/appdaemon.log
grep "Zone.*Field capacity" /config/appdaemon/appdaemon.log
```

---

## 💾 Database Information

The learning system creates a SQLite database at:
`/config/appdaemon/apps/crop_steering/zone_intelligence.db`

### Database Tables
- **`zone_profiles`**: Field capacity, efficiency curves, zone characteristics
- **`irrigation_log`**: Every irrigation with efficiency data
- **`learning_sessions`**: Learning activity tracking

### Backing Up Learning Data
```bash
# Backup your learned intelligence
cp /config/appdaemon/apps/crop_steering/zone_intelligence.db /config/backups/
```

---

## 🔄 Integration with Existing System

### Running Alongside Current Automation
The learning system can run alongside your existing master crop steering app:

```yaml
# In apps.yaml - both can be enabled:
smart_irrigation_learning:
  module: smart_irrigation_learning
  class: SmartIrrigationLearning

master_crop_steering:  # Your existing system
  module: crop_steering.master_crop_steering_app
  class: MasterCropSteeringApp
```

### Migration Path
1. **Phase 1**: Run learning system in monitoring mode (learn but don't control)
2. **Phase 2**: Use learned parameters in existing automation
3. **Phase 3**: Replace rule-based decisions with intelligent calculations

---

## 🎯 Success Metrics

### Learning System is Working When:
- ✅ All zones show "learned" status within 1-2 weeks
- ✅ Field capacity values are reasonable (65-75% for most substrates)
- ✅ Efficiency tracking shows consistent patterns
- ✅ Water usage decreases while plants remain healthy
- ✅ Recommendations match your expectations

### Performance Indicators
- **Field Capacity Accuracy**: Should be repeatable ±2% VWC
- **Efficiency Consistency**: Standard deviation < 20% for same conditions
- **Water Savings**: 15-30% reduction in total volume
- **Plant Response**: More stable VWC curves, less stress

---

## 📞 Support

### Getting Help
1. **Check Logs**: AppDaemon logs show detailed learning progress
2. **Verify Configuration**: Ensure dripper specs match your hardware
3. **Test Services**: Use Developer Tools to manually test services
4. **Monitor Entities**: Watch dashboard entities for learning progress

### Advanced Configuration
For advanced users, you can modify learning parameters:

```python
# In smart_irrigation_learning.py
self.FIELD_CAPACITY_EFFICIENCY_THRESHOLD = 0.3  # Adjust FC detection sensitivity
self.SHOT_TEST_DURATION = 30                    # Adjust test shot size
self.ABSORPTION_WAIT_TIME = 120                 # Adjust absorption wait time
```

---

## Next Steps

### For Basic Operations
- **[Daily Operation Guide](../user-guides/04-daily-operation.md)** - Learn to monitor intelligent features
- **[Troubleshooting Guide](../user-guides/05-troubleshooting.md)** - Resolve learning system issues

### For Integration
- **[LLM Integration](llm-integration.md)** - Add AI decision assistance on top of learning
- **[Entity Reference](../technical/entity-reference.md)** - All learning system entities

---

**🎉 You're Ready!** Your intelligent learning irrigation system is ready to learn each zone's personality automatically, optimize water delivery based on real plant responses, prevent overwatering with precise field capacity detection, adapt over time as substrate and roots change, and save water while improving plant health.

**All using the precision of your existing pressure-compensating drippers - no additional hardware required!**

Start with field capacity detection for one zone, watch it learn, then expand to all zones. Within 2 weeks you'll have the most intelligent home crop steering system possible!