"""Guards 16-17, the pump queue (spec 2.7, ruling R1): with a supply saved in the integration
(sensor.crop_steering_supply_config), the zones that fire in one pass take turns at their pump, rescues first, and
each one that waits behind another is journaled (intent.queued) and shown (binary_sensor shot_queued, sensor
pump_load_pct). The queue never refuses or holds a shot: a zone that alone needs more than its pump still waters,
and says so (CS-214). With no supply saved the act loop is exactly what it was."""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import controller
import fake_ha
import guards
import journal_out
from crop_steering_engine import Reason
from test_blind_grace import _Clock as _Wall  # the controller's wall clock, pinned

pytestmark = pytest.mark.usefixtures("settings_built_in")

ROOT = Path(__file__).resolve().parents[3]
KILL = "input_boolean.kill"
PUMP, MAIN, V1, V2 = "switch.p", "switch.m", "switch.v1", "switch.v2"
SUPPLY = "sensor.crop_steering_supply_config"
QUEUED = "binary_sensor.crop_steering_shot_queued"
LOAD = "sensor.crop_steering_pump_load_pct"
TOPUP = Reason("P2 top-up VWC 40.0 < 45.0", kind="p2_topup")
RESCUE = Reason("P3 emergency VWC 41.0 < 42.0", kind="p3_emergency", cap_exempt=True)
FLOOR = Reason("MIN-DAILY floor 0.0<1.0 of 2.0L", kind="min_daily")


@pytest.fixture
def rig(monkeypatch, tmp_path):
    """Two zones on one pump. The wall clock moves with the controller's sleeps, so a shot takes its time."""
    return _build(monkeypatch, tmp_path)


def _build(monkeypatch, folder, zones=2):
    """A controller with `zones` zones on one pump (zone N reads VWC 39 + N), on its own state file and fake HA."""
    folder.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("F2_STATE_PATH", str(folder / "state.json"))
    _Wall.current = _Wall(2026, 10, 22, 12, 0)  # lights 10-22: on
    monkeypatch.setattr(controller, "datetime", _Wall)
    monkeypatch.setattr(fake_ha, "datetime", _Wall)
    monkeypatch.setattr(journal_out, "datetime", _Wall)  # the events' times on the same clock
    seconds = {"now": 1000.0}

    def sleep(dt):
        seconds["now"] += dt
        _Wall.current += timedelta(seconds=dt)

    monkeypatch.setattr(controller.time, "sleep", sleep)
    monkeypatch.setattr(controller.time, "monotonic", lambda: seconds["now"])
    fake = fake_ha.FakeHA()
    fake.writes = []
    real_set = fake.ha_set

    def ha_set(entity, state, attributes=None, timeout=None):
        fake.writes.append((entity, state, attributes))
        return real_set(entity, state, attributes, timeout)

    fake.ha_set = ha_set
    valves = {str(z): f"switch.v{z}" for z in range(1, zones + 1)}
    options = {
        "num_zones": zones,
        "hardware": {"pump": PUMP, "mainline": MAIN, "valves": valves},
        "enable_flag": KILL,
        "hold_entities": [],
    }
    monkeypatch.setattr(controller, "load_options", lambda: dict(options))
    for name in ("ha_get", "ha_get_status", "ha_call", "ha_get_all", "ha_set", "ha_service_response"):
        monkeypatch.setattr(controller, name, getattr(fake, name))
    for eid in (KILL, "switch.crop_steering_room_active"):
        fake.set_state(eid, "on")
    for eid in (PUMP, MAIN, *valves.values()):
        fake.set_state(eid, "off")
    for zone in range(1, zones + 1):
        fake.set_state(f"switch.crop_steering_zone_{zone}_enabled", "on")
        fake.set_state(f"switch.crop_steering_zone_{zone}_manual_override", "off")
    _probes(fake, zones)
    c = controller.Controller()
    c.journal.flush = lambda *a, **k: 0  # keep the events in the outbox to read
    for zone in range(1, zones + 1):
        c.rooms[0].state[zone]["phase"] = "P2"
        c.rooms[0].state[zone]["last_phase_change"] = _Wall.current - timedelta(hours=1)
    return c, fake


