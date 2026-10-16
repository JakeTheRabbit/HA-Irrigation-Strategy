"""Light dimming on dry substrate: an opt-in protective action for one room (docs/DOSING.md, Light dimming).

The controller's only light actuation. While the room's dry_dim switch and its kill switch are on, the lights
are on by schedule and by the light's own state, and a counted zone has read under the floor for after_min,
the room's light is dimmed to level_pct. It only ever dims: never off, never below MIN_LEVEL_PCT, never
above the brightness it found. Counted zones are the live, enabled zones with a usable fused reading: a
blind zone, a dead probe, or a probe reading under DEAD_VWC (a dead probe looks like a dry pot) never counts.

The brightness it found is kept in state.json (the room's `_dim`), so it is restored, never guessed at:
when every counted zone reads floor + RECOVER_PTS for RECOVER_MIN, when the switch or the kill switch goes
off, RESTORE_BEFORE_OFF_MIN before the schedule's lights-off (or at it), after max_h (with a critical alert:
a dimmed room is a fault too), and on the first pass after a restart. A light someone else changes while
dimmed is left to them: the record is dropped and a person is told, never fought over.

The decisions are pure (Dimmer.step returns what to do); the controller reads and writes Home Assistant.
"""
from __future__ import annotations

import math
from datetime import datetime

MIN_LEVEL_PCT = 30.0  # never dimmed below this, whatever the setting says
DEAD_VWC = 1.0  # a reading under this is a dead probe, not a dry pot
RECOVER_PTS = 3.0  # every counted zone this far over the floor ...
RECOVER_MIN = 10.0  # ... for this long restores the light
RESTORE_BEFORE_OFF_MIN = 5.0  # restored this long before the schedule's lights-off, while the light is still on
TOLERANCE = 3  # brightness (0-255) a read-back may differ by

# The room's settings (number.crop_steering_<prefix>dry_dim_<key>): key -> (default, low, high).
SETTINGS = {
    "floor_vwc": (15.0, 1.0, 60.0),  # % VWC
    "level_pct": (50.0, MIN_LEVEL_PCT, 90.0),  # % brightness
    "after_min": (10.0, 1.0, 120.0),  # minutes under the floor before dimming
    "max_h": (4.0, 0.5, 12.0),  # the longest the room stays dimmed
}


def setting(value, key):
    default, low, high = SETTINGS[key]
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return default
    return min(high, max(low, float(value)))


def dimmable(state, attributes):
    """Whether a light entity can be dimmed: it reports a brightness, or a colour mode other than on/off."""
    attributes = attributes or {}
    modes = attributes.get("supported_color_modes")
    if isinstance(modes, (list, tuple)) and any(m != "onoff" for m in modes):
        return True
    return isinstance(attributes.get("brightness"), (int, float))


def brightness(attributes):
    value = (attributes or {}).get("brightness")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return int(round(value))


def counted(readings):
    """The zones that count: {zone: vwc} with a usable reading (dead probes out)."""
    return {z: v for z, v in readings.items()
            if isinstance(v, (int, float)) and math.isfinite(v) and v >= DEAD_VWC}


class Dimmer:
    """One room's dimming decisions, pass by pass. `record` is the persisted dim (None when not dimmed):
    {"light", "was", "set", "since"}. The clocks for dry and recovered are kept here, in memory."""

    def __init__(self, restarted=False):
        self.dry_since = None
        self.ok_since = None
        self.restarted = restarted  # a record loaded at start is restored on the first pass

    def step(self, record, *, now, enabled, allowed, lights_on, to_off_min, light, state, attributes,
             readings, s):
        """-> (action, why): ("dim", target brightness), ("restore", why), ("drop", why) or (None, None)."""
        zones = counted(readings)
        if record is not None:
            self.dry_since = None
            if self.restarted:
                self.restarted = False
                return "restore", "the controller restarted"
            if state in (None, "unavailable", "unknown", ""):
                return None, None  # can't be read now: tried again next pass (max_h still counts)
            if state != "on":
                return "drop", "the light was switched off while it was dimmed"
            now_b = brightness(attributes)
            if now_b is None or abs(now_b - record["set"]) > TOLERANCE:
                return "drop", "something else changed the light while it was dimmed"
            since = _when(record.get("since"))
            if not enabled:
                return "restore", "dimming was switched off"
            if not allowed:
                return "restore", "the room's kill switch is off"
            if not lights_on or to_off_min <= RESTORE_BEFORE_OFF_MIN:
                return "restore", "the lights go off"
            if since is not None and (now - since).total_seconds() >= s["max_h"] * 3600:
                return "restore", "max"
            if light != record.get("light"):
                return "restore", "the room's light was changed in setup"
            if zones and all(v >= s["floor_vwc"] + RECOVER_PTS for v in zones.values()):
                self.ok_since = self.ok_since or now
                if (now - self.ok_since).total_seconds() >= RECOVER_MIN * 60:
                    return "restore", "the substrate is wet again"
            else:
                self.ok_since = None
            return None, None
        self.restarted = False
        self.ok_since = None
        dry = [z for z, v in zones.items() if v < s["floor_vwc"]]
        if not (enabled and allowed and lights_on and dry and to_off_min > RESTORE_BEFORE_OFF_MIN):
            self.dry_since = None
            return None, None
        self.dry_since = self.dry_since or now
        if (now - self.dry_since).total_seconds() < s["after_min"] * 60:
            return None, None
        if not light or not light.startswith("light.") or state != "on" or not dimmable(state, attributes):
            return None, None
        now_b = brightness(attributes)
        target = int(round(max(s["level_pct"], MIN_LEVEL_PCT) / 100 * 255))
        if now_b is None or now_b <= target:
            return None, None  # only ever dims: never brighter than it found
        return "dim", target


def _when(stamp):
    try:
        return datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None


def load(value):
    """The persisted dim from state.json, or None (absent from older files, or unreadable)."""
    if not isinstance(value, dict):
        return None
    light, was, done = value.get("light"), value.get("was"), value.get("set")
    if not (isinstance(light, str) and light.startswith("light.")):
        return None
    if not all(type(x) is int and 0 < x <= 255 for x in (was, done)):
        return None
    return {"light": light, "was": was, "set": done, "since": value.get("since") if isinstance(value.get("since"), str) else None}
