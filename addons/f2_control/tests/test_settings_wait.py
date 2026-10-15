"""The controller waits for a room's settings, then holds only a zone it cannot size the water of.

A setting that cannot be read is first given three passes to load (Home Assistant starting, the
integration reloading), and no shot of any kind is started meanwhile. After that a setting runs on
the last value read since the controller started, else on its built-in value, and CS-402 says so,
except a setting that sizes a zone's water (pot size, plant count, drippers per plant, dripper flow,
daily limit) that has not been read once since the start: that zone holds, its rescues included,
and every other zone carries on.
"""

from datetime import timedelta

import pytest

import controller
from test_plan_hold_never_stops_rescues import Clock, opened, probe, rig  # noqa: F401 (rig: a pytest fixture)

# What happens once a probe is dead; how long it must be out first is test_blind_grace.py.
pytestmark = pytest.mark.usefixtures("no_blind_grace")

WAITING = "waiting for its settings to load"


def _sized(fake, zones=(1, 2)):
    """The rig sets the room's pot size, plant count and drippers; the daily limit is per zone."""
    for zone in zones:
        fake.set_state(f"number.crop_steering_zone_{zone}_max_daily_volume", "150")


def _pass(c, room, now):
    """One controller pass over the room, as loop_once runs it: count what is missing, then CS-402."""
    c._defaulted_this_loop = set()
    pub = c._loop_room(room, now)
    c._check_defaulted_setpoints()
    return pub


def _p2_topup(fake, room, now):
    probe(fake, 1, 40)
    probe(fake, 2, 55)
    room.state[1].update(phase="P2", last_shot=now - timedelta(hours=1))
    room.state[2].update(phase="P2", last_shot=now - timedelta(hours=1))
    return 1


def _watchdog(fake, room, now):
    """Its daily limit spent, a zone under its re-water point gets only the watchdog's shot."""
    probe(fake, 1, 40)
    probe(fake, 2, 55)
    room.state[1].update(phase="P2", last_shot=now - timedelta(hours=4), daily_vol=150.0)
    room.state[2].update(phase="P2", last_shot=now - timedelta(hours=1))
    return 1


def _p3_emergency(fake, room, now):
    Clock.instant = now.replace(hour=23)
    room._was_lights_on = False
    for zone, vwc in ((1, 30), (2, 55)):
        probe(fake, zone, vwc)
        room.state[zone].update(phase="P3", last_shot=Clock.instant - timedelta(hours=2))
    return 1


def _min_daily(fake, room, now):
    fake.set_state("input_number.crop_steering_zone_1_min_daily_ml_per_plant", "500")
    probe(fake, 1, 50)
    probe(fake, 2, 50)
    for zone in (1, 2):
        room.state[zone].update(phase="P2", last_shot=now - timedelta(minutes=30))
    return 1


def _blind_fallback(fake, room, now):
    for zone in (1, 2):
        room.state[zone].update(phase="P2", last_shot=now - timedelta(hours=2))
    return 1


def _blind_copy(fake, room, now):
    _watchdog(fake, room, now)  # blind zone 2 copies zone 1's watchdog shot
    fake.states.pop("sensor.crop_steering_vwc_zone_2")
    room.state[2].update(last_shot=now - timedelta(hours=4))
    return 2


KINDS = {
    "p2_topup": _p2_topup,
    "watchdog": _watchdog,
    "p3_emergency": _p3_emergency,
    "min_daily": _min_daily,
    "blind_fallback": _blind_fallback,
    "blind_copy_rescue": _blind_copy,
}


@pytest.mark.parametrize("kind", KINDS)
def test_every_shot_kind_waits_three_passes_for_a_missing_setting_then_waters(rig, kind):  # noqa: F811
    c, fake, room = rig
    _sized(fake)
    zone = KINDS[kind](fake, room, Clock.now())
    now = Clock.now()
    for _ in range(controller.SETTINGS_WAIT_PASSES):
        pub = _pass(c, room, now)
        assert pub[zone]["fire"] and WAITING in pub[zone]["block"], pub[zone]
        assert opened(fake) == []
    pub = _pass(c, room, now)
    assert pub[zone]["fire"] and pub[zone]["block"] is None, pub[zone]
    assert getattr(pub[zone]["reason"], "kind", None) == kind, pub[zone]["reason"]
    assert f"switch.v{zone}" in opened(fake)


