"""What a judge sees: one zone's recent history, and code-made facts about it in plain words.

Jev cannot do arithmetic, so no raw series ever reaches it. `ZoneHistory` keeps the last day of readings
and shots; the helpers below turn them into sentences ("rose 3.1 points after the 10:40 shot and held
2.8"), which is what goes into a judge's evidence.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

SETTLE_MIN = 20.0  # a shot's retained rise is read this long after it (the free-water spike is gone)
PEAK_WINDOW_MIN = 10.0  # the spike: the highest reading this soon after a shot


@dataclass
class Shot:
    start: datetime
    seconds: float
    litres: float
    kind: str
    pre_vwc: float | None
    pre_ec: float | None


class ZoneHistory:
    """The last `hours` of readings (one per loop) and shots for one zone."""

    def __init__(self, hours=26):
        self.readings: deque = deque(maxlen=int(hours * 60) + 10)  # (t, vwc, ec)
        self.shots: deque = deque(maxlen=60)

    def add_reading(self, t, vwc, ec):
        if vwc is not None:
            self.readings.append((t, float(vwc), None if ec is None else float(ec)))

    def add_shot(self, shot: Shot):
        self.shots.append(shot)

    def since(self, t):
        return [r for r in self.readings if r[0] >= t]

    def at(self, t, tolerance_min=3.0):
        """The reading nearest to `t` within the tolerance, or None."""
        best = None
        for r in self.readings:
            gap = abs((r[0] - t).total_seconds()) / 60.0
            if gap <= tolerance_min and (best is None or gap < best[0]):
                best = (gap, r)
        return best[1] if best else None


@dataclass
class ShotResponse:
    shot: Shot
    peak_rise: float | None  # highest VWC within PEAK_WINDOW_MIN minus the pre-shot reading
    retained: float | None  # VWC SETTLE_MIN after the shot minus the pre-shot reading
    ec_move: float | None  # EC at SETTLE_MIN minus pre-shot EC
    settled: bool  # SETTLE_MIN has passed


def response(history: ZoneHistory, shot: Shot, now: datetime) -> ShotResponse:
    """How the probe answered one shot, in points, from the readings code already has."""
    end = shot.start + timedelta(seconds=shot.seconds)
    settled = now >= end + timedelta(minutes=SETTLE_MIN)
    window = [r for r in history.readings if end <= r[0] <= end + timedelta(minutes=PEAK_WINDOW_MIN)]
    peak = max((r[1] for r in window), default=None)
    later = history.at(end + timedelta(minutes=SETTLE_MIN)) if settled else None
    pre_v, pre_e = shot.pre_vwc, shot.pre_ec
    return ShotResponse(
        shot,
        None if peak is None or pre_v is None else round(peak - pre_v, 2),
        None if later is None or pre_v is None else round(later[1] - pre_v, 2),
        None if later is None or later[2] is None or pre_e is None else round(later[2] - pre_e, 2),
        settled,
    )


def trend(history: ZoneHistory, now: datetime, minutes: float, index: int = 1):
    """Change per hour of VWC (index 1) or EC (index 2) over the last `minutes`, or None."""
    pts = [r for r in history.since(now - timedelta(minutes=minutes)) if r[index] is not None]
    if len(pts) < 3:
        return None
    (t0, *a), (t1, *b) = pts[0], pts[-1]
    hours = (t1 - t0).total_seconds() / 3600.0
    if hours <= 0:
        return None
    return round((b[index - 1] - a[index - 1]) / hours, 2)


def flat_minutes(history: ZoneHistory, now: datetime, tolerance=0.05):
    """How long VWC has read the same value (within `tolerance` points), in minutes."""
    pts = list(history.readings)
    if not pts:
        return 0.0
    last = pts[-1][1]
    start = pts[-1][0]
    for t, v, _ in reversed(pts):
        if abs(v - last) > tolerance:
            break
        start = t
    return round((now - start).total_seconds() / 60.0, 1)


def words_trend(per_hour, unit="points", what="VWC"):
    if per_hour is None:
        return f"{what} trend unknown (too few readings)"
    if abs(per_hour) < 0.05:
        return f"{what} flat"
    return f"{what} {'rising' if per_hour > 0 else 'falling'} {abs(per_hour):.2f} {unit} an hour"


def words_response(r: ShotResponse, typical_rise=None):
    """One shot's response in a sentence, labelled against the zone's typical retained rise."""
    s = r.shot
    head = f"{s.start:%H:%M} {s.kind} shot of {s.seconds:.0f} s ({s.litres:.1f} L)"
    if not r.settled:
        return f"{head}: still settling"
    if r.retained is None:
        return f"{head}: no reading to judge it by"
    tag = ""
    if typical_rise:
        ratio = r.retained / typical_rise if typical_rise else 0
        tag = (" (normal)" if ratio >= 0.6 else " (weak)" if ratio >= 0.25 else " (almost nothing)")
    spike = "" if r.peak_rise is None else f", spiked +{r.peak_rise:.1f} first"
    ec = "" if r.ec_move is None else f", EC {r.ec_move:+.2f}"
    return f"{head}: retained {r.retained:+.1f} points{tag}{spike}{ec}"


@dataclass
class ZoneContext:
    """Everything one judge may look at for one zone on one pass. Built by the controller."""
    room: str
    prefix: str
    zone: int
    title: str
    now: datetime
    phase: str
    snap: object | None  # crop_steering_engine.ZoneSnapshot (None: no usable probe)
    params: object  # crop_steering_engine.ZoneParams
    history: ZoneHistory
    lights_on: bool
    hours_to_on: float
    hours_to_off: float
    siblings: dict = field(default_factory=dict)  # zone -> {"litres_per_plant", "vwc", "ec", "phase", "rise"}
    plants: int | None = None
    feed_ec: float | None = None
    track: dict = field(default_factory=dict)  # judge -> "their last calls and how they turned out"
    probe_entity: str = ""
    flower_day: int | None = None  # day of flower (day 1 = the first day of 12/12), when the room says
    flower_days: int = 56  # the cultivar's flowering length
    stage: dict | None = None  # doctrine.stage_intent(flower_day): the owner's stage arc row for today
    steering: str | None = None  # the operator's steering mode for the zone: "vegetative" or "generative"
    # What the Setpoints judge may move tonight (jev_bridge.setpoint_view): {"enabled", "current", "home", "bands",
    # "changed_today", "frozen", "day", "last_words"}; None when the room has no setpoint memory.
    setpoints: dict | None = None

    @property
    def since_lights_min(self):
        """Minutes since the lights last switched (on while on, off while off)."""
        hours = self.hours_to_on if self.lights_on else self.hours_to_off
        return round((24.0 - hours) * 60.0) % 1440

    def typical_rise(self):
        """The median retained rise of this zone's settled shots today, or None."""
        rises = sorted(r.retained for r in (response(self.history, s, self.now) for s in self.history.shots)
                       if r.settled and r.retained is not None and r.retained > 0)
        return rises[len(rises) // 2] if rises else None
