"""A zone on the dead-probe path changes phase exactly as one the engine decides for (CTL-009).

The time-only phase moves (lights-off -> P3, lights-on -> P0, the P0 maximum wait, the P1 maximum
shots) were coded twice: once after decide() for a zone with a reading, and again for a blind zone.
The blind copy had drifted: it kept yesterday's P1 wet-up curve into the new day (the Vmax advisory
read two days' ramps as one), and only a move into P1 reached the zone's phase history. Both paths
now go through one _change_phase.
"""
from datetime import timedelta

import pytest

import controller
from test_blind_grace import _Clock, clock  # noqa: F401 - the pinned wall clock
from test_room_status import _room

pytestmark = pytest.mark.usefixtures("settings_built_in", "no_blind_grace")


@pytest.fixture
def recorded(monkeypatch):
    """Every phase change that reached the zone's history, as (was, new)."""
    seen = []
    real = controller.Controller._record_phase

    def record(self, room, zone, st, was, new, now, how, snap=None, p=None):
        seen.append((was, new))
        return real(self, room, zone, st, was, new, now, how, snap, p)

    monkeypatch.setattr(controller.Controller, "_record_phase", record)
    return seen


def _blind_room(phase):
    c, _fake = _room("on")
    st = c.rooms[0].state[1]
    st.update(phase=phase, last_daily_reset=_Clock.now().date(), shots=2, last_shot=_Clock.now(),
              last_phase_change=_Clock.now() - timedelta(minutes=5), vmax_wetup=[48.0, 52.5, 55.0])
    return c, st


def test_a_blind_zone_starts_the_new_day_with_a_fresh_wet_up_curve(recorded):
    c, st = _blind_room("P3")
    _Clock.current = _Clock.current + timedelta(days=1, hours=-4, minutes=5)  # 10:05 the next day: lights-on
    c.loop_once(_Clock.now())
    assert st["phase"] == "P0"
    assert st["vmax_wetup"] == []
    assert st["ec_offset"] == 0.0 and st["last_daily_reset"] == _Clock.now().date()
    assert ("P3", "P0") in recorded


def test_every_phase_change_of_a_blind_zone_reaches_its_history(recorded):
    c, st = _blind_room("P2")
    _Clock.current = _Clock.current.replace(hour=23)  # the rig's lights are 10:00-22:00
    c.loop_once(_Clock.now())
    assert st["phase"] == "P3"
    assert ("P2", "P3") in recorded
