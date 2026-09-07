"""Versioned strategy plans are isolated, explicit, and hydraulically reproducible."""

import copy
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.crop_steering.strategy_model import (
    REQUIRED_PARAMETERS,
    dryback_target_vwc,
    hydraulic_preview,
    interpolate,
    normalize_plan,
    preview_zone,
)
from custom_components.crop_steering.strategy import StrategyManager
from custom_components.crop_steering.strategy_api import resolve_manager
from custom_components.crop_steering.sizing import configured_sizing, prefer_setup_value


class MemoryStore:
    def __init__(self, data=None):
        self.data = data

    async def async_load(self):
        return copy.deepcopy(self.data)

    async def async_save(self, value):
        self.data = copy.deepcopy(value)


def manager_fixture(monkeypatch, prefix="", store=None):
    from custom_components.crop_steering import strategy

    now = datetime(2026, 9, 8, 8, tzinfo=timezone.utc)
    monkeypatch.setattr(strategy, "_now", lambda: now)
    states = {}

    def put(eid, value, attributes=None):
        states[eid] = SimpleNamespace(
            entity_id=eid,
            state=str(value),
            attributes=attributes or {},
            last_updated=now,
        )

    veg, _ = endpoints()
    for key, value in veg.items():
        for native in strategy.MODE_KEYS.get(key, (key,)):
            put(
                f"number.crop_steering_{prefix}zone_1_{native}",
                value,
                {"min": 0, "max": 100, "step": 0.1},
            )
    for key, value in {
        "substrate_volume": 6,
        "plant_count": 36,
        "drippers_per_plant": 1,
        "dripper_flow_rate": 4,
        "max_shot_duration": 900,
        "lights_on_hour": 10,
    }.items():
        put(
            f"number.crop_steering_{prefix}{key}",
            value,
            {"min": 0, "max": 1000, "step": 0.1},
        )
    put(f"sensor.crop_steering_{prefix}vwc_zone_1", 60)
    put(f"sensor.crop_steering_{prefix}ec_zone_1", 3)
    put(f"switch.crop_steering_{prefix}zone_1_enabled", "on")
    flag = f"switch.crop_steering_{prefix}engine_enabled"
    put(flag, "off")
    put(
        f"sensor.crop_steering_{prefix}ai_heartbeat",
        "healthy",
        {"enable_flag": flag, "strategy_snapshot_version": 1},
    )
    state_api = SimpleNamespace(
        get=states.get,
        async_set=lambda eid, state, attributes: put(eid, state, attributes),
    )
    entry = SimpleNamespace(
        entry_id=prefix or "default", data={"room_prefix": prefix}, options={}
    )
    hass = SimpleNamespace(
        states=state_api,
        data={"crop_steering": {entry.entry_id: {"num_zones": 1, "zones": {"1": {}}}}},
    )
    manager = StrategyManager(hass, entry, store or MemoryStore())
    return manager, states, now


def endpoints():
    veg = {
        "dryback_target": 10,
        "ec_target_p0": 2,
        "ec_target_p1": 3,
        "ec_target_p2": 4,
        "p1_target_vwc": 65,
        "p2_vwc_threshold": 50,
        "p2_shot_size": 4,
        "p1_initial_shot_size": 6,
        "p3_emergency_vwc_threshold": 30,
        "p3_emergency_shot_size": 2,
    }
    gen = {
        **veg,
        "dryback_target": 20,
        "ec_target_p0": 3,
        "ec_target_p1": 4,
        "ec_target_p2": 5,
        "p1_target_vwc": 60,
    }
    return veg, gen


def plan():
    veg, gen = endpoints()
    return {
        "schema_version": 1,
        "profiles": [
            {
                "id": "base",
                "name": "Grower profile",
                "vegetative": veg,
                "generative": gen,
            }
        ],
        "zones": [
            {
                "zone_id": 1,
                "start_date": "2026-09-08",
                "schedule": [
                    {"start_day": 1, "end_day": 84, "profile_id": "base", "bias": 50}
                ],
            }
        ],
    }


