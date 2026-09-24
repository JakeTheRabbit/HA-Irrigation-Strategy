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


def test_plateau_fails_p1_over_by_dropping_the_target_to_what_the_zone_achieved():
    c, fake, room = _rig()
    vwc, now = _flat_ramp(c, fake, room)  # 30 -> 33.8, then two flat shots
    assert _writes(fake)["number.crop_steering_zone_1_p1_target_vwc"] == 34.0  # big moves go 6 points a pass...
    _tick(c, fake, room, vwc, now + timedelta(minutes=1))
    w = _writes(fake)
    assert w["number.crop_steering_zone_1_p1_target_vwc"] == round(vwc - 0.1, 1)  # ...and land a minute later:
    # a target the zone has already met, so the engine's own "P1 recovered" rule hands over to P2
    assert room.state[1]["learn"]["peak"] == 33.8
    assert any("auto" in line and "p1_target_vwc" in line for line in c._activity)


def test_once_in_p2_the_achieved_peak_is_the_target_going_forward_and_the_band_follows_it():
    c, fake, room = _rig()
    vwc, now = _flat_ramp(c, fake, room)
    room.state[1]["phase"] = "P2"
    for k in (6, 7):
        _tick(c, fake, room, vwc - 0.3, now + timedelta(minutes=k), rate=0.7)
    w = _writes(fake)
    assert w["number.crop_steering_zone_1_p1_target_vwc"] == 33.8
    assert w["number.crop_steering_zone_1_p2_vwc_threshold"] == round(33.8 - room.state[1]["learn"]["gain"] * 3.0, 1)


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


# ------------------------------------------------------------------ Jev as a guard on the learning
JEV = {"cf_account_id": "acc", "cf_api_token": "tok"}


def _answers(fail=0.04, trust=0.92):
    return {"ec_steer": {"score": 2.0, "confidence": 0.9}, "peak_fit": {"choice": "lower_peak", "confidence": 0.9},
            "probe_trust": {"noul": trust}, "delivery_failure": {"noul": fail}}


def test_jev_can_veto_a_plateau_it_reads_as_a_delivery_failure(monkeypatch):
    monkeypatch.setattr(controller.jev_policy, "call", lambda *a, **k: _answers(fail=0.91))
    c, fake, room = _rig(options=JEV)
    _flat_ramp(c, fake, room)
    assert _writes(fake) == {} and room.state[1]["learn"]["outcome"] == "suspect"
    assert room.state[1]["learn"]["peak"] is None  # the false ceiling was not kept


def test_jev_agreeing_or_being_unreachable_leaves_the_arithmetic_in_charge(monkeypatch):
    for answer, label in ((_answers(), "ok"), (None, "unavailable")):
        monkeypatch.setattr(controller.jev_policy, "call", lambda *a, **k: answer)
        c, fake, room = _rig(options=JEV)
        _flat_ramp(c, fake, room)
        assert "number.crop_steering_zone_1_p1_target_vwc" in _writes(fake)
        assert fake.sets["sensor.crop_steering_zone_1_auto_setpoints"][1]["jev"] == label


