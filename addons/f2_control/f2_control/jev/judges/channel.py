"""Lights on: is the water bypassing the substrate or the probe, or are the plants drinking less?

Two signs make code ask, at most hourly. Shots that spike the probe and fall straight back (two of the last four
settled shots keeping under a quarter of the zone's typical rise) say water is running past the probe or through
the block. A zone drinking under 40 % of the room's typical water per plant says the water is not going in, or the
plants are not taking it. The second sign counts only when the room's typical is at least a tenth of a plant's
substrate (0.5 L a plant on a 5 L block, 1 L on 10 L), so it scales with plant count and pot size: the base
engine's own under-drinker flag needs a median zone of 5 L a day, which a small install never reaches.

The judge never adds water. Doctrine says investigate, not add volume: its only directive is the CS-710 alert
asking for a catch test and a block check, and its latest answer is evidence for the probe judge.
"""
from datetime import timedelta

from ..context import response, words_response
from ..doctrine import doctrine
from .base import Judge, choice, common, with_doctrine
from .zones import water_vs_room

CODE = "CS-710"
CHANNEL_MIN_DRINK_FRAC = 0.10  # the room's typical water per plant must be this share of a plant's substrate
UNDER_SHARE = 0.4  # a zone under this share of the room's typical water per plant is drinking little
FALL_BACK_SHARE = 0.25  # a shot keeping under this share of the zone's typical rise fell back
LAST_SHOTS = 4
EVIDENCE_H = 6.0  # the latest answer is shown to the probe judge this long

SIGNATURES = {
    "no_channeling": "Shots rise and hold like a working zone: the water stays in the substrate.",
    "channeling_at_probe": "Water runs down past the probe: each shot spikes the reading and it falls straight back, while the block as a whole takes the water.",
    "channeling_through_slab": "Water runs through the block and out of the drain without wetting it: shots spike and fall back and the zone keeps drinking little.",
    "dry_core_or_poor_contact": "The block has dried hard or the drippers sit off it, so water runs over or around it instead of in.",
    "under_drinking_plants": "The water lands, but the plants use less of it than their neighbours (smaller, stressed, or root trouble).",
    "delivery_restricted": "Less water arrives than is counted: a slow dripper, a partly closed valve or a restricted line.",
    "insufficient_evidence": "The facts do not support any of the other answers.",
}
ALERT = set(SIGNATURES) - {"no_channeling", "insufficient_evidence"}

QUESTIONS = with_doctrine({
    "signature": [
        choice("You are the head grower checking whether irrigation water is going into one zone's substrate. "
               "Judge only from the facts given. Code saw shots that spike and fall back, or a zone drinking far "
               "less water per plant than the room. A shot that runs past the probe spikes the reading and falls "
               "straight back; water running through or around a dry block shows the same and the zone drinks "
               "little; plants that drink less let water land and hold but use less of it. Which fits?",
               SIGNATURES),
        choice("Water was sent to this zone and code doubts it stayed. Say where it went, from how each shot rose "
               "and what it kept, the zone's water per plant against the room's, and its sibling zones.",
               SIGNATURES),
    ],
}, doctrine("probe", "ramp"))


def fell_back(ctx):
    """(shots that spiked and fell back, settled shots looked at) among the zone's last four settled shots."""
    typical = ctx.typical_rise()
    rs = [r for r in (response(ctx.history, s, ctx.now) for s in ctx.history.shots) if r.settled][-LAST_SHOTS:]
    if typical is None:
        return 0, len(rs)
    fell = [r for r in rs if r.peak_rise is not None and r.retained is not None
            and r.peak_rise >= 0.5 * typical and r.retained < FALL_BACK_SHARE * typical]
    return len(fell), len(rs)


def under_drinking(ctx):
    """(litres a plant, the room's typical, ratio, basis) when the zone drinks under 40 % of the room's typical
    water per plant and that typical is at least CHANNEL_MIN_DRINK_FRAC of a plant's substrate; else None."""
    mine, typical, ratio, basis = water_vs_room(ctx)
    if ratio is None or not ctx.substrate_l or not ctx.plants:
        return None
    if ratio < UNDER_SHARE and typical >= CHANNEL_MIN_DRINK_FRAC * ctx.substrate_l / ctx.plants:
        return mine, typical, ratio, basis
    return None


def signs(ctx):
    """What code saw, in words: [] when there is nothing to ask about."""
    out = []
    fell, seen = fell_back(ctx)
    if fell >= 2:
        out.append(f"{fell} of the last {seen} shots spiked and fell back to under "
                   f"{FALL_BACK_SHARE * 100:.0f}% of this zone's typical rise")
    low = under_drinking(ctx)
    if low is not None:
        mine, typical, ratio, basis = low
        out.append(f"{mine * 1000:.0f} mL a plant today, {ratio * 100:.0f}% of {basis} ({typical * 1000:.0f} mL "
                   f"a plant) on {ctx.substrate_l / ctx.plants:.1f} L of substrate a plant")
    return out


class ChannelJudge(Judge):
    name = "channel"
    cadence_min = 60.0
    max_age_min = 90.0
    questions = QUESTIONS

    def __init__(self):
        self.latest = {}  # (room, zone) -> (when, the answer in words), for the probe judge

    def due(self, ctx, last_asked):
        return ctx.lights_on and super().due(ctx, last_asked) and bool(signs(ctx))

    def evidence(self, ctx):
        typical = ctx.typical_rise()
        rs = [r for r in (response(ctx.history, s, ctx.now) for s in ctx.history.shots) if r.settled]
        e = common(ctx)
        e.update({
            "code_saw": signs(ctx) or ["nothing now (it did when it asked)"],
            "last_shots": [words_response(r, typical) for r in rs[-LAST_SHOTS:]] or ["no settled shots today"],
            "typical_retained_rise": "unknown" if typical is None else f"{typical:.2f} points per shot today",
        })
        if ctx.substrate_l and ctx.plants:
            e["substrate_per_plant"] = f"{ctx.substrate_l / ctx.plants:.1f} L"
        sib = {f"zone {z}": v.get("rise_words") for z, v in ctx.siblings.items() if v.get("rise_words")}
        if sib:
            e["sibling_zones_latest_shot"] = sib
        return e

    def decide(self, verdicts, ctx):
        v = verdicts.get("signature")
        if v is None or v.label not in SIGNATURES:
            return None
        self.latest[(ctx.room, ctx.zone)] = (ctx.now, f"{v.label} (p {v.prob:.2f}) at {ctx.now:%H:%M}: "
                                                      f"{SIGNATURES[v.label]}")
        if not v.firm_in(ALERT, 0.6) or v.label not in ALERT:
            return None
        return self.directive(ctx, "alert", {
            "code": CODE,
            "title": "water may be bypassing the substrate or the probe",
            "message": (f"On {ctx.title} code saw: {'; '.join(signs(ctx)) or 'shots that did not stay'}. Jev's "
                        f"reading: {SIGNATURES[v.label]} Do a catch test on a few drippers, and check the blocks: "
                        f"drippers seated in them, water wetting through rather than running off or out of the "
                        f"drain, and the probe firm in a representative spot. Watering carries on as normal; do "
                        f"not add volume to make up for it."),
        }, f"{v.label} (p={v.prob:.2f})")

    def words(self, room, zone, now):
        """The latest answer for the zone in words while it is under EVIDENCE_H old, else None."""
        at, text = self.latest.get((room, zone), (None, None))
        return text if at is not None and now - at <= timedelta(hours=EVIDENCE_H) else None
