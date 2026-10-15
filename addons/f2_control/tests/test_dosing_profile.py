"""The room's dosing hardware profile (docs/DOSING.md, Hardware profile) on the controller: with no
profile published (an integration from before it) every time and limit is today's constant, and a
room's own profile moves exactly the time or limit it names.

Driven as test_dosing_runner.py drives it: the real Controller, the in-memory Home Assistant and a
fake clock.
"""
from __future__ import annotations

import math

import pytest

import dosing_runner
from test_dosing_runner import BALANCE, BATCH, BLOOM, CONFIG, _full_batch, make_rig


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return make_rig(tmp_path, monkeypatch)


def _profile(r, **profile):
    """Publish this room's hardware profile with the setup already published."""
    state, attributes = r.fake.states[CONFIG][:2]
    r.fake.set_state(CONFIG, state, {**attributes, "profile": profile})


def test_no_profile_or_an_unusable_value_is_todays_timings():
    assert dosing_runner.PROFILE == {
        "hold_wait_s": 600.0, "fill_open_s": 10.0, "full_blind_s": 15.0, "mix_power_s": 20.0,
        "min_flow_ml_s": 0.05, "max_dose_s": 1200.0}
    assert dosing_runner._profile({"pumps": []}) == dosing_runner.PROFILE
    assert dosing_runner._profile({"profile": None}) == dosing_runner.PROFILE
    junk = {"hold_wait_s": True, "fill_open_s": "30", "full_blind_s": -1, "mix_power_s": math.nan,
            "min_flow_ml_s": 0, "max_dose_s": None}
    assert dosing_runner._profile({"profile": junk}) == dosing_runner.PROFILE
    assert dosing_runner._profile({"profile": {"max_dose_s": 2400}}) == {
        **dosing_runner.PROFILE, "max_dose_s": 2400.0}


def test_the_watchdog_counts_the_rooms_wait_for_a_shot_and_dose_cap():
    batch = dict(BATCH, fill_timeout_min=20, premix_min=2, postmix_min=5)
    plan = [(BALANCE, 300, 10.0), (BLOOM, 1180, 1.0)]  # 57.5 s, and 1495 s capped at 360 s
    profile = {**dosing_runner.PROFILE, "hold_wait_s": 1200.0, "max_dose_s": 300.0}
    minutes = 20 + 20 + 2 + 5 + 10
    assert dosing_runner.DosingRunner._watchdog(batch, plan, profile) == minutes * 60 + 57.5 + 360


def test_a_rooms_longest_dose_refuses_and_cuts_by_its_own_limit(rig):
    r = rig({"number.balance_flow": ("0.5", {})})
    r.config()
    _profile(r, max_dose_s=600)
    r.ask(ml=400)  # 800 s at 0.5 mL/s: allowed by today's 20 min, not by this room's 10
    r.poll()
    assert r.status()[1]["handled_result"] == (
        "refused: 400 mL of Balance would take 13.3 min at 0.5 mL/s, more than 10 min")
    assert r.actions() == []

    r.behaviour["button.balance_start"] = "overrun"
    r.ask(ml=290)  # 580 s expected: 580 x 1.25 + 20 = 745 s, capped at 660 s
    r.poll()
    [pressed] = [t for t, service, _e in r.times if service == "press"]
    cut = min(t for t, service, e in r.times if (service, e) == ("turn_off", "switch.balance_power"))
    assert cut - pressed == pytest.approx(660, abs=1.0)
    assert r.status()[1]["handled_result"] == "ran past its time"


def test_a_rooms_lowest_flow_refuses_a_pump_below_it(rig):
    r = rig({"number.balance_flow": ("2", {})})
    r.config()
    _profile(r, min_flow_ml_s=5)
    r.ask(ml=10)
    r.poll()
    assert r.status()[1]["handled_result"] == "refused: Balance is not calibrated (flow 2)"
    assert r.actions() == []


def test_a_rooms_mix_power_time_is_waited_for(rig):
    r = rig()
    _full_batch(r)
    _profile(r, mix_power_s=60)
    r.watts = 0
    r.ask("batch")
    r.poll()
    assert r.status()[1]["handled_result"] == "stopped: mix: the mix pump did not draw 200 W within 60 s"
    assert "within 60 s" in r.alert("CS-805")["message"]


def test_a_rooms_full_sensor_silence_is_waited_for(rig):
    r = rig()
    _full_batch(r)
    _profile(r, full_blind_s=45)
    r.full_after = None
    r.ask("batch")
    r.clock.at(30, lambda: r.set("binary_sensor.tank_full", "unavailable"))
    r.poll()
    assert r.status()[1]["handled_result"] == "stopped: fill: the full sensor stopped reporting"
    assert "for 45 s" in r.alert("CS-804")["message"]
    closed = min(t for t, service, e in r.times if (service, e) == ("turn_off", "switch.tank_fill") and t > 30)
    assert 30 + 45 <= closed <= 30 + 45 + 4


def test_a_rooms_fill_valve_time_is_waited_for(rig):
    r = rig()
    _full_batch(r)
    _profile(r, fill_open_s=30)
    r.deaf["switch.tank_fill"] = 99
    r.ask("batch")
    r.poll()
    assert r.status()[1]["handled_result"] == "stopped: fill: the fill valve did not open"
    assert "did not read on within 30 s" in r.alert("CS-804")["message"]
