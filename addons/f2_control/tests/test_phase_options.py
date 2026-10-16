"""The opt-in phase settings, read by the controller: the P0 minimum wait and stall exit, the EC flush target and its
episode latch, the per-zone P2 dilute ratio behind its room switch, the zone's P2 mode select and the timed P2
numbers, and the room's daily limit on how far the automatic writers move the moisture ladder.

An integration older than these has none of the entities: every read falls back to the rule as it was, and no
missing-setting alert is raised."""
import json
import math
from datetime import timedelta

import pytest

import brain_bridge
import controller
import phase_options
from test_controller import _build
from test_plan_hold_never_stops_rescues import Clock, probe, rig  # noqa: F401 (rig: a pytest fixture)
from test_setpoints_follow_highest_reading import _ladder, _peaks, _room, _writes

HARDWARE = {"pump": "switch.p", "mainline": "switch.m", "valves": {"1": "switch.v1"}}
NEW_NUMBERS = ("p0_minimum_wait", "ec_flush_target", "p2_timed_interval_min", "p2_timed_shot_size",
               "p2_timed_first_hours", "p2_end_hours_before_off", "p2_dilute_ratio")


def _params(states):
    c, _fake = _build({"num_zones": 1, "hardware": HARDWARE}, states=states)
    room = c.rooms[0]
    return c, room, c._params(room, 1)


def test_an_integration_without_them_decides_as_before_and_alerts_nothing():
    c, _room, p = _params({})
    assert (p.p0_min_wait_min, p.p0_stall_exit, p.ec_flush_target, p.p2_dilute_ratio) == (0.0, False, 0.0, 1.2)
    assert (p.p2_mode, p.p2_timed_interval_min, p.p2_timed_shot_size, p.p2_timed_first_h, p.p2_end_h_before_off) == (
        "moisture", 60.0, 0.0, 0.0, 0.0)
    for key in NEW_NUMBERS:
        assert f"number.crop_steering_{key}" not in c._defaulted_this_loop


def test_the_zones_own_values_reach_the_engine():
    z = "number.crop_steering_zone_1_"
    _c, _room, p = _params({
        z + "p0_minimum_wait": ("30", {}), "switch.crop_steering_p0_stall_exit": ("on", {}),
        z + "ec_flush_target": ("4.5", {}), "select.crop_steering_zone_1_p2_mode": ("Timed with guards", {}),
        z + "p2_timed_interval_min": ("45", {}), z + "p2_timed_shot_size": ("3", {}),
        z + "p2_timed_first_hours": ("2", {}), z + "p2_end_hours_before_off": ("1.5", {}),
    })
    assert (p.p0_min_wait_min, p.p0_stall_exit, p.ec_flush_target) == (30.0, True, 4.5)
    assert (p.p2_mode, p.p2_timed_interval_min, p.p2_timed_shot_size, p.p2_timed_first_h, p.p2_end_h_before_off) == (
        "timed_guarded", 45.0, 3.0, 2.0, 1.5)


@pytest.mark.parametrize("state, mode", [("Moisture", "moisture"), ("Timed", "timed"), ("unknown", "moisture"),
                                         ("Something else", "moisture")])
def test_the_p2_mode_select(state, mode):
    assert _params({"select.crop_steering_zone_1_p2_mode": (state, {})})[2].p2_mode == mode


def test_the_zones_dilute_ratio_is_read_only_behind_the_room_switch():
    ratio = {"number.crop_steering_zone_1_p2_dilute_ratio": ("1.5", {}),
             "number.crop_steering_p2_ec_high_threshold": ("1.8", {})}  # the old room value, edited and unread for months
    assert _params(ratio)[2].p2_dilute_ratio == 1.2
    on = dict(ratio, **{"switch.crop_steering_use_p2_ec_thresholds": ("on", {})})
    assert _params(on)[2].p2_dilute_ratio == 1.5
    old_room_only = {"number.crop_steering_p2_ec_high_threshold": ("1.8", {}),
                     "switch.crop_steering_use_p2_ec_thresholds": ("on", {})}
    assert _params(old_room_only)[2].p2_dilute_ratio == 1.2  # the old room ratio is never read


# ---------------------------------------------------------------- the flush episode
def test_the_flush_latch_opens_on_a_fired_flush_and_closes_at_the_goal():
    assert phase_options.flushing(False, 0.0, "p2_dilute", 6.0, None) is False  # no target: never
    assert phase_options.flushing(False, 4.0, "p2_dilute", 6.0, 4.0) is True
    assert phase_options.flushing(False, 4.0, "p2_topup", 6.0, 4.0) is False
    assert phase_options.flushing(True, 4.0, None, 5.0, 4.0) is True
    assert phase_options.flushing(True, 4.0, None, 4.0, 4.0) is False
    assert phase_options.flushing(True, 0.0, None, 5.0, None) is False  # target switched off


def test_lights_off_and_lights_on_end_a_flush_episode(rig):  # noqa: F811
    c, _fake, room = rig
    st = room.state[1]
    for new in ("P3", "P0"):
        st["ec_flushing"] = True
        c._record_phase(room, 1, st, "P2", new, Clock.now(), "test")
        assert st["ec_flushing"] is False


