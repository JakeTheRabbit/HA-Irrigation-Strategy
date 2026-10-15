"""next_shot_size: the size of a zone's next routine shot, as decide() would size it now.

The controller can add up a room's next round of shots to refill its reservoir before it runs short: in
the middle of a P1 ramp the next shot is bigger than the last, and once the ramp is done the next
one is P2's. Each size here is checked against the shot decide() actually fires."""

import pytest

from crop_steering_engine import decide, next_shot_size
from test_core import P, S


def fired(s, p):
    phase, _, fire, size, _ = decide(s, p)
    return phase, fire, size


@pytest.mark.parametrize("count", [0, 1, 2, 5])
def test_mid_ramp_the_next_shot_is_the_one_decide_fires_next(count):
    p = P(p1_initial=2, p1_incr=0.5, p1_max_shots=6, ec_target_p1=6)  # EC 6 on target: no scaling
    s = S(phase="P1", vwc=50, shot_count=count, minutes_since_shot=99)
    assert next_shot_size(s, p) == 2 + 0.5 * count
    assert fired(s, p) == ("P1", True, round(2 + 0.5 * count, 1))


def test_p0_plans_the_ramps_first_shot():
    p = P(p1_initial=2, p1_incr=0.5, ec_target_p1=6)
    assert next_shot_size(S(phase="P0", vwc=55, shot_count=4), p) == 2


def test_an_extra_shot_at_the_ceiling_is_ramp_sized_as_decide_fires_it():
    p = P(p1_initial=2, p1_incr=0.5, p1_max_shots=6, ec_target_p1=6)
    s = S(phase="P1", vwc=61, shot_count=3)  # P1 target 60, no extra shot yet
    assert next_shot_size(s, p) == 3.5
    assert fired(s, p) == ("P1", True, 3.5)


def test_a_ramp_that_is_done_plans_a_maintenance_shot():
    p = P(p1_max_shots=6, p1_min_shots=1, p2_shot_size=5, ec_target_p1=6, ec_target_p2=6)
    every = S(phase="P1", vwc=50, shot_count=6)
    full = S(phase="P1", vwc=61, shot_count=3, p1_reached=True, p1_extra_shots=1,
             peak_vwc=61, p1_peak_before_shot=60.8)  # the last shot raised the peak 0.2: P2
    assert decide(every, p)[0] == decide(full, p)[0] == "P2"
    assert next_shot_size(every, p) == next_shot_size(full, p) == 5


def test_p2_plans_its_maintenance_shot_scaled_by_ec_as_decide_does():
    p = P(p2_shot_size=5, ec_target_p2=6)
    s = S(phase="P2", vwc=40, ec=6.6, ec_smooth=6.6)  # 1.1 x target: a 1.2 x shot
    assert next_shot_size(s, p) == pytest.approx(6.0)
    assert fired(s, p)[2] == 6.0
    settled = S(phase="P2", vwc=40, ec=9.9, ec_settled=3.6)  # the settled EC, as decide() reads it
    assert next_shot_size(settled, p) == pytest.approx(5 * 0.7)


def test_p3_plans_a_rescue_sized_shot():
    assert next_shot_size(S(phase="P3", vwc=55, lights_on=False), P(p3_emergency_shot=2.5)) == 2.5


def test_lights_off_plans_the_rescue_shot_decide_moves_the_zone_to():
    p = P(p2_shot_size=5, p3_emergency_shot=2.5)
    assert next_shot_size(S(phase="P2", vwc=40, lights_on=False), p) == 2.5
