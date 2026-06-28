"""Config flow for Crop Steering System integration."""

from __future__ import annotations

import logging
import os
import yaml
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_NUM_ZONES,
    MIN_ZONES,
    MAX_ZONES,
    DEFAULT_NUM_ZONES,
    CONF_PUMP_SWITCH,
    CONF_MAIN_LINE_SWITCH,
)
from .env_parser import load_env_config
from .room import slugify_room

_LOGGER = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# UI entity-mapping helpers (shared by the setup wizard and the reconfigure flow)
# --------------------------------------------------------------------------
def _sw_sel():
    return selector.EntitySelector(selector.EntitySelectorConfig(domain="switch"))


def _sensor_multi():
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain="sensor", multiple=True)
    )


def _sensor_one():
    return selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))


def _light_sel():
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=["light", "switch"])
    )


def _as_list(v):
    if not v:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _zone_schema(num_zones: int, zones: dict | None = None) -> dict:
    """Build the {marker: selector} map for per-zone entity mapping, prefilled from
    an existing `zones` dict (env_parser/config-entry shape)."""
    zones = zones or {}
    out: dict = {}
    for z in range(1, int(num_zones) + 1):
        zc = zones.get(str(z)) or zones.get(z) or {}
        sw = zc.get("zone_switch") or ""
        vwc = zc.get("vwc_sensors") or (
            _as_list(zc.get("vwc_front")) + _as_list(zc.get("vwc_back"))
        )
        ec = zc.get("ec_sensors") or (
            _as_list(zc.get("ec_front")) + _as_list(zc.get("ec_back"))
        )
        pc = zc.get("plant_count", 4)
        out[
            (
                vol.Required(f"zone_{z}_switch", default=sw)
                if sw
                else vol.Required(f"zone_{z}_switch")
            )
        ] = _sw_sel()
        out[vol.Optional(f"zone_{z}_vwc", default=vwc)] = _sensor_multi()
        out[vol.Optional(f"zone_{z}_ec", default=ec)] = _sensor_multi()
        out[vol.Optional(f"zone_{z}_plant_count", default=pc)] = vol.All(
            vol.Coerce(int), vol.Range(min=1, max=1000)
        )
    return out


def _hardware_schema(hardware: dict | None = None, params: dict | None = None) -> dict:
    """Build the {marker: selector} map for shared hardware + substrate properties."""
    hardware = hardware or {}
    params = params or {}

    def _ent(key, sel):
        val = hardware.get(key) or ""
        out[vol.Optional(key, default=val) if val else vol.Optional(key)] = sel

    out: dict = {}
    _ent("pump_switch", _sw_sel())
    _ent("main_line_switch", _sw_sel())
    _ent("waste_switch", _sw_sel())
    _ent("light_entity", _light_sel())
    out[vol.Optional("lights_on_hour", default=params.get("lights_on_hour", 12))] = (
        vol.All(vol.Coerce(int), vol.Range(min=0, max=23))
    )
    out[vol.Optional("lights_off_hour", default=params.get("lights_off_hour", 0))] = (
        vol.All(vol.Coerce(int), vol.Range(min=0, max=23))
    )
    out[
        vol.Optional("substrate_volume", default=params.get("substrate_volume", 6.0))
    ] = vol.All(vol.Coerce(float), vol.Range(min=0.1, max=200.0))
    out[
        vol.Optional("dripper_flow_rate", default=params.get("dripper_flow_rate", 2.0))
    ] = vol.All(vol.Coerce(float), vol.Range(min=0.1, max=50.0))
    out[
        vol.Optional("drippers_per_plant", default=params.get("drippers_per_plant", 1))
    ] = vol.All(vol.Coerce(int), vol.Range(min=1, max=20))
    out[vol.Optional("field_capacity", default=params.get("field_capacity", 70.0))] = (
        vol.All(vol.Coerce(float), vol.Range(min=30.0, max=95.0))
    )
    out[vol.Optional("max_ec", default=params.get("max_ec", 9.0))] = vol.All(
        vol.Coerce(float), vol.Range(min=1.0, max=15.0)
    )
    _ent("temperature_sensor", _sensor_one())
    _ent("humidity_sensor", _sensor_one())
    _ent("vpd_sensor", _sensor_one())
    _ent("water_level_sensor", _sensor_one())
    out[
        vol.Optional(
            "notification_service", default=hardware.get("notification_service") or ""
        )
    ] = str
    return out


