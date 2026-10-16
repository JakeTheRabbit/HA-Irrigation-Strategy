"""Light dimming on dry substrate (dry_dim.py, docs/DOSING.md, Light dimming) and the shots-held alert (CS-211).

Dimming is opt-in, only ever dims (never off, never below 30 %, never brighter than it found), counts only live
probes, and restores the brightness it recorded at recovery, switch-off, kill switch, lights-off, its longest time
and a restart; a light someone else changes is left to them. Every one of those is a case below, first on the pure
rules, then through the real Controller with a light in the in-memory Home Assistant.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import controller
import dry_dim
from test_controller import _build, _desc

S = {key: spec[0] for key, spec in dry_dim.SETTINGS.items()}  # floor 15, level 50, after 10 min, max 4 h
T0 = datetime(2026, 10, 17, 14, 0)
LIGHT = "light.room"
ON = {"brightness": 255, "supported_color_modes": ["brightness"]}


def step(d, record=None, at=0, **kw):
    args = dict(now=T0 + timedelta(minutes=at), enabled=True, allowed=True, lights_on=True, to_off_min=600,
                light=LIGHT, state="on", attributes=ON, readings={1: 12.0, 2: 40.0}, s=S)
    args.update(kw)
    return d.step(record, **args)


REC = {"light": LIGHT, "was": 255, "set": 128, "since": T0.isoformat()}
DIMMED = {"brightness": 128, "supported_color_modes": ["brightness"]}


def test_a_dry_zone_dims_after_its_delay_to_the_level():
    d = dry_dim.Dimmer()
    assert step(d, at=0) == (None, None)
    assert step(d, at=9) == (None, None)
    assert step(d, at=10) == ("dim", 128)  # 50 % of 255


@pytest.mark.parametrize("change", [
    {"enabled": False}, {"allowed": False}, {"lights_on": False}, {"to_off_min": 4},
    {"light": "switch.room"}, {"state": "off"}, {"attributes": {"supported_color_modes": ["onoff"]}},
    {"attributes": {"brightness": 100, "supported_color_modes": ["brightness"]}},  # dimmer than the level already
    {"readings": {1: 0.0, 2: 40.0}},  # a dead probe reads 0: not a dry pot
    {"readings": {1: 0.5}},
    {"readings": {}},  # every zone blind
    {"readings": {1: 16.0, 2: 40.0}},  # nothing under the floor
])
def test_never_dims_when(change):
    d = dry_dim.Dimmer()
    for at in (0, 10, 20):
        assert step(d, at=at, **change) == (None, None)


def test_never_below_its_minimum_whatever_the_setting():
    d = dry_dim.Dimmer()
    step(d, at=0, s={**S, "level_pct": 5})
    assert step(d, at=10, s={**S, "level_pct": 5}) == ("dim", round(0.3 * 255))


def test_recovered_for_10_minutes_restores():
    d = dry_dim.Dimmer()
    wet = {1: 18.0, 2: 40.0}  # floor 15 + 3
    assert step(d, REC, at=0, attributes=DIMMED, readings=wet) == (None, None)
    assert step(d, REC, at=5, attributes=DIMMED, readings={1: 17.0, 2: 40.0}) == (None, None)  # not +3: restart
    assert step(d, REC, at=6, attributes=DIMMED, readings=wet) == (None, None)
    assert step(d, REC, at=16, attributes=DIMMED, readings=wet) == ("restore", "the substrate is wet again")


@pytest.mark.parametrize("change,why", [
    ({"enabled": False}, "dimming was switched off"),
    ({"allowed": False}, "the room's kill switch is off"),
    ({"lights_on": False}, "the lights go off"),
    ({"to_off_min": 5}, "the lights go off"),
    ({"light": "light.other"}, "the room's light was changed in setup"),
])
def test_restores_when(change, why):
    assert step(dry_dim.Dimmer(), REC, attributes=DIMMED, **change) == ("restore", why)


def test_restores_at_its_longest_time():
    d = dry_dim.Dimmer()
    assert step(d, REC, at=239, attributes=DIMMED) == (None, None)
    assert step(d, REC, at=240, attributes=DIMMED) == ("restore", "max")


def test_restores_after_a_restart():
    assert step(dry_dim.Dimmer(restarted=True), REC, attributes=DIMMED) == ("restore", "the controller restarted")


def test_a_light_changed_by_someone_else_is_left_to_them():
    assert step(dry_dim.Dimmer(), REC, attributes=ON)[0] == "drop"
    assert step(dry_dim.Dimmer(), REC, state="off", attributes={})[0] == "drop"
    assert step(dry_dim.Dimmer(), REC, state="unavailable", attributes={}) == (None, None)


def test_a_saved_dim_loads_and_a_bad_one_is_none():
    assert dry_dim.load(REC) == REC
    for bad in (None, {}, {"light": "switch.x", "was": 255, "set": 128}, {"light": LIGHT, "was": 0, "set": 128},
                {"light": LIGHT, "was": "255", "set": 128}):
        assert dry_dim.load(bad) is None


# ------------------------------------------------------------------ through the controller
@pytest.fixture
def room(monkeypatch):
    c, fake = _build({"num_zones": 2, "enable_flag": "input_boolean.kill"},
                     states={"sensor.crop_steering_engine_config": ("ok", _desc(valves={"1": "switch.v1", "2": "switch.v2"}, num=2)),
                             "input_boolean.kill": ("on", {}), "switch.crop_steering_dry_dim": ("on", {}),
                             "switch.crop_steering_zone_1_enabled": ("on", {}),
                             "switch.crop_steering_zone_2_enabled": ("on", {}),
                             LIGHT: ("on", dict(ON))})
    calls = []

    def call(domain, service, **data):
        calls.append((domain, service, data))
        if domain == "light" and service == "turn_on" and not getattr(c, "_deaf", False):
            fake.set_state(LIGHT, "on", {**fake.states[LIGHT][1], "brightness": data["brightness"]})
            return True
        return fake.ha_call(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", call)
    monkeypatch.setattr(controller.time, "sleep", lambda s: None)
    r = c.rooms[0]
    r.light_entity, r.lights_on_hour, r.lights_off_hour = LIGHT, 6, 22
    return SimpleNamespace(c=c, fake=fake, r=r, calls=calls)


def snaps(*vwc):
    return {z: SimpleNamespace(vwc=v) for z, v in enumerate(vwc, start=1)}


def lights(x):
    return [(d.get("brightness")) for dom, svc, d in x.calls if dom == "light"]


def codes(x):
    return [d["title"].rsplit("(", 1)[1].rstrip(")") for dom, svc, d in x.calls
            if (dom, svc) == ("persistent_notification", "create")]


def test_the_controller_dims_records_and_restores(room):
    x = room
    for minute in (0, 10):
        x.c._watch_dim(x.r, T0 + timedelta(minutes=minute), True, snaps(12.0, 40.0))
    assert lights(x) == [128]
    assert x.r._dim["was"] == 255 and x.r._dim["set"] == 128
    saved = json.load(open(x.c._state_path))["default"]["_dim"]
    assert saved["was"] == 255  # recorded, so a restart restores it
    assert codes(x) == ["CS-810"]
    for minute in (20, 31):
        x.c._watch_dim(x.r, T0 + timedelta(minutes=minute), True, snaps(19.0, 40.0))
    assert lights(x) == [128, 255] and x.r._dim is None
    assert "_dim" not in json.load(open(x.c._state_path))["default"]


def test_a_disabled_zone_does_not_count(room):
    x = room
    x.fake.set_state("switch.crop_steering_zone_1_enabled", "off")
    for minute in (0, 10, 20):
        x.c._watch_dim(x.r, T0 + timedelta(minutes=minute), True, snaps(12.0, 40.0))
    assert lights(x) == []


def test_off_by_default(room):
    x = room
    x.fake.states.pop("switch.crop_steering_dry_dim")
    for minute in (0, 10, 20):
        x.c._watch_dim(x.r, T0 + timedelta(minutes=minute), True, snaps(12.0, 40.0))
    assert lights(x) == [] and codes(x) == []


def test_a_restart_restores_the_recorded_brightness(room):
    x = room
    x.r._dim = dict(REC)
    x.c._save_state()
    x.fake.set_state(LIGHT, "on", dict(DIMMED))
    x.c._load_state()  # the controller started again
    assert x.r._dim == REC and x.r._dimmer.restarted
    x.c._watch_dim(x.r, T0, True, snaps(12.0, 40.0))
    assert lights(x) == [255] and x.r._dim is None


def test_a_restore_never_switches_an_off_light_on(room):
    x = room
    x.r._dim = dict(REC)
    x.r._dimmer = dry_dim.Dimmer(restarted=True)
    x.fake.set_state(LIGHT, "off", {})
    x.c._watch_dim(x.r, T0, False, {})
    assert lights(x) == [] and x.r._dim is None and codes(x) == ["CS-810"]


def test_the_room_switched_off_restores(room):
    x = room
    x.r._dim = dict(REC)
    x.fake.set_state(LIGHT, "on", dict(DIMMED))
    x.c._watch_dim(x.r, T0, True, {}, off_why="the room was switched off")
    assert lights(x) == [255] and x.r._dim is None


def test_the_longest_time_restores_with_a_critical_alert(room):
    x = room
    x.r._dim = dict(REC)
    x.fake.set_state(LIGHT, "on", dict(DIMMED))
    x.c._watch_dim(x.r, T0 + timedelta(hours=4), True, snaps(12.0, 40.0))
    assert lights(x) == [255] and codes(x) == ["CS-811"]


def test_a_light_that_does_not_dim_is_set_back(room):
    x = room
    x.c._deaf = True
    for minute in (0, 10):
        x.c._watch_dim(x.r, T0 + timedelta(minutes=minute), True, snaps(12.0, 40.0))
    assert lights(x) == [128, 255]
    assert codes(x) == ["CS-810"]


def test_a_light_that_does_not_come_back_is_critical_and_tried_again(room):
    x = room
    x.r._dim = dict(REC)
    x.fake.set_state(LIGHT, "on", dict(DIMMED))
    x.c._deaf = True
    x.fake.set_state("switch.crop_steering_dry_dim", "off")
    x.c._watch_dim(x.r, T0, True, snaps(12.0, 40.0))
    assert codes(x) == ["CS-811"] and x.r._dim is not None
    x.c._deaf = False
    x.c._watch_dim(x.r, T0 + timedelta(minutes=1), True, snaps(12.0, 40.0))
    assert lights(x) == [255, 255] and x.r._dim is None


def test_an_old_state_file_has_no_dim(room):
    x = room
    with open(x.c._state_path, "w") as fh:
        json.dump({"default": {"1": {"phase": "P2"}}}, fh)
    x.c._load_state()
    assert x.r._dim is None and not x.r._dimmer.restarted


# ------------------------------------------------------------------ CS-211
def held(zone_block, fire=True):
    return {1: {"fire": fire, "block": zone_block}}


def test_shots_held_for_too_long_alerts_and_clears(room):
    x = room
    x.fake.set_state("number.crop_steering_held_alert_hours", "2")
    gate = "source-water pH 5.75 out of [5.8,6.5]"
    x.c._watch_held(x.r, T0, held(gate))
    x.c._watch_held(x.r, T0 + timedelta(hours=1), held(None, fire=False))  # asks nothing: the clock runs on
    assert codes(x) == []
    x.c._watch_held(x.r, T0 + timedelta(hours=2), held(gate))
    assert codes(x) == ["CS-211"]
    x.c._watch_held(x.r, T0 + timedelta(hours=2, minutes=5), held(None))  # a shot
    assert ("persistent_notification", "dismiss") in [(d, s) for d, s, _ in x.calls]


@pytest.mark.parametrize("block", ["Crop Steering disabled (kill switch off)", "zone disabled", "manual override"])
def test_a_hold_a_person_set_never_counts(room, block):
    x = room
    x.fake.set_state("number.crop_steering_held_alert_hours", "1")
    for h in (0, 2, 4):
        x.c._watch_held(x.r, T0 + timedelta(hours=h), held(block))
    assert codes(x) == []


def test_shots_held_alert_is_off_by_default(room):
    x = room
    for h in (0, 5, 50):
        x.c._watch_held(x.r, T0 + timedelta(hours=h), held("source-water pH dead"))
    assert codes(x) == []
