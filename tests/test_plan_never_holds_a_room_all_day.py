"""A grow-strategy plan never holds a room all day for a fault that clears itself.

The plan moved on to a new day only inside a 120-second window after lights-on, and whatever missed that
window put it in error, which holds the steering of every zone it manages until the next lights-on: Home
Assistant down across lights-on, a stale controller heartbeat or probe at that moment, a lights_on_hour
changed while it ran, a lights-on inside a daylight-saving gap. Now the day is applied on the first tick
that can, the last valid snapshot stays published with a `degraded_reason` until then, and only a fault
the operator has to clear is an error. A plan that is armed or running also refuses a zone-set change,
which would otherwise put it in error.
"""

import asyncio
import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from custom_components.crop_steering import setup_api as api

from .test_setup import payload, rig
from .test_strategy import manager_fixture, plan

HOUR = "number.crop_steering_lights_on_hour"
HEARTBEAT = "sensor.crop_steering_ai_heartbeat"


def fresh(states, at):
    for state in states.values():
        state.last_updated = at


async def running(manager, states, now, lights_on):
    """Armed at `now`, and applied at its first lights-on."""
    await manager.async_init()
    await manager.save(plan(), 0)
    await manager.activate(1, now)
    fresh(states, lights_on)
    await manager.tick(lights_on)
    assert manager.document["status"] == "active"


# ---------------------------------------------------------------- a stale heartbeat at lights-on
def test_a_stale_heartbeat_at_lights_on_waits_for_the_controller_instead_of_holding(
    monkeypatch,
):
    manager, states, now = manager_fixture(monkeypatch)  # 08:00, lights-on at 10:00

    async def scenario():
        await manager.async_init()
        await manager.save(plan(), 0)
        await manager.activate(1, now)
        lights_on = now + timedelta(hours=2)
        fresh(states, lights_on)
        states[HEARTBEAT].last_updated = lights_on - timedelta(minutes=10)
        await manager.tick(lights_on)
        assert manager.document["status"] == "armed"
        assert manager.document["error"] is None
        published = states[manager.entity_id]
        assert published.state == "armed" and published.attributes["enabled"] is False
        assert "heartbeat" in published.attributes["degraded_reason"]
        later = lights_on + timedelta(minutes=7)  # long past the old 120-second window
        fresh(states, later)
        await manager.tick(later)
        assert manager.document["status"] == "active"
        assert manager.document["active"]["grow_day"] == "2026-09-08"
        assert states[manager.entity_id].attributes["degraded_reason"] is None

    asyncio.run(scenario())


def test_a_running_plan_keeps_its_last_snapshot_until_it_can_apply_the_new_day(
    monkeypatch,
):
    manager, states, now = manager_fixture(monkeypatch)

    async def scenario():
        await running(manager, states, now, now + timedelta(hours=2))
        yesterday = copy.deepcopy(manager.document["active"])
        next_lights_on = now + timedelta(days=1, hours=2)
        fresh(states, next_lights_on)
        # A probe gone quiet at lights-on.
        states["sensor.crop_steering_vwc_zone_1"].last_updated = now
        await manager.tick(next_lights_on + timedelta(seconds=30))
        assert manager.document["status"] == "active"
        assert manager.document["active"] == yesterday
        published = states[manager.entity_id].attributes
        assert published["enabled"] is True and published["zones"]
        assert published["grow_day"] == "2026-09-08"
        assert "VWC" in published["degraded_reason"]
        fresh(states, next_lights_on + timedelta(minutes=20))
        await manager.tick(next_lights_on + timedelta(minutes=20))
        assert manager.document["active"]["grow_day"] == "2026-09-09"

    asyncio.run(scenario())


# ---------------------------------------------------------------- Home Assistant down across lights-on
def test_home_assistant_down_across_lights_on_applies_the_missed_day_on_its_first_tick(
    monkeypatch,
):
    manager, states, now = manager_fixture(monkeypatch)

    async def scenario():
        await running(manager, states, now, now + timedelta(hours=2))
        restored, restored_states, _ = manager_fixture(
            monkeypatch, store=manager._store
        )
        await restored.async_init()  # back three hours after the next lights-on
        assert restored.document["status"] == "active"
        assert restored.document["error"] is None
        assert restored_states[restored.entity_id].attributes["zones"]
        back = now + timedelta(days=1, hours=5)
        fresh(restored_states, back)
        await restored.tick(back)
        assert restored.document["status"] == "active"
        assert restored.document["active"]["grow_day"] == "2026-09-09"

    asyncio.run(scenario())


def test_an_armed_plan_whose_first_lights_on_was_missed_starts_that_day(monkeypatch):
    manager, states, now = manager_fixture(monkeypatch)

    async def scenario():
        await manager.async_init()
        await manager.save(plan(), 0)
        await manager.activate(1, now)
        back = now + timedelta(hours=5)  # no tick from before 10:00 until 13:00
        fresh(states, back)
        await manager.tick(back)
        assert manager.document["status"] == "active"
        assert manager.document["active"]["grow_day"] == "2026-09-08"

    asyncio.run(scenario())


