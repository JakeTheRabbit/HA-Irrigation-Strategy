"""Setup lifecycle safety and stable-ID compatibility, without live Home Assistant."""

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.crop_steering import setup_api as api


class Entries:
    def __init__(self, entries):
        self.entries = entries
        self.updates = []

    def async_entries(self, domain):
        return self.entries

    def async_update_entry(self, entry, **kwargs):
        self.updates.append(kwargs)
        for key, value in kwargs.items():
            setattr(entry, key, value)


def rig():
    entry = SimpleNamespace(
        entry_id="one",
        title="Veg",
        options={},
        data={
            "room_name": "Veg",
            "room_slug": "veg",
            "room_prefix": "veg_",
            "num_zones": 2,
            "zones": {
                "1": {"zone_switch": "switch.v1", "plant_count": 4, "special": 123},
                "2": {"zone_switch": "switch.v2", "plant_count": 8},
            },
            "hardware": {"pump_switch": "switch.p", "main_line_switch": "switch.m"},
            "parameters": {"p2_vwc_threshold": 47},
        },
    )
    states = {}
    for eid in [
        "switch.v1",
        "switch.v2",
        "switch.v3",
        "switch.p",
        "switch.m",
        "switch.crop_steering_veg_engine_enabled",
    ]:
        states[eid] = SimpleNamespace(entity_id=eid, state="off", attributes={})
    for eid, unit in [
        ("sensor.vwc", "%"),
        ("sensor.ec", "mS/cm"),
        ("sensor.temp", "°C"),
    ]:
        states[eid] = SimpleNamespace(
            entity_id=eid, state="50", attributes={"unit_of_measurement": unit}
        )
    hass = SimpleNamespace(
        config_entries=Entries([entry]),
        data={},
        states=SimpleNamespace(get=states.get, async_all=lambda: list(states.values())),
    )
    return hass, entry, states


def payload():
    return {
        "entry_id": "one",
        "expected_revision": 0,
        "room_name": "Veg renamed",
        "active": True,
        "zones": [
            {
                "id": 1,
                "name": "Front",
                "active": False,
                "valve": "switch.v1",
                "vwc_sensors": [],
                "ec_sensors": [],
                "plant_count": 4,
            },
            {
                "id": 2,
                "name": "Rear",
                "active": True,
                "valve": "switch.v2",
                "vwc_sensors": ["sensor.vwc"],
                "ec_sensors": ["sensor.ec"],
                "plant_count": 8,
            },
        ],
        "hardware": {"pump_switch": "switch.p", "main_line_switch": "switch.m"},
    }


def test_setup_preserves_identity_and_metadata_when_archiving_middle_zone():
    hass, entry, _ = rig()
    result = asyncio.run(api.save_setup(hass, payload()))
    assert result["entry_id"] == "one" and result["revision"] == 1
    assert result["active_zone_ids"] == [2]
    assert entry.data["room_prefix"] == "veg_"
    assert entry.data["zones"]["1"]["special"] == 123
    assert entry.data["zones"]["2"]["plant_count"] == 8
    assert entry.data["parameters"]["p2_vwc_threshold"] == 47


@pytest.mark.parametrize(
    "entity,state",
    [
        ("switch.p", "on"),
        ("switch.m", "unavailable"),
        ("switch.crop_steering_veg_engine_enabled", "on"),
        ("switch.v1", "unknown"),
    ],
)
def test_setup_rejects_unsafe_hardware_or_armed_engine(entity, state):
    hass, _, states = rig()
    states[entity].state = state
    with pytest.raises(ValueError, match="OFF"):
        asyncio.run(api.save_setup(hass, payload()))
    assert not hass.config_entries.updates


def test_setup_rejects_revision_and_wrong_units_before_writes():
    hass, _, _ = rig()
    data = payload()
    data["expected_revision"] = 5
    with pytest.raises(ValueError, match="changed"):
        asyncio.run(api.save_setup(hass, data))
    data = payload()
    data["zones"][1]["vwc_sensors"] = ["sensor.temp"]
    with pytest.raises(ValueError, match="unit"):
        asyncio.run(api.save_setup(hass, data))
    assert not hass.config_entries.updates


