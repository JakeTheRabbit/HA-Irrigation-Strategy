"""Once a grow-day: is this zone steered the way the owner's stage arc says for today's day of flower?

The base engine has no idea what week of flower it is: the operator's steering mode and setpoints are all
it knows, and nothing notices when they belong to another stage, or when the overnight dryback and the
pore EC drift out of the stage's bands. This judge reads the zone against the owner's stage arc (the slab
guide he chose on 26 Sep 2026, jev.doctrine.STAGE_ARC) and says what is off, as advice (CS-705). It never
changes a setting: moving to a new stage is the grower's call.
"""
from datetime import timedelta

from ..doctrine import doctrine
from .base import Judge, choice, common, stage_words, with_doctrine

ARC = {
    "on_arc": "The zone's steering, overnight dryback and pore EC all fit today's stage.",
    "dryback_too_shallow": "Last night's dryback was smaller than the stage calls for.",
    "dryback_too_deep": "Last night's dryback was deeper than the stage calls for.",
    "ec_below_band": "The settled pore EC sits below the stage's EC band.",
    "ec_above_band": "The settled pore EC sits above the stage's EC band.",
    "move_on_signs": "The stage's own signs for moving on to the next stage are showing.",
    "insufficient_evidence": "The facts do not support any of the other answers.",
}

MISMATCH = "Switch the zone's steering mode to the stage's, or confirm the stage is wrong."

ADVICE = {
    "dryback_too_shallow": "Stop the day's watering a little earlier, or lower the overnight target, one change a day.",
    "dryback_too_deep": "Water a little later into the evening, or raise the overnight target, one change a day.",
    "ec_below_band": "Trim the maintenance shots or the day's peak rather than drying the slab deeper.",
    "ec_above_band": "Give more runoff: bigger or more maintenance shots, or a lower feed EC.",
    "move_on_signs": "Review whether the room has reached the next stage, and move its settings on if so.",
}

QUESTIONS = with_doctrine({
    "arc": [
        choice("You are the head grower checking one zone once a day against the owner's stage arc for today's "
               "day of flower. Judge only from the facts given. Compare last night's dryback with the stage's dryback band (both in points: the probe may read "
               "lower than true water content, so compare relative to the zone's own peak), and the settled pore "
               "EC with the stage's EC band. Say what fits worst, or that everything fits.", ARC),
        choice("Is this zone being steered the way today's stage of flower calls for? Look at how far the slab "
               "dried back overnight, and where the settled root-zone EC sits, against the "
               "stage's own targets. Pick the single most important thing that is off.", ARC),
    ],
}, doctrine("stage", "ripening", limit=5) + " " + doctrine("dryback", "ec", "closed_loop", limit=3))


def _overnight(ctx):
    """(dryback points, as % of the evening reading, evening reading) for the last night, or None."""
    if not ctx.lights_on:
        return None
    on_at = ctx.now - timedelta(minutes=ctx.since_lights_min)
    photoperiod_h = ctx.since_lights_min / 60.0 + ctx.hours_to_off  # this morning's on to tonight's off
    off_at = on_at - timedelta(hours=max(0.5, 24.0 - photoperiod_h))  # last night's lights-off
    evening = ctx.history.at(off_at, tolerance_min=20)
    night = [r[1] for r in ctx.history.readings if off_at <= r[0] <= on_at]
    if evening is None or not night:
        return None
    drop = evening[1] - min(night)
    return round(drop, 1), round(100.0 * drop / evening[1], 1) if evening[1] else None, evening[1]


class StageJudge(Judge):
    name = "stage"
    phases = ("P2",)
    cadence_min = 24 * 60.0
    max_age_min = 180.0
    questions = QUESTIONS

    def due(self, ctx, last_asked):
        return ctx.stage is not None and ctx.lights_on and super().due(ctx, last_asked)

    def evidence(self, ctx):
        s, p, st = ctx.snap, ctx.params, ctx.stage
        e = common(ctx)
        e["stage_today"] = stage_words(ctx)
        e["stage_steering_vs_operator"] = (f"the stage calls for {st['steering']} steering; the operator has the zone "
                                           f"on {ctx.steering or 'an unknown'} steering")
        night = _overnight(ctx)
        e["last_night_dryback"] = ("not enough readings from last night" if night is None else
                                   f"{night[0]:.1f} points on the probe ({night[1]:.1f}% of the evening reading "
                                   f"{night[2]:.1f}%); the stage calls for {st['dryback']}")
        ec = s.ec_settled
        lo, hi = st["pore_ec_range"]
        e["settled_pore_ec_vs_stage_band"] = (
            "no settled reading" if ec is None else
            f"{ec:.2f} mS/cm against the stage's band of {lo:g} to {hi:g}: "
            + ("inside" if lo <= ec <= hi else "below it" if ec < lo else "above it"))
        e["engine_targets"] = (f"re-waters under {p.p2_threshold:.1f}%, ramps to {min(p.p1_target, p.field_capacity):.1f}%, "
                               f"overnight target {p.dryback_target:.0f}% of the peak, maintenance EC target "
                               f"{p.ec_target_p2:.2f}")
        if ctx.plants:
            e["water_per_plant_today"] = f"{s.daily_vol / ctx.plants * 1000:.0f} mL so far"
        return e

    def decide(self, verdicts, ctx):
        st = ctx.stage
        if not st:
            return None
        # The steering mode against the stage is arithmetic, so code states it; Jev judges the rest.
        mismatch = bool(ctx.steering) and ctx.steering != st["steering"]
        v = verdicts.get("arc")
        judged = v is not None and v.firm_in(ADVICE, 0.6) and v.label in ADVICE
        if not (mismatch or judged):
            return None
        found = []
        if mismatch:
            found.append(f"The zone is on {ctx.steering} steering, but the stage calls for {st['steering']}. {MISMATCH}")
        if judged:
            found.append(f"Jev: {ARC[v.label]} Suggested: {ADVICE[v.label]}")
        why = ", ".join(x for x in ("steering mismatch" if mismatch else "",
                                    f"{v.label} (p={v.prob:.2f})" if judged else "") if x)
        return self.directive(ctx, "alert", {
            "code": "CS-705",
            "title": "this zone is off the stage's arc",
            "message": (f"{ctx.title} on flower day {ctx.flower_day} ({st['stage']}): {' '.join(found)} The owner's "
                        f"doctrine for this stage steers {st['steering']}, with a dryback of {st['dryback']} and "
                        f"{st['pore_ec']}. Nothing was changed."),
        }, why)