@pytest.fixture
def fires(monkeypatch):
    """decide() fires every zone each pass, zone N (VWC 39 + N) with its own reason."""
    reasons = {1: TOPUP, 2: TOPUP, 3: TOPUP}

    def decide(snap, p):
        return snap.phase, p.p2_threshold, True, 2.0, reasons[round(snap.vwc) - 39]

    monkeypatch.setattr(controller, "decide", decide)
    return reasons


def _supply(fake, demand=(600.0, 600.0), max_flow=1000.0, concurrent=2, groups=None):
    fake.set_state(SUPPLY, "1", {
        "irrigation_pumps": [{"entity_id": PUMP, "max_flow_lph": max_flow, "max_concurrent_zones": concurrent,
                              "flow_meter": None}],
        "zone_groups": {"room:": groups} if groups else {},
        "zone_meters": {},
        "zone_demand_lph": {"room:": {str(z): lph for z, lph in enumerate(demand, 1)}},
    })


def _probes(fake, zones=2):
    """Fresh readings for the zones (a probe read an hour ago is stale)."""
    for zone in range(1, zones + 1):
        fake.set_state(f"sensor.crop_steering_vwc_zone_{zone}", str(39 + zone))
        fake.set_state(f"sensor.crop_steering_ec_zone_{zone}", "3")


def _events(c, kind):
    return [e for e in c.journal.pending() if e["kind"] == kind]


def _valves(fake):
    return [(svc, data["entity_id"]) for dom, svc, data in fake.calls
            if dom == "switch" and data.get("entity_id") in (V1, V2)]


def _switches(fake):
    return [(svc, data["entity_id"]) for dom, svc, data in fake.calls if dom == "switch"]


def _alerts(fake, code):
    return [data for dom, svc, data in fake.calls
            if (dom, svc) == ("persistent_notification", "create") and f"({code})" in data["title"]]


def _pass(c):
    c.loop_once(_Wall.current)


ONE_THEN_TWO = [("turn_on", V1), ("turn_off", V1), ("turn_on", V2), ("turn_off", V2)]
TWO_THEN_ONE = [("turn_on", V2), ("turn_off", V2), ("turn_on", V1), ("turn_off", V1)]


# ------------------------------------------------------------------------------------------------ absent = as before
def test_no_supply_descriptor_means_todays_order_and_no_events(rig, fires):
    c, fake = rig
    fires[2] = RESCUE  # with a supply saved it would go first; without one the zones go in their order, as always
    _pass(c)
    assert _valves(fake) == ONE_THEN_TWO
    assert _events(c, "intent.queued") == []
    assert not {e for e, _s, _a in fake.writes} & {QUEUED, LOAD}
    assert _alerts(fake, "CS-214") == []
    assert c.rooms[0].__dict__.get("_requested_at", {}) == {}


def test_an_unreadable_supply_descriptor_is_no_descriptor(rig, fires):
    c, fake = rig
    fires[2] = RESCUE
    fake.set_state(SUPPLY, "unavailable", {"error": "the stored settings cannot be read"})
    _pass(c)
    assert _valves(fake) == ONE_THEN_TWO and _events(c, "intent.queued") == []


def test_the_supply_is_read_once_a_pass(rig, fires, monkeypatch):
    c, fake = rig
    _supply(fake)
    reads = []
    monkeypatch.setattr(controller, "ha_get", lambda e, timeout=8: (reads.append(e), fake.ha_get(e, timeout))[1])
    _pass(c)
    assert reads.count(SUPPLY) == 1


# ------------------------------------------------------------------------------------------------------- the line
def test_two_zones_at_60_pct_take_turns_and_the_second_is_queued(rig, fires):
    c, fake = rig
    _supply(fake)  # 600 + 600 L/h on a 1000 L/h pump that may feed 2 zones at once: they cannot run together
    _pass(c)
    assert _valves(fake) == ONE_THEN_TWO
    queued, = _events(c, "intent.queued")
    assert queued["zone"] == 2 and queued["outcome"] == "queued"
    assert queued["data"]["position"] == 1 and queued["data"]["guard"] == "pump_capacity"
    assert queued["data"]["priority"] == "steering"
    done1 = next(e for e in _events(c, "shot.completed") if e["zone"] == 1)
    start2 = next(e for e in _events(c, "shot.started") if e["zone"] == 2)
    assert start2["ts"] >= done1["ts"]
    assert queued["data"]["requested_at"] == start2["data"]["requested_at"]


