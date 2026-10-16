"""The Claude transport (brain.client.call_anthropic): two lanes, every tool call checked before it counts, every
response charged, never a raise, never the key in what comes back (haiku-brain-design sections 3 and 9)."""
import types

import brain_kit as B
import pytest
from brain import client
from brain.client import (BAD_OUTPUT, INTERNAL, NO_CONTEXT, NO_SDK, Meter, call_anthropic, classify, split_lanes,
                        validate_answer)

SNAP = B.FakePrompt.snap


def _call(fake, state=None, questions=None, meter=None, prompt=None):
    return call_anthropic("anthropic", B.SENTINEL, B.STATE if state is None else state,
                          B.QUESTIONS if questions is None else questions, prompt=prompt or B.FakePrompt(),
                          meter=meter, client=fake)


def test_both_lanes_answer_in_the_councils_format():
    fake = B.FakeClient(B.answering())
    answers, usage, error = _call(fake)
    assert error is None and sorted(answers) == ["dusk_call__v0", "dusk_call__v1"]
    a = answers["dusk_call__v0"]
    assert a["type"] == "choice" and a["choice"] == "enter_p3_now" and a["confidence"] == 0.8
    assert abs(sum(a["probabilities"].values()) - 1.0) < 1e-9 and a["rationale"] == "the probe says so"
    assert len(fake.requests) == 2
    assert "lane=0" in fake.requests[0]["messages"][0]["content"][1]["text"]
    assert "lane=1" in fake.requests[1]["messages"][0]["content"][1]["text"]
    assert all(r["timeout"] == 15.0 for r in fake.requests)
    assert set(usage) >= {"input_tokens", "uncached_input_tokens", "cache_creation_input_tokens",
                          "cache_read_input_tokens", "cache_creation_5m", "cache_creation_1h", "output_tokens",
                          "cost_usd", "calls", "model", "refusals", "lanes_answered"}
    assert (usage["calls"], usage["lanes_answered"], usage["model"]) == (2, 2, "claude-haiku-5-5")
    assert usage["input_tokens"] == 2 * (800 + 1500 + 35450)


def test_one_lane_answering_is_an_answer_with_one_phrasing():
    fake = B.FakeClient(B.answering(), B.APITimeoutError("slow"))
    answers, usage, error = _call(fake)
    assert error is None and list(answers) == ["dusk_call__v0"] and usage["lanes_answered"] == 1


@pytest.mark.parametrize("bad", [
    B.choice("another-snapshot", "dusk_call__v0", "enter_p3_now", B.GOOD),
    B.choice(SNAP, "dawn_call__v0", "enter_p3_now", B.GOOD),
    B.choice(SNAP, "dusk_call__v0", "keep_drying", {"keep_drying": 1.0}),
    B.choice(SNAP, "dusk_call__v0", "enter_p3_now", {"enter_p3_now": 0.5, "continue_p2": 0.2}),
    B.choice(SNAP, "dusk_call__v0", "continue_p2", B.GOOD),
    B.choice(SNAP, "dusk_call__v0", "enter_p3_now", B.GOOD, confidence=1.4),
    B.yes_no(SNAP, "dusk_call__v0", 0.9),
    B.tool("answer_choice", snapshot_id=SNAP, question_id="dusk_call__v0"),
])
def test_a_tool_call_that_fails_a_check_is_no_answer(bad):
    fake = B.FakeClient(B.message(bad))
    answers, usage, error = _call(fake)
    assert answers is None and error == BAD_OUTPUT and len(fake.requests) == 2


def test_a_max_tokens_stop_with_no_tool_call_is_no_answer():
    fake = B.FakeClient(B.message(types.SimpleNamespace(type="thinking"), stop="max_tokens"))
    assert _call(fake)[2] == BAD_OUTPUT


def test_the_first_call_for_a_question_wins():
    first = B.choice(SNAP, "dusk_call__v0", "enter_p3_now", B.GOOD)
    second = B.choice(SNAP, "dusk_call__v0", "continue_p2", {"continue_p2": 0.9, "enter_p3_now": 0.1})
    answers, _usage, _error = _call(B.FakeClient(B.message(first, second)))
    assert answers["dusk_call__v0"]["choice"] == "enter_p3_now"


def test_missing_probabilities_count_zero_and_the_sum_is_normalised():
    found = validate_answer(B.choice(SNAP, "q__v0", "enter_p3_now", {"enter_p3_now": 0.66, "continue_p2": 0.3}),
                            SNAP, {"q__v0": B.QUESTIONS["dusk_call__v0"]})
    assert found[1]["probabilities"]["insufficient_evidence"] == 0.0
    assert abs(sum(found[1]["probabilities"].values()) - 1.0) < 1e-9


def test_a_rationale_is_one_line_without_entity_ids_and_capped():
    why = "sensor.crop_steering_vwc_zone_1 read\nflat; " + "x" * 400
    found = validate_answer(B.choice(SNAP, "q__v0", "enter_p3_now", B.GOOD, rationale=why), SNAP,
                            {"q__v0": B.QUESTIONS["dusk_call__v0"]})
    text = found[1]["rationale"]
    assert "\n" not in text and "sensor.crop_steering" not in text and text.startswith("a sensor read flat")
    assert len(text) == 300


