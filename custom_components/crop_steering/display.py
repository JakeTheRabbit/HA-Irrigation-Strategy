"""What the dashboard shows in a room: the room's display options (Settings > Display).

One small store per room, published as sensor.crop_steering_<prefix>display: its state is the
revision, and each option is an attribute. Every option is off until someone turns it on, so a room
whose store is missing, unreadable or older than an option shows the dashboard as it always was.
The options only choose which panels the dashboard draws. Nothing here waters, reads a probe or
changes a setpoint, and the controller app does not read it.

Reading is open to any signed-in user (display_get); a save (display_save) needs an administrator,
as it changes what everyone who opens the room sees.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy

from .admin import async_require_admin
from .const import DOMAIN
from .room import room_prefix

SERVICES = ("display_get", "display_save")
SIGNAL = f"{DOMAIN}_display_changed"
# Each option: its default (always the dashboard as it was before the option) and, for a choice,
# the values it takes. A switch is True or False.
OPTIONS: dict[str, dict] = {
    # Today
    "today_tank_readout": {"default": False},
    "today_zone_layout": {"default": "cards", "choices": ("cards", "table")},
    # A zone's page
    "show_camera": {"default": False},
    "show_climate": {"default": False},
    "show_substrate_temp": {"default": False},
    "zone_day_deltas": {"default": False},
    # History
    "show_equipment_lanes": {"default": False},
    "show_room_day_lanes": {"default": False},
    "show_dryback_drivers": {"default": False},
    # Plan
    "planner_reference_rows": {"default": False},
    "planner_day_curve": {"default": False},
    # Units and clock: display only, per room. Storage and the API stay canonical.
    "ec_unit": {"default": "mS/cm", "choices": ("mS/cm", "ppm500", "ppm700")},
    "temp_unit": {"default": "C", "choices": ("C", "F")},
    # "auto" follows Home Assistant's unit system, as the dashboard does today.
    "volume_unit": {"default": "auto", "choices": ("auto", "L", "gal")},
    "clock": {"default": 24, "choices": (12, 24)},
}


def defaults() -> dict:
    return {key: spec["default"] for key, spec in OPTIONS.items()}


def clean_option(key, value):
    """The value a save may store for `key`; ValueError for an unknown key or a wrong value."""
    spec = OPTIONS.get(key)
    if spec is None:
        raise ValueError(f"Unknown display option: {key}")
    if "choices" in spec:
        # Same type first: True == 1 and 12.0 == 12 must not pass for a number choice.
        if type(value) not in {type(c) for c in spec["choices"]} or (
            value not in spec["choices"]
        ):
            choices = ", ".join(str(c) for c in spec["choices"])
            raise ValueError(f"{key} must be one of: {choices}")
        return value
    if type(value) is not bool:
        raise ValueError(f"{key} must be true or false")
    return value


def from_store(value) -> dict:
    """A stored document as (revision, options). An option this version does not know (saved by a
    newer one, before a rollback) or with a value it does not take is dropped, never the store.
    """
    if not isinstance(value, dict) or type(value.get("revision")) is not int:
        raise ValueError("Invalid stored revision")
    stored = value.get("options")
    options = {}
    for key, item in (stored if isinstance(stored, dict) else {}).items():
        try:
            options[key] = clean_option(key, item)
        except ValueError:
            continue
    return {"revision": max(value["revision"], 0), "options": options}


class DisplayOptions:
    def __init__(self, hass, entry, store=None):
        self.hass, self.entry = hass, entry
        self.prefix = room_prefix(entry)
        self.room_id = "room:" + self.prefix
        self._store = store
        self._lock = asyncio.Lock()
        self.document = {"revision": 0, "options": {}}
        self.error = None

    async def async_init(self):
        try:
            if self._store is None:
                from homeassistant.helpers.storage import Store

                self._store = Store(
                    self.hass, 1, f"{DOMAIN}.display.{self.entry.entry_id}"
                )
            value = await self._store.async_load()
            if value is not None:
                self.document = from_store(value)
        except Exception as error:
            # The dashboard then shows the room as it always did; a save is refused, so the file is
            # never overwritten.
            self.error = (
                "The stored display options could not be loaded; they have not been "
                f"overwritten: {error}"
            )

    def options(self) -> dict:
        return {**defaults(), **self.document["options"]}

    def sensor(self) -> tuple:
        """sensor.crop_steering_<prefix>display as (state, attributes): the revision, and every
        option with its value (the default where none is saved)."""
        attributes = self.options()
        if self.error:
            attributes["error"] = self.error
        return self.document["revision"], attributes

    def response(self) -> dict:
        return {
            "schema_version": 1,
            "room_id": self.room_id,
            "revision": self.document["revision"],
            "options": self.options(),
            "defaults": defaults(),
            "error": self.error,
        }

    async def save(self, expected_revision, changes) -> dict:
        async with self._lock:
            if self.error:
                raise ValueError(self.error)
            if expected_revision != self.document["revision"]:
                raise ValueError(
                    "Display options changed elsewhere. Reload before saving."
                )
            if not isinstance(changes, dict) or not changes:
                raise ValueError("Give at least one display option to save")
            options = dict(self.document["options"])
            for key, value in changes.items():
                options[key] = clean_option(key, value)
            document = {"revision": self.document["revision"] + 1, "options": options}
            await self._store.async_save(deepcopy(document))
            self.document = document
            from homeassistant.helpers.dispatcher import async_dispatcher_send

            async_dispatcher_send(self.hass, f"{SIGNAL}_{self.entry.entry_id}")
            return self.response()


def resolve_display(hass, room_id):
    if not isinstance(room_id, str) or not room_id.startswith("room:"):
        raise ValueError("A canonical room_id is required")
    matches = [
        manager
        for manager in hass.data.get(DOMAIN, {}).get("_display", {}).values()
        if manager.room_id == room_id
    ]
    if len(matches) != 1:
        raise ValueError("Room is unknown or ambiguous")
    return matches[0]


async def async_setup_display(hass, entry):
    import voluptuous as vol
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError

    manager = DisplayOptions(hass, entry)
    await manager.async_init()
    hass.data.setdefault(DOMAIN, {}).setdefault("_display", {})[
        entry.entry_id
    ] = manager

    async def handle(call):
        if call.service != "display_get":
            await async_require_admin(hass, call, f"{DOMAIN}.{call.service}")
        try:
            target = resolve_display(hass, call.data["room_id"])
            if call.service == "display_get":
                return target.response()
            return await target.save(
                call.data["expected_revision"], call.data["options"]
            )
        except (ValueError, OSError) as error:
            raise HomeAssistantError(str(error)) from error

    schemas = {
        "display_get": {vol.Required("room_id"): str},
        "display_save": {
            vol.Required("room_id"): str,
            vol.Required("expected_revision"): vol.All(int, vol.Range(min=0)),
            vol.Required("options"): dict,
        },
    }
    for service in SERVICES:
        hass.services.async_register(
            DOMAIN,
            service,
            handle,
            schema=vol.Schema(schemas[service]),
            supports_response=SupportsResponse.ONLY,
        )


async def async_unload_display(hass, entry):
    managers = hass.data.get(DOMAIN, {}).get("_display", {})
    managers.pop(entry.entry_id, None)
    if not managers:
        for service in SERVICES:
            hass.services.async_remove(DOMAIN, service)
