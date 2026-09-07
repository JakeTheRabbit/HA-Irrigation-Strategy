"""Exercise real sensor methods without importing Home Assistant's entity runtime."""

import ast
import logging
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = (
    Path(__file__).resolve().parents[1] / "custom_components/crop_steering/sensor.py"
)


def sensor(states, prefix=""):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    original = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "CropSteeringSensor"
    )
    names = {
        "_get_zone_weekly_water_usage",
        "_get_zone_daily_water_usage",
        "extra_state_attributes",
        "_average_sensor_values",
    }
    methods = [
        node
        for node in original.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    cls = ast.ClassDef(
        name="SensorMethods", bases=[], keywords=[], body=methods, decorator_list=[]
    )
    module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    namespace = {"math": math, "_LOGGER": logging.getLogger(__name__)}
    exec(compile(module, str(SOURCE), "exec"), namespace)
    instance = namespace["SensorMethods"]()
    instance.hass = SimpleNamespace(states=SimpleNamespace(get=states.get))
    instance._prefix = prefix
    instance._zone_number = 1
    instance.entity_description = SimpleNamespace(key="zone_1_weekly_water_usage")
    return instance


@pytest.mark.parametrize(
    "value", [None, "unknown", "unavailable", "NaN", "inf", "-1", "bad"]
)
def test_missing_or_invalid_weekly_source_is_unknown(value):
    states = (
        {}
        if value is None
        else {
            "sensor.crop_steering_zone_1_weekly_water_app": SimpleNamespace(
                state=value, attributes={}
            )
        }
    )
    entity = sensor(states)
    assert entity._get_zone_weekly_water_usage(1) is None
    assert entity.extra_state_attributes == {
        "coverage": "unknown",
        "history_complete": False,
    }


def test_weekly_consumer_uses_own_room_and_forwards_partial_coverage():
    attrs = {
        "coverage": "partial_history",
        "history_complete": False,
        "observed_grow_days": 2,
        "complete_grow_days": 1,
    }
    entity = sensor(
        {
            "sensor.crop_steering_zone_1_weekly_water_app": SimpleNamespace(
                state="999", attributes={}
            ),
            "sensor.crop_steering_veg_zone_1_weekly_water_app": SimpleNamespace(
                state="0", attributes=attrs
            ),
        },
        "veg_",
    )
    assert entity._get_zone_weekly_water_usage(1) == 0
    assert entity.extra_state_attributes == attrs


def test_fusion_rejects_nonfinite_without_changing_arithmetic_mean():
    values = {
        "sensor.a": "10",
        "sensor.b": "40",
        "sensor.c": "100",
        "sensor.nan": "NaN",
        "sensor.inf": "inf",
        "sensor.neg_inf": "-inf",
        "sensor.offline": "unavailable",
        "sensor.bad": "not a number",
    }
    entity = sensor(
        {key: SimpleNamespace(state=value) for key, value in values.items()}
    )
    assert entity._average_sensor_values(list(values)) == 50.0
    assert (
        entity._average_sensor_values(["sensor.nan", "sensor.inf", "sensor.neg_inf"])
        is None
    )


def test_weekly_descriptor_allows_rolling_total_to_decrease():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    descriptor = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "SensorEntityDescription"
        and any(
            keyword.arg == "key" and "weekly_water_usage" in ast.unparse(keyword.value)
            for keyword in node.keywords
        )
    )
    state_class = next(
        keyword.value for keyword in descriptor.keywords if keyword.arg == "state_class"
    )
    assert ast.unparse(state_class) == "SensorStateClass.TOTAL"


@pytest.mark.parametrize(
    "value", [None, "unknown", "unavailable", "", "NaN", "inf", "-inf", "-1", "bad"]
)
def test_invalid_daily_source_is_unknown(value):
    entity = sensor(
        {
            "sensor.crop_steering_zone_1_daily_water_app": SimpleNamespace(
                state=value, attributes={}
            )
        }
    )
    assert entity._get_zone_daily_water_usage(1) is None


@pytest.mark.parametrize("prefix", ["", "veg_"])
def test_missing_daily_source_does_not_borrow_another_room_or_zone(prefix):
    other_prefix = "veg_" if not prefix else ""
    entity = sensor(
        {
            f"sensor.crop_steering_{other_prefix}zone_1_daily_water_app": SimpleNamespace(
                state="999", attributes={}
            ),
            f"sensor.crop_steering_{prefix}zone_2_daily_water_app": SimpleNamespace(
                state="888", attributes={}
            ),
        },
        prefix,
    )
    assert entity._get_zone_daily_water_usage(1) is None


@pytest.mark.parametrize("value", [0, 1.25])
def test_daily_consumer_preserves_named_room_zero_and_positive_delivery(value):
    entity = sensor(
        {
            "sensor.crop_steering_zone_1_daily_water_app": SimpleNamespace(
                state="999", attributes={}
            ),
            "sensor.crop_steering_veg_zone_1_daily_water_app": SimpleNamespace(
                state=str(value), attributes={}
            ),
        },
        "veg_",
    )
    assert entity._get_zone_daily_water_usage(1) == value
