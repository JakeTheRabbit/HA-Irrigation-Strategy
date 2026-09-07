"""Pure, versioned grower-authored strategy plans; no HA or hardware IO."""

from __future__ import annotations

import copy
import math
import re
from datetime import date

SCHEMA_VERSION = 1
REQUIRED_PARAMETERS = (
    "dryback_target",
    "ec_target_p0",
    "ec_target_p1",
    "ec_target_p2",
    "p1_target_vwc",
    "p2_vwc_threshold",
    "p2_shot_size",
    "p1_initial_shot_size",
    "p3_emergency_vwc_threshold",
    "p3_emergency_shot_size",
)
PARAMETERS = REQUIRED_PARAMETERS + (
    "p1_shot_size_increment",
    "p1_maximum_shots",
    "p1_time_between_shots",
    "p0_maximum_wait_time",
    "max_daily_volume",
    "field_capacity",
    "maximum_ec",
    "watchdog_hours",
)
# Canonical strategy keys mapped to the engine's validate_params limits.
# Existing HA entities retain their historical ranges; only new plans intersect these.
ENGINE_BOUNDS = {
    "p1_target_vwc": (20.0, 85.0),
    "p2_vwc_threshold": (10.0, 70.0),
    "ec_target_p0": (0.5, 9.0),
    "ec_target_p1": (0.5, 9.0),
    "ec_target_p2": (0.5, 9.0),
    "dryback_target": (2.0, 60.0),
    "p3_emergency_vwc_threshold": (10.0, 60.0),
    "field_capacity": (40.0, 90.0),
    "maximum_ec": (3.0, 15.0),
    "watchdog_hours": (0.0, 12.0),
    "p2_shot_size": (0.5, 20.0),
    "p1_initial_shot_size": (0.5, 15.0),
    "p1_shot_size_increment": (0.0, 5.0),
    "p1_maximum_shots": (1.0, 40.0),
    "p1_time_between_shots": (1.0, 120.0),
    "p0_maximum_wait_time": (5.0, 240.0),
    "p3_emergency_shot_size": (0.5, 15.0),
    "max_daily_volume": (10.0, 2000.0),
}
MODE_KEYS = {
    "dryback_target": ("vegetative_dryback_target", "generative_dryback_target"),
    **{
        f"ec_target_p{p}": (f"ec_target_veg_p{p}", f"ec_target_gen_p{p}")
        for p in range(3)
    },
}


def finite(value, label="value"):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def integer(value, low, high, label):
    number = finite(value, label)
    if number != int(number) or not low <= number <= high:
        raise ValueError(f"{label} must be an integer between {low} and {high}")
    return int(number)


