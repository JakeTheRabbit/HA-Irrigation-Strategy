"""The shape of a grow-day: typed decisions, what the daily budget may and may not stop, and which
pore-EC reading the EC rules act on. The live cases are F2, 21-22 Sep 2026."""

import pytest

from crop_steering_engine import CAP_EXEMPT, EC_SETTLE_MIN, Reason, decide
from test_core import P, S


def kind_of(result):
    return result[4].kind


# ---------------------------------------------------------------------------
# Typed decisions: the text is unchanged, the rule and its budget exemption travel with it
# ---------------------------------------------------------------------------
def test_the_reason_is_still_the_same_text_and_now_says_which_rule_fired():
    phase, _, fire, size, reason = decide(S(phase="P2", vwc=40, ec=6, ec_smooth=6), P())
    assert isinstance(reason, Reason) and isinstance(reason, str)
    assert reason == "P2 top-up VWC 40<45" and fire and size == 5
    assert reason.kind == "p2_topup" and reason.cap_exempt is False


@pytest.mark.parametrize(
    "snap,params,kind",
    [
        (dict(phase="P2", vwc=55, ec=10, feed_ec=3), {}, "flush_high_ec"),
        (dict(phase="P0", vwc=50, ec=6, feed_ec=3, dryback_pct=5), dict(ec_target_p0=2, max_ec=12), "p0_ec_flush"),
        (dict(phase="P1", vwc=50, minutes_since_shot=20), {}, "p1_ramp"),
        (dict(phase="P1", vwc=66, ec=8, feed_ec=3, minutes_since_shot=20), dict(max_ec=12), "p1_flush"),
        (dict(phase="P2", vwc=40, ec=8.5, feed_ec=3), {}, "p2_rescue"),
        (dict(phase="P2", vwc=55, ec=7.5, feed_ec=3, minutes_since_shot=30), {}, "p2_dilute"),
        (dict(phase="P2", vwc=40), {}, "p2_topup"),
        (dict(phase="P3", vwc=35, lights_on=False), {}, "p3_emergency"),
        (dict(phase="P3", vwc=42, minutes_since_shot=200), dict(watchdog_hours=3), "watchdog"),
        (dict(phase="P2", vwc=50, daily_vol=3), dict(min_daily_volume=10), "min_daily"),
    ],
)
def test_every_firing_rule_has_its_kind_and_the_documented_exemption(snap, params, kind):
    result = decide(S(**snap), P(**params))
    assert result[2] is True and kind_of(result) == kind
    assert result[4].cap_exempt is CAP_EXEMPT[kind]


def test_the_exemptions_are_the_agreed_ones():
    exempt = {kind for kind, yes in CAP_EXEMPT.items() if yes}
    assert exempt == {"flush_high_ec", "p1_ramp", "p2_rescue", "p3_emergency", "watchdog"}


@pytest.mark.parametrize(
    "snap,params,kind",
    [
        (dict(phase="P2", vwc=55, ec=6, ec_smooth=6), {}, "idle"),
        (dict(phase="P2", vwc=55, ec=10, feed_ec=11), {}, "block_high_ec"),
        (dict(phase="P2", vwc=55, ec=10, feed_ec=3, minutes_since_shot=3), {}, "hold_high_ec"),
        (dict(phase="P2", vwc=40, daily_vol=300), {}, "block_daily_cap"),
    ],
)
def test_a_shot_that_does_not_fire_says_why_and_is_never_exempt(snap, params, kind):
    result = decide(S(**snap), P(**params))
    assert result[2] is False and kind_of(result) == kind and result[4].cap_exempt is False


# ---------------------------------------------------------------------------
# The daily budget: routine and EC-correction shots stop at it, rescues and the ramp do not
# ---------------------------------------------------------------------------
def test_a_p1_flush_is_not_a_rescue_and_stops_at_the_budget():
    # Two ramp shots short of the configured minimum, so P1 cannot complete yet: the EC flush at the
    # ceiling is what would fire, and it no longer counts as an emergency because its text says "flush".
    result = decide(
        S(phase="P1", vwc=66, ec=8, feed_ec=3, minutes_since_shot=20, shot_count=2, daily_vol=300),
        P(max_ec=12, p1_min_shots=4),
    )
    assert result[0] == "P1" and result[2] is False and kind_of(result) == "block_daily_cap"


