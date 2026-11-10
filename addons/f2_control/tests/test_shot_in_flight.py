"""The shot in flight, told to Home Assistant (Controller._say_open, _say_inflight).

Once a shot's valve is open the controller writes sensor.crop_steering_<prefix>shot_in_flight = "open", with
what the shot opened and two lengths in seconds. The integration reads it (shot_backstop.py): when the
controller goes silent with a shot open, the integration switches off what that shot opened once `max_s` has
passed. So what is pinned here is what the integration relies on, and what a shot must never pay for it:

  * nothing new is asked of Home Assistant before the valve is open (ruling R5: nothing new slows watering);
    the write is made in the shot's wait, short, and only when the shot has the time for it;
  * `opened_s` covers the time the shot took to open, and `max_s` what is left of the shot and its close;
  * "idle" is written once the pass is over, when no record of an open shot is left, and at a stop; never
    between shots; at a start an "open" whose devices do not read off is left standing, and no later shot
    writes over it;
  * a write that fails never stops a shot.
"""
import pytest
import test_interrupted_shot as interrupted

import controller

rig = interrupted.rig
SENSOR = "sensor.crop_steering_shot_in_flight"


def recorded(monkeypatch, fake, answer=None):
    """Every state write and switch call, in order. `answer(state, n)`: what Home Assistant answers the n-th
    write of that state to the sensor with (None: no answer; a status), when it is not the usual 200."""
    seen, count = [], {}
    real_set, real_call = fake.ha_set, fake.ha_call

    def ha_set(entity, state, attributes=None, timeout=None):
        seen.append(("set", entity, state, dict(attributes or {}), timeout))
        if entity == SENSOR and answer is not None:
            count[state] = count.get(state, 0) + 1
            status = answer(state, count[state])
            if status != 200:
                return status
        return real_set(entity, state, attributes, timeout)

    def ha_call(domain, service, **data):
        seen.append(("call", service, data.get("entity_id")))
        return real_call(domain, service, **data)

    monkeypatch.setattr(controller, "ha_set", ha_set)
    monkeypatch.setattr(controller, "ha_call", ha_call)
    return seen


def said(seen):
    return [(row[2], row[3]) for row in seen if row[0] == "set" and row[1] == SENSOR]


def states(seen):
    return [state for state, _ in said(seen)]


def pass_over(c):
    """What loop_once does once the pass's last pump is closed."""
    for room in c.rooms:
        c._say_inflight(room)


@pytest.fixture
def started(rig):
    """A controller whose first pass is over: Home Assistant has "idle" from it."""
    c, fake, clock = rig
    pass_over(c)
    assert fake.sets[SENSOR][0] == "idle" and c.rooms[0]._inflight_said == "idle"
    clock.sleep(1000.0)  # the clock is not at 0 when a shot begins
    return c, fake, clock


def test_open_is_written_once_the_valve_is_open_and_idle_when_the_pass_is_over(started, monkeypatch):
    c, fake, _clock = started
    seen = recorded(monkeypatch, fake)
    c._execute_shot(c.rooms[0], 1, 60, 5)
    last_on = max(i for i, row in enumerate(seen) if row[0] == "call" and row[1] == "turn_on")
    first_off = min(i for i, row in enumerate(seen) if row[0] == "call" and row[1] == "turn_off")
    wrote = [i for i, row in enumerate(seen) if row[0] == "set" and row[1] == SENSOR]
    assert [seen[i][2] for i in wrote] == ["open"]  # and nothing more from the shot itself (R5: not between shots)
    # R5: nothing new is asked of Home Assistant before the valve is open
    assert last_on < wrote[0] < first_off
    assert not [row for row in seen[:last_on] if row[0] == "set"]
    assert seen[wrote[0]][4] == 0.5  # short, as a keep-alive's write
    assert c.rooms[0].shot_inflight is None and c.rooms[0]._inflight_due is None
    pass_over(c)
    pass_over(c)
    assert states(seen) == ["open", "idle"] and c.rooms[0]._inflight_said == "idle"


