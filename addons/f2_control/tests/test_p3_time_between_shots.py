"""The controller spaces P3 emergency shots by the room's P3 Time Between Shots.

A probe stuck low overnight used to get a rescue every pass (60 s) all night: each one goes in under
the probe and has not reached it a minute later. Now the next waits the gap from the last shot, 10
minutes unless the room or the zone says otherwise; the first of the night still goes at once. A
controller updated ahead of its integration has no such number and uses the same 10, without raising
the missing-setting alert.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

import controller
import fake_ha

ROOM = "number.crop_steering_p3_time_between_shots"
ZONE = "number.crop_steering_zone_1_p3_time_between_shots"


class Clock(datetime):
    """The controller's wall clock, pinned by the test."""

    instant = None

    @classmethod
    def now(cls, tz=None):
        return cls.instant.replace(tzinfo=tz) if tz else cls.instant


class Monotonic:
    def __init__(self):
        self.seconds = 0.0

    def sleep(self, seconds):
        self.seconds += seconds

    def monotonic(self):
        return self.seconds


@pytest.fixture
def rig(monkeypatch, tmp_path):
    Clock.instant = Clock(2026, 9, 23, 23, 0)  # lights 10-22: night
    monkeypatch.setattr(controller, "datetime", Clock)
    fake = fake_ha.FakeHA()
    options = {
        "num_zones": 2,
        "hardware": {"pump": "switch.p", "mainline": "switch.m",
                     "valves": {"1": "switch.v1", "2": "switch.v2"}},
        "enable_flag": "input_boolean.kill",
    }
    monkeypatch.setattr(controller, "load_options", lambda: options)
    for name in ("ha_get", "ha_get_status", "ha_call", "ha_get_all", "ha_set"):
        monkeypatch.setattr(controller, name, getattr(fake, name))
    with monkeypatch.context() as setup:
        setup.setattr(controller.Controller, "_read_state_file", lambda self: {})
        c = controller.Controller()
    c._state_path = str(tmp_path / "state.json")
    for eid in ("input_boolean.kill", "switch.crop_steering_system_enabled",
                "switch.crop_steering_auto_irrigation_enabled",
                "switch.crop_steering_zone_1_enabled", "switch.crop_steering_zone_2_enabled"):
        fake.set_state(eid, "on")
    for eid in ("switch.p", "switch.m", "switch.v1", "switch.v2"):
        fake.set_state(eid, "off")
    for key, value in {"plant_count": 42, "substrate_volume": 6.75,
                       "drippers_per_plant": 1, "dripper_flow_rate": 4}.items():
        fake.set_state(f"number.crop_steering_{key}", str(value))
    clock = Monotonic()
    monkeypatch.setattr(controller.time, "sleep", clock.sleep)
    monkeypatch.setattr(controller.time, "monotonic", clock.monotonic)
    room = c.rooms[0]
    room._was_lights_on = False
    for zone in (1, 2):
        room.state[zone].update(
            phase="P3", last_daily_reset=date(2026, 9, 23), last_phase_change=Clock(2026, 9, 23, 22, 0),
            last_shot=Clock(2026, 9, 23, 21, 0),
        )
    return c, fake, room


def probe(fake, zone, vwc, ec=5.0):
    stamp = Clock.now(timezone.utc).isoformat()
    fake.set_state(f"sensor.crop_steering_vwc_zone_{zone}", str(vwc), last_updated=stamp)
    fake.set_state(f"sensor.crop_steering_ec_zone_{zone}", str(ec), last_updated=stamp)


def night(c, fake, room, minutes):
    """One pass a minute with zone 1's probe stuck under the 40 rescue level: the minutes zone 1 was watered."""
    start, fired = Clock.instant, []
    for minute in range(minutes):
        Clock.instant = now = start + timedelta(minutes=minute)
        probe(fake, 1, 30)
        probe(fake, 2, 55)
        before = len(fake.calls)
        c._loop_room(room, now)
        if ("switch", "turn_on", {"entity_id": "switch.v1"}) in fake.calls[before:]:
            fired.append(minute)
    assert ("switch", "turn_on", {"entity_id": "switch.v2"}) not in fake.calls  # zone 2 reads over it
    return fired


def test_a_stuck_low_probe_gets_one_rescue_every_ten_minutes_the_first_at_once(rig):
    c, fake, room = rig
    assert night(c, fake, room, 31) == [0, 10, 20, 30]


def test_the_zones_own_value_wins_over_the_rooms(rig):
    c, fake, room = rig
    fake.set_state(ROOM, "10")
    fake.set_state(ZONE, "15")
    assert c._params(room, 1).p3_time_between_min == 15
    assert c._params(room, 2).p3_time_between_min == 10
    assert night(c, fake, room, 31) == [0, 15, 30]


def test_zero_turns_the_gap_off(rig):
    c, fake, room = rig
    fake.set_state(ZONE, "0")
    assert night(c, fake, room, 3) == [0, 1, 2]


def test_an_integration_without_the_setting_leaves_the_controller_at_ten_minutes(rig):
    c, fake, room = rig
    assert ROOM not in fake.states and ZONE not in fake.states
    assert c._params(room, 1).p3_time_between_min == controller.FALLBACK["p3_time_between_shots"] == 10
    assert ROOM not in c._defaulted_this_loop
