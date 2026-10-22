"""What the controller journals (journal_out.Outbox, Controller._flush_journal): shots, phase changes, holds and
alerts. The journal is never on the watering path (ruling R5): a shot fires exactly as before whatever the
integration does with journal_append, the flush runs once after the pass with a 1 s timeout, and only
shot.started is written (durably) before the pump opens."""
import json
import os
from datetime import datetime, timedelta

import pytest

import controller
import fake_ha
import journal_out
from crop_steering_engine import Reason

pytestmark = pytest.mark.usefixtures("settings_built_in")

KILL = "input_boolean.kill"
PUMP, MAIN, VALVE = "switch.p", "switch.m", "switch.v1"
NOW = datetime(2026, 10, 22, 12, 0)  # lights 10-22: on
TOPUP = "P2 top-up VWC 40.0 < 45.0"


class Clock:
    def __init__(self):
        self.seconds = 1000.0

    def sleep(self, seconds):
        self.seconds += seconds

    def monotonic(self):
        return self.seconds


def _accept(data, timeout):
    return 200, {"accepted": [e["id"] for e in data["events"]], "duplicate": [], "seq_max": 1}


@pytest.fixture
def rig(monkeypatch, tmp_path):
    monkeypatch.setenv("F2_STATE_PATH", str(tmp_path / "state.json"))
    fake = fake_ha.FakeHA()
    fake.responses[("crop_steering", "journal_append")] = _accept
    options = {
        "num_zones": 1,
        "hardware": {"pump": PUMP, "mainline": MAIN, "valves": {"1": VALVE}},
        "enable_flag": KILL,
        "hold_entities": [],
    }
    monkeypatch.setattr(controller, "load_options", lambda: dict(options))
    for name in ("ha_get", "ha_get_status", "ha_call", "ha_get_all", "ha_set", "ha_service_response"):
        monkeypatch.setattr(controller, name, getattr(fake, name))
    for eid in (KILL, "switch.crop_steering_room_active", "switch.crop_steering_zone_1_enabled"):
        fake.set_state(eid, "on")
    for eid in (PUMP, MAIN, VALVE):
        fake.set_state(eid, "off")
    fake.set_state("switch.crop_steering_zone_1_manual_override", "off")
    fake.set_state("sensor.crop_steering_vwc_zone_1", "40")
    fake.set_state("sensor.crop_steering_ec_zone_1", "3")
    clock = Clock()
    monkeypatch.setattr(controller.time, "sleep", clock.sleep)
    monkeypatch.setattr(controller.time, "monotonic", clock.monotonic)
    c = controller.Controller()
    c.rooms[0].state[1]["phase"] = "P2"
    c.rooms[0].state[1]["last_phase_change"] = NOW - timedelta(hours=1)
    return c, fake, clock


@pytest.fixture
def firing(monkeypatch):
    """decide() fires a P2 top-up on every pass (the controller's own gates still apply)."""
    reason = {"value": Reason(TOPUP, kind="p2_topup")}

    def decide(snap, p):
        return snap.phase, p.p2_threshold, True, 2.0, reason["value"]

    monkeypatch.setattr(controller, "decide", decide)
    return reason


def _events(c, kind=None):
    return [e for e in c.journal.pending() if kind is None or e["kind"] == kind]


def _sent(fake):
    """Every event journal_append was sent, in order."""
    return [e for dom, svc, data in fake.calls if svc == "journal_append" for e in data["events"]]


def _switch_calls(fake):
    return [(svc, data["entity_id"]) for dom, svc, data in fake.calls if dom == "switch"]


def _passes(c, n, start=NOW, step_s=60):
    for i in range(n):
        c.loop_once(start + timedelta(seconds=i * step_s))


# ------------------------------------------------------------------------------------- never on the watering path
def test_outbox_never_blocks_a_shot_when_the_integration_refuses(rig, firing):
    c, fake, _clock = rig
    c.loop_once(NOW)
    baseline = _switch_calls(fake)
    assert ("turn_on", VALVE) in baseline  # the pass fired its shot

    c2, fake2, _ = _rebuild(rig, refuse=True)
    c2.loop_once(NOW)
    assert _switch_calls(fake2) == baseline
    assert any(svc == "journal_append" for _d, svc, _x in fake2.calls)  # it was asked, and refused
    assert _events(c2, "shot.started") and _events(c2, "shot.completed")  # kept for the next flush


