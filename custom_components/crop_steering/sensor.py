"""Crop Steering System sensors."""

from __future__ import annotations

import logging
import math
import re
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoredExtraData, RestoreEntity

from .const import (
    DOMAIN,
    CONF_NUM_ZONES,
    DEFAULT_EC_RATIO,
    DEFAULT_EC_FALLBACK,
    VWC_ADJUSTMENT_PERCENT,
    SOFTWARE_VERSION,
    PROBE_FAR,
    PROBE_RANGE,
    PROBE_STALE_SECONDS,
    SUBSTRATES,
)
from .room import room_prefix, build_engine_config
from . import stock
from .calculations import ShotCalculator, ec_type_key, fuse_probes
from .probe_offsets import read as read_probe
from .units import to_native
from .zone_status import (
    app_phase_entity,
    mirrored_phase,
    mirrored_status,
    status_app_entity,
)

_LOGGER = logging.getLogger(__name__)

# The configured shot each shot-duration sensor times: P1's first ramp shot, P2's maintenance shot,
# and P3's emergency (rescue) shot.
SHOT_SIZE_KEYS = {
    "p1_shot_duration_seconds": "p1_initial_shot_size",
    "p2_shot_duration_seconds": "p2_shot_size",
    "p3_shot_duration_seconds": "p3_emergency_shot_size",
}


# Base sensor descriptions (non-zone specific)
BASE_SENSOR_DESCRIPTIONS = [
    SensorEntityDescription(
        key="current_phase",
        name="Current phase",
        icon="mdi:water-circle",
    ),
    # No dryback sensor here: the controller publishes each zone's live dryback as
    # sensor.crop_steering_<prefix>zone_N_dryback_app (relative % of the peak, with the drop in
    # VWC points in its attributes). A descriptor here whose value was always None kept writing
    # `unknown` over the old engine's value, so it was removed.
    # Critical Template Calculations - Ported from packages
    SensorEntityDescription(
        key="p1_shot_duration_seconds",
        name="P1 shot duration",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        icon="mdi:timer-sand",
    ),
    SensorEntityDescription(
        key="p2_shot_duration_seconds",
        name="P2 shot duration",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        icon="mdi:timer-sand",
    ),
    SensorEntityDescription(
        key="p3_shot_duration_seconds",
        name="Rescue shot duration",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        icon="mdi:timer-sand",
    ),
    SensorEntityDescription(
        key="ec_ratio",
        name="EC ratio",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:division",
    ),
    SensorEntityDescription(
        key="p2_vwc_threshold_adjusted",
        name="Adjusted re-water point",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:water-alert",
    ),
    SensorEntityDescription(
        key="configured_avg_vwc",
        name="Mean VWC of all zones",
        device_class=SensorDeviceClass.MOISTURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:water-percent",
    ),
    SensorEntityDescription(
        key="configured_avg_ec",
        name="Mean EC of all zones",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="mS/cm",
        icon="mdi:flash",
    ),
]


