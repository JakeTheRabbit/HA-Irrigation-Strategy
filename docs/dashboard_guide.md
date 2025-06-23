# 📊 Dashboard Usage Guide

This guide covers how to use the Advanced AI Crop Steering Dashboard for monitoring, analysis, and optimization of your irrigation system.

## 🎯 Dashboard Overview

The Advanced Dashboard provides real-time visualization of your crop steering system with professional-grade analytics and Athena-style monitoring.

### Key Features

- **Real-Time VWC/EC Trending**: Multi-sensor fusion with confidence bands
- **Dryback Analysis**: Peak/valley detection with timing predictions
- **ML Predictions**: Irrigation probability forecasts with uncertainty bounds
- **Sensor Health**: Reliability monitoring and performance assessment
- **Performance Analytics**: Efficiency metrics and optimization insights

## 📈 Dashboard Components

### 1. VWC Trending Graph (Main Display)

**What it shows:**
- **Fused VWC Line**: Combined reading from all sensors (thick green line)
- **Individual Sensors**: Raw sensor readings (lighter dotted lines)
- **Confidence Bands**: Shaded areas showing fusion reliability
- **Outlier Markers**: Red X marks indicating rejected sensor readings
- **Target Zones**: Colored bands showing optimal VWC ranges
- **Dryback Markers**: Vertical lines indicating dryback events

**How to read it:**
```yaml
Green Line:    Fused VWC value (most reliable)
Dotted Lines:  Individual sensor readings
Red X Marks:   Outliers filtered out by AI
Shaded Areas:  Target VWC zones from crop profile
Orange Lines:  Dryback detection events
```

**Interpretation:**
- **Thick green line trending up**: Recent irrigation
- **Thick green line trending down**: Active dryback
- **Multiple red X marks**: Sensor calibration needed
- **Wide confidence bands**: Poor sensor agreement
- **Narrow confidence bands**: Excellent sensor reliability

### 2. EC Monitoring Graph

**What it shows:**
- **EC Trending**: Real-time electrical conductivity levels
- **Target Lines**: Baseline and maximum EC thresholds
- **Stacking Zones**: Strategic nutrient accumulation areas
- **Multi-Sensor Fusion**: Combined EC readings with reliability

**Key Indicators:**
```yaml
Green Dashed Line:  EC Baseline (target feeding level)
Red Dashed Line:    EC Maximum (caution threshold)
Thick Line:         Fused EC reading
Background Zones:   Optimal EC ranges
```

**Athena Methodology Integration:**
- **3.0 EC Baseline**: Standard Athena feeding concentration
- **4.0-6.0 EC Range**: Vegetative growth targets
- **6.0-9.0 EC Range**: Generative (flowering) targets
- **Strategic Stacking**: Controlled nutrient accumulation

### 3. Dryback Analysis Graph

**What it shows:**
- **Dryback Percentage**: Real-time calculation of substrate drying
- **Detection Confidence**: AI confidence in dryback measurements
- **Target Lines**: Optimal dryback percentages for current growth stage
- **Timing Predictions**: Forecasted completion times

**Understanding Dryback:**
- **10-15% Vegetative**: Aggressive growth promotion
- **15-20% Early Flower**: Transition to generative
- **20-25% Late Flower**: Maximum generative stress
- **25%+ Critical**: Emergency irrigation threshold

### 4. ML Predictions Graph

**What it shows:**
- **Irrigation Probability**: 0-100% likelihood of irrigation need
- **Prediction Horizon**: 2+ hours into the future
- **Confidence Intervals**: Uncertainty bounds around predictions
- **Critical Thresholds**: Alert levels for immediate action

**Interpretation Guide:**
```yaml
0-30%:    Low irrigation need (system stable)
30-50%:   Moderate need (monitor closely)
50-70%:   High need (irrigation likely soon)
70-90%:   Critical need (irrigation recommended)
90-100%:  Emergency (immediate irrigation required)
```

### 5. Sensor Health Heatmap

**What it shows:**
- **Reliability Scores**: 0-1.0 reliability rating per sensor
- **Outlier Rates**: Percentage of readings rejected
- **Health Status**: Color-coded sensor condition
- **Performance Trends**: Historical reliability changes