def test_the_pass_says_idle_after_its_last_pump_and_never_before_a_shot(started, monkeypatch):
    """loop_once: the write is in the pass's own code, after the rooms, and the top of a pass writes none."""
    c, fake, _clock = started
    c.rooms[0]._inflight_said = "open"  # a shot of the last pass was said, and is closed
    seen = recorded(monkeypatch, fake)
    c._reconcile_inflight()  # the top of a pass
    assert states(seen) == []
    order = []
    monkeypatch.setattr(c, "_loop_room", lambda room, now: order.append("room") or {})
    real = c._say_inflight
    monkeypatch.setattr(c, "_say_inflight", lambda room, *a, **k: order.append("idle") or real(room, *a, **k))
    c.loop_once(interrupted.datetime(2026, 9, 23, 12, 0))
    assert order == ["room", "idle"] and states(seen) == ["idle"]


def test_open_names_what_the_shot_opened_the_holds_and_the_other_valves_on_its_line(started, monkeypatch):
    c, fake, _clock = started
    c.hold_entities = ["input_boolean.dosing", "switch.fill"]
    seen = recorded(monkeypatch, fake)
    c._execute_shot(c.rooms[0], 1, 60, 5)
    pass_over(c)
    state, attrs = said(seen)[0]
    assert state == "open"
    assert {k: attrs[k] for k in ("zone", "valve", "mainline", "pump")} == {
        "zone": 1, "valve": "switch.v1", "mainline": "switch.m", "pump": "switch.p"}
    assert attrs["holds"] == ["input_boolean.dosing", "switch.fill"]
    assert attrs["line_valves"] == ["switch.v2"]  # the room's other valve, never the shot's own
    assert attrs["controller_instance"] == c.instance_id and isinstance(attrs["started"], str)
    assert said(seen)[1] == ("idle", {"engine": controller.PRODUCT,
                                      "friendly_name": "Shot in flight (controller)"})


def test_the_two_lengths_are_measured_not_guessed(started, monkeypatch):
    """`opened_s`: the time from the record to the write, by the controller's own clock, so every switch of the
    shot went on within it. `max_s`: what is left of the shot at the write, and the time a close can take."""
    c, fake, clock = started
    seen = recorded(monkeypatch, fake)
    at = {}
    real_save = c._save_state

    def save():
        at.setdefault("record", clock.seconds)  # the write-ahead record: the first save of the shot
        return real_save()

    monkeypatch.setattr(c, "_save_state", save)
    real_set = controller.ha_set

    def ha_set(entity, state, attributes=None, timeout=None):
        if entity == SENSOR and state == "open":
            at["write"] = clock.seconds
        return real_set(entity, state, attributes, timeout)

    monkeypatch.setattr(controller, "ha_set", ha_set)
    real_wait = c._wait_shot

    def wait(room, zone, duration_s, started=None):
        at["deadline"] = (clock.seconds if started is None else started) + duration_s
        return real_wait(room, zone, duration_s, started)

    monkeypatch.setattr(c, "_wait_shot", wait)
    c._execute_shot(c.rooms[0], 1, 600, 5)
    attrs = said(seen)[0][1]
    assert at["record"] >= 1000.0 and at["write"] - at["record"] >= 3.0  # the 2 s prime and the 1 s lead at the least
    assert attrs["opened_s"] == pytest.approx(at["write"] - at["record"], abs=0.11)
    assert attrs["max_s"] == pytest.approx(at["deadline"] - at["write"] + controller.INFLIGHT_CLOSE_S, abs=0.11)
    assert controller.INFLIGHT_CLOSE_S == 150.0 and controller.INFLIGHT_SAY_TRIES == 3


