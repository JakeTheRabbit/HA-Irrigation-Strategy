"""Exercise real sensor methods without importing Home Assistant's entity runtime."""

import ast
import logging
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.crop_steering import units
from custom_components.crop_steering.calculations import ec_type_key, fuse_probes
from custom_components.crop_steering.const import (
    DOMAIN,
    PROBE_FAR,
    PROBE_RANGE,
    PROBE_STALE_SECONDS,
)
from custom_components.crop_steering.generated import shot_length
from custom_components.crop_steering.generated.defaults import CONTROLLER_FALLBACKS

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
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
        "_get_zone_last_irrigation",
        "native_value",
        "extra_state_attributes",
        "_active_zone_mean",
        "_get_zone_irrigation_count_today",
        "_shot_seconds_by_zone",
        "_zone_setting",
        "_probe_readings",
        "_fuse_zone",
        "_probe_method_entity",
        "_ec_types",
        "_get_zone_vwc",
        "_get_zone_ec",
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
    namespace = {
        "Any": Any,
        "math": math,
        "_LOGGER": logging.getLogger(__name__),
        "to_native": units.to_native,
        "fuse_probes": fuse_probes,
        "ec_type_key": ec_type_key,
        "DOMAIN": DOMAIN,
        "PROBE_FAR": PROBE_FAR,
        "PROBE_RANGE": PROBE_RANGE,
        "PROBE_STALE_SECONDS": PROBE_STALE_SECONDS,
        "SHOT_SIZE_KEYS": next(
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and getattr(node.targets[0], "id", None) == "SHOT_SIZE_KEYS"
        ),
        # absent before the retired sensors were: {} keeps this harness loading the old code
        "RETIRED_SENSORS": next(
            (
                ast.literal_eval(node.value)
                for node in tree.body
                if isinstance(node, ast.Assign)
                and getattr(node.targets[0], "id", None) == "RETIRED_SENSORS"
            ),
            {},
        ),
        "CONTROLLER_FALLBACKS": CONTROLLER_FALLBACKS,
        **{
            name: getattr(shot_length, name)
            for name in (
                "DEFAULT_MAX_SHOT_S",
                "raw_seconds",
                "shot_seconds",
                "valid_cap",
            )
        },
        "dt_util": SimpleNamespace(
            parse_datetime=datetime.fromisoformat,
            as_local=lambda value: value.replace(tzinfo=timezone.utc),
            utcnow=lambda: NOW,
        ),
    }
    exec(compile(module, str(SOURCE), "exec"), namespace)
    instance = namespace["SensorMethods"]()
    instance.hass = SimpleNamespace(states=SimpleNamespace(get=states.get))
    instance._prefix = prefix
    instance._zone_number = 1
    instance._zones_config = {}
    instance._probe_offsets = {}
    instance._offsets_at = None
    instance._fusion = None
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


def _probe_mean(entity, sensor_ids, kind=None):
    """The plain mean of each probe as _probe_readings converts it."""
    values = [
        value
        for _sensor_id, value, _age in entity._probe_readings(sensor_ids, kind)
        if value is not None and math.isfinite(value)
    ]
    return round(sum(values) / len(values), 2) if values else None


def _room(states, zones):
    entity = sensor({k: SimpleNamespace(state=v) for k, v in states.items()})
    entity._zones_config = zones
    return entity


def test_the_room_mean_is_of_its_active_zones_own_readings_only():
    """INT-010: it averaged every probe in the config, archived zones and probes a zone leaves out
    included. Each zone's own reading counts only its probes, fused as the controller reads them.
    """
    zones = {"1": {"active": True}, "2": {}, "3": {"active": False}}
    entity = _room(
        {
            "sensor.crop_steering_vwc_zone_1": "40",
            "sensor.crop_steering_vwc_zone_2": "44",
            "sensor.crop_steering_vwc_zone_3": "90",  # archived: not counted
            "sensor.crop_steering_ec_zone_1": "3.0",
            "sensor.crop_steering_ec_zone_2": "unknown",
        },
        zones,
    )
    assert entity._active_zone_mean("vwc") == 42.0
    assert entity._active_zone_mean("ec") == 3.0
    entity.entity_description = SimpleNamespace(key="configured_avg_vwc")
    assert entity.native_value == 42.0


