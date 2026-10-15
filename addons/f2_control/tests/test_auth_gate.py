"""A standalone container whose token Home Assistant refuses while it runs (controller._AuthGate), and the
close-only start for a token that works but is not an administrator's (controller.close_only_start).

Every request Home Assistant refuses counts as a failed login there and walks the machine toward an IP
ban, so a container sends nothing more once refused, except this process's own close of what it has
on: the shot in flight's valve, main line and pump (one turn_off each, then reads back until one is
refused) and a running dose's or batch's hardware. Then it parks: with nothing recorded it sends
nothing at all; with something recorded it asks again (one read of a recorded switch) every 60 s for
10 min and every 15 min after, because a proxy in front of Home Assistant may refuse for a while and
recover, and an accepted answer carries the run on. The Home Assistant app is never gated.

These drive the controller's real ha_* functions against Home Assistant's REST API over a FakeHA's
states (Session), on a test clock.
"""
import json
from datetime import datetime

import pytest

import controller
import fake_ha
import runtime_env
from test_dosing_runner import _full_batch, make_rig

KILL = "input_boolean.kill"
PUMP, MAIN, VALVE = "switch.p", "switch.m", "switch.v1"
OPTIONS = {"num_zones": 1, "enable_flag": KILL, "hardware": {"pump": PUMP, "mainline": MAIN, "valves": {"1": VALVE}}}
CONTAINER = {"F2_RUNTIME": "container", "HA_URL": "http://ha:8123", "HA_TOKEN": "tok"}
# The controller's own REST functions, before any other test module's fake_ha.install replaces them.
REST = ("ha_get", "ha_get_status", "ha_call", "ha_get_all", "ha_set", "ha_service_response", "ha_fire")
REAL = {name: getattr(controller, name) for name in REST}


class Hour(Exception):
    """The test clock ran out while the controller was parked."""


class Clock:
    def __init__(self, until=3600.0):
        self.seconds, self.until, self.due = 0.0, until, []

    def at(self, seconds, action):
        self.due.append((seconds, action))
        self.due.sort(key=lambda item: item[0])

    def sleep(self, seconds):
        end = self.seconds + seconds
        while self.due and self.due[0][0] <= end:
            when, action = self.due.pop(0)
            self.seconds = max(self.seconds, when)
            action()
        self.seconds = end
        if self.seconds > self.until:
            raise Hour

    def monotonic(self):
        return self.seconds


class Answer:
    headers = {}

    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class Session:
    """Home Assistant's REST API over a FakeHA's states. `refuse(method, path)` -> 401/403 to refuse."""

    def __init__(self, fake, clock):
        self.fake, self.clock, self.sent = fake, clock, []
        self.refuse = lambda method, path: None

    def get(self, url, headers=None, timeout=None, params=None):
        return self._answer("GET", url, None)

    def post(self, url, headers=None, json=None, timeout=None, params=None):
        return self._answer("POST", url, json)

    def _answer(self, method, url, data):
        path = url.split("/api", 1)[1]
        status = self.refuse(method, path)
        status, body = (status, {"message": "refused"}) if status else self._serve(method, path, data or {})
        self.sent.append((self.clock.seconds, method, path, status))
        return Answer(status, body)

    def _serve(self, method, path, data):
        fake = self.fake
        if path in ("/", ""):
            return 200, {"message": "API running."}
        if path == "/config":
            return 200, {"time_zone": "UTC"}
        if method == "GET" and path == "/states":
            return 200, fake.ha_get_all()
        if path.startswith("/states/"):
            entity = path[len("/states/"):]
            if method == "POST":
                fake.ha_set(entity, data.get("state"), data.get("attributes"))
                return 200, {}
            if entity not in fake.states:
                return 404, {"message": "Entity not found."}
            state, attributes, updated = fake.states[entity]
            return 200, {"state": state, "attributes": attributes, "last_updated": updated,
                         "last_changed": fake.changed.get(entity)}
        if method == "POST" and path.startswith("/services/"):
            domain, service = path[len("/services/"):].split("/", 1)
            fake.ha_call(domain, service, **data)
            return 200, []
        return 404, {"message": "Not found."}

    def refused(self):
        return [s for s in self.sent if s[3] in (401, 403)]

    def after(self, seconds):
        return [s for s in self.sent if s[0] >= seconds]


