# Home Assistant Crop Steering System - Complete Entity Reference

This document lists every single entity created by the Crop Steering System with detailed descriptions of their functions.

## 📊 SENSORS

### System-Wide Sensors

| Entity ID | Name | Description |
|-----------|------|-------------|
| `sensor.crop_steering_current_phase` | Current Phase | Shows current irrigation phase (P0/P1/P2/P3/Manual) |
| `sensor.crop_steering_irrigation_efficiency` | Irrigation Efficiency | System irrigation efficiency percentage |
| `sensor.crop_steering_water_usage_daily` | Daily Water Usage | Total daily water consumption across all zones (Liters) |
| `sensor.crop_steering_dryback_percentage` | Dryback Percentage | Current dryback percentage from peak VWC |
| `sensor.crop_steering_next_irrigation_time` | Next Irrigation Time | Predicted time for next irrigation event |
| `sensor.crop_steering_configured_avg_vwc` | Average VWC All Zones | Average VWC across all configured zones (%) |
| `sensor.crop_steering_configured_avg_ec` | Average EC All Zones | Average EC across all configured zones (mS/cm) |
| `sensor.crop_steering_ec_ratio` | EC Ratio | Current EC to target EC ratio |
| `sensor.crop_steering_p2_vwc_threshold_adjusted` | P2 VWC Threshold Adjusted | EC-adjusted P2 VWC threshold (%) |

### Shot Duration Calculation Sensors

| Entity ID | Name | Description |
|-----------|------|-------------|
| `sensor.crop_steering_p1_shot_duration_seconds` | P1 Shot Duration | Calculated P1 irrigation duration in seconds |
| `sensor.crop_steering_p2_shot_duration_seconds` | P2 Shot Duration | Calculated P2 irrigation duration in seconds |
| `sensor.crop_steering_p3_shot_duration_seconds` | P3 Emergency Shot Duration | Calculated P3 emergency irrigation duration in seconds |

### Analytics Sensors (AppDaemon Generated)

| Entity ID | Name | Description |
|-----------|------|-------------|
| `sensor.crop_steering_system_health_score` | System Health Score | Overall system health percentage (0-100%) |
| `sensor.crop_steering_daily_water_usage` | Daily Water Usage | System daily water consumption with analytics |
| `sensor.crop_steering_sensor_health` | Sensor Health | Overall sensor availability and health percentage |
| `sensor.crop_steering_system_efficiency` | System Efficiency | Combined system efficiency score |
| `sensor.crop_steering_water_efficiency` | Water Efficiency | Water use efficiency metric (VWC per liter) |
| `sensor.crop_steering_app_current_phase` | Zone Phases | Summary of all zone phases (Z1:P2, Z2:P1, etc.) |
| `sensor.crop_steering_app_next_irrigation` | Next Irrigation Time | AppDaemon calculated next irrigation time |
| `sensor.crop_steering_system_safety_status` | System Safety Status | Overall safety status (safe/warning/unsafe) |

### Zone-Specific Sensors (Per Zone 1-N)

| Entity ID Pattern | Name Pattern | Description |
|-------------------|--------------|-------------|
| `sensor.crop_steering_vwc_zone_{N}` | Zone {N} VWC | Volumetric Water Content for zone N (%) |
| `sensor.crop_steering_ec_zone_{N}` | Zone {N} EC | Electrical Conductivity for zone N (mS/cm) |
| `sensor.crop_steering_zone_{N}_status` | Zone {N} Status | Zone operational status (Optimal/Dry/Saturated/Error) |
| `sensor.crop_steering_zone_{N}_last_irrigation` | Zone {N} Last Irrigation | Timestamp of last irrigation for zone N |
| `sensor.crop_steering_zone_{N}_daily_water_usage` | Zone {N} Daily Water Usage | Daily water consumption for zone N (Liters) |
| `sensor.crop_steering_zone_{N}_weekly_water_usage` | Zone {N} Weekly Water Usage | Weekly water consumption for zone N (Liters) |
| `sensor.crop_steering_zone_{N}_irrigation_count_today` | Zone {N} Irrigations Today | Count of irrigations for zone N today |
| `sensor.crop_steering_zone_{N}_health_score` | Zone {N} Health Score | Zone health score based on VWC/EC (0-1) |
| `sensor.crop_steering_zone_{N}_efficiency` | Zone {N} Efficiency | Zone irrigation efficiency score |
| `sensor.crop_steering_zone_{N}_safety_status` | Zone {N} Safety Status | Zone safety status (safe/warning/unsafe) |

