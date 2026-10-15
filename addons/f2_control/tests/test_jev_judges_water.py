"""The water judges: salt (why pore EC moved, and the P2 EC steer's mode) and shot (did each shot land)."""
import re
from datetime import timedelta

import jev_kit as K
import pytest
from jev import council
from jev.brain import Brain
from jev.client import Asker
from jev.judges.salt import MODE, SaltJudge
from jev.judges.shot import CODE, ShotJudge
from jev.ledger import Ledger


# ------------------------------------------------------------------ helpers
def _verdicts(name, label, p=0.8, label_b=None):
    """The council's verdict on `name`: both phrasings answer `label` (or the second answers `label_b`)."""
    a = K.choice_answer(label, {label: p, "other": round(1 - p, 3)})
    b = None if label_b is None else K.choice_answer(label_b, {label_b: p, label: round(1 - p, 3)})
    return {name: council.combine(K.both(name, a, b), name)}


def _plain(v):
    """Words, counts, lists of words or {name: words}: never a series of numbers."""
    if isinstance(v, (str, bool, int, float)):
        return True
    if isinstance(v, dict):
        return all(isinstance(k, str) and isinstance(x, str) for k, x in v.items())
    if isinstance(v, list):
        return all(isinstance(x, str) for x in v)
    return False


def _plain_evidence(e):
    return all(re.fullmatch(r"[a-z][a-z0-9_]*", k) and _plain(v) for k, v in e.items())


def _salt_ctx(ec=4.4, target=4.5, points=None, shots=(), feed=3.0, phase="P2", now=K.NOW, **snap_over):
    s = K.snap(**{"phase": phase, "ec": ec, "ec_settled": ec, "ec_smooth": ec, **snap_over})
    h = K.history(points=[(m, 36.0, ec) for m in range(0, 400)] if points is None else points, shots=shots)
    return K.ctx(phase, s=s, p=K.params(ec_target_p2=target), h=h, feed_ec=feed, now=now)


def _salt_front_ctx():
    """A 15 L dilute at 10:30; pore EC 4.4 before it, 5.2 once the water had gone through."""
    pts = [(m, 36.0, 4.4 if m > 145 else 5.2) for m in range(0, 400)]
    return _salt_ctx(ec=5.2, points=pts, shots=[(150, 300, 36.0, 4.4, "p2_dilute")])


SHOTS = [(m, 200, 30.0, 4.0, "p2_topup") for m in (160, 120, 80, 40)]  # 10 L each at 10:20, 11:00, 11:40, 12:20


def _flat_history():
    """Four shots went in and the probe never moved: no rise, no EC change."""
    return K.history(points=[(m, 30.0, 4.0) for m in range(0, 240)], shots=SHOTS)


def _after(m):
    """21 minutes after the shot that started `m` minutes before NOW ended: that shot has settled."""
    return K.NOW - timedelta(minutes=m) + timedelta(seconds=200, minutes=21)


def _shot_ctx(now, h=None, **over):
    return K.ctx("P2", h=h or _flat_history(), now=now, **over)


def _audit(judge, ctx, label, p=0.8, label_b=None):
    """One shot audit: due, the evidence built, the council's answer decided."""
    assert judge.due(ctx, None)
    judge.evidence(ctx)
    return judge.decide(_verdicts("landing", label, p, label_b), ctx)


# ------------------------------------------------------------------ the questions
@pytest.mark.parametrize("judge", [SaltJudge(), ShotJudge()])
def test_every_question_is_asked_in_exactly_two_phrasings(judge):
    for name, variants in judge.questions.items():
        assert len(variants) == 2 and variants[0]["instructions"] != variants[1]["instructions"]
        assert variants[0]["criteria"] == variants[1]["criteria"]


def test_the_salt_doctrine_is_written_into_the_questions():
    for v in SaltJudge.questions["salt_cause"]:
        text = v["instructions"]
        assert "45 minutes" in text and "feed" in text
    assert "MORE flushing" in SaltJudge.questions["salt_cause"][0]["instructions"]
    assert set(SaltJudge.questions["salt_cause"][0]["criteria"]) == set(MODE)


