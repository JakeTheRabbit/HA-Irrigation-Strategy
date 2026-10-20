"""A grow plan may carry the grower's own name for it. Optional and additive: a plan without one, every plan
stored before this release among them, normalises byte for byte as before, so nothing a room has stored
changes when it loads."""

import asyncio
import copy
import json

import pytest

from custom_components.crop_steering.strategy_model import normalize_plan

from .test_strategy import catalog, manager_fixture, plan


def test_a_plan_without_a_name_normalises_exactly_as_before():
    normalized = normalize_plan(plan(), [1], catalog())
    assert "name" not in normalized
    assert list(normalized) == ["schema_version", "profiles", "zones"]


def test_a_name_is_kept_trimmed():
    named = dict(plan(), name="  Autumn run  ")
    assert normalize_plan(named, [1], catalog())["name"] == "Autumn run"


@pytest.mark.parametrize("bad", ["", "   ", "x" * 101, 7, ["a"]])
def test_a_name_that_is_not_one_is_refused(bad):
    with pytest.raises(ValueError, match="Plan name"):
        normalize_plan(dict(plan(), name=bad), [1], catalog())


def test_the_name_is_stored_and_handed_back(monkeypatch):
    manager, _states, _now = manager_fixture(monkeypatch)

    async def scenario():
        await manager.async_init()
        await manager.save(dict(plan(), name="Autumn run"), 0)
        assert manager.response()["plan"]["name"] == "Autumn run"
        assert manager._store.data["plan"]["name"] == "Autumn run"
        unnamed = copy.deepcopy(manager.document["plan"])
        unnamed.pop("name")
        await manager.save(unnamed, 1)
        assert "name" not in manager.response()["plan"]
        json.dumps(manager.response())

    asyncio.run(scenario())
