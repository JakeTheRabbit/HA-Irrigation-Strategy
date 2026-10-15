"""The Jev runtime: the council, the background asker, the envelope, the ledger and the brain."""
import os
from datetime import timedelta

import jev_kit as K
import pytest
from jev import council
from jev.brain import Brain
from jev.client import Asker, parse
from jev.envelope import Directive, admit
from jev.judges.probe import ProbeJudge
from jev.judges.ramp import RampJudge
from jev.ledger import Ledger


# ------------------------------------------------------------------ council
def test_two_phrasings_that_agree_are_firm():
    v = council.combine(K.both("q", K.choice_answer("a", {"a": 0.8, "b": 0.2})), "q")
    assert v.label == "a" and v.agreed and v.n == 2 and v.firm(0.6)


def test_two_phrasings_that_disagree_never_act():
    answers = K.both("q", K.choice_answer("a", {"a": 0.9, "b": 0.1}), K.choice_answer("b", {"a": 0.3, "b": 0.7}))
    v = council.combine(answers, "q")
    assert v.label == "a" and not v.agreed and not v.firm(0.5)


def test_one_phrasing_alone_is_never_firm():
    v = council.combine({"q__v0": K.choice_answer("a", {"a": 0.95})}, "q")
    assert v.n == 1 and not v.firm(0.5)


def test_noul_and_score_combine():
    v = council.combine(K.both("t", K.noul_answer(0.1), K.noul_answer(0.2)), "t")
    assert v.label is False and v.agreed and abs(v.prob - 0.85) < 1e-9
    s = council.combine(K.both("s", K.score_answer(2.4, {"2": 0.6, "3": 0.4}), K.score_answer(1.8, {"2": 0.7, "1": 0.3})), "s")
    assert s.label == 2 and s.agreed and abs(s.value - 2.1) < 1e-9


def test_a_malformed_answer_is_no_verdict():
    assert council.combine({"q__v0": {"type": "choice", "probabilities": "junk"}}, "q") is None
    assert council.combine({}, "q") is None


# ------------------------------------------------------------------ asker
def test_parse_reads_cloudflares_envelope():
    answers, usage = parse({"result": {"result": {"answers": {"q": {}}, "usage": {"input_tokens": 5}}}})
    assert answers == {"q": {}} and usage == {"input_tokens": 5}
    assert parse({"result": {"answers": {}}}) == (None, None)


def test_the_asker_is_off_without_credentials_and_never_calls():
    t = K.FakeTransport({})
    a = Asker("", "", transport=t, threaded=False)
    assert not a.enabled and a.submit("k", {}, {}) is False and t.calls == []


def test_the_asker_stores_answers_and_counts_the_budget():
    t = K.FakeTransport({"q__v0": K.noul_answer(0.9)})
    a = Asker("acct", "tok", transport=t, threaded=False, daily_budget=1)
    assert a.submit("k", {"x": 1}, {"q__v0": {}}) is True
    assert a.result("k").answers["q__v0"]["noul"] == 0.9 and a.stats["input_tokens"] == 900
    assert a.submit("k2", {}, {}) is False  # budget spent


def test_a_failing_jev_leaves_no_answer_and_says_why():
    a = Asker("acct", "tok", transport=K.FakeTransport(error="HTTP 500: boom"), threaded=False)
    assert a.submit("k", {}, {}) is True
    assert a.result("k") is None and a.stats["errors"] == 1 and "500" in a.stats["last_error"]


# ------------------------------------------------------------------ envelope
def _d(kind, value, ctx):
    return Directive("t", kind, value, "why", ctx.now + timedelta(minutes=10))


def test_a_phase_only_goes_forward_one_step():
    c = K.ctx("P1", s=K.snap(phase="P1", vwc=39.0, shot_count=3))
    assert admit(_d("advance", "P2", c), c)[0]
    assert not admit(_d("advance", "P3", c), c)[0]
    assert not admit(_d("advance", "P0", c), c)[0]


