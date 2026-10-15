"""A zone with no moisture reading no longer sits in its morning dryback (P0) all day.

The dead-probe path kept the lights' two edges (lights-off -> P3, lights-on -> P0) but none of the day's other
exits, so a zone whose probe was out at lights-on stayed in P0 until lights-off: its phase never said what its
day was doing, and when the probe came back mid-day the engine's own P0 timeout fired at once and started the
morning ramp from its first shot. The dead-probe path now has decide()'s two exits that need no probe: P0 -> P1
once the P0 maximum wait has passed, and P1 -> P2 at the P1 maximum shots.
"""
from datetime import timedelta

import pytest

import controller
from test_blind_grace import _Clock, _later, clock  # noqa: F401 - the pinned wall clock
from test_room_status import _room

pytestmark = pytest.mark.usefixtures("settings_built_in", "no_blind_grace")

P0_WAIT = "number.crop_steering_p0_maximum_wait_time"
MAX_SHOTS = "number.crop_steering_p1_maximum_shots"


def _blind_room_in_p0(minutes_ago):
    c, fake = _room("on")
    fake.set_state(P0_WAIT, "60")
    fake.set_state(MAX_SHOTS, "4")
    st = c.rooms[0].state[1]
    st.update(phase="P0", last_daily_reset=_Clock.now().date(), shots=0, last_shot=_Clock.now(),
              last_phase_change=_Clock.now() - timedelta(minutes=minutes_ago))  # no timer shot due
    return c, fake, st


def test_a_blind_zone_waits_in_p0_until_its_maximum_wait():
    c, _fake, st = _blind_room_in_p0(30)
    c.loop_once(_Clock.now())
    assert st["phase"] == "P0"


def test_a_blind_zone_starts_its_ramp_after_the_p0_maximum_wait():
    c, fake, st = _blind_room_in_p0(61)
    st["shots"] = 3  # yesterday's count must not end today's ramp at once
    c.loop_once(_Clock.now())
    assert st["phase"] == "P1" and st["shots"] == 0
    assert st["last_phase_change"] == _Clock.now()
    assert st["p1_reached"] is False
    assert ("phase", 1, "P0", "P1") in [(e[0], e[1], e[2], e[3]) for e in _phase_events(c)]


def test_a_blind_zone_hands_over_to_maintenance_at_the_p1_maximum_shots():
    c, _fake, st = _blind_room_in_p0(61)
    c.loop_once(_Clock.now())
    assert st["phase"] == "P1"
    st["shots"] = 4
    _later(1)
    c.loop_once(_Clock.now())
    assert st["phase"] == "P2"
    _later(1)
    c.loop_once(_Clock.now())
    assert st["phase"] == "P2"  # no further time exit: lights-off moves it to P3


def test_lights_off_still_takes_a_blind_zone_to_p3_and_lights_on_back_to_p0():
    c, _fake, st = _blind_room_in_p0(61)
    _Clock.current = _Clock.current.replace(hour=23)  # the rig's lights are 10:00-22:00
    c.loop_once(_Clock.now())
    assert st["phase"] == "P3"
    _Clock.current = _Clock.current + timedelta(hours=11, minutes=5)  # 10:05 the next day
    c.loop_once(_Clock.now())
    assert st["phase"] == "P0" and st["last_daily_reset"] == _Clock.now().date()


def _phase_events(c):
    return c.__dict__.get("_phase_seen", [])


@pytest.fixture(autouse=True)
def _record_phase_events(monkeypatch):
    seen = []

    def notify(self, event, room, zone, *detail):
        if event == "phase":
            self.__dict__.setdefault("_phase_seen", []).append((event, zone, *detail))

    monkeypatch.setattr(controller.Controller, "_notify_event", notify)
    return seen
