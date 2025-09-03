"""Config flow for Crop Steering System integration."""
from __future__ import annotations

import logging
import os
import yaml
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, CONF_NUM_ZONES, MIN_ZONES, MAX_ZONES, DEFAULT_NUM_ZONES

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("name", default="Crop Steering System"): str,
        vol.Required(CONF_NUM_ZONES, default=DEFAULT_NUM_ZONES): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_ZONES, max=MAX_ZONES)
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
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}

        if user_input is not None:
            # Store user input
            self._data.update(user_input)
            
            # Check if there's an existing entry
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

            # Check for YAML configuration first
            config_path = os.path.join(self.hass.config.config_dir, "config.yaml")
            if os.path.exists(config_path):
                return await self.async_step_load_yaml()
            else:
                # Proceed with manual configuration
                return await self.async_step_zones()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

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


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""