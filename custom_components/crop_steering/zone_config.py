"""Zone configuration helper for Crop Steering System."""
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

_LOGGER = logging.getLogger(__name__)


class ZoneConfigParser:
    """Parse and manage zone configuration from crop_steering.env file."""
    
    def __init__(self, config_dir: str):
        """Initialize zone config parser.
        
        Args:
            config_dir: Home Assistant configuration directory
        """
        self.config_dir = config_dir
        self.env_file_path = os.path.join(config_dir, "crop_steering.env")
        self.zones = {}
        self.hardware_config = {}
        
    def load_configuration(self) -> bool:
        """Load configuration from crop_steering.env file.
        
        Returns:
            True if configuration loaded successfully
        """
        if not os.path.exists(self.env_file_path):
            _LOGGER.warning(f"Configuration file not found: {self.env_file_path}")
            return False
            
        try:
            with open(self.env_file_path, 'r') as f:
                lines = f.readlines()
                
            # Parse configuration
            config = {}
            for line in lines:
                # Skip comments and empty lines
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                    
                # Parse KEY=VALUE pairs
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    if value:  # Only store non-empty values
                        config[key] = value
                        
            # Extract hardware configuration
            self._parse_hardware_config(config)
            
            # Extract zone configuration
            self._parse_zone_config(config)
            
            _LOGGER.info(f"Loaded configuration for {len(self.zones)} zones")
            return True
            
        except Exception as e:
            _LOGGER.error(f"Error loading configuration: {e}")
            return False
            
    def _parse_hardware_config(self, config: Dict[str, str]) -> None:
        """Parse hardware configuration from config dict."""
        # Main hardware switches
        self.hardware_config['pump_switch'] = config.get('PUMP_SWITCH', '')
        self.hardware_config['main_line_switch'] = config.get('MAIN_LINE_SWITCH', '')
        self.hardware_config['waste_switch'] = config.get('WASTE_SWITCH', '')
        
        # Lighting configuration
        self.hardware_config['light_entity'] = config.get('LIGHT_ENTITY', '')
        self.hardware_config['lights_on_time'] = config.get('LIGHTS_ON_TIME', '')
        self.hardware_config['lights_off_time'] = config.get('LIGHTS_OFF_TIME', '')
        
        # Environmental sensors
        self.hardware_config['temperature_sensor'] = config.get('TEMPERATURE_SENSOR', '')
        self.hardware_config['humidity_sensor'] = config.get('HUMIDITY_SENSOR', '')
        self.hardware_config['vpd_sensor'] = config.get('VPD_SENSOR', '')
        self.hardware_config['water_level_sensor'] = config.get('WATER_LEVEL_SENSOR', '')
        
    def _parse_zone_config(self, config: Dict[str, str]) -> None:
        """Parse zone configuration from config dict."""
        # Find all configured zones
        zone_pattern = re.compile(r'ZONE_(\d+)_')
        zone_numbers = set()
        
        for key in config.keys():
            match = zone_pattern.match(key)
            if match:
                zone_numbers.add(int(match.group(1)))
                
        # Parse each zone's configuration
        for zone_num in sorted(zone_numbers):
            zone_config = {}
            
            # Zone switch
            zone_switch = config.get(f'ZONE_{zone_num}_SWITCH', '')
            if not zone_switch:
                continue  # Skip zones without switches
                
            zone_config['zone_switch'] = zone_switch
            zone_config['zone_number'] = zone_num
            
            # VWC sensors
            zone_config['vwc_front'] = config.get(f'ZONE_{zone_num}_VWC_FRONT', '')
            zone_config['vwc_back'] = config.get(f'ZONE_{zone_num}_VWC_BACK', '')
            
            # EC sensors
            zone_config['ec_front'] = config.get(f'ZONE_{zone_num}_EC_FRONT', '')
            zone_config['ec_back'] = config.get(f'ZONE_{zone_num}_EC_BACK', '')
            
            # Validate zone has at least one VWC and one EC sensor
            has_vwc = zone_config['vwc_front'] or zone_config['vwc_back']
            has_ec = zone_config['ec_front'] or zone_config['ec_back']
            
            if has_vwc and has_ec:
                self.zones[zone_num] = zone_config
            else:
                _LOGGER.warning(f"Zone {zone_num} missing required sensors (VWC: {has_vwc}, EC: {has_ec})")
                
    def get_active_zones(self) -> List[int]:
        """Get list of active zone numbers.
        
        Returns:
            Sorted list of active zone numbers
        """
        return sorted(self.zones.keys())
        
    def get_zone_config(self, zone_num: int) -> Optional[Dict]:
        """Get configuration for specific zone.
        
        Args:
            zone_num: Zone number
            
        Returns:
            Zone configuration dict or None if zone not configured
        """
        return self.zones.get(zone_num)
        
    def get_all_zone_switches(self) -> Dict[int, str]:
        """Get all zone switch entities.
        
        Returns:
            Dict mapping zone number to switch entity ID
        """
        return {
            zone_num: config['zone_switch'] 
            for zone_num, config in self.zones.items()
        }
        
    def get_zone_sensors(self, zone_num: int) -> Dict[str, List[str]]:
        """Get all sensors for a specific zone.
        
        Args:
            zone_num: Zone number
            
        Returns:
            Dict with 'vwc' and 'ec' sensor lists
        """
        zone = self.zones.get(zone_num, {})
        
        vwc_sensors = []
        if zone.get('vwc_front'):
            vwc_sensors.append(zone['vwc_front'])
        if zone.get('vwc_back'):
            vwc_sensors.append(zone['vwc_back'])
            
        ec_sensors = []
        if zone.get('ec_front'):
            ec_sensors.append(zone['ec_front'])
        if zone.get('ec_back'):
            ec_sensors.append(zone['ec_back'])
            
        return {
            'vwc': vwc_sensors,
            'ec': ec_sensors
        }
        
    def get_hardware_config(self) -> Dict[str, str]:
        """Get hardware configuration.
        
        Returns:
            Dict of hardware entity IDs
        """
        return self.hardware_config.copy()
        
    def validate_entities(self, hass) -> Tuple[bool, List[str]]:
        """Validate all configured entities exist in Home Assistant.
        
        Args:
            hass: Home Assistant instance
            
        Returns:
            Tuple of (all_valid, list_of_missing_entities)
        """
        missing_entities = []
        
        # Check hardware entities
        for name, entity_id in self.hardware_config.items():
            if entity_id and not hass.states.get(entity_id):
                missing_entities.append(f"{name}: {entity_id}")
                
        # Check zone entities
        for zone_num, zone_config in self.zones.items():
            for key, entity_id in zone_config.items():
                if key != 'zone_number' and entity_id and not hass.states.get(entity_id):
                    missing_entities.append(f"Zone {zone_num} {key}: {entity_id}")
                    
        return len(missing_entities) == 0, missing_entities