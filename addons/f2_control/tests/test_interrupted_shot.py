"""A shot that never finished: the controller crashed, was stopped, or lost Home Assistant mid-shot.

It writes down what a shot is about to open before opening it, and at the next loop closes exactly that,
and nothing a person is using: the tank is circulated for well over 20 minutes to heat it, and zones are
hand-watered with the valves and main line open, so nothing is ever switched off on a timer or on
suspicion. Also: alerts are only quiet once Home Assistant has them, a late OFF report during an error
cleanup is not a stuck pump, and stopping the app mid-shot still counts the water given."""
import json
from datetime import datetime, timedelta, timezone

import pytest

import controller
import fake_ha

STARTED = datetime(2026, 9, 23, 1, 0, tzinfo=timezone.utc)
RECORD = {"zone": 1, "valve": "switch.v1", "mainline": "switch.m", "pump": "switch.p",
          "started": STARTED.isoformat()}


class Clock:
    def __init__(self):
        self.seconds = 0.0

    def sleep(self, seconds):
        self.seconds += seconds

    def monotonic(self):
        return self.seconds


@pytest.fixture
def rig(monkeypatch, tmp_path):
    fake = fake_ha.FakeHA()
    options = {
        "num_zones": 2,
        "hardware": {"pump": "switch.p", "mainline": "switch.m",
                     "valves": {"1": "switch.v1", "2": "switch.v2"}},
        "enable_flag": "input_boolean.kill",
    }
    monkeypatch.setattr(controller, "load_options", lambda: options)
    for name in ("ha_get", "ha_call", "ha_get_all", "ha_set", "ha_history"):
        monkeypatch.setattr(controller, name, getattr(fake, name))
    with monkeypatch.context() as setup:
        setup.setattr(controller.Controller, "_read_state_file", lambda self: {})
        c = controller.Controller()
    c._state_path = str(tmp_path / "state.json")
    for eid in ("input_boolean.kill", "switch.crop_steering_system_enabled",
                "switch.crop_steering_auto_irrigation_enabled",
                "switch.crop_steering_zone_1_enabled", "switch.crop_steering_zone_2_enabled"):
        fake.set_state(eid, "on")
    for eid in ("switch.p", "switch.m", "switch.v1", "switch.v2"):
        fake.set_state(eid, "off")
    clock = Clock()
    monkeypatch.setattr(controller.time, "sleep", clock.sleep)
    monkeypatch.setattr(controller.time, "monotonic", clock.monotonic)
    return c, fake, clock


def at(seconds):
    return (STARTED + timedelta(seconds=seconds)).isoformat()


def crashed(c, fake, pump=0, main=2, valve=3):
    """The state file holds an interrupted shot; its switches went ON `pump`/`main`/`valve` s after it started."""
    c.rooms[0].shot_inflight = dict(RECORD)
    c._save_state()
    fake.set_state("switch.p", "on", last_updated=at(pump))
    fake.set_state("switch.m", "on", last_updated=at(main))
    fake.set_state("switch.v1", "on", last_updated=at(valve))
    c._load_state()  # what the restarted controller reads back
    fake.calls.clear()
    return c.rooms[0]


def offs(fake):
    return [d["entity_id"] for dom, svc, d in fake.calls if dom == "switch" and svc == "turn_off"]


def saved(c):
    with open(c._state_path) as fh:
        return json.load(fh)


def notifications(fake):
    return [d for dom, svc, d in fake.calls if (dom, svc) == ("persistent_notification", "create")]


