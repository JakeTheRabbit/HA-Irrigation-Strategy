# Advanced Zone Features Implementation Summary

## New Features Implemented

### 1. Zone Grouping for Simultaneous Irrigation ✅
**How it works:**
- Each zone can be assigned to a group (Ungrouped, Group A-D)
- When 50% or more zones in a group need water, ALL zones in that group irrigate together
- Prevents uneven growth in zones with similar plants
- Entity: `select.crop_steering_zone_X_group`

**Example scenario:**
- Zone 1 & 2 are in "Group A" (same strain clones)
- Zone 1 drops below threshold and needs water
- System checks: only 1 of 2 zones (50%) needs water
- Both Zone 1 & 2 irrigate together to maintain uniformity

### 2. Zone-Specific Crop Profiles ✅
**How it works:**
- Each zone can have its own crop profile or follow the main profile
- Supports different strains/stages in different zones
- Entity: `select.crop_steering_zone_X_crop_profile`
- Options: Follow Main, Cannabis_Athena, Cannabis_Indica_Dominant, etc.

**Example scenario:**
- Zone 1: Cannabis_Indica (vegetative) - higher VWC targets
- Zone 2: Cannabis_Sativa (flowering) - lower VWC, aggressive dryback
- Zone 3: Tomato_Hydroponic - continuous production parameters

### 3. Individual Zone Scheduling ✅
**How it works:**
- Each zone can have independent light schedules
- Supports different photoperiods per zone
- Entities: 
  - `select.crop_steering_zone_X_schedule`
  - `number.crop_steering_zone_X_lights_on_hour`
  - `number.crop_steering_zone_X_lights_off_hour`

**Schedule options:**
- Main Schedule (12pm-12am default)
- 12/12 Flowering (6am-6pm)
- 18/6 Vegetative (6am-12am)
- 20/4 Auto (2am-10pm)
- 24/0 Continuous
- Custom (set specific hours)

**Example scenario:**
- Zone 1: 18/6 veg schedule
- Zone 2: 12/12 flowering schedule
- Zone 3: 20/4 autoflower schedule
- Each zone transitions phases based on its own lights

### 4. Zone Priority Configuration ✅
**How it works:**
- Zones can be prioritized: Critical > High > Normal > Low
- Higher priority zones irrigate first when multiple need water
- Critical zones can interrupt lower priority irrigation
- Entity: `select.crop_steering_zone_X_priority`

**Example scenario:**
- Zone 1 (Critical): Mother plants - always get water first
- Zone 2 (High): Flowering week 8 - important but not critical
- Zone 3 (Normal): Veg plants - standard priority
- Zone 4 (Low): Experimental plants - water only after others

### 5. Water Usage Tracking Per Zone ✅
**How it works:**
- Tracks daily and weekly water usage per zone
- Counts irrigation events per day
- Enforces daily water limits
- Resets counters automatically
- Entities:
  - `sensor.crop_steering_zone_X_daily_water_usage`
  - `sensor.crop_steering_zone_X_weekly_water_usage`
  - `sensor.crop_steering_zone_X_irrigation_count_today`
  - `sensor.crop_steering_zone_X_last_irrigation`
  - `number.crop_steering_zone_X_max_daily_volume`

**Calculation:**
```
Volume = dripper_flow_rate × drippers_per_zone × (duration/3600) × shot_multiplier
```

**Example tracking:**
- Zone 1: Used 12.5L today (5 irrigations) - Limit: 20L
- Zone 2: Used 18.2L today (8 irrigations) - Warning at 90%
- Zone 3: Used 20.1L today (9 irrigations) - LIMIT REACHED

### 6. Zone Shot Size Multiplier ✅
**New feature added:**
- Each zone can have different shot sizes
- Entity: `number.crop_steering_zone_X_shot_size_multiplier`
- Range: 0.5x to 2.0x
- Useful for different pot sizes or plant sizes

## Configuration Entities Per Zone

