"""Combining a zone's probes into the one reading the controller steers by (calculations.fuse_probes).

The controller never sees a zone's probes, only this reading. It measures dryback from the zone's
peak and compares the reading with its thresholds, so a reading that jumps because a probe dropped
out is taken as the crop drying back or wetting up. Before this, a zone's probes were averaged:
one probe going offline moved the zone to whatever the others read, in a single step.
"""

from custom_components.crop_steering.calculations import fuse_probes
from custom_components.crop_steering.const import (
    PROBE_FAR,
    PROBE_METHODS,
    PROBE_RANGE,
    PROBE_STALE_SECONDS,
)

LO, HI = PROBE_RANGE["vwc"]
FRESH = 60.0
STALE = PROBE_STALE_SECONDS + 60.0


def fuse(readings, offsets):
    return fuse_probes(readings, offsets, LO, HI, PROBE_STALE_SECONDS)


def test_one_probe_reads_exactly_what_it_reads():
    value, detail = fuse([("sensor.a", 41.37, FRESH)], {})
    assert value == 41.37
    assert detail == {
        "probes": 1,
        "used": ["sensor.a"],
        "excluded": {},
        "spread": 0.0,
        "method": "Median",
        "steered_by": "Median",
        "quality": {"sensor.a": {"quality": "good", "reason": "fresh"}},
    }


def test_one_probe_that_has_stopped_reporting_is_still_the_zone_reading():
    # Setting a quiet probe aside only ever happens in favour of another probe. The controller's
    # own age check decides what a zone with nothing fresher is worth, exactly as before.
    assert fuse([("sensor.a", 41.0, STALE)], {})[0] == 41.0


def test_a_reading_the_controller_would_refuse_is_not_used():
    value, detail = fuse([("sensor.a", 140.0, FRESH)], {})
    assert value is None
    assert detail["excluded"] == {"sensor.a": "out of range"}


def test_two_probes_read_their_mean():
    assert fuse([("sensor.a", 40.0, FRESH), ("sensor.b", 46.0, FRESH)], {})[0] == 43.0


def test_one_wild_probe_among_three_moves_nothing():
    readings = [
        ("sensor.a", 40.0, FRESH),
        ("sensor.b", 42.0, FRESH),
        ("sensor.c", 90.0, FRESH),
    ]
    value, detail = fuse(readings, {})
    assert (
        value == 42.0
    )  # the mean would say 57.33: a zone far wetter than any real probe
    assert detail["spread"] == 50.0


def test_losing_a_probe_does_not_step_the_zone_reading():
    offsets = {}
    assert (
        fuse([("sensor.a", 40.0, FRESH), ("sensor.b", 46.0, FRESH)], offsets)[0] == 43.0
    )

    # B goes offline. Averaging made this 40.0: a 3-point drop the controller reads as dryback.
    value, detail = fuse([("sensor.a", 40.0, FRESH), ("sensor.b", None, None)], offsets)
    assert value == 43.0
    assert detail["used"] == ["sensor.a"]
    assert detail["excluded"] == {"sensor.b": "no reading"}

    # The zone keeps following the probe that is left.
    assert (
        fuse([("sensor.a", 38.0, FRESH), ("sensor.b", None, None)], offsets)[0] == 41.0
    )

    # B comes back having dried the same way: no step on the way back either.
    assert (
        fuse([("sensor.a", 38.0, FRESH), ("sensor.b", 44.0, FRESH)], offsets)[0] == 41.0
    )


def test_a_probe_that_has_stopped_reporting_is_set_aside_while_another_still_reports():
    offsets = {}
    fuse([("sensor.a", 40.0, FRESH), ("sensor.b", 46.0, FRESH)], offsets)
    value, detail = fuse(
        [("sensor.a", 39.0, FRESH), ("sensor.b", 46.0, STALE)], offsets
    )
    assert value == 42.0  # follows A down; B's frozen 46 no longer holds the zone up
    assert detail["excluded"] == {"sensor.b": "not reporting"}


def test_a_probe_missing_before_the_probes_were_ever_compared_leaves_the_others_as_they_read():
    assert fuse([("sensor.a", 40.0, FRESH), ("sensor.b", None, None)], {})[0] == 40.0


