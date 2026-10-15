"""A test a person runs from the dashboard: a zone's test shot.

test_shot presses a zone's Test Shot button (button.py), which the controller app reads by entity id
and answers with a 10-second shot in that zone, through every check a shot passes but a held grow
plan's. Response-only, by canonical room id ("room:" and the room's prefix), for an administrator.
"""

from __future__ import annotations

from .admin import async_require_admin
from .const import DOMAIN

SERVICES = ("test_shot",)


def shot_button(room_id, zone) -> str:
    """The zone's Test Shot button, by the room's canonical id."""
    if not isinstance(room_id, str) or not room_id.startswith("room:"):
        raise ValueError("A canonical room_id is required")
    return f"button.{DOMAIN}_{room_id[len('room:'):]}zone_{zone}_test_shot"


async def async_setup_selftest(hass):
    import voluptuous as vol
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError

    async def handle(call):
        await async_require_admin(hass, call, f"{DOMAIN}.{call.service}")
        try:
            entity_id = shot_button(call.data["room_id"], call.data["zone"])
            state = hass.states.get(entity_id)
            if state is None or state.state == "unavailable":
                raise ValueError(f"This room has no zone {call.data['zone']} to test")
            await hass.services.async_call(
                "button",
                "press",
                {"entity_id": entity_id},
                blocking=True,
                context=call.context,
            )
            pressed = hass.states.get(entity_id)
            return {"requested": pressed.state if pressed else None}
        except (ValueError, KeyError) as error:
            raise HomeAssistantError(str(error)) from error

    hass.services.async_register(
        DOMAIN,
        "test_shot",
        handle,
        schema=vol.Schema(
            {
                vol.Required("room_id"): str,
                vol.Required("zone"): vol.All(int, vol.Range(min=1)),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )


async def async_unload_selftest(hass):
    """Remove the service with the last room."""
    for service in SERVICES:
        hass.services.async_remove(DOMAIN, service)
