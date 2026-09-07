"""Crop Steering System switches."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, CONF_NUM_ZONES, SOFTWARE_VERSION
from .room import room_prefix

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
    # ----- RootSense intelligence module enable switches -----
    # Each pillar reads its corresponding switch on every iteration. When OFF,
    # the module logs "skipped" and short-circuits without touching state or
    # publishing sensors. Defaults: all OFF so existing v2.x installs are
    # unaffected on first upgrade. Operators opt in pillar-by-pillar.
    SwitchEntityDescription(
        key="intelligence_root_zone_enabled",
        name="RootSense — Root Zone Intelligence",
        icon="mdi:water-percent-alert",
    ),
    SwitchEntityDescription(
        key="intelligence_adaptive_enabled",
        name="RootSense — Adaptive Irrigation",
        icon="mdi:tune-vertical-variant",
    ),
    SwitchEntityDescription(
        key="intelligence_agronomic_enabled",
        name="RootSense — Agronomic Intelligence",
        icon="mdi:sprout",
    ),
    SwitchEntityDescription(
        key="intelligence_orchestrator_enabled",
        name="RootSense — Orchestrator",
        icon="mdi:hub-outline",
    ),
    SwitchEntityDescription(
        key="intelligence_anomaly_enabled",
        name="RootSense — Anomaly Scanner",
        icon="mdi:alert-decagram-outline",
    ),
    # ----- ClimateSense pillar enable switches -----
    # Same pattern as RootSense — each pillar reads its own switch on
    # every iteration; OFF short-circuits all side effects. Default OFF
    # so existing GW pack remains the active climate controller until
    # you opt in. See dashboards/legacyag/30_intelligence.yaml for a
    # convenient toggle panel.
    SwitchEntityDescription(
        key="intelligence_climate_sensing_enabled",
        name="ClimateSense — Sensing",
        icon="mdi:thermometer-lines",
    ),
    SwitchEntityDescription(
        key="intelligence_climate_timeline_enabled",
        name="ClimateSense — Timeline",
        icon="mdi:calendar-clock",
    ),
    SwitchEntityDescription(
        key="intelligence_climate_control_enabled",
        name="ClimateSense — Control loops",
        icon="mdi:tune",
    ),
    SwitchEntityDescription(
        key="intelligence_climate_lights_enabled",
        name="ClimateSense — Lights manager",
        icon="mdi:lightbulb-on-outline",
    ),
    SwitchEntityDescription(
        key="intelligence_climate_anomaly_enabled",
        name="ClimateSense — Anomaly scanner",
        icon="mdi:alert-octagon-outline",
    ),
    # Optional — if ON, the timeline pillar drives
    # number.crop_steering_steering_intent based on the active recipe phase.
    SwitchEntityDescription(
        key="intelligence_climate_drives_intent_enabled",
        name="ClimateSense — Recipe drives cultivator intent",
        icon="mdi:link-variant",
    ),
    # ----- LLM advisor (Phase L0 — report only, no LLM calls) -----
    SwitchEntityDescription(
        key="intelligence_llm_report_enabled",
        name="LLM Advisor — Report builder (L0)",
        icon="mdi:file-document-outline",
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

        # Per-zone blocked-dripper protection toggle. ON (default) = abandon emergency
        # irrigation for this row after the threshold of failed shots (blocked-dripper guard).
        # OFF = never abandon; the row keeps retrying emergency shots.
        zone_switches.append(
            SwitchEntityDescription(
                key=f"zone_{zone_num}_dripper_protection",
                name=f"Zone {zone_num} Dripper Protection",
                icon="mdi:water-alert",
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

    # Named rooms and new default rooms receive an engine switch, initially OFF.
    # Legacy default entries retain their existing helper unless explicitly migrated.
    # The add-on reads the selected flag from the engine_config descriptor.
    if (
        room_prefix(entry)
        or config_data.get("enable_flag") == "switch.crop_steering_engine_enabled"
    ):
        switches.append(
            CropSteeringSwitch(
                entry,
                SwitchEntityDescription(
                    key="engine_enabled",
                    name="Engine Enabled (room kill switch)",
                    icon="mdi:power-settings",
                ),
            )
        )

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
        self._attr_object_id = f"{DOMAIN}_{room_prefix(entry)}{description.key}"
        self._is_manual_override = description.key.startswith(
            "zone_"
        ) and description.key.endswith("_manual_override")
        self._override_key = f"{room_prefix(entry)}{description.key}"
        self._override_deadline: datetime | None = None
        self._override_cancel = None
        self._override_generation = 0
        self._override_loaded = False

        # Set default states based on switch type
        if description.key == "system_enabled":
            self._attr_is_on = True  # System enabled by default
        elif description.key == "auto_irrigation_enabled":
            self._attr_is_on = True  # Auto irrigation enabled by default
        elif "zone_" in description.key and "_enabled" in description.key:
            self._attr_is_on = True  # Zones enabled by default
        elif "dripper_protection" in description.key:
            self._attr_is_on = True  # Blocked-dripper protection on by default
        else:
            self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Restore state when added to hass."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._attr_is_on = last_state.state == "on"
        if not self._is_manual_override:
            return
        self._override_loaded = True
        if self._attr_is_on and last_state is not None:
            raw = last_state.attributes.get("manual_override_expires_at")
            if isinstance(raw, str):
                try:
                    deadline = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                    # A naive timestamp cannot safely identify the intended deadline.
                    if deadline.tzinfo is not None and deadline.utcoffset() is not None:
                        deadline = deadline.astimezone(timezone.utc)
                        if deadline <= dt_util.utcnow():
                            self._attr_is_on = False
                        else:
                            self._schedule_override(deadline)
                except (ValueError, OverflowError):
                    _LOGGER.warning(
                        "Invalid manual override deadline for %s; preserving hold",
                        self._override_key,
                    )
        self.hass.data.setdefault(DOMAIN, {}).setdefault("_manual_overrides", {})[
            self._override_key
        ] = self

    def _cancel_override_timer(self) -> None:
        """Invalidate callbacks already queued as well as the scheduled handle."""
        self._override_generation += 1
        if self._override_cancel is not None:
            self._override_cancel()
            self._override_cancel = None

    def _schedule_override(self, deadline: datetime) -> None:
        from homeassistant.helpers.event import async_track_point_in_utc_time

        generation = self._override_generation + 1

        @callback
        def expire(_now):
            if not self._override_loaded or generation != self._override_generation:
                return
            self._override_cancel = None
            self._override_generation += 1
            self._override_deadline = None
            self._attr_is_on = False
            self.async_write_ha_state()

        # Schedule first: a scheduler failure must leave an existing timer intact.
        cancel = async_track_point_in_utc_time(self.hass, expire, deadline)
        self._cancel_override_timer()
        self._override_deadline = deadline
        self._override_cancel = cancel

    async def async_set_manual_override(self, enable: bool, timeout_minutes=60) -> None:
        """Set a durable timed hold on this loaded logical room/zone switch."""
        if not self._is_manual_override or not self._override_loaded:
            raise HomeAssistantError("Manual override switch is not loaded")
        if not isinstance(enable, bool):
            raise HomeAssistantError("enable must be a boolean")
        if enable:
            if (
                isinstance(timeout_minutes, bool)
                or not isinstance(timeout_minutes, (int, float))
                or not math.isfinite(timeout_minutes)
                or not 1 <= timeout_minutes <= 1440
            ):
                raise HomeAssistantError("timeout_minutes must be within 1–1440")
            self._schedule_override(
                dt_util.utcnow() + timedelta(minutes=timeout_minutes)
            )
            self._attr_is_on = True
            self.async_write_ha_state()
        else:
            await self.async_turn_off()

    async def async_will_remove_from_hass(self) -> None:
        """Stop callbacks while leaving the saved deadline available to RestoreEntity."""
        self._override_loaded = False
        self._cancel_override_timer()
        registry = self.hass.data.get(DOMAIN, {}).get("_manual_overrides", {})
        if registry.get(self._override_key) is self:
            registry.pop(self._override_key)
        await super().async_will_remove_from_hass()

    @property
    def extra_state_attributes(self):
        if not self._is_manual_override:
            return {}
        return {
            "manual_override_expires_at": (
                self._override_deadline.isoformat() if self._override_deadline else None
            ),
            "manual_override_mode": (
                ("timed" if self._override_deadline else "indefinite")
                if self._attr_is_on
                else "off"
            ),
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Crop Steering",
            manufacturer="Home Assistant Community",
            model="Professional Irrigation Controller",
            sw_version=SOFTWARE_VERSION,
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on directly; a manual hold stays on until explicitly cleared."""
        self._cancel_override_timer()
        self._override_deadline = None
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Clear the switch and any requested timeout."""
        self._cancel_override_timer()
        self._override_deadline = None
        self._attr_is_on = False
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return if switch is available."""
        return True
