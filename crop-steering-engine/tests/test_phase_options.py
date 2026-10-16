"""Opt-in phase settings: the P0 minimum wait and stall exit, the flush to an EC target, the P2 dilute ratio,
timed P2 shots (plain and guarded) with a timed P2 end, and the wider extra-shot range. Each is off at its
default, and off decides exactly as before."""

import dataclasses

import pytest
from crop_steering_engine import CAP_EXEMPT, decide, ec_flush_goal, next_shot_size, validate_params, waiting_for
from test_core import P, S


def kind(s, p):
    return decide(s, p)[4].kind


def rules(s, p):
    return {item["rule"]: item for item in waiting_for(s, p)}


# ---------------------------------------------------------------- defaults change nothing
def test_every_new_setting_defaults_to_the_rule_as_it_was():
    p = P()
    assert (p.p0_min_wait_min, p.p0_stall_exit, p.ec_flush_target, p.p2_dilute_ratio) == (0.0, False, 0.0, 1.2)
    assert (p.p2_mode, p.p2_end_h_before_off) == ("moisture", 0.0)
    assert S().ec_flushing is False
    assert validate_params(p)[1] == []


# ---------------------------------------------------------------- P0 minimum wait
def _p0(minutes, vwc=50.0, peak=60.0, rate=2.0, **kw):
    return S(phase="P0", vwc=vwc, peak_vwc=peak, dryback_pct=(peak - vwc) / peak * 100,
             phase_minutes=minutes, dryback_rate=rate, **kw)


def test_the_minimum_wait_holds_the_dryback_exit_until_it_has_passed():
    p = P(dryback_target=10, p0_min_wait_min=30)
    assert decide(_p0(10), p)[0] == "P0"  # dried 16.7% already, but only 10 min in
    assert decide(_p0(30), p)[0] == "P1"
    assert decide(_p0(10), P(dryback_target=10))[0] == "P1"  # off: as before


def test_the_minimum_wait_never_holds_the_bypass():
    p = P(p0_min_wait_min=60)
    assert decide(_p0(1, vwc=44), p)[0] == "P1"


def test_the_minimum_wait_holds_the_timeout_too():
    p = P(p0_max_wait_min=45, p0_min_wait_min=45, dryback_target=40)
    assert decide(_p0(44, vwc=58), p)[0] == "P0"
    assert decide(_p0(45, vwc=58), p)[0] == "P1"


def test_a_minimum_wait_over_the_maximum_wait_is_clamped():
    p, warns = validate_params(P(p0_max_wait_min=45, p0_min_wait_min=90))
    assert p.p0_min_wait_min == 45 and warns[0].startswith("p0_min_wait_min=90")


def test_waiting_for_says_when_the_minimum_wait_ends():
    item = rules(_p0(10, vwc=58), P(dryback_target=20, p0_min_wait_min=30))["p0_dryback"]
    assert item["in_min"] == 20
    assert "in_min" not in rules(_p0(10, vwc=58), P(dryback_target=20))["p0_dryback"]


# ---------------------------------------------------------------- P0 stall exit
def test_the_stall_exit_starts_p1_when_the_dryback_cannot_finish_in_time():
    # 60 -> 58 after 40 min, 0.5 pts/h: 10 more points to a 20% dryback would take 20 h, past the 120 min wait.
    p = P(dryback_target=20, p0_max_wait_min=120, p0_stall_exit=True)
    assert decide(_p0(40, vwc=58, rate=0.5), p)[0] == "P1"
    assert decide(_p0(40, vwc=58, rate=0.5), dataclasses.replace(p, p0_stall_exit=False))[0] == "P0"


def test_the_stall_exit_starts_p1_on_a_dryback_under_the_rate_floor():
    p = P(dryback_target=20, p0_max_wait_min=120, p0_stall_exit=True)
    assert decide(_p0(40, vwc=59.9, rate=0.05), p)[0] == "P1"


def test_the_stall_exit_leaves_a_dryback_on_course_alone():
    # 6 pts/h with 10 points to go: 100 more minutes, inside 40 + 100 < 150.
    p = P(dryback_target=20, p0_max_wait_min=150, p0_stall_exit=True)
    assert decide(_p0(40, vwc=58, rate=6.0), p)[0] == "P0"


def test_the_stall_exit_waits_30_minutes_and_never_reads_a_doubted_probe():
    p = P(dryback_target=20, p0_max_wait_min=120, p0_stall_exit=True)
    assert decide(_p0(20, vwc=59.9, rate=0.0), p)[0] == "P0"
    assert decide(_p0(40, vwc=59.9, rate=0.0, p1_probe_suspect=True), p)[0] == "P0"
    assert decide(_p0(40, vwc=59.9, rate=0.0, backed_up=True), p)[0] == "P0"


