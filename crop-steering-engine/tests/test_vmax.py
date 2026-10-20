"""detect_vmax — the P1 wet-up ceiling detector (advisory). Pure, offline."""

from crop_steering_engine import detect_vmax


def test_too_few_points_returns_none():
    assert detect_vmax([50, 60]) == (None, 0.0)
    assert detect_vmax([]) == (None, 0.0)


def test_still_ramping_no_plateau():
    # every shot still adds > plateau_delta -> not at ceiling yet
    v, c = detect_vmax([50, 55, 60, 65, 70])
    assert v is None and c == 0.0


def test_clear_plateau_locks_vmax_high_confidence():
    # big early uptake, then two marginal shots -> plateau at ~65
    v, c = detect_vmax([50, 58, 63, 65, 65.2, 65.3])
    assert v == 65.3
    assert c >= 0.7  # clear contrast + decent coverage


def test_plateau_value_is_the_ceiling_reached():
    v, c = detect_vmax([40, 52, 60, 64, 64.3, 64.4, 64.5])
    assert 64.0 <= v <= 65.0
    assert 0.0 < c <= 1.0


def test_flat_from_start_is_detected():
    v, c = detect_vmax([60, 60, 60, 60])
    assert v == 60.0
    assert c > 0.0


def test_confidence_in_unit_range():
    for series in (
        [50, 58, 63, 65, 65.1, 65.1],
        [30, 45, 55, 60, 60.2, 60.3, 60.3, 60.4],
    ):
        v, c = detect_vmax(series)
        assert v is not None
        assert 0.0 <= c <= 1.0


def test_none_values_tolerated():
    v, c = detect_vmax([50, None, 58, 63, 65, 65.2, 65.3])
    assert v is not None  # Nones filtered, plateau still found
