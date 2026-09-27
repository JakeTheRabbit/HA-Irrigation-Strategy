"""A room whose Crop Steering integration is not running is not watered, whatever its kill switch says.

#120 stopped System Enabled and Auto Irrigation Enabled holding a room. Unreadable, they had also held
a room whose integration was not running (not loaded after an update, its entry disabled, Home
Assistant in safe mode), and nothing else did: a room armed by Home Assistant's own helper (the default
room's input_boolean) stayed armed with every Crop Steering entity gone, its dead probes put it on the
timer, and the pump, main line and valve opened for a zone paused and overridden before the outage.
Now a zone whose switch can't be read is held, as an unreadable kill switch holds a room.
"""

from datetime import datetime

import pytest

import controller
from test_controller import _build, _desc

KILL = "input_boolean.kill"
ZONE = "switch.crop_steering_zone_1_enabled"
OVERRIDE = "switch.crop_steering_zone_1_manual_override"


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


def _room():
    """Armed by an input_boolean, zone 1 paused and overridden, as a grower leaves a zone they are
    working on."""
    states = {
        "sensor.crop_steering_engine_config": ("ok", _desc(enable_flag=KILL)),
        KILL: ("on", {}),
        "switch.crop_steering_room_active": ("on", {}),
        "switch.crop_steering_system_enabled": ("on", {}),
        "switch.crop_steering_auto_irrigation_enabled": ("on", {}),
        ZONE: ("off", {}),
        OVERRIDE: ("on", {}),
    }
    c, fake = _build({"num_zones": 1, "enable_flag": KILL}, states=states)
    room = c.rooms[0]
    assert c._blocked(room, 1) == "zone disabled"
    return c, fake, room


@pytest.mark.usefixtures("no_blind_grace")
@pytest.mark.parametrize("how", ["missing", "unavailable"])
def test_nothing_opens_while_the_integration_is_not_running(how):
    c, fake, room = _room()
    room.state[1].update(phase="P2", last_daily_reset=_Clock.now().date(), last_shot=None)
    for entity in [e for e in fake.states if "crop_steering" in e]:
        if how == "missing":
            fake.states.pop(entity)
        else:
            fake.set_state(entity, "unavailable")
    fake.calls.clear()
    c.loop_once(_Clock.now())
    assert c._blocked(room, 1) == f"{ZONE} unreadable (reads neither on nor off)"
    opened = [d["entity_id"] for dom, svc, d in fake.calls if (dom, svc) == ("switch", "turn_on")]
    assert opened == []


def test_a_zone_switch_that_reads_again_frees_the_zone():
    c, fake, room = _room()
    fake.set_state(ZONE, "unavailable")
    assert c._blocked(room, 1) == f"{ZONE} unreadable (reads neither on nor off)"
    fake.set_state(ZONE, "on")
    fake.set_state(OVERRIDE, "off")
    assert c._blocked(room, 1) is None