def create_zone_sensor_descriptions(num_zones: int) -> list[SensorEntityDescription]:
    """Create sensor descriptions for configured zones."""
    zone_sensors = []

    for zone_num in range(1, num_zones + 1):
        # VWC sensor for each zone
        zone_sensors.append(
            SensorEntityDescription(
                key=f"vwc_zone_{zone_num}",
                name=f"Zone {zone_num} VWC",
                device_class=SensorDeviceClass.MOISTURE,
                state_class=SensorStateClass.MEASUREMENT,
                native_unit_of_measurement=PERCENTAGE,
                icon="mdi:water-percent",
            )
        )

        # EC sensor for each zone
        zone_sensors.append(
            SensorEntityDescription(
                key=f"ec_zone_{zone_num}",
                name=f"Zone {zone_num} EC",
                state_class=SensorStateClass.MEASUREMENT,
                native_unit_of_measurement="mS/cm",
                icon="mdi:lightning-bolt",
            )
        )

        # Zone status sensor
        zone_sensors.append(
            SensorEntityDescription(
                key=f"zone_{zone_num}_status",
                name=f"Zone {zone_num} status",
                icon="mdi:information",
            )
        )

        # Zone last irrigation time
        zone_sensors.append(
            SensorEntityDescription(
                key=f"zone_{zone_num}_last_irrigation",
                name=f"Zone {zone_num} last shot",
                device_class=SensorDeviceClass.TIMESTAMP,
                icon="mdi:history",
            )
        )

        # Zone water usage tracking
        zone_sensors.append(
            SensorEntityDescription(
                key=f"zone_{zone_num}_daily_water_usage",
                name=f"Zone {zone_num} water today",
                device_class=SensorDeviceClass.VOLUME,
                state_class=SensorStateClass.TOTAL_INCREASING,
                native_unit_of_measurement=UnitOfVolume.LITERS,
                icon="mdi:water",
            )
        )

        zone_sensors.append(
            SensorEntityDescription(
                key=f"zone_{zone_num}_weekly_water_usage",
                name=f"Zone {zone_num} water over seven grow-days",
                device_class=SensorDeviceClass.VOLUME,
                # Rolling windows decrease when old grow-days leave the total.
                state_class=SensorStateClass.TOTAL,
                native_unit_of_measurement=UnitOfVolume.LITERS,
                icon="mdi:water-outline",
            )
        )

        zone_sensors.append(
            SensorEntityDescription(
                key=f"zone_{zone_num}_irrigation_count_today",
                name=f"Zone {zone_num} shots today",
                state_class=SensorStateClass.TOTAL_INCREASING,
                icon="mdi:counter",
            )
        )

    return zone_sensors


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Crop Steering sensors."""
    sensors = []

    # Get number of zones from config
    config_data = hass.data[DOMAIN][entry.entry_id]
    num_zones = config_data.get(CONF_NUM_ZONES, 1)
    zones_config = config_data.get("zones", {})
    hardware_config = config_data.get("hardware", {})

    # Use base sensors - no duplication needed
    sensor_descriptions = BASE_SENSOR_DESCRIPTIONS.copy()

    # Add zone-specific sensors
    zone_sensors = create_zone_sensor_descriptions(num_zones)
    sensor_descriptions.extend(zone_sensors)

    # Create sensor entities
    for description in sensor_descriptions:
        cls = (
            CropSteeringZoneStatusSensor
            if re.fullmatch(r"zone_\d+_status", description.key)
            else (
                CropSteeringCurrentPhaseSensor
                if description.key == "current_phase"
                else (
                    CropSteeringProbeSensor
                    if re.fullmatch(r"(vwc|ec)_zone_\d+", description.key)
                    else CropSteeringSensor
                )
            )
        )
        sensors.append(cls(entry, description, zones_config, hardware_config))

    # Publish this room's engine config (hardware map + kill switch + zones) so the
    # f2-control add-on can discover and drive it — multi-room Stage 2.
    sensors.append(
        CropSteeringEngineConfigSensor(entry, num_zones, zones_config, hardware_config)
    )
    sensors.append(CropSteeringStockSensor(entry))
    sensors.append(CropSteeringDosingConfigSensor(entry))
    sensors.append(CropSteeringBrainQuestionsSensor(entry))
    sensors.append(CropSteeringBrainPromptConfigSensor(entry))
    sensors.append(CropSteeringDisplaySensor(entry))
    sensors.extend(
        CropSteeringFeedCorrectedSensor(entry, probe)
        for probe in ("feed_ph", "feed_ec")
    )

    async_add_entities(sensors)


class CropSteeringEngineConfigSensor(SensorEntity):
    """Publishes this room's config (pump/mainline/valves, kill switch, feed probes, zones)
    as attributes so the f2-control add-on can DISCOVER and drive the room — the add-on
    cannot read the integration's config entry directly. Since add-on 0.11.0 the DEFAULT
    room's hardware map comes from the prefix-"" descriptor too (explicit add-on options
    still take precedence), so this sensor is what makes a fresh install actuate at all.
    """

    _attr_should_poll = False
    _attr_icon = "mdi:cog-transfer-outline"

    def __init__(self, entry, num_zones, zones_config, hardware_config):
        self._entry = entry
        self._num_zones = num_zones
        self._zones = zones_config or {}
        self._hw = hardware_config or {}
        self._prefix = room_prefix(entry)
        self._slug = entry.data.get("room_slug", "default")
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_engine_config"
        self._attr_name = "Engine config"
        self._attr_object_id = f"{DOMAIN}_{self._prefix}engine_config"
        # Home Assistant ignores _attr_object_id; the controller finds a room by THIS id.
        self.entity_id = f"sensor.{self._attr_object_id}"
        self._substrate_select = f"select.{DOMAIN}_{self._prefix}substrate"

    async def async_added_to_hass(self) -> None:
        from homeassistant.helpers.dispatcher import async_dispatcher_connect

        from .calibration import SIGNAL as CALIBRATION_SIGNAL

        await super().async_added_to_hass()
        # Republish when the room's substrate is chosen, so the controller is told.
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._substrate_select], self._substrate_changed
            )
        )
        # ... and when a feed probe calibration is applied or reverted (feed_calibration).
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{CALIBRATION_SIGNAL}_{self._entry.entry_id}",
                self.async_write_ha_state,
            )
        )

    def _feed_calibration(self) -> dict:
        hass = getattr(self, "hass", None)
        manager = (
            hass.data.get(DOMAIN, {}).get("_calibration", {}).get(self._entry.entry_id)
            if hass
            else None
        )
        return manager.feed_calibration() if manager is not None else {}

    @callback
    def _substrate_changed(self, _event) -> None:
        self.async_write_ha_state()

    def _substrate(self) -> str:
        hass = getattr(self, "hass", None)
        state = hass.states.get(self._substrate_select) if hass else None
        return (
            state.state
            if state is not None and state.state in SUBSTRATES
            else "generic"
        )

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Crop Steering System",
            manufacturer="Home Assistant Community",
            model="Professional Irrigation Controller",
            sw_version=SOFTWARE_VERSION,
        )

    @property
    def native_value(self) -> Any:
        return self._slug

    @property
    def extra_state_attributes(self) -> dict:
        return build_engine_config(
            self._prefix,
            self._slug,
            self._num_zones,
            self._zones,
            self._hw,
            {**self._entry.data, **self._entry.options},
            integration_version=SOFTWARE_VERSION,
            entry_id=self._entry.entry_id,
            substrate=self._substrate(),
            feed_calibration=self._feed_calibration(),
        )


class CropSteeringStockSensor(SensorEntity):
    """How many of the room's stock tanks are at or below their low mark (0 when none), with every
    tank's level as attributes, so an automation can push a phone alert. The tanks live in the
    integration's store (stock_api.py); this is rewritten whenever they change."""

    _attr_should_poll = False
    _attr_icon = "mdi:flask-outline"

    def __init__(self, entry):
        self._entry = entry
        self._prefix = room_prefix(entry)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_stock_low"
        self._attr_name = "Stock tanks low"
        self._attr_object_id = f"{DOMAIN}_{self._prefix}stock_low"
        self.entity_id = f"sensor.{self._attr_object_id}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Crop Steering System",
            manufacturer="Home Assistant Community",
            model="Professional Irrigation Controller",
            sw_version=SOFTWARE_VERSION,
        )

    def _manager(self):
        return (
            self.hass.data.get(DOMAIN, {}).get("_stock", {}).get(self._entry.entry_id)
        )

    @property
    def native_value(self) -> Any:
        manager = self._manager()
        if manager is None or manager.error:
            return None
        return len(stock.low_tanks(manager.data))

    @property
    def extra_state_attributes(self) -> dict:
        manager = self._manager()
        if manager is None:
            return {}
        doses = manager.doses()
        linked = (
            manager.linked()
        )  # tank id -> the dosing pump that draws it (docs/DOSING.md)
        return {
            "tanks": [
                {
                    "id": tank["id"],
                    "pump": linked.get(tank["id"]),
                    "name": tank["name"],
                    "level_l": tank["level_l"],
                    "capacity_l": tank["capacity_l"],
                    "percent": round(tank["level_l"] / tank["capacity_l"] * 100, 1),
                    "low_l": tank["low_l"],
                    "dose_ml": doses.get(tank["id"]),
                    "batches_left": stock.batches_left(tank, doses.get(tank["id"], 0)),
                    "low": tank["level_l"] <= tank["low_l"],
                }
                for tank in manager.data["tanks"]
            ],
            "last_batch": manager.data["last_batch"],
            "error": manager.error,
        }

    async def async_added_to_hass(self) -> None:
        from homeassistant.helpers.dispatcher import async_dispatcher_connect

        from .dosing_api import SIGNAL as DOSING_SIGNAL
        from .stock_api import SIGNAL

        # The tanks change, or which pump is linked to one (a dosing setup saved).
        for signal in (SIGNAL, DOSING_SIGNAL):
            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass,
                    f"{signal}_{self._entry.entry_id}",
                    self.async_write_ha_state,
                )
            )


