"""Pure calculation helpers for crop steering."""

from __future__ import annotations

import math
import statistics

from .const import PERCENTAGE_TO_RATIO, SECONDS_PER_HOUR


def fuse_probes(readings, offsets, lo, hi, stale_s):
    """Combine one zone's probes into the single reading the controller steers by.

    `readings` is every probe the zone maps as (entity_id, value or None, age in seconds or None),
    the value already in the room's unit. `offsets` remembers how far each probe read from the zone
    reading the last time every probe was usable; it is updated in place and belongs to the zone.

    - A value outside lo..hi cannot be a real reading and is not used.
    - A probe that has not reported for stale_s is used only when no other probe has.
    - With every probe usable the reading is their median: the mean for two, and one wild probe
      among three or more moves nothing.
    - With a probe missing, each remaining probe is first shifted by its remembered offset, so
      losing a probe does not step the reading the controller measures dryback and thresholds from.

    Returns (reading or None, detail for the sensor's attributes).
    """
    readings = list({pid: (pid, v, age) for pid, v, age in readings}.values())
    usable = {
        pid: (v, age)
        for pid, v, age in readings
        if v is not None and math.isfinite(v) and lo <= v <= hi
    }
    pool = {pid: v for pid, (v, age) in usable.items() if age is None or age <= stale_s}
    pool = pool or {pid: v for pid, (v, _age) in usable.items()}
    detail = {
        "probes": len(readings),
        "used": sorted(pool),
        "excluded": {
            pid: (
                "no reading"
                if v is None or not math.isfinite(v)
                else "out of range" if pid not in usable else "not reporting"
            )
            for pid, v, _age in readings
            if pid not in pool
        },
        "spread": round(max(pool.values()) - min(pool.values()), 2) if pool else None,
    }
    if not pool:
        return None, detail
    if len(pool) == len(readings):
        fused = statistics.median(pool.values())
        offsets.clear()
        offsets.update({pid: v - fused for pid, v in pool.items()})
    else:
        fused = statistics.median(v - offsets.get(pid, 0.0) for pid, v in pool.items())
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
