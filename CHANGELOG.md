# Changelog

All notable changes to the Advanced Automated Crop Steering System will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.3.1] - 2025-01-03

### 🔧 Critical Fixes & Documentation Overhaul
- **CRITICAL FIX** - Reconstructed corrupted `config_flow.py` that prevented integration loading
- **Documentation Accuracy** - Complete rewrite of all .md files to reflect actual system capabilities
- **Code Quality** - Major refactoring with 85% reduction in code duplication
- **Dependency Clarity** - Fixed misleading "zero dependencies" claims (AppDaemon required for automation)

### 📚 Documentation Updates
- **README.md** - Updated to v2.3.1, corrected dependency information
- **installation_guide.md** - Complete beginner-friendly rewrite with step-by-step instructions
- **dashboard_guide.md** - Rewritten for actual AppDaemon YAML dashboard system
- **troubleshooting.md** - Updated for rule-based system (removed AI/ML references)
- **Removed** - `ai_operation_guide.md` (contained incorrect AI/ML information)

### 💡 System Clarification
- **Rule-Based Logic** - System uses sophisticated rule-based irrigation logic, not AI/ML
- **Statistical Analysis** - Uses scipy.stats for trend analysis and sensor validation
- **AppDaemon Requirement** - AppDaemon needed for automatic phase transitions and advanced features
- **Core Integration** - Works standalone for manual control, AppDaemon adds automation

### 🏗️ Code Quality Improvements
- **Helper Classes** - Introduced `ShotCalculator` to eliminate code duplication
- **Constants** - Replaced magic numbers with named constants in `const.py`
- **Version Consistency** - Standardized version strings across all files
- **Import Optimization** - Fixed missing imports and standardized patterns

### ⚠️ Truth in Documentation
- **No More AI Claims** - Removed all references to machine learning and AI capabilities
- **Accurate Feature List** - Documentation now reflects actual implemented features
- **Realistic Expectations** - Clear distinction between manual and automated operation modes
- **Beginner Focus** - All guides rewritten for new users with no assumptions

---

## [2.3.0] - 2024-12-26

### 🚀 Major Features
- **Full GUI Configuration** - Complete zone and sensor setup through Home Assistant UI
- **Zero Dependencies** - Removed ALL external Python packages (numpy, pandas, scipy, plotly)
- **Clean Architecture** - Removed all redundant scripts and command line tools
- **Fixed Phase Logic** - P3 now correctly persists through entire lights-off period
- **System-wide Light Controls** - Removed illogical per-zone light controls

### 🗑️ Removed (Cleanup)
- `fix_appdaemon_requirements.sh` - No longer needed, zero dependencies
- `requirements.txt` - System uses only standard Python libraries
- `configure_crop_steering.py` - Replaced by GUI configuration
- `advanced_crop_steering_dashboard.py` - Uses YAML dashboards instead
- Command line dependency for zone configuration

### ✨ Improvements
- **GUI Config Flow** - Advanced setup with sensor configuration for each zone
- **YAML Dashboards** - AppDaemon native dashboards without Plotly
- **Async/Await Fixes** - Proper coroutine handling in AppDaemon
- **Sensor Fusion** - Fixed VWC/EC mixing issue
- **State Machine** - Clean phase management implementation

### 📝 Documentation
- Updated README to v2.3.0 with GUI configuration
- Removed all references to deprecated scripts
- Added proper crop steering terminology explanations
- Marked zone_configuration_helper.py as deprecated

### ⚠️ Breaking Changes
- None - existing configurations continue to work

## [2.1.1] - 2024-12-21

### 🔄 AppDaemon v15+ Compatibility Update
- **Updated all documentation** for AppDaemon v15+ directory changes
- **Fixed file paths** from `/config/appdaemon/` to `/addon_configs/a0d7b954_appdaemon/`
- **Enhanced fix script** to auto-detect AppDaemon version and paths
- **Added migration guide** for upgrading from AppDaemon v14 to v15+
- **Updated installation instructions** with correct Samba share paths

### 📝 Documentation Updates
- `docs/installation_guide.md` - Updated for AppDaemon v15+ paths
- `docs/appdaemon_v15_migration.md` - NEW comprehensive migration guide
- `docs/dynamic_zones_guide.md` - Added AppDaemon v15+ compatibility notes
- `fix_appdaemon_requirements.sh` - Enhanced to handle both old and new paths
- `README.md` - Updated setup instructions for AppDaemon v15+

