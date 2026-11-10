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
    for name in ("ha_get", "ha_get_status", "ha_call", "ha_get_all", "ha_set", "ha_history"):
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


@pytest.mark.parametrize("none", ["", None])
@pytest.mark.parametrize("without", [("mainline",), ("pump",), ("mainline", "pump")],
                         ids=["no main line", "no pump", "a valve only"])
def test_a_room_without_a_main_line_or_a_pump_keeps_a_record_the_next_start_can_use(rig, monkeypatch, without, none):
    """The setup wizard writes "" for a room with no main line, and for one with no pump. The record was saved
    with that "", and the next start took it for damaged and ignored it: a shot that a crash, a kill -9 or a
    power cut interrupted in such a room was not closed by the controller at its next start."""
    c, fake, _ = rig
    room = c.rooms[0]
    for key in without:
        room.hw[key] = none
    on_disk = []
    real = controller.ha_call

    def call(domain, service, **data):
        if domain == "switch" and service == "turn_on" and not on_disk:
            on_disk.append(saved(c)["default"].get("_shot_inflight"))
        return real(domain, service, **data)

    def killed(*_a, **_k):
        raise SystemExit(137)  # no cleanup runs: the stop's own cleanup is a signal handler, not called here

    monkeypatch.setattr(controller, "ha_call", call)
    monkeypatch.setattr(c, "_wait_shot", killed)
    with pytest.raises(SystemExit):
        c._execute_shot(room, 1, 60, 5)
    kept = {"mainline": "switch.m", "pump": "switch.p"}
    assert {key: on_disk[0][key] for key in kept} == {key: None if key in without else kept[key] for key in kept}
    opened = ["switch.v1", *(kept[key] for key in kept if key not in without)]
    assert all(fake.states[entity][0] == "on" for entity in opened)
    c._busy = False
    c._load_state()  # the next start
    assert room.shot_inflight == on_disk[0]
    fake.calls.clear()
    c._reconcile_inflight()
    assert offs(fake) == opened and room.shot_inflight is None


@pytest.mark.parametrize("key", ["mainline", "pump"])
def test_a_record_saved_with_an_empty_main_line_or_pump_is_usable(rig, key):
    """A controller is updated after a crash in a room without that device: the state file still holds the
    record with the "" that the version before wrote."""
    c, fake, _ = rig
    c.rooms[0].hw[key] = ""
    record = {**RECORD, key: ""}
    assert controller.Controller._inflight_record(record) == {**RECORD, key: None}
    with open(c._state_path, "w") as fh:
        json.dump({"default": {"_shot_inflight": record}}, fh)
    for entity in ("switch.v1", "switch.m", "switch.p"):
        if entity != RECORD[key]:
            fake.set_state(entity, "on", last_updated=at(2))
    c._load_state()
    fake.calls.clear()
    c._reconcile_inflight()
    assert offs(fake) == [e for e in ("switch.v1", "switch.m", "switch.p") if e != RECORD[key]]
    assert c.rooms[0].shot_inflight is None


def test_a_record_that_is_damaged_is_still_ignored():
    """No entity at all, a valve of "" (a shot always has one), or something that is no name."""
    for damaged in ({**RECORD, "valve": "", "mainline": "", "pump": ""}, {**RECORD, "valve": ""},
                    {**RECORD, "mainline": 0}, {**RECORD, "pump": ["switch.p"]}, {**RECORD, "valve": False}):
        assert controller.Controller._inflight_record(damaged) is None, damaged


@pytest.mark.parametrize("none", ["", None])
def test_two_rooms_with_no_main_line_on_two_pumps_do_not_share_a_line(rig, none):
    c, fake, _ = rig
    other = type("Room", (), {})()
    other.hw = {"pump": "switch.p2", "mainline": none, "valves": {1: "switch.b1"}}
    fake.set_state("switch.b1", "on")  # the other room waters
    c.rooms.append(other)
    try:
        record = {**RECORD, "mainline": none}
        assert c._line_in_use(c.rooms[0], record) is False
        other.hw["pump"] = "switch.p"  # the same pump: now it is one line
        assert c._line_in_use(c.rooms[0], record) is True
    finally:
        c.rooms.pop()


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
    assert alert["title"] == "Zone 1: the hardware of an interrupted shot can still be ON (CS-309)"
    assert "Can't be read: switch.v1" in alert["message"]