def _build_zones(num_zones: int, data: dict) -> dict:
    """Build the config-entry `zones` dict (env_parser shape) from submitted form data."""
    zones: dict = {}
    for z in range(1, int(num_zones) + 1):
        vwc = _as_list(data.get(f"zone_{z}_vwc"))
        ec = _as_list(data.get(f"zone_{z}_ec"))
        zones[str(z)] = {
            "zone_number": z,
            "zone_switch": data.get(f"zone_{z}_switch", ""),
            "vwc_sensors": vwc,
            "ec_sensors": ec,
            "vwc_front": vwc[0] if vwc else "",
            "vwc_back": vwc[1] if len(vwc) > 1 else "",
            "ec_front": ec[0] if ec else "",
            "ec_back": ec[1] if len(ec) > 1 else "",
            "plant_count": int(data.get(f"zone_{z}_plant_count", 4)),
            "max_daily_volume": 20.0,
            "shot_multiplier": 1.0,
        }
    return zones


def _build_hardware(data: dict) -> dict:
    return {
        "pump_switch": data.get("pump_switch", ""),
        "main_line_switch": data.get("main_line_switch", ""),
        "waste_switch": data.get("waste_switch", ""),
        "light_entity": data.get("light_entity", ""),
        "temperature_sensor": data.get("temperature_sensor", ""),
        "humidity_sensor": data.get("humidity_sensor", ""),
        "vpd_sensor": data.get("vpd_sensor", ""),
        "water_level_sensor": data.get("water_level_sensor", ""),
        "notification_service": data.get("notification_service", ""),
    }


