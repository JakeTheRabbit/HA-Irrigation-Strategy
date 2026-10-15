"""Crop-steering doctrine for Jev: the owner's GrowLabs wiki and Athena's handbook, restated as rules a judge can quote.

Jev answers typed questions about the facts it is given, but it knows no crop-steering doctrine and does no
arithmetic, so every judge writes the doctrine into its question. This module keeps that doctrine in one
place: Ben Isdale's GrowLabs wiki pages, then Athena's Grow Guide Handbook (SOURCES), each point restated as one
plain sentence tagged with where it comes from. A judge appends doctrine("ramp", "probe") to a question's
instructions.

True water content vs probe readings: the wiki's moisture numbers (a ~92 % full mark, a 55-92 % working band,
a 25-30 % recovery floor, drybacks of 5-30 points) are TRUE water content. A probe can read far from that: the
F2 probes read about 33-41 % at saturation. So no rule sets an absolute moisture band against a raw reading.
The rules judge a zone against its own saturation, its own peak and its own trends, and they say "true water
content" wherever they keep a wiki number.

Stage arc: the rockwool and one-steering-law pages put the deepest drybacks and the highest EC in flower
weeks 4-6. The slab-irrigation page (Athena and CCI) makes flower days 22-42 a vegetative bulk. On 26 Sep 2026
the owner chose the slab page's arc, so STAGE_ARC and the "stage" rules follow it. ALT_STAGE_ARC keeps the
other arc for reference only.

Within each topic the rules are listed most important first, so doctrine(..., limit=n) keeps the core.
"""
from dataclasses import dataclass

TEROS = "https://www.growlabs.nz/wiki/root-zone-teros12.html"
LOOP = "https://www.growlabs.nz/wiki/closed-loop.html"
STAGES = "https://www.growlabs.nz/wiki/flowering-stages.html"
ROCKWOOL = "https://www.growlabs.nz/wiki/rockwool-crop-steering.html"
LAW = "https://www.growlabs.nz/wiki/one-steering-law.html"
SLAB = "https://www.growlabs.nz/wiki/slab-irrigation-strategy.html"
RIPEN = "https://www.growlabs.nz/wiki/ripening-harvest-timing.html"

SOURCES = [TEROS, LOOP, STAGES, ROCKWOOL, LAW, SLAB, RIPEN]


@dataclass(frozen=True)
class Rule:
    text: str  # one plain sentence Jev can apply to the facts it is given
    source: str  # the wiki page it restates


