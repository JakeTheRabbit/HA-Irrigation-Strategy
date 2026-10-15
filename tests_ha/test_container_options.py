"""A standalone container's options, given only through the environment (F2_OPT_<OPTION>), build the same
room in a real Home Assistant as the same options handed over as the app's options.json would.

The controller reads them with its own load_options (runtime_env), in container mode, with no options
file at all: the zero-setup way a compose file sets them.
"""

import controller
from test_setup_entry import _install

KILL = "switch.crop_steering_engine_enabled"
OPTIONS = {"enable_flag": KILL, "hold_entities": ["input_boolean.flush", "input_boolean.fill"],
           "notify_min": 15.0, "loop_seconds": 30.0, "lights_on_hour": 6.0, "substrate_l": 7.5}
ENV = {"F2_OPT_ENABLE_FLAG": KILL, "F2_OPT_HOLD_ENTITIES": "input_boolean.flush,input_boolean.fill",
       "F2_OPT_NOTIFY_MIN": "15", "F2_OPT_LOOP_SECONDS": "30", "F2_OPT_LIGHTS_ON_HOUR": "6",
       "F2_OPT_SUBSTRATE_L": "7.5"}
REAL_LOAD = controller.load_options  # the controller's own, before any test stands in for it


def _room(c):
    room = c.rooms[0]
    return (room.slug, room.prefix, dict(room.hw), sorted(room.zones), room.enable_flag, c.hold_entities,
            c.notify_min, c.loop_seconds, c._opt_lon, c.substrate_l)


async def test_options_from_the_environment_alone_build_the_same_room(hass, controller_for, monkeypatch, tmp_path):
    await _install(hass, {"lights_on_hour": 6, "lights_off_hour": 22})
    from_dict, _fake, _clock = controller_for(OPTIONS)

    monkeypatch.setenv("F2_RUNTIME", "container")
    monkeypatch.setenv("HA_URL", "http://ha:8123")
    monkeypatch.setenv("F2_OPTIONS_PATH", str(tmp_path / "no-options.json"))  # no file: zero-setup
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(controller, "load_options", REAL_LOAD)
    from_env = controller.Controller()  # the same Home Assistant behind the same fake

    assert from_env._options == OPTIONS
    assert {k: type(v) for k, v in from_env._options.items()} == {k: type(v) for k, v in OPTIONS.items()}
    assert _room(from_env) == _room(from_dict)