@pytest.mark.parametrize("seconds, written", [(4, True), (2, False)])
def test_a_shot_with_no_time_for_the_write_does_not_make_it(started, monkeypatch, seconds, written):
    """The write must fit in the shot's time with a second to spare: a shot is never made longer for it."""
    c, fake, _clock = started
    seen = recorded(monkeypatch, fake)
    c._execute_shot(c.rooms[0], 1, seconds, 5)
    assert states(seen) == (["open"] if written else [])
    assert c.rooms[0].state[1]["shots"] == 1 and c.rooms[0]._inflight_due is None


@pytest.mark.parametrize("status", [None, 500, 401])
def test_an_open_that_home_assistant_does_not_take_is_tried_three_rounds_and_never_stops_the_shot(
        started, monkeypatch, status):
    c, fake, _clock = started
    seen = recorded(monkeypatch, fake, answer=lambda state, n: status if state == "open" else 200)
    c._execute_shot(c.rooms[0], 1, 60, 5)
    assert [row[1] for row in seen if row[0] == "call"] == [
        "turn_on", "turn_on", "turn_on", "turn_off", "turn_off", "turn_off"]
    assert c.rooms[0].state[1]["shots"] == 1
    assert states(seen) == ["open"] * controller.INFLIGHT_SAY_TRIES
    pass_over(c)
    assert states(seen)[-1] == "idle"  # Home Assistant may have taken one of them: "idle" follows


def test_an_open_taken_at_the_second_round_is_not_written_again(started, monkeypatch):
    c, fake, _clock = started
    seen = recorded(monkeypatch, fake, answer=lambda state, n: None if (state, n) == ("open", 1) else 200)
    c._execute_shot(c.rooms[0], 1, 60, 5)
    assert states(seen) == ["open", "open"]


def test_a_write_that_raises_never_stops_the_shot(started, monkeypatch):
    c, fake, _clock = started

    def broken(*_a, **_k):
        raise RuntimeError("no route to Home Assistant")

    monkeypatch.setattr(controller, "ha_set", broken)
    c._execute_shot(c.rooms[0], 1, 60, 5)
    pass_over(c)
    assert c.rooms[0].state[1]["shots"] == 1 and c.rooms[0]._inflight_said == "owed"


# ------------------------------------------------------------------ idle
def test_idle_is_written_once_after_a_start_and_not_again_each_pass(rig, monkeypatch):
    c, fake, _clock = rig
    seen = recorded(monkeypatch, fake)
    for _ in range(5):
        pass_over(c)
    assert states(seen) == ["idle"]


def test_an_idle_that_was_not_answered_is_written_again_at_the_next_pass(started, monkeypatch):
    c, fake, _clock = started
    seen = recorded(monkeypatch, fake, answer=lambda state, n: None if state == "idle" and n <= 2 else 200)
    c._execute_shot(c.rooms[0], 1, 60, 5)
    pass_over(c)
    assert c.rooms[0]._inflight_said == "owed"
    pass_over(c)
    assert states(seen) == ["open", "idle", "idle"]
    pass_over(c)
    pass_over(c)
    assert states(seen) == ["open", "idle", "idle", "idle"]
    assert fake.sets[SENSOR][0] == "idle" and c.rooms[0]._inflight_said == "idle"


def _open_in_home_assistant(fake, **over):
    attrs = {"zone": 1, "valve": "switch.v1", "mainline": "switch.m", "pump": "switch.p", "started": "x",
             "opened_s": 4.0, "max_s": 200.0, **over}
    fake.set_state(SENSOR, "open", attrs)


@pytest.mark.parametrize("on, state", [("switch.v1", "on"), ("switch.m", "on"), ("switch.p", "on"),
                                       ("switch.v1", "unavailable"), ("switch.p", "unknown")])
def test_at_a_start_an_open_whose_device_does_not_read_off_is_left_standing(rig, monkeypatch, on, state):
    """The state file was lost, or its record could not be used: this controller has no record of the shot.
    The "open" in Home Assistant is all the integration's guard has, so it is not written over."""
    c, fake, _clock = rig
    _open_in_home_assistant(fake)
    fake.set_state(on, state)
    seen = recorded(monkeypatch, fake)
    for _ in range(3):
        pass_over(c)
    assert states(seen) == [] and fake.states[SENSOR][0] == "open"
    fake.set_state(on, "off")  # the guard, or a person, closed it
    pass_over(c)
    pass_over(c)
    assert states(seen) == ["idle"]


