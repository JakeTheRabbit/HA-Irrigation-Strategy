"""The Claude brain's prompt (jev/prompt.py): byte-stable cached blocks, an evidence block with no entity id, no key
and no one site's wording, and a request with nothing a current model refuses (haiku-brain-design sections 7, 9)."""
import pathlib
import re

import brain_kit as B
import pytest
from jev import council, doctrine, prompt
from jev.client import split_lanes
from jev.enrich import enrich
from jev.scrub import HA_DOMAINS

REPO = pathlib.Path(__file__).resolve().parents[3]
CREDENTIALS = ("anthropic_api_key", "typesafe_api_key", "cf_api_token", "cf_account_id", "cf_gateway_id")
ENTITY = re.compile(r"\b(?:" + "|".join(HA_DOMAINS) + r")\.[a-z0-9_]+")


def _rendered():
    p = prompt.Prompt(doctrine.STAGE_ARC, "slab_default")
    out = []
    for judge, ctx in B.scenarios():
        ev = enrich(ctx, judge, judge.evidence(ctx))
        snap, text = p.evidence(ev)
        lanes = [p.questions(snap, i, lane) for i, lane in
                 sorted(split_lanes(council.expand(judge.questions)).items())]
        out.append((judge.name, text, lanes))
    return out


def test_blocks_a_and_b_are_the_same_bytes_on_every_build():
    one, two = prompt.Prompt(doctrine.STAGE_ARC, "slab_default"), prompt.Prompt(doctrine.STAGE_ARC, "slab_default")
    assert (one.a, one.b) == (two.a, two.b)
    assert "\r" not in one.a + one.b
    mixed = prompt.block_b(doctrine.STAGE_ARC, "slab_default", ("rockwool", "coco"))
    assert mixed == prompt.block_b(doctrine.STAGE_ARC, "slab_default", ("coco", "rockwool", "coco"))


def test_block_a_is_the_pack_with_the_preamble_after_its_first_section():
    a = prompt.block_a()
    assert a.startswith("# Crop-steering brain: doctrine ")
    assert a.index("## 2. How this controller asks you") < a.index("### 7.1 What the engine does")
    assert a.count("B-0") >= 4 and "### 7.4 Doctrine rules by topic" in a


def test_block_b_has_the_arc_only_when_one_is_in_force():
    assert "| flower setting (stretch) | 1-21 | generative |" in prompt.block_b(doctrine.STAGE_ARC, "slab_default")
    assert "Stage arc `slab_default`" in prompt.block_b(doctrine.STAGE_ARC, "slab_default")
    assert "| stage |" not in prompt.block_b((), None)


def test_the_topic_map_covers_every_doctrine_topic():
    assert set(prompt.TOPICS) == set(doctrine.RULES)


def test_no_site_string_in_the_cached_blocks():
    patterns = [line.split("\t")[1] for line in (REPO / "doctrine/denylist.public.txt").read_text("utf-8").splitlines()
                if line.strip() and not line.startswith("#")]
    text = prompt.Prompt(doctrine.STAGE_ARC, "slab_default").a + prompt.block_b(doctrine.STAGE_ARC, "slab_default")
    for pat in patterns:
        assert not re.search(pat, text), pat


def test_no_entity_id_key_or_owners_wording_reaches_the_model():
    options = {k: f"secret-{k}-value" for k in CREDENTIALS}
    for name, text, lanes in _rendered():
        everything = text + "".join(lanes)
        assert not ENTITY.search(everything), (name, ENTITY.search(everything).group(0))
        assert B.FUSED_PROBE not in everything and "stage_today" not in everything
        assert "the owner" not in everything.lower(), name
        assert not any(v in everything for v in options.values())
        if name == "probe":
            assert "this zone's moisture probe" in text


def test_the_evidence_block_is_the_same_bytes_for_the_same_moment():
    judge, ctx = B.scenarios()[3]
    p = prompt.Prompt()
    assert p.evidence(enrich(ctx, judge, judge.evidence(ctx))) == p.evidence(enrich(ctx, judge, judge.evidence(ctx)))
    snap, text = p.evidence(enrich(ctx, judge, judge.evidence(ctx)))
    assert snap.startswith("default:z1:dusk:2026-09-27T13:00:") and f'<snapshot id="{snap}"' in text
    assert '<operator_text>zone "Zone 1"</operator_text>' in text


def test_an_alert_question_with_no_bare_phrasing_renders():
    from jev.triage import QUESTIONS

    lanes = split_lanes(council.expand(QUESTIONS))
    text = prompt.Prompt.questions("s", 0, lanes[0])
    assert '<question id="urgency__v0" kind="choice">' in text and "- quiet:" in text


@pytest.mark.parametrize("model", ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"])
def test_the_request_is_valid_for_every_allowed_model(model):
    p = prompt.Prompt(doctrine.STAGE_ARC, "slab_default")
    req = p.request(model, "<snapshot/>", "<questions/>", 2048)
    assert not {"temperature", "top_p", "top_k", "fallbacks", "speed", "inference_geo"} & set(req)
    assert req["thinking"] == {"type": "adaptive"} and req["output_config"] == {"effort": "low"}
    assert req["tool_choice"] == {"type": "auto"} and req["messages"][-1]["role"] == "user"
    marks = [b["cache_control"] for b in req["system"]] + [
        b["cache_control"] for b in req["messages"][0]["content"] if "cache_control" in b]
    assert marks == [{"type": "ephemeral", "ttl": "1h"}] * 2 + [{"type": "ephemeral"}]
    assert "cache_control" not in req["messages"][0]["content"][1]


def test_the_start_line_names_hashes_never_the_text():
    line = prompt.Prompt().describe()
    assert re.fullmatch(r"brain: prompt A=[0-9a-f]{8} B=[0-9a-f]{8}, about \d+\.\dk tokens", line)

