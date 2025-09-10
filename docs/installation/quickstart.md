# 15-Minute Quickstart Guide

**Get your Crop Steering System running fast** with this streamlined setup process. Perfect for first-time users who want to see results quickly.

> **Prerequisites**: Home Assistant running and accessible via web interface

## Step 1: Install the Integration (5 minutes)

### Option A: HACS Installation (Recommended)
1. **Open HACS** in your Home Assistant sidebar
2. **Go to Integrations** tab
3. **Click three dots (⋮)** → "Custom repositories"
4. **Add repository**:
   - URL: `https://github.com/JakeTheRabbit/HA-Irrigation-Strategy`
   - Category: `Integration`
5. **Click "ADD"**
6. **Search for "Crop Steering"** in HACS
7. **Download and install**
8. **Restart Home Assistant**

### Option B: Manual Installation
1. Download the [latest release](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/releases)
2. Copy `custom_components/crop_steering/` to your HA config directory
3. Restart Home Assistant

## Step 2: Add the Integration (5 minutes)

1. **Navigate to** Settings → Devices & Services
2. **Click "+ ADD INTEGRATION"** (bottom right)
3. **Search for "Crop Steering"** and select it
4. **Choose setup method**:
   - **"Advanced Setup"** if you have sensors and hardware
   - **"Basic Setup"** for testing or manual control only

## Step 3: Basic Configuration (5 minutes)

### If You Have Real Hardware:
1. **Set number of zones** (1-6)
2. **Map your entities**:
   - Pump switch: `switch.your_pump_entity`
   - Zone valves: `switch.zone_1_valve`, etc.
   - VWC sensors: `sensor.zone_1_vwc_front`, etc.
   - EC sensors: `sensor.zone_1_ec_front`, etc.

### For Testing Without Hardware:
The integration creates test helper entities automatically:
- `input_boolean.water_pump_1`
- `input_boolean.zone_1_valve`
- `input_number.zone_1_vwc_front`
- `input_number.zone_1_ec_front`

## Step 4: Verify Installation

### Check Your New Entities
1. **Go to** Developer Tools → States
2. **Filter by** `crop_steering`
3. **You should see**:
   - `sensor.crop_steering_current_phase`
   - `switch.crop_steering_system_enabled`
   - `sensor.crop_steering_configured_avg_vwc`
   - Many more entities based on your zone count

### Test Manual Control
1. **Try a test irrigation**:
   ```yaml
   # In Developer Tools > Services
   service: crop_steering.execute_irrigation_shot
   data:
     zone: 1
     duration_seconds: 30
   ```

2. **Watch your pump and valve entities** activate

## What You Have Now

✅ **Complete monitoring system** with 100+ entities  
✅ **Manual irrigation controls** with safety interlocks  
✅ **Shot duration calculations** based on your configuration  
✅ **Professional dashboard** ready for customization  

## Next Steps

### For Manual Operation
- **[Dashboard Guide](../user-guides/dashboard-guide.md)** - Set up monitoring cards
- **[Daily Operation](../user-guides/daily-operation.md)** - Learn the interface

### For Full Automation
- **[Complete Installation Guide](complete-guide.md)** - Add AppDaemon automation
- **[Hardware Setup Guide](hardware-setup.md)** - Connect real sensors and valves

### For Advanced Features
- **[LLM Integration](../advanced-features/llm-integration.md)** - Add AI decision assistance

## Troubleshooting Quick Fixes

**Integration not found?**
- Restart Home Assistant and wait 2-3 minutes
- Check Settings → System → Logs for errors

**Entities showing "Unknown"?**
- Verify your entity names in Developer Tools → States
- Check that sensors are providing numeric values

**Need help?**
- See our **[Troubleshooting Guide](../user-guides/troubleshooting.md)**
- Ask on **[GitHub Issues](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/issues)**

---

**🎉 Congratulations!** You now have a professional crop steering system. Take some time to explore the entities and try manual irrigation before moving to full automation.