def test_the_room_mean_skips_readings_that_are_not_numbers_and_is_unknown_without_any():
    zones = {"1": {}, "2": {}, "3": {}}
    entity = _room(
        {
            "sensor.crop_steering_veg_vwc_zone_1": "NaN",
            "sensor.crop_steering_veg_vwc_zone_2": "inf",
            "sensor.crop_steering_veg_vwc_zone_3": "not a number",
        },
        zones,
    )
    entity._prefix = "veg_"
    assert entity._active_zone_mean("vwc") is None
    assert entity._active_zone_mean("ec") is None  # no state at all


@pytest.mark.parametrize("value", [None, "unknown", "unavailable", "bad"])
def test_shots_today_without_the_controllers_count_is_unknown_not_zero(value):
    """INT-011: a stopped controller read as "0 shots today"."""
    states = (
        {}
        if value is None
        else {
            "sensor.crop_steering_zone_1_irrigation_count_app": SimpleNamespace(
                state=value
            )
        }
    )
    assert sensor(states)._get_zone_irrigation_count_today(1) is None


def test_shots_today_mirror_the_controllers_count():
    states = {
        "sensor.crop_steering_zone_1_irrigation_count_app": SimpleNamespace(state="3")
    }
    assert sensor(states)._get_zone_irrigation_count_today(1) == 3


@pytest.mark.parametrize("key", ["ec_ratio", "p2_vwc_threshold_adjusted"])
def test_a_retired_sensor_is_unknown_and_says_why(key):
    """CTL-011, INT-007: these computed a re-water point and an EC ratio the controller never used,
    from the select it does not read, with a missing number read as 0."""
    entity = sensor(
        {
            "select.crop_steering_irrigation_phase": SimpleNamespace(state="P2"),
            "select.crop_steering_steering_mode": SimpleNamespace(state="Vegetative"),
            "number.crop_steering_p2_vwc_threshold": SimpleNamespace(state="40"),
        }
    )
    entity.entity_description = SimpleNamespace(key=key)
    assert entity.native_value is None
    assert entity.extra_state_attributes["reason"].startswith("Retired:")


def _sized(cap=None, **more):
    states = {
        "number.crop_steering_substrate_volume": "100",
        "number.crop_steering_p2_shot_size": "50",
        "number.crop_steering_drippers_per_plant": "1",
        "number.crop_steering_dripper_flow_rate": "1",
        **({} if cap is None else {"number.crop_steering_max_shot_duration": cap}),
        **more,
    }
    entity = _room(states, {"1": {}})
    entity.entity_description = SimpleNamespace(key="p2_shot_duration_seconds")
    return entity


def test_a_room_without_a_shot_limit_is_shown_within_the_controllers_900_seconds():
    """CTL-010: 50% of 100 L at 1 L/h is 50 h; the controller runs 900 s, the sensor said 180000."""
    entity = _sized()
    assert entity._shot_seconds_by_zone("p2_shot_duration_seconds") == {1: 900}
    assert entity.native_value == 900


@pytest.mark.parametrize("cap", ["unavailable", "unknown", "abc", "3", "nan"])
def test_a_shot_limit_that_is_not_one_shows_no_duration_as_the_controller_runs_none(
    cap,
):
    """CTL-010: the controller starts no shot (CS-203); the sensor showed the uncapped length."""
    entity = _sized(cap)
    assert entity._shot_seconds_by_zone("p2_shot_duration_seconds") == {}
    assert entity.native_value is None