# ------------------------------------------------------------------ (a) due
def test_salt_is_due_in_p2_only_with_a_settled_ec_and_every_30_minutes():
    j = SaltJudge()
    assert j.due(_salt_ctx(), None)
    assert not j.due(_salt_ctx(ec_settled=None), None)
    assert not j.due(_salt_ctx(phase="P1"), None)
    assert not j.due(_salt_ctx(phase="P3"), None)
    assert not j.due(K.ctx("P2", s=None), None)
    assert not j.due(_salt_ctx(), K.NOW - timedelta(minutes=20))
    assert j.due(_salt_ctx(), K.NOW - timedelta(minutes=30))


def test_shot_is_due_only_for_a_settled_shot_not_yet_judged():
    j = ShotJudge()
    assert not j.due(K.ctx("P2", h=K.history(points=[(m, 30.0, 4.0) for m in range(60)])), None)  # no shots
    h = K.history(points=[(m, 30.0, 4.0) for m in range(60)], shots=[(10, 200, 30.0, 4.0, "p2_topup")])
    assert not j.due(K.ctx("P2", h=h), None)  # still settling
    later = K.NOW + timedelta(minutes=20)
    assert j.due(K.ctx("P2", h=h, now=later), None)
    assert not j.due(K.ctx("P2", h=h, now=later, s=None), None)  # no usable probe
    assert not j.due(K.ctx("P2", h=h, now=later), later - timedelta(minutes=5))  # inside the cadence


def test_shot_waits_for_the_answer_it_asked_for_and_asks_again_if_it_is_lost():
    j = ShotJudge()
    c = _shot_ctx(_after(40))
    assert j.due(c, None)
    j.evidence(c)
    assert not j.due(_shot_ctx(_after(40) + timedelta(minutes=15)), None)  # the answer is still to come
    assert j.due(_shot_ctx(_after(40) + timedelta(minutes=31)), None)  # lost: ask again


# ------------------------------------------------------------------ (b) evidence
def test_salt_evidence_is_plain_words_and_reads_the_salt_front():
    c = _salt_front_ctx()
    e = SaltJudge().evidence(c)
    assert _plain_evidence(e)
    for key in ("settled_pore_ec_vs_target", "pore_ec_last_hour", "pore_ec_last_6_hours",
                "pore_ec_after_the_last_flush", "feed_vs_pore_ec", "moisture_vs_field_capacity",
                "water_today", "max_ec", "target_vs_what_was_reached"):
        assert key in e
    assert "rose after the water went in" in e["pore_ec_after_the_last_flush"]
    assert "4.40 before, 5.20 45 minutes after" in e["pore_ec_after_the_last_flush"]
    assert "above the band" in e["settled_pore_ec_vs_target"] and "4.05 and 4.95" in e["settled_pore_ec_vs_target"]
    assert "is lower than pore EC" in e["feed_vs_pore_ec"]
    assert "steady" in e["pore_ec_steps_away_from_shots"]  # the rise came with the water, not a jump


def test_salt_evidence_says_when_the_target_cannot_be_reached():
    # 26 Sep 2026: a target of 6.0 against a pore EC of 2.55 that never moved, fed at 3.0
    pts = [(m, 36.0, 2.5 + (m % 3) * 0.05) for m in range(0, 400)]
    e = SaltJudge().evidence(_salt_ctx(ec=2.55, target=6.0, points=pts, feed=3.0))
    assert "far above anything reached" in e["target_vs_what_was_reached"]
    assert "cannot lower pore EC" in e["feed_vs_pore_ec"]
    assert "below the band" in e["settled_pore_ec_vs_target"]


def test_salt_evidence_follows_the_feed():
    j = SaltJudge()
    assert "not known yet" in j.evidence(_salt_ctx())["feed_ec_change"]
    j.due(_salt_ctx(feed=2.4, now=K.NOW - timedelta(hours=3)), None)
    assert "risen 0.60" in j.evidence(_salt_ctx(feed=3.0))["feed_ec_change"]


