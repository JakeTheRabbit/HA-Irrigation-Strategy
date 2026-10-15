"""Dosing on its own, real thread (docs/DOSING.md, After a restart): the way out never lets a switch-on
land after its offs and waits for the thread to switch its own job off; a thread that dies is noticed
by the main loop, alerted and started again; SIGTERM closes the shot in flight before dosing; and the
dosing thread talks to Home Assistant over a requests.Session of its own.

These run on the real clock, with the runner's timings shortened (the `fast` fixture), because what
they prove is how two threads interleave.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

import controller
import dosing_runner
from test_controller import _build
from test_dosing_runner import BALANCE, BATCH, BLOOM, CONFIG, DEVICES, KILL, ROOM

FAST = {"POLL_S": 0.02, "READ_S": 0.01, "CONFIRM_FIRST_S": 0.01, "CONFIRM_POLL_S": 0.01,
        "CONFIRM_TIMEOUT_S": 0.3, "FILL_OPEN_S": 0.3}
# The REST helpers themselves, taken at collection, before any test puts its fakes in their place.
_REAL = {name: getattr(controller, name) for name in ("ha_call", "ha_service_response")}


@pytest.fixture
def fast(monkeypatch):
    for name, value in FAST.items():
        monkeypatch.setattr(dosing_runner, name, value)


class Real:
    """The Home Assistant side on the real clock: switches that switch, and a call that can be held
    on its way (a slow Home Assistant) to force two threads to meet."""

    def __init__(self, tmp_path, states=None):
        self.c, self.fake = _build(
            {"num_zones": 1, "enable_flag": KILL},
            states={"sensor.crop_steering_engine_config": ("ok", ROOM), KILL: ("on", {}),
                    **{e: (s, {}) for e, s in DEVICES.items()}, **(states or {})},
        )
        self.lock = threading.Lock()
        self.calls = []  # (time.perf_counter() when it landed, service, entity)
        self.held = {}  # (service, entity) -> Event the call waits on
        self.entered = {}  # (service, entity) -> Event set as the call starts
        self.runner = self.build(tmp_path / "dosing_state.json")

    def build(self, path):
        self.runner = dosing_runner.DosingRunner(
            self.c, get=self.fake.ha_get, call=self.call, publish=self.fake.ha_set,
            alert=self.c._dosing_alert, state_path=str(path), log=lambda *a: None,
            history=lambda entity, since: None,
            respond=lambda domain, service, data, timeout: (200, {"skipped": []}),
        )
        self.c.dosing = self.runner
        return self.runner

    def call(self, domain, service, timeout=None, **data):
        entity = data.get("entity_id")
        key = (service, entity)
        if key in self.entered:
            self.entered[key].set()
        if key in self.held:
            self.held[key].wait(10)
        with self.lock:  # recorded as it lands, before anything can read what it did
            self.calls.append((time.perf_counter(), service, entity))
            if domain in ("switch", "input_boolean") and service in ("turn_on", "turn_off"):
                self.fake.set_state(entity, "on" if service == "turn_on" else "off")
            elif service == "set_value":
                self.fake.set_state(entity, f"{float(data['value']):g}")
        return True

    def state(self, entity):
        return self.fake.states[entity][0]

    def ask(self, action, **data):
        request = {"id": uuid.uuid4().hex, "action": action, "pump": data.get("pump"), "ml": data.get("ml"),
                   "at": datetime.now(timezone.utc).isoformat(), "by": "Ben"}
        batch = dict(BATCH, fill_timeout_min=20)
        self.fake.set_state(CONFIG, "1", json.loads(json.dumps(
            {"pumps": [BALANCE, BLOOM], "batch": batch, "request": request})))
        return request

    def saved(self):
        return json.loads(Path(self.runner.path).read_text(encoding="utf-8"))["rooms"]["default"]


def _until(test, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if test():
            return True
        time.sleep(0.005)
    return False


def test_the_way_out_waits_for_the_thread_which_switches_its_own_batch_off(fast, tmp_path):
    real = Real(tmp_path)  # the tank never reads full: the batch sits in its fill
    real.ask("batch")
    thread = real.runner.start()
    assert _until(lambda: real.state("switch.tank_fill") == "on")
    began = time.perf_counter()
    real.runner.exit()
    assert time.perf_counter() - began < dosing_runner.EXIT_JOIN_S + 1
    assert not thread.is_alive()  # it went: its own way out ran
    assert real.state("switch.tank_fill") == "off" and real.state("input_boolean.tank_hold") == "on"
    assert real.saved()["inflight"]["kind"] == "batch"  # kept for the next start
    assert not [c for c in real.calls if c[0] >= began and c[1] == "turn_on"]  # nothing on after


def test_a_switch_on_in_flight_lands_before_the_way_out_switches_off(fast, monkeypatch, tmp_path):
    """The process ends as soon as exit() returns (sys.exit): an off it sent before a slow switch-on
    landed would leave the valve open. The thread's own join is kept short here, so only the gate can
    make the way out wait for the switch-on."""
    monkeypatch.setattr(dosing_runner, "EXIT_JOIN_S", 0.1)
    real = Real(tmp_path)
    key = ("turn_on", "switch.tank_fill")
    real.held[key], real.entered[key] = threading.Event(), threading.Event()
    real.ask("batch")
    real.runner.start()
    assert real.entered[key].wait(5)  # the fill valve's switch-on is on its way to Home Assistant
    threading.Timer(1.0, real.held[key].set).start()  # Home Assistant answers a second later
    real.runner.exit()
    returned, state = time.perf_counter(), real.state("switch.tank_fill")
    fill = [(at, service) for at, service, entity in real.calls if entity == "switch.tank_fill"]
    opened = max(at for at, service in fill if service == "turn_on")
    assert opened < returned  # the way out waited for it to land...
    assert state == "off" and fill[-1][1] == "turn_off"  # ...and it was closed before the way out ended


def test_nothing_is_switched_on_once_the_way_out_has_begun(tmp_path):
    real = Real(tmp_path)
    job = dosing_runner._Job(real.c.rooms[0], {"pumps": [], "batch": BATCH}, {"id": "x"}, "batch")
    real.runner._exiting = True
    with pytest.raises(dosing_runner._Exit):
        real.runner._on(job, "switch.tank_fill")
    job.stopped, real.runner._exiting = True, False
    with pytest.raises(dosing_runner._Ended):
        real.runner._on(job, "switch.tank_fill")
    assert real.calls == []


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")  # it dies on purpose
def test_a_dosing_thread_that_dies_is_noticed_alerted_and_started_again(fast, tmp_path):
    real = Real(tmp_path)
    runner, died = real.runner, threading.Event()
    poll = runner.poll

    def dies_once(busy=None):
        if not died.is_set():
            died.set()
            raise SystemExit("gone")  # not an Exception: it gets past the thread's own handler
        return poll(busy)

    runner.poll = dies_once
    first = runner.start()
    assert _until(lambda: not first.is_alive())
    assert runner.health() == "dead"
    # What it was doing is on record: the restart holds it as a start would.
    with runner._lock:
        runner._doc["rooms"]["default"] = {"inflight": {
            "kind": "batch", "at": "2026-09-28T01:00:00+00:00", "off": ["switch.tank_fill"],
            "hold": "input_boolean.tank_hold", "held": ["default"]}}
    real.c._watch_dosing()
    assert runner.health() == "ok" and runner._thread is not first
    assert runner.holds(real.c.rooms[0]) is not None  # held before the main loop's next shot
    created = [d["title"] for _d, s, d in real.fake.calls if s == "create"]
    assert "Dosing stopped with an error and was started again (CS-806)" in created
    runner.exit()


def test_a_stalled_dosing_thread_is_alerted_once_per_half_hour():
    c, fake = _build({"num_zones": 1})
    runner = c.dosing
    stop = threading.Event()
    runner._thread = threading.Thread(target=stop.wait, daemon=True)
    runner._thread.start()
    runner.beat = runner._mono() - dosing_runner.STALL_S - 1
    try:
        assert runner.health() == "stalled"
        c._watch_dosing()
        c._watch_dosing()  # the main loop checks every loop: one card, not one a minute
    finally:
        stop.set()
    created = [d for _d, s, d in fake.calls if s == "create"]
    assert [d["notification_id"] for d in created] == ["f2_dosing_gone_806_stalled"]


def test_sigterm_closes_the_shot_in_flight_before_dosing_goes(monkeypatch):
    c, _fake = _build({"num_zones": 1, "hardware": {"pump": "switch.p", "mainline": "switch.m",
                                                     "valves": {"1": "switch.v1"}}})
    order = []
    monkeypatch.setattr(c, "_safe_off", lambda: order.append("irrigation"))
    monkeypatch.setattr(c.dosing, "exit", lambda: order.append("dosing"))
    monkeypatch.setattr(c, "_save_state", lambda: order.append("saved"))
    with pytest.raises(SystemExit):
        c._safe_exit()
    assert order == ["irrigation", "dosing", "saved"]


def test_a_service_asked_for_its_answer_says_how_it_went(monkeypatch):
    """What the dosing thread sends stock draws with: Home Assistant's REST API answers a service called
    with ?return_response as {"changed_states": [...], "service_response": {...}}."""
    ha_call, ha_service_response = _REAL["ha_call"], _REAL["ha_service_response"]
    assert ha_call.__module__ == ha_service_response.__module__ == "controller"  # not a test's fakes
    sent = []

    class Answer:
        def __init__(self, status, body):
            self.status_code, self._body = status, body

        def json(self):
            if self._body is None:
                raise ValueError("no JSON")
            return self._body

    class Session:
        def __init__(self, answer):
            self.answer = answer

        def post(self, url, **kwargs):
            sent.append((url, kwargs))
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer

    body = {"changed_states": [], "service_response": {"counted": True, "skipped": ["x"]}}
    monkeypatch.setattr(controller, "_session", lambda: Session(Answer(200, body)))
    assert ha_service_response("crop_steering", "stock_draw", {"key": "k"}, 2) == (
        200, {"counted": True, "skipped": ["x"]})
    url, kwargs = sent[-1]
    assert url.endswith("/services/crop_steering/stock_draw")
    assert kwargs["params"] == {"return_response": ""} and kwargs["json"] == {"key": "k"}
    assert kwargs["timeout"] == 2
    monkeypatch.setattr(controller, "_session", lambda: Session(Answer(400, None)))
    assert ha_service_response("crop_steering", "stock_draw", {}, 2) == (400, None)
    monkeypatch.setattr(controller, "_session", lambda: Session(ConnectionError("down")))
    assert ha_service_response("crop_steering", "stock_draw", {}, 2) == (None, None)
    # ha_call takes a timeout of its own, never sent as service data.
    monkeypatch.setattr(controller, "_session", lambda: Session(Answer(200, [])))
    assert ha_call("switch", "turn_off", timeout=2, entity_id="switch.x") is True
    assert sent[-1][1]["timeout"] == 2 and sent[-1][1]["json"] == {"entity_id": "switch.x"}


def test_the_dosing_thread_talks_to_home_assistant_over_its_own_session():
    assert controller._session() is controller._S  # the main loop's
    seen = []
    thread = threading.Thread(target=lambda: seen.extend([controller._session(), controller._session()]))
    thread.start()
    thread.join()
    assert seen[0] is seen[1] and seen[0] is not controller._S


def test_the_supervisor_gives_the_app_time_to_stop_cleanly():
    """docker stop waits `timeout` seconds after SIGTERM before it kills: 10 by default, too little for
    the shot's safe-off plus dosing's way out (a switch-on in flight, the thread, each off)."""
    config = (Path(controller.__file__).parents[1] / "config.yaml").read_text(encoding="utf-8")
    found = re.search(r"^timeout:\s*(\d+)\s*$", config, re.M)
    assert found and 30 <= int(found.group(1)) <= 300  # the Supervisor accepts 10 to 300
