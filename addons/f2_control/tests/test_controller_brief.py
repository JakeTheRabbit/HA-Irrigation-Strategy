"""How this controller works, in the Claude brain's cached system prompt (jev/controller_brief.py): generated from the
code, so a phase, a setting, an error code or a power the code has and the brief lacks fails here, and the cached
system prompt is byte-stable between calls, with the cache breakpoint on its last block."""
from crop_steering_engine.core import PHASES
from crop_steering_engine.defaults import CONTROLLER_FALLBACKS

from jev import controller_brief as cb
from jev import powers, prompt


def test_the_committed_brief_is_a_fresh_render_of_the_code():
    assert cb.read() == cb.render(cb.load_codes()), "run: python -m jev.controller_brief --write"


def test_every_phase_setting_error_code_and_power_is_in_the_brief():
    brief = cb.read()
    missing = [p for p in PHASES if p not in brief]
    missing += [k for k in CONTROLLER_FALLBACKS if f"- {k}:" not in brief]
    missing += [c["code"] for c in cb.load_codes() if f"- {c['code']} " not in brief]
    missing += [k for k, _d, _w in powers.POWERS if f"- {k} (default" not in brief]
    missing += [k for keys in cb.writable().values() for k in keys if k not in cb.EFFECTS or f"  - {k} (" not in brief]
    assert missing == []


def test_the_cached_system_prompt_carries_the_brief_the_goal_and_the_rules_and_is_byte_stable():
    one, two = prompt.Prompt(), prompt.Prompt()
    assert one.system == two.system  # the same bytes on every call: a cache hit
    assert one.system[-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    a = one.system[0]["text"]
    assert cb.read().strip() in a and a.index("How this controller works") > a.index("Hard rules")
    assert "The owner's powers: the goal and the rules when you set targets yourself" in a
    for rule in ("POW-01", "POW-02", "POW-06", "POW-07", "POW-08", "POW-09", "POW-10"):
        assert rule in a, rule


def test_the_request_keeps_live_state_out_of_the_system_prompt():
    p = prompt.Prompt()
    request = p.request("claude-haiku-5-5", "<snapshot>LIVE-STATE-7731</snapshot>", "<questions/>", 2048)
    assert all("LIVE-STATE-7731" not in block["text"] for block in request["system"])
    assert request["messages"][0]["content"][0]["text"] == "<snapshot>LIVE-STATE-7731</snapshot>"