def catalog():
    return {
        1: {key: {"min": 0, "max": 100, "step": 0.1} for key in REQUIRED_PARAMETERS}
    }


def test_interpolation_is_continuous_and_controls_both_legacy_modes():
    veg, gen = endpoints()
    mid = interpolate(veg, gen, 25)
    assert mid["dryback_target"] == 12.5
    assert mid["ec_target_p0"] == 2.25
    assert mid["ec_target_p1"] == 3.25
    assert mid["ec_target_p2"] == 4.25
    assert interpolate(veg, gen, 0) == veg
    assert interpolate(veg, gen, 100) == gen
    assert dryback_target_vwc(60, 10) == 54


def test_quantization_uses_javascript_round_tie_direction_at_native_step():
    values = interpolate(
        {"p1_target_vwc": 60},
        {"p1_target_vwc": 65},
        50,
        {"p1_target_vwc": {"min": 0, "max": 100, "step": 1}},
    )
    assert values["p1_target_vwc"] == 63


def test_plan_rejects_foreign_zones_bounds_nan_and_overlapping_days():
    for mutate in (
        lambda p: p["zones"][0].update(zone_id=2),
        lambda p: p["profiles"][0]["vegetative"].update(p1_target_vwc=101),
        lambda p: p["zones"][0]["schedule"][0].update(bias=float("nan")),
        lambda p: p["zones"][0]["schedule"].append(
            {"start_day": 80, "end_day": 90, "profile_id": "base", "bias": 50}
        ),
    ):
        draft = plan()
        mutate(draft)
        with pytest.raises(ValueError):
            normalize_plan(draft, [1], catalog())


def test_week_assignments_normalize_to_exact_daily_ranges():
    draft = plan()
    draft["zones"][0]["schedule"] = [
        {"start_week": 1, "end_week": 12, "profile_id": "base", "bias": 25}
    ]
    normalized = normalize_plan(draft, [1], catalog())
    assert normalized["zones"][0]["schedule"][0]["end_day"] == 84
    assert preview_zone(normalized, 1, "2026-09-14")["day"] == 7
    assert preview_zone(normalized, 1, "2026-09-07")["status"] == "waiting"
    assert preview_zone(normalized, 1, "2026-12-01")["status"] == "complete"


def test_hydraulics_are_zone_total_with_per_plant_substrate_units():
    preview = hydraulic_preview(
        {
            "substrate_l_per_plant": 6,
            "plant_count": 36,
            "drippers_per_plant": 1,
            "dripper_flow_lph": 4,
            "max_shot_duration": 900,
        },
        {"p1_initial_shot_size": 6},
    )
    assert preview["zone_substrate_l"] == 216
    assert preview["zone_flow_lps"] == 0.04
    assert preview["shots"]["p1_initial_shot_size"]["volume_l"] == 12.96
    assert preview["shots"]["p1_initial_shot_size"]["duration_s"] == 324
    with pytest.raises(ValueError):
        hydraulic_preview({"plant_count": 0}, {})


def test_plan_does_not_mutate_input_and_has_no_implicit_activation():
    draft = plan()
    original = copy.deepcopy(draft)
    result = normalize_plan(draft, [1], catalog())
    assert draft == original
    assert "enabled" not in result and "active" not in result


def test_explicit_sizing_updates_once_without_overriding_legacy_or_later_ha_tuning():
    entry = SimpleNamespace(
        data={"zones": {"1": {"plant_count": 36}}, "setup_revision": 1}, options={}
    )
    assert configured_sizing(entry, 1) == ({"plant_count": 36}, 1)
    assert prefer_setup_value({}, 1, 36)
    assert not prefer_setup_value({}, 0, 36)
    assert not prefer_setup_value({"setup_revision": 1, "setup_value": 36}, 2, 36)
    assert prefer_setup_value({"setup_revision": 1, "setup_value": 36}, 2, 40)


def test_old_config_load_seeds_draft_and_never_writes_hardware(monkeypatch):
    manager, states, _ = manager_fixture(monkeypatch)
    asyncio.run(manager.async_init())
    assert manager.response()["status"] == "draft"
    assert states[manager.entity_id].attributes["enabled"] is False
    assert states["switch.crop_steering_engine_enabled"].state == "off"


