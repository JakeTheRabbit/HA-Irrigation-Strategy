# Advanced Crop Steering System for Home Assistant

![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.3.0+-41BDF5?logo=home-assistant&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![Zones](https://img.shields.io/badge/Zones-1%E2%80%936-blue)
![Status](https://img.shields.io/badge/Status-Production%20Ready-brightgreen)
![License](https://img.shields.io/badge/License-MIT-green)

**Transform your Home Assistant into a professional crop steering controller** with precision irrigation automation, real-time analytics, and optional AI-powered decision making.

> **Quick Start**: New to crop steering? Follow our [15-minute quickstart guide](docs/installation/quickstart.md) to get up and running today.

## 🌟 What This System Does

**Precision Irrigation Control**
- Automated 4-phase daily cycles (P0→P1→P2→P3) synchronized with your grow lights
- Smart VWC (moisture) and EC (nutrient) monitoring with multi-sensor averaging
- Dynamic shot sizing based on pot volume, flow rates, and growth stage requirements
- Safety-first hardware sequencing with comprehensive error handling

**Professional Analytics**  
- Real-time dashboard with 100+ monitoring entities
- Historical tracking of water usage, irrigation efficiency, and plant responses
- Sensor validation with statistical outlier detection
- Comprehensive logging and troubleshooting diagnostics

**Optional AI Enhancement**
- GPT-5 powered decision assistance for complex irrigation scenarios
- Stateless consultation system with rule-based safety fallbacks
- Budget-controlled API usage starting at $0.10-0.50/day
- Smart caching for 90% cost savings on routine decisions

## 🎯 Choose Your Experience Level

### 🌱 **New to Crop Steering?**
Start with our proven rule-based automation:
- **[15-Minute Quickstart](docs/installation/quickstart.md)** - Get running fast with basic setup
- **[Getting Started Guide](docs/user-guides/getting-started.md)** - Learn the fundamentals
- **[Hardware Setup](docs/installation/hardware-setup.md)** - Connect your sensors and valves

### 🔧 **Ready for Full Automation?**
Add professional-grade features:
- **[Complete Installation](docs/installation/complete-guide.md)** - Full system setup with AppDaemon
- **[Dashboard Guide](docs/user-guides/dashboard-guide.md)** - Master the monitoring interface
- **[Daily Operation](docs/user-guides/daily-operation.md)** - Day-to-day system management

### 🚀 **Want AI-Powered Intelligence?**
Enhance with cutting-edge features:
- **[LLM Integration](docs/advanced-features/llm-integration.md)** - Add GPT-5 decision assistance ($0.10-0.50/day)
- **[Smart Learning](docs/advanced-features/smart-learning.md)** - Adaptive system optimization
- **[Advanced Automation](docs/advanced-features/automation-advanced.md)** - Complex multi-zone coordination

## 🔍 How Crop Steering Works

**Crop steering** is a precision irrigation technique that controls plant growth by managing water stress through automated VWC (moisture) and EC (nutrient concentration) monitoring.

### The 4-Phase Daily Cycle

```
🌅 P0 (Dryback) → 🌱 P1 (Ramp-Up) → 💧 P2 (Maintenance) → 🌙 P3 (Pre-Lights-Off)
```

**P0 - Morning Dryback**: Allow substrate to dry 15-20% from peak to stimulate root growth  
**P1 - Ramp-Up**: Progressive irrigation shots (2%→10% volume) to reach target VWC  
**P2 - Maintenance**: Threshold-based irrigation maintains optimal moisture all day  
**P3 - Pre-Lights-Off**: Reduced irrigation 90 minutes before lights out  

### What You Provide
- **Sensors**: VWC and EC sensors for each growing zone
- **Hardware**: Water pump, main valve, zone valves (up to 6 zones)
- **Configuration**: Pot sizes, flow rates, growth targets via easy setup wizard

### What You Get
- **Automated irrigation** synchronized with your light cycle
- **Real-time monitoring** with professional dashboards
- **Smart hardware control** with safety interlocks and error recovery
- **Historical analytics** for continuous optimization

## 🏗️ System Architecture

### Two-Layer Design for Maximum Flexibility

**🏠 Home Assistant Integration** (Always Required)
- Creates 100+ entities for complete system monitoring and control
- Handles all calculations: shot durations, EC ratios, threshold adjustments
- Provides manual controls and safety overrides
- Works standalone for manual operation or with basic automations

**🤖 AppDaemon Automation** (Recommended)
- Autonomous 4-phase cycle management
- Advanced sensor validation and statistical analysis
- Professional hardware sequencing with safety interlocks
- Optional LLM integration for intelligent decision assistance

**🔧 Optional Enhancements**
- **LLM Integration**: GPT-5 powered decision assistance
- **Smart Learning**: Adaptive parameter optimization
- **Advanced Analytics**: Historical trend analysis and reporting

### Quick Setup Overview
1. **Install integration** via HACS (5 minutes)
2. **Configure zones** through Home Assistant UI (10 minutes) 
3. **Add automation** with AppDaemon for full autonomy (optional)
4. **Enable AI features** for intelligent optimization (optional)

> **Learn More**: See our [complete installation guide](docs/installation/complete-guide.md) for step-by-step instructions.

## 🤖 AI Integration (Optional)

**Add GPT-5 intelligence to your irrigation system** for advanced decision making while maintaining 100% safety through rule-based validation.

### How AI Enhancement Works
- **Stateless consultation**: AI analyzes current sensor snapshot and recommends actions
- **Rule-based validation**: Traditional logic validates all AI suggestions before execution  
- **Cost-effective**: Starting at $0.10-0.50/day with GPT-5-nano
- **Budget-controlled**: Automatic daily limits and emergency fallbacks

### Real Cost Examples
- **Basic Setup**: 480 decisions/day = $0.36/day with 90% caching
- **Advanced Setup**: Complex analysis + weekly reports = $1-3/day
- **Emergency Only**: AI for critical situations only = <$0.10/day

**Ready to add AI?** Follow our [LLM Integration Guide](docs/advanced-features/llm-integration.md) for setup and cost optimization.

> **Important**: The core system operates perfectly without AI. LLM integration is purely an enhancement for users wanting cutting-edge intelligence.

## 🛠️ Quick Installation

### Method 1: HACS (Recommended)
1. **Add to HACS**: `https://github.com/JakeTheRabbit/HA-Irrigation-Strategy`
2. **Download**: Search "Crop Steering" in HACS Integrations
3. **Install**: Restart Home Assistant
4. **Configure**: Settings → Integrations → Add "Crop Steering System"

### Method 2: Manual Install
Copy `custom_components/crop_steering/` to your HA config directory and restart.

### Next Steps
- **New users**: Start with [quickstart guide](docs/installation/quickstart.md)
- **Experienced users**: See [complete installation](docs/installation/complete-guide.md)
- **Hardware setup**: Review [hardware guide](docs/installation/hardware-setup.md)

## 📊 What You Get

**Immediate Benefits:**
- Professional crop steering dashboard with real-time monitoring
- Manual irrigation controls with safety interlocks
- Automated shot duration calculations based on your setup
- Comprehensive entity system (100+ sensors, controls, and settings)

**With AppDaemon Automation:**
- Fully autonomous 4-phase daily cycles
- Advanced sensor validation and error handling  
- Professional hardware sequencing with safety systems
- Historical analytics and performance optimization

**With AI Enhancement:**
- GPT-5 powered irrigation decision assistance
- Intelligent analysis of complex growing conditions
- Adaptive optimization suggestions
- Cost-controlled API usage with safety fallbacks

## 📚 Documentation

### 🚀 Installation & Setup
- **[15-Minute Quickstart](docs/installation/quickstart.md)** - Fastest path to working system
- **[Complete Installation Guide](docs/installation/complete-guide.md)** - Full setup with all features  
- **[Hardware Setup Guide](docs/installation/hardware-setup.md)** - Connect sensors and valves

### 📖 User Guides
- **[Getting Started](docs/user-guides/getting-started.md)** - First-time user walkthrough
- **[Daily Operation](docs/user-guides/daily-operation.md)** - Day-to-day usage and monitoring
- **[Dashboard Guide](docs/user-guides/dashboard-guide.md)** - Understanding the interface
- **[Troubleshooting](docs/user-guides/troubleshooting.md)** - Common issues and solutions

### 🤖 Advanced Features  
- **[LLM Integration](docs/advanced-features/llm-integration.md)** - Add GPT-5 intelligence
- **[Smart Learning System](docs/advanced-features/smart-learning.md)** - Adaptive optimization
- **[Advanced Automation](docs/advanced-features/automation-advanced.md)** - Complex scenarios

### 🔧 Technical Reference
- **[Entity Reference](docs/technical/entity-reference.md)** - Complete entity documentation
- **[Services & API](docs/technical/services-api.md)** - Service calls and events
- **[System Architecture](docs/technical/architecture.md)** - How everything works
- **[Configuration Reference](docs/technical/configuration.md)** - Advanced settings

### 💡 Examples
- **[Sample Configurations](docs/examples/configurations/)** - Real-world setups
- **[Automation Examples](docs/examples/automations/)** - Advanced automations

## 🏆 Key Features

**Professional Irrigation Control**
- Automated 4-phase daily cycles synchronized with grow lights
- Up to 6 independent zones with individual sensor monitoring
- Dynamic shot sizing based on pot volume and growth requirements
- Advanced EC ratio calculations for nutrient optimization

**Safety & Reliability**
- Comprehensive hardware sequencing with safety interlocks
- Multiple sensor validation and error recovery
- Emergency override capabilities and manual controls
- Extensive logging and diagnostic capabilities

**Flexible Architecture**
- Works with or without automation (manual control available)
- Integrates with existing Home Assistant setups
- Optional AI enhancement without compromising core functionality
- Professional dashboards and historical analytics

## ⚡ Quick Start Options

### 🌱 **Beginner Setup (15 minutes)**
1. Install via HACS or manual copy
2. Add integration through Home Assistant UI
3. Configure basic zones and hardware mapping
4. Start with manual control and monitoring

### 🔧 **Full Automation (30 minutes)**
1. Complete basic setup above
2. Install AppDaemon add-on
3. Copy automation files and configure
4. Enable autonomous 4-phase operation

### 🚀 **AI-Enhanced (45 minutes)**
1. Complete full automation setup
2. Get OpenAI API key
3. Configure LLM integration
4. Enable intelligent decision assistance

## 🛟 Support & Community

**Getting Help**
- **[Troubleshooting Guide](docs/user-guides/troubleshooting.md)** - Common issues and solutions
- **[GitHub Issues](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/issues)** - Bug reports and feature requests
- **Home Assistant Community** - Search for "Crop Steering" in the forums

**Contributing**
- **Documentation improvements** - Help make setup easier for everyone
- **Feature requests** - Suggest new capabilities or enhancements
- **Bug reports** - Help us maintain reliability and performance

## 📄 License & Acknowledgments

**MIT License** - Free for personal and commercial use

**Special Thanks**
- Home Assistant Community for integration framework
- AppDaemon developers for automation platform
- Crop steering pioneers for agricultural science foundation

---

**Ready to transform your growing setup?** Start with our **[15-minute quickstart guide](docs/installation/quickstart.md)** and join the precision agriculture revolution! 🌱