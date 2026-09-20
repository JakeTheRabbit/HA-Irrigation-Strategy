"""Tests that run inside a REAL Home Assistant (pytest-homeassistant-custom-component).

Everything under tests/ drives the integration against hand-written stubs. That is fast, and it is
also how 2.17.0 shipped two switches whose entity ids Home Assistant generated from their labels:
the stub tests asserted an attribute the real entity platform ignores. These tests load the real
config flow and the real entity registry, so they fail when Home Assistant would.

Run: `python -m pytest tests_ha -q` on Python 3.13 with requirements-test-ha.txt installed. They are
kept out of tests/ because that suite replaces the `homeassistant` package with stubs.
"""

from pathlib import Path

import custom_components
import pytest

# The test plugin ships its own `custom_components` package (its sample integrations) and imports it
# first, so Home Assistant's loader would never look in this repository. Add ours to that package's
# search path; nothing in the repository layout has to change for the tests.
_OURS = str(Path(__file__).resolve().parents[1] / "custom_components")
if _OURS not in custom_components.__path__:
    custom_components.__path__.append(_OURS)


@pytest.fixture(autouse=True)
def _custom_integrations(hass, enable_custom_integrations, monkeypatch):
    """Let Home Assistant load custom_components/crop_steering from this repository.

    The manifest depends on `frontend` and `http` for one thing only: the sidebar panel. The real
    frontend needs the `hass_frontend` wheel and a listening web server, neither of which these
    tests are about, so both are marked as already set up and the panel registration is a no-op.
    The config flow, the entity platforms and the registries are all real."""
    hass.config.components.update({"frontend", "http"})

    async def _no_panel(_hass):
        return None

    import custom_components.crop_steering.setup_panel as panel

    monkeypatch.setattr(panel, "async_setup_panel", _no_panel)
    monkeypatch.setattr(panel, "async_unload_panel", lambda _hass: None)
    yield
