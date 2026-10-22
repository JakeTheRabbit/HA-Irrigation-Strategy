"""Threshold alert rules (spec 2.9, G6): the rule as stored, its sentence, its lifecycle and its replay. PURE.

A rule watches one source (a zone's VWC, the feed pH, a stock tank, the controller's heartbeat...) and
fires when the value stays above or below its threshold for `min_duration_s` inside its window. Climate
sources are left out on purpose (G6). site_api.py stores the rules, reads the sources and drives step();
replay() runs the same step() over a recorded series, so what a preview says is what the rule would do.

`severity` (info, warning, emergency) is informational: it is stored and shown, and nothing reads it to
decide anything. How loud a push is follows `routing` (spec 2.9): a rule routed to the emergency kind is
pushed as urgent and is never held by a room's mute; every other rule is held while its room is muted.

Rules only notify. Nothing here, nor in what drives it, touches irrigation.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from . import notify_catalog
from .generated.ids import new_id
from .generated.timers import KINDS as WINDOW_KINDS
from .generated.timers import _minutes, _window

# source -> (canonical unit, words for it in a sentence)
SOURCES = {
    "zone.vwc": ("%", "VWC"),
    "zone.ec": ("mS/cm", "EC"),
    "zone.temperature": ("°C", "root-zone temperature"),
    "feed.ph": ("pH", "feed pH"),
    "feed.ec": ("mS/cm", "feed EC"),
    "tank.level": ("%", "tank level"),
    "stock.pct": ("%", "stock tank"),
    "stock.litres": ("L", "stock tank"),
    "zone.flow_ratio": ("%", "flow"),
    "controller.heartbeat": ("s", "controller heartbeat age"),
    "probe.silence_s": ("s", "probe silence"),
}
ZONE_SOURCES = ("zone.vwc", "zone.ec", "zone.temperature", "zone.flow_ratio")
STOCK_SOURCES = ("stock.pct", "stock.litres")
# Evaluated on the minute, not only when an entity changes: an age grows with no state change.
AGE_SOURCES = ("controller.heartbeat", "probe.silence_s")
OPS = ("above", "below")
SEVERITIES = ("info", "warning", "emergency")
STATES = ("draft", "armed", "pending", "firing", "acknowledged", "muted")
ON = ("firing", "acknowledged")
MAX_DURATION_S = 86400
MAX_SERIES = 1440
NOISY = 10


def validate_rule(rule: dict, rule_id: str | None = None) -> dict:
    """The rule as stored, or ValueError in plain words. `rule_id` keeps an existing rule's id; a new
    rule gets a ULID."""
    if not isinstance(rule, dict):
        raise ValueError("A rule must be an object")
    kind = rule.get("kind", "threshold")
    if kind != "threshold":
        raise ValueError("Only threshold rules can be saved here")
    room_id = rule.get("room_id")
    if not isinstance(room_id, str) or not room_id.startswith("room:"):
        raise ValueError("room_id must be a room such as room:f2_")
    source = rule.get("source")
    if source not in SOURCES:
        if isinstance(source, str) and source.startswith(("room.", "climate.")):
            raise ValueError(
                f"{source}: climate sources can't have alert rules; "
                "pick a zone, feed, tank, stock or controller source"
            )
        raise ValueError(f"source must be one of {', '.join(SOURCES)}")
    zones = rule.get("zones") or []
    if not isinstance(zones, list) or any(type(z) is not int or z < 1 for z in zones):
        raise ValueError("zones must be a list of zone numbers")
    zones = sorted(set(zones))
    if source in ZONE_SOURCES and not zones:
        raise ValueError(f"{source} needs at least one zone")
    if rule.get("op") not in OPS:
        raise ValueError("op must be above or below")
    threshold = rule.get("threshold")
    if type(threshold) not in (int, float) or not math.isfinite(threshold):
        raise ValueError("threshold must be a number")
    duration = rule.get("min_duration_s", 0)
    if type(duration) is not int or not 0 <= duration <= MAX_DURATION_S:
        raise ValueError(
            f"min_duration_s must be a whole number of seconds from 0 to {MAX_DURATION_S}"
        )
    severity = rule.get("severity", "warning")
    if severity not in SEVERITIES:
        raise ValueError(f"severity must be one of {', '.join(SEVERITIES)}")
    routing = rule.get("routing", "sensors")
    if routing not in notify_catalog.KIND_IDS:
        raise ValueError(f"routing must be one of {', '.join(notify_catalog.KIND_IDS)}")
    active = rule.get("active", True)
    if type(active) is not bool:
        raise ValueError("active must be true or false")
    out = {
        "id": rule_id or new_id(),
        "kind": "threshold",
        "room_id": room_id,
        "zones": zones,
        "source": source,
        "op": rule["op"],
        "threshold": float(threshold),
        "unit": SOURCES[source][0],
        "window": clean_window(rule.get("window")),
        "min_duration_s": duration,
        "severity": severity,
        "routing": routing,
        "active": active,
    }
    if source == "probe.silence_s":
        entity = rule.get("entity_id")
        if not isinstance(entity, str) or "." not in entity:
            raise ValueError("probe.silence_s needs the probe's entity_id")
        out["entity_id"] = entity
    if source in STOCK_SOURCES:
        tank = rule.get("tank_id")
        if not isinstance(tank, str) or not tank:
            raise ValueError(f"{source} needs the stock tank's tank_id")
        out["tank_id"] = tank
    return out


def clean_window(value) -> dict:
    """all | lights_on | lights_off | {kind: custom, from, to}; a bare kind name is taken too."""
    if value is None:
        return {"kind": "all"}
    if isinstance(value, str):
        value = {"kind": value}
    if not isinstance(value, dict) or value.get("kind") not in WINDOW_KINDS:
        raise ValueError(f"window kind must be one of {', '.join(WINDOW_KINDS)}")
    if value["kind"] != "custom":
        return {"kind": value["kind"]}
    if _minutes(value.get("from")) == _minutes(value.get("to")):
        raise ValueError("Start and end can't be the same")
    return {"kind": "custom", "from": value["from"], "to": value["to"]}


def in_window(now: datetime, window: dict, lights) -> bool:
    start, length = _window(window, lights)
    minute = now.hour * 60 + now.minute + now.second / 60
    return (minute - start) % 1440 < length


# ------------------------------------------------------------------ words
def _num(value) -> str:
    return f"{round(value, 2):g}"


def amount(value, unit) -> str:
    if unit == "s":
        return _duration(value)
    if unit == "%":
        return f"{_num(value)}%"
    if unit == "pH":
        return f"pH {_num(value)}"
    return f"{_num(value)} {unit}"


def _duration(seconds) -> str:
    """600 -> "10 min", 7200 -> "2 h", 90 -> "1.5 min", 45 -> "45 s"."""
    seconds = round(seconds)
    if seconds < 60:
        return f"{seconds} s"
    if seconds % 3600 == 0:
        return f"{seconds // 3600} h"
    return f"{round(seconds / 60, 1):g} min"


def _zones(zones) -> str:
    if len(zones) == 1:
        return f"zone {zones[0]}"
    return "zones " + ", ".join(map(str, zones[:-1])) + f" and {zones[-1]}"


def label(rule, name=None) -> str:
    """What the rule watches, in words: "zone 1 VWC", "feed pH", "stock tank Bloom A". `name`: the
    stock tank's name, or the probe's friendly name (else its tank_id or entity_id)."""
    source, words = rule["source"], SOURCES[rule["source"]][1]
    if source in ZONE_SOURCES:
        return f"{_zones(rule['zones'])} {words}"
    if source in STOCK_SOURCES:
        return f"{words} {name or rule['tank_id']}"
    if source == "probe.silence_s":
        return f"{name or rule['entity_id']} silence"
    return words


def first_upper(text: str) -> str:
    """Only the first character upper-cased: "zone 1 VWC" -> "Zone 1 VWC" (never "Zone 1 vwc")."""
    return text[:1].upper() + text[1:]


def title(rule, room_name=None, name=None) -> str:
    """The rule's short name: "F2 tank level below 30%"."""
    return (
        f"{room_name or room_words(rule['room_id'])} {label(rule, name)} {rule['op']} "
        f"{amount(rule['threshold'], rule['unit'])}"
    )


