"""The dosing runner's refusals as guard chains (guards.py, spec 2.7 guards 18-19): a dose (DOSE), a batch (BATCH, then
RECIPE and RECIPE_DOSE for each recipe line) and pH auto-correct (PH_LOCK, PH_SETUP, PH_WAIT, PH_DOSE). The words, the
order and every side effect are today's; what the chain adds is intent.refused / intent.held in the journal, naming
the guard and its code. DOSE_RUN is the chain Task 20's timed pump runs (prime, calibrate) will ask; nothing runs a
pump through it yet.

test_every_refusal_matches_the_old_code replays each refusal path alone (and a pass of each) and compares the result,
every Home Assistant call, the alerts, the reads and the log with what the runner did before the chain
(dose_guards_golden.json, recorded at 03ac5c60). The journal is compared without the intent.* events the chain adds.
Re-record only for a deliberate change: DOSE_GUARDS_RECORD=1 PY addons/f2_control/tests/test_dose_guards.py
"""
from __future__ import annotations

import hashlib
import json
import os

import pytest

import controller
import dosing_runner
from test_dosing_runner import BALANCE, BATCH, BLOOM, STATUS, _full_batch, make_rig
from test_ph_correct import DOWN, UP, build, minutes  # noqa: F401  (build: the pH rig fixture)

GOLDEN = os.path.join(os.path.dirname(__file__), "dose_guards_golden.json")
RECORD = os.environ.get("DOSE_GUARDS_RECORD") == "1"
NO_MIX = dict(BATCH, recipe=[], mix_pump=None, mix_valves=[])


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return make_rig(tmp_path, monkeypatch)


def _intents(r, kind=None):
    return [e for e in r.c.journal.pending() if e["kind"].startswith("intent.") and kind in (None, e["kind"])]


def _guards():
    import guards

    return guards


# ------------------------------------------------------------------------------------------------- the brief's
def test_an_uncalibrated_pump_is_refused_with_todays_words_and_journaled(rig):
    r = rig()
    r.config()
    del r.fake.states["number.balance_flow"]
    r.ask(ml=50)
    r.poll()
    assert r.status()[1]["handled_result"] == "refused: Balance is not calibrated (flow missing)"
    assert r.actions() == []
    (refused,) = _intents(r)
    assert refused["kind"] == "intent.refused" and refused["outcome"] == "refused" and refused["code"] is None
    assert refused["data"] == {"guard": "calibration_valid", "reason": "Balance is not calibrated (flow missing)"}
    assert (refused["room_id"], refused["zone"]) == ("room:", None)
    assert (refused["source"]["actor"], refused["source"]["detail"]) == ("manual", "Alex")


def test_ph_lockout_refusal_names_dosing_lockout(build):  # noqa: F811
    r = build(batch=NO_MIX)
    minutes(r, 10)
    assert "no mixing pump" in r.alert("CS-809")["message"]
    (refused,) = _intents(r)  # one, though the tick refuses each minute (as the alert, it is said once)
    assert (refused["kind"], refused["outcome"], refused["code"]) == ("intent.refused", "refused", "CS-809")
    assert refused["data"] == {"guard": "dosing_lockout", "reason": (
        "the batch tank has no mixing pump set up, and a dose is never made into a tank that is not mixed")}
    assert refused["source"]["actor"] == "automation"


# ------------------------------------------------------------------------------------------------- the journal
def test_an_uncalibrated_ph_pump_names_calibration_valid_with_cs_809(build):  # noqa: F811
    r = build(**{"number.balance_flow": "0"})
    minutes(r, 7)
    (refused,) = _intents(r)
    assert (refused["code"], refused["data"]) == (
        "CS-809", {"guard": "calibration_valid", "reason": "Balance is not calibrated (flow 0)"})


def test_a_batch_refused_by_its_hold_names_dosing_lockout(rig):
    r = rig()
    _full_batch(r)
    r.set("input_boolean.tank_hold", "on")
    r.ask("batch", by=None)
    r.poll()
    assert r.status()[1]["handled_result"] == "refused: input_boolean.tank_hold is on already: something else is dosing"
    (refused,) = _intents(r)
    assert refused["data"] == {"guard": "dosing_lockout",
                               "reason": "input_boolean.tank_hold is on already: something else is dosing"}
    assert refused["source"]["actor"] == "automation" and refused["correlation"]["batch_id"]


