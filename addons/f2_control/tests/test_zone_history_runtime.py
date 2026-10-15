"""The plateau and night history inside the real controller: the lights edges, each way P1 hands over (the engine,
Jev's Ramp judge, the operator), the day's first shot, and an app restart in the night."""
import json
from datetime import date, datetime, timedelta, timezone

import pytest

import controller
import fake_ha
import jev_bridge
import jev_kit as K
from jev.envelope import Directive


class Clock(datetime):
    """The controller's wall clock, pinned by the test."""

    instant = None

    @classmethod
    def now(cls, tz=None):
        return cls.instant.replace(tzinfo=tz) if tz else cls.instant


@pytest.fixture
def rig(monkeypatch, tmp_path):
    """A two-zone room, lights 10:00-22:00, armed, on 23 Sep 2026 at 11:00."""
    Clock.instant = Clock(2026, 9, 23, 11, 0)
    monkeypatch.setattr(controller, "datetime", Clock)
    fake = fake_ha.FakeHA()
    options = {
        "num_zones": 2,
        "hardware": {"pump": "switch.p", "mainline": "switch.m", "valves": {"1": "switch.v1", "2": "switch.v2"}},
        "enable_flag": "input_boolean.kill",
    }
    monkeypatch.setattr(controller, "load_options", lambda: options)
    for name in ("ha_get", "ha_call", "ha_get_all", "ha_set"):
        monkeypatch.setattr(controller, name, getattr(fake, name))
    with monkeypatch.context() as setup:
        setup.setattr(controller.Controller, "_read_state_file", lambda self: {})
        c = controller.Controller()
    c._state_path = str(tmp_path / "state.json")
    for eid in ("input_boolean.kill", "switch.crop_steering_system_enabled",
                "switch.crop_steering_auto_irrigation_enabled",
                "switch.crop_steering_zone_1_enabled", "switch.crop_steering_zone_2_enabled"):
        fake.set_state(eid, "on")
    for eid in ("switch.p", "switch.m", "switch.v1", "switch.v2"):
        fake.set_state(eid, "off")
    seconds = {"now": 0.0}
    monkeypatch.setattr(controller.time, "monotonic", lambda: seconds["now"])
    monkeypatch.setattr(controller.time, "sleep", lambda dt: seconds.__setitem__("now", seconds["now"] + dt))
    return c, fake, c.rooms[0]


def _loop(c, fake, room, at, vwc1, vwc2=61.0):
    """One pass at `at` with fresh readings. Every reading here is above the default re-water threshold (45) and
    emergency floor (40), so nothing fires; `vwc1=None` is an unreadable zone 1 probe."""
    Clock.instant = at
    stamp = Clock.now(timezone.utc).isoformat()
    for zone, vwc in ((1, vwc1), (2, vwc2)):
        value = "unavailable" if vwc is None else str(vwc)
        fake.set_state(f"sensor.crop_steering_vwc_zone_{zone}", value, last_updated=stamp)
        fake.set_state(f"sensor.crop_steering_ec_zone_{zone}", "4.5", last_updated=stamp)
    return c._loop_room(room, at)


def test_lights_off_opens_the_night_lights_on_reads_it_and_the_first_shot_closes_it(rig):
    c, fake, room = rig
    st = room.state[1]
    st.update(phase="P2", peak=61.0, last_daily_reset=date(2026, 9, 23),
              plateau_hist=[{"date": "2026-09-23", "value": 61.0, "how": "P1 recovered", "shots": 6}])
    room._was_lights_on = True
    _loop(c, fake, room, Clock(2026, 9, 23, 22, 0), 58.4)
    assert st["night"]["off_vwc"] == 58.4 and st["night"]["plateau"] == 61.0
    _loop(c, fake, room, Clock(2026, 9, 24, 10, 0), 51.2)
    assert st["night"]["on_vwc"] == 51.2
    Clock.instant = Clock(2026, 9, 24, 10, 30)
    st.update(phase="P1", shots=0, last_vwc=50.8)  # the ramp's first shot, from 50.8
    c._advance_shot_counters(room, 1, 3.0)
    rec = st["night_hist"][-1]
    assert (rec["date"], rec["landing"], rec["night_shots"]) == ("2026-09-24", 50.8, 0)
    assert rec["night_rate"] == pytest.approx(0.6) and rec["p0_drop"] == pytest.approx(0.4)
    assert st["night"] is None
    assert any("Z1 night: landed 50.80" in line for line in c._activity)


def test_a_restart_in_the_night_keeps_the_open_night(rig):
    c, fake, room = rig
    room.state[1].update(phase="P2", last_daily_reset=date(2026, 9, 23))
    room._was_lights_on = True
    _loop(c, fake, room, Clock(2026, 9, 23, 22, 0), 58.4)
    c._load_state()  # the app restarted at 03:00: the zones come back from the file
    room._was_lights_on = None  # and the new process has not seen the lights yet
    _loop(c, fake, room, Clock(2026, 9, 24, 3, 0), 54.0)
    _loop(c, fake, room, Clock(2026, 9, 24, 10, 0), 51.2)
    night = room.state[1]["night"]
    assert night["off_vwc"] == 58.4 and night["on_vwc"] == 51.2


