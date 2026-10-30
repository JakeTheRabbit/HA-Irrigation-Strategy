"""Tests that run inside a REAL Home Assistant (pytest-homeassistant-custom-component).

Everything under tests/ drives the integration against hand-written stubs. That is fast, and it is
also how 2.17.0 shipped two switches whose entity ids Home Assistant generated from their labels:
the stub tests asserted an attribute the real entity platform ignores. These tests load the real
config flow and the real entity registry, so they fail when Home Assistant would.

Run: `python -m pytest tests_ha -q` on Python 3.14.2+ with requirements-test-ha.txt installed (the
Home Assistant versions CI runs are in docs/TESTING.md). They are kept out of tests/ because that
suite replaces the `homeassistant` package with stubs.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import custom_components
import pytest
from aiohttp.test_utils import TestServer
from homeassistant.setup import async_setup_component

# The test plugin ships its own `custom_components` package (its sample integrations) and imports it
# first, so Home Assistant's loader would never look in this repository. Add ours to that package's
# search path; nothing in the repository layout has to change for the tests.
_OURS = str(Path(__file__).resolve().parents[1] / "custom_components")
if _OURS not in custom_components.__path__:
    custom_components.__path__.append(_OURS)


@pytest.fixture(autouse=True)
def _custom_integrations(hass, enable_custom_integrations):
    """Let Home Assistant load custom_components/crop_steering from this repository.

    The manifest depends on `frontend` and `http` for one thing only: the sidebar panel. The real
    frontend needs the `hass_frontend` wheel and a listening web server, neither of which these
    tests are about, so both are marked as already set up and only the WEB SERVER is stood in for.

    The panel registration itself runs, against the real `homeassistant.components.frontend`.
    It used to be replaced with a no-op here, and that is how an AttributeError on every Home
    Assistant older than 2026.5 got past this tier: `frontend.async_panel_exists` only exists from
    2026.5.0, the entry failed to set up, and no test ever executed the line.
    The config flow, the entity platforms and the registries are all real."""
    hass.config.components.update({"frontend", "http"})
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    yield


@pytest.fixture(autouse=True)
def _config_dir_per_test(hass, tmp_path):
    """The event journal's file (<config>/crop_steering/journal.db) belongs to one test, never shared."""
    hass.config.config_dir = str(tmp_path)
    yield


@pytest.fixture
async def real_api(hass, socket_enabled):
    """Home Assistant's real REST API, with its auth and ban middlewares, served on a loopback port:
    the address (ending in /api) for the controller's own `requests` code. The one thing stood in for
    is the HTTP component's own listener start, which would bind port 8123. A module that uses this
    overrides `_custom_integrations` (above, which puts a MagicMock in place of `http`) with one that
    only enables the custom integrations.

    Only a server is started, never an aiohttp client: nothing here sends through aiohttp, and a
    client's session builds aiohttp's DNS resolver, which with aiodns installed creates a pycares
    channel, and a recent pycares starts a process-long thread for it that the test plugin's
    leaked-thread check fails on (the plugin with Home Assistant 2024.10 predates that thread)."""
    with patch("homeassistant.components.http.HomeAssistantHTTP.start", AsyncMock()):
        assert await async_setup_component(hass, "http", {})
        assert await async_setup_component(hass, "api", {})
    server = TestServer(hass.http.app)
    server.app._router.freeze = lambda: None  # as the plugin's aiohttp_client: views added later still serve
    await server.start_server()
    yield str(server.make_url("/api"))
    await server.close()


# ------------------------------------------------------------------ seeded old installs
FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict:
    """A snapshot of an OLD install, as that version actually wrote it (tests_ha/fixtures/)."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ------------------------------------------------------------------ the real add-on controller
_ADDON = Path(__file__).resolve().parents[1] / "addons" / "f2_control"
for _path in (_ADDON / "f2_control", _ADDON / "tests"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


@pytest.fixture(autouse=True)
def _hermetic_controller_state(tmp_path, monkeypatch):
    """The add-on Controller must never read or write this machine's real /data/state.json."""
    monkeypatch.setenv("F2_STATE_PATH", str(tmp_path / "state.json"))
    # It runs as the Home Assistant app (runtime_env.runtime() is "addon"), as the Supervisor starts it.
    monkeypatch.setenv("F2_RUNTIME", "addon")
    monkeypatch.setenv("SUPERVISOR_TOKEN", "test-supervisor-token")
    monkeypatch.delenv("HA_URL", raising=False)


@pytest.fixture
def controller_for(hass, monkeypatch):
    """The REAL add-on controller, looking at this REAL Home Assistant.

    The two layers only ever meet through entity ids and state attributes over REST, and each
    had tests against its own idea of the other. That seam is where a blank install fell
    through (sensor.engine_config vs sensor.crop_steering_engine_config). States are JSON
    round-tripped so the controller sees what the REST API would really send: string dict keys,
    no Python objects.
    """
    import controller
    import fake_ha

    class Clock:
        seconds = 0.0

        def sleep(self, seconds):
            self.seconds += seconds

        def monotonic(self):
            return self.seconds

    def build(options=None, *, saved_state=None, options_file=False):
        """`options_file`: write the options to the data folder's options.json and let the controller
        read it with its own load_options, as the app does, instead of handing it the dict."""
        fake = fake_ha.FakeHA()
        for state in hass.states.async_all():
            attributes = json.loads(json.dumps(dict(state.attributes), default=str))
            fake.set_state(state.entity_id, state.state, attributes)
        if saved_state is not None:  # what the PREVIOUS controller version left in /data
            Path(os.environ["F2_STATE_PATH"]).write_text(
                json.dumps(saved_state), encoding="utf-8"
            )
        clock = Clock()
        monkeypatch.setattr(controller, "_GATE", controller._AuthGate())  # as the app (see above)
        if options_file:
            path = Path(os.environ["F2_STATE_PATH"]).parent / "options.json"
            path.write_text(json.dumps(options or {}), encoding="utf-8")
            monkeypatch.setenv("F2_OPTIONS_PATH", str(path))
            assert controller.load_options.__module__ == "controller"  # the real one, not a stand-in
        else:
            monkeypatch.setattr(controller, "load_options", lambda: dict(options or {}))
        for name in ("ha_get", "ha_get_status", "ha_call", "ha_get_all", "ha_set", "ha_service_response", "ha_fire"):
            monkeypatch.setattr(controller, name, getattr(fake, name))
        # No recorder behind the fake: history is never asked of a real Home Assistant.
        monkeypatch.setattr(controller, "ha_history", lambda entity, since, timeout=12: None)
        monkeypatch.setattr(controller.time, "sleep", clock.sleep)
        monkeypatch.setattr(controller.time, "monotonic", clock.monotonic)
        return controller.Controller(), fake, clock

    return build


def room_of(controller, prefix="tent_"):
    """The controller's room with this entity-id prefix. Every new room has a slug, so the wizard's
    "Tent" is `tent_`; an upgraded room from before that keeps the un-prefixed ids (prefix "")."""
    (room,) = [room for room in controller.rooms if room.prefix == prefix]
    return room


def switch_calls(fake):
    return [
        (service, data["entity_id"])
        for domain, service, data in fake.calls
        if domain == "switch"
    ]
