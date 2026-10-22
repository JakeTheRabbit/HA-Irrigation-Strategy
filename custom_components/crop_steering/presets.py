"""Presets and copy (G10): a room's or a zone's settings captured by section, and written to other
rooms or zones with a preview diff and a read-back of every write.

Sections: `targets` (the strategy PARAMETERS as the room's own numbers, plus the zone's P2 mode),
`phase_timing`, `water_limits` and `timers` (the room's timer programs, or the one a zone is in).
A key is the number's own key without the zone prefix, so a zone's values apply to another zone or
to a room's own numbers. A key the destination has no entity for is listed as `missing`, never
written and never in the diff, so an apply whose every write held reads back an empty diff.

capture() and diff() are pure. write_numbers() writes through number.set_value (select.select_option
for the P2 mode), reads each state back and journals one target.changed per write; the room's
setpoint log still records the row but leaves the journal event to it. Nothing here runs a pump.
"""

from __future__ import annotations

import json
import logging
import math
from copy import deepcopy

from .const import DOMAIN
from .generated.ids import new_id
from .journal_api import note
from .room import room_prefix
from .strategy_model import MODE_KEYS, PARAMETERS

_LOGGER = logging.getLogger(__name__)

TARGETS = tuple(
    native for key in PARAMETERS for native in MODE_KEYS.get(key, (key,))
) + ("p2_mode",)
PHASE_TIMING = (
    "p0_minimum_wait",
    "p0_dryback_drop_percent",
    "p0_additional_dryback",
    "p1_minimum_shots",
    "p1_rise_pts",
    "p1_maximum_extra_shots",
    "p2_time_between_shots",
    "p2_timed_interval_min",
    "p2_timed_shot_size",
    "p2_timed_first_hours",
    "p2_end_hours_before_off",
    "p3_time_between_shots",
    "ec_min_interval",
    "ec_flush_target",
    "p2_dilute_ratio",
)
WATER_LIMITS = ("min_daily_ml_per_plant", "max_shot_duration")
# The zone numbers no section copies: its size and dripper layout, and the manual shot button's length.
NOT_COPIED = (
    "plant_count",
    "substrate_volume",
    "drippers_per_plant",
    "dripper_flow_rate",
    "manual_shot_seconds",
)
# A room's timer programs (`timers`) and the program a zone is in (`timer`).
SECTIONS = {
    "targets": TARGETS,
    "phase_timing": PHASE_TIMING,
    "water_limits": WATER_LIMITS,
    "timers": ("timers", "timer"),
}
SCOPES = {"targets": ("targets",), "timers": ("timers",), "all": tuple(SECTIONS)}
SELECTS = ("p2_mode",)
# What a timer program is without where it is stored.
_STORED = ("id", "created_at", "updated_at", "deleted_at")
# A copy never takes a zone or a room out of its timer programs (review ruling): when the source has
# none, the target keeps its own and the row is refused with this reason.
NO_TIMER = {
    "timer": "source zone has no timer program",
    "timers": "source room has no timer programs",
}


# ---------------------------------------------------------------------- pure
def capture(values: dict, sections) -> dict:
    """{section: {key: value}} of the `values` ({key: value}) each section holds."""
    return {
        section: {
            key: deepcopy(values[key]) for key in SECTIONS[section] if key in values
        }
        for section in sections
    }


def same(a, b) -> bool:
    numbers = all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in (a, b)
    )
    if numbers:
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-9)
    return a == b


def diff(current: dict, wanted: dict) -> list[dict]:
    """[{section, key, old, new}] for each wanted value the current one differs from; a key the
    current values do not have is {..., old: None, missing: True}."""
    rows = []
    for section, keys in wanted.items():
        have = current.get(section, {})
        for key, new in keys.items():
            if key not in have:
                rows.append(
                    {
                        "section": section,
                        "key": key,
                        "old": None,
                        "new": new,
                        "missing": True,
                    }
                )
            elif not same(have[key], new):
                rows.append(
                    {"section": section, "key": key, "old": have[key], "new": new}
                )
    return rows


def _shape(program) -> dict:
    return {k: deepcopy(v) for k, v in program.items() if k not in _STORED}


def timer_value(programs, zone=None):
    """A room's programs (zone None) as a list in a stable order, or the active program a zone is
    in without its zones (None when it is in none)."""
    if zone is None:
        return sorted(
            (_shape(p) for p in programs),
            key=lambda p: json.dumps(p, sort_keys=True, default=str),
        )
    for program in programs:
        if program.get("active", True) and zone in program.get("zones", ()):
            shape = _shape(program)
            shape.pop("zones", None)
            return shape
    return None


def zone_programs(programs, zone, wanted) -> list[dict]:
    """The room's programs with `zone` moved out of its active program (one left empty is
    dropped) and into the active program shaped as `wanted`, or a new one (wanted None: none).
    """
    out = []
    for program in deepcopy(programs):
        if program.get("active", True) and zone in program.get("zones", ()):
            program["zones"] = [z for z in program["zones"] if z != zone]
            if not program["zones"]:
                continue
        out.append(program)
    if wanted is None:
        return out
    for program in out:
        shape = _shape(program)
        shape.pop("zones", None)
        if program.get("active", True) and shape == wanted:
            program["zones"] = sorted([*program["zones"], zone])
            return out
    out.append({**deepcopy(wanted), "zones": [zone]})
    return out