def test_at_a_start_no_shot_writes_over_an_open_that_stands(rig, monkeypatch):
    """Zone 1's shot was left open and this controller has no record of it. Zone 2 waters: its "open", and the
    "idle" after it, would take zone 1's shot away from the guard. Neither is written."""
    c, fake, _clock = rig
    _open_in_home_assistant(fake)
    fake.set_state("switch.v1", "on")
    pass_over(c)  # the first pass: not settled
    seen = recorded(monkeypatch, fake)
    c._execute_shot(c.rooms[0], 2, 60, 5)
    pass_over(c)
    assert states(seen) == [] and fake.states[SENSOR][1]["valve"] == "switch.v1"
    assert c.rooms[0].state[2]["shots"] == 1  # the shot itself ran


def test_at_a_start_a_device_home_assistant_no_longer_has_does_not_keep_the_room_without_a_guard(rig, monkeypatch):
    """A plug was replaced and has a new id: the old name in a stale "open" answers 404 for ever. It is not on."""
    c, fake, _clock = rig
    _open_in_home_assistant(fake, valve="switch.old_plug")
    seen = recorded(monkeypatch, fake)
    pass_over(c)
    assert states(seen) == ["idle"] and c.rooms[0]._inflight_said == "idle"


def test_at_a_start_an_open_long_past_its_time_is_written_over_and_said(rig, monkeypatch, capsys):
    """A device named in it never reads off again (a dead plug). The integration has had its time with that
    shot; the "open" must not keep every later shot of the room unwritten for ever."""
    c, fake, _clock = rig
    age = 200.0 + controller.INFLIGHT_STALE_S
    seen = recorded(monkeypatch, fake)
    for seconds, written in ((age - 5, []), (age + 5, ["idle"])):
        stamp = (interrupted.datetime.now(interrupted.timezone.utc) - interrupted.timedelta(seconds=seconds)).isoformat()
        fake.set_state(SENSOR, "open", {"zone": 1, "valve": "switch.v1", "mainline": "switch.m", "pump": "switch.p",
                                        "started": "x", "opened_s": 4.0, "max_s": 200.0}, last_updated=stamp)
        fake.set_state("switch.v1", "unavailable")
        pass_over(c)
        pass_over(c)
        assert states(seen) == written, seconds
    out = capsys.readouterr().out
    assert out.count("left for the integration to close") == 1  # said once, not at each pass
    assert out.count("long past its time") == 1
    assert controller.INFLIGHT_STALE_S == 600.0


def test_the_start_reads_the_state_before_the_first_pass_so_its_shots_are_written(rig, monkeypatch):
    """run(): one read for each room before the loop. Without it the shots of the first pass after every start
    would have no second guard, and a start after an update is when a hang is most likely."""
    c, fake, _clock = rig
    seen = recorded(monkeypatch, fake)

    class Started(Exception):
        pass

    def first_pass(now):
        assert states(seen) == ["idle"] and c.rooms[0]._inflight_said == "idle"  # known before the pass
        c._execute_shot(c.rooms[0], 1, 60, 5)
        raise Started

    monkeypatch.setattr(c, "_start_dosing", lambda: None)
    monkeypatch.setattr(c, "loop_once", first_pass)
    monkeypatch.setattr(c, "_sleep_for", lambda seconds: (_ for _ in ()).throw(Started()))
    with pytest.raises(Started):
        c.run()
    assert states(seen) == ["idle", "open"]


