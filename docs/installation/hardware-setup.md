# Hardware Setup Guide

**Connect your physical sensors and valves** to create a fully functional precision irrigation system. This guide covers hardware requirements, wiring, and integration with Home Assistant.

## Hardware Requirements

### Essential Components

**Water System**
- Water pump (12V/24V DC or 240V AC with relay control)
- Main line solenoid valve (optional but recommended)
- Zone-specific solenoid valves (1-6 zones)
- Pressure-compensating drippers or micro-sprinklers
- Water reservoir/tank with level monitoring

**Sensors (Per Zone)**
- VWC (Volumetric Water Content) sensors
- EC (Electrical Conductivity) sensors
- Temperature sensors (optional)

**Control Hardware**
- Relay board or individual relays for pump/valve control
- Microcontroller (ESP32/ESP8266 recommended)
- Power supplies for sensors and control systems

### Recommended Sensor Types

**VWC Sensors**
- **Capacitive soil moisture sensors** (preferred)
  - More durable than resistive types
  - Better long-term accuracy
  - Examples: DFRobot SEN0193, Adafruit STEMMA

- **TDR (Time Domain Reflectometry) sensors** (professional grade)
  - Highest accuracy
  - Industrial reliability
  - Examples: Stevens HydraProbe, Campbell Scientific CS616

**EC Sensors**
- **Analog EC probes** with temperature compensation
  - Examples: DFRobot SEN0169, Atlas Scientific EC probe
  - Require calibration with standard solutions

- **All-in-one sensors** (EC + temperature)
  - Convenient single-probe solution
  - Built-in temperature compensation

## System Architecture

### Typical Setup Diagram

```
[Water Tank] → [Pump] → [Main Valve] → [Zone Valves] → [Drippers]
     ↓              ↓           ↓            ↓
[Level Sensor] [Pump Relay] [Main Relay] [Zone Relays]
     ↓              ↓           ↓            ↓
[ESP32/ESP8266] ← [Relay Board] ← [Home Assistant]
     ↓
[VWC/EC Sensors per Zone]
```

### Power Requirements

**12V DC System (Recommended)**
- Easy to work with and safe
- Common voltage for drip irrigation components
- Requires 12V power supply (minimum 5A)

**24V AC System (Professional)**
- Standard for commercial irrigation
- More robust for longer wire runs
- Requires 24VAC transformer

## Wiring Guide

### Sensor Connections

**VWC Sensors (Analog)**
```
Sensor Pin 1 (VCC) → ESP32 3.3V
Sensor Pin 2 (GND) → ESP32 GND  
Sensor Pin 3 (Analog) → ESP32 GPIO36 (ADC1_CH0)
```

**EC Sensors (Analog)**
```
Sensor Pin 1 (VCC) → ESP32 3.3V
Sensor Pin 2 (GND) → ESP32 GND
Sensor Pin 3 (Analog) → ESP32 GPIO39 (ADC1_CH3)
Sensor Pin 4 (Temp) → ESP32 GPIO34 (ADC1_CH6)
```

### Relay Control

**Pump Control**
```
ESP32 GPIO → Relay Input (3.3V logic)
Relay NO → Pump Power (+)
Relay COM → Power Supply (+)
Pump Power (-) → Power Supply (-)
```

**Valve Control (per zone)**
```
ESP32 GPIO → Relay Input
Relay NO → Valve (+)
Relay COM → Power Supply (+)
Valve (-) → Power Supply (-)
```

### Safety Considerations

⚠️ **Important Safety Notes**
- Always use appropriate relays rated for your pump/valve power
- Install fuses or circuit breakers for overcurrent protection
- Use weatherproof enclosures for outdoor installations
- Ground all metal components properly
- Keep low-voltage sensors separated from high-voltage pump circuits

## ESPHome Configuration

### Basic ESP32 Configuration

```yaml
# crop_steering.yaml
esphome:
  name: crop-steering-controller
  platform: ESP32
  board: esp32dev

wifi:
  ssid: "YourWiFiNetwork"
  password: "YourWiFiPassword"

api:
  password: "your_api_password"

ota:
  password: "your_ota_password"

logger:

# VWC Sensors
sensor:
  - platform: adc
    pin: GPIO36
    name: "Zone 1 VWC Front"
    id: zone1_vwc_front
    update_interval: 30s
    filters:
      - calibrate_linear:
          - 0.0 -> 0.0    # Dry reading
          - 3.3 -> 100.0  # Wet reading
    unit_of_measurement: "%"
    device_class: humidity

  - platform: adc
    pin: GPIO39
    name: "Zone 1 EC Front"
    id: zone1_ec_front
    update_interval: 30s
    filters:
      - calibrate_linear:
          - 0.0 -> 0.0    # Calibration point 1
          - 3.3 -> 5.0    # Calibration point 2
    unit_of_measurement: "mS/cm"

# Pump and Valve Controls
switch:
  - platform: gpio
    pin: GPIO2
    name: "Water Pump 1"
    id: water_pump_1

  - platform: gpio
    pin: GPIO4
    name: "Main Water Valve"
    id: main_water_valve

  - platform: gpio
    pin: GPIO5
    name: "Zone 1 Valve"
    id: zone_1_valve
```

