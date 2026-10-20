"""P2: when does the day's watering stop?

The base engine starts the overnight dryback (P3) at lights-off, or earlier by prediction: in the last 3 hours,
only when the dryback still needed would not finish by lights-on at the zone's drying rate. That rate is the
fall over the last half hour, which is usually 0 when a shot sits in that half hour, and the engine then assumes
0.1 points an hour: at that pace anything over 1.2 points is more than the 12 hours the prediction looks
ahead, so it rarely fires and the zone is topped up until lights-off. Generative steering wants the opposite:
the last shot earlier, so the slab dries back overnight toward its target. A grower stops the watering when
the zone is well above its re-water threshold and far enough above the emergency floor to coast to lights-on.
So does this judge. It can only bring P3 forward, and the overnight rescue shot still fires whatever it says.
"""
from datetime import datetime, timedelta

from ..context import SETTLE_MIN, words_trend
from ..doctrine import doctrine
from .base import Judge, choice, common, with_doctrine

STATES = {
    "enter_p3_now": "Stop watering now and start the overnight dryback: the zone is well above its re-water "
                    "threshold and far enough above the emergency floor to coast to lights-on.",
    "one_more_topup_then_p3": "Give the zone one more top-up first (it is close to its re-water threshold, or pore "
                              "EC is well above its target), then stop for the night.",
    "continue_p2": "Keep the day's watering going as normal for now: it is too early to stop, or the zone is too "
                   "low to coast through the night.",
    "insufficient_evidence": "The facts do not support any of the other answers.",
}

QUESTIONS = with_doctrine({
    "dusk_call": [
        choice("You are the head grower deciding when one zone's watering stops for the day and its overnight "
               "dryback begins, on rockwool or coco. Judge only from the facts given. Whether to stop early "
               "depends on the stage and the steering mode: generative steering (flower setting, the finish) "
               "wants the last shot earlier, so the slab dries back overnight toward the dryback target by "
               "lights-on; vegetative steering (the bulk of flower) keeps refilling through the day and wants "
               "only a small overnight dryback, so it stops late. A zone well above its re-water threshold this close to lights-off does not need "
               "another top-up. But never finish the day dry: the zone must go into the night well above the "
               "emergency floor. Pore EC well above its target climbs further as the slab dries overnight; one "
               "more shot of feed that is below pore EC brings it down first.", STATES),
        choice("Should this zone's watering stop now for the night? Stopping earlier gives a deeper overnight "
               "dryback, the main steering lever, which suits a generative stage and works against a "
               "vegetative one. Stopping with the zone low leaves it dry by morning and forces "
               "the emergency rescue shot. A zone well above its re-water threshold near lights-off has enough "
               "water to coast; a zone near its threshold, or with pore EC well above target, gets one more "
               "shot first; a zone that would end the night near the emergency floor keeps watering.", STATES),
    ],
}, doctrine("dryback", "stage") + " " + doctrine("maintenance", limit=4))


def rate_between(history, t0, t1):
    """VWC change per hour between the readings nearest `t0` and `t1`, or None: no reading near either end, or a
    shot inside the window (it would measure the shot, not the drying)."""
    a, b = history.at(t0), history.at(t1)
    if a is None or b is None or b[0] <= a[0] or any(t0 < sh.start <= t1 for sh in history.shots):
        return None
    return round((b[1] - a[1]) / ((b[0] - a[0]).total_seconds() / 3600.0), 2)


def day_rate(ctx):
    """How fast the zone has dried since its last shot settled (points an hour), or None: too soon to tell."""
    shots = ctx.history.shots
    since = (shots[-1].start + timedelta(seconds=shots[-1].seconds, minutes=SETTLE_MIN) if shots
             else ctx.now - timedelta(hours=1))
    if ctx.now - since < timedelta(minutes=20):
        return None
    return rate_between(ctx.history, since, ctx.now)


def last_night_rate(ctx):
    """Last night's drying (points an hour), from lights-off (or its last shot, settled) to lights-on, or None."""
    off = ctx.now + timedelta(hours=ctx.hours_to_off - 24.0)
    on = ctx.now + timedelta(hours=ctx.hours_to_on - 24.0)
    start = max([off] + [sh.start + timedelta(seconds=sh.seconds, minutes=SETTLE_MIN)
                         for sh in ctx.history.shots if off <= sh.start <= on])
    if on - start < timedelta(hours=2):
        return None
    return rate_between(ctx.history, start, on)


