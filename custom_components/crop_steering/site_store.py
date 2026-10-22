"""The site store: settings that belong to the whole site and not to one room (spec 2.3).

Today it holds the supply section (G1): the irrigation pumps with their output and how many zones
they may feed at once, the exclusive groups, and the flow meter of a zone. This module is the pure
part: the stored document, the checks on what a save may contain, and the pump-capacity arithmetic
(which comes from generated/guards.py, never a copy). site_api.py stores it, serves it and publishes
sensor.crop_steering_supply_config.

A site with no store reads exactly as before: no pumps, no groups, nothing to check.
"""

from __future__ import annotations

import math
import re
from itertools import combinations

from .const import MAX_ZONES
from .generated.guards import worst_case_lph

SCHEMA_VERSION = 2
SUPPLY_SECTIONS = ("irrigation_pumps", "water_sources", "zone_groups", "zone_meters")
_ENTITY = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
_GROUP = re.compile(r"^[A-Za-z0-9_-]{1,24}$")


def empty() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": 0,
        "irrigation_pumps": [],
        "water_sources": [],
        "zone_groups": {},
        "zone_meters": {},
        "presets": [],
        "alert_rules": [],
    }


def supply_of(document: dict) -> dict:
    """The supply section of a document: the part supply_save replaces and the journal records."""
    return {key: document[key] for key in SUPPLY_SECTIONS}


def _entity(value, what):
    if not isinstance(value, str) or not _ENTITY.match(value):
        raise ValueError(f"{what} must be an entity id such as switch.pump_1")
    return value


def clean_pumps(value) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("irrigation_pumps must be a list")
    pumps, seen = [], set()
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("Each irrigation pump must be an object")
        entity = _entity(row.get("entity_id"), "A pump's entity_id")
        if entity in seen:
            raise ValueError(f"{entity} is listed twice")
        seen.add(entity)
        flow = row.get("max_flow_lph")
        if flow is not None:
            if type(flow) not in (int, float) or not math.isfinite(flow) or flow <= 0:
                raise ValueError(f"{entity}: max_flow_lph must be more than 0")
            flow = float(flow)
        concurrent = row.get("max_concurrent_zones", 1)
        if type(concurrent) is not int or not 1 <= concurrent <= MAX_ZONES:
            raise ValueError(
                f"{entity}: max_concurrent_zones must be a whole number from 1 to {MAX_ZONES}"
            )
        meter = row.get("flow_meter")
        pumps.append(
            {
                "entity_id": entity,
                "max_flow_lph": flow,
                "max_concurrent_zones": concurrent,
                "flow_meter": (
                    _entity(meter, f"{entity}: flow_meter") if meter else None
                ),
            }
        )
    return pumps


def clean_sources(value) -> list[dict]:
    if not isinstance(value, list) or not all(isinstance(r, dict) for r in value):
        raise ValueError("water_sources must be a list of objects")
    return [dict(row) for row in value]


def _by_room(value, what, check):
    """{"room:f2_": {"3": x}} with each x checked; an empty x drops the zone."""
    if not isinstance(value, dict):
        raise ValueError(f"{what} must be an object keyed by room_id")
    out = {}
    for room_id, zones in value.items():
        if not isinstance(room_id, str) or not room_id.startswith("room:"):
            raise ValueError(f"{what}: {room_id!r} is not a room_id such as room:f2_")
        if not isinstance(zones, dict):
            raise ValueError(f"{what}: {room_id} must map zone numbers to values")
        kept = {}
        for zone, item in zones.items():
            if not (
                isinstance(zone, str)
                and zone.isdigit()
                and 1 <= int(zone) <= MAX_ZONES
                and str(int(zone)) == zone
            ):
                raise ValueError(
                    f"{what}: zone {zone!r} must be a number from 1 to {MAX_ZONES} as text"
                )
            if item in (None, ""):
                continue
            kept[zone] = check(item, f"{what} {room_id} zone {zone}")
        if kept:
            out[room_id] = kept
    return out


def _group(value, what):
    if not isinstance(value, str) or not _GROUP.match(value):
        raise ValueError(f"{what} must be a short name (letters, digits, - or _)")
    return value


def clean_groups(value) -> dict:
    return _by_room(value, "zone_groups", _group)


def clean_meters(value) -> dict:
    return _by_room(value, "zone_meters", _entity)


