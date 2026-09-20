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
