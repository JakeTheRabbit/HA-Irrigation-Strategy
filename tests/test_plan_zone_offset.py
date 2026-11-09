"""A zone's VWC offset on an armed or active plan (strategy_zone_offset): the plan follows the probe.

F1, 9 Nov 2026: a reseated probe read about 15 points lower, the plan kept a P1 target and P2 threshold the zone
could never reach, and the zone was overwatered for 10 days. The offset moves one zone's four moisture levels
by the same points, at once, without touching the plan, its revision or the draft.
"""

import asyncio
from datetime import timedelta

import pytest

from custom_components.crop_steering.strategy_model import (
    apply_offset,
    check_offset,
)
from .test_strategy import MemoryStore, manager_fixture, plan

LADDER = {
    "field_capacity": 64.0,
    "p1_target_vwc": 61.0,
    "p2_vwc_threshold": 54.0,
    "p3_emergency_vwc_threshold": 40.0,
    "p2_shot_size": 4.0,
}
BOUNDS = {
    "field_capacity": {"min": 40, "max": 80, "step": 0.1},
    "p1_target_vwc": {"min": 30, "max": 80, "step": 0.1},
    "p2_vwc_threshold": {"min": 20, "max": 75, "step": 0.1},
    "p3_emergency_vwc_threshold": {"min": 10, "max": 50, "step": 0.1},
}


def test_an_offset_moves_the_four_moisture_levels_and_nothing_else():
    out = apply_offset(LADDER, -8, BOUNDS)
    assert out == {
        "field_capacity": 56.0,
        "p1_target_vwc": 53.0,
        "p2_vwc_threshold": 46.0,
        "p3_emergency_vwc_threshold": 32.0,
        "p2_shot_size": 4.0,
    }
    assert apply_offset(LADDER, 0, BOUNDS) == LADDER


def test_each_level_is_clamped_to_its_setting_and_step():
    out = apply_offset(LADDER, 18, BOUNDS)
    assert out["field_capacity"] == 80  # 82 clamped to its max
    assert out["p1_target_vwc"] == 79
    out = apply_offset(
        LADDER, -3.33, {k: {**b, "step": 0.5} for k, b in BOUNDS.items()}
    )
    assert out["p1_target_vwc"] == 57.5


def test_a_clamp_that_would_break_the_order_pushes_the_lower_rungs_down():
    # P1 stops at its max of 72 while P2 would go on to 73: P2 is put a step under P1, P3 stays 3 under P2
    tight = {**BOUNDS, "p1_target_vwc": {"min": 30, "max": 72, "step": 0.1}}
    out = apply_offset(LADDER, 19, tight)
    assert (
        out["field_capacity"],
        out["p1_target_vwc"],
        out["p2_vwc_threshold"],
        out["p3_emergency_vwc_threshold"],
    ) == (80, 72, 71.9, 50)
    # FC stops at its max of 66 under a P1 that would be 70: P1 is put at FC
    out = apply_offset(
        LADDER, 9, {**BOUNDS, "field_capacity": {"min": 40, "max": 66, "step": 0.1}}
    )
    assert (out["field_capacity"], out["p1_target_vwc"], out["p2_vwc_threshold"]) == (
        66,
        66,
        63,
    )


def test_only_a_minimum_that_leaves_no_room_refuses():
    # P2 cannot go under its minimum of 70, and P1 sits at 62: no order fits
    tight = {**BOUNDS, "p2_vwc_threshold": {"min": 70, "max": 75, "step": 0.1}}
    with pytest.raises(ValueError, match="no room for p2_vwc_threshold"):
        apply_offset(LADDER, 1, tight)


def test_the_offset_has_no_bound_of_its_own():
    assert check_offset(-35) == -35 and check_offset(42.5) == 42.5
    for bad in (float("nan"), float("inf"), True, "3"):
        with pytest.raises(ValueError):
            check_offset(bad)
    out = apply_offset(
        LADDER, -35, BOUNDS
    )  # each setting stops at its own minimum, in order
    assert (
        out["p1_target_vwc"],
        out["p2_vwc_threshold"],
        out["p3_emergency_vwc_threshold"],
    ) == (30, 20, 10)


def _active(monkeypatch):
    manager, states, now = manager_fixture(monkeypatch)
    boundary = now + timedelta(hours=2)

    async def scenario():
        await manager.async_init()
        await manager.save(plan(), 0)
        await manager.activate(1, now)
        for state in states.values():
            state.last_updated = boundary
        await manager.tick(boundary)

    asyncio.run(scenario())
    assert manager.document["status"] == "active"
    return manager, states, boundary


