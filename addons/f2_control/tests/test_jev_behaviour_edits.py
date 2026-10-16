"""What the Claude brain changes in the shared judge code, and what it leaves exactly as it was (haiku-brain-design
section 15, test_jev_behaviour_edits): the judges' phrasings, the doctrine topics each one carries, the acting
judges, and the day's stage on the default arc."""
import sys

import jev_bridge
import jev_kit as K
from jev import council

TOPICS = {  # each judge's with_doctrine(...) call, as written at its call site
    "dawn": ("dryback", "stage", "probe", "closed_loop"), "dusk": ("dryback", "stage", "maintenance"),
    "night": ("dryback", "closed_loop", "probe"), "probe": ("probe", "closed_loop"),
    "channel": ("probe", "ramp"), "ramp": ("ramp", "probe", "ec"), "salt": ("ec", "closed_loop", "stage", "maintenance"),
    "setpoints": ("maintenance", "ec"), "shot": ("probe", "maintenance", "ramp"),
    "stage": ("stage", "ripening", "dryback", "ec", "closed_loop"), "zones": ("probe", "maintenance", "slab"),
    "balance": ("maintenance", "slab"), "targets": ("ramp", "dryback", "maintenance"), "shotsize": ("ramp", "maintenance"),
}


def test_each_judge_keeps_its_phrasing_and_names_its_doctrine_topics():
    for judge in jev_bridge.judges():
        for variants in judge.questions.values():
            for v in variants:
                assert v["instructions"].startswith(v["base_instructions"] + " Doctrine: ")
                assert v["doctrine_topics"] == TOPICS[judge.name], judge.name


def test_the_acting_judges_are_those_whose_answers_can_act():
    acting = set()
    for judge in jev_bridge.judges():
        src = open(sys.modules[type(judge).__module__].__file__, encoding="utf-8").read()
        if any(f'directive(ctx, "{kind}"' in src for kind in ("advance", "distrust", "ec_mode", "setpoint")) or (
                "directive(ctx, self.kind" in src and judge.kind in ("targets", "shot_size")):
            acting.add(judge.name)
    assert acting == set(jev_bridge.ACTING_JUDGES)


def test_council_keeps_each_phrasings_reason():
    answers = K.both("q", {**K.choice_answer("keep"), "rationale": "one"}, {**K.choice_answer("keep"), "rationale": "two"})
    assert council.combine(answers, "q").notes == ["one", "two"]
    assert council.combine(K.both("q", K.choice_answer("keep")), "q").notes == []