def test_activation_requires_capability_and_only_changes_at_grow_day_boundary(
    monkeypatch,
):
    manager, states, now = manager_fixture(monkeypatch)

    async def scenario():
        await manager.async_init()
        await manager.save(plan(), 0)
        heartbeat = states["sensor.crop_steering_ai_heartbeat"]
        heartbeat.attributes.pop("strategy_snapshot_version")
        with pytest.raises(ValueError, match="snapshot_version"):
            await manager.activate(1, now)
        assert manager.document["status"] == "draft"
        heartbeat.attributes["strategy_snapshot_version"] = 1
        await manager.activate(1, now)
        assert manager.document["status"] == "armed"
        await manager.tick(now + timedelta(hours=1))
        assert manager.document["active"]["zones"] == []
        boundary = now + timedelta(hours=2)
        for state in states.values():
            state.last_updated = boundary
        await manager.tick(boundary)
        assert manager.document["status"] == "active"
        assert (
            manager.document["active"]["zones"][0]["parameters"]["dryback_target"] == 15
        )
        assert states["switch.crop_steering_engine_enabled"].state == "off"
        with pytest.raises(ValueError, match="Disarm"):
            await manager.save(plan(), 1)
        await manager.disarm(boundary + timedelta(minutes=1))
        await manager.tick(boundary + timedelta(hours=1))
        assert manager.document["status"] == "disarming"
        await manager.tick(boundary + timedelta(days=1))
        assert manager.document["status"] == "draft"
        assert states[manager.entity_id].attributes["release_legacy"] is True

    asyncio.run(scenario())


def test_stale_probe_holds_activation_and_room_resolution_never_falls_back(monkeypatch):
    manager, states, now = manager_fixture(monkeypatch, "f2_")

    async def scenario():
        await manager.async_init()
        await manager.save(plan(), 0)
        states["sensor.crop_steering_f2_vwc_zone_1"].last_updated = now - timedelta(
            hours=1
        )
        with pytest.raises(ValueError, match="stale"):
            await manager.activate(1, now)
        manager.hass.data["crop_steering"]["_strategy"] = {
            manager.entry.entry_id: manager
        }
        assert resolve_manager(manager.hass, "room:f2_") is manager
        with pytest.raises(ValueError):
            resolve_manager(manager.hass, "room:")
        with pytest.raises(ValueError):
            resolve_manager(manager.hass, "f2")

    asyncio.run(scenario())


def test_active_store_survives_reload_without_midday_reapplication(monkeypatch):
    manager, states, now = manager_fixture(monkeypatch)
    store = manager._store

    async def scenario():
        await manager.async_init()
        await manager.save(plan(), 0)
        await manager.activate(1, now)
        boundary = now + timedelta(hours=2)
        for state in states.values():
            state.last_updated = boundary
        await manager.tick(boundary)
        restored, _, _ = manager_fixture(monkeypatch, store=store)
        await restored.async_init()
        assert restored.document["active"] == manager.document["active"]
        await restored.tick(boundary + timedelta(days=1, hours=3))
        assert restored.document["status"] == "error"
        assert "missed" in restored.document["error"]

    asyncio.run(scenario())


def test_corrupt_storage_never_arms_seeded_defaults_at_boundary(monkeypatch):
    manager, states, now = manager_fixture(
        monkeypatch, store=MemoryStore({"storage_version": 99})
    )

    async def scenario():
        await manager.async_init()
        boundary = now + timedelta(hours=2)
        for state in states.values():
            state.last_updated = boundary
        await manager.tick(boundary)
        assert manager.document["status"] == "error"
        assert manager.document["active"]["zones"] == []
        assert states[manager.entity_id].attributes["enabled"] is True

    asyncio.run(scenario())