@pytest.fixture
def rig(monkeypatch):
    def build(env=CONTAINER, options=OPTIONS, until=3600.0):
        for name in ("F2_RUNTIME", "SUPERVISOR_TOKEN", "HA_URL"):
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        monkeypatch.setattr(controller, "_GATE", controller._AuthGate())
        fake, clock = fake_ha.FakeHA(), Clock(until)
        for entity in (KILL, "switch.crop_steering_system_enabled", "switch.crop_steering_auto_irrigation_enabled",
                       "switch.crop_steering_room_active", "switch.crop_steering_zone_1_enabled"):
            fake.set_state(entity, "on")
        for entity in (PUMP, MAIN, VALVE):
            fake.set_state(entity, "off")
        session = Session(fake, clock)
        monkeypatch.setattr(controller, "_session", lambda: session)
        for name in REST:
            monkeypatch.setattr(controller, name, REAL[name])
        monkeypatch.setattr(controller, "load_options", lambda: dict(options))
        monkeypatch.setattr(controller.time, "sleep", clock.sleep)
        monkeypatch.setattr(controller.time, "monotonic", clock.monotonic)
        c = controller.Controller()
        c._start_dosing = lambda: None  # the dosing thread's side is test_a_batch_*, below
        session.sent.clear()
        return c, fake, session, clock

    return build


def switched(fake):
    return [(svc, d["entity_id"]) for dom, svc, d in fake.calls if dom == "switch"]


def refuse_from(session, seconds, status, until=None, only=None):
    """Refuse every request (or those `only(method, path)` picks) from `seconds` on, until `until`."""
    def refuse(method, path):
        clock = session.clock.seconds
        if clock >= seconds and (until is None or clock < until) and (only is None or only(method, path)):
            return status
        return None
    session.refuse = refuse


def shot(c, clock, seconds=60.0):
    try:
        c._execute_shot(c.rooms[0], 1, seconds, 2.0, flow_lps=0.02)
    except Hour:
        pass


def park(c):
    with pytest.raises(Hour):
        c._park_refused()


# ------------------------------------------------------------------ the app: never gated
def test_the_app_is_never_gated_and_says_so_at_most_every_10_min(rig, capsys):
    c, fake, session, clock = rig(env={"F2_RUNTIME": "addon", "SUPERVISOR_TOKEN": "t"})
    refuse_from(session, 0, 401)
    for _ in range(25):  # 25 simulated minutes of passes, every request refused
        c.loop_once(datetime.now())
        clock.sleep(60)
    assert controller._GATE.state is None
    assert len(session.refused()) > 25  # every pass still asks, as the app always has
    assert capsys.readouterr().out.count("Home Assistant rejected a request") == 3  # at 0, 10 and 20 min


# ------------------------------------------------------------------ (a) between shots, nothing recorded
def test_a_refused_token_between_shots_sends_one_request_and_then_nothing(rig, capsys):
    c, fake, session, clock = rig()
    refuse_from(session, 0, 401)
    c.loop_once(datetime.now())
    park(c)
    assert len(session.refused()) == 1 and len(session.sent) == 1
    assert switched(fake) == []
    assert "nothing more is sent" in capsys.readouterr().out