def test_the_stall_exit_respects_the_minimum_wait():
    p = P(dryback_target=20, p0_max_wait_min=120, p0_stall_exit=True, p0_min_wait_min=60)
    assert decide(_p0(40, vwc=59.9, rate=0.0), p)[0] == "P0"
    assert decide(_p0(60, vwc=59.9, rate=0.0), p)[0] == "P1"


# ---------------------------------------------------------------- flush to an EC target
FLUSH = dict(phase="P2", vwc=50, ec=6.5, ec_smooth=6.5, feed_ec=2.0, minutes_since_shot=99)


def test_off_no_shot_under_the_dilute_trigger():
    # 6.5 / 6 = 1.08: under the 1.2 dilute trigger, VWC over the re-water point
    assert decide(S(**FLUSH, ec_flushing=True), P())[2] is False


def test_a_flush_episode_keeps_diluting_down_to_the_target_inside_the_budget():
    p = P(ec_flush_target=5.0)
    _phase, _thr, fire, size, reason = decide(S(**FLUSH, ec_flushing=True), p)
    assert fire and reason.kind == "p2_dilute" and reason.cap_exempt is False and size == 7.5
    assert "flush to EC target" in reason
    assert decide(S(**dict(FLUSH, ec=4.9, ec_smooth=4.9), ec_flushing=True), p)[2] is False  # reached
    assert decide(S(**FLUSH), p)[2] is False  # no episode: nothing below the trigger


def test_a_flush_episode_stops_at_the_daily_budget_the_settle_gap_a_full_slab_and_a_backed_up_table():
    p = P(ec_flush_target=5.0)
    flushing = dict(FLUSH, ec_flushing=True)
    assert decide(S(**dict(flushing, daily_vol=300)), p)[4].kind == "block_daily_cap"
    assert decide(S(**dict(flushing, minutes_since_shot=5)), p)[2] is False
    assert decide(S(**dict(flushing, vwc=69)), p)[2] is False  # over field capacity - 2
    assert decide(S(**flushing, backed_up=True), p)[2] is False
    assert decide(S(**dict(flushing, feed_ec=7.0)), p)[2] is False  # feed not dilutive


def test_the_flush_target_never_aims_under_the_feed_ec():
    assert ec_flush_goal(S(feed_ec=4.0), P(ec_flush_target=2.0)) == pytest.approx(4.2)
    assert ec_flush_goal(S(feed_ec=1.0), P(ec_flush_target=2.0)) == 2.0
    assert ec_flush_goal(S(), P()) is None


# ---------------------------------------------------------------- P2 dilute ratio
def test_the_dilute_ratio_moves_the_dilute_trigger():
    s = S(phase="P2", vwc=50, ec=7.0, ec_smooth=7.0, feed_ec=2.0)  # 7 / 6 = 1.17
    assert decide(s, P())[2] is False
    assert kind(s, P(p2_dilute_ratio=1.1)) == "p2_dilute"
    assert rules(s, P(p2_dilute_ratio=1.5))["p2_dilute"]["value"] == 9.0


def test_the_dilute_ratio_is_clamped_to_its_bounds():
    p, warns = validate_params(P(p2_dilute_ratio=0.5))
    assert p.p2_dilute_ratio == 1.0 and warns


# ---------------------------------------------------------------- timed P2
TIMED = dict(phase="P2", vwc=55, ec=6, ec_smooth=6, hours_since_lights_on=6)


def test_a_timed_zone_waters_on_its_interval_whatever_moisture_reads():
    p = P(p2_mode="timed", p2_timed_interval_min=60, p2_timed_shot_size=3)
    _ph, _thr, fire, size, reason = decide(S(**TIMED, minutes_since_shot=60), p)
    assert fire and reason.kind == "p2_timed" and size == 3 and reason.cap_exempt is False
    assert decide(S(**TIMED, minutes_since_shot=59), p)[2] is False
    assert decide(S(**dict(TIMED, vwc=40), minutes_since_shot=30), p)[2] is False  # pure timer: no top-up


def test_a_timed_shot_size_of_0_is_the_maintenance_shot():
    p = P(p2_mode="timed", p2_timed_interval_min=60)
    assert decide(S(**TIMED, minutes_since_shot=90), p)[3] == 5
    assert next_shot_size(S(**TIMED), P(p2_mode="timed", p2_timed_shot_size=2.5)) == 2.5


