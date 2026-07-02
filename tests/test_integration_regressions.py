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
