"""Auto setpoints inside the controller: learning always runs, WRITES only happen when the room's
opt-in switch is on, only to that zone's own number entities, and never while a grow plan owns the room."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import auto_setpoints as au
import controller
from test_controller import _build, _desc

AUTO = "switch.crop_steering_auto_setpoints"
NUMBERS = {
    "number.crop_steering_zone_1_p1_target_vwc": ("40", {}),
    "number.crop_steering_zone_1_field_capacity": ("55", {}),
    "number.crop_steering_zone_1_p2_vwc_threshold": ("34", {}),
    "number.crop_steering_zone_1_p3_emergency_vwc_threshold": ("22", {}),
    "number.crop_steering_zone_1_p2_shot_size": ("3", {}),
}


class _Clock(datetime):
    """The controller's wall clock, pinned mid-photoperiod and moved by the test. On the real clock a
    ramp started within 84 minutes of lights-on crossed into a new grow-day and lost its own record."""
    current = datetime(2026, 9, 19, 11, 0)

    @classmethod
    def now(cls, tz=None):
        return cls.current


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    _Clock.current = datetime(2026, 9, 19, 11, 0)
    monkeypatch.setattr(controller, "datetime", _Clock)


def _p(fake):
    """The zone's params as the engine would read them THIS tick (so a write is seen on the next one)."""
    def num(suffix, default):
        state = fake.states.get(f"number.crop_steering_zone_1_{suffix}", (None,))[0]
        return float(state) if state is not None else default

    return SimpleNamespace(
        p1_target=num("p1_target_vwc", 40.0), field_capacity=num("field_capacity", 55.0),
        p3_emergency_floor=num("p3_emergency_vwc_threshold", 22.0), p2_shot_size=num("p2_shot_size", 3.0),
        dryback_target=12.0, p0_max_wait_min=60.0, p1_initial=3.0, p1_time_between_min=20.0,
        ec_target_p1=4.5, ec_target_p2=5.5)


def _rig(auto="on", numbers=NUMBERS, options=None):
    states = {"sensor.crop_steering_engine_config": ("ok", _desc()), AUTO: (auto, {}), **numbers}
    c, fake = _build({"num_zones": 1, **(options or {})}, states=states)
    plain = controller.ha_call

    def call(domain, service, **data):  # Home Assistant reflects a number.set_value in the entity state
        if (domain, service) == ("number", "set_value"):
            fake.set_state(data["entity_id"], data["value"])
        return plain(domain, service, **data)

    controller.ha_call = call
    return c, fake, c.rooms[0]


def _tick(c, fake, room, vwc, now, rate=0.0):
    c._auto_tick(room, 1, SimpleNamespace(vwc=vwc, ec=5.0, dryback_rate=rate), _p(fake), True, now)


def _flat_ramp(c, fake, room, rises=(1.8, 1.8, 0.1, 0.1), start=30.0):
    """Drive a P1 ramp through the real hooks: shot -> 21 minutes (the ramp spacing) -> retained reading."""
    st, now, vwc = room.state[1], _Clock.current, start
    st["phase"] = "P1"
    _tick(c, fake, room, vwc, now)
    for rise in rises:
        c._advance_shot_counters(room, 1, 3.0)  # stamps the shot with the controller's own clock
        vwc, now = vwc + rise, now + timedelta(minutes=21)
        _Clock.current = now
        _tick(c, fake, room, vwc, now)
    return vwc, now


def _writes(fake):
    return {d["entity_id"]: d["value"] for dom, svc, d in fake.calls if (dom, svc) == ("number", "set_value")}


def test_switch_off_learns_and_reports_but_never_writes():
    c, fake, room = _rig(auto="off")
    _flat_ramp(c, fake, room)
    assert _writes(fake) == {}
    state, attrs = fake.sets["sensor.crop_steering_zone_1_auto_setpoints"]
    assert state == "off" and attrs["learned_peak"] == 33.8 and attrs["p1_outcome"] == "plateau"
    assert "number.crop_steering_zone_1_p1_target_vwc" in attrs["managed"]


def test_only_the_zones_own_number_entities_are_ever_written():
    c, fake, room = _rig(numbers={})  # this install has no per-zone numbers: room-level values are NOT touched
    _flat_ramp(c, fake, room)
    assert _writes(fake) == {}