def test_a_retired_switch_that_is_off_never_hands_an_unsettled_shot_to_a_person(rig):
    # While System Enabled or Auto Irrigation Enabled reads off, the controller switches the room's
    # engine switch off in its place, but only once an interrupted shot is settled: the shot's valve
    # is closed first.
    c, fake, _ = rig
    crashed(c, fake)
    restarted(fake)
    fake.history["switch.v1"] = None  # this loop, whose the valve is can't be told
    fake.set_state("switch.crop_steering_system_enabled", "off")

    def home_assistant_applies_engine_writes():
        for dom, svc, d in fake.calls:
            if dom == "input_boolean":
                fake.set_state(d["entity_id"], "off" if svc == "turn_off" else "on")

    c.loop_once(datetime(2026, 9, 23, 12, 0))
    home_assistant_applies_engine_writes()
    assert offs(fake) == [] and c.rooms[0].shot_inflight is not None
    assert fake.states["input_boolean.kill"][0] == "on"  # the controller did not hand the shot over
    restarted(fake)  # the recorder has it now
    fake.calls.clear()
    c.loop_once(datetime(2026, 9, 23, 12, 1))
    assert offs(fake) == ["switch.v1", "switch.m", "switch.p"]
    assert c.rooms[0].shot_inflight is None
    # Settled, the room's watering goes off in the retired switch's place, as it would have at once.
    home_assistant_applies_engine_writes()
    assert fake.states["input_boolean.kill"][0] == "off"


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


@pytest.mark.parametrize("kill", ["off", "unavailable", None])
def test_with_the_kill_switch_off_what_the_shot_opened_is_still_closed(rig, kill):
    """"Watering off" means no water. Before, an interrupted shot's valve, main line and pump were left ON for as
    long as the room's kill switch was not ON, with one log line and no alert: the operator who obeyed CS-301
    ("set the kill switch to off") kept the water running. Now what the shot opened is closed whatever the kill
    switch reads, or when Home Assistant no longer has it."""
    c, fake, _ = rig
    crashed(c, fake)
    if kill is None:
        del fake.states["input_boolean.kill"]
    else:
        fake.set_state("input_boolean.kill", kill)
    c._reconcile_inflight()
    assert offs(fake) == ["switch.v1", "switch.m", "switch.p"]  # the valve first, then back up the line
    assert c.rooms[0].shot_inflight is None and c.rooms[0].hardware_fault is None
    assert "_shot_inflight" not in saved(c)["default"]


def test_with_the_kill_switch_off_a_valve_a_person_has_switched_since_is_still_theirs(rig):
    """The rule that protects hand watering does not change: only what has been ON since the shot opened it."""
    c, fake, _ = rig
    crashed(c, fake, valve=600)  # switched again ten minutes in: somebody is hand-watering this zone
    fake.set_state("input_boolean.kill", "off")
    c._reconcile_inflight()
    assert offs(fake) == [] and c.rooms[0].shot_inflight is None


def test_with_the_kill_switch_off_a_pump_a_hold_owns_is_still_left(rig):
    c, fake, _ = rig
    c.hold_entities = ["input_boolean.dosing"]
    fake.set_state("input_boolean.dosing", "on")
    crashed(c, fake)
    fake.set_state("input_boolean.kill", "off")
    c._reconcile_inflight()
    assert offs(fake) == ["switch.v1", "switch.m"] and fake.states["switch.p"][0] == "on"


