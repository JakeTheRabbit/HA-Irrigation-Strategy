"""The minimum-daily floor, paced (ZoneParams.min_daily_volume, core.floor_share).

A zone whose probe sits in a wet spot reads wetter than its slab and is never topped up, though its plants drink
as much as the next row's. The floor puts its minimum through whatever the probe says: never in the morning dryback
(P0), then spread evenly over the day so the whole minimum is in min_floor_finish_h before lights-off, the
evening dryback. A zone behind at the end of P0 catches up in P1; every shot it gets counts toward it.
"""

import pytest

from crop_steering_engine.core import decide, floor_share
from test_core import P, S

LITRES_PER_PCT = 8.3 * 42 / 100.0  # a 1 % shot across a zone of 42 plants in 8.3 L slabs
FLOOR = 84.0  # 2 L a plant for 42 plants


def at(hour, **kw):
    """A lights-on (10:00 to 22:00) snapshot `hour` hours after lights-on."""
    return S(hours_since_lights_on=hour, hours_to_lights_off=12.0 - hour, **kw)


def test_the_line_runs_from_nothing_at_lights_on_to_all_of_it_three_hours_before_lights_off():
    p = P(min_daily_volume=FLOOR)
    assert floor_share(at(0), p) == 0.0
    assert floor_share(at(4.5), p) == pytest.approx(0.5)  # half of the 9 hours from 10:00 to 19:00
    assert floor_share(at(9), p) == 1.0
    assert floor_share(at(11), p) == 1.0  # past it: all of it, now
    assert floor_share(S(), p) == 1.0  # no clock: all of it, as the floor always was
    short_day = S(hours_since_lights_on=2, hours_to_lights_off=0.5)  # a day shorter than the margin
    assert floor_share(short_day, P(min_floor_finish_h=3)) == 1.0


def test_it_fires_only_when_the_zone_is_behind_the_line():
    p = P(min_daily_volume=FLOOR)
    behind = decide(at(4.5, vwc=55, daily_vol=30), p)  # 42 L due by now
    assert behind[2] is True and behind[4].kind == "min_daily"
    assert "MIN-DAILY floor 30.0<42.0 of 84.0L" in behind[4]
    ahead = decide(at(4.5, vwc=55, daily_vol=45), p)
    assert ahead[2] is False and ahead[4].kind == "idle"


def test_never_in_the_morning_dryback_however_far_behind():
    p = P(min_daily_volume=FLOOR)
    result = decide(at(0.7, phase="P0", vwc=62, peak_vwc=62, phase_minutes=40, daily_vol=0), p)
    assert result[2] is False, result[4]
    assert decide(at(0.8, phase="P2", vwc=55, daily_vol=0), p)[2] is True


def test_past_the_finish_it_fires_until_the_minimum_is_in_then_stops():
    p = P(min_daily_volume=FLOOR)
    assert decide(at(10.5, vwc=55, daily_vol=70), p)[2] is True
    assert decide(at(10.5, vwc=55, daily_vol=84), p)[2] is False


def test_the_drown_ceiling_and_the_spacing_still_hold_it():
    p = P(min_daily_volume=FLOOR, drown_ceiling=80)
    assert decide(at(8, vwc=80, daily_vol=0), p)[2] is False
    assert decide(at(8, vwc=55, daily_vol=0, minutes_since_shot=5), p)[2] is False
    assert decide(at(8, vwc=55, daily_vol=0, minutes_since_shot=10), p)[2] is True


def _day(probe_vwc, start_phase, ec=5.0):
    """A day from lights-on to lights-off, a minute at a time, with the probe stuck at `probe_vwc`: returns the
    (minute, kind, litres) of each shot, the phase at each minute and the (minute, phase, reason) of each move.
    It feeds the P1 rule as the controller does: its state starts again on the way into P1, `reached` latches
    on every tick in P1 at the ceiling, and each P1 shot records the peak before its water, counting as an extra
    shot once `reached` is set."""
    p = P(min_daily_volume=FLOOR)
    ceiling = min(p.p1_target, p.field_capacity)
    phase, phase_min, since, shots, daily = start_phase, 0.0, 600.0, 0, 0.0
    reached, before, extra = False, None, 0
    fired, phases, moves = [], [], []
    for m in range(12 * 60):
        if phase == "P1" and probe_vwc >= ceiling:
            reached = True
        s = at(m / 60.0, vwc=probe_vwc, peak_vwc=probe_vwc, ec=ec, ec_smooth=ec, phase=phase,
               phase_minutes=phase_min, minutes_since_shot=since, shot_count=shots, daily_vol=daily,
               lights_just_on=m == 0, p1_reached=reached, p1_peak_before_shot=before, p1_extra_shots=extra)
        new_phase, _thr, fire, size, reason = decide(s, p)
        if new_phase != phase:
            moves.append((m, new_phase, reason))
            phase, phase_min = new_phase, 0.0
            if new_phase == "P1":
                shots, reached, before, extra = 0, False, None, 0
        phases.append(phase)
        if fire:
            litres = size * LITRES_PER_PCT
            fired.append((m, reason.kind, litres))
            if phase == "P1":
                before = s.peak_vwc  # the peak before this shot's water went in
                if reached:
                    extra += 1
            daily, since, shots = daily + litres, 0.0, shots + 1
        else:
            since += 1.0
        phase_min += 1.0
    return fired, phases, moves


def test_a_probe_stuck_wet_still_gets_the_whole_minimum_spread_evenly_over_the_day():
    fired, phases, _moves = _day(probe_vwc=55, start_phase="P2")  # above the re-water point: never a top-up
    assert {kind for _m, kind, _l in fired} == {"min_daily"}
    assert sum(litres for _m, _k, litres in fired) >= FLOOR
    times = [m for m, _k, _l in fired]
    assert times[-1] <= 9 * 60  # all in by 19:00, three hours before lights-off
    assert len(times) == 5  # 5 shots of 17.4 L: nothing past the minimum
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert all(95 <= gap <= 130 for gap in gaps), gaps  # about every 1 h 52 min, not all in the morning


def test_a_zone_starting_in_p0_waits_out_the_dryback_then_catches_up():
    fired, phases, moves = _day(probe_vwc=62, start_phase="P0")  # P0 times out at 45 min; P1 is at its ceiling
    assert fired[0][0] >= 45 and all(phases[m] != "P0" for m, _k, _l in fired)
    # behind the line after the dryback, the floor catches up in P1
    assert any(k == "min_daily" and phases[m] == "P1" for m, k, _l in fired)
    # P1 ends by the rise rule (a stuck probe's peak cannot rise), not at max shots
    assert next(why for _m, to, why in moves if to == "P2").startswith("P1 full")
    # the rest is the floor's, spread through P2: all of it by 19:00 and nothing past it but the last floor shot,
    # where a P1 run to its maximum shots would pour well over the minimum
    assert all(k == "min_daily" for m, k, _l in fired if phases[m] == "P2")
    total = sum(litres for _m, _k, litres in fired)
    assert FLOOR <= total < FLOOR + P().p2_shot_size * LITRES_PER_PCT and fired[-1][0] <= 9 * 60
