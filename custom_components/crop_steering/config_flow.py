"""Config flow for Crop Steering System integration."""

from __future__ import annotations

import json
import logging
import os
import yaml
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from .const import (
    SOFTWARE_VERSION,
    DOMAIN,
    CONF_NUM_ZONES,
    MIN_ZONES,
    MAX_ZONES,
    DEFAULT_NUM_ZONES,
    CONF_PUMP_SWITCH,
    CONF_MAIN_LINE_SWITCH,
)
from .env_parser import load_env_config
from .plumbing import PLUMBING_LAYOUTS, infer as infer_plumbing
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


def _plumbing_sel():
    # Shown as a list, not a dropdown: four choices, and a newcomer should see all of them.
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=list(PLUMBING_LAYOUTS),
            translation_key="plumbing",
            mode=selector.SelectSelectorMode.LIST,
        )
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
        out[vol.Optional(f"zone_{z}_name", default=zc.get("name", f"Zone {z}"))] = str
        out[vol.Optional(f"zone_{z}_active", default=zc.get("active", True))] = bool
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


def _hardware_schema(
    hardware: dict | None = None,
    params: dict | None = None,
    plumbing: str | None = None,
) -> dict:
    """Build the {marker: selector} map for shared hardware + substrate properties.

    `plumbing` prefills the layout question: what the room declared, or for a room from before
    the question existed, what its mapped switches imply. A new room gets no prefill, so the
    person setting it up answers it rather than accepting a guess.
    """
    hardware = hardware or {}
    params = params or {}

    def _ent(key, sel):
        # Prefilled as a SUGGESTED value, not a default. With `default=` the frontend dropped an
        # emptied field and voluptuous put the default straight back, so a mapping could be
        # swapped but never removed - and the pump and main-line are optional now, so removing
        # one has to work. The form still opens showing the mapping, so a save cannot wipe it.
        val = hardware.get(key) or ""
        out[
            (
                vol.Optional(key, description={"suggested_value": val})
                if val
                else vol.Optional(key)
            )
        ] = sel

    out: dict = {}
    out[
        (
            vol.Required("plumbing", default=plumbing)
            if plumbing
            else vol.Required("plumbing")
        )
    ] = _plumbing_sel()
    _ent("pump_switch", _sw_sel())
    _ent("main_line_switch", _sw_sel())
    _ent("waste_switch", _sw_sel())
    # Per-room source-water probes (optional). Map this room's reservoir EC/pH probes to
    # enable its source-water gate; leave empty to disable that gate for the room. (The
    # default room can also set these via the add-on options.)
    _ent("feed_ec_sensor", _sensor_one())
    _ent("feed_ph_sensor", _sensor_one())
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
    _ent("tank_temperature_sensor", _sensor_one())
    _ent("tank_ec_sensor", _sensor_one())
    _ent("tank_ph_sensor", _sensor_one())
    _ent(
        "tank_last_fill_sensor",
        selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["sensor", "input_datetime"])
        ),
    )
    _ent(
        "tank_fill_entity",
        selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["switch", "binary_sensor"])
        ),
    )
    out[
        vol.Optional(
            "notification_service", default=hardware.get("notification_service") or ""
        )
    ] = str
    return out


def _build_zones(num_zones: int, data: dict, existing: dict | None = None) -> dict:
    """Build the config-entry `zones` dict (env_parser shape) from submitted form data."""
    zones: dict = {str(k): {**v, "active": False} for k, v in (existing or {}).items()}
    for z in range(1, int(num_zones) + 1):
        vwc = _as_list(data.get(f"zone_{z}_vwc"))
        ec = _as_list(data.get(f"zone_{z}_ec"))
        zones[str(z)] = {
            **((existing or {}).get(str(z)) or (existing or {}).get(z) or {}),
            "zone_number": z,
            "active": data.get(
                f"zone_{z}_active",
                ((existing or {}).get(str(z)) or {}).get("active", True),
            ),
            "name": data.get(f"zone_{z}_name")
            or ((existing or {}).get(str(z)) or {}).get("name", f"Zone {z}"),
            "zone_switch": data.get(f"zone_{z}_switch", ""),
            "vwc_sensors": vwc,
            "ec_sensors": ec,
            "vwc_front": vwc[0] if vwc else "",
            "vwc_back": vwc[1] if len(vwc) > 1 else "",
            "ec_front": ec[0] if ec else "",
            "ec_back": ec[1] if len(ec) > 1 else "",
            "plant_count": int(data.get(f"zone_{z}_plant_count", 4)),
            "max_daily_volume": ((existing or {}).get(str(z)) or {}).get(
                "max_daily_volume", 20.0
            ),
            "shot_multiplier": ((existing or {}).get(str(z)) or {}).get(
                "shot_multiplier", 1.0
            ),
        }
    return zones