def test_a_yes_no_question_takes_the_yes_no_tool():
    lane = {"tracking__v0": {"type": "noul", "instructions": "tracks?", "criteria": {"true": "y", "false": "n"}}}
    assert validate_answer(B.yes_no(SNAP, "tracking__v0", 0.2), SNAP, lane)[1]["noul"] == 0.2
    assert validate_answer(B.yes_no(SNAP, "tracking__v0", 1.2), SNAP, lane) is None


def test_lanes_follow_the_phrasing_index():
    lanes = split_lanes({"a__v0": 1, "b__v0": 2, "a__v1": 3, "b__v1": 4, "report": 5})
    assert lanes == {0: {"a__v0": 1, "b__v0": 2, "report": 5}, 1: {"a__v1": 3, "b__v1": 4}}


def test_no_client_is_no_sdk_and_no_brain_key_sends_nothing():
    assert _call(None) == (None, None, NO_SDK)
    fake = B.FakeClient(B.answering())
    assert _call(fake, state={"phase": "P2"}) == (None, None, NO_CONTEXT)
    assert fake.requests == []


def test_a_fault_in_the_transports_own_code_is_internal(capsys):
    class Broken(B.FakePrompt):
        def evidence(self, state):
            raise KeyError("numbers")

    fake = B.FakeClient(B.answering())
    assert _call(fake, prompt=Broken()) == (None, None, INTERNAL)
    assert fake.requests == [] and "KeyError" in capsys.readouterr().out


@pytest.mark.parametrize("error, said, effect", [
    (B.AuthenticationError("bad " + B.SENTINEL), "HTTP 401: authentication_error", "auth_failed"),
    (B.APIStatusError(403, "no"), "HTTP 403: permission_error", "auth_failed"),
    (B.APIStatusError(404, "model"), "HTTP 404: not_found_error", "model_invalid"),
    (B.RateLimitError("slow", retry_after="30"), "HTTP 429: rate_limit_error", "paused"),
    (B.APIStatusError(529, "busy"), "HTTP 529: overloaded_error", "paused"),
    (B.APIStatusError(503, "down " + B.SENTINEL), "HTTP 503: api_error", None),
    (B.APIStatusError(400, "bad"), "HTTP 400: invalid_request_error", None),
    (B.APITimeoutError(B.SENTINEL), "APITimeoutError", None),
    (B.APIConnectionError(B.SENTINEL), "APIConnectionError", None),
    (ValueError(B.SENTINEL), "ValueError", None),
])
def test_every_sdk_error_becomes_a_key_free_string(error, said, effect):
    meter = Meter(1.0, clock=lambda: 1000.0)
    assert classify(error, meter) == said
    assert meter.state() == effect
    answers, usage, got = _call(B.FakeClient(error), meter=Meter(1.0))
    assert (answers, usage) == (None, None) and got == said and B.SENTINEL not in got


def test_a_request_that_may_have_been_billed_is_charged_and_the_budget_still_stops_retries():
    meter = Meter(0.0008, clock=lambda: 1000.0)
    fake = B.FakeClient(B.APITimeoutError("slow"))
    routes = client.Routes([client.Route("Anthropic", lambda *a, **kw: _call(fake, meter=meter), "anthropic",
                                         B.SENTINEL)], tries=3, sleep=lambda s: None)
    assert routes("anthropic", B.SENTINEL, B.STATE, B.QUESTIONS)[2] == "Anthropic: budget spent"
    assert meter.snapshot()["cost_usd"] > 0 and meter.state() == "budget_spent"
    assert len(fake.requests) == 1  # the retry found the budget spent and sent nothing


def test_an_api_error_or_a_connection_never_opened_is_not_charged():
    refused = B.APIConnectionError("no route")
    refused.__cause__ = type("ConnectError", (Exception,), {})()
    for error in (B.APIStatusError(503), refused):
        meter = Meter(1.0, clock=lambda: 1000.0)
        _call(B.FakeClient(error), meter=meter)
        assert meter.snapshot()["cost_usd"] == 0.0


def test_a_response_is_charged_before_any_other_bookkeeping(monkeypatch):
    meter = Meter(1.0, clock=lambda: 1000.0)
    monkeypatch.setattr(client, "add_usage", lambda *a: 1 / 0)
    assert _call(B.FakeClient(B.answering()), meter=meter) == (None, None, INTERNAL)
    assert meter.snapshot()["cost_usd"] > 0


def test_three_bad_requests_in_a_row_make_the_brain_unavailable_for_an_hour():
    now = {"t": 1000.0}
    meter = Meter(1.0, clock=lambda: now["t"])
    for _ in range(3):
        classify(B.APIStatusError(400), meter)
    assert meter.state() == "unavailable" and meter.take("brain")
    now["t"] += 3601
    assert meter.state() is None


def test_the_client_is_built_with_the_key_and_the_apis_own_address(monkeypatch):
    built = {}
    monkeypatch.setattr(client, "anthropic", types.SimpleNamespace(Anthropic=lambda **kw: built.update(kw) or "c"))
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://sentinel.invalid")
    assert client.make_client(B.SENTINEL) == "c"
    assert built == {"api_key": B.SENTINEL, "base_url": "https://api.anthropic.com", "max_retries": 0}
    assert client.make_client("") is None
    monkeypatch.setattr(client, "anthropic", None)
    assert client.make_client(B.SENTINEL) is None


def test_the_key_option_is_read_stripped_and_empty_is_no_key():
    assert client.anthropic_key({"anthropic_api_key": "  k  "}) == "k"
    assert client.anthropic_key({"anthropic_api_key": None}) == "" == client.anthropic_key({})