def test_shot_evidence_is_plain_words_about_that_shot():
    # a 10 L shot at 12:20: spiked +3, kept +2, pore EC fell toward the 3.0 feed
    pts = [(m, 30.0 if m > 37 else 33.0 if m >= 32 else 32.0, 4.0 if m > 37 else 3.6 if m >= 32 else 3.5)
           for m in range(0, 120)]
    h = K.history(points=pts, shots=[(40, 200, 30.0, 4.0, "p2_topup")])
    c = K.ctx("P2", h=h, s=K.snap(vwc=32.0), siblings={2: {"rise": 1.4, "rise_words": "retained +1.4 points (normal)"}})
    j = ShotJudge()
    assert j.due(c, None)
    e = j.evidence(c)
    assert _plain_evidence(e)
    assert e["shot"] == "12:20 p2_topup shot of 200 s, 10.0 L"
    assert e["before_the_shot"] == "VWC 30.0%, pore EC 4.00 mS/cm"
    assert e["spike_first_10_min"] == "+3.0 points at the highest"
    assert e["retained_rise_at_20_min"].startswith("+2.0 points kept")
    assert "toward the feed EC 3.00" in e["pore_ec_move_at_20_min"]
    assert e["typical_retained_rise"] == "2.00 points per shot today"
    assert e["sibling_zones_latest_shot"] == {"zone 2": "retained +1.4 points (normal)"}
    assert e["moisture_now_vs_before_the_shot"] == "+2.0 points, no shot since"
    assert e["minutes_since_it_ended"] == 37


# ------------------------------------------------------------------ (c) salt decide
@pytest.mark.parametrize("label,mode", [
    ("salts_accumulating", "steer"), ("salt_front_passing", "steer"),
    ("feed_changed", "hold"), ("in_band", "hold"),
    ("probe_suspect", "decay"), ("target_unreachable", "decay"),
])
def test_every_salt_cause_maps_to_an_ec_mode(label, mode):
    c = _salt_ctx()
    d = SaltJudge().decide(_verdicts("salt_cause", label), c)
    assert (d.judge, d.kind, d.value) == ("salt", "ec_mode", mode)
    assert label in d.why and d.expires == c.now + timedelta(minutes=45)


def test_salt_does_nothing_when_the_council_is_not_firm():
    c, j = _salt_ctx(), SaltJudge()
    assert j.decide(_verdicts("salt_cause", "salt_front_passing", 0.8, "probe_suspect"), c) is None  # disagree
    assert j.decide(_verdicts("salt_cause", "salt_front_passing", 0.55), c) is None  # not sure enough
    assert j.decide({"salt_cause": None}, c) is None
    assert j.decide({}, c) is None


# ------------------------------------------------------------------ (d) shot decide
def test_two_misses_in_a_row_raise_cs701_and_a_landing_resets_the_count():
    j = ShotJudge()
    assert _audit(j, _shot_ctx(_after(160)), "not_reaching_zone") is None  # the first miss: no alert
    c = _shot_ctx(_after(120))
    d = _audit(j, c, "not_reaching_zone")
    assert (d.judge, d.kind) == ("shot", "alert") and CODE == "CS-701"
    assert d.value["code"] == "CS-701" and d.value["title"] == "water isn't reaching this zone"
    assert d.value["message"] == ("The last two shots on Zone 1 at 10:20 and 11:00 put in 10.0 L and 10.0 L and "
                                  "moisture did not rise; check the zone's valve, drippers and line; watering "
                                  "carries on as normal.")
    assert _audit(j, _shot_ctx(_after(80)), "landed") is None  # reset
    assert _audit(j, _shot_ctx(_after(40)), "not_reaching_zone") is None  # a first miss again


def test_an_unsure_or_split_council_never_counts_as_a_miss():
    j = ShotJudge()
    assert _audit(j, _shot_ctx(_after(160)), "not_reaching_zone") is None
    assert _audit(j, _shot_ctx(_after(120)), "not_reaching_zone", 0.55) is None  # not sure enough
    assert _audit(j, _shot_ctx(_after(80)), "not_reaching_zone", 0.8, "landed_slow") is None  # split
    assert _audit(j, _shot_ctx(_after(40)), "not_reaching_zone") is None  # only one in a row


def test_each_shot_is_judged_once():
    j = ShotJudge()
    _audit(j, _shot_ctx(_after(160)), "not_reaching_zone")
    c = _shot_ctx(_after(120))
    assert j.due(c, None)
    j.evidence(c)
    v = _verdicts("landing", "not_reaching_zone")
    first = j.decide(v, c)
    assert j.decide(v, c) is first  # the brain reads the same answer again: the same decision, not a third miss
    assert not j.due(_shot_ctx(_after(120) + timedelta(minutes=15)), None)  # nothing new to judge
    assert j.due(_shot_ctx(_after(80)), None)  # the next shot


