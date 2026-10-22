"""G4, flow reconciliation (Task 26): with a flow meter saved in the integration's supply (a zone's meter in
zone_meters, else its pump's flow_meter), each shot that completes compares the litres the meter saw with the litres
the controller counted. flow.reconciled {ratio, commanded_l, metered_l} carries the shot's intent id, its
shot.completed carries metered_l, sensor.crop_steering_<px>zone_N_flow_ratio shows it after the pass, and a shot that
got under 80 % raises CS-318. Between shots a meter that rises more than 0.5 L raises CS-319. With no meter nothing
changes: no read, no event, no sensor. Every new state write and alert comes after the room's pass (R5)."""
from datetime import timedelta

import pytest

import controller
from crop_steering_engine import Reason
from test_pump_queue import PUMP, SUPPLY, V1, V2, _Wall, _build

pytestmark = pytest.mark.usefixtures("settings_built_in")

METER, PUMP_METER = "sensor.z1_meter", "sensor.pump_meter"
RATIO_1, RATIO_2 = "sensor.crop_steering_zone_1_flow_ratio", "sensor.crop_steering_zone_2_flow_ratio"
TOPUP = Reason("P2 top-up VWC 40.0 < 45.0", kind="p2_topup")


@pytest.fixture
def rig(monkeypatch, tmp_path):
    return _build(monkeypatch, tmp_path)


@pytest.fixture
def fire(monkeypatch):
    """decide() fires the zones in `on` each pass (both, to begin with)."""
    on = {1, 2}

    def decide(snap, p):
        zone = round(snap.vwc) - 39
        return snap.phase, p.p2_threshold, zone in on, 2.0 if zone in on else 0.0, TOPUP

    monkeypatch.setattr(controller, "decide", decide)
    return on


def _supply(fake, zone_meters=None, pump_meter=None):
    fake.set_state(SUPPLY, "1", {
        "irrigation_pumps": [{"entity_id": PUMP, "max_flow_lph": 1000.0, "max_concurrent_zones": 1,
                              "flow_meter": pump_meter}],
        "zone_groups": {},
        "zone_meters": {"room:": zone_meters} if zone_meters else {},
        "zone_demand_lph": {"room:": {"1": 240.0, "2": 240.0}},
    })