# ---------------------------------------------------------------------- Home Assistant
def _entry(hass, room_id=None, entry_id=None):
    matches = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.entry_id == entry_id or (room_id and "room:" + room_prefix(e) == room_id)
    ]
    if len(matches) != 1:
        raise ValueError(f"Room {room_id or entry_id} is unknown or ambiguous")
    return matches[0]


def ref(target) -> dict:
    """A target as {room_id, zone?}, or ValueError."""
    if not isinstance(target, dict) or not isinstance(target.get("room_id"), str):
        raise ValueError("Each target needs a room_id such as room:f2_")
    if not target["room_id"].startswith("room:"):
        raise ValueError(f"{target['room_id']!r} is not a room_id such as room:f2_")
    zone = target.get("zone")
    if zone is None:
        return {"room_id": target["room_id"]}
    if type(zone) is not int or zone < 1:
        raise ValueError("zone must be a whole number from 1")
    return {"room_id": target["room_id"], "zone": zone}


def _resolve(hass, target):
    """-> (entry, zone, {key: entity_id}) of a target, or ValueError."""
    target = ref(target)
    entry, zone = _entry(hass, room_id=target["room_id"]), target.get("zone")
    numbers = hass.data.get(DOMAIN, {}).get("_numbers", {}).get(entry.entry_id)
    if numbers is None:
        raise ValueError(f"Room {target['room_id']} is not loaded")
    if zone is not None and f"zone_{zone}_plant_count" not in numbers:
        raise ValueError(f"Zone {zone} is not in room {target['room_id']}")
    entities = {}
    for section in ("targets", "phase_timing", "water_limits"):
        for key in SECTIONS[section]:
            if key in SELECTS:
                if zone is not None:
                    entity_id = f"select.{DOMAIN}_{room_prefix(entry)}zone_{zone}_{key}"
                    if hass.states.get(entity_id) is not None:
                        entities[key] = entity_id
                continue
            number = numbers.get(key if zone is None else f"zone_{zone}_{key}")
            if number is not None:
                entities[key] = number.entity_id
    return entry, zone, entities


def _state(hass, entity_id):
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable"):
        return None
    if entity_id.startswith("select."):
        return state.state
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _timers(hass, entry, zone):
    """The target's timer value under its key, or {} when the room's timers cannot be read."""
    from . import timers_api

    room = hass.data.get(DOMAIN, {}).get("_timers", {}).get(entry.entry_id)
    if room is None or room.error:
        return {}
    programs = timers_api.get_programs(hass, entry.entry_id)
    return {"timers" if zone is None else "timer": timer_value(programs, zone)}


def _values(hass, entry, zone, entities) -> dict:
    values = {}
    for key, entity_id in entities.items():
        value = _state(hass, entity_id)
        if value is not None:
            values[key] = value
    values.update(_timers(hass, entry, zone))
    return values


def read_values(hass, target) -> dict:
    """{key: value} of every setting a target has that reads now."""
    return _values(hass, *_resolve(hass, target))


def read_source(hass, target, sections) -> tuple[dict, list]:
    """(capture of the target's `sections`, [key]) where the keys are the settings of those
    sections the target has but that cannot be read now (unavailable, or timers not loaded).
    """
    entry, zone, entities = _resolve(hass, target)
    values = _values(hass, entry, zone, entities)
    keys = [k for s in sections for k in SECTIONS[s]]
    timer = "timers" if zone is None else "timer"
    skipped = [k for k in entities if k in keys and k not in values]
    if timer in keys and timer not in values:
        skipped.append(timer)
    return capture(values, sections), skipped


async def write_numbers(
    hass, entry_id: str, writes: list[dict], actor: dict
) -> list[dict]:
    """Write [{entity_id, key, value, zone?}] in the room of `entry_id` and read each back.

    -> [{entity_id, key, old, new, readback: verified|refused, error}], `new` being the state read
    after the write and `error` what the entity said when it refused one (else None). A write the entity refuses (a moisture level waiting for its neighbour) is tried
    again after the others while any of them lands; a refused one never stops the rest. Each write
    journals target.changed with `actor` ({actor, user_id, client}, optional detail,
    causation_id and proposal_token).
    """
    from homeassistant.core import Context

    from . import setpoint_log

    room_id = "room:" + room_prefix(_entry(hass, entry_id=entry_id))
    log = setpoint_log.log_for(hass, entry_id)
    context = Context(user_id=actor.get("user_id"))
    old = [_state(hass, w["entity_id"]) for w in writes]
    errors, pending = {}, list(range(len(writes)))
    if log is not None:
        log.quiet.add(
            context.id
        )  # these writes are journaled here, with their readback
    try:
        await _write_all(hass, writes, pending, errors, context)
    finally:
        if log is not None:
            log.quiet.discard(context.id)
    results = []
    for i, write in enumerate(writes):
        now = _state(hass, write["entity_id"])
        verified = i not in errors and now is not None and same(now, write["value"])
        readback = "verified" if verified else "refused"
        results.append(
            {
                "entity_id": write["entity_id"],
                "key": write["key"],
                "old": old[i],
                "new": now,
                "readback": readback,
                "error": errors.get(i),
            }
        )
        zone = write.get("zone")
        note(
            hass,
            room_id,
            "target.changed",
            zone=zone,
            outcome="ok" if verified else "refused",
            actor=actor.get("actor", "system"),
            detail=actor.get("detail"),
            user_id=actor.get("user_id"),
            client=actor.get("client"),
            correlation={
                "causation_id": actor.get("causation_id"),
                "proposal_token": actor.get("proposal_token"),
            },
            readback=readback,
            data={
                "key": write["key"],
                "scope": "room" if zone is None else f"zone:{zone}",
                "layer": "base",
                "old": old[i],
                "new": now,
                "requested": write["value"],
                "error": errors.get(i),
                "entity_id": write["entity_id"],
            },
        )
    return results


