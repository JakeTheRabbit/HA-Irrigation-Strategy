# Service Reference

**Complete reference for all Crop Steering System services** available in Home Assistant for automation and manual control.

> **Prerequisites**: Complete [installation](../user-guides/02-installation.md) to access these services.

## Core System Services

### Phase Management

#### `crop_steering.transition_phase`
Manually force transition to a specific irrigation phase.

**Parameters:**
- `target_phase` (required): Target phase (`P0`, `P1`, `P2`, `P3`, `Manual`)
- `reason` (optional): Reason for transition (for logging)
- `forced` (optional): Force transition even if conditions not met (default: false)

**Example:**
```yaml
service: crop_steering.transition_phase
data:
  target_phase: "P1"
  reason: "Manual override for testing"
  forced: true
```

**Events Generated:**
- `crop_steering_phase_transition` with phase change details

#### `crop_steering.check_transition_conditions`
Check if automatic phase transition conditions are currently met.

**Parameters:** None

**Example:**
```yaml
service: crop_steering.check_transition_conditions
```

**Returns:** Logs current conditions and transition readiness to AppDaemon logs.

### Irrigation Control

#### `crop_steering.execute_irrigation_shot`
Execute a manual irrigation shot for a specific zone.

**Parameters:**
- `zone` (required): Zone number (1-6)
- `duration_seconds` (required): Duration in seconds
- `shot_type` (optional): Type identifier for logging (default: "manual")

**Example:**
```yaml
service: crop_steering.execute_irrigation_shot
data:
  zone: 1
  duration_seconds: 30
  shot_type: "manual_test"
```

**Safety Features:**
- Respects manual override settings
- Checks system enabled status
- Validates zone exists and is enabled
- Prevents excessive duration (max 300 seconds per shot)

**Events Generated:**
- `crop_steering_irrigation_shot` with shot details

#### `crop_steering.set_manual_override`
Enable or disable manual override for a specific zone.

**Parameters:**
- `zone` (required): Zone number (1-6)
- `enable` (required): true to enable, false to disable
- `timeout_minutes` (optional): Auto-disable after timeout (default: 60)

**Example:**
```yaml
service: crop_steering.set_manual_override
data:
  zone: 1
  enable: true
  timeout_minutes: 120
```

**Behavior:**
- When enabled: Blocks all automatic irrigation for the zone
- When disabled: Resumes automatic irrigation based on phase logic
- Timeout: Automatically disables override after specified time

## Smart Learning Services

### Learning Control

#### `crop_steering.detect_field_capacity`
Run field capacity detection for a specific zone.

**Parameters:**
- `zone_id` (required): Zone number (1-6)

**Example:**
```yaml
service: crop_steering.detect_field_capacity
data:
  zone_id: 1
```

**Process:**
1. Delivers progressive water shots
2. Measures VWC increase vs. water delivered
3. Detects saturation point (field capacity)
4. Stores results in learning database

**Duration:** 20-60 minutes depending on substrate and current moisture

#### `crop_steering.characterize_zone_efficiency`
Perform detailed efficiency characterization across moisture levels.

**Parameters:**
- `zone_id` (required): Zone number (1-6)

**Example:**
```yaml
service: crop_steering.characterize_zone_efficiency
data:
  zone_id: 1
```

**Process:**
1. Tests irrigation efficiency at multiple VWC levels
2. Creates detailed efficiency curve
3. Identifies optimal irrigation ranges
4. Updates learning parameters

**Duration:** 2-4 hours per zone

#### `crop_steering.calculate_optimal_shot`
Calculate optimal irrigation duration based on learned zone characteristics.

**Parameters:**
- `zone_id` (required): Zone number (1-6)
- `target_vwc_increase` (optional): Desired VWC increase percentage (default: 5.0)

**Example:**
```yaml
service: crop_steering.calculate_optimal_shot
data:
  zone_id: 1
  target_vwc_increase: 3.5
```

**Returns:**
- Updates sensor entities with recommended duration
- Generates `crop_steering_optimal_shot_calculated` event

#### `crop_steering.get_zone_intelligence`
Retrieve complete learning data for a zone.

**Parameters:**
- `zone_id` (required): Zone number (1-6)

**Example:**
```yaml
service: crop_steering.get_zone_intelligence
data:
  zone_id: 1
```

**Returns:** Comprehensive zone learning data in AppDaemon logs.

## Advanced System Services

### System Configuration

#### `crop_steering.reload_configuration`
Reload system configuration without restarting AppDaemon.

**Parameters:** None

**Example:**
```yaml
service: crop_steering.reload_configuration
```

**Use Cases:**
- After changing configuration parameters
- Testing new settings without full restart
- Recovering from configuration errors

#### `crop_steering.export_data`
Export system data for backup or analysis.

**Parameters:**
- `data_type` (optional): Type of data to export (`configuration`, `history`, `learning`, `all`)
- `days` (optional): Number of days of history to export (default: 30)

**Example:**
```yaml
service: crop_steering.export_data
data:
  data_type: "all"
  days: 7
```

**Output:** Creates JSON files in AppDaemon apps directory

### Diagnostic Services

#### `crop_steering.run_system_diagnostics`
Perform comprehensive system health check.

**Parameters:** None

**Example:**
```yaml
service: crop_steering.run_system_diagnostics
```

**Checks:**
- Entity availability and health
- Sensor reading validity
- Hardware connectivity
- Safety system status
- Learning system status

#### `crop_steering.calibrate_sensors`
Initiate sensor calibration routine.

