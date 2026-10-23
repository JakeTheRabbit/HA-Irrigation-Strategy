"""The morning of issue #195, through the controller: P0 waits for the plants to transpire.

The slab peaked at 71.5 yesterday and dried overnight to 46.9 by lights-on, under the 57 re-water point. P0 used
to end a minute after lights-on ("P0 bypass VWC 47<=rewater 57") and the ramp watered plants that were not
drinking yet. P0 now ends early only at the rescue floor; otherwise it waits for its dryback, measured from the
highest reading since lights-on (not yesterday's peak), or its maximum wait.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

import controller
import fake_ha

pytestmark = pytest.mark.usefixtures("settings_built_in")

LIGHTS_ON = datetime(2026, 9, 24, 10, 0)  # the shipped lights are 10-22


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
    Clock.instant = Clock(2026, 9, 24, 9, 59)
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
    for key, value in {"plant_count": 9, "substrate_volume": 3.375, "drippers_per_plant": 1,
                       "dripper_flow_rate": 4, "p1_target_vwc": 69, "field_capacity": 75,
                       "p2_vwc_threshold": 57, "p3_emergency_vwc_threshold": 40, "p0_maximum_wait_time": 150,
                       "generative_dryback_target": 40, "vegetative_dryback_target": 40}.items():
        fake.set_state(f"number.crop_steering_{key}", str(value))
    clock = Monotonic()
    monkeypatch.setattr(controller.time, "sleep", clock.sleep)
    monkeypatch.setattr(controller.time, "monotonic", clock.monotonic)
    room = c.rooms[0]
    room._was_lights_on = False
    for zone in (1, 2):
        room.state[zone].update(
            phase="P3", peak=71.5, last_daily_reset=date(2026, 9, 23),
            last_phase_change=Clock(2026, 9, 23, 22, 0), last_shot=Clock(2026, 9, 23, 21, 0),
        )
    return c, fake, room


def probe(fake, zone, vwc, ec=3.0):
    stamp = Clock.now(timezone.utc).isoformat()
    fake.set_state(f"sensor.crop_steering_vwc_zone_{zone}", str(vwc), last_updated=stamp)
    fake.set_state(f"sensor.crop_steering_ec_zone_{zone}", str(ec), last_updated=stamp)


def tick(c, fake, room, minutes, zone1, zone2=50.0):
    """One pass at `minutes` after lights-on: the zones watered on it."""
    Clock.instant = now = LIGHTS_ON + timedelta(minutes=minutes)
    probe(fake, 1, zone1)
    probe(fake, 2, zone2)
    before = len(fake.calls)
    pub = c._loop_room(room, now)
    return pub, [z for z in (1, 2) if ("switch", "turn_on", {"entity_id": f"switch.v{z}"}) in fake.calls[before:]]


def test_the_issue_morning_waits_in_p0_and_measures_its_dryback_from_lights_on(rig):
    c, fake, room = rig
    tick(c, fake, room, 0, 46.9)
    assert room.state[1]["phase"] == "P0"
    assert room.state[1]["peak"] == 46.9  # the peak is the lights-on reading, not yesterday's 71.5
    for minute in (1, 2, 5, 30):
        pub, watered = tick(c, fake, room, minute, 46.9 - minute * 0.01)
        assert room.state[1]["phase"] == "P0", (minute, pub[1]["reason"])
        assert "bypass" not in str(pub[1]["reason"])
        assert 1 not in watered
    snap, _p = c._snapshot(room, 1, Clock.instant, True, False)
    assert snap.peak_vwc == 46.9
    assert snap.dryback_pct == pytest.approx((46.9 - 46.6) / 46.9 * 100)
    _pub, watered = tick(c, fake, room, 149, 45.4)
    assert room.state[1]["phase"] == "P0" and 1 not in watered
    pub, watered = tick(c, fake, room, 150, 45.4)
    assert room.state[1]["phase"] == "P1" and 1 in watered
    assert str(pub[1]["reason"]).startswith("P0 timeout 150min")


def test_a_zone_under_the_rescue_floor_still_bypasses_p0_and_gets_water(rig):
    c, fake, room = rig
    tick(c, fake, room, 0, 46.9, zone2=35.0)
    pub, watered = tick(c, fake, room, 1, 46.9, zone2=35.0)
    assert room.state[2]["phase"] == "P1" and 2 in watered
    assert str(pub[2]["reason"]).startswith("P0 emergency bypass VWC 35<=floor 40")
    assert room.state[1]["phase"] == "P0" and 1 not in watered
