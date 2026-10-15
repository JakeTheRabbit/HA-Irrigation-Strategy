"""P0: has the morning dryback gone far enough to start the ramp?

The base engine starts the ramp (P1) when the dryback reaches its target, when moisture falls to the re-water
threshold, or when P0 has lasted its maximum wait. The dryback is measured from the highest reading since P0
began, and a reading lifted by free water (a shot shortly before, a P0 flush) drains away within minutes, so
the figure reads larger than the slab really dried. And the plants' morning uptake varies: some mornings they
are drinking within the hour, some mornings the slab barely moves until the timer ends P0. A grower looking at
the curve starts the ramp when the plants are drinking and the slab has dried back enough. So does this
judge. It can only bring the ramp forward: the base engine's own three ways out of P0 still happen.
"""
from datetime import timedelta

from ..context import flat_minutes, trend, words_trend
from ..doctrine import doctrine
from .base import Judge, choice, common, with_doctrine
from .dusk import rate_between

STATES = {
    "start_ramp_now": "The plants are drinking (moisture falling steadily) and the slab has dried back enough: "
                      "start the ramp.",
    "keep_drying": "The dryback is still in progress, or the plants have not started drinking yet: wait.",
    "probe_not_moving": "The probe reading is not changing, so the dryback reading can't be trusted: leave it "
                        "to the timer.",
    "insufficient_evidence": "The facts do not support any of the other answers.",
}

QUESTIONS = with_doctrine({
    "dawn_call": [
        choice("You are the head grower watching one zone's morning dryback after lights-on, on rockwool or "
               "coco. Judge only from the facts given. The overnight dryback does the main drying; the morning "
               "dryback only lets the slab dry a little further once the plants start drinking, which shows as "
               "moisture falling steadily. In a vegetative stage the first shot comes early and the morning "
               "dryback is short; in a generative stage it runs longer. Flat moisture after lights-on means the "
               "plants are not transpiring yet. When the peak the dryback is "
               "measured from sits above the reading at the start of the dryback, it was free water and the "
               "dryback figure reads high. A reading that has not changed at all for a long time is not "
               "measuring.", STATES),
        choice("Decide whether this zone's first watering of the day should start now. Start only when both "
               "are true: the plants are drinking (moisture falling now, as it was yesterday morning) and the "
               "slab has dried back most of the way to its target, counted from where it stood when the dryback "
               "began. If moisture is flat or the dryback is still well short, wait. If the probe reading has "
               "not moved at all, its dryback can't be trusted and the timer should decide.", STATES),
    ],
}, doctrine("dryback", "stage") + " " + doctrine("probe", "closed_loop", limit=3))


def _share(done, target):
    if target <= 0:
        return "no target set"
    f = done / target
    return ("target reached" if f >= 1.0 else "over three quarters of the way" if f >= 0.75
            else "over half way" if f >= 0.5 else "a quarter to half way" if f >= 0.25
            else "under a quarter of the way")


class DawnJudge(Judge):
    name = "dawn"
    phases = ("P0",)
    cadence_min = 10.0
    max_age_min = 20.0
    questions = QUESTIONS

    def evidence(self, ctx):
        s, p, h = ctx.snap, ctx.params, ctx.history
        left = p.p0_max_wait_min - s.phase_minutes
        e = common(ctx)
        e.update({
            "minutes_in_morning_dryback": (f"{s.phase_minutes:.0f} of at most {p.p0_max_wait_min:.0f}; the timer "
                                           "starts the ramp " + ("now" if left <= 0 else f"in {left:.0f} minutes")),
            "dryback_so_far": (f"{s.dryback_pct:.1f}% of a {p.dryback_target:.1f}% target, measured from the "
                               f"highest reading since the dryback began ({s.peak_vwc:.1f}%): "
                               f"{_share(s.dryback_pct, p.dryback_target)}"),
            "dryback_from_start": self._from_start(ctx),
            "moisture_vs_rewater_threshold": (f"{s.vwc - p.p2_threshold:.1f} points above the re-water threshold "
                                              f"of {p.p2_threshold:.1f}% (at the threshold the ramp starts anyway)"
                                              if s.vwc > p.p2_threshold else "at or under the re-water threshold"),
            "moisture_last_15_min": words_trend(trend(h, ctx.now, 15)),
            "moisture_last_30_min": words_trend(trend(h, ctx.now, 30)),
            "pore_ec_last_hour": words_trend(trend(h, ctx.now, 60, index=2), "mS/cm", "pore EC"),
            "minutes_reading_unchanged": flat_minutes(h, ctx.now),
            "yesterday_ramp_started": self._yesterday_ramp(ctx),
        })
        y = rate_between(h, ctx.now - timedelta(hours=24, minutes=30), ctx.now - timedelta(hours=24))
        e["same_time_yesterday"] = ("no clean reading from this time yesterday" if y is None
                                    else f"{words_trend(y)} at this time yesterday")
        return e

    @staticmethod
    def _from_start(ctx):
        """The dryback counted from the reading when P0 began, which a free-water spike can't inflate."""
        s, p = ctx.snap, ctx.params
        start = ctx.history.at(ctx.now - timedelta(minutes=s.phase_minutes))
        if start is None or start[1] <= 0:
            return "no reading from when the dryback began"
        v0 = start[1]
        pts = v0 - s.vwc
        rel = pts / v0 * 100.0
        text = (f"moisture was {v0:.1f}% when the dryback began and is {s.vwc:.1f}% now: "
                f"{'down' if pts >= 0 else 'up'} {abs(pts):.1f} points, a {max(rel, 0.0):.1f}% dryback "
                f"({_share(rel, p.dryback_target)})")
        if s.peak_vwc - v0 >= 0.5:
            text += (f"; the peak the dryback figure is measured from is {s.peak_vwc - v0:.1f} points above that, "
                     "free water, so that figure reads high")
        return text

    @staticmethod
    def _yesterday_ramp(ctx):
        ramp = [sh for sh in ctx.history.shots
                if sh.kind.startswith("p1") and sh.start >= ctx.now - timedelta(hours=26)]
        if not ramp or ramp[0].pre_vwc is None:
            return "not in the last day's record"
        first, vwc = ramp[0], ctx.snap.vwc
        return (f"the first ramp shot was at {first.start:%H:%M} with moisture at {first.pre_vwc:.1f}%, "
                f"{abs(first.pre_vwc - vwc):.1f} points {'above' if first.pre_vwc > vwc else 'below'} this zone now")

    def decide(self, verdicts, ctx):
        v = verdicts.get("dawn_call")
        if v is None or not v.firm(0.6) or v.label != "start_ramp_now":
            return None
        return self.directive(ctx, "advance", "P1", f"dryback done, plants drinking: start_ramp_now (p={v.prob:.2f})")
