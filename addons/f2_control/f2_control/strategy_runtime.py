"""Validate integration strategy snapshots before the legacy parameter read path."""

import math
from datetime import datetime

MODE_KEYS = {
    "vegetative_dryback_target": "dryback_target",
    "generative_dryback_target": "dryback_target",
    **{
        f"ec_target_{mode}_p{phase}": f"ec_target_p{phase}"
        for mode in ("veg", "gen")
        for phase in range(3)
    },
}
ALLOWED = {
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
    "p1_shot_size_increment",
    "p1_maximum_shots",
    "p1_time_between_shots",
    "p0_maximum_wait_time",
    "max_daily_volume",
    "field_capacity",
    "maximum_ec",
    "watchdog_hours",
}
REQUIRED = {
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
}


def parse_snapshot(state, attributes, prefix, now, was_required=False):
    """Missing new capability preserves legacy behaviour unless previously activated."""
    attrs = attributes if isinstance(attributes, dict) else {}
    required = was_required or attrs.get("enabled") is True
    result = {"required": required, "error": None, "zones": {}, "managed": set()}
    if not required:
        return result
    try:
        if (
            attrs.get("snapshot_version") != 1
            or attrs.get("room_id") != f"room:{prefix}"
        ):
            raise ValueError(
                "Strategy snapshot missing, unsupported or belongs to another room"
            )
        updated = datetime.fromisoformat(attrs["updated_at"]).timestamp()
        expires = datetime.fromisoformat(attrs["valid_until"]).timestamp()
        if not (now - 180 <= updated <= now + 60 and now < expires <= now + 600):
            raise ValueError("Strategy snapshot is stale")
        if state == "draft" and attrs.get("release_legacy") is True:
            result["required"] = False
            return result
        if state not in ("active", "disarming") or attrs.get("enabled") is not True:
            raise ValueError(
                attrs.get("error") or "Strategy is held; no current active snapshot"
            )
        managed = attrs.get("managed_zone_ids")
        if (
            not isinstance(managed, list)
            or not managed
            or any(type(z) is not int or not 1 <= z <= 64 for z in managed)
        ):
            raise ValueError("Invalid managed zone IDs")
        result["managed"] = set(managed)
        for zone in attrs.get("zones", []):
            zid = zone.get("zone_id")
            if (
                type(zid) is not int
                or zid not in result["managed"]
                or zid in result["zones"]
            ):
                raise ValueError("Invalid or duplicate strategy zone")
            parameters = zone.get("parameters")
            if zone.get("status") == "active":
                if (
                    not isinstance(parameters, dict)
                    or not REQUIRED <= parameters.keys()
                    or not parameters.keys() <= ALLOWED
                ):
                    raise ValueError("Incomplete or unsupported strategy parameter set")
                if any(
                    isinstance(v, bool)
                    or not isinstance(v, (int, float))
                    or not math.isfinite(v)
                    or v < 0
                    for v in parameters.values()
                ):
                    raise ValueError("Invalid strategy number")
                if (
                    not parameters["p3_emergency_vwc_threshold"] + 3
                    <= parameters["p2_vwc_threshold"]
                    < parameters["p1_target_vwc"]
                    <= 100
                ):
                    raise ValueError("Invalid strategy VWC bands")
            result["zones"][zid] = {
                "parameters": parameters or {},
                "status": zone.get("status"),
            }
        if result["zones"].keys() != result["managed"]:
            raise ValueError("Strategy snapshot is missing assigned zones")
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        result["error"] = str(error)
        result["zones"] = {}
    return result


def parameter_override(snapshot, zone, suffix):
    """Both native mode families read the same continuous canonical setpoint."""
    if not snapshot or snapshot.get("error"):
        return None
    record = snapshot.get("zones", {}).get(zone)
    if not record or record.get("status") != "active":
        return None
    return record["parameters"].get(MODE_KEYS.get(suffix, suffix))


def strategy_block(snapshot, zone):
    if not snapshot or not snapshot.get("required"):
        return None
    if snapshot.get("error"):
        return f"Strategy hold: {snapshot['error']}"
    if zone in snapshot.get("managed", set()):
        status = snapshot.get("zones", {}).get(zone, {}).get("status")
        if status != "active":
            return f"Strategy zone {status or 'unavailable'}"
    return None
