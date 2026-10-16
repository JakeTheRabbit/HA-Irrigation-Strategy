"""Default request stability, room isolation and all four cache breakpoints."""
import copy
import hashlib

from brain.prompt import Prompt
from brain.prompt_context import export


def test_no_context_keeps_the_legacy_request_byte_identical():
    p = Prompt()
    old = p.request("model", "evidence", "questions", 100)
    p.contexts["room_a"] = {"notes": "", "profile": {}, "cache": {"ttl": "1h", "A": True, "B": True, "C": True, "evidence": True}}
    assert p.request("model", "evidence", "questions", 100, room="room_a") == old
    assert len(old["system"]) == 2


def test_context_is_its_own_room_scoped_block_and_a_is_unchanged():
    p = Prompt()
    original = copy.deepcopy(p.system)
    p.contexts["room_a"] = {"notes": "Inspect drains each morning.", "profile": {"environment": "Sealed room"}}
    req = p.request("model", "facts", "questions", 100, room="room_a")
    assert req["system"][:2] == original
    assert len(req["system"]) == 3
    assert "Sealed room" in req["system"][2]["text"]
    assert "safety" in req["system"][2]["text"]
    assert p.request("model", "facts", "questions", 100, room="room_b")["system"] == original
    assert p.a == original[0]["text"]


def test_breakpoints_and_ttl_have_at_most_four_entries():
    p = Prompt()
    p.contexts["room_a"] = {"notes": "Inspect drains.", "cache": {"ttl": "5m", "A": False, "B": True, "C": True, "evidence": False}}
    req = p.request("model", "facts", "questions", 100, room="room_a")
    assert "cache_control" not in req["system"][0]
    assert req["system"][1]["cache_control"]["ttl"] == "5m"
    assert "cache_control" not in req["messages"][0]["content"][0]
    p.contexts["room_a"]["cache"].update(A=True, evidence=True)
    req = p.request("model", "facts", "questions", 100, room="room_a")
    assert sum("cache_control" in b for b in req["system"] + req["messages"][0]["content"]) == 4


def test_publication_is_exact_built_text_with_full_hash_and_sources():
    p = Prompt(substrates=("rockwool",))
    conf = {"notes": "Check emitters."}
    blocks = export(p, conf)
    p.contexts["room_a"] = conf
    req = p.request("model", "facts", "questions", 100, room="room_a")
    assert [b["text"] for b in blocks] == [b["text"] for b in req["system"]]
    assert [b["id"] for b in blocks] == ["A", "B", "C"]
    for b in blocks:
        assert b["hash"] == hashlib.sha256(b["text"].encode()).hexdigest()
        assert b["sources"]


def test_rebuild_and_failed_publication_retry_without_paid_calls():
    from types import SimpleNamespace
    import prompt_runtime

    p = Prompt()
    c = SimpleNamespace(jev=SimpleNamespace(prompt=p))
    room = SimpleNamespace(slug="room_a", prefix="room_a_", substrate="generic")
    c.rooms = [room]
    calls = []
    attrs = {"config": {"notes": "Inspect emitters."}, "rebuild": 0}
    def get(_entity):
        return "2", attrs
    def call(domain, service, **data):
        calls.append((domain, service, data))
        return len(calls) != 1
    prompt_runtime.sync(c, room, get, call)
    prompt_runtime.sync(c, room, get, call)
    prompt_runtime.sync(c, room, get, call)
    assert len(calls) == 2
    attrs["rebuild"] = 1
    prompt_runtime.sync(c, room, get, call)
    assert len(calls) == 3
    assert all(service == "brain_prompt_publish" for _domain, service, _data in calls)


def test_savings_are_estimated_at_the_billed_tariff_and_old_usage_is_unknown():
    from brain.client import Meter, cost
    model = "claude-haiku-5-5"
    meter = Meter(1, model, clock=lambda: 100.0)
    usage = {"input_tokens": 100, "cache_read_input_tokens": 900, "output_tokens": 10}
    billed = meter.charge(usage)
    difference = cost({"input_tokens": 1000, "output_tokens": 10}, model) - billed
    assert meter.snapshot()["cache_savings_estimate_usd"] == round(difference, 8)
    old = meter.snapshot()
    old.pop("cache_savings_estimate_usd")
    upgraded = Meter(1, model, clock=lambda: 100.0)
    assert upgraded.restore(old)
    assert upgraded.snapshot()["cache_savings_estimate_usd"] is None
    upgraded.charge(usage)
    assert upgraded.snapshot()["cache_savings_estimate_usd"] is None
