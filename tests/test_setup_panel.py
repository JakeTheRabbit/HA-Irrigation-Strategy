"""The bundled dashboard is registered once and preserves another owner's panel."""

import asyncio
import sys
from types import ModuleType, SimpleNamespace


def test_panel_registration_uses_async_paths_and_never_replaces_existing_panel(
    monkeypatch,
):
    from custom_components.crop_steering import setup_panel

    calls = []
    frontend = ModuleType("homeassistant.components.frontend")
    frontend.async_register_built_in_panel = lambda *a, **k: calls.append(k)
    frontend.async_remove_panel = lambda *a: calls.append("removed")
    frontend.async_panel_exists = lambda *a: False
    components = ModuleType("homeassistant.components")
    components.frontend = frontend
    http = ModuleType("homeassistant.components.http")
    http.StaticPathConfig = lambda *a: a
    monkeypatch.setitem(sys.modules, "homeassistant.components", components)
    monkeypatch.setitem(sys.modules, "homeassistant.components.frontend", frontend)
    monkeypatch.setitem(sys.modules, "homeassistant.components.http", http)
    paths = []

    async def register(items):
        paths.extend(items)

    hass = SimpleNamespace(
        data={}, http=SimpleNamespace(async_register_static_paths=register)
    )
    asyncio.run(setup_panel.async_setup_panel(hass))
    asyncio.run(setup_panel.async_setup_panel(hass))
    assert len(paths) == len(calls) == 1
    assert calls[0]["config"]["url"] == "/crop_steering/dashboard.html"
    assert calls[0]["frontend_url_path"] == "crop-steering"
    assert paths[0][0] == "/crop_steering"
    assert paths[0][2] is False
    setup_panel.async_unload_panel(hass)
    assert calls[-1] == "removed"
    frontend.async_panel_exists = lambda *a: True
    asyncio.run(setup_panel.async_setup_panel(hass))
    assert len(calls) == 2
