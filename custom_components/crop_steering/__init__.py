"""The Crop Steering System integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, CONF_NUM_ZONES
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.SELECT, Platform.NUMBER]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Crop Steering System from a config entry."""
    _LOGGER.info("Setting up Crop Steering System v2.3.1")

    # Set up the integration data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data

    # Create test helper entities for hardware simulation
    await _create_test_helpers(hass, entry)

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Set up services
    await async_setup_services(hass)

    _LOGGER.info("Crop Steering System setup complete")

    return True


async def _create_test_helpers(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Create test helper entities for hardware simulation."""
    config_data = entry.data
    num_zones = config_data.get(CONF_NUM_ZONES, 1)

    _LOGGER.info(f"Creating test helper entities for {num_zones} zones")

    # Define test helper specifications
    test_booleans = [
        # Pumps & Valves
        ("water_pump_1", "Water Pump 1", "mdi:water-pump"),
        ("water_pump_2", "Water Pump 2", "mdi:water-pump"),
        ("nutrient_pump_a", "Nutrient Pump A", "mdi:flask"),
        ("nutrient_pump_b", "Nutrient Pump B", "mdi:flask"),
        ("nutrient_pump_c", "Nutrient Pump C", "mdi:flask"),
        ("ph_up_pump", "pH Up Pump", "mdi:ph"),
        ("ph_down_pump", "pH Down Pump", "mdi:ph"),
        ("main_water_valve", "Main Water Valve", "mdi:valve"),
        ("recirculation_valve", "Recirculation Valve", "mdi:valve-closed"),
        ("drain_valve", "Drain Valve", "mdi:pipe-valve"),
        # Status Indicators
        ("system_ready", "System Ready", "mdi:check-circle"),
        ("emergency_stop", "Emergency Stop", "mdi:stop-circle"),
        ("auto_mode", "Auto Mode", "mdi:auto-mode"),
        ("manual_override", "Manual Override", "mdi:hand-water"),
        ("night_mode", "Night Mode", "mdi:weather-night"),
        ("maintenance_mode", "Maintenance Mode", "mdi:wrench"),
        ("flush_mode", "Flush Mode", "mdi:water-sync"),
        ("dose_mode", "Dose Mode", "mdi:needle"),
        # Safety Systems
        ("flow_sensor_ok", "Flow Sensor OK", "mdi:waves"),
        ("pressure_sensor_ok", "Pressure Sensor OK", "mdi:gauge"),
        ("leak_detection", "Leak Detection", "mdi:water-alert"),
        ("pump_overload", "Pump Overload Protection", "mdi:alert-circle"),
        # Communication
        ("modbus_connected", "Modbus Connected", "mdi:lan-connect"),
        ("wifi_connected", "WiFi Connected", "mdi:wifi"),
        ("sensor_hub_online", "Sensor Hub Online", "mdi:access-point"),
        ("controller_responsive", "Controller Responsive", "mdi:chip"),
    ]

    # Add zone-specific booleans
    for zone in range(1, num_zones + 1):
        test_booleans.extend([
            (f"zone_{zone}_valve", f"Zone {zone} Valve", "mdi:valve"),
            (f"zone_{zone}_enabled", f"Zone {zone} Enabled", "mdi:check-circle"),
        ])

    test_numbers = [
        # Tank Sensors
        ("tank_water_level", "Tank Water Level", 0, 100, 1, "%", "mdi:gauge"),
        ("tank_ph", "Tank pH", 0, 14, 0.1, "", "mdi:ph"),
        ("tank_ec", "Tank EC", 0, 10, 0.1, "mS/cm", "mdi:lightning-bolt"),
        ("tank_temperature", "Tank Temperature", 0, 40, 0.1, "°C", "mdi:thermometer"),
        ("tank_flow_rate", "Tank Flow Rate", 0, 100, 0.1, "L/min", "mdi:waves"),
        ("tank_pressure", "Tank Pressure", 0, 10, 0.1, "bar", "mdi:gauge"),
        # Environmental
        ("ambient_temperature", "Ambient Temperature", 0, 50, 0.1, "°C", "mdi:thermometer"),
        ("ambient_humidity", "Ambient Humidity", 0, 100, 1, "%", "mdi:water-percent"),
        ("light_intensity", "Light Intensity", 0, 100000, 100, "lux", "mdi:weather-sunny"),
        # System Performance
        ("pump_frequency", "Pump Frequency", 0, 60, 0.1, "Hz", "mdi:sine-wave"),
        ("valve_position", "Valve Position", 0, 100, 1, "%", "mdi:valve"),
        ("system_pressure", "System Pressure", 0, 10, 0.1, "bar", "mdi:gauge"),
    ]

    # Add zone-specific numbers
    for zone in range(1, num_zones + 1):
        test_numbers.extend([
            (f"zone_{zone}_vwc_front", f"Zone {zone} VWC Front", 0, 100, 1, "%", "mdi:water-percent"),
            (f"zone_{zone}_vwc_back", f"Zone {zone} VWC Back", 0, 100, 1, "%", "mdi:water-percent"),
            (f"zone_{zone}_ec_front", f"Zone {zone} EC Front", 0, 10, 0.1, "mS/cm", "mdi:lightning-bolt"),
            (f"zone_{zone}_ec_back", f"Zone {zone} EC Back", 0, 10, 0.1, "mS/cm", "mdi:lightning-bolt"),
            (f"zone_{zone}_temperature", f"Zone {zone} Temperature", 0, 40, 0.1, "°C", "mdi:thermometer"),
        ])

    # Create input_boolean entities
    for entity_id, name, icon in test_booleans:
        full_entity_id = f"input_boolean.{entity_id}"

        # Check if entity already exists
        if hass.states.get(full_entity_id) is None:
            try:
                await hass.services.async_call(
                    "input_boolean",
                    "create",
                    {
                        "name": name,
                        "icon": icon,
                    },
                    blocking=True,
                )
                _LOGGER.debug(f"Created test helper: {full_entity_id}")
            except Exception as e:
                _LOGGER.warning(f"Could not create {full_entity_id}: {e}")

    # Create input_number entities
    for entity_id, name, min_val, max_val, step, unit, icon in test_numbers:
        full_entity_id = f"input_number.{entity_id}"

        # Check if entity already exists
        if hass.states.get(full_entity_id) is None:
            try:
                service_data = {
                    "name": name,
                    "min": min_val,
                    "max": max_val,
                    "step": step,
                    "icon": icon,
                    "mode": "slider",
                }
                if unit:
                    service_data["unit_of_measurement"] = unit

                await hass.services.async_call(
                    "input_number",
                    "create",
                    service_data,
                    blocking=True,
                )
                _LOGGER.debug(f"Created test helper: {full_entity_id}")
            except Exception as e:
                _LOGGER.warning(f"Could not create {full_entity_id}: {e}")

    _LOGGER.info(f"Test helper creation complete: {len(test_booleans)} booleans, {len(test_numbers)} numbers")

# Note: _install_package_files function removed in v2.0 architecture
# System now uses AppDaemon modules + integration entities only
# No package YAML files needed

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        
    # Unload services
    await async_unload_services(hass)
    
    return unload_ok