def test_with_the_kill_switch_off_the_line_is_still_left_while_another_valve_on_it_is_open(rig):
    c, fake, _ = rig
    crashed(c, fake)
    fake.set_state("switch.v2", "on")  # somebody is hand-watering zone 2 on the same line
    fake.set_state("input_boolean.kill", "off")
    c._reconcile_inflight()
    assert offs(fake) == ["switch.v1"]
    assert {e: fake.states[e][0] for e in ("switch.m", "switch.p")} == {"switch.m": "on", "switch.p": "on"}


def test_with_the_kill_switch_off_a_switch_that_cannot_be_read_is_left_and_said_so(rig):
    """CS-309 as before: what cannot be read is not touched, whatever the kill switch reads."""
    c, fake, _ = rig
    room = crashed(c, fake)
    fake.set_state("input_boolean.kill", "off")
    for entity in ("switch.v1", "switch.m", "switch.p"):
        fake.set_state(entity, "unavailable")
    c._reconcile_inflight()
    assert offs(fake) == [] and room.shot_inflight is not None
    (card,) = notifications(fake)
    assert "(CS-309)" in card["title"] and "Can't be read: switch.v1, switch.m, switch.p" in card["message"]


def test_a_pump_home_assistant_no_longer_has_is_named_and_the_rest_is_closed(rig):
    c, fake, _ = rig
    room = crashed(c, fake)
    del fake.states["switch.p"]
    c._reconcile_inflight()
    assert offs(fake) == ["switch.v1", "switch.m"] and room.shot_inflight is not None
    (card,) = notifications(fake)
    assert "(CS-309)" in card["title"] and "Can't be read: switch.p" in card["message"]


def test_a_record_whose_only_switch_home_assistant_no_longer_has_is_said_not_waited_on_for_ever(rig):
    """Home Assistant answers, and has none of the recorded switches (a relay board removed or renamed). That is
    not Home Assistant being away: the record holds every shot of the room, so it has to be said (CS-309)."""
    c, fake, _ = rig
    room = c.rooms[0]
    room.shot_inflight = {"zone": 1, "valve": "switch.gone", "mainline": None, "pump": None,
                          "started": STARTED.isoformat()}
    c._reconcile_inflight()
    assert offs(fake) == [] and room.shot_inflight is not None
    (card,) = notifications(fake)
    assert "(CS-309)" in card["title"] and "Can't be read: switch.gone" in card["message"]


def test_a_cleared_hold_takes_the_interrupted_shots_card_down_with_it(rig, monkeypatch):
    """A switch that would not close (CS-301, CS-308), then closed by hand with the kill switch off: the hold
    clears, the record is settled, and its card goes too."""
    c, fake, _ = rig
    room = crashed(c, fake)
    real = controller.ha_call
    monkeypatch.setattr(controller, "ha_call", lambda domain, service, **data: True
                        if (service, data.get("entity_id")) == ("turn_off", "switch.v1")
                        else real(domain, service, **data))
    fake.set_state("input_boolean.kill", "off")
    c._reconcile_inflight()
    assert room.hardware_fault and "inflight_default" in c._alerted
    monkeypatch.setattr(controller, "ha_call", real)
    for entity in ("switch.v1", "switch.m", "switch.p"):
        fake.set_state(entity, "off")  # the operator closed them
    fake.calls.clear()
    c._recover_hardware_faults()
    assert room.hardware_fault is None and room.shot_inflight is None and "inflight_default" not in c._alerted
    assert ("persistent_notification", "dismiss", {"notification_id": "f2_inflight_default"}) in fake.calls


