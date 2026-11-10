"""The integration's guard of a shot, in a real Home Assistant with the real controller.

The controller writes which shot is open once its valve is open. When the controller then goes
silent, the integration switches off what that shot opened once the controller's own deadline has
passed, and never before it. It switches nothing on, and it leaves what a person is using.
"""

import asyncio
import time
from datetime import timedelta
from types import SimpleNamespace

import pytest
from conftest import room_of
from homeassistant.core import Context, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from test_safety_ops import KILL, NEW, PUMP, VALVE, _arm, _call, _pumped_room

from custom_components.crop_steering import health, shot_backstop

DOMAIN = "crop_steering"
SENSOR = "sensor.crop_steering_tent_shot_in_flight"
CARD = "shot_left_open_tent"
ROOM = "room:tent_"


@pytest.fixture(autouse=True)
def _quick(monkeypatch):
    monkeypatch.setattr(shot_backstop, "PAUSE_S", 0.0)
    monkeypatch.setattr(shot_backstop, "STOP_READBACK_S", 1.0)


def _guard(hass, entry):
    return hass.data[DOMAIN]["_shot_backstop"][entry.entry_id]


def _card(hass):
    return ir.async_get(hass).async_get_issue(DOMAIN, CARD)


def _wait_of(hass, sensor=SENSOR):
    return hass.states.get(sensor).attributes["max_s"] + shot_backstop.GRACE_S


async def _overdue(hass, guard, sensor=SENSOR, extra=0.0):
    """The guard sees the shot, and then its wait is over: counted on the guard's own monotonic
    clock from when it first saw the shot."""
    await guard.tick()
    seen = guard.memory["seen"]
    guard.clock = lambda: seen + _wait_of(hass, sensor) + extra
    await guard.tick()
    await hass.async_block_till_done()


def _pass_over(c):
    """What the controller's loop does once the pass's last pump is closed."""
    for room in c.rooms:
        c._say_inflight(room)


def _switched(hass):
    """Every call that switches a device, as it is made: [(service, entity id)]."""
    sent = []

    @callback  # in the event loop, so in the order of the calls (a plain function runs in a worker thread)
    def heard(event):
        if event.data["domain"] in shot_backstop.ACTUATORS:
            sent.append((event.data["service"], event.data["service_data"].get("entity_id")))

    hass.bus.async_listen("call_service", heard)
    return sent


async def _alerts(hass, kind="alert.raised"):
    await hass.async_block_till_done()
    answer = await hass.services.async_call(
        DOMAIN,
        "journal_query",
        {"room_id": ROOM, "since": "2000-01-01T00:00:00+00:00", "kinds": [kind]},
        blocking=True,
        return_response=True,
        context=Context(),
    )
    return [e for e in answer["events"] if (e.get("data") or {}).get("key") == CARD]


async def _dies_in_a_shot(hass, controller_for, monkeypatch, seconds=30):
    """The real controller starts a shot in the room and is killed in the middle of it: nothing is
    closed. What it wrote and switched is then put into Home Assistant in the order it did so."""
    entry = await _pumped_room(hass, waste=False)
    c, fake, _clock = controller_for({"enable_flag": KILL})
    room = room_of(c, NEW)
    _arm(fake)
    _pass_over(c)  # its first pass is behind it: Home Assistant has "idle" from this controller

    def killed(*_a, **_k):
        raise SystemExit(137)

    monkeypatch.setattr(c, "_keep_alive", killed)  # in the first round of the shot's wait
    monkeypatch.setattr(c, "_safe_exit", lambda *a, **k: None)  # kill -9: no cleanup runs
    fake.calls.clear()
    with pytest.raises(SystemExit):
        c._execute_shot(room, 1, seconds, 5, flow_lps=0.05)
    assert fake.states[PUMP][0] == "on" and fake.states[VALVE][0] == "on"
    state, attrs = fake.sets[SENSOR]
    assert state == "open"
    # as the controller did: the switches first, the state once the valve was open
    await _call(hass, "input_boolean", "turn_on", PUMP)
    await _call(hass, "input_boolean", "turn_on", VALVE)
    hass.states.async_set(SENSOR, state, attrs)
    return entry, attrs