def test_open_is_written_after_the_rounds_own_reads(started, monkeypatch):
    """The kill switch, the holds and the valve are read first in each round: the write never makes them later."""
    c, fake, _clock = started
    order = []
    real_stop, real_say = c._operator_stop, c._say_open
    monkeypatch.setattr(c, "_operator_stop", lambda *a, **k: order.append("reads") or real_stop(*a, **k))
    monkeypatch.setattr(c, "_say_open", lambda *a, **k: order.append("say") or real_say(*a, **k))
    monkeypatch.setattr(c, "_keep_alive", lambda remaining: order.append("keep alive"))
    c._execute_shot(c.rooms[0], 1, 4, 5)
    wait = order[order.index("say") - 1:]
    assert wait[:3] == ["reads", "say", "keep alive"]


@pytest.mark.parametrize("attrs", [{}, {"mainline": "", "pump": None}, {"valve": ["switch.v1"]}])
def test_at_a_start_an_open_whose_devices_all_read_off_becomes_idle(rig, monkeypatch, attrs):
    """Also one a room with no main line or pump wrote, and one this controller cannot have written."""
    c, fake, _clock = rig
    _open_in_home_assistant(fake, **attrs)
    seen = recorded(monkeypatch, fake)
    pass_over(c)
    assert states(seen) == ["idle"]


@pytest.mark.parametrize("state", ["idle", "unknown"])
def test_at_a_start_a_state_that_is_not_open_is_nothing_to_wait_for(rig, monkeypatch, state):
    c, fake, _clock = rig
    fake.set_state(SENSOR, state)
    fake.set_state("switch.v1", "on")  # a person waters by hand: no business of this state
    seen = recorded(monkeypatch, fake)
    pass_over(c)
    assert states(seen) == ["idle"] and c.rooms[0]._inflight_said == "idle"


@pytest.mark.parametrize("status", [None, 500])
def test_at_a_start_nothing_is_written_while_home_assistant_does_not_answer_the_read(rig, monkeypatch, status):
    c, fake, _clock = rig
    _open_in_home_assistant(fake)
    seen = recorded(monkeypatch, fake)
    asked = []

    def unanswered(entity, **_k):
        asked.append(entity)
        return status, controller.HAState()

    monkeypatch.setattr(controller, "ha_get_status", unanswered)
    pass_over(c)
    assert asked == [SENSOR] and states(seen) == [] and c.rooms[0]._inflight_said is None
    monkeypatch.setattr(controller, "ha_get_status", fake.ha_get_status)
    pass_over(c)
    assert states(seen) == ["idle"]


