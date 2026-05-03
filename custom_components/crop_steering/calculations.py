"""Pure calculation helpers for crop steering."""

from __future__ import annotations

from .const import PERCENTAGE_TO_RATIO, SECONDS_PER_HOUR


class ShotCalculator:
    """Helper class for irrigation shot calculations."""

    @staticmethod
    def calculate_shot_duration(dripper_flow: float, substrate_vol: float, shot_size: float) -> float:
        """Calculate irrigation shot duration in seconds."""
        try:
            if dripper_flow and dripper_flow > 0:
                volume_to_add = substrate_vol * (shot_size * PERCENTAGE_TO_RATIO)
                duration_hours = volume_to_add / dripper_flow
                return round(duration_hours * SECONDS_PER_HOUR, 1)
            return 0.0
        except Exception:
            return 0.0
