# Dashboard Guide

**Create professional monitoring dashboards** for your crop steering system. This guide shows you how to build effective visualization and control interfaces using Home Assistant's dashboard tools.

> **Prerequisites**: Complete [getting started guide](getting-started.md) and have entities visible in Home Assistant.

## Essential Dashboard Cards

### System Status Overview

**Basic Status Card**:
```yaml
type: entities
title: "Crop Steering System"
entities:
  - entity: sensor.crop_steering_current_phase
    name: "Current Phase"
  - entity: switch.crop_steering_system_enabled
    name: "System Enabled"
  - entity: switch.crop_steering_auto_irrigation_enabled
    name: "Auto Irrigation"
  - entity: sensor.crop_steering_next_irrigation_time
    name: "Next Irrigation"
  - entity: sensor.crop_steering_configured_avg_vwc
    name: "Average VWC"
  - entity: sensor.crop_steering_configured_avg_ec
    name: "Average EC"
  - entity: sensor.crop_steering_ec_ratio
    name: "EC Ratio"
```

**Enhanced Status Card with Icons**:
```yaml
type: entities
title: "🌱 Crop Steering Status"
show_header_toggle: false
entities:
  - entity: sensor.crop_steering_current_phase
    name: "Current Phase"
    icon: mdi:water-circle
  - entity: sensor.crop_steering_configured_avg_vwc
    name: "Moisture Level"
    icon: mdi:water-percent
  - entity: sensor.crop_steering_configured_avg_ec
    name: "Nutrient Level"  
    icon: mdi:test-tube
  - entity: sensor.crop_steering_ec_ratio
    name: "EC Ratio"
    icon: mdi:chart-line-variant
  - entity: sensor.crop_steering_water_usage_daily
    name: "Daily Water Usage"
    icon: mdi:water-pump
```

### Zone Monitoring Cards

**Individual Zone Card**:
```yaml
type: entities
title: "Zone 1 Status"
entities:
  - entity: sensor.crop_steering_zone_1_status
    name: "Status"
  - entity: sensor.crop_steering_vwc_zone_1
    name: "VWC"
  - entity: sensor.crop_steering_ec_zone_1
    name: "EC"
  - entity: sensor.crop_steering_zone_1_last_irrigation
    name: "Last Irrigation"
  - entity: switch.crop_steering_zone_1_enabled
    name: "Zone Enabled"
  - entity: switch.crop_steering_zone_1_manual_override
    name: "Manual Override"
```

**Multi-Zone Summary**:
```yaml
type: glance
title: "All Zones Overview"
columns: 3
entities:
  - entity: sensor.crop_steering_zone_1_status
    name: "Zone 1"
  - entity: sensor.crop_steering_zone_2_status
    name: "Zone 2" 
  - entity: sensor.crop_steering_zone_3_status
    name: "Zone 3"
  - entity: sensor.crop_steering_vwc_zone_1
    name: "Z1 VWC"
  - entity: sensor.crop_steering_vwc_zone_2
    name: "Z2 VWC"
  - entity: sensor.crop_steering_vwc_zone_3
    name: "Z3 VWC"
  - entity: sensor.crop_steering_ec_zone_1
    name: "Z1 EC"
  - entity: sensor.crop_steering_ec_zone_2
    name: "Z2 EC"
  - entity: sensor.crop_steering_ec_zone_3
    name: "Z3 EC"
```

### Historical Tracking

**VWC History Graph**:
```yaml
type: history-graph
title: "VWC Levels (24 Hours)"
entities:
  - entity: sensor.crop_steering_configured_avg_vwc
    name: "Average VWC"
  - entity: sensor.crop_steering_vwc_zone_1
    name: "Zone 1"
  - entity: sensor.crop_steering_vwc_zone_2
    name: "Zone 2"
  - entity: sensor.crop_steering_vwc_zone_3
    name: "Zone 3"
hours_to_show: 24
refresh_interval: 300
```

**EC Ratio Trend**:
```yaml
type: history-graph
title: "EC Ratio Trend"
entities:
  - entity: sensor.crop_steering_ec_ratio
    name: "EC Ratio"
hours_to_show: 168  # 7 days
refresh_interval: 300
```

## Advanced Visualization

### Gauge Cards for Key Metrics

**VWC Gauge**:
```yaml
type: gauge
title: "System VWC"
entity: sensor.crop_steering_configured_avg_vwc
min: 0
max: 100
severity:
  green: 50
  yellow: 35
  red: 20
needle: true
```

