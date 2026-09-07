"""Optional tank telemetry mappings are explicit and do not become actuators."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from custom_components.crop_steering import setup_api as api
from custom_components.crop_steering.room import build_engine_config
from .test_setup import payload, rig


MAPPINGS = {
    "water_level_sensor": "sensor.tank_level",
    "tank_temperature_sensor": "sensor.tank_temp",
    "tank_ec_sensor": "sensor.tank_ec",
    "tank_ph_sensor": "sensor.tank_ph",
    "tank_last_fill_sensor": "sensor.tank_last_fill",
    "tank_fill_entity": "binary_sensor.tank_filling",
}


def tank_rig():
    hass, entry, states = rig()
    for entity, state, attrs in [
        ("sensor.tank_level", "65", {"unit_of_measurement": "%"}),
        ("sensor.tank_ec", "2.5", {"unit_of_measurement": "mS/cm"}),
        ("sensor.tank_ph", "5.8", {"unit_of_measurement": "pH"}),
        ("sensor.tank_temp", "21.5", {"unit_of_measurement": "°C"}),
        (
            "sensor.tank_last_fill",
            "2026-09-08T04:00:00+12:00",
            {"device_class": "timestamp"},
        ),
        ("binary_sensor.tank_filling", "on", {}),
    ]:
        states[entity] = SimpleNamespace(
            entity_id=entity, state=state, attributes=attrs
        )
    return hass, entry, states


def test_tank_mappings_roundtrip_without_changing_plumbing_identity_or_setpoints():
    hass, entry, _states = tank_rig()
    entry.data["hardware"]["temperature_sensor"] = "sensor.temp"
    entry.data["hardware"]["feed_ec_sensor"] = "sensor.ec"
    entry.options = {"keep_this_option": 42}
    before = deepcopy(entry.data)
    data = payload()
    data["hardware"].update(MAPPINGS)
    result = asyncio.run(api.save_setup(hass, data))
    for key, value in MAPPINGS.items():
        assert result["hardware"][key] == value
        assert entry.data["hardware"][key] == value
    assert entry.data["hardware"]["temperature_sensor"] == "sensor.temp"
    assert entry.data["hardware"]["feed_ec_sensor"] == "sensor.ec"
    assert entry.data["room_prefix"] == before["room_prefix"]
    assert entry.data["parameters"] == before["parameters"]
    assert entry.data["zones"]["1"]["special"] == 123
    assert entry.options == {"keep_this_option": 42}
    assert api.hardware_entities(entry.data) == {
        "switch.p",
        "switch.m",
        "switch.v1",
        "switch.v2",
    }
    assert not result["safety"][
        "blockers"
    ]  # Filling ON is telemetry, not mapped plumbing.
    assert (
        api.configuration_payload(entry.data)["hardware"]["tank_fill_entity"]
        == MAPPINGS["tank_fill_entity"]
    )
    candidates = api.read_setup(hass)["candidates"]
    assert any(row["entity_id"] == MAPPINGS["tank_fill_entity"] for row in candidates)


def test_descriptor_exposes_only_explicit_room_tank_mappings():
    hardware = {
        **MAPPINGS,
        "feed_ec_sensor": "sensor.feed_ec",
        "feed_ph_sensor": "sensor.feed_ph",
        "temperature_sensor": "sensor.air",
    }
    attrs = build_engine_config("veg_", "veg", 1, {}, hardware)
    for key, value in hardware.items():
        if key != "temperature_sensor":
            assert attrs[key] == value
    absent = build_engine_config(
        "", "default", 1, {}, {"temperature_sensor": "sensor.air"}
    )
    assert all(absent[key] == "" for key in MAPPINGS)
    assert absent["feed_ec_sensor"] == absent["feed_ph_sensor"] == ""


@pytest.mark.parametrize("unit", ["°C", "°F", "K"])
def test_tank_temperature_accepts_explicit_temperature_units(unit):
    hass, entry, states = tank_rig()
    states["sensor.tank_temp"].attributes["unit_of_measurement"] = unit
    data = payload()
    data["hardware"]["tank_temperature_sensor"] = "sensor.tank_temp"
    assert (
        api.prepare_setup(hass, data, entry.data, entry.entry_id)["hardware"][
            "tank_temperature_sensor"
        ]
        == "sensor.tank_temp"
    )


@pytest.mark.parametrize("unit", ["%", "mS/cm", "", None])
def test_tank_temperature_rejects_incompatible_or_missing_units(unit):
    hass, entry, states = tank_rig()
    states["sensor.tank_temp"].attributes["unit_of_measurement"] = unit
    data = payload()
    data["hardware"]["tank_temperature_sensor"] = "sensor.tank_temp"
    with pytest.raises(ValueError, match="unit"):
        api.prepare_setup(hass, data, entry.data, entry.entry_id)


@pytest.mark.parametrize(
    "state,attributes",
    [
        ("2026-09-08T04:00:00", {"device_class": "timestamp"}),
        ("2026-09-08", {"device_class": "timestamp"}),
        ("not a timestamp", {"device_class": "timestamp"}),
        ("65", {"unit_of_measurement": "%"}),
        ("2026-09-08T04:00:00Z", {"device_class": "humidity"}),
    ],
)
def test_last_fill_rejects_levels_and_non_timestamp_states(state, attributes):
    hass, entry, states = tank_rig()
    states["sensor.tank_last_fill"].state = state
    states["sensor.tank_last_fill"].attributes = attributes
    data = payload()
    data["hardware"]["tank_last_fill_sensor"] = "sensor.tank_last_fill"
    with pytest.raises(ValueError, match="timestamp"):
        api.prepare_setup(hass, data, entry.data, entry.entry_id)


@pytest.mark.parametrize(
    "state", [None, "", "unknown", "unavailable", "2026-09-08T04:00:00Z"]
)
def test_last_fill_accepts_unknown_reading_without_inventing_an_event(state):
    hass, entry, states = tank_rig()
    states["sensor.tank_last_fill"].state = state
    data = payload()
    data["hardware"]["tank_last_fill_sensor"] = "sensor.tank_last_fill"
    result = api.prepare_setup(hass, data, entry.data, entry.entry_id)
    assert result["hardware"]["tank_last_fill_sensor"] == "sensor.tank_last_fill"


def test_optional_telemetry_preserves_omissions_and_allows_explicit_clear():
    hass, entry, _states = tank_rig()
    entry.data["hardware"].update(MAPPINGS)
    result = api.prepare_setup(hass, payload(), entry.data, entry.entry_id)
    assert result["hardware"]["tank_temperature_sensor"] == "sensor.tank_temp"
    data = payload()
    data["hardware"].update({key: "" for key in MAPPINGS})
    result = api.prepare_setup(hass, data, entry.data, entry.entry_id)
    assert all(result["hardware"][key] == "" for key in MAPPINGS)


@pytest.mark.parametrize(
    "key,value",
    [
        ("tank_temperature_sensor", "sensor.missing"),
        ("tank_last_fill_sensor", "switch.p"),
        ("tank_fill_entity", "sensor.tank_level"),
    ],
)
def test_tank_mappings_reject_missing_entities_or_wrong_domains(key, value):
    hass, entry, _states = tank_rig()
    data = payload()
    data["hardware"][key] = value
    with pytest.raises(ValueError):
        api.prepare_setup(hass, data, entry.data, entry.entry_id)


@pytest.mark.parametrize(
    "key,entity,unit",
    [
        ("tank_ec_sensor", "sensor.tank_ec", "mS/cm"),
        ("tank_ec_sensor", "sensor.tank_ec", "dS/m"),
        ("tank_ph_sensor", "sensor.tank_ph", "pH"),
        ("tank_ph_sensor", "sensor.tank_ph", ""),
    ],
)
def test_dedicated_tank_quality_units_do_not_enable_feed_gates(key, entity, unit):
    hass, entry, states = tank_rig()
    states[entity].attributes["unit_of_measurement"] = unit
    data = payload()
    data["hardware"][key] = entity
    result = api.prepare_setup(hass, data, entry.data, entry.entry_id)
    assert result["hardware"][key] == entity
    assert not result["hardware"].get("feed_ec_sensor")
    assert not result["hardware"].get("feed_ph_sensor")


@pytest.mark.parametrize(
    "key,entity",
    [
        ("tank_ec_sensor", "sensor.tank_ph"),
        ("tank_ph_sensor", "sensor.tank_ec"),
    ],
)
def test_dedicated_tank_quality_mapping_rejects_wrong_units(key, entity):
    hass, entry, _states = tank_rig()
    data = payload()
    data["hardware"][key] = entity
    with pytest.raises(ValueError, match="unit"):
        api.prepare_setup(hass, data, entry.data, entry.entry_id)


def test_last_fill_accepts_explicit_date_and_time_helper_epoch():
    hass, entry, states = tank_rig()
    entity = "input_datetime.tank_last_filled"
    states[entity] = SimpleNamespace(
        entity_id=entity,
        state="2026-09-08 04:00:00",
        attributes={"has_date": True, "has_time": True, "timestamp": 1788796800.0},
    )
    data = payload()
    data["hardware"]["tank_last_fill_sensor"] = entity
    result = api.prepare_setup(hass, data, entry.data, entry.entry_id)
    assert result["hardware"]["tank_last_fill_sensor"] == entity
    assert any(row["entity_id"] == entity for row in api.read_setup(hass)["candidates"])
    attrs = build_engine_config("veg_", "veg", 1, {}, result["hardware"])
    assert attrs["tank_last_fill_sensor"] == entity


@pytest.mark.parametrize(
    "attributes",
    [
        {"has_date": False, "has_time": True, "timestamp": 1788796800},
        {"has_date": True, "has_time": False, "timestamp": 1788796800},
        {"has_date": True, "has_time": True},
        {"has_date": True, "has_time": True, "timestamp": float("nan")},
        {"has_date": True, "has_time": True, "timestamp": float("inf")},
        {"has_date": True, "has_time": True, "timestamp": "not an epoch"},
        {"has_date": True, "has_time": True, "timestamp": True},
    ],
)
def test_last_fill_helper_requires_complete_date_time_and_finite_epoch(attributes):
    hass, entry, states = tank_rig()
    entity = "input_datetime.tank_last_filled"
    states[entity] = SimpleNamespace(
        entity_id=entity, state="2026-09-08 04:00:00", attributes=attributes
    )
    data = payload()
    data["hardware"]["tank_last_fill_sensor"] = entity
    with pytest.raises(ValueError, match="both date and time|finite epoch timestamp"):
        api.prepare_setup(hass, data, entry.data, entry.entry_id)
