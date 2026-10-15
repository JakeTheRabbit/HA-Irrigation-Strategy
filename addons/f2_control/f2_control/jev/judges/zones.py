"""Why is one zone getting different water from its siblings?

The base engine flags a zone only below 40 % of the room's median litres, comparing zone totals rather
than water per plant, and only on the low side. Seen live (19-26 Sep 2026): zone 1 got 65 L a day against
126 and 106 on the same 42 plants, 61 % of the median, so it was never flagged; its learned settings had
drifted. This judge is asked whenever a zone's water per plant is under 70 % or over 140 % of the room's
median zone (the other zone, in a room of two), and says why.
"""
import statistics

from ..doctrine import doctrine
from .base import Judge, choice, common, with_doctrine

CAUSES = {
    "recipe_difference": "The zone's own settings (thresholds, shot size, targets) are simply different from its siblings', so it is watered differently on purpose.",
    "plants_drinking_less": "Its plants use less water (smaller, stressed, or a cooler spot): moisture falls slower, so it is watered less.",
    "plants_drinking_more": "Its plants use more water: moisture falls faster, so it is watered more.",
    "probe_wet_spot": "Its probe sits somewhere wetter than the rest of the slab, so it reads high and the zone is under-watered.",
    "probe_dry_spot": "Its probe sits somewhere drier than the rest of the slab, so it reads low and the zone is over-watered.",
    "delivery_fault": "A valve, dripper or line problem: the water counted is not what arrived.",
    "water_not_landing": "Shots go in but the moisture does not rise the way its siblings' does, so the engine keeps watering.",
    "insufficient_evidence": "The facts do not support any of the other answers.",
}

QUESTIONS = with_doctrine({
    "why_different": [
        choice("You are the head grower comparing irrigation zones in one room that should drink alike. "
               "Judge only from the facts given. This zone's water per plant today is very different from its "
               "siblings'. Doctrine: zones with the same plants and recipe should get similar water per plant; "
               "a probe reading high makes a zone thirsty-looking plants go without, a probe reading low "
               "floods them.", CAUSES),
        choice("Explain the most likely reason this zone's water per plant differs from the other zones in the "
               "room, using how fast its moisture falls, how it answers shots, and its settings compared with "
               "theirs.", CAUSES),
    ],
}, doctrine("probe", "maintenance", "slab"))

ALERT_CAUSES = {"plants_drinking_less", "plants_drinking_more", "probe_wet_spot", "probe_dry_spot",
                "delivery_fault", "water_not_landing"}


def _lpp(v):
    x = v.get("litres_per_plant")
    return float(x) if isinstance(x, (int, float)) else None


def water_vs_room(ctx):
    """-> (this zone's litres a plant today, what it is compared with, their ratio, that in words).

    The comparison is the median of every zone in the room, this one included, so one thirsty zone
    does not make its siblings look short (27 Sep 2026, the first live day: zone 1 had 2477 mL a plant
    and zones 2 and 3 about 1000, and zones 2 and 3 were flagged against zone 1's 2477). In a room of
    two zones neither is the odd one out, so each is compared with the other."""
    mine = ctx.snap.daily_vol / ctx.plants if ctx.plants and ctx.snap is not None else None
    others = [x for x in (_lpp(v) for v in ctx.siblings.values()) if x is not None]
    if mine is None or not others:
        return None, None, None, None
    if len(others) == 1:
        typical, basis = others[0], "the other zone"
    else:
        typical, basis = statistics.median(others + [mine]), "the room's median zone"
    if typical < 0.05:  # under 50 mL a plant so far: too early in the day to compare
        return mine, typical, None, basis
    return mine, typical, mine / typical, basis


class ZonesJudge(Judge):
    name = "zones"
    phases = ("P1", "P2")
    cadence_min = 60.0
    max_age_min = 90.0
    questions = QUESTIONS

    def _ratio(self, ctx):
        return water_vs_room(ctx)

    def due(self, ctx, last_asked):
        if not ctx.lights_on or not super().due(ctx, last_asked):
            return False
        ratio = self._ratio(ctx)[2]
        return ratio is not None and (ratio < 0.7 or ratio > 1.4)

    def evidence(self, ctx):
        s, p = ctx.snap, ctx.params
        mine, typical, ratio, basis = self._ratio(ctx)
        e = common(ctx)
        e.update({
            "water_per_plant_today": f"{mine * 1000:.0f} mL",
            "compared_with": f"{basis}: {typical * 1000:.0f} mL a plant",
            "share_of_that": f"{ratio * 100:.0f}%",
            "re_water_threshold": f"{p.p2_threshold:.1f}% VWC (shot size {p.p2_shot_size:.1f}% of the substrate)",
            "drying_rate": f"{s.dryback_rate:.2f} points an hour",
            "siblings": {f"zone {z}": {k: v[k] for k in ("litres_per_plant_words", "vwc_words", "threshold_words",
                                                         "rise_words") if v.get(k)}
                         for z, v in ctx.siblings.items()},
        })
        typical = ctx.typical_rise()
        if typical is not None:
            e["typical_retained_rise_per_shot"] = f"{typical:.2f} points"
        return e

    def decide(self, verdicts, ctx):
        v = verdicts.get("why_different")
        if v is None or not v.firm_in(ALERT_CAUSES, 0.6) or v.label not in ALERT_CAUSES:
            return None
        mine, typical, ratio, basis = self._ratio(ctx)
        if ratio is None:
            return None
        return self.directive(ctx, "alert", {
            "code": "CS-702",
            "title": "this zone's water per plant is out of line with the others",
            "message": (f"{ctx.title} has had {mine * 1000:.0f} mL a plant today, {ratio * 100:.0f}% of "
                        f"{basis} ({typical * 1000:.0f} mL). Jev's reading of why: "
                        f"{CAUSES[v.label]} Watering carries on as normal."),
        }, f"{v.label} (p={v.prob:.2f})")