# ------------------------------------------------------------------ (d) a 403 mid-shot that clears
def test_a_403_mid_shot_closes_the_shot_parks_and_carries_on_once_accepted(rig, capsys):
    c, fake, session, clock = rig()
    refuse_from(session, 20, 403, until=200)
    shot(c, clock)
    after = session.after(20)
    assert [(m, p) for _t, m, p, s in after if s == 403][1:] == [
        ("POST", "/services/switch/turn_off"), ("POST", "/services/switch/turn_off"),
        ("POST", "/services/switch/turn_off"), ("GET", f"/states/{VALVE}"),
    ]  # the first refusal ended the shot; then its own three offs and one read, nothing else
    assert controller._GATE.state == "all" and c.rooms[0].shot_inflight is not None
    assert c.rooms[0].hardware_fault is None  # refused, not stuck
    assert json.load(open(c._state_path))["default"]["_shot_inflight"]["valve"] == VALVE
    sent = len(session.sent)
    c._park_refused()  # returns: the probe at 60 s after the park... once Home Assistant accepts
    probes = session.sent[sent:]
    assert all((m, p) == ("GET", f"/states/{VALVE}") for _t, m, p, _s in probes)
    assert [s for *_rest, s in probes][-1] == 200 and len(probes) >= 2
    assert controller._GATE.state is None
    assert "probably a proxy in front of it" in capsys.readouterr().out
    c.loop_once(datetime.now())  # the reconciler closes what the shot left and reads it back
    assert c.rooms[0].shot_inflight is None
    assert fake.states[VALVE][0] == "off"
    assert ("turn_on", VALVE) not in switched(fake)[3:]


def test_a_403_that_clears_before_the_close_reopens_at_once(rig):
    c, fake, session, clock = rig()
    refuse_from(session, 20, 403, until=21)
    shot(c, clock)
    assert controller._GATE.state is None
    assert c.rooms[0].shot_inflight is None and fake.states[VALVE][0] == "off"
    assert switched(fake)[-3:] == [("turn_off", VALVE), ("turn_off", MAIN), ("turn_off", PUMP)]


# ------------------------------------------------------------------ (e) refused for good mid-shot
def test_a_401_for_good_mid_shot_asks_on_the_schedule_and_nothing_else(rig):
    c, fake, session, clock = rig()
    refuse_from(session, 20, 401)
    shot(c, clock)
    assert len(session.refused()) <= 1 + 4
    parked = clock.seconds
    clock.until = parked + 600 + 3600 + 1  # the first 10 min, then an hour
    sent = len(session.sent)
    park(c)
    probes = session.sent[sent:]
    assert all((m, p, s) == ("GET", f"/states/{VALVE}", 401) for _t, m, p, s in probes)
    times = [t - parked for t, *_rest in probes]
    assert times[:10] == [60.0 * n for n in range(1, 11)]
    assert times[10:] == [600.0 + 900.0 * n for n in range(1, len(times) - 9)]
    assert len(times) == 10 + 4


# ------------------------------------------------------------------ (b) the user is no longer an administrator
def test_a_refused_state_write_mid_shot_lets_the_shot_close_then_stops_and_sends_nothing(rig):
    c, fake, session, clock = rig()
    room = c.rooms[0]
    room._beat, room._beat_at = (None, True), -120.0  # a heartbeat is due during the shot
    refuse_from(session, 0, 401, only=lambda method, path: method == "POST" and path.startswith("/states/"))
    shot(c, clock)
    assert controller._GATE.state == "writes"
    writes = [s for s in session.sent if s[1] == "POST" and s[2].startswith("/states/")]
    assert len(writes) == 1  # refused once, never sent again
    assert room.shot_inflight is None and fake.states[VALVE][0] == "off"  # closed and read back
    assert switched(fake)[-3:] == [("turn_off", VALVE), ("turn_off", MAIN), ("turn_off", PUMP)]
    sent = len(session.sent)
    park(c)
    assert session.sent[sent:] == []


# ------------------------------------------------------------------ (f) mid-batch
def test_a_batch_refused_mid_fill_switches_its_hardware_off_once_and_keeps_its_record(tmp_path, monkeypatch):
    r = make_rig(tmp_path, monkeypatch)()
    _full_batch(r)
    refused = [False]
    r.runner._refused = lambda: refused[0]
    r.clock.at(30, lambda: refused.__setitem__(0, True))  # the fill valve opened at about 2 s
    r.ask("batch")
    r.poll()  # the main loop steps the batch until the refusal ends it
    assert r.runner._steps is None and not r.runner._recovered
    offs = [e for (s, e) in r.actions() if s == "turn_off"][4:]  # after the batch's own close step
    hardware = r.runner._dosing_hardware(r.runner._config(r.c.rooms[0]))
    assert sorted(offs) == sorted(hardware)  # one off each, no second round
    assert r.saved()["inflight"] is not None  # recovered once Home Assistant accepts again