# ------------------------------------------------------------------ the controller dies in a shot
async def test_a_shot_the_controller_left_open_is_closed_after_its_deadline_and_not_before(
    hass, controller_for, monkeypatch
):
    entry, attrs = await _dies_in_a_shot(hass, controller_for, monkeypatch)
    assert (attrs["valve"], attrs["pump"]) == (VALVE, PUMP) and not attrs["mainline"]
    guard = _guard(hass, entry)
    sent = _switched(hass)

    await guard.tick()  # now: the shot has only just started
    seen = guard.memory["seen"]
    wait = attrs["max_s"] + shot_backstop.GRACE_S
    guard.clock = lambda: seen + wait - 0.1  # just before the wait is over
    await guard.tick()
    await hass.async_block_till_done()
    assert hass.states.get(VALVE).state == "on" and hass.states.get(PUMP).state == "on"
    assert sent == [] and _card(hass) is None

    guard.clock = lambda: seen + wait
    await guard.tick()
    await hass.async_block_till_done()
    assert sent == [("turn_off", VALVE), ("turn_off", PUMP)]  # valve first, and nothing switched on
    assert hass.states.get(VALVE).state == "off" and hass.states.get(PUMP).state == "off"

    card = _card(hass)
    assert card.translation_key == "shot_left_open" and card.severity is ir.IssueSeverity.CRITICAL
    assert card.is_fixable and card.is_persistent
    said = card.translation_placeholders
    assert said["zone"] == "1" and said["action"] == f"The integration sent OFF to: {VALVE}, {PUMP}."
    assert said["caution"] == " Each of them now reads off." and said["left"] == ""
    (alert,) = await _alerts(hass)
    assert alert["code"] == "CS-617" and alert["zone"] == 1 and alert["source"]["actor"] == "system"
    assert alert["outcome"] == "ok"
    assert alert["data"]["switched_off"] == [VALVE, PUMP] and alert["data"]["still_on"] == []

    sent.clear()
    guard.clock = lambda: seen + wait + 600
    await guard.tick()  # nothing is on any more: nothing is sent again
    await hass.async_block_till_done()
    assert sent == [] and len(await _alerts(hass)) == 1


async def test_no_clock_that_can_be_set_ends_or_lengthens_the_wait(hass, controller_for, monkeypatch):
    """Home Assistant's clock can jump (a time sync after a start with no clock chip), and the
    controller can run on a machine with another clock. The wait is counted on the guard's own
    monotonic clock from when it first saw the shot, and on nothing else."""
    entry, attrs = await _dies_in_a_shot(hass, controller_for, monkeypatch)
    hass.states.async_set(SENSOR, "open", {**attrs, "started": "2020-01-01T00:00:00+00:00"})
    guard = _guard(hass, entry)
    await guard.tick()
    seen = guard.memory["seen"]
    guard.clock = lambda: seen + attrs["max_s"] + shot_backstop.GRACE_S - 1
    await guard.tick(dt_util.utcnow() + timedelta(days=1))  # the time the timer passes is not used
    await hass.async_block_till_done()
    assert hass.states.get(VALVE).state == "on" and _card(hass) is None
    guard.clock = lambda: seen + attrs["max_s"] + shot_backstop.GRACE_S
    await guard.tick(dt_util.utcnow() - timedelta(days=1))  # nor a clock that was set back
    await hass.async_block_till_done()
    assert hass.states.get(VALVE).state == "off" and _card(hass) is not None


async def test_a_controller_that_restarts_with_no_record_leaves_the_shot_to_the_guard(
    hass, controller_for, monkeypatch
):
    """The Supervisor starts the controller again after a crash. If it has no usable record of the
    shot (a lost state file; a room with no main line, whose record it cannot use), it must not
    write "idle" over the "open": that is all the guard has. The guard then closes the shot."""
    import json
    import os
    from pathlib import Path

    entry, _attrs = await _dies_in_a_shot(hass, controller_for, monkeypatch)
    saved = json.loads(Path(os.environ["F2_STATE_PATH"]).read_text(encoding="utf-8"))
    for block in saved.values():
        if isinstance(block, dict):
            block.pop("_shot_inflight", None)  # the record is gone
    again, fake, _clock = controller_for({"enable_flag": KILL}, saved_state=saved)
    room = room_of(again, NEW)
    assert room.shot_inflight is None
    for _pass in range(3):
        _pass_over(again)
    assert SENSOR not in fake.sets and fake.states[SENSOR][0] == "open"  # it stands

    await _overdue(hass, _guard(hass, entry))
    assert hass.states.get(VALVE).state == "off" and hass.states.get(PUMP).state == "off"
    for entity_id in (VALVE, PUMP):  # the restarted controller reads them off now
        fake.set_state(entity_id, "off")
    _pass_over(again)
    assert fake.sets[SENSOR][0] == "idle"


