"""The Crop Steering System integration."""

from __future__ import annotations

import logging

from typing import Any

try:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.const import Platform
    from homeassistant.core import HomeAssistant, callback
    from homeassistant.exceptions import ConfigEntryNotReady
except ImportError:  # pragma: no cover - enables non-HA unit tests
    ConfigEntry = Any  # type: ignore
    HomeAssistant = Any  # type: ignore
    ConfigEntryNotReady = Exception  # type: ignore

    def callback(func):  # type: ignore
        return func

    class Platform:  # type: ignore
        SENSOR = "sensor"
        SWITCH = "switch"
        SELECT = "select"
        NUMBER = "number"
        BUTTON = "button"


from .const import DOMAIN

try:
    from .services import async_setup_services, async_unload_services
except ImportError:  # pragma: no cover - enables non-HA unit tests

    async def async_setup_services(_hass: HomeAssistant) -> None:
        return None

    async def async_unload_services(_hass: HomeAssistant) -> None:
        return None


_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.BUTTON,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Crop Steering System from a config entry."""
    _LOGGER.info("Setting up Crop Steering System")

    # Set up the integration data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = _entry_config(entry)

    # Load this room's named-stage recipe (server-side Store) before the platforms
    # come up, so the recipe select + sensor can read it on setup.
    try:
        from .recipe import RecipeManager

        manager = RecipeManager(hass, entry)
        await manager.async_init()
        hass.data[DOMAIN].setdefault("_recipe", {})[entry.entry_id] = manager
    except Exception as err:  # pragma: no cover - never block setup on the recipe store
        _LOGGER.warning("Recipe store unavailable: %s", err)

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Set up services
    await async_setup_services(hass)

    # Setup health checks -> Home Assistant Repairs (read-only diagnostics)
    from datetime import timedelta

    from homeassistant.helpers.event import async_call_later, async_track_time_interval

    from .health import run_health_check

    @callback
    def _hc(_now=None):
        run_health_check(hass, entry)

    hass.data[DOMAIN].setdefault("_hc_unsubs", {})[entry.entry_id] = [
        async_call_later(hass, 60, _hc),  # first check once the add-on has booted
        async_track_time_interval(hass, _hc, timedelta(minutes=5)),  # then periodically
    ]

    # Reload the entry when its data/options change (e.g. via the options flow) so
    # entities pick up the new config without an HA restart.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _LOGGER.info("Crop Steering System setup complete")

    return True


def _entry_config(entry: ConfigEntry) -> dict[str, Any]:
    """Return the active config entry payload with options overriding base data."""
    return {
        **(getattr(entry, "data", None) or {}),
        **(getattr(entry, "options", None) or {}),
    }


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its config is updated (options flow, reconfigure)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        # Platforms refused to unload — the entry stays loaded, so leave the
        # health checks, recipe manager and services in place.
        return False

    # Stop the health-check timers and clear any Repairs issues we raised.
    for unsub in (
        hass.data.get(DOMAIN, {}).get("_hc_unsubs", {}).pop(entry.entry_id, [])
    ):
        unsub()
    try:
        from .health import clear_all

        clear_all(hass, entry.data.get("room_slug", "default"))
    except Exception:  # pragma: no cover - defensive
        pass

    hass.data.get(DOMAIN, {}).get("_recipe", {}).pop(entry.entry_id, None)
    hass.data[DOMAIN].pop(entry.entry_id, None)

    # Unload services only when the last loaded room goes away — other loaded
    # entries (multi-room installs) still rely on the shared domain services.
    others_loaded = [
        e
        for e in hass.config_entries.async_loaded_entries(DOMAIN)
        if e.entry_id != entry.entry_id
    ]
    if not others_loaded:
        await async_unload_services(hass)

    return True