def test_p1_hands_over_only_near_the_ceiling_with_the_minimum_shots():
    p = K.params(p1_target=40.0, field_capacity=42.0, p1_min_shots=2)
    low = K.ctx("P1", s=K.snap(phase="P1", vwc=35.0, shot_count=3), p=p)
    few = K.ctx("P1", s=K.snap(phase="P1", vwc=39.5, shot_count=1), p=p)
    assert not admit(_d("advance", "P2", low), low)[0]
    assert not admit(_d("advance", "P2", few), few)[0]


def test_p3_early_only_in_the_last_three_hours_and_above_the_floor():
    early = K.ctx("P2", s=K.snap(hours_to_lights_off=5.0, vwc=34.0))
    close = K.ctx("P2", s=K.snap(hours_to_lights_off=2.0, vwc=27.0), p=K.params(p3_emergency_floor=25.0))
    ok = K.ctx("P2", s=K.snap(hours_to_lights_off=2.0, vwc=34.0))
    assert not admit(_d("advance", "P3", early), early)[0]
    assert not admit(_d("advance", "P3", close), close)[0]
    assert admit(_d("advance", "P3", ok), ok)[0]


def test_p0_waits_for_half_the_dryback_or_a_quarter_of_the_wait():
    c = K.ctx("P0", s=K.snap(phase="P0", dryback_pct=4.0, phase_minutes=10.0), p=K.params(dryback_target=20.0))
    assert not admit(_d("advance", "P1", c), c)[0]
    c2 = K.ctx("P0", s=K.snap(phase="P0", dryback_pct=11.0, phase_minutes=10.0))
    assert admit(_d("advance", "P1", c2), c2)[0]


def test_nothing_moves_at_night_or_without_a_probe_or_once_expired():
    night = K.ctx("P2", lights_on=False, s=K.snap(hours_to_lights_off=1.0))
    blind = K.ctx("P2", s=None, hours_to_off=1.0)
    assert not admit(_d("advance", "P3", night), night)[0]
    assert not admit(_d("advance", "P3", blind), blind)[0]
    c = K.ctx("P1", s=K.snap(phase="P1", vwc=39.0, shot_count=3))
    stale = Directive("t", "advance", "P2", "why", c.now - timedelta(minutes=1))
    assert admit(stale, c) == (False, "expired")


def test_a_probe_is_set_aside_only_twice_in_a_row_and_confirmed_by_code():
    c = K.ctx()
    d = _d("distrust", "stuck", c)
    assert not admit(d, c, confirmed=1, evidence_ok=True)[0]
    assert not admit(d, c, confirmed=2, evidence_ok=False)[0]
    assert admit(d, c, confirmed=2, evidence_ok=True)[0]


# ------------------------------------------------------------------ ledger
def test_the_ledger_survives_a_restart_and_gives_a_track_record(tmp_path):
    path = str(tmp_path / "ledger.jsonl")
    led = Ledger(path)
    i = led.record("ramp", "default", 1, "P2", "advance", check_at=K.NOW, check={"vwc": 38.0})
    assert [e["id"] for e in led.due(K.NOW)] == [i]
    led.resolve(i, "VWC held", True)
    again = Ledger(path)
    assert again.due(K.NOW) == []
    assert again.track("ramp", "default", 1) == "your last 1 call(s) of this kind worked 1 time(s): VWC held"


# ------------------------------------------------------------------ brain + ramp
def _ramp_ctx(now=K.NOW):
    h = K.history(points=[(m, 38.0 + (0.1 if m < 20 else 0), 5.4) for m in range(0, 90, 1)],
                  shots=[(60, 120, 36.0, 5.0, "p1_ramp"), (35, 120, 37.8, 5.2, "p1_ramp")])
    s = K.snap(phase="P1", vwc=39.2, shot_count=3, minutes_since_shot=25.0, ec=5.6, ec_settled=5.6)
    return K.ctx("P1", s=s, h=h, now=now)


