"""The dosing runner reads its device numbers through the device-unit table and drives its hardware
through the actuator table (docs/DOSING.md, Units and hardware).

A mix pump's power plug in kW never reached a minimum in W, so every batch failed with CS-805; a flow
in mL/min made every time limit 60 times too short; a volume number in L was told 1000 times the
dose; a fill or mix valve in Home Assistant's valve domain could not be opened. Each now reads and
drives as its unit and domain say. Everything that worked at 3.11.1 must not notice: the calls a
dose, an overrun and a batch on switch, input_boolean and light hardware send are compared with the
ones 3.11.1's runner sent (fixtures/dosing_calls_3_11_1.json), a unitless or mL/s flow gives the same
limits, and no dose that finished under 3.11.1's limits is refused or cut.

Driven as test_dosing_runner.py drives it: the real Controller, the in-memory Home Assistant and a
fake clock.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

import controller
import dosing_runner
from test_dosing_runner import BALANCE, BATCH, BLOOM, make_rig

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "dosing_calls_3_11_1.json")
# How Home Assistant drives a light and a valve (the rig scripts switches and input_booleans).
DRIVEN = {"light": ("turn_on", "turn_off", "on", "off"),
          "valve": ("open_valve", "close_valve", "open", "closed")}
# Dosing hardware on every on/off domain 3.11.1 drove: a switch fill valve, a light relay mixer and an
# input_boolean mix valve.
OLD_DOMAINS = {"fill_valve": "switch.tank_fill", "mix_pump": "light.tank_mixer",
               "mix_valves": ["input_boolean.mix_valve"]}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return make_rig(tmp_path, monkeypatch)


def _hardware(r, units=None, mixer=None):
    """Lights and valves switch as Home Assistant switches them; `units` (entity -> unit) stay on
    their entities whatever state they are set to; `mixer`: a mix pump the rig does not script."""
    units = units or {}
    plain_set, plain_call = r.set, r.call

    def set_(entity, state):
        plain_set(entity, state)
        if entity in units:
            state, _attributes, updated = r.fake.states[entity]
            r.fake.states[entity] = (state, {"unit_of_measurement": units[entity]}, updated)

    def call(domain, service, timeout=None, **data):
        row, entity = DRIVEN.get(domain), data.get("entity_id")
        if not row or service not in row[:2]:
            return plain_call(domain, service, timeout=timeout, **data)
        r.times.append((r.clock.t, service, entity))
        r.fake.calls.append((domain, service, data))
        on = service == row[0]
        if not on and r.stuck.get(entity):
            r.stuck[entity] -= 1
            return True
        r.set(entity, row[2] if on else row[3])
        if on and entity == r.fill and r.full_after is not None:
            r.clock.at(r.full_after, lambda: r.set(BATCH["full_entity"], "on"))
        if entity == mixer:
            watts = r.watts if on else 0
            r.clock.at(2, lambda: r.set(BATCH["mix_power_sensor"], f"{watts:g}"))
        return True

    r.set = set_
    r.runner._call = call
    r.fill = None


def _batch(r, **hardware):
    batch = {**BATCH, **hardware}
    r.fill = batch["fill_valve"]
    r.config(pumps=(BALANCE, BLOOM), batch=batch)
    return batch


def _sent(r):
    """Every command (not a notification, not a stock draw) as (domain, service, data)."""
    return [[domain, service, data] for domain, service, data in r.fake.calls
            if domain not in ("persistent_notification", "crop_steering")]


def _everything(r, reads):
    """A dose, a dose that runs past its time and a whole batch on OLD_DOMAINS hardware -> the
    commands sent, and every read of that hardware and of the pumps' power, in order."""
    hardware = {OLD_DOMAINS["fill_valve"], OLD_DOMAINS["mix_pump"], *OLD_DOMAINS["mix_valves"],
                BATCH["hold_entity"], *BATCH["close_entities"], BALANCE["power_entity"], BLOOM["power_entity"]}
    get = r.runner._get

    def watch(entity, *args, **kwargs):
        if entity in hardware:
            reads.append(entity)
        return get(entity, *args, **kwargs)

    r.runner._get = watch
    _batch(r, **OLD_DOMAINS)
    r.ask(ml=50)
    r.poll()
    r.behaviour["button.balance_start"] = "overrun"
    r.ask(ml=120)
    r.poll()
    r.behaviour.clear()
    r.ask("batch")
    r.poll()
    return _sent(r), r.status()[1]["history"]