# ---------------------------------------------------------------------------
# The write-ahead record
# ---------------------------------------------------------------------------
def test_a_shot_is_written_down_before_anything_opens_and_cleared_once_closed(rig, monkeypatch):
    c, fake, _ = rig
    on_disk = []
    real = controller.ha_call

    def call(domain, service, **data):
        if domain == "switch" and service == "turn_on" and not on_disk:
            on_disk.append(saved(c)["default"].get("_shot_inflight"))
        return real(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", call)
    c._execute_shot(c.rooms[0], 1, 6, 5)
    record = on_disk[0]
    assert (record["zone"], record["valve"], record["mainline"], record["pump"]) == (1, "switch.v1", "switch.m", "switch.p")
    assert controller._aware(record["started"]) is not None
    assert c.rooms[0].shot_inflight is None and "_shot_inflight" not in saved(c)["default"]


def test_a_close_that_is_not_confirmed_keeps_the_record(rig, monkeypatch):
    c, fake, _ = rig
    real = controller.ha_call

    def stuck(domain, service, **data):
        if service == "turn_off" and data.get("entity_id") == "switch.v1":
            fake.calls.append((domain, service, data))
            return True  # accepted; the valve never reports OFF
        return real(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", stuck)
    c._execute_shot(c.rooms[0], 1, 6, 5)
    assert c.rooms[0].hardware_fault is not None
    assert saved(c)["default"]["_shot_inflight"]["valve"] == "switch.v1"


def test_an_old_state_file_loads_and_a_damaged_record_is_ignored(rig):
    c, _, _ = rig
    with open(c._state_path, "w") as fh:
        json.dump({"default": {"1": {"daily_vol": 4}}}, fh)
    c._load_state()
    assert c.rooms[0].shot_inflight is None and c.rooms[0].state[1]["daily_vol"] == 4
    for damaged in ("junk", {"zone": "1", "valve": "switch.v1", "started": STARTED.isoformat()},
                    {"zone": 1, "started": STARTED.isoformat()}, {"zone": 1, "valve": "switch.v1"}):
        with open(c._state_path, "w") as fh:
            json.dump({"default": {"1": {"daily_vol": 4}, "_shot_inflight": damaged}}, fh)
        c._load_state()
        assert c.rooms[0].shot_inflight is None and c.rooms[0].state[1]["daily_vol"] == 4


# ---------------------------------------------------------------------------
# Closing what the interrupted shot opened, and nothing else
# ---------------------------------------------------------------------------
def test_after_a_crash_mid_shot_the_next_loop_closes_what_that_shot_opened(rig):
    c, fake, _ = rig
    crashed(c, fake)
    fake.set_state("switch.crop_steering_system_enabled", "off")  # nothing else may fire in this loop
    c.loop_once(datetime(2026, 9, 23, 12, 0))
    assert offs(fake) == ["switch.v1", "switch.m", "switch.p"]  # the valve first, then back up the line
    assert c.rooms[0].shot_inflight is None and c.rooms[0].hardware_fault is None
    assert "_shot_inflight" not in saved(c)["default"]


def test_a_new_shot_waits_while_an_interrupted_one_is_unsettled(rig):
    c, fake, _ = rig
    crashed(c, fake)
    fake.calls.clear()
    c._execute_shot(c.rooms[0], 2, 6, 5)
    assert not any(dom == "switch" for dom, _svc, _d in fake.calls)


def test_a_valve_a_person_has_switched_since_is_theirs_with_everything_upstream(rig):
    c, fake, _ = rig
    crashed(c, fake, valve=600)  # switched again ten minutes in: somebody is hand-watering this zone
    c._reconcile_inflight()
    assert offs(fake) == []
    assert c.rooms[0].shot_inflight is None  # handed over, and written down as settled


def restarted(fake, back_at=900, gap=True):
    """Home Assistant restarted `back_at` s into the shot. Every switch stayed ON and reads ON with that
    change time; the recorder shows it ON since the shot opened it (with `unavailable` while it was down)."""
    for eid, opened in (("switch.p", 0), ("switch.m", 2), ("switch.v1", 3)):
        rows = [("off", at(-3600)), ("on", at(opened))]
        if gap:
            rows.append(("unavailable", at(back_at - 30)))
        rows.append(("on", at(back_at)))
        fake.history[eid] = rows
        fake.changed[eid] = at(back_at)


def test_a_home_assistant_restart_mid_shot_does_not_hand_the_shot_to_a_person(rig):
    # The valve stayed open through the restart; only its change time moved. Before this it was taken
    # for a person's and left running, and the record was closed without a word.
    c, fake, _ = rig
    crashed(c, fake)
    restarted(fake)
    c._reconcile_inflight()
    assert offs(fake) == ["switch.v1", "switch.m", "switch.p"]
    assert c.rooms[0].shot_inflight is None and notifications(fake) == []


def test_a_switch_that_reconnected_without_reading_unavailable_is_still_the_shots(rig):
    c, fake, _ = rig
    crashed(c, fake)
    restarted(fake, gap=False)
    c._reconcile_inflight()
    assert offs(fake) == ["switch.v1", "switch.m", "switch.p"]


def test_after_a_restart_a_valve_a_person_turned_off_and_on_again_is_theirs(rig):
    c, fake, _ = rig
    crashed(c, fake)
    restarted(fake)
    fake.history["switch.v1"][2:2] = [("off", at(120)), ("on", at(400))]  # hand-watering since
    c._reconcile_inflight()
    assert offs(fake) == [] and c.rooms[0].shot_inflight is None


def test_after_a_restart_with_no_history_nothing_is_switched_and_it_is_said_so(rig):
    c, fake, _ = rig
    crashed(c, fake)
    restarted(fake)
    fake.history["switch.v1"] = None  # the recorder excludes it, or has not started yet
    c._reconcile_inflight()
    assert offs(fake) == [] and c.rooms[0].shot_inflight is not None  # checked again next loop
    (alert,) = [n for n in notifications(fake) if n["notification_id"] == "f2_inflight_default"]
    assert alert["title"] == "Zone 1: an interrupted shot's hardware may still be ON (CS-309)"
    assert "Can't be read: switch.v1" in alert["message"]


def test_the_recorder_is_read_the_way_a_person_would():
    on_since = controller._on_since_shot
    assert on_since([("off", at(-60)), ("on", at(2)), ("unavailable", at(500)), ("on", at(520))], STARTED)
    assert on_since([("on", at(-1800))], STARTED) is False  # already on before the shot
    assert on_since([("off", at(-60)), ("on", at(700))], STARTED) is False  # first on after it
    assert on_since([("off", at(-60)), ("on", at(2)), ("off", at(90)), ("on", at(95))], STARTED) is False
    assert on_since(None, STARTED) is None
    assert on_since([("off", at(-60))], STARTED) is None  # never seen on: can't tell
    assert on_since([("on", "garbage")], STARTED) is None


def test_a_pump_that_was_already_running_for_the_tank_is_left_running(rig):
    c, fake, _ = rig
    crashed(c, fake, pump=-1800)  # circulating to heat the tank since half an hour before the shot
    c._reconcile_inflight()
    assert offs(fake) == ["switch.v1", "switch.m"]
    assert fake.states["switch.p"][0] == "on" and c.rooms[0].shot_inflight is None


def test_the_pump_is_never_touched_while_a_hold_is_on(rig):
    c, fake, _ = rig
    c.hold_entities = ["input_boolean.tank_circulation"]
    fake.set_state("input_boolean.tank_circulation", "on")
    crashed(c, fake)
    c._reconcile_inflight()
    assert offs(fake) == ["switch.v1", "switch.m"] and fake.states["switch.p"][0] == "on"


def test_the_line_is_left_alone_while_another_valve_on_it_is_open(rig):
    c, fake, _ = rig
    crashed(c, fake)
    fake.set_state("switch.v2", "on", last_updated=at(900))  # somebody watering zone 2 by hand
    fake.calls.clear()
    c._reconcile_inflight()
    assert offs(fake) == ["switch.v1"]
    assert fake.states["switch.m"][0] == "on" and fake.states["switch.p"][0] == "on"


def test_with_the_kill_switch_off_the_operator_has_it_and_nothing_is_touched(rig):
    c, fake, _ = rig
    crashed(c, fake)
    fake.set_state("input_boolean.kill", "off")
    c._reconcile_inflight()
    assert offs(fake) == [] and c.rooms[0].shot_inflight is not None
    fake.set_state("input_boolean.kill", "on")
    c._reconcile_inflight()
    assert offs(fake) == ["switch.v1", "switch.m", "switch.p"] and c.rooms[0].shot_inflight is None


def test_a_record_whose_switches_all_read_off_is_simply_closed(rig):
    c, fake, _ = rig
    crashed(c, fake)
    for eid in ("switch.v1", "switch.m", "switch.p"):
        fake.set_state(eid, "off")
    fake.set_state("input_boolean.kill", "off")  # even with the operator in charge: nothing to touch
    fake.calls.clear()
    c._reconcile_inflight()
    assert offs(fake) == [] and c.rooms[0].shot_inflight is None


def test_a_switch_that_will_not_close_latches_the_hold_and_is_retried_every_loop(rig, monkeypatch):
    c, fake, _ = rig
    crashed(c, fake)
    real = controller.ha_call

    def stuck(domain, service, **data):
        if service == "turn_off" and data.get("entity_id") == "switch.v1":
            fake.calls.append((domain, service, data))
            return True
        return real(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", stuck)
    c._reconcile_inflight()
    room = c.rooms[0]
    assert room.hardware_fault is not None and room.shot_inflight is not None
    assert "Zone 1: CRITICAL, an interrupted shot's hardware is still ON (CS-308)" in [
        n["title"] for n in notifications(fake)
    ]
    c._reconcile_inflight()
    assert offs(fake).count("switch.v1") == 2  # tried again on the next loop


def test_a_switch_that_cannot_be_read_is_left_alone_and_said_so_with_its_code(rig):
    c, fake, _ = rig
    crashed(c, fake)
    fake.set_state("switch.v1", "unavailable")  # whose it is now cannot be told
    c._reconcile_inflight()
    assert offs(fake) == []
    (alert,) = [n for n in notifications(fake) if n["notification_id"] == "f2_inflight_default"]
    assert alert["title"] == "Zone 1: an interrupted shot's hardware may still be ON (CS-309)"
    assert "Can't be read: switch.v1" in alert["message"]


def test_without_a_record_a_latched_hold_switches_nothing_off(rig):
    # Staff hand-water with the valves and main line open: only what a recorded shot opened is closed.
    c, fake, _ = rig
    c.rooms[0].hardware_fault = {"reason": "zone 1 valve/pump/mainline close not confirmed",
                                 "entities": ["switch.m", "switch.p", "switch.v1", "switch.v2"]}
    for eid in ("switch.p", "switch.m", "switch.v2"):
        fake.set_state(eid, "on")
    fake.set_state("switch.crop_steering_system_enabled", "off")
    c.loop_once(datetime(2026, 9, 23, 12, 0))
    assert offs(fake) == []


# ---------------------------------------------------------------------------
# Alerts, error cleanup, stopping mid-shot
# ---------------------------------------------------------------------------
def test_an_alert_home_assistant_did_not_take_is_raised_again_and_only_then_goes_quiet(rig, monkeypatch):
    c, fake, _ = rig
    c.notify_service = "notify/phone"
    up = {"ok": False}
    real = controller.ha_call

    def call(domain, service, **data):
        if domain == "persistent_notification" and not up["ok"]:
            fake.calls.append((domain, service, data))
            return False
        return real(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", call)

    def pushes():
        return [d for dom, _svc, d in fake.calls if dom == "notify"]

    c._alert("valve_stuck", "CS-301", "CRITICAL", "valve stuck")
    assert "valve_stuck" not in c._alerted and pushes() == []  # no push without the notification
    up["ok"] = True
    c._alert("valve_stuck", "CS-301", "CRITICAL", "valve stuck")
    assert "valve_stuck" in c._alerted and len(pushes()) == 1
    c._alert("valve_stuck", "CS-301", "CRITICAL", "valve stuck")
    assert len(notifications(fake)) == 2 and len(pushes()) == 1  # quiet only after it landed


def test_a_hold_latched_while_home_assistant_was_away_is_announced_once_it_is_back(rig, monkeypatch):
    c, fake, _ = rig
    fake.set_state("switch.crop_steering_system_enabled", "off")  # nothing may fire in these loops
    up = {"ok": False}
    real = controller.ha_call

    def call(domain, service, **data):
        if not up["ok"] and domain in ("persistent_notification", "switch"):
            fake.calls.append((domain, service, data))
            return False  # Home Assistant unreachable
        return real(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", call)
    c._latch_hardware_fault(c.rooms[0], "zone 1 valve/pump/mainline close not confirmed")
    up["ok"] = True
    fake.calls.clear()
    c.loop_once(datetime(2026, 9, 23, 12, 0))
    c.loop_once(datetime(2026, 9, 23, 12, 1))
    latched = [n for n in notifications(fake) if n["title"].endswith("CRITICAL hardware fault, watering stopped (CS-301)")]
    assert len(latched) == 1  # said once it could be heard, and not again every loop


def slow_report(monkeypatch, fake, clock, entity, lag_s):
    """A Zigbee plug: turn_off is accepted at once, Home Assistant shows OFF `lag_s` later."""
    due = {}
    real_call, real_get = controller.ha_call, controller.ha_get

    def call(domain, service, **data):
        if data.get("entity_id") == entity and service == "turn_off":
            fake.calls.append((domain, service, data))
            due["at"] = clock.seconds + lag_s
            return True
        return real_call(domain, service, **data)

    def get(eid, timeout=8):
        if eid == entity and "at" in due and clock.seconds >= due["at"]:
            fake.set_state(entity, "off")
        return real_get(eid, timeout=timeout)

    monkeypatch.setattr(controller, "ha_call", call)
    monkeypatch.setattr(controller, "ha_get", get)
    return call


def test_15_sep_a_late_off_report_during_an_error_cleanup_is_not_a_stuck_pump(rig, monkeypatch):
    c, fake, clock = rig
    slow = slow_report(monkeypatch, fake, clock, "switch.p", 1.6)

    def mainline_fails(domain, service, **data):
        if data.get("entity_id") == "switch.m" and service == "turn_on":
            return False
        return slow(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", mainline_fails)
    c._execute_shot(c.rooms[0], 1, 60, 5)
    assert c.rooms[0].hardware_fault is None and c.rooms[0].shot_inflight is None
    assert c.rooms[0].state[1]["shots"] == 0  # no water went in, none is counted


def test_a_pump_that_never_reports_off_in_an_error_cleanup_still_latches(rig, monkeypatch):
    c, fake, clock = rig
    slow = slow_report(monkeypatch, fake, clock, "switch.p", 3600)

    def mainline_fails(domain, service, **data):
        if data.get("entity_id") == "switch.m" and service == "turn_on":
            return False
        return slow(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", mainline_fails)
    c._execute_shot(c.rooms[0], 1, 60, 5)
    assert c.rooms[0].hardware_fault is not None and c.rooms[0].shot_inflight is not None


def counted_for_30_s(litres, flow=0.05):
    """30 s of water went in before the stop. Like a normal close, the count runs to the end of the close
    (valve, then the line, then the read-back), so it may be a little over, never under."""
    return flow * 30 <= litres <= flow * (30 + 1 + controller.CONFIRM_TIMEOUT_S)


def stopped_after(c, clock, seconds):
    """A _wait_shot the app is stopped in: SIGTERM runs _safe_exit, which ends in SystemExit."""
    def wait(room, zone, duration_s, started=None):
        clock.sleep(seconds)
        c._safe_exit()
    return wait


def test_stopping_the_app_mid_shot_closes_that_shot_and_counts_the_water_already_given(rig, monkeypatch):
    c, fake, clock = rig
    slow_report(monkeypatch, fake, clock, "switch.p", 1.6)
    monkeypatch.setattr(c, "_wait_shot", stopped_after(c, clock, 30))
    with pytest.raises(SystemExit):
        c._execute_shot(c.rooms[0], 1, 300, 5, flow_lps=0.05)
    assert offs(fake) == ["switch.v1", "switch.m", "switch.p"]  # that shot's own, valve first, once each
    assert {e: fake.states[e][0] for e in ("switch.v1", "switch.m", "switch.p")} == dict.fromkeys(
        ("switch.v1", "switch.m", "switch.p"), "off")
    st = c.rooms[0].state[1]
    assert counted_for_30_s(st["daily_vol"]) and st["shots"] == 1
    assert c.rooms[0].hardware_fault is None and c.rooms[0].shot_inflight is None
    on_disk = saved(c)["default"]
    assert counted_for_30_s(on_disk["1"]["daily_vol"]) and "_shot_inflight" not in on_disk


def test_stopping_the_app_with_no_shot_in_flight_switches_nothing_off(rig):
    # The tank circulating to heat: pump and manifold relay ON, and no shot of the controller's running.
    c, fake, _ = rig
    fake.set_state("switch.p", "on")
    fake.set_state("switch.tank_manifold", "on")
    c.rooms[0].state[1]["daily_vol"] = 7.5
    with pytest.raises(SystemExit):
        c._safe_exit()
    assert offs(fake) == []
    assert fake.states["switch.p"][0] == "on" and fake.states["switch.tank_manifold"][0] == "on"
    assert saved(c)["default"]["1"]["daily_vol"] == 7.5  # state is still saved on the way out


def test_stopping_the_app_mid_shot_leaves_the_pump_to_a_hold_that_came_on_meanwhile(rig, monkeypatch):
    c, fake, clock = rig
    c.hold_entities = ["input_boolean.tank_circulation"]

    def circulation_starts_then_stop(room, zone, duration_s, started=None):
        fake.set_state("input_boolean.tank_circulation", "on")  # somebody starts heating the tank
        clock.sleep(30)
        c._safe_exit()

    monkeypatch.setattr(c, "_wait_shot", circulation_starts_then_stop)
    with pytest.raises(SystemExit):
        c._execute_shot(c.rooms[0], 1, 300, 5, flow_lps=0.05)
    assert offs(fake) == ["switch.v1", "switch.m"] and fake.states["switch.p"][0] == "on"
    assert counted_for_30_s(c.rooms[0].state[1]["daily_vol"])
    assert "_shot_inflight" not in saved(c)["default"]  # settled: the pump is the circulation's now


def test_stopping_the_app_right_after_the_kill_switch_went_off_still_closes_the_shot_running(rig, monkeypatch):
    # The operator hits the kill switch and stops the app a moment later, before the shot saw the switch.
    c, fake, clock = rig

    def killed_then_stopped(room, zone, duration_s, started=None):
        fake.set_state("input_boolean.kill", "off")
        clock.sleep(10)
        c._safe_exit()

    monkeypatch.setattr(c, "_wait_shot", killed_then_stopped)
    with pytest.raises(SystemExit):
        c._execute_shot(c.rooms[0], 1, 300, 5, flow_lps=0.05)
    assert offs(fake) == ["switch.v1", "switch.m", "switch.p"]  # this process's own shot: closed
    assert "_shot_inflight" not in saved(c)["default"]


def test_stopping_the_app_leaves_an_older_interrupted_shot_to_the_operator(rig):
    c, fake, _ = rig
    crashed(c, fake)
    fake.set_state("input_boolean.kill", "off")  # the operator has taken over
    with pytest.raises(SystemExit):
        c._safe_exit()
    assert offs(fake) == [] and saved(c)["default"]["_shot_inflight"]["valve"] == "switch.v1"