async def test_a_controller_that_ends_its_shot_is_never_touched(hass, controller_for):
    entry = await _pumped_room(hass, waste=False)
    c, fake, _clock = controller_for({"enable_flag": KILL})
    _arm(fake)
    _pass_over(c)
    c._execute_shot(room_of(c, NEW), 1, 30, 5, flow_lps=0.05)
    assert fake.sets[SENSOR][0] == "open"  # it stands until the pass is over
    _pass_over(c)
    assert fake.sets[SENSOR][0] == "idle"
    hass.states.async_set(SENSOR, *fake.sets[SENSOR])
    await _call(hass, "input_boolean", "turn_on", PUMP)  # a person circulates the tank afterwards
    guard = _guard(hass, entry)
    guard.clock = lambda: 10**9
    await guard.tick()
    await hass.async_block_till_done()
    assert hass.states.get(PUMP).state == "on" and _card(hass) is None


async def test_a_room_whose_controller_never_writes_the_state_is_never_touched(hass):
    """A controller older than this state, or no controller at all."""
    entry = await _pumped_room(hass, waste=False)
    await _call(hass, "input_boolean", "turn_on", PUMP)
    await _call(hass, "input_boolean", "turn_on", VALVE)
    assert hass.states.get(SENSOR) is None
    guard = _guard(hass, entry)
    guard.clock = lambda: 10**9
    await guard.tick()
    await hass.async_block_till_done()
    assert hass.states.get(PUMP).state == "on" and hass.states.get(VALVE).state == "on"
    assert _card(hass) is None


async def test_the_guard_looks_every_30_seconds_and_stops_with_the_room(hass, monkeypatch):
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    looked = []

    async def tick(self, now=None):
        looked.append(self.entity_id)

    monkeypatch.setattr(shot_backstop.Backstop, "tick", tick)
    entry = await _pumped_room(hass, waste=False)
    assert shot_backstop.EVERY == timedelta(seconds=30)
    assert (shot_backstop.GRACE_S, shot_backstop.ATTEMPTS) == (60.0, 3)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done()
    assert looked == [SENSOR]
    assert await hass.config_entries.async_unload(entry.entry_id)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=62))
    await hass.async_block_till_done()
    assert looked == [SENSOR] and entry.entry_id not in hass.data[DOMAIN].get("_shot_backstop", {})


# ------------------------------------------------------------------ what a person is using stays
async def test_a_pump_that_a_person_had_on_before_the_shot_stays_on(hass, monkeypatch):
    monkeypatch.setattr(shot_backstop, "EARLY_S", 0.0)
    entry = await _pumped_room(hass, waste=False)
    await _call(hass, "input_boolean", "turn_on", PUMP)  # the tank circulates
    await asyncio.sleep(1.2)
    await _call(hass, "input_boolean", "turn_on", VALVE)
    hass.states.async_set(SENSOR, "open", _shot(opened_s=1.0))  # the shot opened in the last second
    await _overdue(hass, _guard(hass, entry))
    assert hass.states.get(VALVE).state == "off" and hass.states.get(PUMP).state == "on"
    said = _card(hass).translation_placeholders
    assert said["action"] == f"The integration sent OFF to: {VALVE}."
    assert said["left"] == f" It left the rest on: {PUMP} was not switched on by this shot."
    (alert,) = await _alerts(hass)
    assert alert["data"]["switched_off"] == [VALVE] and alert["data"]["left"].startswith(PUMP)


@pytest.mark.parametrize(
    "extra, why",
    [
        ({"line_valves": ["input_boolean.other_valve"]}, "another valve on this line is open"),
        ({"holds": ["input_boolean.other_valve"]}, "a hold (dosing, fill, flush or circulation) is on"),
    ],
)
async def test_the_pump_stays_for_another_open_valve_on_its_line_and_for_a_hold(hass, extra, why):
    entry = await _pumped_room(hass, waste=False)
    hass.states.async_set("input_boolean.other_valve", "on")
    await _call(hass, "input_boolean", "turn_on", PUMP)
    await _call(hass, "input_boolean", "turn_on", VALVE)
    hass.states.async_set(SENSOR, "open", _shot(**extra))
    await _overdue(hass, _guard(hass, entry))
    assert hass.states.get(VALVE).state == "off" and hass.states.get(PUMP).state == "on"
    assert _card(hass).translation_placeholders["left"] == f" It left the rest on: {why}."