**EC Ratio Gauge**:
```yaml
type: gauge
title: "EC Ratio"
entity: sensor.crop_steering_ec_ratio
min: 0.5
max: 1.5
severity:
  green: 0.8
  yellow: 0.6
  red: 0.5
needle: true
```

### Statistics Cards

**Daily Water Usage**:
```yaml
type: statistics-graph
title: "Water Usage Trend"
entities:
  - sensor.crop_steering_water_usage_daily
stat_types:
  - mean
  - min
  - max
period: day
days_to_show: 14
```

**Irrigation Events**:
```yaml
type: statistics-graph
title: "Daily Irrigation Events"
entities:
  - sensor.crop_steering_zone_1_irrigation_count_today
  - sensor.crop_steering_zone_2_irrigation_count_today
  - sensor.crop_steering_zone_3_irrigation_count_today
period: day
days_to_show: 7
```

## Control Interface

### Manual Control Panel

**Quick Actions**:
```yaml
type: entities
title: "Manual Controls"
entities:
  - entity: input_select.crop_steering_manual_phase
    name: "Force Phase"
  - entity: input_number.crop_steering_manual_shot_duration
    name: "Shot Duration (seconds)"
  - entity: input_select.crop_steering_manual_zone
    name: "Target Zone"
  - type: button
    name: "Execute Manual Shot"
    tap_action:
      action: call-service
      service: crop_steering.execute_irrigation_shot
      service_data:
        zone: "{{ states('input_select.crop_steering_manual_zone') }}"
        duration_seconds: "{{ states('input_number.crop_steering_manual_shot_duration') | int }}"
        shot_type: "manual"
```

**Emergency Controls**:
```yaml
type: entities
title: "🚨 Emergency Controls"
entities:
  - entity: switch.crop_steering_system_enabled
    name: "System Master Enable"
    icon: mdi:power
  - entity: switch.crop_steering_auto_irrigation_enabled
    name: "Automation Enable"
    icon: mdi:robot
  - type: button
    name: "Emergency Stop All"
    icon: mdi:stop-circle
    tap_action:
      action: call-service
      service: switch.turn_off
      service_data:
        entity_id: switch.crop_steering_system_enabled
```

### Parameter Adjustment

**Key Parameters Panel**:
```yaml
type: entities
title: "⚙️ Key Parameters"
entities:
  - entity: number.crop_steering_p2_vwc_threshold
    name: "P2 Threshold %"
  - entity: number.crop_steering_p2_shot_size
    name: "P2 Shot Size %"
  - entity: number.crop_steering_p1_target_vwc
    name: "P1 Target %"
  - entity: select.crop_steering_growth_stage
    name: "Growth Stage"
  - entity: select.crop_steering_steering_mode
    name: "Steering Mode"
```

## Complete Dashboard Layout

### Main Dashboard Page

```yaml
title: "Crop Steering Control"
type: sections
sections:
  - title: "System Overview"
    type: grid
    cards:
      - type: entities
        title: "🌱 System Status"
        entities:
          - sensor.crop_steering_current_phase
          - switch.crop_steering_system_enabled
          - sensor.crop_steering_next_irrigation_time
          - sensor.crop_steering_configured_avg_vwc
          - sensor.crop_steering_ec_ratio
      
      - type: gauge
        title: "VWC Level"
        entity: sensor.crop_steering_configured_avg_vwc
        min: 0
        max: 100
        severity:
          green: 50
          yellow: 35
          red: 20
      
      - type: gauge  
        title: "EC Ratio"
        entity: sensor.crop_steering_ec_ratio
        min: 0.5
        max: 1.5
        severity:
          green: 0.8
          yellow: 0.6
          red: 0.5

  - title: "Zone Status"
    type: grid
    cards:
      - type: glance
        title: "All Zones"
        columns: 3
        entities:
          - sensor.crop_steering_zone_1_status
          - sensor.crop_steering_zone_2_status
          - sensor.crop_steering_zone_3_status
          - sensor.crop_steering_vwc_zone_1
          - sensor.crop_steering_vwc_zone_2
          - sensor.crop_steering_vwc_zone_3

  - title: "Historical Data"
    type: grid
    cards:
      - type: history-graph
        title: "VWC Levels (24h)"
        entities:
          - sensor.crop_steering_configured_avg_vwc
          - sensor.crop_steering_vwc_zone_1
          - sensor.crop_steering_vwc_zone_2
        hours_to_show: 24
      
      - type: history-graph
        title: "EC Trend (7 days)"
        entities:
          - sensor.crop_steering_ec_ratio
        hours_to_show: 168

  - title: "Controls"
    type: grid
    cards:
      - type: entities
        title: "Manual Controls"
        entities:
          - switch.crop_steering_system_enabled
          - switch.crop_steering_auto_irrigation_enabled
          - number.crop_steering_p2_vwc_threshold
          - number.crop_steering_p2_shot_size
```

