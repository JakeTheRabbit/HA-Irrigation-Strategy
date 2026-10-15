"""Make the vendored engine + controller importable for the add-on test suite.

The add-on ships `crop_steering_engine` vendored inside `f2_control/`, and the
controller imports it as a top-level package. Put that directory on sys.path so
`import controller` and `import crop_steering_engine` both resolve without a build.
"""
import os
import sys

import pytest

_HERE = os.path.dirname(__file__)
_PKG = os.path.abspath(os.path.join(_HERE, "..", "f2_control"))
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)


@pytest.fixture(autouse=True)
def _hermetic_state_file(tmp_path, monkeypatch):
    """Never let a test read or write the machine's real /data/state.json.

    The controller's constructor loads state and may save an adopted setup BEFORE a test
    can repoint `_state_path`. GitHub runners have no /data so that was invisible in CI, but
    on any box where /data exists and is writable (a devcontainer, the add-on container
    itself, a dev machine) the suite wrote a real file there and leaked it into the next
    test. Redirect the path up front, per test.
    """
    monkeypatch.setenv("F2_STATE_PATH", str(tmp_path / "constructor-state.json"))


@pytest.fixture
def no_blind_grace(monkeypatch):
    """For tests of what happens once a probe is dead: it counts as dead at once. How long a probe
    must be out first (controller.BLIND_GRACE_MIN) is tested in test_blind_grace.py."""
    import controller

    monkeypatch.setattr(controller, "BLIND_GRACE_MIN", 0)


@pytest.fixture
def settings_built_in(monkeypatch):
    """For tests whose fake Home Assistant leaves a room's settings out: they run on built-in values at once,
    as they did before the settings wait. The wait, and the zone held on a never-read water-sizing setting
    (controller.SETTINGS_WAIT_PASSES, controller.WATER_SIZING), are tested in test_settings_wait.py."""
    import controller

    monkeypatch.setattr(controller, "SETTINGS_WAIT_PASSES", 0)
    monkeypatch.setattr(controller, "WATER_SIZING", ())


@pytest.fixture(autouse=True)
def _no_real_history(monkeypatch):
    """Never let a test ask a real Home Assistant for history: none is recorded unless a rig says so."""
    import controller

    monkeypatch.setattr(controller, "ha_history", lambda entity, since, timeout=12: None)
