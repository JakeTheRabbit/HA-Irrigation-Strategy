"""Timer programs: validate a program and project it into planned intents. Pure, stdlib only."""

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

TYPES = ("one_off", "recycle", "simple")
KINDS = ("all", "lights_on", "lights_off", "custom")


@dataclass(frozen=True)
class PlannedIntent:
    program_id: str
    zone: int
    at: datetime
    duration_s: float


def _minutes(hhmm) -> float:
    try:
        h, m = str(hhmm).split(":")
        v = int(h) * 60 + int(m)
    except ValueError:
        raise ValueError(f"time must be HH:MM, got {hhmm!r}") from None
    if not 0 <= v < 1440:
        raise ValueError(f"time must be HH:MM, got {hhmm!r}")
    return float(v)


def _finite(value, what) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(what) from None
    if not math.isfinite(v):
        raise ValueError(what)
    return v


def validate(program: dict, lights: tuple[float, float] | None = None) -> dict:
    """The program as stored, or ValueError in plain words. With the room's lights (on, off hours) a
    sync time is also checked against a lights window; without them only a custom window is.
    """
    p = dict(program)
    if p.get("type") not in TYPES:
        raise ValueError(f"type must be one of {', '.join(TYPES)}")
    try:
        zones = [int(z) for z in p.get("zones") or []]
    except (TypeError, ValueError, OverflowError):
        raise ValueError("zones must be integers") from None
    if not zones:
        raise ValueError("pick at least one zone")
    p["zones"] = list(dict.fromkeys(zones))
    p["duration_s"] = _finite(
        p.get("duration_s"), "duration must be a number of seconds"
    )
    if p["duration_s"] <= 0:
        raise ValueError("duration must be greater than 0")
    p["active"] = p.get("active", True)
    if type(p["active"]) is not bool:
        raise ValueError("active must be true or false")
    w = p.get("window") or {"kind": "all"}
    if not isinstance(w, dict):
        raise ValueError('window must be an object such as {"kind": "all"}')
    w = dict(w)
    if w.get("kind") not in KINDS:
        raise ValueError(f"window kind must be one of {', '.join(KINDS)}")
    if w["kind"] == "custom":
        if _minutes(w.get("from")) == _minutes(w.get("to")):
            raise ValueError("End must be after start")
    p["window"] = w
    if p.get("sync_time") is not None:
        _minutes(p["sync_time"])
    if p["type"] == "recycle":
        p["interval_min"] = _finite(
            p.get("interval_min"), "interval must be a number of minutes"
        )
        if p["interval_min"] < 1:
            raise ValueError("interval must be at least 1 minute")
        if p.get("sync_time") is not None and (w["kind"] == "custom" or lights):
            w_from, length = _window(w, lights or (0, 0))
            if (_minutes(p["sync_time"]) - w_from) % 1440 >= length:
                raise ValueError("sync time must be inside the window")
    elif p["type"] == "simple":
        try:
            p["frequency_per_day"] = int(p.get("frequency_per_day"))
        except (TypeError, ValueError, OverflowError):
            raise ValueError("frequency must be a whole number per day") from None
        if p["frequency_per_day"] < 1:
            raise ValueError("frequency must be at least 1 per day")
    else:
        try:
            datetime.fromisoformat(str(p.get("start_at")))
        except ValueError:
            raise ValueError("start_at must be an ISO datetime") from None
    return p


def _window(w: dict, lights: tuple[float, float]) -> tuple[float, float]:
    """(start, length) in minutes from local midnight. A window ending at/before its start crosses midnight."""
    on, off = lights[0] * 60, lights[1] * 60
    kind = w["kind"]
    if kind == "all":
        return 0.0, 1440.0
    if kind == "lights_on":
        a, b = on, off
    elif kind == "lights_off":
        a, b = off, on
    else:
        a, b = _minutes(w["from"]), _minutes(w["to"])
    return a, (b - a) % 1440 or 1440.0


def project(
    program: dict, lights: tuple[float, float], start: datetime, end: datetime
) -> list[PlannedIntent]:
    p = validate(program, lights)
    if not p["active"]:
        return []
    tz = start.tzinfo
    end = end.astimezone(tz)
    pid = str(p.get("id", ""))

    def emit(at: datetime):
        if start <= at < end:
            for z in p["zones"]:
                out.append(PlannedIntent(pid, z, at, p["duration_s"]))

    out: list[PlannedIntent] = []
    if p["type"] == "one_off":
        at = datetime.fromisoformat(str(p["start_at"]))
        emit(at if at.tzinfo else at.replace(tzinfo=tz))
        return sorted(out, key=lambda i: (i.at, i.zone))

    w_from, length = _window(p["window"], lights)
    if p["type"] == "recycle":
        first = 0.0
        if p.get("sync_time") is not None:
            first = (_minutes(p["sync_time"]) - w_from) % 1440
        offsets = []
        t = first
        while t < length:
            offsets.append(t)
            t += p["interval_min"]
    else:
        offsets = [
            i * length / p["frequency_per_day"] for i in range(p["frequency_per_day"])
        ]

    day = start.date() - timedelta(days=1)
    while day <= end.date():
        base = datetime(day.year, day.month, day.day) + timedelta(minutes=w_from)
        for off in offsets:
            naive = base + timedelta(minutes=off)
            at = naive.replace(tzinfo=tz)
            # a wall time that does not exist (DST gap) changes when round-tripped through UTC
            if at.astimezone(UTC).astimezone(tz).replace(tzinfo=None) != naive:
                continue
            emit(at)
        day += timedelta(days=1)
    return sorted(out, key=lambda i: (i.at, i.zone))
