## Title: Integrate zone configuration helper into Home Assistant GUI config flow ✅ COMPLETED

## Description

~~Currently, users need command line access to run configuration helper scripts like `zone_configuration_helper.py`. This is not user-friendly and goes against Home Assistant's philosophy of GUI-first configuration.~~

**UPDATE: This has been implemented!** Users can now configure everything through the Home Assistant GUI without needing command line access.

## Current Situation (RESOLVED)

~~Users must:~~
~~1. Have SSH or terminal access (many don't)~~
~~2. Navigate to /config directory~~
~~3. Run Python scripts from command line~~
~~4. Understand command line basics~~

~~This creates a barrier for non-technical users.~~

**Now users can:**
1. Add integration through Settings → Devices & Services
2. Select "Advanced Setup" for full configuration
3. Configure zones, sensors, and hardware through step-by-step GUI
4. No command line access needed!

## Proposed Solution

Integrate the zone configuration helper functionality directly into the config flow:

### Enhanced Config Flow Steps:

1. **Initial Choice:**
   - Quick Setup (basic switches only)
   - Advanced Setup (full sensor configuration)
   - Load from file

2. **Advanced Setup Flow:**
   ```
   Step 1: Number of Zones
   Step 2: Hardware Configuration
     - Pump switch
     - Main line valve
     - Zone valves (1-6)
   
   Step 3: Zone Sensors (for each zone)
     - VWC sensors (front/back)
     - EC sensors (front/back)
     - Optional: Temperature sensors
   
   Step 4: Environmental Sensors
     - Room temperature
     - Room humidity
     - VPD sensor (optional)
   
   Step 5: Validation & Summary
     - Show configured entities
     - Validate sensor availability
     - Allow editing before save
   ```

3. **Sensor Discovery:**
   - Auto-suggest sensors based on naming patterns
   - Filter by device/area if available
   - Show sensor preview values

### Implementation Details

```python
# config_flow.py additions
async def async_step_zone_sensors(self, user_input=None):
    """Configure sensors for each zone."""
    if user_input is not None:
        # Store zone sensor config
        self._zones[self._current_zone].update(user_input)
        
        if self._current_zone < self._num_zones:
            self._current_zone += 1
            return await self.async_step_zone_sensors()
        else:
            return await self.async_step_environmental()
    
    # Build schema for current zone
    return self.async_show_form(
        step_id="zone_sensors",
        data_schema=vol.Schema({
            vol.Optional(f"vwc_front", 
                description={"suggested_value": f"sensor.z{self._current_zone}_vwc_front"}
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="moisture")
            ),
            vol.Optional(f"vwc_back"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="moisture")
            ),
            vol.Optional(f"ec_front"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(f"ec_back"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
        }),
        description_placeholders={
            "zone_number": str(self._current_zone),
            "zone_total": str(self._num_zones),
        }
    )
```

### Benefits

1. **No terminal access required**
2. **Guided setup with validation**
3. **Entity selector with auto-complete**
4. **Preview sensor values during setup**
5. **Edit configuration through GUI**
6. **Better error messages**
7. **Accessibility for all users**

### Migration Path

1. Keep existing methods working
2. Add new GUI flow as preferred method
3. Deprecate command line tools over time
4. Auto-import existing env files

### UI Mockup

```
Configure Zone 1 Sensors (1 of 4)

Moisture Sensors (VWC):
  Front: [sensor.z1_vwc_front    ▼] (Current: 65.2%)
  Back:  [sensor.z1_vwc_back     ▼] (Current: 64.8%)

Nutrient Sensors (EC):
  Front: [sensor.z1_ec_front     ▼] (Current: 3.2 mS/cm)
  Back:  [sensor.z1_ec_back      ▼] (Current: 3.1 mS/cm)

[Back] [Skip Zone] [Next]
```

## Implementation Details

**Implemented in commit: f544238**

### What was added:
1. **Enhanced config_flow.py** with multi-step configuration:
   - `async_step_zone_sensors()` - Configure sensors for each zone
   - `async_step_environmental()` - Configure room sensors
   - Advanced setup mode as default option

2. **New strings.json** with proper UI translations

3. **Updated documentation** to reflect GUI-first approach

4. **Deprecated zone_configuration_helper.py** with warning message

### Key improvements:
- Entity validation during setup
- Auto-complete for sensor selection  
- Preview values shown during configuration
- Step-by-step guided process
- No command line required

## Status

✅ **COMPLETED** - Users can now configure the entire system through the GUI

## Priority

~~Medium~~ **COMPLETED** - This significantly improved user experience

## Labels
- enhancement ✅
- gui ✅
- user-experience ✅
- config-flow ✅
- completed