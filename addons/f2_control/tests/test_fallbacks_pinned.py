"""With no setting readable, the controller hands decide() what it always did.

Around a Home Assistant restart every setting entity can read unavailable (or be missing, on an
integration older than the setting). The controller then runs on its built-in fallbacks, which now
come from the one defaults table instead of numbers typed at each call site. The table keeps them
at the values the release before it used (Jev 3.11.1, commit 12c6d1a), so the parameters below are
that controller's, written out by hand from its call sites; only P3 Time Between Shots is newer.
"""

import dataclasses

import pytest

import controller
import fake_ha
from crop_steering_engine import ZoneParams
from crop_steering_engine.defaults import DEFAULTS

# What 12c6d1a's _params passed decide() for a zone whose every setting reads nothing: the P2 threshold
# is its 45 fallback inside the band the shell keeps it in (above the rescue floor, below the P1 target).
PARAMS_12C6D1A = ZoneParams(
    p1_target=60,
    p2_threshold=45,
    p2_shot_size=5,
    p1_initial=2,
    p1_incr=0.5,
    p1_max_shots=12,
    p1_min_shots=0,
    p1_time_between_min=15,
    dryback_target=20,
    p0_max_wait_min=45,
    ec_target_p0=4,
    ec_target_p1=5,
    ec_target_p2=6,
    p3_emergency_floor=40,
    p3_emergency_shot=2,
    p3_time_between_min=10,  # added after 12c6d1a, at the number's own default
    max_daily_volume=150,
    field_capacity=70,
    max_ec=9,
    stacking_on=False,
    watchdog_hours=3,
    min_daily_volume=0.0,
    drown_ceiling=90,
)


@pytest.fixture
def rig(monkeypatch):
    fake = fake_ha.FakeHA()
    options = {"num_zones": 1, "hardware": {"valves": {"1": "switch.v1"}}}
    monkeypatch.setattr(controller, "load_options", lambda: options)
    for name in ("ha_get", "ha_call", "ha_get_all", "ha_set"):
        monkeypatch.setattr(controller, name, getattr(fake, name))
    with monkeypatch.context() as setup:
        setup.setattr(controller.Controller, "_read_state_file", lambda self: {})
        c = controller.Controller()
    handed = []

    def validate(raw):
        handed.append(raw)
        return original(raw)

    original = controller.validate_params
    monkeypatch.setattr(controller, "validate_params", validate)
    return c, fake, handed


@pytest.mark.parametrize("mode", ["Vegetative", "Generative"])
@pytest.mark.parametrize("reads", ["missing", "unavailable"])
def test_decide_gets_the_12c6d1a_parameters_when_no_setting_can_be_read(rig, mode, reads):
    c, fake, handed = rig
    fake.set_state("select.crop_steering_growth_stage", mode)
    if reads == "unavailable":
        for key in DEFAULTS:
            fake.set_state(f"number.crop_steering_{key}", "unavailable")
            fake.set_state(f"number.crop_steering_zone_1_{key}", "unavailable")
        fake.set_state(
            "input_number.crop_steering_zone_1_min_daily_ml_per_plant", "unavailable"
        )
    c._params(c.rooms[0], 1)
    (raw,) = handed
    assert dataclasses.asdict(raw) == dataclasses.asdict(PARAMS_12C6D1A)


def test_a_readable_setting_still_wins_over_the_fallback(rig):
    c, fake, handed = rig
    fake.set_state("number.crop_steering_p1_maximum_shots", "7")
    fake.set_state("number.crop_steering_zone_1_p2_vwc_threshold", "52")
    c._params(c.rooms[0], 1)
    (raw,) = handed
    assert (raw.p1_max_shots, raw.p2_threshold) == (7, 52)