def test_the_brain_asks_in_the_background_and_hands_over_the_ramp(tmp_path):
    t = K.FakeTransport(K.both("ramp_state", K.choice_answer("ec_is_feed_front", {"ec_is_feed_front": 0.8, "real_salt": 0.2})))
    asker = Asker("acct", "tok", transport=t, threaded=False, clock=lambda: K.NOW.timestamp())
    brain = Brain(asker, Ledger(str(tmp_path / "l.jsonl")), [RampJudge()], log=lambda *a: None)
    out = brain.tick(_ramp_ctx())
    assert [(d.kind, d.value) for d, _ in out] == [("advance", "P2")]
    asked = t.calls[0]
    assert set(asked["questions"]) == {"ramp_state__v0", "ramp_state__v1"}
    assert "ramp_ceiling" in asked["state"] and "ramp_shot_responses" in asked["state"]
    assert len(brain.ledger.entries) == 1  # recorded once
    brain.tick(_ramp_ctx())
    assert len(brain.ledger.entries) == 1  # the same answer is not recorded twice
    status = brain.zone_status("default", 1)["ramp"]
    assert status["directive"] == "advance P2" and status["verdicts"]["ramp_state"]["agreed"] is True


def test_with_jev_off_or_failing_the_brain_does_nothing(tmp_path):
    for asker in (Asker("", "", threaded=False),
                  Asker("a", "t", transport=K.FakeTransport(error="timeout"), threaded=False)):
        brain = Brain(asker, Ledger(None), [RampJudge(), ProbeJudge()], log=lambda *a: None)
        assert brain.tick(_ramp_ctx()) == []


def test_a_judge_that_raises_is_skipped_not_fatal():
    class Broken(RampJudge):
        def evidence(self, ctx):
            raise ValueError("bad")

    asker = Asker("a", "t", transport=K.FakeTransport({}), threaded=False)
    brain = Brain(asker, Ledger(None), [Broken()], log=lambda *a: None)
    assert brain.tick(_ramp_ctx()) == [] and "bad" in brain.errors["ramp"]


# ------------------------------------------------------------------ probe
def test_code_confirms_a_dead_probe_from_its_shots_and_a_sibling():
    h = K.history(points=[(m, 30.0, 3.0) for m in range(0, 200)],
                  shots=[(120, 200, 30.0, 3.0, "p2_topup"), (60, 200, 30.0, 3.0, "p2_topup")])
    c = K.ctx(h=h, siblings={2: {"rise": 1.4, "rise_words": "retained +1.4"}})
    assert ProbeJudge().evidence_ok(c)
    c_no_sibling = K.ctx(h=h, siblings={2: {"rise": 0.1}})
    # still confirmed: flat for over an hour with water going in
    assert ProbeJudge().evidence_ok(c_no_sibling)


def test_a_moving_probe_is_not_confirmed_dead():
    h = K.history(points=[(m, 30.0 + (2.0 if m < 110 else 0) + (2.0 if m < 50 else 0) - m * 0.01, 3.0)
                          for m in range(0, 200)],
                  shots=[(120, 200, 30.0, 3.0, "p2_topup"), (60, 200, 31.2, 3.0, "p2_topup")])
    assert not ProbeJudge().evidence_ok(K.ctx(h=h, siblings={2: {"rise": 1.4}}))


# ------------------------------------------------------------------ TypeSafe direct
def test_typesafe_answers_are_read_from_the_top_level():
    from jev.client import parse_typesafe
    answers, usage = parse_typesafe({"model": "jev-1.13.0", "answers": {"q__v0": {"type": "noul", "noul": 0.7}},
                                     "usage": {"input_tokens": 327}})
    assert answers["q__v0"]["noul"] == 0.7 and usage["input_tokens"] == 327
    assert parse_typesafe({"result": {"result": {"answers": {"q": {}}}}}) == (None, None)
    assert parse_typesafe(None) == (None, None)