def test_the_episode_survives_a_restart_and_an_old_file_loads_without_it(rig):  # noqa: F811
    c, _fake, room = rig
    room.state[1]["ec_flushing"] = True
    saved = json.loads(json.dumps(c._serialize_zone(room.state[1])))
    assert c._apply_saved_zone(c._fresh_zone(), saved)["ec_flushing"] is True
    old = {k: v for k, v in saved.items() if k != "ec_flushing"}
    assert c._apply_saved_zone(c._fresh_zone(), old)["ec_flushing"] is False
    assert c._apply_saved_zone(c._fresh_zone(), dict(old, ec_flushing="yes"))["ec_flushing"] is False


# ---------------------------------------------------------------- the daily setpoint limit
LIMIT = "number.crop_steering_setpoint_max_step_per_day"
SCOPE = "select.crop_steering_setpoint_step_limit_applies_to"


@pytest.mark.parametrize("limit, fc, target, thr", [
    (None, 61.9, 59.9, 48.8),  # no such number (an older integration): one point, as before
    ("1", 61.9, 59.9, 48.8),
    ("3", 63.9, 61.9, 50.8),
    ("0", 73.4, 73.4, 60.3),  # no limit: the whole way to the highest readings
])
def test_the_follower_moves_as_far_as_the_rooms_limit(rig, limit, fc, target, thr):  # noqa: F811
    c, fake, room = rig
    now = Clock.instant = Clock(2026, 9, 23, 14, 0)
    _room(fake, room, now)
    if limit is not None:
        fake.set_state(LIMIT, limit)
    _ladder(fake, 1, 60.9, 58.9, 47.8, 35.3)
    _peaks(room, 1, 50.0, 73.4)
    c._loop_room(room, now)
    assert _writes(fake, 1) == {"field_capacity": [fc], "p1_target_vwc": [target], "p2_vwc_threshold": [thr],
                                "p3_emergency_vwc_threshold": []}


def test_the_limit_holds_the_learner_and_the_ai_only_when_the_room_chooses(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.instant = Clock(2026, 9, 23, 14, 0)
    fake.set_state(LIMIT, "2")
    assert c._step_allowance(room, 1, "p2_vwc_threshold", now) is None  # the follower only, as before
    assert c._step_bounded(room, 1, "p2_vwc_threshold", 45.0, 52.0, now) == 52.0
    fake.set_state(SCOPE, phase_options.STEP_SCOPE_ALL)
    assert c._step_allowance(room, 1, "p2_vwc_threshold", now) == 2.0
    assert c._step_bounded(room, 1, "p2_vwc_threshold", 45.0, 52.0, now) == 47.0
    assert c._step_bounded(room, 1, "p2_shot_size", 5.0, 9.0, now) == 9.0  # not a ladder setpoint
    c._step_count(room, 1, "p2_vwc_threshold", 45.0, 46.5, now)
    assert c._step_allowance(room, 1, "p2_vwc_threshold", now) == 0.5  # one ledger, whoever writes
    assert c._step_bounded(room, 1, "p2_vwc_threshold", 46.5, 46.0, now) == 46.0
    c._step_count(room, 1, "p2_vwc_threshold", 46.5, 46.0, now)
    assert c._step_bounded(room, 1, "p2_vwc_threshold", 46.0, 50.0, now) is None  # nothing left today
    later = now + timedelta(days=1)
    assert c._step_allowance(room, 1, "p2_vwc_threshold", later) == 2.0  # a new grow-day starts afresh
    fake.set_state(LIMIT, "0")
    assert math.isinf(c._step_allowance(room, 1, "field_capacity", later))


# ---------------------------------------------------------------- the AI dawn judge keeps the minimum wait
def test_the_ai_cannot_start_the_ramp_inside_the_minimum_wait(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.now()
    fake.set_state("number.crop_steering_zone_1_p0_minimum_wait", "60")
    room.state[1].update(phase="P0", last_phase_change=now - timedelta(minutes=20))
    probe(fake, 1, 60.0)
    p = c._params(room, 1)
    snap = c._snapshot(room, 1, now, True, False)[0]

    class Advance:
        value, judge, why = "P1", "dawn", "the plants are drinking"

    assert snap is not None and brain_bridge.advance(c, room, 1, snap, Advance, now, p) is snap
    assert room.state[1]["phase"] == "P0"
    room.state[1]["last_phase_change"] = now - timedelta(minutes=61)
    snap = c._snapshot(room, 1, now, True, False)[0]
    brain_bridge.advance(c, room, 1, snap, Advance, now, p)
    assert room.state[1]["phase"] == "P1"
    assert controller.FC_STEP_MAX == 1.0  # the fallback when the room's limit cannot be read


def test_the_vitals_say_when_the_next_timed_shot_comes():
    from datetime import datetime

    conditions = [{"rule": "p2_timed", "shot": True, "to": None, "in_min": 40, "size": 3.0},
                  {"rule": "lights_off", "shot": False, "to": "P3", "in_min": 300}]
    assert controller.next_text(conditions, datetime(2026, 9, 23, 14, 0)) == "timed shot at 14:40 · P3 by 19:00"
