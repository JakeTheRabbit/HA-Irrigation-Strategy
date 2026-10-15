"""The only things Jev can cause, and the code that admits or refuses each one.

A judge turns Jev's answer into a `Directive`. `admit()` then checks it against arithmetic Jev can't do
and limits Jev can't cross: the daily order of the phases, how far into a phase the zone is, the P3
emergency floor, the ramp's minimum shots, the evidence needed to set a probe aside, the notch budget on
the setpoints. A refused directive does nothing; the base engine decides as it always has.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from crop_steering_engine import p0_dryback

ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
NEXT = {"P0": "P1", "P1": "P2", "P2": "P3"}
FLAT_MIN = 30.0  # a probe reading unchanged this long can't show a dryback: the P0 timer decides

# The notch budget: how far a setting may move, every notch added up, however the band moves under it.
NOTCH_24H = 0.5  # in any 24 h: one notch
NOTCH_7D = 1.0  # in any 7 days: two notches
COOL_DOWN_H = 36.0  # no notch this long after a refused move or one that did not work out: the next night is skipped
BUDGET = "notch budget"  # how the budget's refusals start
MOVE_REFUSALS = ("not a setting", "one notch at a time", "is outside its range")  # the move itself was wrong


@dataclass(frozen=True)
class Directive:
    judge: str
    kind: str  # "advance" | "distrust" | "ec_mode" | "setpoint" | "alert" | "push"
    value: object  # the phase to go to, an EC mode, a setpoint move dict, an alert dict, True/False for a push
    why: str
    expires: datetime


def _p1_ceiling(p):
    return min(p.p1_target, p.field_capacity)


def _flat_minutes(ctx, tolerance=0.05):
    """How long the zone's VWC has read the same value (within `tolerance` points), in minutes; 0 with no
    history. The same count as context.flat_minutes, kept here so the envelope stands on its own."""
    pts = list(getattr(getattr(ctx, "history", None), "readings", None) or ())
    if not pts:
        return 0.0
    start, last = pts[-1][0], pts[-1][1]
    for t, v, *_ in reversed(pts):
        if abs(v - last) > tolerance:
            break
        start = t
    return (ctx.now - start).total_seconds() / 60.0


def admit(d: Directive, ctx, confirmed=0, evidence_ok=False):
    """(True, why) when code lets `d` act on this pass, else (False, why). `confirmed` is how many
    agreeing verdicts in a row stand behind it; `evidence_ok` is the judge's own code-checked evidence."""
    if ctx.now > d.expires:
        return False, "expired"
    snap, p = ctx.snap, ctx.params
    if d.kind == "advance":
        target = d.value
        if NEXT.get(ctx.phase) != target:
            return False, f"only {ctx.phase} -> {NEXT.get(ctx.phase)} may be brought forward"
        if snap is None:
            return False, "no usable probe: phases wait for the base engine"
        if not ctx.lights_on:
            return False, "lights off: the base engine owns the night"
        if target == "P1":
            half = p0_dryback(p) / 2.0
            quarter = p.p0_max_wait_min / 4.0
            if snap.dryback_pct < half and snap.phase_minutes < quarter:
                return False, (f"dryback {snap.dryback_pct:.1f}% under half the target ({half:.1f}%) "
                               f"and only {snap.phase_minutes:.0f} of {p.p0_max_wait_min:.0f} min waited")
            flat = _flat_minutes(ctx)
            if flat >= FLAT_MIN:
                return False, f"the probe reading has not moved for {flat:.0f} min: the P0 timer decides"
            return True, "P0 far enough along"
        if target == "P2":
            if snap.shot_count < max(1, p.p1_min_shots):
                return False, f"only {snap.shot_count} ramp shots in (minimum {max(1, p.p1_min_shots)})"
            ceiling = _p1_ceiling(p)
            if snap.vwc < ceiling - 3.0:
                return False, f"VWC {snap.vwc:.1f} more than 3 points under the ramp ceiling {ceiling:.1f}"
            return True, "ramp near its ceiling with the minimum shots in"
        if target == "P3":
            steering = ctx.steering or ((ctx.stage or {}).get("steering"))
            if steering != "generative":
                return False, (f"the zone is steered {steering or 'with no mode set'}, not generative: an early "
                               "stop is advice only")
            if ctx.hours_to_off > 3.0:
                return False, f"{ctx.hours_to_off:.1f} h to lights-off: only the last 3 h"
            if snap.vwc < p.p3_emergency_floor + 3.0:
                return False, (f"VWC {snap.vwc:.1f} within 3 points of the P3 emergency floor "
                               f"{p.p3_emergency_floor:.1f}")
            return True, "in the last 3 h with room above the emergency floor"
        return False, "unknown phase"
    if d.kind == "distrust":
        if confirmed < 2:
            return False, f"{confirmed} agreeing verdict(s) in a row; 2 needed"
        if not evidence_ok:
            return False, "code has not confirmed it (no shot without a rise while a sibling rose, no flat line)"
        return True, "council twice in a row, confirmed by code"
    if d.kind == "ec_mode":
        if d.value not in ("steer", "hold", "decay"):
            return False, "unknown EC mode"
        if ctx.phase != "P2":
            return False, "the EC steer runs in P2"
        return True, "the EC steer stays inside its own clamp"
    if d.kind == "setpoint":
        return _admit_setpoint(d, ctx)
    if d.kind in ("alert", "push"):
        return True, "alerts never move water"
    return False, "unknown directive"


