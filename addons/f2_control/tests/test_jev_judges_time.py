"""The judges of the day's clock: dawn (when the ramp starts), dusk (when the watering stops) and night (whether an
overnight fall toward the emergency floor is the slab or the probe)."""
import json
from datetime import timedelta

import jev_kit as K
from jev import council
from jev.brain import Brain
from jev.client import Asker
from jev.judges.dawn import DawnJudge
from jev.judges.dusk import DuskJudge
from jev.judges.night import NightJudge
from jev.ledger import Ledger


# ------------------------------------------------------------------ helpers
def _brain(judge, answers, ledger=None):
    t = K.FakeTransport(answers)
    asker = Asker("acct", "tok", transport=t, threaded=False, clock=lambda: K.NOW.timestamp())
    return Brain(asker, ledger or Ledger(None), [judge], log=lambda *a: None), t


def _verdicts(name, answer, answer_b=None):
    return {name: council.combine(K.both(name, answer, answer_b), name)}


def _plain(value):
    """Words and single numbers only: no list anywhere with more than three numbers in it, and nothing but
    strings inside a list."""
    if isinstance(value, dict):
        return all(_plain(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return sum(isinstance(v, (int, float)) for v in value) <= 3 and all(isinstance(v, str) for v in value)
    return value is None or isinstance(value, (str, int, float, bool))


def _council_of_two(judge):
    for variants in judge.questions.values():
        assert len(variants) == 2
        assert variants[0]["instructions"] != variants[1]["instructions"]
        assert variants[0]["criteria"] == variants[1]["criteria"]


# dawn: P0 began `minutes` ago at `start`, drying `per_min` points a minute; yesterday dried 0.02 a minute at
# this time and its first ramp shot came 23 h ago
def _dawn_history(start=38.0, per_min=0.03, minutes=40, flat=False):
    pts = [(m, start if flat else start - per_min * (minutes - m), 3.2) for m in range(minutes, -1, -1)]
    pts += [(m, 37.0 + 0.02 * (m - 1440), 3.1) for m in range(1440, 1471)]
    return K.history(points=pts, shots=[(1380, 120, 31.0, 3.4, "p1_ramp"), (1360, 120, 33.0, 3.5, "p1_ramp")])


def _dawn_ctx(dryback=12.0, minutes=40.0, flat=False, peak=38.0):
    h = _dawn_history(minutes=int(minutes), flat=flat)
    vwc = h.readings[-1][1]
    s = K.snap(phase="P0", vwc=vwc, peak_vwc=peak, dryback_pct=dryback, phase_minutes=minutes, shot_count=0,
               minutes_since_shot=600.0, hours_to_lights_off=11.0, hours_to_lights_on=23.0)
    return K.ctx("P0", s=s, h=h, hours_to_on=23.0)


# dusk: 2 h to lights-off, 8 h to lights-on. Last night (22 h to 16 h ago) dried 0.4 points an hour; the last
# shot was 90 min ago and the zone has dried 0.8 points an hour since it settled, to 34.0 now
def _dusk_history(night_rate=0.4, day_rate=0.8, rescue=False):
    pts = [(m, 33.0 - night_rate * (1320 - m) / 60.0, 4.5) for m in range(1320, 959, -1)]
    pts += [(m, 34.0 + day_rate * m / 60.0, 4.6) for m in range(80, -1, -1)]
    shots = [(90, 120, 33.0, 4.7, "p2_topup")]
    if rescue:
        shots.append((30, 60, 34.4, 4.6, "p3_emergency"))
    return K.history(points=pts, shots=shots)


def _dusk_ctx(hours_to_off=2.0, vwc=34.0, h=None, phase="P2"):
    s = K.snap(phase=phase, vwc=vwc, peak_vwc=38.0, minutes_since_shot=90.0, hours_to_lights_off=hours_to_off,
               hours_to_lights_on=hours_to_off + 6.0, shot_count=9, daily_vol=60.0)
    return K.ctx(phase, s=s, h=h or _dusk_history(), hours_to_on=hours_to_off + 6.0)


# night: lights off 3 h ago (P3 for 180 min), 3 h to lights-on; tonight falling `rate` points an hour to 26.5,
# last night falling 0.3 at this hour from 28.0
def _night_history(rate=0.3, step_at=None, flat=False):
    def v(m):
        if flat:
            return 26.5
        return 26.5 + rate * m / 60.0 + (2.5 if step_at is not None and m > step_at else 0.0)
    pts = [(m, v(m), 4.8) for m in range(240, -1, -1)]
    pts += [(m, 28.0 + 0.3 * (m - 1440) / 60.0, 4.7) for m in range(1440, 1501)]
    return K.history(points=pts)


def _night_ctx(vwc=26.5, h=None, floor=25.0):
    s = K.snap(phase="P3", vwc=vwc, lights_on=False, phase_minutes=180.0, minutes_since_shot=300.0,
               hours_to_lights_on=3.0, hours_to_lights_off=21.0)
    return K.ctx("P3", s=s, h=h or _night_history(), p=K.params(p3_emergency_floor=floor), lights_on=False,
                 hours_to_on=3.0)


# ------------------------------------------------------------------ dawn
def test_dawn_is_asked_every_ten_minutes_in_p0_only():
    j, c = DawnJudge(), _dawn_ctx()
    assert j.due(c, None)
    assert not j.due(c, c.now - timedelta(minutes=5))
    assert j.due(c, c.now - timedelta(minutes=10))
    assert not j.due(K.ctx("P1", s=K.snap(phase="P1")), None)
    assert not j.due(K.ctx("P0", s=None), None)  # no usable probe
    _council_of_two(j)


def test_dawn_evidence_is_plain_facts():
    ev = DawnJudge().evidence(_dawn_ctx(dryback=12.0, minutes=40.0))
    for key in ("minutes_in_morning_dryback", "dryback_so_far", "dryback_from_start", "moisture_vs_rewater_threshold",
                "moisture_last_15_min", "moisture_last_30_min", "pore_ec_last_hour", "minutes_reading_unchanged",
                "yesterday_ramp_started", "same_time_yesterday"):
        assert key in ev, key
    assert _plain(ev) and json.dumps(ev)
    assert ev["minutes_in_morning_dryback"] == "40 of at most 120; the timer starts the ramp in 80 minutes"
    assert "over half way" in ev["dryback_so_far"]
    assert "falling 1.80 points an hour" in ev["moisture_last_30_min"]
    assert ev["yesterday_ramp_started"].startswith("the first ramp shot was at 14:00 with moisture at 31.0%")
    assert ev["same_time_yesterday"] == "VWC falling 1.20 points an hour at this time yesterday"


def test_dawn_evidence_says_when_the_peak_was_a_spike_and_when_the_probe_is_flat():
    spiked = DawnJudge().evidence(_dawn_ctx(peak=40.0))
    assert "free water, so that figure reads high" in spiked["dryback_from_start"]
    flat = DawnJudge().evidence(_dawn_ctx(flat=True, minutes=60.0))
    assert flat["minutes_reading_unchanged"] >= 60 and flat["moisture_last_30_min"] == "VWC flat"


def test_dawn_starts_the_ramp_only_on_a_firm_agreeing_council():
    j, c = DawnJudge(), _dawn_ctx()
    firm = _verdicts("dawn_call", K.choice_answer("start_ramp_now", {"start_ramp_now": 0.8, "keep_drying": 0.2}))
    d = j.decide(firm, c)
    assert (d.kind, d.value, d.judge) == ("advance", "P1", "dawn")
    split = _verdicts("dawn_call", K.choice_answer("start_ramp_now", {"start_ramp_now": 0.8}),
                      K.choice_answer("keep_drying", {"keep_drying": 0.7, "start_ramp_now": 0.3}))
    weak = _verdicts("dawn_call", K.choice_answer("start_ramp_now", {"start_ramp_now": 0.5, "keep_drying": 0.4}))
    wait = _verdicts("dawn_call", K.choice_answer("keep_drying", {"keep_drying": 0.9}))
    flat = _verdicts("dawn_call", K.choice_answer("probe_not_moving", {"probe_not_moving": 0.9}))
    for v in (split, weak, wait, flat, {"dawn_call": None}, {}):
        assert j.decide(v, c) is None


def test_dawn_through_the_brain_brings_the_ramp_forward():
    brain, t = _brain(DawnJudge(), K.both("dawn_call", K.choice_answer("start_ramp_now", {"start_ramp_now": 0.85})))
    out = brain.tick(_dawn_ctx(dryback=12.0, minutes=40.0))
    assert [(d.kind, d.value) for d, _ in out] == [("advance", "P1")]
    assert set(t.calls[0]["questions"]) == {"dawn_call__v0", "dawn_call__v1"}


def test_dawn_too_early_in_p0_is_refused_by_the_envelope():
    brain, t = _brain(DawnJudge(), K.both("dawn_call", K.choice_answer("start_ramp_now", {"start_ramp_now": 0.9})))
    assert brain.tick(_dawn_ctx(dryback=2.0, minutes=5.0)) == []
    assert len(t.calls) == 1  # asked, answered firmly, and still refused
    status = brain.zone_status("default", 1)["dawn"]
    assert status["directive"] == "advance P1" and status["why"].startswith("refused: dryback 2.0% under half")


# ------------------------------------------------------------------ dusk
def test_dusk_is_asked_only_in_p2_in_the_last_three_hours():
    j = DuskJudge()
    assert j.due(_dusk_ctx(hours_to_off=2.5), None)
    assert j.due(_dusk_ctx(hours_to_off=3.0), None)
    assert not j.due(_dusk_ctx(hours_to_off=4.0), None)
    assert not j.due(_dusk_ctx(hours_to_off=2.0, phase="P1"), None)
    c = _dusk_ctx()
    assert not j.due(c, c.now - timedelta(minutes=10)) and j.due(c, c.now - timedelta(minutes=15))
    _council_of_two(j)


def test_dusk_evidence_does_the_overnight_arithmetic():
    ev = DuskJudge().evidence(_dusk_ctx())
    for key in ("base_engine", "moisture_vs_rewater_threshold", "moisture_vs_emergency_floor",
                "overnight_dryback_target", "minutes_since_last_shot", "drying_since_last_shot", "last_night_drying",
                "if_watering_stops_now", "pore_ec_vs_day_target", "feed_vs_pore_ec", "shots_today", "water_today"):
        assert key in ev, key
    assert _plain(ev) and json.dumps(ev)
    assert ev["moisture_vs_rewater_threshold"] == "34.0%, 1.0 points above the re-water threshold of 33.0%"
    assert ev["moisture_vs_emergency_floor"] == "9.0 points above the overnight emergency floor of 25.0%"
    # 20 % down from a 38.0 peak is 30.4: 3.6 points still to lose
    assert ev["overnight_dryback_target"].endswith("which is 30.4% by lights-on: 3.6 points still to lose overnight")
    assert ev["drying_since_last_shot"] == "VWC falling 0.80 points an hour"
    assert ev["last_night_drying"] == "VWC falling 0.40 points an hour"
    # 34.0 - 0.8 x 2 h - 0.4 x 6 h = 30.0
    assert ev["if_watering_stops_now"].startswith("about 30.0% by lights-on")
    assert "past the overnight dryback target (30.4%)" in ev["if_watering_stops_now"]
    assert "5.0 points above the emergency floor (25.0%)" in ev["if_watering_stops_now"]


def test_dusk_evidence_says_what_it_cannot_estimate():
    h = K.history(points=[(m, 34.0, 4.6) for m in range(30, -1, -1)], shots=[(25, 60, 33.5, 4.6, "p2_topup")])
    ev = DuskJudge().evidence(_dusk_ctx(h=h))
    assert ev["drying_since_last_shot"] == "too soon after the last shot to tell"
    assert ev["last_night_drying"] == "unknown (no clean reading of last night)"
    assert ev["if_watering_stops_now"] == "can't be estimated: today's drying since the last shot is unknown"


def test_dusk_stops_the_day_only_on_a_firm_agreeing_council():
    j, c = DuskJudge(), _dusk_ctx()
    d = j.decide(_verdicts("dusk_call", K.choice_answer("enter_p3_now", {"enter_p3_now": 0.75})), c)
    assert (d.kind, d.value) == ("advance", "P3")
    split = _verdicts("dusk_call", K.choice_answer("enter_p3_now", {"enter_p3_now": 0.8}),
                      K.choice_answer("continue_p2", {"continue_p2": 0.6, "enter_p3_now": 0.4}))
    weak = _verdicts("dusk_call", K.choice_answer("enter_p3_now", {"enter_p3_now": 0.55, "continue_p2": 0.45}))
    topup = _verdicts("dusk_call", K.choice_answer("one_more_topup_then_p3", {"one_more_topup_then_p3": 0.9}))
    for v in (split, weak, topup, {}):
        assert j.decide(v, c) is None


def test_dusk_four_hours_out_is_not_even_asked():
    brain, t = _brain(DuskJudge(), K.both("dusk_call", K.choice_answer("enter_p3_now", {"enter_p3_now": 0.9})))
    assert brain.tick(_dusk_ctx(hours_to_off=4.0)) == [] and t.calls == []


def test_dusk_through_the_brain_brings_p3_forward_and_checks_it_two_hours_later():
    ledger = Ledger(None)
    answers = K.both("dusk_call", K.choice_answer("enter_p3_now", {"enter_p3_now": 0.8}))
    brain, _t = _brain(DuskJudge(), answers, ledger)
    out = brain.tick(_dusk_ctx())
    assert [(d.kind, d.value) for d, _ in out] == [("advance", "P3")]
    (entry,) = ledger.entries
    assert entry["check_at"] == (K.NOW + timedelta(minutes=120)).isoformat() and entry["check"]["vwc"] == 34.0
    later = K.ctx("P3", s=K.snap(phase="P3", vwc=31.0), h=_dusk_history(), now=K.NOW + timedelta(minutes=120))
    assert brain.tick(later) == []  # P3 cannot be brought forward again
    assert entry["outcome"]["good"] is True and "no rescue shot" in entry["outcome"]["what"]
    assert ledger.track("dusk", "default", 1).startswith("your last 1 call(s) of this kind worked 1 time(s)")


def test_dusk_near_the_emergency_floor_is_refused_by_the_envelope():
    brain, _t = _brain(DuskJudge(), K.both("dusk_call", K.choice_answer("enter_p3_now", {"enter_p3_now": 0.9})))
    assert brain.tick(_dusk_ctx(vwc=27.0)) == []
    assert "within 3 points of the P3 emergency floor" in brain.zone_status("default", 1)["dusk"]["why"]


def test_dusk_outcome_is_good_only_when_the_zone_coasted():
    j = DuskJudge()
    entry = {"check_at": K.NOW.isoformat(), "check": {"vwc": 34.0}}
    what, good = j.outcome(entry, K.ctx("P3", s=K.snap(phase="P3", vwc=30.0), h=_dusk_history()))
    assert good and what.startswith("2 h after the day's watering stopped VWC 30.0 (was 34.0)")
    _, low = j.outcome(entry, K.ctx("P3", s=K.snap(phase="P3", vwc=25.5), h=_dusk_history()))
    assert low is False
    what, rescued = j.outcome(entry, K.ctx("P3", s=K.snap(phase="P3", vwc=30.0), h=_dusk_history(rescue=True)))
    assert rescued is False and "1 rescue shot(s)" in what
    assert j.outcome(entry, K.ctx("P3", s=None)) is None  # no probe: wait


# ------------------------------------------------------------------ night
def test_night_is_asked_only_in_p3_near_the_emergency_floor():
    j = NightJudge()
    assert j.due(_night_ctx(vwc=26.5), None)
    assert j.due(_night_ctx(vwc=28.0), None)
    assert not j.due(_night_ctx(vwc=29.0), None)
    assert not j.due(K.ctx("P2", s=K.snap(vwc=26.0), p=K.params(p3_emergency_floor=25.0)), None)
    c = _night_ctx()
    assert not j.due(c, c.now - timedelta(minutes=15)) and j.due(c, c.now - timedelta(minutes=20))
    _council_of_two(j)


def test_night_evidence_compares_tonight_with_last_night():
    ev = NightJudge().evidence(_night_ctx())
    for key in ("moisture_vs_emergency_floor", "moisture_last_hour", "moisture_last_3_hours", "same_hour_last_night",
                "tonight_vs_last_night", "largest_step_last_3_hours", "minutes_reading_unchanged",
                "unchanged_reading_vs_last_night", "rescue_shots_tonight"):
        assert key in ev, key
    assert _plain(ev) and json.dumps(ev)
    assert ev["moisture_vs_emergency_floor"].startswith("1.5 points above the emergency floor of 25.0%")
    assert ev["same_hour_last_night"] == "28.0% at this time last night, VWC falling 0.30 points an hour"
    assert ev["tonight_vs_last_night"] == "falling at about the pace of this hour last night"
    assert ev["largest_step_last_3_hours"].endswith("(a smooth line)")
    # a slow fall holds one value for minutes on its own: not a frozen probe
    assert ev["unchanged_reading_vs_last_night"] == "no longer than last night's pace explains"
    assert ev["rescue_shots_tonight"] == ["none yet"]


def test_night_evidence_names_a_step_a_fast_fall_and_a_frozen_probe():
    step = NightJudge().evidence(_night_ctx(h=_night_history(step_at=30)))
    assert "(a sudden step)" in step["largest_step_last_3_hours"]
    fast = NightJudge().evidence(_night_ctx(h=_night_history(rate=1.5)))
    assert fast["tonight_vs_last_night"] == "falling 5.0 times as fast as at this hour last night"
    frozen = NightJudge().evidence(_night_ctx(h=_night_history(flat=True)))
    assert frozen["minutes_reading_unchanged"] >= 180 and frozen["tonight_vs_last_night"] == "not falling tonight"
    assert frozen["unchanged_reading_vs_last_night"].endswith("the reading looks frozen")


def test_night_evidence_shows_a_rescue_shot_and_how_the_probe_answered():
    h = _night_history()
    h.add_shot(K.history(shots=[(60, 60, 26.8, 4.8, "p3_emergency")]).shots[0])
    ev = NightJudge().evidence(_night_ctx(h=h))
    assert len(ev["rescue_shots_tonight"]) == 1 and "p3_emergency shot" in ev["rescue_shots_tonight"][0]


def test_night_alerts_only_on_a_firm_probe_fault():
    j, c = NightJudge(), _night_ctx()
    d = j.decide(_verdicts("night_drop", K.choice_answer("probe_fault", {"probe_fault": 0.8, "real_drying": 0.2})), c)
    assert d.kind == "alert" and d.value["code"] == "CS-703"
    assert d.value["title"] == "overnight low reading looks like a probe fault"
    msg = d.value["message"]
    assert "Zone 1" in msg and "26.5%" in msg and "25.0%" in msg and "rescue shot still fires as normal" in msg
    split = _verdicts("night_drop", K.choice_answer("probe_fault", {"probe_fault": 0.8}),
                      K.choice_answer("real_drying", {"real_drying": 0.7, "probe_fault": 0.3}))
    below_bar = _verdicts("night_drop", K.choice_answer("probe_fault", {"probe_fault": 0.65, "real_drying": 0.35}))
    real = _verdicts("night_drop", K.choice_answer("real_drying", {"real_drying": 0.95}))
    for v in (split, below_bar, real, {}):
        assert j.decide(v, c) is None


def test_night_through_the_brain_raises_the_alert_and_never_moves_a_phase():
    fault = K.both("night_drop", K.choice_answer("probe_fault", {"probe_fault": 0.9}))
    brain, _t = _brain(NightJudge(), fault)
    out = brain.tick(_night_ctx(h=_night_history(step_at=30)))
    assert [(d.kind, d.value["code"]) for d, _ in out] == [("alert", "CS-703")]
    real = K.both("night_drop", K.choice_answer("real_drying", {"real_drying": 0.9}))
    brain, _t = _brain(NightJudge(), real)
    assert brain.tick(_night_ctx()) == []
    brain, t = _brain(NightJudge(), fault)
    assert brain.tick(_night_ctx(vwc=30.0)) == [] and t.calls == []  # far from the floor: not asked
