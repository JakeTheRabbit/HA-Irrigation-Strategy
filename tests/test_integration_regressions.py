"""Regression coverage for integration setup/entity descriptor bugs."""

from __future__ import annotations

import ast
import importlib.util
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_integration_init():
    spec = importlib.util.spec_from_file_location(
        "custom_components.crop_steering",
        ROOT / "custom_components" / "crop_steering" / "__init__.py",
        submodule_search_locations=[str(ROOT / "custom_components" / "crop_steering")],
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_entry_config_options_override_base_data():
    integration = _load_integration_init()
    entry = types.SimpleNamespace(
        data={"num_zones": 1, "room_slug": "default"},
        options={"num_zones": 3, "room_prefix": "flower_"},
    )

    assert integration._entry_config(entry) == {
        "num_zones": 3,
        "room_slug": "default",
        "room_prefix": "flower_",
    }


def test_dead_placeholder_sensor_descriptors_stay_removed():
    source = (ROOT / "custom_components" / "crop_steering" / "sensor.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    descriptor_keys = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    assert "irrigation_efficiency" not in descriptor_keys
    assert "dryback_percentage" not in descriptor_keys
    assert "water_usage_daily" not in descriptor_keys
    assert "next_irrigation_time" not in descriptor_keys


def test_setup_removes_only_this_rooms_retired_entities(monkeypatch):
    """_RETIRED is matched per platform, per room, and a zone key covers every zone's copy. The
    global P2 EC thresholds stay: only their per-zone copies were retired."""
    from homeassistant.helpers import entity_registry as er

    integration = _load_integration_init()
    head = "crop_steering_room-a_"
    items = [
        ("number", head + "zone_12_shot_size_multiplier", "number.multiplier"),
        ("number", head + "zone_3_p2_ec_high_threshold", "number.zone_copy"),
        ("number", head + "p2_ec_high_threshold", "number.global_kept"),
        ("sensor", head + "zone_3_shot_size_multiplier", "sensor.other_platform"),
        ("button", head + "zone_1_trigger_shot", "button.trigger"),
        (
            "switch",
            "crop_steering_room-b_zone_1_dripper_protection",
            "switch.other_room",
        ),
        ("switch", head + "zone_1_manual_override", "switch.kept"),
    ]
    removed = []
    monkeypatch.setattr(
        er,
        "async_get",
        lambda hass: types.SimpleNamespace(async_remove=removed.append),
        raising=False,
    )
    monkeypatch.setattr(
        er,
        "async_entries_for_config_entry",
        lambda registry, entry_id: [
            types.SimpleNamespace(domain=d, unique_id=u, entity_id=e)
            for d, u, e in items
        ],
        raising=False,
    )
    integration._remove_retired_entities(None, types.SimpleNamespace(entry_id="room-a"))
    assert removed == ["number.multiplier", "number.zone_copy", "button.trigger"]
