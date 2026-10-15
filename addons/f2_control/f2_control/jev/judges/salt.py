"""P2: why is pore EC where it is, and should the EC steer chase it?

Every 30 minutes in P2 the base engine moves the re-water threshold on pore EC against its target: above
the band it waters sooner (wetter, more runoff, dilutes), below it lets the slab dry deeper (stacks). It
cannot tell WHY pore EC is off. Two live cases it got wrong:

- 26 Sep 2026, F2 zone 2: pore EC rose 4.4 -> 7.1 across three hand flushes. An assistant blamed the
  probe and said stop flushing; the owner's rule is the opposite: EC going up after flush water went in is
  the salt front still passing the probe, and the slab needs MORE flushing.
- The same day, F2 zone 1: a target of 6.0 against a pore EC of 2.55 that never moved. Three mechanisms
  each shrank the shots on that low reading, and the zone got 30-second shots every 96 s.

This judge asks what is driving pore EC and picks the steer's mode: steer (the base steer carries on),
hold (keep the offset where it is) or decay (let it fall back to none). The envelope admits it only in P2,
and only inside the clamp the base steer already has.
"""
from datetime import timedelta

from ..context import trend, words_trend
from ..doctrine import doctrine
from .base import Judge, choice, common, with_doctrine

BAND = 0.10  # the steer leaves pore EC alone within 10 % of its target (controller._step_ec_offset)
SETTLE_MIN = 45.0  # pore EC read sooner than this after a shot is the feed passing (engine EC_SETTLE_MIN)
FLUSHES = ("flush_high_ec", "p0_ec_flush", "p1_flush", "p2_dilute", "p2_rescue")

CAUSES = {
    "salts_accumulating": "Pore EC is climbing through the day while the feed is lower than it: salt is building in the slab. Steer wetter.",
    "salt_front_passing": "Pore EC went up after flush water went in: the salt front is still passing the probe and the slab needs more flushing. Keep flushing: steer wetter.",
    "feed_changed": "Pore EC is following a change in the feed EC, not a change in the slab: hold the steer where it is.",
    "probe_suspect": "The pore EC readings jump, or disagree with how the moisture behaves: the EC reading is not to be trusted. Let the steer decay.",
    "target_unreachable": "The target pore EC is far from anything the feed and this slab have reached: chasing it only shrinks or stretches the shots. Let the steer decay.",
    "in_band": "Pore EC is inside the band around its target and steady: hold the steer.",
    "below_band_vegetative": "Pore EC is below its band, but the stage steers vegetative with a small dryback: drying the slab deeper to stack EC would fight the stage. Hold the steer; trimming the maintenance shots is the grower's lever here.",
}

MODE = {
    "salts_accumulating": "steer", "salt_front_passing": "steer",
    "feed_changed": "hold", "in_band": "hold",
    "probe_suspect": "decay", "target_unreachable": "decay",
    "below_band_vegetative": "hold",
}

QUESTIONS = with_doctrine({
    "salt_cause": [
        choice("You are the head grower reading one zone's pore EC during maintenance (P2) of rockwool or coco "
               "irrigation. Judge only from the facts given. Doctrine: pore EC read within 45 minutes of a shot "
               "is the fresh feed passing the probe, not the slab. When pore EC goes UP after flush water went "
               "in, the salt front is still passing the probe and the slab needs MORE flushing; that is not a "
               "probe fault. Bigger, wetter maintenance gives more runoff and moves pore EC toward the feed EC; "
               "drier, deeper drybacks and smaller shots let pore EC stack. If the feed EC is not lower than "
               "pore EC, more water cannot lower pore EC. A target far from anything the feed and the slab have "
               "reached must not be chased: chasing it shrinks the shots until the zone gets short shots every "
               "few minutes. What is driving this zone's pore EC?", CAUSES),
        choice("Decide why this zone's pore EC reads what it does, so the EC steer knows whether to act. The "
               "steer moves the maintenance re-water threshold: pore EC above its band means water sooner "
               "(wetter, more runoff, dilutes), below its band means let the slab dry deeper (stacks). Rules a "
               "grower follows: the settled reading, taken 45 minutes or more after a shot, is the slab; the "
               "reading just after a shot is the feed going by. EC that rises after a flush means the salts are "
               "still coming out: flush more, do not blame the probe. Watering cannot bring pore EC below the "
               "feed EC. A target well outside what this slab and feed have ever read is not worth steering "
               "to.", CAUSES),
    ],
}, doctrine("ec") + " " + doctrine("closed_loop", "stage", limit=4) + " "
   + doctrine("maintenance", limit=3))


def _words_ec(v):
    return "unknown" if v is None else f"{v:.2f} mS/cm"