# ---------------------------------------------------------------- the lights-on hour changes
def test_a_lights_on_hour_moved_later_mid_day_keeps_the_day_and_never_errors(
    monkeypatch,
):
    manager, states, now = manager_fixture(monkeypatch)

    async def scenario():
        await running(manager, states, now, now + timedelta(hours=2))
        applied = copy.deepcopy(manager.document["active"])
        states[HOUR].state = "20"
        # At 12:00, and at the new 20:00 lights-on of the same date.
        for at in (now + timedelta(hours=4), now + timedelta(hours=12, seconds=30)):
            fresh(states, at)
            await manager.tick(at)
            assert manager.document["status"] == "active"
            assert manager.document["active"] == applied
            assert manager.degraded_reason is None
        next_day = now + timedelta(days=1, hours=12, seconds=30)
        fresh(states, next_day)
        await manager.tick(next_day)
        assert manager.document["active"]["grow_day"] == "2026-09-09"

    asyncio.run(scenario())


def test_a_lights_on_hour_moved_earlier_is_followed_from_its_next_lights_on(
    monkeypatch,
):
    manager, states, now = manager_fixture(monkeypatch)

    async def scenario():
        await manager.async_init()
        await manager.save(plan(), 0)
        armed = now + timedelta(hours=4)  # 12:00, after the day's 10:00 lights-on
        fresh(states, armed)
        await manager.activate(1, armed)
        states[HOUR].state = "6"
        assert manager.response(armed)["armed_after"] == "2026-09-09T06:00:00+00:00"
        # It used to wait for 10:00, and then for a whole extra day.
        early = datetime(2026, 9, 9, 6, 0, 30, tzinfo=timezone.utc)
        fresh(states, early)
        await manager.tick(early)
        assert manager.document["status"] == "active"
        assert manager.document["active"]["grow_day"] == "2026-09-09"

    asyncio.run(scenario())


# ---------------------------------------------------------------- a daylight-saving gap
def test_a_lights_on_hour_inside_the_daylight_saving_gap_still_starts_the_day(
    monkeypatch,
):
    """Pacific/Auckland on 27 September 2026 goes from 02:00 straight to 03:00."""
    manager, states, _ = manager_fixture(monkeypatch)
    nz = ZoneInfo("Pacific/Auckland")
    states[HOUR].state = "2"

    async def scenario():
        await manager.async_init()
        await manager.save(plan(), 0)
        armed = datetime(2026, 9, 25, 12, 0, tzinfo=nz)
        fresh(states, armed)
        await manager.activate(1, armed)
        for at, day in (
            (datetime(2026, 9, 26, 2, 0, 30, tzinfo=nz), "2026-09-26"),
            (datetime(2026, 9, 27, 1, 59, tzinfo=nz), "2026-09-26"),
            (datetime(2026, 9, 27, 3, 0, 30, tzinfo=nz), "2026-09-27"),
            (datetime(2026, 9, 28, 2, 0, 30, tzinfo=nz), "2026-09-28"),
        ):
            fresh(states, at)
            await manager.tick(at)
            assert manager.document["status"] == "active", at
            assert manager.document["active"]["grow_day"] == day, at
            assert manager.degraded_reason is None, at

    asyncio.run(scenario())


# ---------------------------------------------------------------- what is still an error
def test_zones_that_no_longer_match_the_plan_are_an_error_stored_once(monkeypatch):
    manager, states, now = manager_fixture(monkeypatch)
    saves = []

    async def scenario():
        await running(manager, states, now, now + timedelta(hours=2))
        store_save = manager._store.async_save

        async def counted(value):
            saves.append(value["status"])
            await store_save(value)

        manager._store.async_save = counted
        manager._config()["num_zones"] = 2
        for minutes in (1, 2, 3):
            await manager.tick(now + timedelta(hours=2, minutes=minutes))
        assert manager.document["status"] == "error"
        assert states[manager.entity_id].attributes["enabled"] is True
        assert saves == ["error"]  # not rewritten every minute

    asyncio.run(scenario())


# ---------------------------------------------------------------- a zone change while armed
def _managed(hass, status, zones=(1, 2)):
    manager = SimpleNamespace(
        document={"status": status, "plan": {"zones": [{"zone_id": z} for z in zones]}}
    )
    hass.data["crop_steering"] = {"_strategy": {"one": manager}}
    return manager


@pytest.mark.parametrize("status", ["armed", "active", "disarming", "error"])
def test_a_zone_change_is_refused_while_a_plan_manages_the_room(status):
    hass, _, _ = rig()
    _managed(hass, status)
    with pytest.raises(ValueError, match="disarm it"):
        asyncio.run(api.save_setup(hass, payload()))  # archives zone 1
    assert not hass.config_entries.updates


def test_archiving_the_room_is_refused_while_a_plan_manages_it():
    hass, _, _ = rig()
    _managed(hass, "active")
    request = {"entry_id": "one", "expected_revision": 0, "confirm_name": "Veg"}
    with pytest.raises(ValueError, match="archiving"):
        asyncio.run(api.remove_setup(hass, request))
    assert not hass.config_entries.updates


def test_a_draft_plan_or_an_unchanged_zone_set_leaves_setup_alone():
    hass, entry, _ = rig()
    manager = _managed(hass, "active")
    renamed = {**copy.deepcopy(entry.data), "room_name": "Veg 2"}
    assert api.safety_blockers(hass, entry, renamed) == []
    manager.document["status"] = "draft"
    asyncio.run(api.save_setup(hass, payload()))
    assert hass.config_entries.updates


def test_a_change_back_to_the_plans_own_zones_is_allowed():
    hass, _, _ = rig()
    _managed(hass, "error", zones=(2,))  # the room got out of step with its plan
    # Archiving zone 1 leaves zone 2 only, as planned.
    asyncio.run(api.save_setup(hass, payload()))
    assert hass.config_entries.updates
