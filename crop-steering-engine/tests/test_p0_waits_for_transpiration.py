"""P0 waits for the plants to transpire (issue #195).

The overnight dryback always leaves the slab under the daytime re-water point, so a P0 that ended at that point
ended about a minute after lights-on and the ramp watered plants that were not drinking yet. P0 now ends early
only at the rescue floor (p3_emergency_floor), the level under which a zone is in danger of drying out; otherwise
it ends by its own rules: the dryback since lights-on, the stall exit or the maximum wait.
"""

from crop_steering_engine import decide, waiting_for
from test_core import P, S

# The issue's room: peak 71.5 yesterday, 46.9 at lights-on after the overnight dryback, a 57 re-water point,
# a rescue floor under that, a 40 % generative dryback target and a 150 minute maximum wait.
LIGHTS_ON_VWC = 46.9


def _room(**kw):
    return P(p1_target=69, p2_threshold=57, p3_emergency_floor=40, dryback_target=40, p0_max_wait_min=150, **kw)


def _p0(vwc, minutes, peak=LIGHTS_ON_VWC, rate=0.5):
    """A P0 snapshot as the controller takes it: the peak is the highest reading since lights-on."""
    return S(phase="P0", vwc=vwc, peak_vwc=peak, dryback_pct=(peak - vwc) / peak * 100, dryback_rate=rate,
             phase_minutes=minutes, minutes_since_shot=600)


def test_the_issue_morning_stays_in_p0_under_the_re_water_point():
    p = _room()
    for minutes in (1, 2, 30, 90, 149):
        phase, _thr, fire, _size, reason = decide(_p0(LIGHTS_ON_VWC - minutes * 0.01, minutes), p)
        assert (phase, fire) == ("P0", False), (minutes, str(reason))
        assert "bypass" not in str(reason)


def test_the_issue_morning_ends_at_the_maximum_wait():
    phase, _thr, fire, _size, reason = decide(_p0(45.4, 150), _room())
    assert phase == "P1" and fire
    assert str(reason).startswith("P0 timeout 150min")


def test_the_issue_morning_ends_by_its_dryback_since_lights_on():
    p = _room(p0_additional_dryback=3)
    assert decide(_p0(LIGHTS_ON_VWC * 0.98, 40), p)[0] == "P0"
    phase, _thr, fire, _size, reason = decide(_p0(LIGHTS_ON_VWC * 0.97 - 0.01, 50), p)
    assert phase == "P1" and fire
    assert str(reason).startswith("P0 dryback done 3%")


def test_the_stall_exit_still_ends_p0():
    phase, _thr, _fire, _size, reason = decide(_p0(46.8, 40, rate=0.0), _room(p0_stall_exit=True))
    assert phase == "P1" and str(reason).startswith("P0 stalled")


def test_a_zone_at_or_under_the_rescue_floor_bypasses_at_once_and_gets_water():
    p = _room(p0_min_wait_min=60)
    for vwc in (40.0, 39.4, 25.0):
        phase, _thr, fire, size, reason = decide(_p0(vwc, 1, peak=vwc), p)
        assert phase == "P1" and fire and size > 0, vwc
        assert str(reason).startswith(f"P0 emergency bypass VWC {vwc:.0f}<=floor 40")


def test_just_over_the_rescue_floor_waits():
    assert decide(_p0(40.4, 1, peak=40.4), _room())[0] == "P0"


def test_waiting_for_shows_the_rescue_floor_as_the_p0_bypass():
    p = _room()
    s = _p0(LIGHTS_ON_VWC, 1)
    item = next(i for i in waiting_for(s, p) if i["rule"] == "p0_bypass")
    assert item["value"] == p.p3_emergency_floor and item["op"] == "<="
    assert decide(s, p)[0] == "P0"
    assert decide(_p0(p.p3_emergency_floor, 1), p)[0] == "P1"
