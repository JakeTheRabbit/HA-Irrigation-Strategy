"""Every phase: is this zone's probe telling the truth?

A probe counts for the base engine if it gives an in-range number that changes. A probe pulled half out,
sitting in a channel, stuck on a value it keeps reporting, or wired to the wrong row passes all of that.
The test a person uses is the shots: water goes in, a working probe goes up and dries back down. This
judge reads each probe's answers to the shots against the zone's own typical rise and its siblings'.

Setting a probe aside needs three things: the council twice in a row, code's own confirmation (two
settled shots with almost no rise while a sibling rose, or a flat line for an hour with water going in),
and a fresh answer: when a later answer says the probe tracks, it counts again.
"""
from datetime import timedelta

from ..context import flat_minutes, response, trend, words_response, words_trend
from ..doctrine import doctrine
from .base import Judge, choice, common, noul, with_doctrine

MODES = {
    "healthy": "The probe answers the shots like a working probe: it rises when water goes in and dries back between shots.",
    "stuck": "The probe reads (almost) the same value whatever happens: it has stopped measuring.",
    "channeling": "Water runs past the probe: each shot spikes the reading and it falls straight back, while the slab around it behaves differently.",
    "not_in_block": "The probe barely responds to water at all, as if pulled out of the block or sitting in air.",
    "wrong_zone": "The probe responds to other zones' shots rather than this zone's, as if it is wired or mapped to another row.",
    "drifting": "The probe's level creeps in one direction regardless of shots and drying: calibration drift.",
    "temperature_artefact": "The reading moves with the slab's daily temperature (it jumps or bends when the lights switch), not with water.",
}

QUESTIONS = with_doctrine({
    "tracking": [
        noul("You are checking one irrigation zone's moisture probe. Judge only from the facts given. "
             "Doctrine: every shot of water should raise a working probe's reading and most of the rise "
             "should stay; between shots and overnight it should dry back slowly. Is this probe measuring "
             "the substrate?",
             "Yes: its answers to the shots and its drying look like a working probe.",
             "No: its answers to the shots do not look like a working probe."),
        noul("Would an experienced grower trust this probe to decide when this zone is watered? Compare its "
             "response to each shot with the zone's typical response and with the sibling zones watered at "
             "the same times.",
             "Yes, it can be trusted.",
             "No, it should not be trusted until it is checked."),
    ],
    "mode": [
        choice("If this probe is not working normally, which failure fits the facts best?", MODES),
        choice("Classify how this moisture probe is behaving.", MODES),
    ],
}, doctrine("probe") + " " + doctrine("closed_loop", limit=3))


class ProbeJudge(Judge):
    name = "probe"
    cadence_min = 30.0
    max_age_min = 90.0
    deciding = ("tracking",)  # `mode` only names the fault once `tracking` says the probe is off
    questions = QUESTIONS

    def due(self, ctx, last_asked):
        return super().due(ctx, last_asked) and len(ctx.history.shots) >= 2

    def _responses(self, ctx, hours=6):
        since = ctx.now - timedelta(hours=hours)
        return [response(ctx.history, sh, ctx.now) for sh in ctx.history.shots if sh.start >= since]

    def evidence(self, ctx):
        s, p = ctx.snap, ctx.params
        typical = ctx.typical_rise()
        rs = self._responses(ctx)[-6:]
        e = common(ctx)
        e.update({
            "probe": ctx.probe_entity or "this zone's moisture probe",
            "shot_responses_last_6h": [words_response(r, typical) for r in rs] or ["no shots in the last 6 hours"],
            "typical_retained_rise": "unknown" if typical is None else f"{typical:.2f} points per shot today",
            "minutes_reading_unchanged": flat_minutes(ctx.history, ctx.now),
            "moisture_last_hour": words_trend(trend(ctx.history, ctx.now, 60)),
            "moisture_vs_field_capacity": f"{s.vwc:.1f}% against a field capacity of {p.field_capacity:.1f}%",
            "minutes_since_the_lights_switched": (f"{ctx.since_lights_min} (lights "
                                                  f"{'on' if ctx.lights_on else 'off'})"),
            "pore_ec_last_hour": words_trend(trend(ctx.history, ctx.now, 60, index=2), "mS/cm", "pore EC"),
        })
        sib = {f"zone {z}": v.get("rise_words") for z, v in ctx.siblings.items() if v.get("rise_words")}
        if sib:
            e["sibling_zones_latest_shot"] = sib
        return e

    def decide(self, verdicts, ctx):
        t = verdicts.get("tracking")
        if t is None or not t.firm(0.7) or t.label is not False:
            return None
        m = verdicts.get("mode")
        mode = m.label if (m is not None and m.agreed and m.label != "healthy") else "untrusted"
        return self.directive(ctx, "distrust", mode, f"probe not tracking the substrate (p={t.prob:.2f}), {mode}")

    def evidence_ok(self, ctx):
        """Code's own check: two settled shots with almost no retained rise while a sibling rose, or a flat
        reading for an hour with a shot inside that hour."""
        rs = [r for r in self._responses(ctx) if r.settled and r.retained is not None]
        typical = ctx.typical_rise() or 0.5
        misses = [r for r in rs if r.retained < max(0.2, 0.25 * typical)]
        sibling_rose = any((v.get("rise") or 0) >= 0.5 for v in ctx.siblings.values())
        if len(misses) >= 2 and sibling_rose:
            return True
        flat = flat_minutes(ctx.history, ctx.now)
        watered = any(sh.start >= ctx.now - timedelta(minutes=flat) for sh in ctx.history.shots)
        return flat >= 60 and watered
