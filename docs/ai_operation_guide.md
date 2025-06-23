# 🧠 AI System Operation Guide

This guide covers the complete operation of the Advanced AI Crop Steering System, from initial setup through daily operation and optimization.

## 📋 Table of Contents

1. [System Overview](#system-overview)
2. [Initial Setup](#initial-setup)
3. [AI Learning Phase](#ai-learning-phase)
4. [Daily Operation](#daily-operation)
5. [Monitoring & Analytics](#monitoring--analytics)
6. [Advanced Features](#advanced-features)
7. [Troubleshooting](#troubleshooting)

## 🎯 System Overview

### AI Components

The system consists of 6 integrated AI modules:

| Module | Function | Purpose |
|--------|----------|---------|
| **Master Coordinator** | Main control logic | Orchestrates all AI decisions |
| **Dryback Detector** | Peak/valley analysis | Real-time dryback monitoring |
| **Sensor Fusion** | Multi-sensor validation | Reliable sensor readings |
| **ML Predictor** | Irrigation forecasting | 2-hour irrigation predictions |
| **Crop Profiles** | Strain optimization | Plant-specific parameters |
| **Dashboard** | Real-time monitoring | Professional analytics |

### Key Entities

Monitor these entities for system status:

```yaml
# Core System Status
sensor.crop_steering_system_state         # active/disabled
sensor.crop_steering_current_phase        # P0, P1, P2, P3
sensor.crop_steering_current_decision     # wait/irrigate

# AI Predictions
sensor.crop_steering_ml_irrigation_need   # 0.0-1.0 (0-100%)
sensor.crop_steering_ml_confidence        # Model confidence
sensor.crop_steering_ml_model_accuracy    # R² score

# Sensor Fusion
sensor.crop_steering_fused_vwc            # Multi-sensor VWC
sensor.crop_steering_fused_ec             # Multi-sensor EC
sensor.crop_steering_sensor_health        # Health count

# Dryback Analysis
sensor.crop_steering_dryback_percentage   # Current dryback %
binary_sensor.crop_steering_dryback_in_progress # Active/inactive
```

## 🚀 Initial Setup

### 1. Hardware Verification

Ensure all sensors are connected and reporting:

```bash
# Check sensor status in Home Assistant
# Go to Developer Tools > States
# Filter by your sensor entities

# Example sensor check:
sensor.vwc_r1_front: 45.2%
sensor.vwc_r1_back: 46.1%
sensor.ec_r1_front: 3.4 mS/cm
sensor.ec_r1_back: 3.6 mS/cm
```

### 2. Integration Configuration

Add the integration and configure sensors:

1. **Go to Settings → Devices & Services**
2. **Add Integration → "Crop Steering System"**
3. **Configure sensor entities:**
   ```yaml
   VWC Sensors:
   - sensor.vwc_r1_front
   - sensor.vwc_r1_back
   - sensor.vwc_r2_front
   # ... add all sensors
   
   EC Sensors:
   - sensor.ec_r1_front
   - sensor.ec_r1_back
   # ... add all sensors
   
   Hardware:
   - Pump: switch.f1_irrigation_pump_master_switch
   - Main Line: switch.espoe_irrigation_relay_1_2
   - Zone 1: switch.f1_irrigation_relays_relay_1
   # ... add all zones
   ```

### 3. AppDaemon Installation

Install AI modules:

> **📝 Note:** AI modules are automatically installed via AppDaemon add-on configuration. No manual package installation required.

**AppDaemon Setup:**
1. Install AppDaemon 4 add-on from Home Assistant
2. Configure with required Python packages (handled automatically)
3. Copy AI modules to `/addon_configs/a0d7b954_appdaemon/apps/`
4. Check logs: `/addon_configs/a0d7b954_appdaemon/logs/`

### 4. Crop Profile Selection

Choose your crop profile for optimal AI performance:

```yaml
# In Home Assistant:
# Settings → Devices & Services → Crop Steering System
# Configure crop profile:

Cannabis Profiles:
- Cannabis_Athena          # High-EC Athena methodology
- Cannabis_Indica_Dominant # Higher moisture, shorter plants
- Cannabis_Sativa_Dominant # Lower moisture, taller plants
- Cannabis_Balanced_Hybrid # 50/50 genetics

Other Crops:
- Tomato_Hydroponic       # Continuous production
- Lettuce_Leafy_Greens    # Low-stress cultivation
```

## 🔬 AI Learning Phase

### Week 1: Initial Learning

**What's Happening:**
- ML models collect initial training data
- Sensor fusion establishes reliability scores
- Dryback patterns begin detection
- Crop profile parameters load

**Expected Behavior:**
- System operates conservatively
- ML predictions start at 50% confidence
- Sensor fusion learning sensor characteristics
- Dashboard shows "Learning" status

**Monitor These Entities:**
```yaml
sensor.crop_steering_ml_confidence: 0.3-0.5  # Initial range
sensor.crop_steering_sensor_health: improving # Health scores
sensor.crop_steering_ml_irrigation_need: 0.4-0.6 # Conservative
```

### Week 2: Pattern Recognition

**What's Happening:**
- Dryback patterns become reliable
- ML models identify irrigation timing patterns
- Sensor outlier detection improves
- Profile parameters begin adapting

**Expected Behavior:**
- More confident irrigation decisions
- Better sensor outlier detection
- Improved dryback timing predictions
- Profile-specific optimizations begin

**Monitor These Entities:**
```yaml
sensor.crop_steering_ml_confidence: 0.5-0.7  # Improving
sensor.crop_steering_dryback_percentage: consistent # Patterns
sensor.crop_steering_irrigation_efficiency: 0.6-0.8 # Improving
```

### Week 3+: Optimal Performance

**What's Happening:**
- ML models reach high accuracy (90%+)
- Predictive irrigation recommendations
- Adaptive parameter tuning active
- Full system optimization

**Expected Behavior:**
- Highly accurate irrigation timing
- Excellent sensor validation
- Predictive maintenance alerts
- Maximum irrigation efficiency

**Monitor These Entities:**
```yaml
sensor.crop_steering_ml_confidence: 0.8-0.99 # High confidence
sensor.crop_steering_ml_model_accuracy: 0.9+ # R² score
sensor.crop_steering_irrigation_efficiency: 0.8+ # High efficiency
```

## 🎮 Daily Operation

### Morning Startup (Lights On)

**Automatic Actions:**
1. **Phase P0 begins** - Morning dryback starts
2. **AI monitors** - Dryback progress tracking
3. **Safety checks** - Emergency irrigation monitoring
4. **Predictions** - 2-hour irrigation forecasting

**Monitor Dashboard:**
- VWC trending shows declining pattern
- Dryback percentage increases toward target
- ML predictions show increasing irrigation need
- No emergency alerts

### Midday Operation (Peak Activity)

**Automatic Actions:**
1. **Phase P1** - AI-guided ramp-up irrigation
2. **Phase P2** - Maintenance irrigation with EC adjustment
3. **Sensor fusion** - Continuous multi-sensor validation
4. **Learning** - ML models collect training data

**Monitor Dashboard:**
- VWC maintains target range
- EC stays within profile parameters
- Irrigation efficiency tracking
- Sensor health monitoring

### Evening Transition (Pre-Lights Off)

**Automatic Actions:**
1. **Phase P3** - Predictive final dryback
2. **Emergency prevention** - Critical VWC protection
3. **Performance analysis** - Day's efficiency calculation
4. **Model updates** - ML training with day's data

**Monitor Dashboard:**
- Controlled final dryback
- No emergency irrigation triggers
- Performance metrics updated
- ML confidence maintained

### Night Monitoring (Lights Off)

**Automatic Actions:**
1. **Reduced monitoring** - Lower update frequency
2. **Emergency only** - Critical condition monitoring
3. **Data processing** - Background ML training
4. **Health checks** - Sensor reliability assessment

**Monitor Dashboard:**
- Stable VWC levels
- No irrigation activity
- System health indicators
- Next day preparation

## 📊 Monitoring & Analytics

### Real-Time Dashboard

Access the advanced dashboard through:
```yaml
# Dashboard entity
sensor.crop_steering_dashboard_html

# Key visualization sections:
1. VWC Trending - Multi-sensor fusion with confidence bands
2. EC Monitoring - Target zones and stacking analysis
3. Dryback Analysis - Peak/valley detection with timing
4. ML Predictions - Irrigation probability forecasts
5. Sensor Health - Reliability heatmaps
6. Performance - Efficiency and water usage metrics
```

### Key Performance Indicators (KPIs)

Monitor these metrics for optimal performance:

| Metric | Target Range | Description |
|--------|--------------|-------------|
| **ML Confidence** | 0.8-0.99 | Model prediction confidence |
| **Irrigation Efficiency** | 0.8+ | Success rate of irrigation shots |
| **Sensor Health** | 90%+ | Percentage of healthy sensors |
| **Dryback Accuracy** | ±2% | Hitting target dryback percentage |
| **VWC Stability** | ±3% | VWC variation within targets |
| **System Uptime** | 99%+ | AI system availability |

### Alerts & Notifications

The system generates automatic alerts for:

```yaml
Critical Alerts:
- Emergency VWC levels (<40%)
- Sensor failures (offline/faulty)
- ML model degradation (<60% confidence)
- Hardware malfunction

Warning Alerts:
- High outlier rates (>20%)
- Irrigation efficiency decline (<60%)
- Dryback target misses (>5% variance)
- Profile parameter adaptation needed

Info Alerts:
- ML model retraining completed
- New optimal parameters discovered
- Sensor reliability improvements
- Performance milestone achieved
```

## 🔧 Advanced Features

### Custom Crop Profiles

Create custom profiles for specific strains:

```python
# Access through AppDaemon
custom_profile = crop_profiles.create_custom_profile(
    profile_name="My_Custom_Strain",
    base_profile="Cannabis_Balanced_Hybrid",
    modifications={
        'parameters': {
            'vegetative': {
                'vwc_target_min': 52,  # Slightly higher moisture
                'dryback_target': 12,  # Shorter drybacks
                'ec_baseline': 2.8     # Lower starting EC
            }
        }
    }
)
```

### ML Model Optimization

Adjust ML parameters for your specific setup:

```python
# Access through AppDaemon
ml_predictor.configure({
    'prediction_horizon': 180,    # 3-hour predictions
    'retrain_frequency': 30,      # More frequent retraining
    'confidence_threshold': 0.8,  # Higher confidence requirement
    'feature_importance_min': 0.05 # Feature selection threshold
})
```

### Sensor Fusion Tuning

Optimize sensor fusion for your hardware:

```python
# Access through AppDaemon
sensor_fusion.configure({
    'outlier_multiplier': 1.2,     # More sensitive outlier detection
    'min_sensors_required': 3,     # Require more sensors for fusion
    'confidence_threshold': 0.7,   # Higher confidence threshold
    'kalman_process_noise': 0.05   # Adjust filtering aggressiveness
})
```

### Emergency Response

Configure emergency irrigation parameters:

```yaml
# In integration configuration
emergency_config:
  critical_vwc_threshold: 35     # Emergency irrigation trigger
  emergency_duration: 90        # Seconds of emergency irrigation
  max_emergency_frequency: 300  # 5 minutes between emergency shots
  emergency_zones: [1, 2, 3]    # All zones for emergency
```

## 🔍 Troubleshooting

### Common Issues

#### ML Models Not Learning

**Symptoms:**
- ML confidence stays below 0.6
- Predictions remain at 0.5
- No model retraining messages in logs

**Solutions:**
```python
# Check training data
ml_status = ml_predictor.get_model_status()
print(f"Training samples: {ml_status['training_samples']}")
print(f"Features available: {ml_status['feature_importance']}")

# Reset if needed
ml_predictor.reset_models()
```

#### Sensor Fusion Issues

**Symptoms:**
- High outlier rates (>30%)
- Fused values showing as None
- Sensor health declining

**Solutions:**
```python
# Check sensor health
health_report = sensor_fusion.get_sensor_health_report()
print(f"Healthy sensors: {health_report['healthy_sensors']}")
print(f"Faulty sensors: {health_report['faulty_sensors']}")

# Adjust thresholds
sensor_fusion.outlier_multiplier = 2.0  # Less sensitive
```

#### Dryback Detection Problems

**Symptoms:**
- No dryback detection
- Confidence scores below 0.5
- No peak/valley detection

**Solutions:**
```python
# Check detection parameters
dryback_status = dryback_detector._get_status_dict()
print(f"Peaks detected: {dryback_status['peaks_detected']}")
print(f"Data points: {dryback_status['data_points']}")

# Reset if needed
dryback_detector.reset_analysis()
```

### Performance Optimization

#### Improve ML Accuracy

1. **More training data**: Let system run longer (3+ weeks)
2. **Better features**: Add environmental sensors
3. **Clean data**: Fix sensor outliers and calibration
4. **Frequent retraining**: Increase retrain frequency

#### Enhance Sensor Fusion

1. **Add sensors**: More sensors = better fusion
2. **Calibrate regularly**: Maintain sensor accuracy
3. **Adjust thresholds**: Tune for your specific hardware
4. **Monitor health**: Replace faulty sensors promptly

#### Optimize Dryback Detection

1. **Stable environment**: Reduce external disturbances
2. **Consistent irrigation**: Regular irrigation patterns
3. **Quality sensors**: High-resolution VWC sensors
4. **Proper calibration**: Substrate-specific calibration

### System Maintenance

#### Weekly Tasks

- Review ML performance metrics
- Check sensor health reports
- Validate irrigation efficiency
- Monitor system alerts

#### Monthly Tasks

- Calibrate sensors
- Review crop profile performance
- Optimize ML parameters
- Backup system configuration

#### Quarterly Tasks

- Deep performance analysis
- Hardware inspection
- Software updates
- System optimization review

## 📈 Performance Tuning

### Maximizing Efficiency

Follow these guidelines for optimal performance:

1. **Sensor Quality**: Use high-quality, calibrated sensors
2. **Stable Environment**: Minimize external disturbances
3. **Consistent Power**: Ensure stable electrical supply
4. **Regular Maintenance**: Keep sensors clean and calibrated
5. **Data Quality**: Monitor for and fix sensor issues
6. **Parameter Tuning**: Adjust based on performance metrics

### Expected Performance Timeline

| Week | ML Confidence | Accuracy | Efficiency | Features |
|------|--------------|----------|------------|----------|
| 1 | 0.3-0.5 | 60-70% | 0.5-0.6 | Basic learning |
| 2 | 0.5-0.7 | 70-80% | 0.6-0.7 | Pattern recognition |
| 3 | 0.7-0.9 | 80-90% | 0.7-0.8 | Optimization |
| 4+ | 0.8-0.99 | 90-99% | 0.8+ | Peak performance |

## 🎯 Success Metrics

### System Performance Goals

- **ML Confidence**: >0.8 sustained
- **Irrigation Efficiency**: >80%
- **Sensor Health**: >90% healthy
- **System Uptime**: >99%
- **Dryback Accuracy**: ±2% of target
- **Water Usage Optimization**: 10-25% reduction

### Crop Performance Indicators

- **Consistent Growth**: Steady vegetative development
- **Stress Response**: Controlled generative steering
- **Root Health**: Strong, white root development
- **Nutrient Uptake**: Stable EC in substrate
- **Overall Yield**: Improved harvest quality/quantity

## 📞 Support

For technical support:
- **GitHub Issues**: [Report bugs and feature requests](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/issues)
- **Documentation**: [Full documentation library](../README.md)
- **Community**: Home Assistant and AppDaemon forums
- **Logs**: Check AppDaemon logs for detailed system information

---

**Remember**: The AI system learns continuously. Better data quality and consistent operation lead to better performance over time!