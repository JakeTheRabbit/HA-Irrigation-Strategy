"""Pure unit handling for setup. No Home Assistant imports.

The engine works in ONE set of units - EC in mS/cm, volume in litres, dripper flow in L/hr.
Growers do not: substrate probes report uS/cm, handheld meters read ppm on a 500 or a 700
scale (or CF), pots are sold in US gallons and drippers are rated in GPH. Everything here
converts what a person HAS into what the engine needs, at the edge, so nothing downstream
changes and nobody is asked to do arithmetic or write a template sensor.
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# EC
# ---------------------------------------------------------------------------
# reading x factor = mS/cm.
#   mS/cm and dS/m are the same number. uS/cm is 1000x larger.
#   "ppm" is NOT a unit of conductivity: a meter measures EC and multiplies by a scale.
#     500 scale (often labelled "TDS"): 1.0 mS/cm reads 500 ppm
#     700 scale:                        1.0 mS/cm reads 700 ppm
#   The same 2.0 mS/cm feed therefore reads 1000 or 1400 "ppm" depending on the pen, which
#   is why a bare "ppm" can never be converted without being told the scale. Which scale a
#   pen uses is printed on it or in its manual; it varies by brand and by country.
#   CF (conductivity factor) is mS/cm x 10.
EC_FACTORS = {
    "ms_cm": 1.0,
    "us_cm": 0.001,
    "s_m": 10.0,
    "ppm_500": 1 / 500,
    "ppm_700": 1 / 700,
    "cf": 0.1,
}

# What the operator may pick for probes that do not say (or say only "ppm").
EC_UNIT_AUTO = "auto"
EC_UNIT_CHOICES = (EC_UNIT_AUTO, "ms_cm", "us_cm", "ppm_500", "ppm_700", "cf")

# A probe's own unit_of_measurement, normalised, -> scale. "ppm" is deliberately absent.
_DECLARED_EC = {
    "ms/cm": "ms_cm",
    "ds/m": "ms_cm",
    "mmho/cm": "ms_cm",
    # By universal convention a bare "EC" of 2.0 means 2.0 mS/cm (CF is labelled CF).
    "ec": "ms_cm",
    "us/cm": "us_cm",
    "umho/cm": "us_cm",
    "s/m": "s_m",
    "cf": "cf",
}
_AMBIGUOUS_PPM = {"ppm", "mg/l"}

EC_PROBLEM_AMBIGUOUS_PPM = "ec_unit_ppm_scale"
EC_PROBLEM_MISSING = "ec_unit_missing"
EC_PROBLEM_UNKNOWN = "ec_unit_unknown"


def normalize_unit(unit) -> str:
    """Lower-case, no spaces, and both code points people type for micro folded to 'u'."""
    return (
        str(unit or "")
        .strip()
        .lower()
        .replace(" ", "")
        .replace("µ", "u")  # MICRO SIGN
        .replace("μ", "u")  # GREEK SMALL LETTER MU
    )


def ec_factor(unit, hint=EC_UNIT_AUTO) -> tuple[float | None, str | None]:
    """(factor to mS/cm, None) or (None, problem key).

    A probe that declares an unambiguous unit is always believed over the operator's pick:
    the pick exists for probes that say nothing, or say only "ppm".
    """
    declared = normalize_unit(unit)
    if declared in _DECLARED_EC:
        return EC_FACTORS[_DECLARED_EC[declared]], None
    hint = hint if hint in EC_FACTORS else EC_UNIT_AUTO
    if declared in _AMBIGUOUS_PPM:
        if hint in ("ppm_500", "ppm_700"):
            return EC_FACTORS[hint], None
        return None, EC_PROBLEM_AMBIGUOUS_PPM
    if not declared:
        if hint != EC_UNIT_AUTO:
            return EC_FACTORS[hint], None
        return None, EC_PROBLEM_MISSING
    return None, EC_PROBLEM_UNKNOWN


def ec_to_ms_cm(value: float, unit, hint=EC_UNIT_AUTO) -> float:
    """Convert a live reading. An unconvertible unit passes through UNCHANGED.

    Setup refuses to map such a probe, so this only happens on an install from before units
    were checked (an env-file mapping, a template with no unit). Those readings were always
    averaged as-is; changing them on upgrade would move a live room's EC under its operator.
    """
    factor, _problem = ec_factor(unit, hint)
    return value if factor is None else value * factor


# ---------------------------------------------------------------------------
# Volume and dripper flow
# ---------------------------------------------------------------------------
LITRES_PER_US_GALLON = 3.785411784

# Keys are what is stored and what the dropdowns translate, so they are lowercase slugs
# (hassfest rejects a translation key such as "L/hr"). The symbol a person sees is separate.
VOLUME_UNITS = {"litres": 1.0, "us_gallons": LITRES_PER_US_GALLON}  # x factor = litres
FLOW_UNITS = {"lph": 1.0, "gph": LITRES_PER_US_GALLON}  # x factor = L/hr
_SYMBOLS = {"litres": "L", "us_gallons": "gal", "lph": "L/hr", "gph": "gal/hr"}


def symbol(unit: str, fallback: str = "L") -> str:
    """What to show beside a number: "gal/hr" for "gph". An unknown unit reads as metric,
    matching to_litres/to_lph, which convert an unknown unit with a factor of 1."""
    return _SYMBOLS.get(unit, fallback)


def default_units(is_metric: bool) -> tuple[str, str]:
    """(volume unit, flow unit) for the unit system Home Assistant is already set to."""
    return ("litres", "lph") if is_metric else ("us_gallons", "gph")


def to_litres(value: float, unit: str) -> float:
    return float(value) * VOLUME_UNITS.get(unit, 1.0)


def from_litres(litres: float, unit: str) -> float:
    return float(litres) / VOLUME_UNITS.get(unit, 1.0)


def to_lph(value: float, unit: str) -> float:
    return float(value) * FLOW_UNITS.get(unit, 1.0)


def from_lph(lph: float, unit: str) -> float:
    return float(lph) / FLOW_UNITS.get(unit, 1.0)


def tidy(value: float, places: int = 2) -> float:
    """Round for display/storage without turning 6.0 L into 5.999999 after a round trip."""
    rounded = round(float(value), places)
    return rounded if math.isfinite(rounded) else value
