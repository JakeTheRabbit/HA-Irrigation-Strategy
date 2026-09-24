"""A shot that something else cuts short: a hold comes on, or the zone's valve is switched off.

23 Sep 2026, 11:25:22 NZST: the controller fired a Z1 P1 ramp shot (2.8 %, ~170 s): pump, main line,
then the valve at 11:25:25. At 11:25:29 the batch tank ran empty. the room's dosing automation turned on
input_boolean.nutrient_dosing_active (one of the controller's holds) and switched the pump off, and
his dose guard closed the valve and the main line. The controller did not notice. It waited out the
170 s, ran its close sequence and counted about 7.9 L for about 0.2 L delivered. Had the next dosing
step started the pump to mix inside that window, the end-of-shot close would have stopped it mid-dose.

Now the shot ends at the next check (about every 2 s) once a hold reads ON or the shot's own valve
reads OFF. Only the time the valve was open is counted. Only what is still the shot's is closed, never
a pump a hold now owns, and nothing is re-toggled or read back that somebody else already closed, so
there is no hardware hold for it. Nothing is ever switched off on a timer.
"""
import json
from datetime import datetime, timedelta

import pytest

import controller
import fake_ha

HOLD = "input_boolean.nutrient_dosing_active"
KILL = "input_boolean.kill"
PUMP, MAIN, VALVE = "switch.p", "switch.m", "switch.v1"
FLOW = 7.9 / 170  # L/s: on the day, the full 170 s were counted as about 7.9 L
CUT = "Shot cut short — feed path closed externally"


class Clock:
    """The controller's monotonic clock and sleep. `at(t, action)` runs `action` once the clock reaches t,
    the way Home Assistant automations act while the controller sleeps between its checks."""

    def __init__(self):
        self.seconds = 0.0
        self.due = []

    def at(self, seconds, action):
        self.due.append((seconds, action))
        self.due.sort(key=lambda item: item[0])

    def sleep(self, seconds):
        end = self.seconds + seconds
        while self.due and self.due[0][0] <= end:
            when, action = self.due.pop(0)
            self.seconds = max(self.seconds, when)
            action()
        self.seconds = end

    def monotonic(self):
        return self.seconds


@pytest.fixture
def rig(monkeypatch, tmp_path):
    fake = fake_ha.FakeHA()
    options = {
        "num_zones": 2,
        "hardware": {"pump": PUMP, "mainline": MAIN, "valves": {"1": VALVE, "2": "switch.v2"}},
        "enable_flag": KILL,
        "hold_entities": [HOLD],
    }
    monkeypatch.setattr(controller, "load_options", lambda: options)
    for name in ("ha_get", "ha_call", "ha_get_all", "ha_set"):
        monkeypatch.setattr(controller, name, getattr(fake, name))
    with monkeypatch.context() as setup:
        setup.setattr(controller.Controller, "_read_state_file", lambda self: {})
        c = controller.Controller()
    c._state_path = str(tmp_path / "state.json")
    for eid in (KILL, "switch.crop_steering_system_enabled",
                "switch.crop_steering_auto_irrigation_enabled",
                "switch.crop_steering_zone_1_enabled", "switch.crop_steering_zone_2_enabled"):
        fake.set_state(eid, "on")
    for eid in (PUMP, MAIN, VALVE, "switch.v2", HOLD):
        fake.set_state(eid, "off")
    clock = Clock()
    monkeypatch.setattr(controller.time, "sleep", clock.sleep)
    monkeypatch.setattr(controller.time, "monotonic", clock.monotonic)
    return c, fake, clock


def after_the_valve_opens(monkeypatch, fake, clock, *events):
    """Each (seconds, action) runs `seconds` after the controller switches the valve ON. `action(at)` gets
    at(s): the time Home Assistant records for a change s seconds after the valve came on. Returns where
    the valve's opening lands on the clock, once it has."""
    opened = {}
    real = controller.ha_call

    def call(domain, service, **data):
        ok = real(domain, service, **data)
        if (service, data.get("entity_id")) == ("turn_on", VALVE):
            opened["clock"] = clock.seconds
            on = datetime.fromisoformat(fake.changed[VALVE])

            def at(seconds):
                return (on + timedelta(seconds=seconds)).isoformat()

            for seconds, action in events:
                clock.at(clock.seconds + seconds, lambda action=action: action(at))
        return ok

    monkeypatch.setattr(controller, "ha_call", call)
    return opened