class CropSteeringDosingConfigSensor(SensorEntity):
    """The room's batch-tank dosing setup and its one request, for the controller app, which reads
    this every 2 s (docs/DOSING.md). State: the setup's revision; attributes: pumps, batch and
    request. The setup lives in the integration's store (dosing_api.py); this is rewritten
    whenever it changes."""

    _attr_should_poll = False
    _attr_icon = "mdi:beaker-outline"

    def __init__(self, entry):
        self._entry = entry
        self._prefix = room_prefix(entry)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_dosing_config"
        self._attr_name = "Dosing config"
        self._attr_object_id = f"{DOMAIN}_{self._prefix}dosing_config"
        # Home Assistant ignores _attr_object_id; the controller finds the setup by THIS id.
        self.entity_id = f"sensor.{self._attr_object_id}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Crop Steering System",
            manufacturer="Home Assistant Community",
            model="Professional Irrigation Controller",
            sw_version=SOFTWARE_VERSION,
        )

    def _manager(self):
        return (
            self.hass.data.get(DOMAIN, {}).get("_dosing", {}).get(self._entry.entry_id)
        )

    @property
    def native_value(self) -> Any:
        manager = self._manager()
        return manager.sensor()[0] if manager is not None else None

    @property
    def extra_state_attributes(self) -> dict:
        manager = self._manager()
        return manager.sensor()[1] if manager is not None else {}

    async def async_added_to_hass(self) -> None:
        from homeassistant.helpers.dispatcher import async_dispatcher_connect

        from .dosing_api import SIGNAL

        self._pump_sensors: set[str] = set()

        @callback
        def changed() -> None:
            self.async_write_ha_state()
            self._publish_pumps()

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, f"{SIGNAL}_{self._entry.entry_id}", changed
            )
        )
        self.async_on_remove(self._remove_pumps)
        self._publish_pumps()

    @callback
    def _publish_pumps(self) -> None:
        """Each dosing pump's sensor.crop_steering_<prefix>dosing_pump_<id>_ml_min and _last_calibrated
        (G3), set from the dosing store; a pump no longer set up loses its two."""
        manager = self._manager()
        sensors = manager.pump_sensors() if manager is not None else {}
        for entity_id in self._pump_sensors - set(sensors):
            self.hass.states.async_remove(entity_id)
        for entity_id, (state, attributes) in sensors.items():
            self.hass.states.async_set(entity_id, str(state), attributes)
        self._pump_sensors = set(sensors)

    @callback
    def _remove_pumps(self) -> None:
        for entity_id in self._pump_sensors:
            self.hass.states.async_remove(entity_id)
        self._pump_sensors = set()


class CropSteeringBrainQuestionsSensor(SensorEntity):
    """The room's last questions to the AI assistant (crop_steering.brain_ask), for the
    controller app, which answers each once as sensor.crop_steering_<prefix>brain_answers.
    State: how many are kept; attribute: questions, oldest first (brain_api.py)."""

    _attr_should_poll = False
    _attr_icon = "mdi:chat-question-outline"

    def __init__(self, entry):
        self._entry = entry
        self._prefix = room_prefix(entry)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_brain_questions"
        self._attr_name = "AI assistant questions"
        self._attr_object_id = f"{DOMAIN}_{self._prefix}brain_questions"
        # Home Assistant ignores _attr_object_id; the controller finds the questions by THIS id.
        self.entity_id = f"sensor.{self._attr_object_id}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Crop Steering System",
            manufacturer="Home Assistant Community",
            model="Professional Irrigation Controller",
            sw_version=SOFTWARE_VERSION,
        )

    def _manager(self):
        return (
            self.hass.data.get(DOMAIN, {})
            .get("_brain_questions", {})
            .get(self._entry.entry_id)
        )

    @property
    def native_value(self) -> Any:
        manager = self._manager()
        return manager.sensor()[0] if manager is not None else None

    @property
    def extra_state_attributes(self) -> dict:
        manager = self._manager()
        return manager.sensor()[1] if manager is not None else {}

    async def async_added_to_hass(self) -> None:
        from homeassistant.helpers.dispatcher import async_dispatcher_connect

        from .brain_api import SIGNAL

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, f"{SIGNAL}_{self._entry.entry_id}", self.async_write_ha_state
            )
        )


class CropSteeringBrainPromptConfigSensor(CropSteeringBrainQuestionsSensor):
    """The revisioned context the controller reads; text stays out of Recorder."""

    _unrecorded_attributes = frozenset({"config"})

    def __init__(self, entry):
        super().__init__(entry)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_brain_prompt_config"
        self._attr_name = "AI instructions configuration"
        self._attr_object_id = f"{DOMAIN}_{self._prefix}brain_prompt_config"
        self.entity_id = f"sensor.{self._attr_object_id}"

    def _manager(self):
        return (
            self.hass.data.get(DOMAIN, {})
            .get("_brain_prompt", {})
            .get(self._entry.entry_id)
        )

    @property
    def native_value(self):
        manager = self._manager()
        return manager.revision if manager else None

    @property
    def extra_state_attributes(self):
        manager = self._manager()
        return {"config": manager.config, "rebuild": manager.rebuild} if manager else {}

    async def async_added_to_hass(self):
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .brain_prompt_api import SIGNAL

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, f"{SIGNAL}_{self._entry.entry_id}", self.async_write_ha_state
            )
        )


