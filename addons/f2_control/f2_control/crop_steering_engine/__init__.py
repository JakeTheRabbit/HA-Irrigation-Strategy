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
    waiting_for,
    pick_sibling,
    feed_grace_ok,
    cross_zone_outliers,
    validate_params,
    detect_vmax,
    zone_safety_status,
    system_safety_status,
    zone_status_label,
)

__all__ = [
    "CAP_EXEMPT", "EC_SETTLE_MIN", "Reason",
    "PHASES", "ZoneParams", "ZoneSnapshot", "ec_adjust", "ec_pid", "decide", "waiting_for", "pick_sibling",
    "feed_grace_ok", "cross_zone_outliers", "validate_params", "detect_vmax",
    "zone_safety_status", "system_safety_status", "zone_status_label",
]
__version__ = "0.1.0"