**Health Status Colors:**
- **Green**: Excellent (>90% reliability)
- **Yellow**: Good (70-90% reliability)
- **Orange**: Degraded (50-70% reliability)
- **Red**: Faulty (<50% reliability)
- **Gray**: Offline (no recent data)

### 6. Performance Analytics Dashboard

**What it shows:**
- **Irrigation Efficiency**: Success rate of irrigation events
- **Water Usage Trends**: Historical consumption analysis
- **Target Achievement**: How often system hits goals
- **System Health Score**: Overall system performance

**Key Metrics:**
```yaml
Irrigation Efficiency:  80%+ is excellent
Target Achievement:     85%+ indicates good tuning
System Health:         90%+ shows stable operation
Water Usage Trend:     Should show optimization over time
```

## 🎮 Interactive Features

### Real-Time Updates

The dashboard updates every 30 seconds with:
- **Live sensor readings**
- **Updated ML predictions**
- **Refresh dryback analysis**
- **Current system status**

### Time Range Selection

Adjust viewing window:
- **Last 1 Hour**: Detailed recent activity
- **Last 6 Hours**: Half-day irrigation cycle
- **Last 24 Hours**: Full daily cycle (default)
- **Last 7 Days**: Weekly trends and patterns

### Zoom and Pan

Navigate graphs:
- **Mouse Wheel**: Zoom in/out on specific time periods
- **Click and Drag**: Pan across time ranges
- **Double Click**: Reset to full view
- **Hover**: View exact values at specific times

## 📊 Monitoring Best Practices

### Daily Monitoring Routine

**Morning Check (Lights On):**
1. **Review overnight stability**: VWC should be stable
2. **Check sensor health**: All sensors green/yellow status
3. **Verify dryback start**: P0 phase beginning properly
4. **Monitor ML confidence**: Should be >70% after learning period

**Midday Review (Peak Activity):**
1. **VWC trending**: Oscillating between shots
2. **EC levels**: Within target ranges
3. **Irrigation efficiency**: Recent shots achieving targets
4. **Phase transitions**: P1→P2 happening automatically

**Evening Assessment (Pre-Lights Off):**
1. **Final dryback**: P3 phase progressing correctly
2. **Performance metrics**: Day's efficiency calculation
3. **Sensor reliability**: No degraded sensors
4. **ML predictions**: Confident forecasts for tomorrow

### Weekly Analysis

**Performance Review:**
- **Average irrigation efficiency**: Should trend upward
- **ML model accuracy**: Should improve over time
- **Sensor health trends**: Identify failing sensors early
- **Water usage optimization**: Track consumption reduction

**System Optimization:**
- **Crop profile adjustments**: Based on plant response
- **ML parameter tuning**: If confidence is consistently low
- **Sensor calibration**: For sensors with high outlier rates
- **Hardware maintenance**: Based on reliability trends

## 🚨 Alert Interpretation

### Critical Alerts (Red)

**Emergency VWC Low (<35%)**
```yaml
Immediate Action: Manual irrigation required
Check: Sensor calibration, hardware failure
System Response: Emergency irrigation if enabled
```

**Sensor System Failure**
```yaml
Immediate Action: Check hardware connections
Check: Power supply, network connectivity
System Response: Fallback to single-sensor operation
```

**ML Confidence Collapsed (<30%)**
```yaml
Immediate Action: Review recent changes
Check: Sensor data quality, parameter changes
System Response: Conservative irrigation decisions
```

### Warning Alerts (Orange)

**High Outlier Rate (>20%)**
```yaml
Action: Calibrate affected sensors
Check: Sensor placement, environmental factors
System Response: Reduced weight in sensor fusion
```

**Irrigation Efficiency Low (<60%)**
```yaml
Action: Review irrigation parameters
Check: Hardware function, sensor accuracy
System Response: Parameter adjustment recommendations
```

**Dryback Target Missed**
```yaml
Action: Check crop profile settings
Check: Environmental conditions, plant response
System Response: Adaptive profile adjustments
```

### Info Alerts (Blue)

**ML Model Retrained**
```yaml
Information: New training completed
Impact: Potentially improved predictions
Action: Monitor confidence improvement
```

**Profile Parameters Adapted**
```yaml
Information: Automatic optimization occurred
Impact: Better plant-specific parameters
Action: Review adapted parameters
```

## 🔧 Troubleshooting Dashboard Issues

### Graph Not Updating

