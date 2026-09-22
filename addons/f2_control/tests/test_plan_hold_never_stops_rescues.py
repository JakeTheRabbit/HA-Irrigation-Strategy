"""A held grow-strategy plan stops the steering, never the water-safety shots.

While a room's plan is held (the integration publishes an error, the snapshot is stale, or it is missing
after a restart), the controller used to hold every shot on every zone the plan manages, for as long as
the hold lasted: a missed lights-on boundary held a room all day. Now the P3 emergency, the lights-on
watchdog and the minimum-daily floor still fire (and a blind zone's safety schedule, and its copy of a
sibling's rescue); every other gate still applies to them.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

import controller
import fake_ha
from crop_steering_engine import Reason

PLAN = "sensor.crop_steering_strategy_plan"
HOLD = "Lights-on boundary was missed; schedule held until the next boundary"


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
    Clock.instant = Clock(2026, 9, 23, 14, 0)  # lights 10-22
    monkeypatch.setattr(controller, "datetime", Clock)
    fake = fake_ha.FakeHA()
    options = {
        "num_zones": 2,
        "hardware": {"pump": "switch.p", "mainline": "switch.m",
                     "valves": {"1": "switch.v1", "2": "switch.v2"}},
        "enable_flag": "input_boolean.kill",
    }
    monkeypatch.setattr(controller, "load_options", lambda: options)
    for name in ("ha_get", "ha_call", "ha_get_all", "ha_set"):
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
    for zone in (1, 2):
        room.state[zone].update(last_daily_reset=date(2026, 9, 23), last_phase_change=Clock(2026, 9, 23, 10, 0))
    return c, fake, room


def probe(fake, zone, vwc=None, ec=5.0):
    stamp = Clock.now(timezone.utc).isoformat()
    if vwc is not None:
        fake.set_state(f"sensor.crop_steering_vwc_zone_{zone}", str(vwc), last_updated=stamp)
    if ec is not None:
        fake.set_state(f"sensor.crop_steering_ec_zone_{zone}", str(ec), last_updated=stamp)


def plan_held(fake, room):
    """The integration's plan in error: the controller must hold what the plan steers."""
    now = Clock.now()
    fake.set_state(PLAN, "error", {
        "snapshot_version": 1, "room_id": "room:", "enabled": True, "error": HOLD,
        "updated_at": now.isoformat(), "valid_until": (now + timedelta(seconds=180)).isoformat(),
        "managed_zone_ids": [1, 2], "zones": [],
    })
    room.strategy_required = True


def opened(fake):
    return [d["entity_id"] for dom, svc, d in fake.calls if dom == "switch" and svc == "turn_on"]


def test_a_zone_under_its_overnight_emergency_floor_is_watered_while_the_plan_is_held(rig):
    c, fake, room = rig
    Clock.instant = now = Clock(2026, 9, 23, 23, 0)
    room._was_lights_on = False
    for zone, vwc in ((1, 30), (2, 55)):
        probe(fake, zone, vwc)
        room.state[zone].update(phase="P3", last_shot=now - timedelta(hours=2))
    plan_held(fake, room)
    pub = c._loop_room(room, now)
    assert pub[1]["fire"] and pub[1]["block"] is None and pub[1]["reason"].kind == "p3_emergency"
    assert "switch.v1" in opened(fake) and "switch.v2" not in opened(fake)
    assert "Strategy hold" in pub[2]["block"]  # the hold is still shown on the zone it holds


def test_a_zone_drying_in_p2_gets_the_watchdog_while_the_plan_is_held(rig):
    c, fake, room = rig
    now = Clock.now()
    probe(fake, 1, 40)  # under the 45 re-water threshold, 4 h without water
    probe(fake, 2, 40)  # the same, but watered an hour ago: its top-up waits for the plan
    room.state[1].update(phase="P2", last_shot=now - timedelta(hours=4))
    room.state[2].update(phase="P2", last_shot=now - timedelta(hours=1))
    plan_held(fake, room)
    pub = c._loop_room(room, now)
    assert pub[1]["fire"] and pub[1]["block"] is None and "WATCHDOG" in pub[1]["reason"]
    assert not pub[2]["fire"] and "Strategy hold" in pub[2]["block"]
    assert opened(fake).count("switch.v1") == 1 and "switch.v2" not in opened(fake)


