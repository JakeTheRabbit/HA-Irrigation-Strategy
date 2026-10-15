"""The plan sensor says what kind of thing keeps the day from moving on (`degraded_kind`).

The controller reads it to tell a plan day held by a stale moisture probe (which only the brain may bridge, with
the envelope's agreement) from one held by anything else. Every kind comes from a typed refusal, never from the
reason's wording; an integration before this one publishes no kind, and a controller reads that as unknown.
"""

import asyncio
from datetime import timedelta

from .test_plan_day_per_zone import running, two_zones
from .test_plan_never_holds_a_room_all_day import HEARTBEAT, HOUR, fresh


def _kind(manager, states):
    published = states[manager.entity_id].attributes
    assert published["degraded_kind"] == manager.degraded_kind
    assert manager.response()["degraded_kind"] == manager.degraded_kind
    return manager.degraded_kind


def test_each_refusal_publishes_its_kind_and_none_when_the_day_moved_on(monkeypatch):
    manager, states, now = two_zones(monkeypatch)

    async def scenario():
        nxt = await running(manager, states, now)
        assert _kind(manager, states) is None
        at = nxt + timedelta(seconds=30)
        fresh(states, at)
        states[HEARTBEAT].last_updated = at - timedelta(minutes=10)
        await manager.tick(at)
        assert _kind(manager, states) == "heartbeat"
        fresh(states, at)
        for zone in (1, 2):
            states[f"sensor.crop_steering_vwc_zone_{zone}"].last_updated = now
        await manager.tick(at)
        assert _kind(manager, states) == "probe_stale"
        fresh(states, at)
        states["switch.crop_steering_zone_2_enabled"].state = "unavailable"
        await manager.tick(at)
        assert _kind(manager, states) == "flags"
        fresh(states, at)
        states["switch.crop_steering_zone_2_enabled"].state = "on"
        states[HOUR].state = "unknown"
        await manager.tick(at)
        assert _kind(manager, states) == "lights_hour"
        states[HOUR].state = "10"
        fresh(states, at)
        await manager.tick(at)
        assert _kind(manager, states) is None
        assert manager.document["active"]["grow_day"] == "2026-09-09"

    asyncio.run(scenario())


def test_one_held_zone_is_a_stale_probe_until_it_reads_again(monkeypatch):
    manager, states, now = two_zones(monkeypatch)

    async def scenario():
        nxt = await running(manager, states, now)
        at = nxt + timedelta(seconds=30)
        fresh(states, at)
        states["sensor.crop_steering_vwc_zone_2"].last_updated = now
        await manager.tick(at)
        assert manager.document["active"]["grow_day"] == "2026-09-09"
        assert _kind(manager, states) == "probe_stale"
        fresh(states, at + timedelta(minutes=5))
        await manager.tick(at + timedelta(minutes=5))
        assert _kind(manager, states) is None

    asyncio.run(scenario())
