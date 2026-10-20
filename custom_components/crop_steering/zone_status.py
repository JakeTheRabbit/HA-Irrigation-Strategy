"""What a zone's status sensor shows: the controller's own label for the zone, or that the controller
is not reporting. Pure (no Home Assistant import), so it is tested directly.

The controller publishes its label on sensor.crop_steering_<prefix>zone_N_status_app, with the reason
as an attribute; the integration's sensor.crop_steering_<prefix>zone_N_status mirrors it and is the
only writer of that entity. It used to compute a label of its own from fixed 40 % / 70 % VWC
thresholds while the controller wrote the same entity with its phase-aware label, so the state
flipped between "Dry - Needs Water" and, say, "Overnight dryback" about twice a minute.
"""

from __future__ import annotations

NOT_REPORTING = "Controller not reporting"
# The same limit as the engine-offline repair (health._STALE_MIN). The controller reports every loop
# (a minute), but a batch of long shots holds its loop, and a zone should not be called unreported
# before the engine itself would be.
STALE_MINUTES = 10
_DEAD = ("unknown", "unavailable", "none", "")


def status_app_entity(prefix: str, zone: int) -> str:
    """The entity the controller publishes a zone's label on."""
    return f"sensor.crop_steering_{prefix}zone_{zone}_status_app"


def mirrored_status(source, now) -> tuple[str, dict]:
    """The zone status to show -> (state, attributes).

    `source` is the zone's status_app State, or None when the controller has never published it;
    `now` is an aware datetime. A controller whose report is older than STALE_MINUTES is not
    reporting. `last_reported` moves on every write, even one that changes nothing, so a label that
    stays the same all afternoon is still fresh; Home Assistant without it falls back to
    `last_updated`.
    """
    if source is None or str(source.state).strip().lower() in _DEAD:
        return NOT_REPORTING, {
            "reason": "The controller has not published a status for this zone"
        }
    seen = getattr(source, "last_reported", None) or getattr(
        source, "last_updated", None
    )
    if seen is None or (now - seen).total_seconds() > STALE_MINUTES * 60:
        return NOT_REPORTING, {
            "reason": f"No report from the controller for more than {STALE_MINUTES} minutes"
        }
    reason = (getattr(source, "attributes", None) or {}).get("reason")
    return str(source.state), ({"reason": reason} if isinstance(reason, str) else {})
