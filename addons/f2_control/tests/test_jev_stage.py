"""The owner's doctrine in every judge, the stage arc in every judge's evidence, and the daily Stage judge."""
from datetime import timedelta
from types import SimpleNamespace

import brain_bridge
import jev_kit as K
from brain.doctrine import stage_intent
from brain.judges.dawn import DawnJudge
from brain.judges.dusk import DuskJudge
from brain.judges.night import NightJudge
from brain.judges.probe import MODES, ProbeJudge
from brain.judges.ramp import RampJudge
from brain.judges.salt import MODE, SaltJudge
from brain.judges.shot import ShotJudge
from brain.judges.stage import StageJudge
from brain.judges.zones import ZonesJudge

ALL = [DawnJudge(), RampJudge(), SaltJudge(), DuskJudge(), ProbeJudge(), ShotJudge(), NightJudge(), ZonesJudge(),
       StageJudge()]


def _bulk(**over):
    """Flower day 37 of 56: flower bulk, where the owner's arc steers vegetative."""
    base = dict(flower_day=37, flower_days=56, stage=stage_intent(37), steering="vegetative")
    base.update(over)
    return base


def test_every_judge_asks_with_the_owners_doctrine():
    for judge in ALL:
        for name, variants in judge.questions.items():
            assert len(variants) == 2, (judge.name, name)  # the council
            for v in variants:
                assert "Doctrine:" in v["instructions"], (judge.name, name)


def test_every_judge_sees_the_stage_and_the_steering_mode():
    c = K.ctx(**_bulk())
    e = RampJudge().evidence(K.ctx("P1", s=K.snap(phase="P1", shot_count=2), **_bulk()))
    assert "flower bulk" in e["stage_today"] and "vegetative" in e["stage_today"]
    assert e["operator_steering_mode"] == "vegetative"
    assert K.ctx().stage is None and "not known" in DuskJudge().evidence(K.ctx(s=K.snap(hours_to_lights_off=2)))["stage_today"]
    assert c.since_lights_min >= 0


def test_the_ramp_hands_over_on_real_salt_because_maintenance_flushes_it():
    from brain import council
    answers = K.both("ramp_state", K.choice_answer("real_salt", {"real_salt": 0.8}))
    verdicts = {"ramp_state": council.combine(answers, "ramp_state")}
    d = RampJudge().decide(verdicts, K.ctx("P1", s=K.snap(phase="P1", vwc=39.5, shot_count=3)))
    assert (d.kind, d.value) == ("advance", "P2")


def test_salt_holds_below_its_band_in_a_vegetative_stage():
    assert MODE["below_band_vegetative"] == "hold"
    h = K.history([(m, 36.0, 3.0) for m in range(0, 400)])
    e = SaltJudge().evidence(K.ctx(s=K.snap(ec=3.0, ec_settled=3.0), h=h, **_bulk()))
    assert "below it" in e["stage_ec_band"] and "3.5-6" in e["stage_ec_band"]


def test_the_probe_judge_knows_a_temperature_artefact():
    assert "temperature_artefact" in MODES
    e = ProbeJudge().evidence(K.ctx(h=K.history(shots=[(100, 200, 30, 3, "p2_topup"), (50, 200, 31, 3, "p2_topup")])))
    assert "minutes_since_the_lights_switched" in e


def test_the_flower_start_option_names_rooms_or_all_of_them():
    assert brain_bridge.flower_option("input_datetime.flip") == {"*": "input_datetime.flip"}
    assert brain_bridge.flower_option("default=input_datetime.flip_date, room_b=2026-07-12") == {
        "default": "input_datetime.flip_date", "room_b": "2026-07-12"}
    assert brain_bridge.flower_option("") == {}


def test_the_flower_day_comes_from_the_rooms_entity_or_date():
    now = K.NOW  # 27 Sep 2026
    c = SimpleNamespace(jev=SimpleNamespace(flower_start={"default": "input_datetime.flip_date", "room_b": "2026-07-12"}),
                        _jev_read=lambda e: {"input_datetime.flip_date": "2026-08-22"}.get(e))
    assert brain_bridge.flower_day(c, SimpleNamespace(slug="default"), now) == 37
    assert brain_bridge.flower_day(c, SimpleNamespace(slug="room_b"), now) == 78
    assert brain_bridge.flower_day(c, SimpleNamespace(slug="veg"), now) is None
    c.jev.flower_start = {"default": "input_datetime.missing"}
    assert brain_bridge.flower_day(c, SimpleNamespace(slug="default"), now) is None


