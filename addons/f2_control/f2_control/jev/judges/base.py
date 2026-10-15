"""What every judge is: when it is asked, what it is shown, what it is asked, and what its answer may do."""
from __future__ import annotations

from datetime import timedelta

from ..envelope import Directive


def choice(instructions, criteria):
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


def noul(instructions, true, false):
    return {"type": "noul", "instructions": instructions, "criteria": {"true": true, "false": false}}


def score(instructions, criteria):
    return {"type": "score", "instructions": instructions, "criteria": list(criteria)}


def with_doctrine(questions, text):
    """Every phrasing of every question, with the owner's doctrine (jev.doctrine) appended: Jev knows
    none of its own, so each question carries the rules it is to judge by."""
    return {name: [dict(v, instructions=f"{v['instructions']} {text}") for v in variants]
            for name, variants in questions.items()}


def stage_words(ctx):
    """The day's place on the owner's stage arc, in one sentence, or None."""
    st = ctx.stage
    if not st:
        return None
    lo, hi = st["days"]
    return (f"flower day {ctx.flower_day} of about {ctx.flower_days}: {st['stage']} (days {lo}-{hi}), where the "
            f"owner's doctrine steers {st['steering']}, with a dryback of {st['dryback']}, {st['pore_ec']} and "
            f"runoff {st['runoff']}; the stage moves on when {st['move_on_when']}")


class Judge:
    name = "judge"
    phases = ("P0", "P1", "P2", "P3")  # the phases it may be asked in
    cadence_min = 30.0  # asked at most this often per zone
    max_age_min = 45.0  # an answer older than this is not acted on
    needs_probe = True  # asked only while the zone has a usable probe
    outcome_after_min = None  # when set, an admitted directive is checked this long after
    questions: dict = {}  # {question: [phrasing, phrasing]}
    deciding: tuple = ()  # the questions decide() rests on, for the second look and the stricter gate; () = all

    def due(self, ctx, last_asked):
        if ctx.phase not in self.phases or (self.needs_probe and ctx.snap is None):
            return False
        return last_asked is None or (ctx.now - last_asked) >= timedelta(minutes=self.cadence_min)

    def evidence(self, ctx) -> dict:
        raise NotImplementedError

    def decide(self, verdicts, ctx):
        """verdicts: {question: council.Verdict or None} -> a Directive or None."""
        return None

    def evidence_ok(self, ctx) -> bool:
        """Code's own confirmation, for directives the envelope wants it for (setting a probe aside)."""
        return True

    def outcome(self, entry, ctx):
        """(what happened, good?) for a ledger entry whose check is due, or None to wait."""
        return None

    def more_evidence(self, ctx, verdicts) -> dict:
        """What a second look adds when the last answer was unsure: that answer, and the sibling zones. A judge with
        more to show (the last few days, the doctrine) adds to it."""
        return {
            "why_again": "your last answer was unsure, or your two readings of it disagreed: look again with this",
            "your_last_answer": {q: {"answer": v.label, "p": v.prob, "agreed": v.agreed}
                                 for q, v in verdicts.items() if v is not None},
            "sibling_zones": dict(ctx.siblings or {}),
        }

    def directive(self, ctx, kind, value, why):
        return Directive(self.name, kind, value, why, ctx.now + timedelta(minutes=self.max_age_min))


def common(ctx) -> dict:
    """The facts every judge starts from."""
    s, p = ctx.snap, ctx.params
    e = {
        "zone": ctx.title,
        "phase": ctx.phase,
        "lights": "on" if ctx.lights_on else "off",
        "hours_to_lights_off": round(ctx.hours_to_off, 1),
        "hours_to_lights_on": round(ctx.hours_to_on, 1),
    }
    if s is not None:
        e["vwc_now"] = f"{s.vwc:.1f}%"
        ec = s.ec_settled if s.ec_settled is not None else s.ec
        e["pore_ec_now"] = "unknown" if ec is None else f"{ec:.2f} mS/cm"
        e["shots_today"] = s.shot_count
        e["water_today"] = f"{s.daily_vol:.1f} L of a {p.max_daily_volume:.0f} L daily limit"
    if ctx.feed_ec is not None:
        e["feed_ec"] = f"{ctx.feed_ec:.2f} mS/cm"
    stage = stage_words(ctx)
    e["stage_today"] = stage or ("flower day not known" if ctx.flower_day is None
                                 else f"flower day {ctx.flower_day}: outside the owner's stage arc")
    if ctx.steering:
        e["operator_steering_mode"] = ctx.steering
    return e