def test_an_uncalibrated_recipe_pump_names_calibration_valid(rig):
    r = rig()
    _full_batch(r)
    r.set("sensor.bloom_flow", "0")
    r.ask("batch")
    r.poll()
    assert r.status()[1]["handled_result"] == "refused: Bloom is not calibrated (flow 0)"
    assert [e["data"]["guard"] for e in _intents(r)] == ["calibration_valid"]


def test_a_dose_a_batch_could_not_start_names_its_guard_and_batch(rig):
    r = rig()
    _full_batch(r)
    r.set("binary_sensor.balance_dosing", "on")  # passes the batch's check, refused when its dose comes
    r.ask("batch")
    r.poll()
    assert r.status()[1]["handled_result"] == "stopped: dose: Balance: refused: Balance already reads dosing"
    (refused,) = _intents(r)
    assert refused["data"] == {"guard": "dosing_lockout", "reason": "Balance already reads dosing"}
    steps = [e for e in r.c.journal.pending() if e["kind"] == "batch.step"]
    assert refused["correlation"]["batch_id"] == steps[0]["correlation"]["batch_id"]


def test_a_latched_ph_correct_is_journaled_as_held_by_dosing_lockout(build):  # noqa: F811
    r = build()
    with r.runner._lock:
        r.runner._ph_block(r.c.rooms[0])["latch"] = {"at": "x", "why": "y", "fill": "2026-09-27 19:00:00"}
    minutes(r, 10)
    (held,) = _intents(r)
    assert (held["kind"], held["outcome"], held["code"]) == ("intent.held", "held", "CS-809")
    assert held["data"] == {"guard": "dosing_lockout", "reason": (
        "pH auto-correct is locked until a person switches it off or the tank is filled again")}


def test_a_ph_correction_waiting_on_the_hold_is_journaled_as_held(build):  # noqa: F811
    r = build(**{"input_boolean.tank_hold": "on"})
    minutes(r, 10)
    (held,) = _intents(r)
    assert held["kind"] == "intent.held" and held["code"] is None
    assert held["data"] == {"guard": "dosing_lockout", "reason": (
        "input_boolean.tank_hold does not read off: something else is dosing, or it can't be read")}


def test_each_request_refused_is_journaled(rig):
    r = rig()
    r.config()
    r.set("number.balance_flow", "0")
    for _ in range(2):
        r.ask(ml=50)
        r.poll()
    assert len(_intents(r)) == 2  # two requests, two refusals


def test_a_standing_ph_refusal_is_journaled_again_each_30_min(build):  # noqa: F811
    r = build(batch=NO_MIX)
    minutes(r, 30)  # refused each minute once the reading is steady: journaled the first time
    assert len(_intents(r)) == 1
    minutes(r, 10)  # and again 30 min on
    assert len(_intents(r)) == 2


def test_a_batch_refused_by_a_guard_outside_18_19_is_journaled_too(rig):
    r = rig()
    _full_batch(r)
    r.set("binary_sensor.tank_full", "unavailable")
    r.ask("batch")
    r.poll()
    assert r.status()[1]["handled_result"] == "refused: the tank's full sensor can't be read"
    assert [(e["data"]["guard"], e["code"]) for e in _intents(r)] == [("tank_overfill", None)]


def test_a_ph_correction_held_by_a_hardware_fault_is_journaled_with_cs_301(build):  # noqa: F811
    p = build()
    p.c.rooms[0].hardware_fault = {"reason": "valve stuck", "entities": ["switch.row1"]}
    minutes(p, 7)
    (held,) = _intents(p)
    assert (held["kind"], held["data"]["guard"], held["code"]) == ("intent.held", "hardware_latch", "CS-301")
    assert held["data"]["reason"].startswith("hardware fault (CS-301)")


