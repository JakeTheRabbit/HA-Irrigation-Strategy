"""Crop Steering System select entities."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_NUM_ZONES,
    DRAINAGE_TYPES,
    EC_TYPES,
    PHASES,
    PROBE_METHODS,
    STEERING_MODES,
    GROWTH_STAGES,
    NO_TOUCH_OPTIONS,
    RECIPE_STAGES,
    RECIPE_PARAMS,
    SOFTWARE_VERSION,
    SET_PHASE_OPTIONS,
    SETPOINT_STEP_SCOPES,
    P2_MODES,
    RUNOFF_ESTIMATOR_MODES,
    SHOT_CHECK_MODES,
    SUBSTRATES,
    WATER_TODAY_VIEWS,
)
from .deprecations import note_deprecated
from .room import restored_state_is_ours, room_prefix, zone_device_name
from .recipe import get_manager
from .calculations import ec_type_key

_LOGGER = logging.getLogger(__name__)

SELECT_DESCRIPTIONS = [
    SelectEntityDescription(
        key="growth_stage",
        name="Growth stage",
        icon="mdi:timeline",
        options=GROWTH_STAGES,  # Use constant from const.py
    ),
    SelectEntityDescription(
        key="steering_mode",
        name="Steering mode",
        icon="mdi:steering",
        options=STEERING_MODES,  # Use constant from const.py
    ),
    SelectEntityDescription(
        key="irrigation_phase",
        name="Irrigation phase",
        icon="mdi:water-circle",
        options=PHASES,  # Use constant from const.py (P0-P3 only)
    ),
    # Named-stage recipe: picking a stage applies its setpoints to the zones.
    SelectEntityDescription(
        key="recipe_stage",
        name="Recipe stage",
        icon="mdi:format-list-bulleted-type",
        options=RECIPE_STAGES,
    ),
    # The room's one choice of how Water today reads: the dashboard shows it for everyone, and
    # the controller's vitals notification follows it. Zone total until someone chooses.
    SelectEntityDescription(
        key="water_today_view",
        name="Water today shown as",
        icon="mdi:water-outline",
        options=WATER_TODAY_VIEWS,
    ),
    # How the room's runoff leaves it. A free-draining room is not watched for a table backing up
    # (CS-310); Unknown and flood tables are. Setup asks; a room from before reads Unknown.
    SelectEntityDescription(
        key="drainage",
        name="Drainage",
        icon="mdi:pipe",
        options=DRAINAGE_TYPES,
        translation_key="drainage",
    ),
    # What the room grows in. The engine_config descriptor publishes it for the controller;
    # generic until someone chooses.
    SelectEntityDescription(
        key="substrate",
        name="Substrate",
        icon="mdi:sprout",
        options=SUBSTRATES,
    ),
    # The room's no-touch window: while it runs the AI assistant asks nothing and changes nothing
    # in the room, and the rules carry on. `since` says when it was chosen; the controller sets it
    # back to Off once the hour, the day or the night is over. Off until someone chooses.
    # Which automatic writers the room's Max setpoint move per day holds: the Auto setpoints follower
    # only (the default, as before), or the AI assistant's targets power and the learner as well.
    SelectEntityDescription(
        key="setpoint_step_limit_applies_to",
        name="Max setpoint move applies to",
        icon="mdi:stairs",
        options=SETPOINT_STEP_SCOPES,
    ),
    SelectEntityDescription(
        key="ai_no_touch",
        name="Pause AI changes",
        icon="mdi:hand-back-left-off",
        options=NO_TOUCH_OPTIONS,
    ),
    # The runoff estimator from the sump's water balance: off until someone chooses.
    SelectEntityDescription(
        key="runoff_estimator",
        name="Runoff estimator",
        icon="mdi:water-sync",
        options=RUNOFF_ESTIMATOR_MODES,
    ),
    # The controller's shot check: off until someone chooses (the AI shot judge alone, as before).
    SelectEntityDescription(
        key="shot_check",
        name="Shot check",
        icon="mdi:water-check",
        options=SHOT_CHECK_MODES,
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
    # Safety and operations (safety_ops.py): each starts at Off, as the room was.
    from .safety_ops import SELECTS

    for description in SELECTS:
        selects.append(CropSteeringSelect(entry, description))

    # Get number of zones from config
    config_data = hass.data[DOMAIN][entry.entry_id]
    num_zones = config_data.get(CONF_NUM_ZONES, 1)

    # Add zone-specific select entities
    ec_types = set()
    for zone_num in range(1, num_zones + 1):
        # Zone Steering Mode (per-row Vegetative/Generative; the engine falls back to global).
        # Retained from the lean branch: the master app's _zone_is_vegetative() reads this
        # for per-zone veg/gen EC-target selection.
        selects.append(
            CropSteeringSelect(
                entry,
                SelectEntityDescription(
                    key=f"zone_{zone_num}_steering_mode",
                    name=f"Crop Steering Zone {zone_num} Steering mode",
                    options=["Vegetative", "Generative"],
                    icon="mdi:steering",
                ),
                zone_num=zone_num,
            )
        )

        # How the zone waters in P2: on moisture (the default, as always), on a timer, or on a timer
        # that skips a slot at its ceiling and keeps the moisture top-up as a floor rescue.
        selects.append(
            CropSteeringSelect(
                entry,
                SelectEntityDescription(
                    key=f"zone_{zone_num}_p2_mode",
                    name=f"Zone {zone_num} P2 mode",
                    options=P2_MODES,
                    icon="mdi:timer-cog",
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
                    name=f"Zone {zone_num} set phase",
                    options=SET_PHASE_OPTIONS,
                    icon="mdi:state-machine",
                ),
                zone_num=zone_num,
            )
        )

        # How the zone's probes become its moisture reading, and apart its EC reading: Median
        # unless chosen otherwise (Lowest and Highest need three probes that agree). The zone's
        # VWC and EC sensors apply it; the controller steers on those.
        for metric, label, icon in (
            ("vwc", "Moisture", "mdi:water-percent"),
            ("ec", "EC", "mdi:lightning-bolt"),
        ):
            selects.append(
                CropSteeringSelect(
                    entry,
                    SelectEntityDescription(
                        key=f"zone_{zone_num}_{metric}_method",
                        name=f"Zone {zone_num} {label} from probes",
                        options=PROBE_METHODS,
                        icon=icon,
                    ),
                    zone_num=zone_num,
                )
            )

        # What each of the zone's EC probes measures, pore or bulk EC: unknown until someone
        # says, which fuses as before. The zone's EC sensor never combines a pore with a bulk
        # reading (calculations.fuse_probes).
        zone_config = config_data.get("zones", {})
        zone_config = zone_config.get(zone_num) or zone_config.get(str(zone_num)) or {}
        probes = list(zone_config.get("ec_sensors", [])) or [
            zone_config.get("ec_front"),
            zone_config.get("ec_back"),
        ]
        for probe in probes:
            key = probe and ec_type_key(probe)
            if not key or key in ec_types:
                continue
            ec_types.add(key)
            selects.append(
                CropSteeringSelect(
                    entry,
                    SelectEntityDescription(
                        key=key,
                        name=f"EC type {probe}",
                        options=EC_TYPES,
                        icon="mdi:lightning-bolt-outline",
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
        self._since = None  # ai_no_touch: when the current option was chosen

        # Set default values based on entity type
        if description.key == "growth_stage":
            self._attr_current_option = "Vegetative"
        elif (
            description.key == "drainage"
            and entry.data.get("drainage") in DRAINAGE_TYPES
        ):
            self._attr_current_option = entry.data["drainage"]  # setup's answer
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
                self._since = last_state.attributes.get("since")
        # The recipe stage's source of truth is the server-side recipe Store, not
        # the restored entity state — reflect the loaded recipe's active stage.
        if self.entity_description.key == "recipe_stage":
            mgr = get_manager(self.hass, self._entry)
            if mgr is not None and mgr.active_stage in self.options:
                self._attr_current_option = mgr.active_stage
            # The apply_recipe service shows its stage here (see sync_stage).
            self.hass.data.setdefault(DOMAIN, {}).setdefault("_recipe_selects", {})[
                self._entry.entry_id
            ] = self

    async def async_will_remove_from_hass(self) -> None:
        """Stop offering this select to the apply_recipe service."""
        if self.entity_description.key == "recipe_stage":
            self.hass.data.get(DOMAIN, {}).get("_recipe_selects", {}).pop(
                self._entry.entry_id, None
            )

    def sync_stage(self) -> None:
        """Show the recipe's active stage without applying anything."""
        mgr = get_manager(self.hass, self._entry)
        if mgr is not None and mgr.active_stage in self.options:
            self._attr_current_option = mgr.active_stage
            self.async_write_ha_state()

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
            self._since = dt_util.utcnow().isoformat()
            self.async_write_ha_state()
            # Announce a manual phase pick on the event bus for automations. The controller
            # keeps each zone's phase itself and does not read this select.
            if getattr(self.entity_description, "key", None) == "irrigation_phase":
                note_deprecated(
                    self.hass,
                    "irrigation_phase",
                    "Choosing a value in the Irrigation phase select (it moves no zone)",
                    "Move one zone by hand with its Set phase select.",
                )
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
                note_deprecated(
                    self.hass,
                    "recipe_stage",
                    "Choosing a value in the Recipe stage select",
                    "Set the targets of the room in the dashboard, or use a grow plan.",
                )
                mgr = get_manager(self.hass, self._entry)
                if mgr is not None:
                    await mgr.async_apply(option)

    @property
    def extra_state_attributes(self):
        """Expose the full recipe table on the recipe_stage select so the
        dashboard can read it (and edit via the save_recipe service)."""
        if self.entity_description.key == "ai_no_touch":
            return {"since": self._since}
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
