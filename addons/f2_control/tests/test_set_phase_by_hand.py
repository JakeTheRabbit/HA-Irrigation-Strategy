"""A zone moved to a phase by hand, from its Set Phase select.

25 Sep 2026: after F2 was switched off and on again, its three zones went from P2 back to a P1 ramp an
hour before lights-off, and there was no way to put them back. Now the operator picks a phase on
select.crop_steering_zone_N_set_phase; the controller moves the zone once, sets the select back to
Keep, and its own rules carry on from that phase.
"""
from datetime import datetime, timedelta, timezone

import pytest

import controller
from test_room_status import _room

SET = "select.crop_steering_zone_1_set_phase"
VWC = "sensor.crop_steering_vwc_zone_1"


class _Clock(datetime):
    """The controller's wall clock, pinned, in local time and (for sensor freshness) in UTC."""

    current = None

    @classmethod
    def now(cls, tz=None):
        return cls.current if tz is None else cls.current.astimezone(tz)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    _Clock.current = _Clock(2026, 9, 19, 14, 0)  # lights are 10:00-22:00 in the rig
    monkeypatch.setattr(controller, "datetime", _Clock)
    seconds = {"now": 0.0}
    monkeypatch.setattr(controller.time, "monotonic", lambda: seconds["now"])
    monkeypatch.setattr(controller.time, "sleep", lambda dt: seconds.__setitem__("now", seconds["now"] + dt))


def _zone(phase, **state):
    """An ON room, disarmed so no shot moves the counters under test, its zone reading 47 %."""
    c, fake = _room("on")
    fake.set_state("input_boolean.kill", "off")
    fake.set_state(VWC, "47", {"unit_of_measurement": "%"},
                   last_updated=_Clock.now(timezone.utc).isoformat())
    c.rooms[0].state[1].update(phase=phase, last_daily_reset=_Clock.now().date(), **state)
    return c, fake


def _resets(fake):
    return [d for dom, svc, d in fake.calls if (dom, svc) == ("select", "select_option") and d["entity_id"] == SET]


def test_a_zone_set_to_p2_by_hand_is_in_p2_and_its_select_goes_back_to_keep():
    c, fake = _zone("P1", shots=3, daily_vol=10.0)
    fake.set_state(SET, "P2")
    c.loop_once(_Clock.now())
    st = c.rooms[0].state[1]
    assert st["phase"] == "P2"
    assert (st["shots"], st["daily_vol"]) == (3, 10.0)  # today's water and shots are not touched
    assert _resets(fake) == [{"entity_id": SET, "option": "Keep"}]
    assert "Z1 phase P1 -> P2, set by hand" in c._activity[0]


def test_p1_set_by_hand_ramps_from_its_first_shot():
    c, fake = _zone("P2", shots=6, daily_vol=18.0)
    fake.set_state(SET, "P1")
    c.loop_once(_Clock.now())
    st = c.rooms[0].state[1]
    assert st["phase"] == "P1" and st["shots"] == 0 and st["daily_vol"] == 18.0


def test_p0_set_by_hand_measures_its_dry_back_from_the_moisture_now():
    c, fake = _zone("P2", peak=61.0)
    fake.set_state(SET, "P0")
    c.loop_once(_Clock.now())
    st = c.rooms[0].state[1]
    assert st["phase"] in ("P0", "P1")  # P0, or straight on to P1 if the engine bypasses it
    assert st["peak"] == 47.0  # the old 61 % peak would have counted a 14-point dry-back already


def test_a_request_is_applied_once_only_after_its_select_is_back_on_keep(monkeypatch):
    c, fake = _zone("P1")
    fake.set_state(SET, "P2")

    def refused(domain, service, **data):  # Home Assistant does not take the write
        return False if domain == "select" else fake.ha_call(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", refused)
    c.loop_once(_Clock.now())
    assert c.rooms[0].state[1]["phase"] == "P1"  # not applied: it would be applied again next loop
    monkeypatch.setattr(controller, "ha_call", fake.ha_call)
    c.loop_once(_Clock.now())
    assert c.rooms[0].state[1]["phase"] == "P2"


@pytest.mark.parametrize("value", ["Keep", "unknown", "P5", None])
def test_keep_or_anything_else_changes_nothing(value):
    c, fake = _zone("P1", shots=2)
    if value is not None:
        fake.set_state(SET, value)
    c.loop_once(_Clock.now())
    st = c.rooms[0].state[1]
    assert (st["phase"], st["shots"]) == ("P1", 2)
    assert _resets(fake) == []


def test_the_engines_rules_carry_on_from_the_phase_set_by_hand():
    """P2 picked at night: lights-off moves every zone to P3, and it does so again at once."""
    _Clock.current = _Clock(2026, 9, 19, 23, 0)
    c, fake = _zone("P3")
    fake.set_state(SET, "P2")
    c.loop_once(_Clock.now())
    assert c.rooms[0].state[1]["phase"] == "P3"
    assert _resets(fake)  # the request was taken, and the engine moved the zone on from it


def test_a_zone_set_by_hand_is_not_moved_again_on_the_next_loop():
    c, fake = _zone("P1", shots=3)
    fake.set_state(SET, "P2")
    c.loop_once(_Clock.now())
    fake.set_state(SET, "Keep")  # what Home Assistant shows once the controller's write lands
    _Clock.current += timedelta(minutes=1)
    fake.set_state(VWC, "47", {"unit_of_measurement": "%"},
                   last_updated=_Clock.now(timezone.utc).isoformat())
    c.loop_once(_Clock.now())
    assert c.rooms[0].state[1]["phase"] == "P2" and len(_resets(fake)) == 1
