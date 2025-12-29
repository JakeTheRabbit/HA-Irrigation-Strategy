# ⚠️ CRITICAL INSTALLATION WARNINGS

**READ THIS BEFORE INSTALLING**

## 1. AppDaemon is REQUIRED (Not Optional)

Despite what some documentation may say, **AppDaemon is absolutely required** for this system to automate irrigation.

### What Works WITHOUT AppDaemon:
- ✅ Home Assistant entities (sensors, numbers, switches, selects)
- ✅ Manual service calls via Developer Tools
- ✅ Entity calculations (shot durations, EC ratio, thresholds)
- ✅ Event firing (phase transitions, irrigation requests)

### What DOES NOT Work WITHOUT AppDaemon:
- ❌ **Automatic irrigation** - No hardware control happens
- ❌ **Phase transitions** - System won't move through P0→P1→P2→P3
- ❌ **Hardware sequencing** - Pump/valves won't be controlled
- ❌ **Decision making** - No logic to determine when to water

**Bottom Line:** The HA integration provides the *interface*, AppDaemon provides the *automation*.

---

## 2. AppDaemon Dependencies NOT Included

The AppDaemon modules require **scipy** and **numpy**, which are **NOT automatically installed** with AppDaemon.

### Installation Required:

```bash
# For AppDaemon Add-on (Supervised HA)
docker exec addon_a0d7b954_appdaemon pip install scipy numpy

# For standalone AppDaemon
pip install scipy numpy

# Verify installation
docker exec addon_a0d7b954_appdaemon python3 -c "import scipy; import numpy; print('OK')"
```

### What Breaks Without scipy/numpy:
- ❌ Advanced dryback detection (multi-scale peak finding)
- ❌ Sensor fusion (IQR outlier detection)
- ❌ ML irrigation predictor
- ⚠️ System may still run but with degraded functionality

---

## 3. Dashboard is DISABLED

The "Advanced Dashboard Application" mentioned in documentation is **currently disabled** in `apps.yaml`.

### Reason:
```yaml
# apps.yaml line 18:
# DISABLED: Requires plotly/pandas dependencies not available in AppDaemon
```

### What This Means:
- ❌ No real-time Athena-style monitoring dashboard
- ❌ No advanced analytics graphs
- ✅ Basic entity monitoring still available in HA Lovelace

### To Enable (Experimental):
```bash
docker exec addon_a0d7b954_appdaemon pip install plotly pandas
# Then uncomment dashboard section in apps.yaml
```

**Warning:** Plotly/pandas add significant overhead. Not recommended for production.

---

## 4. Test Helpers Are Created Automatically

As of v2.3.1, test helper entities (input_boolean, input_number) are now created automatically during integration setup.

### What Gets Created:
- ~26 input_boolean entities (pumps, valves, status indicators)
- ~17 input_number entities per zone (VWC, EC, temperature sensors)
- Total: 26 + (17 × num_zones) entities

### If You Don't Want Test Helpers:
Test helpers will be created regardless. To remove them:
1. Go to Settings → Devices & Services → Helpers
2. Filter by "test" or manually find `input_boolean.*` and `input_number.*` entities
3. Delete unwanted helpers manually

**Note:** Test helpers allow development/testing without physical hardware.

---

## 5. Hardware Control Event-Driven

The integration **does not directly control hardware switches**. It fires events that AppDaemon listens to.

### Event Flow:
```
User/Automation → Service Call → Integration → Event Fired → AppDaemon → Hardware Control
```

### Example:
```yaml
# This service call:
service: crop_steering.execute_irrigation_shot
data:
  zone: 1
  duration_seconds: 60

# Does NOT turn on pump/valves directly
# It fires event: crop_steering_irrigation_shot
# AppDaemon must listen and control switches
```

**Critical:** Configure AppDaemon's hardware mappings correctly or irrigation won't work.

---

## 6. Entity Validation During Setup

