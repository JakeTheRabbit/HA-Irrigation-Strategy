"""Room-scoped, reversible setup. Never sends commands to physical hardware."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime
import math

from .const import DOMAIN, MAX_ZONES
from .sizing import prefer_setup_value

API_VERSION = 1
HARDWARE_DOMAINS = {
    "pump_switch": {"switch"},
    "main_line_switch": {"switch"},
    "waste_switch": {"switch"},
    "light_entity": {"light", "switch"},
    "feed_ec_sensor": {"sensor"},
    "feed_ph_sensor": {"sensor"},
    "temperature_sensor": {"sensor"},
    "humidity_sensor": {"sensor"},
    "vpd_sensor": {"sensor"},
    "water_level_sensor": {"sensor"},
    "tank_temperature_sensor": {"sensor"},
    "tank_ec_sensor": {"sensor"},
    "tank_ph_sensor": {"sensor"},
    "tank_last_fill_sensor": {"sensor", "input_datetime"},
    "tank_fill_entity": {"switch", "binary_sensor"},
}
SIZING = {
    "plant_count": (1, 1000, True),
    "substrate_volume": (0.1, 200, False),
    "drippers_per_plant": (1, 20, True),
    "dripper_flow_rate": (0.1, 50, False),
}
UNITS = {
    "vwc": {"%"},
    "ec": {"ms/cm", "ds/m"},
    "ph": {"ph", ""},
    "tank_temperature": {"°c", "°f", "k"},
}


def effective(entry):
    return {**(entry.data or {}), **(getattr(entry, "options", None) or {})}


def hardware_entities(data):
    hw = data.get("hardware", {})
    return {
        entity
        for entity in [
            hw.get("pump_switch"),
            hw.get("main_line_switch"),
            hw.get("waste_switch"),
            *[z.get("zone_switch") for z in data.get("zones", {}).values()],
        ]
        if entity
    }


def engine_flag(hass, data):
    prefix = data.get("room_prefix", "")
    beat = hass.states.get(f"sensor.crop_steering_{prefix}ai_heartbeat")
    return (
        (beat.attributes.get("enable_flag") if beat else None)
        or data.get("enable_flag")
        or (
            f"switch.crop_steering_{prefix}engine_enabled"
            if prefix
            else "input_boolean.f2_control_enabled"
        )
    )


def safety_blockers(hass, entry=None, proposed=None):
    """Require affected engines and union of old/new plumbing definitively OFF."""
    old = effective(entry) if entry else {}
    entities = hardware_entities(old) | hardware_entities(proposed or {})
    affected = [entry] if entry else []
    # Sharing is transitive: an affected room can connect another pump/mainline.
    changed = True
    while changed:
        changed = False
        for other in hass.config_entries.async_entries(DOMAIN):
            if other in affected:
                continue
            other_hw = hardware_entities(effective(other))
            if entities.intersection(other_hw):
                affected.append(other)
                entities.update(other_hw)
                changed = True
    controls = {engine_flag(hass, effective(other)) for other in affected}
    # On first creation there is no existing engine, but an already present flag
    # (for example a restored default helper) must not be ON when hardware is mapped.
    if not entry and proposed:
        flag = engine_flag(hass, proposed)
        if hass.states.get(flag):
            controls.add(flag)
        if not proposed.get("room_prefix") and hass.states.get(
            "input_boolean.f2_control_enabled"
        ):
            controls.add("input_boolean.f2_control_enabled")
    return [
        f"{eid} must read OFF before changing setup"
        for eid in sorted(controls | entities)
        if not (state := hass.states.get(eid)) or state.state != "off"
    ]


def _entry(hass, entry_id):
    return next(
        (
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.entry_id == entry_id
        ),
        None,
    )


def _name(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 80:
        raise ValueError("Room and zone names must contain 1–80 characters")
    return value.strip()


def _entity(hass, eid, domains, kind=None):
    if not isinstance(eid, str) or eid.split(".")[0] not in domains:
        raise ValueError(
            f"Invalid entity domain for {eid!r}; expected {', '.join(sorted(domains))}"
        )
    state = hass.states.get(eid)
    if state is None:
        raise ValueError(f"Entity {eid} does not exist")
    if kind:
        unit = (
            str(state.attributes.get("unit_of_measurement", ""))
            .lower()
            .replace(" ", "")
        )
        if unit not in UNITS[kind]:
            raise ValueError(f"{eid}: incompatible {kind.upper()} unit {unit!r}")
    return eid


def _tank_timestamp(hass, eid):
    """Validate an explicit last-fill reading; never infer an event from state metadata."""
    state = hass.states.get(eid)
    unit = state.attributes.get("unit_of_measurement")
    device_class = state.attributes.get("device_class")
    if (unit is not None and str(unit).strip()) or device_class not in (
        None,
        "",
        "timestamp",
    ):
        raise ValueError(f"{eid}: last fill requires a unitless timestamp sensor")
    if eid.startswith("input_datetime."):
        if (
            state.attributes.get("has_date") is not True
            or state.attributes.get("has_time") is not True
        ):
            raise ValueError(
                f"{eid}: last fill helper must have both date and time enabled"
            )
        timestamp = state.attributes.get("timestamp")
        if type(timestamp) not in (int, float) or not math.isfinite(timestamp):
            raise ValueError(
                f"{eid}: last fill helper requires a finite epoch timestamp"
            )
        return
    if state.state in (None, "", "unknown", "unavailable"):
        return  # The mapping can be saved offline; the overview must show it as unknown.
    try:
        value = datetime.fromisoformat(state.state.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError):
        raise ValueError(
            f"{eid}: last fill requires an ISO timestamp with timezone"
        ) from None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{eid}: last fill timestamp must include a timezone")


def prepare_setup(hass, payload, old=None, entry_id=None):
    """Normalize a complete edit while retaining old fields and immutable IDs."""
    old = old or {}
    result = deepcopy(old)
    result["room_name"] = _name(
        payload.get("room_name", old.get("room_name", old.get("name", "Crop Steering")))
    )
    result["name"] = result["room_name"]
    active = payload.get("active", old.get("active", True))
    if type(active) is not bool:
        raise ValueError("active must be a boolean")
    result["active"] = active
    rows = payload.get("zones")
    if not isinstance(rows, list) or not rows or len(rows) > MAX_ZONES:
        raise ValueError(f"Provide 1–{MAX_ZONES} zone slots (archive unused slots)")
    old_zones = {int(k): v for k, v in old.get("zones", {}).items()}
    ids = [row.get("id") for row in rows if isinstance(row, dict)]
    if (
        len(ids) != len(rows)
        or any(type(z) is not int or z < 1 or z > MAX_ZONES for z in ids)
        or len(set(ids)) != len(ids)
    ):
        raise ValueError("Every zone requires a unique valid integer id")
    if not set(old_zones).issubset(ids):
        raise ValueError(
            "Existing zone IDs cannot disappear; archive the zone with active=false"
        )
    if sorted(ids) != list(range(1, max(ids) + 1)):
        raise ValueError("New zone IDs must append in sequential order")
    zones, allocated = {}, {}
    foreign_shared = set()
    for other in hass.config_entries.async_entries(DOMAIN):
        if other.entry_id == entry_id:
            continue
        cfg = effective(other)
        if not cfg.get("active", True):
            continue
        foreign_shared.update(
            cfg.get("hardware", {}).get(key)
            for key in ("pump_switch", "main_line_switch", "waste_switch")
            if cfg.get("hardware", {}).get(key)
        )
        for zone in cfg.get("zones", {}).values():
            if zone.get("active", True) and zone.get("zone_switch"):
                allocated[zone["zone_switch"]] = other.entry_id
    for row in rows:
        z = row["id"]
        prior = deepcopy(old_zones.get(z, {}))
        enabled = row.get("active", True)
        if type(enabled) is not bool:
            raise ValueError("Zone active must be a boolean")
        prior.update(
            zone_number=z,
            name=_name(row.get("name") or prior.get("name") or f"Zone {z}"),
            active=enabled,
        )
        valve = row.get("valve", prior.get("zone_switch", ""))
        if valve:
            _entity(hass, valve, {"switch"})
        elif enabled:
            raise ValueError(f"Zone {z}: select a valve")
        if enabled and active and valve:
            if valve in foreign_shared:
                raise ValueError(
                    f"Valve {valve} conflicts with another room's shared hardware role"
                )
            if valve in allocated:
                raise ValueError(
                    f"Valve {valve} is already allocated to an active zone"
                )
            allocated[valve] = entry_id or "new room"
        prior["zone_switch"] = valve
        for kind in ("vwc", "ec"):
            sensors = row.get(
                f"{kind}_sensors",
                prior.get(f"{kind}_sensors")
                or [
                    prior[k] for k in (f"{kind}_front", f"{kind}_back") if prior.get(k)
                ],
            )
            if (
                not isinstance(sensors, list)
                or len(sensors) > 32
                or len(set(sensors)) != len(sensors)
            ):
                raise ValueError(
                    "Sensor lists must contain at most 32 unique entity IDs"
                )
            for sensor in sensors:
                if not isinstance(sensor, str) or not sensor.startswith("sensor."):
                    raise ValueError("Sensor lists require sensor entity IDs")
                if enabled and active:
                    _entity(hass, sensor, {"sensor"}, kind)
            prior[f"{kind}_sensors"] = sensors
            prior[f"{kind}_front"] = sensors[0] if sensors else ""
            prior[f"{kind}_back"] = sensors[1] if len(sensors) > 1 else ""
        for key, (low, high, integer) in SIZING.items():
            value = row.get(key, prior.get(key))
            if value is None:
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (float, int))
                or not math.isfinite(value)
                or not low <= value <= high
                or (integer and int(value) != value)
            ):
                raise ValueError(f"{key} must be within {low}–{high}")
            prior[key] = int(value) if integer else float(value)
        zones[str(z)] = prior
    hw = deepcopy(old.get("hardware", {}))
    incoming = payload.get("hardware", {})
    if not isinstance(incoming, dict) or set(incoming) - set(HARDWARE_DOMAINS):
        raise ValueError("Unknown hardware mapping field")
    for key, value in incoming.items():
        if value:
            _entity(
                hass,
                value,
                HARDWARE_DOMAINS[key],
                (
                    "ec"
                    if key in ("feed_ec_sensor", "tank_ec_sensor")
                    else (
                        "ph"
                        if key in ("feed_ph_sensor", "tank_ph_sensor")
                        else (
                            "tank_temperature"
                            if key == "tank_temperature_sensor"
                            else None
                        )
                    )
                ),
            )
            if key == "tank_last_fill_sensor":
                _tank_timestamp(hass, value)
        hw[key] = value or ""
    shared = {
        hw.get("pump_switch"),
        hw.get("main_line_switch"),
        hw.get("waste_switch"),
    } - {None, ""}
    if any(
        entity in allocated and allocated[entity] != (entry_id or "new room")
        for entity in shared
    ):
        raise ValueError(
            "Shared hardware conflicts with another room's zone valve role"
        )
    if len(shared) != len(
        [
            hw[k]
            for k in ("pump_switch", "main_line_switch", "waste_switch")
            if hw.get(k)
        ]
    ):
        raise ValueError("Pump, mainline and waste must use different switches")
    if shared.intersection(
        z["zone_switch"] for z in zones.values() if z.get("active", True)
    ):
        raise ValueError("A valve cannot also be pump, mainline or waste")
    result.update(zones=zones, num_zones=max(ids), hardware=hw)
    return result


def configuration_payload(data):
    """Adapt existing/native-flow storage to the same validated operator payload."""
    rows = []
    for key, zone in data.get("zones", {}).items():
        rows.append(
            {
                "id": int(key),
                "name": zone.get("name", f"Zone {key}"),
                "active": zone.get("active", True),
                "valve": zone.get("zone_switch", ""),
                **{
                    f"{kind}_sensors": zone.get(f"{kind}_sensors")
                    or [
                        zone[k]
                        for k in (f"{kind}_front", f"{kind}_back")
                        if zone.get(k)
                    ]
                    for kind in ("vwc", "ec")
                },
                **{k: zone[k] for k in SIZING if k in zone},
            }
        )
    return {
        "room_name": data.get("room_name", data.get("name", "Crop Steering")),
        "active": data.get("active", True),
        "zones": rows,
        "hardware": {
            k: v for k, v in data.get("hardware", {}).items() if k in HARDWARE_DOMAINS
        },
    }


def setup_sizing(hass, data, cfg, zone, key):
    """Expose current hydraulic numbers without resetting a legacy room on save."""
    prefix = data.get("room_prefix", "")
    zone_state = hass.states.get(f"number.crop_steering_{prefix}zone_{zone}_{key}")
    if key in cfg and prefer_setup_value(
        zone_state.attributes if zone_state else {},
        data.get("setup_revision", 0),
        cfg[key],
    ):
        # An explicit save wins until its newly configured entity has reloaded.
        return cfg[key]
    room_state = hass.states.get(f"number.crop_steering_{prefix}{key}")
    low, high, integer = SIZING[key]
    for state in (zone_state, room_state):
        if state is None:
            continue
        try:
            value = float(state.state)
        except (ValueError, TypeError):
            continue
        if (
            math.isfinite(value)
            and low <= value <= high
            and (not integer or value.is_integer())
        ):
            return int(value) if integer else value
    return cfg.get(
        key,
        data.get("parameters", {}).get(
            key,
            {
                "plant_count": 4,
                "substrate_volume": 6,
                "drippers_per_plant": 1,
                "dripper_flow_rate": 2,
            }[key],
        ),
    )


def setup_room(hass, entry):
    data = effective(entry)
    zones = []
    for z in range(1, int(data.get("num_zones", 1)) + 1):
        cfg = data.get("zones", {}).get(str(z)) or data.get("zones", {}).get(z) or {}
        zones.append(
            {
                "id": z,
                "name": cfg.get("name", f"Zone {z}"),
                "active": cfg.get("active", True),
                "valve": cfg.get("zone_switch", ""),
                **{
                    f"{kind}_sensors": cfg.get(f"{kind}_sensors")
                    or [cfg[k] for k in (f"{kind}_front", f"{kind}_back") if cfg.get(k)]
                    for kind in ("vwc", "ec")
                },
                **{key: setup_sizing(hass, data, cfg, z, key) for key in SIZING},
            }
        )
    blockers = safety_blockers(hass, entry)
    return {
        "entry_id": entry.entry_id,
        "revision": int(data.get("setup_revision", 0)),
        "room_name": data.get("room_name", data.get("name", entry.title)),
        "prefix": data.get("room_prefix", ""),
        "slug": data.get("room_slug", "default"),
        "active": data.get("active", True),
        "num_zones": data.get("num_zones", 1),
        "active_zone_ids": [z["id"] for z in zones if z["active"]],
        "zones": zones,
        "hardware": {
            key: data.get("hardware", {}).get(key, "") for key in HARDWARE_DOMAINS
        },
        "safety": {"ready": not blockers, "blockers": blockers},
    }


def read_setup(hass):
    return {
        "api_version": API_VERSION,
        "capabilities": {
            "create": True,
            "save": True,
            "remove": True,
            "restore": True,
            "stable_zone_ids": True,
        },
        "limits": {"max_zones": MAX_ZONES},
        "rooms": [
            setup_room(hass, e) for e in hass.config_entries.async_entries(DOMAIN)
        ],
        "candidates": [
            {
                "entity_id": s.entity_id,
                "name": s.attributes.get("friendly_name", s.entity_id),
                "domain": s.entity_id.split(".")[0],
                "state": s.state,
                "unit": s.attributes.get("unit_of_measurement", ""),
                "device_class": s.attributes.get("device_class"),
            }
            for s in hass.states.async_all()
            if s.entity_id.split(".")[0]
            in {"sensor", "switch", "light", "binary_sensor", "input_datetime"}
        ],
    }


def _selected(hass, payload):
    entry = _entry(hass, payload.get("entry_id"))
    if entry is None:
        raise ValueError("Select an existing room entry")
    revision = effective(entry).get("setup_revision", 0)
    if (
        type(payload.get("expected_revision")) is not int
        or payload["expected_revision"] != revision
    ):
        raise ValueError("Room setup changed; refresh and review again")
    return entry


def _update(hass, entry, data):
    data["setup_revision"] = int(effective(entry).get("setup_revision", 0)) + 1
    # Old installations may have setup fields in options; remove only shadowing
    # fields we just updated, while retaining every unrelated option.
    options = {
        k: v
        for k, v in (getattr(entry, "options", None) or {}).items()
        if k
        not in {
            "room_name",
            "name",
            "active",
            "num_zones",
            "zones",
            "hardware",
            "parameters",
            "setup_revision",
        }
    }
    hass.config_entries.async_update_entry(
        entry, data=data, options=options, title=data.get("room_name", entry.title)
    )


async def save_setup(hass, payload):
    entry = _selected(hass, payload)
    data = prepare_setup(hass, payload, effective(entry), entry.entry_id)
    blockers = safety_blockers(hass, entry, data)
    if blockers:
        raise ValueError("; ".join(blockers))
    _update(hass, entry, data)
    return setup_room(hass, entry)


async def remove_setup(hass, payload):
    entry = _selected(hass, payload)
    data = deepcopy(effective(entry))
    if payload.get("confirm_name") != data.get(
        "room_name", data.get("name", entry.title)
    ):
        raise ValueError("Confirm the exact selected room name")
    blockers = safety_blockers(hass, entry)
    if blockers:
        raise ValueError("; ".join(blockers))
    data["active"] = False
    _update(hass, entry, data)
    return {
        "entry_id": entry.entry_id,
        "archived": True,
        "revision": data["setup_revision"],
    }


async def create_setup(hass, payload):
    # HA remains responsible for entry creation, unique IDs, and platform setup.
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data={"setup_payload": payload}
    )
    if result.get("type") != "create_entry":
        detail = (result.get("description_placeholders") or {}).get("error")
        raise ValueError(
            f"Room creation did not complete: {detail or result.get('reason') or result.get('errors') or result.get('type')}"
        )
    entry = result.get("result")
    return {
        "entry_id": entry.entry_id,
        "revision": effective(entry).get("setup_revision", 1),
        "reload_required": False,
    }


async def async_setup_setup_services(hass):
    """Response services are discoverable through the standard HA service registry."""
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError
    import voluptuous as vol

    state = hass.data.setdefault(DOMAIN, {}).setdefault("_setup", {})
    if state.get("services_registered"):
        return
    lock = state.setdefault("lock", asyncio.Lock())
    handlers = {
        "setup_read": read_setup,
        "setup_create": create_setup,
        "setup_save": save_setup,
        "setup_remove": remove_setup,
    }
    for name, handler in handlers.items():

        async def call(service_call, fn=handler, action=name):
            user_id = service_call.context.user_id
            user = await hass.auth.async_get_user(user_id) if user_id else None
            if user is None or not user.is_admin:
                raise HomeAssistantError(
                    "Setup requires an authenticated Home Assistant administrator"
                )
            try:
                async with lock:
                    result = (
                        fn(hass)
                        if action == "setup_read"
                        else await fn(hass, service_call.data)
                    )
            except (ValueError, TypeError) as err:
                raise HomeAssistantError(str(err)) from err
            return result if service_call.return_response else None

        hass.services.async_register(
            DOMAIN,
            name,
            call,
            schema=vol.Schema({}, extra=vol.ALLOW_EXTRA),
            supports_response=(
                SupportsResponse.ONLY
                if name == "setup_read"
                else SupportsResponse.OPTIONAL
            ),
        )
    state["services_registered"] = True
