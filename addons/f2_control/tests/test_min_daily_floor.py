"""The minimum daily water is read from the zone's setting, and stops a little above field capacity.

The floor (mL per plant x plant count) used to be read only from an input_number helper nothing in
the product creates. It is now the zone's number.crop_steering_zone_N_min_daily_ml_per_plant, read
like every other setting; an integration older than that number still has the helper read. The floor
watered up to a fixed 90 VWC, above field capacity for most substrates; it now stops at the zone's
field capacity plus 5 points.
"""

import pytest

import controller
import fake_ha

NUMBER = "number.crop_steering_zone_1_min_daily_ml_per_plant"
HELPER = "input_number.crop_steering_zone_1_min_daily_ml_per_plant"


@pytest.fixture
def rig(monkeypatch):
    fake = fake_ha.FakeHA()
    options = {"num_zones": 1, "hardware": {"valves": {"1": "switch.v1"}}}
    monkeypatch.setattr(controller, "load_options", lambda: options)
    for name in ("ha_get", "ha_get_status", "ha_call", "ha_get_all", "ha_set"):
        monkeypatch.setattr(controller, name, getattr(fake, name))
    with monkeypatch.context() as setup:
        setup.setattr(controller.Controller, "_read_state_file", lambda self: {})
        c = controller.Controller()
    fake.set_state("number.crop_steering_zone_1_plant_count", "4")
    handed = []
    original = controller.validate_params

    def validate(raw):
        handed.append(raw)
        return original(raw)

    monkeypatch.setattr(controller, "validate_params", validate)

    def params():
        handed.clear()
        c._defaulted_this_loop = set()
        c._params(c.rooms[0], 1)
        return handed[0]

    return c, fake, params


@pytest.mark.parametrize(
    "states, litres",
    [
        ({}, 0.0),  # neither: off
        ({NUMBER: "200"}, 0.8),  # the zone's setting
        ({HELPER: "250"}, 1.0),  # an older integration: only the helper
        ({NUMBER: "100", HELPER: "250"}, 0.4),  # the setting wins once it exists
        ({NUMBER: "0", HELPER: "250"}, 0.0),  # set to 0, it is off
        ({NUMBER: "unavailable", HELPER: "250"}, 1.0),
    ],
)
def test_the_floor_is_the_zone_setting_then_the_old_helper(rig, states, litres):
    _c, fake, params = rig
    for entity_id, state in states.items():
        fake.set_state(entity_id, state)
    assert params().min_daily_volume == pytest.approx(litres)


@pytest.mark.parametrize("fc, ceiling", [(60, 65), (70, 75), (98, 100), (40, 50)])
def test_the_floor_stops_a_little_above_field_capacity(rig, fc, ceiling):
    _c, fake, params = rig
    fake.set_state("number.crop_steering_zone_1_field_capacity", str(fc))
    assert params().drown_ceiling == ceiling


def test_an_explicit_drown_ceiling_still_overrides(rig):
    _c, fake, params = rig
    fake.set_state("number.crop_steering_zone_1_min_floor_drown_ceiling", "88")
    assert params().drown_ceiling == 88


def test_the_new_reads_never_flag_a_missing_setting(rig):
    c, _fake, params = rig
    params()
    assert not any(
        "min_daily" in e or "drown" in e for e in c._defaulted_this_loop
    )
