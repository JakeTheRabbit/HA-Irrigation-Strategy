"""Pure helpers that work a setup answer out instead of asking for it. No HA imports.

Nothing here touches hardware or writes a setting: each returns a number (or a reason it
cannot) for the operator to accept.
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# Substrate presets: "what are your plants in?" instead of "how many litres?"
# ---------------------------------------------------------------------------
# PER-PLANT volume in litres. Rockwool volumes are the block's outside dimensions; pot sizes
# are the nominal volume on the label. A nursery "trade gallon" pot holds nearer 3 L than
# 3.8 L, so the wizard tells people who are unsure to fill one from a measuring jug.
SUBSTRATE_CUSTOM = "custom"
SUBSTRATE_PRESETS: dict[str, float | None] = {
    SUBSTRATE_CUSTOM: None,
    "cube_4in": 0.65,  # 100 x 100 x 65 mm
    "block_6in": 3.4,  # 150 x 150 x 150 mm
    "pot_1gal": 3.8,
    "pot_2gal": 7.6,
    "pot_3gal": 11.4,
    "pot_5gal": 18.9,
    "pot_7gal": 26.5,
    "pot_10gal": 37.9,
}


def substrate_litres(preset: str | None, typed_litres: float) -> float:
    """A chosen preset wins over the typed number; "custom" (or anything unknown) uses it."""
    known = SUBSTRATE_PRESETS.get(preset or SUBSTRATE_CUSTOM)
    return float(typed_litres) if known is None else known


# ---------------------------------------------------------------------------
# Catch test: measure what a dripper really delivers instead of trusting the packet
# ---------------------------------------------------------------------------
# Same bounds the dripper_flow_rate setting accepts (setup_api.SIZING).
FLOW_MIN_LPH, FLOW_MAX_LPH = 0.1, 50.0

CATCH_PROBLEM_INPUT = "catch_test_invalid"
CATCH_PROBLEM_RANGE = "catch_test_out_of_range"


def catch_test_lph(
    millilitres: float, seconds: float, drippers: float = 1
) -> tuple[float | None, str | None]:
    """(L/hr PER DRIPPER, None) or (None, problem key).

    Run the irrigation for `seconds` with `drippers` emitters draining into one jug, then
    enter the `millilitres` collected. Catching several drippers at once averages out the
    spread between emitters, which is usually larger than the error in reading the jug.
    """
    try:
        ml, secs, count = float(millilitres), float(seconds), float(drippers)
    except (TypeError, ValueError):
        return None, CATCH_PROBLEM_INPUT
    if not all(math.isfinite(v) and v > 0 for v in (ml, secs, count)):
        return None, CATCH_PROBLEM_INPUT
    lph = ml / 1000.0 / count / secs * 3600.0
    if not FLOW_MIN_LPH <= lph <= FLOW_MAX_LPH:
        return None, CATCH_PROBLEM_RANGE
    return round(lph, 2), None


# ---------------------------------------------------------------------------
# Suggested field capacity: read it off the plant instead of guessing 70 %
# ---------------------------------------------------------------------------
# Field capacity is where THIS substrate, read by THIS probe, stops gaining water. The
# controller learns exactly that: the VWC a zone's morning ramp plateaus at ("learned_peak" on
# sensor.crop_steering_<room>zone_N_auto_setpoints), whether or not Auto Setpoints is on.
# The margin and floor MUST match what Auto Setpoints itself would set
# (addons/f2_control/f2_control/setpoint_supervisor.py); tests/test_setup_helpers.py pins them
# together so a suggestion never disagrees with the managed value.
FIELD_CAPACITY_MARGIN_PTS = 2.0
FIELD_CAPACITY_FLOOR = 40.0
FIELD_CAPACITY_CEILING = 100.0


def suggested_field_capacity(learned_peak) -> float | None:
    """The field capacity the zone's own plateau implies, or None until one has been seen."""
    try:
        peak = float(learned_peak)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(peak) or not 0 < peak <= FIELD_CAPACITY_CEILING:
        return None
    return min(
        FIELD_CAPACITY_CEILING,
        max(FIELD_CAPACITY_FLOOR, round(peak + FIELD_CAPACITY_MARGIN_PTS, 1)),
    )
