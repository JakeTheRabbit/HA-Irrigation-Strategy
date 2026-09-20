"""Room-scoped, reversible setup. Never sends commands to physical hardware."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime
import math

from .const import DOMAIN, MAX_ZONES
from .sizing import prefer_setup_value
from .units import (
    EC_PROBLEM_AMBIGUOUS_PPM,
    EC_PROBLEM_MISSING,
    EC_UNIT_AUTO,
    EC_UNIT_CHOICES,
    ec_factor,
)

API_VERSION = 1

# How water reaches the zone valves: layout -> (needs a pump switch, needs a mainline switch).
# Published to the controller as the descriptor's `plumbing`. A room that has never declared
# one (every install from before layouts) is treated as the original three-stage system by
# the controller, so nothing about it changes. Keep in step with the controller's
# PLUMBING_LAYOUTS (tests/test_setup_wizard_rules.py pins them together).
PLUMBING_LAYOUTS = {
    "valves_only": (False, False),
    "pump_valves": (True, False),
    "mainline_valves": (False, True),
    "pump_mainline_valves": (True, True),
}


class SetupError(ValueError):
    """A setup rule that failed, with enough structure to show it next to the right field.

    `str(error)` is the same sentence callers have always received. `key` names a
    translatable message, `path` says what it is about - ("zone", 2, "ec_sensors"),
    ("hardware", "pump_switch"), ("plumbing",) - and `placeholders` fill the message in.
    """

    def __init__(self, message, *, key, path=(), **placeholders):
        super().__init__(message)
        self.key = key
        self.path = tuple(path)
        self.placeholders = {k: str(v) for k, v in placeholders.items()}
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
# EC is absent on purpose: probes report it in many units, so it is CONVERTED (units.ec_factor)
# rather than matched against a list.
UNITS = {
    "vwc": {"%"},
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


def _why_not_off(hass, eid):
    """None when `eid` definitively reads OFF, else what it reads instead."""
    state = hass.states.get(eid)
    if state is None:
        return "missing"
    if state.state == "off":
        return None
    return state.state if state.state in ("on", "unavailable", "unknown") else "other"


_NOT_OFF_DETAIL = {
    "on": "is ON",
    "unavailable": "is unavailable (its device is offline or still starting)",
    "unknown": "has not reported a state yet",
    "missing": "does not exist in Home Assistant",
    "other": "is not reporting on/off",
}


def safety_report(hass, entry=None, proposed=None):
    """[{entity_id, reason, detail}] for everything that must read OFF and does not.

    `reason` is on | unavailable | unknown | missing | other. "Must read OFF" used to be the
    whole message, which sent people hunting for a switch that was in fact offline.
    """
    return [
        {"entity_id": eid, "reason": reason, "detail": _NOT_OFF_DETAIL[reason]}
        for eid in _must_read_off(hass, entry, proposed)
        if (reason := _why_not_off(hass, eid))
    ]


def safety_blockers(hass, entry=None, proposed=None):
    """Require affected engines and union of old/new plumbing definitively OFF."""
    return [
        (
            f"{item['entity_id']} must read OFF before changing setup"
            if item["reason"] == "on"
            else f"{item['entity_id']} {item['detail']}; "
            "it must read OFF before changing setup"
        )
        for item in safety_report(hass, entry, proposed)
    ]


def _must_read_off(hass, entry=None, proposed=None):
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
    return sorted(controls | entities)


def _entry(hass, entry_id):
    return next(
        (
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.entry_id == entry_id
        ),
        None,
    )


def _name(value, path=()):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 80:
        raise SetupError(
            "Room and zone names must contain 1–80 characters",
            key="name_invalid",
            path=path,
        )
    return value.strip()


_EC_PROBLEM_TEXT = {
    EC_PROBLEM_AMBIGUOUS_PPM: (
        "{eid}: reports EC in ppm, which depends on the meter's scale; "
        "choose ppm (500 scale) or ppm (700 scale) as the EC unit"
    ),
    EC_PROBLEM_MISSING: (
        "{eid}: incompatible EC unit ''; it reports no unit, so choose the EC unit it uses"
    ),
}


def _entity(hass, eid, domains, kind=None, path=(), ec_hint=EC_UNIT_AUTO):
    """Validate one mapped entity. For an EC probe, returns its factor to mS/cm."""
    if not isinstance(eid, str) or eid.split(".")[0] not in domains:
        raise SetupError(
            f"Invalid entity domain for {eid!r}; expected {', '.join(sorted(domains))}",
            key="entity_wrong_domain",
            path=path,
            entity=eid,
            expected=", ".join(sorted(domains)),
        )
    state = hass.states.get(eid)
    if state is None:
        raise SetupError(
            f"Entity {eid} does not exist", key="entity_missing", path=path, entity=eid
        )
    if kind == "ec":
        declared = state.attributes.get("unit_of_measurement", "")
        factor, problem = ec_factor(declared, ec_hint)
        if problem:
            text = _EC_PROBLEM_TEXT.get(
                problem, "{eid}: incompatible EC unit {unit!r}"
            ).format(eid=eid, unit=str(declared or ""))
            raise SetupError(
                text, key=problem, path=path, entity=eid, unit=declared or ""
            )
        return factor
    if kind:
        unit = (
            str(state.attributes.get("unit_of_measurement", ""))
            .lower()
            .replace(" ", "")
        )
        if unit not in UNITS[kind]:
            raise SetupError(
                f"{eid}: incompatible {kind.upper()} unit {unit!r}",
                key=f"{kind}_unit",
                path=path,
                entity=eid,
                unit=unit,
            )
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
        payload.get(
            "room_name", old.get("room_name", old.get("name", "Crop Steering"))
        ),
        ("room_name",),
    )
    result["name"] = result["room_name"]
    active = payload.get("active", old.get("active", True))
    if type(active) is not bool:
        raise ValueError("active must be a boolean")
    result["active"] = active
    # Optional, additive fields. Absent from the payload = keep what the room already has;
    # absent from the room too = never declared, which the controller reads as the original
    # pump + mainline + valves system and the fused EC sensor reads as "believe the probe".
    plumbing = payload.get("plumbing", old.get("plumbing"))
    if plumbing is not None and plumbing not in PLUMBING_LAYOUTS:
        raise SetupError(
            f"Unknown plumbing layout {plumbing!r}; expected one of "
            f"{', '.join(PLUMBING_LAYOUTS)}",
            key="plumbing_unknown",
            path=("plumbing",),
        )
    ec_unit = payload.get("ec_unit", old.get("ec_unit", EC_UNIT_AUTO))
    if ec_unit not in EC_UNIT_CHOICES:
        raise SetupError(
            f"Unknown EC unit {ec_unit!r}; expected one of {', '.join(EC_UNIT_CHOICES)}",
            key="ec_unit_choice",
            path=("ec_unit",),
        )
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
            name=_name(
                row.get("name") or prior.get("name") or f"Zone {z}", ("zone", z, "name")
            ),
            active=enabled,
        )
        valve = row.get("valve", prior.get("zone_switch", ""))
        if valve:
            _entity(hass, valve, {"switch"}, path=("zone", z, "valve"))
        elif enabled:
            raise SetupError(
                f"Zone {z}: select a valve",
                key="zone_valve_missing",
                path=("zone", z, "valve"),
                zone=z,
            )
        if enabled and active and valve:
            if valve in foreign_shared:
                raise SetupError(
                    f"Valve {valve} conflicts with another room's shared hardware role",
                    key="valve_is_foreign_shared",
                    path=("zone", z, "valve"),
                    entity=valve,
                )
            if valve in allocated:
                raise SetupError(
                    f"Valve {valve} is already allocated to an active zone",
                    key="valve_already_allocated",
                    path=("zone", z, "valve"),
                    entity=valve,
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
                    raise SetupError(
                        "Sensor lists require sensor entity IDs",
                        key="entity_wrong_domain",
                        path=("zone", z, f"{kind}_sensors"),
                        entity=sensor,
                        expected="sensor",
                    )
                if enabled and active:
                    _entity(
                        hass,
                        sensor,
                        {"sensor"},
                        kind,
                        path=("zone", z, f"{kind}_sensors"),
                        ec_hint=ec_unit,
                    )
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
                raise SetupError(
                    f"{key} must be within {low}–{high}",
                    key="sizing_range",
                    path=("zone", z, key),
                    field=key,
                    low=low,
                    high=high,
                )
            prior[key] = int(value) if integer else float(value)
        zones[str(z)] = prior
    hw = deepcopy(old.get("hardware", {}))
    incoming = payload.get("hardware", {})
    if not isinstance(incoming, dict) or set(incoming) - set(HARDWARE_DOMAINS):
        raise ValueError("Unknown hardware mapping field")
    feed_ec_factor = old.get("feed_ec_factor", 1.0)
    for key, value in incoming.items():
        if value:
            checked = _entity(
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
                path=("hardware", key),
                ec_hint=ec_unit,
            )
            if key == "feed_ec_sensor":
                feed_ec_factor = checked
            if key == "tank_last_fill_sensor":
                _tank_timestamp(hass, value)
        elif key == "feed_ec_sensor":
            feed_ec_factor = 1.0
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
        raise SetupError(
            "Pump, mainline and waste must use different switches",
            key="hardware_duplicate",
            path=("hardware", "pump_switch"),
        )
    doubled = shared.intersection(
        z["zone_switch"] for z in zones.values() if z.get("active", True)
    )
    if doubled:
        role = next(
            k
            for k in ("pump_switch", "main_line_switch", "waste_switch")
            if hw.get(k) in doubled
        )
        raise SetupError(
            "A valve cannot also be pump, mainline or waste",
            key="valve_is_shared",
            path=("hardware", role),
            entity=hw[role],
        )
    if plumbing is not None and active:
        # A declared layout is a promise about which switches exist, checked both ways: a
        # stage it needs must be mapped, and a stage it rules out must not be - otherwise the
        # room would hold "incomplete" forever, or sequence a pump its operator said isn't there.
        for key, needed, name in (
            ("pump_switch", PLUMBING_LAYOUTS[plumbing][0], "pump"),
            ("main_line_switch", PLUMBING_LAYOUTS[plumbing][1], "mainline"),
        ):
            if needed and not hw.get(key):
                raise SetupError(
                    f"The {plumbing} plumbing layout needs a {name} switch",
                    key=f"plumbing_needs_{name}",
                    path=("hardware", key),
                )
            if not needed and hw.get(key):
                raise SetupError(
                    f"The {plumbing} plumbing layout has no {name} switch, "
                    f"but {hw[key]} is mapped as one",
                    key=f"plumbing_unused_{name}",
                    path=("hardware", key),
                    entity=hw[key],
                )
    result.update(zones=zones, num_zones=max(ids), hardware=hw)
    # Only ever ADD the newer fields: a room that never declared them saves exactly as before.
    if plumbing is not None:
        result["plumbing"] = plumbing
    if ec_unit != EC_UNIT_AUTO or "ec_unit" in old:
        result["ec_unit"] = ec_unit
    # Persisted at setup time, not re-derived live: an offline probe drops its unit attribute,
    # and a factor that flapped with it would read to the controller as a changed setup.
    if feed_ec_factor != 1.0 or "feed_ec_factor" in old:
        result["feed_ec_factor"] = feed_ec_factor
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
        **{k: data[k] for k in ("plumbing", "ec_unit") if data.get(k) is not None},
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
        # None = never declared (the controller then requires pump + mainline + valves).
        "plumbing": data.get("plumbing"),
        "ec_unit": data.get("ec_unit", EC_UNIT_AUTO),
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
            "plumbing",
            "ec_unit",
            "feed_ec_factor",
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
