# 📊 Dashboard Usage Guide

This guide covers how to use the AppDaemon YAML dashboards for monitoring and controlling your crop steering system.

## 🎯 Dashboard Overview

The system uses professional AppDaemon YAML dashboards that provide real-time monitoring and control of your irrigation system through a clean, intuitive interface.

### Key Features

- **Real-Time Status Monitoring**: Live system status, phase information, and zone status
- **Zone Control**: Individual zone enable/disable controls with visual status indicators  
- **Parameter Adjustment**: Easy access to key irrigation parameters
- **Phase Management**: Clear display of current phase (P0/P1/P2/P3) with transition controls
- **Safety Monitoring**: Emergency status, overrides, and system health indicators

## 📈 Dashboard Components

### 1. System Status Panel

**What it shows:**
- **Current Phase**: P0 (Morning Dryback), P1 (Ramp-Up), P2 (Maintenance), P3 (Pre-Lights-Off)
- **System Health**: Overall system status and any active alerts
- **Global Controls**: System enable/disable, auto irrigation toggle
- **Emergency Status**: Any emergency conditions or manual overrides

### 2. Zone Status Grid

**What it shows:**
- **Per-Zone Status**: Visual indicators for each configured zone (1-6)
- **Zone Controls**: Individual enable/disable switches for each zone
- **VWC/EC Readings**: Current sensor values for each zone
- **Zone Health**: Status indicators (Optimal/Dry/Saturated/Disabled/Sensor Error)

**Status Color Coding:**
```yaml
Green:    Optimal conditions
Yellow:   Attention needed (dry/saturated)
Red:      Error or critical condition
Gray:     Disabled or offline
```

### 3. Control Panel

**Key Controls:**
- **Phase Transition**: Manual phase control when needed
- **Manual Override**: Per-zone override controls
- **Irrigation Shot**: Emergency manual irrigation controls
- **Parameter Adjustment**: Quick access to critical settings

### 4. Monitoring Panel

**Live Data:**
- **VWC Trends**: Current volumetric water content readings
- **EC Monitoring**: Electrical conductivity levels
- **Irrigation History**: Recent irrigation events and timing
- **System Performance**: Efficiency metrics and water usage

## 🎮 Using the Dashboard

### Daily Operation

**Morning Routine:**
1. **Check System Status**: Verify all green indicators
2. **Review Zone Status**: Ensure all zones are optimal or as expected
3. **Monitor Phase Transition**: P0 should start automatically at lights-on
4. **Verify Sensors**: All zone sensors showing reasonable readings

**Throughout the Day:**
1. **Phase Monitoring**: Watch automatic P0→P1→P2→P3 transitions
2. **Zone Performance**: Monitor individual zone responses
3. **Parameter Adjustment**: Fine-tune settings based on plant response
4. **Alert Response**: Address any yellow/red status indicators

**Evening Check:**
1. **P3 Phase**: Verify pre-lights-off phase is active
2. **Final Irrigation**: Ensure appropriate final watering
3. **Overnight Setup**: System ready for lights-off period
4. **Performance Review**: Check day's irrigation efficiency

### Zone Management

**Individual Zone Control:**
- **Enable/Disable**: Toggle zones on/off as needed
- **Manual Override**: Take direct control when necessary  
- **Status Monitoring**: Watch for sensor errors or calibration needs
- **Parameter Override**: Adjust zone-specific settings

**Multi-Zone Coordination:**
- **Group Operations**: Manage related zones together
- **Priority Settings**: Set irrigation priority for each zone
- **Load Balancing**: Distribute irrigation timing across zones

### Parameter Adjustment

**Quick Access Controls:**
- **VWC Targets**: Adjust moisture targets per phase
- **Shot Sizes**: Modify irrigation volumes
- **Timing Controls**: Adjust phase durations and intervals
- **Safety Thresholds**: Set emergency irrigation triggers

## 📊 Monitoring and Analysis

### Real-Time Indicators

**System Health Monitoring:**
- **Green Status**: All systems operating normally
- **Yellow Warnings**: Attention needed, but not critical
- **Red Alerts**: Immediate action required
- **Gray Offline**: Components not responding

### Performance Tracking

**Key Metrics:**
- **Irrigation Efficiency**: Success rate of irrigation events
- **Water Usage**: Daily/weekly consumption tracking
- **Target Achievement**: How often system hits VWC/EC goals
- **Phase Timing**: Accuracy of phase transitions