def test_a_stuck_switch_still_latches_when_only_the_tokens_writes_are_refused(rig, monkeypatch):
    """A token whose user is no longer an administrator ("writes") still sends its offs: a switch that then stays
    ON is a stuck switch, and it latches as any other."""
    c, fake, _ = rig
    room = crashed(c, fake)
    real = controller.ha_call

    def stuck(domain, service, **data):
        if service == "turn_off" and data.get("entity_id") == "switch.v1":
            fake.calls.append((domain, service, data))
            return True
        return real(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", stuck)
    monkeypatch.setattr(controller._GATE, "state", "writes")
    c._reconcile_inflight()
    assert room.hardware_fault is not None and room.shot_inflight is not None
    assert any("(CS-308)" in n["title"] for n in notifications(fake))


def test_a_close_home_assistant_refuses_for_the_token_latches_nothing(rig, monkeypatch):
    """A refused token is not a stuck switch (as in the shot's own cleanup): nothing latches, the next loop tries."""
    c, fake, _ = rig
    room = crashed(c, fake)
    monkeypatch.setattr(controller, "ha_call", lambda domain, service, **data: False)
    monkeypatch.setattr(controller._GATE, "state", "all")
    c._reconcile_inflight()
    assert room.hardware_fault is None and room.shot_inflight is not None and notifications(fake) == []


@pytest.mark.parametrize("status", [None, 502, 401])
def test_while_home_assistant_answers_nothing_the_record_waits_and_nothing_is_sent(rig, monkeypatch, status):
    """Unchanged: with no read at all there is nothing to close and nobody to tell; the next loop tries again.
    No answer, a 502 from a proxy and a 401 are all "not answering": only a 404 says the entity is gone."""
    c, fake, _ = rig
    room = crashed(c, fake)
    real_get, real_status = controller.ha_get, controller.ha_get_status
    monkeypatch.setattr(controller, "ha_get", lambda entity, *a, **k: controller.HAState())
    monkeypatch.setattr(controller, "ha_get_status", lambda entity, *a, **k: (status, controller.HAState()))
    c._reconcile_inflight()
    assert offs(fake) == [] and notifications(fake) == [] and room.shot_inflight is not None
    monkeypatch.setattr(controller, "ha_get", real_get)
    monkeypatch.setattr(controller, "ha_get_status", real_status)
    c._reconcile_inflight()
    assert offs(fake) == ["switch.v1", "switch.m", "switch.p"] and room.shot_inflight is None


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
    assert "Zone 1: CRITICAL, the hardware of an interrupted shot is still ON (CS-308)" in [
        n["title"] for n in notifications(fake)
    ]
    first = offs(fake).count("switch.v1")
    assert first == 2  # the close, and once more inside its read-back
    c._reconcile_inflight()
    assert offs(fake).count("switch.v1") == 2 * first  # tried again on the next loop


def test_a_switch_that_cannot_be_read_is_left_alone_and_said_so_with_its_code(rig):
    c, fake, _ = rig
    crashed(c, fake)
    fake.set_state("switch.v1", "unavailable")  # whose it is now cannot be told
    c._reconcile_inflight()
    assert offs(fake) == []
    (alert,) = [n for n in notifications(fake) if n["notification_id"] == "f2_inflight_default"]
    assert alert["title"] == "Zone 1: the hardware of an interrupted shot can still be ON (CS-309)"
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
    latched = [n for n in notifications(fake) if n["title"].endswith("CRITICAL hardware fault, no shots (CS-301)")]
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


def late_on_plug(monkeypatch, c, fake, clock, entity, lag_s=1.5, stop_after_s=0.5, off_wins=True):
    """A plug that takes its turn_on at once and shows ON `lag_s` later, as a Zigbee plug does, and the app
    stopped (SIGTERM) `stop_after_s` after that turn_on, while the plug still reads its old OFF.
    `off_wins`: the plug does what it was last told, so the OFF the stop sends leaves it off. Not `off_wins`:
    the ON was still on its way when the OFF arrived (or the OFF was lost) and lands after it.
    -> settle(), which lets the late report land after the process has gone and says what the plug then reads."""
    plug = {"told": "off", "shown_at": None, "settled": False}
    real_call, real_get = controller.ha_call, controller.ha_get

    def show():
        if plug["shown_at"] is not None and clock.seconds >= plug["shown_at"]:
            fake.set_state(entity, plug["told"])

    def call(domain, service, **data):
        if plug["settled"] or data.get("entity_id") != entity or service not in ("turn_on", "turn_off"):
            return real_call(domain, service, **data)
        fake.calls.append((domain, service, data))
        if service == "turn_on" or off_wins:
            plug["told"] = "on" if service == "turn_on" else "off"
            plug["shown_at"] = clock.seconds + lag_s
        if service == "turn_on":
            clock.sleep(stop_after_s)
            c._safe_exit()  # ends in SystemExit, inside the shot's switch-on
        return True

    def get(eid, timeout=8):
        if eid == entity and not plug["settled"]:
            show()
        return real_get(eid, timeout=timeout)

    def settle():
        clock.sleep(lag_s + 5)
        show()
        plug["settled"] = True  # from here an ordinary switch again: it does what it is told, at once
        return fake.states[entity][0]

    monkeypatch.setattr(controller, "ha_call", call)
    monkeypatch.setattr(controller, "ha_get", get)
    return settle


def next_start(c, fake):
    """The app starts again: it reads the state file back and settles what was recorded."""
    fake.calls.clear()
    c._load_state()
    c._reconcile_inflight()
    return c.rooms[0]


OPENED_BEFORE = {"switch.p": [], "switch.m": ["switch.p"], "switch.v1": ["switch.m", "switch.p"]}


@pytest.mark.parametrize("opening", ["switch.p", "switch.m", "switch.v1"])
def test_stopping_the_app_while_a_switch_opens_sends_it_off_though_it_still_reads_off(rig, monkeypatch, opening):
    """The app is stopped (an update, a restart) 0.5 s after the shot sent a switch ON, before Home Assistant
    shows it ON. Before: the stop read OFF, sent nothing, dropped the record and left; the plug then went ON with
    no controller running and nothing recorded to close it at the next start. Now the stop switches off the
    switch the shot was opening whatever it reads, with what the shot had already opened, and keeps the record:
    an OFF that reads back OFF proves nothing about a switch that read OFF before it was sent."""
    c, fake, clock = rig
    settle = late_on_plug(monkeypatch, c, fake, clock, opening)
    with pytest.raises(SystemExit):
        c._execute_shot(c.rooms[0], 1, 120, 5, flow_lps=0.05)
    assert offs(fake) == [opening] + OPENED_BEFORE[opening]  # the one that was opening first, then up the line
    assert c.rooms[0].hardware_fault is None
    assert saved(c)["default"]["_shot_inflight"]["valve"] == "switch.v1"  # still recorded
    assert settle() == "off"  # the late report lands after the process has gone: the plug is off
    assert {e: fake.states[e][0] for e in ("switch.v1", "switch.m", "switch.p")} == dict.fromkeys(
        ("switch.v1", "switch.m", "switch.p"), "off")
    room = next_start(c, fake)  # everything reads OFF: the record is simply closed, nothing is sent
    assert offs(fake) == [] and room.shot_inflight is None and "_shot_inflight" not in saved(c)["default"]


@pytest.mark.parametrize("opening", ["switch.p", "switch.m", "switch.v1"])
def test_an_on_that_lands_after_the_stops_off_is_closed_at_the_next_start(rig, monkeypatch, opening):
    """The ON was still on its way when the stop's OFF arrived, or the OFF was lost: the plug ends ON after the
    process has gone. The shot is still recorded, so the next start closes it."""
    c, fake, clock = rig
    settle = late_on_plug(monkeypatch, c, fake, clock, opening, off_wins=False)
    with pytest.raises(SystemExit):
        c._execute_shot(c.rooms[0], 1, 120, 5, flow_lps=0.05)
    assert opening in offs(fake)
    assert settle() == "on"
    room = next_start(c, fake)
    assert offs(fake) == [opening] + [e for e in OPENED_BEFORE[opening] if fake.states[e][0] != "off"]
    assert fake.states[opening][0] == "off" and room.shot_inflight is None and room.hardware_fault is None


def test_stopping_a_one_switch_room_while_its_valve_opens_sends_it_off(rig, monkeypatch):
    c, fake, clock = rig
    room = c.rooms[0]
    room.hw = {"pump": None, "mainline": None, "valves": {1: "switch.v1"}}
    settle = late_on_plug(monkeypatch, c, fake, clock, "switch.v1")
    with pytest.raises(SystemExit):
        c._execute_shot(room, 1, 120, 5, flow_lps=0.05)
    assert offs(fake) == ["switch.v1"]
    assert settle() == "off" and room.shot_inflight["valve"] == "switch.v1"


def hold_from_the_pumps_turn_on(monkeypatch, fake, state):
    """The hold reads `state` from the moment the pump is told ON (None: it cannot be read)."""
    real_call, real_get = controller.ha_call, controller.ha_get
    seen = {"on": False}

    def call(domain, service, **data):
        if (service, data.get("entity_id")) == ("turn_on", "switch.p"):
            seen["on"] = True
            if state is not None:
                fake.set_state("input_boolean.dosing", state)
        return real_call(domain, service, **data)

    def get(eid, timeout=8):
        if eid == "input_boolean.dosing" and seen["on"] and state is None:
            return controller.HAState()
        return real_get(eid, timeout=timeout)

    fake.set_state("input_boolean.dosing", "off")
    monkeypatch.setattr(controller, "ha_call", call)
    monkeypatch.setattr(controller, "ha_get", get)


@pytest.mark.parametrize("hold", ["on", None])
def test_stopping_while_the_pump_opens_never_switches_off_a_pump_a_hold_may_own(rig, monkeypatch, hold):
    """As everywhere else: a pump is never switched off while a hold (dosing, a fill, a flush, circulation) is
    on, nor when the hold cannot be read. The shot stays recorded either way."""
    c, fake, clock = rig
    c.hold_entities = ["input_boolean.dosing"]
    settle = late_on_plug(monkeypatch, c, fake, clock, "switch.p")
    hold_from_the_pumps_turn_on(monkeypatch, fake, hold)
    with pytest.raises(SystemExit):
        c._execute_shot(c.rooms[0], 1, 120, 5, flow_lps=0.05)
    assert offs(fake) == []
    assert settle() == "on"
    assert saved(c)["default"]["_shot_inflight"]["pump"] == "switch.p"


def unreadable_from_its_turn_on(monkeypatch, fake, entity):
    """`entity` reads unavailable from the moment it is told ON (its device dropped off as it switched)."""
    real_call, real_get = controller.ha_call, controller.ha_get
    told = {"on": False}

    def call(domain, service, **data):
        if (service, data.get("entity_id")) == ("turn_on", entity):
            told["on"] = True
        return real_call(domain, service, **data)

    def get(eid, timeout=8):
        read = real_get(eid, timeout=timeout)
        if eid == entity and told["on"]:
            return controller.HAState("unavailable", read[1], read[2])
        return read

    monkeypatch.setattr(controller, "ha_call", call)
    monkeypatch.setattr(controller, "ha_get", get)


@pytest.mark.parametrize("opening", ["switch.p", "switch.m", "switch.v1"])
def test_a_switch_that_cannot_be_read_while_it_opens_is_sent_off_and_the_shot_stays_recorded(rig, monkeypatch,
                                                                                         opening):
    """Not reading ON is not reading OFF: a switch whose device dropped off as it was told ON may be on. The stop
    sends it OFF and keeps the record, because nothing confirms it."""
    c, fake, clock = rig
    late_on_plug(monkeypatch, c, fake, clock, opening)
    unreadable_from_its_turn_on(monkeypatch, fake, opening)
    with pytest.raises(SystemExit):
        c._execute_shot(c.rooms[0], 1, 120, 5, flow_lps=0.05)
    assert opening in offs(fake)
    assert saved(c)["default"]["_shot_inflight"]["valve"] == "switch.v1"


@pytest.mark.parametrize("opening", ["switch.m", "switch.v1"])
def test_a_hold_never_keeps_the_stop_from_closing_a_valve_or_the_main_line(rig, monkeypatch, opening):
    """A hold owns the pump, never the shot's valve or main line: those are closed whatever a hold reads."""
    c, fake, clock = rig
    c.hold_entities = ["input_boolean.dosing"]
    fake.set_state("input_boolean.dosing", "off")
    settle = late_on_plug(monkeypatch, c, fake, clock, opening)
    real = controller.ha_call

    def hold_starts(domain, service, **data):
        if (service, data.get("entity_id")) == ("turn_on", opening):
            fake.set_state("input_boolean.dosing", "on")
        return real(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", hold_starts)
    with pytest.raises(SystemExit):
        c._execute_shot(c.rooms[0], 1, 120, 5, flow_lps=0.05)
    assert offs(fake)[0] == opening and "switch.p" not in offs(fake)  # the pump is the hold's now
    assert settle() == "off"


def test_a_pump_a_person_had_running_is_left_running_when_the_stop_comes_as_the_shot_opens_it(rig, monkeypatch):
    """The tank was being circulated by hand, the pump on for half an hour, when a shot began and the app was
    stopped as it sent the pump its ON. The pump reads ON: no ON is still to land, and it is the person's
    (it was on before the shot), so nothing is sent, as before."""
    c, fake, clock = rig
    fake.set_state("switch.p", "on", last_updated=(datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat())
    real = controller.ha_call

    def call(domain, service, **data):
        if (service, data.get("entity_id")) == ("turn_on", "switch.p"):
            fake.calls.append((domain, service, data))
            assert c._shot_pending == "switch.p"
            c._safe_exit()
        return real(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", call)
    with pytest.raises(SystemExit):
        c._execute_shot(c.rooms[0], 1, 120, 5, flow_lps=0.05)
    assert offs(fake) == [] and fake.states["switch.p"][0] == "on"


def test_the_opening_switch_is_forgotten_once_it_reads_on_and_when_the_shot_ends(rig, monkeypatch):
    c, fake, _clock = rig
    during = []
    monkeypatch.setattr(c, "_wait_shot", lambda room, zone, duration_s, started=None: during.append(c._shot_pending)
                        or (duration_s, None))
    c._execute_shot(c.rooms[0], 1, 30, 5, flow_lps=0.05)
    assert during == [None]  # every switch had read ON by the time the water ran
    assert c._shot_pending is None

    def refused(domain, service, **data):  # a switch that never reads ON: the shot is cancelled
        fake.calls.append((domain, service, data))
        return True

    real = controller.ha_call
    monkeypatch.setattr(controller, "ha_call", lambda domain, service, **data: refused(domain, service, **data)
                        if (service, data.get("entity_id")) == ("turn_on", "switch.p") else real(domain, service, **data))
    c._execute_shot(c.rooms[0], 2, 30, 5, flow_lps=0.05)
    assert c._shot_pending is None  # not kept past the shot that set it


def test_a_stop_with_no_shot_running_ignores_a_switch_name_left_over(rig):
    """Only the shot running now has a switch that may still be opening. An older interrupted shot is settled by
    the reconciler's rules alone, and with every switch reading OFF its record is simply closed."""
    c, fake, _clock = rig
    room = c.rooms[0]
    room.shot_inflight = dict(RECORD)
    c._shot_room, c._shot_pending = None, "switch.v1"  # no shot in flight in this process
    c._safe_off()
    assert offs(fake) == [] and room.shot_inflight is None


def test_a_stop_between_two_switches_still_closes_a_record_whose_switches_all_read_off(rig):
    """Unchanged: with no switch waiting to read ON and every switch reading OFF, the record is closed and
    nothing is sent."""
    c, fake, _clock = rig
    room = c.rooms[0]
    room.shot_inflight = dict(RECORD)
    c._shot_room, c._shot_pending = room, None
    c._safe_off()
    assert offs(fake) == [] and room.shot_inflight is None


def counting(c, fake, monkeypatch):
    """What the valve read each time a shot was counted."""
    seen = []
    real = c._advance_shot_counters

    def advance(*args, **kwargs):
        seen.append(fake.states["switch.v1"][0])
        return real(*args, **kwargs)

    monkeypatch.setattr(c, "_advance_shot_counters", advance)
    return seen


def test_an_error_mid_shot_closes_the_shot_and_counts_the_water_already_given(rig, monkeypatch):
    # CTL-005: an error 40 s into a 120 s shot closed the hardware but counted nothing, so the daily cap
    # and the minimum interval did not see the water at the next pass. Counted once, after the close.
    c, fake, clock = rig
    seen = counting(c, fake, monkeypatch)

    def wait(room, zone, duration_s, started=None):
        clock.sleep(40)
        raise RuntimeError("boom")

    monkeypatch.setattr(c, "_wait_shot", wait)
    c._execute_shot(c.rooms[0], 1, 120, 5, flow_lps=0.05)
    assert {e: fake.states[e][0] for e in ("switch.v1", "switch.m", "switch.p")} == dict.fromkeys(
        ("switch.v1", "switch.m", "switch.p"), "off")
    assert seen == ["off"]  # counted once, with the valve already closed
    st = c.rooms[0].state[1]
    # 40 s of water, plus the close like a normal shot: a little over, never under.
    assert 0.05 * 40 <= st["daily_vol"] <= 0.05 * (40 + controller.CONFIRM_TIMEOUT_S) and st["shots"] == 1
    assert c.rooms[0].hardware_fault is None and c.rooms[0].shot_inflight is None
    on_disk = saved(c)["default"]
    assert on_disk["1"]["daily_vol"] == st["daily_vol"] and "_shot_inflight" not in on_disk


def test_an_error_after_a_shot_was_counted_does_not_count_it_again(rig, monkeypatch):
    c, fake, clock = rig
    seen = counting(c, fake, monkeypatch)
    real = c._advance_shot_counters

    def advance_then_fail(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("after the count")

    monkeypatch.setattr(c, "_advance_shot_counters", advance_then_fail)
    c._execute_shot(c.rooms[0], 1, 120, 5, flow_lps=0.05)
    st = c.rooms[0].state[1]
    assert len(seen) == 1 and st["shots"] == 1
    assert 0.05 * 120 <= st["daily_vol"] <= 0.05 * (120 + 1 + controller.CONFIRM_TIMEOUT_S)
    assert all(fake.states[e][0] == "off" for e in ("switch.v1", "switch.m", "switch.p"))


def test_an_error_closing_a_shot_cut_short_still_counts_its_water(rig, monkeypatch):
    # _close_cut_short switches the shot off, then its CS-307 alert fails: the water is still counted.
    c, fake, clock = rig
    seen = counting(c, fake, monkeypatch)

    def wait(room, zone, duration_s, started=None):
        clock.sleep(40)
        return 40, ("external", "switch.hold")

    real_alert = c._alert

    def alert(key, code, *args, **kwargs):
        if code == "CS-307":
            raise RuntimeError("notify failed")
        return real_alert(key, code, *args, **kwargs)

    monkeypatch.setattr(c, "_wait_shot", wait)
    monkeypatch.setattr(c, "_alert", alert)
    c._execute_shot(c.rooms[0], 1, 120, 5, flow_lps=0.05)
    assert all(fake.states[e][0] == "off" for e in ("switch.v1", "switch.m", "switch.p"))
    assert seen == ["off"]
    st = c.rooms[0].state[1]
    assert 0.05 * 40 <= st["daily_vol"] <= 0.05 * (40 + controller.CONFIRM_TIMEOUT_S) and st["shots"] == 1
    assert c.rooms[0].hardware_fault is None and c.rooms[0].shot_inflight is None


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