### Predictive Analytics Sensors (AppDaemon Generated)

| Entity ID Pattern | Name Pattern | Description |
|-------------------|--------------|-------------|
| `sensor.crop_steering_prediction_zone_{N}_next_irrigation_hours` | Zone {N} Next Irrigation Hours | Predicted hours until zone N needs irrigation |
| `sensor.crop_steering_prediction_system_vwc_trend` | System VWC Trend | Predicted VWC trend (stable/declining/increasing) |
| `sensor.crop_steering_prediction_estimated_daily_water_need` | Estimated Daily Water Need | Predicted daily water requirement (Liters) |

## 🔢 NUMBER INPUTS

### Substrate & Hardware Configuration

| Entity ID | Name | Range | Unit | Description |
|-----------|------|-------|------|-------------|
| `number.crop_steering_substrate_volume` | Substrate Volume | 1.0-200.0 | L | Volume of growing medium per zone |
| `number.crop_steering_dripper_flow_rate` | Dripper Flow Rate | 0.1-50.0 | L/hr | Flow rate per individual dripper |
| `number.crop_steering_drippers_per_plant` | Drippers Per Plant | 1-6 | count | Number of drippers per individual plant |
| `number.crop_steering_field_capacity` | Field Capacity | 20.0-100.0 | % | Maximum safe VWC (over-watering protection) |
| `number.crop_steering_max_ec` | Maximum EC | 1.0-20.0 | mS/cm | Maximum safe EC (nutrient burn protection) |

### Dryback Target Configuration

| Entity ID | Name | Range | Unit | Description |
|-----------|------|-------|------|-------------|
| `number.crop_steering_veg_dryback_target` | Vegetative Dryback Target | 20.0-80.0 | % | Target VWC for vegetative dryback |
| `number.crop_steering_gen_dryback_target` | Generative Dryback Target | 15.0-70.0 | % | Target VWC for generative dryback |

### Phase Target Configuration

| Entity ID | Name | Range | Unit | Description |
|-----------|------|-------|------|-------------|
| `number.crop_steering_p1_target_vwc` | P1 Target VWC | 30.0-95.0 | % | Target VWC for P1 recovery phase |
| `number.crop_steering_p2_vwc_threshold` | P2 VWC Threshold | 25.0-85.0 | % | VWC threshold for P2 irrigation trigger |

### P0 Phase Parameters

| Entity ID | Name | Range | Unit | Description |
|-----------|------|-------|------|-------------|
| `number.crop_steering_p0_min_wait_time` | P0 Minimum Wait Time | 5.0-300.0 | min | Minimum duration in P0 phase |
| `number.crop_steering_p0_max_wait_time` | P0 Maximum Wait Time | 30.0-600.0 | min | Maximum duration in P0 phase (safety limit) |
| `number.crop_steering_p0_dryback_drop_percent` | P0 Dryback Drop Percent | 2.0-40.0 | % | Alternative exit condition for P0 phase |

### P1 Progressive Irrigation Parameters

| Entity ID | Name | Range | Unit | Description |
|-----------|------|-------|------|-------------|
| `number.crop_steering_p1_initial_shot_size` | P1 Initial Shot Size | 0.1-20.0 | % | Starting shot size for P1 progression |
| `number.crop_steering_p1_shot_increment` | P1 Shot Size Increment | 0.05-10.0 | % | Progressive increase per P1 shot |
| `number.crop_steering_p1_max_shot_size` | P1 Maximum Shot Size | 2.0-50.0 | % | Maximum shot size in P1 phase |
| `number.crop_steering_p1_time_between_shots` | P1 Time Between Shots | 1.0-60.0 | min | Time interval between P1 shots |
| `number.crop_steering_p1_max_shots` | P1 Maximum Shots | 1.0-30.0 | count | Maximum number of P1 shots |
| `number.crop_steering_p1_min_shots` | P1 Minimum Shots | 1.0-20.0 | count | Minimum number of P1 shots |

### P2 Maintenance Parameters

