# Dashboard Examples

**Dashboard layouts** for monitoring and controlling your Crop Steering System in Home Assistant.

> **Prerequisites**: Complete [installation](../user-guides/02-installation.md) and have basic understanding of Home Assistant dashboards.

## Quick Setup Dashboard

### Basic Status Card
Perfect for getting started - shows essential system information:

```yaml
type: entities
title: Crop Steering Overview
entities:
  - entity: sensor.crop_steering_current_phase
    name: Current Phase
  - entity: switch.crop_steering_system_enabled
    name: System Enabled
  - entity: switch.crop_steering_auto_irrigation_enabled
    name: Auto Irrigation
  - entity: sensor.crop_steering_configured_avg_vwc
    name: Average VWC
  - entity: sensor.crop_steering_configured_avg_ec
    name: Average EC
  - entity: sensor.crop_steering_water_usage_daily
    name: Daily Water Usage
show_header_toggle: false
```

### Manual Control Card
Quick access to manual irrigation controls:

```yaml
type: entities
title: Manual Controls
entities:
  - entity: select.crop_steering_irrigation_phase
    name: Force Phase
  - entity: switch.crop_steering_zone_1_manual_override
    name: Zone 1 Override
  - entity: switch.crop_steering_zone_2_manual_override
    name: Zone 2 Override
  - entity: switch.crop_steering_zone_3_manual_override
    name: Zone 3 Override
show_header_toggle: false
```

## Monitoring Dashboard

### System Health Overview
```yaml
type: horizontal-stack
cards:
  - type: gauge
    entity: sensor.crop_steering_system_health_score
    name: System Health
    min: 0
    max: 100
    severity:
      green: 80
      yellow: 60
      red: 0
    
  - type: gauge
    entity: sensor.crop_steering_irrigation_efficiency
    name: Efficiency
    min: 0
    max: 100
    severity:
      green: 80
      yellow: 60
      red: 0
    
  - type: gauge
    entity: sensor.crop_steering_water_efficiency
    name: Water Efficiency
    min: 0
    max: 10
    severity:
      green: 7
      yellow: 4
      red: 0
```

### Multi-Zone Monitoring Grid
```yaml
type: grid
columns: 3
cards:
  # Zone 1
  - type: entities
    title: Zone 1
    entities:
      - entity: sensor.crop_steering_vwc_zone_1
        name: VWC
        icon: mdi:water-percent
      - entity: sensor.crop_steering_ec_zone_1
        name: EC
        icon: mdi:lightning-bolt
      - entity: sensor.crop_steering_zone_1_status
        name: Status
      - entity: sensor.crop_steering_zone_1_last_irrigation
        name: Last Irrigation
      - entity: switch.crop_steering_zone_1_enabled
        name: Enabled
    
  # Zone 2
  - type: entities
    title: Zone 2
    entities:
      - entity: sensor.crop_steering_vwc_zone_2
        name: VWC
        icon: mdi:water-percent
      - entity: sensor.crop_steering_ec_zone_2
        name: EC
        icon: mdi:lightning-bolt
      - entity: sensor.crop_steering_zone_2_status
        name: Status
      - entity: sensor.crop_steering_zone_2_last_irrigation
        name: Last Irrigation
      - entity: switch.crop_steering_zone_2_enabled
        name: Enabled
    
  # Zone 3
  - type: entities
    title: Zone 3
    entities:
      - entity: sensor.crop_steering_vwc_zone_3
        name: VWC
        icon: mdi:water-percent
      - entity: sensor.crop_steering_ec_zone_3
        name: EC
        icon: mdi:lightning-bolt
      - entity: sensor.crop_steering_zone_3_status
        name: Status
      - entity: sensor.crop_steering_zone_3_last_irrigation
        name: Last Irrigation
      - entity: switch.crop_steering_zone_3_enabled
        name: Enabled
```

### Historical Trends Chart
```yaml
type: history-graph
entities:
  - entity: sensor.crop_steering_configured_avg_vwc
    name: Average VWC
  - entity: sensor.crop_steering_configured_avg_ec
    name: Average EC
  - entity: sensor.crop_steering_water_usage_daily
    name: Daily Water Usage
hours_to_show: 168  # 7 days
refresh_interval: 300  # 5 minutes
```

## Advanced Analytics Dashboard

### Phase Transition Timeline
```yaml
type: logbook
entities:
  - select.crop_steering_irrigation_phase
  - sensor.crop_steering_current_phase
hours_to_show: 24
title: Phase Transitions (24h)
```

### Water Usage Analytics
```yaml
type: vertical-stack
cards:
  - type: statistics-graph
    entities:
      - sensor.crop_steering_water_usage_daily
    title: Daily Water Usage Trend
    days_to_show: 30
    
  - type: horizontal-stack
    cards:
      - type: statistic
        entity: sensor.crop_steering_zone_1_daily_water_usage
        name: Zone 1 Daily
        icon: mdi:watering-can
        
      - type: statistic
        entity: sensor.crop_steering_zone_2_daily_water_usage
        name: Zone 2 Daily
        icon: mdi:watering-can
        
      - type: statistic
        entity: sensor.crop_steering_zone_3_daily_water_usage
        name: Zone 3 Daily
        icon: mdi:watering-can
```

