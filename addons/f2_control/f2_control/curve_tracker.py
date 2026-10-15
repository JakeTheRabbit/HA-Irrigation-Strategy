"""Day planner + reference curve: the arithmetic behind "follow the Athena chart". Pure, no I/O.

The chart is arithmetic once four numbers are known per zone (learned from shot history): the
saturation knee, the VWC lift per 1% shot, and the lights-on / lights-off dryback rates. Everything
is RELATIVE to the zone's own knee, so a probe that reads 27 at saturation and one that reads 36 are
planned the same way.

  plan_day()   recipe + zone model -> today's attainable peak, band, timings and dryback
  reference()  the line the day should trace

Nothing here fires a shot or writes a setpoint: setpoint_supervisor turns a plan into engine setpoints.
"""
from dataclasses import dataclass

from crop_steering_engine.defaults import SUBSTRATE_PROFILES


@dataclass
class ZoneModel:
    knee: float  # VWC % where extra water stops raising the reading (field capacity, as THIS probe sees it)
    gain: float  # VWC points gained per 1% shot, below the knee
    day_rate: float  # dryback, points per hour, lights on (measure it fresh: light and VPD move it)
    night_rate: float  # dryback, points per hour, lights off


@dataclass
class Recipe:
    peak_offset: float  # peak VWC target relative to the knee: >0 forces runoff (veg), <=0 limits it (gen)
    dryback_pct: float  # overnight dryback target, RELATIVE % of the peak (Athena's convention)
    p1_delay_min: float  # planned first shot this long after lights-on ("transpiration before irrigation")
    p1_shot_pct: float
    p1_gap_min: float
    p2_shot_pct: float  # starting maintenance shot; EC steering moves it
    ec_range: tuple = (3.0, 6.0)  # pore EC band for the stage, mS/cm
    generative: bool = False  # the dryback may take maintenance shots from the middle of the day on


def curve(substrate="generic"):
    """The day planner's recipe per stage for a substrate (its profile's curve; generic when unknown). The
    profile's generative stages are the ones whose dryback may start from the middle of the day."""
    profile = SUBSTRATE_PROFILES.get(substrate, SUBSTRATE_PROFILES["generic"])
    return {
        stage: Recipe(*row, generative=stage in profile["generative_stages"])
        for stage, row in profile["curve"].items()
    }


def stage(recipe_stage, substrate="generic"):
    """A recipe stage (Veg, Transition, Bulk, Ripen) -> (curve stage, steered generatively), or (None, None)."""
    profile = SUBSTRATE_PROFILES.get(substrate, SUBSTRATE_PROFILES["generic"])
    name = profile["stage_map"].get(recipe_stage)
    return name, (None if name is None else name in profile["generative_stages"])


# The tuning surface. Athena's Precision Irrigation Strategy targets per growth stage (midpoints): stretch is
# generative (big dryback, small shots, stack EC), bulk vegetative (more runoff, lower EC), finish vegetative EC
# with a generative dryback. The generic substrate profile's curve.
ATHENA = curve()


@dataclass
class DayPlan:
    lights_on_h: float
    lights_off_h: float
    start_vwc: float
    peak: float
    p1_start_h: float
    p1_shots: int
    p1_end_h: float
    p2_lift: float
    p2_interval_min: float
    band: tuple
    p2_stop_h: float
    achievable_dryback_pct: float
    floor: float  # VWC the zone should reach by lights-on
    note: str
    day_rate: float
    night_rate: float


def plan_day(model, recipe, lights_on_h, lights_off_h, start_vwc):
    peak = model.knee + recipe.peak_offset
    gap_h = recipe.p1_gap_min / 60.0
    p1_start = lights_on_h + recipe.p1_delay_min / 60.0
    v0 = start_vwc - model.day_rate * recipe.p1_delay_min / 60.0
    lift, loss = model.gain * recipe.p1_shot_pct, model.day_rate * gap_h
    n = 1
    while v0 + n * lift - (n - 1) * loss < peak and n < 40:
        n += 1
    p1_end = p1_start + (n - 1) * gap_h

    p2_lift = model.gain * recipe.p2_shot_pct
    day_h = (lights_off_h - lights_on_h) % 24
    night_pts = model.night_rate * ((lights_on_h - lights_off_h) % 24)
    need = peak * recipe.dryback_pct / 100.0
    # Maintenance shots stop early enough for the night to finish the dryback, but only so early: the
    # dryback is set by adding or taking away P2 shots at the end of the day, never by dropping the whole
    # day. A vegetative day keeps them until its last 3 hours (where the engine's own early stop acts), a
    # generative one until the middle of the day, and P1 always runs in full. A dryback that needs more is
    # not chased: the zone gets the deepest one left, and says so.
    earliest = max((p1_end - lights_on_h) % 24, day_h / 2.0 if recipe.generative else day_h - 3.0)
    early_h = min(max(0.0, (need - night_pts) / model.day_rate), max(0.0, day_h - earliest))
    p2_stop, note = lights_on_h + day_h - early_h, ""
    achievable = (early_h * model.day_rate + night_pts) / peak * 100.0
    if achievable < recipe.dryback_pct - 0.01:
        note = (f"{recipe.dryback_pct:g}% dryback unreachable at this zone's uptake: about "
                f"{achievable:.0f}% tonight, with maintenance shots until {clock(p2_stop)}")
    floor = peak * (1.0 - min(recipe.dryback_pct, achievable) / 100.0)
    return DayPlan(
        lights_on_h, lights_off_h, start_vwc, peak, p1_start, n, p1_end, p2_lift,
        p2_lift / model.day_rate * 60.0, (round(peak - p2_lift, 2), peak), p2_stop, achievable, floor, note,
        model.day_rate, model.night_rate,
    )


def clock(hour):
    """A plan's clock hour, which may run past midnight (past 24), as "HH:MM"."""
    minutes = round(hour * 60) % 1440
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def reference(plan, h):
    """The planned line at clock hour h -> (phase, lo, hi)."""
    t = (h - plan.lights_on_h) % 24
    day_h = (plan.lights_off_h - plan.lights_on_h) % 24
    p1s, p1e, stop = (x - plan.lights_on_h for x in (plan.p1_start_h, plan.p1_end_h, plan.p2_stop_h))
    v0 = plan.start_vwc - plan.day_rate * p1s
    if t < p1s:
        v = plan.start_vwc - plan.day_rate * t
        return "P0", round(v - 0.5, 2), round(v + 0.5, 2)
    if t < p1e:
        v = v0 + (plan.peak - v0) * (t - p1s) / (p1e - p1s)
        return "P1", round(v - 1.0, 2), round(min(plan.peak, v + 1.0), 2)
    if t < stop:
        return "P2", plan.band[0], plan.band[1]
    v = plan.peak - plan.day_rate * (min(t, day_h) - stop) - plan.night_rate * max(0.0, t - day_h)
    return "P3", round(v - 1.0, 2), round(min(plan.peak, v + 0.5), 2)