def test_a_rescue_runs_before_a_steering_shot_in_the_same_pass(rig, fires):
    c, fake = rig
    fires[2] = RESCUE
    _supply(fake)
    _pass(c)
    assert _valves(fake) == TWO_THEN_ONE
    queued, = _events(c, "intent.queued")
    assert queued["zone"] == 1 and queued["data"]["priority"] == "steering" and queued["data"]["position"] == 1
    assert [e["zone"] for e in _events(c, "shot.started")] == [2, 1]


def test_a_min_daily_floor_shot_is_never_held_by_capacity(rig, fires):
    c, fake = rig
    fires[2] = FLOOR
    _supply(fake, demand=(600.0, 1500.0), concurrent=1)  # zone 2 alone is bigger than its pump
    _pass(c)
    assert _valves(fake) == TWO_THEN_ONE  # the floor is a rescue: first, and it waters
    assert _events(c, "intent.held") == []
    assert [e["zone"] for e in _events(c, "shot.completed")] == [2, 1]


def test_a_zone_bigger_than_its_pump_still_waters_and_warns_cs_214(rig, fires):
    c, fake = rig
    fires[1] = RESCUE
    _supply(fake, demand=(1500.0, 600.0))
    _pass(c)
    assert ("turn_on", V1) in _valves(fake) and ("turn_on", V2) in _valves(fake)
    alert, = _alerts(fake, "CS-214")
    assert "zone 1 needs 1500 L/h, switch.p gives 1000 L/h; it waters anyway" in alert["message"]
    assert _events(c, "intent.held") == []
    entry = next(e for e in json.loads((ROOT / "docs" / "error-codes.json").read_text(encoding="utf-8"))["codes"]
                 if e["code"] == "CS-214")
    assert entry["severity"] == "warning" and entry["source"] == "notification"
    assert "CS-214" not in controller.CRITICAL_CODES | controller.INFO_CODES | controller.NOT_WATERING_CODES


def test_exclusive_group_is_recorded_but_changes_nothing(rig, fires):
    c, fake = rig
    _supply(fake, max_flow=2000.0, groups={"1": "A", "2": "A"})  # the pump could feed both: only the group says no
    _pass(c)
    grouped = _switches(fake)
    queued, = _events(c, "intent.queued")
    assert queued["zone"] == 2 and queued["data"]["guard"] == "exclusive_group"
    fake.calls.clear()
    _Wall.current += timedelta(hours=1)
    _probes(fake)
    _supply(fake, max_flow=2000.0)
    _pass(c)
    assert _switches(fake) == grouped and _valves(fake) == ONE_THEN_TWO


def test_shot_queued_and_pump_load_are_published(monkeypatch, tmp_path, fires):
    c, fake = _build(monkeypatch, tmp_path, zones=3)
    _supply(fake, demand=(600.0, 600.0, 600.0))
    _pass(c)
    queued = [(s, a) for e, s, a in fake.writes if e == QUEUED]
    loads = [(s, a) for e, s, a in fake.writes if e == LOAD]
    # once the pass is over (never between turns): nobody waits, and the most its shots put on the pump
    assert queued == [("off", {"room_id": "room:", "queue": [], "friendly_name": "Shot queued"})]
    assert [s for s, _a in loads] == [60.0]  # 600 of 1000 L/h
    assert loads[0][1]["unit_of_measurement"] == "%" and loads[0][1]["pump"] == PUMP
    fake.set_state(KILL, "off")  # every zone held: nothing runs
    for hours in (1, 2):
        fake.writes.clear()
        _Wall.current += timedelta(hours=1)
        _probes(fake, 3)
        _pass(c)
        loads = [s for e, s, _a in fake.writes if e == LOAD]
        assert loads == ([0.0] if hours == 1 else [])  # nothing ran: 0, then written only when it changes
        assert QUEUED not in {e for e, _s, _a in fake.writes}


