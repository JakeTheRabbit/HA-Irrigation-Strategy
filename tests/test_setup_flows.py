"""Drive real native config-flow steps with a minimal HA flow host."""

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from custom_components.crop_steering import setup_api as api

from .test_setup import rig, payload


@pytest.fixture
def flow_module(monkeypatch):
    from . import ha_stubs

    ha_stubs.install()
    entries = sys.modules["homeassistant.config_entries"]

    class Flow:
        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__()

        def _async_current_entries(self):
            return self.hass.config_entries.async_entries("crop_steering")

        async def async_set_unique_id(self, unique):
            self.unique = unique

        def _abort_if_unique_id_configured(self):
            return None

        def async_create_entry(self, **data):
            return {"type": "create_entry", **data}

        def async_abort(self, **data):
            return {"type": "abort", **data}

        def async_show_form(self, **data):
            return {"type": "form", **data}

    monkeypatch.setattr(entries, "ConfigFlow", Flow, raising=False)
    monkeypatch.setattr(entries, "OptionsFlow", Flow, raising=False)
    flow = ModuleType("homeassistant.data_entry_flow")
    flow.FlowResult = dict
    monkeypatch.setitem(sys.modules, "homeassistant.data_entry_flow", flow)
    selector = ModuleType("homeassistant.helpers.selector")
    selector.EntitySelector = lambda config: config
    selector.EntitySelectorConfig = lambda **data: data
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.selector", selector)
    spec = importlib.util.spec_from_file_location(
        "custom_components.crop_steering._setup_flow_test",
        Path(__file__).parents[1] / "custom_components/crop_steering/config_flow.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_native_creation_retains_supported_flow_and_validates_off(flow_module):
    hass, _, states = rig()
    hass.config_entries.entries = []
    flow = flow_module.ConfigFlow()
    flow.hass = hass
    data = payload()
    data["room_name"] = "First room"
    result = asyncio.run(flow.async_step_user({"setup_payload": data}))
    assert result["type"] == "create_entry"
    assert flow.unique == "default" and result["data"]["room_prefix"] == ""
    assert result["data"]["setup_revision"] == 1
    assert result["data"]["enable_flag"] == "switch.crop_steering_engine_enabled"
    assert result["data"]["zones"]["2"]["vwc_sensors"] == ["sensor.vwc"]
    states["switch.p"].state = "on"
    result = asyncio.run(flow.async_step_user({"setup_payload": data}))
    assert (
        result["type"] == "abort"
        and "OFF" in result["description_placeholders"]["error"]
    )


def test_new_named_default_is_rejected_to_protect_controller_state(flow_module):
    hass, _, _ = rig()
    flow = flow_module.ConfigFlow()
    flow.hass = hass
    result = asyncio.run(flow.async_step_room({"room_name": "Default"}))
    assert result["type"] == "abort" and result["reason"] == "reserved_room_name"


def test_native_zone_builder_retains_archived_ids_and_unknown_values(flow_module):
    old = {
        "1": {"active": False, "zone_switch": "switch.v1", "special": 123},
        "2": {"zone_switch": "switch.v2", "max_daily_volume": 37},
    }
    result = flow_module._build_zones(
        1, {"zone_1_switch": "switch.v1", "zone_1_name": "New label"}, old
    )
    assert result["1"]["active"] is False and result["2"]["active"] is False
    assert result["1"]["special"] == 123 and result["2"]["max_daily_volume"] == 37


def test_native_env_reload_cannot_bypass_off_gate(flow_module, monkeypatch):
    hass, entry, states = rig()
    entry.data["config_method"] = "env"
    hass.config = type("Config", (), {"config_dir": "/unused"})()

    async def executor(fn, *args):
        return fn(*args)

    hass.async_add_executor_job = executor
    monkeypatch.setattr(
        flow_module,
        "load_env_config",
        lambda _: {
            "num_zones": 1,
            "zones": {"1": {"zone_switch": "switch.v1"}},
            "hardware": {"pump_switch": "switch.p", "main_line_switch": "switch.m"},
            "parameters": {},
            "features": {},
        },
    )
    flow = flow_module.OptionsFlowHandler(entry)
    flow.hass = hass
    states["switch.p"].state = "on"
    result = asyncio.run(flow.async_step_reload_env())
    assert result["type"] == "abort"
    assert not hass.config_entries.updates
    states["switch.p"].state = "off"
    result = asyncio.run(flow.async_step_reload_env())
    assert result["type"] == "create_entry"
    assert entry.data["zones"]["1"]["special"] == 123
    assert entry.data["zones"]["2"]["active"] is False
    assert entry.data["num_zones"] == 2


def test_native_hardware_schema_retains_explicit_tank_telemetry(
    flow_module, monkeypatch
):
    mappings = {
        "tank_temperature_sensor": "sensor.tank_temp",
        "tank_ec_sensor": "sensor.tank_ec",
        "tank_ph_sensor": "sensor.tank_ph",
        "tank_last_fill_sensor": "sensor.tank_last_fill",
        "tank_fill_entity": "binary_sensor.tank_filling",
    }
    defaults = {}
    original = flow_module.vol.Optional

    def optional(key, **kwargs):
        # Prefilled as a SUGGESTED value, not a default: the form still opens showing the
        # existing mapping (so saving cannot wipe it), but the field can now be cleared.
        # With `default=` the frontend dropped an emptied field and voluptuous restored it,
        # so a tank or pump mapping could be swapped but never removed.
        if key in mappings:
            assert "default" not in kwargs, f"{key} can no longer be cleared"
        defaults[key] = (kwargs.get("description") or {}).get("suggested_value")
        return original(key, **kwargs)

    monkeypatch.setattr(flow_module.vol, "Optional", optional)
    schema = flow_module._hardware_schema(mappings)
    fields = {
        getattr(key, "schema", getattr(key, "key", None)): (key, selector)
        for key, selector in schema.items()
    }
    for key, value in mappings.items():
        assert key in fields
        assert defaults[key] == value
    assert fields["tank_temperature_sensor"][1]["domain"] == "sensor"
    assert set(fields["tank_last_fill_sensor"][1]["domain"]) == {
        "sensor",
        "input_datetime",
    }
    assert set(fields["tank_fill_entity"][1]["domain"]) == {"switch", "binary_sensor"}
    hardware = flow_module._build_hardware(mappings)
    assert all(hardware[key] == value for key, value in mappings.items())


# --------------------------------------------------------------------------- the wizard keeps what you typed
# Seen on a first tent install: the last step failed with "switch.gt1_irrigation_switch must read OFF
# before changing setup", the flow ABORTED, and every zone, sensor and sizing entry was gone.
def _wizard(flow_module, *, zones=1):
    hass, _, states = rig()
    hass.config_entries.entries = []
    flow = flow_module.ConfigFlow()
    flow.hass = hass
    # what HA's real flow base class does: prefill the schema with the last submission
    flow.add_suggested_values_to_schema = lambda schema, values: {
        "schema": schema,
        "kept": dict(values),
    }
    flow._data = {
        "name": "Tent",
        "room_name": "Tent",
        "room_prefix": "",
        "room_slug": "default",
        "num_zones": zones,
    }
    return flow, states


ZONE_INPUT = {
    "zone_1_name": "Tent",
    "zone_1_active": True,
    "zone_1_switch": "switch.v1",
    "zone_1_vwc": ["sensor.vwc"],
    "zone_1_ec": ["sensor.ec"],
    "zone_1_plant_count": 4,
}


def test_a_valve_that_is_on_is_reported_on_the_zones_step_with_the_input_kept(
    flow_module,
):
    flow, states = _wizard(flow_module)
    states["switch.v1"].state = "on"
    result = asyncio.run(flow.async_step_zones(dict(ZONE_INPUT)))
    assert result["type"] == "form" and result["step_id"] == "zones"
    assert result["data_schema"]["kept"] == ZONE_INPUT  # nothing typed is lost
    assert result["errors"] == {"base": "setup_invalid"}
    assert "switch.v1" in result["description_placeholders"]["error"]
    assert "it is ON" in result["description_placeholders"]["error"]
    states["switch.v1"].state = (
        "off"  # fix the cause, press Submit again: the wizard carries on
    )
    result = asyncio.run(flow.async_step_zones(dict(ZONE_INPUT)))
    assert result["type"] == "form" and result["step_id"] == "hardware"


def test_a_wrong_unit_is_reported_on_the_zones_step_not_three_screens_later(
    flow_module,
):
    flow, states = _wizard(flow_module)
    states["sensor.ec"].attributes["unit_of_measurement"] = "ppm"
    result = asyncio.run(flow.async_step_zones(dict(ZONE_INPUT)))
    assert result["type"] == "form" and result["step_id"] == "zones"
    assert "sensor.ec" in result["description_placeholders"]["error"]


def test_a_failure_on_the_last_step_shows_that_step_again_instead_of_aborting(
    flow_module,
):
    flow, states = _wizard(flow_module)
    asyncio.run(flow.async_step_zones(dict(ZONE_INPUT)))
    hardware = {
        "pump_switch": "switch.p",
        "main_line_switch": "switch.m",
        "substrate_volume": 3.2,
    }
    states["switch.p"].state = "unavailable"
    result = asyncio.run(flow.async_step_hardware(dict(hardware)))
    assert result["type"] == "form" and result["step_id"] == "hardware"
    assert result["data_schema"]["kept"] == hardware
    assert "switch.p" in result["description_placeholders"]["error"]
    assert "unavailable" in result["description_placeholders"]["error"]
    assert (
        flow._data["zones"]["1"]["zone_switch"] == "switch.v1"
    )  # earlier steps survive too
    states["switch.p"].state = "off"
    result = asyncio.run(flow.async_step_hardware(dict(hardware)))
    assert result["type"] == "create_entry" and result["data"]["setup_revision"] == 1


def test_a_single_switch_tent_is_a_complete_room(flow_module):
    flow, _states = _wizard(flow_module)
    asyncio.run(flow.async_step_zones(dict(ZONE_INPUT)))
    result = asyncio.run(
        flow.async_step_hardware({"substrate_volume": 3.2})
    )  # no pump, no mainline
    assert result["type"] == "create_entry"
    assert (
        result["data"]["hardware"]["pump_switch"] == ""
        and result["data"]["zones"]["1"]["zone_switch"] == "switch.v1"
    )


def test_a_blocker_says_whether_the_entity_is_on_unreachable_or_missing():
    hass, entry, states = rig()
    states["switch.p"].state = "on"
    states["switch.m"].state = "unavailable"
    del states["switch.v1"]
    found = {line.split(" ")[0]: line for line in api.safety_blockers(hass, entry)}
    assert "it is ON" in found["switch.p"]
    assert "unavailable" in found["switch.m"]
    assert "not found" in found["switch.v1"]
    assert all("must read OFF" in line for line in found.values())
