"""P1: is the morning ramp done?

The base engine ends P1 when VWC reaches the ceiling AND pore EC is within 15 % of the P1 target, or at
the maximum shots. Seen live (23 Sep 2026): during a ramp the fresh feed passing the probe lifts pore EC
30-65 %, the EC gate never passes, and "flush" shots burn the day's budget by 13:00. A person looking at
the curve knows when the slab is full and the EC is just the feed going by. So does this judge.
"""
from ..context import response, trend, words_response, words_trend
from ..doctrine import doctrine
from .base import Judge, choice, common, with_doctrine

STATES = {
    "keep_ramping": "The slab is still taking water: each ramp shot still lifts moisture that stays. Keep ramping.",
    "slab_full": "The slab is full: the last shots barely lifted moisture that stays, or it spiked and fell straight back, and moisture is at or near the ramp ceiling. Hand over to maintenance.",
    "ec_is_feed_front": "Moisture has reached the ceiling and the only thing holding the ramp open is pore EC, which is up because fresh feed is passing the probe right after the shots, not because salt is building. Hand over to maintenance.",
    "real_salt": "Pore EC is genuinely high and not falling after the shots: salt is built up. The ramp only refills the slab; salt leaves in the runoff of the maintenance shots once the slab is full, so hand over and let maintenance flush it.",
    "probe_lagging": "The probe has not caught up with the last shot yet (it reads late): wait before judging.",
    "insufficient_evidence": "The facts do not support any of the other answers.",
}

HANDOVER = ("slab_full", "ec_is_feed_front", "real_salt")  # answers that all mean: hand over

QUESTIONS = with_doctrine({
    "ramp_state": [
        choice("You are the head grower watching one zone's morning ramp (P1) of rockwool or coco irrigation. "
               "Judge only from the facts given. Doctrine: a ramp is done when the slab is full, meaning "
               "shots no longer raise the moisture that stays; pore EC read in the first 45 minutes after a "
               "shot is the fresh feed passing the probe, not the slab.", STATES),
        choice("Decide what this zone's ramp should do next. The ramp's job is to bring the substrate up to "
               "full after the night's dryback. A shot that spikes the reading and then drops back means the "
               "water ran through. EC that rose right after shots with feed EC below it is feed passing by, "
               "and falls again as the slab settles.", STATES),
    ],
}, doctrine("ramp", "probe", "ec", limit=4))


class RampJudge(Judge):
    name = "ramp"
    phases = ("P1",)
    cadence_min = 15.0
    max_age_min = 25.0
    outcome_after_min = 60.0
    questions = QUESTIONS

    def due(self, ctx, last_asked):
        if not super().due(ctx, last_asked):
            return False
        s = ctx.snap
        return s.shot_count >= 1 and s.minutes_since_shot >= 10.0  # a shot to judge, past its spike

    def evidence(self, ctx):
        s, p = ctx.snap, ctx.params
        ceiling = min(p.p1_target, p.field_capacity)
        typical = ctx.typical_rise()
        ramp = [sh for sh in ctx.history.shots if sh.kind.startswith("p1")][-6:]
        ec = s.ec_settled if s.ec_settled is not None else s.ec
        e = common(ctx)
        e.update({
            "ramp_ceiling": f"{ceiling:.1f}% ({'reached' if s.vwc >= ceiling else f'{ceiling - s.vwc:.1f} points to go'})",
            "ramp_shots": f"{s.shot_count} of at most {p.p1_max_shots} (minimum {p.p1_min_shots})",
            "minutes_since_last_shot": round(s.minutes_since_shot),
            "ramp_shot_responses": [words_response(response(ctx.history, sh, ctx.now), typical) for sh in ramp]
            or ["none recorded yet"],
            "moisture_last_30_min": words_trend(trend(ctx.history, ctx.now, 30)),
            "pore_ec_vs_ramp_target": ("unknown" if ec is None else
                                       f"{ec:.2f} against a ramp target of {p.ec_target_p1:.2f} "
                                       f"(the base engine waits for {p.ec_target_p1 * 1.15:.2f} or less)"),
            "pore_ec_last_hour": words_trend(trend(ctx.history, ctx.now, 60, index=2), "mS/cm", "pore EC"),
        })
        if ctx.feed_ec is not None and ec is not None:
            e["feed_vs_pore_ec"] = ("feed is lower than pore EC, so water through the slab lowers it"
                                    if ctx.feed_ec < ec else "feed is not lower than pore EC")
        return e

    def decide(self, verdicts, ctx):
        v = verdicts.get("ramp_state")
        if v is None or not v.firm_in(HANDOVER, 0.6):
            return None
        p = sum(v.probabilities.get(k, 0.0) for k in HANDOVER)
        return self.directive(ctx, "advance", "P2", f"ramp done: {v.label} (hand over p={p:.2f})")

    def outcome(self, entry, ctx):
        s = ctx.snap
        if s is None:
            return None
        before = (entry.get("check") or {}).get("vwc")
        held = s.vwc >= ctx.params.p2_threshold - 0.5
        what = (f"after the hand-over VWC {s.vwc:.1f} (was {before:.1f}), "
                f"{'held above' if held else 'fell under'} the maintenance threshold {ctx.params.p2_threshold:.1f}"
                if before is not None else f"VWC {s.vwc:.1f} an hour after the hand-over")
        return what, held
