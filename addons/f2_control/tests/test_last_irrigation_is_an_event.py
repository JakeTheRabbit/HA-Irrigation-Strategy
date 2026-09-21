""""Last irrigation" is a record of water being delivered. It is never anything else.

Found on the first real tent install: the dashboard and Home Assistant both showed
"Last Irrigation 18:19:37" on a zone with 0 shots and 0.0 L. 18:19:37 was the moment the room was
switched ON. The controller stamps `last_shot` then so that its timers count from switch-on rather
than from "never", and it published that stamp as an irrigation. On a room with one switch and
nothing upstream of it, a false "it just watered" is not a cosmetic problem.
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
LAST = "sensor.crop_steering_zone_1_last_irrigation_app"
NOW = datetime(2026, 9, 21, 18, 45, 0)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    now = {"seconds": 0.0}
    monkeypatch.setattr(controller.time, "monotonic", lambda: now["seconds"])
    monkeypatch.setattr(controller.time, "sleep", lambda dt: now.__setitem__("seconds", now["seconds"] + dt))


def _states(room_active="on"):
    return {
        "sensor.crop_steering_engine_config": ("default", _desc(pump=None, mainline=None, valves={"1": "switch.v1"},
                                                                 enable_flag=KILL, active_zone_ids=[1])),
        "sensor.crop_steering_vwc_zone_1": ("100.0", {"unit_of_measurement": "%"}),
        "sensor.crop_steering_ec_zone_1": ("6.57", {"unit_of_measurement": "mS/cm"}),
        "switch.crop_steering_room_active": (room_active, {}),
        "switch.v1": ("off", {}),
        KILL: ("off", {}),
    }


def _published(fake):
    return fake.sets.get(LAST, (None, {}))[0]


# =========================================================================== FRESH INSTALL
def test_switching_the_room_on_is_not_an_irrigation():
    c, fake = _build({"num_zones": 1, "enable_flag": KILL}, states=_states())
    room = c.rooms[0]
    c._room_switched_on(room)
    st = room.state[1]
    assert st["last_shot"] is not None and st["last_shot_is_anchor"] is True
    assert c._minutes_since_shot(st, datetime.now()) < 1  # the timers still count from switch-on
    c.loop_once(NOW)
    assert _published(fake) == "unknown"  # it said 18:19:37, with 0 shots and 0.0 L
    assert st["shots"] == 0 and st["daily_vol"] == 0


def test_a_real_shot_is_an_irrigation_and_is_published_with_its_time():
    c, fake = _build({"num_zones": 1, "enable_flag": KILL}, states=_states())
    room = c.rooms[0]
    c._room_switched_on(room)
    c._execute_shot(room, 1, 6, 2.0)
    st = room.state[1]
    assert st["shots"] == 1 and st["last_shot_is_anchor"] is False
    c.loop_once(NOW)
    assert _published(fake) not in (None, "unknown")
    assert datetime.fromisoformat(_published(fake)).tzinfo is not None  # still an offset-aware time


def test_a_zone_that_has_done_nothing_publishes_nothing_as_before():
    c, fake = _build({"num_zones": 1, "enable_flag": KILL}, states=_states())
    c.loop_once(NOW)
    assert LAST not in fake.sets


def test_a_room_switched_on_and_off_again_has_the_false_time_taken_back():
    """The state the box was found in: status "Room off", and the false time still on screen. An
    off room publishes almost nothing, so the correction has to be made there too."""
    c, fake = _build({"num_zones": 1, "enable_flag": KILL}, states=_states())
    room = c.rooms[0]
    c._room_switched_on(room)
    fake.set_state("switch.crop_steering_room_active", "off")
    c.loop_once(NOW)
    assert fake.sets["sensor.crop_steering_zone_1_status"][0] == "Room off"
    assert _published(fake) == "unknown"


# =========================================================================== UPGRADE IN PLACE
def _restart_on(zone_state, states):
    path = os.path.join(tempfile.mkdtemp(prefix="f2last_"), "state.json")
    with open(path, "w") as fh:
        json.dump({"default": {"1": zone_state}}, fh)
    os.environ["F2_STATE_PATH"] = path  # restored by the suite's autouse fixture
    fake = fake_ha.FakeHA()
    for eid, (value, attrs) in states.items():
        fake.set_state(eid, value, attrs)
    fake_ha.install(controller, fake, {"num_zones": 1, "enable_flag": KILL})
    return controller.Controller(), fake


def test_an_unmarked_legacy_time_is_not_reclassified_from_zero_water_counters():
    """Old state cannot distinguish switch-on from irrigation after counters/history roll over.
    Keep its timestamp unless the saved state explicitly records that it is an anchor."""
    old = {"phase": "P3", "shots": 0, "daily_vol": 0.0, "last_shot": "2026-09-21T18:19:37.355321",
           "water_history": [{"grow_day": "2026-09-21", "litres": 0.0}]}
    c, fake = _restart_on(old, _states())
    assert c.rooms[0].state[1]["last_shot_is_anchor"] is False
    c.loop_once(NOW)
    assert datetime.fromisoformat(_published(fake)).replace(tzinfo=None) == datetime.fromisoformat(old["last_shot"])


@pytest.mark.parametrize("history", [None, [{"grow_day": "2026-09-21", "litres": 0.0}]])
def test_a_real_old_event_survives_daily_reset_and_missing_or_expired_history(history):
    old = {"phase": "P0", "shots": 0, "daily_vol": 0.0, "last_daily_reset": "2026-09-21",
           "last_shot": "2026-09-12T21:40:00"}
    if history is not None:
        old["water_history"] = history
    c, fake = _restart_on(old, _states())
    assert c.rooms[0].state[1]["last_shot_is_anchor"] is False
    c.loop_once(NOW)
    assert datetime.fromisoformat(_published(fake)).replace(tzinfo=None) == datetime(2026, 9, 12, 21, 40)


@pytest.mark.parametrize("room_active", ["on", "off"])
def test_an_explicit_saved_anchor_stays_unknown_after_restart(room_active):
    old = {"phase": "P3", "shots": 0, "daily_vol": 0.0, "last_shot": "2026-09-21T18:19:37",
           "last_shot_is_anchor": True,
           "water_history": [{"grow_day": "2026-09-20", "litres": 3.5}]}
    c, fake = _restart_on(old, _states(room_active))
    assert c.rooms[0].state[1]["last_shot_is_anchor"] is True
    c.loop_once(NOW)
    assert _published(fake) == "unknown"


@pytest.mark.parametrize("excluded, expected", [("2.5", 2.5), ("bad", 0.0), ({"invalid": 1}, 0.0)])
def test_legacy_excluded_volume_is_normalized_before_it_can_break_startup(excluded, expected):
    old = {"phase": "P2", "shots": 0, "daily_vol": 0.0, "last_shot": "2026-09-20T21:40:00",
           "water_history_legacy_excluded_l": excluded}
    c, _fake = _restart_on(old, _states())
    assert c.rooms[0].state[1]["water_history_legacy_excluded_l"] == expected
    assert c.rooms[0].state[1]["last_shot_is_anchor"] is False


def test_an_install_with_a_real_irrigation_history_keeps_showing_its_last_irrigation():
    """A production room updating in place: nothing the operator sees may move."""
    old = {"phase": "P2", "shots": 0, "daily_vol": 0.0, "last_shot": "2026-09-20T21:40:00",
           "water_history": [{"grow_day": "2026-09-20", "litres": 3.5}, {"grow_day": "2026-09-21", "litres": 0.0}]}
    c, fake = _restart_on(old, _states())
    st = c.rooms[0].state[1]
    assert st["last_shot_is_anchor"] is False and st["last_shot"] == datetime(2026, 9, 20, 21, 40)
    c.loop_once(NOW)
    assert datetime.fromisoformat(_published(fake)).replace(tzinfo=None) == datetime(2026, 9, 20, 21, 40)


@pytest.mark.parametrize("evidence", [{"shots": 3}, {"daily_vol": 1.2}, {"water_history_legacy_excluded_l": 4.0}])
def test_any_recorded_water_means_the_old_time_is_a_real_irrigation(evidence):
    old = {"phase": "P2", "shots": 0, "daily_vol": 0.0, "last_shot": "2026-09-20T21:40:00", **evidence}
    c, _fake = _restart_on(old, _states())
    assert c.rooms[0].state[1]["last_shot_is_anchor"] is False
