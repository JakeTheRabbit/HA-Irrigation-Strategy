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
    monkeypatch.setenv("F2_STATE_PATH", str(tmp_path / "state.json"))
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
    options = {
        "num_zones": 2,
        "hardware": {"pump": PUMP, "mainline": MAIN, "valves": {"1": V1, "2": V2}},
        "enable_flag": KILL,
        "hold_entities": [],
    }
    monkeypatch.setattr(controller, "load_options", lambda: dict(options))
    for name in ("ha_get", "ha_get_status", "ha_call", "ha_get_all", "ha_set", "ha_service_response"):
        monkeypatch.setattr(controller, name, getattr(fake, name))
    for eid in (KILL, "switch.crop_steering_room_active"):
        fake.set_state(eid, "on")
    for eid in (PUMP, MAIN, V1, V2):
        fake.set_state(eid, "off")
    for zone, vwc in ((1, "40"), (2, "41")):
        fake.set_state(f"switch.crop_steering_zone_{zone}_enabled", "on")
        fake.set_state(f"switch.crop_steering_zone_{zone}_manual_override", "off")
        fake.set_state(f"sensor.crop_steering_vwc_zone_{zone}", vwc)
        fake.set_state(f"sensor.crop_steering_ec_zone_{zone}", "3")
    c = controller.Controller()
    c.journal.flush = lambda *a, **k: 0  # keep the events in the outbox to read
    for zone in (1, 2):
        c.rooms[0].state[zone]["phase"] = "P2"
        c.rooms[0].state[zone]["last_phase_change"] = _Wall.current - timedelta(hours=1)
    return c, fake


@pytest.fixture
def fires(monkeypatch):
    """decide() fires both zones each pass: zone 1 (VWC 40) and zone 2 (VWC 41) each with its own reason."""
    reasons = {1: TOPUP, 2: TOPUP}

    def decide(snap, p):
        return snap.phase, p.p2_threshold, True, 2.0, reasons[1 if snap.vwc < 40.5 else 2]

    monkeypatch.setattr(controller, "decide", decide)
    return reasons


def _supply(fake, demand=(600.0, 600.0), max_flow=1000.0, concurrent=2, groups=None):
    fake.set_state(SUPPLY, "1", {
        "irrigation_pumps": [{"entity_id": PUMP, "max_flow_lph": max_flow, "max_concurrent_zones": concurrent,
                              "flow_meter": None}],
        "zone_groups": {"room:": groups} if groups else {},
        "zone_meters": {},
        "zone_demand_lph": {"room:": {"1": demand[0], "2": demand[1]}},
    })


def _probes(fake):
    """Fresh readings for both zones (a probe read an hour ago is stale)."""
    for zone, vwc in ((1, "40"), (2, "41")):
        fake.set_state(f"sensor.crop_steering_vwc_zone_{zone}", vwc)
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


def test_shot_queued_and_pump_load_are_published(rig, fires):
    c, fake = rig
    _supply(fake)
    _pass(c)
    queued = [(s, a) for e, s, a in fake.writes if e == QUEUED]
    loads = [(s, a) for e, s, a in fake.writes if e == LOAD]
    requested = _events(c, "intent.queued")[0]["data"]["requested_at"]
    assert queued[0] == ("on", {"room_id": "room:", "queue": [
        {"zone": 2, "position": 1, "requested_at": requested, "priority": "steering"}],
        "friendly_name": "Shot queued"})
    assert queued[-1][0] == "off" and queued[-1][1]["queue"] == []
    assert [s for s, _a in loads] == [60.0, 0.0]  # zone 1 at 600 of 1000 L/h; zone 2 too (unchanged); idle
    assert loads[0][1]["unit_of_measurement"] == "%" and loads[0][1]["pump"] == PUMP
    fake.writes.clear()
    _Wall.current += timedelta(hours=1)
    fires[1] = fires[2] = Reason("nothing due", kind="idle")
    _pass(c)
    assert not {e for e, _s, _a in fake.writes} & {QUEUED, LOAD}  # written only when they change


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