class SaltJudge(Judge):
    name = "salt"
    phases = ("P2",)
    cadence_min = 30.0
    max_age_min = 45.0
    outcome_after_min = 240.0
    questions = QUESTIONS

    def __init__(self):
        self._feed = {}  # room -> [(time, feed EC)], sampled on each pass (due() runs on every pass)

    def due(self, ctx, last_asked):
        self._note_feed(ctx)
        # Its only action is the EC steer's mode, and the steer runs only while the room's EC stacking is on:
        # asked with stacking off it chose holds that changed nothing and filled the log with their outcomes.
        return (super().due(ctx, last_asked) and ctx.snap.ec_settled is not None
                and getattr(ctx.params, "stacking_on", True))

    def _note_feed(self, ctx):
        if ctx.feed_ec is None:
            return
        pts = self._feed.setdefault(ctx.room, [])
        if not pts or ctx.now - pts[-1][0] >= timedelta(minutes=10):
            pts.append((ctx.now, ctx.feed_ec))
            del pts[:-80]  # about 13 hours

    def evidence(self, ctx):
        s, p = ctx.snap, ctx.params
        ec, target = s.ec_settled, p.ec_target_p2
        lo, hi = target * (1 - BAND), target * (1 + BAND)
        e = common(ctx)
        e.update({
            "settled_pore_ec_vs_target": (
                f"{ec:.2f} mS/cm settled against a maintenance target of {target:.2f}; the steer leaves it alone "
                f"between {lo:.2f} and {hi:.2f}: "
                + ("inside the band, the steer is at rest" if lo <= ec <= hi else
                   f"{ec - hi:.2f} above the band, the steer is watering sooner to dilute" if ec > hi else
                   f"{lo - ec:.2f} below the band, the steer is letting the slab dry deeper to stack")),
            "pore_ec_last_hour": words_trend(trend(ctx.history, ctx.now, 60, index=2), "mS/cm", "pore EC"),
            "pore_ec_last_6_hours": words_trend(trend(ctx.history, ctx.now, 360, index=2), "mS/cm", "pore EC"),
            "pore_ec_after_the_last_flush": self._after_flush(ctx),
            "target_vs_what_was_reached": self._reach(ctx, target),
            "pore_ec_steps_away_from_shots": self._steps(ctx),
            "moisture_last_hour": words_trend(trend(ctx.history, ctx.now, 60)),
            "moisture_vs_field_capacity": (
                f"{s.vwc:.1f}% against a field capacity of {p.field_capacity:.1f}%"
                + (" (within 2 points: the base engine will not flush a slab this full)"
                   if s.vwc >= p.field_capacity - 2.0 else "")),
            "shots_last_6_hours": self._shots(ctx),
            "max_ec": (f"{p.max_ec:.2f} mS/cm, "
                       + (f"{p.max_ec - ec:.2f} above the settled pore EC" if ec < p.max_ec else
                          "and the settled pore EC is at or over it")
                       + "; at it the base engine flushes, and within 1 of it rescues, whatever the steer does"),
            "feed_ec_change": self._feed_change(ctx),
        })
        if ctx.stage:
            lo_s, hi_s = ctx.stage["pore_ec_range"]
            e["stage_ec_band"] = (f"the owner's stage arc wants {ctx.stage['pore_ec']} in {ctx.stage['stage']} "
                                  f"({ctx.stage['steering']} steering); the settled reading is "
                                  + ("inside it" if lo_s <= ec <= hi_s else "below it" if ec < lo_s else "above it"))
        if ctx.feed_ec is not None:
            e["feed_vs_pore_ec"] = (
                f"feed {ctx.feed_ec:.2f} is lower than pore EC {ec:.2f}, so water through the slab lowers pore EC"
                if ctx.feed_ec < ec else
                f"feed {ctx.feed_ec:.2f} is not lower than pore EC {ec:.2f}, so more water cannot lower pore EC")
        return e

    @staticmethod
    def _after_flush(ctx):
        """What pore EC did after the last flush, dilute, rescue or large shot."""
        shots = list(ctx.history.shots)
        sizes = sorted(sh.litres for sh in shots)
        large = 1.5 * sizes[len(sizes) // 2] if sizes else None
        last = next((sh for sh in reversed(shots)
                     if sh.kind in FLUSHES or (large and sh.litres >= large)), None)
        if last is None:
            return "no flush, dilute or large shot recorded"
        end = last.start + timedelta(seconds=last.seconds)
        head = f"{last.start:%H:%M} {last.kind} shot ({last.litres:.1f} L)"
        if ctx.now < end + timedelta(minutes=SETTLE_MIN):
            return f"{head}: too soon to read, the feed front is still passing the probe"
        read = ctx.history.at(end + timedelta(minutes=SETTLE_MIN))
        after = read[2] if read is not None else None
        if last.pre_ec is None or after is None:
            return f"{head}: no pore EC reading to compare"
        move = after - last.pre_ec
        what = ("rose after the water went in" if move >= 0.1 else
                "fell after the water went in" if move <= -0.1 else "about the same after the water went in")
        return (f"{head}: pore EC {last.pre_ec:.2f} before, {after:.2f} 45 minutes after, "
                f"{ctx.snap.ec_settled:.2f} settled now: {what}")

    @staticmethod
    def _reach(ctx, target):
        """The target against the range pore EC has read in the last day."""
        pts = [r[2] for r in ctx.history.since(ctx.now - timedelta(hours=24)) if r[2] is not None]
        if not pts:
            return "no pore EC readings in the last day"
        lo, hi = min(pts), max(pts)
        span = f"pore EC read between {lo:.2f} and {hi:.2f} in the last day"
        if lo <= target <= hi:
            return f"the target {target:.2f} is inside what was reached: {span}"
        edge = hi if target > hi else lo
        far = abs(target - edge) > 0.25 * edge
        side = "above" if target > hi else "below"
        out = (f"the target {target:.2f} is {'far' if far else 'a little'} {side} anything reached "
               f"({abs(target - edge):.2f} {side} the {'highest' if side == 'above' else 'lowest'}): {span}")
        if ctx.feed_ec is not None and side == "below" and ctx.feed_ec > target:
            out += f"; the feed {ctx.feed_ec:.2f} is above the target too"
        return out

    @staticmethod
    def _steps(ctx):
        """The largest step between two readings in a row, away from shots (the feed front excluded)."""
        busy = [(sh.start, sh.start + timedelta(seconds=sh.seconds, minutes=SETTLE_MIN)) for sh in ctx.history.shots]
        quiet = [r for r in ctx.history.since(ctx.now - timedelta(hours=6))
                 if r[2] is not None and not any(a <= r[0] <= b for a, b in busy)]
        steps = [(abs(b[2] - a[2]), b[0]) for a, b in zip(quiet, quiet[1:])
                 if (b[0] - a[0]) <= timedelta(minutes=5)]
        if not steps:
            return "no quiet stretch of readings in the last 6 hours"
        size, at = max(steps)
        tag = "steady" if size < 0.15 else "a small step" if size < 0.4 else "a jump"
        return f"largest step between readings minutes apart: {size:.2f} mS/cm at {at:%H:%M} ({tag})"

    @staticmethod
    def _shots(ctx):
        shots = [sh for sh in ctx.history.shots if sh.start >= ctx.now - timedelta(hours=6)]
        if not shots:
            return "none"
        out = (f"{len(shots)} shot(s), {sum(sh.litres for sh in shots):.1f} L in total, "
               f"{min(sh.seconds for sh in shots):.0f} to {max(sh.seconds for sh in shots):.0f} s each")
        if len(shots) >= 2:
            gap = min((b.start - a.start).total_seconds() / 60.0 for a, b in zip(shots, shots[1:]))
            out += f", as close as {gap:.0f} min apart"
        return out

    def _feed_change(self, ctx):
        pts = [pt for pt in self._feed.get(ctx.room, []) if pt[0] >= ctx.now - timedelta(hours=6)]
        if ctx.feed_ec is None or not pts or ctx.now - pts[0][0] < timedelta(hours=1):
            return "not known yet (too little feed EC history)"
        t0, f0 = pts[0]
        move = ctx.feed_ec - f0
        if abs(move) < 0.1:
            return f"feed EC steady around {ctx.feed_ec:.2f} since {t0:%H:%M}"
        return (f"feed EC {ctx.feed_ec:.2f} now against {f0:.2f} at {t0:%H:%M}: "
                f"{'risen' if move > 0 else 'fallen'} {abs(move):.2f}")

    def decide(self, verdicts, ctx):
        v = verdicts.get("salt_cause")
        if v is None:
            return None
        mode = next((m for m in ("steer", "hold", "decay")
                     if v.firm_in([c for c, x in MODE.items() if x == m], 0.6)), None)
        if mode is None:
            return None
        return self.directive(ctx, "ec_mode", mode, f"pore EC: {v.label} (p={v.prob:.2f}), {mode} the steer")

    def outcome(self, entry, ctx):
        s = ctx.snap
        if s is None:
            return None
        ec = s.ec_settled if s.ec_settled is not None else s.ec
        if ec is None:
            return None
        target = ctx.params.ec_target_p2
        mode = entry.get("label")  # the EC mode acted on: steer, hold or decay
        before = (entry.get("check") or {}).get("ec")
        in_band = abs(ec - target) <= BAND * target
        safe = ec < ctx.params.max_ec - 1.0
        if before is None:
            return (f"pore EC {ec:.2f} four hours after '{mode}', "
                    f"{'inside' if in_band else 'outside'} the band around the target {target:.2f}"), in_band and safe
        toward = abs(ec - target) < abs(before - target)
        steady = abs(ec - before) <= BAND * max(before, 0.1)
        # A steer is judged on reaching the target. A hold or a decay is a call NOT to chase it (an
        # unreachable target, a doubtful probe, a feed change): judged on staying safe and steady, never
        # scored against the target it chose not to chase.
        good = (in_band or toward) if mode == "steer" else safe and (in_band or toward or steady)
        how = ("inside the band" if in_band else "moved toward the target" if toward else
               "held steady" if steady else "moved away from the target")
        return (f"four hours after '{mode}' pore EC read {ec:.2f} (was {before:.2f}) against a target of "
                f"{target:.2f}: {how}{'' if safe else ', and within 1 of max EC'}"), good
