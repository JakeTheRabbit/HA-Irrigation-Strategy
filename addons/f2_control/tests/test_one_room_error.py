"""An error in one room's pass never stops the other rooms, nor the steps after the rooms (CTL-006).

loop_once ran each room's pass, then the defaulted-setpoints check, the notifications and the event
feed, with nothing around a room. An exception in the first room's pass (a snapshot, a decision, a
shot or its status) left the loop: every later room went without its pass, the steps after the rooms
did not run, and run() only logged "loop error". A fault that stayed in room A stopped room B each
minute, with no alert. Now the room is logged, its heartbeat and status say error, and CS-212 tells,
at most each 30 min while the fault stays; every other room and step runs as before.
"""
from datetime import datetime

import pytest

import controller
from test_controller import _build, _desc

NOW = datetime(2026, 9, 21, 14, 0, 0)
VEG = "sensor.crop_steering_veg_engine_config"


def _two_rooms():
    states = {
        "sensor.crop_steering_engine_config": ("ok", _desc(pump=None, mainline=None, valves={"1": "switch.a"})),
        VEG: ("ok", _desc(prefix="veg_", pump=None, mainline=None, valves={"1": "switch.b"}, slug="veg")),
        "sensor.crop_steering_vwc_zone_1": ("45", {"unit_of_measurement": "%"}),
        "sensor.crop_steering_veg_vwc_zone_1": ("45", {"unit_of_measurement": "%"}),
        "sun.sun": ("above_horizon", {}),
    }
    c, fake = _build({"num_zones": 1}, states=states)
    assert [r.slug for r in c.rooms] == ["default", "veg"]
    return c, fake


def _break(monkeypatch, slug, error=RuntimeError("room is broken")):
    """`slug`'s pass raises in its snapshot; the other room's runs as it is. Returns the rooms whose
    pass decided: the ones whose status was published."""
    real_snapshot, real_publish = controller.Controller._snapshot, controller.Controller._publish_status
    decided = []

    def snapshot(self, room, *args, **kwargs):
        if room.slug == slug:
            raise error
        return real_snapshot(self, room, *args, **kwargs)

    def publish(self, room, pub, now):
        decided.append((room.slug, sorted(pub)))
        return real_publish(self, room, pub, now)

    monkeypatch.setattr(controller.Controller, "_snapshot", snapshot)
    monkeypatch.setattr(controller.Controller, "_publish_status", publish)
    return decided


def _spy_globals(monkeypatch):
    ran = []
    for name in ("_check_defaulted_setpoints", "_maybe_notify", "_send_events"):
        real = getattr(controller.Controller, name)
        monkeypatch.setattr(controller.Controller, name,
                            lambda self, *a, _n=name, _r=real: ran.append(_n) or _r(self, *a))
    return ran


def _cards(fake, code):
    return [d for dom, svc, d in fake.calls
            if (dom, svc) == ("persistent_notification", "create") and d["title"].endswith(f"({code})")]


def test_an_error_in_the_first_room_never_stops_the_second_or_the_steps_after(monkeypatch):
    c, fake = _two_rooms()
    decided = _break(monkeypatch, "default")
    ran = _spy_globals(monkeypatch)
    c.loop_once(NOW)  # does not raise
    assert decided == [("veg", [1])]  # the second room decided its zone in the same pass
    assert fake.sets["sensor.crop_steering_veg_ai_heartbeat"][0] == "healthy"
    assert ran == ["_check_defaulted_setpoints", "_maybe_notify", "_send_events"]
    # The broken room says so: its heartbeat and its status, and one CS-212 card that names it.
    beat = fake.sets["sensor.crop_steering_ai_heartbeat"]
    assert beat[0] == "error" and beat[1]["loop_error"] == "RuntimeError: room is broken"
    assert beat[1]["controller_instance"] == c.instance_id  # still this controller's beat
    assert fake.sets["sensor.crop_steering_app_status"][0] == "error"
    # Nothing an earlier pass fired looks live: the room's decision fires nothing and names the error.
    decision = fake.sets["sensor.crop_steering_current_decision"]
    assert decision[1] == {"fired": [], "blocked": ["Controller error: RuntimeError: room is broken"]}
    cards = _cards(fake, "CS-212")
    assert len(cards) == 1 and cards[0]["notification_id"] == "f2_room_error_default"
    assert "RuntimeError: room is broken" in cards[0]["message"]


def test_a_fault_that_stays_is_alerted_once_not_every_minute(monkeypatch):
    c, fake = _two_rooms()
    _break(monkeypatch, "default")
    for _ in range(5):
        c.loop_once(NOW)
    assert len(_cards(fake, "CS-212")) == 1


def test_a_room_that_recovers_reports_healthy_again_and_its_card_goes(monkeypatch):
    c, fake = _two_rooms()
    with monkeypatch.context() as broken:
        _break(broken, "default")
        c.loop_once(NOW)
    assert "room_error_default" in c._alerted
    c.loop_once(NOW)
    beat = fake.sets["sensor.crop_steering_ai_heartbeat"]
    assert beat[0] == "healthy" and "loop_error" not in beat[1]
    dismissed = [d["notification_id"] for dom, svc, d in fake.calls
                 if (dom, svc) == ("persistent_notification", "dismiss")]
    assert dismissed.count("f2_room_error_default") == 1 and "room_error_default" not in c._alerted
    c.loop_once(NOW)  # dismissed once, not every pass after
    assert [d["notification_id"] for dom, svc, d in fake.calls
            if (dom, svc) == ("persistent_notification", "dismiss")].count("f2_room_error_default") == 1


def test_an_off_room_that_fails_is_not_reported_active(monkeypatch):
    c, fake = _two_rooms()
    c.rooms[0]._beat = (None, False, None)  # its last beat: the room is off
    _break(monkeypatch, "default")
    monkeypatch.setattr(controller.Controller, "_loop_room",
                        lambda self, room, now: self._snapshot(room, 1, now, True, False))
    c.loop_once(NOW)
    beat = fake.sets["sensor.crop_steering_ai_heartbeat"]
    assert beat[0] == "error" and beat[1]["room_active"] is False


@pytest.mark.parametrize("stop", [SystemExit(0), KeyboardInterrupt()], ids=["SystemExit", "KeyboardInterrupt"])
def test_a_stop_is_never_swallowed(monkeypatch, stop):
    c, fake = _two_rooms()
    _break(monkeypatch, "default", stop)
    with pytest.raises(type(stop)):
        c.loop_once(NOW)
    assert _cards(fake, "CS-212") == []