async def test_when_the_rules_say_to_leave_what_is_on_the_card_says_so_once_and_nothing_is_sent(hass, monkeypatch):
    """The valve went unavailable and came back in the shot, so Home Assistant no longer shows that
    the shot opened it: the guard leaves it, as it would a valve a person opened. It must not be
    silent about it: the valve is on and the controller is gone."""
    monkeypatch.setattr(shot_backstop, "EARLY_S", 0.0)
    entry = await _pumped_room(hass, waste=False)
    await _call(hass, "input_boolean", "turn_on", VALVE)
    await asyncio.sleep(1.2)
    hass.states.async_set(SENSOR, "open", _shot(opened_s=0.5, pump=None))
    guard = _guard(hass, entry)
    sent = _switched(hass)
    await _overdue(hass, guard)
    guard.clock = lambda: 10**9
    await guard.tick()
    await hass.async_block_till_done()
    assert sent == [] and hass.states.get(VALVE).state == "on"
    said = _card(hass).translation_placeholders
    assert said["action"] == "The integration switched nothing off."
    assert said["caution"].startswith(" CAUTION: The valve of the shot does not read off.")
    assert said["left"] == f" It left the rest on: {VALVE} was not switched on by this shot."
    (alert,) = await _alerts(hass)  # once, not at each look
    assert alert["outcome"] == "failed" and alert["data"]["switched_off"] == []


async def test_a_valve_that_does_not_close_is_tried_three_times_and_the_card_says_go_to_the_room(hass):
    entry = await _pumped_room(hass, waste=False)
    ghost = "switch.ghost_valve"  # Home Assistant has no device behind it: it never reads off
    hass.states.async_set(ghost, "on")
    hass.states.async_set(SENSOR, "open", _shot(valve=ghost, pump=None))
    guard = _guard(hass, entry)
    sent = _switched(hass)
    await _overdue(hass, guard)
    for _ in range(4):
        await guard.tick()
        await hass.async_block_till_done()
    assert sent == [("turn_off", ghost)] * shot_backstop.ATTEMPTS
    said = _card(hass).translation_placeholders
    assert said["action"] == f"The integration sent OFF to: {ghost}."
    assert said["caution"].startswith(f" CAUTION: These still read on: {ghost}.") and "by hand" in said["caution"]
    (alert,) = await _alerts(hass)  # one alert for the shot, not one for each try
    assert alert["outcome"] == "failed" and alert["data"]["still_on"] == [ghost]


@pytest.mark.parametrize("state", ["unavailable", "unknown", None])
async def test_the_read_back_counts_a_device_that_cannot_be_read_as_still_on(hass, state):
    await _pumped_room(hass, waste=False)
    if state is not None:
        hass.states.async_set("switch.ghost_valve", state)
    assert await shot_backstop.switch_off(hass, ["switch.ghost_valve"]) == ["switch.ghost_valve"]


async def test_a_pump_left_on_behind_a_closed_valve_is_no_incident_of_this_shot(hass):
    """The controller closed the valve and left the pump: another shot uses it, a hold has it, or a
    person runs it. The "open" still stands for a while (the controller says "idle" when its pass
    is over). Nothing is sent and no card is raised."""
    entry = await _pumped_room(hass, waste=False)
    await _call(hass, "input_boolean", "turn_on", PUMP)
    hass.states.async_set(SENSOR, "open", _shot())
    await asyncio.sleep(0.05)
    await _call(hass, "input_boolean", "turn_off", PUMP)
    await _call(hass, "input_boolean", "turn_on", PUMP)  # switched on again after the shot's write
    guard = _guard(hass, entry)
    sent = _switched(hass)
    await _overdue(hass, guard)
    assert sent == [] and hass.states.get(PUMP).state == "on" and _card(hass) is None
    assert await _alerts(hass) == []


async def test_everything_off_past_the_wait_is_nothing_to_do_and_nothing_to_say(hass):
    entry = await _pumped_room(hass, waste=False)
    hass.states.async_set(SENSOR, "open", _shot())
    sent = _switched(hass)
    await _overdue(hass, _guard(hass, entry))
    assert sent == [] and _card(hass) is None and await _alerts(hass) == []


async def test_a_reload_of_the_room_does_not_start_the_wait_again_or_send_more_offs(hass):
    """Saving a setting reloads the room. The guard's memory of the shot is the room's, not the
    object's: the wait goes on, the three tries are three in all, and the alert is raised once."""
    entry = await _pumped_room(hass, waste=False)
    ghost = "switch.ghost_valve"
    hass.states.async_set(ghost, "on")
    hass.states.async_set(SENSOR, "open", _shot(valve=ghost, pump=None))
    guard = _guard(hass, entry)
    await guard.tick()
    seen = guard.memory["seen"]
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    again = _guard(hass, entry)
    assert again is not guard and again.memory["seen"] == seen
    sent = _switched(hass)
    again.clock = lambda: seen + _wait_of(hass)
    await again.tick()
    await hass.async_block_till_done()
    assert sent == [("turn_off", ghost)]
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    third = _guard(hass, entry)
    third.clock = lambda: seen + _wait_of(hass)
    for _ in range(5):
        await third.tick()
        await hass.async_block_till_done()
    assert sent == [("turn_off", ghost)] * shot_backstop.ATTEMPTS
    assert len(await _alerts(hass)) == 1


