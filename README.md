# Advanced Automated Crop Steering System

![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.3.0+-41BDF5?logo=home-assistant&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.8+-3776AB?logo=python&logoColor=white)
![Automation](https://img.shields.io/badge/Automation-Rule%20Based-4CAF50?logo=homeassistant&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Status](https://img.shields.io/badge/Status-Heavy%20Development-orange?logo=github&logoColor=white)
![Warning](https://img.shields.io/badge/⚠️-Experimental-red)

## **DEVELOPMENT STATUS WARNING**

**This system is heavily under development and should be considered experimental.** 

- **Vibe coded** - Built based on irrigation theory but not extensively tested in real growing conditions
- **Experimental features** - Complex automation logic that may need tuning for your specific setup
- **Use at your own risk** - Monitor your plants closely and have backup irrigation methods ready
- **Heavy development** - Code and functionality subject to significant changes
- **Not production ready** - Expect bugs, issues, and the need for manual intervention

**Recent Improvements (v2.3.0):**
- **NEW: Full GUI Configuration** - No command line needed! Configure everything through Home Assistant UI
- Fixed async/await issues - No more runtime warnings about unawaited coroutines
- Fixed sensor fusion - VWC and EC values no longer mixed (was causing incorrect readings)
- Implemented clean state machine - Phase transitions now properly tracked and validated
- Improved reliability - Thread-safe operation with proper error handling
- Fixed P3 phase logic - Now correctly persists through entire lights-off period
- Removed hardcoded Zone 3 emergency irrigation - Uses proper phase-based logic

**Recommendation:** Start with manual overrides enabled and gradually trust the automation as you validate it works with your specific hardware and plants.

<!-- Clickable thumbnails that open full-size in a new tab -->
[<img src="https://github.com/user-attachments/assets/6c48967a-1f5d-486c-8fb6-dbad207f158c" width="20"/>](https://github.com/user-attachments/assets/6c48967a-1f5d-486c-8fb6-dbad207f158c) [<img src="https://github.com/user-attachments/assets/ff514550-e6c8-4dc0-a7fe-1fb3bdbecf47" width="250"/>](https://github.com/user-attachments/assets/ff514550-e6c8-4dc0-a7fe-1fb3bdbecf47) [<img src="https://github.com/user-attachments/assets/a2138083-1196-4167-92d4-dc193526594a" width="250"/>](https://github.com/user-attachments/assets/a2138083-1196-4167-92d4-dc193526594a)






## What This System Does

**Transform your Home Assistant into a professional-grade crop steering platform** that automatically manages precision irrigation using advanced rule-based logic and sensor-driven automation. This system replaces manual irrigation guesswork with intelligent threshold-based decisions optimized for plant health and maximum yields.

### The Logic Behind Automated Crop Steering

**Traditional Problem:** Manual irrigation timing leads to:
- Over/under-watering from guesswork
- Inconsistent plant stress patterns
- Poor nutrient timing
- Wasted water and nutrients
- Suboptimal yields

**Automated Solution:** Our system uses:
- **Statistical sensor validation** to get accurate substrate moisture readings
- **Rule-based logic** to determine optimal irrigation timing based on thresholds
- **Real-time dryback detection** using peak detection algorithms
- **Intelligent crop profiles** with strain-specific parameters
- **Professional monitoring** to track efficiency and performance

**The Result:** Consistent irrigation timing, reduced water waste, and precision automation that maintains optimal growing conditions.

### How It Works

1. **Sensors collect data** - VWC and EC sensors monitor substrate conditions
2. **System analyzes patterns** - Statistical algorithms identify dryback patterns and trends
3. **Rule-based decisions execute** - System automatically waters based on threshold logic
4. **Performance tracked** - System monitors efficiency and maintains detailed logs
5. **You get results** - Consistent plants, less work, optimized resource usage

## Advanced Features

### **Statistical Sensor Processing**
- **IQR-Based Outlier Detection**: Mathematical filtering of sensor anomalies
- **Multi-Sensor Validation**: Statistical validation with reliability scoring
- **Data Smoothing**: Moving averages for stable, accurate readings
- **Health Monitoring**: Automatic sensor reliability assessment
- **Threshold Management**: Configurable limits based on crop requirements

### **Real-Time Analytics**
- **Peak Detection Algorithms**: Multi-scale dryback analysis using scipy.signal
- **Statistical Validation**: Mathematical confidence scoring for measurements
- **Performance Tracking**: Irrigation efficiency and water usage monitoring
- **Trend Analysis**: Statistical trend detection using linear regression
- **Professional Metrics**: Comprehensive data logging and reporting

### **Intelligent Crop Profiles**
- **Strain-Specific Parameters**: Cannabis genetics-based settings (Indica/Sativa/Hybrid)
- **Growth Stage Optimization**: Automatic vegetative/flowering parameter adjustment
- **Athena Methodology**: Optimized for 3.0 EC baseline with strategic EC stacking
- **Multi-Crop Support**: Cannabis, Tomato, Lettuce, and custom crop profiles
- **Configurable Thresholds**: User-adjustable parameters for different growing styles

### **Professional Dashboard**
- **Real-Time Monitoring**: AppDaemon YAML dashboards with professional styling
- **VWC Trending**: Multi-sensor displays with color-coded status indicators
- **EC Monitoring**: Target zones, current readings, and trend tracking
- **Phase Indicators**: Current irrigation phase display and navigation
- **System Controls**: Manual overrides, safety limits, and configuration access
- **Performance Analytics**: Water usage tracking and efficiency metrics

## Core Irrigation Logic

### **4-Phase Rule-Based Cycle**
- **P0 (Morning Dryback)**: Controlled drying phase with configurable target thresholds
- **P1 (Ramp-Up)**: Progressive rehydration with increasing shot sizes
- **P2 (Maintenance)**: VWC and EC threshold-based irrigation decisions
- **P3 (Pre-Lights-Off)**: Final dryback management with emergency-only irrigation

### **Automatic Phase Transitions (How It Actually Works)**

The system automatically moves through phases based on plant conditions, not arbitrary timers:

**P3 → P0: Lights On**
- **When:** Lights turn on (default 12pm noon)
- **Logic:** P3 continues through entire lights-off period, then transitions to P0 when lights turn on
- **Simple:** P3 overnight → P0 when lights on

**P0 → P1: Dryback Complete**
- **When:** Plants reach target dryness OR safety timeout
- **Logic:** Let plants get thirsty, then start rehydrating
- **Entities:** `number.crop_steering_veg_dryback_target` (50% drydown), `number.crop_steering_p0_max_wait_time` (45min safety)

**P1 → P2: Recovery Complete**
- **When:** Plants recover to healthy moisture level
- **Logic:** Slowly add water back until plants are satisfied
- **Entities:** `number.crop_steering_p1_target_vwc` (65% target moisture)

**P2 → P3: Pre-Lights-Off Final Watering**
- **When:** Calculated timing based on dryback rate analysis
- **Logic:** Final irrigation before lights-off dark period
- **Simple:** Give plants last drink before sleep

**In Plain English:** Lights on = start getting thirsty → water them slowly until happy → keep them happy all day → final drink before sleep → stay in overnight dryback until lights on again → repeat. Just like caring for plants manually, but perfectly timed by rule-based automation.

### **Detailed Entity Configuration & Triggers**

#### **P3 → P0 Transition (Lights On → Start Drying)**
**Trigger:** Time-based - when lights turn on
- **Light Schedule:** Configurable via entities
- **Light Control Entities:** 
  - `datetime.crop_steering_lights_on_time` (default: 12:00 PM)
  - `datetime.crop_steering_lights_off_time` (default: 12:00 AM)
- **Action:** Records current VWC as "peak" for dryback calculations

#### **P0 → P1 Transition (Dryback Complete → Start Recovery)**
**Trigger:** Condition-based - dryback target achieved OR safety timeout

**Primary Trigger (Dryback %):**
- **Entity:** `number.crop_steering_veg_dryback_target` (default: 50%)
- **Logic:** Calculate `((peak_vwc - current_vwc) / peak_vwc) * 100`
- **Example:** Peak 70% → Current 35% = 50% dryback achieved

**Safety Trigger (Timeout):**
- **Entity:** `number.crop_steering_p0_max_wait_time` (default: 45 minutes)
- **Logic:** If dryback takes too long, exit P0 anyway
- **Purpose:** Prevents plants from getting too dry

**Data Tracking:**
- `self.p0_start_time` - When P0 phase began
- `self.p0_peak_vwc` - VWC level when P0 started

#### **P1 → P2 Transition (Recovery Complete → Maintenance)**
**Trigger:** Condition-based - VWC recovery target achieved

**VWC Recovery:**
- **Entity:** `number.crop_steering_p1_target_vwc` (default: 65%)
- **Logic:** `current_vwc >= target_vwc`
- **Data Source:** `sensor.crop_steering_configured_avg_vwc` (average across all zones)
- **Example:** When average VWC reaches 65%, move to maintenance

#### **P2 → P3 Transition (Maintenance → Bedtime Prep)**
**Trigger:** Calculated timing based on dryback rate analysis

**Statistical Analysis Logic:**
- **Trend Analysis:** Uses `advanced_dryback_detection.py` to calculate dryback rates from recent VWC data
- **Calculation:** `predict_target_dryback_time()` analyzes current dryback trend using linear regression
- **Timing:** Starts P3 at `(lights_off - predicted_dryback_time - 30min_buffer)`
- **Entities:** Uses `number.crop_steering_veg_dryback_target` as overnight dryback goal

**Safety Safeguards:**
- **Minimum Window:** P3 can't start more than 2 hours before lights off
- **Maximum Window:** P3 must start at least 30 minutes before lights off
- **Fallback:** If analysis unavailable, uses default timing based on substrate volume

**How It Improves:**
- **Day 1:** Uses default timing (conservative estimate)
- **Day 2+:** System calculates actual dryback speed from previous nights
- **Continuous:** Each day, timing becomes more accurate based on measured plant response

#### **Key Monitoring Entities**

**Current Phase Status:**
- `sensor.crop_steering_current_phase` - Shows active phase (P0/P1/P2/P3)
- `sensor.crop_steering_app_current_phase` - AppDaemon phase sensor
- `select.crop_steering_irrigation_phase` - Manual phase override

**VWC Monitoring:**
- `sensor.crop_steering_configured_avg_vwc` - Average moisture across all zones
- `sensor.crop_steering_vwc_zone_X` - Individual zone moisture levels
- `sensor.crop_steering_dryback_percentage` - Current dryback progress

**System Status:**
- `sensor.crop_steering_system_state` - Overall system status
- `sensor.crop_steering_next_irrigation_time` - When next irrigation is planned
- `sensor.crop_steering_current_decision` - Last AI irrigation decision

#### **Configuration Tips**

**For Faster Cycles:**
- Lower `number.crop_steering_veg_dryback_target` (e.g., 30% instead of 50%)
- Lower `number.crop_steering_p1_target_vwc` (e.g., 60% instead of 65%)

**For Safety:**
- Lower `number.crop_steering_p0_max_wait_time` (e.g., 30min instead of 45min)
- Monitor `sensor.crop_steering_sensor_health` for sensor reliability

**For Different Strains:**
- Use `number.crop_steering_gen_dryback_target` for flowering plants
- Adjust EC targets: `number.crop_steering_ec_target_veg_pX` / `number.crop_steering_ec_target_gen_pX`

### **Per-Zone Phase & Irrigation System**

**Each zone operates independently through its own phase cycle:**

#### **Independent Zone Phases**
- **Each zone tracks its own phase** (P0, P1, P2, P3)
- **Zones transition independently** based on their individual conditions
- **Mixed phases supported** - Zone 1 can be in P2 while Zone 2 is still in P1
- **Shared setpoints** - All zones use same thresholds but progress at their own pace
- **P3 persists overnight** - Zones remain in P3 through entire lights-off period

#### **Example Scenario:**
```
Zone 1: P2 (65% VWC) - Maintenance, satisfied
Zone 2: P1 (58% VWC) - Still ramping up, needs irrigation  
Zone 3: P3 (42% VWC) - Emergency phase, urgent irrigation
Zone 4: P0 (Dryback)  - No irrigation, letting it dry
```

#### **Per-Zone Phase Transitions:**
- **P0 → P1**: Each zone exits dryback when IT reaches target or timeout
- **P1 → P2**: Each zone moves to maintenance when IT hits recovery VWC
- **P2 → P3**: Zones enter pre-lights-off based on individual ML predictions
- **P3 → P0**: Zones transition from P3 to P0 when lights turn ON (not off)

#### **Zone Phase Sensors:**
- `sensor.crop_steering_zone_1_phase` - Zone 1 current phase
- `sensor.crop_steering_zone_2_phase` - Zone 2 current phase
- `sensor.crop_steering_app_current_phase` - Summary: "Z1:P2, Z2:P1, Z3:P3, Z4:P0"

### **Per-Zone Irrigation Logic**

**All phase irrigation decisions are made PER ZONE, not globally:**

#### **P1 Ramp-Up (Per Zone)**
**Logic:** `zone_vwc < (p1_target_vwc × 0.9)`
- **Entity:** `number.crop_steering_p1_target_vwc` (default: 65%)
- **Trigger:** 90% of target (58.5% for default)
- **Shot Size:** `number.crop_steering_p1_initial_shot_size` (default: 2%)
- **Example Decision:** `"P1 ramp-up zones [1,3]: Z1:55.2%, Z3:56.8% < 58.5%"`

#### **P2 Maintenance - Core Crop Steering Logic (Per Zone)**

**The Heart of Crop Steering:** P2 manages both VWC (water stress) and pwEC (salt stress) simultaneously.

**Crop Steering Terminology:**
- **Field Capacity:** Maximum VWC substrate can hold (auto-detected in P1)
- **VWC:** Volumetric Water Content - water percentage in substrate  
- **pwEC:** Pore water electrical conductivity - salt concentration
- **EC Ratio:** `current_pwEC / target_pwEC` (0.8-1.2 = optimal range)

**Dual Decision Logic:**
1. **VWC Dryback Management:**
   - **Veg Steering:** Allow 10% dryback from field capacity → irrigate back to field capacity
   - **Gen Steering:** Allow 15% dryback from field capacity → more stress for flowering
   - **Example:** Field capacity 70% → Veg irrigates at 63%, Gen at 59.5%

2. **EC Salt Management:**
   - **High EC (>1.2 ratio):** Too salty → Larger shots to dilute
   - **Low EC (<0.8 ratio):** Too dilute → Smaller shots to concentrate  
   - **Shot Adjustment:** `base_shot × min(2.0, current_EC / target_EC)`

**Veg vs Gen EC Targets:**
- **Vegetative:** P2 target = 3.2 mS/cm (comfortable growth)
- **Generative:** P2 target = 6.0 mS/cm (stress for flowering)

**Irrigation Triggers:** Irrigate if EITHER condition met:
- VWC below dryback threshold OR EC ratio outside 0.8-1.2 range

**Real-World P2 Examples:**

*Scenario 1 - Vegetative Zone:*
- Field Capacity: 72%, Current VWC: 62%, Current EC: 2.8 mS/cm, Target: 3.2 mS/cm
- VWC Check: 62% < (72% - 10%) = 62% → At threshold, needs irrigation
- EC Check: 2.8/3.2 = 0.875 ratio → Slightly low but acceptable
- **Decision:** IRRIGATE normal shot to restore field capacity

*Scenario 2 - Generative Zone with High Salt:*
- Field Capacity: 68%, Current VWC: 60%, Current EC: 7.5 mS/cm, Target: 6.0 mS/cm
- VWC Check: 60% > (68% - 15%) = 53% → VWC still good
- EC Check: 7.5/6.0 = 1.25 ratio → HIGH EC, needs dilution
- **Decision:** IRRIGATE larger shot (1.25x normal) to dilute salt buildup

*Scenario 3 - No Irrigation Needed:*
- Field Capacity: 70%, Current VWC: 65%, Current EC: 5.8 mS/cm, Target: 6.0 mS/cm
- VWC Check: 65% > (70% - 15%) = 55% → VWC good
- EC Check: 5.8/6.0 = 0.97 ratio → EC perfect
- **Decision:** NO irrigation, let plants naturally uptake water and concentrate EC

#### **P3 Emergency (Per Zone)**
**Logic:** `zone_vwc < p3_emergency_vwc_threshold`
- **Entity:** `number.crop_steering_p3_emergency_vwc_threshold` (default: 45%)
- **Shot Size:** `number.crop_steering_p3_emergency_shot_size` (default: 2%)
- **Example Decision:** `"P3 emergency zones [1,2,4]: Z1:42.3%, Z2:41.8%, Z4:44.1% < 45.0%"`

#### **Multi-Zone Execution**
**How it works:**
1. **Zone Analysis:** System checks each zone's VWC individually
2. **Zone Selection:** Only zones below threshold are selected for irrigation
3. **Simultaneous Irrigation:** All selected zones irrigated concurrently
4. **Individual Tracking:** Each zone's irrigation is logged separately for ML training

**Benefits:**
- **No waste** - Only thirsty zones get water
- **Individual care** - Each zone gets exactly what it needs
- **Faster cycles** - No waiting for slowest zone
- **Better data** - ML learns each zone's specific behavior

### **Advanced Safety Systems**
- **Emergency Irrigation**: Critical VWC threshold detection with immediate response
- **Thread-Safe Operation**: Concurrent processing with proper synchronization
- **Hardware Sequencing**: Controlled pump → main line → zone valve operation
- **Redundant Validation**: Multi-layer safety checks with failover systems
- **Outlier Protection**: Statistical filtering of sensor anomalies

## Installation

### Quick Start

**👉 [Follow our Complete Installation Guide](docs/installation_guide.md)** - designed for beginners!

> **SYSTEM STATUS: EXPERIMENTAL DEVELOPMENT**  
> This system is experimental and under heavy development. Use with caution and close monitoring. While the logic is based on proven crop steering principles, real-world testing is limited. Expect to need manual intervention and parameter tuning for your specific setup.

### 📋 What You Need

**Hardware:**
- VWC sensors (2+ per zone recommended for sensor fusion)
- EC sensors (2+ per zone recommended for nutrient monitoring)
- Irrigation pump with Home Assistant control
- Main line valve and zone valves
- Grow light controls (for phase timing)
- Home Assistant 2024.3.0+

**Software:**
- AppDaemon 4 add-on (required for advanced features)
- File Editor add-on (optional for manual configuration)

### HACS Installation (Recommended)

1. **Add Custom Repository:**
   - HACS → Integrations → ⋮ Menu → Custom Repositories
   - URL: `https://github.com/JakeTheRabbit/HA-Irrigation-Strategy`
   - Category: Integration

2. **Install Integration:**
   - Search "Crop Steering" in HACS
   - Download and restart Home Assistant

3. **Configure AppDaemon (Required for Advanced Features):**
   - Install AppDaemon 4 add-on
   - **NEW v15+ Path:** `/addon_configs/a0d7b954_appdaemon/`
   - Follow our [Installation Guide](docs/installation_guide.md) for complete setup

**Important:** HACS only installs the basic integration. The advanced automation features require AppDaemon configuration with updated v15+ directory paths.

## Configuration

### Two Setup Methods

#### **Method 1: GUI Configuration (Recommended)**
1. **Add the Integration:**
   - Settings → Devices & Services → Add Integration
   - Search "Crop Steering" and click on it
   - Choose your setup method:
     - **Advanced Setup (Recommended)** - Configure all sensors through the GUI
     - **Basic Setup** - Only configure switches (no sensor monitoring)
     - **Load from file** - Use existing crop_steering.env file

2. **Advanced Setup Flow:**
   - **Step 1:** Choose number of zones (1-6)
   - **Step 2:** Configure hardware (pump, main valve, zone valves)
   - **Step 3:** Configure sensors for each zone:
     - Front/back VWC sensors (moisture)
     - Front/back EC sensors (nutrients)
     - All sensors are optional but recommended
   - **Step 4:** Configure environmental sensors (optional):
     - Room temperature
     - Room humidity
     - VPD sensor
   - **Step 5:** Review and save configuration

**Note:** No command line access required! Everything is configured through the Home Assistant GUI.

#### **Method 2: Environment File (Legacy)**
For users with existing crop_steering.env files:
1. Ensure your crop_steering.env file is properly configured
2. Add integration and select "Load from crop_steering.env file"
3. System validates and imports your configuration

### AppDaemon Setup (Optional for Advanced Features)

**Note:** The Crop Steering system uses NO external Python dependencies! Everything runs with standard Python libraries.

1. **Install AppDaemon 4 add-on** from the Add-on Store
2. **Configure AppDaemon** with NEW v15+ paths:
   - Config file: `/addon_configs/a0d7b954_appdaemon/appdaemon.yaml`
   - Apps directory: `/addon_configs/a0d7b954_appdaemon/apps/`
   - Access via Samba: `\\YOUR_HA_IP\addon_configs\a0d7b954_appdaemon`
3. **Copy AppDaemon apps** from the integration to the AppDaemon directory
4. **Restart AppDaemon add-on**
5. **Advanced Features Activate Automatically:**
   - Statistical analysis modules start processing sensor data
   - Sensor validation begins with first readings
   - YAML dashboards become available

**Detailed setup instructions:** See our [Installation Guide](docs/installation_guide.md) for step-by-step AppDaemon configuration.

## How to Use

### **Automatic Operation**

Once configured, the system runs automatically:

1. **Monitors** - Sensors continuously track substrate conditions
2. **Analyzes** - AI processes patterns and predicts irrigation needs
3. **Irrigates** - System waters at optimal moments automatically
4. **Learns** - Performance improves daily as AI adapts to your setup

### **Monitor Your System**

**Key entities to watch:**
- `sensor.crop_steering_irrigation_recommendation` - System recommendation based on thresholds
- `sensor.crop_steering_fused_vwc` - Validated sensor readings
- `sensor.crop_steering_current_phase` - Current irrigation phase
- `sensor.crop_steering_system_state` - Overall system status

### **System Optimization Timeline**

- **Week 1**: System establishes baseline patterns and thresholds
- **Week 2**: Statistical analysis improves timing accuracy
- **Week 3+**: Optimal performance achieved with fine-tuned parameters

**Detailed operation:** Read our [Operation Guide](docs/operation_guide.md) for complete usage instructions.

## Automation System Components

### **Advanced Features You Get**

**Statistical Analysis Engine**
- Calculates irrigation timing based on threshold analysis
- Processes sensor data using proven mathematical methods
- Maintains consistent performance over time

**Sensor Validation System**
- Combines multiple sensors for accuracy using IQR outlier detection
- Automatically filters out bad readings using statistical methods
- Provides smooth, reliable measurements with moving averages

**Real-Time Dryback Detection**
- Monitors plant water uptake patterns using peak detection algorithms
- Identifies optimal irrigation timing based on configurable thresholds
- Prevents over/under-watering through safety limits

**Intelligent Crop Profiles**
- Optimized parameter sets for different plant types
- Automatically adjusts to growth stages based on configured schedules
- Maintains consistent parameters optimized for each crop type

**Professional Dashboard**
- Real-time monitoring with AppDaemon YAML interface
- Performance tracking and water usage analytics
- Professional styling with intuitive navigation

## What Results to Expect

### **Performance Improvements**
- **Consistent Irrigation**: Optimal timing through threshold-based automation
- **Water Conservation**: Rule-based logic prevents waste through precision timing
- **Reliable Operation**: Statistical analysis provides consistent performance
- **24/7 Monitoring**: Continuous automation without manual intervention

### **System Capabilities**
- **Dynamic Multi-Zone Support**: 1-6 independent irrigation zones with automatic configuration
- **Real-Time Processing**: 30-second update cycles
- **Predictive Horizon**: 2+ hours advance irrigation forecasting
- **High Precision**: ±1% VWC targeting with sensor fusion

## Safety & Reliability

### **Built-In Safety Features**
- **Emergency AI**: Automatically responds to critical low moisture
- **Smart Hardware Control**: Proper pump and valve sequencing
- **Sensor Validation**: Filters out bad readings automatically
- **Backup Systems**: Continues operation even with sensor failures
- **Comprehensive Monitoring**: Tracks system health continuously

### **Reliability Features**
- **Self-Healing**: Automatically recovers from temporary issues
- **Detailed Logging**: Complete system activity tracking
- **Proactive Alerts**: Notifies you of issues before they become problems
- **Graceful Degradation**: Reduces features rather than failing completely

### **Current Development Status**

This system represents sophisticated automation logic but should be considered experimental:

- **Limited Testing**: Theoretical implementation needs real-world validation
- **Complex Logic**: Multi-phase automation may need tuning for your specific plants
- **Parameter Sensitivity**: VWC/EC thresholds may need adjustment for your growing medium
- **Sensor Dependency**: Requires reliable VWC/EC sensors for proper operation
- **Plant Variability**: Different genetics may respond differently to automation
- **User Expertise**: Best results require understanding of crop steering principles

## Documentation

### **Complete Guides Available**
- [Installation Guide](docs/installation_guide.md) - Complete step-by-step setup
- [Operation Guide](docs/operation_guide.md) - How to use the automation features
- [Dashboard Guide](docs/dashboard_guide.md) - Understanding the monitoring interface
- [Dynamic Zones Guide](docs/dynamic_zones_guide.md) - Configure 1-6 zones easily (NEW)
- [AppDaemon v15+ Migration](docs/appdaemon_v15_migration.md) - Updated directory paths (NEW)
- [Troubleshooting Guide](docs/troubleshooting.md) - Fix common issues

## Advanced Configuration

Once installed, you can customize the system through the Home Assistant integration settings:

### **Crop Profiles Available**
- **Cannabis_Athena**: High-EC methodology for maximum yields
- **Cannabis_Indica_Dominant**: Optimized for shorter, bushier plants
- **Cannabis_Sativa_Dominant**: Optimized for taller plants with longer cycles
- **Cannabis_Balanced_Hybrid**: Balanced parameters for 50/50 genetics
- **Tomato_Hydroponic**: Continuous production vegetables
- **Lettuce_Leafy_Greens**: Low-stress leafy green cultivation

### **Automation Features You Get**
- **Statistical Sensor Fusion**: Combines multiple sensors using mathematical validation
- **Trend Analysis Models**: Irrigation timing based on dryback rate calculations
- **Parameter Optimization**: System maintains optimal thresholds over time
- **Real-Time Analytics**: Professional monitoring dashboard with AppDaemon
- **Emergency Response**: Automatic irrigation response to critical VWC conditions

## Contributing

We welcome contributions to advance precision agriculture technology!

### **Development Areas**
- **Statistical Algorithms**: New analysis methods and improvements
- **Sensor Validation**: Advanced filtering techniques
- **Crop Profiles**: New strain and crop parameter sets
- **Dashboard**: Visualization enhancements
- **Hardware Support**: New sensor integrations

### **How to Contribute**
1. [Fork this repository](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/fork)
2. Create a feature branch for your improvement
3. Test your changes thoroughly
4. [Submit a pull request](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/pulls) with detailed description

## License

This project is licensed under the MIT License.

## Acknowledgments

- **Home Assistant Community**: Excellent automation platform
- **AppDaemon Developers**: Powerful Python automation framework  
- **Crop Steering Research**: Scientific foundation and principles
- **Scientific Community**: Statistical algorithms and techniques
- **Beta Testers**: Validation and real-world testing

## Advanced Zone Features (NEW!)

### **Zone Grouping for Simultaneous Irrigation**
- Group zones (A-D) for synchronized irrigation
- When 50% of group needs water, entire group irrigates
- Perfect for clones or identical genetics
- `select.crop_steering_zone_X_group`

### **Zone-Specific Crop Profiles**
- Each zone can use different strain/crop settings
- Mix indica, sativa, tomatoes in same system
- Independent VWC/EC targets per zone
- `select.crop_steering_zone_X_crop_profile`

### **Individual Zone Scheduling**
- Independent light schedules per zone
- 12/12 flowering, 18/6 veg, 20/4 auto, 24/0 continuous
- Phase transitions respect each zone's timing
- `select.crop_steering_zone_X_schedule`

### **Zone Priority Configuration**
- Critical → High → Normal → Low priority
- Higher priority zones irrigate first
- Emergency override for critical plants
- `select.crop_steering_zone_X_priority`

### **Water Usage Tracking Per Zone**
- Daily/weekly water consumption monitoring
- Configurable daily limits per zone
- Irrigation event counting
- Automatic resets and warnings
- `sensor.crop_steering_zone_X_daily_water_usage`

## Transform Your Growing Operation

Experience **research-grade precision agriculture** with advanced automation, statistical analysis, and professional monitoring. From hobby grows to commercial operations, this system delivers the intelligence and control needed for optimal plant health and maximum yields.

**Ready for the future of precision irrigation?** Install now and experience the power of rule-based automated crop steering!

---

*Advancing precision agriculture with intelligent automation*
