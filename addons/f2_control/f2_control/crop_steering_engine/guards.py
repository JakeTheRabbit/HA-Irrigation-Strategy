"""Pump-capacity and queue-order arithmetic. Pure, stdlib only."""

from itertools import combinations

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
    """Largest total over any max_concurrent zones, no two from the same exclusive group."""
    best = 0.0
    for size in range(1, min(max_concurrent, len(zones)) + 1):
        for combo in combinations(zones, size):
            named = [groups.get(z) for z in combo if groups.get(z) is not None]
            if len(named) == len(set(named)):
                best = max(best, sum(zones[z] for z in combo))
    return best


def order(intents: list[dict]) -> list[dict]:
    """Stable sort: priority first (rescue, steering, timer, manual), then first requested first."""
    return sorted(intents, key=lambda i: (PRIORITY[i["priority"]], i["requested_at"]))
