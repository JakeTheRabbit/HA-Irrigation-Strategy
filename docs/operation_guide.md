# 🌱 Operation Guide

This guide covers daily operation and monitoring of your Crop Steering System for optimal plant health and water efficiency.

> **Who runs the show.** The live autonomous engine is the **f2-control add-on**
> (`addons/f2_control/`) — a single Python process that polls Home Assistant every
> 60 s and drives the hardware. The HA integration only provides the entities and
> setpoints; it never touches hardware. Everything below assumes the add-on is
> installed, configured, and **armed** (see the kill switch, next).

## ⏻ Arm / disarm (kill switch)

The whole engine is gated by one boolean:

- **`input_boolean.f2_control_enabled`**
  - **OFF = safe.** The add-on still runs and reports, but performs **no actuation** —
    no pump, no valves, no shots. This is the disarmed / standby state.
  - **ON = armed.** The engine executes phase logic and drives hardware.

Flip it from the dashboard or **Developer Tools → States** before you expect the
system to water. Turning it OFF is the fastest way to stop all irrigation without
touching the hardware or the add-on.

> `switch.crop_steering_system_enabled` (and the per-zone
> `switch.crop_steering_zone_X_enabled` switches) are the integration-level
> enables surfaced on the dashboard. The hard safety stop is
> `input_boolean.f2_control_enabled` — when in doubt, that's the one to pull.

## 🔄 Daily Operation Cycle

### Understanding the 4-Phase System

When armed, the engine cycles each zone independently through 4 phases per
photoperiod:

**P0 - Morning Dryback (Lights On)**
- Controlled drying after lights turn on
- No irrigation until the dryback target (% drop from peak VWC) is reached
- Duration: 30 minutes to 2+ hours (configurable)

**P1 - Ramp-Up**
- Progressive irrigation with increasing shot sizes
- Continues until the per-zone VWC target is achieved
- Shots: 3-10 maximum with size progression

**P2 - Maintenance (Main Day Period)**
- Threshold-based irrigation decisions
- Triggers: VWC < threshold OR EC ratio conditions
- Most irrigation events happen during this phase

**P3 - Pre-Lights Off**
- Final dryback phase before night period
- Emergency-only irrigation
- Prepares plants for lights-off period

> The daily water + shot counters reset at the **P3 → P0 transition (lights-on)** —
> the real grow-day boundary — not at calendar midnight.

## 📊 Daily Monitoring Routine

### Morning Check (First 30 minutes after lights-on)

**System Status:**
- Check `sensor.crop_steering_current_phase` shows "P0"
- Verify `input_boolean.f2_control_enabled` is ON (armed)
- Confirm all zone switches (`switch.crop_steering_zone_X_enabled`) are on

**Sensor Readings:**
- VWC should be stable from overnight (typically 50-65%)
- EC should be within target ranges (2.0-8.0 mS/cm)
- No sensors showing "unknown" or "unavailable"

### Midday Review (Peak activity period)

**Phase Transitions:**
- Should see progression P0 → P1 → P2
- Monitor `sensor.crop_steering_zone_X_last_irrigation` for recent activity
- Check irrigation efficiency is reasonable

**Parameter Adjustment:**
- Fine-tune based on plant response
- Adjust VWC targets if plants appear stressed or over-watered
- Monitor EC ratio for nutrient management

### Evening Assessment (Before lights-off)

**P3 Phase Check:**
- Verify system has entered P3 phase
- Final irrigation should be emergency-only
- Plants should be prepared for night period

**Daily Performance:**
- Review `sensor.crop_steering_water_usage_daily`
- Check irrigation count per zone
- Note any unusual patterns

## ⚙️ Parameter Tuning

### Key Parameters to Monitor

**VWC Targets:**
- `number.crop_steering_p1_target_vwc`: Target for end of P1 (default 65%)
- `number.crop_steering_p2_vwc_threshold`: Trigger for P2 irrigation (default 60%)

**Shot Sizes:**
- `number.crop_steering_p1_initial_shot_size`: Starting shot volume (default 2%)
- `number.crop_steering_p2_shot_size`: Maintenance shot volume (default 5%)

**Dryback Control:**

> All "dryback" values are **% drop from peak VWC** — i.e. how much
> the substrate dries back **by**, not what VWC value it dries back **to**.
> Example: peak 70 %, valley 58 % → dryback = 12 (not 58).

- `number.crop_steering_veg_p0_dryback_drop_pct`: Vegetative endpoint, default 12 %.
- `number.crop_steering_gen_p0_dryback_drop_pct`: Generative endpoint, default 22 %.
- `number.crop_steering_vegetative_dryback_target` / `generative_dryback_target`: legacy aliases (same semantic, kept for backward compatibility).
- `number.crop_steering_p0_dryback_drop_percent`: interpolated current target, written by the engine every tick — read by the legacy P0-exit predicate.

