"""The controller holds a zone's overnight dryback at its target only when its P3 Dryback Hold is on.

Off, or missing (an integration older than the switch), P3 waters only below the rescue level, as it
always has. On, a zone that dries to the day's peak less its dryback target gets a rescue-sized shot, the
P3 time between shots apart.
"""

from datetime import timedelta

import controller
from test_p3_time_between_shots import Clock, probe, rig  # noqa: F401  (rig is a fixture)

HOLD = "switch.crop_steering_zone_1_p3_dryback_hold"


def nights(c, fake, room, minutes):
    """One pass a minute with zone 1 at 60% after an 86.5% peak (a 30% dryback ends at 60.55%) and well
    above the 40% rescue level: the minutes zone 1 was watered."""
    for mode in ("vegetative", "generative"):
        fake.set_state(f"number.crop_steering_{mode}_dryback_target", "30")
    room.state[1]["peak"] = 86.5
    start, fired = Clock.instant, []
    for minute in range(minutes):
        Clock.instant = now = start + timedelta(minutes=minute)
        probe(fake, 1, 60)
        probe(fake, 2, 60)  # no peak seen: nothing to hold to
        before = len(fake.calls)
        c._loop_room(room, now)
        if ("switch", "turn_on", {"entity_id": "switch.v1"}) in fake.calls[before:]:
            fired.append(minute)
    assert ("switch", "turn_on", {"entity_id": "switch.v2"}) not in fake.calls
    return fired


def test_without_the_switch_p3_waters_only_below_the_rescue_level(rig):  # noqa: F811
    c, fake, room = rig
    assert HOLD not in fake.states
    assert c._params(room, 1).p3_hold is False
    assert nights(c, fake, room, 21) == []


def test_switched_off_p3_waters_only_below_the_rescue_level(rig):  # noqa: F811
    c, fake, room = rig
    fake.set_state(HOLD, "off")
    assert nights(c, fake, room, 21) == []


def test_switched_on_the_zone_is_held_at_its_target_ten_minutes_apart(rig):  # noqa: F811
    c, fake, room = rig
    fake.set_state(HOLD, "on")
    assert c._params(room, 1).p3_hold is True
    assert c._params(room, 2).p3_hold is False  # the switch is the zone's own
    assert nights(c, fake, room, 21) == [0, 10, 20]
    assert controller.PLAN_HOLD_EXEMPT.isdisjoint({"p3_hold"})  # a held plan stops it
