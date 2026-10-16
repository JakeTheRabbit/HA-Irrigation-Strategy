"""A plan's profile may carry climate and feed bands for reference only (the planner's reference rows,
Settings > Display). Optional and additive: a profile without them, every plan stored before this
release among them, normalises exactly as before; a half-typed or unknown band is dropped, never the
plan; the controller's snapshot never carries them."""

import asyncio
import json

from custom_components.crop_steering.strategy_model import (
    normalize_plan,
    reference_bands,
)

from .test_strategy import catalog, manager_fixture, plan


def _with(reference):
    p = plan()
    p["profiles"][0]["reference"] = reference
    return p


def test_a_profile_without_reference_normalises_exactly_as_before():
    normalized = normalize_plan(plan(), [1], catalog())
    assert all("reference" not in profile for profile in normalized["profiles"])


def test_only_whole_known_in_range_bands_are_kept():
    kept = normalize_plan(
        _with(
            {
                "humidity": [55, 65],
                "vpd": [1.2, None],
                "co2": [800, 9000],
                "feed_ph": [5.6, 6.2],
                "temp_day": [28, 24],
                "wind": [1, 2],
            }
        ),
        [1],
        catalog(),
    )["profiles"][0]
    assert kept["reference"] == {"humidity": [55, 65], "feed_ph": [5.6, 6.2]}
    assert (
        "reference"
        not in normalize_plan(_with({"vpd": [None, None]}), [1], catalog())["profiles"][
            0
        ]
    )
    assert reference_bands("not a dict") == {}


def test_reference_is_stored_and_never_reaches_the_controller(monkeypatch):
    manager, _states, _now = manager_fixture(monkeypatch)

    async def scenario():
        await manager.async_init()
        await manager.save(_with({"vpd": [1.0, 1.3]}), 0)
        assert manager.response()["plan"]["profiles"][0]["reference"] == {
            "vpd": [1.0, 1.3]
        }
        assert "reference" not in json.dumps(manager.response().get("active", {}))
        json.dumps(manager.response())

    asyncio.run(scenario())