def _meters_flow(c, fake, monkeypatch, meters, share):
    """Each valve's close adds `share` of its shot's commanded litres (its shot.started) to the meters in `meters`
    (valve -> the meter entities its water passes)."""
    real = controller.ha_call

    def ha_call(domain, service, **data):
        if service == "turn_off" and data.get("entity_id") in meters:
            started = [e for e in c.journal.pending() if e["kind"] == "shot.started"][-1]
            for meter in meters[data["entity_id"]]:
                state, attrs, _ = fake.ha_get(meter)
                fake.set_state(meter, str(float(state) + share * started["data"]["commanded_l"]), attrs)
        return real(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", ha_call)


def _events(c, kind):
    return [e for e in c.journal.pending() if e["kind"] == kind]


def _alerts(fake, code):
    return [data for dom, svc, data in fake.calls
            if (dom, svc) == ("persistent_notification", "create") and f"({code})" in data["title"]]


def _written(fake, entity):
    return [(s, a) for e, s, a in fake.writes if e == entity]


def _pass(c, minutes=2):
    c.loop_once(_Wall.current)
    _Wall.current += timedelta(minutes=minutes)


# ---------------------------------------------------------------------------------------------- absent = as before
@pytest.mark.parametrize("supply", [False, True])
def test_no_meter_publishes_nothing(rig, fire, monkeypatch, supply):
    c, fake = rig
    if supply:
        _supply(fake)  # a supply with no meter in it
    reads = []
    real = controller.ha_get
    monkeypatch.setattr(controller, "ha_get", lambda e, timeout=8: (reads.append(e), real(e, timeout))[1])
    _pass(c)
    _pass(c)
    assert len(_events(c, "shot.completed")) == 4
    assert all(e["data"]["metered_l"] is None for e in _events(c, "shot.completed"))
    assert _events(c, "flow.reconciled") == []
    assert not [e for e, _s, _a in fake.writes if e.endswith("_flow_ratio")]
    assert _alerts(fake, "CS-318") == [] and _alerts(fake, "CS-319") == []
    assert not [e for e in reads if "meter" in e]


# ---------------------------------------------------------------------------------------------------- per shot
def test_a_50_pct_shortfall_raises_cs_318_within_one_shot(rig, fire, monkeypatch):  # G4 accept
    c, fake = rig
    fire.discard(2)
    fake.set_state(METER, "100.0", {"unit_of_measurement": "L"})
    _supply(fake, zone_meters={"1": METER})
    _meters_flow(c, fake, monkeypatch, {V1: [METER]}, 0.5)
    _pass(c)
    done, = _events(c, "shot.completed")
    flow, = _events(c, "flow.reconciled")
    assert flow["zone"] == 1 and flow["correlation"]["intent_id"] == done["correlation"]["intent_id"]
    commanded = done["data"]["commanded_l"]
    assert flow["data"]["commanded_l"] == commanded and commanded > 0
    assert flow["data"]["metered_l"] == done["data"]["metered_l"] > 0
    assert flow["data"]["ratio"] == pytest.approx(done["data"]["metered_l"] / commanded)
    assert flow["data"]["ratio"] <= 0.5 + 1e-6 and flow["data"]["verdict"] == "low"
    (state, attrs), = _written(fake, RATIO_1)
    assert state == pytest.approx(flow["data"]["ratio"])
    assert attrs["commanded_l"] == commanded and attrs["metered_l"] == done["data"]["metered_l"]
    assert attrs["intent_id"] == done["correlation"]["intent_id"]
    alert, = _alerts(fake, "CS-318")
    assert alert["notification_id"] == "f2_flow_low_default_z1"


def test_the_pumps_meter_serves_a_zone_with_none_of_its_own_and_ok_water_clears_cs_318(rig, fire, monkeypatch):
    c, fake = rig
    fake.set_state(METER, "10.0", {"unit_of_measurement": "L"})
    fake.set_state(PUMP_METER, "0.5", {"unit_of_measurement": "m³"})
    _supply(fake, zone_meters={"1": METER}, pump_meter=PUMP_METER)
    share = {"x": 0.5}
    real = controller.ha_call

    def ha_call(domain, service, **data):  # zone 1 through both meters, zone 2 through the pump's only
        if service == "turn_off" and data.get("entity_id") in (V1, V2):
            litres = share["x"] * [e for e in c.journal.pending() if e["kind"] == "shot.started"][-1]["data"][
                "commanded_l"]
            if data["entity_id"] == V1:
                fake.set_state(METER, str(float(fake.ha_get(METER)[0]) + litres), {"unit_of_measurement": "L"})
            fake.set_state(PUMP_METER, str(float(fake.ha_get(PUMP_METER)[0]) + litres / 1000),
                           {"unit_of_measurement": "m³"})
        return real(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", ha_call)
    _pass(c)
    by_zone = {e["zone"]: e for e in _events(c, "flow.reconciled")}
    assert by_zone[1]["data"]["verdict"] == by_zone[2]["data"]["verdict"] == "low"
    assert by_zone[2]["data"]["ratio"] == pytest.approx(0.5, rel=0.05)  # m³ read as litres
    assert len(_alerts(fake, "CS-318")) == 2
    share["x"] = 1.0
    fake.calls.clear()
    _pass(c)
    assert {e["data"]["verdict"] for e in _events(c, "flow.reconciled")[2:]} == {"ok"}
    dismissed = {d["notification_id"] for dom, svc, d in fake.calls if (dom, svc) == ("persistent_notification",
                                                                                     "dismiss")}
    assert {"f2_flow_low_default_z1", "f2_flow_low_default_z2"} <= dismissed
    assert _written(fake, RATIO_2)[-1][0] == pytest.approx(1.0, rel=0.05)


def test_the_flow_ratio_is_written_after_the_pass_never_before_a_pump_opens(rig, fire, monkeypatch):
    c, fake = rig
    fake.set_state(METER, "100.0", {"unit_of_measurement": "L"})
    _supply(fake, zone_meters={"1": METER})
    _meters_flow(c, fake, monkeypatch, {V1: [METER]}, 1.0)
    order = []
    real_call, real_set = controller.ha_call, controller.ha_set
    monkeypatch.setattr(controller, "ha_call", lambda d, s, **k: (order.append((s, k.get("entity_id"))),
                                                                  real_call(d, s, **k))[1])
    monkeypatch.setattr(controller, "ha_set", lambda e, *a, **k: (order.append(("set", e)), real_set(e, *a, **k))[1])
    _pass(c)
    last_on = max(i for i, step in enumerate(order) if step == ("turn_on", V2))
    assert order.index(("set", RATIO_1)) > last_on


def test_a_meter_that_does_not_read_after_the_shot_reconciles_nothing(rig, fire, monkeypatch):
    c, fake = rig
    fire.discard(2)
    fake.set_state(METER, "100.0", {"unit_of_measurement": "L"})
    _supply(fake, zone_meters={"1": METER})
    real = controller.ha_call

    def ha_call(domain, service, **data):
        if service == "turn_off" and data.get("entity_id") == V1:
            fake.set_state(METER, "unavailable", {"unit_of_measurement": "L"})
        return real(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", ha_call)
    _pass(c)
    done, = _events(c, "shot.completed")
    assert done["outcome"] == "ok" and done["data"]["metered_l"] is None
    assert _events(c, "flow.reconciled") == [] and not _written(fake, RATIO_1)


def test_a_meter_in_unknown_units_is_ignored_and_logged_once(rig, fire, monkeypatch):
    c, fake = rig
    fake.set_state(METER, "100", {"unit_of_measurement": "pulses"})
    _supply(fake, zone_meters={"1": METER})
    _meters_flow(c, fake, monkeypatch, {V1: [METER]}, 0.5)
    lines = []
    monkeypatch.setattr(controller, "log", lambda *a: lines.append(" ".join(map(str, a))))
    for _ in range(3):
        _pass(c)
        fake.set_state(METER, str(float(fake.ha_get(METER)[0]) + 5), {"unit_of_measurement": "pulses"})
    assert len(_events(c, "shot.completed")) == 6
    assert _events(c, "flow.reconciled") == [] and not _written(fake, RATIO_1)
    assert _alerts(fake, "CS-318") == [] and _alerts(fake, "CS-319") == []
    assert len([line for line in lines if METER in line and "pulses" in line]) == 1


# ------------------------------------------------------------------------------------------------ between shots
def test_meter_rise_with_every_valve_shut_raises_cs_319(rig, fire):
    c, fake = rig
    fire.clear()
    fake.set_state(METER, "100.0", {"unit_of_measurement": "L"})
    _supply(fake, zone_meters={"1": METER})
    _pass(c)
    fake.set_state(METER, "100.5", {"unit_of_measurement": "L"})  # 0.5 L is not more than 0.5 L
    _pass(c)
    assert _alerts(fake, "CS-319") == []
    fake.set_state(METER, "100.6", {"unit_of_measurement": "L"})
    _pass(c)
    alert, = _alerts(fake, "CS-319")
    assert METER in alert["message"]
    assert not [d for dom, svc, d in fake.calls if dom == "switch"]  # it only tells
    fake.calls.clear()
    _pass(c)  # the meter stopped: the card goes
    assert [d["notification_id"] for dom, svc, d in fake.calls
            if (dom, svc) == ("persistent_notification", "dismiss")] == [alert["notification_id"]]


def test_a_shots_own_water_is_never_cs_319(rig, fire, monkeypatch):
    c, fake = rig
    fire.discard(2)
    fake.set_state(METER, "100.0", {"unit_of_measurement": "L"})
    fake.set_state(PUMP_METER, "100.0", {"unit_of_measurement": "L"})
    _supply(fake, zone_meters={"1": METER}, pump_meter=PUMP_METER)
    _meters_flow(c, fake, monkeypatch, {V1: [METER, PUMP_METER]}, 1.0)
    _pass(c)  # a baseline, then the shot
    fire.clear()
    for meter in (METER, PUMP_METER):  # the meters report the end of the shot late
        fake.set_state(meter, str(float(fake.ha_get(meter)[0]) + 2), {"unit_of_measurement": "L"})
    _pass(c)
    _pass(c)
    assert _alerts(fake, "CS-319") == []
    fake.set_state(PUMP_METER, str(float(fake.ha_get(PUMP_METER)[0]) + 1), {"unit_of_measurement": "L"})
    _pass(c)
    alert, = _alerts(fake, "CS-319")
    assert PUMP_METER in alert["message"]