def test_a_queued_shot_records_its_pump_wait(rig, fires):
    c, fake = rig
    _supply(fake)
    _pass(c)
    start1, start2 = sorted(_events(c, "shot.started"), key=lambda e: e["zone"])
    done1 = next(e for e in _events(c, "shot.completed") if e["zone"] == 1)
    first_shot_s = (datetime.fromisoformat(done1["ts"]) - datetime.fromisoformat(start1["ts"])).total_seconds()
    assert first_shot_s >= done1["data"]["elapsed_s"] > 0
    assert start1["data"]["pump_wait_s"] == 0
    assert start2["data"]["pump_wait_s"] == pytest.approx(first_shot_s, abs=1)


def test_a_shot_queued_longer_than_10_min_warns_cs_214_and_waters(rig, fires, monkeypatch):
    c, fake = rig
    monkeypatch.setattr(controller, "QUEUE_ALERT_S", 5)  # zone 1's shot takes longer than this
    _supply(fake)
    _pass(c)
    alert, = _alerts(fake, "CS-214")
    assert "zone 2 waited" in alert["message"] and "switch.p" in alert["message"]
    assert _valves(fake) == ONE_THEN_TWO


def test_a_held_zone_is_not_queued(rig, fires):
    c, fake = rig
    fires[2] = RESCUE
    fake.set_state("switch.crop_steering_zone_2_enabled", "off")
    _supply(fake)
    _pass(c)
    assert _valves(fake) == [("turn_on", V1), ("turn_off", V1)]
    assert _events(c, "intent.queued") == []
    held, = _events(c, "intent.held")
    assert held["zone"] == 2 and held["data"]["guard"] == "zone_paused"


# ------------------------------------------------------------------------------------------------- the chain's shape
def test_queue_guards_queue_and_never_hold():
    assert [(g.key, g.guard, g.stage) for g in guards.QUEUE] == [
        ("pump_capacity", "pump_capacity", "queue"), ("exclusive_group", "exclusive_group", "queue")]
    ctx = {"lph": 600.0, "ahead": [(1, 600.0)], "pump": {"max_flow_lph": 1000.0, "max_concurrent_zones": 2},
           "groups": {}}
    g, why, _code = guards.first(None, guards.QUEUE, None, 2, ctx)
    assert g.guard == "pump_capacity" and isinstance(why, guards.Queued) and why.behind == (1,)
    ctx["pump"]["max_flow_lph"] = 2000.0
    assert guards.first(None, guards.QUEUE, None, 2, ctx) is None
    ctx["groups"] = {1: "A", 2: "A"}
    g, why, _code = guards.first(None, guards.QUEUE, None, 2, ctx)
    assert g.guard == "exclusive_group" and why.behind == (1,)
    assert guards.first(None, guards.QUEUE, None, 2, dict(ctx, ahead=[])) is None


def test_the_daily_cap_is_the_sized_hold_that_reports_back():
    assert [g.key for g in guards.SIZED if g.reports] == ["daily_cap"]
    assert not any(g.reports for g in guards.PASS + guards.PREOPEN + guards.QUEUE)


def test_the_tank_hold_names_its_own_code(rig):
    c, fake = rig
    room = c.rooms[0]
    room.tank = {"distance": "sensor.tank_distance"}
    c._tank_level = lambda room: (None, None)
    assert c._tank_hold(room) == ("tank level unknown (sensor.tank_distance)", "CS-902")


# ------------------------------------------------------------------------------------------------------ fix round 2
def _ha_log(monkeypatch, fake):
    """Every Home Assistant call the controller makes, in order: (kind, entity or service)."""
    seen = []
    monkeypatch.setattr(controller, "ha_get", lambda e, timeout=8: (seen.append(("get", e)), fake.ha_get(e))[1])
    monkeypatch.setattr(controller, "ha_set", lambda e, st, a=None, timeout=None: (
        seen.append(("set", e)), fake.ha_set(e, st, a, timeout))[1])
    monkeypatch.setattr(controller, "ha_call", lambda d, svc, **data: (
        seen.append(("call", d, svc, data.get("entity_id") or data.get("notification_id"))),
        fake.ha_call(d, svc, **data))[1])
    return seen