@pytest.mark.parametrize(
    "snap,params",
    [
        (dict(phase="P2", vwc=55, ec=7.5, feed_ec=3, minutes_since_shot=30, daily_vol=300), {}),
        (dict(phase="P0", vwc=50, ec=6, feed_ec=3, dryback_pct=5, daily_vol=300), dict(ec_target_p0=2, max_ec=12)),
    ],
)
def test_dilute_and_p0_flushes_stop_at_the_budget(snap, params):
    result = decide(S(**snap), P(**params))
    assert result[2] is False and kind_of(result) == "block_daily_cap"


def test_22_sep_a_zone_over_budget_and_starving_gets_the_watchdog_shot():
    # Z1, 22 Sep: budget spent by midday, VWC under the re-water threshold, no water 14:06-22:00.
    result = decide(
        S(phase="P2", vwc=41, ec=5, ec_smooth=5, minutes_since_shot=10 * 60, daily_vol=400,
          hours_to_lights_off=6, hours_to_lights_on=18),
        P(max_daily_volume=300, watchdog_hours=3),
    )
    phase, _, fire, size, reason = result
    assert phase == "P2" and fire and size == 5
    assert reason.kind == "watchdog" and reason.cap_exempt and "WATCHDOG" in reason
    # ...below the P3 emergency floor too, in daylight
    assert decide(S(phase="P2", vwc=39.5, ec=5, minutes_since_shot=600, daily_vol=400),
                  P(max_daily_volume=300))[4].kind == "watchdog"


def test_over_budget_but_watered_within_the_watchdog_window_still_holds():
    result = decide(S(phase="P2", vwc=41, ec=5, minutes_since_shot=60, daily_vol=400), P(max_daily_volume=300))
    assert result[2] is False and kind_of(result) == "block_daily_cap"


def test_the_p1_ramp_runs_in_full_over_the_budget_and_ends_at_max_shots():
    ramp = decide(S(phase="P1", vwc=50, minutes_since_shot=20, shot_count=5, daily_vol=400),
                  P(max_daily_volume=300))
    assert ramp[0] == "P1" and ramp[2] and kind_of(ramp) == "p1_ramp" and ramp[4].cap_exempt
    done = decide(S(phase="P1", vwc=50, minutes_since_shot=20, shot_count=12, daily_vol=400),
                  P(max_daily_volume=300))
    assert done[0] == "P2" and "max shots" in done[4]


def test_p1_at_the_ceiling_held_open_only_by_ec_completes_once_the_budget_is_spent():
    base = dict(phase="P1", vwc=62, ec=8, feed_ec=3, minutes_since_shot=20, shot_count=6)
    under = decide(S(**base, daily_vol=100), P(max_ec=12))
    assert under[0] == "P1" and under[2] and kind_of(under) == "p1_flush"
    over = decide(S(**base, daily_vol=300), P(max_ec=12))
    assert over[0] == "P2" and "P1 complete at ceiling; EC flush over daily budget" in over[4]


# ---------------------------------------------------------------------------
# P0 and the lights-on boundary
# ---------------------------------------------------------------------------
def test_22_sep_no_watchdog_at_lights_on_after_the_night():
    # The first lights-on tick: 12 h of dark counts as "no water", but the day starts with P0's dryback.
    result = decide(
        S(phase="P3", lights_just_on=True, vwc=30, ec=5, minutes_since_shot=12.6 * 60,
          hours_to_lights_off=12, hours_to_lights_on=24),
        P(p2_threshold=37),
    )
    assert result[0] == "P0" and result[2] is False and "WATCHDOG" not in result[4]
    # still no watchdog later in P0, however long since the last shot
    later = decide(S(phase="P0", vwc=30, ec=5, minutes_since_shot=13 * 60, dryback_pct=2, phase_minutes=20),
                   P(p2_threshold=25))
    assert later[2] is False and "WATCHDOG" not in later[4]


def test_the_p0_ec_flush_is_gated_like_every_other_flush():
    p = P(ec_target_p0=2, max_ec=12, field_capacity=70)
    base = dict(phase="P0", vwc=50, ec=6, feed_ec=3, dryback_pct=5)
    assert decide(S(**base), p)[2] is True
    assert decide(S(**{**base, "feed_ec": 8}), p)[2] is False  # feed saltier than the slab
    assert decide(S(**{**base, "vwc": 69}), p)[2] is False  # slab already full
    assert decide(S(**{**base, "minutes_since_shot": 3}), p)[2] is False  # a flush just went in