class CropSteeringDisplaySensor(SensorEntity):
    """What the dashboard shows in the room (Settings > Display, display.py). State: the options'
    revision; attributes: every option with its value, off where none is saved."""

    _attr_should_poll = False
    _attr_icon = "mdi:monitor-dashboard"

    def __init__(self, entry):
        self._entry = entry
        self._prefix = room_prefix(entry)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_display"
        self._attr_name = "Display options"
        self._attr_object_id = f"{DOMAIN}_{self._prefix}display"
        # Home Assistant ignores _attr_object_id; the dashboard finds the options by THIS id.
        self.entity_id = f"sensor.{self._attr_object_id}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Crop Steering System",
            manufacturer="Home Assistant Community",
            model="Professional Irrigation Controller",
            sw_version=SOFTWARE_VERSION,
        )

    def _manager(self):
        return (
            self.hass.data.get(DOMAIN, {}).get("_display", {}).get(self._entry.entry_id)
        )

    @property
    def native_value(self) -> Any:
        manager = self._manager()
        return manager.sensor()[0] if manager is not None else None

    @property
    def extra_state_attributes(self) -> dict:
        manager = self._manager()
        return manager.sensor()[1] if manager is not None else {}

    async def async_added_to_hass(self) -> None:
        from homeassistant.helpers.dispatcher import async_dispatcher_connect

        from .display import SIGNAL

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, f"{SIGNAL}_{self._entry.entry_id}", self.async_write_ha_state
            )
        )


class CropSteeringFeedCorrectedSensor(SensorEntity, RestoreEntity):
    """The room's feed pH or EC reading corrected by the probe's applied calibration (calibration.py):
    sensor.crop_steering_<prefix>feed_ph_corrected / feed_ec_corrected. Unknown while no calibration is
    applied, or the raw sensor has no number; the raw sensor itself is never touched. Written again on
    each change of the raw sensor or of the room's descriptor, and when a calibration is applied or
    reverted.

    After a restart its last value stands in only until the raw sensor first reports, and for 2 min at
    most, so a probe that never comes back is never hidden behind an old reading."""

    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:tune-vertical"

    def __init__(self, entry, probe):
        self._entry = entry
        self._probe = probe
        self._prefix = room_prefix(entry)
        quantity = "pH" if probe == "feed_ph" else "EC"
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{probe}_corrected"
        self._attr_name = f"Feed {quantity} corrected"
        self._attr_object_id = f"{DOMAIN}_{self._prefix}{probe}_corrected"
        # Home Assistant ignores _attr_object_id; the controller finds the reading by THIS id.
        self.entity_id = f"sensor.{self._attr_object_id}"
        self._descriptor = f"sensor.{DOMAIN}_{self._prefix}engine_config"
        self._value = None
        self._attributes = {}
        self._restored = None
        self._source = None
        self._unsub_source = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Crop Steering System",
            manufacturer="Home Assistant Community",
            model="Professional Irrigation Controller",
            sw_version=SOFTWARE_VERSION,
        )

    @property
    def native_value(self) -> Any:
        return self._value

    @property
    def extra_state_attributes(self) -> dict:
        return self._attributes

    def _manager(self):
        return (
            self.hass.data.get(DOMAIN, {})
            .get("_calibration", {})
            .get(self._entry.entry_id)
        )

    def _raw_not_reported(self, source) -> bool:
        state = self.hass.states.get(source) if source else None
        return state is None or bool(state.attributes.get("restored"))

    def _refresh(self) -> None:
        manager = self._manager()
        if manager is None:
            value, attributes = None, {"source": None, "applied": False}
        else:
            value, attributes = manager.corrected(self._probe)
        source = attributes.get("source")
        if (
            value is None
            and self._restored is not None
            and attributes.get("applied")
            and self._raw_not_reported(source)
        ):
            value = self._restored
            attributes = {**attributes, "restored": True}  # not a live reading yet
        elif source and not self._raw_not_reported(source):
            self._restored = None  # the probe has reported: its own reading from now on
        self._value, self._attributes = value, attributes
        if source != self._source:
            self._stop_source()
            self._source = source
            if source:
                self._unsub_source = async_track_state_change_event(
                    self.hass, [source], self._changed
                )

    @callback
    def _stop_source(self) -> None:
        if self._unsub_source:
            self._unsub_source()
            self._unsub_source = None

    @callback
    def _changed(self, _event=None) -> None:
        self._refresh()
        self.async_write_ha_state()

    @callback
    def _end_restore(self, _now=None) -> None:
        self._restored = None
        self._changed()

    async def async_added_to_hass(self) -> None:
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from homeassistant.helpers.event import async_call_later

        from .calibration import SIGNAL

        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        try:
            restored = float(last.state) if last is not None else None
        except (TypeError, ValueError):
            restored = None
        if restored is not None and math.isfinite(restored):
            self._restored = restored
            self.async_on_remove(async_call_later(self.hass, 120, self._end_restore))
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, f"{SIGNAL}_{self._entry.entry_id}", self._changed
            )
        )
        self.async_on_remove(
            async_track_state_change_event(self.hass, [self._descriptor], self._changed)
        )
        self.async_on_remove(self._stop_source)
        self._refresh()


