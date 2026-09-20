"""Tests that run inside a REAL Home Assistant (pytest-homeassistant-custom-component).

Everything under tests/ drives the integration against hand-written stubs. That is fast, and it is
also how 2.17.0 shipped two switches whose entity ids Home Assistant generated from their labels:
the stub tests asserted an attribute the real entity platform ignores. These tests load the real
config flow and the real entity registry, so they fail when Home Assistant would.

Run: `python -m pytest tests_ha -q` on Python 3.13 with requirements-test-ha.txt installed. They are
kept out of tests/ because that suite replaces the `homeassistant` package with stubs.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import custom_components
import pytest

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

    def build(options=None, *, saved_state=None):
        fake = fake_ha.FakeHA()
        for state in hass.states.async_all():
            attributes = json.loads(json.dumps(dict(state.attributes), default=str))
            fake.set_state(state.entity_id, state.state, attributes)
        if saved_state is not None:  # what the PREVIOUS controller version left in /data
            Path(os.environ["F2_STATE_PATH"]).write_text(
                json.dumps(saved_state), encoding="utf-8"
            )
        clock = Clock()
        monkeypatch.setattr(controller, "load_options", lambda: dict(options or {}))
        for name in ("ha_get", "ha_call", "ha_get_all", "ha_set"):
            monkeypatch.setattr(controller, name, getattr(fake, name))
        monkeypatch.setattr(controller.time, "sleep", clock.sleep)
        monkeypatch.setattr(controller.time, "monotonic", clock.monotonic)
        return controller.Controller(), fake, clock

    return build


def switch_calls(fake):
    return [
        (service, data["entity_id"])
        for domain, service, data in fake.calls
        if domain == "switch"
    ]
