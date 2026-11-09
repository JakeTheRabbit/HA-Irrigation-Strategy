"""AN ARMED PLAN THAT HAS NOT STARTED HOLDS NOTHING, across both layers, in a real Home Assistant.

F1, 9 Nov 2026: the room's old plan was disarmed and released at the 10:10 lights-on, and in that same minute plan
rev 4 was saved and armed for the next lights-on. Saving and arming clear release_legacy, and the controller, still
latched from the old plan, had not seen the minute it was set: every pass every zone logged "Strategy hold: Strategy
is held; no current active snapshot", and only the watchdog shot got through until the plan was disarmed. Until its
first lights-on an armed plan leaves the room on its own settings, as before arming (docs/GROW_PLANS.md).

The real integration's plan store, lights-on boundary and published plan sensor, and the real controller; only the
web server and time are stood in for (test_plan_adherence.py).
"""

from datetime import timedelta

from conftest import room_of, switch_calls
from homeassistant.util import dt as dt_util
from strategy_runtime import strategy_block
from test_plan_adherence import TENT, TENT_ARMED, _aligned_plan, _beat, _pass, _start, _tent, TENT_KILL
from test_real_flow import VALVE


async def test_a_plan_armed_mid_day_after_one_ran_leaves_the_zones_watering(hass, controller_for, monkeypatch):
    at = _start()
    _entry, manager, c, fake = await _tent(hass, controller_for, monkeypatch, at)
    room = room_of(c, TENT)

    # The old plan runs, and the controller has latched it.
    await _pass(hass, c, fake, monkeypatch, manager, at)
    assert room.strategy_required is True and not room.strategy_snapshot["error"]

    # It is disarmed, and released at the next lights-on...
    await manager.disarm(dt_util.now())
    assert manager.document["status"] == "disarming"
    lights_on = manager._next_boundary(dt_util.now())
    await manager.tick(lights_on + timedelta(seconds=30))
    assert manager.document["status"] == "draft" and manager.document["release_legacy"] is True

    # ...and in that same minute, before the controller looks again, the new plan is saved and armed mid-day.
    _beat(hass, TENT, TENT_KILL)
    await manager.save(_aligned_plan(manager, start=at.date()), manager.document["revision"])
    await manager.activate(manager.document["revision"], dt_util.now())
    hass.states.async_remove(f"sensor.crop_steering_{TENT}ai_heartbeat")  # the controller writes its own
    assert manager.document["status"] == "armed" and manager.document["release_legacy"] is False
    published = hass.states.get(f"sensor.crop_steering_{TENT}strategy_plan").attributes
    assert published["enabled"] is False and published["zones"] == []

    # The room is armed and the zone is dry: the next pass waters it on the room's own settings.
    for switch in TENT_ARMED:
        hass.states.async_set(switch, "on")
    fake.calls.clear()
    await _pass(hass, c, fake, monkeypatch, manager, at + timedelta(minutes=1))
    assert room.strategy_required is False
    assert strategy_block(room.strategy_snapshot, 1) is None
    assert "Strategy hold" not in (c._blocked(room, 1) or "")
    assert ("turn_on", VALVE) in switch_calls(fake), "the zone did not shoot"


async def test_a_plan_that_runs_and_breaks_still_holds_its_zones(hass, controller_for, monkeypatch):
    """The hold stays for a running plan that is broken: in error, the controller holds its steering."""
    at = _start()
    _entry, manager, c, fake = await _tent(hass, controller_for, monkeypatch, at)
    room = room_of(c, TENT)
    await _pass(hass, c, fake, monkeypatch, manager, at)
    # held by the integration (what _Hold stores): only the operator can clear it
    manager.document.update(status="error", error="Strategy zones do not match room setup")
    await _pass(hass, c, fake, monkeypatch, manager, at + timedelta(minutes=1))
    assert "Strategy hold" in strategy_block(room.strategy_snapshot, 1)
