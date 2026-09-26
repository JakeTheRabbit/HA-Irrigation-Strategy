"""What a room last reported keeps being reported while a shot holds the loop.

25 Sep 2026, the first lights-on after 2.21.0: the controller fired three minimum-daily floor
shots in a row (91 s, 182 s, 145 s). Its loop is synchronous, so no room reported anything from 10:01:01
to 10:09:15, and the dashboard called the controller "not running" while it was watering. A single shot
can be 900 s, longer than every "not reporting" limit (the dashboard's, and the integration's engine
repair and zone status: 10 min each). Now, once a room's report is a minute old, a shot's wait repeats
it: the heartbeat with a fresh time, and the zones' status labels as they were.
"""
from datetime import datetime

import pytest

import controller
import fake_ha

KILL = "input_boolean.kill"
PUMP, MAIN, VALVE = "switch.p", "switch.m", "switch.v1"
BEAT = "sensor.crop_steering_ai_heartbeat"
STATUS = "sensor.crop_steering_zone_1_status_app"
F1_BEAT = "sensor.crop_steering_f1_ai_heartbeat"


class Clock:
    def __init__(self):
        self.seconds = 1000.0

    def sleep(self, seconds):
        self.seconds += seconds

    def monotonic(self):
        return self.seconds


@pytest.fixture
def rig(monkeypatch, tmp_path):
    fake = fake_ha.FakeHA()
    options = {
        "num_zones": 1,
        "hardware": {"pump": PUMP, "mainline": MAIN, "valves": {"1": VALVE}},
        "enable_flag": KILL,
        "hold_entities": [],
    }
    monkeypatch.setattr(controller, "load_options", lambda: options)
    for name in ("ha_get", "ha_call", "ha_get_all"):
        monkeypatch.setattr(controller, name, getattr(fake, name))
    with monkeypatch.context() as setup:
        setup.setattr(controller.Controller, "_read_state_file", lambda self: {})
        c = controller.Controller()
    c._state_path = str(tmp_path / "state.json")
    for eid in (KILL, "switch.crop_steering_room_active"):
        fake.set_state(eid, "on")
    fake.set_state(VALVE, "on")  # the shot's own valve stays open: nothing ends it early
    clock = Clock()
    monkeypatch.setattr(controller.time, "sleep", clock.sleep)
    monkeypatch.setattr(controller.time, "monotonic", clock.monotonic)
    writes = []  # (entity, state, attributes, when, timeout)

    def ha_set(entity, state, attributes=None, timeout=None):
        writes.append((entity, state, dict(attributes or {}), clock.seconds, timeout))

    monkeypatch.setattr(controller, "ha_set", ha_set)
    return c, clock, writes


def _to(writes, entity):
    return [write for write in writes if write[0] == entity]


def test_a_long_shot_repeats_the_rooms_report_once_a_minute(rig):
    c, clock, writes = rig
    room = c.rooms[0]
    c._heartbeat(room, datetime(2026, 9, 25, 10, 1, 1), "valve stuck", room_active=True)
    c._publish_zone_status(room, 1, "Topping up", "P2 top-up VWC 40<45")
    first = writes[0][2]
    started, wall = clock.seconds, datetime.now()
    elapsed, ended = c._wait_shot(room, 1, 300)
    assert ended is None and 300 <= elapsed < 303  # the shot runs its full time, no longer
    beats = _to(writes, BEAT)[1:]
    assert [at - started for _e, _s, _a, at, _t in beats] == [60, 120, 180, 240]  # none in the last seconds
    for _entity, state, attributes, _at, timeout in beats:
        # a fresh time: the controller's local clock at the write, whatever the machine's zone
        assert state == "healthy" and datetime.fromisoformat(attributes["last_beat"]) >= wall
        # Everything but the time is what the room last reported.
        assert {k: v for k, v in attributes.items() if k != "last_beat"} == {
            k: v for k, v in first.items() if k != "last_beat"
        }
        assert 0.25 <= timeout <= 1.0
    statuses = _to(writes, STATUS)[1:]
    assert [(state, attributes["reason"]) for _e, state, attributes, _at, _t in statuses] == [
        ("Topping up", "P2 top-up VWC 40<45")
    ] * 4


