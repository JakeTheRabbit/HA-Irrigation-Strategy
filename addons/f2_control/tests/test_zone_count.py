"""The default room has exactly the zones the integration says it has. Never an invented number.

Found on the first real tent install: one zone set up, and the dashboard's activity filled with
"Z2 ... no hardware mapped" and "Z3 ... no hardware mapped". The app had been started before the
integration was set up; with no room to read, it fell back to the `num_zones` option, whose
default is 3 (the facility this was first written for), and kept those zones.

Both directions are covered, because both are real: a FRESH install in either start order, and an
UPGRADE on top of an existing install's saved state, including a state file that already contains
the phantom zones this bug created.
"""
import json
import os
import tempfile
from datetime import datetime

import pytest

import controller
import fake_ha
from test_controller import _build, _desc

KILL = "switch.crop_steering_engine_enabled"
DESCRIPTOR = "sensor.crop_steering_engine_config"
NOW = datetime(2026, 9, 21, 14, 0, 0)
MAX_ZONES = 24  # custom_components/crop_steering/const.py; pinned against it at the bottom


def _room(n, *, fused=True, active=None, revision=1):
    """Home Assistant as the integration leaves it for an n-zone default room."""
    valves = {str(z): f"switch.valve_{z}" for z in range(1, n + 1)}
    states = {
        DESCRIPTOR: ("default", _desc(pump=None, mainline=None, valves=valves, num=n, enable_flag=KILL,
                                      setup_revision=revision, active=True,
                                      active_zone_ids=active or list(range(1, n + 1)))),
        KILL: ("off", {}),
        "sun.sun": ("above_horizon", {}),
    }
    states.update({valve: ("off", {}) for valve in valves.values()})
    if fused:
        for z in range(1, n + 1):
            states[f"sensor.crop_steering_vwc_zone_{z}"] = ("45", {"unit_of_measurement": "%"})
            states[f"sensor.crop_steering_ec_zone_{z}"] = ("3.1", {"unit_of_measurement": "mS/cm"})
    return states


def _zone_lines(fake):
    """Every zone number the controller has published anything about."""
    found = set()
    for entity_id in fake.sets:
        if "_zone_" in entity_id:
            found.add(int(entity_id.split("_zone_")[1].split("_")[0]))
    return found


def _restart_on(state, states, options=None):
    """A controller process starting on top of an existing /data/state.json."""
    path = os.path.join(tempfile.mkdtemp(prefix="f2zones_"), "state.json")
    with open(path, "w") as fh:
        json.dump(state, fh)
    os.environ["F2_STATE_PATH"] = path  # restored by the suite's autouse fixture
    fake = fake_ha.FakeHA()
    for eid, (value, attrs) in states.items():
        fake.set_state(eid, value, attrs)
    fake_ha.install(controller, fake, options or {"num_zones": 3, "enable_flag": "input_boolean.f2_control_enabled"})
    return controller.Controller(), fake


SHIPPED_OPTIONS = {"num_zones": 3, "enable_flag": "input_boolean.f2_control_enabled"}  # config.yaml defaults


# =========================================================================== FRESH INSTALL
def test_app_started_before_the_integration_invents_no_zones():
    c, fake = _build(dict(SHIPPED_OPTIONS), states={"sun.sun": ("above_horizon", {})})
    room = c.rooms[0]
    assert room.zones == {} and c._default_provisional
    c.loop_once(NOW)  # and a room with no zones is a quiet room, not a crash
    assert _zone_lines(fake) == set()
    assert not [e for e in fake.sets if "zone_2" in e or "zone_3" in e]


@pytest.mark.parametrize("n", range(1, MAX_ZONES + 1))
def test_then_setting_up_an_n_zone_room_gives_exactly_n_zones_within_one_loop(n):
    c, fake = _build(dict(SHIPPED_OPTIONS), states={"sun.sun": ("above_horizon", {})})
    for entity_id, (value, attrs) in _room(n).items():
        fake.set_state(entity_id, value, attrs)  # the operator finishes the wizard
    c.loop_once(NOW)  # the very next loop, not rediscover_seconds (300 s) later
    room = c.rooms[0]
    assert sorted(room.zones) == list(range(1, n + 1))
    assert room.hw["valves"] == {z: f"switch.valve_{z}" for z in range(1, n + 1)}
    assert room.enable_flag == KILL  # the room's real kill switch, not the option's legacy default
    assert not c._default_provisional  # settled: back to the ordinary rediscover interval
    assert _zone_lines(fake) <= set(range(1, n + 1))  # nothing about a zone that does not exist
    assert "no hardware mapped" not in json.dumps({k: v[1] for k, v in fake.sets.items()})