def test_a_broken_journal_never_changes_a_refusal(rig, monkeypatch):
    r = rig()
    r.config()
    r.set("number.balance_flow", "0")

    def broken(*_a, **_k):
        raise RuntimeError("journal down")

    monkeypatch.setattr(r.c.journal, "emit", broken)
    r.ask(ml=50)
    r.poll()
    assert r.status()[1]["handled_result"] == "refused: Balance is not calibrated (flow 0)"
    assert any("journal error" in line for line in r.logs)


# ------------------------------------------------------------------------------------------------- the shapes
def test_the_dosing_stages_in_todays_order():
    g = _guards()
    assert [(x.key, x.guard) for x in g.DOSE] == [
        ("calibrated", "calibration_valid"), ("amount", "dose_amount"), ("too_long", "dose_amount"),
        ("pump_dosing", "dosing_lockout"), ("by_hand", "dosing_lockout")]
    assert [(x.key, x.guard) for x in g.BATCH] == [
        ("hardware_fault", "hardware_latch"), ("hold", "dosing_lockout"), ("full_sensor", "tank_overfill"),
        ("mix_power", "dosing_lockout")]
    assert [(x.key, x.guard) for x in g.RECIPE] == [("recipe_pump", "recipe"), ("recipe_ml", "recipe")]
    assert [(x.key, x.guard) for x in g.RECIPE_DOSE] == [
        ("max_ml", "dose_amount"), ("calibrated", "calibration_valid"), ("too_long", "dose_amount")]
    assert [(x.key, x.guard) for x in g.PH_LOCK] == [("latch", "dosing_lockout")]
    assert [(x.key, x.guard, x.code) for x in g.PH_SETUP] == [
        ("ph_pump", "dosing_lockout", "CS-809"), ("mix_pump", "dosing_lockout", "CS-809"),
        ("mix_power", "dosing_lockout", "CS-809"), ("calibrated", "calibration_valid", "CS-809")]
    assert [(x.key, x.guard) for x in g.PH_WAIT] == [
        ("hold", "dosing_lockout"), ("mixing", "dosing_lockout"), ("hardware_fault", "hardware_latch"),
        ("duplicate", "duplicate_controller")]
    assert [(x.key, x.guard) for x in g.PH_DOSE] == [("daily_max", "dosing_lockout"), ("dose_ml", "dose_amount")]
    assert [(x.key, x.guard) for x in g.DOSE_RUN] == [
        ("hardware_fault", "hardware_latch"), ("inflight", "inflight"), ("calibrated", "calibration_valid"),
        ("hold", "dosing_lockout")]
    for stage, name in ((g.DOSE, "dose"), (g.BATCH, "batch"), (g.RECIPE, "batch"), (g.RECIPE_DOSE, "batch"),
                        (g.PH_LOCK, "ph"), (g.PH_SETUP, "ph"), (g.PH_WAIT, "ph"), (g.PH_DOSE, "ph"),
                        (g.DOSE_RUN, "dose_run")):
        assert {x.stage for x in stage} == {name}
        assert len({x.key for x in stage}) == len(stage)


# ------------------------------------------------------------------------------------------------- DOSE_RUN
def _run_ctx(**kw):
    return {"pump": BALANCE, "profile": dosing_runner.PROFILE, "action": "prime", "batch": BATCH, **kw}


def _dose_run(r, **kw):
    g = _guards()
    hit = g.first(r.runner, g.DOSE_RUN, r.c.rooms[0], None, _run_ctx(**kw))
    return None if hit is None else (hit[0].guard, hit[1], hit[2])


def test_dose_run_passes_a_ready_pump(rig):
    r = rig()
    r.config()
    assert _dose_run(r) is None
    assert r.actions() == []  # a check: nothing is switched


def test_dose_run_holds_on_a_latched_hardware_fault_first(rig):
    r = rig()
    r.config()
    r.c.rooms[0].hardware_fault = {"reason": "valve stuck", "entities": ["switch.row1"]}
    r.c.rooms[0].shot_inflight = {"zone": 1}
    guard, why, code = _dose_run(r)
    assert (guard, code) == ("hardware_latch", "CS-301") and why.startswith("hardware fault (CS-301)")