def _old_rig(rig):
    r = rig({"light.tank_mixer": ("off", {}), "input_boolean.mix_valve": ("off", {})})
    _hardware(r, mixer="light.tank_mixer")
    return r


# ------------------------------------------------------------------ what worked at 3.11.1 is unchanged
def test_switch_input_boolean_and_light_hardware_sends_what_3_11_1_sent(rig):
    r = _old_rig(rig)
    reads = []
    sent, history = _everything(r, reads)
    with open(FIXTURE, encoding="utf-8") as fh:
        recorded = json.load(fh)
    assert [entry["result"] for entry in history] == ["finished", "ran past its time", "finished"]
    assert json.loads(json.dumps(sent)) == recorded["calls"]
    assert reads == recorded["reads"]


FLOWS = ["0.05", "0.5", "10", "11.06", "55.5"]
DOSES = [0.5, 1, 10, 60, 300, 599, 1999]


@pytest.mark.parametrize("unit", [None, "mL/s"])
def test_a_unitless_or_ml_per_s_flow_gives_3_11_1s_limits(rig, unit):
    """3.11.1 took a flow as mL/s whatever it said: refused a dose expected over MAX_DOSE_S, expected
    ml / flow and cut it at min(expected * 1.25 + 20, DOSE_CAP_S)."""
    for flow in FLOWS:
        r = rig({"number.balance_flow": (flow, {"unit_of_measurement": unit} if unit else {})})
        for ml in DOSES:
            why, got = r.runner._dose_check(BALANCE, ml)
            if ml / float(flow) > dosing_runner.MAX_DOSE_S:
                assert (why, got) == (dosing_runner.DosingRunner._too_long(BALANCE, ml, float(flow)), None)
            else:
                assert (why, got) == (None, float(flow))


@pytest.mark.parametrize("unit,per_ml_s", [("mL/s", 1), ("mL/min", 60), ("L/h", 3.6)])
def test_no_dose_that_finished_under_3_11_1s_limits_is_refused_or_cut(rig, unit, per_ml_s):
    """3.11.1 read the number as mL/s. A dose it let finish (its real time, at the flow the unit
    says, inside 3.11.1's cut) is still accepted, cut no sooner and never ends early."""
    for reading in ("0.5", "5", "60", "600", "2000"):
        r = rig({"number.balance_flow": (reading, {"unit_of_measurement": unit})})
        for ml in DOSES:
            old = ml / float(reading)
            real = ml * per_ml_s / float(reading)  # seconds the pump really runs
            if old > dosing_runner.MAX_DOSE_S or real > min(old * 1.25 + 20, dosing_runner.DOSE_CAP_S):
                continue  # refused, or cut, at 3.11.1
            why, flow = r.runner._dose_check(BALANCE, ml)
            assert why is None, (reading, unit, ml)
            expected = ml / flow
            assert real <= min(expected * 1.25 + 20, dosing_runner.DOSE_CAP_S)
            assert real >= expected / 2  # not "ended early"


# ------------------------------------------------------------------ units
def test_a_mix_plug_in_kw_reads_its_power_in_watts(rig):
    r = rig({"sensor.mixer_power": ("0", {"unit_of_measurement": "kW"})})
    _hardware(r, units={"sensor.mixer_power": "kW"})
    _batch(r, mix_min_w=30)
    r.watts = 0.05  # 50 W
    r.ask("batch")
    r.poll()
    assert r.status()[1]["handled_result"] == "finished" and "CS-805" not in r.codes()


def test_a_mix_plug_in_kw_below_the_minimum_still_fails_the_batch(rig):
    r = rig({"sensor.mixer_power": ("0", {"unit_of_measurement": "kW"})})
    _hardware(r, units={"sensor.mixer_power": "kW"})
    _batch(r, mix_min_w=30)
    r.watts = 0.02  # 20 W
    r.ask("batch")
    r.poll()
    assert "CS-805" in r.codes() and "(it reads 0.02 kW)" in r.alert("CS-805")["message"]