### Select Entities (Dropdowns)
- `select.crop_steering_zone_X_group` - Grouping assignment
- `select.crop_steering_zone_X_priority` - Priority level
- `select.crop_steering_zone_X_crop_profile` - Crop type
- `select.crop_steering_zone_X_schedule` - Light schedule

### Number Entities (Sliders)
- `number.crop_steering_zone_X_lights_on_hour` - Custom lights on
- `number.crop_steering_zone_X_lights_off_hour` - Custom lights off
- `number.crop_steering_zone_X_max_daily_volume` - Daily water limit
- `number.crop_steering_zone_X_shot_size_multiplier` - Shot adjustment

### Sensor Entities (Read-only)
- `sensor.crop_steering_zone_X_phase` - Current phase (P0-P3)
- `sensor.crop_steering_zone_X_daily_water_usage` - Today's usage
- `sensor.crop_steering_zone_X_weekly_water_usage` - Week's usage
- `sensor.crop_steering_zone_X_irrigation_count_today` - Event count
- `sensor.crop_steering_zone_X_last_irrigation` - Last watered

## Practical Usage Examples

### Multi-Stage Grow Room
```
Zone 1: Clones (Group A, High Priority, 24/0 light, 10L limit)
Zone 2: Veg Week 2 (Group B, Normal, 18/6 light, 15L limit)
Zone 3: Flower Week 4 (Ungrouped, High, 12/12 light, 20L limit)
Zone 4: Flower Week 8 (Ungrouped, Critical, 12/12 light, 25L limit)
```

### Research Facility
```
Zone 1: Control Group (Group A, Normal, Cannabis_Athena)
Zone 2: High EC Test (Group B, Normal, Custom profile)
Zone 3: Drought Stress (Ungrouped, Low, Modified dryback)
Zone 4: Continuous Flow (Ungrouped, Normal, 24/0 light)
```

### Commercial Operation
```
All zones: Group A (uniform irrigation)
All zones: Normal priority (equal treatment)
Zones 1-3: Cannabis_Indica profile
Zone 4: Cannabis_Sativa profile
All zones: 12/12 flowering schedule
Water limits: 30L/day per zone
```

## Conflict Resolution

### Group vs Individual Needs
- If Zone 1 needs water but Zone 2 (same group) doesn't
- System checks: Is 50% of group thirsty?
- If yes: Both irrigate together
- If no: Only Zone 1 irrigates

### Priority Conflicts
- Multiple zones need water simultaneously
- System irrigates in order: Critical → High → Normal → Low
- Same priority: Lower zone numbers first

### Water Limit Reached
- Zone reaches daily limit (e.g., 20L)
- System logs warning
- Zone excluded from irrigation until reset
- Emergency override available for Critical priority

### Schedule Conflicts
- Each zone follows its own light schedule
- P0 starts when THAT zone's lights turn off
- P3 timing calculated for THAT zone's schedule
- No cross-zone interference

## Dashboard Display Recommendations

### Zone Status Card
```yaml
type: entities
title: Zone Status Overview
entities:
  - entity: sensor.crop_steering_zone_1_phase
    name: Zone 1
    secondary_info: last-changed
  - entity: sensor.crop_steering_zone_1_daily_water_usage
    name: Water Today
  - entity: select.crop_steering_zone_1_group
    name: Group
  - entity: select.crop_steering_zone_1_priority
    name: Priority
```

### Water Usage Graph
```yaml
type: history-graph
title: Daily Water Usage
entities:
  - sensor.crop_steering_zone_1_daily_water_usage
  - sensor.crop_steering_zone_2_daily_water_usage
  - sensor.crop_steering_zone_3_daily_water_usage
  - sensor.crop_steering_zone_4_daily_water_usage
```

## Benefits of New Features

1. **Flexibility**: Run different experiments or crops simultaneously
2. **Efficiency**: Group irrigation reduces pump cycling
3. **Precision**: Zone-specific profiles optimize each area
4. **Monitoring**: Track resource usage per zone
5. **Prioritization**: Critical plants always get water
6. **Automation**: Each zone self-manages based on its schedule
7. **Scalability**: Easy to add/remove zones as needed