async def test_a_new_shot_left_open_starts_its_own_wait_and_raises_a_new_card(hass):
    """The card of the first one was not confirmed. The second is a new incident: its wait is its
    own, its switches get their own tries, and the card is made again, so the phones get it."""
    entry = await _pumped_room(hass, waste=False)
    ghost = "switch.ghost_valve"
    hass.states.async_set(ghost, "on")
    hass.states.async_set(SENSOR, "open", _shot(valve=ghost, pump=None))
    made = []
    hass.bus.async_listen(
        "repairs_issue_registry_updated",
        callback(lambda event: made.append(event.data["action"]) if event.data["issue_id"] == CARD else None),
    )
    guard = _guard(hass, entry)
    sent = _switched(hass)
    await _overdue(hass, guard)
    for _ in range(4):
        await guard.tick()
        await hass.async_block_till_done()
    assert len(sent) == shot_backstop.ATTEMPTS and made.count("create") == 1

    hass.states.async_set(SENSOR, "open", _shot(valve=ghost, pump=None, started="the next shot"))
    hass.states.async_set(ghost, "off")
    hass.states.async_set(ghost, "on")
    hass.states.async_set(SENSOR, "open", _shot(valve=ghost, pump=None, started="the next shot", max_s=201.0))
    sent.clear()
    await guard.tick()  # seen now: its wait has only begun, whatever the clock said for the first
    await hass.async_block_till_done()
    assert sent == [] and guard.memory["tries"] == 0 and guard.memory["said"] is False
    seen = guard.memory["seen"]
    guard.clock = lambda: seen + _wait_of(hass)
    await guard.tick()
    await hass.async_block_till_done()
    assert sent == [("turn_off", ghost)]
    assert made.count("create") == 2 and len(await _alerts(hass)) == 2


# ------------------------------------------------------------------ a controller that still reports
HEARTBEAT = "sensor.crop_steering_tent_ai_heartbeat"


def _reports(hass, guard, state="healthy"):
    """The controller wrote its heartbeat just now, as the guard sees it."""
    hass.states.async_set(HEARTBEAT, state, {"last_beat": dt_util.utcnow().isoformat()})
    guard.silent()


async def _overdue_with_a_fresh_heartbeat(hass, guard, state="healthy"):
    """The shot's wait is over, and the controller wrote its heartbeat a moment ago."""
    await guard.tick()
    seen = guard.memory["seen"]
    guard.clock = lambda: seen + _wait_of(hass)
    _reports(hass, guard, state)
    await guard.tick()
    await hass.async_block_till_done()


async def test_a_controller_that_reports_is_not_accused_while_its_pass_goes_on(hass):
    """The controller writes "idle" when its whole pass is over. While it waters other zones, zone
    1's "open" stands past its wait. Its valve plug then drops out. The controller is alive and
    will close and report by itself: no critical card, and nothing sent."""
    entry = await _pumped_room(hass, waste=False)
    guard = _guard(hass, entry)
    hass.states.async_set(VALVE, "unavailable")
    hass.states.async_set(SENSOR, "open", _shot(pump=None))
    sent = _switched(hass)
    await _overdue_with_a_fresh_heartbeat(hass, guard)
    assert sent == [] and _card(hass) is None and await _alerts(hass) == []
    # 3 minutes with no heartbeat write: now the controller is silent, and the valve is said
    seen = guard.beat["at"]
    guard.clock = lambda: seen + shot_backstop.SILENT_S - 1
    await guard.tick()
    assert _card(hass) is None
    guard.clock = lambda: seen + shot_backstop.SILENT_S
    await guard.tick()
    await hass.async_block_till_done()
    assert _card(hass).translation_placeholders["left"] == f" It left the rest on: {VALVE} cannot be read."
    assert sent == []


@pytest.mark.parametrize("heartbeat", ["healthy", "error"])
async def test_a_pump_behind_the_shots_closed_valve_is_left_while_the_controller_reports(hass, heartbeat):
    """The shot's valve is off and its pump is still on from the shot (it was left under a hold).
    A controller that reports may be priming the next shot through that pump: it is not touched.
    Once the controller is silent, the pump is the guard's to close."""
    entry = await _pumped_room(hass, waste=False)
    guard = _guard(hass, entry)
    await _call(hass, "input_boolean", "turn_on", PUMP)
    hass.states.async_set(SENSOR, "open", _shot())
    sent = _switched(hass)
    await _overdue_with_a_fresh_heartbeat(hass, guard, heartbeat)
    assert sent == [] and hass.states.get(PUMP).state == "on" and _card(hass) is None
    seen = guard.beat["at"]
    guard.clock = lambda: seen + shot_backstop.SILENT_S + 10**6
    await guard.tick()
    await hass.async_block_till_done()
    assert sent == [("turn_off", PUMP)] and hass.states.get(PUMP).state == "off"


