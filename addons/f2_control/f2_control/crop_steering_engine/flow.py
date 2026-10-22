"""Flow reconciliation: compare the water commanded with the water a meter saw. Pure, stdlib only."""

LOW = 0.80
HIGH = 1.20

_EPS = 1e-9
_LITRES = {"L": 1.0, "l": 1.0, "m³": 1000.0, "gal": 3.785411784}


def to_litres(value: float, unit: str | None) -> float | None:
    """Convert a metered volume to litres. An unknown unit is never guessed: it gives None."""
    factor = _LITRES.get(unit) if isinstance(unit, str) else None
    return None if factor is None else value * factor


def reconcile(commanded_l: float, metered_l: float | None) -> dict:
    """Ratio of metered to commanded litres and a verdict: ok, low (< LOW), high (> HIGH) or unmetered."""
    if metered_l is None or commanded_l <= 0:
        return {"ratio": None, "verdict": "unmetered"}
    ratio = metered_l / commanded_l
    verdict = "low" if ratio < LOW - _EPS else "high" if ratio > HIGH + _EPS else "ok"
    return {"ratio": ratio, "verdict": verdict}