def test_activation_storage_failure_keeps_draft_disarmed(monkeypatch):
    manager, states, now = manager_fixture(monkeypatch)

    async def scenario():
        await manager.async_init()
        await manager.save(plan(), 0)

        async def fail(_data):
            raise OSError("disk unavailable")

        manager._store.async_save = fail
        with pytest.raises(OSError):
            await manager.activate(1, now)
        assert manager.document["status"] == "draft"
        assert states[manager.entity_id].attributes["enabled"] is False

    asyncio.run(scenario())


def test_disarm_waits_for_next_boundary_and_survives_missed_boundary_restart(
    monkeypatch,
):
    manager, states, now = manager_fixture(monkeypatch)

    async def scenario():
        await manager.async_init()
        await manager.save(plan(), 0)
        await manager.activate(1, now)
        boundary = now + timedelta(hours=2)
        for state in states.values():
            state.last_updated = boundary
        await manager.tick(boundary)
        await manager.disarm(boundary + timedelta(seconds=30))
        await manager.tick(boundary + timedelta(minutes=1))
        assert manager.document["status"] == "disarming"
        restored, new_states, _ = manager_fixture(monkeypatch, store=manager._store)
        await restored.async_init()
        await restored.tick(boundary + timedelta(days=1, hours=4))
        for state in new_states.values():
            state.last_updated = boundary + timedelta(days=2)
        await restored.tick(boundary + timedelta(days=2))
        assert restored.document["status"] == "draft"
        assert restored.document["active"]["zones"] == []
        assert restored.document["release_legacy"] is True

    asyncio.run(scenario())


def test_setup_zone_changes_hold_active_plan_and_refresh_catalog(monkeypatch):
    manager, states, now = manager_fixture(monkeypatch)

    async def scenario():
        await manager.async_init()
        await manager.save(plan(), 0)
        await manager.activate(1, now)
        boundary = now + timedelta(hours=2)
        for state in states.values():
            state.last_updated = boundary
        await manager.tick(boundary)
        manager._config()["num_zones"] = 2
        await manager.tick(boundary + timedelta(minutes=1))
        assert manager.document["status"] == "error"
        assert "setup" in manager.document["error"].lower()
        assert set(manager.response()["catalog"]) == {1, 2}
        assert len(manager.document["plan"]["zones"]) == 1

    asyncio.run(scenario())


def test_plan_requires_every_current_zone_without_implicit_legacy_zones():
    with pytest.raises(ValueError, match="setup"):
        normalize_plan(plan(), [1, 2], {**catalog(), 2: catalog()[1]})


def test_strategy_catalog_respects_actual_controller_clamps(monkeypatch):
    manager, _, _ = manager_fixture(monkeypatch)
    fields = manager.catalog()[1]
    assert fields["p1_target_vwc"]["min"] == 20
    assert fields["p1_target_vwc"]["max"] == 85
    assert fields["dryback_target"]["max"] == 60
    invalid = plan()
    invalid["profiles"][0]["vegetative"]["p1_target_vwc"] = 90
    with pytest.raises(ValueError, match="bounds"):
        normalize_plan(invalid, [1], manager.catalog())


def test_strategy_bounds_match_canonical_engine_validation():
    import ast
    from pathlib import Path
    from custom_components.crop_steering.strategy_model import ENGINE_BOUNDS

    source = (
        Path(__file__).parents[1]
        / "crop-steering-engine/src/crop_steering_engine/core.py"
    )
    tree = ast.parse(source.read_text(encoding="utf-8"))
    actual = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_PARAM_BOUNDS"
            for target in node.targets
        )
    )
    aliases = {
        "p1_target_vwc": "p1_target",
        "p2_vwc_threshold": "p2_threshold",
        "p3_emergency_vwc_threshold": "p3_emergency_floor",
        "maximum_ec": "max_ec",
        "p1_initial_shot_size": "p1_initial",
        "p1_shot_size_increment": "p1_incr",
        "p1_maximum_shots": "p1_max_shots",
        "p1_time_between_shots": "p1_time_between_min",
        "p0_maximum_wait_time": "p0_max_wait_min",
        "p3_emergency_shot_size": "p3_emergency_shot",
    }
    for key, bounds in ENGINE_BOUNDS.items():
        assert actual[aliases.get(key, key)] == bounds
