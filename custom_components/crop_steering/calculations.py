"""Pure calculation helpers for crop steering."""

from __future__ import annotations

import math
import statistics

from .const import (
    PERCENTAGE_TO_RATIO,
    PROBE_EXTREME_MIN,
    PROBE_METHODS,
    SECONDS_PER_HOUR,
)


def _combine(values, method):
    """Probe readings as one, by a PROBE_METHODS name; the median for any other."""
    values = list(values)
    if method == "Average":
        return sum(values) / len(values)
    if method == "Lowest":
        return min(values)
    if method == "Highest":
        return max(values)
    return statistics.median(values)


def ec_type_key(probe):
    """The key of the select saying what EC probe `probe` (an entity id) measures (select.py)."""
    return f"ec_type_{probe.split('.', 1)[-1]}"


def _passes(v, age, lo, hi, stale_s):
    """A probe reading the zone can use as it is: a number in lo..hi, reported within stale_s."""
    return (
        v is not None
        and math.isfinite(v)
        and lo <= v <= hi
        and (age is None or age <= stale_s)
    )


def fuse_probes(
    readings, offsets, lo, hi, stale_s, method="Median", far=None, ec_types=None
):
    """Combine one zone's probes into the single reading the controller steers by.

    `readings` is every probe the zone maps as (entity_id, value or None, age in seconds or None),
    the value already in the room's unit. `offsets` remembers how far each probe read from the zone
    reading the last time every probe was usable, keyed by probe; it is updated in place, belongs
    to the zone, and is forgotten when the zone's probes change.

    - A value outside lo..hi cannot be a real reading and is not used.
    - A probe that has not reported for stale_s is used only when no other probe has.
    - With three or more probes left, one further from their median than the larger of
      `far` (units, share of the median) agrees with none of them and is not used.
    - The rest become one reading by `method` (PROBE_METHODS; the median, the mean for two). Lowest
      and Highest let one probe steer the zone, so with fewer than PROBE_EXTREME_MIN probes left
      the zone steers on the median instead, and detail["steered_by"] says so.
    - With every probe used, each probe's offset is learned against that reading. With a probe
      missing, each remaining probe is first shifted by its offset, so losing a probe does not step
      the reading the controller measures dryback and thresholds from.
    - `ec_types` says what each EC probe measures (EC_TYPES; unknown when absent). A zone with
      both a pore and a bulk probe never combines the two: it steers on its pore probes (and the
      unknown ones) while one of them passes, else on its bulk probes (and the unknown ones), and
      detail["ec_type"] says which. Unknown probes alone, or beside one type only, fuse as before.

    Returns (reading or None, detail for the sensor's attributes).
    """
    readings = list({pid: (pid, v, age) for pid, v, age in readings}.values())
    kept_apart, ec_type = {}, None
    types = {pid: (ec_types or {}).get(pid) for pid, _v, _age in readings}
    if {"pore", "bulk"} <= set(types.values()):
        pore = any(
            types[pid] == "pore" and _passes(v, age, lo, hi, stale_s)
            for pid, v, age in readings
        )
        ec_type = "pore" if pore else "bulk"
        kept_apart = {
            pid: (
                "bulk EC, kept apart from pore EC"
                if pore
                else (
                    "no reading"
                    if v is None or not math.isfinite(v)
                    else "out of range" if not lo <= v <= hi else "not reporting"
                )
            )
            for pid, v, _age in readings
            if types[pid] == ("bulk" if pore else "pore")
        }
        readings = [r for r in readings if r[0] not in kept_apart]
    if offsets and set(offsets) != {pid for pid, _v, _age in readings}:
        offsets.clear()  # another set of probes: what this one learned says nothing about it
    usable = {
        pid: (v, age)
        for pid, v, age in readings
        if v is not None and math.isfinite(v) and lo <= v <= hi
    }
    pool = {pid: v for pid, (v, age) in usable.items() if age is None or age <= stale_s}
    pool = pool or {pid: v for pid, (v, _age) in usable.items()}
    far_off = set()
    if far is not None and len(pool) >= 3:
        middle = statistics.median(pool.values())
        limit = max(far[0], far[1] * abs(middle))
        far_off = {pid for pid, v in pool.items() if abs(v - middle) > limit}
        if len(far_off) < len(pool):
            pool = {pid: v for pid, v in pool.items() if pid not in far_off}
        else:
            far_off = set()
    method = method if method in PROBE_METHODS else "Median"
    steered_by = (
        method
        if method not in ("Lowest", "Highest") or len(pool) >= PROBE_EXTREME_MIN
        else "Median"
    )
    detail = {
        "probes": len(readings) + len(kept_apart),
        "used": sorted(pool),
        "excluded": kept_apart
        | {
            pid: (
                "no reading"
                if v is None or not math.isfinite(v)
                else (
                    "out of range"
                    if pid not in usable
                    else "far from the others" if pid in far_off else "not reporting"
                )
            )
            for pid, v, _age in readings
            if pid not in pool
        },
        "spread": round(max(pool.values()) - min(pool.values()), 2) if pool else None,
        "method": method,
        "steered_by": steered_by,
    }
    if ec_type:
        detail["ec_type"] = ec_type
    if not pool:
        return None, detail
    if len(pool) == len(readings):
        fused = _combine(pool.values(), steered_by)
        offsets.clear()
        offsets.update({pid: v - fused for pid, v in pool.items()})
    else:
        fused = _combine(
            (v - offsets.get(pid, 0.0) for pid, v in pool.items()), steered_by
        )
    return round(fused, 2), detail


class ShotCalculator:
    """Helper class for irrigation shot calculations."""

    @staticmethod
    def calculate_shot_duration(
        dripper_flow: float, substrate_vol: float, shot_size: float
    ) -> float:
        """Calculate irrigation shot duration in seconds."""
        try:
            if dripper_flow and dripper_flow > 0:
                volume_to_add = substrate_vol * (shot_size * PERCENTAGE_TO_RATIO)
                duration_hours = volume_to_add / dripper_flow
                return round(duration_hours * SECONDS_PER_HOUR, 1)
            return 0.0
        except Exception:
            return 0.0
