"""Task BX item 4: each projection_app intent carries `phase`, the phase the engine expects the zone in at that
time by its clock rules alone (controller._phase_at): lights off is P3, the timed P2 end is P3, a new day starts
at P0 for its P0 wait, and the current phase holds until one of those moves it. A phase only moisture decides
(P0 ending early, P1 -> P2) is None: never guessed. Old consumers ignore the new key."""
import pytest

import controller
from test_timer_mode import _mode, _pass_at, _projection, _timers, engine, rig  # noqa: F401

pytestmark = pytest.mark.usefixtures("settings_built_in")

# Lights 10:00-22:00, at 12:00: off in 10 h, on again in 22 h.
DAY = {"phase": "P2", "lights_on": True, "to_on_h": 22.0, "to_off_h": 10.0, "p2_end_h": 0.0,
       "p0_left_min": 0.0, "p0_wait_min": 120.0}


@pytest.mark.parametrize("minutes,phase", [
    (60, "P2"),                    # the rest of today's P2
    (10 * 60 - 1, "P2"),
    (10 * 60, "P3"),               # lights off
    (21 * 60, "P3"),
    (22 * 60 + 30, "P0"),          # tomorrow's lights-on: P0 for its wait
    (22 * 60 + 119, "P0"),
    (22 * 60 + 150, None),         # then P1 or P2, by moisture
    (34 * 60 + 30, "P3"),          # tomorrow night
])
def test_a_p2_day_then_night_then_the_next_morning(minutes, phase):
    assert controller._phase_at(DAY, minutes) == phase


def test_the_timed_p2_end_is_p3_before_lights_off():
    clock = {**DAY, "p2_end_h": 2.0}
    assert controller._phase_at(clock, 7 * 60) == "P2"
    assert controller._phase_at(clock, 8 * 60) == "P3"
    # The next day's end is P3 too: whether P1 or P2 by then, both end there.
    assert controller._phase_at(clock, 22 * 60 + 11 * 60) == "P3"
    assert controller._phase_at(clock, 22 * 60 + 9 * 60) is None


def test_p0_holds_its_wait_then_moisture_decides():
    clock = {**DAY, "phase": "P0", "p0_left_min": 30.0}
    assert controller._phase_at(clock, 20) == "P0"
    assert controller._phase_at(clock, 40) is None
    assert controller._phase_at(clock, 10 * 60) == "P3"


def test_p1_is_only_known_to_end_at_lights_off():
    clock = {**DAY, "phase": "P1"}
    assert controller._phase_at(clock, 0) == "P1"
    assert controller._phase_at(clock, 60) is None
    assert controller._phase_at(clock, 10 * 60) == "P3"


def test_at_night_p3_runs_to_lights_on():
    clock = {**DAY, "phase": "P3", "lights_on": False, "to_on_h": 2.0, "to_off_h": 14.0}
    assert controller._phase_at(clock, 60) == "P3"
    assert controller._phase_at(clock, 3 * 60) == "P0"
    assert controller._phase_at(clock, 5 * 60) is None


def test_no_clock_has_no_phase():
    assert controller._phase_at(None, 60) is None


def test_projection_intents_carry_the_expected_phase(rig, engine):  # noqa: F811
    c, fake = rig
    fake.set_state(_mode(1), "timer")
    fake.set_state("number.crop_steering_p2_time_between_shots", "30")  # zone 2 steering: a time to show
    _timers(fake)
    _pass_at(c, fake, 12, 10)
    intents = _projection(fake)
    timer = {controller._aware(i["at"]).astimezone().strftime("%d %H:%M"): i["phase"]
             for i in intents if i["source"] == "timer"}
    assert timer["22 12:30"] == "P2" and timer["22 21:30"] == "P2"
    assert timer["22 22:00"] == "P3" and timer["23 09:30"] == "P3"
    assert timer["23 10:30"] == "P0"  # (a slot right on a light edge could read either side)
    assert set(timer.values()) <= {"P0", "P2", "P3", None}
    estimates = [i for i in intents if i["source"] == "engine"]
    assert estimates and {i["phase"] for i in estimates} == {"P2"}
