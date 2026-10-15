"""Tomorrow's maintenance watering, one notch at a time: the Setpoints judge (docs/JEV.md).

Asked once a grow-day, early in the night, when the day's water, shots and pore EC are complete. Jev chooses one
change to the zone's P2 maintenance watering for tomorrow, or none. Code turns the choice into one notch on one of
the zone's own numbers, inside a band around the operator's own value:

- the P2 shot size, 0.5 % a notch, at most 1 % either side of the operator's value and never under 3 %;
- the P2 re-water threshold, 0.5 points a notch, from 2 points under to 1 point over the operator's value, always
  4 points above the rescue floor and 2 under the ramp's ceiling.

Why this shape (26 Sep 2026): the old learner walked zone 1's shot from 3 % to 1 % one step a day (30-second
shots every 96 seconds) and ratcheted zone 3's targets to 74.5 in four days. A band anchored on the operator's
value can't ratchet, the floor stops machine-gun shots, the operator's own edits move the band (jev_bridge), and a
rescue shot after a change puts the old value back and pauses the zone for two days. Nothing moves unless the
room's Auto setpoints switch is on.
"""
from __future__ import annotations

from datetime import timedelta

from ..doctrine import doctrine
from .base import Judge, choice, common, with_doctrine
from .zones import water_vs_room

SHOT, THRESHOLD = "p2_shot_size", "p2_vwc_threshold"
STEP = 0.5
SHOT_FLOOR = 3.0  # percent of the substrate: below it the engine's EC scaling makes machine-gun shots
MAINTENANCE = ("p2_topup", "p2_dilute", "p2_rescue")
LESS_WATER = ("smaller_shots", "later_rewater")
MORE_WATER = ("bigger_shots", "sooner_rewater")

MOVES = {
    "smaller_shots": (SHOT, -STEP),
    "bigger_shots": (SHOT, +STEP),
    "later_rewater": (THRESHOLD, -STEP),
    "sooner_rewater": (THRESHOLD, +STEP),
}

CHOICES = {
    "smaller_shots": "Smaller maintenance shots tomorrow: the same rhythm, less water each time, so less runs to "
                     "waste and pore EC can build.",
    "bigger_shots": "Bigger maintenance shots tomorrow: the same rhythm, more water each time, so more runs off "
                    "and pore EC falls.",
    "later_rewater": "Let the zone dry a little further before each maintenance shot tomorrow: fewer shots and a "
                     "deeper dryback between them.",
    "sooner_rewater": "Re-water a little sooner tomorrow: more shots and a shallower dryback between them.",
    "keep": "Keep tomorrow's maintenance watering as it is: the zone did what its stage asks today.",
    "insufficient_evidence": "The facts don't support any change.",
}

LEVERS = ("How the levers work: bigger maintenance shots push more runoff and lower pore EC, smaller ones cut "
          "runoff and let EC build (EC stacking); adding maintenance shots late in the day makes the overnight "
          "dryback smaller (vegetative), removing them makes it larger (generative). Change one thing at a time.")

QUESTIONS = with_doctrine({
    "tomorrow": [
        choice("You are the head grower setting tomorrow's maintenance (P2) watering for one irrigation zone, one "
               "small step at a time. Judge only from the facts given: today's water per plant against the room, "
               "the zone's shots and how the probe answered them, pore EC against the stage's range, and the "
               f"stage and steering the zone is on. {LEVERS} Pick the single change that best serves the plants "
               "tomorrow, or keep.", CHOICES),
        choice("Looking at how this zone was watered today and where its pore EC and moisture ended up, which one "
               "adjustment to tomorrow's maintenance shots would move it closer to what its stage of flower asks "
               f"for? {LEVERS} Choose keep when it is already on course.", CHOICES),
    ],
}, doctrine("maintenance", "ec"))


