"""Serve the bundled operator dashboard without copying files or sidebar YAML."""

import asyncio
from pathlib import Path

from .const import DOMAIN, SOFTWARE_VERSION

PANEL = "crop-steering"
URL = "/crop_steering"
WWW = Path(__file__).parent / "www"
# The panel's element (www/panel.js): it holds the dashboard in a frame the size of the panel.
ELEMENT = "crop-steering-panel"


def _panel_exists(hass, frontend) -> bool:
    """Whether the sidebar path is already taken, on every supported Home Assistant.

    `frontend.async_panel_exists` only arrived in Home Assistant 2026.5.0. Called
    unconditionally it raised AttributeError inside async_setup_entry on anything older, so
    the config entry failed to set up - no entities, no dashboard - on the 2024.3+ this
    integration says it supports. The fallback is what that helper does: look in the
    frontend's own panel table, whose key has been the same since before 2024.3.
    """
    exists = getattr(frontend, "async_panel_exists", None)
    if exists is not None:
        return exists(hass, PANEL)
    return PANEL in hass.data.get(
        getattr(frontend, "DATA_PANELS", "frontend_panels"), {}
    )


async def async_setup_panel(hass):
    from homeassistant.components import frontend

    state = hass.data.setdefault(DOMAIN, {}).setdefault("_setup", {})
    # Config entries set up concurrently. Hold the shared lock across static-path
    # registration so another room cannot pass the panel guard during that await.
    lock = state.setdefault("panel_lock", asyncio.Lock())
    async with lock:
        if state.get("panel_registered") or _panel_exists(hass, frontend):
            return
        if not state.get("static_registered"):
            directory = str(WWW)
            if hasattr(hass.http, "async_register_static_paths"):
                from homeassistant.components.http import StaticPathConfig

                await hass.http.async_register_static_paths(
                    [StaticPathConfig(URL, directory, False)]
                )
            else:
                # HA 2024.3 predates the async API introduced in June 2024.
                # This fallback is only used when the old API is actually present.
                hass.http.register_static_path(URL, directory, False)
            state["static_registered"] = True
        # Another integration can claim this route while HTTP registration yields.
        # Leave its panel unowned so our unload never removes it.
        if _panel_exists(hass, frontend):
            return
        # The page is served without cache headers, so a browser can keep showing the
        # previous release's copy for hours after an update. A new version is a new URL.
        config = {"url": f"{URL}/dashboard.html?v={SOFTWARE_VERSION}"}
        component = "iframe"
        # A custom panel where its element ships: Home Assistant draws its own title bar above
        # an iframe panel and none above a custom panel. `_panel_custom` is what
        # panel_custom.async_register_panel registers, without depending on panel_custom. It is
        # Home Assistant's internal shape, so the built-in iframe panel on the same URL stays
        # the fallback.
        if (WWW / "panel.js").is_file():
            component = "custom"
            config["_panel_custom"] = {
                "name": ELEMENT,
                "module_url": f"{URL}/panel.js?v={SOFTWARE_VERSION}",
                "embed_iframe": False,
                "trust_external": False,
            }
        frontend.async_register_built_in_panel(
            hass,
            component,
            sidebar_title="Crop Steering",
            sidebar_icon="mdi:sprout",
            frontend_url_path=PANEL,
            config=config,
            require_admin=False,
        )
        state["panel_registered"] = True


def async_unload_panel(hass):
    """Remove only the panel we registered, after the final entry unloads."""
    from homeassistant.components import frontend

    if hass.data.get(DOMAIN, {}).get("_setup", {}).pop("panel_registered", False):
        frontend.async_remove_panel(hass, PANEL)