def identifier(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", value):
        raise ValueError(f"Invalid {label}")
    return value


def interpolate(vegetative, generative, bias, catalog=None):
    weight = finite(bias, "bias") / 100
    if not 0 <= weight <= 1 or set(vegetative) != set(generative):
        raise ValueError("Bias must be 0..100 and endpoint parameters must match")
    result = {}
    for key, start in vegetative.items():
        value = finite(start, key) + (finite(generative[key], key) - start) * bias / 100
        bounds = (catalog or {}).get(key)
        if bounds and bounds.get("step", 0) > 0:
            value = (
                bounds["min"]
                + math.floor((value - bounds["min"]) / bounds["step"] + 0.5)
                * bounds["step"]
            )
        result[key] = (
            int(math.floor(value + 0.5))
            if key == "p1_maximum_shots"
            else math.floor(value * 1_000_000 + 0.5) / 1_000_000
        )
    return result


def dryback_target_vwc(reference_peak, target):
    """The current engine's dryback setting is relative percent of detected peak."""
    peak, drop = finite(reference_peak, "reference_peak"), finite(
        target, "dryback_target"
    )
    if peak < 0 or not 0 <= drop <= 100:
        raise ValueError("Invalid peak or relative dryback target")
    return round(peak * (1 - drop / 100), 6)


def validate_relationships(values):
    if values["p2_vwc_threshold"] >= values["p1_target_vwc"]:
        raise ValueError("P2 VWC threshold must be below the P1 target")
    if values["p3_emergency_vwc_threshold"] + 3 > values["p2_vwc_threshold"]:
        raise ValueError(
            "P2 threshold must be at least 3 points above the emergency floor"
        )
    if (
        "field_capacity" in values
        and values["p1_target_vwc"] > values["field_capacity"]
    ):
        raise ValueError("P1 target exceeds field capacity")
    if (
        "maximum_ec" in values
        and max(values[f"ec_target_p{p}"] for p in range(3)) > values["maximum_ec"]
    ):
        raise ValueError("Phase EC target exceeds maximum EC")


def normalize_plan(plan, zone_ids, catalog):
    """Validate all assignments against this room's actual readable number bounds."""
    if not isinstance(plan, dict) or plan.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported strategy schema_version")
    profiles = plan.get("profiles")
    zones = plan.get("zones")
    if not isinstance(profiles, list) or not 1 <= len(profiles) <= 64:
        raise ValueError("Provide 1..64 endpoint profiles")
    if not isinstance(zones, list) or not zones or len(zones) != len(zone_ids):
        raise ValueError(
            "Plan must assign every active room zone; reconcile the draft with room setup"
        )
    normalized_profiles, by_id = [], {}
    for profile in profiles:
        if not isinstance(profile, dict):
            raise ValueError("Invalid endpoint profile")
        pid = identifier(profile.get("id"), "profile ID")
        if pid in by_id:
            raise ValueError("Duplicate profile ID")
        name = profile.get("name", pid)
        if not isinstance(name, str) or not 1 <= len(name) <= 100:
            raise ValueError("Profile name must be 1..100 characters")
        veg, gen = profile.get("vegetative"), profile.get("generative")
        if not isinstance(veg, dict) or not isinstance(gen, dict):
            raise ValueError("Provide both grower-defined endpoint profiles")
        if (
            set(veg) != set(gen)
            or not set(REQUIRED_PARAMETERS) <= set(veg)
            or not set(veg) <= set(PARAMETERS)
        ):
            raise ValueError(
                "Endpoint keys must match and include all required steering parameters"
            )
        for endpoint in (veg, gen):
            for key, value in endpoint.items():
                finite(value, key)
            validate_relationships(endpoint)
        normalized = {
            "id": pid,
            "name": name,
            "vegetative": copy.deepcopy(veg),
            "generative": copy.deepcopy(gen),
        }
        normalized_profiles.append(normalized)
        by_id[pid] = normalized
    normalized_zones, seen = [], set()
    for assignment in zones:
        if not isinstance(assignment, dict):
            raise ValueError("Invalid zone assignment")
        zid = integer(assignment.get("zone_id"), 1, 64, "zone_id")
        if zid not in zone_ids or zid in seen:
            raise ValueError("Zone is duplicate, archived, or belongs to another room")
        seen.add(zid)
        try:
            start = date.fromisoformat(assignment.get("start_date", "")).isoformat()
        except (ValueError, TypeError):
            raise ValueError("start_date must be YYYY-MM-DD") from None
        schedule = assignment.get("schedule")
        if not isinstance(schedule, list) or not 1 <= len(schedule) <= 366:
            raise ValueError("Provide 1..366 daily or weekly assignments")
        normalized_schedule, end = [], 0
        for segment in schedule:
            if not isinstance(segment, dict):
                raise ValueError("Invalid schedule segment")
            if "start_week" in segment or "end_week" in segment:
                if "start_day" in segment or "end_day" in segment:
                    raise ValueError("Use either days or weeks, not both")
                first = (
                    integer(segment.get("start_week"), 1, 52, "start_week") - 1
                ) * 7 + 1
                last = integer(segment.get("end_week"), 1, 52, "end_week") * 7
            else:
                first = integer(segment.get("start_day"), 1, 366, "start_day")
                last = integer(segment.get("end_day"), 1, 366, "end_day")
            if first != end + 1 or last < first:
                raise ValueError(
                    "Schedule must start on day 1 without gaps or overlaps"
                )
            end = last
            pid = segment.get("profile_id")
            if pid not in by_id:
                raise ValueError("Unknown profile_id")
            bias = finite(segment.get("bias"), "bias")
            if not 0 <= bias <= 100:
                raise ValueError(
                    "Bias must be between 0 (Vegetative) and 100 (Generative)"
                )
            for endpoint in (by_id[pid]["vegetative"], by_id[pid]["generative"]):
                effective = {
                    key: bounds["value"]
                    for key, bounds in catalog.get(zid, {}).items()
                    if bounds.get("value") is not None
                }
                validate_relationships({**effective, **endpoint})
                for key, value in endpoint.items():
                    bounds = catalog.get(zid, {}).get(key)
                    if not bounds or not bounds["min"] <= value <= bounds["max"]:
                        raise ValueError(
                            f"Zone {zid} {key}: unavailable or outside readable HA bounds"
                        )
                    if key == "p1_maximum_shots" and value != int(value):
                        raise ValueError("Maximum shots must be an integer")
                    count = (value - bounds["min"]) / bounds["step"]
                    if abs(count - round(count)) > 1e-6:
                        raise ValueError(
                            f"Zone {zid} {key}: endpoint must align to HA step {bounds['step']}"
                        )
            validate_relationships(
                interpolate(
                    by_id[pid]["vegetative"],
                    by_id[pid]["generative"],
                    bias,
                    catalog.get(zid),
                )
            )
            normalized_schedule.append(
                {"start_day": first, "end_day": last, "profile_id": pid, "bias": bias}
            )
        normalized_zones.append(
            {"zone_id": zid, "start_date": start, "schedule": normalized_schedule}
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "profiles": normalized_profiles,
        "zones": normalized_zones,
    }


def preview_zone(plan, zone_id, grow_day, catalog=None):
    assignment = next(
        (item for item in plan["zones"] if item["zone_id"] == zone_id), None
    )
    if assignment is None:
        return {
            "zone_id": zone_id,
            "status": "waiting",
            "day": None,
            "parameters": {},
            "profile_id": None,
            "bias": None,
        }
    day = (
        date.fromisoformat(grow_day) - date.fromisoformat(assignment["start_date"])
    ).days + 1
    segment = next(
        (
            item
            for item in assignment["schedule"]
            if item["start_day"] <= day <= item["end_day"]
        ),
        None,
    )
    if segment is None:
        return {
            "zone_id": zone_id,
            "day": day,
            "status": "waiting" if day < 1 else "complete",
            "parameters": {},
            "profile_id": None,
            "bias": None,
        }
    profile = next(
        item for item in plan["profiles"] if item["id"] == segment["profile_id"]
    )
    return {
        "zone_id": zone_id,
        "day": day,
        "status": "active",
        "profile_id": profile["id"],
        "bias": segment["bias"],
        "parameters": interpolate(
            profile["vegetative"], profile["generative"], segment["bias"], catalog
        ),
    }


def hydraulic_preview(sizing, parameters):
    keys = (
        "substrate_l_per_plant",
        "plant_count",
        "drippers_per_plant",
        "dripper_flow_lph",
        "max_shot_duration",
    )
    values = {key: finite(sizing.get(key), key) for key in keys}
    if any(value <= 0 for value in values.values()):
        raise ValueError(
            "Pot, plant, emitter, flow and duration-cap values must be positive"
        )
    substrate = values["substrate_l_per_plant"] * values["plant_count"]
    flow = (
        values["plant_count"]
        * values["drippers_per_plant"]
        * values["dripper_flow_lph"]
        / 3600
    )
    shots = {}
    for key in ("p1_initial_shot_size", "p2_shot_size", "p3_emergency_shot_size"):
        if key not in parameters:
            continue
        volume = finite(parameters[key], key) / 100 * substrate
        duration = volume / flow
        shots[key] = {
            "volume_l": round(volume, 6),
            "duration_s": round(duration, 6),
            "capped_duration_s": max(
                5, min(int(values["max_shot_duration"]), int(duration))
            ),
        }
    return {
        **values,
        "zone_substrate_l": round(substrate, 6),
        "zone_flow_lps": round(flow, 9),
        "shots": shots,
    }
