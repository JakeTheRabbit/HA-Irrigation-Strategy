from crop_steering_engine.guards import PRIORITY, capacity_ok, order, worst_case_lph, zone_demand_lph


def test_zone_demand_is_plants_times_drippers_times_rate():
    assert zone_demand_lph(10, 2, 1.6) == 32.0


def test_two_zones_at_60_pct_cannot_share_the_pump():
    assert capacity_ok([], 600, 1000, 2) and not capacity_ok([600], 600, 1000, 2)


def test_no_flow_limit_still_counts_zones_at_once():
    assert capacity_ok([5000], 5000, None, 1) is False and capacity_ok([], 5000, None, 1)


def test_exactly_at_the_limit_fits():
    assert capacity_ok([400], 600, 1000, 2)


def test_worst_case_respects_groups():
    assert worst_case_lph({1: 500, 2: 500, 3: 300}, {1: "a", 2: "a", 3: None}, 2) == 800


def test_worst_case_ungrouped_takes_the_largest():
    assert worst_case_lph({1: 500, 2: 400, 3: 300}, {}, 2) == 900


def test_worst_case_with_no_zones_is_zero():
    assert worst_case_lph({}, {}, 2) == 0.0


def test_rescue_jumps_the_queue_fifo_within_priority():
    intents = [
        {"id": "a", "priority": "timer", "requested_at": 1},
        {"id": "b", "priority": "manual", "requested_at": 0},
        {"id": "c", "priority": "rescue", "requested_at": 5},
        {"id": "d", "priority": "timer", "requested_at": 0},
        {"id": "e", "priority": "steering", "requested_at": 9},
    ]
    assert [i["id"] for i in order(intents)] == ["c", "e", "d", "a", "b"]
    assert [i["id"] for i in intents][0] == "a"  # input untouched
    assert PRIORITY == {"rescue": 0, "steering": 1, "timer": 2, "manual": 3}


def _brute_force(zones, groups, max_concurrent):
    """The definition, by trying every set of zones: the oracle for worst_case_lph."""
    from itertools import combinations

    best = 0.0
    for size in range(1, min(max_concurrent, len(zones)) + 1):
        for combo in combinations(zones, size):
            named = [groups.get(z) for z in combo if groups.get(z) is not None]
            if len(named) == len(set(named)):
                best = max(best, sum(zones[z] for z in combo))
    return best


def test_worst_case_equals_the_brute_force_definition():
    import random

    rnd = random.Random(7)
    for _ in range(200):
        n = rnd.randint(1, 9)
        zones = {i: rnd.choice([50.0, 120.0, 240.0, 333.0]) for i in range(n)}
        groups = {i: rnd.choice([None, None, "a", "b"]) for i in range(n)}
        count = rnd.randint(0, n + 2)
        assert worst_case_lph(zones, groups, count) == _brute_force(zones, groups, count)
    zones = {i: float(10 + i) for i in range(16)}
    groups = {i: (None if i % 2 else "a") for i in range(16)}
    assert worst_case_lph(zones, groups, 5) == _brute_force(zones, groups, 5)


def test_worst_case_of_a_big_pump_is_instant():
    import time

    zones = {i: 100.0 + i for i in range(40)}
    started = time.monotonic()
    assert worst_case_lph(zones, {i: "g" for i in range(10)}, 40) == 100.0 + 9 + sum(zones[i] for i in range(10, 40))
    assert time.monotonic() - started < 0.1
