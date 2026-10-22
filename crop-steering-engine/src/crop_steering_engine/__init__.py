"""crop_steering_engine — the pure, HA-independent crop-steering decision core.

Import the engine anywhere (the f2-control add-on, a standalone service, a worker, a test):

    from crop_steering_engine import decide, ZoneParams, ZoneSnapshot
    phase, p2_thr, fire, size, reason = decide(snapshot, params)
"""
from .core import (
    CAP_EXEMPT,
    EC_SETTLE_MIN,
    PHASES,
    Reason,
    ZoneParams,
    ZoneSnapshot,
    ec_adjust,
    ec_pid,
    decide,
    p0_dryback,
    p0_stalled,
    ec_flush_goal,
    p2_timed_size,
    next_shot_size,
    waiting_for,
    pick_sibling,
    feed_grace_ok,
    cross_zone_outliers,
    validate_params,
    detect_vmax,
    settled_reading,
    zone_safety_status,
    system_safety_status,
    zone_status_label,
)

from .ids import ULID_RE, derived_id, new_id
from .timers import PlannedIntent, project as project_timer_program, validate as validate_timer_program

__all__ = [
    "ULID_RE", "derived_id", "new_id", "PlannedIntent", "project_timer_program", "validate_timer_program",
    "CAP_EXEMPT", "EC_SETTLE_MIN", "Reason",
    "PHASES", "ZoneParams", "ZoneSnapshot", "ec_adjust", "ec_pid", "decide", "p0_dryback", "p0_stalled", "ec_flush_goal", "p2_timed_size", "waiting_for", "pick_sibling",
    "feed_grace_ok", "cross_zone_outliers", "validate_params", "detect_vmax", "settled_reading",
    "next_shot_size",
    "zone_safety_status", "system_safety_status", "zone_status_label",
]
__version__ = "0.1.0"
