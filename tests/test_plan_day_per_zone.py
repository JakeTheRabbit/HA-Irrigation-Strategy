"""One zone's stale probe never holds the whole room's plan day.

The plan used to wait at lights-on for every managed zone's moisture AND root-zone EC to be fresh, so one
zone's dead EC probe, or a flat one whose reading stopped moving, kept every zone on yesterday's targets
for as long as it lasted, while the engine itself waters a zone without EC on moisture alone. Now the
root-zone EC is never waited for, and a zone whose moisture reading is unusable keeps the targets it had
until it reads again, while every other zone moves on. A room with no zone reading, and a plan's first day,
still wait as before.
"""

import asyncio
from datetime import timedelta

from .test_plan_never_holds_a_room_all_day import fresh
from .test_strategy import endpoints, manager_fixture, plan


def two_zones(monkeypatch):
    manager, states, now = manager_fixture(monkeypatch)
    for eid, state in list(states.items()):
        if "zone_1_" in eid or eid.endswith("_zone_1"):
            clone = eid.replace("zone_1", "zone_2")
            states[clone] = type(state)(**{**vars(state), "entity_id": clone})
    manager.hass.data["crop_steering"]["default"].update(
        num_zones=2, zones={"1": {}, "2": {}}
    )
    return manager, states, now


def two_zone_plan(second_bias=50):
    doc = plan()
    veg, gen = endpoints()
    doc["profiles"].append(
        {"id": "late", "name": "Late", "vegetative": veg, "generative": gen}
    )
    doc["zones"][0]["schedule"] = [
        {"start_day": 1, "end_day": 1, "profile_id": "base", "bias": 0},
        {"start_day": 2, "end_day": 84, "profile_id": "late", "bias": 100},
    ]
    doc["zones"].append(
        {
            "zone_id": 2,
            "start_date": "2026-09-08",
            "schedule": [
                {"start_day": 1, "end_day": 1, "profile_id": "base", "bias": 0},
                {"start_day": 2, "end_day": 84, "profile_id": "late", "bias": 100},
            ],
        }
    )
    return doc


async def running(manager, states, now):
    await manager.async_init()
    await manager.save(two_zone_plan(), 0)
    await manager.activate(1, now)
    lights_on = now + timedelta(hours=2)
    fresh(states, lights_on)
    await manager.tick(lights_on)
    assert manager.document["active"]["grow_day"] == "2026-09-08"
    return now + timedelta(days=1, hours=2)  # the next lights-on


def _row(manager, zone):
    return next(r for r in manager.document["active"]["zones"] if r["zone_id"] == zone)


def test_a_stale_ec_probe_no_longer_holds_the_day(monkeypatch):
    manager, states, now = two_zones(monkeypatch)

    async def scenario():
        nxt = await running(manager, states, now)
        fresh(states, nxt)
        states["sensor.crop_steering_ec_zone_2"].last_updated = now  # silent for a day
        states["sensor.crop_steering_ec_zone_1"].state = "unavailable"
        await manager.tick(nxt + timedelta(seconds=30))
        assert manager.document["active"]["grow_day"] == "2026-09-09"
        for zone in (1, 2):
            row = _row(manager, zone)
            assert row["day"] == 2 and row["profile_id"] == "late"
            assert row["applied_day"] == "2026-09-09" and "held" not in row
        assert manager.degraded_reason is None

    asyncio.run(scenario())


