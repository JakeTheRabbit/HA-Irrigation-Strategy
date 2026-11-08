"""The plan follows the probe: a zone's VWC offset on an armed grow plan, from the peaks the zone reaches. Pure, no I/O.

F1, 9 Nov 2026: a probe was reseated and from then on read about 15 points lower (peaks 76 -> about 53). The plan
kept a P1 target of 61 and a P2 threshold of 54 that the zone could never reach, so it sat under P2 all day and was
overwatered for 10 days. While a plan runs, Auto setpoints and the AI assistant's targets judge leave its targets
alone, so nothing caught it.

The peaks are the follower's (controller._count_peak, _keep_day_peak): the highest trusted reading of each grow-day,
kept at lights-on. Here the last DAYS of them are kept as well, and a grow-day with a step change in the probe's
reading (a 0.0, or a jump of more than JUMP_PTS in about a minute or across a blind gap) starts the count again, so
the offset is only ever moved on clean days after the probe settled.

`rec` is a plain JSON-safe dict, kept in the controller's state file.
"""
import math
import statistics

DAYS = 3  # clean grow-days of peaks the rule needs, all of them saying the same
UNREACHABLE_PTS = 4.0  # the plan's P1 target this far over every peak: the zone cannot reach it
OVERSHOOT_PTS = 3.0  # every peak this far over the plan's field capacity: the plan is set under the zone
HEADROOM_PTS = 1.0  # field capacity is put this far over the median peak
STEP_MAX_PTS = 3.0  # the offset moves at most this far a grow-day
OFFSET_MAX = 20.0  # the integration's bound (strategy_model.OFFSET_MAX)
JUMP_PTS = 10.0  # a reading this far from the one before...
JUMP_S = 120.0  # ...this soon after it, or after a blind gap, is a step change


def fresh():
    return {"days": [], "step": False, "last": None, "gap": False, "checked": None}


def _pct(v):
    return (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            and 0.0 < v <= 100.0 else None)


def restore(saved):
    """Saved dict -> a valid record; anything malformed is a fresh one (an old state file has none)."""
    out = fresh()
    if not isinstance(saved, dict):
        return out
    days = saved.get("days")
    if isinstance(days, list):
        out["days"] = [{"day": d["day"], "peak": _pct(d.get("peak"))} for d in days
                       if isinstance(d, dict) and isinstance(d.get("day"), str) and _pct(d.get("peak"))][-DAYS:]
    out["step"] = saved.get("step") is True
    out["gap"] = saved.get("gap") is True
    last = saved.get("last")
    if (isinstance(last, list) and len(last) == 2 and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                                                          for x in last)):
        out["last"] = [float(last[0]), float(last[1])]
    out["checked"] = saved.get("checked") if isinstance(saved.get("checked"), str) else None
    return out


def reading(rec, vwc, ts):
    """A trusted reading at epoch seconds `ts`: marks the grow-day as a step change when it is one."""
    last = rec["last"]
    if vwc <= 0.0:
        rec["step"] = True
    elif last is not None and abs(vwc - last[0]) > JUMP_PTS and (rec["gap"] or ts - last[1] <= JUMP_S):
        rec["step"] = True
    rec["last"], rec["gap"] = [float(vwc), float(ts)], False


def blind(rec):
    """The zone has no trusted reading this pass: the next one is compared across the gap."""
    rec["gap"] = True


def close_day(rec, day, peak):
    """Lights-on: the grow-day `day` that ended, with the follower's counted `peak` for it. A step change day, or
    one without a counted peak (blind all day, a CS-310 day), starts the count again."""
    peak = _pct(peak)
    if rec["step"] or peak is None:
        rec["days"] = []
    else:
        rec["days"] = (rec["days"] + [{"day": day, "peak": round(peak, 2)}])[-DAYS:]
    rec["step"] = False


def decide(days, p1, fc, base_fc, offset):
    """-> {"offset", "why", "median", "goal", "peaks"} for the offset to set, or None to leave it.

    `p1`, `fc`: the plan's P1 target and field capacity in force (the offset included); `base_fc`: its field capacity
    before the offset; `offset`: the zone's offset now. The plan is out of step with the probe when, on every one of
    the last DAYS clean grow-days, the P1 target sat more than UNREACHABLE_PTS over the peak ("unreachable"), or the
    peak more than OVERSHOOT_PTS over field capacity ("overshoot"). The offset then moves towards the one that puts
    field capacity HEADROOM_PTS over the median peak, at most STEP_MAX_PTS a grow-day."""
    if len(days) < DAYS:
        return None
    peaks = [d["peak"] for d in days[-DAYS:]]
    if all(p1 - x > UNREACHABLE_PTS for x in peaks):
        why = "unreachable"
    elif all(x - fc > OVERSHOOT_PTS for x in peaks):
        why = "overshoot"
    else:
        return None
    median = statistics.median(peaks)
    goal = round(median + HEADROOM_PTS - base_fc, 1)
    move = max(-STEP_MAX_PTS, min(STEP_MAX_PTS, goal - offset))
    new = round(max(-OFFSET_MAX, min(OFFSET_MAX, offset + move)), 1)
    if abs(new - offset) < 0.05:
        return None
    return {"offset": new, "why": why, "median": round(median, 2), "goal": goal, "peaks": peaks}
