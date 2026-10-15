"""Stopping the app (SIGTERM) closes what is in flight inside a time budget, however slow Home Assistant is.

The Supervisor kills the app `timeout: 30` s after SIGTERM (config.yaml). The safe-off used to wait on
every read and switch-off at its full timeout, so a slow Home Assistant could see it killed half way,
before it had saved the state file. Now it runs inside runtime_env.stop_budget(): 25 s, or
F2_STOP_BUDGET_S. Dosing is told to start nothing before the first irrigation call; each room with a
shot recorded gets an equal share of the time (the shot running now first), so a slow room never
takes the next one's; what no longer fits is not sent and stays recorded for the next start; and the
state file is always saved.

These run on a test clock. The slow Home Assistant here answers each call a set time after it is made,
or never; a call whose timeout is shorter fails when its timeout is up, as a requests timeout does, so
the stop must never cut a call shorter than Home Assistant is answering: a slow Home Assistant costs
reads, never the offs they prove, and a read that is not made or not answered never counts as off.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

import controller
import runtime_env
from test_controller import _build, _desc

KILL, KILL_B, KILL_C = "input_boolean.kill", "input_boolean.kill_b", "input_boolean.kill_c"
A = ("switch.v1", "switch.m", "switch.p")  # the room whose shot is running now
B = ("switch.vb1", "switch.mb", "switch.pb")  # a room with an older shot recorded, its kill switch on
C_VALVES = ("switch.vc1", "switch.vc2")  # a third room on A's main line and pump
DOSING = {"default": ["switch.dose_power", "switch.fill"], "b": ["switch.dose_power_b", "switch.fill_b"]}
STARTED = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=10)


def at(seconds):
    return (STARTED + timedelta(seconds=seconds)).isoformat()


class Clock:
    def __init__(self):
        self.seconds = 1000.0

    def sleep(self, seconds):
        self.seconds += seconds

    def monotonic(self):
        return self.seconds


@pytest.fixture
def rig(monkeypatch, tmp_path):
    c, fake = _build(
        {"num_zones": 1, "enable_flag": KILL},
        states={
            "sensor.crop_steering_engine_config": ("ok", _desc(enable_flag=KILL)),
            "sensor.crop_steering_b_engine_config": ("ok", _desc(
                prefix="b_", slug="b", pump="switch.pb", mainline="switch.mb",
                valves={"1": "switch.vb1"}, enable_flag=KILL_B)),
            "sensor.crop_steering_c_engine_config": ("ok", _desc(
                prefix="c_", slug="c", valves={"1": "switch.vc1", "2": "switch.vc2"}, num=2,
                enable_flag=KILL_C)),
            KILL: ("on", {}), KILL_B: ("on", {}), KILL_C: ("on", {}),
        },
    )
    rooms = {room.slug: room for room in c.rooms}
    assert set(rooms) == {"default", "b", "c"}
    c._state_path = str(tmp_path / "state.json")
    # Both rooms' switches went on when their shots opened them, and Home Assistant restarted since
    # (last_changed is two minutes into the shot): only their history says they are still the shots'.
    for room, switches in (("default", A), ("b", B)):
        rooms[room].shot_inflight = {"zone": 1, "valve": switches[0], "mainline": switches[1],
                                     "pump": switches[2], "started": STARTED.isoformat()}
        for entity in switches:
            fake.set_state(entity, "on", last_updated=at(120))
            fake.history[entity] = [("off", at(-60)), ("on", at(1)), ("unavailable", at(115)), ("on", at(120))]
    c._shot_room = rooms["default"]
    for slug, entities in DOSING.items():
        c.dosing._doc["rooms"][slug] = {"inflight": {"kind": "dose", "off": entities}}
        for entity in entities:
            fake.set_state(entity, "on")
    assert c.dosing._write()
    clock = Clock()
    monkeypatch.setattr(controller.time, "sleep", clock.sleep)
    monkeypatch.setattr(controller.time, "monotonic", clock.monotonic)
    c.dosing._mono = clock.monotonic
    fake.calls.clear()
    return c, fake, clock, rooms


def slow(monkeypatch, c, fake, clock, latency=None):
    """Home Assistant answers each call `latency(kind, entity)` seconds after it is made (never, when
    that is None), as it does when it is slow: a call whose timeout is shorter fails when the timeout is
    up, as a requests timeout does, and an off it carried is not taken. Returns every call made, as
    (kind, entity, whether dosing had been told to start nothing by then)."""
    made = []

    def answer(kind, entity, timeout):
        made.append((kind, entity, c.dosing._exiting))
        took = None if latency is None else latency(kind, entity)
        if took is None or timeout < took:
            clock.sleep(timeout)
            return False
        clock.sleep(took)
        return True

    def get(entity, timeout=8):
        return fake.ha_get(entity) if answer("get", entity, timeout) else controller.HAState()

    def call(domain, service, timeout=12, **data):
        return answer(service, data.get("entity_id"), timeout) and fake.ha_call(domain, service, **data)

    def history(entity, since, timeout=12):
        return fake.ha_history(entity, since) if answer("history", entity, timeout) else None

    for name, shim in (("ha_get", get), ("ha_call", call), ("ha_history", history)):
        monkeypatch.setattr(controller, name, shim)
    return made


def sent(made):
    return [entity for kind, entity, _ in made if kind == "turn_off"]


def every(seconds):
    return lambda kind, entity: seconds


def opened_by_the_shot(fake, *entities):
    """These went on when the shot opened them, and nothing has changed them since."""
    for entity in entities:
        fake.changed[entity] = at(1)


def offs(fake):
    return [d["entity_id"] for dom, svc, d in fake.calls if svc == "turn_off"]


def stop(c, clock):
    began = clock.seconds
    with pytest.raises(SystemExit):
        c._safe_exit()
    return clock.seconds - began


def saved(c):
    with open(c._state_path) as fh:
        return json.load(fh)


def dosing_file(c):
    with open(c.dosing.path) as fh:
        return json.load(fh)


@pytest.mark.parametrize("budget", [None, "75"])
def test_a_home_assistant_that_never_answers_never_takes_the_stop_past_its_budget(rig, monkeypatch, budget):
    c, fake, clock, rooms = rig
    if budget:
        monkeypatch.setenv("F2_STOP_BUDGET_S", budget)
    else:
        monkeypatch.delenv("F2_STOP_BUDGET_S", raising=False)
    made = slow(monkeypatch, c, fake, clock)

    took = stop(c, clock)

    assert took <= float(budget or 25) + 2
    assert made[0][2] is True  # dosing was told to start nothing before the first irrigation call
    assert sent(made)[0] == "switch.v1"  # the running shot's valve is still tried first
    # Nothing was taken, so everything stays recorded for the next start: both shots, every dose.
    on_disk = saved(c)
    assert on_disk["default"]["_shot_inflight"]["valve"] == "switch.v1"
    assert on_disk["b"]["_shot_inflight"]["valve"] == "switch.vb1"
    assert {slug: block["inflight"]["off"] for slug, block in dosing_file(c)["rooms"].items()} == DOSING


def jitter(low, high):
    """Answers that take between `low` and `high` seconds, never the same twice in a row."""
    times = iter(low + (high - low) * (n % 5) / 4 for n in range(10_000))
    return lambda kind, entity: next(times)


ONE_ROOM_ONE_DOSE, ONE_ROOM, TWO_ROOMS = "one room, one dose", "one room", "two rooms and dosing"


def scene(c, fake, rooms, which):
    """The running shot's switches went on when it opened them; `which` says what else is recorded."""
    opened_by_the_shot(fake, *A, *B)
    if which != TWO_ROOMS:
        rooms["b"].shot_inflight = None
        c.dosing._doc["rooms"].pop("b")
    if which == ONE_ROOM:
        c.dosing._doc["rooms"].clear()
    rooms["c"].hw["mainline"] = rooms["c"].hw["pump"] = None  # the third room has its own line here


