"""Dosing as steps of the controller's main loop (docs/DOSING.md): there is no second thread. The loop
wakes whenever dosing is due; a dose or batch runs on to its next wait at each wake; a stop signal that
lands in the middle of a switch-on waits for it to land before the way out switches off; a step that
crashes is recovered as after a restart; and SIGTERM closes the shot in flight before dosing goes.

Driven as test_dosing_runner.py drives it: the real Controller, the in-memory Home Assistant and a
fake clock.
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import pytest

import controller
import dosing_runner
import runtime_env
from test_controller import _build
from test_dosing_runner import BASE, _full_batch, make_rig

# The REST helpers themselves, taken at collection, before any test puts its fakes in their place.
_REAL = {name: getattr(controller, name) for name in ("ha_call", "ha_service_response")}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return make_rig(tmp_path, monkeypatch)


def _until(r, test, limit=1800.0):
    """Wake the runner whenever it is due, as the main loop does, until `test` holds."""
    end = r.clock.t + limit
    while not test():
        assert r.clock.t < end, "never happened"
        r.clock.sleep(r.runner.step())
    return True


def _state(r, entity):
    return r.fake.states[entity][0]


def test_dosing_starts_no_thread_and_the_loop_wakes_when_a_step_is_due(monkeypatch):
    c, _fake = _build({"num_zones": 1})
    assert not hasattr(dosing_runner.DosingRunner, "start")
    before = threading.active_count()
    c._start_dosing()
    assert threading.active_count() == before
    clock, steps = [0.0], []
    monkeypatch.setattr(controller.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(controller.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(c.dosing, "step", lambda: steps.append(clock[0]) or 0.5)
    c._sleep_for(3.0)
    assert steps == [0.0, 0.5, 1.0, 1.5, 2.0, 2.5] and clock[0] == 3.0
    c.dosing = None  # no dosing: one plain sleep
    clock[0] = 0.0
    c._sleep_for(3.0)
    assert clock[0] == 3.0


def test_a_shots_wait_steps_a_running_dose_or_batch_and_only_then(monkeypatch):
    """A shot in another room can hold the loop for minutes: a batch's open fill valve is still watched
    through it. With nothing running, the wait is the plain sleep it always was."""
    c, _fake = _build({"num_zones": 1, "hardware": {"pump": "switch.p", "mainline": "switch.m",
                                                     "valves": {"1": "switch.v1"}},
                       "enable_flag": "input_boolean.kill"},
                      states={"input_boolean.kill": ("on", {})})
    clock, steps = [0.0], []
    monkeypatch.setattr(controller.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(controller.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(c.dosing, "step", lambda: steps.append(clock[0]) or 0.5)
    monkeypatch.setattr(c.dosing, "running", lambda: True)
    assert c._wait_shot(c.rooms[0], 1, 6) == (6, None)  # the shot still runs its time, no longer
    assert steps == [0.5 * n for n in range(12)]
    steps.clear()
    monkeypatch.setattr(c.dosing, "running", lambda: False)
    assert c._wait_shot(c.rooms[0], 1, 6) == (6, None)
    assert steps == []


def test_a_batch_runs_in_steps_and_the_main_loop_keeps_going_between_them(rig):
    r = rig()
    _full_batch(r)
    r.full_after = None  # the tank never reads full: the batch sits in its fill
    r.ask("batch")
    r.runner.poll()
    assert r.runner._steps is not None  # taken, and waiting for its next step: poll() came back
    _until(r, lambda: _state(r, "switch.tank_fill") == "on")
    at = r.clock.t
    assert 0 < r.runner.step() <= dosing_runner.POLL_S  # due again within a poll
    assert r.clock.t == at  # a step never sleeps through a wait
    assert r.status()[0] == "batch"


def test_the_way_out_switches_off_what_a_running_batch_recorded_and_keeps_its_record(rig):
    r = rig()
    _full_batch(r)
    r.full_after = None
    r.ask("batch")
    r.runner.poll()
    _until(r, lambda: _state(r, "switch.tank_fill") == "on")
    began = len(r.fake.calls)
    r.runner.exit()
    assert _state(r, "switch.tank_fill") == "off" and _state(r, "input_boolean.tank_hold") == "on"
    assert r.saved()["inflight"]["kind"] == "batch"  # kept for the next start (CS-803)
    r.clock.sleep(5)
    r.runner.step()  # the loop may wake once more before the process ends: nothing moves
    assert not [c for c in r.fake.calls[began:] if c[1] == "turn_on"]


def test_a_stop_signal_in_the_middle_of_a_switch_on_waits_for_it_to_land(rig):
    """SIGTERM is handled on the main loop, so it can land while a dosing switch-on is on its way to
    Home Assistant. The way out must not send its offs ahead of that call: the fill valve would be
    left open once the process ends."""
    r = rig()
    _full_batch(r)
    r.full_after = None
    original, landed = r.runner._call, []

    def call(domain, service, **data):
        if (service, data.get("entity_id")) == ("turn_on", "switch.tank_fill") and not landed:
            assert r.c._safe_exit() is None  # the signal: deferred, the call goes on
            landed.append(r.clock.t)
        return original(domain, service, **data)

    r.runner._call = call
    r.ask("batch")
    with pytest.raises(SystemExit):
        r.runner.poll()
        _until(r, lambda: False)
    fill = [service for service, entity in r.actions("switch.tank_fill")]
    assert landed and fill[0] == "turn_on" and fill[-1] == "turn_off"  # on landed first, then off
    assert _state(r, "switch.tank_fill") == "off"
    assert r.saved()["inflight"]["kind"] == "batch"


def test_nothing_is_switched_on_once_the_way_out_has_begun(rig):
    r = rig()
    job = dosing_runner._Job(r.c.rooms[0], {"pumps": [], "batch": {}}, {"id": "x"}, "batch")
    r.runner.stop_starting()
    with pytest.raises(dosing_runner._Exit):
        r.runner._on(job, "switch.tank_fill")
    job.stopped, r.runner._exiting = True, False
    with pytest.raises(dosing_runner._Ended):
        r.runner._on(job, "switch.tank_fill")
    assert r.actions() == []


def test_a_step_that_crashes_is_recovered_as_after_a_restart_and_alerted(rig):
    r = rig()
    r.config()
    r.runner.recover()
    with r.runner._lock:
        r.runner._doc["rooms"]["default"] = {"inflight": {
            "kind": "batch", "at": BASE.isoformat(), "off": ["switch.tank_fill"],
            "hold": "input_boolean.tank_hold", "held": ["default"]}}

    def broken():
        yield 1.0
        raise RuntimeError("a bug")

    r.runner._start(broken())
    r.clock.sleep(1.0)
    r.runner.step()
    assert r.runner._steps is None and r.runner._job is None
    assert r.runner.holds(r.c.rooms[0]) is not None  # held before the main loop's next shot
    assert ("turn_off", "switch.tank_fill") in r.actions()
    assert "Dosing stopped with an error and started again (CS-806)" in [
        d["title"] for d in r.creates("CS-806")]


def test_a_mid_dose_sigterm_switches_the_dose_off_inside_the_stop_budget(rig):
    r = rig()
    r.config()
    r.behaviour["button.balance_start"] = "overrun"  # it would keep dosing
    r.ask(ml=50)
    r.runner.poll()
    _until(r, lambda: _state(r, "switch.balance_power") == "on")
    began = time.monotonic()
    with pytest.raises(SystemExit):
        r.c._safe_exit()
    assert time.monotonic() - began < runtime_env.stop_budget({})
    assert _state(r, "switch.balance_power") == "off"
    assert r.saved()["inflight"]["kind"] == "dose"
    # The next start reads it back off and says so.
    again = r.build(r.runner.path)
    again.recover()
    r.clock.sleep(dosing_runner.POLL_S)
    r.poll(again)
    r.clock.sleep(dosing_runner.POLL_S)
    r.poll(again)
    assert "CS-803" in r.codes() and again.holds(r.c.rooms[0]) is None


def test_sigterm_closes_the_shot_in_flight_before_dosing_goes(monkeypatch):
    c, _fake = _build({"num_zones": 1, "hardware": {"pump": "switch.p", "mainline": "switch.m",
                                                     "valves": {"1": "switch.v1"}}})
    order = []
    monkeypatch.setattr(c.dosing, "stop_starting", lambda: order.append("no dosing starts"))
    monkeypatch.setattr(c, "_safe_off", lambda deadline: order.append("irrigation"))
    monkeypatch.setattr(c.dosing, "exit", lambda within: order.append("dosing"))
    monkeypatch.setattr(c, "_save_state", lambda: order.append("saved"))
    with pytest.raises(SystemExit):
        c._safe_exit()
    assert order == ["no dosing starts", "irrigation", "dosing", "saved"]


def test_a_service_asked_for_its_answer_says_how_it_went(monkeypatch):
    """What dosing sends stock draws with: Home Assistant's REST API answers a service called with
    ?return_response as {"changed_states": [...], "service_response": {...}}."""
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
    monkeypatch.setattr(controller, "_S", Session(Answer(200, body)))
    assert ha_service_response("crop_steering", "stock_draw", {"key": "k"}, 2) == (
        200, {"counted": True, "skipped": ["x"]})
    url, kwargs = sent[-1]
    assert url.endswith("/services/crop_steering/stock_draw")
    assert kwargs["params"] == {"return_response": ""} and kwargs["json"] == {"key": "k"}
    assert kwargs["timeout"] == 2
    monkeypatch.setattr(controller, "_S", Session(Answer(400, None)))
    assert ha_service_response("crop_steering", "stock_draw", {}, 2) == (400, None)
    monkeypatch.setattr(controller, "_S", Session(ConnectionError("down")))
    assert ha_service_response("crop_steering", "stock_draw", {}, 2) == (None, None)
    # ha_call takes a timeout of its own, never sent as service data.
    monkeypatch.setattr(controller, "_S", Session(Answer(200, [])))
    assert ha_call("switch", "turn_off", timeout=2, entity_id="switch.x") is True
    assert sent[-1][1]["timeout"] == 2 and sent[-1][1]["json"] == {"entity_id": "switch.x"}


def test_the_supervisor_gives_the_app_time_to_stop_cleanly():
    """docker stop waits `timeout` seconds after SIGTERM before it kills: 10 by default, too little for
    the shot's safe-off plus dosing's way out (a switch-on in flight, each off)."""
    config = (Path(controller.__file__).parents[1] / "config.yaml").read_text(encoding="utf-8")
    found = re.search(r"^timeout:\s*(\d+)\s*$", config, re.M)
    assert found and 30 <= int(found.group(1)) <= 300  # the Supervisor accepts 10 to 300