def test_a_probe_mapped_twice_counts_once():
    offsets = {}
    readings = [
        ("sensor.a", 40.0, FRESH),
        ("sensor.a", 40.0, FRESH),
        ("sensor.b", 46.0, FRESH),
    ]
    value, detail = fuse(readings, offsets)
    assert value == 43.0 and detail["probes"] == 2
    # ...so the zone is still "every probe usable" and the offsets keep being refreshed.
    assert offsets == {"sensor.a": -3.0, "sensor.b": 3.0}


def test_no_usable_probe_is_no_reading():
    value, detail = fuse(
        [("sensor.a", None, None), ("sensor.b", float("nan"), FRESH)], {}
    )
    assert value is None
    assert detail["spread"] is None
    assert detail["excluded"] == {"sensor.a": "no reading", "sensor.b": "no reading"}
    assert fuse([], {}) == (
        None,
        {
            "probes": 0,
            "used": [],
            "excluded": {},
            "spread": None,
            "method": "Median",
            "steered_by": "Median",
            "quality": {},
        },
    )


def test_pore_ec_uses_its_own_range():
    lo, hi = PROBE_RANGE["ec"]
    value, detail = fuse_probes(
        [("sensor.a", 3.1, FRESH), ("sensor.b", 3100.0, FRESH)],
        {},
        lo,
        hi,
        PROBE_STALE_SECONDS,
    )
    assert value == 3.1  # an unconverted uS/cm figure is not a pore EC
    assert detail["excluded"] == {"sensor.b": "out of range"}


def guarded(readings, offsets, method="Median", kind="vwc"):
    """As the zone sensors call it: the zone's chosen method and the far-from-the-others filter."""
    lo, hi = PROBE_RANGE[kind]
    return fuse_probes(
        readings, offsets, lo, hi, PROBE_STALE_SECONDS, method, PROBE_FAR[kind]
    )


THREE = [
    ("sensor.a", 48.0, FRESH),
    ("sensor.b", 50.0, FRESH),
    ("sensor.c", 52.0, FRESH),
]


def test_median_is_the_first_choice_and_each_method_reads_as_it_says():
    assert PROBE_METHODS[0] == "Median"
    readings = THREE + [("sensor.d", 58.0, FRESH)]
    got = {method: guarded(readings, {}, method)[0] for method in PROBE_METHODS}
    assert got == {"Median": 51.0, "Average": 52.0, "Lowest": 48.0, "Highest": 58.0}
    # A method this does not know steers as the default does.
    assert guarded(readings, {}, "Mode")[1]["steered_by"] == "Median"


def test_a_probe_pulled_out_of_its_cube_does_not_drive_lowest():
    readings = [
        ("sensor.a", 50.0, FRESH),
        ("sensor.b", 52.0, FRESH),
        ("sensor.c", 3.0, FRESH),
    ]
    value, detail = guarded(readings, {}, "Lowest")
    assert (
        value == 51.0
    )  # Lowest of every probe would have said 3: water until the daily cap
    assert detail["excluded"] == {"sensor.c": "far from the others"}
    assert detail["used"] == ["sensor.a", "sensor.b"] and detail["spread"] == 2.0
    # Two probes left are too few to let one steer: the zone steers on their median.
    assert (detail["method"], detail["steered_by"]) == ("Lowest", "Median")


def test_a_probe_in_a_puddle_does_not_starve_the_zone_under_highest():
    readings = [
        ("sensor.a", 40.0, FRESH),
        ("sensor.b", 42.0, FRESH),
        ("sensor.c", 95.0, FRESH),
    ]
    value, detail = guarded(readings, {}, "Highest")
    assert value == 41.0 and detail["steered_by"] == "Median"


def test_lowest_and_highest_need_three_probes_that_agree():
    two = [("sensor.a", 40.0, FRESH), ("sensor.b", 46.0, FRESH)]
    for method in ("Lowest", "Highest"):
        value, detail = guarded(two, {}, method)
        assert value == 43.0 and detail["steered_by"] == "Median"
        value, detail = guarded(THREE, {}, method)
        assert detail["steered_by"] == method
    for method in ("Median", "Average"):
        assert guarded(two, {}, method)[1]["steered_by"] == method


