"""Opt-in safety and operations helpers: rescue shots that do not raise the moisture, and a tank level
estimated from the water the shots used. PURE: plain dicts the controller keeps in /data/state.json.

Rescue shots that are not absorbed (CS-315). A rescue (a P3 emergency or a lights-on watchdog shot) that does
not raise the zone's settled moisture is a miss: a blocked dripper or line, or a probe that no longer sits in
the substrate. A run of misses only ever tells; nothing here holds water. Each rescue keeps the moisture it
started from; it is judged RESCUE_SETTLE_MIN after the shot, or at the next rescue if that comes sooner.

The estimated tank level. A room with no tank level sensor can give its tank's size: each shot's litres are
counted from the last time the tank was filled (its Tank filled button, or a batch that filled it), and the
level is size less litres used. It is an estimate from configured flow, never a measurement, so it only ever
alerts: it never holds a shot.
"""

from datetime import datetime

RESCUE_KINDS = frozenset({"p3_emergency", "watchdog"})
RESCUE_SETTLE_MIN = 15.0  # a rescue is judged on the moisture this long after it
RESCUE_MIN_RISE = 0.5  # VWC points a rescue must lift the moisture by to count as absorbed
RESCUE_MISS_DEFAULT = 4  # misses in a row before CS-315, when the room's number can't be read
TANK_LOW_DEFAULT = 20.0  # % of the estimated tank at or under which CS-905 tells, when its number can't be read


def rescue_fired(st, vwc_before, now):
    """Remember a rescue shot that was delivered, and the moisture it started from."""
    try:
        before = float(vwc_before)
    except (TypeError, ValueError):
        return
    st["rescue_check"] = {"before": before, "at": now.isoformat()}


def rescue_judge(st, vwc_now, now, *, early=False):
    """Judge the zone's last rescue on the moisture now -> True (a miss), False (absorbed) or None (nothing to
    judge yet). `early`: another rescue is about to fire, so the last one is judged before it has settled."""
    check = st.get("rescue_check")
    if not isinstance(check, dict):
        return None
    try:
        before, at = float(check["before"]), datetime.fromisoformat(check["at"])
        waited = (now - at).total_seconds()
        rise = float(vwc_now) - before
    except (KeyError, TypeError, ValueError):
        st["rescue_check"] = None
        return None
    if not early and waited < RESCUE_SETTLE_MIN * 60:
        return None
    st["rescue_check"] = None
    if rise >= RESCUE_MIN_RISE:
        st["rescue_misses"] = 0
        return False
    st["rescue_misses"] = int(st.get("rescue_misses") or 0) + 1
    return True


def restore_zone(d):
    """The two rescue keys from a saved zone, tolerant of an old file without them."""
    out = {}
    misses = (d or {}).get("rescue_misses")
    if type(misses) is int and 0 <= misses <= 10000:
        out["rescue_misses"] = misses
    check = (d or {}).get("rescue_check")
    if isinstance(check, dict) and isinstance(check.get("at"), str):
        try:
            out["rescue_check"] = {"before": float(check["before"]), "at": check["at"]}
        except (KeyError, TypeError, ValueError):
            pass
    return out


def tank_fresh():
    """No fill seen yet: the estimate is unknown until the tank is marked filled."""
    return {"filled_at": None, "used_l": 0.0}


def tank_load(saved):
    """The room's saved `_tank_estimate` block, or a fresh one (an old file has none)."""
    out = tank_fresh()
    if isinstance(saved, dict):
        if isinstance(saved.get("filled_at"), str):
            out["filled_at"] = saved["filled_at"]
        try:
            used = float(saved.get("used_l"))
            if used >= 0 and used == used:
                out["used_l"] = used
        except (TypeError, ValueError):
            pass
    return out


def tank_filled(estimate, at):
    """The tank was filled at `at` (an ISO time): the count starts again. False when `at` is not newer."""
    if not isinstance(at, str) or not at or at == estimate.get("filled_at"):
        return False
    try:
        new = datetime.fromisoformat(at.replace("Z", "+00:00"))
        old = estimate.get("filled_at")
        if old and new <= datetime.fromisoformat(old.replace("Z", "+00:00")):
            return False
    except (TypeError, ValueError):
        return False
    estimate.update(filled_at=at, used_l=0.0)
    return True


def tank_used(estimate, litres):
    """A shot's litres taken from the tank, counted only once a fill has been seen."""
    if estimate.get("filled_at") and litres and litres > 0:
        estimate["used_l"] = float(estimate.get("used_l") or 0.0) + float(litres)


def tank_percent(estimate, size_l):
    """-> (percent, litres left), or (None, None) before the first fill is seen."""
    if not estimate.get("filled_at") or not size_l or size_l <= 0:
        return None, None
    left = max(0.0, size_l - float(estimate.get("used_l") or 0.0))
    return round(left / size_l * 100.0, 1), round(left, 1)
