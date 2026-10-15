"""The doctrine library: the owner's GrowLabs wiki as one-sentence rules the judges write into Jev's questions."""
import re

import pytest
from jev.doctrine import ALT_STAGE_ARC, ATHENA, RULES, SLAB, SOURCES, STAGE_ARC, Rule, doctrine, stage_intent

TOPICS = ("ramp", "dryback", "maintenance", "ec", "probe", "stage", "ripening", "closed_loop", "slab")
ALL = [(t, i, r) for t, rules in RULES.items() for i, r in enumerate(rules)]

# A moisture number (a % or points) must say how to read it: the wiki's numbers are true water content and the
# F2 probes read about 33-41 at saturation, so a raw band is never presented as the truth. "of the water fed"
# marks a runoff share and "of the substrate" a shot size: volumes, not probe readings.
NUMBER = re.compile(r"\d\s*(?:%|points?\b)")
MOISTURE = ("moisture", "water content", "vwc", "dryback", "field capacity", "full mark", "floor", "wetter", "drier")
CAVEATS = ("true water content", "relative", "own ", "of the substrate", "peak", "saturation", "of the water fed")


def test_every_topic_has_rules():
    assert set(TOPICS) <= set(RULES)
    for t in TOPICS:
        assert 5 <= len(RULES[t]) <= 16, t


def test_sources_are_the_seven_wiki_pages_then_athena_and_each_is_used():
    assert len(SOURCES) == len(set(SOURCES)) == 8 and SOURCES[-1] == ATHENA
    assert all(s.startswith("https://www.growlabs.nz/wiki/") and s.endswith(".html") for s in SOURCES[:-1])
    assert {r.source for _, _, r in ALL} == set(SOURCES)


def test_the_owners_rules_lead_every_topic_and_athena_follows():
    for t, rules in RULES.items():
        sources = [r.source for r in rules]
        first_athena = sources.index(ATHENA) if ATHENA in sources else len(sources)
        assert ATHENA not in sources[:first_athena] and all(s == ATHENA for s in sources[first_athena:]), t
    assert "owner's stage arc leads" in RULES["dryback"][-1].text


@pytest.mark.parametrize("topic,i,rule", ALL, ids=[f"{t}-{i}" for t, i, _ in ALL])
def test_each_rule_is_one_short_sourced_sentence(topic, i, rule):
    assert isinstance(rule, Rule)
    assert rule.source in SOURCES
    assert len(rule.text) < 300
    assert rule.text[0].isupper() and rule.text.endswith(".")
    assert not re.search(r"[.!?]\s", rule.text), "more than one sentence"


def test_no_rule_is_repeated():
    texts = [r.text for _, _, r in ALL]
    assert len(texts) == len(set(texts))


def test_moisture_numbers_are_never_raw_probe_truth():
    bad = [(t, r.text) for t, _, r in ALL
           if NUMBER.search(r.text.lower()) and any(w in r.text.lower() for w in MOISTURE)
           and not any(c in r.text.lower() for c in CAVEATS)]
    assert bad == []
    raw = "keep moisture between 55 and 92 % all day"  # the check bites on a bare band
    assert NUMBER.search(raw) and not any(c in raw for c in CAVEATS)


def test_doctrine_joins_the_topics_in_order():
    text = doctrine("ec", "ramp")
    assert text.startswith("Doctrine: ")
    assert all(r.text in text for r in RULES["ec"] + RULES["ramp"])
    assert text.index(RULES["ec"][-1].text) < text.index(RULES["ramp"][0].text)
    assert text == doctrine("ec", "ramp")  # stable
    assert doctrine("ec", "ramp", "ec") == text  # a topic named twice is used once


def test_doctrine_limit_keeps_the_first_rules_of_each_topic():
    text = doctrine("ec", "ramp", limit=2)
    for t in ("ec", "ramp"):
        assert RULES[t][0].text in text and RULES[t][1].text in text
        assert RULES[t][2].text not in text


def test_unknown_topic_is_an_error_and_no_topic_is_empty():
    with pytest.raises(KeyError):
        doctrine("nonsense")
    assert doctrine() == ""


def test_stage_arc_is_the_slab_guide_and_contiguous():
    assert all(row["source"] == SLAB for row in STAGE_ARC)
    assert all(row["source"] in SOURCES for row in ALT_STAGE_ARC)
    assert [row["steering"] for row in STAGE_ARC] == ["vegetative", "generative", "vegetative", "ripening"]
    flower = [row for row in STAGE_ARC if row["days"]]
    assert flower[0]["days"][0] == 1
    for a, b in zip(flower, flower[1:]):
        assert b["days"][0] == a["days"][1] + 1


def test_stage_intent_covers_the_arc_and_nothing_else():
    last = STAGE_ARC[-1]["days"][1]
    for day in range(1, last + 1):
        row = stage_intent(day)
        assert row is not None and row["days"][0] <= day <= row["days"][1], day
    assert stage_intent(1)["stage"] == stage_intent(21)["stage"] == "flower setting"
    assert stage_intent(22)["stage"] == stage_intent(42)["stage"] == "flower bulk"
    assert stage_intent(43)["stage"] == stage_intent(last)["stage"] == "finish"
    for day in (None, 0, -3, last + 1):
        assert stage_intent(day) is None


def test_a_longer_flower_keeps_the_bulk_until_the_final_fortnight():
    assert stage_intent(49, flower_days=63)["days"] == (22, 49)
    assert stage_intent(50, flower_days=63)["stage"] == "finish"
    assert stage_intent(50, flower_days=63)["days"] == (50, 63)
    assert stage_intent(60, flower_days=63)["stage"] == "finish"
    assert stage_intent(64, flower_days=63) is None


def test_stage_intent_hands_out_a_copy():
    row = stage_intent(5)
    row["steering"] = "changed"
    assert STAGE_ARC[1]["steering"] == "generative"
