# Getting Started Guide

**Welcome to precision crop steering!** This guide will help you understand the system, configure it for your setup, and start your first irrigation cycles with confidence.

> **Just installed?** Make sure you've completed the [15-minute quickstart](../installation/quickstart.md) first.

## Understanding Crop Steering

### What is Crop Steering?
Crop steering is a precision irrigation technique that **controls plant growth by managing water stress**. By carefully timing irrigation based on moisture (VWC) and nutrient concentration (EC), you can steer plants toward:

- **Vegetative growth** (bigger plants, more leaves)
- **Generative growth** (more flowers, better fruit production)

### The Science Behind It
- **Controlled drought stress** stimulates beneficial plant responses
- **Precise nutrient delivery** prevents waste and salt buildup
- **Synchronized light/water cycles** optimize photosynthesis
- **Data-driven decisions** replace guesswork

## Your First Configuration

### Step 1: Set Your Light Schedule

The entire system revolves around your grow light timing:

1. **Find these entities**:
   - `number.crop_steering_lights_on_hour`
   - `number.crop_steering_lights_off_hour`

2. **Set your schedule** (24-hour format):
   - Example: Lights on at 6 AM = 6
   - Example: Lights off at 10 PM = 22

### Step 2: Configure Your Growing Medium

1. **Set pot volume** (`number.crop_steering_substrate_volume`):
   - Enter volume in liters
   - This affects shot duration calculations

2. **Set dripper details**:
   - `number.crop_steering_dripper_flow_rate`: Flow rate per dripper (L/hr)
   - `number.crop_steering_drippers_per_plant`: Number of drippers per plant

### Step 3: Choose Your Growth Stage

1. **Select crop type** (`select.crop_steering_crop_type`):
   - Cannabis varieties available
   - Other crops: Tomato, Lettuce, Basil
   - Or choose "Custom" for manual control

2. **Set growth stage** (`select.crop_steering_growth_stage`):
   - **Vegetative**: For growing bigger plants
   - **Generative**: For flowering/fruiting

3. **Set steering mode** (`select.crop_steering_steering_mode`):
   - **Vegetative**: Higher moisture, lower EC
   - **Generative**: Lower moisture, higher EC for stress

## Understanding the 4-Phase Cycle

### Phase Overview

Your system follows this daily pattern:

```
🌅 P0 Dryback → 🌱 P1 Ramp-Up → 💧 P2 Maintenance → 🌙 P3 Pre-Lights-Off
```

### P0 - Morning Dryback (🌅)
**What happens**: System waits for substrate to dry down

**Purpose**: Controlled drought stress stimulates root growth and beneficial plant responses

**Duration**: 30 minutes to 3 hours (depending on settings)

**Key settings**:
- `p0_dryback_drop_percent`: How much moisture to lose (15-20%)
- `p0_min_wait_time`: Minimum wait even if dryback reached
- `p0_max_wait_time`: Maximum wait before giving up

### P1 - Ramp-Up (🌱)
**What happens**: Progressive irrigation shots build moisture back up

**Purpose**: Gradually return to optimal moisture without shocking plants

**Duration**: Usually 30-90 minutes

**Key settings**:
- `p1_initial_shot_size`: Starting shot size (2%)
- `p1_shot_increment`: How much each shot increases (0.5%)
- `p1_target_vwc`: Target moisture to reach (65% veg, 60% gen)

### P2 - Maintenance (💧)
**What happens**: Threshold-based irrigation maintains optimal conditions

**Purpose**: Keep plants in optimal zone all day

**Duration**: Most of the day (8-12 hours)

**Key settings**:
- `p2_vwc_threshold`: When to irrigate (60% veg, 55% gen)
- `p2_shot_size`: Fixed shot size (5%)
- `p2_ec_high_threshold`: Adjust threshold if EC too high

### P3 - Pre-Lights-Off (🌙)
**What happens**: Reduced irrigation before lights turn off

**Purpose**: Prepare plants for night period, avoid excess moisture

**Duration**: 60-90 minutes before lights off

**Key settings**:
- `p3_veg_last_irrigation`: Stop normal irrigation 60 min before lights off
- `p3_gen_last_irrigation`: Stop normal irrigation 90 min before lights off
- `p3_emergency_vwc_threshold`: Only irrigate if VWC drops below 40%

## Your First Day

### Before You Start

1. **Verify sensor readings**:
   - Check `sensor.crop_steering_configured_avg_vwc` shows reasonable value (30-80%)
   - Check `sensor.crop_steering_configured_avg_ec` shows reasonable value (1-6 mS/cm)

