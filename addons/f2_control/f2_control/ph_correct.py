"""pH auto-correct for a room's batch tank: the rules, pure (docs/DOSING.md, pH auto-correct).

The dosing runner reads the room's feed pH probe about once a minute and asks Watch whether the tank
has read off its band long enough to correct; after each small dose and its mix it asks verdict()
whether to stop, dose again or give up. Nothing here reads Home Assistant or moves hardware.

Fail-closed: a reading that is missing, outside PLAUSIBLE or jumps by more than MAX_JUMP between two
reads restarts the wait, so a dead or noisy probe never doses. A dose that moves the pH by less than
MIN_MOVE ends the episode as a fault (a probe or pump problem, not chemistry), and so does a dose that
overshoots the other side of the band.
"""
from __future__ import annotations

import math

PLAUSIBLE = (3.0, 10.0)  # a tank pH outside this is a probe fault, never a reading to dose on
MAX_JUMP = 1.0  # pH between two reads: more is a probe fault
STEADY_S = 300.0  # the tank must read off its band this long, read after read, before a correction
MIN_MOVE = 0.05  # a dose that moves the pH by less than this points at a fault: stop
READ_EVERY_S = 60.0  # how often the probe is read while nothing runs
PROBE_MAX_AGE_S = 900.0  # a reading older than this is stale

# The room's settings (number.crop_steering_<prefix>ph_correct_<key>): key -> (default, low, high).
# The defaults are the ones proposed for the first site: 5 s doses, at most 2 a try.
SETTINGS = {
    "dose_s": (5.0, 1.0, 30.0),  # one dose, in seconds of the pump's calibrated flow
    "max_tries": (2.0, 1.0, 3.0),  # doses in one episode
    "mix_min": (5.0, 2.0, 30.0),  # mixing after each dose before the tank is read again
    "daily_max": (3.0, 1.0, 10.0),  # doses in one day
    "margin": (0.1, 0.0, 0.5),  # pH inside the band to stop at
}
ROLES = {"up": "ph_up", "down": "ph_down"}


def setting(value, key):
    """A setting read from Home Assistant (a float, or None when it could not be read) inside its range;
    its default when it could not be read."""
    default, low, high = SETTINGS[key]
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return default
    return min(high, max(low, float(value)))


def side(ph, lo, hi):
    """"up" when the tank reads under its band, "down" over it, else None. A bound of 0 or less is none."""
    if lo > 0 and ph < lo:
        return "up"
    if hi > 0 and ph > hi:
        return "down"
    return None


def usable(ph):
    return ph is not None and math.isfinite(ph) and PLAUSIBLE[0] <= ph <= PLAUSIBLE[1]


class Watch:
    """One room's tank, read by read: which way it needs correcting once it has read off its band,
    plausibly and steadily, for STEADY_S."""

    def __init__(self):
        self.last = None
        self.side = None
        self.since = None

    def reset(self):
        self.last = self.side = self.since = None

    def read(self, ph, lo, hi, now_s):
        """-> "up", "down" or None (nothing to do, or not yet)."""
        if not usable(ph):
            self.reset()
            return None
        if self.last is not None and abs(ph - self.last) > MAX_JUMP:
            self.reset()
            self.last = ph
            return None
        self.last = ph
        now_side = side(ph, lo, hi)
        if now_side != self.side:
            self.side, self.since = now_side, now_s
        if now_side is not None and now_s - self.since >= STEADY_S:
            return now_side
        return None


def target(way, lo, hi, margin):
    """The pH a correction stops at: margin inside the band from the side it started on."""
    return lo + margin if way == "up" else hi - margin


def verdict(way, before, after, lo, hi, margin):
    """What one dose did -> "done" (at or past its target, inside the band), "again" (moved, not there
    yet), "no response" (moved less than MIN_MOVE), "overshot" (past the other side of the band) or
    "not read" (the probe could not be read after the mix)."""
    if not usable(after):
        return "not read"
    if (way == "up" and hi > 0 and after > hi) or (way == "down" and lo > 0 and after < lo):
        return "overshot"
    goal = target(way, lo, hi, margin)
    if (way == "up" and after >= goal) or (way == "down" and after <= goal):
        return "done"
    moved = (after - before) if way == "up" else (before - after)
    if moved < MIN_MOVE:
        return "no response"
    return "again"


def dose_ml(seconds, flow, max_ml):
    """A dose of `seconds` at the pump's calibrated flow, in whole mL, never above the pump's max_ml.
    0 when it rounds to nothing."""
    ml = math.floor(seconds * flow + 0.5)
    return int(min(ml, math.floor(max_ml)))
