"""Crop Steering System button entities."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, CONF_NUM_ZONES, SOFTWARE_VERSION

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Crop Steering button entities."""
    buttons = []

    config_data = hass.data[DOMAIN][entry.entry_id]
    num_zones = config_data.get(CONF_NUM_ZONES, 1)

    for zone_num in range(1, num_zones + 1):
        buttons.append(CropSteeringTriggerButton(entry, zone_num))

    async_add_entities(buttons)


class CropSteeringTriggerButton(ButtonEntity):
    """Button to trigger a single irrigation shot for a zone."""

    def __init__(self, entry: ConfigEntry, zone_num: int) -> None:
        """Initialize the button entity."""
        self._entry = entry
        self._zone_num = zone_num
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_zone_{zone_num}_trigger_shot"
        self._attr_name = f"Zone {zone_num} Trigger Shot"
        self._attr_object_id = f"{DOMAIN}_zone_{zone_num}_trigger_shot"
        self._attr_icon = "mdi:water-pump"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry.entry_id}_zone_{self._zone_num}")},
            name=f"Zone {self._zone_num}",
            manufacturer="Home Assistant Community",
            model="Zone Controller",
            sw_version=SOFTWARE_VERSION,
            via_device=(DOMAIN, self._entry.entry_id),
        )

    async def async_press(self) -> None:
        """Handle button press — fire event for AppDaemon to pick up."""
        self.hass.bus.async_fire(
            "crop_steering_trigger_zone_shot",
            {"zone": self._zone_num, "source": "button"},
        )
        _LOGGER.info("Trigger shot fired for zone %d", self._zone_num)