| Entity ID | Name | Range | Unit | Description |
|-----------|------|-------|------|-------------|
| `number.crop_steering_p2_shot_size` | P2 Shot Size | 0.5-30.0 | % | Standard shot size for P2 phase |
| `number.crop_steering_p2_ec_high_threshold` | P2 EC High Threshold | 0.50-3.00 | ratio | EC ratio threshold for reduced irrigation |
| `number.crop_steering_p2_ec_low_threshold` | P2 EC Low Threshold | 0.20-2.00 | ratio | EC ratio threshold for increased irrigation |

### P3 Final Phase Parameters

| Entity ID | Name | Range | Unit | Description |
|-----------|------|-------|------|-------------|
| `number.crop_steering_p3_veg_last_irrigation` | P3 Veg Last Irrigation | 15.0-360.0 | min | Last irrigation timing for vegetative phase |
| `number.crop_steering_p3_gen_last_irrigation` | P3 Gen Last Irrigation | 30.0-600.0 | min | Last irrigation timing for generative phase |
| `number.crop_steering_p3_emergency_vwc_threshold` | P3 Emergency VWC Threshold | 20.0-65.0 | % | VWC threshold for emergency irrigation |
| `number.crop_steering_p3_emergency_shot_size` | P3 Emergency Shot Size | 0.1-15.0 | % | Shot size for emergency irrigation |

### EC Target Parameters (Athena Methodology)

| Entity ID | Name | Range | Unit | Description |
|-----------|------|-------|------|-------------|
| `number.crop_steering_ec_target_flush` | EC Target Flush | 0.1-15.0 | mS/cm | Target EC for flush irrigation |
| `number.crop_steering_ec_target_veg_p0` | EC Target Veg P0 | 0.5-15.0 | mS/cm | EC target for vegetative P0 phase |
| `number.crop_steering_ec_target_veg_p1` | EC Target Veg P1 | 0.5-15.0 | mS/cm | EC target for vegetative P1 phase |
| `number.crop_steering_ec_target_veg_p2` | EC Target Veg P2 | 0.5-15.0 | mS/cm | EC target for vegetative P2 phase |
| `number.crop_steering_ec_target_veg_p3` | EC Target Veg P3 | 0.5-15.0 | mS/cm | EC target for vegetative P3 phase |
| `number.crop_steering_ec_target_gen_p0` | EC Target Gen P0 | 0.5-20.0 | mS/cm | EC target for generative P0 phase |
| `number.crop_steering_ec_target_gen_p1` | EC Target Gen P1 | 0.5-20.0 | mS/cm | EC target for generative P1 phase |
| `number.crop_steering_ec_target_gen_p2` | EC Target Gen P2 | 0.5-20.0 | mS/cm | EC target for generative P2 phase |
| `number.crop_steering_ec_target_gen_p3` | EC Target Gen P3 | 0.5-20.0 | mS/cm | EC target for generative P3 phase |

### System Light Schedule

| Entity ID | Name | Range | Unit | Description |
|-----------|------|-------|------|-------------|
| `number.crop_steering_lights_on_hour` | Lights On Hour | 0-23 | hour | Hour when lights turn on for the entire system |
| `number.crop_steering_lights_off_hour` | Lights Off Hour | 0-23 | hour | Hour when lights turn off for the entire system |

### Zone-Specific Numbers (Per Zone 1-N)

| Entity ID Pattern | Name Pattern | Range | Unit | Description |
|-------------------|--------------|-------|------|-------------|
| `number.crop_steering_zone_{N}_plant_count` | Zone {N} Plant Count | 1-50 | count | Number of plants in zone N |
| `number.crop_steering_zone_{N}_max_daily_volume` | Zone {N} Max Daily Volume | 0-200 | L | Maximum daily water volume for zone N |
| `number.crop_steering_zone_{N}_shot_size_multiplier` | Zone {N} Shot Size Multiplier | 0.1-5.0 | factor | Shot size adjustment factor for zone N |

## 🔄 SELECT ENTITIES

### System Configuration

| Entity ID | Name | Options | Description |
|-----------|------|---------|-------------|
| `select.crop_steering_crop_type` | Crop Type | Cannabis_Athena, Cannabis_Hybrid, Cannabis_Indica, Cannabis_Sativa, Tomato, Lettuce, Basil, Custom | Type of crop being grown |
| `select.crop_steering_growth_stage` | Growth Stage | Vegetative, Generative, Transition | Current growth stage |
| `select.crop_steering_steering_mode` | Steering Mode | Vegetative, Generative | Active steering mode |
| `select.crop_steering_irrigation_phase` | Irrigation Phase | P0, P1, P2, P3, Manual | Current irrigation phase |

