"""The dosing runner's fail-safes (docs/DOSING.md), each a way it once could leave a pump, a valve or
a room in a state nobody knew about: a dosing pump whose power does not read off, a restart that
finds a switch unavailable, a full sensor that goes quiet, a flow too small to bound a dose, a pump
that reboots mid-dose, a volume number put back under a running pump, a batch command nobody read
back, a stop that arrives late, a stock draw nobody takes, an alert Home Assistant did not take, an
error in the controller, and a dosing_state.json that can't be read.

Driven as test_dosing_runner.py drives it: the real Controller, the in-memory Home Assistant and a
fake clock. What needs a real thread (the way out, a thread that dies) is in test_dosing_threads.py.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

import pytest

import dosing_runner
from test_controller import _desc
from test_dosing_runner import BALANCE, BASE, BATCH, BLOOM, CONFIG, LINKED, _full_batch, _interrupted, make_rig


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return make_rig(tmp_path, monkeypatch)


def _pass(r, seconds=dosing_runner.POLL_S):
    """One pass of the dosing thread, `seconds` after the last."""
    r.clock.t += seconds
    r.runner.poll()


def _doc(r):
    with open(r.runner.path, encoding="utf-8") as fh:
        return json.load(fh)


# ------------------------------------------------------------------ 1. a dose whose power will not read off
def test_a_dose_whose_power_will_not_read_off_holds_the_room_until_it_does(rig):
    r = rig()
    r.config()
    r.behaviour["button.balance_start"] = "overrun"
    r.stuck["switch.balance_power"] = 99  # the motor's own switch ignores every off
    r.ask(ml=120)
    r.runner.poll()
    room = r.c.rooms[0]
    assert r.status()[1]["handled_result"] == "ran past its time"
    reason = "dosing hardware still on: switch.balance_power"
    assert r.runner.holds(room) == reason and r.c._blocked(room, 1) == reason
    assert r.saved()["inflight"]["kind"] == "dose"  # kept: a restart switches it off as well
    assert r.codes() == ["CS-801"]
    assert "watering in this room is held" in r.alert("CS-801")["message"]
    # Its volume number is not put back while the pump may still run: it waits, recorded.
    assert r.fake.states["number.balance_volume"][0] == "120"
    assert r.saved()["restores"][0]["old_volume"] == 25.0
    # Sent off again on every pass, and said again every 30 minutes.
    offs = r.actions().count(("turn_off", "switch.balance_power"))
    _pass(r)
    assert r.actions().count(("turn_off", "switch.balance_power")) == offs + 1
    assert len(r.creates("CS-801")) == 1
    _pass(r, dosing_runner.REALERT_S)
    assert len(r.creates("CS-801")) == 2
    assert "switch.balance_power still does not read off" in r.alert("CS-801")["message"]
    # It goes at last: released, the card says so, and the volume number is put back.
    r.stuck["switch.balance_power"] = 0
    _pass(r)
    _pass(r)
    assert r.runner.holds(room) is None and r.saved()["inflight"] is None
    assert "Everything now reads off" in r.alert("CS-801")["message"]
    assert r.fake.states["number.balance_volume"][0] == "25" and r.saved()["restores"] == []


def test_a_stopped_dose_whose_power_will_not_read_off_is_held_and_a_stop_releases_it(rig):
    r = rig()
    r.config()
    r.ask(ml=500)

    def stop():
        r.stuck["switch.balance_power"] = 99
        r.ask("stop", by="Sam")

    r.clock.at(10, stop)
    r.runner.poll()
    status = r.status()[1]
    assert status["handled_result"] == "stopped; switch.balance_power does not read off"
    assert status["history"][0]["result"] == "stopped"
    assert r.runner.holds(r.c.rooms[0]) == "dosing hardware still on: switch.balance_power"
    assert r.codes() == ["CS-806"]
    assert "was stopped, but switch.balance_power still does not read off" in r.alert("CS-806")["message"]
    # A stop sends the offs again and, once everything reads off, lets the room water.
    r.stuck["switch.balance_power"] = 0
    r.ask("stop")
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "stopped"
    assert r.runner.holds(r.c.rooms[0]) is None and r.saved()["inflight"] is None


def test_a_stop_switches_off_the_running_jobs_pumps_and_the_current_setups(rig):
    r = rig()
    r.config(pumps=(BALANCE,))
    r.ask(ml=500)

    def saved_and_stopped():  # a setup saved meanwhile names another pump
        r.config(pumps=(BLOOM,), revision="2")
        r.ask("stop")

    r.clock.at(10, saved_and_stopped)
    r.runner.poll()
    offs = {entity for service, entity in r.actions() if service == "turn_off"}
    assert {"switch.balance_power", "switch.bloom_power"} <= offs
    assert r.status()[1]["history"][0]["result"] == "stopped"


# ------------------------------------------------------------------ 2. a restart
def test_a_restart_holds_until_every_recorded_part_reads_off_and_says_so_every_30_min(rig, tmp_path):
    """A host boot: the fill valve's device is not back yet (unavailable), and Home Assistant answers
    turning it off all the same. It is never counted as off, and the rooms the batch held stay held."""
    _interrupted(tmp_path, held=["default", "f1"])
    f1 = _desc(prefix="f1_", slug="f1", pump=None, mainline="switch.f1_feed", valves={"1": "switch.f1_row1"})
    r = rig({"sensor.crop_steering_f1_engine_config": ("ok", f1), "switch.f1_row1": ("off", {}),
             "switch.tank_fill": ("unavailable", {}), "input_boolean.tank_hold": ("on", {})})
    rooms = {room.slug: room for room in r.c.rooms}
    assert r.runner.recover() is True
    assert r.runner.holds(rooms["default"]).startswith("dosing hardware still on")
    assert r.runner.holds(rooms["f1"]).startswith("dosing hardware still on")
    r.runner.poll()
    assert r.runner.holds(rooms["f1"]) == "dosing hardware still on: switch.tank_fill"
    assert r.codes() == ["CS-803"]
    assert "switch.tank_fill still does not read off" in r.alert("CS-803")["message"]
    assert r.fake.states["input_boolean.tank_hold"][0] == "on"  # kept on while anything is on
    assert r.saved()["inflight"]["kind"] == "batch"
    sent = r.actions().count(("turn_off", "switch.tank_fill"))
    _pass(r)
    assert r.actions().count(("turn_off", "switch.tank_fill")) == sent + 1
    assert len(r.creates("CS-803")) == 1
    _pass(r, dosing_runner.REALERT_S)
    assert len(r.creates("CS-803")) == 2
    # The device comes back ON (its relay kept its state): off at once, then the hold, then released.
    r.set("switch.tank_fill", "on")
    _pass(r)
    assert r.fake.states["switch.tank_fill"][0] == "off"
    _pass(r)
    _pass(r)
    assert r.runner.holds(rooms["default"]) is None and r.runner.holds(rooms["f1"]) is None
    assert r.fake.states["input_boolean.tank_hold"][0] == "off" and r.saved()["inflight"] is None
    assert "Everything now reads off" in r.alert("CS-803")["message"]


def test_a_restart_puts_back_the_volume_number_a_dose_changed(rig, tmp_path):
    dose = {"pump": "balance", "ml": 120, "at": BASE.isoformat(), "old_volume": 25.0, "name": "Balance",
            "volume_entity": "number.balance_volume", "dosing_entity": "binary_sensor.balance_dosing",
            "dosing_prefix": "Dosing", "power_entity": "switch.balance_power"}
    _interrupted(tmp_path, kind="dose", dose=dose)
    r = rig({"number.balance_volume": ("120", {}), "binary_sensor.balance_dosing": ("on", {}),
             "switch.balance_power": ("on", {})})
    r.runner.recover()  # its power off: the motor stops
    r.runner.poll()  # it reads off: released, and the volume number put back
    assert r.runner.holds(r.c.rooms[0]) is None and r.codes() == ["CS-803"]
    assert r.fake.states["number.balance_volume"][0] == "25"


# ------------------------------------------------------------------ 3. the tank's full sensor
def test_a_batch_is_refused_when_the_tanks_full_sensor_cannot_be_read(rig):
    r = rig({"binary_sensor.tank_full": ("unavailable", {})})
    _full_batch(r)
    r.ask("batch")
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "refused: the tank's full sensor can't be read"
    assert r.actions() == []


def test_a_full_sensor_that_stops_reporting_mid_fill_closes_the_fill_valve(rig):
    r = rig()
    _full_batch(r)
    r.full_after = None
    r.ask("batch")
    r.clock.at(30, lambda: r.set("binary_sensor.tank_full", "unavailable"))
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "stopped: fill: the full sensor stopped reporting"
    assert r.fake.states["switch.tank_fill"][0] == "off"
    assert r.codes() == ["CS-804", "CS-806"]
    alert = r.alert("CS-804")
    assert alert["title"] == "The batch tank could not be filled (CS-804)"
    assert "the full sensor stopped reporting" in alert["message"]
    # Closed 15 s after it went quiet, not at the end of the 20-minute fill timeout.
    closed = min(t for t, service, e in r.times if (service, e) == ("turn_off", "switch.tank_fill") and t > 30)
    assert 30 + 15 <= closed <= 30 + 15 + 4


# ------------------------------------------------------------------ 4. flow and time limits
def test_a_dose_expected_to_take_more_than_20_minutes_is_refused(rig):
    r = rig({"number.balance_flow": ("0.5", {})})
    r.config()
    r.ask(ml=700)  # 1400 s at 0.5 mL/s
    r.runner.poll()
    assert r.status()[1]["handled_result"] == (
        "refused: 700 mL of Balance would take 23.3 min at 0.5 mL/s, more than 20 min")
    assert r.actions() == []
    r.ask(ml=600)  # exactly 20 minutes: allowed
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "finished"


def test_no_dose_is_left_running_past_21_minutes_whatever_its_flow(rig):
    r = rig({"number.balance_flow": ("0.5", {})})
    r.config()
    r.behaviour["button.balance_start"] = "overrun"
    r.ask(ml=590)  # 1180 s expected: 1180 x 1.25 + 20 = 1495 s, capped at 1260 s
    r.runner.poll()
    [pressed] = [t for t, service, _e in r.times if service == "press"]
    cut = min(t for t, service, e in r.times if (service, e) == ("turn_off", "switch.balance_power"))
    assert cut - pressed == pytest.approx(dosing_runner.DOSE_CAP_S, abs=1.0)
    assert r.status()[1]["handled_result"] == "ran past its time"


def test_a_batch_with_a_dose_longer_than_20_minutes_is_refused(rig):
    r = rig({"number.recipe_bloom": ("1500", {}), "sensor.bloom_flow": ("1", {})})
    _full_batch(r)
    r.ask("batch")
    r.runner.poll()
    assert r.status()[1]["handled_result"] == (
        "refused: 1500 mL of Bloom would take 25.0 min at 1 mL/s, more than 20 min")
    assert r.actions() == []


def test_the_batch_watchdog_counts_the_wait_for_a_shot_and_every_capped_dose():
    batch = dict(BATCH, fill_timeout_min=20, premix_min=2, postmix_min=5)
    plan = [(BALANCE, 300, 10.0), (BLOOM, 1180, 1.0)]  # 57.5 s, and 1495 s capped at 1260 s
    minutes = 10 + 20 + 2 + 5 + 10  # the shot wait, fill, premix, postmix and the margin
    assert dosing_runner.DosingRunner._watchdog(batch, plan) == minutes * 60 + 57.5 + 1260


# ------------------------------------------------------------------ 6. alerts
def test_two_dosing_events_within_30_minutes_are_two_notifications(rig):
    r = rig()
    r.config()
    r.behaviour["button.balance_start"] = "silent"
    r.ask(ml=50)
    r.runner.poll()
    r.clock.t += 60
    r.ask(ml=50)
    r.runner.poll()
    assert [a["title"] for a in r.creates("CS-802")] == ["A dose could not be confirmed (CS-802)"] * 2
    assert len(r.alerts()) == 2  # two cards: the second is not swallowed by the first


def test_a_dosing_alert_home_assistant_did_not_take_is_raised_again_until_it_does(rig):
    r = rig()
    r.config()
    r.behaviour["button.balance_start"] = "silent"
    r.created = False
    r.ask(ml=50)
    r.runner.poll()
    assert r.creates() == [] and _doc(r)["outbox"][0]["code"] == "CS-802"
    r.runner.poll()
    assert r.creates() == []
    # Kept across a restart as well.
    again = r.build(r.runner.path)
    r.c.dosing = again
    r.created = True
    again.recover()
    again.poll()
    assert [a["title"] for a in r.creates()] == ["A dose could not be confirmed (CS-802)"]
    again.poll()
    assert len(r.creates()) == 1 and _doc(r)["outbox"] == []


def test_switching_a_room_off_does_not_dismiss_its_dosing_alerts(rig):
    r = rig()
    r.config()
    r.behaviour["button.balance_start"] = "silent"
    r.ask(ml=50)
    r.runner.poll()
    [key] = [k for k in r.c._alerted if k.startswith("dosing_")]
    r.c._alerted["blind_default_z1"] = datetime.now()  # a room alert: that one stands down
    r.c._room_switched_off(r.c.rooms[0])
    dismissed = [d["notification_id"] for _dom, svc, d in r.fake.calls if svc == "dismiss"]
    assert dismissed == ["f2_blind_default_z1"] and key in r.c._alerted


# ------------------------------------------------------------------ 7. when a dose counts as finished
@pytest.mark.parametrize("how", ["reboot", "flicker", "blink"])
def test_a_pump_whose_sensor_drops_out_after_the_press_is_not_confirmed(rig, how):
    """reboot: the reads see it unavailable; flicker and blink: only the recorder does (it came back
    between two reads). Before, any change after the press counted, so unavailable -> Idle was a
    finished dose."""
    r = rig()
    r.config()
    r.behaviour["button.balance_start"] = how
    r.ask(ml=100)
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "not confirmed"
    assert "read unavailable or unknown during the dose" in r.alert("CS-802")["message"]


def test_a_dose_too_short_to_read_waits_for_the_recorder_and_without_one_is_not_confirmed(rig):
    r = rig()
    r.config()
    r.behaviour["button.balance_start"] = "quick"
    r.recorder_lag = 5.0  # the recorder has it only seconds later
    r.ask(ml=2)
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "finished" and r.codes() == []
    r.recorder = False  # nothing can say it dosed
    r.ask(ml=2)
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "not confirmed" and r.codes() == ["CS-802"]


def test_a_dose_that_ends_in_less_than_half_its_time_ended_early_and_draws_what_ran(rig):
    r = rig()
    r.config(pumps=(LINKED,))
    r.behaviour["button.balance_start"] = "early"
    r.ask(ml=500)  # 50 s expected; the firmware stops it at 10 s
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "ended early"
    alert = r.alert("CS-802")
    assert alert["title"] == "A dose ended early (CS-802)" and "it ended early" in alert["message"]
    [draw] = r.draws()
    assert 100 <= draw["draws"]["balance_stock"] <= 120  # the seconds it ran x the flow, not 500


def test_a_batch_stops_at_a_dose_that_ended_early(rig):
    r = rig()
    _full_batch(r)
    r.behaviour["button.balance_start"] = "early"
    r.ask("batch")
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "stopped: dose: Balance: ended early"
    assert r.codes() == ["CS-802", "CS-806"]


# ------------------------------------------------------------------ 8. the volume number
def test_a_volume_number_that_does_not_read_back_is_named_in_cs_806(rig):
    r = rig()
    r.config()
    real = r.call

    def deaf(domain, service, timeout=None, **data):  # the number ignores being put back
        if service == "set_value" and data["value"] == 25.0:
            r.fake.calls.append((domain, service, data))
            return True
        return real(domain, service, timeout=timeout, **data)

    r.runner._call = deaf
    r.ask(ml=50)
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "finished"
    assert "the volume number of Balance could not be put back to 25 mL" in r.alert("CS-806")["message"]


# ------------------------------------------------------------------ 10. batch commands, read back
def test_a_hold_that_does_not_read_on_ends_the_batch_before_anything_else_moves(rig):
    r = rig()
    _full_batch(r)
    r.deaf["input_boolean.tank_hold"] = 99
    r.ask("batch")
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "stopped: hold: input_boolean.tank_hold did not read on"
    assert ("turn_off", "switch.row1") not in r.actions()  # nothing of the room was closed
    assert ("turn_on", "switch.tank_fill") not in r.actions()
    assert r.runner.holds(r.c.rooms[0]) is None


def test_a_fill_valve_that_does_not_open_ends_the_batch_and_is_switched_off(rig):
    r = rig()
    _full_batch(r)
    r.deaf["switch.tank_fill"] = 99
    r.ask("batch")
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "stopped: fill: the fill valve did not open"
    assert r.codes() == ["CS-804", "CS-806"]
    assert "the fill valve (switch.tank_fill) did not open" in r.alert("CS-804")["message"]
    assert ("turn_off", "switch.tank_fill") in r.actions()
    assert not any(svc == "set_value" for _d, svc, _data in r.fake.calls)  # nothing dosed


def test_a_mix_pump_that_does_not_read_on_ends_the_batch(rig):
    r = rig()
    _full_batch(r)
    r.deaf["switch.tank_mixer"] = 99
    r.ask("batch")
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "stopped: mix: the mix pump (switch.tank_mixer) did not read on"
    assert r.codes() == ["CS-805", "CS-806"]


def test_a_batch_whose_mix_minimum_power_has_no_sensor_is_refused(rig):
    r = rig()
    r.config(pumps=(BALANCE, BLOOM), batch=dict(BATCH, mix_power_sensor=None))
    r.ask("batch")
    r.runner.poll()
    assert r.status()[1]["handled_result"] == (
        "refused: the mix pump has a minimum power but no power sensor to read it")


def test_a_batch_whose_fill_time_cannot_be_stamped_finishes_with_a_warning(rig):
    r = rig()
    _full_batch(r)
    real = r.call

    def no_stamp(domain, service, timeout=None, **data):
        return False if service == "set_datetime" else real(domain, service, timeout=timeout, **data)

    r.runner._call = no_stamp
    r.ask("batch")
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "finished; input_datetime.tank_filled could not be stamped"
    assert r.codes() == ["CS-806"] and "record it by hand" in r.alert("CS-806")["message"]
    assert r.runner.holds(r.c.rooms[0]) is None


def test_a_hold_that_will_not_release_keeps_the_rooms_held_and_is_sent_off_every_pass(rig):
    r = rig()
    _full_batch(r)
    r.ask("batch")
    r.clock.at(400, lambda: r.stuck.update({"input_boolean.tank_hold": 99}))  # in the postmix
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "finished"
    assert r.runner.holds(r.c.rooms[0]) == "dosing hardware still on: input_boolean.tank_hold"
    assert r.codes() == ["CS-806"] and "does not read off" in r.alert("CS-806")["message"]
    offs = r.actions().count(("turn_off", "input_boolean.tank_hold"))
    _pass(r)
    assert r.actions().count(("turn_off", "input_boolean.tank_hold")) == offs + 1
    r.stuck["input_boolean.tank_hold"] = 0
    _pass(r)
    _pass(r)
    assert r.runner.holds(r.c.rooms[0]) is None and r.saved()["inflight"] is None


# ------------------------------------------------------------------ 11. a stop, never late
def test_a_stop_is_acted_on_however_old_while_a_dose_runs_in_its_room(rig):
    r = rig()
    r.config()
    r.ask(ml=500)
    r.clock.at(10, lambda: r.ask("stop", age=300))  # read late, five minutes after it was made
    r.runner.poll()
    status = r.status()[1]
    assert status["handled_result"] == "stopped" and status["history"][0]["result"] == "stopped"


def test_a_stop_is_read_at_every_step_not_only_on_the_next_pass(rig, monkeypatch):
    r = rig()
    _full_batch(r)
    monkeypatch.setattr(dosing_runner, "POLL_S", 1000.0)  # no pass between steps: only the step sees it
    r.clock.at(1.5, lambda: r.ask("stop"))  # while the room is being closed
    r.ask("batch")
    r.runner.poll()
    assert ("turn_on", "switch.tank_fill") not in r.actions()  # the fill valve never opened
    assert r.status()[1]["history"][0]["result"] == "stopped: fill: stop requested by Ben"


def test_while_a_batch_runs_the_chores_wait_30_s_between_runs(rig):
    r = rig()
    r.config(pumps=(LINKED,))
    r.draw_ok = False
    r.ask(ml=50)
    r.runner.poll()  # a draw Home Assistant does not take
    batch = dict(BATCH, recipe=[], fill_valve=None, full_entity=None, mix_pump=None, mix_valves=[],
                 mix_power_sensor=None, mix_min_w=0, premix_min=2, postmix_min=0)
    r.config(pumps=(LINKED,), batch=batch)
    reads, real = [], r.runner._get

    def counted(entity, **timeout):
        reads.append(entity)
        return real(entity, **timeout)

    r.runner._get = counted
    sent = len(r.draws())
    r.ask("batch")
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "finished"
    # A two-minute premix read every 2 s: the draw retried about every 30 s, not on every pass, and
    # the pumps' flow read about as often.
    assert 3 <= len(r.draws()) - sent <= 7
    assert 3 <= reads.count(LINKED["flow_entity"]) <= 9


# ------------------------------------------------------------------ 12. stock draws
def test_a_draw_for_a_tank_the_room_does_not_have_is_dropped_kept_in_the_history_and_alerted(rig):
    r = rig()
    r.config(pumps=(LINKED,))
    r.draw_answer = (200, {"counted": False, "duplicate": False, "skipped": ["balance_stock"]})
    r.ask(ml=50)
    r.runner.poll()
    assert r.saved()["draws"] == []
    entry = r.saved()["history"][0]
    assert entry["kind"] == "draw" and entry["draws"] == {"balance_stock": 50}
    assert "balance_stock does not name one of this room's stock tanks" in entry["result"]
    assert r.codes() == ["CS-807"]
    r.runner.poll()
    assert len(r.draws()) == 1 and len(r.creates("CS-807")) == 1  # once


def test_a_draw_home_assistant_refuses_is_not_sent_again(rig):
    r = rig()
    r.config(pumps=(LINKED,))
    r.draw_answer = (400, None)
    r.ask(ml=50)
    r.runner.poll()
    r.runner.poll()
    assert len(r.draws()) == 1 and r.saved()["draws"] == []
    assert "Home Assistant refused it (HTTP 400)" in r.alert("CS-807")["message"]


def test_a_draw_home_assistant_never_takes_is_given_up_after_a_day(rig):
    r = rig()
    r.config(pumps=(LINKED,))
    r.draw_ok = False
    r.ask(ml=50)
    r.runner.poll()
    _pass(r, 23 * 3600)
    assert len(r.saved()["draws"]) == 1 and r.codes() == []
    _pass(r, 3600)
    assert r.saved()["draws"] == [] and r.codes() == ["CS-807"]
    assert "did not take it within 24 hours" in r.alert("CS-807")["message"]


# ------------------------------------------------------------------ 13. stuck batch hardware
def test_what_a_batch_left_on_is_said_again_every_30_min_and_a_stop_releases_it(rig):
    r = rig()
    _full_batch(r)
    r.stuck["switch.tank_mixer"] = 99
    r.ask("batch")
    r.runner.poll()
    assert r.runner.holds(r.c.rooms[0]) == "dosing hardware still on: switch.tank_mixer"
    _pass(r, dosing_runner.REALERT_S)
    assert len(r.creates("CS-806")) == 2
    r.stuck["switch.tank_mixer"] = 0
    r.ask("stop")
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "stopped"
    assert r.runner.holds(r.c.rooms[0]) is None and r.saved()["inflight"] is None
    assert r.fake.states["input_boolean.tank_hold"][0] == "off"


# ------------------------------------------------------------------ 14. errors in the controller
def test_an_error_in_the_middle_of_a_single_dose_cuts_the_pump_and_settles_it(rig, monkeypatch):
    r = rig()
    r.config()

    def broken(*_a, **_k):
        raise RuntimeError("a bug")

    monkeypatch.setattr(r.runner, "_recorded", broken)  # as the dose ends
    r.ask(ml=50)
    r.runner.poll()
    status = r.status()[1]
    assert status["handled_result"] == "stopped: an error in the controller"
    assert ("turn_off", "switch.balance_power") in r.actions()
    assert r.codes() == ["CS-806"] and r.saved()["inflight"] is None
    assert status["history"][0]["result"] == "stopped: an error in the controller"


def test_an_error_before_a_single_dose_starts_is_settled_too(rig, monkeypatch):
    r = rig()
    r.config()
    monkeypatch.setattr(r.runner, "_dose_check", lambda pump, ml: 1 / 0)
    r.ask(ml=50)
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "stopped: an error in the controller"
    assert r.saved()["inflight"] is None and r.codes() == ["CS-806"]


def test_an_error_while_checking_a_batch_refuses_it_and_nothing_moves(rig, monkeypatch):
    r = rig()
    _full_batch(r)
    monkeypatch.setattr(r.runner, "_held_rooms", lambda room, batch: 1 / 0)
    r.ask("batch")
    r.runner.poll()
    assert r.status()[1]["handled_result"].startswith("refused: an error in the controller (ZeroDivisionError")
    assert r.actions() == [] and r.saved()["inflight"] is None
    assert r.runner.holds(r.c.rooms[0]) is None


def test_one_rooms_error_never_stops_the_others_and_is_alerted_when_it_keeps_on(rig, monkeypatch):
    veg = _desc(prefix="veg_", slug="veg", pump="switch.veg_pump", mainline=None, valves={"1": "switch.veg_row1"})
    r = rig({"sensor.crop_steering_veg_engine_config": ("ok", veg)})
    r.config()
    real = r.runner._config

    def broken(room):
        if room.slug == "veg":
            raise RuntimeError("veg is broken")
        return real(room)

    monkeypatch.setattr(r.runner, "_config", broken)
    request = r.ask(ml=10)
    for _ in range(dosing_runner.POLL_FAILS):
        _pass(r)
    assert r.status()[1]["handled"] == request["id"]  # the default room carried on
    assert r.codes() == ["CS-806"]
    assert r.alert("CS-806")["title"] == "veg: dosing in this room keeps failing (CS-806)"
    assert "veg is broken" in r.alert("CS-806")["message"]


# ------------------------------------------------------------------ 15. dosing_state.json
def test_a_corrupt_dosing_state_is_kept_and_every_rooms_current_hardware_switched_off(rig, tmp_path):
    r = rig({"switch.tank_mixer": ("on", {})})
    r.config(pumps=(BALANCE, BLOOM), batch=BATCH)
    (tmp_path / "dosing_state.json").write_text("{not json", encoding="utf-8")
    r.runner = r.c.dosing = r.build(tmp_path / "dosing_state.json")  # the app starts again
    assert (tmp_path / "dosing_state.json.bad").read_text(encoding="utf-8") == "{not json"
    r.runner.recover()
    assert r.codes() == ["CS-803"] and "dosing_state.json.bad" in r.alert("CS-803")["message"]
    r.runner.poll()  # the room's setup is read: its dosing hardware held and switched off
    assert r.runner.holds(r.c.rooms[0]).startswith("dosing hardware still on")
    _pass(r)
    _pass(r)
    assert r.fake.states["switch.tank_mixer"][0] == "off"
    assert r.runner.holds(r.c.rooms[0]) is None
    offs = {entity for service, entity in r.actions() if service == "turn_off"}
    assert offs >= {"switch.balance_power", "switch.bloom_power", "switch.tank_fill", "switch.tank_mixer",
                    "switch.mix_valve"}
    assert "input_boolean.tank_hold" not in offs  # it may be someone else's: never touched
    assert json.loads((tmp_path / "dosing_state.json").read_text(encoding="utf-8"))["rooms"]


def test_dosing_state_is_synced_to_disk_on_every_write(rig, monkeypatch):
    synced, real = [], os.fsync
    monkeypatch.setattr(dosing_runner.os, "fsync", lambda fd: synced.append(fd) or real(fd))
    r = rig()
    r.config()
    r.ask(ml=10)
    r.runner.poll()
    assert len(synced) >= 3  # every write: the request taken, the dose recorded, its end


# ------------------------------------------------------------------ the rest
def test_a_batch_is_refused_when_its_hold_cannot_be_read(rig):
    r = rig({"input_boolean.tank_hold": ("unavailable", {})})
    _full_batch(r)
    r.ask("batch")
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "refused: input_boolean.tank_hold can't be read"
    assert r.actions() == []


def test_a_pause_never_sleeps_a_negative_time(rig, monkeypatch):
    r = rig()
    _full_batch(r)
    waits, real_check, real_wait = [], r.runner._check, r.runner._wait

    def slow(job, catch=False):  # a check that takes a while, past the pause's end
        r.clock.t += 1.5
        return real_check(job, catch)

    def wait(job, seconds):
        waits.append(seconds)
        return real_wait(job, seconds)

    monkeypatch.setattr(r.runner, "_check", slow)
    monkeypatch.setattr(r.runner, "_wait", wait)
    r.ask("batch")
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "finished"
    assert waits and min(waits) >= 0


def test_a_pass_changes_a_rooms_saved_part_only_under_the_lock(rig, monkeypatch):
    r = rig()
    r.config()
    real = r.runner._block

    def checked(room):
        assert r.runner._lock._is_owned(), "a room's saved part changed without the lock"
        return real(room)

    monkeypatch.setattr(r.runner, "_block", checked)
    r.ask(ml=10)
    r.runner.poll()
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "finished"


def test_a_running_dose_keeps_its_setup_on_the_page_when_one_read_fails(rig):
    r = rig()
    r.config()
    seen = []
    r.ask(ml=500)
    r.clock.at(10, lambda: r.fake.set_state(CONFIG, "unavailable", {}))
    r.clock.at(13, lambda: seen.append(r.status()[0]))
    r.runner.poll()
    assert seen == ["dosing"]  # not "unavailable": the dose is still running


def test_a_pump_running_by_hand_or_that_cannot_be_watched_is_not_dosed(rig):
    r = rig({"switch.balance_power": ("on", {})})
    r.config()
    r.ask(ml=10)
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "refused: Balance is running by hand"
    r.set("switch.balance_power", "off")
    r.set("binary_sensor.balance_dosing", "unavailable")
    r.ask(ml=10)
    r.runner.poll()
    assert r.status()[1]["handled_result"] == (
        "refused: Balance's dosing state (binary_sensor.balance_dosing) can't be read")
    assert r.actions() == []  # nothing pressed, nothing switched (its power is never switched on)