def test_setup_rejects_duplicate_valves_across_rooms():
    hass, _, _ = rig()
    hass.config_entries.entries.append(
        SimpleNamespace(
            entry_id="other",
            options={},
            data={
                "room_prefix": "other_",
                "zones": {"1": {"zone_switch": "switch.v2"}},
                "num_zones": 1,
            },
        )
    )
    with pytest.raises(ValueError, match="allocated"):
        asyncio.run(api.save_setup(hass, payload()))


def test_room_archive_requires_exact_selection_and_is_reversible():
    hass, entry, _ = rig()
    with pytest.raises(ValueError, match="name"):
        asyncio.run(
            api.remove_setup(
                hass,
                {"entry_id": "one", "expected_revision": 0, "confirm_name": "wrong"},
            )
        )
    result = asyncio.run(
        api.remove_setup(
            hass, {"entry_id": "one", "expected_revision": 0, "confirm_name": "Veg"}
        )
    )
    assert result["archived"] and entry.data["active"] is False
    assert set(entry.data["zones"]) == {"1", "2"}
    data = payload()
    data["expected_revision"] = 1
    asyncio.run(api.save_setup(hass, data))
    assert entry.data["active"] is True


def test_setup_new_ids_append_and_existing_ids_cannot_disappear():
    hass, _, _ = rig()
    data = payload()
    data["zones"] = data["zones"][1:]
    with pytest.raises(ValueError, match="archive"):
        asyncio.run(api.save_setup(hass, data))
    data = payload()
    data["zones"].append(
        {"id": 4, "name": "skip", "active": True, "valve": "switch.v3"}
    )
    with pytest.raises(ValueError, match="sequential"):
        asyncio.run(api.save_setup(hass, data))


@pytest.mark.parametrize("role", ["pump_is_foreign_valve", "valve_is_foreign_pump"])
def test_shared_hardware_cannot_conflict_with_a_zone_role(role):
    hass, _, states = rig()
    data = payload()
    foreign = {"room_prefix": "other_", "num_zones": 1, "zones": {}, "hardware": {}}
    if role == "pump_is_foreign_valve":
        foreign["zones"] = {"1": {"zone_switch": "switch.p"}}
    else:
        foreign["hardware"] = {"pump_switch": "switch.v2"}
    hass.config_entries.entries.append(
        SimpleNamespace(entry_id="other", data=foreign, options={})
    )
    states["switch.crop_steering_other_engine_enabled"] = SimpleNamespace(
        state="off", attributes={}
    )
    with pytest.raises(ValueError, match="role"):
        asyncio.run(api.save_setup(hass, data))
    assert not hass.config_entries.updates


def test_shared_room_must_be_disarmed_even_when_owner_is_off():
    hass, _, states = rig()
    hass.config_entries.entries.append(
        SimpleNamespace(
            entry_id="other",
            options={},
            data={
                "room_prefix": "other_",
                "num_zones": 1,
                "zones": {},
                "hardware": {"pump_switch": "switch.p"},
            },
        )
    )
    states["switch.crop_steering_other_engine_enabled"] = SimpleNamespace(
        state="on", attributes={}
    )
    with pytest.raises(ValueError, match="other_engine_enabled.*OFF"):
        asyncio.run(api.save_setup(hass, payload()))


def test_options_shadow_is_removed_and_unrelated_option_preserved():
    hass, entry, _ = rig()
    entry.options = {"zones": entry.data["zones"], "future_option": 42}
    asyncio.run(api.save_setup(hass, payload()))
    assert "zones" not in entry.options
    assert entry.options["future_option"] == 42
    assert api.effective(entry)["future_option"] == 42
    assert api.effective(entry)["zones"]["1"]["active"] is False


def test_archiving_zone_does_not_require_a_removed_moisture_probe():
    hass, entry, _ = rig()
    entry.data["zones"]["1"]["vwc_sensors"] = ["sensor.deleted"]
    data = payload()
    data["zones"][0]["vwc_sensors"] = ["sensor.deleted"]
    result = asyncio.run(api.save_setup(hass, data))
    assert result["active_zone_ids"] == [2]
    assert entry.data["zones"]["1"]["vwc_sensors"] == ["sensor.deleted"]