def room_words(room_id: str) -> str:
    """A room's name from its id when nothing better is known: room:f2_ -> F2."""
    slug = room_id[len("room:") :].strip("_").replace("_", " ")
    return slug.title() if slug else "The room"


def summary_sentence(rule: dict, room_name: str | None = None, name=None) -> str:
    """ "Tell when F2 tank level stays below 30% for 10 min during lights-on." """
    seconds = rule.get("min_duration_s", 0)
    verb = "stays" if seconds else "goes"
    text = (
        f"Tell when {room_name or room_words(rule['room_id'])} {label(rule, name)} {verb} "
        f"{rule['op']} {amount(rule['threshold'], rule['unit'])}"
    )
    if seconds:
        text += f" for {_duration(seconds)}"
    window = rule.get("window") or {"kind": "all"}
    if window["kind"] == "lights_on":
        text += " during lights-on"
    elif window["kind"] == "lights_off":
        text += " during lights-off"
    elif window["kind"] == "custom":
        text += f" between {window['from']} and {window['to']}"
    return text + "."


# ------------------------------------------------------------------ the lifecycle (spec 6.4)
def breaching(value, rule) -> bool:
    if value is None:
        return False
    if rule["op"] == "below":
        return value < rule["threshold"]
    return value > rule["threshold"]


