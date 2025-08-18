"""The Crop Steering System integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR, 
    Platform.SWITCH, 
    Platform.SELECT, 
    Platform.NUMBER,
    Platform.INPUT_BOOLEAN,
    Platform.INPUT_NUMBER,
]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Crop Steering System from a config entry."""
    _LOGGER.info("Setting up Crop Steering System")
    
    # Set up the integration data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data
    
    # Note: Package installation removed - system now uses AppDaemon + integration architecture
    # No package files needed as per v2.0 architecture
    
    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Set up services
    await async_setup_services(hass)
    
    return True

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