def test_the_gate_lets_through_only_this_processs_own_offs_once_and_their_read_back():
    gate = controller._AuthGate()
    gate.container, gate.own = True, lambda: [VALVE, "switch.dose_power"]
    gate.saw("read", 403, "GET x")
    assert gate.state == "all"
    assert not gate.allows("read", VALVE)  # nothing is read before its off
    assert gate.allows("off", VALVE) and not gate.allows("off", VALVE)
    assert gate.allows("off", "switch.dose_power")
    assert not gate.allows("off", MAIN) and not gate.allows("write") and not gate.allows("other")
    assert gate.allows("read", VALVE)
    gate.saw("read", 403, "GET y")
    assert not gate.allows("read", VALVE)  # a read-back stops at its first refused read
    gate.saw("off", 200, "POST z")
    assert gate.state is None and gate.allows("other")


def test_a_closed_gate_fires_no_event(rig):
    """The controller's naming of its own setpoint writes (an event) goes through the gate like a service call."""
    c, fake, session, clock = rig()
    refuse_from(session, 0, 401)
    assert not controller.ha_fire("crop_steering_setpoint_write", {"entity_id": "number.x"})
    assert controller._GATE.state == "all" and len(session.sent) == 1
    assert not controller.ha_fire("crop_steering_setpoint_write", {"entity_id": "number.x"})
    assert len(session.sent) == 1


# ------------------------------------------------------------------ U8 (m): the close-only start
def test_a_non_admin_token_with_a_shot_recorded_closes_it_and_sends_nothing_more(rig, monkeypatch, tmp_path):
    first, fake, session, clock = rig()
    first.rooms[0].shot_inflight = {"zone": 1, "valve": VALVE, "mainline": MAIN, "pump": PUMP,
                                    "started": datetime.now().astimezone().isoformat()}
    first._save_state()
    fake.set_state(VALVE, "on")  # the previous run died with its valve open
    monkeypatch.setattr(controller, "_GATE", controller._AuthGate())
    monkeypatch.setattr(runtime_env, "_follows", lambda zone: True)
    refuse_from(session, 0, 401, only=lambda method, path: method == "POST" and path.startswith("/states/"))
    session.sent.clear()
    env = {**CONTAINER, "TZ": "UTC", "F2_STATE_PATH": first._state_path, "F2_DATA_DIR": str(tmp_path)}
    with pytest.raises(Hour):
        runtime_env.preflight(controller.close_only_start, env, http=session, sleep=clock.sleep,
                              clock=clock.monotonic)
    posts = [(m, p, s) for _t, m, p, s in session.sent if m == "POST" and p.startswith("/states/")]
    assert posts == [("POST", f"/states/{runtime_env.RUNTIME_ENTITY}", 401)]  # the admin probe only
    assert ("turn_off", VALVE) in switched(fake) and fake.states[VALVE][0] == "off"
    assert not [call for call in switched(fake) if call[0] == "turn_on"]
    closed = max(t for t, m, p, _s in session.sent if p == f"/states/{VALVE}")
    assert [s for s in session.sent if s[0] > closed] == []  # nothing more over the hour
    assert "_shot_inflight" not in json.load(open(first._state_path))["default"]


def test_the_log_shows_home_assistants_address_without_a_password():
    """HA_URL may carry a user name and password; every log line names the address through SHOWN_BASE."""
    with open(controller.__file__, encoding="utf-8") as fh:
        source = fh.read()
    assert "{BASE}" not in "".join(line for line in source.splitlines() if "_GATE.saw(" in line or "log(" in line)
    assert '"| base:", BASE)' not in source
    shown = runtime_env._shown("http://grower:hunter2@ha:8123/api")
    assert "hunter2" not in shown and shown.endswith("@ha:8123/api")