### Troubleshooting Indicators

**Common Issues:**
```yaml
Sensor Error:     Check calibration, connections
Phase Stuck:      Manual phase transition may be needed  
High Water Usage: Review shot sizes and frequencies
Low Efficiency:   Check sensor accuracy, hardware function
```

## 🔧 Configuration Through Dashboard

### Basic Settings

**System Configuration:**
- **Zone Count**: Select number of active zones (1-6)
- **Light Schedule**: Set lights-on/lights-off times
- **Crop Profile**: Select plant type and growth stage
- **Safety Settings**: Configure emergency thresholds

### Advanced Parameters

**Irrigation Timing:**
- **P0 Settings**: Morning dryback parameters
- **P1 Controls**: Ramp-up shot sizes and timing
- **P2 Thresholds**: Maintenance phase triggers
- **P3 Timing**: Pre-lights-off irrigation controls

**Sensor Configuration:**
- **VWC Calibration**: Adjust moisture sensor readings
- **EC Calibration**: Set conductivity sensor parameters
- **Averaging Settings**: Configure multi-sensor fusion
- **Error Handling**: Set sensor failure responses

## 🚨 Alert Management

### Alert Types

**Critical Alerts (Red):**
- **Emergency VWC Low**: Immediate irrigation needed
- **Sensor Failure**: Hardware malfunction detected
- **System Offline**: Core components not responding
- **Safety Override Active**: Manual intervention in progress

**Warning Alerts (Yellow):**
- **High VWC**: Possible overwatering
- **Low Efficiency**: System performance degraded
- **Sensor Drift**: Calibration may be needed
- **Phase Timing**: Unexpected phase duration

**Info Alerts (Blue):**
- **Phase Transition**: Normal phase change completed
- **Irrigation Complete**: Scheduled watering finished
- **Parameter Change**: Settings updated successfully
- **System Ready**: All systems operational

### Alert Response

**Immediate Actions:**
1. **Read Alert Message**: Understand the specific issue
2. **Check System Status**: Verify current system state
3. **Review Recent Changes**: Identify potential causes
4. **Take Corrective Action**: Follow alert-specific guidance

## 📱 Mobile Access

### Responsive Design

The dashboard is fully responsive and works on:
- **Desktop Computers**: Full featured experience
- **Tablets**: Touch-optimized interface
- **Mobile Phones**: Essential controls and monitoring
- **Different Browsers**: Chrome, Firefox, Safari, Edge

### Mobile-Specific Features

**Quick Access:**
- **Zone Status**: Swipe through zone status cards
- **Emergency Controls**: Large, easy-to-tap emergency buttons  
- **Status Indicators**: High-contrast visual indicators
- **Alert Notifications**: Clear alert messages and actions

## 🔧 Dashboard Customization

### Layout Options

**Panel Arrangements:**
- **Standard Layout**: Balanced view of all components
- **Monitoring Focus**: Larger status displays
- **Control Focus**: Emphasized control panels
- **Mobile Layout**: Optimized for small screens

### Color Themes

**Available Themes:**
- **Professional**: Clean, modern appearance
- **High Contrast**: Enhanced visibility
- **Crop Green**: Plant-focused color scheme
- **Custom**: User-defined colors and styling

## 📞 Support and Troubleshooting

### Common Issues

**Dashboard Not Loading:**
1. Check AppDaemon is running
2. Verify network connectivity
3. Clear browser cache
4. Check for JavaScript errors

**Controls Not Responding:**
1. Verify Home Assistant connection
2. Check integration status
3. Restart AppDaemon if needed
4. Review entity configurations

**Missing Data:**
1. Check sensor connectivity
2. Verify entity names in configuration
3. Review AppDaemon logs
4. Test individual entities in HA

### Getting Help

**Documentation Resources:**
- [Installation Guide](installation_guide.md) - Setup instructions
- [Operation Guide](operation_guide.md) - Daily operation procedures  
- [Troubleshooting Guide](troubleshooting.md) - Problem resolution

**Community Support:**
- **GitHub Issues**: [Technical support](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/issues)
- **Home Assistant Forum**: Community discussions
- **AppDaemon Discord**: Real-time help

---

**Master Your Dashboard!** 📊

The AppDaemon YAML dashboard provides professional-grade monitoring and control for your crop steering system. With proper setup and regular monitoring, it becomes your central command center for precision irrigation.