@pytest.mark.parametrize("which, latency", [
    (ONE_ROOM_ONE_DOSE, jitter(2.6, 3.0)),
    (ONE_ROOM_ONE_DOSE, every(3.0)),
    (ONE_ROOM, every(3.5)),
    (TWO_ROOMS, every(1.0)),
])
def test_a_slow_home_assistant_still_takes_every_off_of_the_running_shot(rig, monkeypatch, which, latency):
    """However slow Home Assistant is, as long as the room's share holds its reads and offs, a call is
    never cut shorter than it is answering: every off of the running shot is taken, valve first."""
    c, fake, clock, rooms = rig
    scene(c, fake, rooms, which)
    slow(monkeypatch, c, fake, clock, latency)
    took = stop(c, clock)
    assert took <= runtime_env.STOP_BUDGET_S + 2
    assert offs(fake)[:3] == list(A)
    assert all(fake.states[e][0] == "off" for e in A)
    if which == TWO_ROOMS:
        assert fake.states["switch.vb1"][0] == "off"


@pytest.mark.parametrize("latency", [1.5, 2.0, 2.5])
def test_with_two_rooms_and_dosing_the_running_shots_valve_is_taken_first(rig, monkeypatch, latency):
    """Too slow for both rooms' every switch: the running shot's valve is still the first off taken,
    and the older shot's valve is taken too."""
    c, fake, clock, rooms = rig
    scene(c, fake, rooms, TWO_ROOMS)
    slow(monkeypatch, c, fake, clock, every(latency))
    took = stop(c, clock)
    assert took <= runtime_env.STOP_BUDGET_S + 2
    assert offs(fake)[0] == "switch.v1"
    assert fake.states["switch.v1"][0] == "off" and fake.states["switch.vb1"][0] == "off"
    on_disk = saved(c)
    for slug, switches in (("default", A), ("b", B)):
        if any(fake.states[e][0] == "on" for e in switches):  # not all switched off: still recorded
            assert on_disk[slug]["_shot_inflight"]["valve"] == switches[0], slug


