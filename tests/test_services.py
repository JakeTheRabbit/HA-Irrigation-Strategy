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
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from . import ha_stubs

ha_stubs.install()

from custom_components.crop_steering import services  # noqa: E402
from custom_components.crop_steering.const import DOMAIN  # noqa: E402
from homeassistant.exceptions import HomeAssistantError  # noqa: E402


class Call:
    """Minimal ServiceCall stand-in, made with no user: an automation's call."""

    def __init__(self, **data):
        self.data = data
        self.context = SimpleNamespace(user_id=None)


def _handlers(hass):
    """Run async_setup_services and return the registered handler map."""
    asyncio.run(services.async_setup_services(hass))
    return {name: fn for (domain, name), fn in hass.services.registered.items()}


def _veg_entry():
    return ha_stubs.FakeEntry(
        data={"room_slug": "veg", "room_prefix": "veg_"}, entry_id="veg-entry"
    )


def test_set_manual_override_named_room_targets_prefixed_switch():
    override = SimpleNamespace(
        entity_id="switch.crop_steering_veg_zone_2_manual_override",
        _override_loaded=True,
        async_set_manual_override=AsyncMock(),
        extra_state_attributes={
            "manual_override_expires_at": "2026-01-01T13:00:00+00:00"
        },
    )
    hass = ha_stubs.FakeHass(
        entries=[_veg_entry()],
        data={DOMAIN: {"_manual_overrides": {"veg_zone_2_manual_override": override}}},
    )
    h = _handlers(hass)
    asyncio.run(h["set_manual_override"](Call(zone=2, room="veg", enable=True)))

    override.async_set_manual_override.assert_awaited_once_with(True, 60)
    assert hass.services.calls == []
    assert hass.bus.events[-1][1]["room"] == "veg"
    assert hass.bus.events[-1][1]["expires_at"] == "2026-01-01T13:00:00+00:00"
    # a real ISO timestamp (proves no hass.helpers.template crash)
    assert hass.bus.events[-1][1]["timestamp"].startswith("2026-01-01")


def test_unknown_room_raises_instead_of_steering_default():
    # Silently acting on a different room than the caller named is the wrong-room
    # hazard the room parameter exists to prevent — a typo must error, not water room 1.
    override = SimpleNamespace(
        entity_id=f"switch.{DOMAIN}_zone_1_manual_override",
        _override_loaded=True,
        async_set_manual_override=AsyncMock(),
        extra_state_attributes={"manual_override_expires_at": None},
    )
    # The default room's override is loaded, so a fallback to it would succeed.
    hass = ha_stubs.FakeHass(
        data={DOMAIN: {"_manual_overrides": {"zone_1_manual_override": override}}}
    )  # no entries → 'ghost' cannot resolve
    h = _handlers(hass)
    with pytest.raises(HomeAssistantError, match="Unknown crop_steering room 'ghost'"):
        asyncio.run(h["set_manual_override"](Call(zone=1, room="ghost")))
    override.async_set_manual_override.assert_not_awaited()
    assert hass.services.calls == [] and hass.bus.events == []  # nothing actuated


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
