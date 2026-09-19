"""Room On/Off status and the opt-in auto-setpoints switch.

An empty room (nothing growing) must be switchable OFF: the engine then neither irrigates nor
alerts for it, and the integration's Repairs health checks stop nagging about its unplugged probes.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from . import ha_stubs

ha_stubs.install()

from custom_components.crop_steering import health  # noqa: E402


@pytest.fixture
def switch_module(monkeypatch):
    class Entity:
        async def async_added_to_hass(self):
            pass

    class SwitchEntity(Entity):
        pass

    class RestoreEntity(Entity):
        async def async_get_last_state(self):
            return None

    def module(name, **attributes):
        value = ModuleType(name)
        value.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, value)

    module(
        "homeassistant.components.switch",
        SwitchEntity=SwitchEntity,
        SwitchEntityDescription=lambda **kw: SimpleNamespace(**kw),
    )
    module("homeassistant.config_entries", ConfigEntry=ha_stubs.FakeEntry)
    module("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
    module("homeassistant.helpers.entity", DeviceInfo=lambda **kw: kw)
    module("homeassistant.helpers.restore_state", RestoreEntity=RestoreEntity)
    module(
        "homeassistant.helpers.event",
        async_track_point_in_utc_time=lambda *a, **k: (lambda: None),
    )
    spec = importlib.util.spec_from_file_location(
        "custom_components.crop_steering._room_status_switch_under_test",
        Path(__file__).parents[1] / "custom_components/crop_steering/switch.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make(switch_module, key, prefix=""):
    entry = ha_stubs.FakeEntry(
        data={"room_prefix": prefix, "room_slug": prefix.rstrip("_") or "default"},
        entry_id=prefix or "default",
    )
    description = next(
        d for d in switch_module.BASE_SWITCH_DESCRIPTIONS if d.key == key
    )
    return switch_module.CropSteeringSwitch(entry, description)


def test_every_room_gets_a_room_active_switch_that_defaults_on(switch_module):
    default = _make(switch_module, "room_active")
    f1 = _make(switch_module, "room_active", prefix="f1_")
    assert default._attr_is_on and f1._attr_is_on  # a fresh install keeps watering
    assert default._attr_object_id == "crop_steering_room_active"
    assert f1._attr_object_id == "crop_steering_f1_room_active"


def test_auto_setpoints_is_opt_in(switch_module):
    entity = _make(switch_module, "auto_setpoints", prefix="f1_")
    assert entity._attr_is_on is False  # nothing rewrites setpoints until asked to
    assert entity._attr_object_id == "crop_steering_f1_auto_setpoints"


def _f1_entry():
    return ha_stubs.FakeEntry(
        data={
            "room_slug": "f1",
            "room_prefix": "f1_",
            "zones": {"1": {"vwc_sensors": []}, "2": {"vwc_front": "sensor.dead"}},
        },
        entry_id="f1",
    )


def test_an_empty_room_with_unplugged_probes_nags_while_it_is_on():
    hass = ha_stubs.FakeHass(
        states={
            "switch.crop_steering_f1_room_active": ha_stubs.FakeState("on"),
            "sensor.crop_steering_f1_vwc_zone_2": ha_stubs.FakeState("unavailable"),
        }
    )
    health.run_health_check(hass, _f1_entry())
    assert "zone_no_sensor_f1" in hass._issues
    assert "fused_sensor_unavailable_f1" in hass._issues
    assert "engine_offline_f1" in hass._issues


def test_switching_the_room_off_clears_and_silences_its_repairs():
    hass = ha_stubs.FakeHass(
        states={
            "switch.crop_steering_f1_room_active": ha_stubs.FakeState("on"),
            "sensor.crop_steering_f1_vwc_zone_2": ha_stubs.FakeState("unavailable"),
        }
    )
    health.run_health_check(hass, _f1_entry())
    assert hass._issues  # nagging
    hass.states.set("switch.crop_steering_f1_room_active", "off")
    health.run_health_check(hass, _f1_entry())
    assert not [i for i in hass._issues if i.endswith("_f1")]


def test_a_missing_room_active_switch_means_on():
    # older installs have no switch yet: behaviour must not change
    hass = ha_stubs.FakeHass(states={})
    health.run_health_check(hass, _f1_entry())
    assert "zone_no_sensor_f1" in hass._issues
