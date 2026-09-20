"""The real-Home-Assistant tier.

`tests/` drives the integration against hand-written stubs where voluptuous, the selectors and
the flow base class are no-ops. That is fast, and it is why a wizard that could not be finished
in a real Home Assistant passed every test. Here the integration is loaded by an actual
Home Assistant core (pytest-homeassistant-custom-component): real config entries, a real entity
registry, real restore state, real schema validation and serialisation.

This directory is separate on purpose: `tests/conftest.py` registers fake `homeassistant`
modules, which would shadow the real package.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
ADDON = ROOT / "addons" / "f2_control" / "f2_control"

# HA imports custom integrations as `custom_components.<domain>`; the add-on tests helper
# (FakeHA) and the controller are imported by the cross-layer tests.
for path in (ROOT, ADDON, ROOT / "addons" / "f2_control" / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# The HA test harness bundles its own `custom_components` package and mounts it at the front of
# sys.path when a test core starts. Import THIS repo's package first so it is the one cached,
# and refuse to run at all if something else won: a green run against the wrong code is worse
# than no run.
import custom_components  # noqa: E402

assert str(ROOT / "custom_components") in list(
    custom_components.__path__
), f"tests_ha would test {list(custom_components.__path__)}, not this repository"

DOMAIN = "crop_steering"


@pytest.fixture(autouse=True)
def _load_this_repos_integration(hass, enable_custom_integrations):
    """Let Home Assistant discover custom_components/crop_steering.

    The manifest depends on `frontend` and `http` for the sidebar panel. Setting the real ones
    up needs the 50 MB frontend wheel and a bound port, neither of which this tier is about, so
    they are marked as already running and `hass.http` only records the static path. The
    integration's own panel code still runs against the real frontend module.
    """
    from unittest.mock import AsyncMock, MagicMock

    hass.config.components.update({"frontend", "http"})
    hass.http = MagicMock(async_register_static_paths=AsyncMock())


@pytest.fixture(autouse=True)
def _hermetic_controller_state(tmp_path, monkeypatch):
    """The add-on Controller must never touch this machine's real /data/state.json."""
    monkeypatch.setenv("F2_STATE_PATH", str(tmp_path / "state.json"))


def fixture(name: str) -> dict:
    """A seeded snapshot of an OLD install, as that version actually wrote it."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def controller_for(hass, monkeypatch):
    """The REAL add-on controller, looking at this REAL Home Assistant.

    The two layers only ever meet through entity states over REST, and until now no test
    crossed that seam: each side was tested against its own idea of the other. States are
    JSON round-tripped so the controller sees what the REST API would actually send (string
    dict keys, no Python objects).
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
            fake.set_state(
                state.entity_id,
                state.state,
                json.loads(json.dumps(dict(state.attributes), default=str)),
            )
        if (
            saved_state is not None
        ):  # what the PREVIOUS controller version left in /data
            Path(__import__("os").environ["F2_STATE_PATH"]).write_text(
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


TENT_SWITCH = "switch.gt1_irrigation_switch"


def seed_tent(hass, *, switch="off", ec_unit="µS/cm", ec="2300"):
    """The hardware a single-zone tent really has: one switch, one moisture/EC probe."""
    hass.states.async_set(TENT_SWITCH, switch)
    hass.states.async_set("sensor.gt1_vwc", "48", {"unit_of_measurement": "%"})
    hass.states.async_set(
        "sensor.gt1_ec", ec, {"unit_of_measurement": ec_unit} if ec_unit else {}
    )
