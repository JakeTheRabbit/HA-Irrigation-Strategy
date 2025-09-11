# Crop Steering for Home Assistant

Automated irrigation system that controls water and nutrient timing based on sensor readings. Monitors soil moisture (VWC) and nutrient concentration (EC) to decide when and how much to irrigate each zone.

## What is Crop Steering?

**The Problem**: Plants need different amounts of water at different times. Too much water = weak plants and nutrient runoff. Too little = stress and poor growth. Manual watering is inconsistent and time-consuming.

**The Solution**: Monitor soil moisture and nutrient levels continuously. Automatically irrigate when thresholds are reached. Adjust irrigation based on plant growth phase and environmental conditions.

**4-Phase Daily Cycle**:
- **P0 (Morning)**: Wait for soil to dry back to target moisture level
- **P1 (Ramp-up)**: Small frequent irrigations to reach ideal moisture
- **P2 (Maintenance)**: Maintain moisture at target level throughout day
- **P3 (Evening)**: Minimal irrigation before lights turn off

## Will This Work For Your Setup?

**You Need**:
- Home Assistant server running 2024.3.0+
- Soil moisture sensors (VWC) - one per zone minimum
- Nutrient sensors (EC) - one per zone minimum  
- Water pump and zone valves controlled by Home Assistant
- Pressure-compensating drippers (1-2 L/hr recommended)

**Works With**:
- Coco coir, rockwool, perlite, soil - any substrate
- 1-6 growing zones
- Any pump/valve hardware controllable by HA
- ESPHome sensors, commercial sensors, or manual test entities

**Won't Work If**:
- You can't measure soil moisture electronically
- Your irrigation system can't be controlled by Home Assistant
- You need more than 6 zones (current limit)

## What You Get

### Just Home Assistant Integration
Install the custom component:
- Dashboard showing all sensor readings and calculations
- Manual irrigation services you trigger yourself
- Safety checks (won't run multiple zones simultaneously)
- No automatic decisions - you control everything

### Add AppDaemon (Full Automation)  
Install Python automation scripts:
- Automatically transitions between P0→P1→P2→P3 phases
- Makes irrigation decisions based on sensor readings
- Handles pump priming, valve sequencing, timing delays
- Statistical analysis of sensor data for validation

### Add Learning System (Optional)
Uses your existing drippers to learn each zone:
- Detects true field capacity (when soil is saturated)
- Learns how efficiently each zone absorbs water
- Adapts irrigation timing to each zone's characteristics
- No additional hardware required

### Add AI Consultation (Optional)
Integrates with OpenAI for complex decisions:
- GPT-5 analyzes sensor data and recommends actions
- All AI suggestions validated by rule-based safety checks
- Costs ~$0.05-1.25/day depending on usage
- Completely optional - system works fine without it

## Quick Setup Check

**Can you answer yes to these?**
- ✅ I have Home Assistant running and can install custom components
- ✅ I can measure soil moisture and EC electronically in each zone
- ✅ I have a water pump and valves controllable by Home Assistant
- ✅ I want to automate irrigation timing decisions

**If yes**: [Installation Guide](docs/user-guides/02-installation.md)

**If no**: This system probably isn't right for your setup

## Example Hardware Setup

```
Zone 1: Coco + Perlite
├── VWC Sensor (front) → ESPHome → HA
├── VWC Sensor (back) → ESPHome → HA  
├── EC Sensor → ESPHome → HA
└── Zone Valve → Relay → ESPHome → HA

Water System:
├── Pump → Relay → ESPHome → HA
├── Main Line Valve → Relay → ESPHome → HA
└── Pressure-compensating drippers (1.2 L/hr)
```

## Documentation

**Start Here**: [Getting Started Guide](docs/user-guides/01-getting-started.md)
**Install**: [Installation Guide](docs/user-guides/02-installation.md)  
**Configure**: [Configuration Guide](docs/user-guides/03-configuration.md)
**Operate**: [Daily Operation Guide](docs/user-guides/04-daily-operation.md)
**Troubleshoot**: [Troubleshooting Guide](docs/user-guides/05-troubleshooting.md)

**Advanced Features**:
- [Smart Learning System](docs/advanced-features/smart-learning-system.md)
- [LLM Integration](docs/advanced-features/llm-integration.md)

**Technical Reference**:
- [System Architecture](docs/technical/architecture.md)
- [Entity Reference](docs/technical/entity-reference.md) 
- [Service Reference](docs/technical/service-reference.md)

## License

MIT License - use for hobby or commercial growing operations.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.