@pytest.mark.parametrize("which", [ONE_ROOM_ONE_DOSE, ONE_ROOM])
@pytest.mark.parametrize("latency, hold_latency", [(2.8, 2.8), (3.0, 5.0), (3.0, 10.0), (5.0, 5.0), (9.0, 9.0)])
def test_a_hold_that_could_not_be_read_in_time_leaves_the_pump_on(rig, monkeypatch, which, latency, hold_latency):
    """The tank is circulating (a hold is on). However slow Home Assistant is, a hold read that is not
    made or not answered never counts as off: the pump stays on."""
    c, fake, clock, rooms = rig
    scene(c, fake, rooms, which)
    c.hold_entities = ["input_boolean.circulating"]
    fake.set_state("input_boolean.circulating", "on")
    made = slow(monkeypatch, c, fake, clock,
                lambda kind, entity: hold_latency if entity == "input_boolean.circulating" else latency)
    stop(c, clock)
    assert "switch.p" not in sent(made) and fake.states["switch.p"][0] == "on"


@pytest.mark.parametrize("unanswered", ["switch.vc1", "switch.vc2"])
def test_another_valve_on_the_line_that_could_not_be_read_leaves_the_line_on(rig, monkeypatch, unanswered):
    """Someone is hand-watering a zone of the third room, on the running shot's main line and pump. A
    read of that room's valves that is not answered in time never counts as closed: the main line and
    pump stay on and stay recorded, and only the shot's own valve is switched off."""
    c, fake, clock, rooms = rig
    scene(c, fake, rooms, ONE_ROOM)
    rooms["c"].hw["mainline"], rooms["c"].hw["pump"] = "switch.m", "switch.p"
    fake.set_state("switch.vc2", "on")
    made = slow(monkeypatch, c, fake, clock, lambda kind, entity: 10.0 if entity == unanswered else 2.0)
    stop(c, clock)
    assert sent(made) == ["switch.v1"] and offs(fake) == ["switch.v1"]
    assert fake.states["switch.m"][0] == "on" and fake.states["switch.p"][0] == "on"
    assert saved(c)["default"]["_shot_inflight"]["mainline"] == "switch.m"