def _build_parameters(data: dict) -> dict:
    return {
        "substrate_volume": data.get("substrate_volume", 6.0),
        "dripper_flow_rate": data.get("dripper_flow_rate", 2.0),
        "drippers_per_plant": data.get("drippers_per_plant", 1),
        "field_capacity": data.get("field_capacity", 70.0),
        "max_ec": data.get("max_ec", 9.0),
        "lights_on_hour": data.get("lights_on_hour", 12),
        "lights_off_hour": data.get("lights_off_hour", 0),
    }


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("name", default="Crop Steering System"): str,
        vol.Required("config_method", default="env"): vol.In(
            {
                "env": "Load from crop_steering.env file (Recommended)",
                "manual": "Manual UI configuration",
            }
        ),
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Crop Steering System."""

    VERSION = 1

    def __init__(self):
        """Initialize config flow."""
        self._data = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Initial step. The first config is the default (un-prefixed) room — existing
        single-room installs are unchanged. Any further config adds another fully-isolated
        room (own zones/sensors/pump/setpoints), namespaced as crop_steering_<slug>_*."""
        # A room already exists -> this is an additional room (UI-mapped, prefixed).
        if self._async_current_entries():
            return await self.async_step_room()

        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=STEP_USER_DATA_SCHEMA,
                description_placeholders={
                    "info": "Choose how to configure the Crop Steering System. "
                    ".env file is recommended for initial setup (automatic zone detection). "
                    "UI configuration allows manual entry but requires more steps."
                },
            )

        await self.async_set_unique_id("default")
        self._abort_if_unique_id_configured()
        self._data.update(user_input)
        self._data["room_prefix"] = ""
        self._data["room_name"] = user_input.get("name", "Crop Steering")

        if user_input["config_method"] == "env":
            return await self.async_step_load_env()
        return await self.async_step_manual_zones()

    async def async_step_room(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Name an additional, fully-isolated room, then map it in the UI."""
        if user_input is None:
            return self.async_show_form(
                step_id="room",
                data_schema=vol.Schema({vol.Required("room_name"): str}),
                description_placeholders={
                    "info": "Name this room (e.g. Veg, Flower B). It gets its own zones, "
                    "sensors, pump and setpoints — completely isolated from your other rooms."
                },
            )
        slug = slugify_room(user_input["room_name"])
        await self.async_set_unique_id(f"room_{slug}")
        self._abort_if_unique_id_configured()
        self._data["name"] = user_input["room_name"]
        self._data["room_name"] = user_input["room_name"]
        self._data["room_slug"] = slug
        self._data["room_prefix"] = f"{slug}_"
        return await self.async_step_manual_zones()

    async def async_step_load_env(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Load configuration from crop_steering.env file."""
        env_path = os.path.join(self.hass.config.config_dir, "crop_steering.env")

        if not os.path.exists(env_path):
            return self.async_abort(
                reason="env_not_found",
                description_placeholders={
                    "path": env_path,
                    "message": f"File not found: {env_path}\n\n"
                    "Please create crop_steering.env in your Home Assistant config directory, "
                    "or choose Manual configuration.",
                },
            )

        try:
            # Load and parse .env file
            env_config = load_env_config(self.hass.config.config_dir)

            if env_config["num_zones"] == 0:
                return self.async_abort(
                    reason="no_zones_configured",
                    description_placeholders={
                        "message": "No zones detected in crop_steering.env file. "
                        "Please add at least one ZONE_N_SWITCH entry."
                    },
                )

            # Validate entity IDs (skip if user chose to ignore missing)
            ignore_missing = (
                user_input.get("ignore_missing", False) if user_input else False
            )
            missing_entities = await self._validate_env_entities(env_config)
            if missing_entities and not ignore_missing:
                return self.async_show_form(
                    step_id="load_env",
                    data_schema=vol.Schema(
                        {vol.Required("ignore_missing", default=False): bool}
                    ),
                    errors={"base": "missing_entities"},
                    description_placeholders={
                        "missing": "\n".join(missing_entities[:10]),
                        "count": str(len(missing_entities)),
                    },
                )

            # Create entry with .env configuration
            _LOGGER.info(
                f"Creating entry from .env: {env_config['num_zones']} zones, "
                f"zones: {list(env_config['zones'].keys())}"
            )

            return self.async_create_entry(
                title=f"Crop Steering ({env_config['num_zones']} zones from .env)",
                data={
                    "name": self._data.get("name", "Crop Steering System"),
                    "config_method": "env",
                    "room_name": self._data.get("room_name", "Crop Steering"),
                    "room_prefix": "",
                    "room_slug": "default",
                    "num_zones": env_config["num_zones"],
                    "zones": env_config["zones"],
                    "hardware": env_config["hardware"],
                    "parameters": env_config["parameters"],
                    "features": env_config["features"],
                    "env_file_path": env_path,
                },
            )

        except Exception as e:
            _LOGGER.error(f"Error loading .env file: {e}", exc_info=True)
            return self.async_abort(
                reason="env_parse_error",
                description_placeholders={
                    "error": str(e),
                    "message": "Failed to parse crop_steering.env file. Please check the format.",
                },
            )

    async def async_step_manual_zones(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manual configuration - ask how many zones."""
        if user_input is None:
            return self.async_show_form(
                step_id="manual_zones",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_NUM_ZONES, default=DEFAULT_NUM_ZONES
                        ): vol.All(
                            vol.Coerce(int), vol.Range(min=MIN_ZONES, max=MAX_ZONES)
                        ),
                    }
                ),
                description_placeholders={
                    "info": f"Configure {MIN_ZONES}-{MAX_ZONES} irrigation zones. "
                    "Each zone can have independent sensors and controls."
                },
            )

        # Store number of zones and proceed to basic configuration
        self._data[CONF_NUM_ZONES] = user_input[CONF_NUM_ZONES]

        return await self.async_step_zones()

    async def async_step_load_yaml(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Load configuration from config.yaml."""
        config_path = os.path.join(self.hass.config.config_dir, "config.yaml")

        if not os.path.exists(config_path):
            return self.async_abort(reason="yaml_not_found")

        try:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)
        except yaml.YAMLError:
            return self.async_abort(reason="yaml_error")

        # Basic validation
        if not isinstance(config, dict) or "zones" not in config:
            return self.async_abort(reason="yaml_invalid_format")

        # Extract and validate entities
        entities_to_validate = []
        if hardware := config.get("irrigation_hardware"):
            entities_to_validate.extend(
                [
                    v
                    for k, v in hardware.items()
                    if v and isinstance(v, str) and "." in v
                ]
            )
        if env_sensors := config.get("environmental_sensors"):
            entities_to_validate.extend(
                [
                    v
                    for k, v in env_sensors.items()
                    if v and isinstance(v, str) and "." in v
                ]
            )

        zones_config = {}
        for zone in config.get("zones", []):
            zone_id = zone.get("zone_id")
            if not zone_id:
                continue

            zones_config[zone_id] = {
                "zone_number": zone_id,
                "zone_switch": zone.get("switch"),
            }
            entities_to_validate.append(zone.get("switch"))

            if sensors := zone.get("sensors"):
                zones_config[zone_id].update(
                    {
                        "vwc_front": sensors.get("vwc_front"),
                        "vwc_back": sensors.get("vwc_back"),
                        "ec_front": sensors.get("ec_front"),
                        "ec_back": sensors.get("ec_back"),
                    }
                )
                entities_to_validate.extend(
                    [
                        v
                        for k, v in sensors.items()
                        if v and isinstance(v, str) and "." in v
                    ]
                )

        missing_entities = [
            entity
            for entity in entities_to_validate
            if entity and not self.hass.states.get(entity)
        ]

        if missing_entities:
            return self.async_abort(
                reason="missing_entities",
                description_placeholders={"missing": "\n".join(missing_entities[:5])},
            )

        # Build data for config entry
        hardware_config = {
            **config.get("irrigation_hardware", {}),
            **config.get("environmental_sensors", {}),
        }

        data = {
            "installation_mode": "yaml",
            "name": self._data.get("name", "Crop Steering System"),
            CONF_NUM_ZONES: len(zones_config),
            "zones": zones_config,
            "hardware": hardware_config,
            "config_yaml": config,  # Store the full yaml config
        }

        return self.async_create_entry(
            title=data["name"],
            data=data,
        )

    async def async_step_zones(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Map each zone's valve and sensors via entity pickers."""
        num = int(self._data.get(CONF_NUM_ZONES, DEFAULT_NUM_ZONES))
        if user_input is None:
            return self.async_show_form(
                step_id="zones",
                data_schema=vol.Schema(_zone_schema(num)),
                description_placeholders={
                    "info": f"Pick the valve and probe(s) for each of your {num} zones. "
                    "You can choose MORE THAN ONE moisture/EC sensor per zone — the engine "
                    "averages them and rejects outliers."
                },
            )
        self._data["zones"] = _build_zones(num, user_input)
        return await self.async_step_hardware()

    async def async_step_hardware(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Map shared hardware (pump/mainline/lights) and substrate properties."""
        if user_input is None:
            return self.async_show_form(
                step_id="hardware",
                data_schema=vol.Schema(_hardware_schema()),
                description_placeholders={
                    "info": "Shared plumbing, lights and the substrate facts used to size shots. "
                    "Leave Pump empty if your system auto-starts the pump on flow."
                },
            )
        data = {
            "installation_mode": "manual",
            "config_method": "manual",
            "name": self._data.get("name", "Crop Steering System"),
            "room_name": self._data.get("room_name", "Crop Steering"),
            "room_prefix": self._data.get("room_prefix", ""),
            "room_slug": self._data.get("room_slug", "default"),
            CONF_NUM_ZONES: int(self._data.get(CONF_NUM_ZONES, DEFAULT_NUM_ZONES)),
            "zones": self._data.get("zones", {}),
            "hardware": _build_hardware(user_input),
            "parameters": _build_parameters(user_input),
            "features": {"ec_stacking": False, "analytics": True, "ml_features": False},
        }
        return self.async_create_entry(title=data["name"], data=data)

    async def _validate_entities(self, user_input: dict) -> dict:
        """Validate that entity IDs exist in Home Assistant."""
        errors = {}

        # List of entity keys to validate
        entity_keys = [
            "zone_switch",
            "vwc_front",
            "vwc_back",
            "ec_front",
            "ec_back",
            CONF_PUMP_SWITCH,
            CONF_MAIN_LINE_SWITCH,
        ]

        for key in entity_keys:
            entity_id = user_input.get(key, "").strip()
            if entity_id and not self.hass.states.get(entity_id):
                _LOGGER.warning(f"Entity ID not found: {entity_id}")
                errors[key] = "entity_not_found"

        return errors

    async def _validate_env_entities(self, env_config: dict) -> list[str]:
        """Validate entity IDs from .env configuration."""
        missing = []

        # Check hardware entities
        for key, entity_id in env_config.get("hardware", {}).items():
            if entity_id and not self.hass.states.get(entity_id):
                missing.append(f"{key}: {entity_id}")

        # Check zone entities
        for zone_num, zone_config in env_config.get("zones", {}).items():
            for key, entity_id in zone_config.items():
                if key in [
                    "zone_switch",
                    "vwc_front",
                    "vwc_back",
                    "ec_front",
                    "ec_back",
                ]:
                    if entity_id and not self.hass.states.get(entity_id):
                        missing.append(f"Zone {zone_num} {key}: {entity_id}")

        return missing

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class EntityNotFound(HomeAssistantError):
    """Error to indicate entity ID does not exist."""


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Crop Steering System."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        """Initialize options flow."""
        self.config_entry = config_entry
        self._edit_num: int | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "reload_env",
                "edit_parameters",
                "edit_zones",
                "edit_features",
            ],
        )

    async def async_step_reload_env(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Reload configuration from .env file."""
        if self.config_entry.data.get("config_method") != "env":
            return self.async_abort(
                reason="not_env_config",
                description_placeholders={
                    "message": "This integration was not configured from .env file. "
                    "Use 'Edit Parameters' or 'Edit Zones' instead."
                },
            )

        try:
            # Reload .env file
            env_config = load_env_config(self.hass.config.config_dir)

            # Update config entry
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    **self.config_entry.data,
                    "num_zones": env_config["num_zones"],
                    "zones": env_config["zones"],
                    "hardware": env_config["hardware"],
                    "parameters": env_config["parameters"],
                    "features": env_config["features"],
                },
            )

            return self.async_create_entry(
                title="",
                data={"reloaded": True, "zones_detected": env_config["num_zones"]},
            )

        except Exception as e:
            _LOGGER.error(f"Error reloading .env: {e}")
            return self.async_abort(reason="reload_failed")

    async def async_step_edit_parameters(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit irrigation parameters via UI."""
        if user_input is not None:
            # Update parameters in config entry
            new_data = {**self.config_entry.data}
            if "parameters" not in new_data:
                new_data["parameters"] = {}
            new_data["parameters"].update(user_input)

            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )

            return self.async_create_entry(title="", data={})

        # Get current parameters
        current_params = self.config_entry.data.get("parameters", {})

        return self.async_show_form(
            step_id="edit_parameters",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "substrate_volume",
                        default=current_params.get("substrate_volume", 10.0),
                    ): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=200.0)),
                    vol.Optional(
                        "dripper_flow_rate",
                        default=current_params.get("dripper_flow_rate", 2.0),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=50.0)),
                    vol.Optional(
                        "p1_target_vwc",
                        default=current_params.get("p1_target_vwc", 65.0),
                    ): vol.All(vol.Coerce(float), vol.Range(min=30.0, max=95.0)),
                    vol.Optional(
                        "p2_vwc_threshold",
                        default=current_params.get("p2_vwc_threshold", 60.0),
                    ): vol.All(vol.Coerce(float), vol.Range(min=25.0, max=85.0)),
                }
            ),
            description_placeholders={
                "info": "Edit irrigation parameters. Changes take effect immediately. "
                "You can also edit these via number entities in Home Assistant."
            },
        )

    async def async_step_edit_zones(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Reconfigure zones — step 1: how many zones (add or remove)."""
        cur = int(self.config_entry.data.get("num_zones", 1))
        if user_input is None:
            return self.async_show_form(
                step_id="edit_zones",
                data_schema=vol.Schema(
                    {
                        vol.Required("num_zones", default=cur): vol.All(
                            vol.Coerce(int), vol.Range(min=MIN_ZONES, max=MAX_ZONES)
                        ),
                    }
                ),
                description_placeholders={
                    "info": "Set how many zones you have. Increase it to ADD a zone, decrease to "
                    "remove the highest ones. You'll map entities on the next screen."
                },
            )
        self._edit_num = int(user_input["num_zones"])
        return await self.async_step_edit_zones_map()

    async def async_step_edit_zones_map(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Reconfigure zones — step 2: remap valves/sensors and shared hardware."""
        num = getattr(self, "_edit_num", None) or int(
            self.config_entry.data.get("num_zones", 1)
        )
        data = self.config_entry.data
        if user_input is None:
            schema = {
                **_zone_schema(num, data.get("zones", {})),
                **_hardware_schema(
                    data.get("hardware", {}), data.get("parameters", {})
                ),
            }
            return self.async_show_form(
                step_id="edit_zones_map",
                data_schema=vol.Schema(schema),
                description_placeholders={
                    "info": "Add, remove or swap the sensors and switches for each zone. "
                    "Pick multiple moisture/EC probes per zone if you have them — they get fused."
                },
            )
        new_data = {
            **data,
            "num_zones": num,
            "zones": _build_zones(num, user_input),
            "hardware": {**data.get("hardware", {}), **_build_hardware(user_input)},
            "parameters": {
                **data.get("parameters", {}),
                **_build_parameters(user_input),
            },
        }
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
        await self.hass.config_entries.async_reload(self.config_entry.entry_id)
        return self.async_create_entry(title="", data={})

    async def async_step_edit_features(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit feature flags."""
        if user_input is not None:
            new_data = {**self.config_entry.data}
            if "features" not in new_data:
                new_data["features"] = {}
            new_data["features"].update(user_input)

            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )

            return self.async_create_entry(title="", data={})

        current_features = self.config_entry.data.get("features", {})

        return self.async_show_form(
            step_id="edit_features",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "ec_stacking",
                        default=current_features.get("ec_stacking", False),
                    ): bool,
                    vol.Optional(
                        "analytics", default=current_features.get("analytics", True)
                    ): bool,
                    vol.Optional(
                        "ml_features",
                        default=current_features.get("ml_features", False),
                    ): bool,
                }
            ),
        )
