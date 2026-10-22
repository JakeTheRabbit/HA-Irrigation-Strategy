"""Timed pump runs (Task 20): a prime or a pump calibration switches one dosing pump's power on for its seconds and
off again, read back both ways, and reports {id, action, pump, ran_s, result} in the status's handled_result for the
integration (dosing_api._status_changed). A stop_pump ends it early; every way it ends leaves the power read back
off, or latches the room and raises CS-801. A dose is sized with the pump's calibrated flow when it has no flow entity.

Driven as test_dosing_runner.py drives the runner: the real Controller, the in-memory Home Assistant and a fake clock.
"""
from __future__ import annotations

import json
import uuid
from datetime import timedelta

import pytest

import dosing_runner
import guards
from test_dosing_runner import BALANCE, BATCH, BLOOM, CONFIG, KILL, _full_batch, make_rig

POWER = "switch.balance_power"


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return make_rig(tmp_path, monkeypatch)


def _timed(r, action="prime", pump="balance", seconds=10, age=0.0, by="Alex"):
    """The request the integration's pump_prime / pump_calibrate / pump_stop stores (dosing_api._timed)."""
    request = {"id": uuid.uuid4().hex, "action": action, "pump": pump, "ml": None,
               "at": (r.clock.now() - timedelta(seconds=age)).isoformat(), "by": by}
    if action != "stop_pump":
        request["seconds"] = seconds
    state, attributes = r.fake.states[CONFIG][:2]
    r.fake.set_state(CONFIG, state, {**attributes, "request": request})
    return request


def _calibrating(r, entry):
    state, attributes = r.fake.states[CONFIG][:2]
    r.fake.set_state(CONFIG, state, {**attributes, "calibrating": entry})


def _report(r):
    return r.status()[1]["handled_result"]


def _events(r, kind):
    return [e for e in r.c.journal.pending() if e["kind"] == kind]


def _off_at(r, entity=POWER):
    return [t for t, service, e in r.times if (service, e) == ("turn_off", entity)]


# ------------------------------------------------------------------------------------------------- the brief's
def test_prime_runs_the_power_switch_for_its_seconds_and_reads_it_back_off(rig):
    r = rig()
    r.config()
    request = _timed(r, seconds=10)
    seen = []
    r.clock.at(5, lambda: seen.append((r.status()[0], _report(r), r.fake.states[POWER][0])))
    r.poll()
    assert seen == [("dosing", "priming", "on")]  # running: the integration sees the room busy
    assert r.actions() == [("turn_on", POWER), ("turn_off", POWER)]
    assert r.fake.states[POWER][0] == "off"
    assert _report(r) == {"id": request["id"], "action": "prime", "pump": "balance", "ran_s": 10.0, "result": "done"}
    assert r.status()[0] == "idle" and r.status()[1]["handled"] == request["id"]
    assert r.saved()["inflight"] is None and r.codes() == []
    (done,) = _events(r, "dose.completed")
    assert (done["outcome"], done["code"], done["source"]["actor"]) == ("ok", None, "manual")
    assert done["data"] == {"pump": "balance", "kind": "prime", "seconds": 10.0, "ran_s": 10.0, "result": "done",
                            "ml": None, "given_ml": None, "flow_ml_s": None}
    assert r.status()[1]["history"][0]["kind"] == "prime"
    r.fake.calls.clear()
    r.poll()  # taken once
    assert r.actions() == []


def test_prime_is_refused_while_a_shot_is_in_flight(rig):
    r = rig()
    r.config()
    r.c.rooms[0].shot_inflight = {"zone": 1}
    request = _timed(r)
    r.poll()
    assert r.actions() == []
    assert _report(r) == {"id": request["id"], "action": "prime", "pump": "balance", "ran_s": 0,
                          "result": "refused: a shot is in flight in this room"}
    (refused,) = _events(r, "intent.refused")
    assert refused["data"] == {"guard": "inflight", "reason": "a shot is in flight in this room"}
    assert _events(r, "dose.completed") == []


def test_a_pump_that_does_not_read_off_latches_and_alerts_cs_801(rig):
    r = rig()
    r.config()
    r.stuck[POWER] = 99
    request = _timed(r, seconds=5)
    r.poll()
    # ran_s 0: the pump may still run, so no calibration or prime is taken from it
    assert _report(r) == {"id": request["id"], "action": "prime", "pump": "balance", "ran_s": 0, "result": "stuck"}
    assert "CS-801" in r.codes()
    assert r.runner.holds(r.c.rooms[0]) == "dosing hardware still on: " + POWER
    (stuck,) = _events(r, "dose.completed")
    assert (stuck["outcome"], stuck["code"]) == ("failed", "CS-801")
    # Latched: the next request is refused, the off is sent again every pass until it reads off.
    _timed(r, seconds=5)
    r.poll()
    assert _report(r)["result"] == "refused: " + POWER + " does not read off yet"
    r.stuck[POWER] = 0
    for _ in range(2):  # sent off again, then read back off
        r.clock.t += dosing_runner.POLL_S
        r.poll()
    assert r.runner.holds(r.c.rooms[0]) is None and r.saved()["inflight"] is None