def test_with_a_prompt_home_assistant_the_stop_closes_everything_as_before(rig):
    c, fake, clock, rooms = rig
    took = stop(c, clock)
    assert took <= runtime_env.STOP_BUDGET_S
    assert offs(fake)[:6] == [*A, *B]  # each shot's own, valve first, the running one first
    assert all(fake.states[e][0] == "off" for e in (*A, *B))
    assert sorted(offs(fake)[6:]) == sorted(DOSING["default"] + DOSING["b"])
    on_disk = saved(c)
    assert "_shot_inflight" not in on_disk["default"] and "_shot_inflight" not in on_disk["b"]
    assert rooms["default"].shot_inflight is None and rooms["b"].shot_inflight is None


def test_the_running_shots_valve_is_switched_off_when_whose_it_is_cannot_be_told(rig):
    c, fake, clock, rooms = rig
    rooms["b"].shot_inflight = None
    fake.history.update(dict.fromkeys(A))  # no recorder: nothing says the valve is still the shot's
    stop(c, clock)
    assert offs(fake)[:1] == ["switch.v1"]
    assert fake.states["switch.m"][0] == "on" and fake.states["switch.p"][0] == "on"
    assert saved(c)["default"]["_shot_inflight"]["valve"] == "switch.v1"  # the rest stays recorded


def test_an_older_shot_whose_switches_cannot_be_told_is_still_left_alone(rig):
    c, fake, clock, rooms = rig
    c._shot_room = None  # no shot running now: both records are older ones
    fake.history.update(dict.fromkeys((*A, *B)))  # no recorder: whose they are cannot be told
    stop(c, clock)
    assert [e for e in offs(fake) if e in (*A, *B)] == []
    assert saved(c)["default"]["_shot_inflight"] and saved(c)["b"]["_shot_inflight"]


def test_dosing_keeps_its_part_of_the_budget_only_while_it_has_something_recorded(rig, monkeypatch):
    c, _fake, clock, _rooms = rig
    given = []
    monkeypatch.setattr(c, "_safe_off", lambda deadline: given.append(deadline - clock.seconds))
    stop(c, clock)
    c.dosing._doc["rooms"].clear()
    stop(c, clock)
    assert given == [runtime_env.STOP_BUDGET_S - controller.STOP_DOSING_S, runtime_env.STOP_BUDGET_S]


def test_the_state_file_is_saved_even_when_the_safe_off_fails(rig, monkeypatch):
    c, _fake, clock, rooms = rig

    def broken(deadline):
        raise RuntimeError("boom")

    monkeypatch.setattr(c, "_safe_off", broken)
    rooms["default"].state[1]["daily_vol"] = 4.5
    stop(c, clock)
    assert saved(c)["default"]["1"]["daily_vol"] == 4.5


def test_the_normal_close_after_a_shot_waits_as_it_always_did(rig, monkeypatch):
    c, fake, clock, rooms = rig
    rooms["default"].shot_inflight = None
    for entity in A:
        fake.set_state(entity, "off")
    seen = []
    real = controller.Controller._confirm_switches

    def confirm(entities, want, deadline=None):
        seen.append(deadline)
        return real(entities, want, deadline)

    monkeypatch.setattr(controller.Controller, "_confirm_switches", staticmethod(confirm))
    c._execute_shot(rooms["default"], 1, 10, 5, flow_lps=0.05)
    assert seen == [None]


