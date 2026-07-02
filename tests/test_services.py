"""Behavioral tests for the crop_steering service handlers.

Confirms three shipped fixes without a live HA:
  * #15  services no longer call the removed `hass.helpers.template.now()` — event
         payloads carry a timestamp from `homeassistant.util.dt.now()` and do not raise.
  * #16  services resolve a `room` slug to that room's entity-id prefix, so a second
         room is steered independently (and the default room is unchanged).
  * #27  apply_recipe / save_recipe raise instead of silently doing nothing when the
         recipe store is not loaded.
"""

from __future__ import annotations

import asyncio

import pytest

from . import ha_stubs

ha_stubs.install()

from custom_components.crop_steering import services  # noqa: E402
from custom_components.crop_steering.const import DOMAIN  # noqa: E402
from homeassistant.exceptions import HomeAssistantError  # noqa: E402


class Call:
    """Minimal ServiceCall stand-in."""

    def __init__(self, **data):
        self.data = data


def _handlers(hass):
    """Run async_setup_services and return the registered handler map."""
    asyncio.run(services.async_setup_services(hass))
    return {name: fn for (domain, name), fn in hass.services.registered.items()}


def _veg_entry():
    return ha_stubs.FakeEntry(
        data={"room_slug": "veg", "room_prefix": "veg_"}, entry_id="veg-entry"
    )


def test_transition_phase_default_room_uses_dt_util_and_unprefixed_select():
    hass = ha_stubs.FakeHass()
    h = _handlers(hass)
    asyncio.run(h["transition_phase"](Call(target_phase="P1", reason="test")))

    # select.select_option targeted the DEFAULT room's (un-prefixed) phase select
    assert hass.services.calls, "no service call made"
    domain, service, data = hass.services.calls[-1]
    assert (domain, service) == ("select", "select_option")
    assert data["entity_id"] == f"select.{DOMAIN}_irrigation_phase"

    # event fired with a real ISO timestamp (proves no hass.helpers.template crash)
    assert hass.bus.events, "no event fired"
    _etype, payload = hass.bus.events[-1]
    assert payload["room"] == "default"
    assert payload["timestamp"].startswith("2026-01-01")


def test_transition_phase_named_room_targets_prefixed_select():
    hass = ha_stubs.FakeHass(entries=[_veg_entry()])
    h = _handlers(hass)
    asyncio.run(h["transition_phase"](Call(target_phase="P2", room="veg")))

    _domain, _service, data = hass.services.calls[-1]
    assert data["entity_id"] == f"select.{DOMAIN}_veg_irrigation_phase"
    assert hass.bus.events[-1][1]["room"] == "veg"


def test_set_manual_override_named_room_targets_prefixed_switch():
    hass = ha_stubs.FakeHass(entries=[_veg_entry()])
    h = _handlers(hass)
    asyncio.run(h["set_manual_override"](Call(zone=2, room="veg", enable=True)))

    _domain, service, data = hass.services.calls[-1]
    assert service == "turn_on"
    assert data["entity_id"] == f"switch.{DOMAIN}_veg_zone_2_manual_override"


def test_unknown_room_raises_instead_of_steering_default():
    # Silently acting on a different room than the caller named is the wrong-room
    # hazard the room parameter exists to prevent — a typo must error, not water room 1.
    hass = ha_stubs.FakeHass()  # no entries → 'ghost' cannot resolve
    h = _handlers(hass)
    with pytest.raises(HomeAssistantError):
        asyncio.run(h["transition_phase"](Call(target_phase="P0", room="ghost")))
    assert hass.services.calls == []  # nothing actuated


def test_apply_recipe_without_store_raises():
    hass = ha_stubs.FakeHass()  # hass.data has no DOMAIN/_recipe
    h = _handlers(hass)
    with pytest.raises(HomeAssistantError):
        asyncio.run(h["apply_recipe"](Call(stage="Bulk")))


def test_save_recipe_without_store_raises():
    hass = ha_stubs.FakeHass()
    h = _handlers(hass)
    with pytest.raises(HomeAssistantError):
        asyncio.run(h["save_recipe"](Call(recipe={"stages": {}})))


def test_check_transition_conditions_missing_setpoints_no_crash():
    # phase select + avg sensors present, but the number entities are missing:
    # must warn and return, not raise AttributeError on a None state.
    hass = ha_stubs.FakeHass(
        states={
            f"select.{DOMAIN}_irrigation_phase": "P1",
            f"sensor.{DOMAIN}_configured_avg_vwc": "60",
            f"sensor.{DOMAIN}_configured_avg_ec": "3.0",
        }
    )
    h = _handlers(hass)
    # should complete without raising and fire no transition_check event
    asyncio.run(h["check_transition_conditions"](Call()))
    assert not any(e[0] == "crop_steering_transition_check" for e in hass.bus.events)