### EC Ratio Monitoring
```yaml
type: custom:mini-graph-card
entities:
  - entity: sensor.crop_steering_ec_ratio
    name: EC Ratio
color_thresholds:
  - value: 0.7
    color: "#ff9800"
  - value: 1.0
    color: "#4caf50"
  - value: 1.3
    color: "#ff9800"
  - value: 1.5
    color: "#f44336"
line_color: "#03a9f4"
line_width: 2
hours_to_show: 24
points_per_hour: 4
show:
  extrema: true
  average: true
```

## Smart Learning Dashboard

### Learning Progress Overview
```yaml
type: entities
title: Learning System Status
entities:
  - entity: sensor.crop_steering_learning_progress
    name: Overall Progress
    icon: mdi:brain
  - entity: sensor.crop_steering_total_irrigations_logged
    name: Irrigations Logged
    icon: mdi:counter
  - type: divider
  - entity: sensor.crop_steering_zone_1_learning_status
    name: Zone 1 Status
  - entity: sensor.crop_steering_zone_1_field_capacity
    name: Zone 1 Field Capacity
  - entity: sensor.crop_steering_zone_1_avg_efficiency
    name: Zone 1 Efficiency
```

### Field Capacity Visualization
```yaml
type: horizontal-stack
cards:
  - type: gauge
    entity: sensor.crop_steering_zone_1_field_capacity
    name: Zone 1 FC
    min: 50
    max: 85
    severity:
      green: 65
      yellow: 60
      red: 50
    
  - type: gauge
    entity: sensor.crop_steering_zone_2_field_capacity
    name: Zone 2 FC
    min: 50
    max: 85
    severity:
      green: 65
      yellow: 60
      red: 50
    
  - type: gauge
    entity: sensor.crop_steering_zone_3_field_capacity
    name: Zone 3 FC
    min: 50
    max: 85
    severity:
      green: 65
      yellow: 60
      red: 50
```

## Troubleshooting Dashboard

### System Diagnostics
```yaml
type: entities
title: System Diagnostics
entities:
  - entity: sensor.crop_steering_system_safety_status
    name: Safety Status
  - entity: sensor.crop_steering_sensor_health
    name: Sensor Health
  - entity: switch.crop_steering_debug_mode
    name: Debug Mode
  - type: divider
  - entity: binary_sensor.water_pump_1
    name: Pump Status
  - entity: binary_sensor.main_water_valve
    name: Main Valve
  - entity: binary_sensor.zone_1_valve
    name: Zone 1 Valve
  - entity: binary_sensor.zone_2_valve
    name: Zone 2 Valve
  - entity: binary_sensor.zone_3_valve
    name: Zone 3 Valve
```

### Error Log Display
```yaml
type: logbook
entities:
  - sensor.crop_steering_system_safety_status
  - switch.crop_steering_system_enabled
  - switch.crop_steering_auto_irrigation_enabled
hours_to_show: 12
title: System Events (12h)
```

## Mobile-Optimized Dashboard

### Compact Overview
```yaml
type: vertical-stack
cards:
  - type: glance
    entities:
      - entity: sensor.crop_steering_current_phase
        name: Phase
      - entity: sensor.crop_steering_configured_avg_vwc
        name: VWC
      - entity: sensor.crop_steering_configured_avg_ec
        name: EC
      - entity: sensor.crop_steering_system_health_score
        name: Health
    columns: 4
    
  - type: horizontal-stack
    cards:
      - type: button
        entity: switch.crop_steering_system_enabled
        name: System
        tap_action:
          action: toggle
        
      - type: button
        entity: switch.crop_steering_auto_irrigation_enabled
        name: Auto
        tap_action:
          action: toggle
```

### Quick Zone Control
```yaml
type: grid
columns: 1
cards:
  - type: entities
    title: Zone Controls
    entities:
      - type: custom:slider-entity-row
        entity: number.crop_steering_zone_1_shot_size_multiplier
        name: Zone 1 Shot Size
        min: 0.1
        max: 3.0
        step: 0.1
      - type: custom:slider-entity-row
        entity: number.crop_steering_zone_2_shot_size_multiplier
        name: Zone 2 Shot Size
        min: 0.1
        max: 3.0
        step: 0.1
```

## Configuration Dashboard

### Phase Parameters
```yaml
type: entities
title: Phase Configuration
entities:
  - type: section
    label: P0 Phase
  - entity: number.crop_steering_p0_min_wait_time
    name: Min Wait Time
  - entity: number.crop_steering_p0_max_wait_time
    name: Max Wait Time
  - entity: number.crop_steering_p0_dryback_drop_percent
    name: Dryback Drop %
  - type: section
    label: P1 Phase
  - entity: number.crop_steering_p1_initial_shot_size
    name: Initial Shot Size
  - entity: number.crop_steering_p1_shot_increment
    name: Shot Increment
  - entity: number.crop_steering_p1_target_vwc
    name: Target VWC
  - type: section
    label: P2 Phase
  - entity: number.crop_steering_p2_shot_size
    name: Shot Size
  - entity: number.crop_steering_p2_vwc_threshold
    name: VWC Threshold
```

