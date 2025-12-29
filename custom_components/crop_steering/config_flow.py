"""Config flow for Crop Steering System integration."""
from __future__ import annotations

import logging
import os
import yaml
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, CONF_NUM_ZONES, MIN_ZONES, MAX_ZONES, DEFAULT_NUM_ZONES
from .env_parser import load_env_config

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("name", default="Crop Steering System"): str,
        vol.Required("config_method", default="env"): vol.In({
            "env": "Load from crop_steering.env file (Recommended)",
            "manual": "Manual UI configuration",
        }),
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
        """Handle the initial step - choose config method."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=STEP_USER_DATA_SCHEMA,
                description_placeholders={
                    "info": "Choose how to configure the Crop Steering System. "
                    ".env file is recommended for initial setup (automatic zone detection). "
                    "UI configuration allows manual entry but requires more steps."
                }
            )

        errors = {}

        # Check if there's an existing entry
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        # Store user input
        self._data.update(user_input)

        # Route based on chosen configuration method
        if user_input["config_method"] == "env":
            return await self.async_step_load_env()
        else:
            return await self.async_step_manual_zones()

    async def async_step_load_env(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Load configuration from crop_steering.env file."""
        env_path = os.path.join(self.hass.config.config_dir, "crop_steering.env")

        if not os.path.exists(env_path):
            return self.async_abort(
                reason="env_not_found",
                description_placeholders={
                    "path": env_path,
                    "message": f"File not found: {env_path}\n\n"
                    "Please create crop_steering.env in your Home Assistant config directory, "
                    "or choose Manual configuration."
                }
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
                    }
                )

            # Validate entity IDs
            missing_entities = await self._validate_env_entities(env_config)
            if missing_entities:
                return self.async_show_form(
                    step_id="load_env",
                    data_schema=vol.Schema({
                        vol.Required("ignore_missing", default=False): bool
                    }),
                    errors={"base": "missing_entities"},
                    description_placeholders={
                        "missing": "\n".join(missing_entities[:10]),
                        "count": str(len(missing_entities))
                    }
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
                    "message": "Failed to parse crop_steering.env file. Please check the format."
                }
            )

    async def async_step_manual_zones(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manual configuration - ask how many zones."""
        if user_input is None:
            return self.async_show_form(
                step_id="manual_zones",
                data_schema=vol.Schema({
                    vol.Required(CONF_NUM_ZONES, default=DEFAULT_NUM_ZONES): vol.All(
                        vol.Coerce(int), vol.Range(min=MIN_ZONES, max=MAX_ZONES)
                    ),
                }),
                description_placeholders={
                    "info": f"Configure {MIN_ZONES}-{MAX_ZONES} irrigation zones. "
                    "Each zone can have independent sensors and controls."
                }
            )

        # Store number of zones and proceed to basic configuration
        self._data[CONF_NUM_ZONES] = user_input[CONF_NUM_ZONES]

        return await self.async_step_zones()

    async def async_step_load_yaml(self, user_input: dict[str, Any] | None = None) -> FlowResult:
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
            entities_to_validate.extend([v for k, v in hardware.items() if v and isinstance(v, str) and "." in v])
        if env_sensors := config.get("environmental_sensors"):
            entities_to_validate.extend([v for k, v in env_sensors.items() if v and isinstance(v, str) and "." in v])
        
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
                zones_config[zone_id].update({
                    "vwc_front": sensors.get("vwc_front"),
                    "vwc_back": sensors.get("vwc_back"),
                    "ec_front": sensors.get("ec_front"),
                    "ec_back": sensors.get("ec_back"),
                })
                entities_to_validate.extend([v for k, v in sensors.items() if v and isinstance(v, str) and "." in v])

        missing_entities = [
            entity for entity in entities_to_validate if entity and not self.hass.states.get(entity)
        ]

        if missing_entities:
            return self.async_abort(
                reason="missing_entities",
                description_placeholders={"missing": "\n".join(missing_entities[:5])},
            )

        # Build data for config entry
        hardware_config = {**config.get("irrigation_hardware", {}), **config.get("environmental_sensors", {})}
        
        data = {
            "installation_mode": "yaml",
            "name": self._data.get("name", "Crop Steering System"),
            CONF_NUM_ZONES: len(zones_config),
            "zones": zones_config,
            "hardware": hardware_config,
            "config_yaml": config, # Store the full yaml config
        }
        
        return self.async_create_entry(
            title=data["name"],
            data=data,
        )

    async def async_step_zones(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Configure zones manually."""
        # For now, create a basic configuration without detailed zone setup
        # This can be expanded in the future for manual configuration
        
        data = {
            "installation_mode": "manual",
            "name": self._data.get("name", "Crop Steering System"),
            CONF_NUM_ZONES: self._data.get(CONF_NUM_ZONES, DEFAULT_NUM_ZONES),
            "zones": {},
            "hardware": {},
        }
        
        return self.async_create_entry(
            title=data["name"],
            data=data,
        )


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
                if key in ["zone_switch", "vwc_front", "vwc_back", "ec_front", "ec_back"]:
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

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage the options."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["reload_env", "edit_parameters", "edit_zones", "edit_features"]
        )

    async def async_step_reload_env(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Reload configuration from .env file."""
        if self.config_entry.data.get("config_method") != "env":
            return self.async_abort(
                reason="not_env_config",
                description_placeholders={
                    "message": "This integration was not configured from .env file. "
                    "Use 'Edit Parameters' or 'Edit Zones' instead."
                }
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
                }
            )

            return self.async_create_entry(
                title="",
                data={
                    "reloaded": True,
                    "zones_detected": env_config["num_zones"]
                }
            )

        except Exception as e:
            _LOGGER.error(f"Error reloading .env: {e}")
            return self.async_abort(reason="reload_failed")

    async def async_step_edit_parameters(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Edit irrigation parameters via UI."""
        if user_input is not None:
            # Update parameters in config entry
            new_data = {**self.config_entry.data}
            if "parameters" not in new_data:
                new_data["parameters"] = {}
            new_data["parameters"].update(user_input)

            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=new_data
            )

            return self.async_create_entry(title="", data={})

        # Get current parameters
        current_params = self.config_entry.data.get("parameters", {})

        return self.async_show_form(
            step_id="edit_parameters",
            data_schema=vol.Schema({
                vol.Optional(
                    "substrate_volume",
                    default=current_params.get("substrate_volume", 10.0)
                ): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=200.0)),
                vol.Optional(
                    "dripper_flow_rate",
                    default=current_params.get("dripper_flow_rate", 2.0)
                ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=50.0)),
                vol.Optional(
                    "p1_target_vwc",
                    default=current_params.get("p1_target_vwc", 65.0)
                ): vol.All(vol.Coerce(float), vol.Range(min=30.0, max=95.0)),
                vol.Optional(
                    "p2_vwc_threshold",
                    default=current_params.get("p2_vwc_threshold", 60.0)
                ): vol.All(vol.Coerce(float), vol.Range(min=25.0, max=85.0)),
            }),
            description_placeholders={
                "info": "Edit irrigation parameters. Changes take effect immediately. "
                "You can also edit these via number entities in Home Assistant."
            }
        )

    async def async_step_edit_zones(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Edit zone configuration via UI."""
        return self.async_show_menu(
            step_id="edit_zones",
            menu_options=[f"zone_{i}" for i in range(1, self.config_entry.data.get("num_zones", 1) + 1)]
        )

    async def async_step_edit_features(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Edit feature flags."""
        if user_input is not None:
            new_data = {**self.config_entry.data}
            if "features" not in new_data:
                new_data["features"] = {}
            new_data["features"].update(user_input)

            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=new_data
            )

            return self.async_create_entry(title="", data={})

        current_features = self.config_entry.data.get("features", {})

        return self.async_show_form(
            step_id="edit_features",
            data_schema=vol.Schema({
                vol.Optional(
                    "ec_stacking",
                    default=current_features.get("ec_stacking", False)
                ): bool,
                vol.Optional(
                    "analytics",
                    default=current_features.get("analytics", True)
                ): bool,
                vol.Optional(
                    "ml_features",
                    default=current_features.get("ml_features", False)
                ): bool,
            })
        )