def switched(fake):
    return [(svc, d["entity_id"]) for dom, svc, d in fake.calls if dom == "switch"]


def offs(fake):
    return [eid for svc, eid in switched(fake) if svc == "turn_off"]


def notifications(fake):
    return [d for dom, svc, d in fake.calls if (dom, svc) == ("persistent_notification", "create")]


def saved(c):
    with open(c._state_path) as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# 23 Sep 11:25, replayed from the recorder (offsets from the valve's ON at 11:25:25.377)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("mixing", [False, True], ids=["as-on-the-day", "dose-mixes-inside-the-shot"])
def test_23_sep_the_tank_ran_empty_4_s_into_a_170_s_shot(rig, monkeypatch, mixing):
    c, fake, clock = rig

    def tank_runs_empty(at):
        fake.set_state(HOLD, "on", last_updated=at(4.065))  # the dosing automation takes the tank...
        fake.set_state(PUMP, "off", last_updated=at(4.117))  # ...and its pump
        fake.set_state(VALVE, "off", last_updated=at(4.187))  # the dose guard closes the feed path
        fake.set_state(MAIN, "off", last_updated=at(4.188))

    events = [(4.19, tank_runs_empty)]
    if mixing:  # the next dosing step runs the pump to mix, before the controller has closed up
        events.append((5.0, lambda at: fake.set_state(PUMP, "on", last_updated=at(5.0))))
    opened = after_the_valve_opens(monkeypatch, fake, clock, *events)
    c._execute_shot(c.rooms[0], 1, 170, 2.8, flow_lps=FLOW)

    room, st = c.rooms[0], c.rooms[0].state[1]
    assert clock.seconds - opened["clock"] <= 4.19 + 2  # ended at the next check, not after 170 s
    # Nothing re-toggled: the valve and main line were already closed, the pump is the dose's.
    assert switched(fake) == [("turn_on", PUMP), ("turn_on", MAIN), ("turn_on", VALVE)]
    assert fake.states[PUMP][0] == ("on" if mixing else "off")
    # The valve's own change time says it closed 4.187 s in: about 0.19 L, not 7.9 L.
    assert st["daily_vol"] == pytest.approx(FLOW * 4.187, rel=1e-3) and st["shots"] == 1
    assert room.hardware_fault is None
    assert room.shot_inflight is None and "_shot_inflight" not in saved(c)["default"]
    alerts = notifications(fake)
    assert [n["title"] for n in alerts] == [CUT]
    assert HOLD in alerts[0]["message"] and "after 4 of 170 s" in alerts[0]["message"]


# ---------------------------------------------------------------------------
# The valve switched off by something else, with no hold on
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("stamped", [True, False], ids=["change-time-read", "no-change-time"])
def test_a_valve_switched_off_by_something_else_counts_only_the_time_it_was_open(rig, monkeypatch, stamped):
    c, fake, clock = rig

    def somebody_closes_the_valve(at):
        fake.set_state(VALVE, "off", last_updated=at(30.4))
        if not stamped:
            del fake.changed[VALVE]  # no usable change time: count to when the controller saw it

    after_the_valve_opens(monkeypatch, fake, clock, (30.4, somebody_closes_the_valve))
    c._execute_shot(c.rooms[0], 1, 120, 5, flow_lps=FLOW)

    room, st = c.rooms[0], c.rooms[0].state[1]
    counted = 30.4 if stamped else 32  # else the first check after it (every 2 s: 30, then 32)
    assert st["daily_vol"] == pytest.approx(FLOW * counted, rel=1e-3) and st["shots"] == 1
    assert offs(fake) == [MAIN, PUMP]  # the shot's main line and pump; its valve is not switched again
    assert room.hardware_fault is None and room.shot_inflight is None
    alerts = notifications(fake)
    assert [n["title"] for n in alerts] == [CUT]
    assert VALVE in alerts[0]["message"] and f"after {counted:.0f} of 120 s" in alerts[0]["message"]