### EC Targets Configuration
```yaml
type: entities
title: EC Targets
entities:
  - type: section
    label: Vegetative Targets
  - entity: number.crop_steering_ec_target_veg_p0
    name: P0 Target
  - entity: number.crop_steering_ec_target_veg_p1
    name: P1 Target
  - entity: number.crop_steering_ec_target_veg_p2
    name: P2 Target
  - type: section
    label: Generative Targets
  - entity: number.crop_steering_ec_target_gen_p0
    name: P0 Target
  - entity: number.crop_steering_ec_target_gen_p1
    name: P1 Target
  - entity: number.crop_steering_ec_target_gen_p2
    name: P2 Target
```

## Custom Cards and Styling

### Custom CSS for Enhanced Styling
```yaml
# Add to your theme or dashboard configuration
card-mod-card-yaml: |
  .: |
    ha-card.crop-steering-card {
      border-left: 4px solid var(--primary-color);
      box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .crop-steering-header {
      background: linear-gradient(90deg, var(--primary-color), var(--accent-color));
      color: white;
      padding: 8px 16px;
      margin: -16px -16px 16px -16px;
      border-radius: 4px 4px 0 0;
    }
```

### Conditional Card Display
```yaml
type: conditional
conditions:
  - entity: sensor.crop_steering_current_phase
    state: "P1"
card:
  type: markdown
  content: |
    ## P1 Phase Active
    System is in ramp-up phase. Progressive irrigation shots are being delivered.
    
    **Next shot in:** {{ relative_time(states.sensor.crop_steering_next_irrigation_time.last_changed) }}
```

### Picture Element Overlay
```yaml
type: picture-elements
image: /local/grow_room_layout.png
elements:
  - type: state-badge
    entity: sensor.crop_steering_vwc_zone_1
    style:
      top: 25%
      left: 20%
  - type: state-badge
    entity: sensor.crop_steering_vwc_zone_2
    style:
      top: 25%
      left: 50%
  - type: state-badge
    entity: sensor.crop_steering_vwc_zone_3
    style:
      top: 25%
      left: 80%
```

## Automation Integration

### Dashboard-Triggered Actions
```yaml
# Button card that triggers manual irrigation
type: button
entity: script.manual_irrigation_zone_1
name: Irrigate Zone 1
icon: mdi:water
tap_action:
  action: call-service
  service: script.manual_irrigation_zone_1
  confirmation:
    text: "Irrigate Zone 1 for 30 seconds?"
```

### Dynamic Content Cards
```yaml
type: markdown
content: |
  ## System Status: {{ states('sensor.crop_steering_current_phase') }}
  
  {% if states('sensor.crop_steering_current_phase') == 'P0' %}
  🌅 **Morning Dryback Phase**
  - Waiting for {{ states('number.crop_steering_p0_dryback_drop_percent') }}% VWC drop
  - Current dryback: {{ states('sensor.crop_steering_dryback_percentage') }}%
  {% elif states('sensor.crop_steering_current_phase') == 'P1' %}
  🌱 **Ramp-Up Phase**
  - Progressive shots targeting {{ states('number.crop_steering_p1_target_vwc') }}% VWC
  - Current average: {{ states('sensor.crop_steering_configured_avg_vwc') }}%
  {% elif states('sensor.crop_steering_current_phase') == 'P2' %}
  💧 **Maintenance Phase**
  - Threshold irrigation at {{ states('number.crop_steering_p2_vwc_threshold') }}% VWC
  - EC ratio: {{ states('sensor.crop_steering_ec_ratio') }}
  {% elif states('sensor.crop_steering_current_phase') == 'P3' %}
  🌙 **Pre-Lights-Off Phase**
  - Emergency-only irrigation below {{ states('number.crop_steering_p3_emergency_vwc_threshold') }}%
  {% endif %}
```

---

## Related Documentation

### For Setup
- **[Installation Guide](../user-guides/02-installation.md)** - Complete system setup
- **[Daily Operation](../user-guides/04-daily-operation.md)** - Understanding dashboard data

### For Reference
- **[Entity Reference](../technical/entity-reference.md)** - All available entities for dashboards
- **[Service Reference](../technical/service-reference.md)** - Services you can call from dashboards

### For Advanced Features
- **[Automation Examples](automation-examples.md)** - Integrate dashboards with automations
- **[Smart Learning System](../advanced-features/smart-learning-system.md)** - Learning system dashboard entities

---

**💡 Dashboard Tips:**
- Start with the Quick Setup dashboard and gradually add complexity
- Use conditional cards to show relevant information based on system state
- Group related entities together for better organization
- Consider mobile users when designing card layouts
- Use the history-graph card to track trends over time
- Implement button cards for frequently used manual actions