"""crop_steering_engine — the pure, HA-independent crop-steering decision core.

Import the engine anywhere (AppDaemon, a standalone async service, a worker, a test):

    from crop_steering_engine import decide, ZoneParams, ZoneSnapshot
    phase, p2_thr, fire, size, reason = decide(snapshot, params)
"""
from .core import (
    PHASES,
    ZoneParams,
    ZoneSnapshot,
    ec_adjust,
    ec_pid,
    decide,
    pick_sibling,
    feed_grace_ok,
    cross_zone_outliers,
    validate_params,
    zone_safety_status,
    system_safety_status,
    zone_status_label,
)

__all__ = [
    "PHASES", "ZoneParams", "ZoneSnapshot", "ec_adjust", "ec_pid", "decide", "pick_sibling",
    "feed_grace_ok", "cross_zone_outliers", "validate_params",
    "zone_safety_status", "system_safety_status", "zone_status_label",
]
__version__ = "0.1.0"