RULES = {
    "ramp": [
        Rule("P1 refills the slab after the morning dryback in a series of shots and stops as soon as the zone "
             "reaches its full mark for the day, never topping up past it.", LAW),
        Rule("The full mark (field capacity) belongs to this zone's own slab and plants, is learned from about five "
             "agreeing waterings and shrinks as roots fill the slab, so 'full' is judged against the zone's own "
             "recent peaks.", TEROS),
        Rule("As the slab nears full each shot's lasting rise gets smaller, so a run of shots that barely add "
             "lasting moisture is the sign the ramp is done.", TEROS),
        Rule("The ramp's job is to refill the slab, and the runoff that flushes stacked salt comes once the slab "
             "is at field capacity, through the day's maintenance shots.", ROCKWOOL),
        Rule("A single shot should lift water content by roughly 2-5 points of true water content: enough to "
             "register on the probe, not so much that it runs straight out as runoff.", ROCKWOOL),
        Rule("A P1 shot is typically 2-6 % of the substrate volume (commonly 3-5 %), with the shots 15-30 minutes "
             "apart.", SLAB),
        Rule("Runoff appearing while moisture barely rises means channeling or poor block contact, and adding "
             "volume blindly does not fix it.", SLAB),
        Rule("If P1 never reaches its target, suspect a target above the peak the slab can actually hold, a "
             "blocked dripper, a wrong flow assumption or too few ramp shots before adding water.", SLAB),
        Rule("A vegetative day starts the ramp early with a short climb to a high peak, while a generative day "
             "delays the first shot after a longer overnight dryback and peaks lower, mid-band.", ROCKWOOL),
    ],
    "dryback": [
        Rule("Dryback depth is the main steering lever: a small dryback of about 5-15 points of true water "
             "content steers vegetative and a large one of about 20-30 points steers generative.", ROCKWOOL),
        Rule("Dryback is counted in points of true water content (peak minus trough), so on a probe that "
             "under-reads it is judged against the zone's own peak and its own previous days rather than the "
             "wiki's point numbers.", LAW),
        Rule("The recovery floor is a safety limit, not a steering target: in true water content rockwool stops "
             "wicking below about 25-30 %, water then tunnels past a dry core, and only a hand-soak recovers "
             "it.", ROCKWOOL),
        Rule("A minimum moisture for the crop and slab is established before any dryback target is used, and no "
             "dryback may cross it.", SLAB),
        Rule("P0 runs from lights-on to the first shot, which is triggered by measured water loss and the "
             "block's hydration while staying above the crop's established minimum moisture.", SLAB),
        Rule("P3 starts with the day's last shot, often before lights-off, and a generative day uses a shorter "
             "irrigation window so the overnight dryback is longer.", SLAB),
        Rule("The overnight dryback adds roughly 5-15 points of true water content in any stage, and its job is "
             "to put air back into the root zone.", ROCKWOOL),
        Rule("Some dryback is essential but deeper is not always better: easing the overnight dryback to leave "
             "the slab about a tenth wetter lifted medicinal yield in research.", LAW),
        Rule("Steering is a dimmer moved one notch a day across a week, never an overnight switch, so dryback "
             "targets change in small steps.", LAW),
        Rule("A dryback smaller than the probe's error is guesswork: calibrate the probe to the slab or use a "
             "bigger dryback.", LAW),
        Rule("A dryback that suddenly deepens usually means a missed shot or a change in demand (light, VPD, CO2 "
             "or airflow): check the logs and climate first, and add maintenance water only once the cause is "
             "known.", SLAB),
    ],
    "maintenance": [
        Rule("P2 replaces the water the plants use through the light period, and its drainage is what carries "
             "dissolved salt out, judged by the EC and the runoff it produces.", SLAB),
        Rule("Through P2 the zone is held inside its band: top it up when it dips, and steer with the feed "
             "strength rather than by swinging the moisture.", LAW),
        Rule("Aim for roughly 10-20 % runoff of the water fed once the slab is at field capacity, because that "
             "runoff flushes stacked salt and shows the slab's EC.", ROCKWOOL),
        Rule("Vegetative steering gives many small shots and keeps the slab wetter, while generative steering "
             "gives fewer, bigger shots and lets it dry further between them.", LAW),
        Rule("A consistently wetter daytime gave higher yield at the same cannabinoid levels across the first six "
             "of eight flower weeks in Grodan's trials, so steer with timing and dryback, not by starving the "
             "day of water.", ROCKWOOL),
        Rule("Minimum daily volume is a floor, not a target: the right volume keeps the slab above its recovery "
             "floor and its EC on target, set by the probe and the runoff, not by a fixed clock.", ROCKWOOL),
        Rule("When a shot's expected moisture step never appears the water did not land (a clog, pump or line "
             "fault), and the answer is to re-fire it and raise an alert.", LOOP),
        Rule("A healthy moisture trace is a sawtooth of sharp rises at each shot and gradual falls between them, "
             "and a line that only falls or sits flat means water is not arriving.", LAW),
        Rule("Plants drinking hard under high light can make the dryback far bigger than set, answered by more "
             "maintenance shots once the controller and the probe are verified.", ROCKWOOL),
        Rule("Change one irrigation variable at a time and watch its effect over a full light-dark cycle before "
             "changing another.", SLAB),
        Rule("Runoff must be caught at representative plants or slabs in each zone, never inferred from how long "
             "the pump ran.", SLAB),
        Rule("Slabs that behave unevenly across a room point to dripper flow or placement: flush and check the "
             "lines and match the dripper count to the slab.", ROCKWOOL),
    ],
    "ec": [
        Rule("Steer by the EC in the slab, the pore water the roots sit in, not by the dripper or drain EC, "
             "because rockwool holds no nutrient reserve.", ROCKWOOL),
        Rule("As the slab dries, water leaves and the salt stays, so pore EC rises through every dryback on its "
             "own (a 3.0 feed can read over 5.0 by late afternoon) and each shot pulls it back down.", LAW),
        Rule("Pore or runoff EC that keeps climbing, even right after water has gone through, means not enough "
             "has been flushed yet and salt is still coming out, so the answer is bigger or more frequent shots, "
             "not blaming the probe.", ROCKWOOL),
        Rule("Water through the slab replaces its pore water with fresh feed, so more water moves pore EC toward "
             "the feed EC and can lower it only when the feed is weaker than the slab.", ROCKWOOL),
        Rule("Pore EC below its target means the slab is being over-flushed, answered by trimming the maintenance "
             "shots or the peak slightly and watching a full day.", SLAB),
        Rule("One high EC reading is noise, while a rise that runs for days past the zone's normal range is salt "
             "creep, seen about four days before tip burn, and the answer is to ease the dryback back.", LOOP),
        Rule("Root-zone salt is the slowest balance in the room, taking about four hours to settle after a "
             "change, so an EC move is judged hours after the change, not minutes.", LOOP),
        Rule("Only compare EC readings taken with the same method at similar moisture, because the same salt "
             "reads stronger in a drier slab and feed, drain and pore EC are different measurements.", SLAB),
        Rule("Pore EC is a model estimate built from bulk EC, moisture and temperature, off by up to about a "
             "fifth, and not valid in a nearly dry substrate (below about 10 % true water content).", TEROS),
        Rule("Runoff EC well above the feed EC means salt is building in the slab, answered by more runoff or a "
             "lower feed EC.", LAW),
        Rule("Pore EC drifting lower over several days on an unchanged feed means the plants are eating faster "
             "than they are fed, so the feed strength can come up a little.", LAW),
        Rule("When EC climbs outside its stage band, check the feed EC and the climate before adding maintenance "
             "water or runoff, and make that one recorded change.", SLAB),
    ],
    "probe": [
        Rule("A working probe answers each shot with a sharp rise and then a slow decay as the slab dries back, "
             "and near saturation its response flattens, so a shrinking rise per shot means the zone is nearing "
             "full.", TEROS),
        Rule("A reading that is pinned at zero or full scale, flat, missing or stale, or that jitters wildly, is "
             "a probe fault: stop acting on it and fall back to a safe routine.", TEROS),
        Rule("Treat the probe as one noisy witness, not the truth: it shows a tenth of a point but is accurate "
             "only to about 1-2 points of true water content when calibrated to the slab, and about 3 when "
             "not.", TEROS),
        Rule("A probe that differs from identically treated neighbouring zones points to a blocked dripper or a "
             "dud probe, and wetting and drying paths that diverge point to channeling.", TEROS),
        Rule("Moisture that rises and falls with the slab's daily temperature cycle is a contact or calibration "
             "artefact, not water moving.", TEROS),
        Rule("The probe senses only about a litre of slab around its prongs, one local spot rather than the "
             "zone's average, so channeling, dry pockets or poor contact can make a sound probe "
             "unrepresentative.", TEROS),
        Rule("The probe must sit firmly at a fixed, representative spot, because a loose probe or an air gap "
             "reports its surroundings instead of the root zone.", TEROS),
        Rule("An uncalibrated probe can be off by several points, so a probe whose saturation peak sits far "
             "below the slab's known full mark is under-reading and is judged against its own saturation peak "
             "and trends.", LAW),
        Rule("Steer on the shape and slope of the moisture trace, which a calibration offset does not change, "
             "rather than on its absolute level.", TEROS),
        Rule("Never let one probe alone move water: a second witness, such as runoff starting or the slab's "
             "weight, should agree first.", LAW),
        Rule("Check a doubtful probe in order: a hardware fault first, then temperature tracking, then drift "
             "against its siblings, and only then treat it as a noisy but usable witness.", TEROS),
        Rule("Moisture (VWC) is the share of the slab's volume that is liquid water and bulk EC is the "
             "conductivity of the whole wet slab, from which pore EC, the salt the roots feel, is "
             "estimated.", TEROS),
    ],
    "stage": [
        Rule("The owner steers by the slab guide's arc (chosen 26 Sep 2026): vegetative in established veg, "
             "generative through flower setting (nominal days 1-21), vegetative again through the bulk (days "
             "22-42), and a lower-EC generative finish over the final 10-14 days.", SLAB),
        Rule("Move from setting to bulk when the vertical stretch has clearly slowed or stopped, and from bulk to "
             "finish when flower expansion slows and ripening signals dominate: the day numbers are nominal, the "
             "plant's signals decide.", SLAB),
        Rule("Flower setting (nominal days 1-21) peaks at or below field capacity with 1-7 % runoff of the water "
             "fed, starts the dryback near 15 points of true water content and moves it toward 20-25 over three "
             "weeks, with root-zone EC 5-10.", SLAB),
        Rule("The bulk (nominal days 22-42) returns to vegetative irrigation: at or above field capacity, 8-16 % "
             "runoff of the water fed, a 10-15 point dryback in true water content and root-zone EC 3.5-6.",
             SLAB),
        Rule("The finish (normally the final 10-14 days) runs at or below field capacity with 1-7 % runoff of the "
             "water fed unless correcting excess EC, a 20-25 point dryback in true water content deepened only "
             "on cultivar data, and root-zone EC 3-4.", SLAB),
        Rule("Vegetative irrigation refills more often with less dryback, while generative irrigation uses a "
             "shorter irrigation window with more dryback.", SLAB),
        Rule("Established veg runs at or above field capacity with 8-16 % runoff of the water fed, a 10-15 point "
             "dryback in true water content and root-zone EC 3-5, and is ready to flip once roots are "
             "established and uptake repeats day to day.", SLAB),
        Rule("The rockwool and one-law guides instead put the deepest dryback (20-30 points of true water "
             "content) and the highest EC in flower weeks 4-6, an arc the owner has not chosen, so it is not "
             "the target.", ROCKWOOL),
        Rule("Final height locks in around flower week 4, almost all of it in the early stretch, and most of the "
             "flower weight goes on in weeks 5-7.", STAGES),
        Rule("The flowering guide's drip (feed) EC climbs from about 2.0-2.2 in week 1 to 2.6 in weeks 5-7 and "
             "eases to 2.2-2.4 in weeks 8-10, and these feed numbers must not be compared with pore or "
             "root-zone EC.", STAGES),
        Rule("A typical hybrid flowers for 8-10 weeks and a cultivar can finish a week or more either side of "
             "that, so any flower-day stage boundary is an estimate.", STAGES),
    ],
    "ripening": [
        Rule("Uptake falls as the plant senesces, so tapering feed EC modestly over the final week to match its "
             "appetite is sound agronomy, not a flush.", RIPEN),
        Rule("Long plain-water flushes showed no gain in yield, potency, terpenes or taste in blind trials, and "
             "they can crash the slab's EC and force an early fade while weight is still going on.", RIPEN),
        Rule("Flower weight keeps rising late (in one trial from week 5 to week 11, with total yield peaking at "
             "week 9), so the finish must not starve the plants early.", RIPEN),
        Rule("A hard, crispy fade by week 6 means over-flushing, a nitrogen crash or a root-zone EC collapse, "
             "and the answer is to restore a modest feed.", RIPEN),
        Rule("The finish's generative dryback still stops above the zone's established minimum moisture and goes "
             "deeper than its opening depth only on data for this cultivar.", SLAB),
        Rule("Ripening eases the feed EC and lowers the humidity, because dense late colas in humid air invite "
             "bud rot.", STAGES),
        Rule("Late flower humidity belongs at 45-55 % with 58 % as the ceiling, judged on the worst hour (the "
             "lights-off spike on dense colas) rather than the average, because botrytis rides those "
             "spikes.", RIPEN),
        Rule("Trichomes read on mid-cola calyxes decide the harvest, not the calendar or the pistils, so the "
             "finish's end date stays an estimate until they do.", RIPEN),
        Rule("When buds stop swelling and trichomes stall for a week, check the room temperature and the feed EC "
             "before deciding the plant is simply done.", RIPEN),
        Rule("The Athena fade swaps the core nutrient for Fade in weeks 8-9 at full bloom EC and cleanses with RO "
             "water on the last day, and the guide itself notes this does not show that flushing improves "
             "quality.", SLAB),
    ],
    "closed_loop": [
        Rule("Every reading is signal plus noise, so smooth it with a rolling or median average and act on the "
             "trend, never on a single spike.", LOOP),
        Rule("Judge a reading against limits drawn from the zone's own history: inside them do nothing, and treat "
             "only a point past the limit or a run that is not random as something to act on.", LOOP),
        Rule("Before reacting, check that the reading has left its usual range, for longer than one reading with "
             "the sensors agreeing, and that you know which lever answers it; if any of the three fails, it is "
             "noise.", LOOP),
        Rule("Reacting to every wiggle swings the zone back and forth without settling, so make one decisive "
             "correction only when the signal clearly crosses a limit.", LOOP),
        Rule("When the evidence disagrees, do the safe thing (a small shot, a wait, or a person), preferring a "
             "mild deficit to flooding while always keeping the hard moisture floor.", LAW),
        Rule("Steer to a band around a setpoint rather than to a single number, acting only when the reading "
             "leaves the band.", LOOP),
        Rule("The probe is one opinion checked against a running tally of the water put in and the water used, "
             "so a lying sensor can only push the zone toward caution, never into flooding.", LAW),
        Rule("Every lever moves more than one balance (water, salt, humidity, heat), so name which balance a "
             "change moves, and in which direction, before making it.", LOOP),
        Rule("Fuse several signals before flagging a problem, stay quiet by default, and give every prescribed "
             "change a number and the evidence behind it.", LOOP),
        Rule("Automate small, reversible moves first, such as a three-point dryback nudge behind a confirmation, "
             "and leave expensive or irreversible moves to a person.", LOOP),
        Rule("Sample fast enough to see a shot's response within half an hour but not so fast that jitter "
             "invites over-correction.", LOOP),
    ],
    "slab": [
        Rule("In true water content rockwool is full at about 92 %, works between about 55 and 92 % and passes "
             "its danger line at about 25-30 %, and none of these can be read straight off a probe that "
             "under-reads.", ROCKWOOL),
        Rule("Rockwool holds only about 10 % air when soaked and has almost no buffer, so what is fed is what "
             "the roots get and mistakes show quickly.", LAW),
        Rule("Shot sizes scale with each zone's own substrate volume per plant (its slab share plus its block), "
             "and on the guide's 7.35 L example a 3 % shot is about 220 mL and a 5 % shot about 370 mL.", SLAB),
        Rule("The guide's example block (15 cm) holds about 3.6 L and its 1 m slab about 11.25 L, giving about "
             "7.35 L per plant with three plants to a slab, and a slab of other dimensions changes these "
             "volumes.", SLAB),
        Rule("A single 4 L/h dripper per plant runs about 3.3 minutes for a 3 % shot and 5.5 minutes for a 5 % "
             "shot on 7.35 L, and one dripper per plant is a single point of failure.", SLAB),
        Rule("The slab guide's runoff targets are 8-16 % of the water fed in its vegetative stages and 1-7 % in "
             "its generative ones, caught and measured rather than estimated.", SLAB),
        Rule("Block and slab exchange water only through their contact face, so each block must sit on exposed "
             "slab fibre with no plastic bridging the contact.", SLAB),
        Rule("Fresh transplants that stall on a wet slab usually mean the block itself is dry or out of contact, "
             "so check the block and its roots, not only the slab probe.", SLAB),
        Rule("One plant wilting while its neighbours are fine means a single dripper or local contact fault, "
             "fixed by restoring flow and hand-watering that block with balanced feed.", SLAB),
        Rule("Warm, persistently wet slabs can leave roots short of oxygen, so slab temperature matters alongside "
             "moisture.", SLAB),
        Rule("The slab guide supplies no locally validated setpoints, so its numbers are starting ranges to be "
             "confirmed against this room's own records.", SLAB),
    ],
}