**Parameters:**
- `zone_id` (optional): Specific zone to calibrate (default: all zones)
- `sensor_type` (optional): Type of sensor (`vwc`, `ec`, `all`)

**Example:**
```yaml
service: crop_steering.calibrate_sensors
data:
  zone_id: 1
  sensor_type: "vwc"
```

**Process:**
- Guides through calibration steps
- Updates calibration parameters
- Validates sensor accuracy

## Service Usage Patterns

### Automation Integration

#### Sequential Zone Irrigation
```yaml
automation:
  - alias: "Sequential Zone Irrigation"
    trigger:
      - platform: time
        at: "08:00:00"
    action:
      - repeat:
          count: 3  # For 3 zones
          sequence:
            - service: crop_steering.execute_irrigation_shot
              data:
                zone: "{{ repeat.index }}"
                duration_seconds: 45
                shot_type: "scheduled_sequential"
            - delay: "00:02:00"  # 2 minute delay between zones
```

#### Smart Learning Automation
```yaml
automation:
  - alias: "Auto Smart Irrigation"
    trigger:
      - platform: numeric_state
        entity_id: sensor.crop_steering_vwc_zone_1
        below: 55
    condition:
      - condition: state
        entity_id: sensor.crop_steering_zone_1_learning_status
        state: "learned"
    action:
      - service: crop_steering.calculate_optimal_shot
        data:
          zone_id: 1
      - wait_for_trigger:
          - platform: event
            event_type: crop_steering_optimal_shot_calculated
      - service: crop_steering.execute_irrigation_shot
        data:
          zone: 1
          duration_seconds: "{{ trigger.event.data.optimal_duration_seconds }}"
```

### Script Integration

#### Emergency Response Script
```yaml
script:
  emergency_stop_and_flush:
    alias: "Emergency Stop and Flush"
    sequence:
      - service: switch.turn_off
        target:
          entity_id: switch.crop_steering_system_enabled
      - service: crop_steering.set_manual_override
        data:
          zone: 1
          enable: true
      - service: crop_steering.execute_irrigation_shot
        data:
          zone: 1
          duration_seconds: 120
          shot_type: "emergency_flush"
      - delay: "00:10:00"
      - service: crop_steering.set_manual_override
        data:
          zone: 1
          enable: false
```

## Events Generated

### System Events

#### `crop_steering_phase_transition`
Fired when irrigation phase changes.

**Data:**
- `old_phase`: Previous phase
- `new_phase`: Current phase
- `reason`: Transition reason
- `timestamp`: Transition time

#### `crop_steering_irrigation_shot`
Fired for every irrigation event.

**Data:**
- `zone`: Zone number
- `duration_seconds`: Shot duration
- `shot_type`: Type identifier
- `vwc_before`: VWC before irrigation
- `timestamp`: Shot time

#### `crop_steering_transition_check`
Fired when transition conditions are evaluated.

**Data:**
- `current_phase`: Current phase
- `conditions_met`: Boolean
- `next_phase`: Potential next phase
- `reasons`: List of condition results

### Learning Events

#### `crop_steering_optimal_shot_calculated`
Fired when smart learning calculates optimal shot.

**Data:**
- `zone_id`: Zone number
- `optimal_duration_seconds`: Calculated duration
- `target_vwc_increase`: Target increase
- `confidence`: Calculation confidence (0-1)

#### `crop_steering_field_capacity_detected`
Fired when field capacity detection completes.

**Data:**
- `zone_id`: Zone number
- `field_capacity_vwc`: Detected FC percentage
- `confidence`: Detection confidence
- `shots_taken`: Number of test shots

## Error Handling

### Common Service Errors

#### Zone Not Found
```
Error: Zone 5 not configured or enabled
```
**Solution:** Check zone configuration in integration setup

#### System Disabled
```
Error: Crop steering system is disabled
```
**Solution:** Enable system with `switch.crop_steering_system_enabled`

#### Manual Override Active
```
Error: Zone 1 is in manual override mode
```
**Solution:** Disable override or use override-specific services

#### Sensor Unavailable
```
Error: VWC sensor for zone 1 unavailable
```
**Solution:** Check sensor connectivity and entity mapping

### Service Rate Limiting

#### Irrigation Frequency
- Maximum 1 irrigation per zone per 5 minutes
- Maximum 10 irrigations per zone per hour
- Emergency shots exempt from rate limiting

#### Learning Services
- Field capacity detection: Once per zone per day
- Efficiency characterization: Once per zone per week
- Optimal shot calculation: No limit

## Security Considerations

### Service Access Control
- All services require Home Assistant authentication
- Consider creating dedicated service user for automations
- Use secrets for any API keys or sensitive parameters

### Safety Mechanisms
- All irrigation services respect safety limits
- Manual override provides emergency stop capability
- System-level enable/disable overrides all automation

---

## Related Documentation

### For Setup
- **[Installation Guide](../user-guides/02-installation.md)** - Set up services
- **[Daily Operation](../user-guides/04-daily-operation.md)** - Using services operationally

### For Integration
- **[Automation Examples](../examples/automation-examples.md)** - Service usage in automations
- **[Entity Reference](entity-reference.md)** - Related entities and sensors

### For Troubleshooting
- **[Troubleshooting Guide](../user-guides/05-troubleshooting.md)** - Service-related issues

---

**💡 Service Tips:**
- Test services manually in Developer Tools before automation
- Use appropriate shot_type parameters for tracking and debugging
- Monitor events to understand service execution
- Implement error handling in automations using service calls
- Consider service rate limits when designing frequent automations