"""Room On/Off. An OFF room (nothing growing) must neither irrigate nor alert, must keep a heartbeat
so the integration does not call the engine offline, and must start a fresh run when switched back on.

The pain this fixes, as seen live on 2026-09-20: F1 was empty with unplugged probes, yet the engine
ran its 90-minute blind schedule (31.5 L per zone per day) and re-raised "probe dead" every 30 minutes.
"""
from datetime import datetime, timedelta

import pytest

import controller
from test_controller import _build, _desc

ROOM_ACTIVE = "switch.crop_steering_room_active"
FLAGS = {  # everything else says GO: only the room status differs between tests
    "input_boolean.kill": ("on", {}),
    "switch.crop_steering_system_enabled": ("on", {}),
    "switch.crop_steering_auto_irrigation_enabled": ("on", {}),
    "switch.crop_steering_zone_1_enabled": ("on", {}),
}


class _Clock(datetime):
    """The controller's wall clock, pinned. On the real clock these tests changed meaning with the hour
    they ran at: before lights-on locally, mid-photoperiod on a UTC build machine."""
    current = datetime(2026, 9, 19, 3, 0)

    @classmethod
    def now(cls, tz=None):
        return cls.current


@pytest.fixture(autouse=True)
def fake_clock(monkeypatch):
    """Shots run synchronously against time.monotonic/sleep: fake both so a fired shot costs no real time."""
    _Clock.current = datetime(2026, 9, 19, 3, 0)  # lights are 10:00-22:00 in the rig: this is night
    monkeypatch.setattr(controller, "datetime", _Clock)
    clock = {"seconds": 0.0}
    monkeypatch.setattr(controller.time, "monotonic", lambda: clock["seconds"])
    monkeypatch.setattr(controller.time, "sleep", lambda dt: clock.__setitem__("seconds", clock["seconds"] + dt))
    return clock


def _room(room_state, extra=None):
    states = {"sensor.crop_steering_engine_config": ("ok", _desc(enable_flag="input_boolean.kill")), **FLAGS}
    if room_state is not None:
        states[ROOM_ACTIVE] = (room_state, {})
    states.update(extra or {})  # no VWC sensor at all -> the zone is blind, exactly like empty F1
    return _build({"num_zones": 1, "enable_flag": "input_boolean.kill", "notify_service": "notify/phone"}, states=states)


def _notifications(fake):
    return [d for dom, svc, d in fake.calls if (dom, svc) == ("persistent_notification", "create")]


def _pushes(fake):
    return [d for dom, svc, d in fake.calls if dom == "notify"]


def _valve_opens(fake):
    return [d for dom, svc, d in fake.calls if (dom, svc) == ("switch", "turn_on")]


@pytest.mark.usefixtures("no_blind_grace")
def test_an_on_room_with_dead_probes_alerts_and_waters_blind_this_is_the_nuisance():
    c, fake = _room("on")
    c.rooms[0].state[1]["last_shot"] = None  # never watered -> the blind schedule is due
    c.loop_once(_Clock.now())
    assert any("blind" in str(n.get("notification_id")) for n in _notifications(fake))
    assert _pushes(fake)


def test_an_off_room_neither_waters_nor_alerts():
    c, fake = _room("off")
    c.rooms[0].state[1]["last_shot"] = None
    c.loop_once(_Clock.now())
    assert _valve_opens(fake) == []
    assert _notifications(fake) == [] and _pushes(fake) == []  # no alerts, no vitals digest either
    assert "Room off" in c._blocked(c.rooms[0], 1)


def test_an_off_room_still_reports_in_so_nothing_calls_the_engine_offline():
    c, fake = _room("off")
    c.loop_once(_Clock.now())
    state, attrs = fake.sets["sensor.crop_steering_ai_heartbeat"]
    assert state == "healthy" and attrs["room_active"] is False
    assert fake.sets["sensor.crop_steering_zone_1_status_app"][0] == "Room off"
    assert "Room off" in fake.sets["sensor.crop_steering_current_decision"][0]


def test_a_missing_switch_means_on_so_older_integrations_keep_watering():
    c, fake = _room(None)
    assert c._room_active(c.rooms[0]) is True
    c.loop_once(_Clock.now())
    assert fake.sets["sensor.crop_steering_ai_heartbeat"][1]["room_active"] is True


def test_an_off_room_stays_off_while_home_assistant_restarts():
    """Seen live 2026-09-20 23:54: during a core restart the switch read unavailable, unavailable meant ON,
    and empty F1 began a 'fresh run' and raised probe-dead alerts at midnight."""
    c, fake = _room("off")
    c.loop_once(_Clock.now())
    for unreadable in ("unavailable", "unknown"):
        fake.set_state(ROOM_ACTIVE, unreadable)
        c.loop_once(_Clock.now())
        assert c._room_active(c.rooms[0]) is False
    assert not _notifications(fake) and not _pushes(fake) and not _valve_opens(fake)
    assert fake.sets["sensor.crop_steering_ai_heartbeat"][1]["room_active"] is False


def test_the_last_known_room_status_survives_a_controller_restart_while_home_assistant_is_away():
    c, fake = _room("off")
    c.loop_once(_Clock.now())
    c._save_state()
    fake.set_state(ROOM_ACTIVE, "unavailable")
    again = controller.Controller()
    again._state_path = c._state_path
    again._load_state()
    assert again._room_active(again.rooms[0]) is False


