"""
Master Crop Steering Application with Advanced AI Features
Coordinates all advanced modules: dryback detection, sensor fusion, ML prediction, crop profiles, and dashboard
"""

import appdaemon.plugins.hass.hassapi as hass
import json
import logging
import asyncio
import threading
import os
import pickle
from datetime import datetime, timedelta, time
from typing import Dict, List, Optional, Any
import numpy as np

# Import our advanced modules with fallback
try:
    from .advanced_dryback_detection import AdvancedDrybackDetector
    from .intelligent_sensor_fusion import IntelligentSensorFusion
    from .ml_irrigation_predictor import SimplifiedIrrigationPredictor
    from .intelligent_crop_profiles import IntelligentCropProfiles
except ImportError:
    # Fallback for direct execution or import issues
    from advanced_dryback_detection import AdvancedDrybackDetector
    from intelligent_sensor_fusion import IntelligentSensorFusion
    from ml_irrigation_predictor import SimplifiedIrrigationPredictor
    from intelligent_crop_profiles import IntelligentCropProfiles

_LOGGER = logging.getLogger(__name__)


class MasterCropSteeringApp(hass.Hass):
    """
    Master application that coordinates all advanced crop steering modules.
    
    This is the main AI-powered crop steering system that brings together:
    - Multi-scale peak detection for dryback analysis
    - IQR-based sensor fusion with outlier detection  
    - Machine learning irrigation prediction and optimization
    - Strain-specific crop profiles with adaptive learning
    - Real-time Athena-style dashboard with advanced graphs
    
    The system operates autonomously while providing detailed monitoring,
    predictions, and recommendations through the dashboard interface.
    """

    def initialize(self):
        """Initialize the master crop steering application."""
        
        # Load configuration
        self.config = self._load_configuration()
        
        # Initialize thread lock for thread safety
        self.lock = threading.RLock()
        
        # System state
        self.system_enabled = True
        self.irrigation_in_progress = False
        self.last_irrigation_time = None
        
        # Get number of zones from integration or config
        self.num_zones = self._get_number_of_zones()
        
        # Per-zone phase tracking
        self.zone_phases = {}  # {zone_num: phase}
        self.zone_phase_data = {}  # {zone_num: {'p0_start_time': ..., 'p0_peak_vwc': ...}}
        
        # Initialize per-zone tracking
        self.zone_water_usage = {}  # Track water usage per zone
        self.zone_profiles = {}     # Zone-specific crop profiles
        self.zone_schedules = {}    # Zone-specific light schedules
        
        for zone_num in range(1, self.num_zones + 1):
            self.zone_phases[zone_num] = 'P2'  # Default to maintenance phase
            self.zone_phase_data[zone_num] = {
                'p0_start_time': None,
                'p0_peak_vwc': None,
                'last_irrigation_time': None
            }
            # Initialize water tracking
            self.zone_water_usage[zone_num] = {
                'daily_total': 0.0,
                'weekly_total': 0.0,
                'daily_count': 0,
                'last_reset_daily': datetime.now().date(),
                'last_reset_weekly': datetime.now().date()
            }
        
        # Initialize all advanced modules
        self._initialize_advanced_modules()
        
        # Set up listeners and timers
        self._setup_listeners()
        self._setup_timers()
        
        # Initialize crop profile
        self._initialize_default_crop_profile()
        
        # Load persistent state from file
        self._load_persistent_state()
        
        # Create initial sensors for integration compatibility
        self.run_in(self._create_initial_sensors, 2)
        
        # Save state periodically
        self.run_every(self._save_persistent_state, 'now+60', 300)  # Every 5 minutes
        
        self.log("🚀 Master Crop Steering Application with Advanced AI Features initialized!")
        self.log(f"📊 Modules: Dryback Detection ✓, Sensor Fusion ✓, ML Prediction ✓, Crop Profiles ✓, Dashboard ✓")

    def _load_configuration(self) -> Dict:
        """Load system configuration from crop_steering.env file and defaults."""
        try:
            # Load from environment file
            env_config = self._load_env_file()
            
            # Build configuration with environment values or fallbacks
            config = {
                'hardware': {
                    'pump_master': env_config.get('PUMP_SWITCH', 'switch.crop_steering_pump'),
                    'main_line': env_config.get('MAIN_LINE_SWITCH', 'switch.crop_steering_main_line'),
                    'zone_valves': {}
                },
                'sensors': {
                    'vwc': [],
                    'ec': [],
                    'environmental': {
                        'temperature': env_config.get('TEMPERATURE_SENSOR', 'sensor.grow_room_temperature'),
                        'humidity': env_config.get('HUMIDITY_SENSOR', 'sensor.grow_room_humidity'),
                        'vpd': env_config.get('VPD_SENSOR', 'sensor.grow_room_vpd')
                    }
                },
                'timing': {
                    'phase_check_interval': int(env_config.get('PHASE_CHECK_INTERVAL', '30')),
                    'ml_prediction_interval': int(env_config.get('ML_PREDICTION_INTERVAL', '60')),
                    'sensor_health_interval': int(env_config.get('SENSOR_HEALTH_INTERVAL', '120')),
                    'dashboard_update_interval': int(env_config.get('DASHBOARD_UPDATE_INTERVAL', '30'))
                },
                'thresholds': {
                    'emergency_vwc': float(env_config.get('EMERGENCY_VWC_THRESHOLD', '40')),
                    'critical_ec': float(env_config.get('MAX_EC_THRESHOLD', '8.0')),
                    'max_irrigation_duration': int(env_config.get('MAX_IRRIGATION_DURATION', '300')),
                    'min_irrigation_interval': int(env_config.get('MIN_IRRIGATION_INTERVAL', '900'))
                },
                'notification_service': env_config.get('NOTIFICATION_SERVICE', 'notify.persistent_notification')
            }
            
            # Load zone configurations dynamically from new format
            for key, value in env_config.items():
                # Zone switches (ZONE_1_SWITCH, ZONE_2_SWITCH, etc.)
                if key.startswith('ZONE_') and key.endswith('_SWITCH') and value:
                    zone_num = key.split('_')[1]
                    if zone_num.isdigit():
                        config['hardware']['zone_valves'][int(zone_num)] = value
                
                # VWC sensors (ZONE_1_VWC_FRONT, ZONE_1_VWC_BACK, etc.)
                elif key.startswith('ZONE_') and '_VWC_' in key and value:
                    config['sensors']['vwc'].append(value)
                
                # EC sensors (ZONE_1_EC_FRONT, ZONE_1_EC_BACK, etc.)
                elif key.startswith('ZONE_') and '_EC_' in key and value:
                    config['sensors']['ec'].append(value)
            
            # Sort sensor lists for consistency
            config['sensors']['vwc'].sort()
            config['sensors']['ec'].sort()
            
            self.log(f"Configuration loaded: {len(config['sensors']['vwc'])} VWC sensors, "
                    f"{len(config['sensors']['ec'])} EC sensors, "
                    f"{len(config['hardware']['zone_valves'])} zones")
            self.log(f"🔍 DEBUG VWC Sensors: {config['sensors']['vwc']}")
            self.log(f"🔍 DEBUG EC Sensors: {config['sensors']['ec']}")
            self.log(f"🔍 DEBUG Zone Valves: {config['hardware']['zone_valves']}")
            
            # Test reading one sensor directly for debugging
            if config['sensors']['vwc']:
                test_sensor = config['sensors']['vwc'][0]
                test_value = self.get_state(test_sensor)
                self.log(f"🔍 DEBUG Test read {test_sensor}: {test_value}")
            
            return config
            
        except Exception as e:
            self.log(f"Error loading configuration: {e}", level="ERROR")
            return self._get_fallback_configuration()

    def _load_env_file(self) -> Dict[str, str]:
        """
        Load environment variables from crop_steering.env file.
        
        Searches multiple possible locations for the configuration file:
        1. /config/crop_steering.env (default HA config path)
        2. /homeassistant/crop_steering.env (alternative HA path)
        3. /usr/share/hassio/homeassistant/crop_steering.env (HASSIO path)
        4. ./crop_steering.env (current directory)
        
        Returns:
            Dict[str, str]: Configuration key-value pairs from env file
            
        Note:
            Skips comment lines (starting with #) and empty lines
            Strips quotes from values and handles KEY=value format
        """
        env_config = {}
        env_path = "/config/crop_steering.env"  # Default Home Assistant config path
        
        try:
            if not os.path.exists(env_path):
                # Try alternative paths
                alt_paths = [
                    "/homeassistant/crop_steering.env",
                    "/usr/share/hassio/homeassistant/crop_steering.env",
                    "./crop_steering.env"
                ]
                
                for alt_path in alt_paths:
                    if os.path.exists(alt_path):
                        env_path = alt_path
                        break
                else:
                    self.log("crop_steering.env not found, using defaults", level="WARNING")
                    return env_config
            
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip().strip('"\'')
                        if value:
                            env_config[key] = value
            
            self.log(f"Loaded {len(env_config)} configuration values from {env_path}")
            
        except Exception as e:
            self.log(f"Error reading environment file: {e}", level="ERROR")
        
        return env_config

    def _get_fallback_configuration(self) -> Dict:
        """
        Get fallback configuration when env file loading fails.
        
        Provides minimal working configuration with generic entity names
        that allow the system to start even without proper configuration.
        
        Returns:
            Dict: Minimal configuration with generic entity names
            
        Warning:
            This configuration uses placeholder entities that likely don't exist.
            Users should configure crop_steering.env for proper operation.
        """
        self.log("Using fallback configuration", level="WARNING")
        return {
            'hardware': {
                'pump_master': 'switch.crop_steering_pump',
                'main_line': 'switch.crop_steering_main_line',
                'zone_valves': {1: 'switch.crop_steering_zone_1'}
            },
            'sensors': {
                'vwc': ['sensor.crop_steering_vwc_1'],
                'ec': ['sensor.crop_steering_ec_1'],
                'environmental': {
                    'temperature': 'sensor.grow_room_temperature',
                    'humidity': 'sensor.grow_room_humidity',
                    'vpd': 'sensor.grow_room_vpd'
                }
            },
            'timing': {
                'phase_check_interval': 30,
                'ml_prediction_interval': 60,
                'sensor_health_interval': 120,
                'dashboard_update_interval': 30
            },
            'thresholds': {
                'emergency_vwc': 40,
                'critical_ec': 8.0,
                'max_irrigation_duration': 300,
                'min_irrigation_interval': 900
            }
        }

    def _initialize_advanced_modules(self):
        """Initialize all advanced AI modules."""
        
        # 1. Advanced Dryback Detection
        self.dryback_detector = AdvancedDrybackDetector(
            window_size=200,
            min_peak_distance=10,
            noise_threshold=0.5,
            confidence_threshold=0.7
        )
        
        # 2. Intelligent Sensor Fusion
        self.sensor_fusion = IntelligentSensorFusion(
            outlier_multiplier=1.5,
            min_sensors_required=2,
            history_window=500,
            confidence_threshold=0.6
        )
        
        # 3. ML Irrigation Predictor
        self.ml_predictor = SimplifiedIrrigationPredictor(
            history_window=1000,
            prediction_horizon=120,  # 2 hours
            update_frequency=50,
            min_training_samples=50
        )
        
        # 4. Intelligent Crop Profiles
        self.crop_profiles = IntelligentCropProfiles()
        
        # 5. Advanced Dashboard (will be initialized separately as AppDaemon app)
        # Note: Dashboard runs as separate AppDaemon app for modularity
        
        self.log("🧠 Advanced AI modules initialized successfully")

    def _setup_listeners(self):
        """Set up Home Assistant entity listeners."""
        
        # Listen to all VWC sensors
        for sensor in self.config['sensors']['vwc']:
            self.listen_state(self._on_vwc_sensor_update, sensor)
        
        # Listen to all EC sensors
        for sensor in self.config['sensors']['ec']:
            self.listen_state(self._on_ec_sensor_update, sensor)
        
        # Listen to environmental sensors
        for sensor in self.config['sensors']['environmental'].values():
            self.listen_state(self._on_environmental_update, sensor)
        
        # Listen to system control entities
        self.listen_state(self._on_system_toggle, 'switch.crop_steering_system_enabled')
        self.listen_state(self._on_phase_change, 'select.crop_steering_irrigation_phase')
        self.listen_state(self._on_crop_profile_change, 'select.crop_steering_crop_type')
        
        # Listen to manual irrigation triggers
        self.listen_event(self._on_manual_irrigation, 'crop_steering_manual_irrigation')

    def _setup_timers(self):
        """Set up periodic processing timers."""
        
        # Main irrigation decision loop
        self.run_every(
            self._irrigation_decision_loop, 
            'now', 
            self.config['timing']['phase_check_interval']
        )
        
        # ML prediction updates
        self.run_every(
            self._update_ml_predictions,
            'now+10',
            self.config['timing']['ml_prediction_interval']
        )
        
        # Sensor health monitoring
        self.run_every(
            self._monitor_sensor_health,
            'now+15',
            self.config['timing']['sensor_health_interval']
        )
        
        # Performance analytics
        self.run_every(
            self._update_performance_analytics,
            'now+20',
            300  # Every 5 minutes
        )
        
        # Automatic phase transition checking
        self.run_every(
            self._check_phase_transitions,
            'now+30',
            300  # Check every 5 minutes for phase transitions
        )

    def _initialize_default_crop_profile(self):
        """Initialize with default crop profile."""
        try:
            # Try to get current crop from HA, default to Cannabis_Athena
            current_crop = self.get_state('select.crop_steering_crop_type', default='Cannabis_Athena')
            current_stage = self.get_state('select.crop_steering_growth_stage', default='vegetative')
            
            profile_result = self.crop_profiles.select_profile(current_crop, current_stage)
            
            if profile_result['status'] == 'success':
                self.log(f"✅ Initialized crop profile: {current_crop} ({current_stage})")
            else:
                self.log(f"⚠️ Failed to initialize crop profile: {profile_result.get('message', 'Unknown error')}")
                
        except Exception as e:
            self.log(f"❌ Error initializing crop profile: {e}", level='ERROR')

    def _get_phase_icon(self, phase: str) -> str:
        """Get icon for irrigation phase."""
        phase_icons = {
            'P0': 'mdi:weather-night',
            'P1': 'mdi:arrow-up-thick',
            'P2': 'mdi:water-check',
            'P3': 'mdi:weather-sunset-down'
        }
        return phase_icons.get(phase, 'mdi:water')
    
    def _get_zone_group(self, zone_num: int) -> str:
        """Get the group assignment for a zone."""
        try:
            group_entity = f"select.crop_steering_zone_{zone_num}_group"
            state = self.get_state(group_entity)
            return state if state and state != 'unknown' else 'Ungrouped'
        except Exception:
            return 'Ungrouped'
    
    def _get_zone_priority(self, zone_num: int) -> str:
        """Get the priority level for a zone."""
        try:
            priority_entity = f"select.crop_steering_zone_{zone_num}_priority"
            state = self.get_state(priority_entity)
            return state if state and state != 'unknown' else 'Normal'
        except Exception:
            return 'Normal'
    
    def _get_zone_profile(self, zone_num: int) -> str:
        """Get the crop profile for a zone."""
        try:
            profile_entity = f"select.crop_steering_zone_{zone_num}_crop_profile"
            state = self.get_state(profile_entity)
            if state and state != 'unknown' and state != 'Follow Main':
                return state
            # Fall back to main profile
            return self.get_state('select.crop_steering_crop_type', default='Cannabis_Athena')
        except Exception:
            return 'Cannabis_Athena'
    
    def _get_zone_schedule(self, zone_num: int) -> Dict[str, time]:
        """Get the light schedule for a zone."""
        try:
            schedule_entity = f"select.crop_steering_zone_{zone_num}_schedule"
            schedule = self.get_state(schedule_entity, default='Main Schedule')
            
            if schedule == 'Main Schedule' or schedule == 'unknown':
                # Use default 12pm-12am
                return {'lights_on': time(12, 0), 'lights_off': time(0, 0)}
            elif schedule == '12/12 Flowering':
                return {'lights_on': time(6, 0), 'lights_off': time(18, 0)}
            elif schedule == '18/6 Vegetative':
                return {'lights_on': time(6, 0), 'lights_off': time(0, 0)}
            elif schedule == '20/4 Auto':
                return {'lights_on': time(2, 0), 'lights_off': time(22, 0)}
            elif schedule == '24/0 Continuous':
                return {'lights_on': time(0, 0), 'lights_off': time(23, 59)}
            else:  # Custom
                # Get custom hours from number entities
                on_hour = int(self._get_number_entity_value(f"number.crop_steering_zone_{zone_num}_lights_on_hour", 12))
                off_hour = int(self._get_number_entity_value(f"number.crop_steering_zone_{zone_num}_lights_off_hour", 0))
                return {'lights_on': time(on_hour, 0), 'lights_off': time(off_hour, 0)}
        except Exception as e:
            self.log(f"❌ Error getting zone {zone_num} schedule: {e}", level='ERROR')
            return {'lights_on': time(12, 0), 'lights_off': time(0, 0)}

    async def _create_initial_sensors(self, kwargs):
        """Create initial sensors for HA integration compatibility."""
        try:
            # Create zone phase summary
            phase_summary = ", ".join([f"Z{z}:{p}" for z, p in self.zone_phases.items()])
            await self.set_state('sensor.crop_steering_app_current_phase',
                               state=phase_summary,
                               attributes={
                                   'friendly_name': 'Zone Phases',
                                   'icon': 'mdi:water-circle',
                                   'zone_phases': self.zone_phases.copy(),
                                   'updated': datetime.now().isoformat()
                               })
            
            # Create next irrigation time sensor
            next_irrigation = self._calculate_next_irrigation_time()
            if next_irrigation:
                await self.set_state('sensor.crop_steering_app_next_irrigation',
                                   state=next_irrigation.isoformat(),
                                   attributes={
                                       'friendly_name': 'Next Irrigation Time',
                                       'icon': 'mdi:clock-outline',
                                       'device_class': 'timestamp',
                                       'updated': datetime.now().isoformat()
                                   })
            else:
                await self.set_state('sensor.crop_steering_app_next_irrigation',
                                   state='unknown',
                                   attributes={
                                       'friendly_name': 'Next Irrigation Time',
                                       'icon': 'mdi:clock-outline',
                                       'device_class': 'timestamp',
                                       'reason': 'Calculating...',
                                       'updated': datetime.now().isoformat()
                                   })
            
            # Create individual zone phase sensors
            for zone_num in range(1, self.num_zones + 1):
                phase = self.zone_phases.get(zone_num, 'P2')
                await self.set_state(f'sensor.crop_steering_zone_{zone_num}_phase',
                                   state=phase,
                                   attributes={
                                       'friendly_name': f'Zone {zone_num} Phase',
                                       'icon': self._get_phase_icon(phase),
                                       'updated': datetime.now().isoformat()
                                   })
            
            # Create water usage sensors
            for zone_num in range(1, self.num_zones + 1):
                await self._update_zone_water_sensors(zone_num)
            
            self.log("✅ Initial sensors created for HA integration")
            
        except Exception as e:
            self.log(f"❌ Error creating initial sensors: {e}", level='ERROR')

    async def _update_zone_water_usage(self, zone_num: int, duration_seconds: float):
        """Update water usage tracking for a zone."""
        try:
            # Calculate water volume used
            dripper_flow = self._get_number_entity_value("number.crop_steering_dripper_flow_rate", 2.0)  # L/hour
            drippers_per_zone = self._get_number_entity_value("number.crop_steering_drippers_per_zone", 4)
            shot_multiplier = self._get_number_entity_value(f"number.crop_steering_zone_{zone_num}_shot_size_multiplier", 1.0)
            
            # Calculate volume: (flow rate * drippers * hours * multiplier)
            hours = duration_seconds / 3600
            volume_liters = dripper_flow * drippers_per_zone * hours * shot_multiplier
            
            # Update tracking data
            today = datetime.now().date()
            zone_data = self.zone_water_usage.get(zone_num, {})
            
            # Reset daily counter if new day
            if zone_data.get('last_reset_daily') != today:
                zone_data['daily_total'] = 0
                zone_data['daily_count'] = 0
                zone_data['last_reset_daily'] = today
            
            # Reset weekly counter if new week (Monday)
            if today.weekday() == 0 and zone_data.get('last_reset_weekly') != today:
                zone_data['weekly_total'] = 0
                zone_data['last_reset_weekly'] = today
            
            # Update totals
            zone_data['daily_total'] += volume_liters
            zone_data['weekly_total'] += volume_liters
            zone_data['daily_count'] += 1
            
            self.zone_water_usage[zone_num] = zone_data
            
            # Update sensors
            await self._update_zone_water_sensors(zone_num)
            
            # Check daily limit
            max_daily = self._get_number_entity_value(f"number.crop_steering_zone_{zone_num}_max_daily_volume", 20.0)
            if zone_data['daily_total'] >= max_daily:
                self.log(f"⚠️ Zone {zone_num} daily water limit reached: {zone_data['daily_total']:.1f}L >= {max_daily}L", 
                        level='WARNING')
            
        except Exception as e:
            self.log(f"❌ Error updating zone {zone_num} water usage: {e}", level='ERROR')
    
    async def _update_zone_water_sensors(self, zone_num: int):
        """Update water usage sensors for a zone."""
        try:
            zone_data = self.zone_water_usage.get(zone_num, {})
            
            # Daily water usage
            await self.set_state(f'sensor.crop_steering_zone_{zone_num}_daily_water_app',
                               state=round(zone_data.get('daily_total', 0), 2),
                               attributes={
                                   'friendly_name': f'Zone {zone_num} Daily Water',
                                   'unit_of_measurement': 'L',
                                   'icon': 'mdi:water',
                                   'device_class': 'volume',
                                   'state_class': 'total_increasing',
                                   'last_reset': str(zone_data.get('last_reset_daily', datetime.now().date()))
                               })
            
            # Weekly water usage
            await self.set_state(f'sensor.crop_steering_zone_{zone_num}_weekly_water_app',
                               state=round(zone_data.get('weekly_total', 0), 2),
                               attributes={
                                   'friendly_name': f'Zone {zone_num} Weekly Water',
                                   'unit_of_measurement': 'L',
                                   'icon': 'mdi:water-outline',
                                   'device_class': 'volume',
                                   'state_class': 'total_increasing',
                                   'last_reset': str(zone_data.get('last_reset_weekly', datetime.now().date()))
                               })
            
            # Irrigation count today
            await self.set_state(f'sensor.crop_steering_zone_{zone_num}_irrigation_count_app',
                               state=zone_data.get('daily_count', 0),
                               attributes={
                                   'friendly_name': f'Zone {zone_num} Irrigations Today',
                                   'icon': 'mdi:counter',
                                   'state_class': 'total_increasing',
                                   'last_reset': str(zone_data.get('last_reset_daily', datetime.now().date()))
                               })
            
            # Last irrigation time
            last_irrigation = self.zone_phase_data.get(zone_num, {}).get('last_irrigation_time')
            if last_irrigation:
                await self.set_state(f'sensor.crop_steering_zone_{zone_num}_last_irrigation_app',
                                   state=last_irrigation.isoformat(),
                                   attributes={
                                       'friendly_name': f'Zone {zone_num} Last Irrigation',
                                       'device_class': 'timestamp',
                                       'icon': 'mdi:history'
                                   })
            
        except Exception as e:
            self.log(f"❌ Error updating zone {zone_num} water sensors: {e}", level='ERROR')

    def _get_state_file_path(self) -> str:
        """Get the path for persistent state file."""
        # Use AppDaemon's config directory
        config_dir = self.config.get('config_dir', '/config')
        return os.path.join(config_dir, 'crop_steering_state.pkl')

    def _save_persistent_state(self, kwargs=None):
        """Save critical system state to file for restart recovery."""
        try:
            state_data = {
                'timestamp': datetime.now().isoformat(),
                'zone_phases': self.zone_phases.copy(),
                'zone_phase_data': {},
                'zone_water_usage': {},
                'last_irrigation_time': self.last_irrigation_time.isoformat() if self.last_irrigation_time else None,
                'version': '2.1.0'
            }
            
            # Convert datetime objects to ISO strings for JSON serialization
            for zone_num, data in self.zone_phase_data.items():
                state_data['zone_phase_data'][zone_num] = {
                    'p0_start_time': data['p0_start_time'].isoformat() if data['p0_start_time'] else None,
                    'p0_peak_vwc': data['p0_peak_vwc'],
                    'last_irrigation_time': data['last_irrigation_time'].isoformat() if data['last_irrigation_time'] else None
                }
            
            # Convert date objects for water usage
            for zone_num, data in self.zone_water_usage.items():
                state_data['zone_water_usage'][zone_num] = {
                    'daily_total': data['daily_total'],
                    'weekly_total': data['weekly_total'],
                    'daily_count': data['daily_count'],
                    'last_reset_daily': data['last_reset_daily'].isoformat() if data['last_reset_daily'] else None,
                    'last_reset_weekly': data['last_reset_weekly'].isoformat() if data['last_reset_weekly'] else None
                }
            
            # Save to file
            state_file = self._get_state_file_path()
            with open(state_file, 'w') as f:
                json.dump(state_data, f, indent=2)
            
            self.log(f"💾 State saved to {state_file}")
            
        except Exception as e:
            self.log(f"❌ Error saving persistent state: {e}", level='ERROR')

    def _load_persistent_state(self):
        """Load system state from file after restart."""
        try:
            state_file = self._get_state_file_path()
            
            if not os.path.exists(state_file):
                self.log("📂 No existing state file found - using defaults")
                return
            
            with open(state_file, 'r') as f:
                state_data = json.load(f)
            
            # Check version compatibility
            saved_version = state_data.get('version', '1.0.0')
            self.log(f"📂 Loading state from version {saved_version}")
            
            # Restore zone phases
            if 'zone_phases' in state_data:
                self.zone_phases.update(state_data['zone_phases'])
                self.log(f"✅ Restored zone phases: {self.zone_phases}")
            else:
                # Fallback: try to get phases from HA sensors
                self._restore_phases_from_ha()
            
            # Validate phase data consistency
            self._validate_restored_state()
            
            # Restore zone phase data
            if 'zone_phase_data' in state_data:
                for zone_str, data in state_data['zone_phase_data'].items():
                    zone_num = int(zone_str)
                    self.zone_phase_data[zone_num] = {
                        'p0_start_time': datetime.fromisoformat(data['p0_start_time']) if data['p0_start_time'] else None,
                        'p0_peak_vwc': data['p0_peak_vwc'],
                        'last_irrigation_time': datetime.fromisoformat(data['last_irrigation_time']) if data['last_irrigation_time'] else None
                    }
                self.log(f"✅ Restored zone phase data for {len(state_data['zone_phase_data'])} zones")
            
            # Restore water usage (check if data is from today/this week)
            if 'zone_water_usage' in state_data:
                today = datetime.now().date()
                for zone_str, data in state_data['zone_water_usage'].items():
                    zone_num = int(zone_str)
                    last_daily_reset = datetime.fromisoformat(data['last_reset_daily']).date() if data['last_reset_daily'] else today
                    last_weekly_reset = datetime.fromisoformat(data['last_reset_weekly']).date() if data['last_reset_weekly'] else today
                    
                    # Only restore if from same day/week
                    daily_total = data['daily_total'] if last_daily_reset == today else 0.0
                    daily_count = data['daily_count'] if last_daily_reset == today else 0
                    weekly_total = data['weekly_total'] if (today - last_weekly_reset).days < 7 else 0.0
                    
                    self.zone_water_usage[zone_num] = {
                        'daily_total': daily_total,
                        'weekly_total': weekly_total,
                        'daily_count': daily_count,
                        'last_reset_daily': today,
                        'last_reset_weekly': last_weekly_reset
                    }
                self.log(f"✅ Restored water usage for {len(state_data['zone_water_usage'])} zones")
            
            # Restore last irrigation time
            if state_data.get('last_irrigation_time'):
                self.last_irrigation_time = datetime.fromisoformat(state_data['last_irrigation_time'])
                self.log(f"✅ Restored last irrigation time: {self.last_irrigation_time}")
            
            # Calculate recovery time
            saved_time = datetime.fromisoformat(state_data['timestamp'])
            downtime = datetime.now() - saved_time
            self.log(f"🔄 System recovered after {downtime.total_seconds():.0f} seconds of downtime")
            
        except Exception as e:
            self.log(f"❌ Error loading persistent state: {e}", level='ERROR')
            self.log("⚠️ Using default state values")

    def _restore_phases_from_ha(self):
        """Fallback: Restore zone phases from HA sensors."""
        try:
            self.log("🔄 Attempting to restore phases from HA sensors...")
            for zone_num in range(1, self.num_zones + 1):
                sensor_id = f"sensor.crop_steering_zone_{zone_num}_phase"
                phase = self.get_state(sensor_id)
                if phase and phase in ['P0', 'P1', 'P2', 'P3']:
                    self.zone_phases[zone_num] = phase
                    self.log(f"✅ Zone {zone_num}: Restored phase {phase} from HA sensor")
        except Exception as e:
            self.log(f"❌ Error restoring from HA sensors: {e}", level='ERROR')

    def _validate_restored_state(self):
        """Validate that restored state makes sense."""
        try:
            now = datetime.now()
            current_time = now.time()
            
            # Check if any zones are in impossible states
            for zone_num in range(1, self.num_zones + 1):
                zone_schedule = self._get_zone_schedule(zone_num)
                lights_on = self._are_lights_on(current_time, zone_schedule['lights_on'], zone_schedule['lights_off'])
                zone_phase = self.zone_phases.get(zone_num, 'P2')
                
                # If lights are off but zone isn't in P0, fix it
                if not lights_on and zone_phase != 'P0':
                    self.log(f"🔧 Zone {zone_num}: Lights off but phase is {zone_phase}, correcting to P0")
                    self.zone_phases[zone_num] = 'P0'
                    # Record current VWC as peak for dryback calculations
                    zone_vwc = self._get_zone_vwc(zone_num)
                    if zone_vwc:
                        self.zone_phase_data[zone_num]['p0_start_time'] = now
                        self.zone_phase_data[zone_num]['p0_peak_vwc'] = zone_vwc
                
                # If lights are on but zone is in P0 and dryback is done, fix it
                elif lights_on and zone_phase == 'P0':
                    zone_data = self.zone_phase_data.get(zone_num, {})
                    if zone_data.get('p0_start_time'):
                        elapsed = (now - zone_data['p0_start_time']).total_seconds() / 60
                        if elapsed > 120:  # More than 2 hours in P0
                            self.log(f"🔧 Zone {zone_num}: Lights on and long P0 duration, moving to P1")
                            self.zone_phases[zone_num] = 'P1'
            
            self.log("✅ State validation complete")
            
        except Exception as e:
            self.log(f"❌ Error validating state: {e}", level='ERROR')

    async def _on_vwc_sensor_update(self, entity, attribute, old, new, kwargs):
        """Handle VWC sensor updates with advanced processing."""
        try:
            if new in ['unavailable', 'unknown', None]:
                return
            
            with self.lock:
                vwc_value = float(new)
                timestamp = datetime.now()
                
                # TEMPORARILY BYPASS sensor fusion - it's mixing VWC and EC values
                # Just use the direct sensor value
                fusion_result = {
                    'sensor_id': entity,
                    'value': vwc_value,
                    'is_outlier': False,
                    'sensor_reliability': 0.9,
                    'sensor_health': 'good',
                    'fused_value': vwc_value,  # Use direct value
                    'fusion_confidence': 0.9,
                    'active_sensors': 1,
                    'outlier_rate': 0.0
                }
                
                # Add to dryback detector (use direct value)
                dryback_result = self.dryback_detector.add_vwc_reading(
                    vwc_value, timestamp
                )
                
                # Update HA entities with dryback data
                self._update_dryback_entities(dryback_result)
                
                # Update fusion entities
                self._update_sensor_fusion_entities(entity, fusion_result)
                
                # Get current sensor data for emergency check
                sensor_data = self._get_current_sensor_data()
                if sensor_data:
                    # Use direct average instead of fusion result for now
                    direct_vwc = sensor_data['average_vwc']
                    self.log(f"🔍 DEBUG Emergency check: fusion={fusion_result['fused_value']:.1f}%, direct={direct_vwc:.1f}%")
                    await self._check_emergency_conditions(direct_vwc)
                else:
                    # Fallback to fusion result
                    await self._check_emergency_conditions(fusion_result['fused_value'])
                
                # Log significant changes
                if fusion_result['is_outlier']:
                    self.log(f"⚠️ VWC outlier detected: {entity} = {vwc_value}%")
                
        except Exception as e:
            self.log(f"❌ Error processing VWC update: {e}", level='ERROR')

    async def _on_ec_sensor_update(self, entity, attribute, old, new, kwargs):
        """Handle EC sensor updates with advanced processing."""
        try:
            if new in ['unavailable', 'unknown', None]:
                return
            
            with self.lock:
                ec_value = float(new)
                timestamp = datetime.now()
                
                # TEMPORARILY BYPASS sensor fusion - it's mixing VWC and EC values
                # Just use the direct sensor value
                fusion_result = {
                    'sensor_id': entity,
                    'value': ec_value,
                    'is_outlier': False,
                    'sensor_reliability': 0.9,
                    'sensor_health': 'good',
                    'fused_value': ec_value,  # Use direct value
                    'fusion_confidence': 0.9,
                    'active_sensors': 1,
                    'outlier_rate': 0.0
                }
                
                # Update fusion entities
                self._update_sensor_fusion_entities(entity, fusion_result)
                
                # Check for critical EC levels (using direct value)
                if ec_value > self.config['thresholds']['critical_ec']:
                    self.log(f"🚨 Critical EC level detected: {ec_value:.2f} mS/cm", level='WARNING')
                    await self._handle_critical_ec(ec_value)
                
                # Log outliers
                if fusion_result['is_outlier']:
                    self.log(f"⚠️ EC outlier detected: {entity} = {ec_value:.2f} mS/cm")
                
        except Exception as e:
            self.log(f"❌ Error processing EC update: {e}", level='ERROR')

    async def _on_environmental_update(self, entity, attribute, old, new, kwargs):
        """Handle environmental sensor updates."""
        try:
            if new in ['unavailable', 'unknown', None]:
                return
            
            # Update environmental tracking for ML features
            env_value = float(new)
            self.log(f"🌡️ Environmental update: {entity} = {env_value}", level='DEBUG')
            
        except Exception as e:
            self.log(f"❌ Error processing environmental update: {e}", level='ERROR')

    async def _on_system_toggle(self, entity, attribute, old, new, kwargs):
        """Handle system enable/disable."""
        try:
            self.system_enabled = new == 'on'
            status = "enabled" if self.system_enabled else "disabled"
            self.log(f"🔄 Crop steering system {status}")
            
            if not self.system_enabled:
                # Emergency stop all irrigation
                await self._emergency_stop()
                
        except Exception as e:
            self.log(f"❌ Error handling system toggle: {e}", level='ERROR')

    async def _on_phase_change(self, entity, attribute, old, new, kwargs):
        """Handle manual irrigation phase changes (legacy compatibility)."""
        try:
            # Manual phase change applies to all zones
            self.log(f"📊 Manual phase transition requested: {old} → {new}")
            
            # Apply to all zones
            for zone_num in range(1, self.num_zones + 1):
                await self._transition_zone_to_phase(zone_num, new, "Manual phase change")
            
        except Exception as e:
            self.log(f"❌ Error handling phase change: {e}", level='ERROR')

    async def _on_crop_profile_change(self, entity, attribute, old, new, kwargs):
        """Handle crop profile changes."""
        try:
            current_stage = self.get_state('select.crop_steering_growth_stage', default='vegetative')
            profile_result = self.crop_profiles.select_profile(new, current_stage)
            
            if profile_result['status'] == 'success':
                self.log(f"🌱 Crop profile changed: {old} → {new}")
                await self._update_system_for_new_profile()
            else:
                self.log(f"❌ Failed to change crop profile: {profile_result.get('message', 'Unknown error')}")
                
        except Exception as e:
            self.log(f"❌ Error handling crop profile change: {e}", level='ERROR')

    async def _on_manual_irrigation(self, event_name, data, kwargs):
        """Handle manual irrigation requests."""
        try:
            zone = data.get('zone', 1)
            duration = data.get('duration', 30)
            
            self.log(f"🔧 Manual irrigation requested: Zone {zone}, {duration}s")
            
            if self.system_enabled:
                await self._execute_irrigation_shot(zone, duration, shot_type='manual')
            else:
                self.log("⚠️ Manual irrigation blocked - system disabled")
                
        except Exception as e:
            self.log(f"❌ Error handling manual irrigation: {e}", level='ERROR')

    async def _irrigation_decision_loop(self, kwargs):
        """Main irrigation decision logic with AI integration."""
        try:
            if not self.system_enabled:
                return
            
            with self.lock:
                # Get current system state
                current_state = await self._get_current_system_state()
                
                if not current_state:
                    return
                
                # Get crop profile parameters
                profile_params = self.crop_profiles.get_current_parameters()
                if not profile_params:
                    self.log("⚠️ No active crop profile - using defaults", level='WARNING')
                    return
                
                # Check dryback status
                dryback_status = self._get_latest_dryback_status()
                
                # Get ML predictions
                ml_predictions = await self._get_ml_irrigation_predictions(current_state)
                
                # Make irrigation decision
                decision = await self._make_irrigation_decision(
                    current_state, profile_params, dryback_status, ml_predictions
                )
                
                # Execute decision
                if decision['action'] == 'irrigate':
                    await self._execute_intelligent_irrigation(decision)
                elif decision['action'] == 'wait':
                    self.log(f"⏳ Waiting: {decision.get('reason', 'Monitoring conditions')}")
                
                # Update performance tracking
                await self._update_decision_tracking(current_state, decision)
                
        except Exception as e:
            self.log(f"❌ Error in irrigation decision loop: {e}", level='ERROR')

    async def _get_current_system_state(self) -> Optional[Dict]:
        """Get comprehensive current system state."""
        try:
            # Get latest sensor fusion results
            vwc_sensors = {}
            ec_sensors = {}
            
            for sensor in self.config['sensors']['vwc']:
                try:
                    value = self.get_state(sensor)
                    self.log(f"🔍 DEBUG: Reading VWC sensor {sensor} = {value} (type: {type(value)})")
                    if value not in ['unavailable', 'unknown', None, '']:
                        vwc_sensors[sensor] = float(value)
                        self.log(f"✓ VWC sensor {sensor}: {value}")
                    else:
                        self.log(f"⚠️ VWC sensor {sensor} unavailable: {value}", level='WARNING')
                except Exception as e:
                    self.log(f"❌ Error reading VWC sensor {sensor}: {e}", level='ERROR')
            
            for sensor in self.config['sensors']['ec']:
                try:
                    value = self.get_state(sensor)
                    self.log(f"🔍 DEBUG: Reading EC sensor {sensor} = {value} (type: {type(value)})")
                    if value not in ['unavailable', 'unknown', None, '']:
                        ec_sensors[sensor] = float(value)
                        self.log(f"✓ EC sensor {sensor}: {value}")
                    else:
                        self.log(f"⚠️ EC sensor {sensor} unavailable: {value}", level='WARNING')
                except Exception as e:
                    self.log(f"❌ Error reading EC sensor {sensor}: {e}", level='ERROR')
            
            if not vwc_sensors:
                self.log("⚠️ No VWC sensors available", level='WARNING')
                return None
            
            # Get environmental data - handle async properly
            try:
                temp_state = self.get_state(self.config['sensors']['environmental']['temperature'])
                temperature = float(temp_state) if temp_state not in ['unavailable', 'unknown', None] else 25.0
            except (ValueError, TypeError):
                temperature = 25.0
                
            try:
                hum_state = self.get_state(self.config['sensors']['environmental']['humidity'])
                humidity = float(hum_state) if hum_state not in ['unavailable', 'unknown', None] else 60.0
            except (ValueError, TypeError):
                humidity = 60.0
                
            try:
                vpd_state = self.get_state(self.config['sensors']['environmental']['vpd'])
                vpd = float(vpd_state) if vpd_state not in ['unavailable', 'unknown', None] else 1.0
            except (ValueError, TypeError):
                vpd = 1.0
            
            avg_vwc = np.mean(list(vwc_sensors.values())) if vwc_sensors else 0
            avg_ec = np.mean(list(ec_sensors.values())) if ec_sensors else 3.0
            
            self.log(f"🔍 DEBUG Calculated averages: VWC={avg_vwc:.2f}%, EC={avg_ec:.2f} mS/cm")
            self.log(f"🔍 DEBUG VWC values: {list(vwc_sensors.values())}")
            self.log(f"🔍 DEBUG EC values: {list(ec_sensors.values())}")
            
            return {
                'vwc_sensors': vwc_sensors,
                'ec_sensors': ec_sensors,
                'average_vwc': avg_vwc,
                'average_ec': avg_ec,
                'temperature': temperature,
                'humidity': humidity,
                'vpd': vpd,
                'zone_phases': self.zone_phases.copy(),
                'lights_on': self.get_state('sun.sun', attribute='elevation', default=0) > 0,
                'timestamp': datetime.now()
            }
            
        except Exception as e:
            self.log(f"❌ Error getting system state: {e}", level='ERROR')
            return None

    async def _get_ml_irrigation_predictions(self, current_state: Dict) -> Optional[Dict]:
        """Get ML-based irrigation predictions."""
        try:
            # Prepare ML features
            features = {
                'current_vwc': current_state['average_vwc'],
                'current_ec': current_state['average_ec'],
                'temperature': current_state['temperature'],
                'humidity': current_state['humidity'],
                'vpd': current_state['vpd'],
                'current_phase': current_state['current_phase'],
                'lights_on': current_state['lights_on'],
                'time_since_last_irrigation': self._get_time_since_last_irrigation(),
                'irrigation_count_24h': self._get_irrigation_count_24h(),
                'steering_mode': self.get_state('select.crop_steering_steering_mode', default='Vegetative')
            }
            
            # Add dryback features if available
            dryback_status = self._get_latest_dryback_status()
            if dryback_status:
                features['dryback_percentage'] = dryback_status['dryback_percentage']
                features['dryback_in_progress'] = dryback_status['dryback_in_progress']
            
            # Get predictions
            predictions = self.ml_predictor.predict_irrigation_need(features)
            
            if predictions.get('prediction_available', False):
                return predictions
            else:
                self.log(f"🤖 ML predictions not available: {predictions.get('reason', 'Unknown')}")
                return None
                
        except Exception as e:
            self.log(f"❌ Error getting ML predictions: {e}", level='ERROR')
            return None

    def _get_latest_dryback_status(self) -> Optional[Dict]:
        """Get latest dryback detection status."""
        try:
            # Get from dryback detector
            if hasattr(self.dryback_detector, 'current_dryback'):
                return {
                    'dryback_percentage': self.dryback_detector.current_dryback,
                    'dryback_in_progress': self.dryback_detector.dryback_in_progress,
                    'confidence_score': self.dryback_detector.confidence_score,
                    'last_peak_vwc': self.dryback_detector.last_peak_vwc,
                    'last_peak_time': self.dryback_detector.last_peak_time
                }
            return None
            
        except Exception as e:
            self.log(f"❌ Error getting dryback status: {e}", level='ERROR')
            return None

    async def _make_irrigation_decision(self, current_state: Dict, profile_params: Dict, 
                                      dryback_status: Dict, ml_predictions: Dict) -> Dict:
        """Make intelligent irrigation decision using all available data."""
        try:
            decision = {
                'action': 'wait',
                'reason': 'Evaluating conditions',
                'zone': 1,
                'duration': 30,
                'confidence': 0.5,
                'factors': []
            }
            
            current_vwc = current_state['average_vwc']
            
            # Emergency conditions check
            if current_vwc < self.config['thresholds']['emergency_vwc']:
                decision.update({
                    'action': 'irrigate',
                    'reason': f'Emergency VWC level: {current_vwc:.1f}%',
                    'duration': 60,  # Longer emergency irrigation
                    'confidence': 1.0
                })
                decision['factors'].append('emergency_vwc')
                return decision
            
            # Check if irrigation is on cooldown
            time_since_last = self._get_time_since_last_irrigation()
            min_interval = self.config['thresholds']['min_irrigation_interval']
            
            if time_since_last < min_interval:
                decision.update({
                    'reason': f'Irrigation cooldown: {min_interval - time_since_last:.0f}s remaining',
                    'confidence': 0.0
                })
                return decision
            
            # Phase-specific logic
            phase_decision = self._evaluate_phase_requirements(current_state, profile_params)
            if phase_decision['action'] == 'irrigate':
                decision.update(phase_decision)
                decision['factors'].append('phase_requirements')
            
            # Dryback-based decision
            if dryback_status and dryback_status['dryback_in_progress']:
                dryback_decision = self._evaluate_dryback_decision(dryback_status, profile_params)
                if dryback_decision['action'] == 'irrigate':
                    decision.update(dryback_decision)
                    decision['factors'].append('dryback_target')
            
            # ML-based decision (highest priority if confidence is high)
            if ml_predictions and ml_predictions.get('model_confidence', 0) > 0.7:
                ml_decision = self._evaluate_ml_decision(ml_predictions, current_state)
                if ml_decision['action'] == 'irrigate' and ml_decision['confidence'] > decision['confidence']:
                    decision.update(ml_decision)
                    decision['factors'].append('ml_prediction')
            
            # Profile-based fallback
            if decision['action'] == 'wait':
                profile_decision = self._evaluate_profile_decision(current_state, profile_params)
                if profile_decision['action'] == 'irrigate':
                    decision.update(profile_decision)
                    decision['factors'].append('profile_parameters')
            
            return decision
            
        except Exception as e:
            self.log(f"❌ Error making irrigation decision: {e}", level='ERROR')
            return {'action': 'wait', 'reason': f'Decision error: {e}', 'confidence': 0.0}

    def _evaluate_phase_requirements(self, current_state: Dict, profile_params: Dict) -> Dict:
        """Evaluate irrigation needs based on per-zone phases with grouping and priority."""
        # Collect zones needing irrigation across all phases
        zones_by_priority = {'Critical': [], 'High': [], 'Normal': [], 'Low': []}
        zone_decisions = {}
        groups_needing_water = {}  # Track which groups need water
        
        # Check each zone's phase and needs
        for zone_num in range(1, self.num_zones + 1):
            zone_phase = self.zone_phases.get(zone_num, 'P2')
            zone_group = self._get_zone_group(zone_num)
            zone_priority = self._get_zone_priority(zone_num)
            zone_profile = self._get_zone_profile(zone_num)
            
            # Get zone-specific profile parameters
            if zone_profile != self.get_state('select.crop_steering_crop_type'):
                # Load zone-specific profile
                zone_profile_params = self.crop_profiles.get_profile_parameters(zone_profile)
            else:
                zone_profile_params = profile_params
                
            if zone_phase == 'P0':  # Dryback - no irrigation
                continue
                
            elif zone_phase == 'P1':  # Ramp-up phase
                decision = self._evaluate_zone_p1_needs(zone_num, zone_profile_params)
                if decision['needs_irrigation']:
                    zone_decisions[zone_num] = decision
                    zones_by_priority[zone_priority].append(zone_num)
                    if zone_group != 'Ungrouped':
                        groups_needing_water.setdefault(zone_group, []).append(zone_num)
                    
            elif zone_phase == 'P2':  # Maintenance phase
                decision = self._evaluate_zone_p2_needs(zone_num, zone_profile_params)
                if decision['needs_irrigation']:
                    zone_decisions[zone_num] = decision
                    zones_by_priority[zone_priority].append(zone_num)
                    if zone_group != 'Ungrouped':
                        groups_needing_water.setdefault(zone_group, []).append(zone_num)
                    
            elif zone_phase == 'P3':  # Pre-lights-off emergency
                decision = self._evaluate_zone_p3_needs(zone_num)
                if decision['needs_irrigation']:
                    zone_decisions[zone_num] = decision
                    zones_by_priority[zone_priority].append(zone_num)
                    if zone_group != 'Ungrouped':
                        groups_needing_water.setdefault(zone_group, []).append(zone_num)
        
        # Process grouped zones
        all_zones_to_irrigate = []
        
        # Add all zones from groups where at least one zone needs water
        for group, zones_in_group in groups_needing_water.items():
            # Get all zones in this group
            all_group_zones = []
            for zone_num in range(1, self.num_zones + 1):
                if self._get_zone_group(zone_num) == group:
                    all_group_zones.append(zone_num)
            
            # Check if enough zones in group need water (>50% threshold)
            if len(zones_in_group) >= len(all_group_zones) * 0.5:
                # Add all zones in the group
                for zone in all_group_zones:
                    if zone not in all_zones_to_irrigate:
                        all_zones_to_irrigate.append(zone)
                        # Add dummy decision if zone didn't originally need water
                        if zone not in zone_decisions:
                            zone_vwc = self._get_zone_vwc(zone)
                            zone_decisions[zone] = {
                                'needs_irrigation': True,
                                'vwc': zone_vwc if zone_vwc else 50,
                                'reason': f'Group {group} irrigation',
                                'confidence': 0.5
                            }
        
        # Add ungrouped zones by priority
        for priority in ['Critical', 'High', 'Normal', 'Low']:
            for zone_num in zones_by_priority[priority]:
                if zone_num not in all_zones_to_irrigate and self._get_zone_group(zone_num) == 'Ungrouped':
                    all_zones_to_irrigate.append(zone_num)
        
        # If any zones need irrigation, return a multi-zone decision
        if all_zones_to_irrigate:
            # Sort by zone number for consistent ordering
            all_zones_to_irrigate.sort()
            
            # Combine zone details into a single decision
            zone_details = []
            combined_confidence = 0
            for zone_num in all_zones_to_irrigate:
                decision = zone_decisions[zone_num]
                zone_details.append(f"Z{zone_num}[{self.zone_phases[zone_num]}]:{decision['vwc']:.1f}%")
                combined_confidence = max(combined_confidence, decision['confidence'])
            
            return {
                'action': 'irrigate',
                'reason': f'Multi-zone irrigation {all_zones_to_irrigate}: {", ".join(zone_details)}',
                'duration': 30,  # Standard duration
                'confidence': combined_confidence,
                'zones': all_zones_to_irrigate,
                'zone_decisions': zone_decisions
            }
        
        return {'action': 'wait', 'reason': 'All zones satisfied in their current phases'}

    def _evaluate_zone_p1_needs(self, zone_num: int, profile_params: Dict) -> Dict:
        """Evaluate if a specific zone in P1 needs irrigation."""
        target_vwc = self._get_number_entity_value("number.crop_steering_p1_target_vwc", 65)
        zone_vwc = self._get_zone_vwc(zone_num)
        
        if zone_vwc is not None and zone_vwc < target_vwc * 0.9:
            shot_size = self._get_number_entity_value("number.crop_steering_p1_initial_shot_size", 2.0)
            return {
                'needs_irrigation': True,
                'vwc': zone_vwc,
                'threshold': target_vwc * 0.9,
                'shot_size': shot_size,
                'confidence': 0.8
            }
        
        return {'needs_irrigation': False, 'vwc': zone_vwc}

    def _evaluate_zone_p2_needs(self, zone_num: int, profile_params: Dict) -> Dict:
        """Evaluate if a specific zone in P2 needs irrigation."""
        vwc_threshold = self._get_number_entity_value("number.crop_steering_p2_vwc_threshold", 60)
        zone_vwc = self._get_zone_vwc(zone_num)
        
        if zone_vwc is not None and zone_vwc < vwc_threshold:
            shot_size = self._get_number_entity_value("number.crop_steering_p2_shot_size", 5.0)
            return {
                'needs_irrigation': True,
                'vwc': zone_vwc,
                'threshold': vwc_threshold,
                'shot_size': shot_size,
                'confidence': 0.7
            }
        
        return {'needs_irrigation': False, 'vwc': zone_vwc}

    def _evaluate_zone_p3_needs(self, zone_num: int) -> Dict:
        """P3 is the final dryback period - NO irrigation unless true emergency."""
        zone_vwc = self._get_zone_vwc(zone_num)
        
        # P3 should normally have NO irrigation - it's the dryback period
        # Only irrigate if there's a critical emergency (plant wilting risk)
        critical_threshold = 35.0  # Much lower than P3 emergency threshold
        
        if zone_vwc is not None and zone_vwc < critical_threshold:
            # This is a true emergency - plant health at risk
            shot_size = self._get_number_entity_value("number.crop_steering_p3_emergency_shot_size", 1.0)
            return {
                'needs_irrigation': True,
                'vwc': zone_vwc,
                'threshold': critical_threshold,
                'shot_size': shot_size,
                'confidence': 1.0,
                'emergency': True
            }
        
        # Normal P3 operation - no irrigation, let it dry back
        return {'needs_irrigation': False, 'vwc': zone_vwc}

    def _evaluate_dryback_decision(self, dryback_status: Dict, profile_params: Dict) -> Dict:
        """Evaluate irrigation based on dryback analysis."""
        current_dryback = dryback_status['dryback_percentage']
        target_dryback = profile_params.get('dryback_target', 15)
        confidence = dryback_status.get('confidence_score', 0.5)
        
        if current_dryback >= target_dryback * 0.9 and confidence > 0.7:
            return {
                'action': 'irrigate',
                'reason': f'Dryback target reached: {current_dryback:.1f}% ≥ {target_dryback}%',
                'duration': 35,
                'confidence': confidence
            }
        
        return {'action': 'wait', 'reason': f'Dryback in progress: {current_dryback:.1f}%'}

    def _evaluate_ml_decision(self, ml_predictions: Dict, current_state: Dict) -> Dict:
        """Evaluate irrigation based on ML predictions."""
        analysis = ml_predictions.get('analysis', {})
        max_need = analysis.get('max_irrigation_need', 0)
        urgency = analysis.get('irrigation_urgency', 'moderate')
        confidence = ml_predictions.get('model_confidence', 0.5)
        
        if urgency == 'critical' and max_need > 0.9:
            return {
                'action': 'irrigate',
                'reason': f'ML critical prediction: {max_need:.1%} need',
                'duration': 45,
                'confidence': confidence
            }
        elif urgency == 'high' and max_need > 0.7:
            return {
                'action': 'irrigate',
                'reason': f'ML high priority: {max_need:.1%} need',
                'duration': 30,
                'confidence': confidence * 0.8
            }
        
        return {'action': 'wait', 'reason': f'ML prediction: {max_need:.1%} need ({urgency})'}

    def _evaluate_profile_decision(self, current_state: Dict, profile_params: Dict) -> Dict:
        """Evaluate irrigation based on crop profile parameters."""
        vwc = current_state['average_vwc']
        vwc_min = profile_params.get('vwc_target_min', 50)
        
        if vwc < vwc_min:
            return {
                'action': 'irrigate',
                'reason': f'Below profile minimum: {vwc:.1f}% < {vwc_min}%',
                'duration': 30,
                'confidence': 0.6
            }
        
        return {'action': 'wait', 'reason': 'Profile parameters satisfied'}

    async def _execute_intelligent_irrigation(self, decision: Dict):
        """Execute irrigation with intelligent zone selection and monitoring."""
        try:
            # Check if this is multi-zone emergency irrigation
            zones = decision.get('zones', [])
            if zones:
                # Multi-zone emergency irrigation
                duration = decision.get('duration', 40)
                reason = decision.get('reason', 'Emergency irrigation')
                shot_size = decision.get('shot_size_percent', 2.0)
                
                self.log(f"🚨 Executing emergency irrigation: Zones {zones}, {duration}s - {reason}")
                
                # Execute irrigation for each zone that needs it
                for zone in zones:
                    try:
                        zone_result = await self._execute_irrigation_shot(zone, duration, shot_type='emergency')
                        self.log(f"💧 Emergency irrigation completed for zone {zone}")
                        
                        # Add to ML training data
                        zone_decision = decision.copy()
                        zone_decision['zone'] = zone
                        await self._add_ml_training_sample(zone_decision, zone_result)
                        
                    except Exception as zone_error:
                        self.log(f"❌ Error irrigating zone {zone}: {zone_error}", level='ERROR')
                
                return
                
            # Standard single-zone irrigation
            zone = decision.get('zone', 1)
            duration = decision.get('duration', 30)
            reason = decision.get('reason', 'Intelligent irrigation')
            
            # Select optimal zone based on sensor readings
            optimal_zone = await self._select_optimal_zone()
            if optimal_zone:
                zone = optimal_zone
            
            self.log(f"💧 Executing intelligent irrigation: Zone {zone}, {duration}s - {reason}")
            
            # Execute irrigation
            irrigation_result = await self._execute_irrigation_shot(zone, duration, shot_type='intelligent')
            
            # Add to ML training data
            await self._add_ml_training_sample(decision, irrigation_result)
            
            # Update crop profile performance
            await self._update_crop_profile_performance(irrigation_result)
            
        except Exception as e:
            self.log(f"❌ Error executing intelligent irrigation: {e}", level='ERROR')

    async def _select_optimal_zone(self) -> Optional[int]:
        """Select optimal irrigation zone based on sensor data."""
        try:
            zone_scores = {}
            
            # Analyze VWC by zone
            configured_zones = list(self.config['hardware']['zone_valves'].keys())
            for zone in configured_zones:
                zone_vwc_sensors = [s for s in self.config['sensors']['vwc'] if f'r{zone}' in s or f'z{zone}' in s]
                
                if zone_vwc_sensors:
                    zone_vwc_values = []
                    for sensor in zone_vwc_sensors:
                        value = self.get_state(sensor)
                        if value not in ['unavailable', 'unknown', None]:
                            zone_vwc_values.append(float(value))
                    
                    if zone_vwc_values:
                        avg_vwc = np.mean(zone_vwc_values)
                        vwc_std = np.std(zone_vwc_values)
                        
                        # Score based on need (lower VWC = higher score) and reliability (lower std = higher score)
                        need_score = max(0, (70 - avg_vwc) / 70)  # Higher score for lower VWC
                        reliability_score = max(0, 1 - (vwc_std / 10))  # Higher score for lower variance
                        
                        zone_scores[zone] = need_score * 0.7 + reliability_score * 0.3
            
            if zone_scores:
                optimal_zone = max(zone_scores, key=zone_scores.get)
                self.log(f"🎯 Optimal zone selected: {optimal_zone} (score: {zone_scores[optimal_zone]:.2f})")
                return optimal_zone
            
            return None
            
        except Exception as e:
            self.log(f"❌ Error selecting optimal zone: {e}", level='ERROR')
            return None

    async def _execute_irrigation_shot(self, zone: int, duration: int, shot_type: str = 'manual') -> Dict:
        """Execute irrigation shot with proper sequencing and monitoring."""
        try:
            if self.irrigation_in_progress:
                self.log("⚠️ Irrigation already in progress - skipping")
                return {'status': 'skipped', 'reason': 'already_in_progress'}
            
            self.irrigation_in_progress = True
            start_time = datetime.now()
            
            # Record pre-irrigation VWC
            pre_vwc = self._get_zone_average_vwc(zone)
            
            # Hardware sequence: Pump -> Main Line -> Zone Valve
            pump_entity = self.config['hardware']['pump_master']
            main_line_entity = self.config['hardware']['main_line']
            zone_entity = self.config['hardware']['zone_valves'][zone]
            
            # Turn on pump
            await self.call_service('switch/turn_on', entity_id=pump_entity)
            await asyncio.sleep(2)  # Allow pump to prime
            
            # Turn on main line
            await self.call_service('switch/turn_on', entity_id=main_line_entity)
            await asyncio.sleep(1)  # Allow pressure to build
            
            # Turn on zone valve
            await self.call_service('switch/turn_on', entity_id=zone_entity)
            
            # Log irrigation start
            self.log(f"💧 Irrigation started: Zone {zone}, {duration}s, Type: {shot_type}")
            
            # Wait for irrigation duration
            await asyncio.sleep(duration)
            
            # Turn off in reverse order: Zone -> Main Line -> Pump
            await self.call_service('switch/turn_off', entity_id=zone_entity)
            await asyncio.sleep(1)
            await self.call_service('switch/turn_off', entity_id=main_line_entity)
            await asyncio.sleep(1)
            await self.call_service('switch/turn_off', entity_id=pump_entity)
            
            end_time = datetime.now()
            actual_duration = (end_time - start_time).total_seconds()
            
            # Record post-irrigation VWC (wait a bit for absorption)
            await asyncio.sleep(30)
            post_vwc = self._get_zone_average_vwc(zone)
            
            # Calculate results
            irrigation_result = {
                'status': 'completed',
                'zone': zone,
                'duration_requested': duration,
                'duration_actual': actual_duration,
                'shot_type': shot_type,
                'start_time': start_time.isoformat(),
                'end_time': end_time.isoformat(),
                'pre_vwc': pre_vwc,
                'post_vwc': post_vwc,
                'vwc_improvement': post_vwc - pre_vwc if pre_vwc and post_vwc else 0,
                'efficiency': min((post_vwc - pre_vwc) / duration * 100, 1.0) if pre_vwc and post_vwc else 0.5
            }
            
            self.last_irrigation_time = end_time
            self.irrigation_in_progress = False
            
            # Update zone-specific last irrigation time
            if zone in self.zone_phase_data:
                self.zone_phase_data[zone]['last_irrigation_time'] = end_time
            
            # Update water usage tracking
            await self._update_zone_water_usage(zone, duration)
            
            # Save state after irrigation (critical event)
            self._save_persistent_state()
            
            # Fire irrigation event
            self.fire_event('crop_steering_irrigation_shot', irrigation_result)
            
            self.log(f"✅ Irrigation completed: Zone {zone}, {actual_duration:.1f}s, "
                    f"VWC: {pre_vwc:.1f}% → {post_vwc:.1f}%")
            
            return irrigation_result
            
        except Exception as e:
            self.irrigation_in_progress = False
            await self._emergency_stop()
            self.log(f"❌ Error during irrigation: {e}", level='ERROR')
            return {'status': 'error', 'error': str(e)}

    def _get_zone_average_vwc(self, zone: int) -> Optional[float]:
        """Get average VWC for specific zone."""
        try:
            zone_sensors = [s for s in self.config['sensors']['vwc'] if f'r{zone}' in s]
            vwc_values = []
            
            for sensor in zone_sensors:
                value = self.get_state(sensor)
                if value not in ['unavailable', 'unknown', None]:
                    vwc_values.append(float(value))
            
            return np.mean(vwc_values) if vwc_values else None
            
        except Exception as e:
            self.log(f"❌ Error getting zone VWC: {e}", level='ERROR')
            return None

    async def _emergency_stop(self):
        """Emergency stop all irrigation hardware."""
        try:
            hardware = self.config['hardware']
            
            # Turn off all zone valves
            for zone_entity in hardware['zone_valves'].values():
                await self.call_service('switch/turn_off', entity_id=zone_entity)
            
            # Turn off main line
            await self.call_service('switch/turn_off', entity_id=hardware['main_line'])
            
            # Turn off pump
            await self.call_service('switch/turn_off', entity_id=hardware['pump_master'])
            
            self.irrigation_in_progress = False
            self.log("🛑 Emergency stop executed - all irrigation hardware turned off")
            
        except Exception as e:
            self.log(f"❌ Error during emergency stop: {e}", level='ERROR')

    async def _check_emergency_conditions(self, fused_vwc: float):
        """Check for emergency irrigation conditions."""
        try:
            if fused_vwc and fused_vwc < self.config['thresholds']['emergency_vwc']:
                self.log(f"🚨 Emergency VWC condition: {fused_vwc:.1f}%", level='WARNING')
                
                # Check if we can irrigate (not on cooldown)
                time_since_last = self._get_time_since_last_irrigation()
                if time_since_last > 300:  # 5 minutes minimum for emergency
                    await self._execute_irrigation_shot(1, 60, shot_type='emergency')
                
        except Exception as e:
            self.log(f"❌ Error checking emergency conditions: {e}", level='ERROR')

    async def _handle_critical_ec(self, ec_level: float):
        """Handle critical EC levels."""
        try:
            self.log(f"🚨 Critical EC level handling: {ec_level:.2f} mS/cm")
            
            # Alert via configured notification service
            notification_service = self.config.get('notification_service', 'notify.persistent_notification')
            if notification_service and notification_service.startswith('notify.'):
                service_name = notification_service.replace('.', '/')
                await self.call_service(service_name, 
                                message=f"🚨 Critical EC level detected: {ec_level:.2f} mS/cm")
            else:
                self.log(f"📱 Critical EC Alert: {ec_level:.2f} mS/cm")
            
        except Exception as e:
            self.log(f"❌ Error handling critical EC: {e}", level='ERROR')

    def _get_time_since_last_irrigation(self) -> float:
        """Get time since last irrigation in seconds."""
        if self.last_irrigation_time:
            return (datetime.now() - self.last_irrigation_time).total_seconds()
        return 86400  # 24 hours if no previous irrigation

    def _get_irrigation_count_24h(self) -> int:
        """Get irrigation count in last 24 hours."""
        # This would typically query a database or entity history
        return 8  # Placeholder

    def _get_zone_vwc(self, zone_num: int) -> float | None:
        """Get VWC value for specific zone from configured sensors."""
        try:
            # Try integration sensor first (preferred method)
            integration_sensor = f"sensor.crop_steering_vwc_zone_{zone_num}"
            state = self.get_state(integration_sensor)
            if state not in ['unknown', 'unavailable', None]:
                return float(state)
            
            # Fallback to direct sensor configuration
            zone_vwc_sensors = []
            
            # Look for zone-specific sensors in VWC sensor list
            if 'sensors' in self.config and 'vwc' in self.config['sensors']:
                for sensor in self.config['sensors']['vwc']:
                    # Check if sensor belongs to this zone (various naming patterns)
                    if (f'_zone_{zone_num}_' in sensor or 
                        f'_z{zone_num}_' in sensor or 
                        f'_r{zone_num}_' in sensor or
                        f'zone{zone_num}' in sensor.lower()):
                        zone_vwc_sensors.append(sensor)
            
            # Average values from zone sensors
            if zone_vwc_sensors:
                values = []
                for sensor in zone_vwc_sensors:
                    try:
                        state = self.get_state(sensor)
                        if state not in ['unknown', 'unavailable', None]:
                            values.append(float(state))
                    except (ValueError, TypeError):
                        continue
                
                if values:
                    return round(sum(values) / len(values), 2)
            
            return None
            
        except Exception as e:
            self.log(f"❌ Error getting zone {zone_num} VWC: {e}", level='ERROR')
            return None

    def _get_number_of_zones(self) -> int:
        """Get number of zones from integration configuration."""
        try:
            # Try to get from integration number entity
            zones_entity = self.get_state("number.crop_steering_substrate_volume")  # This exists, so integration is loaded
            if zones_entity:
                # Check for zone entities to count them
                zone_count = 0
                for i in range(1, 11):  # Check up to 10 zones
                    zone_sensor = f"sensor.crop_steering_vwc_zone_{i}"
                    if self.entity_exists(zone_sensor):
                        zone_count = i
                return max(zone_count, 1)  # At least 1 zone
            
            # Fallback to configuration
            if 'hardware' in self.config and 'zone_valves' in self.config['hardware']:
                return len(self.config['hardware']['zone_valves'])
            
            return 1  # Default single zone
        except Exception as e:
            self.log(f"❌ Error getting number of zones: {e}", level='ERROR')
            return 1

    def _calculate_next_irrigation_time(self) -> datetime | None:
        """Calculate when next irrigation should occur based on zone phases."""
        try:
            now = datetime.now()
            
            # If irrigation is currently in progress, return None
            if self.irrigation_in_progress:
                return None
            
            # Find the soonest irrigation needed across all zones
            earliest_time = None
            
            for zone_num in range(1, self.num_zones + 1):
                zone_phase = self.zone_phases.get(zone_num, 'P2')
                zone_vwc = self._get_zone_vwc(zone_num)
                
                zone_next_time = None
                
                if zone_phase == "P0":
                    # No irrigation during dryback
                    continue
                    
                elif zone_phase == "P1":
                    # Ramp-up phase - frequent small irrigations
                    zone_next_time = now + timedelta(minutes=45)
                    
                elif zone_phase == "P2":
                    # Maintenance phase - based on VWC thresholds
                    if zone_vwc is not None:
                        threshold = self._get_number_entity_value("number.crop_steering_p2_vwc_threshold", 60.0)
                        if zone_vwc < threshold:
                            # Needs irrigation soon
                            zone_next_time = now + timedelta(minutes=15)
                        else:
                            # Can wait longer
                            zone_next_time = now + timedelta(hours=2)
                    else:
                        # No VWC data, conservative estimate
                        zone_next_time = now + timedelta(hours=1)
                    
                elif zone_phase == "P3":
                    # Pre-lights-off - check emergency threshold
                    emergency_threshold = self._get_number_entity_value("number.crop_steering_p3_emergency_vwc_threshold", 45)
                    if zone_vwc and zone_vwc < emergency_threshold:
                        # Emergency irrigation needed
                        zone_next_time = now + timedelta(minutes=5)
                    else:
                        zone_next_time = now + timedelta(minutes=30)
                
                # Keep track of earliest time needed
                if zone_next_time and (earliest_time is None or zone_next_time < earliest_time):
                    earliest_time = zone_next_time
            
            return earliest_time
            
        except Exception as e:
            self.log(f"❌ Error calculating next irrigation time: {e}", level='ERROR')
            return None

    def _get_lights_off_time(self) -> datetime | None:
        """Get the time when lights turn off."""
        try:
            # This would typically read from a schedule or light entity
            # For now, assume lights off at 22:00
            now = datetime.now()
            lights_off = now.replace(hour=22, minute=0, second=0, microsecond=0)
            
            # If already past lights off time, assume next day
            if lights_off <= now:
                lights_off += timedelta(days=1)
            
            return lights_off
        except Exception:
            return None

    async def _check_phase_transitions(self, kwargs):
        """Check and handle automatic phase transitions PER ZONE based on conditions."""
        try:
            now = datetime.now()
            current_time = now.time()
            
            # Get configuration values from existing entities
            p0_max_duration = self._get_number_entity_value("number.crop_steering_p0_max_wait_time", 45)
            p1_recovery_target = self._get_number_entity_value("number.crop_steering_p1_target_vwc", 65)
            dryback_target = self._get_number_entity_value("number.crop_steering_veg_dryback_target", 50)
            
            # Check each zone independently with its own schedule
            for zone_num in range(1, self.num_zones + 1):
                current_phase = self.zone_phases.get(zone_num, 'P2')
                zone_vwc = self._get_zone_vwc(zone_num)
                
                # Get zone-specific schedule
                zone_schedule = self._get_zone_schedule(zone_num)
                lights_on_time = zone_schedule['lights_on']
                lights_off_time = zone_schedule['lights_off']
                
                # Check if lights are currently on for this zone
                lights_on = self._are_lights_on(current_time, lights_on_time, lights_off_time)
                
                target_phase = None
                reason = ""
                
                # Phase transition logic PER ZONE
                if not lights_on:
                    # Lights off - zone should be in P0 (night dryback)
                    if current_phase != 'P0':
                        target_phase = 'P0'
                        reason = f"Zone {zone_num}: Lights off - night dryback phase"
                    
                elif lights_on and current_phase == 'P0':
                    # Check P0 → P1 transition conditions for this zone
                    if self._should_zone_exit_p0(zone_num, zone_vwc, dryback_target, p0_max_duration):
                        target_phase = 'P1'
                        reason = f"Zone {zone_num}: P0 dryback target achieved or max duration reached"
                        
                elif current_phase == 'P1':
                    # Check P1 → P2 transition conditions for this zone
                    if zone_vwc and zone_vwc >= p1_recovery_target:
                        target_phase = 'P2'
                        reason = f"Zone {zone_num}: P1 recovery target achieved: {zone_vwc:.1f}% >= {p1_recovery_target}%"
                        
                elif current_phase == 'P2':
                    # Check P2 → P3 transition based on ML-predicted last irrigation timing
                    # P3 starts AFTER the last P2 shot, when we begin final dryback to morning
                    should_transition = await self._should_zone_start_p3(zone_num, lights_on_time, lights_off_time)
                    if should_transition:
                        target_phase = 'P3'
                        reason = f"Zone {zone_num}: Starting final dryback period to achieve target by morning"
                        
                elif current_phase == 'P3':
                    # P3 → P0 when lights turn off
                    if not lights_on:
                        target_phase = 'P0'
                        reason = f"Zone {zone_num}: Lights off - starting night dryback"
                
                # Execute transition if needed for this zone
                if target_phase and target_phase != current_phase:
                    await self._transition_zone_to_phase(zone_num, target_phase, reason)
                    
        except Exception as e:
            self.log(f"❌ Error checking phase transitions: {e}", level='ERROR')

    def _add_minutes_to_time(self, time_obj: time, minutes: float) -> time:
        """Add minutes to a time object."""
        dt = datetime.combine(datetime.today(), time_obj)
        dt += timedelta(minutes=minutes)
        return dt.time()

    def _time_is_between(self, current: time, start: time, end: time) -> bool:
        """Check if current time is between start and end times."""
        if start <= end:
            return start <= current <= end
        else:
            # Handle overnight periods (e.g., 22:00 to 06:00)
            return current >= start or current <= end

    def _are_lights_on(self, current_time: time, lights_on: time, lights_off: time) -> bool:
        """Check if lights should be on at current time."""
        if lights_on <= lights_off:
            # Normal day schedule (e.g., 12pm to 12am)
            return lights_on <= current_time <= lights_off
        else:
            # Overnight schedule (e.g., 6pm to 6am)
            return current_time >= lights_on or current_time <= lights_off

    def _time_is_near(self, current: time, target: time, tolerance_minutes: int = 5) -> bool:
        """Check if current time is within tolerance of target time."""
        current_minutes = current.hour * 60 + current.minute
        target_minutes = target.hour * 60 + target.minute
        
        # Handle day boundary
        if abs(current_minutes - target_minutes) > 12 * 60:  # More than 12 hours apart
            if current_minutes < target_minutes:
                current_minutes += 24 * 60
            else:
                target_minutes += 24 * 60
        
        return abs(current_minutes - target_minutes) <= tolerance_minutes

    def _should_zone_exit_p0(self, zone_num: int, zone_vwc: float, dryback_target: float, max_duration_minutes: float) -> bool:
        """Check if zone's P0 phase should end based on dryback progress and max duration."""
        try:
            zone_data = self.zone_phase_data.get(zone_num, {})
            
            # Check max duration first (safety limit)
            if zone_data.get('p0_start_time'):
                elapsed_minutes = (datetime.now() - zone_data['p0_start_time']).total_seconds() / 60
                if elapsed_minutes >= max_duration_minutes:
                    self.log(f"🕐 Zone {zone_num}: P0 max duration reached: {elapsed_minutes:.1f}min >= {max_duration_minutes}min")
                    return True
            
            # Check dryback target (if we have VWC data)
            if zone_vwc and zone_data.get('p0_peak_vwc'):
                dryback_percent = ((zone_data['p0_peak_vwc'] - zone_vwc) / zone_data['p0_peak_vwc']) * 100
                if dryback_percent >= dryback_target:
                    self.log(f"🎯 Zone {zone_num}: P0 dryback target achieved: {dryback_percent:.1f}% >= {dryback_target}%")
                    return True
            
            return False
            
        except Exception as e:
            self.log(f"❌ Error checking zone {zone_num} P0 exit conditions: {e}", level='ERROR')
            return False

    async def _calculate_optimal_p3_timing(self, lights_off_time: time) -> time | None:
        """Calculate optimal P3 start time using ML dryback prediction."""
        try:
            # Get target dryback for overnight period
            target_dryback = self._get_number_entity_value("number.crop_steering_veg_dryback_target", 50)
            
            # Get current dryback status from advanced detector
            if hasattr(self, 'dryback_detector') and self.dryback_detector:
                # Get dryback prediction for target percentage
                prediction = await self.dryback_detector.predict_target_dryback_time(target_dryback)
                
                if prediction.get('prediction_available'):
                    predicted_minutes = prediction.get('predicted_minutes_remaining', 60)
                    confidence = prediction.get('confidence', 0.5)
                    
                    self.log(f"🧠 ML Dryback Prediction: {predicted_minutes:.1f}min to reach {target_dryback}% (confidence: {confidence:.2f})")
                    
                    # Calculate when to start P3 to achieve target dryback by lights off
                    lights_off_dt = datetime.combine(datetime.today(), lights_off_time)
                    optimal_p3_start = lights_off_dt - timedelta(minutes=predicted_minutes + 30)  # +30min buffer for P3 irrigation
                    
                    # Ensure P3 doesn't start too early (minimum 2 hours before lights off)
                    earliest_p3 = lights_off_dt - timedelta(hours=2)
                    if optimal_p3_start < earliest_p3:
                        optimal_p3_start = earliest_p3
                        self.log(f"⚠️ P3 timing adjusted to minimum 2-hour window")
                    
                    # Ensure P3 doesn't start too late (minimum 30 minutes before lights off)  
                    latest_p3 = lights_off_dt - timedelta(minutes=30)
                    if optimal_p3_start > latest_p3:
                        optimal_p3_start = latest_p3
                        self.log(f"⚠️ P3 timing adjusted to ensure 30min minimum window")
                    
                    return optimal_p3_start.time()
            
            # Fallback to historical average if ML prediction unavailable
            return await self._calculate_historical_p3_timing(lights_off_time)
            
        except Exception as e:
            self.log(f"❌ Error calculating optimal P3 timing: {e}", level='ERROR')
            # Ultimate fallback - 1 hour before lights off
            fallback_dt = datetime.combine(datetime.today(), lights_off_time) - timedelta(hours=1)
            return fallback_dt.time()

    async def _calculate_historical_p3_timing(self, lights_off_time: time) -> time | None:
        """Calculate P3 timing based on historical dryback patterns."""
        try:
            # Get historical dryback data from the last 7 days
            # This would query ML training data or stored dryback patterns
            
            # For now, use intelligent defaults based on typical dryback rates
            target_dryback = self._get_number_entity_value("number.crop_steering_veg_dryback_target", 50)
            substrate_volume = self._get_number_entity_value("number.crop_steering_substrate_volume", 10)
            
            # Estimate dryback time based on substrate size and target
            # Larger substrates = slower dryback, higher targets = longer time
            base_dryback_minutes = 120  # 2 hours base
            volume_factor = substrate_volume / 10  # Normalize to 10L baseline
            target_factor = target_dryback / 50    # Normalize to 50% baseline
            
            estimated_dryback_minutes = base_dryback_minutes * volume_factor * target_factor
            
            # Add buffer for P3 irrigation (30 minutes)
            total_minutes_needed = estimated_dryback_minutes + 30
            
            # Calculate optimal P3 start time
            lights_off_dt = datetime.combine(datetime.today(), lights_off_time)
            optimal_p3_start = lights_off_dt - timedelta(minutes=total_minutes_needed)
            
            self.log(f"📊 Historical P3 timing: {total_minutes_needed:.0f}min before lights off (est. dryback: {estimated_dryback_minutes:.0f}min)")
            
            return optimal_p3_start.time()
            
        except Exception as e:
            self.log(f"❌ Error calculating historical P3 timing: {e}", level='ERROR')
            return None

    async def _should_zone_start_p3(self, zone_num: int, lights_on_time: time, lights_off_time: time) -> bool:
        """Determine if zone should transition to P3 (start final dryback period)."""
        try:
            now = datetime.now()
            zone_vwc = self._get_zone_vwc(zone_num)
            if zone_vwc is None:
                return False
            
            # Calculate hours until next lights-on
            next_lights_on = datetime.combine(datetime.today(), lights_on_time)
            if next_lights_on <= now:
                next_lights_on += timedelta(days=1)
            hours_until_lights_on = (next_lights_on - now).total_seconds() / 3600
            
            # Get target dryback for overnight
            target_dryback = self._get_number_entity_value("number.crop_steering_veg_dryback_target", 50)
            
            # Get ML-predicted dryback rate for this zone
            predicted_dryback_rate = await self._get_zone_dryback_rate(zone_num)
            if predicted_dryback_rate is None:
                # Fallback: estimate based on substrate volume
                substrate_volume = self._get_number_entity_value("number.crop_steering_substrate_volume", 10)
                predicted_dryback_rate = 2.0 / substrate_volume  # %/hour, smaller = slower
            
            # Calculate how many hours needed to achieve target dryback
            hours_needed_for_dryback = target_dryback / predicted_dryback_rate
            
            # If we've reached the point where we need to start drying back
            if hours_until_lights_on <= hours_needed_for_dryback:
                self.log(f"🎯 Zone {zone_num}: Time to start P3 dryback. "
                        f"Need {hours_needed_for_dryback:.1f}h to dry {target_dryback}% "
                        f"({predicted_dryback_rate:.2f}%/h rate), "
                        f"have {hours_until_lights_on:.1f}h until lights on")
                return True
            
            # Also check if zone just got irrigated and won't need water again before morning
            zone_data = self.zone_phase_data.get(zone_num, {})
            if zone_data.get('last_irrigation_time'):
                time_since_irrigation = (now - zone_data['last_irrigation_time']).total_seconds() / 60
                if time_since_irrigation < 5:  # Just irrigated in last 5 minutes
                    # Check if this VWC level will last until morning
                    p2_threshold = self._get_number_entity_value("number.crop_steering_p2_vwc_threshold", 60)
                    vwc_buffer = zone_vwc - p2_threshold
                    hours_until_dry = vwc_buffer / predicted_dryback_rate if predicted_dryback_rate > 0 else 999
                    
                    if hours_until_dry >= hours_until_lights_on:
                        self.log(f"💧 Zone {zone_num}: Last P2 irrigation complete. "
                                f"VWC {zone_vwc:.1f}% will last {hours_until_dry:.1f}h until threshold. "
                                f"Starting P3 dryback period.")
                        return True
            
            return False
            
        except Exception as e:
            self.log(f"❌ Error checking zone {zone_num} P3 transition: {e}", level='ERROR')
            return False

    async def _get_zone_dryback_rate(self, zone_num: int) -> float | None:
        """Get ML-predicted or historical dryback rate for a specific zone."""
        try:
            # Try to get from dryback detector if available
            if hasattr(self, 'dryback_detector') and self.dryback_detector:
                # For now, use overall dryback rate
                # TODO: Implement per-zone dryback tracking
                status = await self.dryback_detector.get_current_status()
                if status and status.get('current_dryback_rate'):
                    return abs(status['current_dryback_rate'])
            
            # Fallback to historical estimate based on zone characteristics
            # Could be enhanced with zone-specific ML model
            return None
            
        except Exception as e:
            self.log(f"❌ Error getting zone {zone_num} dryback rate: {e}", level='ERROR')
            return None

    async def _transition_zone_to_phase(self, zone_num: int, new_phase: str, reason: str):
        """Transition a specific zone to a new irrigation phase."""
        try:
            old_phase = self.zone_phases.get(zone_num, 'P2')
            self.zone_phases[zone_num] = new_phase
            
            self.log(f"🔄 Zone {zone_num} transition: {old_phase} → {new_phase} ({reason})")
            
            # Save state after phase change (critical event)
            self._save_persistent_state()
            
            # Update zone-specific sensor
            await self.set_state(f'sensor.crop_steering_zone_{zone_num}_phase',
                               state=new_phase,
                               attributes={
                                   'friendly_name': f'Zone {zone_num} Phase',
                                   'icon': self._get_phase_icon(new_phase),
                                   'transition_reason': reason,
                                   'transition_time': datetime.now().isoformat()
                               })
            
            # Update zone phase data
            zone_data = self.zone_phase_data.get(zone_num, {})
            
            if new_phase == 'P0':
                self.log(f"🌅 Zone {zone_num}: Starting dryback phase")
                zone_data['p0_start_time'] = datetime.now()
                # Record peak VWC at start of P0 for dryback calculation
                zone_vwc = self._get_zone_vwc(zone_num)
                if zone_vwc:
                    zone_data['p0_peak_vwc'] = zone_vwc
                    self.log(f"📊 Zone {zone_num}: P0 peak VWC recorded: {zone_vwc:.1f}%")
            elif new_phase == 'P1':
                self.log(f"⬆️ Zone {zone_num}: Starting ramp-up phase")
                # Reset P0 tracking
                zone_data['p0_start_time'] = None
                zone_data['p0_peak_vwc'] = None
            elif new_phase == 'P2':
                self.log(f"⚖️ Zone {zone_num}: Starting maintenance phase")
            elif new_phase == 'P3':
                self.log(f"🌙 Zone {zone_num}: Starting pre-lights-off phase")
            
            self.zone_phase_data[zone_num] = zone_data
            
            # Update crop profile parameters if needed (could be zone-specific in future)
            await self._update_phase_parameters()
            
        except Exception as e:
            self.log(f"❌ Error transitioning zone {zone_num} to phase {new_phase}: {e}", level='ERROR')

    def _get_phase_icon(self, phase: str) -> str:
        """Get icon for phase."""
        phase_icons = {
            'P0': 'mdi:water-minus',
            'P1': 'mdi:water-plus', 
            'P2': 'mdi:water-check',
            'P3': 'mdi:water-alert'
        }
        return phase_icons.get(phase, 'mdi:water')

    async def _add_ml_training_sample(self, decision: Dict, irrigation_result: Dict):
        """Add irrigation result to ML training data."""
        try:
            if irrigation_result['status'] != 'completed':
                return
            
            # Prepare features (simplified)
            features = {
                'current_vwc': irrigation_result.get('pre_vwc', 50),
                'irrigation_efficiency': irrigation_result.get('efficiency', 0.5),
                'duration': irrigation_result.get('duration_actual', 30),
                'decision_confidence': decision.get('confidence', 0.5)
            }
            
            # Prepare outcome
            outcome = {
                'irrigation_efficiency': irrigation_result.get('efficiency', 0.5),
                'vwc_improvement': irrigation_result.get('vwc_improvement', 0),
                'optimal_timing_score': 0.8  # Would be calculated based on timing analysis
            }
            
            # Add training sample
            result = self.ml_predictor.add_training_sample(features, outcome)
            
            if result['status'] == 'retrained':
                performance = result['performance']['ensemble']['r2']
                self.log(f"🎓 ML models retrained - R² performance: {performance:.3f}")
            
        except Exception as e:
            self.log(f"❌ Error adding ML training sample: {e}", level='ERROR')

    async def _update_crop_profile_performance(self, irrigation_result: Dict):
        """Update crop profile with irrigation performance data."""
        try:
            if irrigation_result['status'] != 'completed':
                return
            
            # Prepare performance data
            performance_data = {
                'irrigation_efficiency': irrigation_result.get('efficiency', 0.5),
                'vwc_response': irrigation_result.get('vwc_improvement', 0),
                'target_achieved': irrigation_result.get('vwc_improvement', 0) > 3,  # 3% improvement considered success
                'water_used': irrigation_result.get('duration_actual', 30),
                'plant_response_score': min(irrigation_result.get('vwc_improvement', 0) / 10, 1.0)
            }
            
            # Update profile
            update_result = self.crop_profiles.update_performance(performance_data)
            
            if update_result.get('adaptations_applied', {}).get('status') == 'adaptations_applied':
                self.log(f"🌱 Crop profile adapted based on performance feedback")
            
        except Exception as e:
            self.log(f"❌ Error updating crop profile performance: {e}", level='ERROR')

    async def _update_ml_predictions(self, kwargs):
        """Update ML predictions and system recommendations."""
        try:
            current_state = await self._get_current_system_state()
            if not current_state:
                return
            
            predictions = await self._get_ml_irrigation_predictions(current_state)
            
            if predictions:
                # Update HA entities with predictions
                analysis = predictions.get('analysis', {})
                
                self.set_state('sensor.crop_steering_ml_irrigation_need',
                              state=analysis.get('max_irrigation_need', 0),
                              attributes=predictions)
                
                self.set_state('sensor.crop_steering_ml_confidence',
                              state=predictions.get('model_confidence', 0))
                
                # Log significant predictions
                urgency = analysis.get('irrigation_urgency', 'moderate')
                if urgency in ['high', 'critical']:
                    max_need = analysis.get('max_irrigation_need', 0)
                    self.log(f"🤖 ML Alert: {urgency} irrigation need ({max_need:.1%})")
            
        except Exception as e:
            self.log(f"❌ Error updating ML predictions: {e}", level='ERROR')

    async def _monitor_sensor_health(self, kwargs):
        """Monitor sensor health and performance."""
        try:
            health_report = self.sensor_fusion.get_sensor_health_report()
            
            # Update HA entities
            self.set_state('sensor.crop_steering_sensor_health',
                          state=health_report['healthy_sensors'],
                          attributes=health_report)
            
            # Alert on issues
            faulty_sensors = health_report['faulty_sensors']
            offline_sensors = health_report['offline_sensors']
            
            if faulty_sensors > 0 or offline_sensors > 0:
                self.log(f"⚠️ Sensor issues: {faulty_sensors} faulty, {offline_sensors} offline", level='WARNING')
            
            # Update individual sensor entities
            for sensor_id, sensor_data in health_report['sensors'].items():
                entity_id = f"sensor.{sensor_id.replace('.', '_')}_health"
                self.set_state(entity_id,
                              state=sensor_data['health_status'],
                              attributes=sensor_data)
            
        except Exception as e:
            self.log(f"❌ Error monitoring sensor health: {e}", level='ERROR')

    async def _update_performance_analytics(self, kwargs):
        """Update system performance analytics."""
        try:
            # Calculate system performance metrics
            metrics = {
                'ml_model_accuracy': 0.0,
                'sensor_fusion_confidence': 0.0,
                'dryback_detection_accuracy': 0.0,
                'irrigation_efficiency': 0.0,
                'system_uptime': 1.0
            }
            
            # ML model performance
            ml_status = self.ml_predictor.get_model_status()
            if ml_status.get('trained', False):
                metrics['ml_model_accuracy'] = ml_status.get('model_accuracy', 0.0)
            
            # Sensor fusion performance
            health_report = self.sensor_fusion.get_sensor_health_report()
            if health_report['total_sensors'] > 0:
                metrics['sensor_fusion_confidence'] = health_report['healthy_sensors'] / health_report['total_sensors']
            
            # Dryback detection
            dryback_status = self._get_latest_dryback_status()
            if dryback_status:
                metrics['dryback_detection_accuracy'] = dryback_status.get('confidence_score', 0)
            
            # Update HA entities
            for metric_name, value in metrics.items():
                entity_id = f'sensor.crop_steering_{metric_name}'
                self.set_state(entity_id, state=value, 
                              attributes={'last_updated': datetime.now().isoformat()})
            
            self.log(f"📊 Performance updated - ML: {metrics['ml_model_accuracy']:.2f}, "
                    f"Sensors: {metrics['sensor_fusion_confidence']:.2f}")
            
        except Exception as e:
            self.log(f"❌ Error updating performance analytics: {e}", level='ERROR')

    def _update_dryback_entities(self, dryback_result: Dict):
        """Update Home Assistant entities with dryback data."""
        try:
            self.set_state('sensor.crop_steering_dryback_percentage',
                          state=dryback_result['dryback_percentage'],
                          attributes=dryback_result)
            
            self.set_state('binary_sensor.crop_steering_dryback_in_progress',
                          state='on' if dryback_result['dryback_in_progress'] else 'off',
                          attributes={'confidence': dryback_result['confidence_score']})
            
        except Exception as e:
            self.log(f"❌ Error updating dryback entities: {e}", level='ERROR')

    def _update_sensor_fusion_entities(self, sensor_id: str, fusion_result: Dict):
        """Update sensor fusion entities."""
        try:
            # Update individual sensor status
            entity_base = sensor_id.replace('.', '_')
            
            self.set_state(f'sensor.{entity_base}_reliability',
                          state=fusion_result['sensor_reliability'],
                          attributes={'health': fusion_result['sensor_health'],
                                    'outlier_rate': fusion_result['outlier_rate']})
            
            # Update fused values if this was the latest update
            if fusion_result['fused_value'] is not None:
                sensor_type = 'vwc' if 'vwc' in sensor_id else 'ec'
                self.set_state(f'sensor.crop_steering_fused_{sensor_type}',
                              state=fusion_result['fused_value'],
                              attributes={'confidence': fusion_result['fusion_confidence'],
                                        'active_sensors': fusion_result['active_sensors']})
            
        except Exception as e:
            self.log(f"❌ Error updating sensor fusion entities: {e}", level='ERROR')

    async def _update_decision_tracking(self, current_state: Dict, decision: Dict):
        """Update decision tracking and system state entities."""
        try:
            # Update current decision entity
            self.set_state('sensor.crop_steering_current_decision',
                          state=decision['action'],
                          attributes={
                              'reason': decision['reason'],
                              'confidence': decision['confidence'],
                              'factors': decision.get('factors', []),
                              'timestamp': datetime.now().isoformat()
                          })
            
            # Update system state entity
            self.set_state('sensor.crop_steering_system_state',
                          state='active' if self.system_enabled else 'disabled',
                          attributes={
                              'zone_phases': self.zone_phases.copy(),
                              'irrigation_in_progress': self.irrigation_in_progress,
                              'time_since_last_irrigation': self._get_time_since_last_irrigation(),
                              'average_vwc': current_state['average_vwc'],
                              'average_ec': current_state['average_ec']
                          })
            
            # Create dedicated sensors for integration compatibility
            # Create a summary of all zone phases
            phase_summary = ", ".join([f"Z{z}:{p}" for z, p in self.zone_phases.items()])
            self.set_state('sensor.crop_steering_app_current_phase',
                          state=phase_summary,
                          attributes={
                              'friendly_name': 'Zone Phases',
                              'icon': 'mdi:water-circle',
                              'zone_phases': self.zone_phases.copy(),
                              'updated': datetime.now().isoformat()
                          })
            
            # Calculate and set next irrigation time
            next_irrigation = self._calculate_next_irrigation_time()
            if next_irrigation:
                self.set_state('sensor.crop_steering_app_next_irrigation',
                              state=next_irrigation.isoformat(),
                              attributes={
                                  'friendly_name': 'Next Irrigation Time',
                                  'icon': 'mdi:clock-outline',
                                  'device_class': 'timestamp',
                                  'updated': datetime.now().isoformat()
                              })
            else:
                self.set_state('sensor.crop_steering_app_next_irrigation',
                              state='unknown',
                              attributes={
                                  'friendly_name': 'Next Irrigation Time',
                                  'icon': 'mdi:clock-outline',
                                  'device_class': 'timestamp',
                                  'updated': datetime.now().isoformat()
                              })
            
        except Exception as e:
            self.log(f"❌ Error updating decision tracking: {e}", level='ERROR')

    async def _update_phase_parameters(self):
        """Update system parameters when phase changes."""
        try:
            current_params = self.crop_profiles.get_current_parameters()
            if current_params:
                # Update HA entities with current phase parameters
                phase_params = {
                    'vwc_target_min': current_params.get('vwc_target_min', 50),
                    'vwc_target_max': current_params.get('vwc_target_max', 70),
                    'dryback_target': current_params.get('dryback_target', 15),
                    'ec_baseline': current_params.get('ec_baseline', 3.0)
                }
                
                for param, value in phase_params.items():
                    entity_id = f'sensor.crop_steering_{param}'
                    self.set_state(entity_id, state=value)
                
                self.log(f"📊 Phase parameters updated for zones: {list(self.zone_phases.values())}")
            
        except Exception as e:
            self.log(f"❌ Error updating phase parameters: {e}", level='ERROR')

    async def _update_system_for_new_profile(self):
        """Update system when crop profile changes."""
        try:
            # Reload parameters
            await self._update_phase_parameters()
            
            # Reset ML models if significant profile change
            # (This is optional - you might want to preserve learning)
            # self.ml_predictor.reset_models()
            
            self.log("🌱 System updated for new crop profile")
            
        except Exception as e:
            self.log(f"❌ Error updating system for new profile: {e}", level='ERROR')

    def get_system_status(self) -> Dict:
        """Get comprehensive system status."""
        try:
            return {
                'system_enabled': self.system_enabled,
                'zone_phases': self.zone_phases.copy(),
                'irrigation_in_progress': self.irrigation_in_progress,
                'last_irrigation': self.last_irrigation_time.isoformat() if self.last_irrigation_time else None,
                'modules': {
                    'dryback_detector': bool(self.dryback_detector),
                    'sensor_fusion': bool(self.sensor_fusion),
                    'ml_predictor': bool(self.ml_predictor),
                    'crop_profiles': bool(self.crop_profiles)
                },
                'ml_status': self.ml_predictor.get_model_status() if self.ml_predictor else {},
                'sensor_health': self.sensor_fusion.get_sensor_health_report() if self.sensor_fusion else {},
                'active_crop_profile': self.crop_profiles.current_profile if self.crop_profiles else None
            }
        except Exception as e:
            self.log(f"❌ Error getting system status: {e}", level='ERROR')
            return {'error': str(e)}

    def terminate(self):
        """Clean shutdown of master application."""
        try:
            # Emergency stop irrigation - sync version for shutdown
            try:
                pump_entity = self.config['hardware']['pump_master']
                main_line_entity = self.config['hardware']['main_line']
                
                # Turn off hardware synchronously during shutdown
                self.turn_off(pump_entity)
                self.turn_off(main_line_entity)
                
                for zone_valve in self.config['hardware']['zone_valves'].values():
                    self.turn_off(zone_valve)
                    
                self.log("🛑 Emergency stop executed during shutdown")
                    
            except Exception as stop_error:
                self.log(f"⚠️ Could not emergency stop during shutdown: {stop_error}")
            
            self.log("🛑 Master Crop Steering Application terminated")
            
        except Exception as e:
            self.log(f"❌ Error during termination: {e}", level='ERROR')