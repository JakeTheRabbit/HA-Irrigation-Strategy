"""Switching a zone off stops a shot already running in it, as the engine switch, Room Active and
manual override do: within a round of the shot's checks (<= 2 s), with the valve and anything upstream
switched off and the water delivered so far counted. It used to finish the shot."""
import controller
from test_controller import _build

KILL = "input_boolean.kill"
ZONE = "switch.crop_steering_zone_1_enabled"
HARDWARE = {"pump": "switch.p", "mainline": "switch.m", "valves": {"1": "switch.v1"}}


def _room(monkeypatch, *, zone_switch="on", switch_off=ZONE):
    """A one-zone room whose `switch_off` goes off while the shot's valve is open (None: nothing)."""
    states = {KILL: ("on", {})}
    if zone_switch is not None:
        states[ZONE] = (zone_switch, {})
    c, fake = _build({"num_zones": 1, "hardware": HARDWARE, "enable_flag": KILL}, states=states)
    clock = {"seconds": 0.0}
    monkeypatch.setattr(controller.time, "monotonic", lambda: clock["seconds"])

    def sleep(seconds):
        clock["seconds"] += seconds
        if switch_off and fake.states["switch.v1"][0] == "on":  # the shot is running
            fake.set_state(switch_off, "off")

    monkeypatch.setattr(controller.time, "sleep", sleep)
    return c, fake


def test_the_zone_switch_stops_its_running_shot(monkeypatch):
    c, fake = _room(monkeypatch)
    fake.set_state("switch.v1", "on")  # the shot's valve, as _execute_shot leaves it
    elapsed, aborted = c._wait_shot(c.rooms[0], 1, 10)
    assert aborted == ("abort", ZONE)
    assert 0 < elapsed < 10


def test_the_stopped_shot_is_closed_counted_and_named(monkeypatch):
    c, fake = _room(monkeypatch)
    c._execute_shot(c.rooms[0], 1, 10, 6)
    assert [fake.states[e][0] for e in ("switch.v1", "switch.m", "switch.p")] == ["off"] * 3
    assert c.rooms[0].state[1]["shots"] == 1  # it ran partway: the water it gave counts
    alerts = [d for dom, svc, d in fake.calls if dom == "persistent_notification" and svc == "create"]
    stopped = [d for d in alerts if "killshot" in d.get("notification_id", "")]
    assert stopped and "because this zone was switched off" in stopped[0]["message"]
    assert ZONE in stopped[0]["message"] and "stopped after 2 of 10 seconds" in stopped[0]["message"]


def test_the_engine_switch_is_still_named_as_the_engine_switch(monkeypatch):
    c, fake = _room(monkeypatch, switch_off=KILL)
    c._execute_shot(c.rooms[0], 1, 10, 6)
    alerts = [d for dom, svc, d in fake.calls if dom == "persistent_notification" and svc == "create"]
    assert any("because the engine switch was turned off" in d["message"] for d in alerts)


def test_a_zone_left_on_or_without_a_switch_runs_the_shot_to_its_end(monkeypatch):
    for zone_switch in ("on", None):  # None: an install whose zone has no switch entity
        c, _fake = _room(monkeypatch, zone_switch=zone_switch, switch_off=None)
        assert c._wait_shot(c.rooms[0], 1, 6) == (6, None)
