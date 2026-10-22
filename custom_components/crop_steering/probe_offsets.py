"""A moisture probe's user offset and curve (G9), applied to its reading before the zone's probes are fused.

PURE except `read`, which only consults the unit table. Nothing here touches the store, Home Assistant
or the journal: calibration.py keeps the settings, sensor.py applies them.

`apply(raw, offset, curve)` is `curve(raw) + offset`:

- with no curve the probe already reads moisture in percent, and the offset is percentage points
  (handheld meter 52 %, probe 49 % -> offset +3);
- with a curve the probe reads something else that the curve turns into moisture in percent
  (a dielectric permittivity, "epsilon"), as the quadratic `a + b*raw + c*raw**2`. A probe whose unit is
  already percent has nothing to convert and is refused a curve (calibration.py).

CURVES are quadratic least-squares fits of the Topp et al. 1980 cubic for mineral soil,
theta = -5.3e-2 + 2.92e-2*e - 5.5e-4*e**2 + 4.3e-6*e**3 (Topp, Davis & Annan, Water Resources Research
16(3), 574-582), in percent moisture:

- "soilless": fitted over e = 3..30 (coir and peat blends; worst error 0.42 points of moisture);
- "rockwool": fitted over e = 10..60 (wet slabs; worst error 2.7 points of moisture).

They are generic starting curves, not a vendor's substrate calibration: matching a handheld meter
(`offset`) corrects the rest at the moisture the grower steers around.
"""

from __future__ import annotations

import math

from .units import to_native

CURVES = {
    "soilless": (-4.14733, 2.616006, -0.033715),
    "rockwool": (7.46991, 1.501645, -0.00985),
}
# Bounds on what a grower may enter, in percentage points of moisture.
OFFSET_LIMIT = 20.0


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
        if not math.isfinite(raw):
            return None, None, False
        return raw, apply(raw, offset, curve), False
    base, aside = to_native("vwc", unit, raw, source)
    if base is None or aside:
        return None, None, True
    return base, apply(base, offset), False