class CropSteeringSensor(SensorEntity):
    """Crop Steering sensor."""

    def __init__(
        self,
        entry: ConfigEntry,
        description: SensorEntityDescription,
        zones_config: dict,
        hardware_config: dict,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        self._entry = entry
        self._zones_config = zones_config
        self._hardware_config = hardware_config
        # Room prefix ("" for the default room) — every cross-entity read below is
        # namespaced with it so a second room reads its OWN entities, not room 1's.
        self._prefix = room_prefix(entry)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{description.key}"
        self._attr_name = description.name
        # Set object_id to include crop_steering prefix for entity_id generation
        self._attr_object_id = f"{DOMAIN}_{self._prefix}{description.key}"
        # Home Assistant ignores _attr_object_id and would name a NEW entity from its friendly name
        # (number.p1_target_vwc). Existing installs keep the id the registry already holds.
        self.entity_id = f"sensor.{self._attr_object_id}"
        # A zone VWC/EC sensor's memory of how its probes read against each other (fuse_probes),
        # when every probe last reported together, and what the last reading was made from.
        self._probe_offsets: dict[str, float] = {}
        self._offsets_at: str | None = None
        self._fusion: dict | None = None
        # The offset and curve each moisture probe was last read under (probe_offsets.py), so a change
        # moves what fusion learned of the probe by the same step.
        self._applied_fix: dict[str, tuple] = {}

        # Extract zone number from key if this is a zone sensor.
        # Regex matches BOTH `vwc_zone_3` and `zone_3_status`-style keys; the prior
        # `split("_zone_")` logic missed keys that *start* with `zone_` (e.g.
        # zone_N_status), leaving _zone_number=None so the zone branch never fired.
        self._zone_number = None
        m = re.search(r"zone_(\d+)", description.key)
        if m:
            try:
                self._zone_number = int(m.group(1))
            except (ValueError, IndexError):
                pass

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Crop Steering System",
            manufacturer="Home Assistant Community",
            model="Professional Irrigation Controller",
            sw_version=SOFTWARE_VERSION,
        )

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        # Handle zone-specific sensors
        if self._zone_number is not None:
            if f"vwc_zone_{self._zone_number}" == self.entity_description.key:
                return self._get_zone_vwc(self._zone_number)
            elif f"ec_zone_{self._zone_number}" == self.entity_description.key:
                return self._get_zone_ec(self._zone_number)
            elif (
                f"zone_{self._zone_number}_last_irrigation"
                == self.entity_description.key
            ):
                return self._get_zone_last_irrigation(self._zone_number)
            elif (
                f"zone_{self._zone_number}_daily_water_usage"
                == self.entity_description.key
            ):
                return self._get_zone_daily_water_usage(self._zone_number)
            elif (
                f"zone_{self._zone_number}_weekly_water_usage"
                == self.entity_description.key
            ):
                return self._get_zone_weekly_water_usage(self._zone_number)
            elif (
                f"zone_{self._zone_number}_irrigation_count_today"
                == self.entity_description.key
            ):
                return self._get_zone_irrigation_count_today(self._zone_number)

        # Implement critical calculations ported from template entities
        if self.entity_description.key in SHOT_SIZE_KEYS:
            seconds = self._shot_seconds_by_zone(self.entity_description.key)
            return max(seconds.values()) if seconds else None
        elif self.entity_description.key == "ec_ratio":
            return self._calculate_ec_ratio()
        elif self.entity_description.key == "p2_vwc_threshold_adjusted":
            return self._calculate_adjusted_p2_threshold()
        elif self.entity_description.key == "configured_avg_vwc":
            return self._calculate_avg_vwc()
        elif self.entity_description.key == "configured_avg_ec":
            return self._calculate_avg_ec()
        else:
            # Other sensors return None (placeholder)
            return None

    def _zone_setting(self, zone_num: int, key: str) -> float | None:
        """A zone's setting as the controller reads it: the zone's own number, else the room's.
        None when neither reads as a number."""
        for entity_id in (
            f"number.crop_steering_{self._prefix}zone_{zone_num}_{key}",
            f"number.crop_steering_{self._prefix}{key}",
        ):
            state = self.hass.states.get(entity_id)
            if state is None or state.state in ("unknown", "unavailable", "none", ""):
                continue
            try:
                value = float(state.state)
            except (TypeError, ValueError):
                return None
            return value if math.isfinite(value) else None
        return None

    def _shot_seconds_by_zone(self, key: str) -> dict[int, int]:
        """How long the controller runs the configured shot `key` times, in each of the room's
        active zones: the zone's pot size, drippers per plant and dripper flow, in whole seconds
        within the room's shot limits. A zone whose sizing doesn't give a flow is left out.
        """
        zones = sorted(
            int(zone)
            for zone, config in self._zones_config.items()
            if str(zone).isdigit() and (config or {}).get("active", True)
        ) or [1]
        # The room's maximum shot length, or its older entity's, as the controller reads it.
        cap = None
        for suffix in ("max_shot_duration", "maximum_shot_duration"):
            cap_state = self.hass.states.get(
                f"number.crop_steering_{self._prefix}{suffix}"
            )
            if cap_state is None:
                continue
            try:
                cap = float(cap_state.state)
            except (TypeError, ValueError):
                cap = None
            break
        seconds = {}
        for zone in zones:
            sizing = [
                self._zone_setting(zone, setting)
                for setting in (
                    "substrate_volume",
                    SHOT_SIZE_KEYS[key],
                    "drippers_per_plant",
                    "dripper_flow_rate",
                )
            ]
            if any(value is None or value <= 0 for value in sizing):
                continue
            substrate, size, drippers, flow = sizing
            raw = ShotCalculator.calculate_shot_duration(
                flow, substrate, size, drippers
            )
            seconds[zone] = ShotCalculator.capped_shot_seconds(raw, cap)
        return seconds

    def _calculate_ec_ratio(self) -> float:
        """Calculate current EC ratio vs target."""
        try:
            current_ec = self._calculate_avg_ec()
            # Get current EC target based on phase and mode
            target_ec = self._get_current_ec_target()

            if target_ec > 0 and current_ec is not None:
                return round(current_ec / target_ec, 2)
            return DEFAULT_EC_RATIO
        except Exception:
            return DEFAULT_EC_RATIO

    def _calculate_adjusted_p2_threshold(self) -> float:
        """Calculate P2 VWC threshold adjusted for EC ratio."""
        try:
            base_threshold = self._get_number_value("p2_vwc_threshold")
            ec_ratio = self._calculate_ec_ratio()
            ec_high_threshold = self._get_number_value("p2_ec_high_threshold")
            ec_low_threshold = self._get_number_value("p2_ec_low_threshold")

            # Simplified adjustment logic
            if ec_ratio > ec_high_threshold:
                return round(
                    base_threshold + VWC_ADJUSTMENT_PERCENT, 2
                )  # Raise threshold when EC high
            elif ec_ratio < ec_low_threshold:
                return round(
                    base_threshold - VWC_ADJUSTMENT_PERCENT, 2
                )  # Lower threshold when EC low
            else:
                return round(base_threshold, 2)
        except Exception:
            return self._get_number_value("p2_vwc_threshold")

    def _get_zone_vwc(self, zone_num: int) -> float | None:
        """Get VWC value for specific zone from configured sensors.

        Supports N sensors per zone (new vwc_sensors list) with
        fallback to legacy vwc_front/vwc_back pair.
        """
        # _zones_config keys can be int OR str ('1','2','3') depending on how the config
        # entry was (re)loaded — JSON serialises dict keys as strings, so after a config
        # reload the int lookup misses and every zone reads None ('unknown'). Accept both.
        zone_config = (
            self._zones_config.get(zone_num)
            or self._zones_config.get(str(zone_num))
            or {}
        )

        # Prefer new list format
        vwc_sensors = list(zone_config.get("vwc_sensors", []))
        if not vwc_sensors:
            # Legacy fallback
            if zone_config.get("vwc_front"):
                vwc_sensors.append(zone_config["vwc_front"])
            if zone_config.get("vwc_back"):
                vwc_sensors.append(zone_config["vwc_back"])

        return self._fuse_zone(vwc_sensors, "vwc")

    def _get_zone_ec(self, zone_num: int) -> float | None:
        """Get EC value for specific zone from configured sensors.

        Supports N sensors per zone (new ec_sensors list) with
        fallback to legacy ec_front/ec_back pair.
        """
        zone_config = (
            self._zones_config.get(zone_num)
            or self._zones_config.get(str(zone_num))
            or {}
        )

        ec_sensors = list(zone_config.get("ec_sensors", []))
        if not ec_sensors:
            if zone_config.get("ec_front"):
                ec_sensors.append(zone_config["ec_front"])
            if zone_config.get("ec_back"):
                ec_sensors.append(zone_config["ec_back"])

        return self._fuse_zone(ec_sensors, "ec")

    def _get_zone_last_irrigation(self, zone_num: int):
        """Return zone last-irrigation as a tz-aware datetime (or None).

        device_class=TIMESTAMP requires a tz-aware datetime. A naive ISO string makes HA raise
        inside the platform's shared asyncio.gather, which freezes the other sensors too.
        """
        s = self.hass.states.get(
            f"sensor.crop_steering_{self._prefix}zone_{zone_num}_last_irrigation_app"
        )
        if not s or s.state in ("unknown", "unavailable", "", None):
            return None
        dt = dt_util.parse_datetime(s.state)
        if dt is None:
            return None
        # Legacy producer strings do not identify their timezone. Wait for an
        # explicit offset instead of assigning a potentially incorrect time.
        return dt if dt.tzinfo is not None and dt.utcoffset() is not None else None

    def _get_zone_daily_water_usage(self, zone_num: int) -> float | None:
        """Get finite non-negative daily usage, preserving an unavailable source."""
        usage_sensor = self.hass.states.get(
            f"sensor.crop_steering_{self._prefix}zone_{zone_num}_daily_water_app"
        )
        if usage_sensor and usage_sensor.state not in ["unknown", "unavailable"]:
            try:
                value = float(usage_sensor.state)
                return value if math.isfinite(value) and value >= 0 else None
            except (TypeError, ValueError):
                pass
        return None

    def _get_zone_weekly_water_usage(self, zone_num: int) -> float | None:
        """Get weekly water usage for zone."""
        # Check the engine sensor for weekly usage
        usage_sensor = self.hass.states.get(
            f"sensor.crop_steering_{self._prefix}zone_{zone_num}_weekly_water_app"
        )
        if usage_sensor and usage_sensor.state not in ["unknown", "unavailable"]:
            try:
                value = float(usage_sensor.state)
                return value if math.isfinite(value) and value >= 0 else None
            except (TypeError, ValueError):
                pass
        return None

    @property
    def extra_state_attributes(self) -> dict | None:
        """Expose the weekly producer's coverage so partial history stays visible, which probes
        a zone's VWC/EC reading was made from, and a shot-duration sensor's seconds in each zone
        (it shows the longest)."""
        if self.entity_description.key in SHOT_SIZE_KEYS:
            seconds = self._shot_seconds_by_zone(self.entity_description.key)
            return {"zones": {str(zone): value for zone, value in seconds.items()}}
        if self._zone_number and self.entity_description.key in (
            f"vwc_zone_{self._zone_number}",
            f"ec_zone_{self._zone_number}",
        ):
            return self._fusion
        if self._zone_number and self.entity_description.key == (
            f"zone_{self._zone_number}_weekly_water_usage"
        ):
            source = self.hass.states.get(
                f"sensor.crop_steering_{self._prefix}zone_{self._zone_number}_weekly_water_app"
            )
            if (
                source is None
                or self._get_zone_weekly_water_usage(self._zone_number) is None
            ):
                return {"coverage": "unknown", "history_complete": False}
            keys = (
                "window_start_grow_day",
                "window_end_grow_day",
                "observed_grow_days",
                "complete_grow_days",
                "history_complete",
                "coverage",
                "legacy_volume_excluded_l",
                "measurement",
            )
            return {
                key: source.attributes[key] for key in keys if key in source.attributes
            }
        return None

    def _get_zone_irrigation_count_today(self, zone_num: int) -> int:
        """Get today's irrigation count for zone."""
        # Check the engine sensor for count
        count_sensor = self.hass.states.get(
            f"sensor.crop_steering_{self._prefix}zone_{zone_num}_irrigation_count_app"
        )
        if count_sensor and count_sensor.state not in ["unknown", "unavailable"]:
            try:
                return int(count_sensor.state)
            except ValueError:
                pass
        return 0

    def _user_corrections(self) -> dict:
        """{probe: (offset, curve)} the grower set for the room's moisture probes (calibration.py)."""
        manager = (
            self.hass.data.get(DOMAIN, {})
            .get("_calibration", {})
            .get(self._entry.entry_id)
        )
        return manager.user_corrections() if manager is not None else {}

    def _unreadable_offsets(self, sensor_ids) -> bool:
        """Whether the stored probe offsets of any of these probes cannot be read (calibration.py), so
        they read without them."""
        manager = (
            self.hass.data.get(DOMAIN, {})
            .get("_calibration", {})
            .get(self._entry.entry_id)
        )
        return manager is not None and bool(manager.affected_probes() & set(sensor_ids))

    def _probe_readings(
        self, sensor_ids: list[str], kind: str | None = None
    ) -> list[tuple[str, float | None, float | None]]:
        """(entity_id, value, age in seconds) for every probe, each value first converted to the
        unit the room steers in (`kind` "ec" -> mS/cm, "vwc" -> %). Mixed probes are common: one
        Atlas in uS/cm beside one TEROS in mS/cm would otherwise average to nonsense far over any
        EC target. Value None = no usable number; age None = the state carries no time. The probes
        set aside for their unit are left in self._unit_set_aside as {entity_id: unit}.
        """
        readings = []
        self._unit_set_aside = {}
        fixes = self._user_corrections() if kind == "vwc" else {}
        for sensor_id in sensor_ids:
            if not sensor_id:
                continue
            value = age = None
            try:
                state = self.hass.states.get(sensor_id)
                if state is None:
                    _LOGGER.warning(f"Sensor entity not found: {sensor_id}")
                elif state.state not in ["unknown", "unavailable", "none", None]:
                    value = float(state.state)
                    if math.isfinite(value):
                        unit = (getattr(state, "attributes", None) or {}).get(
                            "unit_of_measurement"
                        )
                        raw = value
                        fix = fixes.get(sensor_id)
                        if fix:
                            _base, value, aside = read_probe(
                                raw, unit, fix[0], fix[1], sensor_id
                            )
                        else:
                            value, aside = to_native(kind, unit, raw, sensor_id)
                        if kind == "vwc":
                            self._follow_fix(sensor_id, raw, unit, fix, value)
                        if aside:
                            self._unit_set_aside[sensor_id] = unit or ""
                    # last_reported moves on every report, last_updated only on a change.
                    stamp = getattr(state, "last_reported", None) or getattr(
                        state, "last_updated", None
                    )
                    if stamp is not None:
                        age = (dt_util.utcnow() - stamp).total_seconds()
            except (ValueError, TypeError) as e:
                _LOGGER.debug(f"Could not parse sensor value for {sensor_id}: {e}")
            readings.append((sensor_id, value, age))
        return readings

    def _follow_fix(self, sensor_id, raw, unit, fix, value) -> None:
        """A probe's offset or curve changed since it was last read: what fusion learned of the probe
        (its offset against the zone) moves by the same step, so a later pass with a probe missing
        does not step the reading."""
        fix = fix or (0.0, None)
        before = self._applied_fix.get(sensor_id)
        self._applied_fix[sensor_id] = fix
        if before is None or before == fix or sensor_id not in self._probe_offsets:
            return
        _base, was, _aside = read_probe(raw, unit, before[0], before[1], sensor_id)
        if was is not None and value is not None:
            self._probe_offsets[sensor_id] += value - was

    def _probe_method_entity(self, kind: str) -> str:
        """The zone's select of how its probes become its `kind` reading (select.py)."""
        return f"select.{DOMAIN}_{self._prefix}zone_{self._zone_number}_{kind}_method"

    def _ec_types(self, sensor_ids: list[str]) -> dict[str, str]:
        """What each EC probe measures, from its select (select.py); unknown without one."""
        types = {}
        for probe in sensor_ids:
            state = probe and self.hass.states.get(
                f"select.{DOMAIN}_{self._prefix}{ec_type_key(probe)}"
            )
            if state:
                types[probe] = state.state
        return types

    def _fuse_zone(self, sensor_ids: list[str], kind: str) -> float | None:
        """One zone's reading from its probes (calculations.fuse_probes), combined as the zone's
        select says; Median without it. Probes the zone's setup leaves out (`<kind>_unused`) do not
        count; the one it names primary (`<kind>_primary`) is published, for the controller to say
        when it goes offline (CS-505)."""
        lo, hi = PROBE_RANGE[kind]
        zone = (
            self._zones_config.get(self._zone_number)
            or self._zones_config.get(str(self._zone_number))
            or {}
        )
        unused = set(zone.get(f"{kind}_unused") or ()) & set(sensor_ids)
        if unused == set(sensor_ids):
            unused = (
                set()
            )  # setup never leaves a zone none; an edited entry must not either
        method = self.hass.states.get(self._probe_method_entity(kind))
        value, self._fusion = fuse_probes(
            self._probe_readings([s for s in sensor_ids if s not in unused], kind),
            self._probe_offsets,
            lo,
            hi,
            PROBE_STALE_SECONDS,
            method.state if method is not None else "Median",
            PROBE_FAR[kind],
            self._ec_types(sensor_ids) if kind == "ec" else None,
        )
        if value is not None and not self._fusion["excluded"]:
            self._offsets_at = dt_util.utcnow().isoformat()
        self._fusion["offsets_learned"] = (
            self._offsets_at if self._probe_offsets else None
        )
        # Say which probes were set aside for their unit, so the controller can name the probe and
        # its unit (CS-503) rather than only that the zone has no reading.
        aside = {
            pid: unit
            for pid, unit in self._unit_set_aside.items()
            if pid in self._fusion["excluded"]
        }
        if aside:
            self._fusion["excluded"].update(
                {pid: "set aside for its unit" for pid in aside}
            )
            self._fusion["quality"].update(
                {pid: {"quality": "bad", "reason": "unknown_unit"} for pid in aside}
            )
            self._fusion["unit_set_aside"] = aside
        self._fusion["excluded"].update(dict.fromkeys(sorted(unused), "not counted"))
        if kind == "vwc" and self._unreadable_offsets(sensor_ids):
            self._fusion["user_offsets"] = "unreadable"
        primary = zone.get(f"{kind}_primary")
        self._fusion["primary"] = (
            primary if primary in sensor_ids and primary not in unused else None
        )
        return value

    def _average_sensor_values(
        self, sensor_ids: list[str], kind: str | None = None
    ) -> float | None:
        """Plain average of every finite probe reading (the room-wide figures)."""
        if not sensor_ids:
            _LOGGER.debug("No sensor IDs provided for averaging")
            return None

        values = [
            value
            for _sensor_id, value, _age in self._probe_readings(sensor_ids, kind)
            if value is not None and math.isfinite(value)
        ]

        if values:
            return round(sum(values) / len(values), 2)

        _LOGGER.debug(f"No valid sensor values found from {len(sensor_ids)} sensors")
        return None

    def _calculate_avg_vwc(self) -> float | None:
        """Calculate average VWC from all configured zone sensors."""
        all_sensors = []
        for zone_config in self._zones_config.values():
            sensors = list(zone_config.get("vwc_sensors", []))
            if sensors:
                all_sensors.extend(sensors)
            else:
                if zone_config.get("vwc_front"):
                    all_sensors.append(zone_config["vwc_front"])
                if zone_config.get("vwc_back"):
                    all_sensors.append(zone_config["vwc_back"])

        return self._average_sensor_values(all_sensors, "vwc")

    def _calculate_avg_ec(self) -> float | None:
        """Calculate average EC from all configured zone sensors."""
        all_sensors = []
        for zone_config in self._zones_config.values():
            sensors = list(zone_config.get("ec_sensors", []))
            if sensors:
                all_sensors.extend(sensors)
            else:
                if zone_config.get("ec_front"):
                    all_sensors.append(zone_config["ec_front"])
                if zone_config.get("ec_back"):
                    all_sensors.append(zone_config["ec_back"])

        return self._average_sensor_values(all_sensors, "ec")

    def _get_number_value(self, key: str) -> float:
        """Get value from integration number entity."""
        try:
            entity_id = f"number.crop_steering_{self._prefix}{key}"
            state = self.hass.states.get(entity_id)
            if state is None:
                _LOGGER.debug(f"Number entity not found: {entity_id}")
                return 0.0
            if state.state not in ["unknown", "unavailable", "none", None]:
                return float(state.state)
            return 0.0
        except (ValueError, TypeError) as e:
            _LOGGER.warning(f"Could not parse number value for {key}: {e}")
            return 0.0

    def _get_current_ec_target(self) -> float:
        """Get current EC target based on phase and steering mode."""
        try:
            # Get current phase and mode
            phase_state = self.hass.states.get(
                f"select.crop_steering_{self._prefix}irrigation_phase"
            )
            mode_state = self.hass.states.get(
                f"select.crop_steering_{self._prefix}steering_mode"
            )

            if not phase_state or not mode_state:
                return DEFAULT_EC_FALLBACK  # Default fallback

            phase = phase_state.state
            mode = mode_state.state.lower()

            # Map to EC target entities
            if mode == "vegetative":
                if phase == "P0":
                    return self._get_number_value("ec_target_veg_p0")
                elif phase == "P1":
                    return self._get_number_value("ec_target_veg_p1")
                elif phase == "P2":
                    return self._get_number_value("ec_target_veg_p2")
                elif phase == "P3":
                    return self._get_number_value("ec_target_veg_p3")
            else:  # Generative
                if phase == "P0":
                    return self._get_number_value("ec_target_gen_p0")
                elif phase == "P1":
                    return self._get_number_value("ec_target_gen_p1")
                elif phase == "P2":
                    return self._get_number_value("ec_target_gen_p2")
                elif phase == "P3":
                    return self._get_number_value("ec_target_gen_p3")

            return DEFAULT_EC_FALLBACK  # Default fallback
        except Exception:
            return DEFAULT_EC_FALLBACK

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        return True


