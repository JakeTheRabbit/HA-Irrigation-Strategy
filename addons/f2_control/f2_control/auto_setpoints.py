"""Auto setpoints: learn a zone from its own shots and keep that zone's targets attainable. Pure, no I/O.

The engine fires every shot by its own rules. This module only decides what the zone's SETPOINTS
should be, from how the probe actually behaved:

  * Every shot's RETAINED gain is recorded: the reading right before the next shot (or 20 minutes
    on), minus the reading before it. Minutes after a shot the probe still rides a free-water spike
    that takes tens of minutes to drain, so anything sooner reads runoff as gain. Retained gains teach
    the zone's gain, its dryback rates and its ceiling.
  * P1 always tries for a higher peak. When the last couple of ramp shots stop lifting VWC, the
    substrate is full: the P1 target drops to what the zone just achieved, so the engine's own
    "target reached" rule hands over to P2. That achieved peak is the P1 target from then on.
  * After a plateau the peak is held for a few days, then probed one point higher again. A ramp that
    reaches its target while still responding means tomorrow aims one point higher.
  * A "plateau" is only believed if the ramp really climbed and did not stall far under a peak the
    zone has held before. Anything else is a delivery or probe problem: nothing is learned, nothing
    is rewritten, and the reason is published.

`learn` is a plain JSON-safe dict so it persists in the controller's state file.
"""
import copy

import curve_tracker as ct
import setpoint_supervisor as ss

SETTLE_MIN = 20.0  # minutes before a shot's retained gain is read, unless the next shot arrives first
PLATEAU_SHOTS = 2  # "a couple of shots"
PLATEAU_RISE_PTS = 0.3  # a retained gain under this is no gain...
WEAK_FRACTION = 0.3  # ...and so is one under this share of what the zone's learned gain predicts
MIN_CLIMB_PTS = 2.0  # a believable ramp climbs at least this much before it flattens
SUSPECT_DROP_PTS = 3.0  # stalling this far under a known peak is not saturation
PROBE_STEP_PTS = 1.0  # how much higher to aim when probing for a better peak
HOLD_DAYS = 3  # days to hold a plateau peak before probing above it again
ALPHA = 0.3  # EWMA weight of a new sample
MIN_RATE_SAMPLES = 30  # quiet minutes a photoperiod (or night) must contribute before its mean counts
MIN_RATE_DAYS = 2  # such days needed per light state before the dryback rate is trusted
GAIN_HEADROOM_PTS = 2.0  # only ramp shots fired at least this far under the ceiling teach the gain
QUIET_MIN = 30.0  # minutes since a shot before a dryback reading is clean (drainage has finished)
DEFAULT_BAND_PTS = 1.5  # P2 band under the peak until the gain is known
MANAGED = ("p1_target_vwc", "field_capacity", "p2_vwc_threshold", "p3_emergency_vwc_threshold")

_NUMBERS = ("peak", "gain", "day_rate", "night_rate")


def fresh():
    return {"peak": None, "gain": None, "day_rate": None, "night_rate": None, "day_n": 0, "night_n": 0,
            "day_acc": [0.0, 0], "night_acc": [0.0, 0],
            "hold_days": 0, "day": None, "ramp_start": None, "ramp": [], "pending": None,
            "outcome": "pending", "stalled_at": None, "last_change": "", "prev_peak": None, "prev_hold": 0,
            "veto": None}


def restore(saved):
    """Saved dict -> a valid learn dict. Anything malformed falls back to fresh(): never crash the engine."""
    base = fresh()
    if not isinstance(saved, dict):
        return base
    try:
        out = copy.deepcopy({k: saved.get(k, v) for k, v in base.items()})
        for k in _NUMBERS + ("ramp_start", "stalled_at", "prev_peak"):
            if out[k] is not None:
                out[k] = float(out[k])
        for k in ("day_n", "night_n", "hold_days", "prev_hold"):
            out[k] = int(out[k])
        if not isinstance(out["ramp"], list) or not all(
            isinstance(r, dict) and {"pct", "rise", "settled"} <= set(r) for r in out["ramp"]
        ):
            return base
        if out["pending"] is not None and not {"t", "pre", "pct", "ramp"} <= set(out["pending"]):
            return base
        for k in ("day_acc", "night_acc"):
            out[k] = [float(out[k][0]), int(out[k][1])]
        return out
    except (TypeError, ValueError):
        return base