def test_the_shot_is_timed_on_zone_totals_as_the_controller_does():
    # 2% of 11.4 L for each of 7 plants through two 3.8 L/hr drippers each: 108 s.
    entity = _sized(
        "900",
        **{
            "number.crop_steering_substrate_volume": "11.4",
            "number.crop_steering_p2_shot_size": "2",
            "number.crop_steering_drippers_per_plant": "2",
            "number.crop_steering_dripper_flow_rate": "3.8",
            "number.crop_steering_zone_1_plant_count": "7",
        },
    )
    raw = shot_length.raw_seconds(2.0, 11.4 * 7, 7 * 2 * 3.8 / 3600.0)
    assert entity._shot_seconds_by_zone("p2_shot_duration_seconds") == {
        1: shot_length.shot_seconds(raw, 900.0)
    }
    assert entity.native_value == 108


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


def test_last_irrigation_wrapper_keeps_legacy_naive_timestamp_unknown():
    entity = sensor(
        {
            "sensor.crop_steering_zone_1_last_irrigation_app": SimpleNamespace(
                state="2026-09-08T10:30:00"
            )
        }
    )
    assert entity._get_zone_last_irrigation(1) is None


@pytest.mark.parametrize(
    "value",
    ["2026-01-08T10:30:00+13:00", "2026-09-08T10:30:00+12:00", "2026-09-07T22:30:00Z"],
)
def test_last_irrigation_wrapper_preserves_explicit_event_timestamp(value):
    entity = sensor(
        {
            "sensor.crop_steering_veg_zone_1_last_irrigation_app": SimpleNamespace(
                state=value
            )
        },
        "veg_",
    )
    assert entity._get_zone_last_irrigation(1) == datetime.fromisoformat(value)


def test_last_irrigation_wrapper_does_not_borrow_other_room_timestamp():
    entity = sensor(
        {
            "sensor.crop_steering_zone_1_last_irrigation_app": SimpleNamespace(
                state="2026-09-08T10:30:00+12:00"
            )
        },
        "veg_",
    )
    assert entity._get_zone_last_irrigation(1) is None


# --------------------------------------------------------------------------- probe units
def _probe(value, unit):
    return SimpleNamespace(state=str(value), attributes={"unit_of_measurement": unit})


def test_pore_ec_in_microsiemens_is_fused_as_millisiemens():
    # Unconverted, 3200 next to 3.0 averages 1601.5 "mS/cm": far over any EC target, and the
    # engine enlarges shots when pore EC is over target.
    entity = sensor(
        {"sensor.a": _probe(3200, "µS/cm"), "sensor.b": _probe(3.0, "mS/cm")}
    )
    assert _probe_mean(entity, ["sensor.a", "sensor.b"], "ec") == 3.1
    greek_mu = sensor({"sensor.a": _probe(2500, "μS/cm")})
    assert _probe_mean(greek_mu, ["sensor.a"], "ec") == 2.5


def test_vwc_reported_as_a_volume_fraction_is_fused_as_percent():
    entity = sensor({"sensor.a": _probe(0.42, "m³/m³"), "sensor.b": _probe(44, "%")})
    assert _probe_mean(entity, ["sensor.a", "sensor.b"], "vwc") == 43.0


def test_a_probe_with_no_unit_or_an_unknown_one_reads_exactly_as_before():
    entity = sensor(
        {"sensor.a": _probe(50, ""), "sensor.b": SimpleNamespace(state="52")}
    )
    assert _probe_mean(entity, ["sensor.a", "sensor.b"], "vwc") == 51.0
    assert _probe_mean(entity, ["sensor.a", "sensor.b"]) == 51.0


# --------------------------------------------------------------------------- a zone's probes
def _reported(value, unit, minutes_ago):
    return SimpleNamespace(
        state=str(value),
        attributes={"unit_of_measurement": unit},
        last_reported=NOW - timedelta(minutes=minutes_ago),
    )


