"""A zone's moisture ladder, and which moves of it are refused. Pure: no Home Assistant.

The engine waters by the order between the levels: rescue + 3 <= re-water < peak target. A rescue
level at or above the re-water level waters all night, outside the daily cap. So a move that breaks
a rule the ladder kept is refused. A move is judged as ONE set (a recipe stage, Auto setpoints'
moves), never level by level, so a move of several levels does not depend on the order they are
written in. A ladder that is already out of order can be repaired one number at a time: only a rule
the ladder kept before the move can refuse it.

A peak target above field capacity is only advised, not refused: the ramp stops at field capacity
anyway, and a peak above it is a deliberate choice on some probes.
"""

from __future__ import annotations

LADDER = (
    "p3_emergency_vwc_threshold",
    "p2_vwc_threshold",
    "p1_target_vwc",
    "field_capacity",
)


def broken(ladder):
    """The ordering rules `ladder` breaks: "rescue", "peak". A level it lacks breaks nothing."""
    rescue, rewater, peak = (ladder.get(key) for key in LADDER[:3])
    out = set()
    if rescue is not None and rewater is not None and rescue + 3 > rewater:
        out.add("rescue")
    if rewater is not None and peak is not None and rewater >= peak:
        out.add("peak")
    return out


def refusal(current, changes):
    """Why moving `current` by `changes`, as one set, is refused: None when it is not."""
    after = {**current, **changes}
    new = broken(after) - broken(current)
    rescue, rewater, peak = (after.get(key) for key in LADDER[:3])
    words = []
    if "rescue" in new:
        words.append(
            f"the re-water level ({rewater:g}) must stay at least 3 points above "
            f"the rescue level ({rescue:g})"
        )
    if "peak" in new:
        words.append(
            f"the re-water level ({rewater:g}) must stay below the peak target ({peak:g})"
        )
    return "; ".join(words) or None


def peak_above_field_capacity(current, changes):
    """True when the move puts the peak target above field capacity (advised, never refused)."""

    def above(ladder):
        peak, fc = ladder.get("p1_target_vwc"), ladder.get("field_capacity")
        return peak is not None and fc is not None and peak > fc

    return above({**current, **changes}) and not above(current)
