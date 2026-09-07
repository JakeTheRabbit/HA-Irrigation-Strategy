"""Drive real native config-flow steps with a minimal HA flow host."""

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

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
