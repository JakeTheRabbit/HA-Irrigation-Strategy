"""Jev as the judge behind the setpoint supervisor: typed answers -> small bounded nudges, always fail open."""
import json
import os

import jev_policy as jp


def _answers(ec_level=2, ec_conf=0.9, peak="keep", peak_conf=0.9, trust=0.92, fail=0.04):
    return {
        "ec_steer": {"type": "score", "score": float(ec_level), "confidence": ec_conf},
        "peak_fit": {"type": "choice", "choice": peak, "confidence": peak_conf},
        "probe_trust": {"type": "noul", "noul": trust},
        "delivery_failure": {"type": "noul", "noul": fail},
    }


def test_the_questions_carry_the_doctrine_and_offer_a_way_out():
    q = jp.QUESTIONS
    assert set(q) == {"ec_steer", "peak_fit", "probe_trust", "delivery_failure"}
    assert len(q["ec_steer"]["criteria"]) == 5 and "runoff" in q["ec_steer"]["instructions"]
    assert set(q["peak_fit"]["criteria"]) == set(jp.PEAK_STEP) | {"insufficient_evidence"}


def test_ec_verdict_moves_the_p2_shot_the_right_way():
    assert jp.verdicts(_answers(ec_level=0))["p2_shot_delta"] == 1.0  # far above range: flush hard, bigger shots
    assert jp.verdicts(_answers(ec_level=1))["p2_shot_delta"] == 0.5
    assert jp.verdicts(_answers(ec_level=2))["p2_shot_delta"] == 0.0
    assert jp.verdicts(_answers(ec_level=4))["p2_shot_delta"] == -1.0  # far below range: stack, smaller shots
    assert jp.verdicts(_answers(ec_level=0.6))["p2_shot_delta"] == 0.5  # scores land between levels


def test_peak_verdict_nudges_the_target_half_a_point():
    assert jp.verdicts(_answers(peak="lower_peak"))["peak_delta"] == -0.5
    assert jp.verdicts(_answers(peak="raise_peak"))["peak_delta"] == 0.5
    assert jp.verdicts(_answers(peak="insufficient_evidence"))["peak_delta"] == 0.0


def test_an_unsure_jev_moves_nothing():
    v = jp.verdicts(_answers(ec_level=0, ec_conf=0.55, peak="lower_peak", peak_conf=0.6))
    assert v == {"freeze": None, "p2_shot_delta": 0.0, "peak_delta": 0.0, "why": []}


def test_guards_outrank_every_nudge():
    v = jp.verdicts(_answers(ec_level=0, fail=0.91))
    assert v["freeze"] and "delivery" in v["freeze"] and v["p2_shot_delta"] == 0.0
    assert "probe trust" in jp.verdicts(_answers(trust=0.2))["freeze"]


def test_anything_unusable_is_none_so_the_arithmetic_carries_on_alone():
    assert jp.verdicts(None) is None
    assert jp.parse({"success": False, "errors": [{"code": 10000}], "result": None}) is None
    assert jp.parse("not json") is None


def test_call_fails_open_and_sends_the_documented_request(monkeypatch):
    seen = {}

    class Resp:
        status_code = 200

        def json(self):
            return {"result": {"result": {"answers": _answers()}}, "success": True}

    def post(url, **kw):
        seen.update(url=url, **kw)
        return Resp()

    monkeypatch.setattr(jp.requests, "post", post)
    a = jp.call("acc123", "tok", {"pore_ec": "5.2"}, gateway="crop-steering")
    assert a["peak_fit"]["choice"] == "keep"
    assert seen["url"].endswith("/accounts/acc123/ai/run") and seen["json"]["model"] == "typesafe/jev"
    assert seen["json"]["input"] == {"state": {"pore_ec": "5.2"}, "questions": jp.QUESTIONS}
    assert seen["headers"]["cf-aig-gateway-id"] == "crop-steering"

    def boom(url, **kw):
        raise jp.requests.ConnectionError("no route")

    monkeypatch.setattr(jp.requests, "post", boom)
    assert jp.call("acc123", "tok", {}) is None


def test_recorded_live_responses_parse_into_verdicts():
    path = os.path.join(os.path.dirname(__file__), "fixtures", "jev_supervisor_recorded.json")
    if not os.path.exists(path):  # recorded by the live twin run; absent on a fresh checkout until then
        return
    with open(path, encoding="utf-8") as fh:
        rec = json.load(fh)
    assert rec
    for r in rec:
        v = jp.verdicts(jp.parse(r["response"]))
        assert v is not None and v["p2_shot_delta"] in jp.EC_STEP.values() and v["peak_delta"] in jp.PEAK_STEP.values()