# Athena's Grow Guide Handbook (metric), Precision Irrigation Strategy, pages 33-41: sent by the owner on 28 Sep
# 2026 as more doctrine for Jev. Its rules follow the owner's in each topic (the owner's pages lead, so
# doctrine(..., limit=n) keeps them first), and where they differ the owner's stage arc wins (the last dryback rule).
ATHENA = "Athena Grow Guide Handbook (metric), Precision Irrigation Strategy, pp. 33-41"
SOURCES.append(ATHENA)

_ATHENA_RULES = {
    "ramp": [
        Rule("The day's first shot waits until the plants have been transpiring for about one to two hours after "
             "lights-on, so water goes into a slab that is already drinking.", ATHENA),
        Rule("P1 builds the slab back up with several small shots of about 2-6 % of the substrate spaced 15-30 "
             "minutes apart, because one large shot channels straight through instead of wetting it.", ATHENA),
        Rule("Early in a crop the ramp alone can carry the day until the daily dryback passes about a quarter of "
             "the peak (relative), and only then are maintenance shots added.", ATHENA),
    ],
    "dryback": [
        Rule("Athena states every dryback as a relative change, a share of the peak water content, because points "
             "mean different things in substrates with different field capacities.", ATHENA),
        Rule("Athena's overnight dryback targets are 30-40 % of the peak (relative) for vegetative steering and "
             "40-50 % for generative, the larger one meaning more stress and more compact growth.", ATHENA),
        Rule("After lights-on the slab keeps drying another 1-5 % of the peak (relative) until the first shot, and "
             "that additional dryback is part of the plan, not a missed shot.", ATHENA),
        Rule("Where Athena's relative drybacks and the owner's drybacks in points of true water content differ, "
             "the owner's stage arc leads.", ATHENA),
    ],
    "maintenance": [
        Rule("Maintenance shots hold the peak target through the light period and are the main lever on both the "
             "dryback and the root-zone EC.", ATHENA),
        Rule("As plants grow and dry the slab faster, maintenance shots have to be added to keep the dryback in "
             "its range.", ATHENA),
        Rule("The overnight dryback is sized by the day's last maintenance shots: adding late shots makes it "
             "smaller (vegetative) and removing them makes it larger (generative).", ATHENA),
    ],
    "ec": [
        Rule("Bigger maintenance shots push more runoff and pull root-zone EC down, while smaller shots cut runoff "
             "and let it build, which is EC stacking.", ATHENA),
        Rule("To force runoff the peak target sits between field capacity and full saturation, to restrict it the "
             "peak sits at or below field capacity, and a target above full saturation can never be reached and "
             "only drains.", ATHENA),
        Rule("Athena's runoff targets are 8-16 % of the water fed for vegetative steering and 1-7 % of the water "
             "fed for generative.", ATHENA),
        Rule("During the ramp, pore EC falls when the feed is weaker than the water already in the slab and keeps "
             "falling until runoff starts.", ATHENA),
    ],
    "stage": [
        Rule("Athena's stage table runs veg at EC 3-5 vegetative, flower stretch (weeks 1-4) at EC 4-10 generative "
             "with a 40-50 % relative dryback, flower bulk (weeks 5-7) at EC 3.5-6 vegetative with 30-40 %, and the "
             "finish (weeks 8-9) at EC 3-4 with a generative 40-50 %.", ATHENA),
        Rule("Stretch steers generatively for flower sites and short internodes, bulk steers vegetatively for bud "
             "size, and the finish lowers built-up EC to encourage ripening.", ATHENA),
        Rule("Athena's day climate runs from veg at 22-28 C, 58-75 % RH, VPD 0.8-1.0 kPa and PPFD 300-600 to the "
             "finish at 18-22 C, 50-60 % RH, VPD 1.2-1.4 kPa and PPFD 600-900, and a high root-zone EC burns "
             "plants when the climate is off.", ATHENA),
    ],
    "probe": [
        Rule("The zone's probe goes in a plant that stands for the zone's average moisture, away from fans, walls "
             "and aisles, which dry faster, and a big zone may need several probes read together.", ATHENA),
        Rule("In rockwool the probe sits about 2.5 cm above the bottom of the block.", ATHENA),
        Rule("A probe is checked against caught runoff, whose EC normally reads a little under the root-zone EC "
             "the probe shows.", ATHENA),
    ],
    "closed_loop": [
        Rule("Runoff is caught from two or three average plants per zone on trays, right after the maintenance "
             "shots end, and its volume, EC and pH steer the next day's shots.", ATHENA),
        Rule("Runoff pH a little above the feed's is a healthy sign, and a lower runoff pH points to roots sitting "
             "too wet.", ATHENA),
        Rule("Each cultivar gets its own irrigation zone where possible, because drybacks differ between "
             "cultivars.", ATHENA),
    ],
    "slab": [
        Rule("A smaller substrate dries back faster, which makes the root-zone EC easier to steer.", ATHENA),
    ],
}
for _topic, _rules in _ATHENA_RULES.items():
    RULES[_topic].extend(_rules)