def test_dose_run_holds_while_a_shot_is_in_flight(rig):
    r = rig()
    r.config()
    r.c.rooms[0].shot_inflight = {"zone": 1}
    assert _dose_run(r) == ("inflight", "a shot is in flight in this room", None)


def test_dose_run_refuses_an_uncalibrated_pump_except_to_calibrate_it(rig):
    r = rig()
    r.config()
    r.set("number.balance_flow", "0")
    assert _dose_run(r) == ("calibration_valid", "Balance is not calibrated (flow 0)", None)
    assert _dose_run(r, action="calibrate") is None  # the calibration run is how it gets one


def test_dose_run_holds_on_the_batch_hold(rig):
    r = rig()
    r.config()
    r.set("input_boolean.tank_hold", "on")
    assert _dose_run(r) == ("dosing_lockout", "input_boolean.tank_hold is on already: something else is dosing",
                            None)
    r.set("input_boolean.tank_hold", "unavailable")
    assert _dose_run(r) == ("dosing_lockout", "input_boolean.tank_hold can't be read", None)
    assert _dose_run(r, batch=dict(BATCH, hold_entity=None)) is None


# ------------------------------------------------------------------------------------------------- the differential
def _single(ml=50, **states):
    def go(rig, _build):
        r = rig()
        r.config()
        for entity, state in states.items():
            if state is None:
                del r.fake.states[entity]
            else:
                r.set(entity, state)

        def run():
            r.ask(ml=ml)
            r.poll()
        return r, run
    return go


def _batch(batch=None, fault=False, **states):
    def go(rig, _build):
        r = rig()
        _full_batch(r)
        if batch is not None:
            r.config(pumps=(BALANCE, BLOOM), batch=batch)
        if fault:
            r.c.rooms[0].hardware_fault = {"reason": "valve stuck", "entities": ["switch.row1"]}
        for entity, state in states.items():
            r.set(entity, state)

        def run():
            r.ask("batch")
            r.poll()
        return r, run
    return go


def _ph(n=7, moves=(), latch=None, fault=False, duplicate=False, used=None, **kw):
    def go(_rig, make):
        r = make(**kw)
        r.moves = list(moves)
        room = r.c.rooms[0]
        with r.runner._lock:
            block = r.runner._ph_block(room)
            if latch is not None:
                block["latch"] = {"at": "2026-09-28T00:00:00+00:00", "why": "a dose did not move the pH", "fill": latch}
            if used is not None:
                block["day"], block["doses"] = r.runner._today(), used
        if fault:
            room.hardware_fault = {"reason": "valve stuck", "entities": ["switch.row1"]}
        if duplicate:
            r.c._guard[room.slug] = {"answered": False, "seen": None, "until": None}
        return r, lambda: minutes(r, n)
    return go