def test_a_flow_of_60_ml_per_minute_gives_one_second_per_ml(rig):
    r = rig({"number.balance_flow": ("60", {"unit_of_measurement": "mL/min"})})
    r.config()
    r.behaviour["button.balance_start"] = "overrun"  # the motor runs until the clock stops it
    r.ask(ml=30)
    r.clock.at(31, lambda: r._halt(BALANCE))  # 30 mL at 1 mL/s, pressed at 1 s
    r.poll()
    status = r.status()[1]
    assert status["handled_result"] == "finished" and r.codes() == []
    assert status["pumps"]["balance"]["flow_ml_s"] == 1.0
    assert r.runner._dose_check(BALANCE, 30) == (None, 1.0)


def test_a_volume_number_in_litres_is_written_and_read_back_in_litres(rig):
    r = rig({"number.balance_volume": ("0.025", {"unit_of_measurement": "L"})})
    _hardware(r, units={"number.balance_volume": "L"})
    r.config()
    r.behaviour["button.balance_start"] = "overrun"
    r.ask(ml=100)
    r.clock.at(11, lambda: r._halt(BALANCE))  # 100 mL at 10 mL/s, pressed at 1 s
    r.poll()
    assert [d["value"] for _dom, svc, d in r.fake.calls if svc == "set_value"] == [0.1, 0.025]
    assert r.status()[1]["handled_result"] == "finished" and r.codes() == []
    assert r.fake.states["number.balance_volume"][0] == "0.025"


def test_a_volume_number_that_does_not_read_back_in_its_unit_is_refused(rig):
    r = rig({"number.balance_volume": ("0.025", {"unit_of_measurement": "L"})})
    r.config()  # the rig drops the unit on the write: the number reads 0.1 mL, not 100
    r.ask(ml=100)
    r.poll()
    assert r.status()[1]["handled_result"] == (
        "refused: number.balance_volume did not read back 100 mL, so start was not pressed")
    assert ("press", "button.balance_start") not in r.actions()


def test_an_unknown_unit_is_read_as_before_and_said_once(rig, capsys):
    r = rig({"number.balance_flow": ("10", {"unit_of_measurement": "drops"})})
    r.config()
    for _ in range(2):
        assert r.runner._dose_check(BALANCE, 50) == (None, 10.0)
    said = [line for line in capsys.readouterr().out.splitlines() if "number.balance_flow" in line]
    assert len(said) == 1 and "'drops'" in said[0] and "as it always was" in said[0]


# ------------------------------------------------------------------ actuators
VALVES = {"fill_valve": "valve.tank_fill", "mix_valves": ["valve.mix_valve"]}


def _valve_rig(rig):
    r = rig({"valve.tank_fill": ("closed", {}), "valve.mix_valve": ("closed", {})})
    _hardware(r)
    return r


def test_a_valve_fill_and_mix_valve_run_a_batch_opened_closed_and_read_back(rig):
    r = _valve_rig(rig)
    _batch(r, **VALVES)
    r.ask("batch")
    r.poll()
    assert r.status()[1]["handled_result"] == "finished" and r.codes() == []
    assert r.actions("valve.tank_fill", "valve.mix_valve") == [
        ("open_valve", "valve.tank_fill"),
        ("close_valve", "valve.tank_fill"),
        ("open_valve", "valve.mix_valve"),
        ("close_valve", "valve.mix_valve"),
    ]
    assert {r.fake.states[v][0] for v in ("valve.tank_fill", "valve.mix_valve")} == {"closed"}


@pytest.mark.parametrize("fill", ["switch.tank_fill", "valve.tank_fill"])
def test_a_fill_valve_that_does_not_close_takes_the_stuck_hardware_path(rig, fill):
    r = _valve_rig(rig)
    _batch(r, fill_valve=fill)
    r.stuck[fill] = 99
    r.ask("batch")
    r.poll()
    room = r.c.rooms[0]
    assert r.runner.holds(room) == f"dosing hardware still on: {fill}"
    assert f"{fill} did not read off after filling" in r.status()[1]["handled_result"]
    assert r.codes()[-1] == "CS-806"