## Mobile-Optimized Layout

### Phone Dashboard

```yaml
title: "Crop Steering Mobile"
type: sections
sections:
  - title: "Quick Status"
    type: grid
    cards:
      - type: entities
        entities:
          - sensor.crop_steering_current_phase
          - sensor.crop_steering_configured_avg_vwc
          - sensor.crop_steering_ec_ratio
          - switch.crop_steering_system_enabled

  - title: "Zones"
    type: grid  
    cards:
      - type: glance
        columns: 2
        entities:
          - sensor.crop_steering_zone_1_status
          - sensor.crop_steering_zone_2_status
          - sensor.crop_steering_vwc_zone_1
          - sensor.crop_steering_vwc_zone_2

  - title: "Emergency"
    type: grid
    cards:
      - type: entities
        entities:
          - switch.crop_steering_system_enabled
          - switch.crop_steering_auto_irrigation_enabled
```

## Conditional Display

### Show/Hide Based on System State

**AppDaemon Status Card** (only show if AppDaemon installed):
```yaml
type: conditional
conditions:
  - entity: sensor.crop_steering_app_current_phase
    state_not: "unavailable"
card:
  type: entities
  title: "AppDaemon Status"
  entities:
    - sensor.crop_steering_app_current_phase
    - sensor.crop_steering_app_next_irrigation
    - sensor.crop_steering_system_health_score
```

**LLM Status Card** (only show if LLM enabled):
```yaml
type: conditional
conditions:
  - entity: switch.crop_steering_llm_enabled
    state: "on"
card:
  type: entities
  title: "🤖 AI Assistant"
  entities:
    - sensor.crop_steering_llm_daily_cost
    - sensor.crop_steering_llm_confidence_avg
    - sensor.crop_steering_llm_cache_hit_rate
```

## Alerting Integration

### Visual Alerts

**Problem Indicator Card**:
```yaml
type: conditional
conditions:
  - entity: sensor.crop_steering_configured_avg_vwc
    state_not: "unknown"
    below: 30
card:
  type: markdown
  content: |
    ## ⚠️ LOW VWC ALERT
    **Average VWC: {{ states('sensor.crop_steering_configured_avg_vwc') }}%**
    
    System VWC is critically low. Check:
    - System enabled status
    - Sensor readings
    - Hardware operation
    
    Consider manual irrigation if needed.
```

**High EC Warning**:
```yaml
type: conditional
conditions:
  - entity: sensor.crop_steering_ec_ratio
    above: 1.4
card:
  type: markdown
  content: |
    ## 🔶 HIGH EC RATIO
    **Current Ratio: {{ states('sensor.crop_steering_ec_ratio') }}**
    
    Nutrients may be too concentrated. System should increase irrigation to flush.
```

## Dashboard Performance Tips

### Optimization
1. **Limit history graphs** to reasonable time periods
2. **Use conditional cards** to reduce entity queries
3. **Group related entities** in single cards when possible
4. **Refresh intervals** should match data update frequency

### Best Practices
1. **Start simple** and add complexity gradually
2. **Test on mobile** devices if you'll use them
3. **Use descriptive names** instead of entity IDs
4. **Include units** in card titles when helpful
5. **Group by function** rather than entity type

## Customization Ideas

### Theme Integration
- Use custom CSS for crop-specific colors
- Add plant growth stage indicators
- Seasonal theme changes

### Advanced Cards
- Weather integration for environmental correlation
- Plant development photo timeline
- Harvest tracking and yield analysis

### Automation Integration
- Dashboard buttons that trigger complex automations
- Scene selection for different growth stages
- Maintenance mode toggles

---

**📊 Dashboard Mastery!** A well-designed dashboard makes monitoring and controlling your crop steering system intuitive and efficient. Start with the basics and evolve your interface as you learn the system.