**Possible Causes:**
1. **AppDaemon not running**: Check AppDaemon status
2. **Sensor data issues**: Verify sensor connectivity
3. **Browser cache**: Refresh page or clear cache
4. **Network issues**: Check Home Assistant connectivity

**Solutions:**
```bash
# Check AppDaemon status
tail -f /addon_configs/a0d7b954_appdaemon/logs/crop_steering_dashboard.log

# Restart AppDaemon if needed
# Home Assistant > Settings > Add-ons > AppDaemon > Restart

# Clear browser cache
# Browser > Settings > Clear Cache
```

### Missing Data Points

**Possible Causes:**
1. **Sensor offline**: Individual sensor failure
2. **Fusion failure**: Insufficient reliable sensors
3. **Data storage**: History buffer overflow
4. **Configuration error**: Wrong entity names

**Solutions:**
```bash
# Check sensor entities
# Developer Tools > States > Filter by sensor names

# Verify entity configuration
# Settings > Devices & Services > Crop Steering System
```

### Performance Slow

**Possible Causes:**
1. **High update frequency**: Too many updates
2. **Large data sets**: Excessive history retention
3. **Complex graphs**: Too many data series
4. **System resources**: Insufficient CPU/RAM

**Solutions:**
```yaml
# Reduce update frequency in AppDaemon configuration
update_interval: 60  # Increase from 30 seconds

# Reduce history retention
max_data_points: 1440  # Reduce from 2880

# Simplify graphs
# Remove unused sensor traces
```

## 📈 Advanced Dashboard Features

### Custom Graph Creation

Create specialized monitoring views:

```python
# Example: Custom VWC analysis
custom_graph = {
    'data': [
        {
            'x': timestamps,
            'y': vwc_values,
            'type': 'scatter',
            'mode': 'lines',
            'name': 'Custom VWC Analysis'
        }
    ],
    'layout': {
        'title': 'Custom Crop Analysis',
        'xaxis': {'title': 'Time'},
        'yaxis': {'title': 'VWC (%)'}
    }
}
```

### Data Export

Export dashboard data for analysis:

```yaml
# Available export formats
CSV Export:     Raw sensor data
JSON Export:    Complete system state
PDF Reports:    Dashboard snapshots
Excel Format:   Analysis-ready datasets
```

### Integration with External Tools

Connect to external analytics:

```yaml
InfluxDB:       Time-series database integration
Grafana:        Advanced visualization platform
Excel:          Spreadsheet analysis
Python/R:       Custom data science workflows
```

## 🎯 Optimization Strategies

### Performance Tuning

**High-Performance Setup:**
- **Dedicated hardware**: Separate machine for AI processing
- **SSD storage**: Fast data access for ML operations
- **Sufficient RAM**: 8GB+ for optimal AI performance
- **Stable network**: Reliable sensor data collection

**Resource Conservation:**
- **Reduce update frequency**: 60-120 second intervals
- **Limit history retention**: 24-48 hours of data
- **Selective monitoring**: Focus on critical metrics
- **Efficient sensors**: Use high-quality, stable sensors

### Data Quality Improvement

**Sensor Calibration:**
- **Regular calibration**: Monthly sensor verification
- **Cross-validation**: Compare sensors against standards
- **Environmental stability**: Minimize external disturbances
- **Proper installation**: Follow manufacturer guidelines

**Noise Reduction:**
- **Stable power supply**: Clean electrical connections
- **EMI shielding**: Protect from electromagnetic interference
- **Temperature stability**: Control sensor environment
- **Mechanical isolation**: Prevent vibration effects

## 📞 Support and Resources

### Documentation Links
- [AI Operation Guide](ai_operation_guide.md) - Complete operational procedures
- [Installation Guide](installation_guide.md) - Setup and configuration
- [Troubleshooting Guide](troubleshooting.md) - Problem resolution

### Community Resources
- **GitHub Issues**: [Technical support](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/issues)
- **Home Assistant Forum**: Community discussions
- **AppDaemon Discord**: Real-time help

### Professional Support
- **System Integration**: Custom installation services
- **Performance Optimization**: Advanced tuning services
- **Training Programs**: Operational training courses
- **Custom Development**: Specialized feature development

---

**Master Your Dashboard!** 📊

With proper understanding and regular monitoring, the Advanced AI Dashboard becomes your command center for precision irrigation and optimal plant health.