@pytest.mark.parametrize("heartbeat", ["healthy", "stopped", None])
async def test_the_shots_own_valve_past_its_time_is_closed_whatever_the_heartbeat_says(hass, heartbeat):
    """This is the case the guard is for. A controller that hangs in a shot can still be writing
    its heartbeat: an open valve of the shot past the controller's own deadline is closed."""
    entry = await _pumped_room(hass, waste=False)
    guard = _guard(hass, entry)
    await _call(hass, "input_boolean", "turn_on", PUMP)
    await _call(hass, "input_boolean", "turn_on", VALVE)
    hass.states.async_set(SENSOR, "open", _shot())
    sent = _switched(hass)
    if heartbeat is None:
        await _overdue(hass, guard)
    else:
        await _overdue_with_a_fresh_heartbeat(hass, guard, heartbeat)
    assert sent == [("turn_off", VALVE), ("turn_off", PUMP)] and _card(hass) is not None


async def test_a_heartbeat_that_is_written_again_is_a_controller_that_reports(hass):
    entry = await _pumped_room(hass, waste=False)
    guard = _guard(hass, entry)
    assert guard.silent() is True  # no heartbeat at all
    _reports(hass, guard)
    start = guard.beat["at"]
    guard.clock = lambda: start + shot_backstop.SILENT_S - 1
    assert guard.silent() is False
    hass.states.async_set(HEARTBEAT, "healthy", {"last_beat": "a new one"})  # written again: the count starts again
    assert guard.silent() is False and guard.beat["at"] == start + shot_backstop.SILENT_S - 1
    guard.clock = lambda: start + 2 * shot_backstop.SILENT_S - 2
    assert guard.silent() is False
    guard.clock = lambda: start + 2 * shot_backstop.SILENT_S - 1
    assert guard.silent() is True
    hass.states.async_set(HEARTBEAT, "stopped", {})
    guard.clock = lambda: start + 2 * shot_backstop.SILENT_S
    assert guard.silent() is True  # it said so itself
    assert shot_backstop.SILENT_S == 180.0


async def test_a_valve_entity_that_reads_closed_raises_no_card_and_a_missing_valve_does(hass):
    entry = await _pumped_room(hass, waste=False)
    guard = _guard(hass, entry)
    hass.states.async_set("valve.z1", "closed")
    hass.states.async_set("switch.main", "unavailable")
    hass.states.async_set(SENSOR, "open", _shot(valve="valve.z1", mainline="switch.main", pump=None))
    await _overdue(hass, guard)  # no heartbeat: the controller is silent
    assert _card(hass) is None  # the shot's valve is closed: an unreadable main line behind it is no incident
    hass.states.async_remove("valve.z1")
    hass.states.async_set(SENSOR, "open", _shot(valve="valve.z1", mainline="switch.main", pump=None, max_s=201.0))
    await _overdue(hass, guard)
    assert _card(hass).translation_placeholders["left"] == " It left the rest on: valve.z1 cannot be read."


# ------------------------------------------------------------------ the card
async def test_the_card_stays_over_a_reload_and_a_room_switched_off_until_a_person_confirms_it(
    hass, controller_for, monkeypatch
):
    assert await async_setup_component(hass, "repairs", {})
    entry, _attrs = await _dies_in_a_shot(hass, controller_for, monkeypatch)
    await _overdue(hass, _guard(hass, entry))
    assert _card(hass) is not None

    hass.states.async_set("switch.crop_steering_tent_room_active", "off")
    health.run_health_check(hass, entry)
    assert _card(hass) is not None
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _card(hass) is not None

    flows = hass.data["repairs"]["flow_manager"]
    step = await flows.async_init(DOMAIN, data={"issue_id": CARD})
    assert step["type"] == "form" and step["step_id"] == "confirm"
    done = await flows.async_configure(step["flow_id"], {})
    assert done["type"] == "create_entry"
    assert _card(hass) is None
    (cleared,) = await _alerts(hass, "alert.cleared")
    assert cleared["source"]["actor"] == "manual"


async def test_the_push_to_a_phone_carries_the_words_of_the_card(hass, controller_for, monkeypatch):
    """A card with a Fix button has its words on the confirm step, not in a description: the push
    must read them there, or the phone gets a title and nothing to act on."""
    entry, _attrs = await _dies_in_a_shot(hass, controller_for, monkeypatch)
    await _overdue(hass, _guard(hass, entry))
    notifier = hass.data[DOMAIN]["_notify"]
    title, message = await notifier._issue_text(
        "shot_left_open", dict(_card(hass).translation_placeholders), "CS-617"
    )
    assert title == "Controller did not close a shot (CS-617)"
    assert f"The integration sent OFF to: {VALVE}, {PUMP}. Each of them now reads off." in message
    assert "{" not in message and "Code CS-617." in message
    _title, latch = await notifier._issue_text("max_run_latch", {"zones": "1", "what": ""}, "CS-312")
    assert "maximum shot length" in latch  # the other card with a button: no longer the stand-in text