def test_an_armed_grow_plan_owns_the_room_so_nothing_is_written():
    c, fake, room = _rig()
    room.strategy_required = True
    _flat_ramp(c, fake, room)
    assert _writes(fake) == {}


def test_a_ramp_that_never_lifted_vwc_freezes_and_alerts_once_instead_of_learning_a_false_ceiling():
    c, fake, room = _rig()
    _flat_ramp(c, fake, room, rises=(0.1, 0.0, 0.1), start=24.0)
    assert _writes(fake) == {}
    assert fake.sets["sensor.crop_steering_zone_1_auto_setpoints"][0] == "frozen"
    alerts = [d for dom, svc, d in fake.calls if (dom, svc) == ("persistent_notification", "create")]
    assert len([a for a in alerts if "auto_" in a["notification_id"]]) == 1


def test_learned_state_is_saved_with_the_zone_and_restored():
    c, fake, room = _rig()
    _flat_ramp(c, fake, room)
    saved = c._serialize_zone(room.state[1])
    restored = c._apply_saved_zone(c._fresh_zone(), saved)
    assert restored["learn"] == room.state[1]["learn"] and restored["learn"]["peak"] == 33.8
    assert c._apply_saved_zone(c._fresh_zone(), {"learn": "junk"})["learn"] == au.fresh()


@pytest.mark.parametrize("phase", ["P1", "P2"])
def test_the_same_value_is_not_rewritten_every_tick(phase):
    c, fake, room = _rig()
    vwc, now = _flat_ramp(c, fake, room)
    room.state[1]["phase"] = phase
    fake.calls.clear()
    frozen = _p(fake)  # HA has NOT reflected the write yet: the same value must not be re-sent every tick
    for k in range(3):
        c._auto_tick(room, 1, SimpleNamespace(vwc=vwc, ec=5.0, dryback_rate=0.0), frozen, True, now + timedelta(minutes=k))
    sent = [(d["entity_id"], d["value"]) for dom, svc, d in fake.calls if (dom, svc) == ("number", "set_value")]
    assert len(sent) == len(set(sent))


@pytest.mark.parametrize("mode, stop", [("Vegetative", "19:00"), ("Generative", "16:00")])
def test_a_dryback_the_nights_cannot_reach_keeps_the_zones_afternoon_by_its_steering_mode(mode, stop):
    """Vegetative, a 30% P3 dryback its nights could not reach, and no maintenance shot all day after the
    ramp. At 17:00 (lights 10:00-22:00) a vegetative zone is still watered, a generative one has been
    drying since the middle of the day, and the dashboard is told why and from when."""
    c, fake, room = _rig(numbers={**NUMBERS, "select.crop_steering_zone_1_steering_mode": (mode, {}),
                                  # a rescue level the 30% dryback stays above
                                  "number.crop_steering_zone_1_p3_emergency_vwc_threshold": ("15", {})})
    room.lights_on_hour, room.lights_off_hour = 10.0, 22.0
    room.state[1]["learn"] = dict(
        au.fresh(), peak=36.0, gain=0.6, day_rate=0.72, night_rate=0.37,
        day_n=au.MIN_RATE_DAYS, night_n=au.MIN_RATE_DAYS, outcome="reached", hold_days=2,
    )
    room.state[1]["phase"], room.state[1]["shots"] = "P2", 6
    _Clock.current = datetime(2026, 9, 19, 17, 0)
    p = SimpleNamespace(**{**vars(_p(fake)), "dryback_target": 30.0})
    c._auto_tick(room, 1, SimpleNamespace(vwc=35.0, ec=5.0, dryback_rate=0.0), p, True, _Clock.current)
    trigger = float(fake.states["number.crop_steering_zone_1_p2_vwc_threshold"][0])
    band = round(36.0 - 0.6 * 3.0, 1)
    assert (trigger == band) is (mode == "Vegetative")
    attrs = fake.sets["sensor.crop_steering_zone_1_auto_setpoints"][1]
    assert attrs["dryback_note"].startswith("30% dryback unreachable at this zone's uptake")
    assert attrs["dryback_note"].endswith(stop) and attrs["p2_stop"] == stop
