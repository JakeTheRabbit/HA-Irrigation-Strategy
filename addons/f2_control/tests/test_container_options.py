"""The controller built from what a standalone container gives it: options from F2_OPT_* and its own
options.json (runtime_env.load_options), and the version line when it and the integration differ.

A secret given to a container (from its variable or a file) reaches only what uses it: never the log,
a state file, Home Assistant's states, a service call or the heartbeat. A hold from a container's own
options.json holds a shot as the app's does.
"""
import functools
import json
from datetime import datetime

import pytest

import controller
import fake_ha
import brain_bridge
import jev_kit as K
from brain.client import Asker
from test_controller import _desc

KILL = "input_boolean.kill"
NOW = datetime(2026, 9, 27, 13, 0)
SENTINEL = "key-SENTINEL-never-shown"
REAL_LOAD = controller.load_options  # before any other test module's fake_ha.install replaces it


def _fake():
    fake = fake_ha.FakeHA()
    fake.set_state("sensor.crop_steering_engine_config", "ok", _desc(enable_flag=KILL))
    for entity in (KILL, "switch.crop_steering_room_active", "switch.crop_steering_zone_1_enabled"):
        fake.set_state(entity, "on")
    for entity in ("switch.p", "switch.m", "switch.v1"):
        fake.set_state(entity, "off")
    fake.set_state("sensor.crop_steering_vwc_zone_1", "40.5", {"unit_of_measurement": "%"})
    fake.set_state("sensor.crop_steering_ec_zone_1", "6.5", {"unit_of_measurement": "mS/cm"})
    return fake


@pytest.fixture
def container(monkeypatch, tmp_path):
    """A container's environment, its data folder in tmp_path; the controller's real load_options."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("F2_RUNTIME", "container")
    monkeypatch.setenv("HA_URL", "http://ha:8123")
    monkeypatch.setenv("F2_DATA_DIR", str(data))
    monkeypatch.setenv("F2_STATE_PATH", str(data / "state.json"))
    monkeypatch.setattr(controller, "_GATE", controller._AuthGate())

    def build(fake):
        fake_ha.install(controller, fake, {})
        monkeypatch.setattr(controller, "load_options", REAL_LOAD)
        return controller.Controller()

    return data, build


@pytest.mark.parametrize("source", ["variable", "file"])
def test_a_containers_secret_reaches_no_log_file_or_home_assistant(container, monkeypatch, tmp_path, capsys, source):
    """U7, end to end: anthropic_api_key from F2_OPT_ANTHROPIC_API_KEY or its _FILE, with the AI assistant on (the
    whole options dict reaches brain_bridge.build) and one pass of the loop."""
    data, build = container
    if source == "file":
        secret = tmp_path / "anthropic_api_key"
        secret.write_text(SENTINEL)
        monkeypatch.setenv("F2_OPT_ANTHROPIC_API_KEY_FILE", str(secret))
    else:
        monkeypatch.setenv("F2_OPT_ANTHROPIC_API_KEY", SENTINEL)
    monkeypatch.setenv("F2_OPT_BRAIN_PROVIDER", "claude_haiku")
    monkeypatch.setenv("F2_OPT_ENABLE_FLAG", KILL)
    transport = K.FakeTransport({})
    K.sdk(monkeypatch, transport)
    monkeypatch.setattr(brain_bridge, "Asker", functools.partial(Asker, threaded=False, clock=lambda: NOW.timestamp()))
    clock = [0.0]  # a shot's waits on a test clock
    monkeypatch.setattr(controller.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    monkeypatch.setattr(controller.time, "monotonic", lambda: clock[0])
    fake = _fake()
    c = build(fake)
    assert c._options["anthropic_api_key"] == SENTINEL and c.jev is not None  # it reached what uses it
    c.loop_once(NOW)
    c._save_state()
    out = capsys.readouterr().out
    assert "anthropic_api_key=<set>" in out
    assert SENTINEL not in out
    assert SENTINEL not in json.dumps([fake.calls, fake.sets, fake.states], default=str)
    files = {p.name: p.read_text(encoding="utf-8", errors="replace") for p in data.iterdir() if p.is_file()}
    assert "state.json" in files and "jev_usage.json" in files
    for name in ("dosing_state.json", "jev_journal.jsonl", "jev_setpoints.json", "jev_usage.json"):
        assert SENTINEL not in files.get(name, ""), name
    assert not [name for name, text in files.items() if SENTINEL in text]


def test_a_hold_from_a_containers_own_options_file_holds_a_shot(container):
    """U15 (m): {"hold_entities": [...]} from the file, the hold on: no shot, and the reason names it."""
    data, build = container
    (data / "options.json").write_text(json.dumps({"enable_flag": KILL, "hold_entities": ["input_boolean.flush"]}))
    fake = _fake()
    fake.set_state("input_boolean.flush", "on")
    c = build(fake)
    assert c.hold_entities == ["input_boolean.flush"]
    assert c._blocked(c.rooms[0], 1) == "external hold (flush)"


@pytest.mark.parametrize("theirs, said", [
    ("0.0.1", f"version: controller {controller.CONTROLLER_VERSION}, integration 0.0.1; set CONTROLLER_VERSION to 0.0.1"),
    (controller.CONTROLLER_VERSION, None),
])
def test_a_different_integration_version_is_logged_once_per_discovery(container, capsys, theirs, said):
    """U13: at the start and at each re-discovery, a log line with the fix; nothing holds for it."""
    _data, build = container
    fake = _fake()
    fake.set_state("sensor.crop_steering_engine_config", "ok", _desc(enable_flag=KILL, integration_version=theirs))
    c = build(fake)
    c._rediscover(NOW)
    out = capsys.readouterr().out
    if said is None:
        assert "version: controller" not in out
    else:
        assert out.count(said) == 2


def test_the_app_is_told_to_update_instead(monkeypatch, capsys):
    monkeypatch.setattr(controller, "_GATE", controller._AuthGate())  # the app (conftest)
    fake = _fake()
    fake.set_state("sensor.crop_steering_engine_config", "ok", _desc(enable_flag=KILL, integration_version="0.0.1"))
    fake_ha.install(controller, fake, {"enable_flag": KILL})
    controller.Controller()
    assert "integration 0.0.1; update the app, or the integration" in capsys.readouterr().out
