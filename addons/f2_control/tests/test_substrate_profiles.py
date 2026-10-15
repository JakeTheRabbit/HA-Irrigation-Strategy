"""The controller runs each room on its substrate profile, and a generic room (every upgraded room) on
exactly the numbers it used before the pack: the engine's EC settle, P1 rise, P0 flush and shot
scaling, the Auto setpoints shift, and the learner's and its judge's bounds."""
import dataclasses
from datetime import datetime, timedelta

import auto_setpoints
import controller
import curve_tracker as ct
import jev_policy
import setpoint_supervisor as ss
from crop_steering_engine import ZoneParams
from crop_steering_engine.defaults import SUBSTRATE_PROFILES
from test_substrate import _start

ENGINE_KEYS = ("ec_settle_min", "p1_rise_pts", "p0_ec_flush_ratio", "p0_ec_flush_shot",
               "ec_adjust_up", "ec_adjust_down")


def _engine_part(p):
    return {k: getattr(p, k) for k in ENGINE_KEYS}


def test_a_generic_room_gets_the_engine_it_had():
    c, _fake = _start()
    got = _engine_part(c._params(c.rooms[0], 1))
    assert got == {k: SUBSTRATE_PROFILES["generic"][k] for k in ENGINE_KEYS}
    # ...which is what a ZoneParams built without them (an older controller) gets
    assert got == {f.name: f.default for f in dataclasses.fields(ZoneParams) if f.name in ENGINE_KEYS}


def test_a_coco_room_gets_the_coco_profile_and_a_change_follows_at_once():
    c, fake = _start(substrate="coco")
    room = c.rooms[0]
    assert _engine_part(c._params(room, 1)) == {k: SUBSTRATE_PROFILES["coco"][k] for k in ENGINE_KEYS}
    attrs = fake.states["sensor.crop_steering_engine_config"][1]
    fake.set_state("sensor.crop_steering_engine_config", "ok", {**attrs, "substrate": "generic"})
    c._apply_setup_descriptors()
    assert _engine_part(c._params(room, 1)) == {k: SUBSTRATE_PROFILES["generic"][k] for k in ENGINE_KEYS}


def test_the_settled_reading_waits_for_the_rooms_settle_time():
    c, _fake = _start()
    now = datetime(2026, 10, 1, 12, 0)
    st = {"last_shot": now - timedelta(minutes=50), "ec_settled": 4.0}
    assert c._settled_ec(dict(st), 6.0, now) == 6.0  # generic: 45 min
    assert c._settled_ec(dict(st), 6.0, now, SUBSTRATE_PROFILES["coco"]["ec_settle_min"]) == 4.0  # coco: 60, held


def test_generic_keeps_the_learner_and_judge_bounds_it_had():
    assert controller.FC_SHIFT_MIN == 1.0
    assert auto_setpoints.JEV_SHOT_RANGE == (1.0, 4.0)
    assert auto_setpoints.JEV_PEAK_ADJ_RANGE == (-2.0, 2.0)
    assert ss.ADDITIONAL_DRYBACK_PCT == 3.0 and ss.P2_SHOT_RANGE == (1.0, 4.0) and ss.PEAK_ADJ_RANGE == (-2.0, 2.0)
    assert jev_policy.EC_STEP == {0: 1.0, 1: 0.5, 2: 0.0, 3: -0.5, 4: -1.0}
    assert jev_policy.PEAK_STEP == {"lower_peak": -0.5, "keep": 0.0, "raise_peak": 0.5}
    assert ct.ATHENA == {
        "veg": ct.Recipe(1.0, 25.0, 60, 3.0, 20, 3.0, (3.0, 5.0)),
        "stretch": ct.Recipe(0.0, 45.0, 90, 3.0, 20, 1.5, (4.0, 10.0)),
        "bulk": ct.Recipe(1.0, 35.0, 60, 4.0, 20, 3.0, (3.5, 6.0)),
        "finish": ct.Recipe(1.0, 45.0, 90, 3.0, 20, 3.0, (3.0, 4.0)),
    }


def test_the_judge_steers_within_the_rooms_learner_bounds():
    narrow = {**SUBSTRATE_PROFILES["generic"]["learner"], "p2_shot_range": (1.0, 2.5), "ec_step": (2.0,) * 5}
    answers = {"ec_steer": {"score": 0, "confidence": 0.9}}
    assert jev_policy.verdicts(answers)["p2_shot_delta"] == 1.0
    verdict = jev_policy.verdicts(answers, learner=narrow)
    assert verdict["p2_shot_delta"] == 2.0
    learn = auto_setpoints.fresh()
    learn["day"] = "2026-10-01"
    assert auto_setpoints.jev_verdict(dict(learn, jev=dict(learn["jev"])), "h", verdict, 2.0, "12:00") == {
        "p2_shot_size": 4.0}
    assert auto_setpoints.jev_verdict(learn, "h", verdict, 2.0, "12:00", narrow) == {"p2_shot_size": 2.5}


def test_the_stage_map_names_each_recipe_stage():
    assert ct.stage("Veg") == ("veg", False)
    assert ct.stage("Transition") == ("stretch", True)
    assert ct.stage("Ripen", "coco") == ("finish", True)
    assert ct.stage("Custom") == (None, None)
    assert ct.curve("rockwool")["veg"].dryback_pct == SUBSTRATE_PROFILES["rockwool"]["curve"]["veg"][1]
    assert ct.curve("peat") == ct.ATHENA
