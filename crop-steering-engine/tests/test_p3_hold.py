"""P3 holds the overnight dryback at its target (opt-in, off by default).

P3 waters only below the rescue level, and the overnight dryback is read only by P2's early move to P3,
which can start the dryback sooner but never stop it. A night that dries faster than the day goes on past
the target to the rescue level (a 30% dryback from an 86.5% peak should end at 60.55%; drying 2.3 points
an hour from 74.2%, a zone was on course for about 51% by lights-on, with the next shot at a 50% rescue
level). With the hold on, each time a P3 zone dries to the day's peak less its overnight dryback it gets a
rescue-sized shot, the P3 time between shots apart. Off, every decision is the one it always was.
"""

import itertools

import pytest

from crop_steering_engine import CAP_EXEMPT, decide, waiting_for, zone_status_label
from crop_steering_engine.core import p3_dryback, p3_hold_level
from test_core import P, S

PEAK = dict(peak_vwc=86.5, lights_on=False, hours_to_lights_on=6)


def night(**snap):
    return S(phase="P3", **dict(PEAK, **snap))


def params(**kw):
    return P(**dict(dict(dryback_target=30, p3_emergency_floor=50, p3_emergency_shot=2, p3_hold=True), **kw))


def test_the_hold_level_is_the_peak_less_the_relative_dryback():
    assert p3_hold_level(night(vwc=70), params()) == pytest.approx(60.55)
    assert p3_hold_level(night(vwc=70, peak_vwc=0), params()) is None
    assert p3_hold_level(night(vwc=70), params(p3_hold=False)) is None


def test_a_zone_that_dries_to_its_dryback_target_gets_a_rescue_sized_shot():
    phase, _, fire, size, reason = decide(night(vwc=60.4), params())
    assert (phase, fire, size) == ("P3", True, 2)
    assert reason.kind == "p3_hold" and reason == "P3 hold dryback VWC 60.4<60.5 (30% of peak 86.5)"
    assert reason.cap_exempt is False and CAP_EXEMPT["p3_hold"] is False


@pytest.mark.parametrize("vwc", [74.2, 60.6, 60.55])
def test_nothing_fires_above_or_at_the_dryback_target(vwc):
    result = decide(night(vwc=vwc), params())
    assert result[2] is False and result[4].kind == "idle"


def test_below_the_rescue_level_the_rescue_fires_first_and_stays_exempt():
    result = decide(night(vwc=49), params())
    assert result[2] is True and result[4].kind == "p3_emergency" and result[4].cap_exempt is True


def test_the_p3_time_between_shots_spaces_the_hold_as_it_does_the_rescue():
    p = params(p3_time_between_min=10)
    for vwc, kind in ((60, "p3_hold"), (49, "p3_emergency")):
        assert decide(night(vwc=vwc, minutes_since_shot=9), p)[2] is False, kind
        assert decide(night(vwc=vwc, minutes_since_shot=10), p)[4].kind == kind


def test_the_daily_water_limit_holds_it_but_never_the_rescue():
    spent = dict(daily_vol=300)
    result = decide(night(vwc=60, **spent), params(max_daily_volume=300))
    assert result[2] is False and result[4].kind == "block_daily_cap"
    result = decide(night(vwc=49, **spent), params(max_daily_volume=300))
    assert result[2] is True and result[4].kind == "p3_emergency"


def test_a_held_plan_stops_it_but_never_the_rescue():
    assert decide(night(vwc=60, steering_held=True), params())[2] is False
    result = decide(night(vwc=49, steering_held=True), params())
    assert result[2] is True and result[4].kind == "p3_emergency"


def test_nothing_is_held_before_a_peak_has_been_seen():
    assert decide(night(vwc=55, peak_vwc=0), params())[2] is False


def test_only_p3_holds_the_dryback():
    assert decide(S(phase="P2", vwc=60, peak_vwc=86.5, minutes_since_shot=99), params(p2_threshold=55))[2] is False
    assert decide(S(phase="P0", vwc=60, peak_vwc=86.5, phase_minutes=5), params(p2_threshold=55))[2] is False


def test_lights_off_moves_a_zone_already_past_its_target_to_p3_and_holds_it_at_once():
    phase, _, fire, _, reason = decide(S(phase="P2", vwc=60, lights_on=False, peak_vwc=86.5), params(p2_threshold=55))
    assert (phase, fire, reason.kind) == ("P3", True, "p3_hold")
    assert reason == "lights-off -> P3 | P3 hold dryback VWC 60.0<60.5 (30% of peak 86.5)"


def test_lights_on_ends_the_night_without_a_hold_shot():
    phase, _, fire, _, _ = decide(night(vwc=60, lights_on=True, lights_just_on=True), params(p2_threshold=55))
    assert (phase, fire) == ("P0", False)


def test_the_zone_label_says_it_is_holding_the_dryback_not_an_emergency():
    _, _, fire, _, reason = decide(night(vwc=60.4), params())
    assert zone_status_label("P3", fire, None, False, reason) == "Holding dryback"
    _, _, fire, _, reason = decide(night(vwc=49), params())
    assert zone_status_label("P3", fire, None, False, reason) == "Emergency"


def test_waiting_for_names_the_hold_only_when_it_is_on():
    hold = next(i for i in waiting_for(night(vwc=70, minutes_since_shot=4), params(p3_time_between_min=10))
                if i["rule"] == "p3_hold")
    assert (hold["op"], hold["value"], hold["dryback"], hold["in_min"]) == ("<", 60.55, 30, 6.0)
    assert "p3_hold" not in [i["rule"] for i in waiting_for(night(vwc=70), params(p3_hold=False))]
    assert "p3_hold" not in [i["rule"] for i in waiting_for(night(vwc=70, steering_held=True), params())]


def test_the_overnight_dryback_is_its_own_target_when_given():
    """The shared dryback_target was both the P0 morning dryback and the overnight one. The overnight one
    can now be given on its own; without it, both read the shared one as before."""
    assert p3_dryback(params()) == 30
    p = params(p3_dryback_target=20)
    assert p3_dryback(p) == 20
    assert p3_hold_level(night(vwc=70), p) == pytest.approx(69.2)
    # P0 still reads the shared target: a 25% drop has not finished a 30% morning dryback.
    morning = S(phase="P0", vwc=64.9, peak_vwc=86.5, dryback_pct=25, phase_minutes=5)
    assert decide(morning, p)[0] == "P0"


# Every reading, phase and clock a zone can be in: off, the hold never fires, and turning it on changes a
# decision only by adding a hold shot where nothing was going to fire.
GRID = list(itertools.product(
    ("P0", "P1", "P2", "P3"), (30, 49, 55, 60.4, 61, 74.2), (0, 86.5), (True, False), (1, 9, 600), (False, True),
))


@pytest.mark.parametrize("phase,vwc,peak,lights_on,since,held", GRID)
def test_off_means_the_decisions_it_always_gave(phase, vwc, peak, lights_on, since, held):
    s = S(phase=phase, vwc=vwc, peak_vwc=peak, lights_on=lights_on, minutes_since_shot=since,
          steering_held=held, hours_to_lights_off=2, uptime_min=30)
    base = dict(dryback_target=30, p3_emergency_floor=50, p3_time_between_min=10)
    off, on = decide(s, P(**base)), decide(s, P(**base, p3_hold=True))
    assert off[4].kind != "p3_hold"
    assert "p3_hold" not in [i["rule"] for i in waiting_for(s, P(**base))]
    if on != off or on[4].kind != off[4].kind:
        assert on[4].kind == "p3_hold" and off[2] is False and off[4].kind == "idle"
        assert on[:2] == off[:2]