As of v2.3.1, the config flow validates that mapped entity IDs exist in Home Assistant.

### What Happens:
- ✅ System checks if `switch.water_pump` exists before accepting config
- ✅ Warns about missing sensors
- ❌ Blocks setup if critical entities missing

### Best Practice:
1. Create/configure all hardware entities FIRST
2. Then install Crop Steering integration
3. Map to existing entities during config flow

---

## 7. Minimum Requirements

### Hardware (or simulated):
- Home Assistant 2024.3.0+
- Supported platform (RPi4+ recommended for AppDaemon overhead)
- Minimum 1GB RAM (2GB+ recommended with AppDaemon)

### Software:
- Home Assistant integration: **No dependencies**
- AppDaemon 4.x: **Required**
- Python packages in AppDaemon: scipy, numpy

### Sensors (real or simulated):
- VWC sensors (at least 1 per zone)
- EC sensors (at least 1 per zone)
- Optional: temperature, humidity, VPD, tank level

### Hardware Switches (real or simulated):
- Water pump switch
- Main line valve (optional)
- Zone valve switches (1-6 zones)

---

## 8. Known Limitations

### Current Version (v2.3.1):
- ⚠️ **No unit tests for AppDaemon modules** - integration calculations tested only
- ⚠️ **No hardware abstraction layer** - tight coupling to switch entities
- ⚠️ **Limited error recovery** - system may need manual intervention if hardware fails
- ⚠️ **No backup/restore for runtime state** - phase data lost on restart
- ⚠️ **Dashboard disabled** - advanced analytics not available
- ⚠️ **Entity naming assumptions** - AppDaemon expects specific entity ID patterns

### Planned Fixes:
- Add comprehensive test suite
- Implement hardware abstraction
- Add state persistence beyond RestoreEntity
- Re-enable dashboard with lighter dependencies
- Add diagnostic/troubleshooting tools

---

## 9. Version Compatibility Matrix

| Component | Version | Required | Notes |
|-----------|---------|----------|-------|
| Home Assistant | 2024.3.0+ | ✅ Yes | Core platform |
| AppDaemon 4 | 4.0.0+ | ✅ Yes | Automation engine |
| Python | 3.11+ | ✅ Yes | HA/AppDaemon requirement |
| scipy | Latest | ✅ Yes (AppDaemon) | Dryback detection |
| numpy | Latest | ✅ Yes (AppDaemon) | ML predictor |
| plotly | Latest | ❌ No | Dashboard only (disabled) |
| pandas | Latest | ❌ No | Dashboard only (disabled) |

---

## 10. Troubleshooting Checklist

Before reporting issues, verify:

- [ ] AppDaemon add-on is installed and running
- [ ] scipy and numpy are installed in AppDaemon
- [ ] AppDaemon apps directory contains crop_steering modules
- [ ] apps.yaml enables master_crop_steering app
- [ ] All mapped entity IDs exist in Home Assistant
- [ ] Test helpers created successfully (check for input_boolean/input_number entities)
- [ ] Integration shows in Settings → Devices & Services
- [ ] AppDaemon logs show no import errors
- [ ] Events are firing (check Developer Tools → Events)

### Common Errors:

**"Module scipy not found"**
```bash
docker exec addon_a0d7b954_appdaemon pip install scipy
```

**"Entity not found" in logs**
- Check entity ID spelling
- Verify entity exists: Developer Tools → States
- Recreate integration if mapping incorrect

**"No irrigation happening"**
- Check AppDaemon is running: Settings → Add-ons → AppDaemon
- Review AppDaemon logs: `docker logs addon_a0d7b954_appdaemon`
- Verify auto_irrigation_enabled switch is ON
- Check current phase (may be in P0 dryback waiting)

---

## Support

**Issues:** https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/issues
**Discussions:** https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/discussions
**Documentation:** See README.md and CLAUDE.md

**⚠️ IMPORTANT:** This is community software. Use at your own risk. Test thoroughly before production use.
