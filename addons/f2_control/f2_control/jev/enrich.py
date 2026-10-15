"""The enrichment hook (haiku-brain-design section 2): what a judge's evidence needs before it goes to Claude.

The transport sees only the evidence dict, never the zone's context, so Brain calls `enrich(ctx, judge, ev)` before
every ask under brain_provider claude_haiku (never on the legacy routes, whose payloads stay as they are). It
returns a copy with the probe's entity id replaced by words, `stage_today` dropped (the `stage` block carries it,
from the install's own arc), one site's wording made neutral, the balance judge's verdict for the setpoints judge
(`room_balance`), and a "_brain" key holding the room, zone, judge and time and the numbers, settings, interlocks,
data quality, stage and sibling zones code knows.
"""
from __future__ import annotations

import copy

from . import numbers

PROBE_WORDS = "this zone's moisture probe"
NEUTRAL = (("the owner's doctrine", "the doctrine"), ("the owner's stage arc", "this install's stage arc"),
           ("The owner's", "This install's"), ("the owner's", "this install's"), ("The owner", "The grower"),
           ("the owner", "the grower"))


def neutral(text):
    """`text` with no one site's decision in its wording ("the owner's stage arc" -> "this install's stage arc")."""
    if not isinstance(text, str):
        return text
    for old, new in NEUTRAL:
        text = text.replace(old, new)
    return text


def neutral_all(value):
    if isinstance(value, str):
        return neutral(value)
    if isinstance(value, dict):
        return {k: neutral_all(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [neutral_all(v) for v in value]
    return value


def brain_meta(ctx, judge):
    """The "_brain" key: who is asked about what, when, and the blocks only code can build from the context."""
    b = getattr(ctx, "brain", None) or {}
    return {"room": ctx.room, "zone": ctx.zone, "judge": judge, "asked": ctx.now.isoformat(timespec="minutes"),
            "numbers": numbers.zone_numbers(ctx), "zone_config": numbers.zone_config(ctx),
            "interlocks": b.get("interlocks") or "not known", "data_quality": b.get("data_quality") or "not known",
            "stage": numbers.stage_block(ctx),
            "siblings": {str(z): v for z, v in sorted((ctx.siblings or {}).items())}}


def enrich(ctx, judge, ev):
    out = copy.deepcopy(ev)
    if "probe" in out:
        out["probe"] = PROBE_WORDS
    out.pop("stage_today", None)
    out = neutral_all(out)
    balance = (getattr(ctx, "brain", None) or {}).get("room_balance")
    if judge.name == "setpoints" and balance:
        out["room_balance"] = balance  # the balance judge's verdict: it informs the one writer, never writes
    out["_brain"] = brain_meta(ctx, judge.name)
    return out
