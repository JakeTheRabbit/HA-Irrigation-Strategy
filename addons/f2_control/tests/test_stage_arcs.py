"""Stage arcs (brain.doctrine.stage_rows / stage_intent): the default arc is the one the judges always had, every arc
the stage_arc option offers passes the check and runs every judge, and an arc the judges could not read is refused
with a reason instead of breaking them (haiku-brain-design sections 2 and 7, test_stage_arcs)."""
import json
import pathlib

import brain_bridge
import jev_kit as K
import pytest
import yaml
from brain import doctrine, prompt
from brain.doctrine import FINISH_DAYS, STAGE_ARC, ArcInvalid, stage_intent, stage_rows
from brain.judges.base import common

ADDON = pathlib.Path(__file__).parents[1]
RELEASED = ("slab_default",)  # every stage_arc value a released config.yaml has offered: never removed


def _offered():
    kind = yaml.safe_load((ADDON / "config.yaml").read_text(encoding="utf-8"))["schema"]["stage_arc"]
    return kind[len("list("):-len(")?")].split("|")


def _before(flower_day, flower_days=56):
    """stage_intent as 3.11.1 wrote it."""
    if flower_day is None or not 1 <= flower_day <= flower_days:
        return None
    _veg, setting, bulk, finish = STAGE_ARC
    start = max(flower_days - FINISH_DAYS + 1, bulk["days"][0])
    if flower_day <= setting["days"][1]:
        return dict(setting)
    if flower_day < start:
        return {**bulk, "days": (bulk["days"][0], start - 1)}
    return {**finish, "days": (start, flower_days)}


def test_the_default_arc_is_the_one_the_judges_always_had():
    assert stage_rows("slab_default") is STAGE_ARC
    for days in range(42, 85):
        for day in [None] + list(range(0, 121)):
            assert stage_intent(day, days) == _before(day, days) == stage_intent(day, days, STAGE_ARC)
    assert stage_intent(10, 56, ()) is None


def test_the_default_arc_is_read_from_the_pack_and_keeps_todays_numbers():
    """One copy: the default arc is the pack's slab_default table, and its numbers are the ones 3.11.1 kept by hand."""
    assert STAGE_ARC == doctrine._read_arc("slab_default", doctrine.PACK_ARCS)
    assert [(r["days"], r["steering"], r["dryback_points"], r["pore_ec_range"], r["runoff_pct"]) for r in STAGE_ARC] == [
        (None, "vegetative", (10, 15), (3.0, 5.0), (8, 16)),
        ((1, 21), "generative", (15, 25), (5.0, 10.0), (1, 7)),
        ((22, 42), "vegetative", (10, 15), (3.5, 6.0), (8, 16)),
        ((43, 56), "ripening", (20, 25), (3.0, 4.0), (1, 7)),
    ]


def test_the_dashboard_reads_the_same_arc():
    board = ADDON.parents[1] / "frontend" / "src" / "lib" / "generated" / "arcs.json"
    pack = json.loads(board.read_text(encoding="utf-8"))
    assert pack["default_arc"] == doctrine.DEFAULT_ARC
    bulk = next(r for r in pack["arcs"]["slab_default"]["stages"] if r["stage"] == "flower bulk")
    ours = stage_intent(30)
    assert ours["stage"] == bulk["stage"] and ours["steering"] == bulk["steering"]
    assert [list(ours[k]) for k in ("days", "dryback_points", "pore_ec_range", "runoff_pct")] == [
        bulk["flower_days"], bulk["dryback_points"], bulk["pore_ec"], bulk["runoff_pct"]]


def test_every_offered_arc_passes_and_no_released_one_is_withdrawn():
    offered = _offered()
    assert offered[0] == "slab_default" and set(RELEASED) <= set(offered)
    for arc in offered:
        stage_rows(arc)


@pytest.mark.parametrize("arc", _offered())
def test_every_judge_runs_on_every_flower_day_of_every_offered_arc(arc):
    rows = stage_rows(arc)
    for days in (42, 56, 63, 84):
        for day in range(0, days + 8):
            st = stage_intent(day, days, rows)
            for judge in brain_bridge.judges():
                ctx = K.ctx(judge.phases[0], flower_day=day, flower_days=days, stage=st, steering="generative")
                common(ctx)
                if judge.due(ctx, None):
                    judge.evidence(ctx)
                judge.decide({q: None for q in judge.questions}, ctx)
    assert "| stage |" in prompt.block_b(rows, arc)


def test_the_packs_preview_shows_the_numbers_the_judges_use():
    for arc in _offered():
        lines = [ln for ln in (pathlib.Path(prompt.PACK) / "arcs" / f"{arc}.md").read_text("utf-8").splitlines()
                 if ln.startswith("|")]
        head = [c.strip() for c in lines[0].strip("|").split("|")]
        table = [dict(zip(head, (c.strip() for c in ln.strip("|").split("|")))) for ln in lines[2:]]
        for row, pack in zip(stage_rows(arc), table, strict=True):
            for ours, theirs in (("dryback_points", "dryback_points"), ("pore_ec_range", "pore_ec"),
                                 ("runoff_pct", "runoff_pct")):
                lo, hi = row[ours]
                assert pack[theirs] == f"{lo:g}-{hi:g}", (arc, row["stage"], theirs)
            assert pack["steering"] == row["steering"]


ARC = """### Stage arc `planted`: a test arc (TEST)

| stage | flower_days | steering | peak | dryback_points | pore_ec | runoff_pct | move_on_when |
|---|---|---|---|---|---|---|---|
| veg |  | vegetative | high | 10-15 | 3-5 | 8-16 | ready |
| setting | 1-21 | generative | low | 15-25 | 5-10 | 1-7 | stretch slows |
| finish | last 14 days | ripening | low | 20-25 | 3-4 | 1-7 | maturity |
"""


@pytest.mark.parametrize("change, said", [
    (("5-10 | 1-7 | stretch", "stepping up | 1-7 | stretch"), "not a number range"),
    (("generative | low", "building | low"), "not one of"),
    (("| stretch slows |", "|  |"), "no sign"),
    (("| 1-21 |", "| 2-21 |"), "does not start on flower day 1"),
])
def test_an_arc_the_judges_could_not_read_is_refused_with_a_reason(tmp_path, change, said):
    (tmp_path / "planted.md").write_text(ARC, encoding="utf-8")
    rows = stage_rows("planted", pack=str(tmp_path))
    assert [r["days"] for r in rows] == [None, (1, 21), (22, 35)]
    assert rows[1]["source"] == "Stage arc `planted`: a test arc (TEST)"
    (tmp_path / "planted.md").write_text(ARC.replace(*change), encoding="utf-8")
    with pytest.raises(ArcInvalid, match=said):
        stage_rows("planted", pack=str(tmp_path))


def test_the_packs_rockwool_arc_is_refused_as_it_stands():
    with pytest.raises(ArcInvalid):
        stage_rows("rockwool_default")
    with pytest.raises(ArcInvalid, match="no stage arc"):
        stage_rows("none")
    assert doctrine.DEFAULT_ARC == "slab_default"
