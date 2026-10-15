"""P0 additional dryback: the small extra dryback before the first shot, as a % below the highest
reading since lights-on. 0 is off: P0 then waits for the dryback target, its timeout or the
maintenance trigger, exactly as before, so a room that never sets it decides P0 as it always has.
"""

from crop_steering_engine import decide, p0_dryback, validate_params, waiting_for
from test_core import P, S

PEAK = 60.5


def _p0(vwc, minutes):
    """A P0 snapshot whose dryback is measured from the lights-on reading, as the controller does."""
    return S(
        phase="P0",
        vwc=vwc,
        peak_vwc=PEAK,
        dryback_pct=(PEAK - vwc) / PEAK * 100,
        phase_minutes=minutes,
    )


# A grow-day's morning, one reading every 10 minutes from lights-on: the slab dries slowly,
# then faster as the plants start drinking.
DROPS = [0, 0.3, 0.8, 1.4, 1.9, 2.6, 3.4, 4.3, 5.2, 6.4, 7.7, 9.1, 10.6]
MORNING = [(minutes, PEAK - drop) for minutes, drop in zip(range(0, 130, 10), DROPS)]

# Today's P0 (before the setting existed) with a 20 % dryback target and a 120 minute timeout: only the
# timeout ends it. Pinned, so off can never drift from it.
TODAY = ["P0"] * 12 + ["P1"]


def _day(p):
    return [decide(_p0(vwc, minutes), p)[0] for minutes, vwc in MORNING]


def test_off_decides_p0_exactly_as_before():
    off = P(p0_max_wait_min=120, dryback_target=20)
    assert off.p0_additional_dryback == 0
    assert p0_dryback(off) == 20
    assert _day(off) == TODAY
    assert _day(P(p0_max_wait_min=120, dryback_target=20, p0_additional_dryback=0)) == TODAY
    s = _p0(PEAK - 2, 40)
    assert waiting_for(s, off) == waiting_for(s, P(p0_max_wait_min=120, dryback_target=20))


def test_three_percent_ends_p0_once_moisture_is_three_percent_below_its_lights_on_reading():
    p = P(p0_max_wait_min=120, dryback_target=20, p0_additional_dryback=3)
    assert p0_dryback(p) == 3
    day = _day(p)
    first = day.index("P1")
    assert MORNING[first][0] == 40 and (PEAK - MORNING[first][1]) / PEAK * 100 >= 3
    assert (PEAK - MORNING[first - 1][1]) / PEAK * 100 < 3
    moved = decide(_p0(58.6, 40), p)
    assert moved[0] == "P1" and moved[4].startswith("P0 dryback done")
    item = next(i for i in waiting_for(_p0(59.0, 30), p) if i["rule"] == "p0_dryback")
    assert item["value"] == round(PEAK * 0.97, 2)


def test_every_other_p0_exit_is_unchanged_by_the_setting():
    p = P(p0_max_wait_min=45, dryback_target=20, p0_additional_dryback=3)
    assert decide(_p0(PEAK - 0.5, 45), p)[0] == "P1"  # the timeout
    assert decide(_p0(45, 5), p)[0] == "P1"  # the maintenance trigger


def test_the_setting_is_kept_between_0_and_40_percent():
    for given, kept in ((-1, 0), (55, 40)):
        p, warnings = validate_params(P(p0_additional_dryback=given))
        assert p.p0_additional_dryback == kept
        assert warnings[0].startswith("p0_additional_dryback=")
    assert validate_params(P(p0_additional_dryback=3))[1] == []
