"""A feed path that is offline holds the shot, and a probe out for minutes is a blip, not a dead probe.

25 Sep 2026, F2, 14:04: the pump went unavailable, then the main line and every valve (back at 14:49),
and the zones' moisture sensors read unknown. The controller watered Zone 2 on its dead-probe timer at
once, straight into the offline pump. Home Assistant took the commands, nothing switched, and the close
could not be read back, so a hardware hold latched (CS-301) and the room was not watered again until
someone re-armed it at 20:57. Now nothing opens while any switch on the feed path reads neither on nor
off, and a probe must be out for BLIND_GRACE_MIN minutes before its zone is watered on the timer or
alerted about.
"""
from datetime import datetime, timedelta, timezone

import pytest

import controller
from test_room_status import _room

VWC = "sensor.crop_steering_vwc_zone_1"
STATUS = "sensor.crop_steering_zone_1_status_app"


class _Clock(datetime):
    """The controller's wall clock, pinned, in local time and (for sensor freshness) in UTC."""

    current = None

    @classmethod
    def now(cls, tz=None):
        return cls.current if tz is None else cls.current.astimezone(tz)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    _Clock.current = _Clock(2026, 9, 25, 14, 0)  # lights are 10:00-22:00 in the rig
    monkeypatch.setattr(controller, "datetime", _Clock)
    seconds = {"now": 0.0}
    monkeypatch.setattr(controller.time, "monotonic", lambda: seconds["now"])
    monkeypatch.setattr(controller.time, "sleep", lambda dt: seconds.__setitem__("now", seconds["now"] + dt))


def _probe(fake, value="30"):
    fake.set_state(VWC, value, {"unit_of_measurement": "%"}, last_updated=_Clock.now(timezone.utc).isoformat())


def _later(minutes):
    _Clock.current += timedelta(minutes=minutes)


def _opened(fake):
    return [d["entity_id"] for dom, svc, d in fake.calls if (dom, svc) == ("switch", "turn_on")]


def _probe_alerts(fake):
    return [d for dom, svc, d in fake.calls
            if (dom, svc) == ("persistent_notification", "create") and "blind" in str(d.get("notification_id"))]


def _dry_p2_zone():
    """An armed room at 14:00 whose zone reads 30 %, under its P2 trigger: a top-up is due."""
    c, fake = _room("on")
    c.rooms[0].state[1].update(phase="P2", last_daily_reset=_Clock.now().date(),
                               last_shot=_Clock.now() - timedelta(hours=1))
    _probe(fake)
    return c, fake


def test_a_shot_waits_while_its_pump_is_offline_and_latches_nothing():
    c, fake = _dry_p2_zone()
    fake.set_state("switch.p", "unavailable")
    c.loop_once(_Clock.now())
    assert _opened(fake) == []  # nothing opened onto a pump that cannot switch
    assert c.rooms[0].hardware_fault is None  # and nothing latched
    assert fake.sets[STATUS][0].startswith("Blocked: switch.p offline")
    fake.set_state("switch.p", "off")  # the pump reads again
    _later(1)
    _probe(fake)
    c.loop_once(_Clock.now())
    assert _opened(fake) == ["switch.p", "switch.m", "switch.v1"]
    assert c.rooms[0].hardware_fault is None


@pytest.mark.parametrize("switch", ["switch.m", "switch.v1"])
@pytest.mark.parametrize("state", ["unavailable", "unknown", None])
def test_any_switch_on_the_feed_path_that_reads_neither_on_nor_off_holds_the_shot(switch, state):
    c, fake = _dry_p2_zone()
    if state is None:
        fake.states.pop(switch)  # the entity is gone, or Home Assistant cannot be reached
    else:
        fake.set_state(switch, state)
    c.loop_once(_Clock.now())
    assert _opened(fake) == [] and c.rooms[0].hardware_fault is None
    assert f"{switch} offline" in fake.sets[STATUS][0]


def test_a_probe_out_for_a_few_minutes_gets_no_timer_shot_and_no_alert():
    c, fake = _room("on")  # no moisture reading at all
    c.rooms[0].state[1].update(phase="P2", last_daily_reset=_Clock.now().date(), last_shot=None)
    for minutes in (0, 5, 9):  # 14:00, 14:05, 14:14
        _later(minutes)
        c.loop_once(_Clock.now())
        assert _opened(fake) == [] and _probe_alerts(fake) == []
    _later(1)  # out for 15 minutes: now it is a dead probe
    c.loop_once(_Clock.now())
    assert _probe_alerts(fake)
    assert _opened(fake) == ["switch.p", "switch.m", "switch.v1"]


def test_a_probe_that_reads_again_starts_its_wait_over():
    c, fake = _room("on")
    c.rooms[0].state[1].update(phase="P2", last_daily_reset=_Clock.now().date(),
                               last_shot=_Clock.now() - timedelta(hours=3))
    c.loop_once(_Clock.now())  # out from 14:00
    _later(10)
    _probe(fake, "60")  # back at 14:10, in band
    c.loop_once(_Clock.now())
    _later(1)
    fake.states.pop(VWC)  # out again from 14:11
    c.loop_once(_Clock.now())
    _later(13)  # 14:24: 24 minutes since the first outage began, 13 since this one
    c.loop_once(_Clock.now())
    assert _opened(fake) == [] and _probe_alerts(fake) == []
    _later(2)  # 14:26: this outage is 15 minutes old
    c.loop_once(_Clock.now())
    assert _opened(fake) and _probe_alerts(fake)