@pytest.mark.parametrize("kind", ["p2_topup", "watchdog", "p3_emergency", "min_daily", "blind_fallback"])
def test_a_zone_whose_water_sizing_setting_was_never_read_holds_its_rescues_included(rig, kind):  # noqa: F811
    """Zone 1's daily limit has never been there; zone 2 has its own and carries on."""
    c, fake, room = rig
    _sized(fake, zones=(2,))
    KINDS[kind](fake, room, Clock.now())
    now = Clock.now()
    for _ in range(controller.SETTINGS_WAIT_PASSES):
        _pass(c, room, now)
    pub = _pass(c, room, now)
    assert pub[1]["fire"], pub[1]
    assert "number.crop_steering_max_daily_volume not read since the controller started" in pub[1]["block"]
    assert "CS-402" in pub[1]["block"]
    assert "switch.v1" not in opened(fake)
    assert c._settings_hold(room, 2) is None  # the other zone is not held by it


def test_the_cs402_card_names_the_setting_and_says_the_zone_is_not_watered(rig):  # noqa: F811
    c, fake, room = rig
    _sized(fake, zones=(2,))
    _watchdog(fake, room, Clock.now())
    for _ in range(controller.SETTINGS_WAIT_PASSES):
        _pass(c, room, Clock.now())
    cards = [d["message"] for dom, svc, d in fake.calls
             if (dom, svc) == ("persistent_notification", "create") and "CS-402" in d.get("title", "")]
    assert cards and "number.crop_steering_max_daily_volume" in cards[-1]
    assert "The daily water limit set the water of a zone" in cards[-1] and "gets no shots" in cards[-1]


def test_a_setting_read_once_then_lost_runs_on_its_last_value_and_its_zone_waters(rig):  # noqa: F811
    c, fake, room = rig
    _sized(fake)
    _p2_topup(fake, room, Clock.now())
    now = Clock.now()
    fake.set_state("number.crop_steering_plant_count", "42")
    fake.set_state("number.crop_steering_zone_1_p2_shot_size", "7")
    for _ in range(controller.SETTINGS_WAIT_PASSES + 1):
        _pass(c, room, now)
    for entity in ("number.crop_steering_plant_count", "number.crop_steering_zone_1_p2_shot_size"):
        del fake.states[entity]
    for _ in range(controller.SETTINGS_WAIT_PASSES):  # lost again: it may be loading
        pub = _pass(c, room, now)
        assert WAITING in pub[1]["block"], pub[1]
    pub = _pass(c, room, now)
    assert pub[1]["fire"] and pub[1]["block"] is None, pub[1]
    assert c._zone_num(room, 1, "plant_count", 0) == 42  # the last value read, not the built-in 0
    assert c._zone_num(room, 1, "p2_shot_size", 5) == 7
    assert c._zone_num(room, 1, "p1_target_vwc", 60) == 60  # never read: the built-in value
    assert "number.crop_steering_plant_count" in c._defaulted  # and CS-402 still says it is missing


def test_a_restart_forgets_what_was_read(rig, monkeypatch, tmp_path):  # noqa: F811
    """'Since the controller started': a new controller has read nothing, so a lost sizing setting holds."""
    c, fake, room = rig
    _sized(fake)
    c._zone_num(room, 1, "plant_count", 0)
    assert "number.crop_steering_plant_count" in c._settings_seen
    with monkeypatch.context() as setup:
        setup.setattr(controller.Controller, "_read_state_file", lambda self: {})
        fresh = controller.Controller()
    fresh._state_path = str(tmp_path / "fresh.json")
    del fake.states["number.crop_steering_plant_count"]
    fresh._defaulted["number.crop_steering_plant_count"] = controller.SETTINGS_WAIT_PASSES
    assert "number.crop_steering_plant_count not read" in fresh._settings_hold(fresh.rooms[0], 1)
