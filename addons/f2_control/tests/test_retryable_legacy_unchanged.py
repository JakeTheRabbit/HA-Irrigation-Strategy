"""retryable() matches its non-retryable constants by prefix, and Route hides its token (haiku-brain-design section 2,
the client.py rows). Every transport error keeps the verdict it had in 3.11.1; a billed
Claude call is never handed back to Routes as one to try again."""
import functools

import brain_kit as B
import pytest
from brain.client import (BAD_OUTPUT, BUDGET, INTERNAL, NO_ANSWERS, NO_CONTEXT, NO_REQUESTS, NO_SDK, NOT_JSON, PAUSED,
                        REFUSED, Meter, Route, Routes, call_anthropic, retryable)


def _before(error):
    """retryable() as 3.11.1 wrote it."""
    if error.startswith("HTTP "):
        code = error[5:8]
        return code == "429" or code.startswith("5")
    return error not in (NO_REQUESTS, NOT_JSON, NO_ANSWERS)


LEGACY = [NO_REQUESTS, NOT_JSON, NO_ANSWERS, "HTTP 400: {\"error\": \"bad\"}", "HTTP 401: Unauthorized",
          "HTTP 403: forbidden", "HTTP 404: no such model", "HTTP 408: timeout", "HTTP 429: rate limited",
          "HTTP 500: boom", "HTTP 502: bad gateway", "HTTP 503: busy", "HTTP 524: timeout",
          "ReadTimeout: HTTPSConnectionPool(host='api.example.com'): read timed out",
          "ConnectTimeout: connect timed out", "ConnectionError: [Errno 111] Connection refused",
          "SSLError: certificate verify failed", "ChunkedEncodingError: connection broken",
          "TooManyRedirects: exceeded 30 redirects", "InvalidURL: no host", "RuntimeError: refused",
          "dropped unasked: it waited 400 s in the queue"]


@pytest.mark.parametrize("error", LEGACY)
def test_every_legacy_error_keeps_its_verdict(error):
    assert retryable(error) == _before(error)


@pytest.mark.parametrize("constant", [BAD_OUTPUT, REFUSED, BUDGET, NO_SDK, PAUSED, NO_CONTEXT, INTERNAL])
def test_no_claude_constant_is_retried_with_or_without_a_suffix(constant):
    assert not retryable(constant) and not retryable(constant + ": bio")


def test_a_route_never_prints_its_token():
    r = Route("Anthropic", print, "acct", B.SENTINEL, "gw")
    assert B.SENTINEL not in repr(r) and "acct" in repr(r)


def _send(fake, meter, tries=3):
    slept = []
    fn = functools.partial(call_anthropic, model="claude-haiku-5-5", prompt=B.FakePrompt(), meter=meter, client=fake)
    send = Routes([Route("Anthropic", fn, "anthropic", B.SENTINEL)], tries=tries, sleep=slept.append,
                  clock=lambda: 0.0)
    return send("anthropic", B.SENTINEL, B.STATE, B.QUESTIONS), slept


def test_a_refusal_on_both_lanes_is_refused_and_billed_once_per_lane():
    meter = Meter(1.0)
    fake = B.FakeClient(B.message(stop="refusal", category="bio"))
    (answers, _usage, error), slept = _send(fake, meter)
    assert answers is None and error == f"Anthropic: {REFUSED}" and len(fake.requests) == 2 and slept == []
    assert meter.snapshot()["calls"] == 2


@pytest.mark.parametrize("first, then, said", [
    (B.message(stop="refusal"), B.RateLimitError("slow"), REFUSED),
    (B.message(B.tool("answer_choice", snapshot_id="stale")), B.APITimeoutError(), BAD_OUTPUT),
    (B.message(B.tool("answer_choice", snapshot_id="stale")), B.APIStatusError(529), BAD_OUTPUT),
])
def test_a_billed_lane_is_never_billed_again(first, then, said):
    meter = Meter(1.0)
    fake = B.FakeClient(first, then)
    (answers, _usage, error), slept = _send(fake, meter)
    assert answers is None and error == f"Anthropic: {said}"
    assert len(fake.requests) == 2 and slept == []
    # a timed-out lane may have been billed, so it is charged an estimate too
    assert meter.snapshot()["calls"] == (2 if isinstance(then, B.APITimeoutError) else 1)
    if isinstance(then, B.RateLimitError):
        assert meter.state() == "paused"


def test_a_call_that_failed_before_any_response_may_be_tried_again():
    meter = Meter(1.0)
    fake = B.FakeClient(B.APIStatusError(503), B.answering())
    (answers, usage, error), slept = _send(fake, meter)
    assert error is None and sorted(answers) == ["dusk_call__v0", "dusk_call__v1"]
    assert slept == [2.0] and usage["retries"] == 1 and usage["route"] == "Anthropic"