def _admit_setpoint(d, ctx):
    """One notch on one of the zone's own numbers, inside the band around the operator's value, at most once a
    grow-day, only with the room's Auto setpoints switch on, never while the zone is paused after a revert, and
    within the notch budget (notch_budget)."""
    sp = getattr(ctx, "setpoints", None) or {}
    v = d.value if isinstance(d.value, dict) else {}
    suffix, frm, to = v.get("suffix"), v.get("from"), v.get("to")
    if not sp.get("enabled"):
        return False, "Auto setpoints is off for this room (or a grow plan owns it)"
    if sp.get("frozen"):
        return False, f"paused after a safety revert until {sp['frozen'][:16].replace('T', ' ')}"
    if sp.get("changed_today"):
        return False, "one change per zone per grow-day"
    band = (sp.get("bands") or {}).get(suffix)
    cur = (sp.get("current") or {}).get(suffix)
    if band is None or cur is None or frm is None or to is None:
        return False, "not a setting Jev may move on this zone"
    if abs(float(frm) - float(cur)) > 1e-6:
        return False, f"the setting changed since Jev was asked ({frm:g} -> {cur:g})"
    if abs(float(to) - float(frm)) > 0.5 + 1e-9 or to == frm:
        return False, "one notch at a time"
    lo, hi = band
    if not lo - 1e-9 <= float(to) <= hi + 1e-9:
        return False, f"{to:g} is outside its range {lo:g}-{hi:g} around your value"
    spent = notch_budget(sp, suffix, ctx.now, abs(float(to) - float(frm)))
    if spent:
        return False, spent
    return True, "one notch inside its range around your value"


def notch_budget(sp, suffix, now, step=0.5):
    """Why a notch of `step` on `suffix` may not be made at `now`, or None. `sp["setbacks"]` holds when a move was
    refused or did not work out, `sp["notches"]` the (at, suffix, step) moves made (jev_bridge reads both from the
    ledger); either may be missing."""
    for at in sp.get("setbacks") or ():
        until = at + timedelta(hours=COOL_DOWN_H)
        if until > now:
            return f"{BUDGET}: resting until {until:%Y-%m-%d %H:%M} after a change was refused or did not work out"
    for hours, cap, span in ((24, NOTCH_24H, "24 h"), (24 * 7, NOTCH_7D, "7 days")):
        used = sum(abs(n) for at, s, n in sp.get("notches") or () if s == suffix and now - at < timedelta(hours=hours))
        if used + step > cap + 1e-9:
            return f"{BUDGET}: {used:g} already moved in {span} (at most {cap:g})"
    return None


def cools_down(why):
    """True when a refused setpoint move starts the cool-down: the move itself was wrong, not its timing (the
    switch, a pause, today's change, the budget) and not an edit by hand made while Jev was asked."""
    return any(r in why for r in MOVE_REFUSALS)
