"""A room switched off and on again, in a real Home Assistant, with the real controller.

25 Sep 2026, F2: to clear a hardware hold the operator switched the room off and on again at 20:53.
All three zones were in P2, an hour before lights-off, and the controller took the switch-on for a new
crop: it started their day again from P0, then a P1 ramp, with today's counters at 0. The room switch
here is the integration's own entity; only the controller's REST reads stand in for HTTP.
"""

from datetime import datetime, timedelta

from test_recreated_room_controller import _see
from test_setup_entry import _install

ROOM = "switch.crop_steering_room_active"


class _Clock(datetime):
    """The controller's wall clock, pinned, so the photoperiod does not depend on when CI runs."""

    current = None

    @classmethod
    def now(cls, tz=None):
        return cls.current


async def _switch(hass, fake, service):
    await hass.services.async_call("switch", service, {"entity_id": ROOM}, blocking=True)
    await hass.async_block_till_done()
    _see(hass, fake)


async def test_a_room_switched_off_and_on_again_carries_on_where_it_was(
    hass, controller_for, monkeypatch
):
    await _install(hass)
    c, fake, _clock = controller_for({})
    import controller

    monkeypatch.setattr(controller, "datetime", _Clock)
    _Clock.current = _Clock(2026, 9, 25, 20, 50)  # the lights are on (the new room's 12:00 to 00:00)
    room = c.rooms[0]
    zone = next(iter(room.zones))
    room.state[zone].update(
        phase="P2", shots=4, daily_vol=12.0, last_daily_reset=_Clock.current.date()
    )
    c.loop_once(_Clock.now())
    assert room.state[zone]["phase"] == "P2"

    await _switch(hass, fake, "turn_off")
    _Clock.current += timedelta(minutes=1)
    c.loop_once(_Clock.now())
    await _switch(hass, fake, "turn_on")
    _Clock.current += timedelta(minutes=3)
    c.loop_once(_Clock.now())

    st = room.state[zone]
    assert st["phase"] == "P2"  # not P0 and a P1 ramp: its day goes on
    assert (st["shots"], st["daily_vol"]) == (4, 12.0)