class CropSteeringProbeSensor(CropSteeringSensor, RestoreEntity):
    """A zone's moisture or EC reading from its probes. What it learned of how they read against each
    other is kept over a restart, keyed by probe, with when every probe last reported together, so
    a probe missing at start-up does not step the reading. A new choice in the zone's method select
    shows at once, not at the next poll."""

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_extra_data()
        data = last.as_dict() if last is not None else {}
        offsets = data.get("probe_offsets")
        if isinstance(offsets, dict) and all(
            isinstance(pid, str) and isinstance(v, (int, float)) and math.isfinite(v)
            for pid, v in offsets.items()
        ):
            self._probe_offsets.update(offsets)
            self._offsets_at = data.get("offsets_learned")
        kind = self.entity_description.key.split("_", 1)[0]
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._probe_method_entity(kind)], self._method_changed
            )
        )
        if kind == "vwc":  # a probe's new offset or curve shows at once
            from homeassistant.helpers.dispatcher import async_dispatcher_connect

            from .calibration import SIGNAL as CALIBRATION_SIGNAL

            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass,
                    f"{CALIBRATION_SIGNAL}_{self._entry.entry_id}",
                    self.async_write_ha_state,
                )
            )

    @callback
    def _method_changed(self, _event) -> None:
        self.async_write_ha_state()

    @property
    def extra_restore_state_data(self) -> RestoredExtraData:
        return RestoredExtraData(
            {
                "probe_offsets": dict(self._probe_offsets),
                "offsets_learned": self._offsets_at,
            }
        )


