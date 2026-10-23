"""Crop Steering Services."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .admin import async_require_admin
from .const import (
    DOMAIN,
    MIN_ZONES,
    MAX_ZONES,
    RECIPE_STAGES,
    SERVICE_SET_MANUAL_OVERRIDE,
    SERVICE_APPLY_RECIPE,
    SERVICE_SAVE_RECIPE,
)
from .deprecations import note_deprecated
from .room import room_prefix

_LOGGER = logging.getLogger(__name__)


def _resolve_prefix(hass: HomeAssistant, room_slug: str | None) -> str:
    """Map a service `room` slug to its entity-id prefix.

    Omitted or "default" targets the default (un-prefixed) room, so existing
    single-room callers are unchanged. Where there is no such room (every new room has a
    slug), it targets the only room, and with several rooms it raises: the caller must say
    which. A named slug resolves to that room's ``<slug>_`` prefix via its config entry.
    An unknown slug raises — silently acting on a different room than the caller named is
    exactly the wrong-room hazard the room parameter exists to prevent.
    """
    if not room_slug or room_slug == "default":
        prefixes = {
            room_prefix(entry) for entry in hass.config_entries.async_entries(DOMAIN)
        }
        if "" in prefixes or not prefixes:
            return ""
        if len(prefixes) == 1:
            return prefixes.pop()
        raise HomeAssistantError(
            "Several crop_steering rooms are set up — name the room this call is for"
        )
    for entry in hass.config_entries.async_entries(DOMAIN):
        data = getattr(entry, "data", None) or {}
        if (
            data.get("room_slug") == room_slug
            or room_prefix(entry).rstrip("_") == room_slug
        ):
            return room_prefix(entry)
    raise HomeAssistantError(
        f"Unknown crop_steering room '{room_slug}' — no config entry has that slug"
    )


# Service schemas
MANUAL_OVERRIDE_SCHEMA = vol.Schema(
    {
        vol.Required("zone"): vol.Range(min=MIN_ZONES, max=MAX_ZONES),
        vol.Optional("timeout_minutes"): vol.Range(min=1, max=1440),  # Max 24 hours
        vol.Optional("enable"): cv.boolean,
        vol.Optional("room"): cv.string,
    }
)

# Named-stage recipes
APPLY_RECIPE_SCHEMA = vol.Schema(
    {
        vol.Optional("stage"): vol.In(RECIPE_STAGES),
        vol.Optional("room"): cv.string,
    }
)
SAVE_RECIPE_SCHEMA = vol.Schema(
    {
        vol.Required("recipe"): dict,
        vol.Optional("room"): cv.string,
    }
)

SERVICES = {
    SERVICE_APPLY_RECIPE: {
        "schema": APPLY_RECIPE_SCHEMA,
        "method": "async_apply_recipe",
    },
    SERVICE_SAVE_RECIPE: {
        "schema": SAVE_RECIPE_SCHEMA,
        "method": "async_save_recipe",
    },
    SERVICE_SET_MANUAL_OVERRIDE: {
        "schema": MANUAL_OVERRIDE_SCHEMA,
        "method": "async_set_manual_override",
    },
}


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for crop steering."""

    async def async_set_manual_override(call: ServiceCall) -> None:
        """Set a timed manual override; omitted timeout defaults to one hour."""
        zone = call.data["zone"]
        timeout_minutes = call.data.get("timeout_minutes", 60)  # Default 1 hour
        enable = call.data.get("enable", True)
        room = call.data.get("room")
        prefix = _resolve_prefix(hass, room)

        _LOGGER.info(
            f"Manual override requested: Zone {zone}, Enable: {enable}, Timeout: {timeout_minutes}min"
        )

        # The loaded RestoreEntity owns its deadline and scheduler. The controller
        # currently reads canonical IDs, so reject a renamed switch before success.
        key = f"{prefix}zone_{zone}_manual_override"
        override = hass.data.get(DOMAIN, {}).get("_manual_overrides", {}).get(key)
        if override is None or not override._override_loaded:
            raise HomeAssistantError(
                f"Manual override for room {room or 'default'} zone {zone} is not loaded"
            )
        expected_entity_id = f"switch.{DOMAIN}_{key}"
        if override.entity_id != expected_entity_id:
            raise HomeAssistantError(
                f"Restore the manual override entity ID to {expected_entity_id} in "
                "Home Assistant before using timed overrides; the controller cannot "
                f"read its renamed ID {override.entity_id}"
            )
        await override.async_set_manual_override(enable, timeout_minutes)

        # Preserve the public event for observers; expiry is handled by the switch.
        if enable and timeout_minutes:
            hass.bus.async_fire(
                "crop_steering_manual_override",
                {
                    "zone": zone,
                    "action": "enable_with_timeout",
                    "timeout_minutes": timeout_minutes,
                    "expires_at": override.extra_state_attributes[
                        "manual_override_expires_at"
                    ],
                    "room": room or "default",
                    "timestamp": dt_util.now().isoformat(),
                },
            )
        else:
            hass.bus.async_fire(
                "crop_steering_manual_override",
                {
                    "zone": zone,
                    "action": "disable" if not enable else "enable_permanent",
                    "room": room or "default",
                    "timestamp": dt_util.now().isoformat(),
                },
            )

        _LOGGER.info(
            f"Manual override set for Zone {zone}: {'Enabled' if enable else 'Disabled'}"
        )

    def _recipe_manager(call: ServiceCall, service: str, not_done: str):
        """The named room's RecipeManager (the recipe is per config entry / room).

        Without a room it is the only room's; with several rooms it refuses, even when one
        of them is the un-prefixed default room: a recipe call once acted on every room, so
        an old caller must say which room now rather than be narrowed to one silently.
        """
        room = call.data.get("room")
        managers = list(hass.data.get(DOMAIN, {}).get("_recipe", {}).values())
        if not managers:
            raise HomeAssistantError(f"{service}: recipe store not loaded — {not_done}")
        if not room and len(managers) > 1:
            raise HomeAssistantError(
                "Several crop_steering rooms are set up — name the room this call is for"
            )
        prefix = _resolve_prefix(hass, room)
        for mgr in managers:
            if room_prefix(mgr.entry) == prefix:
                return mgr
        raise HomeAssistantError(
            f"{service}: recipe store of room {room or 'default'} not loaded — {not_done}"
        )

    async def async_apply_recipe(call: ServiceCall) -> None:
        """Apply a recipe stage's setpoints to the zone numbers of one room."""
        note_deprecated(
            hass,
            "apply_recipe",
            "The crop_steering.apply_recipe service",
            "Set the targets of the room in the dashboard, or use a grow plan.",
        )
        stage = call.data.get("stage")
        mgr = _recipe_manager(call, "apply_recipe", "no setpoints were applied")
        applied = await mgr.async_apply(stage)
        _LOGGER.info(
            "apply_recipe: stage=%s wrote %d entities",
            stage or mgr.active_stage,
            applied,
        )
        # Show the applied stage on the recipe_stage select. The select is told directly: going
        # through select.select_option would apply the same stage a second time.
        select = (
            hass.data.get(DOMAIN, {}).get("_recipe_selects", {}).get(mgr.entry.entry_id)
        )
        if select is not None:
            select.sync_stage()

    async def async_save_recipe(call: ServiceCall) -> None:
        """Replace the recipe table of one room."""
        note_deprecated(
            hass,
            "save_recipe",
            "The crop_steering.save_recipe service",
            "Set the targets of the room in the dashboard, or use a grow plan.",
        )
        recipe = call.data["recipe"]
        mgr = _recipe_manager(call, "save_recipe", "recipe was not saved")
        await mgr.async_save(recipe)
        _LOGGER.info(
            "save_recipe: stored recipe with %d stages", len(recipe.get("stages", {}))
        )

    # Register services
    for service_name, service_config in SERVICES.items():
        handler = _admin_only(hass, service_name, locals()[service_config["method"]])
        hass.services.async_register(
            DOMAIN, service_name, handler, schema=service_config["schema"]
        )

    _LOGGER.info("Crop steering services registered")


def _admin_only(hass: HomeAssistant, service_name: str, handler):
    """The handler, run only once the caller has passed the administrator check."""

    async def guarded(call: ServiceCall) -> None:
        await async_require_admin(hass, call, f"{DOMAIN}.{service_name}")
        await handler(call)

    return guarded


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload services."""
    for service_name in SERVICES:
        hass.services.async_remove(DOMAIN, service_name)

    _LOGGER.info("Crop steering services unloaded")
