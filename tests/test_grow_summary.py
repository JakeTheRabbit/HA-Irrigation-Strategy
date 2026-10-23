"""Grow day, days to harvest and stage, published beside the plan sensor."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace

from custom_components.crop_steering.strategy import grow_summary

from .test_strategy import manager_fixture, plan


def _plan(last_end=63):
    doc = plan()
    doc["zones"][0]["schedule"] = [
        {"start_day": 1, "end_day": 20, "profile_id": "base", "bias": 0},
        {"start_day": 21, "end_day": last_end, "profile_id": "base", "bias": 100},
    ]
    doc["profiles"][0]["name"] = "Flower"
    return doc


def _row(day, zone=1, status="active"):
    return {"zone_id": zone, "day": day, "status": status, "profile_id": "base"}


def test_day_38_of_63_is_25_days_to_harvest():  # G16 accept
    out = grow_summary(_plan(), [_row(38)], "veg")
    assert out == {"grow_day": 38, "days_to_harvest": 25, "stage": "Flower"}


def test_no_active_plan_is_unknown():
    unknown = {"grow_day": "unknown", "days_to_harvest": "unknown", "stage": "unknown"}
    assert grow_summary(None, [], None) == unknown
    assert grow_summary(_plan(), [_row(40, status="complete")], None) == unknown


def test_lowest_numbered_active_zone_wins():
    out = grow_summary(_plan(), [_row(5, zone=3), _row(9, zone=2)], None)
    assert out["grow_day"] == 9


def test_open_ended_last_segment_has_unknown_days_to_harvest():
    out = grow_summary(_plan(last_end=None), [_row(38)], None)
    assert out["grow_day"] == 38 and out["days_to_harvest"] == "unknown"


def test_stage_falls_back_to_the_growth_stage_select():
    p = _plan()
    p["profiles"][0]["name"] = ""
    assert grow_summary(p, [_row(3)], "flower")["stage"] == "flower"
    assert grow_summary(p, [_row(3)], "unavailable")["stage"] == "unknown"
    assert grow_summary(p, [_row(3)], None)["stage"] == "unknown"


def test_old_install_publishes_unknown_and_does_not_error(monkeypatch):
    manager, states, now = manager_fixture(monkeypatch)
    manager._publish(now)
    for key in ("grow_day", "days_to_harvest", "stage"):
        assert states[f"sensor.crop_steering_{key}"].state == "unknown"


def test_publish_sets_the_three_sensors(monkeypatch):
    manager, states, now = manager_fixture(monkeypatch)
    states["select.crop_steering_growth_stage"] = SimpleNamespace(state="veg")

    async def scenario():
        await manager.async_init()
        await manager.save(_plan(), 0)
        await manager.activate(1, now)
        lights_on = now + timedelta(hours=2)
        for state in states.values():
            state.last_updated = lights_on
        await manager.tick(lights_on)

    asyncio.run(scenario())
    assert states["sensor.crop_steering_grow_day"].state == "1"
    assert states["sensor.crop_steering_days_to_harvest"].state == "62"
    assert states["sensor.crop_steering_stage"].state == "Flower"
