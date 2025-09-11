# Automation Examples

**Comprehensive automation examples** for integrating the Crop Steering System with your Home Assistant setup.

> **Prerequisites**: Complete [installation](../user-guides/02-installation.md) and understand [daily operation](../user-guides/04-daily-operation.md) before implementing automations.

## Basic Automations

### Emergency Stop Automation
```yaml
# Automatically stop all irrigation if critical sensors fail
automation:
  - alias: "Crop Steering Emergency Stop"
    trigger:
      - platform: state
        entity_id: 
          - sensor.zone_1_vwc_front
          - sensor.zone_1_ec_front
        to: "unavailable"
        for: "00:05:00"
    action:
      - service: switch.turn_off
        target:
          entity_id: switch.crop_steering_system_enabled
      - service: notify.mobile_app
        data:
          message: "🚨 Crop steering emergency stop activated - sensor failure detected"
          title: "Irrigation System Alert"
```

### Low Water Tank Alert
```yaml
# Alert when water tank level is low
automation:
  - alias: "Water Tank Low Alert"
    trigger:
      - platform: numeric_state
        entity_id: sensor.water_tank_level
        below: 25
    action:
      - service: notify.mobile_app
        data:
          message: "💧 Water tank is low ({{ states('sensor.water_tank_level') }}%). Please refill."
          title: "Tank Level Alert"
```

## Advanced Phase-Based Automations

### Nutrient Injection Based on Phase
```yaml
# Inject nutrients based on current irrigation phase
automation:
  - alias: "Phase-Based Nutrient Injection"
    trigger:
      - platform: event
        event_type: crop_steering_irrigation_shot
    condition:
      - condition: template
        value_template: "{{ trigger.event.data.shot_type in ['P1', 'P2'] }}"
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.nutrient_pump
      - delay: "00:00:05"  # 5 second injection
      - service: switch.turn_off
        target:
          entity_id: switch.nutrient_pump
```

### EC-Based Feed Adjustment
```yaml
# Automatically adjust nutrient strength based on EC readings
automation:
  - alias: "Auto EC Adjustment"
    trigger:
      - platform: numeric_state
        entity_id: sensor.crop_steering_ec_ratio
        above: 1.3  # EC too high
        for: "00:30:00"
    action:
      - service: number.set_value
        target:
          entity_id: number.crop_steering_p2_shot_size
        data:
          value: "{{ states('number.crop_steering_p2_shot_size') | float + 0.5 }}"
      - service: notify.mobile_app
        data:
          message: "📈 Increased irrigation shot size due to high EC ratio"
```

## Environmental Integration

### Lights-Off Phase Transition
```yaml
# Force P3 phase when lights turn off
automation:
  - alias: "Force P3 at Lights Off"
    trigger:
      - platform: state
        entity_id: switch.grow_lights
        to: "off"
    condition:
      - condition: state
        entity_id: switch.crop_steering_system_enabled
        state: "on"
    action:
      - service: crop_steering.transition_phase
        data:
          target_phase: "P3"
          reason: "Lights off - automated P3 transition"
```

### VPD-Based Irrigation Adjustment
```yaml
# Adjust irrigation frequency based on VPD
automation:
  - alias: "VPD Irrigation Adjustment"
    trigger:
      - platform: numeric_state
        entity_id: sensor.vpd
        above: 1.5  # High VPD = more plant stress
    action:
      - service: number.set_value
        target:
          entity_id: number.crop_steering_p2_vwc_threshold
        data:
          value: "{{ [states('number.crop_steering_p2_vwc_threshold') | float + 2, 70] | min }}"
```

## Smart Learning Integration

### Learning Mode Activation
```yaml
# Activate learning mode for new zones
automation:
  - alias: "Auto Learning Mode New Zones"
    trigger:
      - platform: state
        entity_id: 
          - switch.crop_steering_zone_4_enabled
          - switch.crop_steering_zone_5_enabled
          - switch.crop_steering_zone_6_enabled
        to: "on"
    condition:
      - condition: state
        entity_id: sensor.crop_steering_zone_{{ trigger.entity_id.split('_')[3] }}_learning_status
        state: "needs_learning"
    action:
      - service: crop_steering.detect_field_capacity
        data:
          zone_id: "{{ trigger.entity_id.split('_')[3] }}"
```