### Zone-Specific Selects (Per Zone 1-N)

| Entity ID Pattern | Name Pattern | Options | Description |
|-------------------|--------------|---------|-------------|
| `select.crop_steering_zone_{N}_group` | Zone {N} Group | Ungrouped, Group A, Group B, Group C, Group D | Zone grouping for coordination |
| `select.crop_steering_zone_{N}_priority` | Zone {N} Priority | Critical, High, Normal, Low | Zone irrigation priority level |
| `select.crop_steering_zone_{N}_crop_profile` | Zone {N} Crop Profile | Follow Main, Cannabis_Athena, Cannabis_Indica_Dominant, Cannabis_Sativa_Dominant, Cannabis_Balanced_Hybrid, Tomato_Hydroponic, Lettuce_Leafy_Greens, Custom | Zone-specific crop profile |

## 🔘 SWITCHES

### System Control Switches

| Entity ID | Name | Description |
|-----------|------|-------------|
| `switch.crop_steering_system_enabled` | System Enabled | Master system enable/disable switch |
| `switch.crop_steering_auto_irrigation_enabled` | Auto Irrigation Enabled | Enable/disable automatic irrigation |
| `switch.crop_steering_ec_stacking_enabled` | EC Stacking Enabled | Enable EC-based shot stacking |
| `switch.crop_steering_analytics_enabled` | Analytics Enabled | Enable advanced statistical analysis features |
| `switch.crop_steering_debug_mode` | Debug Mode | Enable debug logging and verbose output |

### Zone Control Switches (Per Zone 1-N)

| Entity ID Pattern | Name Pattern | Description |
|-------------------|--------------|-------------|
| `switch.crop_steering_zone_{N}_enabled` | Zone {N} Enabled | Enable/disable zone N for irrigation |
| `switch.crop_steering_zone_{N}_manual_override` | Zone {N} Manual Override | Manual override switch for zone N (blocks auto irrigation) |

## 🛠️ SERVICES

### Phase Management Services

| Service ID | Parameters | Description |
|------------|------------|-------------|
| `crop_steering.transition_phase` | `target_phase`, `reason`, `forced` | Manually transition to specified irrigation phase |
| `crop_steering.check_transition_conditions` | None | Check if phase transition conditions are met |

### Irrigation Control Services

| Service ID | Parameters | Description |
|------------|------------|-------------|
| `crop_steering.execute_irrigation_shot` | `zone`, `duration_seconds`, `shot_type` | Execute manual irrigation shot for specified zone |
| `crop_steering.set_manual_override` | `zone`, `timeout_minutes`, `enable` | Set manual override for zone with optional timeout |

## 📋 ENTITY USAGE SUMMARY

### Total Entity Count by Type:
- **Sensors**: 70+ (varies by zone count)
- **Numbers**: 46+ (varies by zone count, includes per-zone plant counts)  
- **Selects**: 20+ (varies by zone count)
- **Switches**: 10+ (varies by zone count)
- **Services**: 4

### Key Features:
- **100% Entity Functionality**: All entities are fully functional and integrated
- **Zone Scalability**: Supports 1-10 zones with per-zone entities
- **Real-time Analytics**: Comprehensive monitoring and reporting
- **Safety Systems**: Multi-layer protection against over-watering and nutrient burn
- **Advanced Automation**: EC-based irrigation, progressive P1, intelligent phase transitions
- **Manual Control**: Complete override system with timeout functionality
- **Professional Monitoring**: Health scoring, efficiency metrics, predictive analytics

### Entity Categories:
1. **Configuration Entities**: Set system parameters and zone settings
2. **Control Entities**: Enable/disable features and manual overrides
3. **Monitoring Entities**: Real-time system status and analytics
4. **Safety Entities**: Critical safety limits and protection systems
5. **Analytics Entities**: Performance metrics and predictive data
6. **Zone Entities**: Per-zone controls and monitoring

This comprehensive entity system provides complete control over a professional-grade crop steering irrigation system with rule-based automation, safety systems, and real-time monitoring capabilities.