def test_a_saved_supply_adds_no_home_assistant_call_before_any_pump_opens(monkeypatch, tmp_path, fires):
    """R5's spirit: nothing new slows watering. With a supply saved, every Home Assistant call up to the pass's last
    pump OFF is the call made with none; the queue, the pump load and CS-214 come after it."""
    monkeypatch.setattr(controller, "QUEUE_ALERT_S", 5)  # zone 2 and 3 wait longer: CS-214 on the wait too
    runs = {}
    for name in ("none", "supply"):
        _Wall.current = _Wall(2026, 10, 22, 12, 0)
        c, fake = _build(monkeypatch, tmp_path / name, zones=3)
        if name == "supply":
            _supply(fake, demand=(600.0, 600.0, 1500.0))  # zone 3 alone is bigger than its pump: CS-214
        seen = _ha_log(monkeypatch, fake)
        _pass(c)
        runs[name] = seen
    pump_on, pump_off = ("call", "switch", "turn_on", PUMP), ("call", "switch", "turn_off", PUMP)
    assert runs["supply"].count(pump_on) == runs["none"].count(pump_on) == 3

    def last_off(seen):
        return len(seen) - seen[::-1].index(pump_off)

    supply, none = runs["supply"], runs["none"]
    assert supply[:last_off(supply)] == none[:last_off(none)]  # identical, nothing taken away
    after = supply[last_off(supply):]
    assert ("set", QUEUED) in after and ("set", LOAD) in after
    raised = [x[3] for x in after if x[:3] == ("call", "persistent_notification", "create")]
    assert "f2_pump_short_default_z3" in raised and "f2_pump_wait_default_z3" in raised


# ------------------------------------------------------------------------------------------------------ fix round 1
def test_a_blind_copy_rescue_goes_before_a_steering_top_up(rig, fires):
    c, fake = rig
    fires[2] = Reason("COPY Z1 (VWC probe dead)", kind="blind_copy_rescue")
    _supply(fake)
    _pass(c)
    assert _valves(fake) == TWO_THEN_ONE
    queued, = _events(c, "intent.queued")
    assert queued["zone"] == 1 and queued["data"]["priority"] == "steering"


@pytest.mark.parametrize("stage", ["sized", "preopen"])
def test_a_shot_held_after_its_turn_is_not_queued_and_adds_no_pump_load(rig, fires, stage):
    c, fake = rig
    _supply(fake, demand=(600.0, 300.0))
    if stage == "sized":  # zone 2 has spent its day's budget
        c.rooms[0].state[2]["daily_vol"] = 1e6
    else:  # the plan holds zone 2 just before anything opens
        real = c._strategy_preflight
        c._strategy_preflight = lambda room, zone, now: "plan changed" if zone == 2 else real(room, zone, now)
    _pass(c)
    assert _valves(fake) == [("turn_on", V1), ("turn_off", V1)]
    assert _events(c, "intent.queued") == []
    assert [e["zone"] for e in _events(c, "intent.held")] == [2]
    assert [s for e, s, _a in fake.writes if e == LOAD] == [60.0]  # zone 2's 30 % never counted


def test_a_room_error_mid_loop_clears_shot_queued_and_the_pump_load(monkeypatch, tmp_path, fires):
    c, fake = _build(monkeypatch, tmp_path, zones=3)
    _supply(fake, demand=(600.0, 600.0, 600.0))
    _pass(c)
    assert [s for e, s, _a in fake.writes if e == LOAD] == [60.0]
    c._line_shown[QUEUED] = ("on", {})  # as a queue still shown would read
    real = c._sweep_held

    def sweep(room, zone):  # zone 2's act raises: the pass never reaches its end
        real(room, zone)
        if zone == 2:
            raise RuntimeError("boom")

    monkeypatch.setattr(c, "_sweep_held", sweep)
    fake.writes.clear()
    _Wall.current += timedelta(hours=1)
    _probes(fake, 3)
    _pass(c)
    assert [(s, a["queue"]) for e, s, a in fake.writes if e == QUEUED] == [("off", [])]
    assert [s for e, s, _a in fake.writes if e == LOAD] == [0.0]