def _ewma(old, new):
    return new if old is None else old + ALPHA * (new - old)


def new_day(learn, grow_day, vwc):
    """Idempotent per grow-day: a fresh ramp record, and one day off any plateau hold."""
    if learn["day"] == grow_day:
        return
    learn.update(day=grow_day, ramp_start=vwc, ramp=[], pending=None, outcome="pending", stalled_at=None, veto=None)
    learn["hold_days"] = max(0, learn["hold_days"] - 1)
    for rate, n, acc in (("day_rate", "day_n", "day_acc"), ("night_rate", "night_n", "night_acc")):
        total, count = learn[acc]
        if count >= MIN_RATE_SAMPLES:  # yesterday's MEAN: transpiration swings through the day, so one
            learn[rate] = round(_ewma(learn[rate], total / count), 3)  # minute's rate says little
            learn[n] += 1
        learn[acc] = [0.0, 0]


def _flat(learn, rise, pct):
    expected = learn["gain"] * pct if learn["gain"] else 0.0
    return rise < max(PLATEAU_RISE_PTS, WEAK_FRACTION * expected)


def _settle(learn, vwc):
    """Close out the pending shot: what it RETAINED is this reading minus the one before it fired."""
    p, learn["pending"] = learn["pending"], None
    rise = vwc - p["pre"]
    flat = _flat(learn, rise, p["pct"])
    if p["ramp"]:
        learn["ramp"].append({"pct": p["pct"], "rise": round(rise, 2), "settled": round(vwc, 2), "flat": flat})
    # Gain is what a shot lifts a substrate that still has room. Near the ceiling (every P2 top-up, the end
    # of every ramp) most of the water runs off, and averaging those in shrinks the gain, which shrinks the
    # P2 band, which fires more near-ceiling shots: a runaway. Only roomy ramp shots teach it.
    roomy = learn["peak"] is None or p["pre"] < learn["peak"] - GAIN_HEADROOM_PTS
    if p["ramp"] and not flat and roomy and 0.05 <= rise / p["pct"] <= 3.0:
        learn["gain"] = round(_ewma(learn["gain"], rise / p["pct"]), 3)


def shot(learn, phase, size_pct, pre_vwc, ts):
    if pre_vwc is None or size_pct <= 0:
        return
    if learn["pending"]:  # the reading right before this shot is what the last one retained
        _settle(learn, pre_vwc)
    learn["pending"] = {"t": ts, "pre": pre_vwc, "pct": size_pct, "ramp": phase in ("P0", "P1")}


def tick(learn, vwc, phase, ts, lights_on, dryback_rate, minutes_since_shot):
    """Settle the last shot once it is old enough, and sample the dryback rate when the zone is quiet."""
    if learn["pending"] and ts - learn["pending"]["t"] >= SETTLE_MIN * 60.0:
        _settle(learn, vwc)
    if minutes_since_shot >= QUIET_MIN and dryback_rate and 0.02 <= dryback_rate <= 5.0:
        acc = learn["day_acc" if lights_on else "night_acc"]
        acc[0], acc[1] = acc[0] + dryback_rate, acc[1] + 1