@pytest.mark.parametrize("phase", ["P1", "P2"])
def test_22_sep_a_zone_found_in_its_day_phases_on_a_new_grow_day_starts_again_at_p0(phase):
    # Restarted after lights-on with the zones saved in yesterday's P2: today gets its own budget.
    result = decide(S(phase=phase, lights_on=True, new_grow_day=True, vwc=42, ec=5, daily_vol=61),
                    P(max_daily_volume=60))
    assert result[0] == "P0" and "new grow-day -> P0 (reset)" in result[4]


def test_the_new_grow_day_reset_needs_the_lights_on_and_a_new_day():
    assert decide(S(phase="P2", lights_on=False, new_grow_day=True), P())[0] == "P3"
    assert decide(S(phase="P2", lights_on=True, new_grow_day=False, vwc=55), P())[0] == "P2"
    assert decide(S(phase="P0", lights_on=True, new_grow_day=True, vwc=55, dryback_pct=5), P())[0] == "P0"


# ---------------------------------------------------------------------------
# Settled pore EC
# ---------------------------------------------------------------------------
def test_22_sep_p1_at_the_ceiling_hands_over_on_the_settled_ec_not_the_ramp_transient():
    snap = dict(phase="P1", vwc=61, ec=7.4, feed_ec=3, minutes_since_shot=16, shot_count=6)
    raw_only = decide(S(**snap), P(max_ec=12))
    assert raw_only[0] == "P1"  # the transient kept the ramp flushing into runoff
    settled = decide(S(**snap, ec_settled=4.5), P(max_ec=12))
    assert settled[0] == "P2" and "EC ok 4.5" in settled[4]


def test_every_ec_rule_reads_the_settled_value_when_there_is_one():
    # anti-lockout: a transient over max_ec is not a lockout
    assert decide(S(phase="P2", vwc=55, ec=10, feed_ec=3, ec_settled=6), P())[2] is False
    # shot scaling: a transient does not double the top-up
    assert decide(S(phase="P2", vwc=40, ec=12, ec_settled=6), P(max_ec=15))[3] == 5
    assert decide(S(phase="P2", vwc=40, ec=6, ec_settled=12, minutes_since_shot=10), P(max_ec=15))[3] == 10
    # dilute tier
    assert decide(S(phase="P2", vwc=55, ec=5, ec_settled=7.5, feed_ec=3, minutes_since_shot=60), P())[4].kind == "p2_dilute"
    # a NaN settled value is no value: the raw reading applies
    assert decide(S(phase="P2", vwc=40, ec=6, ec_settled=float("nan")), P())[3] == 5


def test_a_correction_judged_on_a_held_settled_value_waits_for_the_next_settled_reading():
    snap = dict(phase="P2", vwc=55, ec=5, ec_settled=9.5, feed_ec=3)
    held = decide(S(**snap, minutes_since_shot=20), P())
    assert held[2] is False and held[4].kind == "hold_high_ec" and f"/{EC_SETTLE_MIN:.0f}min" in held[4]
    fresh = decide(S(**snap, minutes_since_shot=EC_SETTLE_MIN), P())
    assert fresh[2] is True and fresh[4].kind == "flush_high_ec"
    # a P2 rescue never re-fires on the same held value; a dry zone still gets its top-up meanwhile
    rescue = dict(phase="P2", vwc=40, ec=5, ec_settled=8.5, feed_ec=3)
    assert decide(S(**rescue, minutes_since_shot=20), P())[4].kind == "p2_topup"
    assert decide(S(**rescue, minutes_since_shot=50), P())[4].kind == "p2_rescue"
    # and the P1 flush at the ceiling waits too, while the ramp itself does not
    flush = dict(phase="P1", vwc=62, ec=5, ec_settled=8, feed_ec=3, shot_count=3)
    assert decide(S(**flush, minutes_since_shot=20), P(max_ec=12))[2] is False
    assert decide(S(**flush, minutes_since_shot=50), P(max_ec=12))[4].kind == "p1_flush"
    assert decide(S(**{**flush, "vwc": 50}, minutes_since_shot=20), P(max_ec=12))[4].kind == "p1_ramp"


def test_without_a_settled_value_the_raw_reading_behaves_exactly_as_before():
    assert decide(S(phase="P2", vwc=55, ec=10, feed_ec=3, minutes_since_shot=12), P())[4].kind == "flush_high_ec"
    held = decide(S(phase="P2", vwc=55, ec=10, feed_ec=3, minutes_since_shot=3), P())
    assert "flush draining (3/10min)" in held[4]
    assert decide(S(phase="P1", vwc=62, ec=8, feed_ec=3, minutes_since_shot=16), P(max_ec=12))[4].kind == "p1_flush"
