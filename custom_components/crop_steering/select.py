"""Crop Steering System select entities."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    DOMAIN,
    CONF_NUM_ZONES,
    PHASES,
    STEERING_MODES,
    GROWTH_STAGES,
    RECIPE_STAGES,
    RECIPE_PARAMS,
    SOFTWARE_VERSION,
    SET_PHASE_OPTIONS,
)
from .room import restored_state_is_ours, room_prefix, zone_device_name
from .recipe import get_manager

_LOGGER = logging.getLogger(__name__)

SELECT_DESCRIPTIONS = [
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
        # Zone Steering Mode (per-row Vegetative/Generative; the engine falls back to global).
        # Retained from the lean branch: the master app's _zone_is_vegetative() reads this
        # for per-zone veg/gen EC-target selection.
        selects.append(
            CropSteeringSelect(
                entry,
                SelectEntityDescription(
                    key=f"zone_{zone_num}_steering_mode",
                    name=f"Crop Steering Zone {zone_num} Steering Mode",
                    options=["Vegetative", "Generative"],
                    icon="mdi:steering",
                ),
                zone_num=zone_num,
            )
        )

        # Move the zone to a phase by hand. The controller applies a choice once, within a
        # minute, and sets this back to Keep; its own rules carry on from that phase.
        selects.append(
            CropSteeringSelect(
                entry,
                SelectEntityDescription(
                    key=f"zone_{zone_num}_set_phase",
                    name=f"Zone {zone_num} Set Phase",
                    options=SET_PHASE_OPTIONS,
                    icon="mdi:state-machine",
                ),
                zone_num=zone_num,
            )
        )

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
        # Home Assistant ignores _attr_object_id and would name a NEW entity from its friendly name
        # (number.p1_target_vwc). Existing installs keep the id the registry already holds.
        self.entity_id = f"select.{self._attr_object_id}"
        self._attr_options = description.options

        # Set default values based on entity type
        if description.key == "growth_stage":
            self._attr_current_option = "Vegetative"
        else:
            self._attr_current_option = (
                description.options[0] if description.options else None
            )

    async def async_added_to_hass(self) -> None:
        """Restore state when added to hass."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        # A state left behind by a DELETED room is not this room's.
        if last_state is not None and restored_state_is_ours(self._entry, last_state):
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
                name=zone_device_name(self._entry, self._zone_num),
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
            # Announce a manual phase pick on the event bus for automations. The controller
            # keeps each zone's phase itself and does not read this select.
            if getattr(self.entity_description, "key", None) == "irrigation_phase":
                self.hass.bus.async_fire(
                    "crop_steering_phase_transition",
                    {
                        "target_phase": option,
                        "reason": "Manual (phase select)",
                        "forced": True,
                    },
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