# ------------------------------------------------------------------ the rule itself, at its edges
def _shot(**over):
    base = {"zone": 1, "valve": VALVE, "mainline": None, "pump": PUMP, "started": "x",
            "opened_s": 30.0, "max_s": 200.0, "holds": [], "line_valves": []}
    return {**base, **over}


class _States:
    def __init__(self, t0, **entities):
        """{entity: (state, seconds after the write it changed)}"""
        self._all = {
            name.replace("__", "."): SimpleNamespace(state=state, last_changed=t0 + timedelta(seconds=since))
            for name, (state, since) in entities.items()
        }

    def get(self, entity_id):
        return self._all.get(entity_id)


def _plan(attrs, state="open", **entities):
    t0 = dt_util.utcnow()
    hass = SimpleNamespace(states=_States(t0, **entities))
    shot = SimpleNamespace(state=state, attributes=attrs, last_updated=t0)
    return shot_backstop.plan(hass, shot)


ON = {"input_boolean__tent_valve": ("on", -1), "input_boolean__tent_pump": ("on", -4)}


def test_what_the_shot_opened_is_closed_valve_first_and_an_idle_state_is_nothing():
    assert _plan(_shot(), **ON) == ([VALVE, PUMP], "")
    assert _plan(_shot(), state="idle", **ON) is None


@pytest.mark.parametrize("since, own", [(-35.1, False), (-35.0, True), (-0.01, True), (0.0, True), (0.01, False)])
def test_a_switch_is_the_shots_only_when_it_went_on_while_the_shot_opened(since, own):
    """The shot took 30 s to open, with 5 s of slack before that. Every switch of the shot was read on
    before the write, so one that went on after it is not the shot's."""
    found = _plan(_shot(), input_boolean__tent_valve=("on", since), input_boolean__tent_pump=("on", -4))
    assert found == (([VALVE, PUMP], "") if own else ([], f"{VALVE} was not switched on by this shot"))


def test_a_valve_that_is_not_the_shots_keeps_everything_upstream_of_it_on():
    found = _plan(_shot(mainline="switch.main"), input_boolean__tent_valve=("on", 500),
                  switch__main=("on", -2), input_boolean__tent_pump=("on", -4))
    assert found == ([], f"{VALVE} was not switched on by this shot")


@pytest.mark.parametrize("valve", [None, ("unavailable", -1), ("unknown", -1), ("opening", -1)])
def test_a_switch_that_cannot_be_read_is_not_touched_and_nothing_upstream_of_it_is(valve):
    entities = {"input_boolean__tent_pump": ("on", -4)}
    if valve:
        entities["input_boolean__tent_valve"] = valve
    assert _plan(_shot(), **entities) == ([], f"{VALVE} cannot be read")


def test_everything_off_is_nothing_to_do_and_nothing_to_say():
    found = _plan(_shot(), input_boolean__tent_valve=("off", 100), input_boolean__tent_pump=("off", 101))
    assert found == ([], "")


def test_a_closed_valve_and_a_pump_still_on_closes_the_pump():
    found = _plan(_shot(), input_boolean__tent_valve=("off", 100), input_boolean__tent_pump=("on", -4))
    assert found == ([PUMP], "")
    found = _plan(_shot(valve="valve.z1"), valve__z1=("closed", 100), input_boolean__tent_pump=("on", -4))
    assert found == ([PUMP], "")  # a valve entity reads closed, not off


def test_the_order_is_valve_main_line_pump_and_a_valve_entity_counts_open_as_on():
    attrs = _shot(valve="valve.z1", mainline="switch.main")
    found = _plan(attrs, valve__z1=("open", -1), switch__main=("on", -2), input_boolean__tent_pump=("on", -4))
    assert found == (["valve.z1", "switch.main", PUMP], "")


