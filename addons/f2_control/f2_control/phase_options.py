"""Opt-in phase settings that the controller reads around the engine: the P2 mode select, the daily limit on how
far the automatic writers move the moisture ladder, and the latch of an EC flush episode.

Pure helpers, no Home Assistant: the controller reads the entities and passes their states in. Every default is
the rule as it was, so an integration that has none of these entities waters exactly as before."""

import math

# The zone's P2 mode select (integration const.P2_MODES) -> the engine's ZoneParams.p2_mode.
P2_MODE_OPTIONS = {"Moisture": "moisture", "Timed": "timed", "Timed with guards": "timed_guarded"}
# The room's select of which writers the daily setpoint limit holds; this option adds the AI assistant's targets
# power and the Auto setpoints learner to the follower of the highest readings.
STEP_SCOPE_ALL = "Auto setpoints and AI"
# The EC rules whose shot opens a flush episode (ZoneSnapshot.ec_flushing).
FLUSH_KINDS = frozenset({"flush_high_ec", "p0_ec_flush", "p2_rescue", "p2_dilute"})


def p2_mode(state):
    """The engine's p2_mode for the select's state: moisture for a missing or unknown one."""
    return P2_MODE_OPTIONS.get(state, "moisture")


def step_limit(value, fallback):
    """The daily limit in VWC points for the number's value: `fallback` when it cannot be read, no limit at 0."""
    if value is None or not math.isfinite(value) or value < 0:
        return fallback
    return math.inf if value == 0 else value


def step_left(follow, day, suffix, limit):
    """What is left of grow-day `day`'s allowance for `suffix` on the follower's ledger (st["fc_follow"]), which is
    started afresh on a new grow-day."""
    if follow.get("day") != day:
        follow.update(day=day, used={})
    return max(0.0, limit - (follow["used"].get(suffix) or 0.0))


def step_used(follow, suffix, points):
    follow["used"][suffix] = round((follow["used"].get(suffix) or 0.0) + abs(points), 1)


def clamp_step(old, value, left):
    """`value` no further from `old` than `left`."""
    return round(max(old - left, min(old + left, value)), 2)


def flushing(was, target, fired_kind, ec_settled, goal):
    """The flush episode latch after this pass: opened by a fired EC flush while a target is set, closed once the
    settled pore EC is at or under the goal (core.ec_flush_goal), or when the target is switched off."""
    if not target or target <= 0:
        return False
    if fired_kind in FLUSH_KINDS:
        was = True
    if was and ec_settled is not None and goal is not None and ec_settled <= goal:
        return False
    return bool(was)
