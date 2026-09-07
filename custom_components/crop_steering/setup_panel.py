"""Serve the bundled operator dashboard without copying files or sidebar YAML."""

from pathlib import Path

from .const import DOMAIN

PANEL = "crop-steering"
URL = "/crop_steering"


async def async_setup_panel(hass):
    from homeassistant.components import frontend

    state = hass.data.setdefault(DOMAIN, {}).setdefault("_setup", {})
    if state.get("panel_registered") or frontend.async_panel_exists(hass, PANEL):
        return
    if not state.get("static_registered"):
        directory = str(Path(__file__).parent / "www")
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
    frontend.async_register_built_in_panel(
        hass,
        "iframe",
        sidebar_title="Crop Steering",
        sidebar_icon="mdi:sprout",
        frontend_url_path=PANEL,
        config={"url": f"{URL}/dashboard.html"},
        require_admin=False,
    )
    state["panel_registered"] = True


def async_unload_panel(hass):
    """Remove only the panel we registered, after the final entry unloads."""
    from homeassistant.components import frontend

    if hass.data.get(DOMAIN, {}).get("_setup", {}).pop("panel_registered", False):
        frontend.async_remove_panel(hass, PANEL)