def test_probes_that_simply_read_apart_are_all_used():
    readings = [
        ("sensor.a", 38.0, FRESH),
        ("sensor.b", 50.0, FRESH),
        ("sensor.c", 62.0, FRESH),
    ]
    value, detail = guarded(readings, {}, "Lowest")
    assert value == 38.0 and detail["excluded"] == {}


def test_pore_ec_far_from_the_others_is_left_out_by_its_own_measure():
    readings = [
        ("sensor.a", 3.0, FRESH),
        ("sensor.b", 3.2, FRESH),
        ("sensor.c", 0.1, FRESH),
    ]
    value, detail = guarded(readings, {}, "Lowest", kind="ec")
    assert value == 3.1 and detail["excluded"] == {"sensor.c": "far from the others"}
    # 8.0 beside 9.6 is a spread, not a fault: within 40 % of the median.
    spread = [
        ("sensor.a", 8.0, FRESH),
        ("sensor.b", 8.4, FRESH),
        ("sensor.c", 9.6, FRESH),
    ]
    assert guarded(spread, {}, "Highest", kind="ec")[0] == 9.6


def test_the_filter_never_leaves_a_zone_with_nothing():
    readings = [
        ("sensor.a", 5.0, FRESH),
        ("sensor.b", 10.0, FRESH),
        ("sensor.c", 90.0, FRESH),
        ("sensor.d", 95.0, FRESH),
    ]
    value, detail = guarded(readings, {})
    assert value == 50.0 and detail["excluded"] == {}


def test_offsets_are_learned_against_the_reading_the_zone_steered_by():
    offsets = {}
    assert guarded(THREE, offsets, "Lowest")[0] == 48.0
    assert offsets == {"sensor.a": 0.0, "sensor.b": 2.0, "sensor.c": 4.0}
    # C is pulled out: the zone carries on from the lowest reading instead of stepping to 3 or 51.
    pulled = THREE[:2] + [("sensor.c", 3.0, FRESH)]
    value, detail = guarded(pulled, offsets, "Lowest")
    assert value == 48.0 and detail["steered_by"] == "Median"
    # ...and keeps following the probes that are left.
    assert (
        guarded(
            [
                ("sensor.a", 46.0, FRESH),
                ("sensor.b", 48.0, FRESH),
                ("sensor.c", 3.0, FRESH),
            ],
            offsets,
            "Lowest",
        )[0]
        == 46.0
    )


def test_offsets_are_forgotten_when_the_zones_probes_change():
    offsets = {}
    guarded(THREE, offsets)
    # Probe C is unmapped and D mapped in its place, D not yet reporting: B's old offset would
    # shift the zone by what it once read against a probe that is gone.
    value, _detail = guarded([THREE[0], THREE[1], ("sensor.d", None, None)], offsets)
    assert value == 49.0 and offsets == {}


def test_each_probe_says_the_quality_of_its_reading_and_why():
    """Beside the freshness and range checks, each probe's quality and the reason for it."""
    reasons = {
        "fresh": [("sensor.a", 40.0, FRESH)],
        "stale": [("sensor.a", 40.0, FRESH), ("sensor.b", 42.0, STALE)],
        "out_of_range": [("sensor.a", 40.0, FRESH), ("sensor.b", 140.0, FRESH)],
        "excluded_outlier": [
            ("sensor.a", 40.0, FRESH),
            ("sensor.c", 42.0, FRESH),
            ("sensor.b", 90.0, FRESH),
        ],
    }
    for reason, readings in reasons.items():
        _value, detail = fuse_probes(
            readings, {}, LO, HI, PROBE_STALE_SECONDS, far=PROBE_FAR["vwc"]
        )
        probe = readings[-1][0]
        assert detail["quality"][probe] == {
            "quality": "good" if reason == "fresh" else "bad",
            "reason": reason,
        }, reason
        assert detail["quality"]["sensor.a"] == {"quality": "good", "reason": "fresh"}


def test_a_probe_with_no_reading_is_stale_and_a_stale_one_steering_is_suspect():
    detail = fuse([("sensor.a", None, None), ("sensor.b", 41.0, STALE)], {})[1]
    assert detail["quality"] == {
        "sensor.a": {"quality": "bad", "reason": "stale"},
        "sensor.b": {"quality": "suspect", "reason": "stale"},
    }