def test_switching_off_dismisses_that_rooms_standing_alerts():
    c, fake = _room("on")
    c.rooms[0].state[1]["last_shot"] = None
    c.loop_once(_Clock.now())
    raised = {n["notification_id"] for n in _notifications(fake)}
    assert raised
    fake.set_state(ROOM_ACTIVE, "off")
    c.loop_once(_Clock.now())
    dismissed = {d["notification_id"] for dom, svc, d in fake.calls if (dom, svc) == ("persistent_notification", "dismiss")}
    assert {i for i in raised if "default" in i} <= dismissed


@pytest.mark.parametrize("hour,phase", [
    (3, "P3"),  # at night it waits for lights-on
    (14, "P0"),  # mid-photoperiod it starts the day from the top: never resumes in P2, never skips the ramp
])
def test_switching_back_on_starts_a_fresh_run_but_keeps_the_water_history(hour, phase):
    _Clock.current = datetime(2026, 9, 19, hour, 0)
    c, fake = _room("off")
    st = c.rooms[0].state[1]
    yesterday = (_Clock.now() - timedelta(days=1)).date().isoformat()  # inside the 7-grow-day window
    record = {"grow_day": yesterday, "litres": 12.0, "complete": True}
    st.update(phase="P2", shots=9, daily_vol=31.5, peak=44.0, water_history=[record])
    c.loop_once(_Clock.now())
    fake.set_state(ROOM_ACTIVE, "on")
    c.loop_once(_Clock.now())
    st = c.rooms[0].state[1]
    assert (st["shots"], st["daily_vol"], st["peak"]) == (0, 0.0, 0.0)
    assert st["phase"] == phase  # a fresh cycle, in order, instead of resuming mid-phase
    assert _valve_opens(fake) == []  # and the blind-probe clock starts NOW: time to plug probes in first
    kept = [r for r in st["water_history"] if r["grow_day"] == yesterday]
    assert kept and kept[0]["litres"] == 12.0  # delivered water is a site record, not part of the run


def _mid_p2_room():
    """An ON room at 14:00, its zone in P2 with today's counters, then switched off and seen off."""
    _Clock.current = _Clock(2026, 9, 19, 14, 0)  # a _Clock, so its times pass the state file's type check
    c, fake = _room("on")
    c.rooms[0].state[1].update(phase="P2", shots=9, daily_vol=31.5, peak=44.0,
                               last_shot=_Clock.now() - timedelta(minutes=20),
                               last_daily_reset=_Clock.now().date())
    c.loop_once(_Clock.now())
    fake.set_state(ROOM_ACTIVE, "off")
    c.loop_once(_Clock.now())
    return c, fake


def test_switching_a_room_off_and_on_again_within_a_day_carries_on_where_it_was():
    """25 Sep 2026: the operator switched F2 off and on again at 20:53 to clear a fault, and all three
    zones, in P2 an hour before lights-off, went back to P0 and a P1 ramp with today's counters at 0."""
    c, fake = _mid_p2_room()
    _Clock.current += timedelta(minutes=3)
    fake.set_state(ROOM_ACTIVE, "on")
    c.loop_once(_Clock.now())
    st = c.rooms[0].state[1]
    assert st["phase"] == "P2"
    assert (st["shots"], st["daily_vol"], st["peak"]) == (9, 31.5, 44.0)
    assert st["last_shot_is_anchor"] is False  # its last shot is still its last shot
    assert c.rooms[0]._off_since is None  # and a later switch-off is timed afresh


def test_a_room_off_for_more_than_a_day_starts_a_fresh_run():
    c, fake = _mid_p2_room()
    _Clock.current += timedelta(hours=25)
    fake.set_state(ROOM_ACTIVE, "on")
    c.loop_once(_Clock.now())
    st = c.rooms[0].state[1]
    assert (st["shots"], st["daily_vol"], st["peak"]) == (0, 0.0, 0.0)
    assert st["phase"] == "P0"  # 15:00, lights on: the new crop's grow-day starts from the top


def test_when_a_room_went_off_survives_a_controller_restart():
    c, fake = _mid_p2_room()
    again = controller.Controller()
    again._state_path = c._state_path
    again._load_state()
    again.loop_once(_Clock.now())  # restarted while the room is off: it has not been switched off again
    _Clock.current += timedelta(minutes=5)
    fake.set_state(ROOM_ACTIVE, "on")
    again.loop_once(_Clock.now())
    assert again.rooms[0].state[1]["phase"] == "P2"
    assert again.rooms[0].state[1]["shots"] == 9


def test_a_shot_in_flight_is_cut_when_the_room_is_switched_off(monkeypatch):
    c, fake = _room("on")
    clock = {"seconds": 0.0}
    monkeypatch.setattr(controller.time, "monotonic", lambda: clock["seconds"])

    def sleep(dt):
        clock["seconds"] += dt
        fake.set_state(ROOM_ACTIVE, "off")

    monkeypatch.setattr(controller.time, "sleep", sleep)
    elapsed, aborted = c._wait_shot(c.rooms[0], 1, 60)
    assert aborted == ("abort", ROOM_ACTIVE) and elapsed < 60
