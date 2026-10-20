"""P1: is the morning ramp done?

The engine ends P1 on its settled-rise test, a below-target stall, the extra-shot cap, the budget at target,
or maximum shots. Pore EC does not hold the ramp open. This judge can recognise a full or stalled substrate
sooner, within the envelope's minimum-shot and trusted-probe guards.
"""
from datetime import timedelta

from crop_steering_engine.core import p1_rise, p1_stall

from ..context import response, trend, words_response, words_trend
from ..doctrine import doctrine
from .base import Judge, choice, common, with_doctrine

STATES = {
    "keep_ramping": "The slab is still taking water: each ramp shot still lifts moisture that stays. Keep ramping.",
    "slab_full": "The slab is full: the last shots barely lifted moisture that stays, or it spiked and fell straight back, and moisture is at or near the ramp ceiling. Hand over to maintenance.",
    "ec_is_feed_front": "Moisture has reached the ceiling; pore EC is up because fresh feed is passing the probe after the shots, not because salt is building. Hand over to maintenance.",
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


def stalling(ctx):
    """True when the zone's last ramp shot under its ceiling did not give the rise P1 needs (core.p1_stall) and code
    does not doubt the probe."""
    s, p = ctx.snap, ctx.params
    if s is None or s.vwc >= min(p.p1_target, p.field_capacity) or s.backed_up or s.p1_probe_suspect:
        return False
    return p.p1_stall_shots > 0 and p1_stall(s, p) >= 1


class RampJudge(Judge):
    name = "ramp"
    phases = ("P1",)
    cadence_min = 15.0
    max_age_min = 25.0
    outcome_after_min = 60.0
    questions = QUESTIONS

    def due(self, ctx, last_asked):
        s = ctx.snap
        if ctx.phase in self.phases and s is not None and s.minutes_since_shot >= 10.0 and stalling(ctx):
            # A ramp shot that did not rise: asked once about it, whatever the cadence. Hand over now, or let the
            # engine give the one more shot after which it ends P1 itself (core.p1_stall).
            return last_asked is None or ctx.now - last_asked >= timedelta(minutes=s.minutes_since_shot)
        if not super().due(ctx, last_asked):
            return False
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
                                       f"{ec:.2f} against a ramp target of {p.ec_target_p1:.2f}; "
                                       "pore EC does not gate the engine's P1 exit"),
            "pore_ec_last_hour": words_trend(trend(ctx.history, ctx.now, 60, index=2), "mS/cm", "pore EC"),
        })
        if stalling(ctx):
            rise, need = p1_rise(s, p)
            e["ramp_stall"] = (f"the last {p1_stall(s, p)} ramp shot(s) in a row raised the settled moisture by less "
                               f"than {need:.2f} points (the last one {rise:+.2f}), {ceiling - s.vwc:.1f} points under "
                               f"the ceiling; code ends the ramp after {p.p1_stall_shots} such shots: hand over now, "
                               "or let it give one more")
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