def test_shots_are_counted_per_zone():
    j = ShotJudge()
    _audit(j, _shot_ctx(_after(160)), "not_reaching_zone")
    assert _audit(j, _shot_ctx(_after(120), zone=2, title="Zone 2"), "not_reaching_zone") is None


# ------------------------------------------------------------------ (e) through the brain
def test_the_brain_admits_the_salt_mode_in_p2_and_the_envelope_refuses_it_in_p1():
    t = K.FakeTransport(K.both("salt_cause", K.choice_answer("salt_front_passing",
                                                             {"salt_front_passing": 0.8, "probe_suspect": 0.2})))
    asker = Asker("acct", "tok", transport=t, threaded=False, clock=lambda: K.NOW.timestamp())
    brain = Brain(asker, Ledger(None), [SaltJudge()], log=lambda *a: None)
    out = brain.tick(_salt_front_ctx())
    assert [(d.kind, d.value) for d, _ in out] == [("ec_mode", "steer")]
    assert set(t.calls[0]["questions"]) == {"salt_cause__v0", "salt_cause__v1"}
    assert "pore_ec_after_the_last_flush" in t.calls[0]["state"]
    [entry] = brain.ledger.entries
    assert entry["label"] == "steer" and entry["check"]["ec"] == 5.2
    assert entry["check_at"] == (K.NOW + timedelta(hours=4)).isoformat()

    assert brain.tick(_salt_ctx(ec=5.2, phase="P1")) == []  # the same answer, now in P1
    # The brain stops an answer outside its judge's phases before the envelope (which refuses it too).
    assert brain.zone_status("default", 1)["salt"]["why"] == "waiting for its phase"
    assert not __import__("jev.envelope", fromlist=["admit"]).admit(
        brain.state[("default", 1, "salt")].directive, _salt_ctx(ec=5.2, phase="P1"))[0]
    assert len(t.calls) == 1  # never asked in P1


def test_the_brain_raises_cs701_once_per_run_and_asks_once_per_shot():
    t = K.FakeTransport(K.both("landing", K.choice_answer("not_reaching_zone",
                                                          {"not_reaching_zone": 0.85, "landed": 0.15})))
    clock = {"t": 0.0}
    asker = Asker("acct", "tok", transport=t, threaded=False, clock=lambda: clock["t"])
    brain = Brain(asker, Ledger(None), [ShotJudge()], log=lambda *a: None)
    h = _flat_history()

    def tick(now):
        clock["t"] = now.timestamp()
        return brain.tick(_shot_ctx(now, h))

    assert tick(_after(160)) == []
    [(d, why)] = tick(_after(120))
    assert d.kind == "alert" and d.value["code"] == "CS-701" and why == "alerts never move water"
    assert t.calls[1]["state"]["shot"] == "11:00 p2_topup shot of 200 s, 10.0 L"
    tick(_after(120) + timedelta(minutes=15))  # nothing new to judge
    assert len(t.calls) == 2 and len(brain.ledger.entries) == 1


# ------------------------------------------------------------------ (f) salt outcome
def test_the_salt_outcome_is_good_when_pore_ec_moved_toward_the_target_or_stayed_in_band():
    j = SaltJudge()
    toward, good = j.outcome({"label": "steer", "check": {"ec": 6.0}}, _salt_ctx(ec=5.2))
    assert good and "moved toward the target" in toward and "(was 6.00)" in toward
    stayed, good = j.outcome({"label": "hold", "check": {"ec": 4.4}}, _salt_ctx(ec=4.6))
    assert good and "inside the band" in stayed


def test_the_salt_outcome_is_bad_when_pore_ec_moved_away():
    what, good = SaltJudge().outcome({"label": "steer", "check": {"ec": 5.0}}, _salt_ctx(ec=5.6))
    assert not good and "moved away from the target" in what


def test_the_salt_outcome_waits_without_a_reading():
    assert SaltJudge().outcome({"label": "steer", "check": {"ec": 5.0}}, K.ctx("P2", s=None)) is None