def test_a_shot_under_a_minute_repeats_nothing(rig):
    c, _clock, writes = rig
    room = c.rooms[0]
    c._heartbeat(room, datetime(2026, 9, 25, 10, 1, 1), None)
    c._wait_shot(room, 1, 45)
    assert len(writes) == 1


def test_nothing_is_repeated_before_a_first_report_or_in_a_shots_last_seconds(rig):
    c, clock, writes = rig
    room = c.rooms[0]
    c._wait_shot(room, 1, 120)  # the controller has not reported yet: nothing to repeat
    assert writes == []
    c._heartbeat(room, datetime(2026, 9, 25, 10, 1, 1), None)
    c._publish_zone_status(room, 1, "Optimal", "in band")
    clock.seconds += 61
    c._keep_alive(1.9)  # two writes, each allowed twice its timeout, do not fit with a second to spare
    assert len(writes) == 2
    c._keep_alive(10)
    assert [(entity, timeout) for entity, _s, _a, _at, timeout in writes[2:]] == [(BEAT, 0.5), (STATUS, 0.5)]


def test_every_room_is_repeated_the_quietest_first(rig):
    c, clock, writes = rig
    default = c.rooms[0]
    f1 = controller.Room("f1", "f1_", {1: {}}, {"pump": None, "mainline": None, "valves": {1: "switch.f1_v1"}},
                         "switch.crop_steering_f1_engine_enabled", "", "", 10, 22)
    c.rooms.append(f1)
    c._heartbeat(f1, datetime(2026, 9, 25, 10, 1, 1), None, room_active=False)  # an OFF room reports too
    clock.seconds += 5
    c._heartbeat(default, datetime(2026, 9, 25, 10, 1, 6), None)
    clock.seconds += 61
    for _round in range(3):
        c._keep_alive(30)
    assert [entity for entity, *_rest in writes[2:]] == [F1_BEAT, BEAT]  # then both are fresh
    assert writes[2][2]["room_active"] is False


def test_a_zone_the_room_no_longer_has_is_not_brought_back(rig):
    c, clock, writes = rig
    room = c.rooms[0]
    c._heartbeat(room, datetime(2026, 9, 25, 10, 1, 1), None)
    c._publish_zone_status(room, 2, "Optimal", "in band")  # from before its zone count went down to one
    clock.seconds += 61
    c._keep_alive(30)
    assert [entity for entity, *_rest in writes[2:]] == [BEAT]


def test_a_round_repeats_at_most_two_reports_so_the_kill_switch_is_read_again_soon(rig):
    """Codex review of #97: a round repeated a room's whole report, 25 writes for a 24-zone room, each
    allowed a second to connect and a second to read. A stalled Home Assistant could hold one round
    for 50 s while the shot's valve stayed open and its kill switch went unread. A round now repeats
    at most two, the heartbeat first; the labels follow in the next rounds, oldest first."""
    c, clock, writes = rig
    zones = range(1, 25)
    big = controller.Room("big", "big_", {z: {} for z in zones},
                          {"pump": None, "mainline": None, "valves": {z: f"switch.big_v{z}" for z in zones}},
                          "switch.crop_steering_big_engine_enabled", "", "", 10, 22)
    c.rooms.append(big)
    for zone in zones:
        c._publish_zone_status(big, zone, "Optimal", "in band")
    c._heartbeat(big, datetime(2026, 9, 25, 10, 1, 1), None)
    clock.seconds += 61
    rounds = []
    for _round in range(14):
        before = len(writes)
        c._keep_alive(30)
        rounds.append(writes[before:])
    assert all(len(written) <= c.KEEP_ALIVE_WRITES == 2 for written in rounds)
    # each write may take its timeout twice (connect, read): a round fits in one 2 s step of the shot
    assert all(2 * sum(timeout for *_rest, timeout in written) <= 2.0 for written in rounds)
    repeated = [entity for written in rounds for entity, *_rest in written]
    assert repeated == [
        "sensor.crop_steering_big_ai_heartbeat",
        *(f"sensor.crop_steering_big_zone_{z}_status_app" for z in zones),
    ]
    assert rounds[-1] == []  # all 25 repeated in 13 rounds, then nothing is due