def test_next_dose_uses_calibrated_flow_when_no_flow_entity(rig):
    r = rig()
    pump = {k: v for k, v in BALANCE.items() if k != "flow_entity"}
    r.config(pumps=(dict(pump, calibrated_ml_min=300),))
    assert r.runner._flow(dict(pump, calibrated_ml_min=300)) == (5.0, 5.0)  # 300 mL/min -> 5 mL/s
    r.set("number.balance_flow", "5")  # the motor itself (the rig's firmware reads it): 50 mL in 10 s
    r.ask(ml=50)
    r.poll()
    assert _report(r) == "finished"
    assert r.status()[1]["pumps"]["balance"]["flow_ml_s"] == 5.0
    (dose,) = _events(r, "dose.completed")
    assert dose["data"]["flow_ml_s"] == 5.0
    # A calibrated flow too small to bound a dose is refused as a flow entity's is.
    r.config(pumps=(dict(pump, calibrated_ml_min=0.6),), revision="2")
    r.ask(ml=50)
    r.poll()
    assert _report(r) == "refused: Balance is not calibrated (flow 0.01)"
    # Neither a flow entity nor a calibration: the setup can't be read, as before (nothing is acted on).
    r.config(pumps=(pump,), revision="3")
    r.ask(ml=50)
    r.fake.calls.clear()
    r.poll()
    assert r.status()[0] == "unavailable" and r.actions() == []


def test_flow_entity_still_wins_over_calibrated_flow(rig):
    r = rig()
    r.config(pumps=(dict(BALANCE, calibrated_ml_min=300),))
    assert r.runner._flow(dict(BALANCE, calibrated_ml_min=300)) == (10.0, "10")
    r.ask(ml=50)
    r.poll()
    assert _report(r) == "finished"
    assert _events(r, "dose.completed")[0]["data"]["flow_ml_s"] == 10.0


def test_stop_pump_ends_a_prime_early_and_reports_ran_s(rig):
    r = rig()
    r.config()
    request = _timed(r, seconds=20)
    stop = {}
    r.clock.at(4, lambda: stop.update(_timed(r, "stop_pump", by="Sam")))
    r.poll()
    (off,) = _off_at(r)
    assert 4 <= off <= 6  # seen within one wait tick
    assert r.fake.states[POWER][0] == "off"
    status = r.status()[1]
    assert (status["handled"], status["handled_result"]) == (stop["id"], "stopped")  # the stop is taken once, too
    assert status["handled_results"][request["id"]] == {"id": request["id"], "action": "prime", "pump": "balance",
                                                       "ran_s": 4.0, "result": "stopped"}
    (done,) = _events(r, "dose.completed")
    assert (done["outcome"], done["data"]["ran_s"]) == ("aborted", 4.0)


def test_stop_pump_leaves_a_running_batch_alone(rig):
    r = rig()
    _full_batch(r)
    r.ask("batch")
    stop = {}
    r.clock.at(30, lambda: stop.update(_timed(r, "stop_pump", by="Sam")))
    r.poll()
    assert r.status()[1]["handled"] == stop["id"]
    assert r.status()[1]["history"][0]["result"] == "finished"
    assert ("turn_off", POWER) not in r.actions()


# ------------------------------------------------------------------------------------------------- every way out
def test_a_power_that_does_not_read_on_is_switched_off_and_refused(rig):
    r = rig()
    r.config()
    r.deaf[POWER] = 1
    request = _timed(r)
    r.poll()
    assert r.actions() == [("turn_on", POWER), ("turn_off", POWER)]
    assert _report(r) == {"id": request["id"], "action": "prime", "pump": "balance", "ran_s": 0,
                          "result": "refused: " + POWER + " did not read on"}
    assert r.saved()["inflight"] is None and r.runner.holds(r.c.rooms[0]) is None


def test_a_power_that_reads_neither_on_nor_off_is_stuck(rig):
    r = rig()
    r.config()
    r.set(POWER, "unavailable")
    _timed(r)
    r.poll()
    assert _report(r)["result"] == "stuck" and _report(r)["ran_s"] == 0
    assert "CS-801" in r.codes() and r.runner.holds(r.c.rooms[0]).startswith("dosing hardware still on")