### Smart Shot Size Automation
```yaml
# Use learned optimal shot sizes
automation:
  - alias: "Smart Shot Size Zone 1"
    trigger:
      - platform: numeric_state
        entity_id: sensor.crop_steering_vwc_zone_1
        below: 55
    condition:
      - condition: state
        entity_id: sensor.crop_steering_zone_1_learning_status
        state: "learned"
      - condition: state
        entity_id: sensor.crop_steering_current_phase
        state: "P2"
    action:
      - service: crop_steering.calculate_optimal_shot
        data:
          zone_id: 1
          target_vwc_increase: 5
      - wait_for_trigger:
          - platform: event
            event_type: crop_steering_optimal_shot_calculated
        timeout: "00:01:00"
      - service: crop_steering.execute_irrigation_shot
        data:
          zone: 1
          duration_seconds: "{{ trigger.event.data.optimal_duration_seconds }}"
          shot_type: "smart_auto"
```

## Multi-Zone Coordination

### Sequential Zone Irrigation
```yaml
# Irrigate zones sequentially to manage pump load
automation:
  - alias: "Sequential Zone Irrigation"
    trigger:
      - platform: event
        event_type: crop_steering_phase_transition
        event_data:
          new_phase: "P1"
    action:
      - repeat:
          count: "{{ states('sensor.crop_steering_configured_zones') | int }}"
          sequence:
            - service: crop_steering.execute_irrigation_shot
              data:
                zone: "{{ repeat.index }}"
                duration_seconds: 30
                shot_type: "P1_sequential"
            - delay: "00:02:00"  # 2 minute delay between zones
```

### Group-Based Irrigation
```yaml
# Irrigate zones by priority groups
automation:
  - alias: "Priority Group Irrigation"
    trigger:
      - platform: time_pattern
        minutes: "/15"  # Check every 15 minutes
    condition:
      - condition: state
        entity_id: sensor.crop_steering_current_phase
        state: "P2"
    action:
      - repeat:
          for_each:
            - "Critical"
            - "High" 
            - "Normal"
            - "Low"
          sequence:
            - condition: template
              value_template: >
                {{ states | selectattr('entity_id', 'match', 'select.crop_steering_zone_.*_priority') 
                   | selectattr('state', 'eq', repeat.item) 
                   | map(attribute='entity_id') | list | length > 0 }}
            - service: script.irrigate_priority_group
              data:
                priority: "{{ repeat.item }}"
```

## Error Handling and Recovery

### Sensor Validation Automation
```yaml
# Validate sensor readings and alert on anomalies
automation:
  - alias: "Sensor Validation"
    trigger:
      - platform: state
        entity_id: 
          - sensor.crop_steering_vwc_zone_1
          - sensor.crop_steering_vwc_zone_2
          - sensor.crop_steering_vwc_zone_3
    condition:
      - condition: template
        value_template: >
          {{ trigger.to_state.state | float < 0 or 
             trigger.to_state.state | float > 100 or
             (trigger.to_state.state | float - trigger.from_state.state | float) | abs > 20 }}
    action:
      - service: notify.mobile_app
        data:
          message: >
            🚨 Sensor anomaly detected: {{ trigger.entity_id }} 
            changed from {{ trigger.from_state.state }}% to {{ trigger.to_state.state }}%
          title: "Sensor Alert"
```

### Automatic Recovery
```yaml
# Automatically recover from minor issues
automation:
  - alias: "Auto Recovery Minor Issues"
    trigger:
      - platform: state
        entity_id: sensor.crop_steering_system_safety_status
        to: "warning"
        for: "00:05:00"
    action:
      - service: crop_steering.check_transition_conditions
      - delay: "00:01:00"
      - condition: state
        entity_id: sensor.crop_steering_system_safety_status
        state: "warning"
      - service: switch.turn_off
        target:
          entity_id: switch.crop_steering_auto_irrigation_enabled
      - delay: "00:05:00"
      - service: switch.turn_on
        target:
          entity_id: switch.crop_steering_auto_irrigation_enabled
```

## Notification Systems

### Daily Report Automation
```yaml
# Send daily irrigation report
automation:
  - alias: "Daily Irrigation Report"
    trigger:
      - platform: time
        at: "20:00:00"  # 8 PM daily report
    action:
      - service: notify.mobile_app
        data:
          title: "Daily Crop Steering Report"
          message: >
            📊 Today's Summary:
            💧 Water used: {{ states('sensor.crop_steering_water_usage_daily') }}L
            🌱 Current phase: {{ states('sensor.crop_steering_current_phase') }}
            📈 Avg VWC: {{ states('sensor.crop_steering_configured_avg_vwc') }}%
            ⚡ System efficiency: {{ states('sensor.crop_steering_irrigation_efficiency') }}%
```

