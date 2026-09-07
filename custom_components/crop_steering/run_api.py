"""Response-only metadata services, isolated by canonical room identity."""

from .const import DOMAIN
from .run_store import RunStore

SERVICES = ("runs_get", "runs_save", "runs_archive", "runs_import")


def resolve_runs(hass, room_id):
    if not isinstance(room_id, str) or not room_id.startswith("room:"):
        raise ValueError("A canonical room_id is required")
    matches = [
        manager
        for manager in hass.data.get(DOMAIN, {}).get("_runs", {}).values()
        if manager.room_id == room_id
    ]
    if len(matches) != 1:
        raise ValueError("Run metadata room is unknown or ambiguous")
    return matches[0]


async def async_setup_runs(hass, entry):
    import voluptuous as vol
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError

    manager = RunStore(hass, entry)
    await manager.async_init()
    hass.data.setdefault(DOMAIN, {}).setdefault("_runs", {})[entry.entry_id] = manager

    async def handle(call):
        try:
            target = resolve_runs(hass, call.data["room_id"])
            if call.service == "runs_get":
                return target.response()
            return await target.mutate(call.service, call.data)
        except (ValueError, KeyError, OSError) as error:
            raise HomeAssistantError(str(error)) from error

    for service in SERVICES:
        schema = {vol.Required("room_id"): str}
        if service != "runs_get":
            schema[vol.Required("expected_revision")] = vol.All(int, vol.Range(min=0))
        if service == "runs_save":
            schema[vol.Required("record")] = dict
        elif service == "runs_archive":
            schema.update({vol.Required("id"): str, vol.Required("archived"): bool})
        elif service == "runs_import":
            schema[vol.Required("runs")] = vol.All(list, vol.Length(max=100))
        hass.services.async_register(
            DOMAIN,
            service,
            handle,
            schema=vol.Schema(schema),
            supports_response=SupportsResponse.ONLY,
        )


async def async_unload_runs(hass, entry):
    managers = hass.data.get(DOMAIN, {}).get("_runs", {})
    managers.pop(entry.entry_id, None)
    if not managers:
        for service in SERVICES:
            hass.services.async_remove(DOMAIN, service)