def test_a_hold_keeps_only_the_pump_and_another_open_valve_keeps_the_main_line_too():
    on = {"valve__z1": ("open", -1), "switch__main": ("on", -2), "input_boolean__tent_pump": ("on", -4)}
    attrs = _shot(valve="valve.z1", mainline="switch.main", holds=["switch.fill"], line_valves=["valve.z2"])
    assert _plan(attrs, switch__fill=("on", -900), **on) == (
        ["valve.z1", "switch.main"], "a hold (dosing, fill, flush or circulation) is on")
    assert _plan(attrs, valve__z2=("open", -900), **on) == (
        ["valve.z1"], "another valve on this line is open")
    # one that cannot be read does not count as on, as in the controller's own check
    assert _plan(attrs, switch__fill=("unavailable", 0), valve__z2=("unknown", 0), **on) == (
        ["valve.z1", "switch.main", PUMP], "")


@pytest.mark.parametrize("state", ["on", "ON", "true", "open", "1", "home"])
def test_a_hold_is_on_in_every_state_the_controller_reads_as_on(state):
    attrs = _shot(holds=["input_boolean.dosing"])
    found = _plan(attrs, input_boolean__dosing=(state, -900), **ON)
    assert found == ([VALVE], "a hold (dosing, fill, flush or circulation) is on")


@pytest.mark.parametrize(
    "attrs",
    [
        _shot(max_s="200"),
        _shot(max_s=True),
        _shot(max_s=0),
        _shot(max_s=shot_backstop.LONGEST_S + 1),
        _shot(opened_s=None),
        _shot(opened_s=0),
        _shot(opened_s="4"),
        _shot(valve=None, pump=None),
        _shot(valve="light.grow"),  # not a domain the controller switches
        _shot(pump=["input_boolean.tent_pump"]),
    ],
)
def test_a_state_that_is_not_a_shots_is_never_acted_on(attrs):
    assert _plan(attrs, **ON) is None


def test_the_longest_shot_is_still_a_shot_and_junk_in_the_lists_is_passed_over():
    assert _plan(_shot(max_s=shot_backstop.LONGEST_S), **ON) == ([VALVE, PUMP], "")
    assert shot_backstop.LONGEST_S == 4 * 3600.0
    attrs = _shot(line_valves=[None, 5, "valve.z2"], holds=[["x"], "switch.fill"])
    assert _plan(attrs, **ON) == ([VALVE, PUMP], "")
    assert _plan(attrs, valve__z2=("open", -900), **ON) == ([VALVE], "another valve on this line is open")


def test_an_empty_main_line_is_no_main_line():
    """The setup wizard writes "" for a room with no main line, and the controller passes it on."""
    assert _plan(_shot(mainline=""), **ON) == ([VALVE, PUMP], "")


# ------------------------------------------------------------------ a room from before this guard
async def test_a_room_updated_in_place_from_2_25_1_gets_the_guard_with_nothing_to_set_up(
    hass, controller_for, monkeypatch
):
    """The seeded 2.25.1 room has a pump, a main line and a zone valve, and no room prefix. Updated
    in place, the real controller writes the state and the guard sends the three OFFs in order."""
    from conftest import fixture
    from test_upgrade_in_place import KILL as OLD_KILL
    from test_upgrade_in_place import UPSTREAM_2_25_1, _upgrade

    valve, main, pump = "switch.zone_1_valve", "switch.irrigation_main_line", "switch.irrigation_pump"
    sensor = "sensor.crop_steering_shot_in_flight"
    seed = fixture(UPSTREAM_2_25_1)
    await _upgrade(hass, UPSTREAM_2_25_1, registry_ids=seed["registry"])
    hass.states.async_set(OLD_KILL, "on")
    real_clock = time.monotonic
    c, fake, _clock = controller_for(seed["addon_options"], saved_state=seed["controller_saved"])
    room = c.rooms[0]
    _pass_over(c)

    def killed(*_a, **_k):
        raise SystemExit(137)

    monkeypatch.setattr(c, "_keep_alive", killed)
    monkeypatch.setattr(c, "_safe_exit", lambda *a, **k: None)
    with pytest.raises(SystemExit):
        c._execute_shot(room, 1, 30, 5, flow_lps=0.05)
    state, attrs = fake.sets[sensor]
    assert state == "open" and (attrs["valve"], attrs["mainline"], attrs["pump"]) == (valve, main, pump)
    # The controller ran on the test's own clock, which stands still; the guard's read-back waits on the real one.
    monkeypatch.setattr(time, "monotonic", real_clock)
    for entity_id in (pump, main, valve):  # no device behind them in this test: they stay on
        hass.states.async_set(entity_id, "on")
    hass.states.async_set(sensor, state, attrs)
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    sent = _switched(hass)
    await _overdue(hass, _guard(hass, entry), sensor)
    assert sent == [("turn_off", valve), ("turn_off", main), ("turn_off", pump)]
    card = ir.async_get(hass).async_get_issue(DOMAIN, "shot_left_open")  # the default room: no slug
    assert card is not None and card.translation_placeholders["caution"].startswith(" CAUTION:")