### Weekly Performance Summary
```yaml
# Send weekly performance analysis
automation:
  - alias: "Weekly Performance Summary"
    trigger:
      - platform: time
        at: "09:00:00"
      - condition: time
        weekday:
          - sun
    action:
      - service: notify.mobile_app
        data:
          title: "Weekly Crop Steering Performance"
          message: >
            📈 Week {{ now().strftime('%W') }} Summary:
            💧 Total water: {{ states('sensor.crop_steering_weekly_water_usage') }}L
            🎯 Irrigation events: {{ states('sensor.crop_steering_weekly_irrigation_count') }}
            📊 Avg efficiency: {{ states('sensor.crop_steering_water_efficiency') }}%
            🌡️ System health: {{ states('sensor.crop_steering_system_health_score') }}%
```

## Integration Scripts

### Custom Irrigation Script
```yaml
# Reusable irrigation script with safety checks
script:
  custom_irrigation_shot:
    alias: "Custom Irrigation Shot"
    icon: mdi:water
    fields:
      zone:
        description: "Zone number to irrigate"
        example: 1
      duration:
        description: "Duration in seconds"
        example: 30
      safety_check:
        description: "Perform safety checks"
        default: true
    sequence:
      - condition: template
        value_template: "{{ safety_check == false or states('switch.crop_steering_system_enabled') == 'on' }}"
      - condition: template
        value_template: "{{ states('sensor.crop_steering_vwc_zone_' + zone|string) | float < 85 }}"
      - service: crop_steering.execute_irrigation_shot
        data:
          zone: "{{ zone }}"
          duration_seconds: "{{ duration }}"
          shot_type: "manual_script"
      - service: notify.mobile_app
        data:
          message: "💧 Manual irrigation: Zone {{ zone }} for {{ duration }}s"
```

### Emergency Flush Script
```yaml
# Emergency EC flush script
script:
  emergency_ec_flush:
    alias: "Emergency EC Flush"
    icon: mdi:water-alert
    fields:
      zone:
        description: "Zone to flush"
        example: 1
    sequence:
      - condition: numeric_state
        entity_id: "sensor.crop_steering_ec_zone_{{ zone }}"
        above: 6.0  # Only flush if EC is dangerously high
      - service: number.set_value
        target:
          entity_id: "number.crop_steering_ec_target_flush"
        data:
          value: 1.0  # Low EC for flushing
      - repeat:
          count: 3
          sequence:
            - service: crop_steering.execute_irrigation_shot
              data:
                zone: "{{ zone }}"
                duration_seconds: 60
                shot_type: "emergency_flush"
            - delay: "00:10:00"
      - service: notify.mobile_app
        data:
          message: "🚨 Emergency EC flush completed for Zone {{ zone }}"
```

## Testing and Development

### Test Mode Automation
```yaml
# Safe test mode for development
automation:
  - alias: "Test Mode Safety"
    trigger:
      - platform: state
        entity_id: input_boolean.crop_steering_test_mode
        to: "on"
    action:
      - service: number.set_value
        target:
          entity_id: number.crop_steering_p2_shot_size
        data:
          value: 0.5  # Very small shots in test mode
      - service: switch.turn_off
        target:
          entity_id: switch.crop_steering_ec_stacking_enabled
```

---

## Related Documentation

### For Setup
- **[Installation Guide](../user-guides/02-installation.md)** - Complete system setup
- **[Daily Operation](../user-guides/04-daily-operation.md)** - Understanding system behavior

### For Reference  
- **[Service Reference](../technical/service-reference.md)** - All available services
- **[Entity Reference](../technical/entity-reference.md)** - Complete entity documentation

### For Troubleshooting
- **[Troubleshooting Guide](../user-guides/05-troubleshooting.md)** - Resolve automation issues

---

**💡 Pro Tips:**
- Start with basic automations and gradually add complexity
- Always include safety conditions in your automations
- Test automations in a safe environment before production use
- Monitor automation behavior for the first few days after implementation
- Use the notification system to track automation effectiveness