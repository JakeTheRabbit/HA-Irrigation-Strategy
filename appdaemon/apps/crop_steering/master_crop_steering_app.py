"""
Master Crop Steering Application with Advanced AI Features
Coordinates all advanced modules: dryback detection, sensor fusion, ML prediction, crop profiles, and dashboard
"""

# Removed - now inheriting from BaseAsyncApp which provides all needed functionality
import json
import logging
import asyncio
import threading
import os
import pickle
import statistics
import math
from datetime import datetime, timedelta, time
from typing import Dict, List, Optional, Any

# Import our advanced modules with fallback
try:
    from .advanced_dryback_detection import AdvancedDrybackDetector
    from .intelligent_sensor_fusion import IntelligentSensorFusion
    from .ml_irrigation_predictor import SimplifiedIrrigationPredictor
    from .intelligent_crop_profiles import IntelligentCropProfiles
    from .base_async_app import BaseAsyncApp
    from .phase_state_machine import ZoneStateMachine, IrrigationPhase, PhaseTransition
except ImportError:
    # Fallback for direct execution or import issues
    from advanced_dryback_detection import AdvancedDrybackDetector
    from intelligent_sensor_fusion import IntelligentSensorFusion
    from ml_irrigation_predictor import SimplifiedIrrigationPredictor
    from intelligent_crop_profiles import IntelligentCropProfiles
    from base_async_app import BaseAsyncApp
    from phase_state_machine import ZoneStateMachine, IrrigationPhase, PhaseTransition

_LOGGER = logging.getLogger(__name__)


