"""Unit tests for leaf VPD math.

Reference values cross-checked against published Tetens-equation tables
and the standard cannabis VPD chart at typical leaf-air ΔT of 1-3 °C.
"""
from __future__ import annotations

import pytest

from . import _appdaemon_stub  # noqa: F401

from crop_steering.intelligence.climate.leaf_vpd import (  # noqa: E402
    actual_vapor_pressure_kpa,
    air_vpd_kpa,
    leaf_vpd_kpa,
    saturated_vapor_pressure_kpa,
    solve_target_rh,
)


# ─── SVP / AVP basics ──────────────────────────────────────────────────

@pytest.mark.parametrize("temp_c, expected_kpa", [
    (0,   0.611),
    (10,  1.228),
    (20,  2.339),
    (25,  3.169),
    (30,  4.243),
    (35,  5.624),
])
def test_svp_matches_tetens_table(temp_c, expected_kpa):
    """Tetens equation, classic published values."""
    got = saturated_vapor_pressure_kpa(temp_c)
    assert got == pytest.approx(expected_kpa, abs=0.05), (
        f"SVP({temp_c}°C) = {got:.3f}; expected ≈ {expected_kpa}"
    )


def test_avp_at_50_percent_rh_is_half_svp():
    svp = saturated_vapor_pressure_kpa(25)
    avp = actual_vapor_pressure_kpa(25, 50)
    assert avp == pytest.approx(svp / 2, abs=0.001)


# ─── Air VPD vs leaf VPD ───────────────────────────────────────────────

def test_air_vpd_at_25c_50rh():
    """At 25 °C, 50 % RH, air VPD ≈ 1.58 kPa (canonical chart point)."""
    assert air_vpd_kpa(25, 50) == pytest.approx(1.58, abs=0.05)


def test_leaf_vpd_lower_than_air_vpd_under_transpiration():
    """When leaf is cooler than air (good transpiration), leaf VPD < air VPD.

    Air 25 °C, 60 % RH → air VPD ≈ 1.27 kPa
    Leaf 23 °C (2 °C below air) → leaf VPD ≈ 0.90 kPa
    Plants experience the lower number — that's the cultivation-relevant value.
    """
    air_vpd = air_vpd_kpa(25, 60)
    leaf = leaf_vpd_kpa(leaf_temp_c=23, air_temp_c=25, air_rh_pct=60)
    assert leaf < air_vpd
    assert air_vpd == pytest.approx(1.27, abs=0.05)
    assert leaf == pytest.approx(0.90, abs=0.05)


def test_leaf_vpd_negative_when_leaf_below_dewpoint():
    """If leaf temp is below the room's dewpoint, leaf VPD is negative —
    that's condensation on the leaf (a real problem). Caller treats this
    as an anomaly, not just a number."""
    # Room: 25 °C, 90 % RH → dewpoint ≈ 23.2 °C
    leaf = leaf_vpd_kpa(leaf_temp_c=20, air_temp_c=25, air_rh_pct=90)
    assert leaf < 0


def test_leaf_vpd_zero_at_saturation_with_matched_temps():
    """Leaf and air at same temp, 100 % RH → VPD = 0 (saturated)."""
    assert leaf_vpd_kpa(25, 25, 100) == pytest.approx(0.0, abs=0.001)


# ─── solve_target_rh — the supervisory inversion ──────────────────────

def test_solve_target_rh_round_trip():
    """If we solve for RH at target_vpd, then plug that RH into
    leaf_vpd_kpa(), we should get target_vpd back. Round-trip property."""
    target_vpd = 1.10
    leaf, air = 23.0, 25.5
    result = solve_target_rh(target_vpd, leaf, air)
    assert result.attainable
    back = leaf_vpd_kpa(leaf_temp_c=leaf, air_temp_c=air, air_rh_pct=result.target_rh_pct)
    assert back == pytest.approx(target_vpd, abs=0.01)


def test_solve_target_rh_realistic_late_flower():
    """Late flower target: leaf VPD 1.30 kPa, leaf 21 °C, air 24 °C.
    Required RH lands in the high-30s to low-40s — consistent with the
    Athena late-flower envelope (45-50 % once you account for normal
    leaf-air ΔT being ~2-3 °C)."""
    result = solve_target_rh(1.30, leaf_temp_c=21.0, air_temp_c=24.0)
    assert result.attainable
    assert 35 <= result.target_rh_pct <= 50


def test_solve_target_rh_unattainable_low():
    """Demanding very high VPD with cold leaf → RH would need to go below 30 %.
    Returns clipped + attainable=False."""
    # leaf 20, air 22, target VPD 2.0 — physically requires very dry air
    result = solve_target_rh(2.0, leaf_temp_c=20.0, air_temp_c=22.0)
    assert not result.attainable
    assert result.target_rh_pct == 30.0  # clipped to floor


def test_solve_target_rh_unattainable_high():
    """Demanding very low VPD with warm leaf → RH would need to go above 90 %."""
    # leaf 30, air 25, target VPD 0.2 — physically requires very humid air
    result = solve_target_rh(0.2, leaf_temp_c=30.0, air_temp_c=25.0)
    assert not result.attainable
    # Math may push RH > 100; clipped to 90.
    assert result.target_rh_pct == 90.0


def test_solve_target_rh_diagnostic_fields_populated():
    result = solve_target_rh(1.0, leaf_temp_c=22.0, air_temp_c=24.5)
    assert result.leaf_temp_c == 22.0
    assert result.air_temp_c == 24.5
    assert result.target_leaf_vpd_kpa == 1.0
    # raw is the un-clipped math; should agree with target_rh_pct when attainable
    if result.attainable:
        assert result.target_rh_pct == pytest.approx(result.raw_target_rh_pct, abs=0.001)


# ─── Industry chart sanity checks ─────────────────────────────────────

@pytest.mark.parametrize("phase, leaf_c, air_c, target_vpd, rh_lo, rh_hi", [
    # (phase name, leaf temp, air temp, target leaf VPD, RH band lo, RH band hi)
    ("transplant",   24.0, 26.0, 0.7,  65, 78),
    ("veg",          24.5, 27.0, 0.95, 55, 67),
    ("early flower", 24.0, 26.5, 1.10, 50, 61),
    ("mid flower",   23.0, 26.0, 1.20, 45, 56),
    ("late flower",  22.0, 25.0, 1.30, 40, 51),
    ("ripening",     21.0, 23.0, 1.40, 35, 48),
])
def test_solve_target_rh_matches_phase_envelopes(phase, leaf_c, air_c,
                                                  target_vpd, rh_lo, rh_hi):
    """Each cannabis phase's typical leaf VPD should solve to an RH that
    falls within the published cultivation chart band for that phase."""
    result = solve_target_rh(target_vpd, leaf_temp_c=leaf_c, air_temp_c=air_c)
    assert result.attainable, f"{phase}: not attainable at given temps"
    assert rh_lo <= result.target_rh_pct <= rh_hi, (
        f"{phase}: solved RH = {result.target_rh_pct:.1f}, "
        f"expected band [{rh_lo}, {rh_hi}]"
    )
