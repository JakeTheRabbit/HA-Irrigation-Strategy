"""The substrate profile pack reaches the engine, and "generic" is today's engine on every constant.

Every room that has not chosen a substrate (every upgraded room) runs the generic profile, so generic
must be exactly the numbers the engine used before the pack: the EC settle time, the P1 rise, the
P0 EC flush (2.5x the P0 target, a 10 % shot) and the shot scaling by pore EC. A room that chooses
another substrate gets that profile's numbers through ZoneParams.
"""

import dataclasses

from crop_steering_engine import ZoneParams, core, decide, ec_adjust
from crop_steering_engine.defaults import SUBSTRATE_PROFILES
from test_core import P, S

GENERIC = SUBSTRATE_PROFILES["generic"]
ENGINE_KEYS = (
    "ec_settle_min",
    "p1_rise_pts",
    "p0_ec_flush_ratio",
    "p0_ec_flush_shot",
    "ec_adjust_up",
    "ec_adjust_down",
)


def _ec_adjust_before_the_pack(size, ec, target):
    """ec_adjust as it was written before the pack (Jev 3.11.1)."""
    if ec is None or target <= 0:
        return size
    r = ec / target
    if r > 1.5:
        return size * 2.0
    if r > 1.2:
        return size * 1.5
    if r > 1.0:
        return size * 1.2
    if r < 0.5:
        return size * 0.5
    if r < 0.8:
        return size * 0.7
    return size


def test_generic_is_todays_engine_on_every_constant():
    assert GENERIC["ec_settle_min"] == core.EC_SETTLE_MIN == 45.0
    assert GENERIC["p1_rise_pts"] == core.P1_RISE_PTS == 0.5
    assert GENERIC["p0_ec_flush_ratio"] == core.P0_EC_FLUSH_RATIO == 2.5
    assert GENERIC["p0_ec_flush_shot"] == core.P0_EC_FLUSH_SHOT == 10.0
    assert GENERIC["ec_adjust_up"] == core.EC_ADJUST_UP
    assert GENERIC["ec_adjust_down"] == core.EC_ADJUST_DOWN
    # A caller that passes nothing (an older controller) gets the generic profile.
    defaults = {f.name: f.default for f in dataclasses.fields(ZoneParams)}
    assert {k: defaults[k] for k in ENGINE_KEYS} == {k: GENERIC[k] for k in ENGINE_KEYS}


def test_generic_shot_scaling_is_todays_table_at_every_ratio():
    target = 4.0
    for tenth in range(0, 41):
        ec = target * tenth / 10.0
        for ratio in (ec, ec + 1e-9, ec - 1e-9):
            assert ec_adjust(5.0, ratio, target) == _ec_adjust_before_the_pack(5.0, ratio, target)
            assert ec_adjust(
                5.0, ratio, target, GENERIC["ec_adjust_up"], GENERIC["ec_adjust_down"]
            ) == _ec_adjust_before_the_pack(5.0, ratio, target)


def test_generic_keeps_the_p0_flush_at_2_5x_and_a_10_percent_shot():
    p = P(ec_target_p0=3, **{k: GENERIC[k] for k in ENGINE_KEYS})
    s = dict(phase="P0", vwc=55, peak_vwc=58, dryback_pct=1, feed_ec=2.0)
    assert not decide(S(ec=7.4, **s), p)[2]  # 2.47x
    _, _, fire, size, reason = decide(S(ec=7.6, **s), p)  # 2.53x
    assert fire and size == 10.0 and reason.kind == "p0_ec_flush"


def test_a_profile_reaches_decide():
    s = dict(phase="P0", vwc=55, peak_vwc=58, dryback_pct=1, feed_ec=2.0)
    p = P(ec_target_p0=3, p0_ec_flush_ratio=2.0, p0_ec_flush_shot=6.0)
    _, _, fire, size, _ = decide(S(ec=6.5, **s), p)
    assert fire and size == 6.0
    # A slower settle holds an EC correction judged on a settled reading longer.
    hot = dict(ec=10.0, ec_settled=10.0, vwc=50, minutes_since_shot=50)
    assert decide(S(**hot), P())[4].kind == "flush_high_ec"
    assert decide(S(**hot), P(ec_settle_min=60.0))[4].kind == "hold_high_ec"
    # The P1 rise decides when a full slab hands over to P2.
    p1 = dict(phase="P1", vwc=62, shot_count=4, p1_reached=True, p1_extra_shots=1,
              p1_peak_before_shot=62.0, peak_vwc=62.6, minutes_since_shot=30)
    assert decide(S(**p1), P())[0] == "P1"  # rose 0.6 >= 0.5
    assert decide(S(**p1), P(p1_rise_pts=1.0))[0] == "P2"


def test_every_profile_carries_every_engine_key():
    for name, profile in SUBSTRATE_PROFILES.items():
        assert set(profile) == set(GENERIC), name
        ZoneParams(**{**dataclasses.asdict(P()), **{k: profile[k] for k in ENGINE_KEYS}})
