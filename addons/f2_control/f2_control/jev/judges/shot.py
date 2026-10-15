"""Every phase: did the water land?

A shot the controller fired is not a shot the plants got. On 24 Sep 2026 F2 zone 2 did not land from 14:36
to 16:42: four shots of about 270 s, moisture falling 30.5 -> 26.4 while zones 1 and 3 landed normally.
The watchdog meant to catch it could never fire (it was gated on health sensors that no longer existed).
A person reads a shot the way this judge does: water went in; did the probe go up and stay up, did pore
EC move toward the feed, and what did the sibling zones watered at the same time do?

Each shot is audited once, about 20 minutes after it ends (the newest one, when shots come faster than
the cadence). The judge never adds water: its only directive is the CS-701 alert, raised when two shots
in a row did not reach the zone. Watering carries on as normal either way.
"""
from dataclasses import dataclass, field
from datetime import timedelta

from ..context import response
from ..doctrine import doctrine
from .base import Judge, choice, common, with_doctrine

CODE = "CS-701"

LANDINGS = {
    "landed": "Moisture rose after the shot and held, like a normal shot for this zone.",
    "landed_slow": "A small or late rise: the water arrived, but less or later than usual.",
    "reached_probe_vwc_flat": "The probe saw the water (pore EC moved toward the feed EC) but moisture did not rise: the slab may be full, or the water is channeling past.",
    "not_reaching_zone": "No sign the water reached this zone at all: moisture did not rise and pore EC did not move toward the feed.",
    "insufficient_evidence": "The facts do not support any of the other answers.",
}

QUESTIONS = with_doctrine({
    "landing": [
        choice("You are the head grower checking one shot of irrigation on one zone of rockwool or coco, about 20 "
               "minutes after it ended. Judge only from the facts given. Doctrine: a shot that lands raises the "
               "probe's moisture reading within minutes; part of the rise drains away (the free-water spike in "
               "the first 10 minutes) and most of it stays. Fresh feed passing the probe moves pore EC toward "
               "the feed EC even when moisture cannot rise because the slab is already full. Compare the shot "
               "with this zone's typical rise and with the sibling zones. Did this shot's water land?", LANDINGS),
        choice("Water was sent to this zone. Say where it went. A zone whose valve, drippers or line are blocked "
               "shows no moisture rise and no pore EC change at all, while sibling zones on the same feed rise "
               "as usual. A full slab or water channeling past the probe shows pore EC moving toward the feed "
               "while moisture stays flat. A slow dripper or a dry, hard-to-wet slab shows a small or late "
               "rise.", LANDINGS),
    ],
}, doctrine("probe", "maintenance", limit=4) + " " + doctrine("ramp", limit=3))


@dataclass
class _Zone:
    judged: object = None  # start time of the last shot judged
    asking: object = None  # the Shot the question in flight is about
    asked_at: object = None
    misses: list = field(default_factory=list)  # the last firm "not reaching" shots in a row, oldest first
    verdicts: object = None  # the answer last decided (the brain hands it back on every pass while fresh)
    directive: object = None  # what was decided for it


def _pct(v):
    return "unknown" if v is None else f"{v:.1f}%"


def _ec(v):
    return "unknown" if v is None else f"{v:.2f} mS/cm"


def _retained(r, typical):
    if r.retained is None:
        return "no reading to judge it by"
    out = f"{r.retained:+.1f} points kept 20 minutes after it ended"
    if typical:
        ratio = r.retained / typical
        out += (" (about the usual)" if ratio >= 0.6 else " (less than usual)" if ratio >= 0.25
                else " (almost nothing)")
    return out


def _ec_move(r, feed):
    if r.ec_move is None:
        return "no reading to judge it by"
    out = f"{r.ec_move:+.2f} mS/cm"
    if abs(r.ec_move) < 0.05:
        return out + " (no change)"
    pre = r.shot.pre_ec
    if feed is not None and pre is not None and abs(pre - feed) >= 0.05:
        toward = (r.ec_move < 0) == (pre > feed)
        out += f", {'toward' if toward else 'away from'} the feed EC {feed:.2f}"
    return out


