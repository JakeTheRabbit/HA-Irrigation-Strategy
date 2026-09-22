"""The controller's side of the grow-day: a day started late still gets its own budget, the EC rules act
on settled pore EC, yesterday's EC steer stays in yesterday, and a routine shot only gets what is left of
the budget. The live cases are F2, 21-22 Sep 2026."""
import json
from datetime import date, datetime, timedelta, timezone

import pytest

import controller
import fake_ha
from crop_steering_engine import Reason

FLOW = 42 * 1 * 4 / 3600  # 42 plants x 1 dripper x 4 L/h, in L/s


class Clock(datetime):
    """The controller's wall clock, pinned by the test."""

    instant = None  # set by the rig (a Clock, so values derived from it serialize as datetimes)

    @classmethod
    def now(cls, tz=None):
        return cls.instant.replace(tzinfo=tz) if tz else cls.instant


class Monotonic:
    def __init__(self):
        self.seconds = 0.0

    def sleep(self, seconds):
        self.seconds += seconds

    def monotonic(self):
        return self.seconds


@pytest.fixture
def rig(monkeypatch, tmp_path):
    Clock.instant = Clock(2026, 9, 23, 11, 0)  # lights 10-22: an hour into the photoperiod
    monkeypatch.setattr(controller, "datetime", Clock)
    fake = fake_ha.FakeHA()
    options = {
        "num_zones": 2,
        "hardware": {"pump": "switch.p", "mainline": "switch.m",
                     "valves": {"1": "switch.v1", "2": "switch.v2"}},
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
    # F2's hydraulics: 42 plants in 6.75 L blocks, one 4 L/h dripper each
    for key, value in {"plant_count": 42, "substrate_volume": 6.75,
                       "drippers_per_plant": 1, "dripper_flow_rate": 4}.items():
        fake.set_state(f"number.crop_steering_{key}", str(value))
    clock = Monotonic()
    monkeypatch.setattr(controller.time, "sleep", clock.sleep)
    monkeypatch.setattr(controller.time, "monotonic", clock.monotonic)
    return c, fake, c.rooms[0]


def probe(fake, zone, vwc=None, ec=None):
    """Fresh fused readings, stamped on the controller's own clock."""
    stamp = Clock.now(timezone.utc).isoformat()
    if vwc is not None:
        fake.set_state(f"sensor.crop_steering_vwc_zone_{zone}", str(vwc), last_updated=stamp)
    if ec is not None:
        fake.set_state(f"sensor.crop_steering_ec_zone_{zone}", str(ec), last_updated=stamp)


def turned_on(fake):
    return [d["entity_id"] for dom, svc, d in fake.calls if dom == "switch" and svc == "turn_on"]


# ---------------------------------------------------------------------------
# A new grow-day in any phase
# ---------------------------------------------------------------------------
def test_22_sep_a_restart_after_lights_on_starts_the_day_at_p0_with_its_own_budget(rig):
    c, fake, room = rig
    fake.set_state("number.crop_steering_max_daily_volume", "60")
    yesterday = Clock(2026, 9, 22, 21, 0)
    for zone in (1, 2):
        probe(fake, zone, vwc=42, ec=5)
        room.state[zone].update(phase="P2", daily_vol=61.0, shots=9, last_shot=yesterday,
                                last_phase_change=yesterday, last_daily_reset=date(2026, 9, 22))
    pub = c._loop_room(room, Clock.now())
    for zone in (1, 2):
        st = room.state[zone]
        assert st["phase"] == "P0" and st["daily_vol"] == 0 and st["shots"] == 0
        assert st["last_daily_reset"] == date(2026, 9, 23)
        assert "new grow-day -> P0 (reset)" in pub[zone]["reason"]
        assert "daily-cap" not in pub[zone]["reason"]


def test_a_blind_zone_left_in_p2_also_starts_the_new_day(rig):
    c, fake, room = rig
    probe(fake, 1, vwc=42, ec=5)  # zone 2 has no probe reading at all
    for zone in (1, 2):
        room.state[zone].update(phase="P2", daily_vol=61.0, shots=9, last_daily_reset=date(2026, 9, 22))
    c._loop_room(room, Clock.now())
    assert room.state[2]["phase"] == "P0" and room.state[2]["daily_vol"] == 0
    assert room.state[2]["last_daily_reset"] == date(2026, 9, 23)


def test_a_zone_with_no_dated_reset_is_not_restarted_mid_day(rig):
    c, fake, room = rig
    probe(fake, 1, vwc=55, ec=5)
    probe(fake, 2, vwc=55, ec=5)
    room.state[1].update(phase="P2", daily_vol=12.0, shots=3)  # fresh state: last_daily_reset unknown
    c._loop_room(room, Clock.now())
    assert room.state[1]["phase"] == "P2" and room.state[1]["daily_vol"] == 12.0


# ---------------------------------------------------------------------------
# Settled pore EC
# ---------------------------------------------------------------------------
def test_22_sep_p1_hands_over_on_the_settled_ec_not_the_ramp_transient(rig):
    c, fake, room = rig
    now = Clock.now()
    probe(fake, 1, vwc=61, ec=7.4)  # 16 minutes after a ramp shot: the feed front, not the slab
    probe(fake, 2, vwc=55, ec=5)
    room.state[1].update(phase="P1", shots=6, last_shot=now - timedelta(minutes=16), last_daily_reset=now.date(),
                         ec_settled=4.5, ec_settled_at=now - timedelta(hours=2))
    pub = c._loop_room(room, now)
    assert room.state[1]["phase"] == "P2" and "EC ok 4.5" in pub[1]["reason"]
    assert pub[1]["ec"] == 7.4 and pub[1]["ec_settled"] == 4.5  # both published; the rules used the settled one
    assert room.state[1]["ec_settled"] == 4.5  # the transient did not replace it


def test_only_a_reading_taken_45_minutes_after_a_shot_settles_and_feeds_the_ec_steer(rig):
    c, fake, room = rig
    now = Clock.now()
    st = room.state[1]
    st.update(phase="P2", last_shot=now - timedelta(minutes=20), last_daily_reset=now.date(),
              ec_smooth=5.0, ec_settled=5.0, ec_settled_at=now - timedelta(hours=1))
    probe(fake, 1, vwc=55, ec=7.8)
    probe(fake, 2, vwc=55, ec=5)
    c._loop_room(room, now)
    assert st["ec_settled"] == 5.0 and st["ec_smooth"] == 5.0  # 20 min after the shot: not settled
    Clock.instant = later = now + timedelta(minutes=30)  # 50 min after it
    probe(fake, 1, vwc=55, ec=5.6)
    probe(fake, 2, vwc=55, ec=5)
    c._loop_room(room, later)
    assert st["ec_settled"] == 5.6 and st["ec_settled_at"] == later
    assert st["ec_smooth"] == pytest.approx(0.3 * 5.6 + 0.7 * 5.0)
    c._save_state()
    c._load_state()
    assert room.state[1]["ec_settled"] == 5.6 and room.state[1]["ec_settled_at"] == later


def test_a_dead_ec_probe_is_unknown_ec_whatever_was_settled_before(rig):
    c, fake, room = rig
    now = Clock.now()
    probe(fake, 1, vwc=44, ec="unavailable")
    probe(fake, 2, vwc=55, ec=5)
    room.state[1].update(phase="P2", last_daily_reset=now.date(), ec_settled=9.5)
    pub = c._loop_room(room, now)
    assert pub[1]["ec_settled"] is None and "EC unknown" in pub[1]["reason"]
    assert "FLUSH" not in pub[1]["reason"]


def test_an_old_state_file_without_settled_ec_loads(rig):
    c, fake, room = rig
    with open(c._state_path, "w") as fh:
        json.dump({"default": {"1": {"phase": "P2", "daily_vol": 3, "ec_smooth": 5.1}}}, fh)
    c._load_state()
    st = room.state[1]
    assert st["ec_settled"] is None and st["ec_settled_at"] is None and st["ec_smooth"] == 5.1
    with open(c._state_path, "w") as fh:
        json.dump({"default": {"1": {"ec_settled": "junk", "ec_settled_at": "not a time"}}}, fh)
    c._load_state()
    assert room.state[1]["ec_settled"] is None and room.state[1]["ec_settled_at"] is None


# ---------------------------------------------------------------------------
# Yesterday's EC steer stays in yesterday
# ---------------------------------------------------------------------------
def test_the_first_tick_of_the_day_runs_on_the_base_threshold_and_fires_no_watchdog(rig):
    c, fake, room = rig
    Clock.instant = now = Clock(2026, 9, 23, 10, 0)
    probe(fake, 1, vwc=44, ec=5)
    probe(fake, 2, vwc=55, ec=5)
    room.state[1].update(phase="P3", ec_offset=4.0, ec_integral=2.0, ec_prev_err=1.0,
                         last_daily_reset=date(2026, 9, 22), last_shot=now - timedelta(hours=12))
    room._was_lights_on = False  # the loop has seen the dark
    pub = c._loop_room(room, now)
    st = room.state[1]
    assert pub[1]["p"].p2_threshold == 45  # the base threshold, not 45 + yesterday's 4
    assert st["phase"] == "P0" and st["ec_offset"] == 0 and st["ec_integral"] == 0
    assert pub[1]["fire"] is False and "WATCHDOG" not in pub[1]["reason"]


# ---------------------------------------------------------------------------
# The daily budget
# ---------------------------------------------------------------------------
def test_a_routine_shot_gets_only_what_is_left_of_the_daily_budget(rig):
    c, fake, room = rig
    fake.set_state("number.crop_steering_max_daily_volume", "60")
    room.state[1]["daily_vol"] = 59.0
    topup = Reason("P2 top-up VWC 40<45", "p2_topup", False)
    c._act_zone(room, 1, c._params(room, 1), None, (True, 5.0, topup), None, True, Clock.now())
    # a 5% shot is 14.2 L (~304 s); 1 L was left, so it ran ~21 s
    assert 59.0 < room.state[1]["daily_vol"] <= 60.0
    assert room.state[1]["shots"] == 1


def test_less_than_the_shortest_shot_left_holds_without_touching_the_hardware(rig):
    c, fake, room = rig
    fake.set_state("number.crop_steering_max_daily_volume", "60")
    room.state[1]["daily_vol"] = 59.9  # 0.1 L: about 2 s of this zone's flow
    topup = Reason("P2 top-up VWC 40<45", "p2_topup", False)
    acted = c._act_zone(room, 1, c._params(room, 1), None, (True, 5.0, topup), None, True, Clock.now())
    assert acted == (False, 0.0, "BLOCK daily-cap (0.10 L left)")
    assert turned_on(fake) == [] and room.state[1]["shots"] == 0


def test_a_rescue_is_never_cut_to_the_budget(rig):
    c, fake, room = rig
    fake.set_state("number.crop_steering_max_daily_volume", "60")
    room.state[1]["daily_vol"] = 70.0
    rescue = Reason("WATCHDOG 4.0h no water (VWC 40<45)", "watchdog", True)
    c._act_zone(room, 1, c._params(room, 1), None, (True, 5.0, rescue), None, True, Clock.now())
    assert room.state[1]["daily_vol"] == pytest.approx(70.0 + FLOW * 303)


def test_a_copied_or_blind_decision_is_never_exempt(rig):
    c, fake, room = rig
    fake.set_state("number.crop_steering_max_daily_volume", "60")
    room.state[1]["daily_vol"] = 59.9
    acted = c._act_zone(room, 1, c._params(room, 1), None, (True, 5.0, "COPY Z2 (VWC probe dead)"),
                        None, True, Clock.now())
    assert acted[0] is False and turned_on(fake) == []


def test_22_sep_a_starving_zone_with_a_sliver_of_budget_left_gets_the_watchdog_shot(rig):
    c, fake, room = rig
    now = Clock.now()
    fake.set_state("number.crop_steering_max_daily_volume", "60")
    probe(fake, 1, vwc=40, ec=5)
    probe(fake, 2, vwc=55, ec=5)
    room.state[1].update(phase="P2", daily_vol=59.9, last_shot=now - timedelta(hours=4), last_daily_reset=now.date())
    pub = c._loop_room(room, now)
    assert pub[1]["fire"] and "WATCHDOG" in pub[1]["reason"] and "over the daily budget" in pub[1]["reason"]
    assert room.state[1]["daily_vol"] > 60.0  # the rescue is exempt


def test_a_sliver_of_budget_and_recent_water_holds_as_spent(rig):
    c, fake, room = rig
    now = Clock.now()
    fake.set_state("number.crop_steering_max_daily_volume", "60")
    probe(fake, 1, vwc=40, ec=5)
    probe(fake, 2, vwc=55, ec=5)
    room.state[1].update(phase="P2", daily_vol=59.9, last_shot=now - timedelta(hours=1), last_daily_reset=now.date())
    pub = c._loop_room(room, now)
    assert pub[1]["fire"] is False and "BLOCK daily-cap" in pub[1]["reason"] and turned_on(fake) == []


def test_22_sep_p1_at_its_ceiling_with_the_budget_spent_completes_instead_of_waiting_all_day(rig):
    c, fake, room = rig
    now = Clock.now()
    fake.set_state("number.crop_steering_max_daily_volume", "60")
    probe(fake, 1, vwc=61, ec=8.0)  # EC keeps P1 open (gate 5.75); no settled reading yet
    probe(fake, 2, vwc=55, ec=5)
    room.state[1].update(phase="P1", shots=7, daily_vol=59.9, last_shot=now - timedelta(minutes=20),
                         last_daily_reset=now.date())
    pub = c._loop_room(room, now)
    assert room.state[1]["phase"] == "P2"
    assert "P1 complete at ceiling; EC flush over daily budget" in pub[1]["reason"]
