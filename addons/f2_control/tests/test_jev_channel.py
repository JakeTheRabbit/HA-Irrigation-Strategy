"""The channel judge: water bypassing the substrate or the probe, or plants drinking less.

Code asks it only on its own two signs (shots that spike and fall back; a zone drinking under 40 % of the room's
typical water per plant, counted once the room drinks a tenth of a plant's substrate), so the trigger scales with
plant count and pot size. Its only directive is the CS-710 alert, and its latest answer reaches the probe judge.
"""
from datetime import timedelta
from types import SimpleNamespace

import jev_bridge
import jev_kit as K
from jev import council
from jev.envelope import admit
from jev.judges.channel import CHANNEL_MIN_DRINK_FRAC, CODE, ChannelJudge, fell_back, signs, under_drinking
from jev.judges.probe import ProbeJudge
from test_controller import _build


def _verdicts(label, p=0.8):
    answer = K.choice_answer(label, {label: p, "no_channeling": round(1 - p, 3)})
    return {"signature": council.combine(K.both("signature", answer), "signature")}


def _small(pot_l, zone_l=0.3, other_l=1.6, plants=4):
    """One room of two zones, four plants each on `pot_l` L pots: this zone drank `zone_l` L today, the other
    `other_l` L, so the room's median zone drinks under the engine's 5 L under-drinker floor."""
    sib = {2: {"litres_per_plant": other_l / plants}}
    return K.ctx("P2", s=K.snap(daily_vol=zone_l), h=K.history(points=[(m, 36.0, 4.4) for m in range(60)]),
                 siblings=sib, plants=plants, substrate_l=pot_l * plants)


def _spike_and_fall():
    """Four shots of 10 L: the first two rose and held 2 points, the last two spiked 2 points and fell back."""
    pts = []
    for m in range(240, -1, -1):
        v = 30.0
        for start, keeps in ((200, True), (160, True), (120, False), (80, False)):
            end = start - 200 / 60
            if m <= end:
                v += 2.0 if keeps else (2.0 if end - m <= 8 else 0.1)
        pts.append((m, v, 4.4))
    shots = [(200, 200, None, 4.4, "p2_topup"), (160, 200, None, 4.4, "p2_topup"),
             (120, 200, None, 4.4, "p2_topup"), (80, 200, None, 4.4, "p2_topup")]
    h = K.history(points=pts, shots=shots)
    for sh in h.shots:  # the reading just before each shot
        sh.pre_vwc = h.at(sh.start, tolerance_min=1.5)[1]
    return K.ctx("P2", h=h, plants=4, substrate_l=40.0)


# ------------------------------------------------------------------ the questions
def test_every_question_is_asked_in_exactly_two_phrasings():
    for _name, variants in ChannelJudge.questions.items():
        assert len(variants) == 2 and variants[0]["instructions"] != variants[1]["instructions"]
        assert variants[0]["criteria"] == variants[1]["criteria"]
        assert "channeling" in variants[0]["instructions"].lower()


def test_the_judge_is_built_and_selectable():
    assert "channel" in jev_bridge.ALL
    assert "channel" in [j.name for j in jev_bridge.judges()]


# ------------------------------------------------------------------ the trigger
def test_the_under_drinker_trigger_fires_on_a_small_install_of_2_litre_pots():
    c = _small(2.0)
    mine, typical, ratio, _basis = under_drinking(c)
    assert round(mine, 3) == 0.075 and typical == 0.4 and ratio < 0.4
    assert typical * 4 * 2 < 5.0  # the room's median zone drinks under the engine's own 5 L floor
    assert ChannelJudge().due(c, None)
    assert "on 2.0 L of substrate a plant" in signs(c)[0]


def test_the_under_drinker_trigger_scales_with_substrate_per_plant():
    # The room drinks 0.4 L a plant: over a tenth of a 3 L pot, under a tenth of a 10 L one (too little yet).
    assert CHANNEL_MIN_DRINK_FRAC * 3.0 < 0.4 < CHANNEL_MIN_DRINK_FRAC * 10.0
    assert ChannelJudge().due(_small(3.0), None)
    assert under_drinking(_small(10.0)) is None and not ChannelJudge().due(_small(10.0), None)
    # Ten times the plants on the same pots drink ten times the water: the same per-plant call.
    assert ChannelJudge().due(_small(2.0, zone_l=3.0, other_l=16.0, plants=40), None)