def test_a_room_stop_ends_a_calibration_run(rig):
    r = rig()
    r.config()
    request = _timed(r, "calibrate", seconds=60)
    r.clock.at(7, lambda: r.ask("stop", by="Sam"))
    r.poll()
    assert r.fake.states[POWER][0] == "off" and max(_off_at(r)) <= 9
    assert _report(r) == "stopped"  # the room stop, handled last
    assert r.status()[1]["handled_results"][request["id"]] == {"id": request["id"], "action": "calibrate",
                                                               "pump": "balance", "ran_s": 7.0, "result": "stopped"}


@pytest.mark.parametrize("what", ["kill switch", "hardware fault", "shot in flight"])
def test_a_run_is_ended_by_the_abort_checks(rig, what):
    r = rig()
    r.config()
    room = r.c.rooms[0]

    def trip():
        if what == "kill switch":
            r.set(KILL, "off")
        elif what == "hardware fault":
            room.hardware_fault = {"reason": "valve stuck", "entities": ["switch.row1"], "switches": []}
        else:
            room.shot_inflight = {"zone": 1}

    request = _timed(r, seconds=20)
    r.clock.at(6, trip)
    r.poll()
    assert r.fake.states[POWER][0] == "off" and max(_off_at(r)) <= 8
    assert _report(r) == {"id": request["id"], "action": "prime", "pump": "balance", "ran_s": 6.0,
                          "result": "stopped"}
    assert r.saved()["inflight"] is None


def test_a_prime_with_the_kill_switch_off_never_starts(rig):
    r = rig({KILL: ("off", {})})
    r.config()
    _timed(r)
    r.poll()
    assert r.actions() == [] and _report(r)["result"].startswith("refused: the room's kill switch")


def _saved(runner):
    with open(runner.path, encoding="utf-8") as fh:
        return json.load(fh)["rooms"]["default"]


def test_a_refused_token_mid_run_switches_off_and_the_recovery_reads_it_back(rig):
    r = rig()
    r.config()
    request = _timed(r, seconds=20)
    refused = []
    r.runner._refused = lambda: bool(refused)
    r.clock.at(5, lambda: refused.append(1))
    r.poll()
    assert r.fake.states[POWER][0] == "off" and _off_at(r)  # off at once, as a dose's way out
    assert _saved(r.runner)["inflight"]["off"] == [POWER]  # kept until it is read back
    refused.clear()
    for _ in range(2):
        r.runner.step()  # Home Assistant accepts again: recovered, sent off, read back off
        r.clock.t += dosing_runner.POLL_S
    saved = _saved(r.runner)
    assert saved["inflight"] is None and r.runner.holds(r.c.rooms[0]) is None
    assert saved["handled_result"] == {"id": request["id"], "action": "prime", "pump": "balance", "ran_s": 0,
                                       "result": "stopped"}


def test_the_app_stopping_mid_run_switches_off_and_the_next_start_reads_it_back(rig, tmp_path):
    r = rig()
    r.config()
    request = _timed(r, seconds=20)
    r.runner.poll()  # taken and switched on
    assert r.fake.states[POWER][0] == "on"
    r.runner.exit()  # SIGTERM: what the run recorded is sent off, and the record stays
    assert r.fake.states[POWER][0] == "off" and _saved(r.runner)["inflight"]["off"] == [POWER]
    again = r.build(tmp_path / "dosing_state.json")
    again.recover()
    saved = _saved(again)
    assert saved["handled_result"] == {"id": request["id"], "action": "prime", "pump": "balance", "ran_s": 0,
                                       "result": "stopped"}
    assert saved["history"][0]["kind"] == "prime" and saved["history"][0]["result"] == "interrupted by a restart"
    r.clock.t += dosing_runner.POLL_S
    r.poll(again)
    assert again.holds(r.c.rooms[0]) is None and _saved(again)["inflight"] is None


def test_a_restart_with_a_pump_that_does_not_read_off_holds_the_room_and_alerts(rig, tmp_path):
    r = rig()
    r.config()
    r.stuck[POWER] = 99
    _timed(r, seconds=20)
    r.runner.poll()
    r.runner.exit()
    assert r.fake.states[POWER][0] == "on"
    again = r.build(tmp_path / "dosing_state.json")
    again.recover()
    for _ in range(2):
        r.clock.t += dosing_runner.POLL_S
        r.poll(again)
    assert again.holds(r.c.rooms[0]) == "dosing hardware still on: " + POWER
    assert r.codes()  # said, and sent off again every pass until it reads off


