# Complete Installation Guide

**Transform your Home Assistant into a fully autonomous crop steering controller** with professional automation, advanced analytics, and optional AI enhancement.

> **Before Starting**: Complete the [15-minute quickstart](quickstart.md) first to ensure the basic integration is working.

## Part 1: Full Automation with AppDaemon

### Step 1: Install AppDaemon Add-on

1. **Navigate to** Settings → Add-ons → Add-on Store
2. **Search for "AppDaemon 4"**
3. **Install AppDaemon 4** (don't start yet)

### Step 2: Configure AppDaemon

1. **Get your access token**:
   - Go to your Home Assistant Profile (click your username)
   - Scroll to "Long-Lived Access Tokens"
   - Click "CREATE TOKEN"
   - Copy the token (you'll need it in the next step)

2. **Edit AppDaemon configuration**:
   - Go to Settings → Add-ons → AppDaemon 4 → Configuration
   - Replace the configuration with:
   ```yaml
   appdaemon:
     latitude: YOUR_LATITUDE
     longitude: YOUR_LONGITUDE  
     elevation: YOUR_ELEVATION
     time_zone: YOUR_TIMEZONE
     plugins:
       HASS:
         type: hass
         ha_url: http://YOUR_HA_IP:8123
         token: YOUR_LONG_LIVED_ACCESS_TOKEN
   ```

### Step 3: Download Automation Files

**Option A: GitHub Download**
1. Go to https://github.com/JakeTheRabbit/HA-Irrigation-Strategy
2. Click **"Code"** → **"Download ZIP"**
3. Extract and locate the `appdaemon/apps/` folder

**Option B: Git Clone**
```bash
git clone https://github.com/JakeTheRabbit/HA-Irrigation-Strategy.git
```

### Step 4: Copy Automation Files

1. **Access AppDaemon folder**:
   - Via File Manager: `/addon_configs/a0d7b954_appdaemon/apps/`
   - Via Samba: `\\\\YOUR_HA_IP\\addon_configs\\a0d7b954_appdaemon\\apps\\`

2. **Copy these files**:
   ```
   appdaemon/apps/apps.yaml → /addon_configs/a0d7b954_appdaemon/apps/
   appdaemon/apps/crop_steering/ → /addon_configs/a0d7b954_appdaemon/apps/crop_steering/
   ```

### Step 5: Start AppDaemon

1. **Go to** Settings → Add-ons → AppDaemon 4
2. **Click "START"**
3. **Wait 30 seconds**
4. **Check the log** for: "Master Crop Steering Application initialized"

## Part 2: Hardware Integration

### Sensor Setup

**VWC (Moisture) Sensors**
- Connect to your Home Assistant system
- Ensure they provide values in percentage (0-100%)
- Recommended: Front and back sensors per zone for averaging

**EC (Nutrient) Sensors**
- Connect to provide readings in mS/cm
- Recommended: Front and back sensors per zone for averaging
- Ensure stable readings and proper calibration

**Environmental Sensors (Optional)**
- Temperature sensor for system-wide monitoring
- Humidity sensor for environmental analytics
- VPD sensor if available

### Hardware Control

**Pump Control**
- Create a switch entity that controls your water pump
- Ensure pump can be turned on/off reliably
- Test manual control before automation

**Main Line Valve (Optional)**
- Controls main water distribution
- Recommended for systems with multiple zones
- Can be omitted for single-zone setups

**Zone Valves**
- Individual control for each growing zone
- Must be reliable on/off operation
- Test each valve manually before automation

### Configuration Mapping

1. **Reconfigure the integration**:
   - Settings → Devices & Services → Crop Steering System → Configure
   - Update entity mappings to match your hardware

2. **Set physical parameters**:
   - Pot volume in liters
   - Dripper flow rate in L/hr
   - Number of drippers per plant

3. **Configure light schedule**:
   - Set `lights_on_hour` (0-23)
   - Set `lights_off_hour` (0-23)

## Part 3: System Tuning

### Growth Parameters

**Vegetative Stage**
- Higher VWC targets (65-70%)
- Lower EC targets (1.5-2.0 mS/cm)
- More frequent irrigation

**Generative/Flowering Stage**
- Lower VWC targets (55-60%)
- Higher EC targets (2.5-3.5 mS/cm)
- Controlled stress for better production

### Phase Settings

**P0 (Morning Dryback)**
- `p0_dryback_drop_percent`: 15-20%
- `p0_min_wait_time`: 30 minutes
- `p0_max_wait_time`: 180 minutes

**P1 (Ramp-Up)**
- `p1_initial_shot_size`: 2%
- `p1_shot_increment`: 0.5%
- `p1_target_vwc`: 65% (veg) or 60% (gen)

**P2 (Maintenance)**
- `p2_vwc_threshold`: 60% (veg) or 55% (gen)
- `p2_shot_size`: 5%

**P3 (Pre-Lights-Off)**
- `p3_veg_last_irrigation`: 60 minutes
- `p3_gen_last_irrigation`: 90 minutes
- `p3_emergency_vwc_threshold`: 40%

## Part 4: Optional AI Enhancement

### Prerequisites
- Working AppDaemon automation (from Part 1)
- OpenAI API account and key

### Setup Steps

1. **Get OpenAI API Key**:
   - Go to https://platform.openai.com/api-keys
   - Create a new API key
   - Copy the key (starts with `sk-proj-`)

2. **Add to Home Assistant secrets**:
   ```yaml
   # In your secrets.yaml
   openai_api_key: "sk-proj-YOUR_KEY_HERE"
   ```

3. **Update AppDaemon configuration**:
   Edit `/addon_configs/a0d7b954_appdaemon/apps/apps.yaml`:
   ```yaml
   llm_crop_steering:
     module: llm_enhanced_app
     class: LLMEnhancedCropSteering
     llm_enabled: true
     llm_provider: "openai"
     model: "gpt-5-nano"
     daily_budget: 1.00
     confidence_threshold: 0.8
   ```

4. **Restart AppDaemon**

### Cost Management
- Start with $1/day budget
- Monitor usage for first week
- Adjust budget based on needs
- See [LLM Integration Guide](../advanced-features/llm-integration.md) for optimization

## Verification & Testing

### System Health Check

1. **Check integration status**:
   - Settings → Devices & Services → Crop Steering System
   - Should show "Connected" status

2. **Verify AppDaemon**:
   - Settings → Add-ons → AppDaemon 4 → Log
   - Look for successful initialization messages

3. **Test automation**:
   - Try manual phase transition
   - Test irrigation shot
   - Monitor for automatic phase changes

### Safety Testing

1. **Test emergency stop**:
   - Turn off `switch.crop_steering_system_enabled`
   - Verify all irrigation stops

2. **Test manual override**:
   - Enable zone manual override
   - Verify automation bypassed

3. **Test sensor failures**:
   - Disconnect a sensor temporarily
   - Verify system handles gracefully

## What You Have Now

✅ **Fully autonomous 4-phase operation**  
✅ **Advanced sensor validation and analytics**  
✅ **Professional hardware sequencing**  
✅ **Comprehensive safety systems**  
✅ **Historical tracking and optimization**  
✅ **Optional AI-powered decision assistance**  

## Next Steps

### Daily Operation
- **[Daily Operation Guide](../user-guides/daily-operation.md)** - Learn to monitor and maintain
- **[Dashboard Guide](../user-guides/dashboard-guide.md)** - Set up professional monitoring

### Advanced Features
- **[LLM Integration](../advanced-features/llm-integration.md)** - Optimize AI usage and costs
- **[Smart Learning](../advanced-features/smart-learning.md)** - Enable adaptive optimization
- **[Advanced Automation](../advanced-features/automation-advanced.md)** - Complex scenarios

### Fine-Tuning
- Monitor first few days closely
- Adjust parameters based on plant response
- Review historical data for optimization opportunities

## Troubleshooting

**AppDaemon won't start?**
- Check your token is valid
- Verify Home Assistant URL
- Ensure timezone matches HA

**No automatic irrigation?**
- Check current phase (may be in P0 waiting)
- Verify system and auto irrigation switches are ON
- Review thresholds vs current VWC

**AI features not working?**
- Verify OpenAI API key is correct
- Check daily budget hasn't been exceeded
- Review AppDaemon logs for errors

For detailed troubleshooting, see our **[Troubleshooting Guide](../user-guides/troubleshooting.md)**.

---

**🚀 Congratulations!** You now have a professional-grade autonomous crop steering system with cutting-edge features. Monitor the first few cycles closely and adjust parameters as needed for optimal results.