def ramp_outcome(learn, phase):
    """pending | reached | short | plateau | suspect. Decided once per day; learning happens here."""
    if learn["outcome"] != "pending" or not learn["ramp"]:
        return learn["outcome"]
    ramp = learn["ramp"]
    top = max(r["settled"] for r in ramp)
    flat = len(ramp) >= PLATEAU_SHOTS and all(r.get("flat") for r in ramp[-PLATEAU_SHOTS:])
    if phase == "P1" and flat:
        climbed = top - (learn["ramp_start"] if learn["ramp_start"] is not None else top) >= MIN_CLIMB_PTS
        far_under = learn["peak"] is not None and top < learn["peak"] - SUSPECT_DROP_PTS
        if climbed and not far_under:
            learn.update(prev_peak=learn["peak"], prev_hold=learn["hold_days"])
            learn.update(outcome="plateau", peak=top, hold_days=HOLD_DAYS)
        else:
            learn.update(outcome="suspect", stalled_at=top)
    elif phase in ("P2", "P3"):  # the engine graduated the ramp itself
        if not ramp[-1].get("flat") and not flat:  # still taking water when the target was met
            learn.update(outcome="reached", peak=max(top, learn["peak"] or 0.0))  # a plateau hold stays in force
        else:
            learn["outcome"] = "short"
            if learn["peak"] is None or top > learn["peak"]:
                learn["peak"] = top
    return learn["outcome"]


def distrust(learn, why):
    """A guard (Jev) read today's plateau as a delivery or probe problem: forget it, keep the old ceiling."""
    if learn["outcome"] == "plateau":
        learn.update(outcome="suspect", stalled_at=learn["peak"], peak=learn["prev_peak"],
                     hold_days=learn["prev_hold"], veto=why)


def frozen_reason(learn):
    if learn["outcome"] != "suspect":
        return None
    if learn["veto"]:
        return f"today's plateau was not believed ({learn['veto']}): check delivery and the probe"
    if learn["peak"] is not None and learn["stalled_at"] is not None and learn["stalled_at"] < learn["peak"] - SUSPECT_DROP_PTS:
        return (f"ramp stalled at {learn['stalled_at']:.1f}%, {learn['peak'] - learn['stalled_at']:.1f} points under "
                f"the peak this zone has held ({learn['peak']:.1f}%): check delivery and the probe")
    return "ramp shots are not lifting VWC: water is not reaching this probe (check the dripper, line and probe)"


def p1_target(learn, vwc, phase):
    """The P1 target this zone should hold now, or None to leave the operator's value alone."""
    if phase == "P1":
        if learn["outcome"] == "plateau":  # fail over NOW: a target the zone has already met
            return round(min(learn["peak"], vwc) - 0.1, 1)
        return None  # never move the target under a ramp that is still climbing
    if learn["peak"] is None or learn["outcome"] == "suspect":
        return None
    return round(learn["peak"] + (PROBE_STEP_PTS if learn["hold_days"] == 0 else 0.0), 1)


def model(learn):
    """ZoneModel once the ceiling, gain and both dryback rates are learned; else None."""
    if None in (learn["peak"], learn["gain"], learn["day_rate"], learn["night_rate"]):
        return None
    if learn["day_n"] < MIN_RATE_DAYS or learn["night_n"] < MIN_RATE_DAYS:
        return None
    return ct.ZoneModel(knee=learn["peak"], gain=learn["gain"], day_rate=learn["day_rate"], night_rate=learn["night_rate"])


