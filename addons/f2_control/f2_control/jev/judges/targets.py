"""Setting a zone's targets itself: the targets judge, and the shot size judge beside it (docs/JEV.md, "Powers").

Asked once a grow-day, in the first 3 h after lights-off, on the Claude route. Code shows the zone's scorecard (how each
of the last few grow-days did against the goal of each phase), the AI assistant's own earlier changes with what
followed, and the settings now with each one's own range. The AI assistant answers with the values it wants
(set_values), each with its reason, the result it expects tomorrow and its confidence, or with none to keep them.

With the room's power on (set_targets_from_achievable, tune_shot_sizes) code writes the values as given: no limit
applies other than each setting's own range in Home Assistant, to which a value is clamped (and the clamp logged). The
AI assistant is trusted to follow the doctrine's goal and rules for these powers (the system prompt); code records
every change, with its reason and expected result, in the room's setpoint change log. With the power off (the
default) it advises: the decision log shows what it would set.
"""
from __future__ import annotations

import math

from ..doctrine import doctrine
from .base import Judge, common, with_doctrine

P1, FC, THR, RESCUE = "p1_target_vwc", "field_capacity", "p2_vwc_threshold", "p3_emergency_vwc_threshold"
VEG_DB, GEN_DB = "vegetative_dryback_target", "generative_dryback_target"
P1S, P2S = "p1_initial_shot_size", "p2_shot_size"
LADDER_KEYS = (FC, P1, THR, RESCUE)  # top to bottom
SCORE_DAYS = 5  # grow-days on the scorecard

MEANINGS = {
    FC: "field capacity: the moisture the slab holds when full (% VWC)",
    P1: "the peak target: where the morning ramp hands over to maintenance (% VWC)",
    THR: "the re-water point: maintenance shots fire when moisture falls under it (% VWC)",
    RESCUE: "the rescue floor: a P3 rescue shot fires under it at night (% VWC); the plants' safety net",
    VEG_DB: "the dryback target while steered vegetative (% of the peak)",
    GEN_DB: "the dryback target while steered generative (% of the peak)",
    P1S: "the first ramp shot (% of the substrate)",
    P2S: "a maintenance shot (% of the substrate)",
}


def values(instructions, keys):
    """A question answered with numbers (the set_values tool): `keys` are the settings it may set, with meanings."""
    return {"type": "values", "instructions": instructions, "criteria": dict(keys)}


TARGET_QUESTIONS = with_doctrine({
    "targets": [values(
        "You are the head grower setting one zone's targets for tomorrow yourself. The owner has given you this power: "
        "code writes the values you give as they are, clamped only to each setting's own range. Follow the goal and "
        "the rules for the owner's powers in your doctrine: keep the order rescue floor < re-water point < peak target "
        "<= field capacity with the doctrine's gaps, change gradually, never set a peak above what the zone reached on "
        "trusted days, move the rescue floor only with a clear reason, respect the steering mode and the grow plan. "
        "Judge from the scorecard and your earlier changes. Give only the settings you change, each with its reason "
        "and the result you expect tomorrow, or none to keep them.",
        {k: MEANINGS[k] for k in (FC, P1, THR, RESCUE, VEG_DB, GEN_DB)})],
}, doctrine("ramp", "dryback", "maintenance", limit=4))

SHOT_QUESTIONS = with_doctrine({
    "shot_sizes": [values(
        "You are the head grower sizing one zone's shots for tomorrow yourself. The owner has given you this power: "
        "code writes the values you give as they are, clamped only to each setting's own range. Follow the goal and "
        "the rules for the owner's powers in your doctrine: small ramp shots that each lift moisture a few points and "
        "hold, maintenance shots that refill the zone toward its peak without running to waste, gradual changes, one "
        "lever at a time. Judge from the scorecard, the shot response and your earlier changes. Give only the shot "
        "sizes you change, each with its reason and the result you expect tomorrow, or none to keep them.",
        {k: MEANINGS[k] for k in (P1S, P2S)})],
}, doctrine("ramp", "maintenance", limit=4))


def _f(v, unit=""):
    return "unknown" if v is None else f"{v:g}{unit}"


def scorecard_line(d):
    """One grow-day of a zone against each phase's goal, in words: hit or missed, and by how much."""
    parts = [str(d.get("day", "?"))]
    p0 = d.get("p0") or {}
    if p0.get("actual") is not None and p0.get("target"):
        parts.append(f"P0 dryback {p0['actual']:.1f}% at the ramp's start against a {p0['target']:g}% target "
                     f"({'hit' if p0.get('hit') else 'missed by ' + format(p0['actual'] - p0['target'], '+.1f')})")
    p1 = d.get("p1") or {}
    if p1.get("target") is not None:
        top = p1.get("top")
        parts.append(f"P1 peak {_f(top, '%')} against the {p1['target']:g}% target"
                     + (f" in {p1['shots']} shots" if p1.get("shots") else "")
                     + (" (hit)" if p1.get("hit") else f" (missed by {top - p1['target']:+.1f})" if top else " (missed)"))
    p2 = d.get("p2") or {}
    if p2.get("ec") is not None and p2.get("band"):
        lo, hi = p2["band"]
        off = 0.0 if lo <= p2["ec"] <= hi else (p2["ec"] - lo if p2["ec"] < lo else p2["ec"] - hi)
        parts.append(f"P2 pore EC {p2['ec']:.2f} against the stage's {lo:g}-{hi:g} "
                     + ("(hit)" if off == 0.0 else f"(missed by {off:+.2f})"))
    p3 = d.get("p3") or {}
    if p3.get("rescues") is not None:
        parts.append("P3 no rescue shot (hit)" if not p3["rescues"] else f"P3 {p3['rescues']} rescue shot(s) (missed)")
    u = d.get("uniformity") or {}
    if u.get("ratio") is not None:
        parts.append(f"water per plant {u['ratio'] * 100:.0f}% of the room's typical zone "
                     + ("(hit)" if u.get("hit") else "(missed)"))
    parts.append("probe trusted" if d.get("trusted") else f"probe NOT trusted ({d.get('why') or 'no trusted reading'})")
    return "; ".join(parts)