# ------------------------------------------------------------------ the Stage judge
def _stage_ctx(steering="generative", ec=4.4, **over):
    # lights on at 10:00 (3 h ago), off at 22:00; last night's readings drop 4 points
    pts = []
    for m in range(0, 26 * 60, 10):
        t = K.NOW - timedelta(minutes=m)
        v = 36.0 if t.hour >= 10 and t.date() == K.NOW.date() else (38.0 if 12 <= t.hour < 22 else 34.0)
        pts.append((m, v, ec))
    s = K.snap(ec=ec, ec_settled=ec)
    return K.ctx(s=s, h=K.history(pts), hours_to_on=21.0, hours_to_off=9.0, **_bulk(steering=steering), **over)


def test_the_stage_judge_asks_once_a_grow_day_when_the_stage_is_known():
    j = StageJudge()
    assert j.due(_stage_ctx(), None)
    assert not j.due(_stage_ctx(), K.NOW - timedelta(hours=2))
    assert not j.due(K.ctx(), None)  # no flower day: no stage
    e = j.evidence(_stage_ctx())
    assert "calls for vegetative steering" in e["stage_steering_vs_operator"]
    assert "generative" in e["stage_steering_vs_operator"]
    assert "last_night_dryback" in e and "settled_pore_ec_vs_stage_band" in e


def test_the_stage_judge_advises_and_never_acts_on_water():
    from brain import council
    j = StageJudge()
    ctx = _stage_ctx()
    on_arc = {"arc": council.combine(K.both("arc", K.choice_answer("on_arc", {"on_arc": 0.9})), "arc")}
    # code finds the steering mismatch itself (generative steering in flower bulk), whatever the AI assistant says
    d = j.decide(on_arc, ctx)
    assert d.kind == "alert" and d.value["code"] == "CS-705"
    assert "uses generative steering, but the stage needs vegetative" in d.value["message"]
    assert "flower day 37" in d.value["message"] and "changed nothing" in d.value["message"]
    matched = _stage_ctx(steering="vegetative")
    assert j.decide(on_arc, matched) is None  # steering right, the AI assistant content: nothing to say
    firm = {"arc": council.combine(K.both("arc", K.choice_answer("ec_above_band", {"ec_above_band": 0.8})), "arc")}
    assert "AI assistant: The settled pore EC sits above" in j.decide(firm, matched).value["message"]
    split = {"arc": council.combine(K.both("arc", K.choice_answer("ec_above_band", {"ec_above_band": 0.9}),
                                           K.choice_answer("on_arc", {"on_arc": 0.9})), "arc")}
    assert j.decide(split, matched) is None


# ------------------------------------------------------------------ the council on actions, and vegetative dusk
def test_answers_that_mean_the_same_action_add_up():
    from brain import council
    split = K.both("q", K.choice_answer("slab_full", {"slab_full": 0.34, "ec_is_feed_front": 0.33, "keep_ramping": 0.33}),
                   K.choice_answer("ec_is_feed_front", {"slab_full": 0.3, "ec_is_feed_front": 0.4, "keep_ramping": 0.3}))
    v = council.combine(split, "q")
    assert not v.firm(0.6)  # neither label alone
    assert v.firm_in(("slab_full", "ec_is_feed_front"), 0.6)  # but both mean hand over
    mixed = K.both("q", K.choice_answer("slab_full", {"slab_full": 0.9}), K.choice_answer("keep_ramping", {"keep_ramping": 0.9}))
    assert not council.combine(mixed, "q").firm_in(("slab_full", "ec_is_feed_front"), 0.1)


def test_a_vegetative_zone_is_never_stopped_early():
    from brain.envelope import Directive, admit
    c = K.ctx(s=K.snap(hours_to_lights_off=2.0, vwc=36.0), hours_to_off=2.0, **_bulk())
    d = Directive("dusk", "advance", "P3", "why", K.NOW + timedelta(minutes=10))
    ok, why = admit(d, c)
    assert not ok and "vegetative" in why
    gen = K.ctx(s=K.snap(hours_to_lights_off=2.0, vwc=36.0), hours_to_off=2.0, **_bulk(steering="generative"))
    assert admit(d, gen)[0]  # the operator's generative choice is theirs to make
    assert not DuskJudge().due(c, None)  # and Dusk is not even asked