def test_the_minimum_daily_floor_fires_while_the_plan_is_held(rig):
    c, fake, room = rig
    now = Clock.now()
    fake.set_state("input_number.crop_steering_zone_1_min_daily_ml_per_plant", "500")  # 21 L for 42 plants
    probe(fake, 1, 50)
    probe(fake, 2, 50)
    for zone in (1, 2):
        room.state[zone].update(phase="P2", last_shot=now - timedelta(minutes=30))
    plan_held(fake, room)
    pub = c._loop_room(room, now)
    assert pub[1]["fire"] and pub[1]["reason"].kind == "min_daily" and pub[1]["block"] is None
    assert not pub[2]["fire"]  # zone 2 has no floor, and nothing else is due
    assert "switch.v1" in opened(fake)


def test_without_a_held_plan_the_same_zone_is_simply_topped_up(rig):
    c, fake, room = rig
    now = Clock.now()
    probe(fake, 1, 40)
    probe(fake, 2, 55)
    room.state[1].update(phase="P2", last_shot=now - timedelta(hours=4))
    room.state[2].update(phase="P2", last_shot=now - timedelta(hours=1))
    pub = c._loop_room(room, now)
    assert pub[1]["reason"].kind == "p2_topup" and pub[2]["block"] is None


def test_every_other_gate_still_stops_a_rescue(rig):
    c, fake, room = rig
    now = Clock.now()
    fake.set_state("input_boolean.kill", "off")
    probe(fake, 1, 40)
    probe(fake, 2, 55)
    room.state[1].update(phase="P2", last_shot=now - timedelta(hours=4))
    plan_held(fake, room)
    pub = c._loop_room(room, now)
    assert pub[1]["fire"] and "kill switch" in pub[1]["block"]
    assert opened(fake) == []


def test_a_plan_that_goes_stale_between_the_decision_and_the_shot_does_not_stop_a_rescue(rig):
    c, fake, room = rig
    plan_held(fake, room)
    c._load_strategy_snapshot(room, Clock.now())
    watchdog = Reason("WATCHDOG 4.0h no water (VWC 40<45)", "watchdog", True)
    c._act_zone(room, 1, c._params(room, 1), None, (True, 5.0, watchdog), None, True, Clock.now())
    topup = Reason("P2 top-up VWC 40<45", "p2_topup", False)
    c._act_zone(room, 2, c._params(room, 2), None, (True, 5.0, topup), None, True, Clock.now())
    assert opened(fake).count("switch.v1") == 1 and "switch.v2" not in opened(fake)


def test_a_blind_zone_keeps_its_safety_schedule_while_the_plan_is_held(rig):
    c, fake, room = rig
    now = Clock.now()
    for zone in (1, 2):  # no probe reading on either zone: nothing to copy, the blind schedule runs
        room.state[zone].update(phase="P2", last_shot=now - timedelta(hours=2))
    plan_held(fake, room)
    pub = c._loop_room(room, now)
    for zone in (1, 2):
        assert pub[zone]["fire"] and pub[zone]["block"] is None
        assert pub[zone]["reason"].kind == "blind_fallback" and not pub[zone]["reason"].cap_exempt
    assert {"switch.v1", "switch.v2"} <= set(opened(fake))


def test_a_blind_zone_copies_a_siblings_rescue_through_the_hold(rig):
    c, fake, room = rig
    now = Clock.now()
    probe(fake, 1, 40)  # zone 2 is blind and copies zone 1, which gets the watchdog
    for zone in (1, 2):
        room.state[zone].update(phase="P2", last_shot=now - timedelta(hours=4))
    plan_held(fake, room)
    pub = c._loop_room(room, now)
    assert pub[2]["reason"].kind == "blind_copy_rescue" and pub[2]["fire"] and pub[2]["block"] is None
    assert "switch.v2" in opened(fake)


def test_a_copy_of_routine_steering_is_held_like_the_steering(rig):
    c, fake, room = rig
    now = Clock.now()
    probe(fake, 1, 40)  # no plan: zone 1 is topped up and blind zone 2 copies it
    for zone in (1, 2):
        room.state[zone].update(phase="P2", last_shot=now - timedelta(hours=1))
    pub = c._loop_room(room, now)
    assert pub[2]["reason"].kind == "blind_copy" and pub[2]["fire"]
    plan_held(fake, room)
    c._load_strategy_snapshot(room, now)
    assert "Strategy hold" in c._blocked(room, 2, pub[2]["reason"])
    assert c._blocked(room, 2, Reason("COPY Z1 (VWC probe dead)", "blind_copy_rescue")) is None