def wanted(learn, current, vwc, phase, plan_ctx):
    """suffix -> value this zone should hold now. {} until something has been learned.

    plan_ctx (optional, needs a complete model) adds the through-the-day schedule of the P2 threshold:
    {lights_on_h, lights_off_h, minutes_since_lights_on, shots_today, dryback_pct, p0_wait_min,
     p1_shot_pct, p1_gap_min, start_vwc}
    """
    target = p1_target(learn, vwc, phase)
    if target is None:
        return {}
    want = {"p1_target_vwc": target, "field_capacity": max(40.0, round(target + 2.0, 1))}
    m = model(learn)
    if m and plan_ctx:
        recipe = ct.Recipe(0.0, plan_ctx["dryback_pct"], plan_ctx["p0_wait_min"], plan_ctx["p1_shot_pct"],
                           plan_ctx["p1_gap_min"], current["p2_shot_size"])
        plan = ct.plan_day(m, recipe, plan_ctx["lights_on_h"], plan_ctx["lights_off_h"], plan_ctx["start_vwc"])
        d = ss.desired(m, recipe, plan, ss.Steer(current["p2_shot_size"]),
                       {"minutes_since_lights_on": plan_ctx["minutes_since_lights_on"],
                        "shots_today": plan_ctx["shots_today"], "feed_ec": 0.0}, ec_seen_max=0.0)
        want["p2_vwc_threshold"] = d["p2_vwc_threshold"]
    else:
        band = learn["gain"] * current["p2_shot_size"] if learn["gain"] else DEFAULT_BAND_PTS
        want["p2_vwc_threshold"] = round(learn["peak"] - band, 1)
    thr = want.get("p2_vwc_threshold", current["p2_vwc_threshold"])
    if current["p3_emergency_vwc_threshold"] + 3.0 > thr:  # only touched when it would invert the ladder
        want["p3_emergency_vwc_threshold"] = round(thr - 3.0, 1)
    return want


def status(learn, enabled):
    reason = frozen_reason(learn)
    state = "off" if not enabled else "frozen" if reason else "tracking" if model(learn) else "learning"
    return state, {
        "learned_peak": learn["peak"], "gain": learn["gain"], "day_rate": learn["day_rate"],
        "night_rate": learn["night_rate"], "p1_outcome": learn["outcome"], "hold_days": learn["hold_days"],
        "frozen_reason": reason, "last_change": learn["last_change"],
    }


def evidence(learn, phase, vwc, target, ec, ec_target, feed_ec, p2_shot, shots_today):
    """The situation for the judge (Jev), every comparison already made and put into words."""
    ramp = learn["ramp"]
    top = max([r["settled"] for r in ramp] + [vwc])
    reach = "reached the peak target" if top >= target - 0.3 else f"{target - top:.1f} points short of the peak target"
    normal = 0.5 * learn["gain"] if learn["gain"] else None
    responses = []
    for r in ramp[-4:]:
        ok = r["rise"] >= (normal * r["pct"] if normal else 1.0)
        responses.append(f"+{r['rise']:.1f} {'normal' if ok else 'weak'}")
    e = {"phase": phase, "peak_target": f"{target:.1f}% VWC", "highest_vwc_today": f"{top:.1f}% ({reach})",
         "vwc_now": f"{vwc:.1f}%", "shots_today": shots_today, "p2_shot_size_now": f"{p2_shot:.1f}%",
         "last_shot_responses": responses}
    held = max(learn["peak"] or 0.0, learn["prev_peak"] or 0.0)
    if held:
        e["highest_vwc_this_zone_has_held"] = f"{held:.1f}%"
    if ec is not None and ec_target:
        lo, hi = ec_target * 0.85, ec_target * 1.15
        where = "BELOW" if ec < lo else "ABOVE" if ec > hi else "INSIDE"
        e["pore_ec"] = f"{ec:.1f} mS/cm, {where} the stage range {lo:.1f} to {hi:.1f}"
        if feed_ec is not None:
            side, effect = ("lower", "lowers") if feed_ec < ec else ("higher", "raises")
            e["feed_ec"] = f"{feed_ec:.1f} mS/cm ({side} than pore EC, so runoff {effect} pore EC)"
    return e


def p1_ec_gate(ec, ec_target_p1, ec_target_p2):
    """The engine only leaves P1 on "target reached" once pore EC <= 1.15 x the P1 EC target; above that
    it keeps flushing at the ceiling until max shots. After a PLATEAU that flush is pure runoff, so a P1
    EC target stricter than the zone's own P2 target must not hold the hand-over. Returns the smallest P1
    EC target that lets it through, or None: never above the P2 target, because pore EC over THAT is
    genuinely high and the engine's flush is exactly what is wanted."""
    if ec is None or not ec_target_p1 or not ec_target_p2:
        return None
    need = round(ec / 1.15 + 0.05, 1)
    return need if ec_target_p1 < need <= ec_target_p2 else None
