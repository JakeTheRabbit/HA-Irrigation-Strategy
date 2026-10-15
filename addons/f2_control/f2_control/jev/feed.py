"""The Feed task (haiku-brain-design section 5): once a grow-day, an hour after lights-on, in a room whose feed EC sensor
is mapped, the Claude brain is asked whether the room's feed should change. It advises a person and nothing else: a
firm proposal other than keeping the feed becomes a CS-711 card. It never writes a feed, dosing or any other value
(recipe tuning is a person's call). Built like the Alerts judge (triage.py): it runs outside Brain, so it puts its own
"_brain" key in what it asks.
"""
from __future__ import annotations

from . import council
from .judges.base import choice

AFTER_H = 1.0  # asked this long after lights-on, once the morning's first shots have settled
FIRM = 0.6

PROPOSAL = {
    "keep_feed": "The feed suits the room: the zones' pore EC sits near their targets and the feed is in its band.",
    "feed_ec_down_small": "Pore EC runs above the targets across the room's zones while the feed is in its band: a "
                          "small step down in feed EC.",
    "feed_ec_up_small": "Pore EC runs below the targets across the room's zones while the feed is in its band and "
                        "the steering wants it higher: a small step up in feed EC.",
    "feed_ph_out_of_band": "The feed's pH is outside its band: put the pH right before changing anything else.",
    "check_dosing_or_source": "The feed's EC is off its band, not reading, or not what the recipe should make: check "
                              "the dosing and the source water before changing the recipe.",
    "insufficient_evidence": "Not enough readings to judge the feed today.",
}

QUESTIONS = {
    "proposal": [
        choice("You advise a grower on the feed of a whole grow room. Judge only from the feed's readings and each "
               "zone's pore EC against its target. Every zone in the room shares this feed, so one zone off its "
               "target is not a reason to change it.", PROPOSAL),
        choice("Should this room's feed change today? A person decides and makes any change. Propose one only when "
               "the room as a whole shows it, and prefer checking the dosing or the source water when the feed "
               "itself reads wrong.", PROPOSAL),
    ],
}

WORDS = {  # the CS-711 card's first line for each proposal that is one
    "feed_ec_down_small": "The AI assistant proposes a small decrease of the feed EC of this room.",
    "feed_ec_up_small": "The AI assistant proposes a small increase of the feed EC of this room.",
    "feed_ph_out_of_band": "The AI assistant proposes to put the feed pH of this room back in its band.",
    "check_dosing_or_source": "The AI assistant proposes a check of the dosing system and the source water of this "
                              "room before a change to the recipe.",
}


def verdict(ans):
    return council.combine(ans.answers, "proposal")


def proposal(v):
    """The proposal a Verdict makes a card of, or None: both phrasings agree firmly on something other than keeping
    the feed or not knowing."""
    return v.label if v is not None and v.firm(FIRM) and v.label in WORDS else None


class Feed:
    """One question a grow-day per room. `meta(room, now)` is the "_brain" key the Claude route needs."""

    def __init__(self, asker, meta):
        self.asker, self.meta = asker, meta
        self.asked: dict[str, tuple] = {}  # room -> (grow-day, the asker's clock at the ask)
        self.told: dict[str, str] = {}  # room -> the grow-day whose answer was read

    def due(self, room, day):
        return self.asked.get(room, (None, None))[0] != day

    def ask(self, room, day, state, now):
        """Ask for `day` (the room's grow-day) unless it was asked already. True when it was asked now."""
        if not self.due(room, day):
            return False
        at = self.asker.clock()
        if not self.asker.submit(f"feed:{room}", dict(state, _brain=self.meta(room, now)),
                                 council.expand(QUESTIONS)):
            return False  # the budget, a pause or the latch said no: asked again on a later pass today
        self.asked[room] = (day, at)
        return True

    def answer(self, room):
        """The day's answer, once, when it has come in; else None."""
        day, at = self.asked.get(room, (None, None))
        if day is None or self.told.get(room) == day:
            return None
        ans = self.asker.result(f"feed:{room}")
        if ans is None or ans.at < at:
            return None
        self.told[room] = day
        return ans