@pytest.fixture
def looping(monkeypatch):
    """A room driven by loop_once. Its zone's turn holds the loop for five minutes, as a shot does
    (_execute_shot waits its shot out in _wait_shot), without the hardware sequence around it."""
    from test_room_status import _Clock, _room

    _Clock.current = datetime(2026, 9, 19, 3, 0)
    monkeypatch.setattr(controller, "datetime", _Clock)
    clock = Clock()
    monkeypatch.setattr(controller.time, "sleep", clock.sleep)
    monkeypatch.setattr(controller.time, "monotonic", clock.monotonic)

    def build(room_state):
        c, fake = _room(room_state)
        writes = []  # (entity, state, attributes, when, timeout)

        def ha_set(entity, state, attributes=None, timeout=None):
            writes.append((entity, state, dict(attributes or {}), clock.seconds, timeout))
            fake.ha_set(entity, state, attributes)

        monkeypatch.setattr(controller, "ha_set", ha_set)
        monkeypatch.setattr(c, "_act_zone", lambda room, zone, *_rest: c._wait_shot(room, zone, 300) and None)
        return c, fake, clock, writes

    return build, _Clock


@pytest.mark.usefixtures("no_blind_grace")
def test_a_fresh_controllers_first_pass_reports_before_its_shot_and_through_it(looping):
    """Codex review of #97: a controller that has just started has reported nothing, so a long shot on
    its first pass had nothing to repeat and the room still went quiet. The pass reports the room
    before its first shot, and the shot repeats that."""
    build, clock_class = looping
    c, _fake, clock, writes = build("on")
    c.rooms[0].state[1]["last_shot"] = None  # never watered: the blind schedule waters it now
    start = clock.seconds
    c.loop_once(clock_class.now())
    beats = [(at - start, a["room_active"]) for entity, _s, a, at, _t in writes if entity == BEAT]
    assert beats == [(0, True), (60, True), (120, True), (180, True), (240, True), (300, True)]
    # the zone being watered has no label yet: none is made up for it, and none is repeated
    assert [at - start for entity, *_rest, at, _t in writes if entity == STATUS] == [300]


def test_a_room_switched_back_on_is_not_reported_off_while_its_first_pass_holds_the_loop(looping):
    """Codex review of #97: an OFF room's last report says "Room off", every zone included. Switched
    back on, its first pass's shot repeated that report while the room was on again. The pass reports
    the room afresh before acting, so what is repeated is the room on, with each zone's new label."""
    build, clock_class = looping
    c, fake, clock, writes = build("off")
    c.loop_once(clock_class.now())
    assert [a["room_active"] for e, _s, a, *_r in writes if e == BEAT] == [False]
    assert {s for e, s, *_r in writes if e == STATUS} == {"Room off"}
    fake.set_state("switch.crop_steering_room_active", "on")
    writes.clear()
    start = clock.seconds
    c.loop_once(clock_class.now())
    beats = [(at - start, a["room_active"]) for entity, _s, a, at, _t in writes if entity == BEAT]
    assert beats == [(0, True), (60, True), (120, True), (180, True), (240, True), (300, True)]
    labels = [(at - start, s) for entity, s, _a, at, _t in writes if entity == STATUS]
    assert [at for at, _label in labels] == [0, 60, 120, 180, 240, 300]
    assert "Room off" not in {label for _at, label in labels}
