"""Setpoint supervisor: keeps a zone's targets ATTAINABLE and moves them through the day so the engine's
own shots trace the reference curve. It never fires a shot - it only proposes setpoint writes. Pure, no I/O.

Why setpoints have to move during the day (from the engine's actual rules):
  * P0 is skipped whenever VWC <= the P2 threshold. After any real overnight dryback that is always
    true, so "transpiration before irrigation" never happens. Holding the threshold BELOW the zone
    overnight and through P0 gives a real P0, which then ends on Athena's 1-5% additional dryback
    (the engine measures P0 dryback from the lights-on reading) or on the wait timeout.
  * P1 only graduates at its target. A target above what the probe can read burns every ramp shot
    into runoff, so the target follows the zone's own saturation knee.
  * P2 tops up under its threshold until lights-off. Dropping the threshold at the planned stop time
    is what starts the dryback early enough to land the overnight target.

Arithmetic (knee, band, stop time, attainable dryback) is done here. Judgement is asked of a `judge`
(Jev): is the probe believable, is water landing, which way should pore EC be steered, does the peak
target fit what the ramp is showing. Any judge failure leaves the arithmetic in charge.
"""
from dataclasses import dataclass

import curve_tracker as ct

ADDITIONAL_DRYBACK_PCT = 3.0  # Athena: 1-5% further dryback after lights-on before the first shot
P2_SHOT_RANGE = (1.0, 4.0)  # the EC lever: bigger shots force runoff and lower pore EC, smaller shots stack it
PEAK_ADJ_RANGE = (-2.0, 2.0)  # how far judgement may move the peak off the learned knee
MAX_STEP = {"p1_target_vwc": 6.0, "field_capacity": 20.0, "p2_vwc_threshold": 10.0,
            "p3_emergency_vwc_threshold": 10.0, "dryback_target": 15.0}
BOUNDS = {  # the engine's own _PARAM_BOUNDS, by setpoint suffix
    "p1_target_vwc": (20, 85), "p2_vwc_threshold": (10, 70), "field_capacity": (40, 90), "dryback_target": (2, 60),
    "p0_maximum_wait_time": (5, 240), "p3_emergency_vwc_threshold": (10, 60), "p2_shot_size": (0.5, 20),
    "p1_initial_shot_size": (0.5, 15), "p1_shot_size_increment": (0, 5), "p1_maximum_shots": (1, 40),
    "p1_time_between_shots": (1, 120), "ec_target_p1": (0.5, 9), "ec_target_p2": (0.5, 9),
}


@dataclass
class Steer:
    """What judgement has moved, on top of the arithmetic."""
    p2_shot: float
    peak_adj: float = 0.0


def attainable_ec_target(ec_range, feed_ec, ec_seen_max):
    """Middle of the stage range, but never below what the feed makes possible nor far above anything seen."""
    mid = (ec_range[0] + ec_range[1]) / 2.0
    return round(max(feed_ec + 0.5, min(mid, ec_seen_max + 0.5)), 1)


def desired(model, recipe, plan, steer, ctx, ec_seen_max):
    """The setpoints this zone should hold RIGHT NOW: attainable, and scheduled by where the day is."""
    peak = plan.peak + steer.peak_adj
    low = round(plan.floor - 2.0, 1)  # a threshold the zone sits above: no P0 bypass, no top-ups
    band_lo = round(peak - model.gain * steer.p2_shot, 1)
    mins_on = ctx.get("minutes_since_lights_on")
    before_first_shot = ctx["shots_today"] == 0
    drying = mins_on is None or mins_on >= (plan.p2_stop_h - plan.lights_on_h) % 24 * 60.0
    watering = not drying and not before_first_shot
    ec_t = attainable_ec_target(recipe.ec_range, ctx["feed_ec"], ec_seen_max)
    overnight = round(min(recipe.dryback_pct, plan.achievable_dryback_pct), 1)
    return {
        "p1_target_vwc": round(peak, 1),
        "field_capacity": max(40.0, round(peak + 2.0, 1)),
        "p2_vwc_threshold": band_lo if watering else low,
        "p3_emergency_vwc_threshold": max(10.0, round(plan.floor - 5.0, 1)),
        "dryback_target": ADDITIONAL_DRYBACK_PCT if (before_first_shot and not drying) else overnight,
        "p0_maximum_wait_time": float(recipe.p1_delay_min),
        "p1_initial_shot_size": recipe.p1_shot_pct,
        "p1_shot_size_increment": 0.0,  # Athena's ramp is even 2-6% shots, not an escalating series
        "p1_maximum_shots": float(plan.p1_shots + 3),
        "p1_time_between_shots": float(recipe.p1_gap_min),
        "p2_shot_size": steer.p2_shot,
        "ec_target_p1": ec_t,  # P1 can only graduate once pore EC is within 15% of this, so it must be reachable
        "ec_target_p2": ec_t,
    }


