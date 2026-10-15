"""The hourly P2 check is retired: the Auto setpoints pass asks nothing over the network, and the learner does the
same arithmetic whether or not Cloudflare keys are set. A state file it left (the `jev` record and the working-peak
adjustment) still loads, and the adjustment keeps its saved value: nothing writes it any more."""
import importlib.util
from datetime import datetime, timedelta

import pytest
import requests

import auto_setpoints as au
import test_auto_setpoints_runtime as asr

CF = {"cf_account_id": "acc", "cf_api_token": "tok", "jev_enabled": False}  # keys set, no brain
SENSOR = "sensor.crop_steering_zone_1_auto_setpoints"
P2_SHOT = "number.crop_steering_zone_1_p2_shot_size"


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    asr._Clock.current = datetime(2026, 9, 19, 11, 0)
    monkeypatch.setattr(asr.controller, "datetime", asr._Clock)


@pytest.fixture
def network(monkeypatch):
    """Every way the controller could reach the network, recorded and refused."""
    asked = []

    def refuse(*a, **k):
        asked.append((a, k))
        raise requests.ConnectionError("no network in this test")

    for owner, name in ((requests, "post"), (requests, "get"), (requests, "request"), (requests.Session, "request")):
        monkeypatch.setattr(owner, name, refuse)
    return asked


def _plateau_then_p2(c, fake, room, hours=3):
    """A P1 ramp that flattens (the plateau the old check was asked about), then hours of P2 (where it was asked
    once an hour)."""
    vwc, now = asr._flat_ramp(c, fake, room)
    room.state[1]["phase"] = "P2"
    for minute in range(0, hours * 60, 10):
        asr._Clock.current = now + timedelta(minutes=minute)
        asr._tick(c, fake, room, vwc, asr._Clock.current)
    return vwc


def test_the_auto_setpoints_pass_makes_no_network_call_with_cloudflare_keys_set(network):
    c, fake, room = asr._rig(options=CF)
    _plateau_then_p2(c, fake, room)
    assert network == []
    assert room.state[1]["learn"]["outcome"] == "plateau"  # believed: no outside guard vetoes it
    assert P2_SHOT not in asr._writes(fake)  # nothing nudges the P2 shot size
    attrs = fake.sets[SENSOR][1]
    assert attrs["jev"] == "disabled"
    assert P2_SHOT not in attrs["managed"] and "hourly" not in " ".join(attrs["managed_by"].values())


def test_the_learner_does_the_same_arithmetic_with_or_without_cloudflare_keys(network):
    runs = []
    for options in (None, CF):
        asr._Clock.current = datetime(2026, 9, 19, 11, 0)
        c, fake, room = asr._rig(options=options)
        _plateau_then_p2(c, fake, room)
        runs.append((room.state[1]["learn"], asr._writes(fake), fake.sets[SENSOR]))
    assert runs[0] == runs[1]
    assert runs[0][1]  # and the learner did write: the arithmetic ran, it was not just switched off
    assert network == []


def test_a_saved_working_peak_adjustment_loads_and_keeps_its_value(network):
    c, fake, room = asr._rig(options=CF)
    learn = au.fresh()
    learn.update(peak=33.8, peak_adj=1.0)
    learn["jev"].update(day="2026-09-19", nudged=["peak"], asked="2026-09-19T10", last="10:00 no change")
    room.state[1] = c._apply_saved_zone(c._fresh_zone(), {"phase": "P2", "learn": learn})
    assert room.state[1]["learn"]["peak_adj"] == 1.0 and au.working_peak(room.state[1]["learn"]) == 34.8

    now = asr._Clock.current
    for minute in range(0, 180, 10):
        asr._tick(c, fake, room, 33.0, now + timedelta(minutes=minute))
    kept = c._serialize_zone(room.state[1])["learn"]
    assert kept["peak_adj"] == 1.0 and kept["jev"]["nudged"] == ["peak"]  # nothing writes either again
    attrs = fake.sets[SENSOR][1]
    assert attrs["working_peak_adjust"] == 1.0
    assert attrs["jev_last"] is None and attrs["jev_changed_today"] is None  # the saved answer is not shown
    assert network == []

    learn["peak_adj"] = 3.5  # a saved value outside the range is still held inside it on load
    assert au.restore(learn)["peak_adj"] == au.JEV_PEAK_ADJ_RANGE[1]


def test_the_hourly_check_and_its_helpers_are_gone():
    assert importlib.util.find_spec("jev_policy") is None
    for name in ("evidence", "jev_due", "jev_verdict", "JEV_MANAGED", "JEV_SHOT_RANGE"):
        assert not hasattr(au, name), name
    assert not hasattr(asr.controller, "jev_policy")


def test_an_old_learn_record_with_a_malformed_jev_block_still_loads():
    saved = {**au.fresh(), "peak_adj": -1.5, "jev": "junk"}
    restored = au.restore(saved)
    assert restored["peak_adj"] == -1.5
    assert restored["jev"] == {"day": None, "asked": None, "last": None, "changed": None, "nudged": []}