def _rebuild(rig, refuse=False, handler=None):
    """A second controller on the same fake set-up, with journal_append answered by `handler`."""
    c, fake, clock = rig
    fake.calls.clear()
    for eid in (PUMP, MAIN, VALVE):
        fake.set_state(eid, "off")
    fake.responses[("crop_steering", "journal_append")] = handler or (
        (lambda data, timeout: (400, None)) if refuse else _accept)
    for path in (c.journal.path, c._state_path):  # a clean start, as the first one had
        if os.path.exists(path):
            os.remove(path)
    c2 = controller.Controller()
    c2.rooms[0].state[1]["phase"] = "P2"
    c2.rooms[0].state[1]["last_phase_change"] = NOW - timedelta(hours=1)
    return c2, fake, clock


def test_a_hung_integration_adds_under_1_5_s_to_a_pass(rig, firing):
    c, fake, clock = rig
    before = clock.seconds
    c.loop_once(NOW)
    baseline = clock.seconds - before

    timeouts = []

    def hung(data, timeout):
        timeouts.append(timeout)
        clock.sleep(min(30, timeout))  # a handler that would hang 30 s, cut at the caller's timeout
        return None, None

    c2, _fake, clock = _rebuild(rig, handler=hung)
    before = clock.seconds
    c2.loop_once(NOW)
    assert timeouts == [1]
    assert (clock.seconds - before) - baseline < 1.5


def test_flush_backs_off_for_5_passes_after_a_failure(rig):
    c, fake, _clock = rig
    fake.responses[("crop_steering", "journal_append")] = lambda data, timeout: (500, None)
    c.journal.emit("", "alert.raised", code="CS-207", data={"key": "k", "title": "t"})
    _passes(c, 7)
    appends = [i for i, (_d, svc, _x) in enumerate(fake.calls) if svc == "journal_append"]
    assert len(appends) == 2  # pass 1, then pass 7: passes 2 to 6 skipped
    fake.responses[("crop_steering", "journal_append")] = _accept
    _passes(c, 6, start=NOW + timedelta(minutes=7))  # 5 more skipped, then it goes through
    assert c.journal.pending() == []


def test_no_flush_happens_between_pass_start_and_the_last_shot(rig, firing):
    c, fake, _clock = rig
    c.loop_once(NOW)
    offs = [i for i, (dom, svc, _x) in enumerate(fake.calls) if dom == "switch" and svc == "turn_off"]
    appends = [i for i, (_d, svc, _x) in enumerate(fake.calls) if svc == "journal_append"]
    assert offs and appends
    assert min(appends) > max(offs)
    assert {e["kind"] for e in _sent(fake)} >= {"shot.started", "shot.completed"}
    assert c.journal.pending() == []  # accepted: gone from the outbox