@pytest.mark.parametrize("n", [1, 2, 3, 7, 20, MAX_ZONES])
@pytest.mark.parametrize("fused", [True, False], ids=["sensors-exist", "sensors-not-created-yet"])
def test_integration_set_up_first_gives_exactly_n_zones_at_once(n, fused):
    c, _fake = _build(dict(SHIPPED_OPTIONS), states=_room(n, fused=fused))
    assert sorted(c.rooms[0].zones) == list(range(1, n + 1))
    assert not c._default_provisional


def test_an_archived_zone_is_not_driven_even_before_its_sensors_exist():
    c, _fake = _build(dict(SHIPPED_OPTIONS), states=_room(3, fused=False, active=[1, 3]))
    assert sorted(c.rooms[0].zones) == [1, 3]


def test_home_assistant_unreachable_at_start_uses_the_documented_fallback_then_corrects_itself(monkeypatch):
    """The `num_zones` option still means what its description says: "only used if Home Assistant
    isn't reachable at startup". What is new is that it is a stand-in: the moment Home Assistant
    answers, the room's real zones replace it."""
    states = _room(1)
    fake = fake_ha.FakeHA()
    fake_ha.install(controller, fake, dict(SHIPPED_OPTIONS))  # nothing answers yet
    c = controller.Controller()
    assert sorted(c.rooms[0].zones) == [1, 2, 3] and c._default_provisional
    for entity_id, (value, attrs) in states.items():
        fake.set_state(entity_id, value, attrs)  # Home Assistant finishes booting
    c.loop_once(NOW)
    assert sorted(c.rooms[0].zones) == [1] and not c._default_provisional


# =========================================================================== UPGRADE IN PLACE
def _saved(zones):
    return {"default": {str(z): {"phase": "P2", "peak": 61.0, "shots": 4 + z, "daily_vol": 2.5} for z in zones}}


def test_a_working_three_zone_install_is_untouched_by_the_update():
    """A pumped three-zone room, mid grow-day, both halves updated. Same zones, same counters, and
    not provisional, so nothing re-resolves it."""
    c, _fake = _restart_on(_saved([1, 2, 3]), _room(3, revision=0))
    room = c.rooms[0]
    assert sorted(room.zones) == [1, 2, 3] and not c._default_provisional
    assert [room.state[z]["shots"] for z in (1, 2, 3)] == [5, 6, 7]
    assert room.state[2]["daily_vol"] == 2.5


def test_a_box_that_already_saved_the_phantom_zones_stops_showing_them():
    """The box this was found on: its state file holds zones 1, 2 and 3, and the room has one.
    After the update the real zone keeps its counters and the phantoms are neither driven nor
    published. (Their saved entries are left in the file: this controller never deletes counters.)"""
    c, fake = _restart_on(_saved([1, 2, 3]), _room(1))
    room = c.rooms[0]
    assert sorted(room.zones) == [1]
    assert room.state[1]["shots"] == 5
    c.loop_once(NOW)
    assert _zone_lines(fake) <= {1}
    c._save_state()
    with open(c._state_path) as fh:
        assert {"1", "2", "3"} <= set(json.load(fh)["default"])  # nothing was thrown away


def test_a_hand_mapped_install_keeps_the_zone_count_in_its_app_options():
    """`hardware` and `num_zones` typed into the app options, no integration room: honoured as before."""
    options = {**SHIPPED_OPTIONS, "num_zones": 2,
               "hardware": {"pump": "switch.p", "mainline": "switch.m", "valves": {"1": "switch.v1", "2": "switch.v2"}}}
    c, _fake = _build(options, states={"sun.sun": ("above_horizon", {})})
    assert sorted(c.rooms[0].zones) == [1, 2] and not c._default_provisional


def test_the_limit_used_here_is_the_integrations():
    import pathlib
    import re
    const = (pathlib.Path(__file__).parents[3] / "custom_components/crop_steering/const.py").read_text()
    assert int(re.search(r"^MAX_ZONES\s*=\s*(\d+)", const, re.M).group(1)) == MAX_ZONES
