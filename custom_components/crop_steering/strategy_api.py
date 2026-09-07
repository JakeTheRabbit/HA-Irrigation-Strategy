"""Response-bearing strategy services, always addressed by canonical room ID."""

from .const import DOMAIN

SERVICES = (
    "strategy_get",
    "strategy_save",
    "strategy_preview",
    "strategy_activate",
    "strategy_disarm",
)


def resolve_manager(hass, room_id):
    if not isinstance(room_id, str) or not room_id.startswith("room:"):
        raise ValueError("A canonical room_id is required")
    matches = [
        manager
        for manager in hass.data.get(DOMAIN, {}).get("_strategy", {}).values()
        if manager.room_id == room_id
    ]
    if len(matches) != 1:
        raise ValueError("Room is unknown or ambiguous")
    return matches[0]


async def async_setup_strategy_services(hass):
    import voluptuous as vol
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError

    async def handle(call):
        try:
            manager = resolve_manager(hass, call.data["room_id"])
            if call.service == "strategy_save":
                return await manager.save(
                    call.data["plan"], call.data["expected_revision"]
                )
            if call.service == "strategy_activate":
                return await manager.activate(call.data["expected_revision"])
            if call.service == "strategy_disarm":
                return await manager.disarm()
            result = manager.response()
            if call.service == "strategy_preview":
                result["preview"] = manager.preview(
                    call.data.get("plan"), call.data.get("date")
                )
            return result
        except (ValueError, KeyError) as error:
            raise HomeAssistantError(str(error)) from error

    for service in SERVICES:
        schema = {vol.Required("room_id"): str}
        if service in ("strategy_save", "strategy_activate"):
            schema[vol.Required("expected_revision")] = vol.All(int, vol.Range(min=0))
        if service == "strategy_save":
            schema[vol.Required("plan")] = dict
        elif service == "strategy_preview":
            schema[vol.Optional("plan")] = dict
            schema[vol.Optional("date")] = str
        hass.services.async_register(
            DOMAIN,
            service,
            handle,
            schema=vol.Schema(schema),
            supports_response=SupportsResponse.ONLY,
        )


async def async_unload_strategy_services(hass):
    for service in SERVICES:
        hass.services.async_remove(DOMAIN, service)