class ShotJudge(Judge):
    name = "shot"
    cadence_min = 10.0
    max_age_min = 30.0
    questions = QUESTIONS

    def __init__(self):
        self._zones = {}  # (room, zone) -> _Zone

    def _z(self, ctx):
        return self._zones.setdefault((ctx.room, ctx.zone), _Zone())

    def _next(self, ctx):
        """The newest settled shot not judged yet, or None."""
        judged = self._z(ctx).judged
        for sh in reversed(ctx.history.shots):
            if judged is not None and sh.start <= judged:
                return None
            if response(ctx.history, sh, ctx.now).settled:
                return sh
        return None

    def due(self, ctx, last_asked):
        if not super().due(ctx, last_asked):
            return False
        z = self._z(ctx)
        if z.asking is not None and ctx.now - z.asked_at < timedelta(minutes=self.max_age_min):
            return False  # the answer about the shot last asked is still to come
        return self._next(ctx) is not None

    def evidence(self, ctx):
        z = self._z(ctx)
        sh = self._next(ctx)
        z.asking, z.asked_at = sh, ctx.now
        r = response(ctx.history, sh, ctx.now)
        typical = ctx.typical_rise()
        end = sh.start + timedelta(seconds=sh.seconds)
        e = common(ctx)
        e.update({
            "shot": f"{sh.start:%H:%M} {sh.kind} shot of {sh.seconds:.0f} s, {sh.litres:.1f} L",
            "minutes_since_it_ended": round((ctx.now - end).total_seconds() / 60.0),
            "before_the_shot": f"VWC {_pct(sh.pre_vwc)}, pore EC {_ec(sh.pre_ec)}",
            "spike_first_10_min": ("no reading to judge it by" if r.peak_rise is None
                                   else f"{r.peak_rise:+.1f} points at the highest"),
            "retained_rise_at_20_min": _retained(r, typical),
            "pore_ec_move_at_20_min": _ec_move(r, ctx.feed_ec),
            "typical_retained_rise": "unknown" if typical is None else f"{typical:.2f} points per shot today",
        })
        later = sum(1 for x in ctx.history.shots if sh.start < x.start <= ctx.now)
        if later:
            e["shots_since"] = later
        elif sh.pre_vwc is not None:
            e["moisture_now_vs_before_the_shot"] = f"{ctx.snap.vwc - sh.pre_vwc:+.1f} points, no shot since"
        sib = {f"zone {n}": v.get("rise_words") for n, v in ctx.siblings.items() if v.get("rise_words")}
        if sib:
            e["sibling_zones_latest_shot"] = sib
        return e

    def decide(self, verdicts, ctx):
        z = self._z(ctx)
        if verdicts is z.verdicts:  # the same answer again: what was decided for it
            return z.directive
        z.verdicts, z.directive = verdicts, None
        sh, z.asking = z.asking, None
        if sh is None:
            return None  # an answer with no shot on record
        z.judged = sh.start
        v = verdicts.get("landing")
        if v is not None and v.firm(0.6) and v.label == "not_reaching_zone":
            z.misses = (z.misses + [sh])[-2:]
        else:
            z.misses = []  # a landing, or no firm answer: the run is broken
        if len(z.misses) == 2:
            a, b = z.misses
            alert = {"code": CODE, "title": "water isn't reaching this zone",
                     "message": (f"The last two shots on {ctx.title} at {a.start:%H:%M} and {b.start:%H:%M} put in "
                                 f"{a.litres:.1f} L and {b.litres:.1f} L and moisture did not rise; check the "
                                 f"zone's valve, drippers and line; watering carries on as normal.")}
            z.directive = self.directive(ctx, "alert", alert,
                                         f"two shots in a row did not reach the zone (p={v.prob:.2f})")
        return z.directive