def test_while_a_close_is_not_confirmed_open_stands(started, monkeypatch):
    """A valve that does not close: the record stays (CS-301), and so does "open" in Home Assistant, so the
    integration's guard still has the shot."""
    c, fake, _clock = started
    seen = recorded(monkeypatch, fake)
    real = controller.ha_call

    def stuck(domain, service, **data):
        if service == "turn_off" and data.get("entity_id") == "switch.v1":
            return True  # taken, and the valve stays on
        return real(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", stuck)
    c._execute_shot(c.rooms[0], 1, 60, 5)
    room = c.rooms[0]
    assert room.shot_inflight and room.hardware_fault
    pass_over(c)
    c._say_stopped(interrupted.datetime(2026, 9, 23, 12, 0), controller.time.monotonic() + 20)
    assert states(seen) == ["open"] and fake.sets[SENSOR][0] == "open"


# ------------------------------------------------------------------ a stop
def test_a_stop_says_idle_for_the_shot_it_closed(started, monkeypatch):
    """A stop closes the shot that runs (its own cleanup). The "open" must not stand until the next start: a
    device somebody switches in between would look like that shot's."""
    c, fake, clock = started
    seen = recorded(monkeypatch, fake)
    room = c.rooms[0]
    c._execute_shot(room, 1, 60, 5)  # said "open"; closed
    assert room._inflight_said == "open" and room.shot_inflight is None
    c._say_stopped(interrupted.datetime(2026, 9, 23, 12, 0), clock.monotonic() + 20)
    assert states(seen) == ["open", "idle"]
    assert [row[4] for row in seen if row[0] == "set" and row[1] == SENSOR][-1] <= 1.0  # inside the stop's budget


def test_a_stop_says_an_idle_that_a_failed_write_left_owed(started, monkeypatch):
    c, fake, clock = started
    c.rooms[0]._inflight_said = "owed"
    seen = recorded(monkeypatch, fake)
    c._say_stopped(interrupted.datetime(2026, 9, 23, 12, 0), clock.monotonic() + 20)
    assert states(seen) == ["idle"]


@pytest.mark.parametrize("budget, written", [(0.6, True), (0.4, False)])
def test_a_stops_idle_takes_its_share_of_the_time_that_is_left_and_no_less_than_a_quarter_second(
        started, monkeypatch, budget, written):
    """One room: the heartbeat's write gets half of what is left, then "idle" half of what is left then."""
    c, fake, clock = started
    c.rooms[0]._inflight_said = "open"
    seen = recorded(monkeypatch, fake)
    c._say_stopped(interrupted.datetime(2026, 9, 23, 12, 0), clock.monotonic() + budget)
    assert states(seen) == (["idle"] if written else [])
    if written:
        assert [row[4] for row in seen if row[0] == "set" and row[1] == SENSOR] == [pytest.approx(budget / 2)]


@pytest.mark.parametrize("said_before", [None, "idle"])
def test_a_stop_writes_no_idle_it_does_not_owe(rig, monkeypatch, said_before):
    """Not known since the start (an "open" may stand for the guard), or "idle" is there already."""
    c, fake, clock = rig
    c.rooms[0]._inflight_said = said_before
    seen = recorded(monkeypatch, fake)
    c._say_stopped(interrupted.datetime(2026, 9, 23, 12, 0), clock.monotonic() + 20)
    assert states(seen) == []


def test_a_stop_with_no_time_left_writes_no_idle(started, monkeypatch):
    c, fake, clock = started
    c.rooms[0]._inflight_said = "open"
    seen = recorded(monkeypatch, fake)
    c._say_stopped(interrupted.datetime(2026, 9, 23, 12, 0), clock.monotonic() + 0.3)
    assert states(seen) == []


# ------------------------------------------------------------------ the other valves on the line
def _other_room(hw):
    other = type("Room", (), {})()
    other.hw = hw
    return other


@pytest.mark.parametrize("hw, shares", [
    ({"pump": "switch.p", "mainline": None, "valves": {1: "switch.b1"}}, True),
    ({"pump": "switch.p2", "mainline": "switch.m", "valves": {1: "switch.b1"}}, True),
    ({"pump": "switch.p2", "mainline": None, "valves": {1: "switch.b1"}}, False),
])
def test_a_room_on_the_same_pump_or_main_line_adds_its_valves(rig, hw, shares):
    c, fake, _clock = rig
    room = c.rooms[0]
    room.shot_inflight = dict(interrupted.RECORD)
    c.rooms.append(_other_room(hw))
    try:
        c._say_inflight(room, {"opened_s": 4.0, "max_s": 200.0})
    finally:
        c.rooms.pop()
    state, attrs = fake.sets[SENSOR]
    assert state == "open" and (attrs["opened_s"], attrs["max_s"]) == (4.0, 200.0)
    assert attrs["line_valves"] == (["switch.b1", "switch.v2"] if shares else ["switch.v2"])


@pytest.mark.parametrize("none", [None, ""])
def test_two_rooms_with_no_main_line_do_not_share_one(rig, none):
    """The setup wizard writes "" for a room with no main line: two such rooms on two pumps share nothing."""
    c, fake, _clock = rig
    room = c.rooms[0]
    room.shot_inflight = {**interrupted.RECORD, "mainline": none}
    c.rooms.append(_other_room({"pump": "switch.p2", "mainline": none, "valves": {1: "switch.b1"}}))
    try:
        c._say_inflight(room, {"opened_s": 4.0, "max_s": 200.0})
    finally:
        c.rooms.pop()
    assert fake.sets[SENSOR][1]["line_valves"] == ["switch.v2"]