class CropSteeringZoneStatusSensor(CropSteeringSensor):
    """zone_N_status: what the CONTROLLER says about the zone, mirrored from its zone_N_status_app.

    Not polled. It is updated when zone_N_status_app changes, and checked once a minute for a
    controller that has stopped reporting, and it writes only when what it shows changes. A
    controller from before this, which still writes zone_N_status itself, is therefore left alone
    rather than fought every 30 seconds: the integration shows "Controller not reporting" once, and
    that controller's own label stands until it is updated.
    """

    _attr_should_poll = False

    def __init__(self, entry, description, zones_config, hardware_config) -> None:
        super().__init__(entry, description, zones_config, hardware_config)
        self._source = status_app_entity(self._prefix, self._zone_number)
        self._shown: tuple[str, dict] | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._source], self._source_changed
            )
        )
        self.async_on_remove(
            async_track_time_interval(self.hass, self._refresh, timedelta(minutes=1))
        )

    @callback
    def _source_changed(self, _event) -> None:
        self._refresh(dt_util.utcnow())

    @callback
    def _refresh(self, now) -> None:
        shown = mirrored_status(self.hass.states.get(self._source), now)
        if shown != self._shown:
            self._shown = shown
            self.async_write_ha_state()

    def _current(self) -> tuple[str, dict]:
        if self._shown is None:
            self._shown = mirrored_status(
                self.hass.states.get(self._source), dt_util.utcnow()
            )
        return self._shown

    @property
    def native_value(self) -> Any:
        return self._current()[0]

    @property
    def extra_state_attributes(self) -> dict | None:
        return dict(self._current()[1])


