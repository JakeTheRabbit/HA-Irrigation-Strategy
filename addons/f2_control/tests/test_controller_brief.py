"""How this controller works, in the Claude brain's cached system prompt (brain/controller_brief.py): generated from the
code, so a phase, a setting, an error code or a power the code has and the brief lacks fails here, and the cached
system prompt is byte-stable between calls, with the cache breakpoint on its last block."""
from crop_steering_engine.core import PHASES
from crop_steering_engine.core import CAP_EXEMPT
from crop_steering_engine.defaults import CONTROLLER_FALLBACKS

from brain import controller_brief as cb
from brain import powers, prompt


def test_the_committed_brief_is_a_fresh_render_of_the_code():
    assert cb.read() == cb.render(cb.load_codes()), "run: python -m brain.controller_brief --write"


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


def test_budget_exemptions_match_the_engine_and_error_responses_are_not_truncated():
    brief = cb.render(cb.load_codes())
    cap_line = next(line for line in brief.splitlines() if "safety shots are exempt:" in line)
    for kind, exempt in CAP_EXEMPT.items():
        assert (kind in cap_line) is exempt
    response = "The zone stops. Rescues are held until a person resets the latch."
    rendered = cb.render([{"code": "CHECK-1", "title": "Latch", "meaning": "Fault.", "watering": response}])
    assert response in rendered


def test_generic_arc_uses_relative_vendor_band_without_dividing_uncalibrated_vwc():
    from types import SimpleNamespace

    from brain.doctrine import stage_rows
    from brain.numbers import stage_block

    rows = stage_rows("slab_default")
    stage = rows[1]
    context = SimpleNamespace(brain={"zone_config": {"substrate": "generic"}}, steering="generative",
                              flower_day=7, flower_days=56, stage=stage, snap=SimpleNamespace(peak_vwc=9))
    value = stage_block(context)
    assert "% of peak (vendor starting band)" in value
    assert "points" not in value
    assert "overnight dryback (% of peak, vendor)" in prompt.arc_table(rows, "slab_default")
