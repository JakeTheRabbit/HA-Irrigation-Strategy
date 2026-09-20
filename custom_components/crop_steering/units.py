"""Probe units the integration understands, and how each becomes the unit it steers in.

Pore EC is steered in mS/cm and VWC in percent. A probe in another unit is accepted only when the
conversion is exact. Letting a raw 3200 uS/cm into an EC comparison written for 3.2 mS/cm would read
as a thousandfold overshoot, and the engine enlarges shots when pore EC is over target.
"""

from __future__ import annotations

# unit (lower-cased, spaces removed) -> multiply the reading by this
_TO_NATIVE: dict[str, dict[str, float]] = {
    "ec": {
        "ms/cm": 1.0,
        "ds/m": 1.0,
        "µs/cm": 0.001,  # micro sign, U+00B5
        "μs/cm": 0.001,  # Greek small mu, U+03BC: what many integrations actually emit
        "us/cm": 0.001,
    },
    "vwc": {
        "%": 1.0,
        "m³/m³": 100.0,
        "m3/m3": 100.0,
    },
}
# Units that look convertible and are not, with the reason an operator needs.
_REFUSED: dict[str, dict[str, str]] = {
    "ec": {
        "ppm": "ppm depends on the meter's 500 or 700 scale, which a sensor does not report; "
        "use the probe's EC reading instead",
        "ppt": "ppt depends on the meter's conversion scale; use the probe's EC reading instead",
    },
}


def normalise(unit) -> str:
    return str(unit or "").lower().replace(" ", "")


def accepted(kind: str) -> set[str]:
    return set(_TO_NATIVE.get(kind, {}))


def refusal(kind: str, unit) -> str | None:
    """Why this unit is not accepted for this kind of probe, when there is a specific reason."""
    return _REFUSED.get(kind, {}).get(normalise(unit))


def to_native(kind: str | None, unit, value: float) -> float:
    """The reading in the unit the integration steers in.

    A unit this table does not know is passed through unchanged. Installs older than setup validation
    have probes with no unit or an odd label, and their readings must keep meaning what they meant.
    """
    return value * _TO_NATIVE.get(kind or "", {}).get(normalise(unit), 1.0)