def step(
    state: dict,
    value: float | None,
    now: datetime,
    rule: dict,
    lights: tuple[float, float],
    muted: bool,
) -> tuple[dict, str | None]:
    """One evaluation -> (new state, "raised" | "cleared" | None).

    state: {"state", "since" (the breach's start), "fired_at"}; {} is a fresh rule. A value of None (no
    entity, unavailable) never fires and never clears. `muted`: the room is muted and the rule is not
    routed to emergencies; a rule that already fires keeps firing.
    """
    current = (state or {}).get("state")
    if not rule.get("active", True):
        return {"state": "draft"}, ("cleared" if current in ON else None)
    if current in ON:
        if value is not None and not breaching(value, rule):
            return {"state": "armed"}, "cleared"
        return dict(state), None
    if muted:
        return {"state": "muted"}, None
    if not breaching(value, rule) or not in_window(
        now, rule.get("window") or {"kind": "all"}, lights
    ):
        return {"state": "armed"}, None
    since = state.get("since") if current == "pending" else None
    since = since or now
    if now - since >= timedelta(seconds=rule.get("min_duration_s", 0)):
        return {"state": "firing", "since": since, "fired_at": now}, "raised"
    return {"state": "pending", "since": since}, None


# ------------------------------------------------------------------ replay
def merge_worst(series: list[list[tuple[datetime, float | None]]], op: str):
    """Several zones' series as one: at each time the worst of their last values (the lowest for a
    below rule), None only when none of them has a value."""
    times = sorted({t for s in series for t, _ in s})
    pick = min if op == "below" else max
    out, idx, last = [], [0] * len(series), [None] * len(series)
    for t in times:
        for i, s in enumerate(series):
            while idx[i] < len(s) and s[idx[i]][0] <= t:
                last[i] = s[idx[i]][1]
                idx[i] += 1
        known = [v for v in last if v is not None]
        out.append((t, pick(known) if known else None))
    return out


def age_samples(reports: list[datetime], start: datetime, end: datetime, step_s=60):
    """The age in seconds of the newest report at each step from start to end (None before the first)."""
    reports = sorted(reports)
    out, i, newest, t = [], 0, None, start
    while t <= end:
        while i < len(reports) and reports[i] <= t:
            newest = reports[i]
            i += 1
        out.append((t, None if newest is None else (t - newest).total_seconds()))
        t += timedelta(seconds=step_s)
    return out


def downsample(series, op, limit=MAX_SERIES):
    """At most `limit` points: each bucket keeps its worst value (the lowest for a below rule)."""
    if len(series) <= limit:
        return list(series)
    size = math.ceil(len(series) / limit)
    worse = (lambda a, b: a < b) if op == "below" else (lambda a, b: a > b)
    out = []
    for i in range(0, len(series), size):
        best = None
        for point in series[i : i + size]:
            if best is None or (
                point[1] is not None and (best[1] is None or worse(point[1], best[1]))
            ):
                best = point
        out.append(best)
    return out


