"""Late maintenance: should tomorrow move this zone toward the room's water per plant, and which way?

Asked once a grow-day in the last two hours before lights-off, only while the zone's water per plant today is
outside 85-115 % of the room's median zone (zones.water_vs_room) and the zones judge has not named a hardware cause
for it today. It advises only and has no directive: its answer is kept and handed to tonight's setpoints judge for
the same zone as `room_balance` (brain_bridge.brain_context, brain.enrich), so the setpoints judge stays the one writer
of the zone's shot size and re-water threshold. Built only under brain_provider claude_haiku (brain_bridge.build).
"""
from datetime import timedelta

from ..doctrine import doctrine
from .base import Judge, choice, common, with_doctrine
from .zones import water_vs_room

LOW, HIGH = 0.85, 1.15  # inside this share of the room's median water per plant the zone is in balance
LATE_H = 2.0  # asked only in the last this many hours before lights-off
EVIDENCE_H = 8.0  # the answer is handed to the setpoints judge this long (through the first hours of the night)
# The zones judge's causes that are hardware: water counted is not water the plants got, so do not chase the room.
HARDWARE = ("probe_wet_spot", "probe_dry_spot", "delivery_fault", "water_not_landing")

CHOICES = {
    "less_water_toward_room": "Tomorrow this zone should get less water per plant, toward the room's: it is drinking "
                              "more than its siblings for no reason the facts show.",
    "more_water_toward_room": "Tomorrow this zone should get more water per plant, toward the room's: it is drinking "
                              "less than its siblings for no reason the facts show.",
    "difference_is_intended": "The difference is on purpose: the zone's own settings, plants or steering differ from "
                              "its siblings', so it should stay different.",
    "difference_is_hardware": "The difference looks like hardware (a probe in a wet or dry spot, a dripper, valve or "
                              "line), not the plants: a person should check it before any setting follows it.",
    "keep_as_is": "Leave tomorrow's water as it is: the difference is small or already closing.",
    "insufficient_evidence": "The facts do not support any of the other answers.",
}

QUESTIONS = with_doctrine({
    "toward_room": [
        choice("You are the head grower balancing irrigation zones in one room that share the feed and the climate. "
               "Judge only from the facts given. This zone's water per plant today is outside 85-115 % of the "
               "room's median zone. Say whether tomorrow should move it toward the room, and which way, or why it "
               "should not. Your answer is shown to tonight's setpoints judge; it changes nothing itself.", CHOICES),
        choice("Compare this zone's water per plant, settings and drying with its sibling zones. Should tomorrow's "
               "maintenance watering bring it closer to the room's water per plant (less or more), or is the "
               "difference intended, hardware, or not worth acting on?", CHOICES),
    ],
}, doctrine("maintenance", "slab"))


class BalanceJudge(Judge):
    name = "balance"
    phases = ("P2",)
    cadence_min = 20 * 60.0  # once a grow-day: the next window opens a day later
    max_age_min = 3 * 60.0
    questions = QUESTIONS

    def __init__(self):
        self.latest = {}  # (room, zone) -> (when, the answer in words), for tonight's setpoints judge

    def due(self, ctx, last_asked):
        if ctx.brain is None or not ctx.lights_on or ctx.hours_to_off > LATE_H or not super().due(ctx, last_asked):
            return False
        if ctx.brain.get("zones_hardware"):
            return False
        ratio = water_vs_room(ctx)[2]
        return ratio is not None and not LOW <= ratio <= HIGH

    def evidence(self, ctx):
        s, p = ctx.snap, ctx.params
        mine, typical, ratio, basis = water_vs_room(ctx)
        e = common(ctx)
        if ratio is not None:
            e.update({
                "water_per_plant_today": f"{mine * 1000:.0f} mL",
                "compared_with": f"{basis}: {typical * 1000:.0f} mL a plant",
                "share_of_that": f"{ratio * 100:.0f}% (in balance between {LOW * 100:.0f}% and {HIGH * 100:.0f}%)",
            })
        e.update({
            "re_water_threshold": f"{p.p2_threshold:.1f}% VWC (shot size {p.p2_shot_size:.1f}% of the substrate)",
            "drying_rate": f"{s.dryback_rate:.2f} points an hour",
            "siblings": {f"zone {z}": {k: v[k] for k in ("litres_per_plant_words", "vwc_words", "threshold_words",
                                                         "rise_words") if v.get(k)}
                         for z, v in ctx.siblings.items()},
        })
        return e

    def decide(self, verdicts, ctx):
        v = verdicts.get("toward_room")
        if v is not None and v.label in CHOICES:
            self.latest[(ctx.room, ctx.zone)] = (ctx.now, f"the balance judge said {v.label}, p {v.prob:.2f}, at "
                                                          f"{ctx.now:%H:%M}: {CHOICES[v.label]}")
        return None

    def words(self, room, zone, now):
        """The latest answer for the zone in words while it is under EVIDENCE_H old, else None."""
        at, text = self.latest.get((room, zone), (None, None))
        return text if at is not None and now - at <= timedelta(hours=EVIDENCE_H) else None