def hits(d):
    """(goals hit, goals missed) on a grow-day's record."""
    keys = [d.get(k) or {} for k in ("p0", "p1", "p2", "p3", "uniformity")]
    out = [k.get("hit") for k in keys if k.get("hit") is not None]
    return sum(1 for h in out if h), sum(1 for h in out if not h)


def change_line(change, after):
    """One of the AI assistant's earlier changes, what it expected, and what followed (the next grow-day's card)."""
    moves = ", ".join(f"{k} {o:g} -> {n:g}" for k, (o, n) in (change.get("values") or {}).items())
    return (f"{change.get('day')}: you set {moves or 'nothing'}; you expected: {change.get('expected') or 'not said'}"
            + (f"; what followed: {scorecard_line(after)}" if after else "; what followed: not measured yet"))


class TargetsJudge(Judge):
    """The zone's ladder and dryback targets, as the AI assistant sets them (power set_targets_from_achievable)."""
    name = "targets"
    phases = ("P3",)
    cadence_min = 12 * 60.0  # once a night
    max_age_min = 180.0
    outcome_after_min = 24 * 60.0  # the next night, against the next grow-day's card
    questions = TARGET_QUESTIONS
    question = "targets"
    kind = "targets"
    view_attr = "targets"

    def _view(self, ctx):
        return getattr(ctx, self.view_attr, None) or {}

    def due(self, ctx, last_asked):
        v = self._view(ctx)
        if not v.get("current") or v.get("changed_today"):
            return False
        if ctx.lights_on or ctx.since_lights_min > 180:  # the first three hours of the night
            return False
        return super().due(ctx, last_asked)

    def questions_for(self, ctx):
        """The question with this zone's settings only, each with its value now and its own range."""
        v = self._view(ctx)
        crit = {}
        for k, cur in (v.get("current") or {}).items():
            lo, hi = (v.get("limits") or {}).get(k, (None, None))
            crit[k] = f"{MEANINGS[k]}; now {cur:g}" + (f", its range {lo:g}-{hi:g}" if lo is not None else "")
        return {q: [dict(x, criteria=crit) for x in variants] for q, variants in self.questions.items()}

    def evidence(self, ctx):
        v = self._view(ctx)
        e = common(ctx)
        days = (v.get("days") or [])[-SCORE_DAYS:]
        e["goal"] = ("each grow-day: P0 reaches the stage's dryback by the ramp's start; P1 reaches the peak target in "
                     "a sensible number of shots; P2 holds between the re-water point and the peak with pore EC in the "
                     "stage band; P3 dries back overnight as the stage wants with no rescue shot; the room's zones "
                     "drink alike")
        e["scorecard"] = [scorecard_line(d) for d in days] or ["no grow-day recorded yet"]
        by_day = {d.get("day"): d for d in v.get("days") or []}
        days_sorted = sorted(by_day)
        e["your_earlier_changes"] = [
            change_line(c, by_day.get(next((x for x in days_sorted if x > str(c.get("day"))), None)))
            for c in (v.get("changes") or [])[-5:]] or ["none yet"]
        e["settings_now"] = {k: f"{cur:g}" for k, cur in (v.get("current") or {}).items()}
        if v.get("plan"):
            e["grow_plan"] = v["plan"]
        e["your_power"] = ("on: code writes what you set, clamped only to each setting's own range" if v.get("power")
                           else "off: what you set is shown to the owner as advice and not written")
        return e

    def decide(self, verdicts, ctx):
        """The values the AI assistant set, as one directive; none set (keep) is no directive."""
        v = verdicts.get(self.question)
        allowed = self._view(ctx).get("current") or {}
        if v is None or v.kind != "values":
            return None
        chosen = {k: x for k, x in (v.values or {}).items() if k in allowed}
        if not chosen:
            return None
        return self.directive(ctx, self.kind, {
            "values": {k: x["value"] for k, x in chosen.items()},
            "reasons": {k: x.get("reason", "") for k, x in chosen.items()},
            "expected": v.expected or "", "confidence": v.confidence, "choice": "set",
            "words": ", ".join(f"{k} {float(allowed[k]):g} -> {x['value']:g}" for k, x in chosen.items()),
        }, f"set (confidence {v.confidence:.2f})")

    def outcome(self, entry, ctx):
        """The next night: how the next grow-day did against its goals."""
        days = self._view(ctx).get("days") or []
        if not days or str(days[-1].get("day")) <= str(entry.get("at", ""))[:10]:
            return None
        hit, missed = hits(days[-1])
        return f"the grow-day after: {scorecard_line(days[-1])}", hit >= missed


class ShotSizeJudge(TargetsJudge):
    """The zone's ramp and maintenance shot sizes, as the AI assistant sets them (power tune_shot_sizes)."""
    name = "shotsize"
    questions = SHOT_QUESTIONS
    question = "shot_sizes"
    kind = "shot_size"
    view_attr = "shots"

    def evidence(self, ctx):
        e = super().evidence(ctx)
        v = self._view(ctx)
        e["shot_response"] = (f"each percent of shot keeps about {v['gain']:.2f} points (learned from ramp shots)"
                              if v.get("gain") else "not measured yet")
        return e


def finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