def test_no_timed_shot_before_the_first_hour():
    p = P(p2_mode="timed", p2_timed_interval_min=60, p2_timed_first_h=7)
    assert decide(S(**TIMED, minutes_since_shot=90), p)[2] is False
    assert decide(S(**dict(TIMED, hours_since_lights_on=7), minutes_since_shot=90), p)[2] is True


def test_guarded_skips_a_slot_at_the_ceiling_and_keeps_the_floor_rescue():
    p = P(p2_mode="timed_guarded", p2_timed_interval_min=60)  # ceiling min(60, 70 - 2) = 60
    skipped = decide(S(**dict(TIMED, vwc=61), minutes_since_shot=90), p)
    assert skipped[2] is False and "SKIP timed" in skipped[4]
    assert kind(S(**dict(TIMED, vwc=59), minutes_since_shot=90), p) == "p2_timed"
    assert kind(S(**dict(TIMED, vwc=40), minutes_since_shot=10), p) == "p2_topup"  # under the re-water point


def test_timed_shots_stop_at_the_daily_budget_and_under_a_held_plan():
    p = P(p2_mode="timed", p2_timed_interval_min=60)
    assert kind(S(**TIMED, minutes_since_shot=90, daily_vol=300), p) == "block_daily_cap"
    assert decide(S(**TIMED, minutes_since_shot=90, steering_held=True), p)[2] is False
    assert CAP_EXEMPT["p2_timed"] is False


def test_ec_corrections_come_before_a_timed_shot():
    p = P(p2_mode="timed", p2_timed_interval_min=60)
    assert kind(S(**dict(TIMED, ec=8.5, ec_smooth=8.5), minutes_since_shot=90, feed_ec=2.0), p) == "p2_rescue"


def test_waiting_for_shows_the_next_timed_shot():
    items = rules(S(**TIMED, minutes_since_shot=20), P(p2_mode="timed", p2_timed_interval_min=60))
    assert items["p2_timed"]["in_min"] == 40 and "p2_topup" not in items
    guarded = rules(S(**TIMED, minutes_since_shot=20), P(p2_mode="timed_guarded"))
    assert guarded["p2_timed"]["ceiling"] == 60 and "p2_topup" in guarded


def test_an_unknown_mode_is_moisture():
    p, warns = validate_params(P(p2_mode="sometimes"))
    assert p.p2_mode == "moisture" and warns


# ---------------------------------------------------------------- timed P2 end
def test_the_timed_end_hands_p1_and_p2_to_p3_and_skips_predictive_p3():
    p = P(p2_end_h_before_off=2)
    assert decide(S(phase="P2", hours_to_lights_off=2), p)[0] == "P3"
    assert decide(S(phase="P1", hours_to_lights_off=1.5), p)[0] == "P3"
    assert decide(S(phase="P2", hours_to_lights_off=2.5), p)[0] == "P2"
    # predictive P3 would move this zone (2 points to go at 2 pts/h, 1 h to lights-on): the timed end replaces it
    early = S(phase="P2", vwc=50, peak_vwc=60, hours_to_lights_off=2.5, hours_to_lights_on=1, dryback_rate=2)
    assert decide(early, P(dryback_target=20))[0] == "P3"
    assert decide(early, p)[0] == "P2"
    assert rules(S(phase="P2", hours_to_lights_off=5), p)["lights_off"]["in_min"] == 180


def test_after_the_timed_end_p3_rescues_as_always():
    p = P(p2_end_h_before_off=2)
    assert kind(S(phase="P3", vwc=35, hours_to_lights_off=1), p) == "p3_emergency"


# ---------------------------------------------------------------- more extra shots
def test_the_engine_takes_30_extra_shots_and_clamps_31():
    assert validate_params(P(p1_max_extra_shots=30))[1] == []
    p, warns = validate_params(P(p1_max_extra_shots=31))
    assert p.p1_max_extra_shots == 30 and warns


def test_maximum_ramp_shots_still_end_p1_before_the_extra_shots_run_out():
    s = S(phase="P1", vwc=62, shot_count=12, p1_reached=True, p1_extra_shots=5)
    assert decide(s, P(p1_max_extra_shots=30, p1_max_shots=12))[0] == "P2"


def test_extra_shots_stay_inside_the_daily_budget():
    s = S(phase="P1", vwc=62, shot_count=4, p1_reached=True, p1_extra_shots=5, daily_vol=300)
    assert decide(s, P(p1_max_extra_shots=30))[0] == "P2"