def band(suffix, home, params):
    """(lo, hi) that notches may reach for `suffix` around the operator's value `home`; lo > hi means none."""
    if suffix == SHOT:
        return max(SHOT_FLOOR, home - 1.0), home + 1.0
    lo = max(home - 2.0, params.p3_emergency_floor + 4.0)
    hi = min(home + 1.0, min(params.p1_target, params.field_capacity) - 2.0)
    return lo, hi


def words(suffix, frm, to):
    if suffix == SHOT:
        return f"P2 shot {frm:g}% -> {to:g}%"
    return f"re-water under {frm:g}% -> {to:g}%"


def day_start(ctx):
    """When today's lights came on."""
    if ctx.lights_on:
        return ctx.now - timedelta(minutes=ctx.since_lights_min)
    night_h = ctx.hours_to_on + ctx.since_lights_min / 60.0  # minutes since lights-off + hours to lights-on
    return ctx.now - timedelta(minutes=ctx.since_lights_min) - timedelta(hours=24.0 - night_h)


class SetpointsJudge(Judge):
    name = "setpoints"
    phases = ("P3",)
    cadence_min = 12 * 60.0  # once a night
    max_age_min = 180.0
    outcome_after_min = 24 * 60.0  # the next night, after a full day on the new setting
    questions = QUESTIONS

    def due(self, ctx, last_asked):
        sp = ctx.setpoints or {}
        if not sp.get("enabled") or sp.get("frozen") or sp.get("changed_today") or not sp.get("current"):
            return False
        if ctx.lights_on or ctx.since_lights_min > 180:  # the first three hours of the night
            return False
        return super().due(ctx, last_asked)

    def evidence(self, ctx):
        s, sp = ctx.snap, ctx.setpoints or {}
        e = common(ctx)
        mine, typical, ratio, basis = water_vs_room(ctx)
        if ratio is not None:
            e["water_per_plant_today"] = (f"{mine * 1000:.0f} mL, {ratio * 100:.0f}% of {basis} "
                                          f"({typical * 1000:.0f} mL)")
            if ratio > 1.4:
                e["water_calls_for"] = "less water a day: this zone drank far more than the room's typical zone"
            elif ratio < 0.7:
                e["water_calls_for"] = "more water a day: this zone got far less than the room's typical zone"
        start = day_start(ctx)
        today = [sh for sh in ctx.history.shots if sh.start >= start]
        e["shots_today"] = len(today)  # every shot since lights-on (the engine's counter is per phase)
        maint = [sh for sh in today if sh.kind in MAINTENANCE]
        e["maintenance_shots_today"] = (
            "none" if not maint else
            f"{len(maint)}, {sum(sh.litres for sh in maint):.1f} L in all, about {sum(sh.seconds for sh in maint) / len(maint):.0f} s each")
        if len(maint) >= 2:
            gaps = sorted((b.start - a.start).total_seconds() / 60.0 for a, b in zip(maint, maint[1:]))
            e["time_between_maintenance_shots"] = f"about {gaps[len(gaps) // 2]:.0f} min"
        typical_rise = ctx.typical_rise()
        if typical_rise is not None:
            e["typical_retained_rise_per_shot"] = f"{typical_rise:.2f} points"
        sib = {f"zone {z}": v["rise_words"] for z, v in ctx.siblings.items() if v.get("rise_words")}
        if sib:
            e["sibling_zones_latest_shot"] = sib
        first = next((r for r in ctx.history.readings if r[0] >= start and r[2] is not None), None)
        ec_now = None if s is None else (s.ec_settled if s.ec_settled is not None else s.ec)
        stage = ctx.stage or {}
        lo_hi = stage.get("pore_ec_range")
        if ec_now is not None:
            day = "" if first is None else f"from {first[2]:.2f} at lights-on to "
            rng = "" if not lo_hi else f"; the stage asks {lo_hi[0]:g}-{lo_hi[1]:g}"
            e["pore_ec_today"] = f"{day}{ec_now:.2f} mS/cm now{rng}"
            if lo_hi:  # the lever's direction is doctrine, not judgement (Athena: EC up = smaller shots)
                if ec_now < lo_hi[0]:
                    e["pore_ec_calls_for"] = ("less runoff: pore EC is under the stage's range, and it rises when "
                                              "shots are smaller or fewer")
                elif ec_now > lo_hi[1]:
                    e["pore_ec_calls_for"] = ("more runoff: pore EC is over the stage's range, and it falls when "
                                              "shots are bigger")
                else:
                    e["pore_ec_calls_for"] = "nothing: pore EC is inside the stage's range"
        # a rescue or the lights-on watchdog means the zone ran short; the minimum-daily floor fires routinely from
        # lights-on, so it is not a safety event
        rescues = [sh for sh in today if sh.kind in ("p3_emergency", "watchdog")]
        e["safety_shots_today"] = "none" if not rescues else ", ".join(f"{sh.kind} at {sh.start:%H:%M}" for sh in rescues)
        settings = []
        for suffix, label in ((SHOT, "P2 shot size"), (THRESHOLD, "re-waters under")):
            cur = (sp.get("current") or {}).get(suffix)
            if cur is None:
                continue
            home = (sp.get("home") or {}).get(suffix, cur)
            lo, hi = (sp.get("bands") or {}).get(suffix, (cur, cur))
            unit = "%" if suffix == SHOT else "% VWC"
            edge = " (at the bottom of its range)" if cur <= lo + 1e-9 else " (at the top of its range)" if cur >= hi - 1e-9 else ""
            settings.append(f"{label} {cur:g}{unit}{edge}; your value {home:g}, may move {lo:g}-{hi:g}")
        e["settings_now"] = settings
        if sp.get("last_words"):
            e["last_change"] = sp["last_words"]
        return e

    def decide(self, verdicts, ctx):
        """Both phrasings must pick the same lever. It acts when that lever alone, or its direction (less or more
        water), holds 60 %: live, zone 1's heavy day read smaller shots 0.47 with the rest mostly on re-watering
        later, a firm "less water" with the lever agreed. Split between two levers, nothing moves."""
        v = verdicts.get("tomorrow")
        if v is None or v.label not in MOVES:
            return None
        direction = LESS_WATER if v.label in LESS_WATER else MORE_WATER
        if not (v.firm(0.6) or (v.agreed and v.firm_in(direction, 0.6))):
            return None
        suffix, step = MOVES[v.label]
        cur = ((ctx.setpoints or {}).get("current") or {}).get(suffix)
        if cur is None:
            return None
        to = round(cur + step, 2)
        return self.directive(ctx, "setpoint", {
            "suffix": suffix, "from": cur, "to": to, "choice": v.label, "words": words(suffix, cur, to),
        }, f"{v.label} (p={v.prob:.2f})")

    def outcome(self, entry, ctx):
        """A day later: did the zone's water move the way the change meant, or its pore EC toward the stage?"""
        s = ctx.snap
        if s is None:
            return None
        check = entry.get("check") or {}
        before, after = check.get("daily_vol"), s.daily_vol
        ec0, ec1 = check.get("ec"), (s.ec_settled if s.ec_settled is not None else s.ec)
        less = entry.get("label") in LESS_WATER
        water_ok = before is not None and after is not None and ((after < before) if less else (after > before))
        rng = (ctx.stage or {}).get("pore_ec_range")
        ec_ok, ec_words = False, ""
        if rng and ec0 is not None and ec1 is not None:
            lo, hi = rng

            def gap(x):
                return max(lo - x, 0.0, x - hi)
            ec_ok = gap(ec1) < gap(ec0) - 0.05 or gap(ec0) == gap(ec1) == 0.0
            ec_words = f", pore EC {ec0:.2f} -> {ec1:.2f} (stage {lo:g}-{hi:g})"
        what = (f"a day after '{str(entry.get('label')).replace('_', ' ')}': water "
                f"{before if before is None else f'{before:.0f}'} -> {after:.0f} L{ec_words}")
        return what, bool(water_ok or ec_ok)
