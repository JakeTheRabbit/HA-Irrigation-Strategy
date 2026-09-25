"""A zone moved to a phase by hand, in a real Home Assistant, with the real controller.

The operator picks a phase on the integration's own select.crop_steering_zone_N_set_phase. The
controller, which only reads and writes over REST, moves the zone and sets the select back to Keep:
its write is replayed into Home Assistant here, so the real entity has to accept it.
"""

from datetime import datetime

from test_recreated_room_controller import _see
from test_setup_entry import _install

SET = "select.crop_steering_zone_1_set_phase"


class _Clock(datetime):
    """The controller's wall clock, pinned, so the photoperiod does not depend on when CI runs."""

    current = None

    @classmethod
    def now(cls, tz=None):
        return cls.current if tz is None else cls.current.astimezone(tz)


async def test_a_phase_picked_on_the_zone_select_moves_the_zone_once(
    hass, controller_for, monkeypatch
):
    await _install(hass)
    picker = hass.states.get(SET)
    assert picker.state == "Keep"
    assert picker.attributes["options"] == ["Keep", "P0", "P1", "P2", "P3"]

    c, fake, _clock = controller_for({})
    import controller

    monkeypatch.setattr(controller, "datetime", _Clock)
    _Clock.current = _Clock(2026, 9, 25, 20, 50)  # the lights are on (the new room's 12:00 to 00:00)
    zone = c.rooms[0].state[1]
    zone.update(phase="P1", shots=2, last_daily_reset=_Clock.current.date())

    await hass.services.async_call(
        "select", "select_option", {"entity_id": SET, "option": "P2"}, blocking=True
    )
    _see(hass, fake)
    c.loop_once(_Clock.now())
    assert zone["phase"] == "P2" and zone["shots"] == 2

    written = [
        data
        for domain, service, data in fake.calls
        if (domain, service) == ("select", "select_option")
    ]
    assert written == [{"entity_id": SET, "option": "Keep"}]
    for data in written:  # what the controller sends over REST, into the real entity
        await hass.services.async_call("select", "select_option", data, blocking=True)
    assert hass.states.get(SET).state == "Keep"
