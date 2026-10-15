"""What the controller publishes for the simplified dashboard: outcomes tied to their decision in words, Jev's
setpoint ranges per zone, a call count that survives restarts, and no Pore EC question while stacking is off."""
import json
from datetime import timedelta
from types import SimpleNamespace

import jev_bridge
import jev_kit as K
from jev.brain import Brain
from jev.client import Asker
from jev.journal import Journal, label_words
from jev.judges.ramp import RampJudge
from jev.judges.salt import SaltJudge
from jev.judges.setpoints import SetpointsJudge
from jev.ledger import Ledger
from jev.setpoint_memory import SetpointMemory


def test_the_pore_ec_judge_is_not_asked_while_ec_stacking_is_off():
    s = K.snap(ec_settled=4.4)
    assert SaltJudge().due(K.ctx("P2", s=s, p=K.params(stacking_on=True)), None)
    assert not SaltJudge().due(K.ctx("P2", s=s, p=K.params(stacking_on=False)), None)


def test_an_outcome_names_its_decision_in_words(tmp_path):
    answer = K.choice_answer("ec_is_feed_front", {"ec_is_feed_front": 0.8, "real_salt": 0.2})
    asker = Asker("a", "t", transport=K.FakeTransport(K.both("ramp_state", answer)), threaded=False,
                  clock=lambda: K.NOW.timestamp())
    brain = Brain(asker, Ledger(str(tmp_path / "l.jsonl")), [RampJudge()], log=lambda *a: None)
    brain.journal = Journal(None)
    h = K.history(points=[(m, 38.0, 5.4) for m in range(0, 90)],
                  shots=[(60, 120, 36.0, 5.0, "p1_ramp"), (35, 120, 37.8, 5.2, "p1_ramp")])
    brain.tick(K.ctx("P1", s=K.snap(phase="P1", vwc=39.2, shot_count=3, ec=5.6, ec_settled=5.6), h=h))
    decision = brain.journal.recent("default")[0]
    brain.tick(K.ctx("P2", s=K.snap(phase="P2", vwc=38.5), now=K.NOW + timedelta(minutes=61)))
    outcome = brain.journal.recent("default")[0]
    assert outcome["kind"] == "outcome" and outcome["of"] == decision["t"]
    assert outcome["verdict"] == "hand over to maintenance"


def test_labels_read_as_actions():
    assert label_words("ec_mode", "hold") == "hold the EC steer"
    assert label_words("advance", "P3") == "end the day's watering"
    assert label_words("setpoint", "smaller_shots") == "smaller shots"
    assert label_words("alert", "CS-702") == "CS-702"


def test_the_days_call_count_survives_a_restart(tmp_path):
    path = str(tmp_path / "usage.json")
    today = K.NOW.date().isoformat()
    brain = SimpleNamespace(usage_path=path, asker=Asker("a", "t", threaded=False, clock=lambda: K.NOW.timestamp()))
    brain.asker.stats.update(day=today, calls=13, input_tokens=35582, errors=1, last_error="timeout")
    jev_bridge.save_usage(brain)
    again = Asker("a", "t", threaded=False, clock=lambda: K.NOW.timestamp())
    jev_bridge.restore_usage(again, path)
    assert (again.stats["calls"], again.stats["input_tokens"], again.stats["errors"]) == (13, 35582, 1)
    tomorrow = Asker("a", "t", threaded=False, clock=lambda: (K.NOW + timedelta(days=1)).timestamp())
    jev_bridge.restore_usage(tomorrow, path)
    assert tomorrow.stats["calls"] == 0  # yesterday's count is not today's
    with open(path, encoding="utf-8") as fh:
        assert json.load(fh)["day"] == today


def test_each_zone_publishes_jevs_setpoint_range(tmp_path):
    asker = Asker("a", "t", transport=K.FakeTransport({}), threaded=False)
    brain = Brain(asker, Ledger(None), [RampJudge(), SetpointsJudge()], log=lambda *a: None)
    brain.journal, brain.setpoints = Journal(None), SetpointMemory(None)
    brain.flower_start, brain.flower_days = {}, 56
    brain.setpoints.zone("default", 1)["home"].update({"p2_shot_size": 5.0, "p2_vwc_threshold": 30.5})
    brain.setpoints.zone("default", 1)["last"] = {"at": "2026-09-28T22:31:00", "words": "P2 shot 5% -> 4.5%",
                                                  "reverted": False}
    c = SimpleNamespace(jev=brain, _jev_read=lambda e: None, _on=lambda e, d=False: True)
    p = K.params(p2_shot_size=4.5, p2_threshold=30.5, p3_emergency_floor=20.7, p1_target=36.5, field_capacity=40.0)
    room = SimpleNamespace(slug="default", prefix="", zones={1: {}}, state={1: {"ec_offset": 0.0}},
                           strategy_required=False, _jev_params={1: p})
    out = {}
    jev_bridge.publish(c, room, K.NOW, lambda eid, state, attrs: out.__setitem__(eid, attrs))
    sp = out["sensor.crop_steering_zone_1_jev"]["setpoints"]
    assert sp["managed"] is True and sp["home"] == {"p2_shot_size": 5.0, "p2_vwc_threshold": 30.5}
    assert sp["current"] == {"p2_shot_size": 4.5, "p2_vwc_threshold": 30.5}
    assert sp["range"] == {"p2_shot_size": [4.0, 6.0], "p2_vwc_threshold": [28.5, 31.5]}
    assert sp["last"] == "2026-09-28 22:31: P2 shot 5% -> 4.5%" and sp["paused_until"] is None
