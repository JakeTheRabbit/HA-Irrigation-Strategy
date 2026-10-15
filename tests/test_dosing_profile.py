"""The room's dosing hardware profile (docs/DOSING.md, Hardware profile): its defaults are today's
timings, a setup stored before it loads with them, a save that sends none keeps the stored one, and
what is saved is what sensor.crop_steering_<prefix>dosing_config gives the controller."""

import copy
import re

import pytest

from . import ha_stubs
from .test_dosing import BATCH, PUMP
from .test_dosing_api import clock, dispatcher  # noqa: F401  (autouse fixtures)
from .test_dosing_api import rig, save

ha_stubs.install()

from custom_components.crop_steering import dosing  # noqa: E402

DEFAULTS = {
    "hold_wait_s": 600,
    "fill_open_s": 10,
    "full_blind_s": 15,
    "mix_power_s": 20,
    "min_flow_ml_s": 0.05,
    "max_dose_s": 1200,
}


def test_the_defaults_are_todays_timings():
    assert dosing.empty_profile() == DEFAULTS
    assert dosing.clean_profile(None) == DEFAULTS
    assert dosing.clean_profile({}) == DEFAULTS
    assert dosing.empty()["profile"] == DEFAULTS


def test_a_profile_keeps_what_is_sent_and_fills_in_the_rest():
    cleaned = dosing.clean_profile({"max_dose_s": 2400, "min_flow_ml_s": "0.5", "x": 1})
    assert cleaned == {**DEFAULTS, "max_dose_s": 2400, "min_flow_ml_s": 0.5}


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"max_dose_s": 30}, "longest dose (s) must be between 60 and 3600"),
        ({"hold_wait_s": 7200}, "wait for a shot in flight (s) must be between"),
        ({"fill_open_s": True}, "fill valve open read-back (s) must be a number"),
        ({"mix_power_s": "soon"}, "mix pump power read-back (s) must be a number"),
        (
            {"min_flow_ml_s": float("nan")},
            "lowest calibrated flow (mL/s) must be between",
        ),
        ([600], "the hardware profile must be an object"),
    ],
)
def test_a_profile_out_of_range_is_refused(raw, message):
    with pytest.raises(dosing.DosingError, match=re.escape(message)):
        dosing.clean_profile(raw)


def test_a_setup_stored_before_the_profile_loads_with_the_defaults():
    old = {
        "revision": 3,
        "pumps": [copy.deepcopy(PUMP)],
        "batch": copy.deepcopy(BATCH),
        "request": None,
        "updated_at": "2026-10-01T00:00:00+00:00",
    }
    _, store = rig(old)
    assert store.error is None and store.data["revision"] == 3
    assert store.data["profile"] == DEFAULTS
    state, attributes = store.sensor()
    assert state == 3 and attributes["profile"] == DEFAULTS


def test_a_saved_profile_is_published_and_a_save_without_one_keeps_it():
    _, store = rig()
    response = save(store, profile={"fill_open_s": 30})
    assert response["error"] is None
    profile = {**DEFAULTS, "fill_open_s": 30}
    assert response["config"]["profile"] == profile
    assert store._store.value["profile"] == profile
    assert store.sensor()[1]["profile"] == profile

    kept = save(store)  # the dashboard sends only its pumps and batch
    assert kept["error"] is None and kept["config"]["profile"] == profile

    refused = save(store, profile={"fill_open_s": 1})
    assert "fill valve open read-back" in refused["error"]
    assert store.data["profile"] == profile and store.data["revision"] == 2