def _build_hardware(data: dict) -> dict:
    return {
        "pump_switch": data.get("pump_switch", ""),
        "main_line_switch": data.get("main_line_switch", ""),
        "waste_switch": data.get("waste_switch", ""),
        "feed_ec_sensor": data.get("feed_ec_sensor", ""),
        "feed_ph_sensor": data.get("feed_ph_sensor", ""),
        "light_entity": data.get("light_entity", ""),
        "temperature_sensor": data.get("temperature_sensor", ""),
        "humidity_sensor": data.get("humidity_sensor", ""),
        "vpd_sensor": data.get("vpd_sensor", ""),
        "water_level_sensor": data.get("water_level_sensor", ""),
        "tank_temperature_sensor": data.get("tank_temperature_sensor", ""),
        "tank_ec_sensor": data.get("tank_ec_sensor", ""),
        "tank_ph_sensor": data.get("tank_ph_sensor", ""),
        "tank_last_fill_sensor": data.get("tank_last_fill_sensor", ""),
        "tank_fill_entity": data.get("tank_fill_entity", ""),
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
        vol.Required("config_method", default="manual"): vol.In(
            {
                "manual": "Search and select devices (Recommended)",
                "env": "Load from crop_steering.env file (advanced)",
            }
        ),
    }
)


