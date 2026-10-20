"""What the AI assistant may do in a room: its powers, one switch each (docs/AI_ASSISTANT.md, "Powers").

The owner ticks what the AI assistant may change. A power that is off leaves its judge asking and advising (the
journal and the panel show what it would do), and the envelope refuses to act on it. The integration names the
same keys and defaults (custom_components/crop_steering/const.py AI_POWERS); a missing switch (an integration from
before the powers) is its default, so an install updated in place does exactly what it did before.
"""
from __future__ import annotations

# (key, default, which directives it gates in words)
POWERS = (
    ("advance_phase", True, "start the morning ramp or the night dryback early (dawn, dusk)"),
    ("ramp_control", True, "end the morning ramp (ramp)"),
    ("set_probe_aside", True, "set a probe aside (probe)"),
    ("ec_mode", True, "choose the EC steer's mode (salt)"),
    ("nudge_setpoints", True, "move the maintenance shot size or re-water point one notch (setpoints)"),
    ("plan_catch_up", True, "apply today's plan day while a stale probe holds it (plan)"),
    ("set_targets_from_achievable", False, "set a zone's field capacity, peak target, re-water point, rescue floor "
     "and dryback target itself (targets)"),
    ("tune_shot_sizes", False, "set a zone's ramp and maintenance shot sizes itself (shotsize)"),
)
DEFAULTS = {key: default for key, default, _words in POWERS}
WORDS = {key: words for key, _default, words in POWERS}


def entity(prefix, key):
    return f"switch.crop_steering_{prefix}ai_power_{key}"


def power_of(d):
    """The power a directive needs, or None for one that never acts (an alert, a push)."""
    if d.kind == "advance":
        return "ramp_control" if d.judge == "ramp" else "advance_phase"
    return {"distrust": "set_probe_aside", "ec_mode": "ec_mode", "setpoint": "nudge_setpoints",
            "catch_up": "plan_catch_up", "targets": "set_targets_from_achievable",
            "shot_size": "tune_shot_sizes"}.get(d.kind)


def allowed(powers, key):
    """Whether the room's `powers` ({key: on}, None when not read) give `key`; unread or missing is the default."""
    if key is None:
        return True
    value = (powers or {}).get(key)
    return DEFAULTS.get(key, False) if value is None else bool(value)


def read(on, prefix):
    """{key: on} for a room, read through `on(entity_id, default)` (the controller's switch read)."""
    return {key: bool(on(entity(prefix, key), default)) for key, default, _words in POWERS}


def published(powers):
    """The brain sensor's `powers`: every power in order with whether it is on and its default."""
    return [{"key": key, "on": allowed(powers, key), "default": default} for key, default, _words in POWERS]