def test_an_error_mid_run_still_switches_off_and_reads_it_back(rig, monkeypatch):
    r = rig()
    r.config()
    request = _timed(r, seconds=20)
    real, calls = r.runner._run_abort, []

    def broken(room):
        calls.append(1)
        if len(calls) == 3:
            raise RuntimeError("boom")
        return real(room)

    monkeypatch.setattr(r.runner, "_run_abort", broken)
    r.poll()
    assert r.fake.states[POWER][0] == "off"
    report = _report(r)
    assert report["id"] == request["id"] and report["result"] == "stopped" and 0 < report["ran_s"] < 20
    assert any("boom" in line for line in r.logs)


def test_a_restart_mid_run_reports_it_stopped_and_switches_off(rig, tmp_path):
    r = rig()
    r.config()
    request = _timed(r, seconds=20)
    r.runner.poll()  # taken and switched on; the app dies here, with no way out
    assert r.fake.states[POWER][0] == "on"
    again = r.build(tmp_path / "dosing_state.json")
    again.recover()
    assert _saved(again)["handled_result"] == {"id": request["id"], "action": "prime", "pump": "balance",
                                               "ran_s": 0, "result": "stopped"}
    assert r.fake.states[POWER][0] == "off"


# ------------------------------------------------------------------------------------------------- caps and guards
@pytest.mark.parametrize("action, asked, ran", [("prime", 45, 30.0), ("calibrate", 200, 120.0), ("prime", 3, 3.0)])
def test_the_run_is_capped_at_its_seconds_and_at_the_cap(rig, action, asked, ran):
    r = rig()
    r.config()
    _timed(r, action, seconds=asked)
    r.poll()
    assert _report(r)["ran_s"] == ran and _report(r)["result"] == "done"


@pytest.mark.parametrize("seconds", [0, -5, True, "10", None, float("nan")])
def test_a_run_with_no_usable_seconds_is_refused(rig, seconds):
    r = rig()
    r.config()
    _timed(r, seconds=seconds)
    r.poll()
    assert r.actions() == [] and _report(r)["result"].startswith("refused: ")


def test_an_uncalibrated_pump_may_be_calibrated_but_not_primed(rig):
    r = rig()
    r.config()
    r.set("number.balance_flow", "0")
    _timed(r, "prime")
    r.poll()
    assert _report(r)["result"] == "refused: Balance is not calibrated (flow 0)" and r.actions() == []
    _timed(r, "calibrate", seconds=5)
    r.poll()
    assert _report(r)["result"] == "done"


@pytest.mark.parametrize("entry, words", [
    ({"pump": "balance", "request_id": "x", "until": "z"}, None),  # its own prime's hold
    ({"pump": "balance", "session_id": "s", "until": "z"}, None),  # its own calibration session
    ({"pump": "bloom", "session_id": "s", "until": "z"}, guards.CALIBRATING_PUMP),
    ({"probe": "feed_ph", "session_id": "s", "until": "z"}, guards.CALIBRATING_PROBE),
    ({"pump": "balance", "probe": "feed_ph", "session_id": "s", "until": "z",
      "sessions": [{"pump": "balance", "session_id": "s", "until": "z"},
                   {"probe": "feed_ph", "session_id": "p", "until": "z"}]}, guards.CALIBRATING_PROBE),
    ({"pump": "balance", "request_id": "x", "until": "z",
      "sessions": [{"pump": "balance", "request_id": "x", "until": "z"},
                   {"pump": "bloom", "request_id": "y", "until": "z"}]}, guards.CALIBRATING_PUMP),
])
def test_a_pumps_own_hold_does_not_hold_its_own_run(rig, entry, words):
    r = rig()
    r.config(pumps=(BALANCE, BLOOM))
    _calibrating(r, entry)
    _timed(r, "calibrate", seconds=5)
    r.poll()
    assert _report(r)["result"] == ("done" if words is None else f"refused: {words}")


def test_a_single_dose_and_a_batch_are_still_held_by_a_pumps_hold(rig):
    r = rig()
    r.config(pumps=(BALANCE, BLOOM))
    _calibrating(r, {"pump": "balance", "request_id": "x", "until": "z"})
    r.ask(ml=50)
    r.poll()
    assert _report(r) == "refused: " + guards.CALIBRATING_PUMP