def test_a_zone_drinking_like_the_room_is_not_asked():
    assert not ChannelJudge().due(_small(2.0, zone_l=1.4), None)
    assert not ChannelJudge().due(_small(2.0, plants=4, zone_l=0.3, other_l=0.1), None)  # under 50 mL a plant


def test_shots_that_spike_and_fall_back_make_code_ask():
    c = _spike_and_fall()
    assert fell_back(c) == (2, 4)
    assert ChannelJudge().due(c, None)
    assert signs(c)[0].startswith("2 of the last 4 shots spiked and fell back")


def test_asked_only_with_lights_on_and_at_most_hourly():
    c = _small(2.0)
    j = ChannelJudge()
    assert not j.due(K.replace(c, lights_on=False), None)
    assert not j.due(c, K.NOW - timedelta(minutes=50))
    assert j.due(c, K.NOW - timedelta(minutes=60))
    assert j.due(K.replace(c, phase="P0"), None) and j.due(K.replace(c, phase="P3"), None)


# ------------------------------------------------------------------ the answer
def test_a_firm_bypass_raises_cs_710_with_a_catch_test_and_never_moves_water():
    c = _small(2.0)
    j = ChannelJudge()
    e = j.evidence(c)
    assert e["code_saw"] and e["substrate_per_plant"] == "2.0 L"
    d = j.decide(_verdicts("channeling_through_slab"), c)
    assert (d.judge, d.kind, d.value["code"]) == ("channel", "alert", CODE) and CODE == "CS-710"
    assert d.value["title"] == "water can bypass the substrate or the probe"
    assert "catch test" in d.value["message"] and "Do not increase the shot size" in d.value["message"]
    assert admit(d, c, confirmed=1, evidence_ok=True) == (True, "alerts never move water")


def test_no_channeling_or_an_unsure_answer_raises_nothing():
    c = _small(2.0)
    assert ChannelJudge().decide(_verdicts("no_channeling"), c) is None
    assert ChannelJudge().decide(_verdicts("insufficient_evidence"), c) is None
    assert ChannelJudge().decide(_verdicts("channeling_at_probe", p=0.5), c) is None


def test_its_latest_answer_reaches_the_probe_judge():
    c = _small(2.0)
    j = ChannelJudge()
    brain = SimpleNamespace(judges=[ProbeJudge(), j])
    assert jev_bridge.channel_words(brain, "default", 1, K.NOW) is None
    j.decide(_verdicts("channeling_at_probe"), c)
    words = jev_bridge.channel_words(brain, "default", 1, K.NOW + timedelta(hours=1))
    assert words.startswith("channeling_at_probe (p 0.80) at 13:00: Water runs down past the probe")
    probe = ProbeJudge().evidence(K.replace(c, channel=words))
    assert probe["channel_judge_latest"] == words
    assert "channel_judge_latest" not in ProbeJudge().evidence(c)
    assert jev_bridge.channel_words(brain, "default", 1, K.NOW + timedelta(hours=7)) is None  # stale
    assert jev_bridge.channel_words(brain, "default", 2, K.NOW) is None
    assert jev_bridge.channel_words(SimpleNamespace(judges=[ProbeJudge()]), "default", 1, K.NOW) is None


def test_the_controller_raises_cs_710_as_a_zone_card():
    c, fake = _build({"num_zones": 1})
    c._jev_alert(c.rooms[0], 1, "channel", {"code": CODE, "title": "water may be bypassing the substrate or the"
                                            " probe", "message": "Do a catch test."})
    [card] = [d for dom, svc, d in fake.calls if (dom, svc) == ("persistent_notification", "create")]
    assert card["notification_id"] == "f2_jev_channel_default_z1" and card["title"].endswith("(CS-710)")