def test_a_probe_out_at_lights_off_still_opens_the_night(rig):
    c, fake, room = rig
    room.state[1].update(phase="P2", last_daily_reset=date(2026, 9, 23))
    room._was_lights_on = True
    _loop(c, fake, room, Clock(2026, 9, 23, 22, 0), None)
    night = room.state[1]["night"]
    assert night is not None and night["off_vwc"] is None and night["off_at"] == "2026-09-23T22:00:00"


def test_the_engine_handing_p1_over_records_the_plateau(rig):
    c, fake, room = rig
    now = Clock.now()
    # at its target, and the extra shot after it did not raise the peak (the owner's P1 rule, 6 Oct 2026)
    room.state[1].update(phase="P1", shots=6, peak=61.0, p1_reached=True, p1_extra=1, p1_peak_before=61.0,
                         last_shot=now - timedelta(minutes=16), last_daily_reset=now.date())
    _loop(c, fake, room, now, 61.0)
    st = room.state[1]
    assert st["phase"] == "P2"
    [entry] = st["plateau_hist"]
    assert (entry["date"], entry["value"], entry["shots"]) == ("2026-09-23", 61.0, 6)
    assert entry["how"].startswith("P1 full: the last shot raised the peak 0.0")


def test_jevs_ramp_judge_handing_over_records_the_plateau(rig):
    c, fake, room = rig
    now = Clock.now()
    st = room.state[1]
    st.update(phase="P1", peak=36.1, shots=5)
    d = Directive("ramp", "advance", "P2", "ramp done: block_is_full (hand over p=0.84)", now + timedelta(minutes=45))
    jev_bridge.advance(c, room, 1, K.snap(phase="P1", vwc=36.0), d, now)
    assert st["phase"] == "P2"
    assert st["plateau_hist"] == [{"date": "2026-09-23", "value": 36.1, "shots": 5,
                                   "how": "Jev's ramp judge: ramp done: block_is_full (hand over p=0.84)"}]


def test_a_hand_over_set_by_hand_records_the_plateau(rig):
    c, fake, room = rig
    st = room.state[1]
    st.update(phase="P1", peak=44.0, shots=4)
    fake.set_state("select.crop_steering_zone_1_set_phase", "P2")
    c._apply_phase_request(room, 1, st, Clock.now())
    assert st["phase"] == "P2"
    assert st["plateau_hist"] == [{"date": "2026-09-23", "value": 44.0, "how": "set by hand", "shots": 4}]


def test_a_night_left_open_across_a_missed_morning_is_not_merged_into_a_later_one(rig):
    c, fake, room = rig
    st = room.state[1]
    st.update(phase="P2", last_daily_reset=date(2026, 9, 23))
    room._was_lights_on = True
    _loop(c, fake, room, Clock(2026, 9, 23, 22, 0), 58.4)
    room._was_lights_on = None  # the 24th's edges were missed: the room was off, or the app restarted
    _loop(c, fake, room, Clock(2026, 9, 25, 10, 0), 52.0)
    Clock.instant = Clock(2026, 9, 25, 10, 30)
    st.update(phase="P1", shots=0, last_vwc=47.0)
    c._advance_shot_counters(room, 1, 3.0)
    assert st["night_hist"] == [] and st["night"] is None


def test_a_history_with_wrong_types_is_dropped_on_load_and_the_room_carries_on(rig):
    c, fake, room = rig
    with open(c._state_path, "w") as fh:
        json.dump({"default": {"1": {"phase": "P2", "last_daily_reset": "2026-09-23",
                                     "plateau_hist": [{"date": "2026-09-23", "how": "no value", "shots": 6}],
                                     "night": {"off_at": "garbage", "shots": "x"}}}}, fh)
    c._load_state()
    st = room.state[1]
    assert (st["plateau_hist"], st["night"]) == ([], None)
    room._was_lights_on = True
    _loop(c, fake, room, Clock(2026, 9, 23, 22, 0), 58.4)
    assert st["phase"] == "P3" and st["night"]["off_vwc"] == 58.4


def test_a_history_error_never_costs_a_counted_shot(rig):
    c, fake, room = rig
    st = room.state[1]
    st.update(phase="P1", shots=0, last_vwc=50.8,
              night={"off_at": "garbage", "off_vwc": 58.4, "plateau": None, "day": "2026-09-22",
                     "on_at": "2026-09-23T10:00:00", "on_vwc": 51.2, "on_shots": 0, "shots": 0, "end_at": None,
                     "end_vwc": None})  # a night only code that skips restore could hold: it fails in the arithmetic
    c._advance_shot_counters(room, 1, 3.0)
    assert st["shots"] == 1 and st["daily_vol"] > 0 and st["last_shot"] == Clock.now()


def test_a_broken_history_never_blocks_a_hand_over(rig):
    c, fake, room = rig
    st = room.state[1]
    st.update(phase="P1", peak=44.0, shots=4, plateau_hist="junk")
    fake.set_state("select.crop_steering_zone_1_set_phase", "P2")
    c._apply_phase_request(room, 1, st, Clock.now())
    assert st["phase"] == "P2"