def test_every_route_jev_has_is_used_typesafe_first(tmp_path):
    import jev_bridge
    from jev.client import Routes, call, call_typesafe

    both = jev_bridge.build({"typesafe_api_key": "apikey_x"}, ("acct", "tok", ""), "/tmp/state.json", lambda *a: None)
    assert isinstance(both.asker.transport, Routes) and both.routes == ["TypeSafe", "Cloudflare"]
    assert [(r.fn, r.token) for r in both.asker.transport.routes] == [(call_typesafe, "apikey_x"), (call, "tok")]
    ran = str(tmp_path / "state.json")
    K.has_run(ran)  # Cloudflare alone starts Jev only where it has run before
    cf_only = jev_bridge.build({}, ("acct", "tok", ""), ran, lambda *a: None)
    assert cf_only.routes == ["Cloudflare"] and cf_only.asker.daily_budget == 5000
    assert jev_bridge.build({}, ("", "", ""), "/tmp/state.json", lambda *a: None) is None


def test_cloudflare_alone_starts_no_jev_where_jev_has_never_run(tmp_path):
    """An install updated from a line without Jev may have set Cloudflare for the Auto Setpoints check: no brain."""
    import jev_bridge

    said = []
    state = str(tmp_path / "state.json")
    assert jev_bridge.build({"jev_enabled": True}, ("acct", "tok", ""), state, said.append) is None
    assert "jev: off" in said[0] and str(tmp_path) in said[0] and "tok" not in said[0]
    assert os.listdir(tmp_path) == []  # nothing written, so the next start decides the same
    typesafe = jev_bridge.build({"typesafe_api_key": "apikey_x"}, ("", "", ""), state, said.append)
    assert typesafe.routes == ["TypeSafe"]  # only the Jev line has a TypeSafe key: it starts as before


@pytest.mark.parametrize("name", ["jev_usage.json", "jev_ledger.jsonl", "jev_journal.jsonl", "jev_setpoints.json"])
@pytest.mark.parametrize("content", [b"", b"\xff\x00 not json"], ids=["empty", "unreadable"])
def test_any_one_jev_file_in_the_state_folder_starts_jev_on_cloudflare_alone(tmp_path, name, content):
    import jev_bridge

    (tmp_path / name).write_bytes(content)
    brain = jev_bridge.build({}, ("acct", "tok", ""), str(tmp_path / "state.json"), lambda *a: None)
    assert brain is not None and brain.routes == ["Cloudflare"]
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    assert jev_bridge.build({}, ("acct", "tok", ""), str(elsewhere / "state.json"), lambda *a: None) is None


def test_an_old_options_file_keeps_its_budget_and_takes_the_new_defaults():
    import jev_bridge

    options_3_8_0 = {"typesafe_api_key": "apikey_x", "jev_enabled": True, "jev_judges": "all",
                "jev_daily_calls": 2000, "jev_flower_start": "", "jev_flower_days": 56}
    brain = jev_bridge.build(options_3_8_0, ("", "", ""), "/tmp/state.json", lambda *a: None)
    assert brain.routes == ["TypeSafe"] and brain.asker.daily_budget == 2000
    assert (brain.reask_max, brain.unsure_below, brain.strict_after, brain.strict_prob) == (2, 0.7, 3, 0.8)
    assert (brain.asker.warn_pct, brain.asker.transport.tries) == (80, 3)


# ------------------------------------------------------------------ second looks and the stricter gate
UNSURE = K.both("ramp_state", K.choice_answer("slab_full", {"slab_full": 0.5, "keep_ramping": 0.5}))
SURE = K.both("ramp_state", K.choice_answer("ec_is_feed_front", {"ec_is_feed_front": 0.85, "keep_ramping": 0.15}))
FAIRLY = K.both("ramp_state", K.choice_answer("ec_is_feed_front", {"ec_is_feed_front": 0.75, "keep_ramping": 0.25}))


def _brain(t, ledger=None, judge=None):
    asker = Asker("acct", "tok", transport=t, threaded=False, clock=lambda: K.NOW.timestamp())
    return Brain(asker, ledger or Ledger(None), [judge or RampJudge()], log=lambda *a: None)


def _bad_run(led, judge="ramp", n=3):
    for _ in range(n):
        led.resolve(led.record(judge, "default", 1, "P2", "advance"), "moisture fell back", False)


