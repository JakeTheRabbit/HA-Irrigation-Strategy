"""The suite must be hermetic: no test may read or write the machine's real /data.

Found on a dev box that happens to have a writable /data: the constructor adopted the test
setup and saved it to /data/state.json, the next test loaded it, and six resume tests failed
with state they never wrote. GitHub runners have no /data, so CI stayed green and hid it.
"""
import json
import os

import controller
import fake_ha
from test_controller import _desc

KILL = "input_boolean.kill"


def _construct(states):
    fake = fake_ha.FakeHA()
    for entity, (state, attrs) in states.items():
        fake.set_state(entity, state, attrs)
    fake_ha.install(controller, fake, {"num_zones": 1, "enable_flag": KILL})
    return controller.Controller()


def test_the_constructor_reads_and_writes_the_redirected_state_file_only():
    redirected = os.environ["F2_STATE_PATH"]
    assert not redirected.startswith("/data")
    # Kill switch OFF + hardware OFF + a revisioned descriptor = the constructor ADOPTS the
    # setup and saves it, which is exactly the write that used to land in /data.
    c = _construct({
        "sensor.crop_steering_engine_config": (
            "ok", _desc(enable_flag=KILL, setup_revision=4, active=True, active_zone_ids=[1])),
        KILL: ("off", {}),
        "switch.p": ("off", {}), "switch.m": ("off", {}), "switch.v1": ("off", {}),
    })
    assert c._state_path == redirected
    assert c.rooms[0].setup_revision == 4
    with open(redirected) as handle:
        assert json.load(handle)["default"]["_setup"]["revision"] == 4


def test_a_live_install_still_defaults_to_the_ha_managed_data_path(monkeypatch):
    """The override is a test/dev seam only: unset, the path is unchanged for every install."""
    monkeypatch.delenv("F2_STATE_PATH")
    # Neutralise every read/write so asserting the default cannot itself touch /data.
    monkeypatch.setattr(controller.Controller, "_load_state", lambda self: None)
    monkeypatch.setattr(controller.Controller, "_apply_setup_descriptors", lambda self: None)
    assert _construct({})._state_path == "/data/state.json"