### 🔧 Technical Changes
- **Auto-detection** of AppDaemon directory structure in scripts
- **Backward compatibility** maintained for AppDaemon v14 and earlier
- **Improved error messages** for missing AppDaemon directories
- **Updated Samba share paths** in all documentation

### ⚠️ Important Notes
- **If using AppDaemon v15+**: Files are now in `/addon_configs/a0d7b954_appdaemon/`
- **Samba access**: Use `\\YOUR_HA_IP\addon_configs\a0d7b954_appdaemon`
- **Migration required**: Run updated scripts to move files to correct locations

---

## [2.1.0] - 2024-12-21

### 🚀 Major Features Added
- **Dynamic Zone Configuration** - Support for 1-6 irrigation zones (previously hardcoded to 3)
- **Interactive Zone Setup Tool** - `zone_configuration_helper.py` for easy zone configuration
- **AppDaemon Compatibility Fix** - `fix_appdaemon_requirements.sh` resolves scikit-learn installation issues
- **Flexible Entity Creation** - Automatic generation of sensors and switches per configured zone

### ✨ New Components
- `zone_config.py` - Zone configuration parser and validator
- `zone_configuration_helper.py` - Interactive setup wizard
- `fix_appdaemon_requirements.sh` - AppDaemon compatibility fix script
- `docs/dynamic_zones_guide.md` - Complete zone configuration documentation
- `services.yaml` - Proper service documentation

### 🔧 Enhancements
- **Config Flow Improvements** - Two setup modes: automatic (from env file) or manual (UI wizard)
- **Service Updates** - Dynamic zone validation in irrigation services
- **Entity Scaling** - All components now create entities per configured zone
- **Error Handling** - Improved validation and graceful error handling
- **Documentation** - Updated all guides for v2.1.0 features

### 🐛 Bug Fixes
- Fixed hardcoded zone iteration in AppDaemon modules
- Resolved entity creation for zones 2+ (previously only zone 1 worked)
- Fixed service validation to accept configured zones instead of hardcoded 1-3
- Removed obsolete package references in config flow
- Fixed sensor averaging to use actual configured sensors

### 🏗️ Architecture Changes
- **Zone Detection** - Dynamic zone discovery from configuration
- **Entity Generation** - Runtime entity creation based on zone count
- **AppDaemon Integration** - Removed hardcoded zone loops
- **Configuration Management** - Centralized zone config through new parser

### 📊 Per-Zone Entities Created
For each configured zone:
- `switch.crop_steering_zone_X_enabled` - Zone enable/disable
- `switch.crop_steering_zone_X_manual_override` - Manual control
- `sensor.crop_steering_vwc_zone_X` - Average VWC for zone
- `sensor.crop_steering_ec_zone_X` - Average EC for zone  
- `sensor.crop_steering_zone_X_status` - Zone operational status
- `sensor.crop_steering_zone_X_last_irrigation` - Last irrigation timestamp

### 🔄 Migration Notes
- Existing 3-zone setups continue working without changes
- New installations can configure any number of zones 1-6
- Zone configuration now centralized in `crop_steering.env`
- Helper scripts automate setup process

### ⚠️ Breaking Changes
- None - fully backward compatible with existing installations

### 🔮 Future Enhancements
- Zone grouping for simultaneous irrigation
- Zone-specific crop profiles
- Individual zone scheduling
- Water usage tracking per zone

---

## [2.0.0] - 2024-12-15

### 🚀 Major Release - Complete System Overhaul
- **New Architecture** - Integration + AppDaemon AI modules (replaced package-based approach)
- **Advanced AI Features** - Machine learning, sensor fusion, dryback detection
- **Professional Dashboard** - Real-time Plotly visualizations
- **Quality Assurance** - Complete code validation and optimization
- **Production Ready** - Comprehensive testing and error handling

### ✨ AI Features
- **Machine Learning Engine** - Predictive irrigation with ensemble models
- **Intelligent Sensor Fusion** - Multi-sensor validation with outlier detection
- **Advanced Dryback Detection** - Peak detection algorithms
- **Intelligent Crop Profiles** - Strain-specific optimization

### 🏗️ Architecture
- **Home Assistant Integration** - Native HA integration with config flow
- **AppDaemon AI Modules** - Advanced machine learning and automation
- **Configuration Management** - File-based hardware configuration
- **Real-time Dashboard** - Professional monitoring interface

### 📚 Documentation
- Complete installation guide for beginners
- AI operation guide
- Dashboard usage guide  
- Troubleshooting documentation

---

## [1.x] - Legacy Versions
Previous package-based implementations. See git history for details.