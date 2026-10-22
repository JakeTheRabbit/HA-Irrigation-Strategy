"""Timer programs: validate a program and project it into planned intents. Pure, stdlib only."""

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


def validate(program: dict) -> dict:
    p = dict(program)
    if p.get("type") not in TYPES:
        raise ValueError(f"type must be one of {', '.join(TYPES)}")
    try:
        zones = [int(z) for z in p.get("zones") or []]
    except (TypeError, ValueError):
        raise ValueError("zones must be integers") from None
    if not zones:
        raise ValueError("pick at least one zone")
    p["zones"] = zones
    try:
        p["duration_s"] = float(p.get("duration_s"))
    except (TypeError, ValueError):
        raise ValueError("duration must be a number of seconds") from None
    if p["duration_s"] <= 0:
        raise ValueError("duration must be greater than 0")
    p["active"] = bool(p.get("active", True))
    w = dict(p.get("window") or {"kind": "all"})
    if w.get("kind") not in KINDS:
        raise ValueError(f"window kind must be one of {', '.join(KINDS)}")
    if w["kind"] == "custom":
        if _minutes(w.get("from")) == _minutes(w.get("to")):
            raise ValueError("End must be after start")
    p["window"] = w
    if p.get("sync_time") is not None:
        _minutes(p["sync_time"])
    if p["type"] == "recycle":
        try:
            p["interval_min"] = float(p.get("interval_min"))
        except (TypeError, ValueError):
            raise ValueError("interval must be a number of minutes") from None
        if p["interval_min"] <= 0:
            raise ValueError("interval must be greater than 0")
    elif p["type"] == "simple":
        try:
            p["frequency_per_day"] = int(p.get("frequency_per_day"))
        except (TypeError, ValueError):
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
    p = validate(program)
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
