"""The controller says which version it is, so the dashboard can show what is actually running.

It reads the number from the config.yaml it was built from (the Dockerfile copies that file next
to the module), so there is nothing to bump anywhere else, and these tests are the "don't forget"
that a second copy would have needed: they fail if the report and config.yaml ever disagree, or
if the Dockerfile stops shipping the file (the image would then report "unknown", silently).
"""
import json
import pathlib
import re

import controller
from test_controller import _build, _desc

ADDON = pathlib.Path(__file__).parents[1]
KILL = "input_boolean.kill"


def _config_version():
    return re.search(r'^version:\s*"?([^"\s]+)', (ADDON / "config.yaml").read_text(), re.M).group(1)


def test_the_controller_reports_the_version_in_config_yaml():
    assert controller.CONTROLLER_VERSION == _config_version()
    assert re.fullmatch(r"\d+\.\d+\.\d+", controller.CONTROLLER_VERSION)


def test_in_the_image_it_is_read_from_the_copy_the_dockerfile_ships(tmp_path):
    (tmp_path / "addon.yaml").write_text('name: x\nversion: "9.8.7"  # from the build\nslug: f2_control\n')
    assert controller.read_controller_version(str(tmp_path)) == "9.8.7"
    dockerfile = (ADDON / "Dockerfile").read_text()
    assert "COPY config.yaml /app/addon.yaml" in dockerfile
    assert dockerfile.index("COPY f2_control /app") < dockerfile.index("COPY config.yaml /app/addon.yaml")
    assert "config.yaml" not in (ADDON / ".dockerignore").read_text()  # or the COPY has nothing to copy


def test_an_unreadable_version_is_reported_as_unknown_not_guessed(tmp_path):
    assert controller.read_controller_version(str(tmp_path / "nowhere" / "deeper")) == "unknown"
    (tmp_path / "addon.yaml").write_text("name: no version line here\n")
    nested = tmp_path / "pkg"
    nested.mkdir()
    assert controller.read_controller_version(str(nested)) == "unknown"


def test_every_heartbeat_carries_it():
    c, fake = _build(
        {"num_zones": 1, "enable_flag": KILL},
        states={"sensor.crop_steering_engine_config": ("ok", _desc(enable_flag=KILL)), KILL: ("off", {})},
    )
    c._heartbeat(c.rooms[0], controller.datetime.now(), None)
    attrs = fake.sets["sensor.crop_steering_ai_heartbeat"][1]  # what the controller published
    assert attrs["controller_version"] == _config_version()
    assert attrs["engine"] == "f2-control"  # and nothing that was there has gone


def test_the_integrations_version_in_the_descriptor_does_not_touch_the_setup_fingerprint():
    """The integration now publishes `integration_version` in the descriptor. If that leaked into
    the fingerprint, every room would come back from every integration update blocked behind a
    disarm cycle (the 2026-09-20 outage, on a schedule)."""
    room = type("R", (), {"enable_flag": KILL})()
    attrs = _desc(enable_flag=KILL, setup_revision=4, active=True, active_zone_ids=[1])
    before = controller.Controller._setup_fingerprint(attrs, room)
    after = controller.Controller._setup_fingerprint({**attrs, "integration_version": "2.19.1"}, room)
    later = controller.Controller._setup_fingerprint({**attrs, "integration_version": "3.0.0"}, room)
    assert before == after == later
    assert "integration_version" not in json.loads(after)
