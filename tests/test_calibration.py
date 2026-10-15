"""The two-point arithmetic behind a feed-probe calibration check (custom_components/.../
calibration.py), and the frontend's copy of it agreeing (frontend/src/lib/calibration.test.ts uses
the same cases)."""

import pytest

from . import ha_stubs

ha_stubs.install()

from custom_components.crop_steering.calibration import evaluate  # noqa: E402


def _pts(*pairs):
    return [{"reference": r, "reading": m} for r, m in pairs]


@pytest.mark.parametrize(
    "kind,pairs,slope,offset,verdict",
    [
        ("ph", ((7.0, 7.0), (4.0, 4.0)), 100.0, 0.0, "pass"),
        ("ph", ((7.0, 7.05), (4.0, 4.1)), 98.3, 0.05, "pass"),
        ("ph", ((4.0, 4.2), (7.0, 7.2)), 100.0, 0.2, "drifting"),
        ("ph", ((7.0, 7.0), (4.0, 4.5)), 83.3, 0.0, "fail"),
        ("ec", ((1.413, 1.5), (12.88, 12.0)), 91.6, 0.206, "drifting"),
        ("ec", ((0.0, 0.0), (2.77, 2.8)), 101.1, 0.0, "pass"),
    ],
)
def test_slope_offset_and_verdict(kind, pairs, slope, offset, verdict):
    result = evaluate(kind, _pts(*pairs))
    assert (result["slope_pct"], result["offset"], result["verdict"]) == (
        slope,
        offset,
        verdict,
    )


@pytest.mark.parametrize(
    "kind,points,message",
    [
        ("ph", _pts((7.0, 7.0)), "exactly two points"),
        ("ph", _pts((7.0, 7.0), (6.5, 6.5)), "at least 1 apart"),
        ("ph", _pts((7.0, 7.0), (15.0, 15.0)), "from 0 to 14"),
        ("ec", _pts((1.0, True), (3.0, 3.0)), "Reading must be a number"),
        ("ec", [{"reference": 1.0}, {"reference": 3.0, "reading": 3.0}], "Reading"),
    ],
)
def test_bad_points_are_refused(kind, points, message):
    with pytest.raises(ValueError, match=message):
        evaluate(kind, points)