def test_an_unsure_answer_is_asked_again_with_more_evidence_and_the_sure_one_acts():
    t = K.ScriptedTransport(UNSURE, SURE)
    brain = _brain(t)
    assert brain.tick(_ramp_ctx()) == []  # unsure: nothing acts
    out = brain.tick(_ramp_ctx())  # the same minute: asked again at once, not after the 15-minute cadence
    assert [(d.kind, d.value) for d, _ in out] == [("advance", "P2")]
    assert len(t.calls) == 2 and "second_look" not in t.calls[0]["state"]
    look = t.calls[1]["state"]["second_look"]
    assert look["your_last_answer"]["ramp_state"] == {"answer": "slab_full", "p": 0.5, "agreed": True}
    assert brain.asker.stats["reasks"] == 1


def test_jev_is_asked_again_at_most_twice_then_the_engine_decides():
    t = K.ScriptedTransport(UNSURE)
    brain = _brain(t)
    for _ in range(5):
        assert brain.tick(_ramp_ctx()) == []
    assert len(t.calls) == 3 and brain.asker.stats["reasks"] == 2  # the question and two second looks


def test_two_phrasings_that_disagree_are_asked_again():
    split = K.both("ramp_state",
                   K.choice_answer("ec_is_feed_front", {"ec_is_feed_front": 0.9, "keep_ramping": 0.1}),
                   K.choice_answer("keep_ramping", {"ec_is_feed_front": 0.2, "keep_ramping": 0.8}))
    t = K.ScriptedTransport(split)
    brain = _brain(t)
    brain.tick(_ramp_ctx())
    brain.tick(_ramp_ctx())
    assert len(t.calls) == 2


def test_a_single_phrasing_is_asked_again():
    one = {"ramp_state__v0": K.choice_answer("ec_is_feed_front", {"ec_is_feed_front": 0.95, "keep_ramping": 0.05})}
    t = K.ScriptedTransport(one)
    brain = _brain(t)
    assert brain.tick(_ramp_ctx()) == [] and brain.tick(_ramp_ctx()) == []
    assert len(t.calls) == 2


def test_the_stricter_gate_comes_after_three_bad_calls_and_lifts_after_two_good():
    led = Ledger(None)
    _bad_run(led, n=2)
    assert not led.strict("ramp", "default", 1)
    _bad_run(led, n=1)
    assert led.strict("ramp", "default", 1) and not led.strict("ramp", "default", 2)  # per zone
    led.resolve(led.record("ramp", "default", 1, "P2", "advance"), "held", True)
    assert led.strict("ramp", "default", 1)  # one good call is not enough
    led.resolve(led.record("ramp", "default", 1, "P2", "advance"), "held", True)
    assert not led.strict("ramp", "default", 1)


def test_on_the_stricter_gate_a_sure_answer_waits_for_a_second_look_that_agrees():
    led = Ledger(None)
    _bad_run(led)
    t = K.ScriptedTransport(SURE, SURE)
    brain = _brain(t, led)
    assert brain.tick(_ramp_ctx()) == []  # 0.85, but no second look yet
    assert brain.zone_status("default", 1)["ramp"]["why"].startswith("refused: stricter gate")
    out = brain.tick(_ramp_ctx())  # the second look agrees: it acts
    assert [(d.kind, d.value) for d, _ in out] == [("advance", "P2")] and len(t.calls) == 2
    assert brain.strict == {("default", 1, "ramp"): True}


def test_on_the_stricter_gate_an_answer_under_0_8_never_acts():
    led = Ledger(None)
    _bad_run(led)
    t = K.ScriptedTransport(FAIRLY)
    brain = _brain(t, led)
    for _ in range(4):
        assert brain.tick(_ramp_ctx()) == []
    assert len(t.calls) == 3  # the question and two second looks, all at 0.75


def test_the_owner_is_told_once_when_a_judge_goes_on_the_stricter_gate():
    class Graded(RampJudge):
        def outcome(self, entry, ctx):
            return "moisture fell back", False

    led = Ledger(None)
    for _ in range(3):
        led.record("ramp", "default", 1, "P2", "advance", check_at=K.NOW - timedelta(minutes=1), check={})
    brain = _brain(K.FakeTransport({}), led, Graded())
    brain.tick(_ramp_ctx())
    assert brain.events == [("strict", "default", 1, "ramp")] and led.strict("ramp", "default", 1)
    brain.tick(_ramp_ctx())
    assert brain.events == [("strict", "default", 1, "ramp")]  # once, when the run tipped over
    assert _brain(K.FakeTransport({}), led).events == []  # a restart reads the gate, it does not push again