class CropSteeringCurrentPhaseSensor(CropSteeringSensor):
    """current_phase: the phase the CONTROLLER publishes on app_current_phase, mirrored.

    Unknown, with a reason attribute, when the controller has not published or has stopped
    reporting; never a default phase. Not polled: it follows app_current_phase and is checked once a
    minute for a controller that has stopped.
    """

    _attr_should_poll = False

    def __init__(self, entry, description, zones_config, hardware_config) -> None:
        super().__init__(entry, description, zones_config, hardware_config)
        self._source = app_phase_entity(self._prefix)
        self._shown: tuple[str | None, dict] | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._source], self._source_changed
            )
        )
        self.async_on_remove(
            async_track_time_interval(self.hass, self._refresh, timedelta(minutes=1))
        )

    @callback
    def _source_changed(self, _event) -> None:
        self._refresh(dt_util.utcnow())

    @callback
    def _refresh(self, now) -> None:
        shown = mirrored_phase(self.hass.states.get(self._source), now)
        if shown != self._shown:
            self._shown = shown
            self.async_write_ha_state()

    def _current(self) -> tuple[str | None, dict]:
        if self._shown is None:
            self._shown = mirrored_phase(
                self.hass.states.get(self._source), dt_util.utcnow()
            )
        return self._shown

    @property
    def native_value(self) -> Any:
        return self._current()[0]

    @property
    def extra_state_attributes(self) -> dict | None:
        return dict(self._current()[1])
