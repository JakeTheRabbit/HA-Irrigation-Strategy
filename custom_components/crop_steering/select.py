"""Crop Steering System select entities."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, CONF_NUM_ZONES, PHASES, STEERING_MODES, CROP_TYPES, SOFTWARE_VERSION

_LOGGER = logging.getLogger(__name__)

# Zone grouping options
ZONE_GROUP_OPTIONS = [
    "Ungrouped",
    "Group A", 
    "Group B",
    "Group C",
    "Group D"
]

# Zone priority levels
ZONE_PRIORITY_OPTIONS = [
    "Critical",
    "High",
    "Normal", 
    "Low"
]

# Zone-specific crop profiles
ZONE_CROP_PROFILES = [
    "Follow Main",
    "Cannabis_Athena",
    "Cannabis_Indica_Dominant",
    "Cannabis_Sativa_Dominant", 
    "Cannabis_Balanced_Hybrid",
    "Tomato_Hydroponic",
    "Lettuce_Leafy_Greens",
    "Custom"
]

# Note: Light schedules are now system-wide, not per-zone

SELECT_DESCRIPTIONS = [
    SelectEntityDescription(
        key="crop_type",
        name="Crop Type",
        icon="mdi:sprout",
        options=[
            "Cannabis_Athena",
            "Cannabis_Hybrid", 
            "Cannabis_Indica",
            "Cannabis_Sativa",
            "Tomato",
            "Lettuce",
            "Basil",
            "Custom"
        ],
    ),
    SelectEntityDescription(
        key="growth_stage",
        name="Growth Stage",
        icon="mdi:timeline",
        options=["Vegetative", "Generative", "Transition"],
    ),
    SelectEntityDescription(
        key="steering_mode",
        name="Steering Mode",
        icon="mdi:steering",
        options=["Vegetative", "Generative"],
    ),
    SelectEntityDescription(
        key="irrigation_phase",
        name="Irrigation Phase",
        icon="mdi:water-circle",
        options=["P0", "P1", "P2", "P3", "Manual"],
    ),
]

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Crop Steering select entities."""
    selects = []
    
    # Add main select entities
    for description in SELECT_DESCRIPTIONS:
        selects.append(CropSteeringSelect(entry, description))
    
    # Get number of zones from config
    config_data = hass.data[DOMAIN][entry.entry_id]
    num_zones = config_data.get(CONF_NUM_ZONES, 1)
    
    # Add zone-specific select entities
    for zone_num in range(1, num_zones + 1):
        # Zone Group
        selects.append(CropSteeringSelect(
            entry,
            SelectEntityDescription(
                key=f"zone_{zone_num}_group",
                name=f"Zone {zone_num} Group",
                options=ZONE_GROUP_OPTIONS,
                icon="mdi:group",
            ),
            zone_num=zone_num
        ))
        
        # Zone Priority
        selects.append(CropSteeringSelect(
            entry,
            SelectEntityDescription(
                key=f"zone_{zone_num}_priority",
                name=f"Zone {zone_num} Priority",
                options=ZONE_PRIORITY_OPTIONS,
                icon="mdi:priority-high",
            ),
            zone_num=zone_num
        ))
        
        # Zone Crop Profile
        selects.append(CropSteeringSelect(
            entry,
            SelectEntityDescription(
                key=f"zone_{zone_num}_crop_profile",
                name=f"Zone {zone_num} Crop Profile",
                options=ZONE_CROP_PROFILES,
                icon="mdi:sprout",
            ),
            zone_num=zone_num
        ))
    
    async_add_entities(selects)

class CropSteeringSelect(SelectEntity, RestoreEntity):
    """Crop Steering select entity with state restoration."""

    def __init__(
        self,
        entry: ConfigEntry,
        description: SelectEntityDescription,
        zone_num: int = None,
    ) -> None:
        """Initialize the select entity."""
        self.entity_description = description
        self._entry = entry
        self._zone_num = zone_num
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{description.key}"
        self._attr_name = description.name
        # Set object_id to include crop_steering prefix for entity_id generation
        self._attr_object_id = f"{DOMAIN}_{description.key}"
        self._attr_options = description.options
        
        # Set default values based on entity type
        if "group" in description.key:
            self._attr_current_option = "Ungrouped"
        elif "priority" in description.key:
            self._attr_current_option = "Normal"
        elif "crop_profile" in description.key:
            self._attr_current_option = "Follow Main"
        elif "schedule" in description.key:
            self._attr_current_option = "Main Schedule"
        elif description.key == "growth_stage":
            self._attr_current_option = "Vegetative"
        else:
            self._attr_current_option = description.options[0] if description.options else None

    async def async_added_to_hass(self) -> None:
        """Restore state when added to hass."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state in self.options:
                self._attr_current_option = last_state.state

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        if self._zone_num is not None:
            # Zone-specific device
            return DeviceInfo(
                identifiers={(DOMAIN, f"{self._entry.entry_id}_zone_{self._zone_num}")},
                name=f"Zone {self._zone_num}",
                manufacturer="Home Assistant Community",
                model="Zone Controller",
                sw_version="2.3.0",
                via_device=(DOMAIN, self._entry.entry_id),
            )
        else:
            # Main device
            return DeviceInfo(
                identifiers={(DOMAIN, self._entry.entry_id)},
                name="Crop Steering System",
                manufacturer="Home Assistant Community",
                model="Professional Irrigation Controller", 
                sw_version="2.3.0",
            )

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option in self.options:
            self._attr_current_option = option
            self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return if select is available."""
        return True