def _brain_at(t, clock, ledger=None, judge=None):
    asker = Asker("acct", "tok", transport=t, threaded=False, clock=lambda: clock["t"])
    return Brain(asker, ledger or Ledger(None), [judge or RampJudge()], log=lambda *a: None)


def test_a_second_look_is_dropped_once_the_zone_leaves_the_judges_phase():
    t = K.ScriptedTransport(UNSURE, SURE)
    brain = _brain(t)
    assert brain.tick(_ramp_ctx()) == []  # unsure: a second look is due
    brain.tick(K.ctx("P2", s=K.snap(phase="P2")))  # the zone handed over by other means first
    brain.tick(_ramp_ctx(K.NOW + timedelta(days=1)))  # the next day's ramp
    assert "second_look" not in t.calls[-1]["state"] and brain.asker.stats["reasks"] == 0


def test_a_second_look_is_dropped_once_the_answer_it_rechecks_is_too_old():
    clock = {"t": K.NOW.timestamp()}
    t = K.ScriptedTransport(UNSURE, SURE)
    brain = _brain_at(t, clock)
    brain.asker.daily_budget = 1  # the day's calls are spent: the second look cannot go out yet
    assert brain.tick(_ramp_ctx()) == [] and brain.tick(_ramp_ctx()) == []
    brain.asker.daily_budget = 5000
    clock["t"] += 30 * 60  # half an hour on: older than the ramp judge's 25 minutes
    brain.tick(_ramp_ctx(K.NOW + timedelta(minutes=30)))
    assert "second_look" not in t.calls[-1]["state"]


def test_on_the_stricter_gate_yesterdays_call_does_not_confirm_todays():
    led = Ledger(None)
    _bad_run(led)
    clock = {"t": K.NOW.timestamp()}
    t = K.ScriptedTransport(SURE, SURE)
    brain = _brain_at(t, clock, led)
    brain.asker.daily_budget = 1  # no second look can go out on day one
    assert brain.tick(_ramp_ctx()) == []
    clock["t"] += 86400
    assert brain.tick(_ramp_ctx(K.NOW + timedelta(days=1))) == []  # the same call a day later is not a second look


def test_an_answer_that_acted_is_not_asked_again():
    """0.65 is enough for the Ramp judge to hand over (0.6) and under 0.7: it acts once, and is not asked again, so
    one decision is one call and one entry in the ledger."""
    led = Ledger(None)
    t = K.ScriptedTransport(K.both("ramp_state", K.choice_answer(
        "ec_is_feed_front", {"ec_is_feed_front": 0.65, "keep_ramping": 0.35})))
    brain = _brain(t, led)
    assert [(d.kind, d.value) for d, _ in brain.tick(_ramp_ctx())] == [("advance", "P2")]
    brain.tick(_ramp_ctx())
    assert len(t.calls) == 1 and len(led.entries) == 1


def test_only_the_questions_a_judge_decides_on_can_make_it_ask_again():
    """Probe decides on `tracking`; `mode` only names the fault. A split `mode` beside a firm `tracking` is sure."""
    answers = {**K.both("tracking", K.noul_answer(0.92)),
               **K.both("mode", K.choice_answer("healthy", {"healthy": 0.5, "stuck": 0.5}))}
    t = K.ScriptedTransport(answers)
    h = K.history(points=[(m, 30.0, 3.0) for m in range(0, 200)],
                  shots=[(120, 200, 30.0, 3.0, "p2_topup"), (60, 200, 30.0, 3.0, "p2_topup")])
    brain = _brain(t, judge=ProbeJudge())
    brain.tick(K.ctx(h=h))
    brain.tick(K.ctx(h=h))
    assert len(t.calls) == 1