# ---------------------------------------------------------------------------
# A hold that comes on while the valve is still open
# ---------------------------------------------------------------------------
def test_a_hold_that_comes_on_mid_shot_closes_valve_and_main_line_and_leaves_the_pump(rig, monkeypatch):
    c, fake, clock = rig
    # Dosing takes the tank and keeps its pump running; nothing has closed the feed path yet.
    after_the_valve_opens(monkeypatch, fake, clock,
                          (10.5, lambda at: fake.set_state(HOLD, "on", last_updated=at(10.5))))
    c._execute_shot(c.rooms[0], 1, 170, 2.8, flow_lps=FLOW)

    room, st = c.rooms[0], c.rooms[0].state[1]
    assert offs(fake) == [VALVE, MAIN]  # the shot's own, valve first
    assert fake.states[PUMP][0] == "on"  # the dose's now: never switched off, never read back
    assert room.hardware_fault is None and room.shot_inflight is None
    # Still open when the hold was seen at the 12 s check: its change time is when it opened, not a close.
    assert st["daily_vol"] == pytest.approx(FLOW * 12) and st["shots"] == 1
    alerts = notifications(fake)
    assert [n["title"] for n in alerts] == [CUT]
    assert HOLD in alerts[0]["message"] and "after 12 of 170 s" in alerts[0]["message"]
    assert f"Left {PUMP} on" in alerts[0]["message"]


def test_one_alert_per_zone_per_half_hour_however_often_it_happens(rig, monkeypatch):
    c, fake, clock = rig
    after_the_valve_opens(monkeypatch, fake, clock,
                          (8, lambda at: fake.set_state(VALVE, "off", last_updated=at(8))))
    c._execute_shot(c.rooms[0], 1, 60, 5, flow_lps=FLOW)
    c._execute_shot(c.rooms[0], 1, 60, 5, flow_lps=FLOW)
    assert [n["title"] for n in notifications(fake)] == [CUT]  # the usual 30-minute quiet period
    assert c.rooms[0].state[1]["daily_vol"] == pytest.approx(FLOW * 16)  # and both counted as delivered


# ---------------------------------------------------------------------------
# Nothing external: exactly as before
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("report_lag", [0.0, 1.6], ids=["valve-reports-at-once", "valve-reports-1.6-s-late"])
def test_a_shot_nothing_interrupts_runs_and_closes_exactly_as_before(rig, monkeypatch, report_lag):
    c, fake, clock = rig
    if report_lag:  # a Zigbee plug: turn_on is accepted at once, Home Assistant shows ON 1.6 s later
        real = controller.ha_call

        def call(domain, service, **data):
            if (service, data.get("entity_id")) == ("turn_on", VALVE):
                fake.calls.append((domain, service, data))
                clock.at(clock.seconds + report_lag, lambda: fake.set_state(VALVE, "on"))
                return True
            return real(domain, service, **data)

        monkeypatch.setattr(controller, "ha_call", call)
    c._execute_shot(c.rooms[0], 1, 60, 5, flow_lps=FLOW)

    room, st = c.rooms[0], c.rooms[0].state[1]
    assert switched(fake) == [("turn_on", PUMP), ("turn_on", MAIN), ("turn_on", VALVE),
                              ("turn_off", VALVE), ("turn_off", MAIN), ("turn_off", PUMP)]
    assert st["daily_vol"] == pytest.approx(FLOW * 60) and st["shots"] == 1
    assert notifications(fake) == []
    assert room.hardware_fault is None and room.shot_inflight is None


@pytest.mark.parametrize("valve_off_too", [False, True], ids=["kill-switch", "kill-switch-and-valve-off-at-once"])
def test_the_kill_switch_still_wins_and_closes_as_before(rig, monkeypatch, valve_off_too):
    c, fake, clock = rig

    def operator_stops_it(at):
        fake.set_state(KILL, "off")
        if valve_off_too:
            fake.set_state(VALVE, "off", last_updated=at(20.5))

    after_the_valve_opens(monkeypatch, fake, clock, (20.5, operator_stops_it))
    c._execute_shot(c.rooms[0], 1, 170, 2.8, flow_lps=FLOW)

    room, st = c.rooms[0], c.rooms[0].state[1]
    assert offs(fake) == [VALVE, MAIN, PUMP]  # the shot's valve, main line and pump, as always
    assert st["daily_vol"] == pytest.approx(FLOW * 22) and st["shots"] == 1  # to the check that saw it
    assert [n["title"] for n in notifications(fake)] == ["Shot cut short — kill switch / override"]
    assert room.hardware_fault is None and room.shot_inflight is None