def test_without_cloudflare_credentials_jev_is_simply_disabled(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not be called")

    monkeypatch.setattr(controller.jev_policy, "call", boom)
    c, fake, room = _rig()
    _flat_ramp(c, fake, room)
    assert fake.sets["sensor.crop_steering_zone_1_auto_setpoints"][1]["jev"] == "disabled"


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


# ------------------------------------------------------------------ Jev manages P2
# The owner, 2026-09-20: "setup jev to manage the p2 using cloudflare". Until now Jev was asked once, at a P1
# plateau. In P2 it is now asked once an hour whether pore EC wants bigger or smaller maintenance shots
# and whether the learned peak fits. It can only nudge, one step per lever per grow-day, inside fixed
# bounds; a guard that trips means hands off; an unreachable Cloudflare never delays a shot.
P2_SHOT = "number.crop_steering_zone_1_p2_shot_size"


def _p2_rig(monkeypatch, answers, options=JEV, auto="on"):
    asked = []

    def call(account, token, state, gateway=None, timeout=5.0):
        asked.append(state)
        return answers() if callable(answers) else answers

    monkeypatch.setattr(controller.jev_policy, "call", call)
    c, fake, room = _rig(auto=auto, options=options)
    vwc, now = _flat_ramp(c, fake, room)  # the zone knows its peak; the ramp is over
    room.state[1]["phase"] = "P2"
    asked.clear()
    fake.calls.clear()
    return c, fake, room, vwc, now, asked


def _p2_hours(c, fake, room, vwc, now, hours, ec=5.0):
    for minute in range(0, hours * 60, 10):
        _Clock.current = now + timedelta(minutes=minute)
        _tick(c, fake, room, vwc, _Clock.current)


def _flush_more():  # pore EC over range: level 4 = flush, i.e. +1 % on the shot... mapped by jev_policy.EC_STEP
    return {"ec_steer": {"score": 0.0, "confidence": 0.9}, "peak_fit": {"choice": "keep", "confidence": 0.9},
            "probe_trust": {"noul": 0.95}, "delivery_failure": {"noul": 0.03}}


def test_in_p2_jev_is_asked_once_an_hour_and_moves_the_shot_one_bounded_step_per_grow_day(monkeypatch):
    c, fake, room, vwc, now, asked = _p2_rig(monkeypatch, _flush_more)
    _p2_hours(c, fake, room, vwc, now, hours=3)
    assert 3 <= len(asked) <= 4  # hourly, not every tick
    assert asked[0]["phase"] == "P2" and "pore_ec" in asked[0]
    step = controller.jev_policy.EC_STEP[0]
    assert _writes(fake)[P2_SHOT] == 3.0 + step  # ONE step, although it was told the same thing every hour
    sent = [d["value"] for dom, svc, d in fake.calls if (dom, svc) == ("number", "set_value") and d["entity_id"] == P2_SHOT]
    assert sent == [3.0 + step]
    attrs = fake.sets["sensor.crop_steering_zone_1_auto_setpoints"][1]
    assert attrs["jev"] == "ok" and P2_SHOT in attrs["managed"]
    assert "p2_shot_size 3 -> 4" in attrs["jev_changed_today"]  # what it changed today stays visible...
    assert "no change" in attrs["jev_last"]  # ...and the latest hourly answer says it left things alone
    assert any("jev" in line.lower() and "p2_shot_size" in line for line in c._activity)


def test_the_shot_size_jev_asks_for_never_leaves_its_bounds(monkeypatch):
    numbers = {**NUMBERS, P2_SHOT: ("4", {})}
    monkeypatch.setattr(controller.jev_policy, "call", lambda *a, **k: _flush_more())
    c, fake, room = _rig(numbers=numbers, options=JEV)
    vwc, now = _flat_ramp(c, fake, room)
    room.state[1]["phase"] = "P2"
    fake.calls.clear()
    _p2_hours(c, fake, room, vwc, now, hours=2)
    assert P2_SHOT not in _writes(fake)  # already at the 4 % ceiling: nothing to write


def test_a_guard_that_trips_in_p2_means_hands_off(monkeypatch):
    c, fake, room, vwc, now, asked = _p2_rig(monkeypatch, lambda: _answers(trust=0.2))
    _p2_hours(c, fake, room, vwc, now, hours=2)
    assert asked and P2_SHOT not in _writes(fake)
    assert "probe trust" in fake.sets["sensor.crop_steering_zone_1_auto_setpoints"][1]["jev_last"]


def test_cloudflare_being_down_in_p2_changes_nothing_and_is_reported(monkeypatch):
    c, fake, room, vwc, now, asked = _p2_rig(monkeypatch, None)
    _p2_hours(c, fake, room, vwc, now, hours=2)
    assert asked and P2_SHOT not in _writes(fake)
    assert fake.sets["sensor.crop_steering_zone_1_auto_setpoints"][1]["jev"] == "unavailable"


@pytest.mark.parametrize("why", ["switch off", "no credentials", "plan owns the room", "not P2"])
def test_jev_is_not_asked_when_it_has_no_business_being_asked(monkeypatch, why):
    options = None if why == "no credentials" else JEV
    c, fake, room, vwc, now, asked = _p2_rig(monkeypatch, _flush_more, options=options,
                                            auto="off" if why == "switch off" else "on")
    if why == "plan owns the room":
        room.strategy_required = True
    if why == "not P2":
        room.state[1]["phase"] = "P3"
    _p2_hours(c, fake, room, vwc, now, hours=2)
    assert asked == [] and P2_SHOT not in _writes(fake)


def test_jev_nudges_survive_a_restart_so_the_day_is_not_nudged_twice(monkeypatch):
    c, fake, room, vwc, now, asked = _p2_rig(monkeypatch, _flush_more)
    _p2_hours(c, fake, room, vwc, now, hours=1)
    saved = c._serialize_zone(room.state[1])
    restored = c._apply_saved_zone(c._fresh_zone(), saved)
    assert "ec" in restored["learn"]["jev"]["nudged"]