2. **Start conservatively**:
   - Use default settings first
   - Monitor closely for the first few cycles
   - Make small adjustments based on plant response

### Monitoring Your First Cycle

**Watch these key indicators**:

1. **Current phase** (`sensor.crop_steering_current_phase`):
   - Should change automatically throughout the day

2. **VWC levels** (`sensor.crop_steering_configured_avg_vwc`):
   - Should drop during P0
   - Should rise during P1
   - Should maintain stable during P2

3. **EC ratio** (`sensor.crop_steering_ec_ratio`):
   - Close to 1.0 is ideal
   - Above 1.3 = nutrients too concentrated
   - Below 0.7 = nutrients too diluted

4. **Next irrigation** (`sensor.crop_steering_next_irrigation_time`):
   - Shows when system expects to irrigate next

### Manual Override When Needed

**Temporary control** (1-1440 minutes):
```yaml
service: crop_steering.set_manual_override
data:
  zone: 1
  timeout_minutes: 30
  enable: true
```

**Manual irrigation shot**:
```yaml
service: crop_steering.execute_irrigation_shot  
data:
  zone: 1
  duration_seconds: 60
```

**Emergency stop**:
Turn off `switch.crop_steering_system_enabled`

## Common First-Week Adjustments

### If Plants Look Overwatered
- **Reduce** `p2_shot_size` from 5% to 3-4%
- **Increase** `p2_vwc_threshold` from 60% to 65%
- **Increase** dryback target from 15% to 20%

### If Plants Look Underwatered
- **Increase** `p2_shot_size` from 5% to 6-7%
- **Decrease** `p2_vwc_threshold` from 60% to 55%
- **Decrease** dryback target from 15% to 10%

### If EC Issues
- **High EC** (>3.0): Enable EC stacking, increase shot sizes to flush
- **Low EC** (< target): Check nutrient solution concentration
- **Fluctuating EC**: Check sensor calibration and placement

## Safety Features

### Automatic Safety Checks
- **VWC limits**: Won't irrigate if substrate too wet (>75%)
- **EC limits**: Blocks irrigation if EC dangerously high
- **Time locks**: Prevents rapid-fire irrigation
- **Sensor validation**: Handles sensor failures gracefully

### Manual Safety Controls
- **System enable** (`switch.crop_steering_system_enabled`): Master on/off
- **Auto irrigation** (`switch.crop_steering_auto_irrigation_enabled`): Disable automation
- **Zone enables** (`switch.crop_steering_zone_X_enabled`): Per-zone control
- **Manual overrides**: Take direct control when needed

## Troubleshooting First Steps

### System Not Irrigating
1. Check `sensor.crop_steering_current_phase` - may be in P0 waiting for dryback
2. Verify `switch.crop_steering_system_enabled` is ON
3. Verify `switch.crop_steering_auto_irrigation_enabled` is ON
4. Check VWC vs threshold - may not need irrigation yet

### Unexpected Irrigation
1. Check VWC sensors for correct readings
2. Verify thresholds are set appropriately
3. Look for manual overrides that may be active
4. Check for emergency conditions triggering irrigation

### Sensors Not Working
1. Verify entity names match your hardware in Developer Tools → States
2. Check physical sensor connections and power
3. Look for "Unknown" or "Unavailable" states
4. Test sensors manually if possible

## Next Steps

Once you're comfortable with basic operation:

1. **[Daily Operation Guide](daily-operation.md)** - Master day-to-day monitoring
2. **[Dashboard Guide](dashboard-guide.md)** - Set up monitoring cards
3. **[Complete Installation](../installation/complete-guide.md)** - Add full automation with AppDaemon

### Advanced Features
- **[LLM Integration](../advanced-features/llm-integration.md)** - Add AI decision assistance
- **[Smart Learning](../advanced-features/smart-learning.md)** - Enable adaptive optimization

## Tips for Success

### Week 1: Learn the Basics
- Start with conservative settings
- Monitor every few hours
- Take photos to track plant response
- Keep a simple log of changes

### Week 2: Fine-Tune
- Adjust shot sizes based on plant response
- Optimize thresholds for your setup
- Try different steering modes (veg vs gen)
- Enable more advanced features

### Week 3+: Optimize
- Add AppDaemon for full automation
- Set up monitoring dashboards
- Consider AI enhancement for complex decisions
- Share your setup with the community

---

**🌱 You're Ready!** Take your time learning the system. Crop steering is powerful but requires patience to master. Start conservative and adjust based on what your plants tell you.