def writes(current, want):
    """current + desired -> [(suffix, value, why)], clamped to the engine's bounds, big moves taken in steps."""
    out = []
    for suffix, target in want.items():
        cur = current.get(suffix)
        lo, hi = BOUNDS.get(suffix, (-1e9, 1e9))
        target = max(lo, min(hi, target))
        if cur is not None and suffix in MAX_STEP:
            target = max(cur - MAX_STEP[suffix], min(cur + MAX_STEP[suffix], target))
        if suffix == "field_capacity":  # while a too-high P1 target is still stepping down, stay above it
            target = max(target, dict((s, v) for s, v, _w in out).get("p1_target_vwc", current.get("p1_target_vwc", 0)))
        target = round(target, 1)
        if cur is None or abs(target - cur) >= 0.05:
            out.append((suffix, target, f"{suffix} {cur} -> {target}"))
    merged = dict(current, **{s: v for s, v, _w in out})
    ok = (merged["p3_emergency_vwc_threshold"] + 3 <= merged["p2_vwc_threshold"]
          < merged["p1_target_vwc"] <= merged["field_capacity"])
    return out if ok else []  # never hand the engine an inverted VWC ladder


def evidence(model, recipe, plan, steer, ctx, ec_trend_24h=None, light_note=None):
    """The situation for the judge, every comparison already made and put into words."""
    lo, hi = recipe.ec_range
    ec = ctx["ec"]
    where = "BELOW" if ec < lo else "ABOVE" if ec > hi else "INSIDE"
    peak = plan.peak + steer.peak_adj
    top = ctx["peak_today"]
    reach = "reached the peak target" if top >= peak - 0.3 else f"{peak - top:.1f} points short of the peak target"
    expect = model.gain * recipe.p1_shot_pct
    e = {
        "phase": ctx["phase"],
        "pore_ec": f"{ec:.1f} mS/cm, {where} the stage range {lo:.1f} to {hi:.1f}",
        "feed_ec": f"{ctx['feed_ec']:.1f} mS/cm ({'lower' if ctx['feed_ec'] < ec else 'higher'} than pore EC, "
                   f"so runoff {'lowers' if ctx['feed_ec'] < ec else 'raises'} pore EC)",
        "runoff_today": f"{ctx['runoff_today']:.1f} points of water drained past saturation",
        "p2_shot_size_now": f"{steer.p2_shot:.1f}% (allowed {P2_SHOT_RANGE[0]:.0f} to {P2_SHOT_RANGE[1]:.0f}%)",
        "peak_target": f"{peak:.1f}% VWC",
        "highest_vwc_today": f"{top:.1f}% ({reach})",
        "shots_today": ctx["shots_today"],
        "last_shot_responses": [f"+{r:.1f} {'normal' if r >= 0.5 * expect else 'weak'}" for r in ctx["responses"]],
    }
    if ec_trend_24h is not None:
        e["pore_ec_trend_24h"] = f"{ec_trend_24h:+.1f} mS/cm ({'rising' if ec_trend_24h > 0.1 else 'falling' if ec_trend_24h < -0.1 else 'steady'})"
    if light_note:
        e["light_today"] = light_note
    return e


class Supervisor:
    """Callable for engine_twin.run (and later the add-on loop): ctx -> [(suffix, value, why)]."""

    def __init__(self, model, recipe, lights_on_h, lights_off_h, ec_seen_max, judge=None, judge_every_min=60):
        self.model, self.recipe, self.on, self.off = model, recipe, lights_on_h, lights_off_h
        self.ec_seen_max, self.judge, self.judge_every = ec_seen_max, judge, judge_every_min
        self.steer = Steer(p2_shot=recipe.p2_shot_pct)
        self.plan, self.log, self._ec_yesterday, self._nudged = None, [], {}, set()

    def __call__(self, ctx):
        mins = ctx.get("minutes_since_lights_on")
        if self.plan is None or mins == 0:  # a fresh plan at every lights-on, from that morning's real VWC
            self.plan = ct.plan_day(self.model, self.recipe, self.on, self.off, start_vwc=ctx["vwc"])
            self._nudged = set()
        if self.judge and mins and mins % self.judge_every == 0:
            before = self._ec_yesterday.get(mins)  # same time yesterday -> a 24 h pore-EC trend
            self._ec_yesterday[mins] = ctx["ec"]
            verdict = self.judge(evidence(self.model, self.recipe, self.plan, self.steer, ctx,
                                          ec_trend_24h=None if before is None else ctx["ec"] - before,
                                          light_note=ctx.get("light_note")))
            self.log.append((round(ctx["clock_h"], 2), verdict))
            if verdict and verdict.get("freeze"):
                return []  # a guard tripped: leave every setpoint exactly where it is
            if verdict:  # ONE nudge per lever per photoperiod: pore EC and the knee answer over a day, not an hour
                if verdict.get("p2_shot_delta") and "ec" not in self._nudged:
                    lo, hi = P2_SHOT_RANGE
                    self.steer.p2_shot = round(max(lo, min(hi, self.steer.p2_shot + verdict["p2_shot_delta"])), 1)
                    self._nudged.add("ec")
                if verdict.get("peak_delta") and "peak" not in self._nudged:
                    lo, hi = PEAK_ADJ_RANGE
                    self.steer.peak_adj = round(max(lo, min(hi, self.steer.peak_adj + verdict["peak_delta"])), 1)
                    self._nudged.add("peak")
        want = desired(self.model, self.recipe, self.plan, self.steer, ctx, self.ec_seen_max)
        return writes(ctx["setpoints"], want)