**Cultivator Intent:**

The single dial that drives all derived parameters:
- `number.crop_steering_steering_intent`: -100 (pure generative) … +100 (pure vegetative). Default 0 = balanced.

### When to Adjust Parameters

**Increase VWC Targets if:**
- Plants show signs of stress (wilting, leaf curl)
- Growth rate is slower than expected
- Environmental conditions are harsh (high heat, low humidity)

**Decrease VWC Targets if:**
- Signs of overwatering (yellowing, root issues)
- Substrate stays too wet between irrigations
- EC is rising too quickly

**Adjust Shot Sizes if:**
- VWC swings are too large (increase frequency, decrease size)
- System over/under-shoots VWC targets
- Water usage is higher than expected

## 🚨 Alert Response

### Red Alerts (Immediate Action Required)

**Emergency VWC Low:**
```yaml
# Manual irrigation
service: crop_steering.execute_irrigation_shot
data:
  zone: 1  # Replace with affected zone
  duration_seconds: 60
  shot_type: "P3_emergency"
```

**System Offline:**
- Check the **f2-control add-on** is running (Settings → Add-ons → f2-control, or `ha addons logs <f2_control_slug>`)
- Confirm `input_boolean.f2_control_enabled` is ON (armed) — a disarmed engine reports but never waters
- Verify the Home Assistant integration is active
- Test hardware entities manually (pump / mainline / zone valves)

### Yellow Warnings (Monitor Closely)

**High Water Usage:**
- Review shot sizes and frequencies
- Check for system leaks
- Monitor plant response

**Sensor Drift:**
- Cross-validate sensors against known standards
- Check calibration
- Consider sensor replacement if persistent

## 📈 Performance Optimization

### Weekly Review

**Irrigation Efficiency:**
- Should be 70%+ for well-tuned systems
- Track trends over time
- Adjust parameters based on plant response

**Water Usage Trends:**
- Should decrease as system learns optimal patterns
- Seasonal adjustments may be needed
- Compare across zones for consistency

**Sensor Health:**
- All sensors should read consistently
- Replace sensors showing persistent issues
- Maintain regular calibration schedule

### Seasonal Adjustments

**Vegetative Growth:**
- Higher VWC targets (60-65%)
- More frequent, smaller shots
- Focus on consistent moisture

**Flowering/Fruiting:**
- Lower VWC targets (55-60%)
- Controlled dryback periods
- Strategic stress for quality

## 🔧 Manual Control

### Emergency Procedures

**Manual Shot:**
```yaml
service: crop_steering.execute_irrigation_shot
data:
  zone: 1
  duration_seconds: 30  # Adjust as needed
```

**Phase Override:**
```yaml
service: crop_steering.transition_phase
data:
  target_phase: "P2"  # Force specific phase
  forced: true        # Bypass transition-condition checks
```

**Zone Override:**
```yaml
service: crop_steering.set_manual_override
data:
  zone: 1
  enable: true
  timeout_minutes: 60  # Auto-disable after 1 hour
```

While a zone is overridden, the autonomous engine leaves it alone until the
override is cleared (or the timeout expires).

### When to Use Manual Control

**Maintenance Windows:**
- System cleaning or sensor calibration
- Hardware repairs
- Substrate changes

**Emergency Situations:**
- Sensor failures
- Unusual plant stress
- Environmental extremes

## 📚 Learning and Optimization

### Understanding Your System

**Week 1-2: Learning Phase**
- Monitor closely, minimal adjustments
- Document plant responses
- Note optimal timing patterns

**Week 3-4: Fine-Tuning**
- Adjust parameters based on observations
- Optimize for your specific conditions
- Establish consistent routines

**Month 2+: Autonomous Operation**
- System should run with minimal intervention
- Focus on preventive maintenance
- Seasonal adjustments as needed

### Best Practices

**Consistent Monitoring:**
- Check system status at least twice daily
- Document any changes or observations
- Track plant health and growth rates

**Gradual Changes:**
- Small parameter adjustments (2-5% at a time)
- Allow 24-48 hours between changes
- Monitor impact before further adjustments

**Data-Driven Decisions:**
- Use entity history graphs to identify trends
- Compare before/after performance metrics
- Base changes on objective measurements

## 🆘 When to Seek Help

**Persistent Issues:**
- System not maintaining target VWC levels
- Consistent sensor errors or drift
- Poor irrigation efficiency (<60%)

**Performance Problems:**
- Plants showing stress despite proper readings
- Unexpected water usage patterns
- System not following expected phase timing

**Getting Support:**
- Check [troubleshooting guide](troubleshooting.md) first
- Search GitHub issues for similar problems
- Provide specific data when requesting help

---

**Remember:** The system is designed to learn and optimize over time. Be patient during the initial learning period, and make adjustments gradually based on plant response and system performance data.
