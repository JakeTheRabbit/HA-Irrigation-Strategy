"""Safety and operations: the room's Stop all, and the opt-in settings the controller app reads for them.

Every setting here starts at the value that keeps what a room did before it existed: a select at Off, a
switch off, a tank size of 0, a manual shot of the Test Shot's 10 s. The controller app reads each one by
entity id and treats one it cannot read the same way.

Stop all is here, in the integration, so it works with the controller app stopped: it switches the room's kill
switch off, then switches off the room's pump, main line, waste valve and every zone valve, and reads each one
back. It never switches anything on. A device that still reads on raises a notification (CS-308).
"""

from __future__ import annotations

import asyncio
import logging
import time

from homeassistant.components.number import NumberEntityDescription
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.const import PERCENTAGE, UnitOfTime, UnitOfVolume

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

RESCUE_MISS_ACTIONS = ["Off", "Alert"]
WASTE_VALVE_RULES = ["Off", "Check closed", "Close for each shot"]
STOP_READBACK_S = 10.0  # how long a device may take to report OFF after Stop all
OFF_STATES = ("off", "closed")

# Room numbers: (description, starting value).
ROOM_NUMBERS = [
    (
        NumberEntityDescription(
            key="rescue_miss_count",
            name="Rescue misses before alert",
            icon="mdi:water-alert",
            native_min_value=1,
            native_max_value=20,
            native_step=1,
            mode="box",
        ),
        4,
    ),
    (
        NumberEntityDescription(
            key="tank_size_l",
            name="Tank size (estimate)",
            icon="mdi:storage-tank-outline",
            native_min_value=0,
            native_max_value=100000,
            native_step=1,
            native_unit_of_measurement=UnitOfVolume.LITERS,
            mode="box",
        ),
        0,
    ),
    (
        NumberEntityDescription(
            key="tank_estimate_low_pct",
            name="Estimated tank low alert",
            icon="mdi:storage-tank-outline",
            native_min_value=1,
            native_max_value=90,
            native_step=1,
            native_unit_of_measurement=PERCENTAGE,
            mode="box",
        ),
        20,
    ),
    (
        NumberEntityDescription(
            key="pump_deadhead_watts",
            name="Pump dead-head power",
            icon="mdi:pump-off",
            native_min_value=1,
            native_max_value=10000,
            native_step=1,
            native_unit_of_measurement="W",
            mode="box",
        ),
        20,
    ),
]


def zone_numbers(zone: int):
    """The zone's numbers: (description, starting value)."""
    return [
        (
            NumberEntityDescription(
                key=f"zone_{zone}_manual_shot_seconds",
                name=f"Zone {zone} manual shot length",
                icon="mdi:timer-play-outline",
                native_min_value=5,
                native_max_value=3600,
                native_step=1,
                native_unit_of_measurement=UnitOfTime.SECONDS,
                mode="box",
            ),
            10,
        )
    ]


SELECTS = [
    # CS-315: count rescue shots that do not raise the moisture, and alert. Never stops water.
    SelectEntityDescription(
        key="rescue_miss_action",
        name="Rescue shots not absorbed",
        icon="mdi:water-alert",
        options=RESCUE_MISS_ACTIONS,
    ),
    # CS-316: what the controller does with the room's waste valve around a shot. Off: nothing, as before.
    SelectEntityDescription(
        key="waste_valve_rule",
        name="Waste valve rule",
        icon="mdi:valve-closed",
        options=WASTE_VALVE_RULES,
    ),
]

SWITCHES = [
    # While the feed EC or pH probe is dead, a P3 emergency or watchdog rescue still passes the source-water
    # gate. Off (as before): a dead probe holds every shot.
    SwitchEntityDescription(
        key="rescue_past_dead_feed_probe",
        name="Rescues past a dead feed probe",
        icon="mdi:water-alert-outline",
    ),
]


def room_devices(data: dict) -> list[str]:
    """The room's pump, main line, waste valve and every zone valve, from its setup."""
    hw = data.get("hardware") or {}
    zones = data.get("zones") or {}
    found = [
        hw.get("pump_switch"),
        hw.get("main_line_switch"),
        hw.get("waste_switch"),
        *[(z or {}).get("zone_switch") for z in zones.values()],
    ]
    return list(dict.fromkeys(e for e in found if e))


def _off_call(entity_id: str) -> tuple[str, str]:
    domain = entity_id.split(".", 1)[0]
    return (domain, "close_valve") if domain == "valve" else (domain, "turn_off")


async def async_stop_all(hass, entry, context=None) -> dict:
    """Kill switch off, then every pump and valve of the room off, read back. Never switches anything on."""
    from homeassistant.components import persistent_notification

    from .room import default_gate, room_gate, room_prefix
    from .setup_api import effective

    prefix = room_prefix(entry)
    data = effective(entry)
    gates = list(dict.fromkeys([room_gate(hass, prefix), default_gate(prefix)]))
    devices = room_devices(data)
    asked, refused = [], []
    for entity_id in [g for g in gates if hass.states.get(g) is not None] + devices:
        domain, service = _off_call(entity_id)
        try:
            await asyncio.wait_for(
                hass.services.async_call(
                    domain,
                    service,
                    {"entity_id": entity_id},
                    blocking=True,
                    context=context,
                ),
                STOP_READBACK_S,
            )
            asked.append(entity_id)
        except (
            Exception
        ) as err:  # noqa: BLE001 - reported below; the others are still switched off
            _LOGGER.warning(
                "Stop all: %s could not be switched off: %s", entity_id, err
            )
            refused.append(entity_id)
    end = time.monotonic() + STOP_READBACK_S
    while True:
        still_on = [
            e
            for e in devices
            if getattr(hass.states.get(e), "state", None) not in OFF_STATES
        ]
        if not still_on or time.monotonic() >= end:
            break
        await asyncio.sleep(0.5)
    name = data.get("room_name") or data.get("name") or prefix.rstrip("_") or "the room"
    _LOGGER.warning(
        "Stop all in %s: kill switch off; switched off %s%s",
        name,
        ", ".join(asked) or "nothing",
        f"; still not off: {', '.join(still_on)}" if still_on else "",
    )
    if still_on:
        persistent_notification.async_create(
            hass,
            "Stop all switched these off, but they do not read off: "
            f"{', '.join(still_on)}. Water can still flow. CAUTION: Go to the room now and stop them by "
            "hand. Code CS-308.",
            title=f"Crop Steering: {name}: Stop all, devices still on (CS-308)",
            notification_id=f"{DOMAIN}_stop_all_{prefix or 'default'}",
        )
    return {
        "kill_switch": [g for g in gates if g in asked],
        "switched_off": [e for e in asked if e in devices],
        "refused": refused,
        "still_on": still_on,
    }


async def async_setup_stop_all(hass):
    """The crop_steering.stop_all service, by canonical room id. Any user may call it: it only stops."""
    import voluptuous as vol
    from .api_v2 import fields, wrap
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError

    from .room import room_prefix

    async def handle(call):
        room_id = call.data["room_id"]
        if not room_id.startswith("room:"):
            raise HomeAssistantError("A canonical room_id is required")
        prefix = room_id[len("room:") :]
        for entry in hass.config_entries.async_entries(DOMAIN):
            if room_prefix(entry) == prefix:
                return await async_stop_all(hass, entry, call.context)
        raise HomeAssistantError(f"No room {room_id}")

    hass.services.async_register(
        DOMAIN,
        "stop_all",
        wrap(handle),
        schema=vol.Schema(fields({vol.Required("room_id"): str})),
        supports_response=SupportsResponse.OPTIONAL,
    )