# ------------------------------------------------------------------ no read or command skips the tables
NUMBERS = {"number.balance_volume", "number.balance_flow", "input_number.bloom_volume", "sensor.bloom_flow",
           "number.recipe_bloom", "sensor.mixer_power", "sensor.tank_ec", "sensor.tank_ph"}
ACTUATORS = {"valve.tank_fill", "valve.mix_valve", "switch.tank_mixer", "switch.balance_power",
             "switch.bloom_power"}


def _spy(r):
    """Which function read each dosing number and actuator, and which sent each actuator command."""
    reads, calls = [], []
    get, call = r.runner._get, r.runner._call

    def watch_get(entity, *args, **kwargs):
        if entity in NUMBERS | ACTUATORS:
            frame = sys._getframe(2)  # 1 is _fetch
            names = [frame.f_code.co_name, frame.f_back.f_code.co_name]
            reads.append((entity, names[0] if names[0] != "_state" else names[1]))
        return get(entity, *args, **kwargs)

    def watch_call(domain, service, timeout=None, **data):
        if data.get("entity_id") in ACTUATORS:
            calls.append((data["entity_id"], service, sys._getframe(1).f_code.co_name))
        return call(domain, service, timeout=timeout, **data)

    r.runner._get, r.runner._call = watch_get, watch_call
    return reads, calls


def _bypasses(reads, calls):
    table = controller.ACTUATORS
    return ([row for row in reads if row[1] != ("_device" if row[0] in NUMBERS else "_hw_state")]
            + [row for row in calls if row[2] not in ("_on", "_switch_off", "_send_off")
               or row[1] not in table[row[0].split(".", 1)[0]][:2]])


def test_every_dosing_number_and_actuator_goes_through_the_tables(rig):
    r = _valve_rig(rig)
    _batch(r, **VALVES)
    r.set("sensor.mixer_power", "0")
    room = r.c.rooms[0]  # the tank probes the mix check reads (test_mix_check.py)
    room.feed_ec_sensor, room.feed_ph_sensor = "sensor.tank_ec", "sensor.tank_ph"
    r.fake.set_state("sensor.tank_ec", "2000", {"unit_of_measurement": "µS/cm"})
    r.fake.set_state("sensor.tank_ph", "5.9", {})
    r.fake.set_state("number.crop_steering_irrigation_ec_max", "2.5", {})
    r.fake.set_state("number.crop_steering_irrigation_ph_max", "6.4", {})
    reads, calls = _spy(r)
    r.ask(ml=50)
    r.poll()
    r.behaviour["button.balance_start"] = "overrun"  # its power is switched off and read back
    r.ask(ml=120)
    r.poll()
    r.behaviour.clear()
    r.ask("batch")
    r.poll()
    r.clock.sleep(dosing_runner.MIX_SETTLE_S)
    r.runner.poll()
    assert [entry["result"] for entry in r.status()[1]["history"]] == ["finished", "ran past its time", "finished"]
    assert r.status()[1]["mix"]["verdict"] == "good"
    assert _bypasses(reads, calls) == []
    assert {entity for entity, _how in reads} == NUMBERS | ACTUATORS  # every one was read
    # and every actuator driven but Bloom's power, which nothing in this run switches off
    assert {entity for entity, _service, _how in calls} == ACTUATORS - {"switch.bloom_power"}


def test_the_guard_catches_a_read_or_command_that_skips_the_tables(rig):
    r = _valve_rig(rig)
    reads, calls = _spy(r)
    r.runner._state("number.balance_flow")  # a new code path reading a flow as it stands
    r.runner._call("valve", "turn_on", entity_id="valve.tank_fill")
    assert _bypasses(reads, calls) == [
        ("number.balance_flow", "test_the_guard_catches_a_read_or_command_that_skips_the_tables"),
        ("valve.tank_fill", "turn_on", "test_the_guard_catches_a_read_or_command_that_skips_the_tables"),
    ]