def test_requests_while_a_run_runs_are_refused_and_a_run_while_a_dose_runs_too(rig):
    r = rig()
    r.config()
    _timed(r, seconds=20)
    seen = {}
    r.clock.at(5, lambda: seen.update(r.ask(ml=50)))
    r.clock.at(8, lambda: seen.update(result=_report(r)))
    r.poll()
    assert seen["result"] == "refused: a prime is running"
    r.ask(ml=500)  # 50 s
    prime = {}
    r.clock.at(5, lambda: prime.update(_timed(r, seconds=5)))
    r.clock.at(8, lambda: prime.update(result=_report(r)))
    r.poll()
    assert prime["result"] == {"id": prime["id"], "action": "prime", "pump": "balance", "ran_s": 0,
                               "result": "refused: a dose is running"}


def test_a_prime_too_old_to_act_on_is_reported_refused(rig):
    r = rig()
    r.config()
    request = _timed(r, age=300)
    r.poll()
    assert r.actions() == []
    assert _report(r) == {"id": request["id"], "action": "prime", "pump": "balance", "ran_s": 0,
                          "result": "refused: too old to act on"}


def test_a_stop_pump_with_nothing_running_switches_that_pump_off(rig):
    r = rig()
    r.config(pumps=(BALANCE, BLOOM))
    r.set(POWER, "on")
    _timed(r, "stop_pump")
    r.poll()
    assert r.actions() == [("turn_off", POWER)] and _report(r) == "stopped"


# ------------------------------------------------------------------------------------------------- carried minors
def test_a_refusal_whose_journal_failed_is_journaled_once_it_works(rig, monkeypatch):
    r = rig()
    r.config()
    r.set("number.balance_flow", "0")
    real = r.c.journal.emit
    monkeypatch.setattr(r.c.journal, "emit", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    r.runner._journal_intent(r.c.rooms[0], "intent.refused",
                             guards.Why((guards.DOSE[0], "Balance is not calibrated (flow 0)", None)))
    monkeypatch.setattr(r.c.journal, "emit", real)
    r.runner._journal_intent(r.c.rooms[0], "intent.refused",
                             guards.Why((guards.DOSE[0], "Balance is not calibrated (flow 0)", None)))
    assert len(_events(r, "intent.refused")) == 1  # the key was not kept for the emit that failed


def test_the_ph_latch_names_no_code():
    assert guards.PH_LOCK[0].code is None


def test_a_mix_check_with_no_dosing_config_gives_up_and_alerts(rig):
    m = rig({"number.crop_steering_irrigation_ec_min": ("1.5", {}),
             "number.crop_steering_irrigation_ec_max": ("2.5", {}),
             "sensor.tank_ec": ("2.0", {"unit_of_measurement": "mS/cm"})})
    m.c.rooms[0].feed_ec_sensor = "sensor.tank_ec"
    m.config(pumps=(BALANCE, BLOOM), batch=BATCH)
    m.ask("batch")
    m.poll()
    del m.fake.states[CONFIG]  # the integration stops publishing it
    m.clock.sleep(dosing_runner.MIX_SETTLE_S)
    m.runner.poll()
    assert m.saved()["mix"]["verdict"] is None and "CS-808" not in m.codes()  # waits, a while
    m.clock.sleep(dosing_runner.MIX_CONFIG_WAIT_S)
    m.runner.poll()
    mix = m.saved()["mix"]
    assert mix["verdict"] is None and mix["gave_up_at"]  # no verdict: never marked good
    assert "CS-808" in m.codes()
    m.runner.poll()
    assert len(m.creates("CS-808")) == 1  # said once
    assert m.runner._mix_refuses(m.c.rooms[0]) == "the last batch's mix is not checked yet"


# ------------------------------------------------------------------------------------------------- each answer kept
def test_a_dose_refused_during_a_prime_keeps_its_own_answer_and_the_prime_reports(rig):
    r = rig()
    r.config()
    prime = _timed(r, seconds=20)
    dose = {}
    r.clock.at(5, lambda: dose.update(r.ask(ml=50)))
    r.poll()
    status = r.status()[1]
    # The latest request handled keeps handled / handled_result, as every reader had them.
    assert (status["handled"], status["handled_result"]) == (dose["id"], "refused: a prime is running")
    assert status["handled_results"] == {
        prime["id"]: {"id": prime["id"], "action": "prime", "pump": "balance", "ran_s": 20.0, "result": "done"},
        dose["id"]: "refused: a prime is running"}
    assert r.saved()["handled_results"] == status["handled_results"]  # kept across a restart


def test_the_last_ten_answers_are_kept(rig):
    r = rig()
    r.config()
    r.set("number.balance_flow", "0")
    asked = []
    for _ in range(12):
        asked.append(r.ask(ml=50)["id"])
        r.poll()
    answers = r.status()[1]["handled_results"]
    assert list(answers) == asked[2:]
    assert set(answers.values()) == {"refused: Balance is not calibrated (flow 0)"}
