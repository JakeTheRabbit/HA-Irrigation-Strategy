"""The Anthropic key never leaves the SDK client: not in an answer, a usage block, an error string or the log, whatever
the call does (haiku-brain-design section 9). The same sentinel runs through the wired brain in test_brain_wiring."""
import brain_kit as B
import pytest
from jev import client
from jev.client import Meter, call_anthropic, redact


@pytest.mark.parametrize("script", [
    (B.answering(),),
    (B.AuthenticationError("invalid x-api-key " + B.SENTINEL),),
    (B.RateLimitError("slow down " + B.SENTINEL, retry_after="20"),),
    (B.APITimeoutError("timed out talking with " + B.SENTINEL),),
    (B.message(B.tool("answer_choice", snapshot_id="nope", rationale=B.SENTINEL)),),
    (B.message(B.choice(B.FakePrompt.snap, "dusk_call__v0", "enter_p3_now", B.GOOD, rationale=B.SENTINEL)),),
    (RuntimeError("the SDK said " + B.SENTINEL),),
], ids=["success", "401", "429", "timeout", "malformed", "rationale", "sdk-exception"])
def test_the_key_is_in_nothing_the_transport_returns_or_prints(script, capsys):
    meter = Meter(1.0)
    out = call_anthropic("anthropic", B.SENTINEL, B.STATE, B.QUESTIONS, prompt=B.FakePrompt(), meter=meter,
                         client=B.FakeClient(*script))
    seen = repr(out) + repr(meter.snapshot()) + capsys.readouterr().out
    assert B.SENTINEL not in seen and "sk-ant-" not in seen


def test_redact_takes_out_the_key_and_any_key_shaped_run():
    client._keys.add(B.SENTINEL)
    try:
        assert redact(f"failed: {B.SENTINEL}!") == "failed: <key>!"
        assert redact("token sk-ant-api03-abcDEF_123-xyz here") == "token <key> here"
        assert redact("plain words") == "plain words"
    finally:
        client._keys.discard(B.SENTINEL)