def doctrine(*topics, limit=None):
    """The rules of `topics`, in the order given (a topic named twice is used once), as one paragraph for a
    question's instructions; `limit` keeps the first rules of each topic. An unknown topic is a KeyError."""
    texts = [r.text for t in dict.fromkeys(topics) for r in RULES[t][:limit]]
    return "Doctrine: " + " ".join(texts) if texts else ""


# The owner's chosen stage arc (slab guide, chosen 26 Sep 2026). Day 1 is the first day of 12/12. Dryback is in
# points of TRUE water content; root-zone EC is in mS/cm and compares only with EC read the same way; runoff is
# a share of the water fed. The veg row has no flower days: code picks it by room, not by day.
STAGE_ARC = [
    {"stage": "established veg", "days": None, "steering": "vegetative",
     "peak": "at or above measured field capacity",
     "dryback": "10-15 points of true water content", "dryback_points": (10, 15),
     "pore_ec": "root-zone EC 3-5", "pore_ec_range": (3.0, 5.0),
     "runoff": "8-16 % of the water fed", "runoff_pct": (8, 16),
     "move_on_when": "roots established, uptake repeats day to day, plant ready to flip", "source": SLAB},
    {"stage": "flower setting", "days": (1, 21), "steering": "generative",
     "peak": "at or below field capacity",
     "dryback": ("start near 15 points of true water content and move toward 20-25 over the three weeks; never "
                 "cross the established minimum moisture"), "dryback_points": (15, 25),
     "pore_ec": "root-zone EC 5-10", "pore_ec_range": (5.0, 10.0),
     "runoff": "1-7 % of the water fed", "runoff_pct": (1, 7),
     "move_on_when": "vertical stretch has clearly slowed or stopped", "source": SLAB},
    {"stage": "flower bulk", "days": (22, 42), "steering": "vegetative",
     "peak": "at or above field capacity",
     "dryback": "10-15 points of true water content", "dryback_points": (10, 15),
     "pore_ec": "root-zone EC 3.5-6", "pore_ec_range": (3.5, 6.0),
     "runoff": "8-16 % of the water fed", "runoff_pct": (8, 16),
     "move_on_when": "flower expansion slows and ripening signals dominate", "source": SLAB},
    {"stage": "finish", "days": (43, 56), "steering": "ripening",
     "peak": "at or below field capacity",
     "dryback": ("a generative 20-25 points of true water content to start, deeper only on cultivar data, never "
                 "below the established minimum moisture"), "dryback_points": (20, 25),
     "pore_ec": "lower: root-zone EC 3-4", "pore_ec_range": (3.0, 4.0),
     "runoff": "1-7 % of the water fed unless correcting excess EC", "runoff_pct": (1, 7),
     "move_on_when": "cultivar-specific maturity (trichomes on mid-cola calyxes)", "source": SLAB},
]

