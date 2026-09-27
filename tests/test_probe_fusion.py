"""Combining a zone's probes into the one reading the controller steers by (calculations.fuse_probes).

The controller never sees a zone's probes, only this reading. It measures dryback from the zone's
peak and compares the reading with its thresholds, so a reading that jumps because a probe dropped
out is taken as the crop drying back or wetting up. Before this, a zone's probes were averaged:
one probe going offline moved the zone to whatever the others read, in a single step.
"""

from custom_components.crop_steering.calculations import fuse_probes
from custom_components.crop_steering.const import PROBE_RANGE, PROBE_STALE_SECONDS

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
        {"probes": 0, "used": [], "excluded": {}, "spread": None},
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