async def _write_all(hass, writes, pending, errors, context):
    """Each write in turn; the ones refused again while any other lands."""
    while pending:
        failed = []
        for i in pending:
            entity_id, value = writes[i]["entity_id"], writes[i]["value"]
            try:
                if entity_id.startswith("select."):
                    domain, service, data = "select", "select_option", {"option": value}
                else:
                    domain, service, data = "number", "set_value", {"value": value}
                await hass.services.async_call(
                    domain,
                    service,
                    {"entity_id": entity_id, **data},
                    blocking=True,
                    context=context,
                )
                errors.pop(i, None)
            except Exception as error:  # noqa: BLE001 - reported as refused
                errors[i] = str(error)
                failed.append(i)
        if len(failed) == len(pending):
            return
        pending = failed


async def _write_timers(hass, entry, zone, wanted, actor) -> tuple[str, str | None]:
    """-> (readback, error)."""
    from . import timers_api

    key = "timers" if zone is None else "timer"
    error = None
    try:
        room_id = "room:" + room_prefix(entry)
        revision = timers_api.list_programs(hass, room_id)["revision"]
        current = timers_api.get_programs(hass, entry.entry_id)
        programs = (
            deepcopy(wanted) if zone is None else zone_programs(current, zone, wanted)
        )
        await timers_api.set_programs(hass, entry.entry_id, programs, revision, actor)
    except Exception as failed:  # noqa: BLE001 - reported as refused
        error = str(failed)
        _LOGGER.warning("Crop Steering presets: timers not written: %s", error)
    if _timers(hass, entry, zone).get(key, ...) == wanted:
        return "verified", None
    return "refused", error or "the timer programs read back different"


async def apply(hass, wanted: dict, targets: list, preview: bool, actor: dict) -> dict:
    """Write `wanted` ({section: {key: value}}) to each target, or (preview) only say what would
    change. -> {diff: [{target, key, old, new}], missing: [{target, key, reason?}], applied?:
    [{target, key, readback, error}]}. Every target is resolved before anything is written. A
    target is never taken out of its timer programs by a source that has none (NO_TIMER).
    """
    if not isinstance(targets, list) or not targets:
        raise ValueError("Give at least one target")
    resolved = [(ref(t), *_resolve(hass, t)) for t in targets]
    out, plans, refused = {"diff": [], "missing": []}, [], []
    for target, entry, zone, entities in resolved:
        current = capture(_values(hass, entry, zone, entities), wanted)
        rows = []
        for row in diff(current, wanted):
            if row.get("missing"):
                out["missing"].append({"target": target, "key": row["key"]})
                continue
            if row["section"] == "timers" and not row["new"]:
                reason = NO_TIMER[row["key"]]
                out["missing"].append(
                    {"target": target, "key": row["key"], "reason": reason}
                )
                refused.append(
                    {
                        "target": target,
                        "key": row["key"],
                        "readback": "refused",
                        "error": reason,
                    }
                )
                continue
            rows.append(row)
            out["diff"].append(
                {
                    "target": target,
                    "key": row["key"],
                    "old": row["old"],
                    "new": row["new"],
                }
            )
        plans.append((target, entry, zone, entities, rows))
    if preview:
        return out
    actor = {**actor, "causation_id": new_id()}
    applied = []
    for target, entry, zone, entities, rows in plans:
        writes = [
            {
                "entity_id": entities[r["key"]],
                "key": r["key"],
                "value": r["new"],
                "zone": zone,
            }
            for r in rows
            if r["section"] != "timers"
        ]
        for result in await write_numbers(hass, entry.entry_id, writes, actor):
            applied.append(
                {
                    "target": target,
                    "key": result["key"],
                    "readback": result["readback"],
                    "error": result["error"],
                }
            )
        for row in rows:
            if row["section"] == "timers":
                readback, error = await _write_timers(
                    hass, entry, zone, row["new"], actor
                )
                applied.append(
                    {
                        "target": target,
                        "key": row["key"],
                        "readback": readback,
                        "error": error,
                    }
                )
    out["applied"] = applied + refused
    return out
