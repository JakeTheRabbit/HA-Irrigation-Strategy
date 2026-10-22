"""A moisture probe's user offset and curve (G9), applied to its reading before the zone's probes are fused.

PURE except `read`, which only consults the unit table. Nothing here touches the store, Home Assistant
or the journal: calibration.py keeps the settings, sensor.py applies them.

`apply(raw, offset, curve)` is `curve(raw) + offset`:

- with no curve the probe already reads moisture in percent, and the offset is percentage points
  (handheld meter 52 %, probe 49 % -> offset +3);
- with a curve the probe reads something else that the curve turns into moisture in percent
  (a dielectric permittivity, "epsilon"), as the quadratic `a + b*raw + c*raw**2`. A curve applies only
  to a probe whose unit is an explicit permittivity label (`is_permittivity`); any other probe, with no
  unit included, is refused a curve (calibration.py) and set aside if it somehow has one.

CURVES are GENERIC APPROXIMATIONS, not substrate calibrations. They are quadratic least-squares fits of the Topp et al. 1980 cubic for mineral soil,
theta = -5.3e-2 + 2.92e-2*e - 5.5e-4*e**2 + 4.3e-6*e**3 (Topp, Davis & Annan, Water Resources Research
16(3), 574-582), in percent moisture:

- "generic_soilless": fitted over e = 3..30 (coir and peat blends; worst error 0.42 points of moisture);
- "generic_rockwool": fitted over e = 10..60 (wet slabs; worst error 2.7 points of moisture).

They are generic starting curves, not a vendor's substrate calibration: matching a handheld meter
(`offset`) corrects the rest at the moisture the grower steers around.
"""

from __future__ import annotations

import math

from .units import to_native

CURVES = {
    "generic_soilless": (-4.14733, 2.616006, -0.033715),
    "generic_rockwool": (7.46991, 1.501645, -0.00985),
}
CURVE_WARNING = (
    "Generic approximation (Topp 1980 mineral-soil fit) \u2014 not a substrate calibration; "
    "match a handheld after choosing."
)
# Bounds on what a grower may enter, in percentage points of moisture.
OFFSET_LIMIT = 20.0


def is_permittivity(unit) -> bool:
    """Whether `unit` is an explicit permittivity label: it names epsilon, permittivity or dielectric."""
    text = str(unit or "").lower()
    return any(
        label in text for label in ("ε", "epsilon", "permittivity", "dielectric")
    )


def apply(raw: float, offset: float = 0.0, curve: str | None = None) -> float:
    """The probe's reading under its offset and curve. `raw` is what the probe reports (percent when
    there is no curve)."""
    if curve is None:
        return raw + offset
    try:
        a, b, c = CURVES[curve]
    except KeyError:
        raise ValueError(f"Unknown curve {curve!r}") from None
    return a + b * raw + c * raw * raw + offset


def read(raw: float, unit, offset: float, curve: str | None, source=None):
    """(base, value, set aside) for a moisture probe reporting `raw` in `unit` under this offset and
    curve. `base` is the reading before the offset and curve are applied, in the unit the offset and
    the curve work in; `value` is None when the probe is set aside for its unit."""
    if curve is not None:
        # A raw reading in any other unit is never fed into the quadratic: the probe is set aside.
        if not is_permittivity(unit):
            return None, None, True
        if not math.isfinite(raw):
            return None, None, False
        return raw, apply(raw, offset, curve), False
    base, aside = to_native("vwc", unit, raw, source)
    if base is None or aside:
        return None, None, True
    return base, apply(base, offset), False