FILLED = "2026-09-27 19:00:00"
SCENARIOS = {
    "dose/ok": _single(),
    "dose/uncalibrated_zero": _single(**{"number.balance_flow": "0"}),
    "dose/uncalibrated_missing": _single(**{"number.balance_flow": None}),
    "dose/amount_zero": _single(ml=0),
    "dose/amount_over": _single(ml=5000),
    "dose/too_long": _single(ml=1500, **{"number.balance_flow": "1"}),
    "dose/already_dosing": _single(**{"binary_sensor.balance_dosing": "on"}),
    "dose/dosing_unreadable": _single(**{"binary_sensor.balance_dosing": "unavailable"}),
    "dose/by_hand": _single(**{"switch.balance_power": "on"}),
    "batch/ok": _batch(),
    "batch/fault": _batch(fault=True),
    "batch/hold_on": _batch(**{"input_boolean.tank_hold": "on"}),
    "batch/hold_dead": _batch(**{"input_boolean.tank_hold": "unavailable"}),
    "batch/full_dead": _batch(**{"binary_sensor.tank_full": "unavailable"}),
    "batch/mix_power_no_sensor": _batch(batch=dict(BATCH, mix_power_sensor=None)),
    "batch/recipe_unknown_pump": _batch(batch=dict(BATCH, recipe=[{"pump": "nope", "ml": 10}])),
    "batch/recipe_ml_dead": _batch(**{"number.recipe_bloom": "unavailable"}),
    "batch/recipe_over_max": _batch(**{"number.recipe_bloom": "5000"}),
    "batch/recipe_uncalibrated": _batch(**{"sensor.bloom_flow": "0"}),
    "batch/recipe_too_long": _batch(**{"number.balance_flow": "0.2"}),
    "batch/recipe_skips_zero_never_reads_its_flow": _batch(**{"number.recipe_bloom": "0", "sensor.bloom_flow": "0"}),
    "batch/dose_refused": _batch(**{"binary_sensor.balance_dosing": "on"}),
    "ph/ok": _ph(moves=(0.3,)),
    "ph/no_role": _ph(pumps=(BALANCE,)),
    "ph/no_mix_pump": _ph(batch=NO_MIX),
    "ph/mix_power_no_sensor": _ph(batch=dict(BATCH, recipe=[], mix_power_sensor=None)),
    "ph/uncalibrated": _ph(**{"number.balance_flow": "0"}),
    "ph/hold_on": _ph(**{"input_boolean.tank_hold": "on"}),
    "ph/hold_dead": _ph(**{"input_boolean.tank_hold": "unavailable"}),
    "ph/mixing": _ph(**{"switch.tank_mixer": "on"}),
    "ph/fault": _ph(fault=True),
    "ph/duplicate": _ph(duplicate=True),
    "ph/daily_used": _ph(used=3),
    "ph/dose_under_1_ml": _ph(pumps=(dict(UP, max_ml=0),)),
    "ph/latched": _ph(latch=FILLED),
    "ph/latched_then_filled": _ph(latch="2026-09-26 08:00:00", moves=(0.3,)),
    "ph/down": _ph(ph="6.9", pumps=(UP, DOWN), moves=(-0.6,), **{
        "number.acid_volume": "0", "button.acid_start": "unknown", "binary_sensor.acid_dosing": "off",
        "switch.acid_power": "off", "number.acid_flow": "10"}),
}


def _digest(items):
    text = json.dumps(items, default=str)
    return [len(items), hashlib.sha256(text.encode()).hexdigest()]


def _record(r, reads):
    sets = r.fake.sets.get(STATUS)
    status = sets[1] if sets else {}
    saved = {}
    if os.path.exists(r.runner.path):  # nothing written: nothing was ever done
        with open(r.runner.path, encoding="utf-8") as fh:
            saved = json.load(fh)["rooms"].get("default") or {}
    return json.loads(json.dumps({
        "result": status.get("handled_result"),
        "history": [h.get("result") for h in status.get("history") or []],
        "calls": [[d, s, data] for d, s, data in r.fake.calls],
        "reads": _digest(reads),
        "logs": _digest(r.logs),
        "ph": saved.get("ph"),
        "inflight": saved.get("inflight"),
        "journal": [[e["kind"], e["outcome"], e["code"], e["data"]] for e in r.c.journal.pending()
                    if not e["kind"].startswith("intent.")],
    }, default=str))


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_refusal_matches_the_old_code(name, rig, build, monkeypatch):  # noqa: F811
    r, run = SCENARIOS[name](rig, build)
    if name == "ph/down":
        r.pumps[DOWN["start_entity"]] = DOWN
    reads = []

    def spy(get):
        def read(entity, *a, **k):
            reads.append(entity)
            return get(entity, *a, **k)
        return read

    r.runner._get = spy(r.runner._get)
    monkeypatch.setattr(controller, "ha_get", spy(controller.ha_get))
    run()
    got = _record(r, reads)
    golden = {}
    if os.path.exists(GOLDEN):
        with open(GOLDEN, encoding="utf-8") as fh:
            golden = json.load(fh)
    if RECORD:
        golden[name] = got
        with open(GOLDEN, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(golden, fh, indent=1, sort_keys=True)
            fh.write("\n")
        return
    assert got == golden[name]