def _retry_form(flow, step_id, schema, user_input, info, error):
    """Show the same step again with everything typed still in it, and say what is wrong.

    These steps used to abort: one entity that was ON, unreachable or mistyped threw away every
    zone, sensor and sizing entry. Home Assistant prefills a schema from the last submission.
    """
    prefill = getattr(flow, "add_suggested_values_to_schema", None)
    return flow.async_show_form(
        step_id=step_id,
        data_schema=prefill(schema, user_input) if prefill else schema,
        errors={"base": "setup_invalid"},
        description_placeholders={
            "info": f"{info}\n\n**Not saved yet.** {error}",
            "error": str(error),
        },
    )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Crop Steering System."""

    VERSION = 1

    def __init__(self):
        """Initialize config flow."""
        self._data = {}

    def _retry(self, step_id, schema, user_input, info, error):
        return _retry_form(self, step_id, schema, user_input, info, error)

    def _check(self, data):
        """Validate what has been entered so far, at the step it was entered on."""
        from .setup_api import configuration_payload, prepare_setup, safety_blockers

        prepared = prepare_setup(self.hass, configuration_payload(data), data)
        blockers = safety_blockers(self.hass, proposed=prepared)
        if blockers:
            raise ValueError("; ".join(blockers))
        return prepared

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Initial step. The first config is the default (un-prefixed) room — existing
        single-room installs are unchanged. Any further config adds another fully-isolated
        room (own zones/sensors/pump/setpoints), namespaced as crop_steering_<slug>_*.
        """
        # Never set a room up on code that is waiting for a restart: whatever it creates is
        # created by the OLD code, and entity ids are for life.
        running, waiting = await _versions(self.hass)
        if waiting:
            return self.async_abort(
                reason="restart_required",
                description_placeholders={"running": running, "installed": waiting},
            )
        if user_input is not None and "setup_payload" in user_input:
            from .setup_api import prepare_setup, safety_blockers

            try:
                data = prepare_setup(self.hass, user_input["setup_payload"])
                named = bool(self._async_current_entries())
                slug = slugify_room(data["room_name"]) if named else "default"
                if named and slug == "default":
                    return self.async_abort(reason="reserved_room_name")
                await self.async_set_unique_id(f"room_{slug}" if named else "default")
                self._abort_if_unique_id_configured()
                data.update(
                    room_slug=slug,
                    room_prefix=f"{slug}_" if named else "",
                    config_method="manual",
                    setup_revision=1,
                )
                data["enable_flag"] = (
                    f"switch.crop_steering_{data['room_prefix']}engine_enabled"
                )
                blockers = safety_blockers(self.hass, proposed=data)
                if blockers:
                    raise ValueError("; ".join(blockers))
                return self.async_create_entry(title=data["room_name"], data=data)
            except ValueError as err:
                return self.async_abort(
                    reason="setup_invalid", description_placeholders={"error": str(err)}
                )
        # A room already exists -> this is an additional room (UI-mapped, prefixed).
        if self._async_current_entries():
            return await self.async_step_room()

        if user_input is None:
            running, _waiting = await _versions(self.hass)
            return self.async_show_form(
                step_id="user",
                data_schema=STEP_USER_DATA_SCHEMA,
                description_placeholders={
                    "info": "Choose how to configure the Crop Steering System. "
                    "Select devices with searchable pickers (recommended). "
                    "Advanced users can import an existing .env file.",
                    "version": running,
                    "restart_notice": "",
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

    async def async_step_room(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Name an additional, fully-isolated room, then map it in the UI."""
        if user_input is None:
            return self.async_show_form(
                step_id="room",
                data_schema=vol.Schema({vol.Required("room_name"): str}),
                description_placeholders={
                    "info": "Name this room (e.g. Veg, Flower B). It gets its own zones, "
                    "sensors, pump and setpoints — completely isolated from your other rooms.",
                    "version": SOFTWARE_VERSION,
                },
            )
        slug = slugify_room(user_input["room_name"])
        if slug == "default":
            return self.async_abort(reason="reserved_room_name")
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

        if not await self.hass.async_add_executor_job(os.path.exists, env_path):
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
            # Load and parse .env file off the event loop (file I/O must not block it)
            env_config = await self.hass.async_add_executor_job(
                load_env_config, self.hass.config.config_dir
            )

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

        def _read_yaml():
            # Existence check + read + parse together, off the event loop.
            if not os.path.exists(config_path):
                return None
            with open(config_path, "r") as f:
                return yaml.safe_load(f)

        try:
            config = await self.hass.async_add_executor_job(_read_yaml)
        except yaml.YAMLError:
            return self.async_abort(reason="yaml_error")

        if config is None:
            return self.async_abort(reason="yaml_not_found")

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
        info = (
            f"Pick the valve and probe(s) for each of your {num} zones. "
            "You can choose MORE THAN ONE moisture/EC sensor per zone — the engine "
            "averages valid readings. Outliers are not automatically rejected."
        )
        if user_input is None:
            return self.async_show_form(
                step_id="zones",
                data_schema=vol.Schema(_zone_schema(num)),
                description_placeholders={"info": info},
            )
        zones = _build_zones(num, user_input)
        try:  # a valve that is ON or a probe in the wrong unit is reported here, not three screens later
            self._check(
                {
                    "room_name": self._data.get("room_name", "Crop Steering"),
                    "room_prefix": self._data.get("room_prefix", ""),
                    "enable_flag": f"switch.crop_steering_{self._data.get('room_prefix', '')}engine_enabled",
                    "zones": zones,
                }
            )
        except ValueError as err:
            return self._retry(
                "zones", vol.Schema(_zone_schema(num)), user_input, info, err
            )
        self._data["zones"] = zones
        return await self.async_step_hardware()

    async def async_step_hardware(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Map shared hardware (pump/mainline/lights) and substrate properties."""
        info = (
            "Shared plumbing, lights and the substrate facts used to size shots. Start by saying how "
            "the room is plumbed: a room with one switch per zone, such as a tent on a single smart "
            "plug, is zone valves only and needs nothing more than the valves you have already "
            "picked. If water only flows while a pump runs, say so and choose the pump."
        )
        if user_input is None:
            return self.async_show_form(
                step_id="hardware",
                data_schema=vol.Schema(_hardware_schema()),
                description_placeholders={"info": info},
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
        data["enable_flag"] = (
            f"switch.crop_steering_{data['room_prefix']}engine_enabled"
        )
        if user_input.get("plumbing"):
            data["plumbing"] = user_input["plumbing"]
        try:
            data = self._check(data)
        except ValueError as err:
            return self._retry(
                "hardware", vol.Schema(_hardware_schema()), user_input, info, err
            )
        data["setup_revision"] = 1
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


def _installed_version() -> str | None:
    """The version in manifest.json ON DISK, which is what HACS last downloaded. Blocking: call
    it in the executor. None when it cannot be read, which never stops anybody."""
    try:
        manifest = json.loads(
            (Path(__file__).parent / "manifest.json").read_text(encoding="utf-8")
        )
        version = manifest.get("version")
    except (OSError, ValueError, AttributeError):
        return None
    return version if isinstance(version, str) and version else None


async def _versions(hass) -> tuple[str, str | None]:
    """(running, waiting). `running` is the code Home Assistant loaded when it started; HACS
    replaces the files and Home Assistant goes on running the old ones until it restarts.
    `waiting` is the version on disk when it differs, else None.

    2026-09-21: 2.19.2 was on disk, code from before 2.18.0 was running, and nothing said so.
    Setup was run twice on it, Home Assistant named every entity, and the controller could not
    find one of them.
    """
    installed = await hass.async_add_executor_job(_installed_version)
    return SOFTWARE_VERSION, (
        installed if installed and installed != SOFTWARE_VERSION else None
    )


def _restart_notice(running: str, waiting: str | None) -> str:
    if not waiting:
        return ""
    return (
        f"⚠️ Home Assistant is still running {running}, but {waiting} is installed. Restart "
        "Home Assistant to run it: an update downloaded by HACS does nothing until then."
    )


def _number_range(key: str) -> vol.Range:
    """The limits of this integration's own number entity for `key`: one definition, in
    number.py, so a form can never refuse a value the entity it edits accepts, nor write one the
    entity then rejects. Imported here, not at module level: number.py is an entity platform.
    """
    from .number import NUMBER_DESCRIPTIONS

    described = next(d for d in NUMBER_DESCRIPTIONS if d.key == key)
    return vol.Range(min=described.native_min_value, max=described.native_max_value)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Crop Steering System."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        """Initialize options flow."""
        self._entry = config_entry
        self._edit_num: int | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        running, waiting = await _versions(self.hass)
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "reload_env",
                "edit_parameters",
                "edit_zones",
                "edit_features",
            ],
            # Not blocked while an update waits for a restart: an operator with a growing room
            # has to be able to get in here. It is told what is going on instead.
            description_placeholders={
                "version": running,
                "restart_notice": _restart_notice(running, waiting),
            },
        )

    async def async_step_reload_env(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Reload configuration from .env file."""
        if self._entry.data.get("config_method") != "env":
            return self.async_abort(
                reason="not_env_config",
                description_placeholders={
                    "message": "This integration was not configured from .env file. "
                    "Use 'Edit Parameters' or 'Edit Zones' instead."
                },
            )

        try:
            # Reload .env file off the event loop (file I/O must not block it)
            env_config = await self.hass.async_add_executor_job(
                load_env_config, self.hass.config.config_dir
            )

            from .setup_api import (
                effective,
                configuration_payload,
                prepare_setup,
                safety_blockers,
                _update,
            )

            prior = effective(self._entry)
            zones = {
                str(k): {**v, "active": False}
                for k, v in prior.get("zones", {}).items()
            }
            for key, zone in env_config["zones"].items():
                zones[str(key)] = {**zones.get(str(key), {}), **zone, "active": True}
            proposed = {
                **prior,
                "num_zones": max(
                    int(prior.get("num_zones", 1)), env_config["num_zones"]
                ),
                "zones": zones,
                "hardware": {**prior.get("hardware", {}), **env_config["hardware"]},
                "parameters": {
                    **prior.get("parameters", {}),
                    **env_config["parameters"],
                },
                "features": {**prior.get("features", {}), **env_config["features"]},
            }
            proposed = prepare_setup(
                self.hass,
                configuration_payload(proposed),
                proposed,
                self._entry.entry_id,
            )
            blockers = safety_blockers(self.hass, self._entry, proposed)
            if blockers:
                raise ValueError("; ".join(blockers))
            _update(self.hass, self._entry, proposed)

            return self.async_create_entry(
                title="",
                data={"reloaded": True, "zones_detected": env_config["num_zones"]},
            )

        except Exception as e:
            _LOGGER.error(f"Error reloading .env: {e}")
            return self.async_abort(reason="reload_failed")

    def _number_id(self, key: str) -> str:
        from .setup_api import effective

        prefix = effective(self._entry).get("room_prefix", "")
        return f"number.crop_steering_{prefix}{key}"

    def _live_numbers(self, keys) -> dict:
        """{key: value} for each of this room's number entities that has a numeric state."""
        live = {}
        for key in keys:
            state = self.hass.states.get(self._number_id(key))
            try:
                live[key] = float(state.state)
            except (AttributeError, TypeError, ValueError):
                continue  # absent or unavailable: the caller falls back to what setup recorded
        return live

    async def _set_live_numbers(self, values: dict) -> None:
        for key, value in values.items():
            if self.hass.states.get(self._number_id(key)) is None:
                continue
            await self.hass.services.async_call(
                "number",
                "set_value",
                {"entity_id": self._number_id(key), "value": value},
                blocking=True,
            )

    async def async_step_edit_parameters(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit irrigation parameters via UI."""
        from .setup_api import effective, safety_blockers, _update

        if user_input is not None:
            blockers = safety_blockers(self.hass, self._entry)
            if blockers:
                return self.async_abort(
                    reason="setup_invalid",
                    description_placeholders={"error": "; ".join(blockers)},
                )
            # The entry's `parameters` only SEED a number entity the first time it is created.
            # After that the entity restores its own last value, so updating `parameters` alone
            # saved the edit, reloaded, and each number restored the old value over the top:
            # nothing the engine reads ever changed. Write the live entities first; the reload
            # that follows then restores the value just written.
            await self._set_live_numbers(user_input)
            new_data = effective(self._entry)
            new_data["parameters"] = {**new_data.get("parameters", {}), **user_input}
            _update(self.hass, self._entry, new_data)

            return self.async_create_entry(title="", data={})

        # What the engine is reading NOW. The recorded `parameters` go stale the moment a number
        # is changed on a dashboard, so showing them here presented an old value as current.
        current_params = {
            **effective(self._entry).get("parameters", {}),
            **self._live_numbers(
                (
                    "substrate_volume",
                    "dripper_flow_rate",
                    "p1_target_vwc",
                    "p2_vwc_threshold",
                )
            ),
        }

        # The form opens on the live entities, so it takes their limits too. It used to restate
        # them, and demanded a P1 target of at least 30 and a P2 threshold of at least 25 where
        # the entities accept 5: a room steering lower could not submit this form even unchanged.
        return self.async_show_form(
            step_id="edit_parameters",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        key, default=current_params.get(key, fallback)
                    ): vol.All(vol.Coerce(float), _number_range(key))
                    for key, fallback in (
                        ("substrate_volume", 10.0),
                        ("dripper_flow_rate", 2.0),
                        ("p1_target_vwc", 65.0),
                        ("p2_vwc_threshold", 60.0),
                    )
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
        from .setup_api import effective

        cur = int(effective(self._entry).get("num_zones", 1))
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
            self._entry.data.get("num_zones", 1)
        )
        from .setup_api import effective

        data = effective(self._entry)
        schema = vol.Schema(
            {
                **_zone_schema(num, data.get("zones", {})),
                **_hardware_schema(
                    data.get("hardware", {}),
                    data.get("parameters", {}),
                    data.get("plumbing") or infer_plumbing(data.get("hardware", {})),
                ),
            }
        )
        info = (
            "Add, remove or swap the sensors and switches for each zone. "
            "Pick multiple moisture/EC probes per zone if you have them — they get fused."
        )
        if user_input is None:
            return self.async_show_form(
                step_id="edit_zones_map",
                data_schema=schema,
                description_placeholders={"info": info},
            )
        new_data = {
            **data,
            "num_zones": max(num, int(data.get("num_zones", 1))),
            "zones": _build_zones(num, user_input, data.get("zones", {})),
            "hardware": {**data.get("hardware", {}), **_build_hardware(user_input)},
            "parameters": {
                **data.get("parameters", {}),
                **_build_parameters(user_input),
            },
        }
        if user_input.get("plumbing"):
            new_data["plumbing"] = user_input["plumbing"]
        from .setup_api import (
            configuration_payload,
            prepare_setup,
            safety_blockers,
            _update,
        )

        try:
            new_data = prepare_setup(
                self.hass,
                configuration_payload(new_data),
                new_data,
                self._entry.entry_id,
            )
            blockers = safety_blockers(self.hass, self._entry, new_data)
            if blockers:
                raise ValueError("; ".join(blockers))
        except ValueError as err:
            return _retry_form(self, "edit_zones_map", schema, user_input, info, err)
        _update(self.hass, self._entry, new_data)
        return self.async_create_entry(title="", data={})

    async def async_step_edit_features(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit feature flags."""
        if user_input is not None:
            new_data = {**self._entry.data}
            if "features" not in new_data:
                new_data["features"] = {}
            new_data["features"].update(user_input)

            self.hass.config_entries.async_update_entry(self._entry, data=new_data)

            return self.async_create_entry(title="", data={})

        current_features = self._entry.data.get("features", {})

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