def _iso(t: datetime) -> str:
    return t.isoformat()


def replay(
    samples: list[tuple[datetime, float | None]],
    rule: dict,
    lights: tuple[float, float],
    *,
    hours: float = 24,
    end: datetime | None = None,
    muted=(),
) -> dict:
    """What the rule would have done over `samples` (time, value; the value holds until the next):
    {series, fires: [{start, fired_at, end}], ignored: [{start, end, reason}], count, min, max,
    sentence}. Evaluated at every sample and every minute between, as the live rule is. `muted`:
    spans [(start, end)] the room was muted, which hold the rule unless it is routed to emergencies.

    `ignored` reasons: "shorter than min_duration" (back in range before min_duration_s), "outside
    window" (a breach outside the rule's window, or one that left it while pending), "muted". A breach
    that ends because the reading went missing (None) gets no row.
    """
    samples = sorted(samples, key=lambda p: p[0])
    values = [v for _, v in samples if v is not None]
    out = {
        "series": [[_iso(t), v] for t, v in downsample(samples, rule["op"])],
        "fires": [],
        "ignored": [],
        "count": 0,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }
    if samples:
        end = max(end or samples[-1][0], samples[-1][0])
        ticks, t = {s[0] for s in samples}, samples[0][0]
        while t <= end:
            ticks.add(t)
            t += timedelta(minutes=1)
        emergency = rule.get("routing") == "emergency"
        state, i, value, open_span = {}, 0, None, None
        for t in sorted(ticks):
            while i < len(samples) and samples[i][0] <= t:
                value = samples[i][1]
                i += 1
            held = not emergency and any(a <= t < b for a, b in muted)
            before = state
            state, event = step(state, value, t, rule, lights, held)
            carry = None  # the start of a breach that goes on, now held by the window or a mute
            if event == "raised":
                out["fires"].append(
                    {"start": _iso(state["since"]), "fired_at": _iso(t), "end": None}
                )
            elif event == "cleared":
                out["fires"][-1]["end"] = _iso(t)
            elif before.get("state") == "pending" and state["state"] != "pending":
                # A pending breach that ends: back in range is a short breach; still breaching, it
                # left the window or the room was muted (its span below starts with the breach). A
                # missing reading (None) ends it with no row: nothing says what the value did.
                if value is not None and not breaching(value, rule):
                    out["ignored"].append(
                        {
                            "start": _iso(before["since"]),
                            "end": _iso(t),
                            "reason": "shorter than min_duration",
                        }
                    )
                elif value is not None:
                    carry = before["since"]
            reason = None
            if breaching(value, rule) and state["state"] not in ON:
                if state["state"] == "muted":
                    reason = "muted"
                elif state["state"] == "armed":
                    reason = "outside window"
            if open_span and open_span["reason"] != reason:
                open_span["end"] = _iso(t)
                out["ignored"].append(open_span)
                open_span = None
            if reason and open_span is None:
                open_span = {"start": _iso(carry or t), "end": None, "reason": reason}
        if open_span:
            out["ignored"].append(open_span)
        out["ignored"].sort(key=lambda span: span["start"])
    out["count"] = len(out["fires"])
    out["sentence"] = replay_sentence(out, rule, hours)
    return out


def replay_sentence(result: dict, rule: dict, hours: float = 24) -> str:
    count = result["count"]
    when = "yesterday" if hours == 24 else f"in the last {_num(hours)} h"
    if count > NOISY:
        per_day = round(count * 24 / hours)
        lower = "lower" if rule["op"] == "below" else "higher"
        return f"That's {per_day} messages a day. Try a longer wait or a {lower} threshold."
    if count:
        times = ", ".join(
            datetime.fromisoformat(f["fired_at"]).strftime("%H:%M")
            for f in result["fires"]
        )
        often = "once" if count == 1 else f"{count} times"
        return f"This rule would have fired {often} {when} — {times}."
    if result["min"] is None:
        return f"There's no history for this in the last {_num(hours)} h."
    if rule["op"] == "below":
        worst = f"Lowest was {amount(result['min'], rule['unit'])}"
    else:
        worst = f"Highest was {amount(result['max'], rule['unit'])}"
    return f"It wouldn't have fired in the last {_num(hours)} h. {worst}."
