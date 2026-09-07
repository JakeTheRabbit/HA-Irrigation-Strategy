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


def test_concurrent_room_setup_registers_one_panel_and_one_static_path(monkeypatch):
    from custom_components.crop_steering import setup_panel

    registered = set()
    calls = []
    paths = []
    frontend = ModuleType("homeassistant.components.frontend")

    def register_panel(*args, **kwargs):
        panel = kwargs["frontend_url_path"]
        if panel in registered:
            raise ValueError(f"Overwriting panel {panel}")
        registered.add(panel)
        calls.append(kwargs)

    frontend.async_panel_exists = lambda hass, panel: panel in registered
    frontend.async_register_built_in_panel = register_panel
    components = ModuleType("homeassistant.components")
    components.frontend = frontend
    http = ModuleType("homeassistant.components.http")
    http.StaticPathConfig = lambda *args: args
    monkeypatch.setitem(sys.modules, "homeassistant.components", components)
    monkeypatch.setitem(sys.modules, "homeassistant.components.frontend", frontend)
    monkeypatch.setitem(sys.modules, "homeassistant.components.http", http)

    async def register_paths(items):
        paths.extend(items)
        # Both config-entry setup tasks reach this await before either can register.
        await asyncio.sleep(0)

    hass = SimpleNamespace(
        data={}, http=SimpleNamespace(async_register_static_paths=register_paths)
    )

    async def setup_both():
        await asyncio.gather(
            setup_panel.async_setup_panel(hass), setup_panel.async_setup_panel(hass)
        )

    asyncio.run(setup_both())
    assert registered == {"crop-steering"}
    assert len(calls) == len(paths) == 1


def _panel_rig(monkeypatch, legacy=False):
    from custom_components.crop_steering import setup_panel

    observed = SimpleNamespace(
        panels=set(),
        registrations=[],
        removals=[],
        paths=[],
        path_attempts=0,
        panel_attempts=0,
        path_failures=0,
        panel_failures=0,
        during_static=None,
    )
    frontend = ModuleType("homeassistant.components.frontend")

    def register_panel(*args, **kwargs):
        observed.panel_attempts += 1
        if observed.panel_failures:
            observed.panel_failures -= 1
            raise RuntimeError("frontend not ready")
        panel = kwargs["frontend_url_path"]
        if panel in observed.panels:
            raise ValueError(f"Overwriting panel {panel}")
        observed.panels.add(panel)
        observed.registrations.append(kwargs)

    def remove_panel(hass, panel):
        observed.panels.remove(panel)
        observed.removals.append(panel)

    def register_static(items):
        observed.path_attempts += 1
        if observed.path_failures:
            observed.path_failures -= 1
            raise RuntimeError("HTTP registration failed")
        observed.paths.extend(items)
        if observed.during_static:
            observed.during_static()

    async def register_paths(items):
        await asyncio.sleep(0)
        register_static(items)

    frontend.async_panel_exists = lambda hass, panel: panel in observed.panels
    frontend.async_register_built_in_panel = register_panel
    frontend.async_remove_panel = remove_panel
    components = ModuleType("homeassistant.components")
    components.frontend = frontend
    http = ModuleType("homeassistant.components.http")
    http.StaticPathConfig = lambda *args: args
    for name, module in (
        ("homeassistant.components", components),
        ("homeassistant.components.frontend", frontend),
        ("homeassistant.components.http", http),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    transport = (
        SimpleNamespace(register_static_path=lambda *args: register_static([args]))
        if legacy
        else SimpleNamespace(async_register_static_paths=register_paths)
    )
    return setup_panel, SimpleNamespace(data={}, http=transport), observed


def test_panel_registration_failure_releases_lock_for_waiting_room(monkeypatch):
    panel, hass, observed = _panel_rig(monkeypatch)
    observed.panel_failures = 1

    async def concurrent_retry():
        return await asyncio.gather(
            panel.async_setup_panel(hass),
            panel.async_setup_panel(hass),
            return_exceptions=True,
        )

    results = asyncio.run(concurrent_retry())
    assert isinstance(results[0], RuntimeError) and results[1] is None
    assert observed.panel_attempts == 2
    assert observed.path_attempts == 1
    assert observed.panels == {panel.PANEL}


def test_static_registration_failure_is_retried_without_false_success(monkeypatch):
    panel, hass, observed = _panel_rig(monkeypatch)
    observed.path_failures = 1

    async def concurrent_retry():
        return await asyncio.gather(
            panel.async_setup_panel(hass),
            panel.async_setup_panel(hass),
            return_exceptions=True,
        )

    results = asyncio.run(concurrent_retry())
    assert isinstance(results[0], RuntimeError) and results[1] is None
    assert observed.path_attempts == 2 and len(observed.paths) == 1
    assert observed.panel_attempts == 1


def test_existing_foreign_panel_is_neither_registered_nor_removed(monkeypatch):
    panel, hass, observed = _panel_rig(monkeypatch)
    observed.panels.add(panel.PANEL)
    asyncio.run(panel.async_setup_panel(hass))
    panel.async_unload_panel(hass)
    assert observed.panels == {panel.PANEL}
    assert observed.path_attempts == observed.panel_attempts == 0
    assert observed.removals == []


def test_foreign_panel_appearing_during_http_await_is_preserved(monkeypatch):
    panel, hass, observed = _panel_rig(monkeypatch)
    observed.during_static = lambda: observed.panels.add(panel.PANEL)
    asyncio.run(panel.async_setup_panel(hass))
    panel.async_unload_panel(hass)
    assert observed.panels == {panel.PANEL}
    assert observed.panel_attempts == 0 and observed.removals == []


def test_unregister_then_register_keeps_the_existing_static_path(monkeypatch):
    panel, hass, observed = _panel_rig(monkeypatch)
    asyncio.run(panel.async_setup_panel(hass))
    panel.async_unload_panel(hass)
    assert observed.panels == set()
    asyncio.run(panel.async_setup_panel(hass))
    assert observed.panels == {panel.PANEL}
    assert observed.path_attempts == 1 and observed.panel_attempts == 2
    assert observed.removals == [panel.PANEL]


def test_ha_2024_3_legacy_static_path_registration_is_still_supported(monkeypatch):
    panel, hass, observed = _panel_rig(monkeypatch, legacy=True)
    asyncio.run(panel.async_setup_panel(hass))
    asyncio.run(panel.async_setup_panel(hass))
    assert observed.path_attempts == observed.panel_attempts == 1
    assert observed.paths[0][0] == "/crop_steering"
    assert observed.paths[0][2] is False