### Advanced Multi-Zone Configuration

```yaml
# Add more sensors for additional zones
sensor:
  # Zone 1 Sensors
  - platform: adc
    pin: GPIO36
    name: "Zone 1 VWC Front"
    # ... configuration ...

  - platform: adc
    pin: GPIO37
    name: "Zone 1 VWC Back"
    # ... configuration ...

  # Zone 2 Sensors  
  - platform: adc
    pin: GPIO38
    name: "Zone 2 VWC Front"
    # ... configuration ...

# Add more valves for additional zones
switch:
  - platform: gpio
    pin: GPIO5
    name: "Zone 1 Valve"
    
  - platform: gpio
    pin: GPIO6
    name: "Zone 2 Valve"
```

## Sensor Calibration

### VWC Sensor Calibration

1. **Dry Calibration**:
   - Remove sensor from soil
   - Let dry completely
   - Record raw ADC value (should be near 0)

2. **Wet Calibration**:
   - Submerge sensor in water
   - Record raw ADC value (should be near maximum)

3. **Apply Calibration**:
   ```yaml
   filters:
     - calibrate_linear:
         - [dry_value] -> 0.0
         - [wet_value] -> 100.0
   ```

### EC Sensor Calibration

1. **Use Standard Solutions**:
   - Calibration solution 1: 1.413 mS/cm
   - Calibration solution 2: 12.88 mS/cm

2. **Two-Point Calibration**:
   ```yaml
   filters:
     - calibrate_linear:
         - [low_reading] -> 1.413
         - [high_reading] -> 12.88
   ```

3. **Temperature Compensation**:
   - Use temperature sensor for automatic compensation
   - EC typically increases 2% per °C above 25°C

## Physical Installation

### Sensor Placement

**VWC Sensors**
- Install at root zone depth (typically 10-15cm)
- Place 5-10cm from plant stem
- Use front and back positions for averaging
- Ensure good soil contact

**EC Sensors**
- Install near VWC sensors for correlation
- Same depth as VWC sensors
- Keep probe clean and calibrated
- Replace sensing elements annually

### Dripper Layout

**Optimal Dripper Placement**
- 2-4 drippers per plant
- Evenly spaced around plant
- Flow rate: 1-4 L/hr per dripper
- Pressure compensating preferred

**Flow Rate Calculations**
```
Duration (seconds) = (Pot Volume × Shot %) ÷ (Flow Rate × Drippers) × 3600
```

Example:
- 10L pot, 5% shot, 2×2L/hr drippers
- Duration = (10 × 0.05) ÷ (2 × 2) × 3600 = 450 seconds

## Integration with Home Assistant

### Device Discovery

Once ESPHome device is running:
1. **Go to** Settings → Devices & Services
2. **ESPHome devices** should auto-discover
3. **Configure and adopt** the device
4. **All sensors and switches** become available as entities

### Entity Naming

**Sensor Entities**:
- `sensor.zone_1_vwc_front`
- `sensor.zone_1_vwc_back`
- `sensor.zone_1_ec_front`
- `sensor.zone_1_ec_back`

**Switch Entities**:
- `switch.water_pump_1`
- `switch.main_water_valve`
- `switch.zone_1_valve`

### Testing Hardware

**Test Individual Components**:
```yaml
# Test pump
service: switch.turn_on
target:
  entity_id: switch.water_pump_1

# Test valve
service: switch.turn_on
target:
  entity_id: switch.zone_1_valve
```

**Verify Sensor Readings**:
- Check sensors provide reasonable values
- VWC: 0-100%
- EC: 0-8 mS/cm typically
- Sensors update regularly (every 30-60 seconds)

## Troubleshooting Hardware Issues

### Sensor Problems

**VWC readings erratic**:
- Check sensor is properly inserted in soil
- Verify stable power supply
- Clean sensor contacts
- Recalibrate if necessary

**EC readings drift**:
- Clean probe electrodes
- Check temperature compensation
- Recalibrate with fresh standard solutions
- Replace probe if old

### Control Problems

**Pump won't start**:
- Check relay clicks when activated
- Verify pump power supply
- Test pump manually with direct power
- Check for binding or blockages

**Valves don't open**:
- Verify 12V/24V reaches valve solenoid
- Check for debris in valve mechanism
- Test valve coil resistance (should be 20-200 ohms)
- Replace valve if solenoid burned out

### Communication Issues

**ESPHome device offline**:
- Check WiFi signal strength
- Verify power supply stability
- Check for interference from other devices
- Restart device if necessary

## Maintenance Schedule

### Weekly
- Visual inspection of all connections
- Check for water leaks
- Verify sensor readings are reasonable

### Monthly
- Clean sensor probes
- Check valve operation
- Inspect dripper flow rates
- Test pump operation

### Quarterly
- Calibrate EC sensors
- Replace any failed components
- Check all wire connections
- Update ESPHome firmware if needed

---

**🔧 Hardware Setup Complete!** Once your sensors and controls are working reliably, proceed to the [Complete Installation Guide](complete-guide.md) to enable full automation features.