def _zone(states, **zone):
    entity = sensor(states)
    entity._zones_config = {
        "1": zone
    }  # string keys: what a reloaded config entry holds
    entity.entity_description = SimpleNamespace(key="vwc_zone_1")
    return entity


def test_a_zone_converts_each_probe_before_combining_them():
    entity = _zone(
        {"sensor.a": _probe(3200, "µS/cm"), "sensor.b": _probe(3.0, "mS/cm")},
        ec_sensors=["sensor.a", "sensor.b"],
    )
    assert entity._get_zone_ec(1) == 3.1


def test_a_zones_reading_names_the_probes_it_was_made_from():
    states = {
        "sensor.a": _reported(40, "%", 1),
        "sensor.b": _reported(42, "%", 1),
        "sensor.c": _reported(90, "%", 1),
    }
    entity = _zone(states, vwc_sensors=["sensor.a", "sensor.b", "sensor.c"])
    assert entity._get_zone_vwc(1) == 41.0
    assert entity.extra_state_attributes == {
        "probes": 3,
        "used": ["sensor.a", "sensor.b"],
        "excluded": {"sensor.c": "far from the others"},
        "spread": 2.0,
        "method": "Median",
        "steered_by": "Median",
        "quality": {
            "sensor.a": {"quality": "good", "reason": "fresh"},
            "sensor.b": {"quality": "good", "reason": "fresh"},
            "sensor.c": {"quality": "bad", "reason": "excluded_outlier"},
        },
        "offsets_learned": None,
        "primary": None,
    }


def test_a_probe_that_stops_reporting_is_set_aside_without_stepping_the_zone():
    states = {"sensor.a": _reported(40, "%", 1), "sensor.b": _reported(46, "%", 1)}
    entity = _zone(states, vwc_sensors=["sensor.a", "sensor.b"])
    assert entity._get_zone_vwc(1) == 43.0
    states["sensor.a"] = _reported(39, "%", 0)
    states["sensor.b"] = _reported(46, "%", 30)  # last heard from half an hour ago
    assert entity._get_zone_vwc(1) == 42.0
    assert entity.extra_state_attributes["excluded"] == {"sensor.b": "not reporting"}


def test_a_probe_set_aside_for_its_unit_is_named_with_that_unit():
    """What the controller names in CS-503: the probe and its unit, not only that the zone is blind."""
    states = {"sensor.a": _reported(1250, "mV", 1)}
    entity = _zone(states, vwc_sensors=["sensor.a"])
    assert entity._get_zone_vwc(1) is None
    assert entity.extra_state_attributes["excluded"] == {
        "sensor.a": "set aside for its unit"
    }
    assert entity.extra_state_attributes["unit_set_aside"] == {"sensor.a": "mV"}
    assert entity.extra_state_attributes["quality"] == {
        "sensor.a": {"quality": "bad", "reason": "unknown_unit"}
    }
    states["sensor.a"] = _reported(45, "%", 0)  # its unit corrected: it counts again
    assert entity._get_zone_vwc(1) == 45.0
    assert "unit_set_aside" not in entity.extra_state_attributes


def test_a_unitless_probe_out_of_range_is_excluded_as_out_of_range_as_before():
    entity = _zone(
        {"sensor.a": _reported(450, "", 1), "sensor.b": _reported(44, "%", 1)},
        vwc_sensors=["sensor.a", "sensor.b"],
    )
    assert entity._get_zone_vwc(1) == 44.0
    assert entity.extra_state_attributes["excluded"] == {"sensor.a": "out of range"}
    assert "unit_set_aside" not in entity.extra_state_attributes


def test_the_legacy_front_and_back_pair_is_still_a_zones_probes():
    entity = _zone(
        {"sensor.front": _probe(40, "%"), "sensor.back": _probe(46, "%")},
        vwc_front="sensor.front",
        vwc_back="sensor.back",
    )
    assert entity._get_zone_vwc(1) == 43.0