# ------------------------------------------------------------------------------------------------------- shots
def test_shot_started_is_on_disk_before_the_pump_switch_is_called(rig, firing, monkeypatch):
    c, fake, _clock = rig
    synced, seen = [], []
    monkeypatch.setattr(journal_out.os, "fsync", lambda fd: synced.append(fd))
    real_call = controller.ha_call

    def call(domain, service, **data):
        if data.get("entity_id") == PUMP and service == "turn_on":
            with open(c.journal.path, encoding="utf-8") as fh:
                seen.extend(json.loads(line)["kind"] for line in fh if line.strip())
            seen.append(len(synced))
        return real_call(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", call)
    c.loop_once(NOW)
    assert "shot.started" in seen
    assert synced == []  # in the file (flushed), never fsynced on the watering path (ruling R5)


def test_a_completed_shot_carries_verified_readback_litres_and_the_started_intent_id(rig, firing):
    c, fake, _clock = rig
    c.journal.flush = lambda *a, **k: 0  # keep them in the outbox to read
    c.loop_once(NOW)
    started, = _events(c, "shot.started")
    done, = _events(c, "shot.completed")
    assert started["correlation"]["intent_id"] and (
        done["correlation"]["intent_id"] == started["correlation"]["intent_id"])
    assert done["outcome"] == "ok" and done["zone"] == 1 and done["room_id"] == "room:"
    assert done["readback"]["status"] == "verified"
    assert done["readback"]["entities"] == [PUMP, MAIN, VALVE]
    data = done["data"]
    assert data["metered_l"] is None and data["vwc_before"] == 40.0 and data["ec_before"] == 3.0
    assert data["commanded_l"] == pytest.approx(c.rooms[0].state[1]["daily_vol"])
    assert data["elapsed_s"] > 0
    assert started["source"]["client"] == f"f2_control/{controller.CONTROLLER_VERSION}"


@pytest.mark.parametrize("phase, rise", [("P1", 1.5), ("P2", 1.5)])
def test_shot_started_carries_reason_phase_vwc_before_and_expected(rig, firing, phase, rise):
    c, fake, _clock = rig
    c.journal.flush = lambda *a, **k: 0
    st = c.rooms[0].state[1]
    st["phase"], st["p1_expected_rise"] = phase, rise
    if phase == "P1":
        firing["value"] = Reason("P1 ramp shot 2", kind="p1_ramp", cap_exempt=True)
    c.loop_once(NOW)
    started, = _events(c, "shot.started")
    data = started["data"]
    assert data["phase"] == phase and data["vwc_before"] == 40.0
    assert data["vwc_expected"] == (pytest.approx(41.5) if phase == "P1" else None)
    assert data["kind"] == ("p1_ramp" if phase == "P1" else "p2_topup")
    what, why = controller.log_words.shot(firing["value"])
    assert data["reason"] == f"{what}: {why}"
    assert data["pump_wait_s"] == 0
    assert datetime.fromisoformat(data["requested_at"]).tzinfo is not None
    assert data["size_pct"] == 2.0 and data["duration_s"] > 0 and data["commanded_l"] > 0
    assert started["outcome"] == "ok" and started["source"]["actor"] == "engine"


def test_a_valve_that_does_not_open_is_a_failed_shot_with_its_code(rig, monkeypatch):
    c, fake, _clock = rig
    real_call = fake.ha_call

    def call(domain, service, **data):
        if data.get("entity_id") == VALVE and service == "turn_on":
            fake.calls.append((domain, service, data))
            return True  # taken, but it stays off
        return real_call(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", call)
    c._execute_shot(c.rooms[0], 1, 120, 2.0, flow_lps=0.05, reason_text="test")  # a read-back the shot does not cut short
    started, = _events(c, "shot.started")
    ended, = _events(c, "shot.aborted")
    assert ended["outcome"] == "failed" and ended["code"] == "CS-304"
    assert ended["correlation"]["intent_id"] == started["correlation"]["intent_id"]
    assert ended["readback"]["status"] == "off"  # it read back a definite OFF
    assert ended["readback"]["entities"] == [PUMP, MAIN]  # what did read back on
    assert not _events(c, "shot.completed")


def test_an_errored_shot_whose_water_was_counted_is_a_failed_abort_with_its_litres(rig, monkeypatch):
    c, fake, _clock = rig
    room = c.rooms[0]

    def boom(*a, **k):
        raise RuntimeError("wait broke")

    monkeypatch.setattr(c, "_wait_shot", boom)
    c._execute_shot(room, 1, 10, 2.0, flow_lps=0.05)
    ended, = _events(c, "shot.aborted")
    assert ended["outcome"] == "failed"
    assert ended["data"]["commanded_l"] == pytest.approx(room.state[1]["daily_vol"])
    assert room.state[1]["daily_vol"] > 0  # #197: its water still counts
    assert ended["readback"]["status"] == "verified"  # every switch read back on before it broke


def test_a_kill_switch_stop_mid_shot_is_an_aborted_shot(rig, monkeypatch):
    c, fake, clock = rig

    def sleep(dt):
        clock.seconds += dt
        if fake.states[VALVE][0] == "on":
            fake.set_state(KILL, "off")

    monkeypatch.setattr(controller.time, "sleep", sleep)
    c._execute_shot(c.rooms[0], 1, 10, 2.0, flow_lps=0.05)
    ended, = _events(c, "shot.aborted")
    assert ended["outcome"] == "aborted" and ended["code"] == "CS-305"
    assert ended["data"]["commanded_l"] == pytest.approx(c.rooms[0].state[1]["daily_vol"])


# ------------------------------------------------------------------------------------------------------- holds
def test_a_standing_hold_is_journaled_once_per_reason_and_every_30_min(rig, firing):
    c, fake, _clock = rig
    fake.set_state(KILL, "off")
    c.journal.flush = lambda *a, **k: 0
    _passes(c, 40)
    held = _events(c, "intent.held")
    assert len(held) == 2
    assert held[0]["outcome"] == "held" and held[0]["zone"] == 1
    assert held[0]["data"] == {"reason": f"{controller.PRODUCT} disabled (kill switch off)", "would": TOPUP}
    assert not _events(c, "shot.started")
    assert len(c._held_journaled) == 1
    fake.set_state(KILL, "on")  # the hold clears and the zone fires: its key goes
    c.loop_once(NOW + timedelta(hours=1))
    assert _events(c, "shot.started") and c._held_journaled == {}


def test_a_hold_whose_numbers_drift_is_one_hold(rig, firing):
    c, fake, _clock = rig
    c.journal.flush = lambda *a, **k: 0
    room = c.rooms[0]
    room.feed_ec_sensor = "sensor.feed_ec"
    fake.set_state("number.crop_steering_irrigation_ec_min", "1")
    fake.set_state("number.crop_steering_irrigation_ec_max", "2")
    for i in range(40):  # the feed EC drifts each pass, out of its band all along
        fake.set_state("sensor.feed_ec", f"{2.5 + i * 0.1:.1f}", {"unit_of_measurement": "mS/cm"})
        c.loop_once(NOW + timedelta(seconds=30 * i))
    held = _events(c, "intent.held")
    assert len(held) == 1 and held[0]["data"]["reason"].startswith("source-water EC 2.5 out of [1,2]")
    assert len(c._held_journaled) == 1  # the keys do not grow


def test_an_unsized_zone_and_an_unreadable_cap_are_journaled_holds(rig, firing, monkeypatch):
    c, fake, _clock = rig
    c.journal.flush = lambda *a, **k: 0
    monkeypatch.setattr(c, "_zone_flow_lps", lambda room, zone: 0.0)
    c.loop_once(NOW)
    monkeypatch.setattr(c, "_zone_flow_lps", lambda room, zone: 0.05)
    monkeypatch.setattr(c, "_room_duration_cap", lambda room: None)
    c.loop_once(NOW + timedelta(minutes=1))
    held = _events(c, "intent.held")
    assert [(e["code"], e["data"]["would"]) for e in held] == [("CS-204", TOPUP), ("CS-203", TOPUP)]
    assert not _events(c, "shot.started")


def test_a_shot_whose_valve_close_failed_completes_failed_with_its_code(rig, monkeypatch):
    c, fake, _clock = rig
    real_call = fake.ha_call

    def call(domain, service, **data):
        if data.get("entity_id") == VALVE and service == "turn_off":
            return False  # Home Assistant refused the close
        return real_call(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", call)
    c._execute_shot(c.rooms[0], 1, 6, 2.0, flow_lps=0.05)
    done, = _events(c, "shot.completed")
    assert done["outcome"] == "failed" and done["code"] == "CS-301"
    assert done["data"]["commanded_l"] > 0


def test_a_held_journal_that_breaks_never_raises(rig):
    c, _fake, _clock = rig
    room = c.rooms[0]
    c._journal_held(room, 1, "a hold", now=NOW)
    c._journal_held(room, 1, "a hold", now="not a time")  # its own error is logged, never raised


def test_a_pre_open_hold_is_journaled(rig, firing):
    c, fake, _clock = rig
    c.journal.flush = lambda *a, **k: 0
    c.rooms[0].shot_inflight = {"zone": 1, "valve": VALVE, "mainline": MAIN, "pump": PUMP}
    c._execute_shot(c.rooms[0], 1, 10, 2.0, flow_lps=0.05, reason_text=TOPUP)
    held, = _events(c, "intent.held")
    assert held["data"]["reason"] == "an interrupted shot's hardware is not accounted for yet"
    assert held["data"]["would"] == TOPUP
    assert not _events(c, "shot.started")


def test_publishing_waiting_for_journals_nothing(rig):
    c, fake, _clock = rig
    fake.set_state(KILL, "off")
    room = c.rooms[0]
    assert c._blocked(room, 1)
    c._publish_waiting_for(room, 1, None, None, NOW)
    c._publish_room_off(room, NOW)
    assert c.journal.pending() == []


# ------------------------------------------------------------------------------------- rooms, phases and alerts
def test_room_id_comes_from_the_prefix_not_the_slug(rig):
    c, fake, _clock = rig
    room = controller.Room("f2", "f2_", {1: {}},
                           {"pump": None, "mainline": None, "valves": {1: "switch.f2_v1"}},
                           "input_boolean.f2", "", "", 10, 22)
    c.rooms.append(room)
    c._load_room_state(room, {})
    for eid in ("input_boolean.f2", "switch.crop_steering_f2_room_active", "switch.crop_steering_f2_zone_1_enabled"):
        fake.set_state(eid, "on")
    fake.set_state("switch.f2_v1", "off")
    c._execute_shot(room, 1, 6, 2.0, flow_lps=0.05)
    c._alert("probe_f2_z1", "CS-101", "probe offline", "x", room=room, zone=1, entity_id="sensor.f2_vwc_1")
    events = c.journal.pending()
    assert {e["kind"] for e in events} >= {"shot.started", "shot.completed", "alert.raised"}
    assert {e["room_id"] for e in events} == {"room:f2_"}


def test_phase_change_and_alert_are_journaled(rig):
    c, fake, _clock = rig
    room = c.rooms[0]
    st = room.state[1]
    st["phase"] = "P0"
    c._change_phase(room, 1, st, "P1", "lights-on", NOW)
    # the operator's Set Phase journals too
    fake.set_state("select.crop_steering_zone_1_set_phase", "P2")
    c._apply_phase_request(room, 1, st, NOW)
    changed = _events(c, "phase.changed")
    assert [e["data"] for e in changed] == [
        {"from": "P0", "to": "P1", "how": "lights-on"},
        {"from": "P1", "to": "P2", "how": "set by hand"},
    ]
    assert [e["source"]["actor"] for e in changed] == ["engine", "manual"]

    assert c._alert("wd_default_z1", "CS-207", "dry", "msg", room=room, zone=1)
    assert not c._alert("wd_default_z1", "CS-207", "dry", "msg", room=room, zone=1)  # quiet: not due again
    raised = _events(c, "alert.raised")
    assert len(raised) == 1
    assert raised[0]["code"] == "CS-207" and raised[0]["zone"] == 1 and raised[0]["source"]["actor"] == "engine"
    assert raised[0]["data"]["key"] == "wd_default_z1" and "dry" in raised[0]["data"]["title"]
    assert "entity_id" not in raised[0]["data"]
    c._dismiss("wd_default_z1")
    c._dismiss("wd_default_z1")  # already down: nothing more
    cleared = _events(c, "alert.cleared")
    assert [(e["room_id"], e["data"]) for e in cleared] == [("room:", {"key": "wd_default_z1"})]


def test_a_cancelled_shot_alert_names_its_switch(rig, monkeypatch):
    c, fake, _clock = rig
    real_call = fake.ha_call

    def call(domain, service, **data):
        if data.get("entity_id") == PUMP and service == "turn_on":
            return True  # taken, stays off
        return real_call(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", call)
    c._execute_shot(c.rooms[0], 1, 10, 2.0, flow_lps=0.05)
    raised, = _events(c, "alert.raised")
    assert raised["code"] == "CS-302" and raised["data"]["entity_id"] == PUMP


def test_old_state_file_without_outbox_still_loads(rig):
    c, _fake, _clock = rig
    assert not os.path.exists(c.journal.path)
    assert os.path.dirname(c.journal.path) == os.path.dirname(c._state_path)
    assert c.journal.pending() == []
    c.loop_once(NOW)  # nothing to flush: nothing sent