def test_an_offset_is_in_force_at_once_in_the_snapshot_and_the_preview(monkeypatch):
    manager, states, now = _active(monkeypatch)
    revision = manager.document["revision"]
    plan_before = manager.document["plan"]
    asyncio.run(manager.set_zone_offset(1, -6, "probe moved", now=now))
    row = states[manager.entity_id].attributes["zones"][0]
    assert row["vwc_offset"] == -6
    assert row["parameters"]["p1_target_vwc"] == 56.5  # 62.5 at bias 50, minus 6
    assert row["parameters"]["p2_vwc_threshold"] == 44
    assert row["parameters"]["p3_emergency_vwc_threshold"] == 24
    assert row["vwc_base"]["p1_target_vwc"] == 62.5
    assert row["applied_day"] == now.date().isoformat()
    preview = manager.preview(grow_day=now.date().isoformat())["zones"][0]
    assert preview["parameters"] == row["parameters"]
    assert manager.response()["offsets"] == {"1": -6}
    # the plan, its revision and the draft are untouched
    assert manager.document["revision"] == revision
    assert manager.document["plan"] == plan_before
    # a plan being drafted is previewed without it
    assert (
        manager.preview(plan(), now.date().isoformat())["zones"][0]["parameters"][
            "p1_target_vwc"
        ]
        == 62.5
    )


def test_the_next_lights_on_keeps_the_offset(monkeypatch):
    manager, states, now = _active(monkeypatch)
    asyncio.run(manager.set_zone_offset(1, -4, "probe moved", now=now))
    later = now + timedelta(days=1)
    for state in states.values():
        state.last_updated = later
    asyncio.run(manager.tick(later))
    row = states[manager.entity_id].attributes["zones"][0]
    assert row["applied_day"] == later.date().isoformat()
    assert row["parameters"]["p1_target_vwc"] == 58.5


def test_an_offset_needs_an_armed_or_active_plan_and_a_zone_in_it(monkeypatch):
    manager, _states, now = manager_fixture(monkeypatch)
    asyncio.run(manager.async_init())
    with pytest.raises(ValueError, match="armed or active"):
        asyncio.run(manager.set_zone_offset(1, -2, "x", now=now))
    manager, _states, now = _active(monkeypatch)
    with pytest.raises(ValueError, match="not in this room"):
        asyncio.run(manager.set_zone_offset(2, -2, "x", now=now))
    # past 20 points is fine: P1 62.5 - 25 = 37.5, P2 25, P3 5
    asyncio.run(manager.set_zone_offset(1, -25, "x", now=now))
    assert manager.offset(1) == -25


def test_a_clamped_level_pushes_the_ones_under_it_down(monkeypatch):
    manager, states, now = _active(monkeypatch)
    for eid, state in states.items():
        if eid.endswith("zone_1_p1_target_vwc"):
            state.attributes = {**state.attributes, "max": 66}
    asyncio.run(manager.set_zone_offset(1, 18, "x", now=now))
    params = states[manager.entity_id].attributes["zones"][0]["parameters"]
    assert (
        params["p1_target_vwc"],
        params["p2_vwc_threshold"],
        params["p3_emergency_vwc_threshold"],
    ) == (66, 65.9, 48)


def test_a_refused_offset_changes_nothing(monkeypatch):
    manager, states, now = _active(monkeypatch)
    before = states[manager.entity_id].attributes["zones"][0]["parameters"]
    # P1 2.5, and P2 and P3 at their minimum of 0: P3 cannot sit 3 under P2
    with pytest.raises(ValueError, match="no room"):
        asyncio.run(manager.set_zone_offset(1, -60, "x", now=now))
    assert manager.offset(1) == 0
    assert states[manager.entity_id].attributes["zones"][0]["parameters"] == before


def test_saving_or_arming_a_plan_resets_every_offset(monkeypatch):
    manager, _states, now = _active(monkeypatch)
    asyncio.run(manager.set_zone_offset(1, -5, "x", now=now))
    asyncio.run(manager.disarm(now))
    later = now + timedelta(days=1)
    for state in _states.values():
        state.last_updated = later
    asyncio.run(manager.tick(later))
    assert manager.document["status"] == "draft"
    asyncio.run(manager.save(plan(), manager.document["revision"]))
    assert manager.document["offsets"] == {}
    manager.document["offsets"] = {"1": -3}
    asyncio.run(manager.activate(manager.document["revision"], later))
    assert manager.document["offsets"] == {}


def test_a_document_stored_before_offsets_loads_with_none(monkeypatch):
    manager, _states, now = _active(monkeypatch)
    stored = dict(manager.document)
    stored.pop("offsets")
    old, _s, _n = manager_fixture(monkeypatch, store=MemoryStore(stored))
    asyncio.run(old.async_init())
    assert old.offset(1) == 0
    assert old.response()["offsets"] == {"1": 0.0}
    asyncio.run(old.set_zone_offset(1, -2, "x", now=now))
    assert old.offset(1) == -2
