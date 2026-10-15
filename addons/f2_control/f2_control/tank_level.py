"""A room's tank level (docs/USER_GUIDE.md, "Tank level"), and the drawdown check that tells a stuck sensor.

The level comes from a distance sensor (the distance down to the water, through the device-unit table) turned
into a percentage by the room's full and empty distances, and/or from a low-level float. Nothing here switches
anything.

The drawdown check. A level sensor is trusted unless it is unavailable: ESPHome sends a reading only when it
changes, so a quiet tank's sensor goes hours without an update and a staleness timeout would raise false alarms.
What a timeout was meant to catch is a sensor stuck reading high while the tank drains, which would leave a
pump to run the tank dry. So the litres the shots draw are counted against the level's fall. Each time the
level falls far enough, the litres drawn per 1 % of level are learned from it; once they are known, shots that
should have lowered the level by DRAWDOWN_PCT or more while it moved less than a quarter of that mean the sensor
is stuck, and its level is not trusted until it moves again. A rise (a refill) starts the count again.

Pure: the state is a plain dict the controller keeps in /data/state.json (the room's `_tank` block).
"""

LEARN_PCT = 5.0  # a fall at least this big teaches the litres per 1 %
RISE_PCT = 2.0  # a rise at least this big is a refill: the count starts again
DRAWDOWN_PCT = 5.0  # shots that should have lowered the level this much are enough to judge
STUCK_SHARE = 0.25  # ...and a level that fell less than this share of it is stuck
LEARN_WEIGHT = 0.3  # how much a new fall moves the learned litres per 1 %


def mapping(attrs):
    """The tank level a room descriptor maps: {"distance", "full_mm", "empty_mm", "float", "float_low_state"},
    with what is not mapped left out. {} when nothing is, or the levels are unusable (the integration checks
    them at mapping, so only a hand-edited descriptor gets here)."""
    attrs = attrs or {}
    level = attrs.get("tank_level") if isinstance(attrs.get("tank_level"), dict) else {}
    out = {}
    distance = attrs.get("tank_distance_sensor")
    full, empty = level.get("full_mm"), level.get("empty_mm")
    if (
        isinstance(distance, str)
        and distance
        and all(type(x) in (int, float) for x in (full, empty))
        and 0 <= full < empty
    ):
        out.update(distance=distance, full_mm=float(full), empty_mm=float(empty))
    if isinstance(attrs.get("tank_low_float"), str) and attrs["tank_low_float"]:
        out["float"] = attrs["tank_low_float"]
        out["float_low_state"] = "off" if level.get("float_low_state") == "off" else "on"
    return out


def percent(distance_mm, full_mm, empty_mm):
    """The level, 0 % empty to 100 % full, from the distance down to the water. Not clipped: a tank filled
    past its full mark reads over 100 %."""
    return (empty_mm - distance_mm) / (empty_mm - full_mm) * 100.0


def fresh():
    return {"base_pct": None, "litres": 0.0, "litres_per_pct": None, "stuck": False}


def load(saved):
    """A saved `_tank` block, or fresh when there is none (every install before this) or it is unreadable."""
    state = fresh()
    if not isinstance(saved, dict):
        return state
    for key in ("base_pct", "litres_per_pct"):
        value = saved.get(key)
        if type(value) in (int, float) and value == value:
            state[key] = float(value)
    litres = saved.get("litres")
    if type(litres) in (int, float) and litres == litres and litres >= 0:
        state["litres"] = float(litres)
    if state["litres_per_pct"] is not None and state["litres_per_pct"] <= 0:
        state["litres_per_pct"] = None
    state["stuck"] = saved.get("stuck") is True
    return state


def drawn(state, litres):
    """A shot drew `litres` from the tank."""
    if state["base_pct"] is not None and litres > 0:
        state["litres"] += litres


def observe(state, level_pct):
    """Count one level reading. True when the level can be trusted, False when the shots say it is stuck."""
    base = state["base_pct"]
    if base is None or level_pct >= base + RISE_PCT:
        state.update(base_pct=level_pct, litres=0.0, stuck=False)
        return True
    fall = base - level_pct
    if fall >= LEARN_PCT:
        if state["litres"] > 0:
            sample = state["litres"] / fall
            known = state["litres_per_pct"]
            state["litres_per_pct"] = (
                sample if known is None else known + LEARN_WEIGHT * (sample - known)
            )
        state.update(base_pct=level_pct, litres=0.0, stuck=False)
        return True
    known = state["litres_per_pct"]
    if known:
        expected = state["litres"] / known
        if expected >= DRAWDOWN_PCT and fall < expected * STUCK_SHARE:
            state["stuck"] = True
    return not state["stuck"]
