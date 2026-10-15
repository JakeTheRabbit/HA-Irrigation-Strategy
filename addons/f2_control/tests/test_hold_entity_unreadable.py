"""A hold entity that can't be read holds, as one that reads ON does.

A hold (the `hold_entities` option) is how a dosing, tank-fill or flush automation tells the controller
to keep water off while it works. It used to be read with an unreadable state taken as OFF, so a hold
whose device or helper went offline (unavailable), had no state yet (unknown) or no longer existed let
every shot through, while whatever it guarded might still be running. Now it holds new shots, names the
entity, and frees them once it reads again. A shot already running still ends only on a definite ON.
"""

from datetime import datetime

import pytest

import controller
from test_controller import _build, _desc

pytestmark = pytest.mark.usefixtures("settings_built_in")

KILL = "input_boolean.kill"
HOLD = "input_boolean.tank_dosing"
UNREADABLE = f"external hold {HOLD} unreadable (reads neither on nor off)"


class _Clock(datetime):
    current = datetime(2026, 9, 25, 14, 0)

    @classmethod
    def now(cls, tz=None):
        return cls.current if tz is None else cls.current.astimezone(tz)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    _Clock.current = _Clock(2026, 9, 25, 14, 0)
    monkeypatch.setattr(controller, "datetime", _Clock)
    seconds = {"now": 0.0}
    monkeypatch.setattr(controller.time, "monotonic", lambda: seconds["now"])
    monkeypatch.setattr(
        controller.time, "sleep", lambda dt: seconds.__setitem__("now", seconds["now"] + dt)
    )


def _room(holds=(HOLD,)):
    states = {
        "sensor.crop_steering_engine_config": ("ok", _desc(enable_flag=KILL)),
        KILL: ("on", {}),
        "switch.crop_steering_room_active": ("on", {}),
        "switch.crop_steering_system_enabled": ("on", {}),
        "switch.crop_steering_auto_irrigation_enabled": ("on", {}),
        "switch.crop_steering_zone_1_enabled": ("on", {}),
        "switch.crop_steering_zone_1_manual_override": ("off", {}),
        HOLD: ("off", {}),
    }
    c, fake = _build({"num_zones": 1, "enable_flag": KILL, "hold_entities": list(holds)}, states=states)
    room = c.rooms[0]
    assert c._blocked(room, 1) is None
    return c, fake, room


def _unreadable(fake, how):
    if how == "missing":
        fake.states.pop(HOLD)
    else:
        fake.set_state(HOLD, how)


@pytest.mark.parametrize("how", ["unavailable", "unknown", "missing"])
def test_a_hold_that_cannot_be_read_holds_and_names_the_entity(how):
    c, fake, room = _room()
    _unreadable(fake, how)
    assert c._blocked(room, 1) == UNREADABLE


def test_a_hold_that_reads_again_frees_the_zone():
    c, fake, room = _room()
    fake.set_state(HOLD, "unavailable")
    assert c._blocked(room, 1) == UNREADABLE
    fake.set_state(HOLD, "off")
    assert c._blocked(room, 1) is None


def test_a_hold_that_reads_on_still_holds_as_before():
    c, fake, room = _room()
    fake.set_state(HOLD, "on")
    assert c._blocked(room, 1) == "external hold (tank_dosing)"


def test_no_hold_set_up_holds_nothing():
    c, fake, room = _room(holds=())
    fake.states.pop(HOLD)
    assert c._blocked(room, 1) is None


@pytest.mark.usefixtures("no_blind_grace")
@pytest.mark.parametrize("how", ["unavailable", "missing"])
def test_nothing_opens_while_a_hold_cannot_be_read(how):
    c, fake, room = _room()
    room.state[1].update(phase="P2", last_daily_reset=_Clock.now().date(), last_shot=None)
    _unreadable(fake, how)
    fake.calls.clear()
    c.loop_once(_Clock.now())
    opened = [d["entity_id"] for dom, svc, d in fake.calls if (dom, svc) == ("switch", "turn_on")]
    assert opened == []
