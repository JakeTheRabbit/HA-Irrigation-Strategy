"""Crop Steering System switches."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, CONF_NUM_ZONES

_LOGGER = logging.getLogger(__name__)

# Base switch descriptions (non-zone specific)
BASE_SWITCH_DESCRIPTIONS = [
    SwitchEntityDescription(
        key="ec_stacking_enabled",
        name="EC Stacking Enabled",
        icon="mdi:chemistry-bottle",
    ),
    SwitchEntityDescription(
        key="system_enabled",
        name="System Enabled",
        icon="mdi:power",
    ),
    SwitchEntityDescription(
        key="auto_irrigation_enabled",
        name="Auto Irrigation Enabled",
        icon="mdi:auto-mode",
    ),
    SwitchEntityDescription(
        key="analytics_enabled",
        name="Analytics Enabled",
        icon="mdi:chart-line",
    ),
]


def create_zone_switch_descriptions(num_zones: int) -> list[SwitchEntityDescription]:
    """Create switch descriptions for configured zones."""
    zone_switches = []
    
    for zone_num in range(1, num_zones + 1):
        zone_switches.append(
            SwitchEntityDescription(
                key=f"zone_{zone_num}_enabled",
                name=f"Zone {zone_num} Enabled",
                icon="mdi:water-pump",
            )
        )
        
        # Add per-zone manual override switch
        zone_switches.append(
            SwitchEntityDescription(
                key=f"zone_{zone_num}_manual_override",
                name=f"Zone {zone_num} Manual Override",
                icon="mdi:hand-water",
            )
        )
    
    return zone_switches

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Crop Steering switches."""
    switches = []
    
    # Get number of zones from config
    config_data = hass.data[DOMAIN][entry.entry_id]
    num_zones = config_data.get(CONF_NUM_ZONES, 1)
    
    # Add base switches
    for description in BASE_SWITCH_DESCRIPTIONS:
        switches.append(CropSteeringSwitch(entry, description))
    
    # Add zone-specific switches
    zone_switches = create_zone_switch_descriptions(num_zones)
    for description in zone_switches:
        switches.append(CropSteeringSwitch(entry, description))
    
    async_add_entities(switches)

class CropSteeringSwitch(SwitchEntity, RestoreEntity):
    """Crop Steering switch with state restoration."""

    def __init__(
        self,
        entry: ConfigEntry,
        description: SwitchEntityDescription,
    ) -> None:
        """Initialize the switch."""
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{description.key}"
        self._attr_name = description.name
        # Set object_id to include crop_steering prefix for entity_id generation
        self._attr_object_id = f"{DOMAIN}_{description.key}"
        
        # Set default states based on switch type
        if description.key == "system_enabled":
            self._attr_is_on = True  # System enabled by default
        elif description.key == "auto_irrigation_enabled":
            self._attr_is_on = True  # Auto irrigation enabled by default
        elif "zone_" in description.key and "_enabled" in description.key:
            self._attr_is_on = True  # Zones enabled by default
        else:
            self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Restore state when added to hass."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_is_on = last_state.state == "on"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Crop Steering System",
            manufacturer="Home Assistant Community", 
            model="Professional Irrigation Controller",
            sw_version="2.0.0",
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        self._attr_is_on = False
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return if switch is available."""
        return True