def test_a_zone_without_moisture_keeps_its_targets_while_the_others_move_on(
    monkeypatch,
):
    manager, states, now = two_zones(monkeypatch)

    async def scenario():
        nxt = await running(manager, states, now)
        yesterday = dict(_row(manager, 2))
        fresh(states, nxt)
        states["sensor.crop_steering_vwc_zone_2"].last_updated = now
        await manager.tick(nxt + timedelta(seconds=30))
        assert manager.document["active"]["grow_day"] == "2026-09-09"
        assert _row(manager, 1)["day"] == 2
        held = _row(manager, 2)
        assert held["day"] == 1 and held["parameters"] == yesterday["parameters"]
        assert held["applied_day"] == "2026-09-08" and "VWC" in held["held"]
        published = states[manager.entity_id].attributes
        assert published["grow_day"] == "2026-09-09"
        assert (
            "zone 2 stays on the targets of 2026-09-08" in published["degraded_reason"]
        )
        # Its probe back: zone 2 gets the day too, on the next tick.
        later = nxt + timedelta(minutes=40)
        fresh(states, later)
        await manager.tick(later)
        released = _row(manager, 2)
        assert released["day"] == 2 and "held" not in released
        assert released["applied_day"] == "2026-09-09"
        assert manager.degraded_reason is None
        assert manager._store.data["active"] == manager.document["active"]

    asyncio.run(scenario())


def test_a_held_zone_stays_on_its_own_last_day_across_two_lights_on(monkeypatch):
    manager, states, now = two_zones(monkeypatch)

    async def scenario():
        nxt = await running(manager, states, now)
        for day in (0, 1):
            at = nxt + timedelta(days=day, seconds=30)
            fresh(states, at)
            states["sensor.crop_steering_vwc_zone_2"].last_updated = now
            await manager.tick(at)
        assert manager.document["active"]["grow_day"] == "2026-09-10"
        assert _row(manager, 1)["day"] == 3
        assert _row(manager, 2)["day"] == 1
        assert _row(manager, 2)["applied_day"] == "2026-09-08"

    asyncio.run(scenario())


def test_no_zone_reading_still_holds_the_room_on_its_last_day(monkeypatch):
    manager, states, now = two_zones(monkeypatch)

    async def scenario():
        nxt = await running(manager, states, now)
        before = dict(manager.document["active"])
        fresh(states, nxt)
        for zone in (1, 2):
            states[f"sensor.crop_steering_vwc_zone_{zone}"].last_updated = now
        await manager.tick(nxt + timedelta(seconds=30))
        assert manager.document["active"] == before
        assert "VWC" in manager.degraded_reason

    asyncio.run(scenario())


def test_a_plans_first_day_still_waits_for_every_zones_moisture(monkeypatch):
    manager, states, now = two_zones(monkeypatch)

    async def scenario():
        await manager.async_init()
        await manager.save(two_zone_plan(), 0)
        await manager.activate(1, now)
        lights_on = now + timedelta(hours=2)
        fresh(states, lights_on)
        states["sensor.crop_steering_vwc_zone_2"].last_updated = now - timedelta(
            hours=1
        )
        await manager.tick(lights_on)
        assert manager.document["status"] == "armed"
        assert "Zone 2 VWC" in manager.degraded_reason
        fresh(states, lights_on)
        states["sensor.crop_steering_ec_zone_2"].last_updated = now - timedelta(hours=1)
        await manager.tick(lights_on + timedelta(minutes=1))
        assert manager.document["status"] == "active"  # a stale EC never stops it

    asyncio.run(scenario())


def test_arming_needs_moisture_but_not_root_zone_ec(monkeypatch):
    manager, states, now = two_zones(monkeypatch)

    async def scenario():
        await manager.async_init()
        await manager.save(two_zone_plan(), 0)
        states["sensor.crop_steering_ec_zone_2"].last_updated = now - timedelta(hours=1)
        await manager.activate(1, now)
        assert manager.document["status"] == "armed"

    asyncio.run(scenario())


def test_an_old_stored_snapshot_without_applied_day_moves_on_as_before(monkeypatch):
    """A document a release before this one stored: its rows carry no applied_day and no held."""
    manager, states, now = two_zones(monkeypatch)

    async def scenario():
        nxt = await running(manager, states, now)
        for row in manager.document["active"]["zones"]:
            row.pop("applied_day")
        fresh(states, nxt)
        states["sensor.crop_steering_vwc_zone_2"].last_updated = now
        await manager.tick(nxt + timedelta(seconds=30))
        held = _row(manager, 2)
        assert held["applied_day"] == "2026-09-08" and held["day"] == 1

    asyncio.run(scenario())
