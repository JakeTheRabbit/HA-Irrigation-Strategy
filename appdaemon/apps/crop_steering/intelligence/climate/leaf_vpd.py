"""Leaf VPD — the supervisory climate variable.

Plants regulate stomata on the vapour-pressure-deficit *at the leaf
surface*, not in bulk air. Under good transpiration the leaf sits 1-3 °C
below air temp, so leaf VPD is meaningfully lower than air VPD. Best-
practice cultivation controllers chase leaf VPD; everything else (room
RH, room temp setpoints) is derived from it.

This module is pure math. No HA, no AppDaemon. Trivially testable.

The control flow is:
1. Recipe declares target leaf VPD per phase.
2. Sensors give us air temp, leaf temp, current air RH.
3. We solve for the air RH that — given current temperatures — produces
   the target leaf VPD.
4. The RH controller chases the *derived* RH target, not the recipe's
   raw `day_rh_pct` value.

Math:
    SVP(T) = 0.6108 * exp(17.27 * T / (T + 237.3))     [kPa]   (Tetens)
    AVP_air = SVP(T_air) * (RH / 100)
    leaf_VPD = SVP(T_leaf) - AVP_air
    target_RH = (SVP(T_leaf) - target_leaf_VPD) / SVP(T_air) * 100

Bounded: target RH is clipped to the [min_rh, max_rh] range the
operator considers physically sane (default 30-90 %). If the math
demands an out-of-band RH, the recipe target is unattainable given
current leaf temp — `solve_target_rh()` returns the clipped value
plus an `attainable=False` flag so the caller can flag it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


def saturated_vapor_pressure_kpa(temp_c: float) -> float:
    """Tetens equation. Returns kPa. Valid 0-50 °C."""
    return 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))


def actual_vapor_pressure_kpa(temp_c: float, rh_pct: float) -> float:
    """AVP of air at given temp + RH."""
    return saturated_vapor_pressure_kpa(temp_c) * (rh_pct / 100.0)


def leaf_vpd_kpa(leaf_temp_c: float, air_temp_c: float, air_rh_pct: float) -> float:
    """Compute leaf VPD from leaf temp + air temp + air RH.

    Returns kPa. Negative means leaf is *condensing* (leaf colder than
    dewpoint of room air) which is a problem — the caller should treat
    a negative result as an anomaly.
    """
    svp_leaf = saturated_vapor_pressure_kpa(leaf_temp_c)
    avp_air = actual_vapor_pressure_kpa(air_temp_c, air_rh_pct)
    return svp_leaf - avp_air


def air_vpd_kpa(air_temp_c: float, air_rh_pct: float) -> float:
    """Air VPD — useful for cross-check / dashboards. Plants don't
    actually experience this; leaf VPD is the biological reality."""
    svp = saturated_vapor_pressure_kpa(air_temp_c)
    return svp * (1.0 - air_rh_pct / 100.0)


@dataclass(frozen=True)
class RHSolution:
    target_rh_pct: float
    attainable: bool
    raw_target_rh_pct: float        # before clipping — useful for diagnostics
    leaf_temp_c: float
    air_temp_c: float
    target_leaf_vpd_kpa: float


def solve_target_rh(
    target_leaf_vpd_kpa_value: float,
    leaf_temp_c: float,
    air_temp_c: float,
    *,
    min_rh: float = 30.0,
    max_rh: float = 90.0,
) -> RHSolution:
    """Given target leaf VPD + current leaf+air temp, return the air RH
    that would produce that leaf VPD right now.

    `attainable` is False if the math demands RH outside [min_rh, max_rh],
    which means the operator's recipe is asking for a leaf VPD the room
    physically cannot deliver at current temperatures. The clipped value
    is still returned so the controller has *something* to chase, but the
    caller should flag this as an anomaly so the operator either adjusts
    the recipe target or addresses the temp gap.
    """
    svp_leaf = saturated_vapor_pressure_kpa(leaf_temp_c)
    svp_air = saturated_vapor_pressure_kpa(air_temp_c)
    if svp_air <= 0:
        return RHSolution(
            target_rh_pct=min_rh, attainable=False,
            raw_target_rh_pct=0.0,
            leaf_temp_c=leaf_temp_c, air_temp_c=air_temp_c,
            target_leaf_vpd_kpa=target_leaf_vpd_kpa_value,
        )

    target_avp_air = svp_leaf - target_leaf_vpd_kpa_value
    raw_rh = (target_avp_air / svp_air) * 100.0
    clipped = max(min_rh, min(max_rh, raw_rh))
    return RHSolution(
        target_rh_pct=clipped,
        attainable=(min_rh <= raw_rh <= max_rh),
        raw_target_rh_pct=raw_rh,
        leaf_temp_c=leaf_temp_c,
        air_temp_c=air_temp_c,
        target_leaf_vpd_kpa=target_leaf_vpd_kpa_value,
    )
