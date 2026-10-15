"""P3: is the overnight fall toward the emergency floor the slab drying, or the probe?

Overnight the base engine fires a rescue shot whenever the reading falls under the P3 emergency floor. That is
right for a slab that is really drying, and it stays so: this judge never stops a rescue. But a probe that slips
out of the block, loses contact as the slab shrinks, or steps down on a bad reading looks exactly like a slab
running dry, and nobody finds out until someone reads the curve in the morning. A person reading it tells a
steady transpiration-and-drainage fall from a step, a fall far faster than the same hour last night, or a line
that stopped moving. So does this judge, and all it may do is say so: an alert naming the zone, the reading,
the floor, and that the rescue shot still fires as normal.
"""
from datetime import timedelta

from ..context import SETTLE_MIN, flat_minutes, response, trend, words_response, words_trend
from ..doctrine import doctrine
from .base import Judge, choice, common, with_doctrine
from .dusk import rate_between

STATES = {
    "real_drying": "Steady overnight drying consistent with transpiration and drainage: a smooth fall at about "
                   "the pace the zone dried on previous nights.",
    "probe_fault": "A probe fault: a sudden step, a reading that disagrees with how the zone dried on previous "
                   "nights, or a probe that stopped moving.",
    "insufficient_evidence": "The facts do not support any of the other answers.",
}

QUESTIONS = with_doctrine({
    "night_drop": [
        choice("You are checking one zone overnight, lights off, on rockwool or coco, whose moisture reading is "
               "falling toward the emergency floor where a rescue shot fires. Judge only from the facts given. "
               "With the lights off the plants drink little, so real overnight drying is smooth and "
               "steady and looks like the same hour on previous nights; how many points it is depends on the "
               "probe, so compare with this zone's own nights. Lights-off also cools the slab, and a reading "
               "that bends right at lights-off can be temperature, not water. A sudden "
               "step between two readings in a row is not drying. A fall much faster than the same hour last "
               "night, a reading frozen on one value, or a rescue shot the reading did not rise for, points to "
               "the probe, not the slab.", STATES),
        choice("Is this zone really drying toward its emergency floor tonight, or is its moisture probe "
               "misreading? Transpiration and drainage dry a slab smoothly and at much the same pace each night. "
               "A step down, a fall far faster than at this hour last night, or a probe stuck on one value is "
               "what a probe fault looks like.", STATES),
    ],
}, doctrine("dryback", "closed_loop", limit=3) + " " + doctrine("probe", limit=5))


def _pace(tonight, last):
    """Tonight's fall against the same hour last night, in words (the ratio is code's to work out)."""
    if tonight is None or last is None:
        return "can't be compared (too few readings)"
    fall, was = -tonight, -last
    if fall < 0.05:
        return "not falling tonight"
    if was < 0.05:
        return "falling tonight where at this hour last night it held steady"
    ratio = fall / was
    if ratio > 2.0:
        return f"falling {ratio:.1f} times as fast as at this hour last night"
    if ratio < 0.5:
        return "falling more slowly than at this hour last night"
    return "falling at about the pace of this hour last night"


def _frozen(flat, last):
    """Whether an unchanged reading is longer than last night's pace explains: a slow overnight fall holds one
    value for a while on its own (0.05 points at 0.1 points an hour is half an hour)."""
    if last is None:
        return "can't be compared (no clean reading of last night)"
    if -last < 0.05:
        return "last night held steady at this hour too"
    expected = 0.05 / -last * 60.0
    return ("longer than last night's pace explains: the reading looks frozen" if flat >= max(30.0, 3.0 * expected)
            else "no longer than last night's pace explains")


def _largest_step(ctx, minutes=180):
    """The biggest fall between two readings in a row, leaving out a shot's free water draining away."""
    pts = ctx.history.since(ctx.now - timedelta(minutes=minutes))
    shots = ctx.history.shots
    best = None
    for (_, v0, _e0), (t1, v1, _e1) in zip(pts, pts[1:]):
        if any(sh.start <= t1 <= sh.start + timedelta(seconds=sh.seconds, minutes=SETTLE_MIN) for sh in shots):
            continue
        if best is None or v0 - v1 > best[0]:
            best = (v0 - v1, t1)
    if best is None:
        return "too few readings to tell"
    if best[0] < 0.05:
        return "no fall of more than 0.05 points between two readings in a row (a smooth line)"
    size = "a sudden step" if best[0] >= 1.0 else "a small jump" if best[0] >= 0.3 else "smooth"
    return f"{best[0]:.2f} points between two readings in a row at {best[1]:%H:%M} ({size})"


class NightJudge(Judge):
    name = "night"
    phases = ("P3",)
    cadence_min = 20.0
    max_age_min = 40.0
    questions = QUESTIONS

    def due(self, ctx, last_asked):
        return super().due(ctx, last_asked) and ctx.snap.vwc <= ctx.params.p3_emergency_floor + 3.0

    def evidence(self, ctx):
        s, p, h = ctx.snap, ctx.params, ctx.history
        floor = p.p3_emergency_floor
        tonight = trend(h, ctx.now, 60)
        last = rate_between(h, ctx.now - timedelta(hours=25), ctx.now - timedelta(hours=24))
        then = h.at(ctx.now - timedelta(hours=24))
        since = ctx.now - timedelta(minutes=s.phase_minutes)
        typical = ctx.typical_rise()
        rescues = [words_response(response(h, sh, ctx.now), typical)
                   for sh in h.shots if sh.start >= since and sh.kind.startswith("p3")]
        flat = flat_minutes(h, ctx.now)
        e = common(ctx)
        e.update({
            "moisture_vs_emergency_floor": (f"{s.vwc - floor:.1f} points above the emergency floor of {floor:.1f}%; "
                                            "the rescue shot fires under it" if s.vwc >= floor else
                                            f"{floor - s.vwc:.1f} points under the emergency floor of {floor:.1f}%; "
                                            "the rescue shot fires"),
            "moisture_last_hour": words_trend(tonight),
            "moisture_last_3_hours": words_trend(trend(h, ctx.now, 180)),
            "same_hour_last_night": ("no reading from this time last night" if then is None
                                     else f"{then[1]:.1f}% at this time last night, {words_trend(last)}"),
            "tonight_vs_last_night": _pace(tonight, last),
            "largest_step_last_3_hours": _largest_step(ctx),
            "minutes_reading_unchanged": flat,
            "unchanged_reading_vs_last_night": _frozen(flat, last),
            "rescue_shots_tonight": rescues or ["none yet"],
        })
        return e

    def decide(self, verdicts, ctx):
        v = verdicts.get("night_drop")
        if v is None or not v.firm(0.7) or v.label != "probe_fault":
            return None
        s, floor = ctx.snap, ctx.params.p3_emergency_floor
        message = (f"{ctx.title} reads {s.vwc:.1f}% overnight, close to its emergency floor of {floor:.1f}%, but "
                   "the way the reading fell looks like a probe fault, not the slab drying. The rescue shot still "
                   "fires as normal whenever the reading is under the floor. Check the probe in the morning.")
        alert = {"code": "CS-703", "title": "overnight low reading looks like a probe fault", "message": message}
        return self.directive(ctx, "alert", alert, f"overnight fall looks like a probe fault (p={v.prob:.2f})")
