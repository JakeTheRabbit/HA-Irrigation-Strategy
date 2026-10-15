"""A "Test Shot" button for each zone.

Pressing one does nothing here. Home Assistant records when it was pressed as the button's state, and
the controller app, which reads that, acts the next time it looks: it waters that zone for 10 seconds,
to check that watering works. It is a request, not a command: the controller only acts while the
room's watering switch is on and nothing else is in the way, and says so if it cannot.
"""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_NUM_ZONES, DOMAIN, SOFTWARE_VERSION
from .room import room_prefix, zone_device_name

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    zones = hass.data[DOMAIN][entry.entry_id].get(CONF_NUM_ZONES, 1)
    async_add_entities(
        CropSteeringTestShotButton(entry, zone) for zone in range(1, zones + 1)
    )


class CropSteeringTestShotButton(ButtonEntity):
    """A zone's Test Shot: the controller app waters the zone for 10 seconds, through every check a
    shot passes but a held grow plan's. Its water counts toward the day's; it is not a ramp shot.
    """

    _attr_icon = "mdi:water-check-outline"

    def __init__(self, entry: ConfigEntry, zone: int) -> None:
        self._entry, self._zone = entry, zone
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_zone_{zone}_test_shot"
        self._attr_name = f"Zone {zone} Test Shot"
        self._attr_object_id = f"{DOMAIN}_{room_prefix(entry)}zone_{zone}_test_shot"
        # An explicit entity_id is the suggestion Home Assistant uses at first registration.
        self.entity_id = f"button.{self._attr_object_id}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry.entry_id}_zone_{self._zone}")},
            name=zone_device_name(self._entry, self._zone),
            manufacturer="Home Assistant Community",
            model="Zone Controller",
            sw_version=SOFTWARE_VERSION,
            via_device=(DOMAIN, self._entry.entry_id),
        )

    async def async_press(self) -> None:
        _LOGGER.info(
            "Test shot requested for zone %s of %s",
            self._zone,
            room_prefix(self._entry) or "the room",
        )