APP = {"F2_RUNTIME": "addon", "SUPERVISOR_TOKEN": "t"}  # what the Supervisor gives the app


@pytest.mark.parametrize("runtime, default", [(APP, 25.0), ({"F2_RUNTIME": "container"}, 75.0), ({}, 25.0),
                                              ({"SUPERVISOR_TOKEN": "t"}, 25.0)])
@pytest.mark.parametrize(
    "value, budget",
    [(None, None), ("", None), ("40", 40.0), ("7.5", 7.5), ("0", None), ("-3", None), ("soon", None),
     ("nan", None), ("inf", None)],
)
def test_the_stop_budget_is_f2_stop_budget_s_when_it_is_a_number_above_0(runtime, default, value, budget):
    env = dict(runtime) if value is None else {**runtime, "F2_STOP_BUDGET_S": value}
    assert runtime_env.stop_budget(env) == (default if budget is None else budget)


BEATS = {"default": "sensor.crop_steering_ai_heartbeat", "b": "sensor.crop_steering_b_ai_heartbeat",
         "c": "sensor.crop_steering_c_ai_heartbeat"}


def test_the_stop_ends_with_every_rooms_heartbeat_saying_stopped(rig):
    """An update, a restart or a stop by hand: the dashboard shows a stopped controller, and since when,
    not one that went quiet. The integration still finds each room's engine switch, and no grow plan is
    armed on a stopped controller."""
    c, fake, clock, rooms = rig
    rooms["c"]._beat = (None, False)  # its last report said the room is off
    fake.sets.clear()
    took = stop(c, clock)
    assert took <= runtime_env.STOP_BUDGET_S
    for slug, beat in BEATS.items():
        state, attrs = fake.sets[beat]
        assert state == "stopped" and attrs["stopped_at"] == attrs["last_beat"], slug
        assert attrs["controller_version"] == controller.CONTROLLER_VERSION
        assert attrs["enable_flag"] == rooms[slug].enable_flag
        assert "strategy_snapshot_version" not in attrs
    assert fake.sets[BEATS["c"]][1]["room_active"] is False
    assert fake.sets[BEATS["default"]][1]["room_active"] is True


def unanswered_writes(monkeypatch, clock):
    """Home Assistant never answers a state write: requests waits out the connect and then the read."""
    tried = []

    def put(entity, state, attributes=None, timeout=8):
        tried.append((entity, timeout))
        clock.sleep(2 * timeout)

    monkeypatch.setattr(controller, "ha_set", put)
    return tried


def test_the_stopped_heartbeat_fits_in_what_is_left_of_the_budget(rig, monkeypatch):
    c, _fake, clock, _rooms = rig
    monkeypatch.setattr(c, "_safe_off", lambda deadline: clock.sleep(deadline - clock.seconds - 3))
    tried = unanswered_writes(monkeypatch, clock)
    took = stop(c, clock)
    assert took <= runtime_env.STOP_BUDGET_S
    assert [entity for entity, _ in tried] == list(BEATS.values())


def test_a_stop_with_no_time_left_sends_no_heartbeat(rig, monkeypatch):
    c, _fake, clock, _rooms = rig
    c.dosing._doc["rooms"].clear()
    monkeypatch.setattr(c, "_safe_off", lambda deadline: clock.sleep(deadline - clock.seconds))
    tried = unanswered_writes(monkeypatch, clock)
    took = stop(c, clock)
    assert took <= runtime_env.STOP_BUDGET_S and tried == []


def test_a_home_assistant_that_never_answers_still_stops_inside_the_budget_with_the_heartbeat(rig, monkeypatch):
    c, fake, clock, _rooms = rig
    slow(monkeypatch, c, fake, clock)
    tried = unanswered_writes(monkeypatch, clock)
    took = stop(c, clock)
    assert took <= runtime_env.STOP_BUDGET_S + 2  # the safe-off's own bound: the heartbeat adds nothing
    assert all(timeout >= 0.25 for _, timeout in tried)