def load(value) -> tuple[dict, list[dict]]:
    """A stored document and its warnings. A section this version cannot read reads as empty
    rather than refusing the store, and is named in the warnings [{section, error}]; the caller
    must not save over it unless the save replaces that section on purpose."""
    if not isinstance(value, dict) or type(value.get("revision")) is not int:
        raise ValueError("Invalid stored revision")
    document, warnings = empty(), []
    document["revision"] = max(value["revision"], 0)
    for key, clean in (
        ("irrigation_pumps", clean_pumps),
        ("water_sources", clean_sources),
        ("zone_groups", clean_groups),
        ("zone_meters", clean_meters),
    ):
        try:
            document[key] = clean(value.get(key, document[key]))
        except ValueError as error:
            warnings.append({"section": key, "error": str(error)})
    for key in ("presets", "alert_rules"):
        if isinstance(value.get(key), list):
            document[key] = value[key]
    return document, warnings


def from_store(value) -> dict:
    return load(value)[0]


def _suggest(demands, groups, max_flow):
    """The most zones the pump can feed at once with the worst mix, or None when it cannot be said."""
    if max_flow is None or not demands:
        return None
    best = 1
    for count in range(2, len(demands) + 1):
        if worst_case_lph(demands, groups, count) > max_flow:
            break  # the worst mix only grows with the count
        best = count
    return best


def _pump_check(pump, members, zone_groups):
    """members: [(room_id, zone, lph)] on this pump, in order. Returns (row, pairs)."""
    demands = {i: lph for i, (_, _, lph) in enumerate(members)}
    groups = {
        i: zone_groups.get(room_id, {}).get(str(zone))
        for i, (room_id, zone, _) in enumerate(members)
    }
    max_flow, concurrent = pump["max_flow_lph"], pump["max_concurrent_zones"]
    worst = worst_case_lph(demands, groups, concurrent)
    row = {
        "entity_id": pump["entity_id"],
        "worst_case_lph": worst,
        "max_flow_lph": max_flow,
        "max_concurrent_zones": concurrent,
        "ok": max_flow is None or worst <= max_flow,
        "suggest_max_concurrent": _suggest(demands, groups, max_flow),
    }
    pairs = []
    for a, b in combinations(range(len(members)), 2):
        lph = demands[a] + demands[b]
        shared = groups[a] is not None and groups[a] == groups[b]
        one_by_one = (
            shared or concurrent < 2 or (max_flow is not None and lph > max_flow)
        )
        same_room = members[a][0] == members[b][0]
        refs = [
            (
                members[i][1]
                if same_room
                else {"room_id": members[i][0], "zone": members[i][1]}
            )
            for i in (a, b)
        ]
        pairs.append(
            {
                "zones": refs,
                "lph": lph,
                "pct_of_pump": None if max_flow is None else lph / max_flow * 100,
                "verdict": "one_after_another" if one_by_one else "together",
            }
        )
    return row, pairs


def capacity_check(pumps, rooms, zone_groups) -> dict:
    """Can each pump feed the zones it is allowed to feed at once?

    rooms: [{"room_id", "pump": switch entity or "", "zones": {zone number: demand L/h}}], the
    active zones only. The headline numbers are those of the first pump that fails, else the one
    with the largest worst case; `pumps` has every pump's own row and `pairs` every pair of zones
    on a pump.
    """
    rows, pairs = [], []
    for pump in pumps:
        members = sorted(
            (room["room_id"], zone, lph)
            for room in rooms
            if room.get("pump") == pump["entity_id"]
            for zone, lph in room["zones"].items()
        )
        row, found = _pump_check(pump, members, zone_groups)
        rows.append(row)
        pairs.extend(found)
    headline = next(
        (r for r in rows if not r["ok"]),
        max(rows, key=lambda r: r["worst_case_lph"], default=None),
    )
    return {
        "worst_case_lph": headline["worst_case_lph"] if headline else 0.0,
        "max_flow_lph": headline["max_flow_lph"] if headline else None,
        "ok": all(r["ok"] for r in rows),
        "suggest_max_concurrent": (
            headline["suggest_max_concurrent"] if headline else None
        ),
        "pairs": pairs,
        "pumps": rows,
    }


def refuse_over_capacity(check) -> None:
    """ValueError 'pump_over_capacity: ...' when a pump is set to feed more zones at once than it can.

    One zone at a time is never refused here: a single zone bigger than its pump still waters (CS-214
    warns about it when the controller runs).
    """
    for row in check["pumps"]:
        if row["ok"] or row["max_concurrent_zones"] < 2:
            continue
        raise ValueError(
            f"pump_over_capacity: {row['entity_id']} cannot feed "
            f"{row['max_concurrent_zones']} zones at once: the worst mix needs "
            f"{row['worst_case_lph']:g} L/h and the pump gives {row['max_flow_lph']:g} L/h. "
            f"Set Zones at once to {row['suggest_max_concurrent']} or less."
        )