# The arc the rockwool and one-law pages give instead. Recorded, not followed: the owner chose STAGE_ARC.
ALT_STAGE_ARC = [
    {"stage": "flower weeks 1-3", "days": (1, 21), "peak": "high (wet, bulking)",
     "dryback": "10-18 points of true water content", "pore_ec": "stepping up", "runoff": "10-15 % of the water fed",
     "source": ROCKWOOL},
    {"stage": "flower weeks 4-6", "days": (22, 42), "peak": "mid",
     "dryback": "20-30 points of true water content, the deepest",
     "pore_ec": "highest (4.5-6.0 in the one-law guide)", "runoff": "15-20 % of the water fed, to flush",
     "source": ROCKWOOL},
    {"stage": "flower weeks 7-8", "days": (43, 56), "peak": "mid, steady",
     "dryback": "18-25 points of true water content, easing", "pore_ec": "easing or as planned",
     "runoff": "maintained", "source": ROCKWOOL},
]

NOMINAL_FLOWER_DAYS = 56  # the slab guide's nominal days: setting 1-21, bulk 22-42, a two-week finish
FINISH_DAYS = 14  # "normally the final 10-14 days": the finish starts this many days before the end


def stage_intent(flower_day, flower_days=NOMINAL_FLOWER_DAYS):
    """A copy of the STAGE_ARC row for a day of flower (day 1 = the first day of 12/12), or None when the day is
    unknown or outside flower. The finish is the last FINISH_DAYS of `flower_days`: a longer cultivar stays in
    the bulk until then, because the guide moves on when ripening signals dominate, not on a date."""
    if flower_day is None or not 1 <= flower_day <= flower_days:
        return None
    _veg, setting, bulk, finish = STAGE_ARC
    start = max(flower_days - FINISH_DAYS + 1, bulk["days"][0])
    if flower_day <= setting["days"][1]:
        return dict(setting)
    if flower_day < start:
        return {**bulk, "days": (bulk["days"][0], start - 1)}
    return {**finish, "days": (start, flower_days)}
