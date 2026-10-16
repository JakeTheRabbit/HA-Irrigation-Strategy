"""The enrichment hook (brain/enrich.py), called directly: what a judge's evidence carries to Claude beyond the
judge's own sentences, and what it no longer carries (haiku-brain-design sections 2, 7)."""
import brain_kit as B
import jev_kit as K
from brain import doctrine
from brain.enrich import PROBE_WORDS, enrich, neutral
from brain.judges.probe import ProbeJudge
from brain.judges.salt import SaltJudge
from brain.judges.stage import StageJudge
from brain.scrub import scrub


def _ctx(name, **over):
    return next(c for j, c in B.scenarios(**over) if j.name == name)


def test_every_judge_gets_a_brain_key_with_every_block():
    for judge, ctx in B.scenarios():
        ev = enrich(ctx, judge, judge.evidence(ctx))
        meta = ev["_brain"]
        assert (meta["room"], meta["zone"], meta["judge"], meta["asked"]) == ("default", 1, judge.name,
                                                                              "2026-09-27T13:00")
        assert set(meta) >= {"numbers", "zone_config", "interlocks", "data_quality", "stage", "siblings"}
        assert meta["numbers"]["moisture_pct"] == ctx.snap.vwc and meta["numbers"]["phase"] == ctx.phase
        assert meta["numbers"]["room_median_litres_per_plant_l"] > 0
        assert meta["zone_config"]["plants"] == 4 and set(meta["siblings"]) == {"2", "3"}
        assert "stage_today" not in ev


def test_the_probe_judge_sends_words_not_its_entity_id():
    ctx = _ctx("probe")
    ev = enrich(ctx, ProbeJudge(), ProbeJudge().evidence(ctx))
    assert ev["probe"] == PROBE_WORDS and B.FUSED_PROBE not in repr(ev)


def test_the_stage_block_carries_what_stage_today_said_from_the_installs_arc():
    ctx = _ctx("stage")
    stage = enrich(ctx, StageJudge(), StageJudge().evidence(ctx))["_brain"]["stage"]
    row = doctrine.STAGE_ARC[1]
    assert stage.startswith("flower day 10 of about 56: flower setting (stretch) (days 1-21)")
    assert row["move_on_when"] in stage and "pore EC 5-10" in stage and "% of this zone's peak" in stage
    assert stage.endswith("The grower's steering mode for this zone: generative.")


def test_with_no_flower_start_the_stage_is_unknown():
    ctx = _ctx("dusk", flower_day=None, stage=None)
    judge = next(j for j, _c in B.scenarios() if j.name == "dusk")
    assert enrich(ctx, judge, judge.evidence(ctx))["_brain"]["stage"].startswith("unknown: no flower start")


def test_no_owners_wording_survives():
    ctx = _ctx("salt")
    ev = enrich(ctx, SaltJudge(), SaltJudge().evidence(ctx))
    assert "owner" not in repr(ev)
    assert neutral("against the owner's stage arc and the owner's doctrine") == (
        "against this install's stage arc and the doctrine")


def test_the_scrub_takes_every_domain_and_leaves_ordinary_dots():
    text = ("valve.row_2 light.flower button.go climate.room fan.a input_boolean.f2_control_enabled select.mode, "
            "e.g. host.example and version 3.11.1")
    out = scrub(text)
    for gone in ("valve.row_2", "light.flower", "button.go", "climate.room", "fan.a", "input_boolean.", "select."):
        assert gone not in out
    assert "e.g. host.example and version 3.11.1" in out


def test_a_context_built_without_a_brain_still_works():
    ctx = K.ctx("P2")
    from brain.judges.dusk import DuskJudge

    assert enrich(ctx, DuskJudge(), DuskJudge().evidence(ctx))["_brain"]["interlocks"] == "not known"
