"""Pump-capacity and queue-order arithmetic. Pure, stdlib only."""

PRIORITY = {"rescue": 0, "steering": 1, "timer": 2, "manual": 3}


def zone_demand_lph(
    plant_count: int, drippers_per_plant: int, dripper_flow_rate: float
) -> float:
    """Litres per hour a zone draws while its valve is open."""
    return plant_count * drippers_per_plant * dripper_flow_rate


def capacity_ok(
    running_lph: list[float],
    this_lph: float,
    max_flow_lph: float | None,
    max_concurrent: int,
) -> bool:
    """True when one more zone fits: within the zone count and, if a flow limit is set, within it."""
    if len(running_lph) + 1 > max_concurrent:
        return False
    return max_flow_lph is None or sum(running_lph) + this_lph <= max_flow_lph


def worst_case_lph(
    zones: dict[int, float], groups: dict[int, str | None], max_concurrent: int
) -> float:
    """Largest total over any max_concurrent zones, no two from the same exclusive group.

    At most one zone per group can run, so only each group's largest zone competes with the zones
    in no group; the answer is the sum of the max_concurrent largest of those.
    """
    candidates, largest = [], {}
    for zone, lph in zones.items():
        group = groups.get(zone)
        if group is None:
            candidates.append(lph)
        elif group not in largest or lph > largest[group]:
            largest[group] = lph
    candidates.extend(largest.values())
    candidates.sort(reverse=True)
    return float(sum(candidates[: max(max_concurrent, 0)]))


def order(intents: list[dict]) -> list[dict]:
    """Stable sort: priority first (rescue, steering, timer, manual), then first requested first."""
    return sorted(intents, key=lambda i: (PRIORITY[i["priority"]], i["requested_at"]))
