"""Crop Steering System select entities."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, CONF_NUM_ZONES, PHASES, STEERING_MODES, CROP_TYPES, GROWTH_STAGES, RECIPE_STAGES, RECIPE_PARAMS, SOFTWARE_VERSION
from .room import room_prefix
from .recipe import get_manager

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

ZONE_PHASE_OVERRIDE_OPTIONS = ["Auto", "P0", "P1", "P2", "P3"]

# Note: Light schedules are now system-wide, not per-zone

SELECT_DESCRIPTIONS = [
    SelectEntityDescription(
        key="crop_type",
        name="Crop Type",
        icon="mdi:sprout",
        options=CROP_TYPES,  # Use constant from const.py
    ),
    SelectEntityDescription(
        key="growth_stage",
        name="Growth Stage",
        icon="mdi:timeline",
        options=GROWTH_STAGES,  # Use constant from const.py
    ),
    SelectEntityDescription(
        key="steering_mode",
        name="Steering Mode",
        icon="mdi:steering",
        options=STEERING_MODES,  # Use constant from const.py
    ),
    SelectEntityDescription(
        key="irrigation_phase",
        name="Irrigation Phase",
        icon="mdi:water-circle",
        options=PHASES,  # Use constant from const.py (P0-P3 only)
    ),
    # Named-stage recipe: picking a stage applies its setpoints to the zones.
    SelectEntityDescription(
        key="recipe_stage",
        name="Recipe Stage",
        icon="mdi:format-list-bulleted-type",
        options=RECIPE_STAGES,
    ),
    # RootSense v3 — derived view of `number.crop_steering_steering_intent`.
    # Read-mostly: kept as a Select (not a Sensor) so dashboards can use it
    # in glance/entity cards without extra templating. The IntentResolver in
    # the engine updates this on every intent
    # change. Operators who change it manually trigger a corresponding
    # intent slider update via the existing automation path.
    SelectEntityDescription(
        key="steering_mode_derived",
        name="Steering Mode (derived)",
        icon="mdi:tune-vertical-variant",
        options=["Generative", "Mixed-generative", "Balanced",
                 "Mixed-vegetative", "Vegetative"],
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
                name=f"Crop Steering Zone {zone_num} Group",
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
                name=f"Crop Steering Zone {zone_num} Priority",
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
                name=f"Crop Steering Zone {zone_num} Crop Profile",
                options=ZONE_CROP_PROFILES,
                icon="mdi:sprout",
            ),
            zone_num=zone_num
        ))

        # Zone Phase Override (native per-zone phase forcing: Auto/P0-P3) — RootSense v3.
        selects.append(CropSteeringSelect(
            entry,
            SelectEntityDescription(
                key=f"zone_{zone_num}_phase_override",
                name=f"Zone {zone_num} Phase Override",
                options=ZONE_PHASE_OVERRIDE_OPTIONS,
                icon="mdi:state-machine",
            ),
            zone_num=zone_num
        ))

        # Zone Steering Mode (per-row Vegetative/Generative; the engine falls back to global).
        # Retained from the lean branch: the master app's _zone_is_vegetative() reads this
        # for per-zone veg/gen EC-target selection.
        selects.append(CropSteeringSelect(
            entry,
            SelectEntityDescription(
                key=f"zone_{zone_num}_steering_mode",
                name=f"Crop Steering Zone {zone_num} Steering Mode",
                options=["Vegetative", "Generative"],
                icon="mdi:steering",
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
        self._attr_object_id = f"{DOMAIN}_{room_prefix(entry)}{description.key}"
        self._attr_options = description.options
        
        # Set default values based on entity type
        if "group" in description.key:
            self._attr_current_option = "Ungrouped"
        elif "priority" in description.key:
            self._attr_current_option = "Normal"
        elif "crop_profile" in description.key:
            self._attr_current_option = "Follow Main"
        elif "phase_override" in description.key:
            self._attr_current_option = "Auto"
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
        # The recipe stage's source of truth is the server-side recipe Store, not
        # the restored entity state — reflect the loaded recipe's active stage.
        if self.entity_description.key == "recipe_stage":
            mgr = get_manager(self.hass, self._entry)
            if mgr is not None and mgr.active_stage in self.options:
                self._attr_current_option = mgr.active_stage

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        if self._zone_num is not None:
            # Zone-specific device
            return DeviceInfo(
                identifiers={(DOMAIN, f"{self._entry.entry_id}_zone_{self._zone_num}")},
                name=f"Crop Steering Zone {self._zone_num}",
                manufacturer="Home Assistant Community",
                model="Zone Controller",
                sw_version=SOFTWARE_VERSION,
                via_device=(DOMAIN, self._entry.entry_id),
            )
        else:
            # Main device
            return DeviceInfo(
                identifiers={(DOMAIN, self._entry.entry_id)},
                name="Crop Steering",
                manufacturer="Home Assistant Community",
                model="Professional Irrigation Controller",
                sw_version=SOFTWARE_VERSION,
            )

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option in self.options:
            self._attr_current_option = option
            self.async_write_ha_state()
            # The irrigation-phase select is a manual override: drive the engine by firing
            # the same event the transition_phase service uses (forced => applies from any
            # phase). Without this, changing the select did nothing to the controller.
            if getattr(self.entity_description, "key", None) == "irrigation_phase":
                self.hass.bus.async_fire(
                    "crop_steering_phase_transition",
                    {"target_phase": option, "reason": "Manual (phase select)", "forced": True},
                )
            # Selecting a recipe stage applies its setpoints to the zone numbers.
            elif self.entity_description.key == "recipe_stage":
                mgr = get_manager(self.hass, self._entry)
                if mgr is not None:
                    await mgr.async_apply(option)

    @property
    def extra_state_attributes(self):
        """Expose the full recipe table on the recipe_stage select so the
        dashboard can read it (and edit via the save_recipe service)."""
        if self.entity_description.key != "recipe_stage":
            return None
        mgr = get_manager(self.hass, self._entry)
        if mgr is None:
            return None
        return {
            "params": RECIPE_PARAMS,
            "stages": mgr.recipe.get("stages", {}),
            "active_stage": mgr.active_stage,
        }

    @property
    def available(self) -> bool:
        """Return if select is available."""
        return True