def _coast(ctx, target):
    """Where the zone ends up by lights-on if no more water goes in, in words."""
    day, night = day_rate(ctx), last_night_rate(ctx)
    if day is None or night is None:
        return ("can't be estimated: " + ("today's drying since the last shot" if day is None
                                          else "last night's drying") + " is unknown")
    s, floor = ctx.snap, ctx.params.p3_emergency_floor
    night_hours = max(ctx.hours_to_on - ctx.hours_to_off, 0.0)
    end = s.vwc + min(day, 0.0) * ctx.hours_to_off + min(night, 0.0) * night_hours
    vs_target = ("past the overnight dryback target" if end <= target
                 else f"{end - target:.1f} points short of the overnight dryback target")
    vs_floor = (f"{end - floor:.1f} points above the emergency floor" if end >= floor
                else "under the emergency floor, so the rescue shot would fire overnight")
    return (f"about {end:.1f}% by lights-on (today's drying until lights-off, last night's after): "
            f"{vs_target} ({target:.1f}%), {vs_floor} ({floor:.1f}%)")


def _against(value, mark):
    return f"{abs(value - mark):.1f} points {'above' if value >= mark else 'below'}"


class DuskJudge(Judge):
    name = "dusk"
    phases = ("P2",)
    cadence_min = 15.0
    max_age_min = 25.0
    outcome_after_min = 120.0
    questions = QUESTIONS

    def due(self, ctx, last_asked):
        # A zone steered vegetative stops late: the envelope would refuse an early stop, so don't ask.
        if (ctx.steering or (ctx.stage or {}).get("steering")) == "vegetative":
            return False
        return ctx.hours_to_off <= 3.0 and super().due(ctx, last_asked)

    def evidence(self, ctx):
        s, p = ctx.snap, ctx.params
        target = s.peak_vwc * (1.0 - p.dryback_target / 100.0)
        left = s.vwc - target
        ec = s.ec_settled if s.ec_settled is not None else s.ec
        day, night = day_rate(ctx), last_night_rate(ctx)
        e = common(ctx)
        e.update({
            "base_engine": "stops the day's watering at lights-off at the latest",
            "moisture_vs_rewater_threshold": f"{s.vwc:.1f}%, {_against(s.vwc, p.p2_threshold)} the re-water "
                                             f"threshold of {p.p2_threshold:.1f}%",
            "moisture_vs_emergency_floor": f"{_against(s.vwc, p.p3_emergency_floor)} the overnight emergency "
                                           f"floor of {p.p3_emergency_floor:.1f}%",
            "overnight_dryback_target": (f"{p.dryback_target:.0f}% down from the day's peak of {s.peak_vwc:.1f}%, "
                                         f"which is {target:.1f}% by lights-on: "
                                         + (f"{left:.1f} points still to lose overnight" if left > 0
                                            else "already reached")),
            "minutes_since_last_shot": round(s.minutes_since_shot),
            "drying_since_last_shot": ("too soon after the last shot to tell" if day is None
                                       else words_trend(day)),
            "last_night_drying": ("unknown (no clean reading of last night)" if night is None
                                  else words_trend(night)),
            "if_watering_stops_now": _coast(ctx, target),
        })
        if ec is None:
            e["pore_ec_vs_day_target"] = "unknown"
        elif p.ec_target_p2 > 0:
            r = ec / p.ec_target_p2
            words = ("well above target" if r > 1.2 else "above target" if r > 1.05
                     else "below target" if r < 0.95 else "on target")
            e["pore_ec_vs_day_target"] = f"{ec:.2f} against a day target of {p.ec_target_p2:.2f} ({words})"
        if ctx.feed_ec is not None and ec is not None:
            e["feed_vs_pore_ec"] = ("feed is lower than pore EC, so a shot lowers it"
                                    if ctx.feed_ec < ec else "feed is not lower than pore EC")
        return e

    def decide(self, verdicts, ctx):
        v = verdicts.get("dusk_call")
        if v is None or not v.firm(0.6) or v.label != "enter_p3_now":
            return None
        return self.directive(ctx, "advance", "P3", f"day's watering done: enter_p3_now (p={v.prob:.2f})")

    def outcome(self, entry, ctx):
        """Good when the zone coasted: no rescue shot since the call, and VWC at least a point above the floor."""
        s = ctx.snap
        if s is None:
            return None
        floor = ctx.params.p3_emergency_floor
        since = datetime.fromisoformat(entry["check_at"]) - timedelta(minutes=self.outcome_after_min)
        rescues = sum(1 for sh in ctx.history.shots if sh.start >= since and sh.kind.startswith("p3"))
        good = rescues == 0 and s.vwc >= floor + 1.0
        before = (entry.get("check") or {}).get("vwc")
        was = "" if before is None else f" (was {before:.1f})"
        what = (f"2 h after the day's watering stopped VWC {s.vwc:.1f}{was}, {_against(s.vwc, floor)} the "
                f"emergency floor {floor:.1f}, " + (f"{rescues} rescue shot(s)" if rescues else "no rescue shot"))
        return what, good