class MasterCropSteeringApp(BaseAsyncApp):
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
    
    @property
    def zone_phases(self) -> Dict[int, str]:
        """Backward compatibility property for zone phases"""
        return {zone_id: machine.get_phase_string() 
                for zone_id, machine in self.zone_state_machines.items()}
    
    @property
    def zone_phase_data(self) -> Dict[int, Dict]:
        """Backward compatibility property for zone phase data"""
        result = {}
        for zone_id, machine in self.zone_state_machines.items():
            state = machine.state
            phase_data = state.get_current_phase_data()
            
            # Convert to legacy format
            legacy_data = {
                'last_irrigation_time': None,
                'p0_start_time': None,
                'p0_peak_vwc': None,
                'p1_start_time': None,
                'p1_shot_count': 0,
                'p1_current_shot_size': None,
                'p1_last_shot_time': None,
                'p1_vwc_at_start': None,
                'p1_shot_history': []
            }
            
            # Map current phase data to legacy format
            if state.current_phase == IrrigationPhase.P0_MORNING_DRYBACK and state.p0_data:
                legacy_data['p0_start_time'] = state.p0_data.entry_time
                legacy_data['p0_peak_vwc'] = state.p0_data.peak_vwc
            elif state.current_phase == IrrigationPhase.P1_RAMP_UP and state.p1_data:
                legacy_data['p1_start_time'] = state.p1_data.entry_time
                legacy_data['p1_shot_count'] = state.p1_data.shot_count
                legacy_data['p1_current_shot_size'] = state.p1_data.current_shot_size
                legacy_data['p1_vwc_at_start'] = state.p1_data.vwc_at_start
                legacy_data['p1_shot_history'] = [(s['timestamp'], s['size'], s['vwc_before'], s['vwc_after']) 
                                                 for s in state.p1_data.shot_history]
                if state.p1_data.shot_history:
                    legacy_data['p1_last_shot_time'] = state.p1_data.shot_history[-1]['timestamp']
            elif state.current_phase == IrrigationPhase.P2_MAINTENANCE and state.p2_data:
                legacy_data['last_irrigation_time'] = state.p2_data.last_irrigation_time
            
            result[zone_id] = legacy_data
        
        return result

    def initialize(self):
        """Initialize the master crop steering application."""
        # Initialize parent class for async-safe entity access
        super().initialize()
        
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
        
        # Per-zone state machines
        self.zone_state_machines = {}  # {zone_num: ZoneStateMachine}
        
        # Legacy compatibility - provide zone_phases property
        self._zone_phases_compat = {}  # For backward compatibility
        
        # Initialize per-zone tracking
        self.zone_profiles = {}     # Zone-specific crop profiles
        self.zone_schedules = {}    # Zone-specific light schedules
        self.emergency_attempts = {}  # Track emergency irrigation attempts per zone
        self.manual_overrides = {}  # Track manual override timeouts per zone
        self.zone_water_usage = {}  # Track water usage per zone
        
        for zone_num in range(1, self.num_zones + 1):
            # Create state machine for each zone
            state_machine = ZoneStateMachine(
                zone_id=zone_num,
                initial_phase=IrrigationPhase.P2_MAINTENANCE,  # Default to maintenance
                logger=self
            )
            
            # Register phase callbacks
            self._register_phase_callbacks(zone_num, state_machine)
            
            self.zone_state_machines[zone_num] = state_machine
            # Initialize emergency attempt tracking
            self.emergency_attempts[zone_num] = {
                'attempts': [],  # List of (timestamp, vwc_before, vwc_after)
                'abandoned_until': None  # Timestamp when abandonment expires
            }
            # Initialize manual override tracking
            self.manual_overrides[zone_num] = {
                'timeout_handle': None,  # Timer handle for auto-disable
                'enabled_time': None,  # When override was enabled
                'timeout_minutes': None  # Timeout duration
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
        """Load system configuration from AppDaemon args."""
        try:
            # Build configuration with values from apps.yaml or fallbacks
            config = {
                'hardware': self.args.get('hardware', {}),
                'sensors': self.args.get('sensors', {}),
                'timing': self.args.get('timing', {}),
                'thresholds': self.args.get('thresholds', {}),
                'notification_service': self.args.get('notification_service', 'notify.persistent_notification')
            }
            
            self.log(f"Configuration loaded from apps.yaml")
            return config
            
        except Exception as e:
            self.log(f"Error loading configuration from apps.yaml: {e}", level="ERROR")
            # Fallback to empty config
            return {
                'hardware': {},
                'sensors': {},
                'timing': {},
                'thresholds': {},
                'notification_service': 'notify.persistent_notification'
            }

    def _register_phase_callbacks(self, zone_num: int, state_machine: ZoneStateMachine):
        """Register callbacks for phase transitions and state changes."""
        
        # P0 Entry - Start morning dryback
        state_machine.register_on_enter(
            IrrigationPhase.P0_MORNING_DRYBACK,
            lambda **kwargs: self._on_enter_p0(zone_num)
        )
        
        # P1 Entry - Start ramp-up
        state_machine.register_on_enter(
            IrrigationPhase.P1_RAMP_UP,
            lambda **kwargs: self._on_enter_p1(zone_num)
        )
        
        # P2 Entry - Start maintenance
        state_machine.register_on_enter(
            IrrigationPhase.P2_MAINTENANCE,
            lambda **kwargs: self._on_enter_p2(zone_num)
        )
        
        # P3 Entry - Start pre-lights-off
        state_machine.register_on_enter(
            IrrigationPhase.P3_PRE_LIGHTS_OFF,
            lambda **kwargs: self._on_enter_p3(zone_num)
        )
        
        # P0 Exit - Clean up dryback data
        state_machine.register_on_exit(
            IrrigationPhase.P0_MORNING_DRYBACK,
            lambda **kwargs: self.log(f"Zone {zone_num}: Exiting P0 dryback phase")
        )
        
        # P1 Exit - Log ramp-up summary
        state_machine.register_on_exit(
            IrrigationPhase.P1_RAMP_UP,
            lambda **kwargs: self._on_exit_p1(zone_num)
        )
    
    def _on_enter_p0(self, zone_num: int):
        """Handle P0 phase entry."""
        self.log(f"Zone {zone_num}: Entering P0 Morning Dryback phase")
        # Record current VWC as peak
        current_vwc = self._get_zone_average_vwc(zone_num)
        if current_vwc and self.zone_state_machines[zone_num].state.p0_data:
            self.zone_state_machines[zone_num].state.p0_data.peak_vwc = current_vwc
    
    def _on_enter_p1(self, zone_num: int):
        """Handle P1 phase entry."""
        self.log(f"Zone {zone_num}: Entering P1 Ramp-Up phase")
        # Record starting VWC
        current_vwc = self._get_zone_average_vwc(zone_num)
        self.zone_state_machines[zone_num].update_p1_progress(current_vwc)
    
    def _on_enter_p2(self, zone_num: int):
        """Handle P2 phase entry."""
        self.log(f"Zone {zone_num}: Entering P2 Maintenance phase")
    
    def _on_enter_p3(self, zone_num: int):
        """Handle P3 phase entry."""
        self.log(f"Zone {zone_num}: Entering P3 Pre-Lights-Off phase")
    
    def _on_exit_p1(self, zone_num: int):
        """Handle P1 phase exit."""
        machine = self.zone_state_machines[zone_num]
        if machine.state.p1_data:
            self.log(f"Zone {zone_num}: P1 Summary - {machine.state.p1_data.shot_count} shots administered")

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
        
        # Listen to manual irrigation shot service calls
        self.listen_event(self._on_manual_irrigation_shot, 'crop_steering_irrigation_shot')
        
        # Listen to manual override events
        self.listen_event(self._on_manual_override_event, 'crop_steering_manual_override')

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
        
        # Comprehensive analytics system
        self.run_every(
            self._update_analytics_system,
            'now+25',
            120  # Every 2 minutes for detailed analytics
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
            current_crop = self.get_entity_value('select.crop_steering_crop_type', default='Cannabis_Athena')
            current_stage = self.get_entity_value('select.crop_steering_growth_stage', default='vegetative')
            
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
            state = self.get_entity_value(group_entity)
            return state if state and state != 'unknown' else 'Ungrouped'
        except Exception:
            return 'Ungrouped'
    
    def _get_zone_priority(self, zone_num: int) -> str:
        """Get the priority level for a zone."""
        try:
            priority_entity = f"select.crop_steering_zone_{zone_num}_priority"
            state = self.get_entity_value(priority_entity)
            return state if state and state != 'unknown' else 'Normal'
        except Exception:
            return 'Normal'
    
    def _get_zone_profile(self, zone_num: int) -> str:
        """Get the crop profile for a zone."""
        try:
            profile_entity = f"select.crop_steering_zone_{zone_num}_crop_profile"
            state = self.get_entity_value(profile_entity)
            if state and state != 'unknown' and state != 'Follow Main':
                return state
            # Fall back to main profile
            return self.get_entity_value('select.crop_steering_crop_type', default='Cannabis_Athena')
        except Exception:
            return 'Cannabis_Athena'
    
    def _get_zone_schedule(self, zone_num: int) -> Dict[str, time]:
        """Get the light schedule - SYSTEM-WIDE not per-zone (zones share same lights)."""
        try:
            # All zones use the same system-wide light schedule
            # Get system-wide light hours from number entities
            on_hour = int(self._get_number_entity_value("number.crop_steering_lights_on_hour", 12))
            off_hour = int(self._get_number_entity_value("number.crop_steering_lights_off_hour", 0))
            return {'lights_on': time(on_hour, 0), 'lights_off': time(off_hour, 0)}
        except Exception as e:
            self.log(f"❌ Error getting system light schedule: {e}", level='ERROR')
            return {'lights_on': time(12, 0), 'lights_off': time(0, 0)}

    async def _async_set_entity_wrapper(self, kwargs):
        """Async wrapper for set_entity_value calls."""
        try:
            entity_id = kwargs.get('entity_id')
            value = kwargs.get('value')
            attributes = kwargs.get('attributes', {})
            
            await self.async_set_entity_value(entity_id, value, attributes=attributes)
        except Exception as e:
            self.log(f"❌ Error in async entity wrapper: {e}", level='ERROR')

    async def _create_initial_sensors(self, kwargs):
        """Create initial sensors for HA integration compatibility."""
        try:
            # Create zone phase summary
            phase_summary = ", ".join([f"Z{z}:{p}" for z, p in self.zone_phases.items()])
            await self.async_set_entity_value('sensor.crop_steering_app_current_phase',
                               phase_summary,
                               attributes={
                                   'friendly_name': 'Zone Phases',
                                   'icon': 'mdi:water-circle',
                                   'zone_phases': {str(k): str(v) for k, v in self.zone_phases.items()},
                                   'updated': datetime.now().isoformat()
                               })
            
            # Create next irrigation time sensor
            next_irrigation = self._calculate_next_irrigation_time()
            if next_irrigation:
                await self.async_set_entity_value('sensor.crop_steering_app_next_irrigation',
                                   next_irrigation.isoformat(),
                                   attributes={
                                       'friendly_name': 'Next Irrigation Time',
                                       'icon': 'mdi:clock-outline',
                                       'device_class': 'timestamp',
                                       'updated': datetime.now().isoformat()
                                   })
            else:
                await self.async_set_entity_value('sensor.crop_steering_app_next_irrigation',
                                   'unknown',
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
                await self.async_set_entity_value(f'sensor.crop_steering_zone_{zone_num}_phase',
                                   phase,
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
            # Calculate water volume used: num_plants * drippers_per_plant * dripper_flow_rate * hours
            dripper_flow_rate = self._get_number_entity_value("number.crop_steering_dripper_flow_rate", 1.2)  # L/hour per dripper
            drippers_per_plant = self._get_number_entity_value("number.crop_steering_drippers_per_plant", 2)
            num_plants = self._get_number_entity_value(f"number.crop_steering_zone_{zone_num}_plant_count", 4)
            shot_multiplier = self._get_number_entity_value(f"number.crop_steering_zone_{zone_num}_shot_size_multiplier", 1.0)
            
            # Calculate volume: (plants * drippers_per_plant * flow_rate_per_dripper * hours * multiplier)
            hours = duration_seconds / 3600
            volume_liters = num_plants * drippers_per_plant * dripper_flow_rate * hours * shot_multiplier
            
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
            await self.async_set_entity_value(f'sensor.crop_steering_zone_{zone_num}_daily_water_app',
                               round(zone_data.get('daily_total', 0), 2),
                               attributes={
                                   'friendly_name': f'Zone {zone_num} Daily Water',
                                   'unit_of_measurement': 'L',
                                   'icon': 'mdi:water',
                                   'device_class': 'volume',
                                   'state_class': 'total_increasing',
                                   'last_reset': str(zone_data.get('last_reset_daily', datetime.now().date()))
                               })
            
            # Weekly water usage
            await self.async_set_entity_value(f'sensor.crop_steering_zone_{zone_num}_weekly_water_app',
                               round(zone_data.get('weekly_total', 0), 2),
                               attributes={
                                   'friendly_name': f'Zone {zone_num} Weekly Water',
                                   'unit_of_measurement': 'L',
                                   'icon': 'mdi:water-outline',
                                   'device_class': 'volume',
                                   'state_class': 'total_increasing',
                                   'last_reset': str(zone_data.get('last_reset_weekly', datetime.now().date()))
                               })
            
            # Irrigation count today
            await self.async_set_entity_value(f'sensor.crop_steering_zone_{zone_num}_irrigation_count_app',
                               zone_data.get('daily_count', 0),
                               attributes={
                                   'friendly_name': f'Zone {zone_num} Irrigations Today',
                                   'icon': 'mdi:counter',
                                   'state_class': 'total_increasing',
                                   'last_reset': str(zone_data.get('last_reset_daily', datetime.now().date()))
                               })
            
            # Last irrigation time
            last_irrigation = self.zone_phase_data.get(zone_num, {}).get('last_irrigation_time')
            if last_irrigation:
                await self.async_set_entity_value(f'sensor.crop_steering_zone_{zone_num}_last_irrigation_app',
                                   last_irrigation.isoformat(),
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
                phase = self.get_entity_value(sensor_id)
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
                
                self.log(f"🔧 Zone {zone_num}: Time {current_time}, Lights ON: {zone_schedule['lights_on']}-{zone_schedule['lights_off']}, Currently: {'ON' if lights_on else 'OFF'}, Phase: {zone_phase}")
                
                # If lights are on but zone isn't in P0, start P0 (morning dryback)
                if lights_on and zone_phase not in ['P0', 'P1', 'P2', 'P3']:
                    self.log(f"🔧 Zone {zone_num}: Lights on but phase is {zone_phase}, starting P0 morning dryback")
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
                
                # If lights are OFF, zone should be in P3 (waiting period before lights on)
                elif not lights_on and zone_phase not in ['P3']:
                    self.log(f"🔧 Zone {zone_num}: Lights off but phase is {zone_phase}, correcting to P3 (waiting)")
                    self.zone_phases[zone_num] = 'P3'
            
            # Update sensors after phase corrections
            self._update_phase_sensors()
            
            self.log("✅ State validation complete")
            
        except Exception as e:
            self.log(f"❌ Error validating state: {e}", level='ERROR')

    def _update_phase_sensors(self):
        """Update phase sensors after phase changes."""
        try:
            # Update the main phase summary sensor
            phase_summary = ", ".join([f"Z{z}:{p}" for z, p in self.zone_phases.items()])
            self.set_entity_value('sensor.crop_steering_app_current_phase',
                          phase_summary,
                          attributes={
                              'friendly_name': 'Zone Phases',
                              'icon': 'mdi:water-circle',
                              'zone_phases': {str(k): str(v) for k, v in self.zone_phases.items()},
                              'updated': datetime.now().isoformat()
                          })
            
            # Update individual zone phase sensors
            for zone_num, phase in self.zone_phases.items():
                self.run_in(self._async_set_entity_wrapper, 0, 
                           entity_id=f'sensor.crop_steering_zone_{zone_num}_phase',
                           value=phase,
                           attributes={
                               'friendly_name': f'Zone {zone_num} Phase',
                               'icon': 'mdi:state-machine',
                               'updated': datetime.now().isoformat()
                           })
            
            self.log(f"📊 Updated phase sensors: {phase_summary}")
            
        except Exception as e:
            self.log(f"❌ Error updating phase sensors: {e}", level='ERROR')

    def _on_vwc_sensor_update(self, entity, attribute, old, new, kwargs):
        """Handle VWC sensor updates with advanced processing."""
        try:
            if new in ['unavailable', 'unknown', None]:
                return
            
            with self.lock:
                vwc_value = float(new)
                timestamp = datetime.now()
                
                # Process VWC sensor through fusion system
                fusion_result = self.sensor_fusion.add_sensor_reading(
                    sensor_id=entity,
                    value=vwc_value,
                    timestamp=timestamp,
                    sensor_type='vwc'  # Explicitly mark as VWC sensor
                )
                
                # Add to dryback detector (use direct value)
                dryback_result = self.dryback_detector.add_vwc_reading(
                    vwc_value, timestamp
                )
                
                # Update HA entities with dryback data
                self._update_dryback_entities(dryback_result)
                
                # Update fusion entities
                self._update_sensor_fusion_entities(entity, fusion_result)
                
                # Use fusion result for emergency check
                self.log(f"🔍 DEBUG Emergency check: fusion={fusion_result['fused_value']:.1f}%")
                # Schedule async emergency check
                self.run_in(self._run_emergency_check, 0, vwc_value=fusion_result['fused_value'])
                
                # Log significant changes
                if fusion_result['is_outlier']:
                    self.log(f"⚠️ VWC outlier detected: {entity} = {vwc_value}%")
                
        except Exception as e:
            self.log(f"❌ Error processing VWC update: {e}", level='ERROR')

    async def _run_emergency_check(self, kwargs):
        """Helper method to run emergency check asynchronously."""
        try:
            vwc_value = kwargs.get('vwc_value', 50.0)
            await self._check_emergency_conditions(vwc_value)
        except Exception as e:
            self.log(f"❌ Error in emergency check: {e}", level='ERROR')

    async def _run_critical_ec_check(self, kwargs):
        """Helper method to run critical EC check asynchronously."""
        try:
            ec_value = kwargs.get('ec_value', 3.0)
            await self._handle_critical_ec(ec_value)
        except Exception as e:
            self.log(f"❌ Error in critical EC check: {e}", level='ERROR')

    def _on_ec_sensor_update(self, entity, attribute, old, new, kwargs):
        """Handle EC sensor updates with advanced processing."""
        try:
            if new in ['unavailable', 'unknown', None]:
                return
            
            with self.lock:
                ec_value = float(new)
                timestamp = datetime.now()
                
                # Process EC sensor through fusion system
                fusion_result = self.sensor_fusion.add_sensor_reading(
                    sensor_id=entity,
                    value=ec_value,
                    timestamp=timestamp,
                    sensor_type='ec'  # Explicitly mark as EC sensor
                )
                
                # Update fusion entities
                self._update_sensor_fusion_entities(entity, fusion_result)
                
                # Check for critical EC levels (using direct value)
                if ec_value > self.config['thresholds']['critical_ec']:
                    self.log(f"🚨 Critical EC level detected: {ec_value:.2f} mS/cm", level='WARNING')
                    # Schedule async critical EC handling
                    self.run_in(self._run_critical_ec_check, 0, ec_value=ec_value)
                
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
            current_stage = self.get_entity_value('select.crop_steering_growth_stage', default='vegetative')
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
                # Check phase transitions for all zones
                await self._check_all_zone_phase_transitions()
                
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
                    value = self.get_entity_value(sensor)
                    # Handle async Task objects properly
                    if hasattr(value, '__await__'):
                        self.log(f"⚠️ Skipping async task from VWC sensor {sensor}")
                        continue
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
                    value = self.get_entity_value(sensor)
                    # Handle async Task objects properly
                    if hasattr(value, '__await__'):
                        self.log(f"⚠️ Skipping async task from EC sensor {sensor}")
                        continue
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
                temp_state = self.get_entity_value(self.config['sensors']['environmental']['temperature'])
                temperature = float(temp_state) if temp_state not in ['unavailable', 'unknown', None] else 25.0
            except (ValueError, TypeError):
                temperature = 25.0
                
            try:
                hum_state = self.get_entity_value(self.config['sensors']['environmental']['humidity'])
                humidity = float(hum_state) if hum_state not in ['unavailable', 'unknown', None] else 60.0
            except (ValueError, TypeError):
                humidity = 60.0
                
            try:
                vpd_state = self.get_entity_value(self.config['sensors']['environmental']['vpd'])
                vpd = float(vpd_state) if vpd_state not in ['unavailable', 'unknown', None] else 1.0
            except (ValueError, TypeError):
                vpd = 1.0
            
            # Get fused values from sensor fusion system (properly separated by type)
            fused_vwc = self.sensor_fusion.get_fused_vwc()
            fused_ec = self.sensor_fusion.get_fused_ec()
            
            # Fallback to simple average if fusion not available
            avg_vwc = fused_vwc if fused_vwc is not None else (statistics.mean(list(vwc_sensors.values())) if vwc_sensors else 0)
            avg_ec = fused_ec if fused_ec is not None else (statistics.mean(list(ec_sensors.values())) if ec_sensors else 3.0)
            
            self.log(f"DEBUG Fused values: VWC={avg_vwc:.2f}% (fusion: {fused_vwc}), EC={avg_ec:.2f} mS/cm (fusion: {fused_ec})")
            self.log(f"DEBUG Raw VWC values: {list(vwc_sensors.values())}")
            self.log(f"DEBUG Raw EC values: {list(ec_sensors.values())}")
            self.log(f"DEBUG Active VWC sensors: {self.sensor_fusion.get_sensor_count_by_type('vwc')}")
            self.log(f"DEBUG Active EC sensors: {self.sensor_fusion.get_sensor_count_by_type('ec')}")
            
            return {
                'vwc_sensors': vwc_sensors,
                'ec_sensors': ec_sensors,
                'average_vwc': avg_vwc,
                'average_ec': avg_ec,
                'temperature': temperature,
                'humidity': humidity,
                'vpd': vpd,
                'zone_phases': self.zone_phases.copy(),
                'lights_on': self.get_entity_value('sun.sun', attribute='elevation', default=0) > 0,
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
                'steering_mode': self.get_entity_value('select.crop_steering_steering_mode', default='Vegetative')
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
            if zone_profile != self.get_entity_value('select.crop_steering_crop_type'):
                # Load zone-specific profile
                zone_profile_params = self.crop_profiles.get_profile_parameters(zone_profile)
            else:
                zone_profile_params = profile_params
                
            if zone_phase == 'P0':  # Dryback phase - check for emergencies only
                decision = self._evaluate_zone_p0_needs(zone_num)
                if decision['needs_irrigation']:
                    zone_decisions[zone_num] = decision
                    zones_by_priority['Critical'].append(zone_num)  # P0 emergencies are always critical
                    if zone_group != 'Ungrouped':
                        groups_needing_water.setdefault(zone_group, []).append(zone_num)
                
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
        """Evaluate P1 progressive irrigation needs with EC-based logic."""
        target_vwc = self._get_number_entity_value("number.crop_steering_p1_target_vwc", 65)
        zone_vwc = self._get_zone_vwc(zone_num)
        zone_ec = self._get_zone_ec(zone_num)
        
        # Get growth stage for EC target selection
        growth_stage = self._get_select_entity_value("select.crop_steering_growth_stage", "Vegetative")
        
        # Get EC target for P1 based on growth stage
        if growth_stage.lower() == "vegetative":
            ec_target = self._get_number_entity_value("number.crop_steering_ec_target_veg_p1", 3.0)
        else:  # Generative
            ec_target = self._get_number_entity_value("number.crop_steering_ec_target_gen_p1", 5.0)
        
        # Get P1 progression parameters
        initial_shot_size = self._get_number_entity_value("number.crop_steering_p1_initial_shot_size", 2.0)
        shot_increment = self._get_number_entity_value("number.crop_steering_p1_shot_increment", 0.5)
        max_shot_size = self._get_number_entity_value("number.crop_steering_p1_max_shot_size", 10.0)
        min_shots = self._get_number_entity_value("number.crop_steering_p1_min_shots", 3.0)
        max_shots = self._get_number_entity_value("number.crop_steering_p1_max_shots", 6.0)
        time_between_shots = self._get_number_entity_value("number.crop_steering_p1_time_between_shots", 15.0)
        
        # Get current P1 progression data from state machine
        machine = self.zone_state_machines.get(zone_num)
        if not machine or machine.state.current_phase != IrrigationPhase.P1_RAMP_UP:
            return {'needs_irrigation': False, 'reason': 'Not in P1 phase'}
        
        p1_data = machine.state.p1_data
        if not p1_data:
            return {'needs_irrigation': False, 'reason': 'No P1 data'}
        
        current_shot_count = p1_data.shot_count
        last_shot_time = p1_data.shot_history[-1]['timestamp'] if p1_data.shot_history else None
        p1_start_time = p1_data.entry_time
        current_shot_size = p1_data.current_shot_size or initial_shot_size
        
        # Update P1 progress with current VWC if needed
        machine.update_p1_progress(zone_vwc)
        
        # Check if we need to continue P1 progression
        vwc_needs_irrigation = zone_vwc is not None and zone_vwc < target_vwc
        
        # Check timing - need to wait between shots
        now = datetime.now()
        time_since_last_shot = 0
        if last_shot_time:
            time_since_last_shot = (now - last_shot_time).total_seconds() / 60  # minutes
            
        # Check if we're still in timing cooldown
        if last_shot_time and time_since_last_shot < time_between_shots:
            remaining_wait = time_between_shots - time_since_last_shot
            return {
                'needs_irrigation': False,
                'vwc': zone_vwc,
                'ec': zone_ec,
                'ec_target': ec_target,
                'reason': f"P1 cooldown: {remaining_wait:.1f}min remaining (shot {current_shot_count}/{max_shots})",
                'p1_progression': {
                    'shot_count': current_shot_count,
                    'current_shot_size': current_shot_size,
                    'remaining_wait': remaining_wait
                }
            }
        
        # Check if we've reached target VWC
        if not vwc_needs_irrigation:
            if current_shot_count >= min_shots:
                # P1 successful - ready to transition to P2
                return {
                    'needs_irrigation': False,
                    'vwc': zone_vwc,
                    'ec': zone_ec,
                    'ec_target': ec_target,
                    'reason': f"P1 complete: VWC {zone_vwc:.1f}% reached target {target_vwc}% after {current_shot_count} shots",
                    'p1_complete': True,
                    'p1_progression': {
                        'shot_count': current_shot_count,
                        'success': True
                    }
                }
            else:
                # Haven't reached minimum shots yet, continue
                vwc_needs_irrigation = True
        
        # Check if we've exceeded maximum shots
        if current_shot_count >= max_shots:
            return {
                'needs_irrigation': False,
                'vwc': zone_vwc,
                'ec': zone_ec,
                'ec_target': ec_target,
                'reason': f"P1 max shots reached: {current_shot_count}/{max_shots} shots completed, VWC {zone_vwc:.1f}%",
                'p1_complete': True,
                'p1_progression': {
                    'shot_count': current_shot_count,
                    'success': False,
                    'reason': 'max_shots_reached'
                }
            }
        
        # Check EC conditions
        ec_irrigation_decision = self._evaluate_ec_irrigation_need(zone_ec, ec_target, "P1")
        
        # Determine if we need irrigation (VWC or EC driven)
        needs_irrigation = vwc_needs_irrigation or ec_irrigation_decision['needs_irrigation']
        
        if needs_irrigation:
            # Calculate progressive shot size
            progressive_shot_size = self._calculate_p1_progressive_shot_size(
                zone_num, initial_shot_size, shot_increment, max_shot_size, current_shot_count
            )
            
            # Apply EC adjustments to the progressive shot size
            final_shot_size = self._calculate_ec_adjusted_shot_size(
                progressive_shot_size, zone_ec, ec_target, ec_irrigation_decision
            )
            
            # Build reason string
            if vwc_needs_irrigation and ec_irrigation_decision['needs_irrigation']:
                reason = f"P1 shot {current_shot_count + 1}/{max_shots}: VWC {zone_vwc:.1f}% < {target_vwc}% + {ec_irrigation_decision['reason']}"
                confidence = 0.9
            elif vwc_needs_irrigation:
                reason = f"P1 shot {current_shot_count + 1}/{max_shots}: VWC {zone_vwc:.1f}% < {target_vwc}%"
                confidence = 0.8
            else:
                reason = f"P1 shot {current_shot_count + 1}/{max_shots}: {ec_irrigation_decision['reason']}"
                confidence = ec_irrigation_decision['confidence']
            
            return {
                'needs_irrigation': True,
                'vwc': zone_vwc,
                'ec': zone_ec,
                'threshold': target_vwc,
                'ec_target': ec_target,
                'shot_size': final_shot_size,
                'reason': reason,
                'confidence': confidence,
                'ec_decision': ec_irrigation_decision,
                'p1_progression': {
                    'shot_count': current_shot_count,
                    'next_shot': current_shot_count + 1,
                    'progressive_shot_size': progressive_shot_size,
                    'final_shot_size': final_shot_size,
                    'max_shots': max_shots
                }
            }
        
        return {
            'needs_irrigation': False, 
            'vwc': zone_vwc, 
            'ec': zone_ec,
            'ec_target': ec_target,
            'reason': f"P1 shot {current_shot_count}/{max_shots}: VWC stable at {zone_vwc:.1f}%"
        }

    def _evaluate_zone_p2_needs(self, zone_num: int, profile_params: Dict) -> Dict:
        """Evaluate if a specific zone in P2 needs irrigation with EC-based logic."""
        vwc_threshold = self._get_number_entity_value("number.crop_steering_p2_vwc_threshold", 60)
        zone_vwc = self._get_zone_vwc(zone_num)
        zone_ec = self._get_zone_ec(zone_num)
        
        # Get growth stage for EC target selection
        growth_stage = self._get_select_entity_value("select.crop_steering_growth_stage", "Vegetative")
        
        # Get EC target and thresholds for P2
        if growth_stage.lower() == "vegetative":
            ec_target = self._get_number_entity_value("number.crop_steering_ec_target_veg_p2", 3.2)
        else:  # Generative
            ec_target = self._get_number_entity_value("number.crop_steering_ec_target_gen_p2", 6.0)
        
        # Get P2 EC thresholds for ratio-based irrigation
        ec_high_threshold = self._get_number_entity_value("number.crop_steering_p2_ec_high_threshold", 1.2)
        ec_low_threshold = self._get_number_entity_value("number.crop_steering_p2_ec_low_threshold", 0.8)
        
        # Check VWC condition
        vwc_needs_irrigation = zone_vwc is not None and zone_vwc < vwc_threshold
        
        # Check EC conditions
        ec_irrigation_decision = self._evaluate_ec_irrigation_need(zone_ec, ec_target, "P2")
        
        # Check EC ratio conditions (P2 specific logic)
        ec_ratio_decision = self._evaluate_p2_ec_ratio_irrigation(
            zone_ec, ec_target, ec_high_threshold, ec_low_threshold
        )
        
        # Combined decision logic for P2
        needs_irrigation = vwc_needs_irrigation or ec_irrigation_decision['needs_irrigation'] or ec_ratio_decision['needs_irrigation']
        
        if needs_irrigation:
            # Calculate shot size with EC-based adjustments
            base_shot_size = self._get_number_entity_value("number.crop_steering_p2_shot_size", 5.0)
            
            # Use EC ratio decision if it's the primary driver
            if ec_ratio_decision['needs_irrigation']:
                ec_adjusted_shot_size = ec_ratio_decision['adjusted_shot_size']
                primary_reason = ec_ratio_decision['reason']
                confidence = ec_ratio_decision['confidence']
            else:
                ec_adjusted_shot_size = self._calculate_ec_adjusted_shot_size(
                    base_shot_size, zone_ec, ec_target, ec_irrigation_decision
                )
                
                # Determine primary reason
                if vwc_needs_irrigation and ec_irrigation_decision['needs_irrigation']:
                    primary_reason = f"P2: VWC {zone_vwc:.1f}% < {vwc_threshold}% + {ec_irrigation_decision['reason']}"
                    confidence = 0.8
                elif vwc_needs_irrigation:
                    primary_reason = f"P2: VWC {zone_vwc:.1f}% < {vwc_threshold}%"
                    confidence = 0.7
                else:
                    primary_reason = f"P2: {ec_irrigation_decision['reason']}"
                    confidence = ec_irrigation_decision['confidence']
            
            return {
                'needs_irrigation': True,
                'vwc': zone_vwc,
                'ec': zone_ec,
                'threshold': vwc_threshold,
                'ec_target': ec_target,
                'shot_size': ec_adjusted_shot_size,
                'reason': primary_reason,
                'confidence': confidence,
                'ec_decision': ec_irrigation_decision,
                'ec_ratio_decision': ec_ratio_decision
            }
        
        return {
            'needs_irrigation': False, 
            'vwc': zone_vwc, 
            'ec': zone_ec,
            'ec_target': ec_target
        }

    def _evaluate_zone_p3_needs(self, zone_num: int) -> Dict:
        """P3 is the final dryback period - NO irrigation unless true emergency."""
        zone_vwc = self._get_zone_vwc(zone_num)
        zone_ec = self._get_zone_ec(zone_num)
        
        # Get emergency threshold from entity
        emergency_threshold = self._get_number_entity_value("number.crop_steering_p3_emergency_vwc_threshold", 40)
        
        # Get growth stage for EC target selection
        growth_stage = self._get_select_entity_value("select.crop_steering_growth_stage", "Vegetative")
        
        # Get EC target for P3 based on growth stage
        if growth_stage.lower() == "vegetative":
            ec_target = self._get_number_entity_value("number.crop_steering_ec_target_veg_p3", 3.0)
        else:  # Generative
            ec_target = self._get_number_entity_value("number.crop_steering_ec_target_gen_p3", 4.5)
        
        # P3 should normally have NO irrigation - it's the dryback period
        # Only irrigate if there's a critical emergency (plant wilting risk)
        vwc_emergency = zone_vwc is not None and zone_vwc < emergency_threshold
        
        # Check for extreme EC conditions that require emergency intervention
        ec_emergency = False
        ec_emergency_reason = ""
        if zone_ec is not None:
            ec_ratio = zone_ec / ec_target if ec_target > 0 else 0
            # Only irrigate in P3 for extreme EC conditions
            if ec_ratio > 2.0:  # EC extremely high - plant stress risk
                ec_emergency = True
                ec_emergency_reason = f"Extreme EC: {zone_ec:.2f} vs {ec_target:.2f} target (ratio: {ec_ratio:.2f})"
        
        if vwc_emergency or ec_emergency:
            # This is a true emergency - plant health at risk
            shot_size = self._get_number_entity_value("number.crop_steering_p3_emergency_shot_size", 1.0)
            
            # Adjust shot size for EC emergency
            if ec_emergency and zone_ec is not None:
                # Larger shot for extreme EC dilution
                shot_size *= min(2.0, zone_ec / ec_target)  # Cap at 2x shot size
            
            reason = ""
            if vwc_emergency and ec_emergency:
                reason = f"P3 EMERGENCY: VWC {zone_vwc:.1f}% < {emergency_threshold}% + {ec_emergency_reason}"
            elif vwc_emergency:
                reason = f"P3 EMERGENCY: VWC {zone_vwc:.1f}% < {emergency_threshold}%"
            else:
                reason = f"P3 EMERGENCY: {ec_emergency_reason}"
            
            return {
                'needs_irrigation': True,
                'vwc': zone_vwc,
                'ec': zone_ec,
                'threshold': emergency_threshold,
                'ec_target': ec_target,
                'shot_size': shot_size,
                'reason': reason,
                'confidence': 1.0,
                'emergency': True
            }
        
        # Normal P3 operation - no irrigation, let it dry back
        return {
            'needs_irrigation': False, 
            'vwc': zone_vwc, 
            'ec': zone_ec,
            'ec_target': ec_target
        }

    def _evaluate_zone_p0_needs(self, zone_num: int) -> Dict:
        """P0 is dryback phase - NO irrigation during dryback period."""
        zone_vwc = self._get_zone_vwc(zone_num)
        zone_ec = self._get_zone_ec(zone_num)
        
        # Get growth stage for EC target selection
        growth_stage = self._get_select_entity_value("select.crop_steering_growth_stage", "Vegetative")
        
        # Get EC target for P0 based on growth stage
        if growth_stage.lower() == "vegetative":
            ec_target = self._get_number_entity_value("number.crop_steering_ec_target_veg_p0", 3.0)
        else:  # Generative
            ec_target = self._get_number_entity_value("number.crop_steering_ec_target_gen_p0", 4.0)
        
        # P0 is for dryback - typically NO irrigation allowed
        # Only exception: extreme EC emergencies that threaten plant health
        ec_emergency = False
        if zone_ec is not None:
            ec_ratio = zone_ec / ec_target if ec_target > 0 else 0
            # Only irrigate in P0 for extremely dangerous EC levels
            if ec_ratio > 2.5:  # EC dangerously high
                ec_emergency = True
        
        if ec_emergency:
            # Emergency flush needed even during dryback
            flush_target = self._get_number_entity_value("number.crop_steering_ec_target_flush", 0.8)
            flush_shot_size = 10.0  # Large flush shot
            
            return {
                'needs_irrigation': True,
                'vwc': zone_vwc,
                'ec': zone_ec,
                'ec_target': ec_target,
                'shot_size': flush_shot_size,
                'reason': f"P0 EMERGENCY FLUSH: EC {zone_ec:.2f} dangerously high vs {ec_target:.2f} target",
                'confidence': 1.0,
                'emergency': True,
                'flush': True
            }
        
        # Normal P0 operation - no irrigation during dryback
        return {
            'needs_irrigation': False, 
            'vwc': zone_vwc, 
            'ec': zone_ec,
            'ec_target': ec_target,
            'reason': 'P0 dryback phase - no irrigation'
        }

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
        """Select optimal irrigation zone based on priority, grouping, and sensor data."""
        try:
            # Get all configured zones
            configured_zones = list(self.config['hardware']['zone_valves'].keys())
            if not configured_zones:
                configured_zones = list(range(1, self.num_zones + 1))
            
            # Filter zones that are enabled and not blocked
            candidate_zones = []
            for zone in configured_zones:
                # Check if zone is enabled
                zone_enabled = self._get_switch_state(f"switch.crop_steering_zone_{zone}_enabled", True)
                if not zone_enabled:
                    continue
                
                # Check for conflicts (group conflicts, manual overrides, etc.)
                has_conflicts = await self._check_zone_conflicts(zone)
                if has_conflicts:
                    continue
                
                candidate_zones.append(zone)
            
            if not candidate_zones:
                self.log("⚠️ No zones available for irrigation (all blocked or disabled)")
                return None
            
            # Use priority-based selection with integrated VWC analysis
            selected_zone = self._select_next_zone_by_priority(candidate_zones)
            
            if selected_zone:
                zone_group = self._get_zone_group(selected_zone)
                zone_priority = self._get_zone_priority(selected_zone)
                zone_vwc = self._get_zone_vwc(selected_zone)
                
                self.log(f"🎯 Optimal zone selected: Zone {selected_zone} (Group: {zone_group}, Priority: {zone_priority}, VWC: {zone_vwc:.1f}%)")
                return selected_zone
            
            # Fallback to original VWC-based selection if priority selection fails
            self.log("⚠️ Priority selection failed, falling back to VWC-based selection")
            return await self._select_zone_by_vwc_fallback(candidate_zones)
            
        except Exception as e:
            self.log(f"❌ Error selecting optimal zone: {e}", level='ERROR')
            return None

    async def _select_zone_by_vwc_fallback(self, candidate_zones: List[int]) -> Optional[int]:
        """Fallback zone selection based purely on VWC sensor data."""
        try:
            zone_scores = {}
            
            for zone in candidate_zones:
                zone_vwc_sensors = [s for s in self.config['sensors']['vwc'] if f'r{zone}' in s or f'z{zone}' in s]
                
                if zone_vwc_sensors:
                    zone_vwc_values = []
                    for sensor in zone_vwc_sensors:
                        value = self.get_entity_value(sensor)
                        if value not in ['unavailable', 'unknown', None]:
                            # Ensure value is a string or number, not an async Task
                            if hasattr(value, '__await__'):
                                self.log(f"⚠️ Skipping async task from sensor {sensor}")
                                continue
                            zone_vwc_values.append(float(value))
                    
                    if zone_vwc_values:
                        avg_vwc = statistics.mean(zone_vwc_values)
                        vwc_std = statistics.stdev(zone_vwc_values) if len(zone_vwc_values) > 1 else 0
                        
                        # Score based on need (lower VWC = higher score) and reliability (lower std = higher score)
                        need_score = max(0, (70 - avg_vwc) / 70)  # Higher score for lower VWC
                        reliability_score = max(0, 1 - (vwc_std / 10))  # Higher score for lower variance
                        
                        zone_scores[zone] = need_score * 0.7 + reliability_score * 0.3
            
            if zone_scores:
                optimal_zone = max(zone_scores, key=zone_scores.get)
                self.log(f"🎯 Fallback zone selected: {optimal_zone} (VWC score: {zone_scores[optimal_zone]:.2f})")
                return optimal_zone
            
            return candidate_zones[0] if candidate_zones else None
            
        except Exception as e:
            self.log(f"❌ Error in VWC fallback selection: {e}", level='ERROR')
            return candidate_zones[0] if candidate_zones else None

    async def _execute_irrigation_shot(self, zone: int, duration: int, shot_type: str = 'manual') -> Dict:
        """Execute irrigation shot with proper sequencing and monitoring."""
        try:
            if self.irrigation_in_progress:
                self.log("⚠️ Irrigation already in progress - skipping")
                return {'status': 'skipped', 'reason': 'already_in_progress'}
            
            # MANUAL OVERRIDE CHECKS - Critical user control functionality
            # Zone-level manual override
            zone_manual_override = self._get_switch_state(f"switch.crop_steering_zone_{zone}_manual_override", False)
            if zone_manual_override:
                self.log(f"🛑 Zone {zone} irrigation blocked: Manual override active")
                return {
                    'status': 'blocked',
                    'reason': 'manual_override',
                    'zone': zone,
                    'message': f'Zone {zone} manual override is active - irrigation bypassed'
                }
            
            # System-level controls
            system_enabled = self._get_switch_state("switch.crop_steering_system_enabled", True)
            auto_irrigation_enabled = self._get_switch_state("switch.crop_steering_auto_irrigation_enabled", True)
            zone_enabled = self._get_switch_state(f"switch.crop_steering_zone_{zone}_enabled", True)
            
            if not system_enabled:
                self.log(f"🛑 Zone {zone} irrigation blocked: System disabled")
                return {
                    'status': 'blocked',
                    'reason': 'system_disabled',
                    'zone': zone,
                    'message': 'Crop steering system is disabled'
                }
            
            if not auto_irrigation_enabled and shot_type != 'manual':
                self.log(f"🛑 Zone {zone} irrigation blocked: Auto irrigation disabled")
                return {
                    'status': 'blocked',
                    'reason': 'auto_irrigation_disabled',
                    'zone': zone,
                    'message': 'Automatic irrigation is disabled'
                }
            
            if not zone_enabled:
                self.log(f"🛑 Zone {zone} irrigation blocked: Zone disabled")
                return {
                    'status': 'blocked',
                    'reason': 'zone_disabled',
                    'zone': zone,
                    'message': f'Zone {zone} is disabled'
                }
            
            # Tank filling conflict check
            tank_filling = self._get_switch_state("switch.tank_filling", False)
            if tank_filling:
                self.log(f"🛑 Zone {zone} irrigation blocked: Tank filling in progress")
                return {
                    'status': 'blocked',
                    'reason': 'tank_filling',
                    'zone': zone,
                    'message': 'Tank filling in progress - irrigation blocked to prevent conflicts'
                }
            
            # CRITICAL SAFETY CHECKS - HIGH PRIORITY 7
            safety_check = self._check_irrigation_safety_limits(zone, shot_type)
            if safety_check['blocked']:
                self.log(f"🚨 Zone {zone} irrigation blocked: {safety_check['reason']}")
                return {
                    'status': 'blocked',
                    'reason': safety_check['reason'],
                    'zone': zone,
                    'message': safety_check['message']
                }
            
            # All override checks passed - proceed with irrigation
            self.irrigation_in_progress = True
            start_time = datetime.now()
            
            # Record pre-irrigation VWC
            pre_vwc = self._get_zone_average_vwc(zone)
            
            # Hardware sequence: Pump -> Main Line -> Zone Valve
            # Check hardware configuration with error handling
            try:
                pump_entity = self.config['hardware']['pump_master']
                main_line_entity = self.config['hardware']['main_line']
                zone_entity = self.config['hardware']['zone_valves'][zone]
                
                # Validate entities exist and are not None/empty
                if not pump_entity or not main_line_entity or not zone_entity:
                    missing_entities = []
                    if not pump_entity:
                        missing_entities.append('pump_master')
                    if not main_line_entity:
                        missing_entities.append('main_line')
                    if not zone_entity:
                        missing_entities.append(f'zone_{zone}_valve')
                    
                    self.log(f"🚨 Hardware configuration error: Missing entities {missing_entities}", level="ERROR")
                    return {
                        'status': 'error',
                        'reason': 'hardware_configuration_missing',
                        'zone': zone,
                        'message': f'Hardware entities not configured: {missing_entities}. Please check crop_steering.env configuration.'
                    }
                    
            except KeyError as e:
                self.log(f"🚨 Hardware configuration error: Missing key {e}", level="ERROR")
                return {
                    'status': 'error',
                    'reason': 'hardware_configuration_incomplete',
                    'zone': zone,
                    'message': f'Hardware configuration incomplete: {e}. Please check crop_steering.env configuration.'
                }
            except Exception as e:
                self.log(f"🚨 Hardware configuration error: {e}", level="ERROR")
                return {
                    'status': 'error',
                    'reason': 'hardware_configuration_error',
                    'zone': zone,
                    'message': f'Hardware configuration error: {e}'
                }
            
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
            
            # Record P1 shot if in P1 phase
            machine = self.zone_state_machines.get(zone)
            if machine and machine.state.current_phase == IrrigationPhase.P1_RAMP_UP:
                # Calculate shot size as % of substrate volume
                shot_size = (duration / 60.0) * 2.0  # Rough estimate: 2% per minute
                machine.record_p1_shot(shot_size, pre_vwc or 0, post_vwc or 0)
            elif machine and machine.state.current_phase == IrrigationPhase.P2_MAINTENANCE:
                machine.record_p2_irrigation()
            elif machine and machine.state.current_phase == IrrigationPhase.P3_PRE_LIGHTS_OFF:
                machine.record_p3_emergency()
            
            # Update water usage tracking
            await self._update_zone_water_usage(zone, duration)
            
            # Save state after irrigation (critical event)
            self._save_persistent_state()
            
            # Fire irrigation event
            self.fire_event('crop_steering_irrigation_shot', **irrigation_result)
            
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
                value = self.get_entity_value(sensor)
                if value not in ['unavailable', 'unknown', None]:
                    vwc_values.append(float(value))
            
            return statistics.mean(vwc_values) if vwc_values else None
            
        except Exception as e:
            self.log(f"❌ Error getting zone VWC: {e}", level='ERROR')
            return None

    async def _emergency_stop(self):
        """Emergency stop all irrigation hardware."""
        try:
            hardware = self.config.get('hardware', {})
            
            # Safely turn off all zone valves
            zone_valves = hardware.get('zone_valves', {})
            for zone_id, zone_entity in zone_valves.items():
                if zone_entity:
                    try:
                        await self.call_service('switch/turn_off', entity_id=zone_entity)
                        self.log(f"🛑 Emergency stop: Zone {zone_id} valve {zone_entity} turned off")
                    except Exception as e:
                        self.log(f"⚠️ Emergency stop: Failed to turn off zone {zone_id} valve: {e}", level="WARNING")
            
            # Safely turn off main line
            main_line_entity = hardware.get('main_line')
            if main_line_entity:
                try:
                    await self.call_service('switch/turn_off', entity_id=main_line_entity)
                    self.log(f"🛑 Emergency stop: Main line {main_line_entity} turned off")
                except Exception as e:
                    self.log(f"⚠️ Emergency stop: Failed to turn off main line: {e}", level="WARNING")
            
            # Safely turn off pump
            pump_entity = hardware.get('pump_master')
            if pump_entity:
                try:
                    await self.call_service('switch/turn_off', entity_id=pump_entity)
                    self.log(f"🛑 Emergency stop: Pump {pump_entity} turned off")
                except Exception as e:
                    self.log(f"⚠️ Emergency stop: Failed to turn off pump: {e}", level="WARNING")
            
            self.irrigation_in_progress = False
            self.log("🛑 Emergency stop executed - all available irrigation hardware turned off")
            
        except Exception as e:
            self.log(f"❌ Error during emergency stop: {e}", level='ERROR')

    async def _check_emergency_conditions(self, fused_vwc: float):
        """Check for emergency irrigation conditions."""
        try:
            if fused_vwc and fused_vwc < self.config['thresholds']['emergency_vwc']:
                self.log(f"🚨 Emergency VWC condition: {fused_vwc:.1f}%", level='WARNING')
                
                # Check if system is enabled and auto irrigation is enabled
                system_enabled = self._get_switch_state("switch.crop_steering_system_enabled", True)
                auto_irrigation_enabled = self._get_switch_state("switch.crop_steering_auto_irrigation_enabled", True)
                
                if not system_enabled:
                    self.log("🛑 Emergency irrigation blocked: System disabled")
                    return
                
                if not auto_irrigation_enabled:
                    self.log("🛑 Emergency irrigation blocked: Auto irrigation disabled")
                    return
                
                # Check for tank filling (if tank fill sensor exists)
                tank_filling = self._get_switch_state("switch.tank_filling", False)
                if tank_filling:
                    self.log("🛑 Emergency irrigation blocked: Tank filling in progress")
                    return
                
                # Check if we can irrigate (not on cooldown)
                time_since_last = self._get_time_since_last_irrigation()
                cooldown_seconds = 300  # 5 minutes between emergency shots
                if time_since_last > cooldown_seconds:
                    # Use integration sensors which are working properly
                    emergency_zone = await self._select_emergency_zone_from_integration()
                    if emergency_zone:
                        # Check if zone is enabled
                        zone_enabled = self._get_switch_state(f"switch.crop_steering_zone_{emergency_zone}_enabled", True)
                        if not zone_enabled:
                            self.log(f"🛑 Emergency irrigation blocked: Zone {emergency_zone} disabled")
                            return
                        
                        # Track emergency attempts for abandonment logic
                        await self._track_emergency_attempt(emergency_zone, fused_vwc)
                        
                        # Check if we should abandon this zone (blocked dripper protection)
                        if await self._should_abandon_emergency_zone(emergency_zone):
                            self.log(f"🚫 Abandoning emergency irrigation for Zone {emergency_zone} - possible blocked dripper")
                            return
                        
                        await self._execute_irrigation_shot(emergency_zone, 60, shot_type='emergency')
                    else:
                        # Fallback to zone 3 based on user feedback
                        self.log("⚠️ Integration sensor selection failed, using Zone 3 fallback")
                        zone_3_enabled = self._get_switch_state("switch.crop_steering_zone_3_enabled", True)
                        if zone_3_enabled:
                            await self._execute_irrigation_shot(3, 60, shot_type='emergency')
                        else:
                            self.log("🛑 Emergency irrigation blocked: Zone 3 disabled")
                else:
                    remaining_cooldown = cooldown_seconds - time_since_last
                    self.log(f"⏱️ Emergency irrigation on cooldown: {remaining_cooldown:.0f}s remaining")
                
        except Exception as e:
            self.log(f"❌ Error checking emergency conditions: {e}", level='ERROR')

    async def _select_emergency_zone_from_integration(self) -> Optional[int]:
        """Select zone with lowest VWC using multiple fallback methods."""
        try:
            zone_vwc = {}
            
            # WORKAROUND: Multiple strategies to bypass AppDaemon async Task issue
            for zone_num in range(1, self.num_zones + 1):
                integration_sensor = f"sensor.crop_steering_vwc_zone_{zone_num}"
                value = None
                
                try:
                    # Method 1: Use get_history to get last known good value
                    history = self.get_history(entity_id=integration_sensor, duration=1)
                    if history and len(history) > 0 and len(history[0]) > 0:
                        last_state = history[0][-1]
                        if hasattr(last_state, 'state') and last_state.state not in ['unknown', 'unavailable']:
                            value = last_state.state
                            self.log(f"🔍 Zone {zone_num} via history: {value}")
                except:
                    pass
                
                # Method 2: Direct get_state with sync call
                if value is None:
                    try:
                        state_value = self.get_state(integration_sensor)
                        if state_value not in ['unknown', 'unavailable', None] and not hasattr(state_value, '__await__'):
                            value = state_value
                            self.log(f"🔍 Zone {zone_num} via get_state: {value}")
                    except:
                        pass
                
                # Method 3: Use get_state with async check
                if value is None:
                    try:
                        if self.entity_exists(integration_sensor):
                            test_value = self.get_entity_value(integration_sensor)
                            if test_value and not hasattr(test_value, '__await__'):
                                value = test_value
                                self.log(f"🔍 Zone {zone_num} via get_state: {value}")
                    except:
                        pass
                
                # Method 4: Fallback to raw sensor calculation
                if value is None:
                    zone_vwc_calc = self._get_zone_vwc(zone_num)
                    if zone_vwc_calc:
                        value = zone_vwc_calc
                        self.log(f"🔍 Zone {zone_num} via _get_zone_vwc: {value}")
                
                # Parse the value if we got one
                if value and value not in ['unknown', 'unavailable', None]:
                    try:
                        vwc = float(value)
                        zone_vwc[zone_num] = vwc
                        self.log(f"✅ Zone {zone_num} VWC: {vwc:.1f}%")
                    except (ValueError, TypeError):
                        self.log(f"❌ Zone {zone_num} invalid value: {value}")
                else:
                    self.log(f"❌ Zone {zone_num} unavailable: {value}")
            
            if zone_vwc:
                # Select zone with lowest VWC (most critical)
                emergency_zone = min(zone_vwc, key=zone_vwc.get)
                lowest_vwc = zone_vwc[emergency_zone]
                self.log(f"🚨 Emergency zone selected: Zone {emergency_zone} with {lowest_vwc:.1f}% VWC")
                self.log(f"📊 All zone VWCs: {zone_vwc}")
                return emergency_zone
            else:
                self.log("⚠️ CRITICAL: All sensors unavailable - using user-specified Zone 3 override")
                return 3  # Manual override based on user feedback
            
        except Exception as e:
            self.log(f"❌ Error selecting emergency zone: {e}", level='ERROR')
            return 3  # Emergency fallback to zone 3

    async def _select_emergency_zone(self) -> Optional[int]:
        """Select zone with lowest VWC for emergency irrigation."""
        try:
            zone_vwc = {}
            
            # Try to get zone VWC from sensor fusion results instead of direct sensor reading
            # Look for zone-specific sensor fusion data
            for zone_num in range(1, self.num_zones + 1):
                zone_sensors = [s for s in self.config['sensors']['vwc'] if f'r{zone_num}' in s or f'z{zone_num}' in s]
                zone_values = []
                
                for sensor in zone_sensors:
                    # Try to get the latest sensor reading that isn't an async Task
                    try:
                        value = self.get_entity_value(sensor)
                        if value not in ['unknown', 'unavailable', None] and not hasattr(value, '__await__'):
                            zone_values.append(float(value))
                    except (ValueError, TypeError):
                        continue
                
                if zone_values:
                    avg_vwc = sum(zone_values) / len(zone_values)
                    zone_vwc[zone_num] = avg_vwc
                    self.log(f"🔍 Zone {zone_num} emergency VWC: {avg_vwc:.1f}% (from {len(zone_values)} sensors)")
            
            if zone_vwc:
                # Select zone with lowest VWC (most critical)
                emergency_zone = min(zone_vwc, key=zone_vwc.get)
                lowest_vwc = zone_vwc[emergency_zone]
                self.log(f"🚨 Emergency zone selected: Zone {emergency_zone} with {lowest_vwc:.1f}% VWC")
                return emergency_zone
            else:
                self.log("⚠️ No zone VWC data available for emergency selection")
                return None
            
        except Exception as e:
            self.log(f"❌ Error selecting emergency zone: {e}", level='ERROR')
            return None

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
            state = self.get_entity_value(integration_sensor)
            if state not in ['unknown', 'unavailable', None]:
                # Ensure state is a string or number, not an async Task
                if hasattr(state, '__await__'):
                    self.log(f"⚠️ Async context detected for {integration_sensor}, falling back to safe method")
                    # Try alternative methods to get the value safely
                    try:
                        # Use entity_exists check first
                        if self.entity_exists(integration_sensor):
                            # Try get_state directly as a last resort
                            alt_state = self.get_state(integration_sensor)
                            if alt_state and not hasattr(alt_state, '__await__') and alt_state not in ['unknown', 'unavailable']:
                                return float(alt_state)
                    except Exception:
                        pass
                else:
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
                        state = self.get_entity_value(sensor)
                        if state not in ['unknown', 'unavailable', None]:
                            # Ensure state is a string or number, not an async Task
                            if hasattr(state, '__await__'):
                                self.log(f"⚠️ Async task from sensor {sensor}, trying alternative method")
                                # Try direct get_state as fallback
                                try:
                                    alt_state = self.get_state(sensor)
                                    if alt_state and not hasattr(alt_state, '__await__') and alt_state not in ['unknown', 'unavailable']:
                                        values.append(float(alt_state))
                                except Exception:
                                    pass
                                continue
                            values.append(float(state))
                    except (ValueError, TypeError) as e:
                        self.log(f"⚠️ Error reading sensor {sensor}: {e}")
                        continue
                
                if values:
                    return round(sum(values) / len(values), 2)
            
            return None
            
        except Exception as e:
            self.log(f"❌ Error getting zone {zone_num} VWC: {e}", level='ERROR')
            return None

    def _get_number_entity_value(self, entity_id: str, default: float) -> float:
        """Get value from number entity with fallback to default."""
        try:
            state = self.get_entity_value(entity_id)
            self.log(f"🔍 DEBUG: Number {entity_id} state: {state} (type: {type(state)})")
            if state not in ['unknown', 'unavailable', None]:
                # Handle async Task objects
                if hasattr(state, '__await__'):
                    self.log(f"⚠️ Number {entity_id} async Task detected, using default: {default}")
                    return default
                return float(state)
            else:
                self.log(f"⚠️ Number {entity_id} unavailable state: {state}, using default: {default}")
                return default
        except (ValueError, TypeError) as e:
            self.log(f"❌ Error reading number {entity_id}: {e}, using default: {default}")
            return default

    def _get_select_entity_value(self, entity_id: str, default: str) -> str:
        """Get value from select entity with fallback to default."""
        try:
            state = self.get_entity_value(entity_id)
            self.log(f"🔍 DEBUG: Select {entity_id} state: {state} (type: {type(state)})")
            if state not in ['unknown', 'unavailable', None]:
                # Handle async Task objects
                if hasattr(state, '__await__'):
                    self.log(f"⚠️ Select {entity_id} async Task detected, using default: {default}")
                    return default
                return str(state)
            else:
                self.log(f"⚠️ Select {entity_id} unavailable state: {state}, using default: {default}")
                return default
        except Exception as e:
            self.log(f"❌ Error reading select {entity_id}: {e}, using default: {default}")
            return default

    def _get_zone_ec(self, zone_num: int) -> Optional[float]:
        """Get average EC for specific zone."""
        try:
            zone_sensors = [s for s in self.config['sensors']['ec'] if f'r{zone_num}' in s or f'z{zone_num}' in s or f'zone_{zone_num}' in s.lower()]
            if not zone_sensors:
                # Try integration sensor as fallback
                integration_sensor = f"sensor.crop_steering_ec_zone_{zone_num}"
                state = self.get_entity_value(integration_sensor)
                if state not in ['unknown', 'unavailable', None]:
                    return float(state)
                return None
            
            ec_values = []
            for sensor in zone_sensors:
                try:
                    value = self.get_entity_value(sensor)
                    if value not in ['unknown', 'unavailable', None] and not hasattr(value, '__await__'):
                        ec_values.append(float(value))
                except (ValueError, TypeError):
                    continue
            
            if ec_values:
                return sum(ec_values) / len(ec_values)
            return None
            
        except Exception as e:
            self.log(f"❌ Error getting zone {zone_num} EC: {e}", level='ERROR')
            return None

    def _evaluate_ec_irrigation_need(self, current_ec: Optional[float], target_ec: float, phase: str) -> Dict:
        """Evaluate if irrigation is needed based on EC levels."""
        try:
            if current_ec is None:
                return {
                    'needs_irrigation': False,
                    'reason': 'No EC data available',
                    'confidence': 0.0,
                    'ec_ratio': None
                }
            
            # Calculate EC ratio (current/target)
            ec_ratio = current_ec / target_ec if target_ec > 0 else 0
            
            # Check if EC stacking is enabled
            ec_stacking_enabled = self._get_switch_state("switch.crop_steering_ec_stacking_enabled", False)
            
            if not ec_stacking_enabled:
                # Standard EC evaluation - irrigate if EC is too high
                if ec_ratio > 1.2:  # EC is 20% above target
                    return {
                        'needs_irrigation': True,
                        'reason': f'EC too high: {current_ec:.2f} vs {target_ec:.2f} target (ratio: {ec_ratio:.2f})',
                        'confidence': 0.8,
                        'ec_ratio': ec_ratio,
                        'action': 'dilute'
                    }
                elif ec_ratio < 0.8:  # EC is 20% below target
                    return {
                        'needs_irrigation': False,  # Don't irrigate if EC is too low (would dilute further)
                        'reason': f'EC too low: {current_ec:.2f} vs {target_ec:.2f} target (ratio: {ec_ratio:.2f}) - needs stronger nutrient',
                        'confidence': 0.6,
                        'ec_ratio': ec_ratio,
                        'action': 'strengthen'
                    }
            else:
                # EC stacking mode - gradually build EC through controlled irrigation
                if ec_ratio < 1.0:  # EC below target
                    # Calculate how much below target
                    ec_deficit = target_ec - current_ec
                    if ec_deficit > 0.5:  # Significant deficit
                        return {
                            'needs_irrigation': True,
                            'reason': f'EC stacking: building EC from {current_ec:.2f} to {target_ec:.2f} target',
                            'confidence': 0.7,
                            'ec_ratio': ec_ratio,
                            'action': 'stack'
                        }
            
            # EC is within acceptable range
            return {
                'needs_irrigation': False,
                'reason': f'EC optimal: {current_ec:.2f} (ratio: {ec_ratio:.2f})',
                'confidence': 0.9,
                'ec_ratio': ec_ratio,
                'action': 'maintain'
            }
            
        except Exception as e:
            self.log(f"❌ Error evaluating EC irrigation need: {e}", level='ERROR')
            return {
                'needs_irrigation': False,
                'reason': f'EC evaluation error: {e}',
                'confidence': 0.0,
                'ec_ratio': None
            }

    def _evaluate_p2_ec_ratio_irrigation(self, current_ec: Optional[float], target_ec: float, 
                                       high_threshold: float, low_threshold: float) -> Dict:
        """P2 specific EC ratio-based irrigation logic."""
        try:
            if current_ec is None:
                return {
                    'needs_irrigation': False,
                    'reason': 'No EC data for P2 ratio evaluation',
                    'confidence': 0.0
                }
            
            ec_ratio = current_ec / target_ec if target_ec > 0 else 0
            base_shot_size = self._get_number_entity_value("number.crop_steering_p2_shot_size", 5.0)
            
            if ec_ratio > high_threshold:
                # EC too high - irrigate with larger shot to dilute
                adjusted_shot_size = base_shot_size * 1.5  # 50% larger shot
                return {
                    'needs_irrigation': True,
                    'reason': f'P2 EC dilution: {current_ec:.2f} mS/cm (ratio: {ec_ratio:.2f} > {high_threshold})',
                    'confidence': 0.85,
                    'adjusted_shot_size': adjusted_shot_size,
                    'action': 'dilute'
                }
            elif ec_ratio < low_threshold:
                # EC too low - smaller shot to avoid further dilution
                adjusted_shot_size = base_shot_size * 0.7  # 30% smaller shot
                return {
                    'needs_irrigation': True,
                    'reason': f'P2 EC conservation: {current_ec:.2f} mS/cm (ratio: {ec_ratio:.2f} < {low_threshold})',
                    'confidence': 0.75,
                    'adjusted_shot_size': adjusted_shot_size,
                    'action': 'conserve'
                }
            
            return {
                'needs_irrigation': False,
                'reason': f'P2 EC ratio optimal: {ec_ratio:.2f} ({low_threshold} - {high_threshold})',
                'confidence': 0.9,
                'adjusted_shot_size': base_shot_size
            }
            
        except Exception as e:
            self.log(f"❌ Error in P2 EC ratio evaluation: {e}", level='ERROR')
            return {
                'needs_irrigation': False,
                'reason': f'P2 EC ratio error: {e}',
                'confidence': 0.0
            }

    def _calculate_ec_adjusted_shot_size(self, base_shot_size: float, current_ec: Optional[float], 
                                       target_ec: float, ec_decision: Dict) -> float:
        """Calculate shot size adjusted for EC conditions."""
        try:
            if current_ec is None or ec_decision.get('ec_ratio') is None:
                return base_shot_size
            
            ec_ratio = ec_decision['ec_ratio']
            action = ec_decision.get('action', 'maintain')
            
            if action == 'dilute':
                # EC too high - increase shot size to dilute
                if ec_ratio > 1.5:
                    return base_shot_size * 2.0  # Double shot for severe EC
                elif ec_ratio > 1.2:
                    return base_shot_size * 1.5  # 50% larger shot
                else:
                    return base_shot_size * 1.2  # 20% larger shot
                    
            elif action == 'conserve' or action == 'strengthen':
                # EC too low - reduce shot size to avoid dilution
                if ec_ratio < 0.5:
                    return base_shot_size * 0.5  # Half shot for very low EC
                elif ec_ratio < 0.8:
                    return base_shot_size * 0.7  # 30% smaller shot
                else:
                    return base_shot_size * 0.9  # 10% smaller shot
                    
            elif action == 'stack':
                # EC stacking mode - controlled building
                return base_shot_size * 1.1  # 10% larger for gradual building
            
            # Maintain or unknown action
            return base_shot_size
            
        except Exception as e:
            self.log(f"❌ Error calculating EC adjusted shot size: {e}", level='ERROR')
            return base_shot_size

    def _calculate_p1_progressive_shot_size(self, zone_num: int, initial_shot_size: float, 
                                          shot_increment: float, max_shot_size: float, 
                                          current_shot_count: int) -> float:
        """Calculate progressive shot size for P1 irrigation."""
        try:
            # Progressive shot sizing: start small, increase with each shot
            progressive_size = initial_shot_size + (shot_increment * current_shot_count)
            
            # Cap at maximum shot size
            progressive_size = min(progressive_size, max_shot_size)
            
            # Apply zone-specific shot size multiplier
            zone_multiplier = self._get_number_entity_value(f"number.crop_steering_zone_{zone_num}_shot_size_multiplier", 1.0)
            final_size = progressive_size * zone_multiplier
            
            self.log(f"📈 Zone {zone_num} P1 shot progression: base={initial_shot_size:.1f}% + increment={shot_increment:.1f}% * {current_shot_count} = {progressive_size:.1f}% * multiplier={zone_multiplier:.1f} = {final_size:.1f}%")
            
            return final_size
            
        except Exception as e:
            self.log(f"❌ Error calculating P1 progressive shot size: {e}", level='ERROR')
            return initial_shot_size

    def _update_p1_progression_after_irrigation(self, zone_num: int, shot_size: float, vwc_before: Optional[float]):
        """Update P1 progression tracking after irrigation."""
        try:
            zone_data = self.zone_phase_data[zone_num]
            now = datetime.now()
            
            # Update shot count and timing
            zone_data['p1_shot_count'] = zone_data.get('p1_shot_count', 0) + 1
            zone_data['p1_last_shot_time'] = now
            zone_data['p1_current_shot_size'] = shot_size
            
            # Record shot history
            shot_history = zone_data.get('p1_shot_history', [])
            shot_history.append({
                'timestamp': now,
                'shot_size': shot_size,
                'vwc_before': vwc_before,
                'vwc_after': None,  # Will be updated later when we read VWC again
                'shot_number': zone_data['p1_shot_count']
            })
            zone_data['p1_shot_history'] = shot_history
            
            # Log progression
            self.log(f"📊 Zone {zone_num} P1 progression updated: shot {zone_data['p1_shot_count']}, size {shot_size:.1f}%, VWC before: {vwc_before:.1f}%")
            
        except Exception as e:
            self.log(f"❌ Error updating P1 progression: {e}", level='ERROR')

    def _reset_p1_progression(self, zone_num: int):
        """Reset P1 progression when transitioning out of P1."""
        try:
            zone_data = self.zone_phase_data[zone_num]
            
            # Log final P1 stats
            shot_count = zone_data.get('p1_shot_count', 0)
            start_time = zone_data.get('p1_start_time')
            if start_time:
                duration = (datetime.now() - start_time).total_seconds() / 60  # minutes
                self.log(f"🎯 Zone {zone_num} P1 completed: {shot_count} shots over {duration:.1f} minutes")
            
            # Reset P1 tracking
            zone_data.update({
                'p1_start_time': None,
                'p1_shot_count': 0,
                'p1_current_shot_size': None,
                'p1_last_shot_time': None,
                'p1_vwc_at_start': None,
                'p1_shot_history': []
            })
            
        except Exception as e:
            self.log(f"❌ Error resetting P1 progression: {e}", level='ERROR')

    def _get_number_of_zones(self) -> int:
        """Get number of zones from integration configuration."""
        try:
            # Try to get from integration number entity
            zones_entity = self.get_entity_value("number.crop_steering_substrate_volume")  # This exists, so integration is loaded
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
                if lights_on and current_phase != 'P0':
                    # Lights on - zone should start P0 (morning dryback)
                    # P0 begins when lights turn on (plants wake up and start using water)
                    target_phase = 'P0'
                    reason = f"Zone {zone_num}: Lights on - starting morning dryback phase"
                    
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
                    # P3 continues until lights turn off, then system waits for lights on to start P0
                    # No transition needed here - P3 → P0 happens when lights turn on (handled above)
                    pass
                
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
        """Check if zone's P0 phase should end based on dryback progress and timing parameters."""
        try:
            zone_data = self.zone_phase_data.get(zone_num, {})
            now = datetime.now()
            
            # Get P0 timing parameters
            min_wait_time = self._get_number_entity_value("number.crop_steering_p0_min_wait_time", 30.0)
            dryback_drop_percent = self._get_number_entity_value("number.crop_steering_p0_dryback_drop_percent", 15.0)
            
            # Check if P0 phase has been initialized
            if not zone_data.get('p0_start_time'):
                self.log(f"⚠️ Zone {zone_num}: P0 not properly initialized - triggering initialization")
                self._initialize_p0_phase(zone_num, zone_vwc)
                return False  # Don't exit until properly initialized
            
            elapsed_minutes = (now - zone_data['p0_start_time']).total_seconds() / 60
            
            # MINIMUM WAIT TIME CHECK - Must stay in P0 for minimum duration
            if elapsed_minutes < min_wait_time:
                remaining_time = min_wait_time - elapsed_minutes
                self.log(f"⏱️ Zone {zone_num}: P0 minimum wait: {remaining_time:.1f}min remaining (min: {min_wait_time}min)")
                return False
            
            # MAXIMUM DURATION CHECK - Safety limit (force exit)
            if elapsed_minutes >= max_duration_minutes:
                self.log(f"🚨 Zone {zone_num}: P0 max duration exceeded: {elapsed_minutes:.1f}min >= {max_duration_minutes}min - forcing P1 transition")
                return True
            
            # DRYBACK TARGET CHECK - Primary exit condition
            if zone_vwc and zone_data.get('p0_peak_vwc'):
                # Calculate absolute dryback percentage
                peak_vwc = zone_data['p0_peak_vwc']
                dryback_amount = peak_vwc - zone_vwc
                dryback_percent = (dryback_amount / peak_vwc) * 100 if peak_vwc > 0 else 0
                
                # Check against target dryback percentage
                if dryback_percent >= dryback_target:
                    self.log(f"🎯 Zone {zone_num}: P0 dryback target achieved: {dryback_percent:.1f}% >= {dryback_target}% (dropped {dryback_amount:.1f}% from peak {peak_vwc:.1f}%)")
                    return True
                
                # Alternative check: minimum drop requirement
                if dryback_amount >= dryback_drop_percent:
                    self.log(f"📉 Zone {zone_num}: P0 minimum drop achieved: {dryback_amount:.1f}% >= {dryback_drop_percent}% (from peak {peak_vwc:.1f}%)")
                    return True
                
                # Log progress
                remaining_target = dryback_target - dryback_percent
                remaining_drop = dryback_drop_percent - dryback_amount
                self.log(f"📊 Zone {zone_num}: P0 progress - {elapsed_minutes:.1f}min elapsed, {dryback_percent:.1f}% dried (need {remaining_target:.1f}% more or {remaining_drop:.1f}% drop)")
            
            # INTELLIGENT DRYBACK RATE CHECK - Predict completion time
            if self._should_p0_exit_based_on_rate(zone_num, zone_vwc, dryback_target, max_duration_minutes):
                return True
            
            return False
            
        except Exception as e:
            self.log(f"❌ Error checking P0 exit conditions: {e}", level='ERROR')
            return False

    def _initialize_p0_phase(self, zone_num: int, current_vwc: Optional[float]):
        """Initialize P0 phase tracking for a zone."""
        try:
            zone_data = self.zone_phase_data[zone_num]
            now = datetime.now()
            
            # Set P0 start time
            zone_data['p0_start_time'] = now
            
            # Record peak VWC at start of P0 (highest moisture before dryback)
            if current_vwc is not None:
                zone_data['p0_peak_vwc'] = current_vwc
                self.log(f"🌱 Zone {zone_num}: P0 initialized - peak VWC: {current_vwc:.1f}%, start time: {now.strftime('%H:%M')}")
            else:
                # Estimate peak VWC if no current reading
                zone_data['p0_peak_vwc'] = 75.0  # Conservative estimate
                self.log(f"⚠️ Zone {zone_num}: P0 initialized without VWC reading - using estimated peak: 75.0%")
            
            # Reset P1 progression data since we're starting fresh cycle
            self._reset_p1_progression(zone_num)
            
        except Exception as e:
            self.log(f"❌ Error initializing P0 phase: {e}", level='ERROR')

    def _should_p0_exit_based_on_rate(self, zone_num: int, current_vwc: Optional[float], 
                                    dryback_target: float, max_duration_minutes: float) -> bool:
        """Check if P0 should exit based on dryback rate prediction."""
        try:
            if not current_vwc:
                return False
                
            zone_data = self.zone_phase_data[zone_num]
            if not zone_data.get('p0_start_time') or not zone_data.get('p0_peak_vwc'):
                return False
            
            now = datetime.now()
            elapsed_minutes = (now - zone_data['p0_start_time']).total_seconds() / 60
            
            # Need at least 15 minutes of data to calculate rate
            if elapsed_minutes < 15:
                return False
            
            peak_vwc = zone_data['p0_peak_vwc']
            current_dryback = ((peak_vwc - current_vwc) / peak_vwc) * 100
            dryback_rate = current_dryback / elapsed_minutes  # %/minute
            
            if dryback_rate <= 0:
                return False  # No dryback happening
            
            # Calculate time to reach target at current rate
            remaining_dryback = dryback_target - current_dryback
            if remaining_dryback <= 0:
                return True  # Already at target
            
            estimated_minutes_to_target = remaining_dryback / dryback_rate
            total_estimated_duration = elapsed_minutes + estimated_minutes_to_target
            
            # If we'll exceed max duration at current rate, exit now to start irrigation
            if total_estimated_duration > max_duration_minutes * 0.9:  # 90% of max time
                self.log(f"⏰ Zone {zone_num}: P0 rate-based exit - would exceed max duration: {total_estimated_duration:.1f}min > {max_duration_minutes * 0.9:.1f}min")
                return True
            
            # If rate is extremely slow, exit to prevent stalling
            if dryback_rate < 0.1 and elapsed_minutes > 60:  # Less than 0.1%/min after 1 hour
                self.log(f"🐌 Zone {zone_num}: P0 slow rate exit - dryback rate too slow: {dryback_rate:.3f}%/min")
                return True
            
            return False
            
        except Exception as e:
            self.log(f"❌ Error in P0 rate-based check: {e}", level='ERROR')
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
                # Note: Per-zone dryback tracking implemented via state machines
                status = self.dryback_detector._get_status_dict()
                if status and status.get('dryback_percentage') is not None:
                    return abs(status['dryback_percentage'])
            
            # Fallback to historical estimate based on zone characteristics
            # Could be enhanced with zone-specific ML model
            return None
            
        except Exception as e:
            self.log(f"❌ Error getting zone {zone_num} dryback rate: {e}", level='ERROR')
            return None

    async def _transition_zone_to_phase(self, zone_num: int, new_phase: str, reason: str):
        """Transition a specific zone to a new irrigation phase."""
        try:
            machine = self.zone_state_machines.get(zone_num)
            if not machine:
                self.log(f"Error: No state machine for zone {zone_num}", level='ERROR')
                return
            
            # Map string phase to enum
            phase_map = {
                'P0': IrrigationPhase.P0_MORNING_DRYBACK,
                'P1': IrrigationPhase.P1_RAMP_UP,
                'P2': IrrigationPhase.P2_MAINTENANCE,
                'P3': IrrigationPhase.P3_PRE_LIGHTS_OFF
            }
            
            target_phase = phase_map.get(new_phase)
            if not target_phase:
                self.log(f"Error: Invalid phase {new_phase}", level='ERROR')
                return
            
            # Determine appropriate transition type
            transition_type = PhaseTransition.MANUAL_OVERRIDE  # Default for manual changes
            current_phase = machine.state.current_phase
            
            # Map specific transitions
            if current_phase == IrrigationPhase.P0_MORNING_DRYBACK and target_phase == IrrigationPhase.P1_RAMP_UP:
                if "dryback complete" in reason.lower():
                    transition_type = PhaseTransition.DRYBACK_COMPLETE
                elif "timeout" in reason.lower():
                    transition_type = PhaseTransition.DRYBACK_TIMEOUT
            elif current_phase == IrrigationPhase.P1_RAMP_UP and target_phase == IrrigationPhase.P2_MAINTENANCE:
                if "target reached" in reason.lower():
                    transition_type = PhaseTransition.RAMP_UP_COMPLETE
            elif target_phase == IrrigationPhase.P3_PRE_LIGHTS_OFF:
                if "lights off" in reason.lower() or "ml" in reason.lower():
                    transition_type = PhaseTransition.LIGHTS_OFF_APPROACHING
            elif target_phase == IrrigationPhase.P0_MORNING_DRYBACK:
                if "lights on" in reason.lower():
                    transition_type = PhaseTransition.LIGHTS_ON
            
            # Execute transition
            success = machine.transition(transition_type, target_phase, reason=reason)
            
            if not success:
                self.log(f"Zone {zone_num}: Failed to transition to {new_phase}", level='WARNING')
                return
            
            # Save state after phase change (critical event)
            self._save_persistent_state()
            
            # Update zone-specific sensor
            await self.async_set_entity_value(f'sensor.crop_steering_zone_{zone_num}_phase',
                               new_phase,
                               attributes={
                                   'friendly_name': f'Zone {zone_num} Phase',
                                   'icon': self._get_phase_icon(new_phase),
                                   'transition_reason': reason,
                                   'transition_time': datetime.now().isoformat()
                               })
            
            # Update crop profile parameters if needed (could be zone-specific in future)
            await self._update_phase_parameters()
            
        except Exception as e:
            self.log(f"❌ Error transitioning zone {zone_num} to phase {new_phase}: {e}", level='ERROR')
    
    async def _check_all_zone_phase_transitions(self):
        """Check all zones for phase transition conditions."""
        try:
            current_time = datetime.now().time()
            lights_on_time = self._get_zone_schedule(1)['lights_on']  # System-wide schedule
            lights_off_time = self._get_zone_schedule(1)['lights_off']
            
            # Check if lights just turned on
            lights_just_on = self._is_time_between(
                current_time,
                lights_on_time,
                (datetime.combine(datetime.today(), lights_on_time) + timedelta(minutes=5)).time()
            )
            
            for zone_num in range(1, self.num_zones + 1):
                machine = self.zone_state_machines.get(zone_num)
                if not machine:
                    continue
                
                current_phase = machine.state.current_phase
                zone_vwc = self._get_zone_average_vwc(zone_num)
                
                # P3 → P0: Lights turned on (only from P3, not P2)
                if lights_just_on and current_phase == IrrigationPhase.P3_PRE_LIGHTS_OFF:
                    await self._transition_zone_to_phase(zone_num, 'P0', 'Lights on - starting morning dryback')
                
                # P0 → P1: Dryback complete or timeout
                elif current_phase == IrrigationPhase.P0_MORNING_DRYBACK:
                    p0_data = machine.state.p0_data
                    if p0_data and zone_vwc is not None:
                        # Update dryback progress
                        machine.update_p0_dryback(zone_vwc, p0_data.peak_vwc or zone_vwc)
                        
                        # Check dryback completion
                        dryback_target = p0_data.target_dryback_percentage
                        current_dryback = p0_data.current_dryback_percentage
                        phase_duration = machine.get_phase_duration().total_seconds() / 60  # minutes
                        
                        if current_dryback >= dryback_target:
                            await self._transition_zone_to_phase(zone_num, 'P1', f'Dryback complete: {current_dryback:.1f}%')
                        elif phase_duration >= p0_data.max_duration_minutes:
                            await self._transition_zone_to_phase(zone_num, 'P1', f'P0 timeout: {phase_duration:.0f} minutes')
                
                # P1 → P2: Recovery complete
                elif current_phase == IrrigationPhase.P1_RAMP_UP:
                    p1_data = machine.state.p1_data
                    if p1_data and zone_vwc is not None:
                        if zone_vwc >= p1_data.target_vwc:
                            await self._transition_zone_to_phase(zone_num, 'P2', f'Recovery complete: {zone_vwc:.1f}%')
                
                # P2 → P3: ML-based or time-based transition
                elif current_phase == IrrigationPhase.P2_MAINTENANCE:
                    # Check if it's time to transition to P3
                    should_start_p3 = await self._should_zone_start_p3(zone_num)
                    if should_start_p3:
                        await self._transition_zone_to_phase(zone_num, 'P3', 'ML predicted lights-off approaching')
        
        except Exception as e:
            self.log(f"Error checking phase transitions: {e}", level='ERROR')
    
    def _is_time_between(self, check_time: time, start_time: time, end_time: time) -> bool:
        """Check if a time is between two times (handles midnight wrap)."""
        if start_time <= end_time:
            return start_time <= check_time <= end_time
        else:
            return check_time >= start_time or check_time <= end_time
    
    async def _should_zone_start_p3(self, zone_num: int) -> bool:
        """Determine if zone should transition to P3 based on ML predictions."""
        try:
            # Get lights-off time
            lights_off_time = self._get_zone_schedule(zone_num)['lights_off']
            now = datetime.now()
            
            # Calculate time until lights off
            lights_off_datetime = datetime.combine(now.date(), lights_off_time)
            if lights_off_datetime < now:
                lights_off_datetime += timedelta(days=1)
            
            time_until_lights_off = (lights_off_datetime - now).total_seconds() / 3600  # hours
            
            # Get dryback rate prediction
            dryback_rate = await self._get_zone_dryback_rate(zone_num)
            if dryback_rate and dryback_rate > 0:
                # Calculate time needed to achieve overnight dryback
                target_dryback = self._get_number_entity_value("number.crop_steering_veg_dryback_target", 50.0)
                time_needed = target_dryback / dryback_rate + 0.5  # Add 30min buffer
                
                # Start P3 if we need to begin final dryback
                return time_until_lights_off <= time_needed
            else:
                # Fallback: Start P3 2 hours before lights off
                return time_until_lights_off <= 2.0
                
        except Exception as e:
            self.log(f"Error checking P3 transition for zone {zone_num}: {e}", level='ERROR')
            return False

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
                
                self.set_entity_value('sensor.crop_steering_ml_irrigation_need',
                              state=analysis.get('max_irrigation_need', 0),
                              attributes=predictions)
                
                self.set_entity_value('sensor.crop_steering_ml_confidence',
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
            self.set_entity_value('sensor.crop_steering_sensor_health',
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
                self.set_entity_value(entity_id, sensor_data['health_status'], attributes=sensor_data)
            
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
                self.set_entity_value(entity_id, value, 
                              attributes={'last_updated': datetime.now().isoformat()})
            
            self.log(f"📊 Performance updated - ML: {metrics['ml_model_accuracy']:.2f}, "
                    f"Sensors: {metrics['sensor_fusion_confidence']:.2f}")
            
        except Exception as e:
            self.log(f"❌ Error updating performance analytics: {e}", level='ERROR')

    def _update_dryback_entities(self, dryback_result: Dict):
        """Update Home Assistant entities with dryback data."""
        try:
            self.run_in(self._async_set_entity_wrapper, 0,
                       entity_id='sensor.crop_steering_dryback_percentage',
                       value=dryback_result['dryback_percentage'],
                       attributes=dryback_result)
            
            self.run_in(self._async_set_entity_wrapper, 0,
                       entity_id='binary_sensor.crop_steering_dryback_in_progress',
                       value='on' if dryback_result['dryback_in_progress'] else 'off',
                       attributes={'confidence': dryback_result['confidence_score']})
            
        except Exception as e:
            self.log(f"❌ Error updating dryback entities: {e}", level='ERROR')

    def _update_sensor_fusion_entities(self, sensor_id: str, fusion_result: Dict):
        """Update sensor fusion entities."""
        try:
            # Update individual sensor status
            entity_base = sensor_id.replace('.', '_')
            
            self.run_in(self._async_set_entity_wrapper, 0,
                       entity_id=f'sensor.{entity_base}_reliability',
                       value=fusion_result['sensor_reliability'],
                       attributes={'health': fusion_result['sensor_health'],
                                 'outlier_rate': fusion_result['outlier_rate']})
            
            # Update fused values if this was the latest update
            if fusion_result['fused_value'] is not None:
                sensor_type = 'vwc' if 'vwc' in sensor_id else 'ec'
                self.run_in(self._async_set_entity_wrapper, 0,
                           entity_id=f'sensor.crop_steering_fused_{sensor_type}',
                           value=fusion_result['fused_value'],
                           attributes={'confidence': fusion_result['fusion_confidence'],
                                     'active_sensors': fusion_result['active_sensors']})
            
        except Exception as e:
            self.log(f"❌ Error updating sensor fusion entities: {e}", level='ERROR')

    async def _update_decision_tracking(self, current_state: Dict, decision: Dict):
        """Update decision tracking and system state entities."""
        try:
            # Update current decision entity
            self.set_entity_value('sensor.crop_steering_current_decision',
                          state=decision['action'],
                          attributes={
                              'reason': str(decision['reason']),
                              'confidence': float(decision['confidence']),
                              'factors': str(decision.get('factors', [])),
                              'timestamp': datetime.now().isoformat()
                          })
            
            # Update system state entity
            self.set_entity_value('sensor.crop_steering_system_state',
                          state='active' if self.system_enabled else 'disabled',
                          attributes={
                              'zone_phases': {str(k): str(v) for k, v in self.zone_phases.items()},
                              'irrigation_in_progress': self.irrigation_in_progress,
                              'time_since_last_irrigation': self._get_time_since_last_irrigation(),
                              'average_vwc': current_state['average_vwc'],
                              'average_ec': current_state['average_ec']
                          })
            
            # Create dedicated sensors for integration compatibility
            # Create a summary of all zone phases
            phase_summary = ", ".join([f"Z{z}:{p}" for z, p in self.zone_phases.items()])
            self.set_entity_value('sensor.crop_steering_app_current_phase',
                          phase_summary,
                          attributes={
                              'friendly_name': 'Zone Phases',
                              'icon': 'mdi:water-circle',
                              'zone_phases': {str(k): str(v) for k, v in self.zone_phases.items()},
                              'updated': datetime.now().isoformat()
                          })
            
            # Calculate and set next irrigation time
            next_irrigation = self._calculate_next_irrigation_time()
            if next_irrigation:
                self.set_entity_value('sensor.crop_steering_app_next_irrigation',
                              state=next_irrigation.isoformat(),
                              attributes={
                                  'friendly_name': 'Next Irrigation Time',
                                  'icon': 'mdi:clock-outline',
                                  'device_class': 'timestamp',
                                  'updated': datetime.now().isoformat()
                              })
            else:
                self.set_entity_value('sensor.crop_steering_app_next_irrigation',
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
                    self.set_entity_value(entity_id, value)
                
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

    def _get_switch_state(self, entity_id: str, default: bool = False) -> bool:
        """Get switch state with error handling."""
        try:
            state = self.get_entity_value(entity_id)
            self.log(f"🔍 DEBUG: Switch {entity_id} state: {state} (type: {type(state)})")
            if state in ['on', True, 'true', '1']:
                return True
            elif state in ['off', False, 'false', '0']:
                return False
            else:
                self.log(f"⚠️ Switch {entity_id} unknown state: {state}, using default: {default}")
                return default
        except Exception as e:
            self.log(f"❌ Error reading switch {entity_id}: {e}, using default: {default}")
            return default

    async def _track_emergency_attempt(self, zone_num: int, vwc_before: float):
        """Track emergency irrigation attempts for abandonment logic."""
        try:
            now = datetime.now()
            attempts = self.emergency_attempts[zone_num]['attempts']
            
            # Remove attempts older than 1 hour
            cutoff_time = now - timedelta(hours=1)
            attempts[:] = [attempt for attempt in attempts if attempt[0] > cutoff_time]
            
            # Record this attempt
            attempts.append((now, vwc_before, None))  # vwc_after will be updated later
            
            self.log(f"📊 Zone {zone_num} emergency attempts in last hour: {len(attempts)}")
            
        except Exception as e:
            self.log(f"❌ Error tracking emergency attempt: {e}", level='ERROR')

    async def _should_abandon_emergency_zone(self, zone_num: int) -> bool:
        """Check if we should abandon emergency irrigation for a zone (blocked dripper protection)."""
        try:
            # Check if zone is already abandoned
            abandoned_until = self.emergency_attempts[zone_num].get('abandoned_until')
            if abandoned_until and datetime.now() < abandoned_until:
                return True
            
            attempts = self.emergency_attempts[zone_num]['attempts']
            now = datetime.now()
            
            # Look for recent attempts (last 30 minutes)
            recent_cutoff = now - timedelta(minutes=30)
            recent_attempts = [attempt for attempt in attempts if attempt[0] > recent_cutoff]
            
            # If we've had 4+ emergency shots in 30 minutes, consider abandoning
            if len(recent_attempts) >= 4:
                self.log(f"🚫 Zone {zone_num}: {len(recent_attempts)} emergency shots in 30min - likely blocked dripper")
                
                # Abandon for 2 hours
                self.emergency_attempts[zone_num]['abandoned_until'] = now + timedelta(hours=2)
                
                # Send notification if configured
                notification_service = self.config.get('notification_service')
                if notification_service and notification_service.startswith('notify.'):
                    await self.call_service(
                        notification_service.replace('notify.', 'notify/'),
                        message=f"⚠️ Zone {zone_num} emergency irrigation abandoned - possible blocked dripper. Will retry in 2 hours.",
                        title="Crop Steering Alert"
                    )
                
                return True
            
            return False
            
        except Exception as e:
            self.log(f"❌ Error checking abandonment: {e}", level='ERROR')
            return False

    async def _on_manual_irrigation_shot(self, event_name, data, kwargs):
        """Handle manual irrigation shot service calls."""
        try:
            zone = data.get('zone', 1)
            duration = data.get('duration_seconds', 30)
            shot_type = data.get('shot_type', 'manual')
            
            self.log(f"🔧 Manual irrigation shot requested: Zone {zone}, {duration}s, type: {shot_type}")
            
            # Execute the irrigation shot (manual shots bypass some checks)
            result = await self._execute_irrigation_shot(zone, duration, shot_type='manual')
            
            if result['status'] == 'completed':
                self.log(f"✅ Manual irrigation shot completed: Zone {zone}")
            elif result['status'] == 'blocked':
                self.log(f"🛑 Manual irrigation shot blocked: Zone {zone} - {result['message']}")
            else:
                self.log(f"❌ Manual irrigation shot failed: Zone {zone} - {result.get('message', 'Unknown error')}")
                
        except Exception as e:
            self.log(f"❌ Error handling manual irrigation shot: {e}", level='ERROR')

    async def _on_manual_override_event(self, event_name, data, kwargs):
        """Handle manual override events with timeout functionality."""
        try:
            zone = data.get('zone', 1)
            action = data.get('action', 'enable')
            timeout_minutes = data.get('timeout_minutes', 60)
            
            self.log(f"🔧 Manual override event: Zone {zone}, Action: {action}, Timeout: {timeout_minutes}min")
            
            if action == 'enable_with_timeout':
                await self._enable_manual_override_with_timeout(zone, timeout_minutes)
            elif action == 'enable_permanent':
                await self._enable_manual_override_permanent(zone)
            elif action == 'disable':
                await self._disable_manual_override(zone)
                
        except Exception as e:
            self.log(f"❌ Error handling manual override event: {e}", level='ERROR')

    async def _enable_manual_override_with_timeout(self, zone: int, timeout_minutes: int):
        """Enable manual override for a zone with automatic timeout."""
        try:
            # Cancel any existing timeout
            if self.manual_overrides[zone]['timeout_handle']:
                self.cancel_timer(self.manual_overrides[zone]['timeout_handle'])
            
            # Set new timeout
            timeout_handle = self.run_in(
                self._auto_disable_manual_override, 
                timeout_minutes * 60,  # Convert to seconds
                zone=zone
            )
            
            # Update tracking
            self.manual_overrides[zone].update({
                'timeout_handle': timeout_handle,
                'enabled_time': datetime.now(),
                'timeout_minutes': timeout_minutes
            })
            
            self.log(f"🕐 Manual override enabled for Zone {zone} with {timeout_minutes} minute timeout")
            
            # Send notification if configured
            notification_service = self.config.get('notification_service')
            if notification_service and notification_service.startswith('notify.'):
                await self.call_service(
                    notification_service.replace('notify.', 'notify/'),
                    message=f"Zone {zone} manual override enabled for {timeout_minutes} minutes. Automatic irrigation disabled.",
                    title="Crop Steering Manual Override"
                )
                
        except Exception as e:
            self.log(f"❌ Error enabling manual override with timeout: {e}", level='ERROR')

    async def _enable_manual_override_permanent(self, zone: int):
        """Enable manual override for a zone permanently (no timeout)."""
        try:
            # Cancel any existing timeout
            if self.manual_overrides[zone]['timeout_handle']:
                self.cancel_timer(self.manual_overrides[zone]['timeout_handle'])
            
            # Update tracking
            self.manual_overrides[zone].update({
                'timeout_handle': None,
                'enabled_time': datetime.now(),
                'timeout_minutes': None
            })
            
            self.log(f"🔒 Manual override enabled permanently for Zone {zone}")
            
            # Send notification if configured
            notification_service = self.config.get('notification_service')
            if notification_service and notification_service.startswith('notify.'):
                await self.call_service(
                    notification_service.replace('notify.', 'notify/'),
                    message=f"Zone {zone} manual override enabled permanently. Automatic irrigation disabled until manually disabled.",
                    title="Crop Steering Manual Override"
                )
                
        except Exception as e:
            self.log(f"❌ Error enabling permanent manual override: {e}", level='ERROR')

    async def _disable_manual_override(self, zone: int):
        """Disable manual override for a zone."""
        try:
            # Cancel any existing timeout
            if self.manual_overrides[zone]['timeout_handle']:
                self.cancel_timer(self.manual_overrides[zone]['timeout_handle'])
            
            # Update tracking
            self.manual_overrides[zone].update({
                'timeout_handle': None,
                'enabled_time': None,
                'timeout_minutes': None
            })
            
            self.log(f"🔓 Manual override disabled for Zone {zone}")
            
        except Exception as e:
            self.log(f"❌ Error disabling manual override: {e}", level='ERROR')

    async def _auto_disable_manual_override(self, kwargs):
        """Automatically disable manual override when timeout expires."""
        try:
            zone = kwargs.get('zone', 1)
            
            # Turn off the manual override switch
            await self.call_service('switch/turn_off', 
                                   entity_id=f"switch.crop_steering_zone_{zone}_manual_override")
            
            # Update tracking
            self.manual_overrides[zone].update({
                'timeout_handle': None,
                'enabled_time': None,
                'timeout_minutes': None
            })
            
            self.log(f"⏰ Manual override auto-disabled for Zone {zone} - timeout expired")
            
            # Send notification if configured
            notification_service = self.config.get('notification_service')
            if notification_service and notification_service.startswith('notify.'):
                await self.call_service(
                    notification_service.replace('notify.', 'notify/'),
                    message=f"Zone {zone} manual override timeout expired. Automatic irrigation resumed.",
                    title="Crop Steering Manual Override"
                )
                
        except Exception as e:
            self.log(f"❌ Error auto-disabling manual override: {e}", level='ERROR')

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
                'active_crop_profile': self.crop_profiles.current_profile if self.crop_profiles else None,
                'emergency_attempts': {
                    zone: {
                        'recent_attempts': len([a for a in data['attempts'] if a[0] > datetime.now() - timedelta(hours=1)]),
                        'abandoned_until': data['abandoned_until'].isoformat() if data['abandoned_until'] else None
                    }
                    for zone, data in self.emergency_attempts.items()
                },
                'group_status': self._get_group_status_summary(),
                'zone_priorities': {
                    zone: self._get_zone_priority(zone) 
                    for zone in range(1, self.num_zones + 1)
                },
                'zone_groups': {
                    zone: self._get_zone_group(zone) 
                    for zone in range(1, self.num_zones + 1)
                }
            }
        except Exception as e:
            self.log(f"❌ Error getting system status: {e}", level='ERROR')
            return {'error': str(e)}

    # Zone Grouping and Priority Logic - HIGH PRIORITY 5
    def _get_zone_group(self, zone_num: int) -> str:
        """Get zone group from integration entity."""
        try:
            group_entity = f"select.crop_steering_zone_{zone_num}_group"
            group_state = self.get_entity_value(group_entity)
            
            if group_state and group_state not in ['unknown', 'unavailable']:
                # Handle async task case
                if hasattr(group_state, '__await__'):
                    self.log(f"⚠️ Async task detected for zone {zone_num} group, using default")
                    return "Ungrouped"
                return group_state
            return "Ungrouped"
        except Exception as e:
            self.log(f"❌ Error getting zone {zone_num} group: {e}", level='ERROR')
            return "Ungrouped"

    def _get_zone_priority(self, zone_num: int) -> str:
        """Get zone priority from integration entity."""
        try:
            priority_entity = f"select.crop_steering_zone_{zone_num}_priority"
            priority_state = self.get_entity_value(priority_entity)
            
            if priority_state and priority_state not in ['unknown', 'unavailable']:
                # Handle async task case
                if hasattr(priority_state, '__await__'):
                    self.log(f"⚠️ Async task detected for zone {zone_num} priority, using default")
                    return "Normal"
                return priority_state
            return "Normal"
        except Exception as e:
            self.log(f"❌ Error getting zone {zone_num} priority: {e}", level='ERROR')
            return "Normal"

    def _get_priority_score(self, priority: str) -> int:
        """Convert priority string to numeric score for sorting."""
        priority_scores = {
            "Critical": 4,
            "High": 3,
            "Normal": 2,
            "Low": 1
        }
        return priority_scores.get(priority, 2)

    def _get_zones_by_group(self, group_name: str) -> List[int]:
        """Get all zones in a specific group."""
        try:
            zones_in_group = []
            for zone_num in range(1, self.num_zones + 1):
                zone_group = self._get_zone_group(zone_num)
                if zone_group == group_name:
                    zones_in_group.append(zone_num)
            return zones_in_group
        except Exception as e:
            self.log(f"❌ Error getting zones in group {group_name}: {e}", level='ERROR')
            return []

    def _get_zones_by_priority(self, priority: str) -> List[int]:
        """Get all zones with a specific priority level."""
        try:
            zones_at_priority = []
            for zone_num in range(1, self.num_zones + 1):
                zone_priority = self._get_zone_priority(zone_num)
                if zone_priority == priority:
                    zones_at_priority.append(zone_num)
            return zones_at_priority
        except Exception as e:
            self.log(f"❌ Error getting zones at priority {priority}: {e}", level='ERROR')
            return []

    def _sort_zones_by_priority(self, zone_list: List[int]) -> List[int]:
        """Sort zones by priority (Critical first, Low last)."""
        try:
            return sorted(zone_list, key=lambda z: self._get_priority_score(self._get_zone_priority(z)), reverse=True)
        except Exception as e:
            self.log(f"❌ Error sorting zones by priority: {e}", level='ERROR')
            return zone_list

    async def _coordinate_group_irrigation(self, group_name: str) -> bool:
        """Coordinate irrigation within a group to prevent conflicts."""
        try:
            zones_in_group = self._get_zones_by_group(group_name)
            if not zones_in_group:
                return True  # No conflict if no zones in group
            
            # Check if any zone in group is already irrigating
            for zone in zones_in_group:
                zone_valve_entity = self.config['hardware']['zone_valves'].get(zone)
                if zone_valve_entity:
                    valve_state = self.get_entity_value(zone_valve_entity)
                    if valve_state == 'on':
                        self.log(f"🚦 Group {group_name}: Zone {zone} already irrigating - blocking other zones in group")
                        return False
            
            return True  # Safe to irrigate
            
        except Exception as e:
            self.log(f"❌ Error coordinating group {group_name} irrigation: {e}", level='ERROR')
            return True  # Allow irrigation on error to prevent system lockup

    def _select_next_zone_by_priority(self, candidate_zones: List[int]) -> Optional[int]:
        """Select next zone to irrigate based on priority and need."""
        try:
            if not candidate_zones:
                return None
            
            # Calculate priority scores for each zone
            zone_scores = {}
            
            for zone in candidate_zones:
                # Base priority score
                priority = self._get_zone_priority(zone)
                priority_score = self._get_priority_score(priority)
                
                # VWC need score (lower VWC = higher need)
                zone_vwc = self._get_zone_vwc(zone)
                if zone_vwc is not None:
                    vwc_need_score = max(0, (70 - zone_vwc) / 70)  # 0-1 scale
                else:
                    vwc_need_score = 0.5  # Default if no VWC data
                
                # Phase urgency score
                zone_phase = self.zone_phases.get(zone, 'P2')
                phase_urgency = {
                    'P0': 0.1,  # Low urgency during dryback
                    'P1': 0.9,  # High urgency during recovery
                    'P2': 0.6,  # Medium urgency during maintenance
                    'P3': 0.8   # High urgency during final period
                }.get(zone_phase, 0.5)
                
                # Combined score: Priority (40%) + VWC Need (40%) + Phase Urgency (20%)
                total_score = (priority_score * 0.4) + (vwc_need_score * 0.4) + (phase_urgency * 0.2)
                zone_scores[zone] = total_score
                
                self.log(f"🎯 Zone {zone}: Priority={priority} ({priority_score}), VWC={zone_vwc:.1f}% (need={vwc_need_score:.2f}), Phase={zone_phase} (urgency={phase_urgency:.2f}) → Score={total_score:.2f}")
            
            # Select zone with highest score
            selected_zone = max(zone_scores, key=zone_scores.get)
            max_score = zone_scores[selected_zone]
            
            self.log(f"🏆 Selected Zone {selected_zone} with highest priority score: {max_score:.2f}")
            return selected_zone
            
        except Exception as e:
            self.log(f"❌ Error selecting zone by priority: {e}", level='ERROR')
            return candidate_zones[0] if candidate_zones else None

    async def _check_zone_conflicts(self, target_zone: int) -> bool:
        """Check if irrigating target zone would conflict with group or system constraints."""
        try:
            # Check group conflicts
            zone_group = self._get_zone_group(target_zone)
            if zone_group != "Ungrouped":
                group_clear = await self._coordinate_group_irrigation(zone_group)
                if not group_clear:
                    self.log(f"🚫 Zone {target_zone} irrigation blocked: Group {zone_group} conflict")
                    return True  # Conflict detected
            
            # Check system-wide irrigation limit (prevent too many zones irrigating simultaneously)
            active_irrigation_count = 0
            for zone_num in range(1, self.num_zones + 1):
                zone_valve_entity = self.config['hardware']['zone_valves'].get(zone_num)
                if zone_valve_entity:
                    valve_state = self.get_entity_value(zone_valve_entity)
                    if valve_state == 'on':
                        active_irrigation_count += 1
            
            # Limit to 1 zone irrigating at a time to prevent pressure issues
            max_concurrent_zones = 1
            if active_irrigation_count >= max_concurrent_zones:
                self.log(f"🚫 Zone {target_zone} irrigation blocked: {active_irrigation_count} zones already irrigating (max: {max_concurrent_zones})")
                return True  # Conflict detected
            
            return False  # No conflicts
            
        except Exception as e:
            self.log(f"❌ Error checking zone {target_zone} conflicts: {e}", level='ERROR')
            return False  # Allow irrigation on error

    def _get_group_status_summary(self) -> Dict[str, Dict]:
        """Get status summary for all zone groups."""
        try:
            group_status = {}
            
            # Get all unique groups
            all_groups = set()
            for zone_num in range(1, self.num_zones + 1):
                group = self._get_zone_group(zone_num)
                all_groups.add(group)
            
            for group_name in all_groups:
                zones_in_group = self._get_zones_by_group(group_name)
                
                if zones_in_group:
                    # Calculate group statistics
                    group_vwc_values = []
                    group_phases = []
                    irrigating_zones = 0
                    
                    for zone in zones_in_group:
                        # VWC
                        zone_vwc = self._get_zone_vwc(zone)
                        if zone_vwc is not None:
                            group_vwc_values.append(zone_vwc)
                        
                        # Phases
                        zone_phase = self.zone_phases.get(zone, 'P2')
                        group_phases.append(f"Z{zone}:{zone_phase}")
                        
                        # Irrigation status
                        zone_valve_entity = self.config['hardware']['zone_valves'].get(zone)
                        if zone_valve_entity:
                            valve_state = self.get_entity_value(zone_valve_entity)
                            if valve_state == 'on':
                                irrigating_zones += 1
                    
                    group_status[group_name] = {
                        'zones': zones_in_group,
                        'zone_count': len(zones_in_group),
                        'avg_vwc': round(sum(group_vwc_values) / len(group_vwc_values), 1) if group_vwc_values else None,
                        'phases': ", ".join(group_phases),
                        'irrigating_zones': irrigating_zones,
                        'status': 'Active' if irrigating_zones > 0 else 'Idle'
                    }
            
            return group_status
            
        except Exception as e:
            self.log(f"❌ Error getting group status summary: {e}", level='ERROR')
            return {}

    # Analytics System Implementation - HIGH PRIORITY 6
    async def _update_analytics_system(self, kwargs):
        """Update comprehensive analytics and performance metrics."""
        try:
            # Calculate system-wide analytics
            analytics_data = await self._calculate_system_analytics()
            
            # Update analytics sensor entities
            self._update_analytics_entities(analytics_data)
            
            # Update performance tracking
            await self._update_performance_metrics(analytics_data)
            
            # Update irrigation efficiency metrics
            await self._update_efficiency_metrics(analytics_data)
            
            # Update predictive analytics
            await self._update_predictive_analytics(analytics_data)
            
            # Update safety status monitoring
            self._update_safety_status_entities()
            
        except Exception as e:
            self.log(f"❌ Error updating analytics system: {e}", level='ERROR')

    async def _calculate_system_analytics(self) -> Dict:
        """Calculate comprehensive system analytics."""
        try:
            now = datetime.now()
            analytics = {
                'timestamp': now.isoformat(),
                'system_performance': {},
                'zone_analytics': {},
                'irrigation_analytics': {},
                'sensor_analytics': {},
                'efficiency_metrics': {},
                'predictive_metrics': {}
            }
            
            # System Performance Analytics
            analytics['system_performance'] = {
                'uptime_hours': (now - getattr(self, 'start_time', now)).total_seconds() / 3600,
                'total_zones': self.num_zones,
                'active_zones': len([z for z in range(1, self.num_zones + 1) 
                                   if self._get_switch_state(f"switch.crop_steering_zone_{z}_enabled", True)]),
                'zones_irrigating': len([z for z in range(1, self.num_zones + 1) 
                                       if self._is_zone_irrigating(z)]),
                'system_health_score': self._calculate_system_health_score()
            }
            
            # Zone-level Analytics
            for zone_num in range(1, self.num_zones + 1):
                zone_analytics = await self._calculate_zone_analytics(zone_num)
                analytics['zone_analytics'][f'zone_{zone_num}'] = zone_analytics
            
            # Irrigation Analytics
            analytics['irrigation_analytics'] = await self._calculate_irrigation_analytics()
            
            # Sensor Analytics
            analytics['sensor_analytics'] = self._calculate_sensor_analytics()
            
            # Efficiency Metrics
            analytics['efficiency_metrics'] = await self._calculate_efficiency_metrics()
            
            # Predictive Metrics
            analytics['predictive_metrics'] = await self._calculate_predictive_metrics()
            
            return analytics
            
        except Exception as e:
            self.log(f"❌ Error calculating system analytics: {e}", level='ERROR')
            return {}

    async def _calculate_zone_analytics(self, zone_num: int) -> Dict:
        """Calculate analytics for a specific zone."""
        try:
            zone_vwc = self._get_zone_vwc(zone_num)
            zone_ec = self._get_zone_ec(zone_num)
            zone_phase = self.zone_phases.get(zone_num, 'P2')
            zone_group = self._get_zone_group(zone_num)
            zone_priority = self._get_zone_priority(zone_num)
            
            # Calculate zone water usage from AppDaemon tracking
            daily_water = self.zone_water_usage.get(zone_num, {}).get('daily_total', 0.0)
            weekly_water = self.zone_water_usage.get(zone_num, {}).get('weekly_total', 0.0)
            daily_count = self.zone_water_usage.get(zone_num, {}).get('daily_count', 0)
            
            # Calculate zone health score
            health_factors = []
            if zone_vwc is not None and 40 <= zone_vwc <= 80:
                health_factors.append(1.0)  # Good VWC
            elif zone_vwc is not None:
                health_factors.append(0.5)  # Suboptimal VWC
            else:
                health_factors.append(0.0)  # No VWC data
                
            if zone_ec is not None and 1.0 <= zone_ec <= 8.0:
                health_factors.append(1.0)  # Good EC
            elif zone_ec is not None:
                health_factors.append(0.5)  # Suboptimal EC
            else:
                health_factors.append(0.0)  # No EC data
            
            zone_health = sum(health_factors) / len(health_factors) if health_factors else 0.0
            
            return {
                'vwc': zone_vwc,
                'ec': zone_ec,
                'phase': zone_phase,
                'group': zone_group,
                'priority': zone_priority,
                'daily_water_liters': daily_water,
                'weekly_water_liters': weekly_water,
                'daily_irrigation_count': daily_count,
                'health_score': round(zone_health, 2),
                'efficiency_score': self._calculate_zone_efficiency(zone_num),
                'last_irrigation': self.zone_phase_data.get(zone_num, {}).get('last_irrigation_time'),
                'p1_progression': self._get_p1_progression_status(zone_num)
            }
            
        except Exception as e:
            self.log(f"❌ Error calculating zone {zone_num} analytics: {e}", level='ERROR')
            return {}

    def _calculate_zone_efficiency(self, zone_num: int) -> float:
        """Calculate irrigation efficiency score for a zone."""
        try:
            zone_data = self.zone_phase_data.get(zone_num, {})
            p1_history = zone_data.get('p1_shot_history', [])
            
            if not p1_history:
                return 0.5  # Neutral score if no data
            
            # Calculate efficiency from recent shots
            recent_shots = [shot for shot in p1_history if shot[0] > datetime.now() - timedelta(days=1)]
            
            if not recent_shots:
                return 0.5
            
            efficiency_scores = []
            for timestamp, shot_size, vwc_before, vwc_after in recent_shots:
                if vwc_before and vwc_after and shot_size > 0:
                    # Calculate VWC improvement per unit of water
                    vwc_improvement = vwc_after - vwc_before
                    efficiency = max(0, min(1, vwc_improvement / shot_size))
                    efficiency_scores.append(efficiency)
            
            return round(sum(efficiency_scores) / len(efficiency_scores), 2) if efficiency_scores else 0.5
            
        except Exception as e:
            self.log(f"❌ Error calculating zone {zone_num} efficiency: {e}", level='ERROR')
            return 0.5

    async def _calculate_irrigation_analytics(self) -> Dict:
        """Calculate overall irrigation analytics."""
        try:
            total_daily_water = sum([data.get('daily_total', 0) for data in self.zone_water_usage.values()])
            total_weekly_water = sum([data.get('weekly_total', 0) for data in self.zone_water_usage.values()])
            total_daily_count = sum([data.get('daily_count', 0) for data in self.zone_water_usage.values()])
            
            avg_vwc = self._calculate_system_average_vwc()
            avg_ec = self._calculate_system_average_ec()
            
            # Calculate phase distribution
            phase_distribution = {}
            for phase in ['P0', 'P1', 'P2', 'P3']:
                count = sum([1 for z_phase in self.zone_phases.values() if z_phase == phase])
                phase_distribution[phase] = count
            
            return {
                'total_daily_water_liters': round(total_daily_water, 2),
                'total_weekly_water_liters': round(total_weekly_water, 2),
                'total_daily_irrigations': total_daily_count,
                'average_vwc': round(avg_vwc, 1) if avg_vwc else None,
                'average_ec': round(avg_ec, 1) if avg_ec else None,
                'phase_distribution': phase_distribution,
                'irrigation_frequency': round(total_daily_count / max(self.num_zones, 1), 1),
                'water_per_zone': round(total_daily_water / max(self.num_zones, 1), 2)
            }
            
        except Exception as e:
            self.log(f"❌ Error calculating irrigation analytics: {e}", level='ERROR')
            return {}

    def _calculate_sensor_analytics(self) -> Dict:
        """Calculate sensor health and performance analytics."""
        try:
            vwc_sensors_online = 0
            vwc_sensors_total = len(self.config['sensors']['vwc'])
            ec_sensors_online = 0
            ec_sensors_total = len(self.config['sensors']['ec'])
            
            # Check VWC sensor status
            for sensor in self.config['sensors']['vwc']:
                state = self.get_entity_value(sensor)
                if state not in ['unknown', 'unavailable', None]:
                    vwc_sensors_online += 1
            
            # Check EC sensor status
            for sensor in self.config['sensors']['ec']:
                state = self.get_entity_value(sensor)
                if state not in ['unknown', 'unavailable', None]:
                    ec_sensors_online += 1
            
            vwc_availability = (vwc_sensors_online / max(vwc_sensors_total, 1)) * 100
            ec_availability = (ec_sensors_online / max(ec_sensors_total, 1)) * 100
            
            return {
                'vwc_sensors_online': vwc_sensors_online,
                'vwc_sensors_total': vwc_sensors_total,
                'vwc_availability_percent': round(vwc_availability, 1),
                'ec_sensors_online': ec_sensors_online,
                'ec_sensors_total': ec_sensors_total,
                'ec_availability_percent': round(ec_availability, 1),
                'overall_sensor_health': round((vwc_availability + ec_availability) / 2, 1),
                'sensor_fusion_active': bool(self.sensor_fusion),
                'ml_predictor_active': bool(self.ml_predictor)
            }
            
        except Exception as e:
            self.log(f"❌ Error calculating sensor analytics: {e}", level='ERROR')
            return {}

    async def _calculate_efficiency_metrics(self) -> Dict:
        """Calculate system efficiency metrics."""
        try:
            # Calculate water use efficiency
            total_water = sum([data.get('daily_total', 0) for data in self.zone_water_usage.values()])
            avg_vwc = self._calculate_system_average_vwc()
            
            # Water use efficiency (VWC achieved per liter)
            water_efficiency = (avg_vwc / max(total_water, 0.1)) if avg_vwc else 0
            
            # Calculate automation efficiency (percentage of automatic vs manual irrigations)
            auto_irrigations = 0
            manual_irrigations = 0
            
            for zone_data in self.zone_phase_data.values():
                p1_history = zone_data.get('p1_shot_history', [])
                # Count recent irrigations
                recent_shots = [shot for shot in p1_history if shot[0] > datetime.now() - timedelta(days=1)]
                auto_irrigations += len(recent_shots)
            
            # Estimate manual irrigations from emergency attempts
            for zone_data in self.emergency_attempts.values():
                recent_attempts = [a for a in zone_data['attempts'] if a[0] > datetime.now() - timedelta(days=1)]
                manual_irrigations += len(recent_attempts)
            
            total_irrigations = auto_irrigations + manual_irrigations
            automation_rate = (auto_irrigations / max(total_irrigations, 1)) * 100
            
            return {
                'water_use_efficiency': round(water_efficiency, 3),
                'automation_rate_percent': round(automation_rate, 1),
                'auto_irrigations_today': auto_irrigations,
                'manual_irrigations_today': manual_irrigations,
                'system_efficiency_score': round((water_efficiency * 10 + automation_rate) / 2, 1)
            }
            
        except Exception as e:
            self.log(f"❌ Error calculating efficiency metrics: {e}", level='ERROR')
            return {}

    async def _calculate_predictive_metrics(self) -> Dict:
        """Calculate predictive analytics and recommendations."""
        try:
            predictions = {}
            
            # Predict next irrigation times for each zone
            for zone_num in range(1, self.num_zones + 1):
                zone_vwc = self._get_zone_vwc(zone_num)
                zone_phase = self.zone_phases.get(zone_num, 'P2')
                
                if zone_vwc is not None:
                    # Simple prediction based on phase and VWC trend
                    if zone_phase == 'P1':
                        next_irrigation_hours = 1.0  # Soon for P1
                    elif zone_phase == 'P2':
                        # Based on VWC threshold
                        threshold = self._get_number_entity_value("number.crop_steering_p2_vwc_threshold", 60.0)
                        if zone_vwc < threshold:
                            next_irrigation_hours = 0.5  # Soon
                        else:
                            next_irrigation_hours = 3.0  # Later
                    else:
                        next_irrigation_hours = 2.0  # Default
                    
                    predictions[f'zone_{zone_num}_next_irrigation_hours'] = round(next_irrigation_hours, 1)
            
            # System-level predictions
            avg_vwc = self._calculate_system_average_vwc()
            if avg_vwc:
                vwc_trend = 'stable'  # Simplified - could be enhanced with historical data
                if avg_vwc < 50:
                    vwc_trend = 'declining'
                elif avg_vwc > 70:
                    vwc_trend = 'increasing'
                    
                predictions['system_vwc_trend'] = vwc_trend
                predictions['estimated_daily_water_need'] = round(self.num_zones * 5.0, 1)  # Simplified estimate
            
            return predictions
            
        except Exception as e:
            self.log(f"❌ Error calculating predictive metrics: {e}", level='ERROR')
            return {}

    def _update_analytics_entities(self, analytics_data: Dict):
        """Update Home Assistant entities with analytics data."""
        try:
            # System performance entities
            perf = analytics_data.get('system_performance', {})
            self.set_entity_value('sensor.crop_steering_system_health_score',
                          state=perf.get('system_health_score', 0),
                          attributes={
                              'uptime_hours': perf.get('uptime_hours', 0),
                              'active_zones': perf.get('active_zones', 0),
                              'zones_irrigating': perf.get('zones_irrigating', 0)
                          })
            
            # Irrigation analytics entities
            irrig = analytics_data.get('irrigation_analytics', {})
            self.set_entity_value('sensor.crop_steering_daily_water_usage',
                          state=irrig.get('total_daily_water_liters', 0),
                          attributes=irrig)
            
            # Sensor analytics entities
            sensor = analytics_data.get('sensor_analytics', {})
            self.set_entity_value('sensor.crop_steering_sensor_health',
                          state=sensor.get('overall_sensor_health', 0),
                          attributes=sensor)
            
            # Efficiency metrics entities
            efficiency = analytics_data.get('efficiency_metrics', {})
            self.set_entity_value('sensor.crop_steering_system_efficiency',
                          state=efficiency.get('system_efficiency_score', 0),
                          attributes=efficiency)
            
            # Zone analytics entities
            zone_analytics = analytics_data.get('zone_analytics', {})
            for zone_key, zone_data in zone_analytics.items():
                zone_num = zone_key.split('_')[1]
                
                # Create zone health sensor
                self.set_entity_value(f'sensor.crop_steering_zone_{zone_num}_health_score',
                              state=zone_data.get('health_score', 0),
                              attributes=zone_data)
                
                # Create zone efficiency sensor
                self.set_entity_value(f'sensor.crop_steering_zone_{zone_num}_efficiency',
                              state=zone_data.get('efficiency_score', 0),
                              attributes={
                                  'daily_water': zone_data.get('daily_water_liters', 0),
                                  'irrigation_count': zone_data.get('daily_irrigation_count', 0)
                              })
            
        except Exception as e:
            self.log(f"❌ Error updating analytics entities: {e}", level='ERROR')

    def _calculate_system_health_score(self) -> float:
        """Calculate overall system health score (0-100)."""
        try:
            health_factors = []
            
            # Sensor availability factor
            vwc_sensors_working = 0
            for sensor in self.config['sensors']['vwc']:
                if self.get_entity_value(sensor) not in ['unknown', 'unavailable', None]:
                    vwc_sensors_working += 1
            sensor_health = vwc_sensors_working / max(len(self.config['sensors']['vwc']), 1)
            health_factors.append(sensor_health)
            
            # Zone health factor
            healthy_zones = 0
            for zone_num in range(1, self.num_zones + 1):
                zone_vwc = self._get_zone_vwc(zone_num)
                if zone_vwc and 40 <= zone_vwc <= 80:  # Healthy VWC range
                    healthy_zones += 1
            zone_health = healthy_zones / max(self.num_zones, 1)
            health_factors.append(zone_health)
            
            # System functionality factor
            functionality_score = 1.0 if self.system_enabled else 0.0
            health_factors.append(functionality_score)
            
            # Calculate overall score
            overall_health = (sum(health_factors) / len(health_factors)) * 100
            return round(overall_health, 1)
            
        except Exception as e:
            self.log(f"❌ Error calculating system health score: {e}", level='ERROR')
            return 50.0

    def _is_zone_irrigating(self, zone_num: int) -> bool:
        """Check if a zone is currently irrigating."""
        try:
            zone_valve_entity = self.config['hardware']['zone_valves'].get(zone_num)
            if zone_valve_entity:
                valve_state = self.get_entity_value(zone_valve_entity)
                return valve_state == 'on'
            return False
        except Exception:
            return False

    def _calculate_system_average_vwc(self) -> Optional[float]:
        """Calculate system-wide average VWC."""
        try:
            vwc_values = []
            for zone_num in range(1, self.num_zones + 1):
                zone_vwc = self._get_zone_vwc(zone_num)
                if zone_vwc is not None:
                    vwc_values.append(zone_vwc)
            
            return sum(vwc_values) / len(vwc_values) if vwc_values else None
        except Exception:
            return None

    def _calculate_system_average_ec(self) -> Optional[float]:
        """Calculate system-wide average EC."""
        try:
            ec_values = []
            for zone_num in range(1, self.num_zones + 1):
                zone_ec = self._get_zone_ec(zone_num)
                if zone_ec is not None:
                    ec_values.append(zone_ec)
            
            return sum(ec_values) / len(ec_values) if ec_values else None
        except Exception:
            return None

    async def _update_performance_metrics(self, analytics_data: Dict):
        """Update long-term performance tracking."""
        try:
            # This could store historical data for trend analysis
            # For now, just log key metrics
            perf = analytics_data.get('system_performance', {})
            efficiency = analytics_data.get('efficiency_metrics', {})
            
            self.log(f"📊 Performance Update - Health: {perf.get('system_health_score', 0):.1f}%, "
                    f"Efficiency: {efficiency.get('system_efficiency_score', 0):.1f}%, "
                    f"Water: {analytics_data.get('irrigation_analytics', {}).get('total_daily_water_liters', 0):.1f}L")
                    
        except Exception as e:
            self.log(f"❌ Error updating performance metrics: {e}", level='ERROR')

    async def _update_efficiency_metrics(self, analytics_data: Dict):
        """Update efficiency tracking metrics."""
        try:
            efficiency = analytics_data.get('efficiency_metrics', {})
            
            # Update water efficiency sensor
            self.set_entity_value('sensor.crop_steering_water_efficiency',
                          state=efficiency.get('water_use_efficiency', 0),
                          attributes={
                              'automation_rate': efficiency.get('automation_rate_percent', 0),
                              'auto_irrigations': efficiency.get('auto_irrigations_today', 0),
                              'manual_irrigations': efficiency.get('manual_irrigations_today', 0)
                          })
                          
        except Exception as e:
            self.log(f"❌ Error updating efficiency metrics: {e}", level='ERROR')

    async def _update_predictive_analytics(self, analytics_data: Dict):
        """Update predictive analytics and recommendations."""
        try:
            predictions = analytics_data.get('predictive_metrics', {})
            
            # Update prediction sensors
            for key, value in predictions.items():
                if isinstance(value, (int, float)):
                    self.set_entity_value(f'sensor.crop_steering_prediction_{key}',
                                  state=value,
                                  attributes={
                                      'updated': datetime.now().isoformat(),
                                      'prediction_type': 'automated'
                                  })
                          
        except Exception as e:
            self.log(f"❌ Error updating predictive analytics: {e}", level='ERROR')

    def _get_p1_progression_status(self, zone_num: int) -> Dict:
        """Get P1 progression status for analytics."""
        try:
            zone_data = self.zone_phase_data.get(zone_num, {})
            
            return {
                'current_shot_count': zone_data.get('p1_shot_count', 0),
                'current_shot_size': zone_data.get('p1_current_shot_size', 0),
                'last_shot_time': zone_data.get('p1_last_shot_time'),
                'vwc_at_start': zone_data.get('p1_vwc_at_start'),
                'shots_completed': len(zone_data.get('p1_shot_history', []))
            }
        except Exception as e:
            self.log(f"❌ Error getting P1 progression status: {e}", level='ERROR')
            return {}

    # Field Capacity and Max EC Safety - HIGH PRIORITY 7
    def _check_irrigation_safety_limits(self, zone: int, shot_type: str) -> Dict:
        """Check critical safety limits before allowing irrigation."""
        try:
            # Get current zone conditions
            zone_vwc = self._get_zone_vwc(zone)
            zone_ec = self._get_zone_ec(zone)
            
            # Get safety limits from integration entities
            field_capacity = self._get_number_entity_value("number.crop_steering_field_capacity", 80.0)
            max_ec_limit = self._get_number_entity_value("number.crop_steering_max_ec", 8.0)
            
            # Get zone-specific daily limits
            max_daily_volume = self._get_number_entity_value(f"number.crop_steering_zone_{zone}_max_daily_volume", 20.0)
            
            # Check field capacity safety (prevent over-watering)
            if zone_vwc is not None and zone_vwc >= field_capacity:
                return {
                    'blocked': True,
                    'reason': 'field_capacity_exceeded',
                    'message': f'Zone {zone} VWC ({zone_vwc:.1f}%) at or above field capacity ({field_capacity:.1f}%) - irrigation blocked to prevent over-watering'
                }
            
            # Check maximum EC safety (prevent nutrient burn)
            if zone_ec is not None and zone_ec >= max_ec_limit:
                return {
                    'blocked': True,
                    'reason': 'max_ec_exceeded',
                    'message': f'Zone {zone} EC ({zone_ec:.1f} mS/cm) at or above safety limit ({max_ec_limit:.1f} mS/cm) - irrigation blocked to prevent nutrient burn'
                }
            
            # Check daily water volume limit
            daily_water_used = self.zone_water_usage.get(zone, {}).get('daily_total', 0.0)
            if daily_water_used >= max_daily_volume:
                return {
                    'blocked': True,
                    'reason': 'daily_volume_limit',
                    'message': f'Zone {zone} daily water limit reached ({daily_water_used:.1f}L >= {max_daily_volume:.1f}L) - irrigation blocked to prevent excessive watering'
                }
            
            # Check for extremely high VWC (backup safety)
            if zone_vwc is not None and zone_vwc >= 90.0:
                return {
                    'blocked': True,
                    'reason': 'extreme_saturation',
                    'message': f'Zone {zone} extremely saturated ({zone_vwc:.1f}%) - irrigation blocked for plant safety'
                }
            
            # Check for extremely high EC (backup safety)
            if zone_ec is not None and zone_ec >= 15.0:
                return {
                    'blocked': True,
                    'reason': 'extreme_ec',
                    'message': f'Zone {zone} extremely high EC ({zone_ec:.1f} mS/cm) - irrigation blocked for plant safety'
                }
            
            # Check irrigation frequency limits (prevent too frequent irrigation)
            if shot_type != 'manual':  # Only apply to automatic irrigation
                frequency_check = self._check_irrigation_frequency_safety(zone)
                if frequency_check['blocked']:
                    return frequency_check
            
            # Check phase-specific safety limits
            phase_check = self._check_phase_specific_safety(zone, zone_vwc, zone_ec)
            if phase_check['blocked']:
                return phase_check
            
            # All safety checks passed
            return {
                'blocked': False,
                'reason': None,
                'message': 'All safety checks passed'
            }
            
        except Exception as e:
            self.log(f"❌ Error checking irrigation safety limits: {e}", level='ERROR')
            # Default to allowing irrigation on error to prevent system lockup
            return {
                'blocked': False,
                'reason': 'safety_check_error',
                'message': f'Safety check error: {e}'
            }

    def _check_irrigation_frequency_safety(self, zone: int) -> Dict:
        """Check irrigation frequency safety limits."""
        try:
            zone_data = self.zone_phase_data.get(zone, {})
            last_irrigation = zone_data.get('last_irrigation_time')
            
            if last_irrigation:
                time_since_last = (datetime.now() - last_irrigation).total_seconds() / 60  # minutes
                
                # Minimum time between irrigations (prevent pump cycling)
                min_interval_minutes = 10.0  # Minimum 10 minutes between irrigations
                
                if time_since_last < min_interval_minutes:
                    return {
                        'blocked': True,
                        'reason': 'frequency_limit',
                        'message': f'Zone {zone} irrigation too frequent - {time_since_last:.1f}min since last irrigation (min: {min_interval_minutes}min)'
                    }
            
            # Check daily irrigation count
            daily_count = self.zone_water_usage.get(zone, {}).get('daily_count', 0)
            max_daily_irrigations = 50  # Maximum irrigations per day
            
            if daily_count >= max_daily_irrigations:
                return {
                    'blocked': True,
                    'reason': 'daily_count_limit',
                    'message': f'Zone {zone} maximum daily irrigations reached ({daily_count} >= {max_daily_irrigations})'
                }
            
            return {'blocked': False}
            
        except Exception as e:
            self.log(f"❌ Error checking irrigation frequency safety: {e}", level='ERROR')
            return {'blocked': False}

    def _check_phase_specific_safety(self, zone: int, zone_vwc: Optional[float], zone_ec: Optional[float]) -> Dict:
        """Check phase-specific safety limits."""
        try:
            zone_phase = self.zone_phases.get(zone, 'P2')
            
            # P0 phase safety - should not irrigate during dryback
            if zone_phase == 'P0':
                return {
                    'blocked': True,
                    'reason': 'p0_phase_irrigation',
                    'message': f'Zone {zone} in P0 dryback phase - irrigation blocked to allow proper drying'
                }
            
            # P1 phase safety - check VWC not too high for progressive irrigation
            if zone_phase == 'P1' and zone_vwc is not None:
                p1_target = self._get_number_entity_value("number.crop_steering_p1_target_vwc", 65.0)
                if zone_vwc >= p1_target + 10:  # Allow 10% buffer above target
                    return {
                        'blocked': True,
                        'reason': 'p1_target_exceeded',
                        'message': f'Zone {zone} VWC ({zone_vwc:.1f}%) well above P1 target ({p1_target:.1f}%) - irrigation blocked'
                    }
            
            # P3 phase safety - check if final dryback period
            if zone_phase == 'P3':
                # Allow emergency irrigation but warn
                emergency_threshold = self._get_number_entity_value("number.crop_steering_p3_emergency_vwc_threshold", 45.0)
                if zone_vwc is not None and zone_vwc > emergency_threshold + 5:  # 5% buffer
                    return {
                        'blocked': True,
                        'reason': 'p3_non_emergency',
                        'message': f'Zone {zone} in P3 phase with VWC ({zone_vwc:.1f}%) above emergency level ({emergency_threshold:.1f}%) - irrigation blocked'
                    }
            
            return {'blocked': False}
            
        except Exception as e:
            self.log(f"❌ Error checking phase-specific safety: {e}", level='ERROR')
            return {'blocked': False}

    def _update_safety_status_entities(self):
        """Update safety status entities for monitoring."""
        try:
            safety_status = {}
            
            for zone_num in range(1, self.num_zones + 1):
                zone_vwc = self._get_zone_vwc(zone_num)
                zone_ec = self._get_zone_ec(zone_num)
                field_capacity = self._get_number_entity_value("number.crop_steering_field_capacity", 80.0)
                max_ec_limit = self._get_number_entity_value("number.crop_steering_max_ec", 8.0)
                
                # Calculate safety margins
                vwc_margin = field_capacity - zone_vwc if zone_vwc else None
                ec_margin = max_ec_limit - zone_ec if zone_ec else None
                
                # Determine safety status
                status = 'safe'
                if zone_vwc and zone_vwc >= field_capacity:
                    status = 'over_saturated'
                elif zone_ec and zone_ec >= max_ec_limit:
                    status = 'ec_limit_exceeded'
                elif zone_vwc and zone_vwc >= field_capacity - 5:  # Within 5% of limit
                    status = 'approaching_saturation'
                elif zone_ec and zone_ec >= max_ec_limit - 1:  # Within 1 mS/cm of limit
                    status = 'approaching_ec_limit'
                
                safety_status[f'zone_{zone_num}'] = {
                    'status': status,
                    'vwc_margin': round(vwc_margin, 1) if vwc_margin else None,
                    'ec_margin': round(ec_margin, 1) if ec_margin else None,
                    'field_capacity': field_capacity,
                    'max_ec': max_ec_limit
                }
                
                # Create individual zone safety sensor
                self.set_entity_value(f'sensor.crop_steering_zone_{zone_num}_safety_status',
                              state=status,
                              attributes={
                                  'vwc': zone_vwc,
                                  'ec': zone_ec,
                                  'vwc_margin': round(vwc_margin, 1) if vwc_margin else None,
                                  'ec_margin': round(ec_margin, 1) if ec_margin else None,
                                  'field_capacity': field_capacity,
                                  'max_ec_limit': max_ec_limit
                              })
            
            # Create system-wide safety status
            unsafe_zones = len([status for status in safety_status.values() 
                              if status['status'] in ['over_saturated', 'ec_limit_exceeded']])
            warning_zones = len([status for status in safety_status.values() 
                               if status['status'] in ['approaching_saturation', 'approaching_ec_limit']])
            
            system_safety_status = 'safe'
            if unsafe_zones > 0:
                system_safety_status = 'unsafe'
            elif warning_zones > 0:
                system_safety_status = 'warning'
            
            self.set_entity_value('sensor.crop_steering_system_safety_status',
                          state=system_safety_status,
                          attributes={
                              'unsafe_zones': unsafe_zones,
                              'warning_zones': warning_zones,
                              'safe_zones': self.num_zones - unsafe_zones - warning_zones,
                              'zone_details': safety_status
                          })
            
        except Exception as e:
            self.log(f"❌ Error updating safety status entities: {e}", level='ERROR')

    def terminate(self):
        """Clean shutdown of master application."""
        try:
            # Emergency stop irrigation - sync version for shutdown
            try:
                # Safely access hardware entities with error handling
                hardware = self.config.get('hardware', {})
                
                pump_entity = hardware.get('pump_master')
                main_line_entity = hardware.get('main_line')
                zone_valves = hardware.get('zone_valves', {})
                
                # Turn off hardware synchronously during shutdown (only if configured)
                if pump_entity:
                    self.turn_off(pump_entity)
                    self.log(f"🛑 Emergency stop: Turned off pump {pump_entity}")
                else:
                    self.log("⚠️ Emergency stop: Pump entity not configured")
                    
                if main_line_entity:
                    self.turn_off(main_line_entity)
                    self.log(f"🛑 Emergency stop: Turned off main line {main_line_entity}")
                else:
                    self.log("⚠️ Emergency stop: Main line entity not configured")
                
                if zone_valves:
                    for zone_id, zone_valve in zone_valves.items():
                        if zone_valve:
                            self.turn_off(zone_valve)
                            self.log(f"🛑 Emergency stop: Turned off zone {zone_id} valve {zone_valve}")
                else:
                    self.log("⚠️ Emergency stop: No zone valves configured")
                    
                self.log("🛑 Emergency stop executed during shutdown")
                    
            except Exception as stop_error:
                self.log(f"⚠️ Could not emergency stop during shutdown: {stop_error}")
            
            self.log("🛑 Master Crop Steering Application terminated")
            
        except Exception as e:
            self.log(f"❌ Error during termination: {e}", level='ERROR')