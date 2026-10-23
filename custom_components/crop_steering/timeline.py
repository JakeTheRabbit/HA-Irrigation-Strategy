"""Timeline (G5): what each zone did, and is planned to do, folded from the journal. Pure: no Home Assistant.

build() turns journal events and the controller's planned intents into the timeline_get answer (spec section 5.2):
per room its lights windows, one row of blocks per zone, the pump load, and the error markers.

- `shot.started` / `shot.completed` / `shot.aborted` with one `correlation.intent_id` are one `shot` block: done when
  completed, error when aborted or failed, warning when partial. A shot still open is done and `running: true` until
  its `duration_s` plus RUNNING_GRACE_S has passed, then a warning. A completion or abort whose start was not read
  is dropped: a shot belongs to the day and window it started in, and windows() reads the completions of the shots
  that start inside a window up to CLOSE_MARGIN past its end. Its litres are the commanded ones;
  `metered_l` comes from `shot.completed.data.metered_l`, else from the `flow.reconciled` of the same intent, else
  None. `reason`, `phase`, `vwc_before`, `vwc_expected`, `requested_at` and `pump_wait_s` come from the
  `shot.started` data; any that is missing is None.
- `intent.held` and `intent.queued` are point blocks (`held`, `queued`), `alert.raised` an `alert` block; all warnings.
- `planned` blocks come only from the controller's `projection_app` intents (timer and engine alike, so nothing is
  drawn twice), and only those after now. An engine expectation keeps `expected: true`. A slot the room's timer
  skips already cover is `skipped: true` and no longer skippable.
- `pump_load` is the room's pump's total: every room on that pump (pumps are site-wide, G1) adds its running zones'
  demand, over the pump's capacity.

summarise() counts the same blocks per room per local day for timeline_summary.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

MAX_SPAN = timedelta(hours=48)
SPAN_REFUSED = "timeline span is at most 48 h"
MAX_DAYS = 14
DAYS_REFUSED = f"timeline summary covers at most {MAX_DAYS} days"
# The longest shot a room can be set to (number.py "Longest shot", max_shot_duration native_max_value), and the
# grace after a shot's planned end before an open shot reads as a warning (pump prime and main line lead included).
LONGEST_SHOT_S = 3600
RUNNING_GRACE_S = 120
CLOSE_MARGIN = timedelta(seconds=LONGEST_SHOT_S + RUNNING_GRACE_S)
# timeline_get answers at most this many blocks, the newest (`truncated: true` when it cut).
MAX_BLOCKS = 5000
SHOT_KINDS = ("shot.started", "shot.completed", "shot.aborted")
# The journal kinds a fold reads (journal_query `kinds`).
KINDS = (*SHOT_KINDS, "intent.held", "intent.queued", "alert.raised", "flow.reconciled")
CLOSING_KINDS = ("shot.completed", "shot.aborted", "flow.reconciled")
POINT_KINDS = {
    "intent.held": "held",
    "intent.queued": "queued",
    "alert.raised": "alert",
}
STARTED_FIELDS = (
    "reason",
    "phase",
    "vwc_before",
    "vwc_expected",
    "requested_at",
    "pump_wait_s",
)
PLANNED_SOURCES = ("timer", "engine")


def at(value, tz=None) -> datetime | None:
    """An ISO time as an aware datetime (a naive one is in `tz`, else UTC), or None."""
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=tz or UTC)


def check_span(start: datetime, end: datetime) -> None:
    if end <= start:
        raise ValueError("timeline end must be after its start")
    if end - start > MAX_SPAN:
        raise ValueError(SPAN_REFUSED)


def check_days(days) -> list[date]:
    if len(days) > MAX_DAYS:
        raise ValueError(DAYS_REFUSED)
    try:
        return [date.fromisoformat(d) for d in days]
    except (TypeError, ValueError) as err:
        raise ValueError("days are dates such as 2026-10-22") from err


def windows(since: datetime, until: datetime, *, openers: bool) -> list[tuple]:
    """The journal reads for [since, until): (since, until, kinds). Every kind in the window; the completions of
    shots started in it up to CLOSE_MARGIN after it; with `openers`, the starts and closes up to CLOSE_MARGIN before
    it, so a shot that runs into the window is drawn whole and one that closed before it is not drawn.
    """
    out = [(since, until, KINDS), (until, until + CLOSE_MARGIN, CLOSING_KINDS)]
    if openers:
        out.append((since - CLOSE_MARGIN, since, ("shot.started", *CLOSING_KINDS)))
    return out


def _seconds(value):
    return (
        value
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else None
    )


def _block(kind, status, start, end, *, ident, source=None, code=None, event_id=None):
    return {
        "id": ident,
        "kind": kind,
        "status": status,
        "start": start,
        "end": end,
        "litres": None,
        "metered_l": None,
        **{key: None for key in STARTED_FIELDS},
        "source": source,
        "code": code,
        "event_id": event_id,
        "skippable": False,
        "skipped": False,
        "expected": False,
        "running": False,
    }


def _shot(started, ended, metered, now) -> dict:
    first = started
    begun = started.get("data") or {}
    done = (ended or {}).get("data") or {}
    start = at(started["ts"])
    end = at(ended["ts"]) if ended else None
    running = False
    if ended is None:  # still open: no completion or abort journaled
        duration = _seconds(begun.get("duration_s"))
        end = start + timedelta(seconds=duration) if duration is not None else None
        running = start + timedelta(seconds=(duration or 0) + RUNNING_GRACE_S) >= now
        status = "done" if running else "warning"
    elif ended["kind"] == "shot.aborted" or ended.get("outcome") in (
        "aborted",
        "failed",
    ):
        status = "error"
    elif ended.get("outcome") == "partial":
        status = "warning"
    else:
        status = "done"
    intent_id = ((first.get("correlation") or {}).get("intent_id")) or first["id"]
    block = _block(
        "shot",
        status,
        start,
        end,
        ident=intent_id,
        source=(first.get("source") or {}).get("actor"),
        code=(ended or {}).get("code") or started.get("code"),
        event_id=(ended or started)["id"],
    )
    block["running"] = running
    block["litres"] = done.get("commanded_l", begun.get("commanded_l"))
    block["metered_l"] = (
        done["metered_l"]
        if done.get("metered_l") is not None
        else metered.get(intent_id)
    )
    for key in STARTED_FIELDS:
        block[key] = begun.get(key)
    return block


def _blocks(events, now) -> list[tuple[str, object, dict]]:
    """(room_id, zone, block) for every journaled shot, hold, queue and alert (each event once, by id). Block times
    are datetimes."""
    shots: dict = {}
    metered: dict = {}
    out = []
    unique = {ev["id"]: ev for ev in events}
    for ev in unique.values():
        kind = ev.get("kind")
        intent_id = (ev.get("correlation") or {}).get("intent_id")
        if kind == "flow.reconciled":
            if intent_id and (ev.get("data") or {}).get("metered_l") is not None:
                metered[intent_id] = ev["data"]["metered_l"]
        elif kind in SHOT_KINDS:
            key = (ev.get("room_id"), intent_id or ev["id"])
            slot = shots.setdefault(key, {"zone": ev.get("zone")})
            slot["started" if kind == "shot.started" else "ended"] = ev
        elif kind in POINT_KINDS:
            moment = at(ev["ts"])
            block = _block(
                POINT_KINDS[kind],
                "warning",
                moment,
                moment,
                ident=ev["id"],
                source=(ev.get("source") or {}).get("actor"),
                code=ev.get("code"),
                event_id=ev["id"],
            )
            data = ev.get("data") or {}
            block["reason"] = data.get("reason") or data.get("title")
            block["requested_at"] = data.get("requested_at")
            out.append((ev.get("room_id"), ev.get("zone"), block))
    for (room_id, _), slot in shots.items():
        if (
            "started" not in slot
        ):  # only its end was read: it belongs to a window it started in
            continue
        block = _shot(slot["started"], slot.get("ended"), metered, now)
        out.append((room_id, slot["zone"], block))
    return out


def _skipped(intent, moment, skips) -> bool:
    """A timer slot is skipped by a skip at its instant; an engine shot by a skip whose [at, until) holds it."""
    for skip in skips:
        if skip.get("zone") != intent.get("zone"):
            continue
        since, until = at(skip.get("at")), at(skip.get("until"))
        if since is None:
            continue
        if intent.get("source") == "timer" and moment == since:
            return True
        if intent.get("source") == "engine" and until and since <= moment < until:
            return True
    return False


def _planned(intent, now, skips=()) -> dict | None:
    moment = at(intent.get("at"))
    if moment is None or moment <= now:
        return None
    duration = _seconds(intent.get("duration_s"))
    source = intent.get("source")
    block = _block(
        "planned",
        "planned",
        moment,
        moment + timedelta(seconds=duration) if duration is not None else moment,
        ident=intent.get("id"),
        source=source,
    )
    block["skipped"] = _skipped(intent, moment, skips)
    block["skippable"] = source in PLANNED_SOURCES and not block["skipped"]
    block["expected"] = intent.get("expected") is True
    # The phase the engine expects then (a controller from before it sends none).
    if intent.get("phase") in ("P0", "P1", "P2", "P3"):
        block["phase"] = intent["phase"]
    return block


def lights_windows(hours, tz, start: datetime, end: datetime) -> list[dict]:
    """The room's lights-on windows that overlap [start, end), from its (on, off) hours in local time `tz`. Lights
    off at or before the on hour go off the next day. Equal hours give no window (nothing to tell from them).
    """
    if not hours or tz is None:
        return []
    on_h, off_h = (float(h) for h in hours)
    if on_h == off_h:
        return []

    def local(day, hour):
        minutes = round(hour * 60)
        return datetime(
            day.year, day.month, day.day, minutes // 60, minutes % 60, tzinfo=tz
        )

    out = []
    day = start.astimezone(tz).date() - timedelta(days=1)
    while day <= end.astimezone(tz).date():
        on = local(day, on_h)
        off = local(day + timedelta(days=1) if off_h <= on_h else day, off_h)
        if on < end and off > start:
            out.append({"on": on.isoformat(), "off": off.isoformat()})
        day += timedelta(days=1)
    return out


def pump_load(shots, demand: dict, capacity_lph, start, end) -> list[dict]:
    """[{t, pct}] at each shot start and end within [start, end] (and at `start` when a shot runs across it): the
    running zones' demand (L/h) over the pump's capacity, in %. shots: [(room_id, zone, block)]; demand:
    {room_id: {"3": L/h}}. pct is None when the capacity, or a running zone's demand, is not known.
    """
    spans = [
        (b["start"], b["end"], room_id, zone)
        for room_id, zone, b in shots
        if b["start"] and b["end"]
    ]
    out = []
    moments = {t for s, e, _, _ in spans for t in (s, e) if start <= t <= end}
    if any(s < start < e for s, e, _, _ in spans):
        moments.add(start)
    for moment in sorted(moments):
        running = [(r, z) for s, e, r, z in spans if s <= moment < e]
        needs = [(demand.get(r) or {}).get(str(z)) for r, z in running]
        if capacity_lph is None or any(n is None for n in needs):
            pct = None
        else:
            pct = sum(needs) / capacity_lph * 100
        out.append({"t": moment, "pct": pct})
    return out


def _zone_key(zone):
    return (zone is None, zone if zone is not None else 0)


def build(
    rooms: list[dict],
    events: list[dict],
    planned: list[dict],
    start,
    end,
    *,
    now=None,
    tz=None,
    zones=None,
    pumps=None,
) -> dict:
    """The timeline_get answer.

    rooms: [{room_id, lights_hours: (on, off) | None, pump: switch entity | None, capacity_lph: float | None,
    planned_source: "projection_app" | "unavailable", skips: [{zone, at, until}]}]. planned: projection_app
    intents, each with its room_id. pumps: {pump: {room_id: {"3": L/h}}}, every room on each requested room's
    pump with its zones' demand; `events` carries the shots of those rooms too. A room's `pump_load` is its
    pump's total (each room on a pump answers the same series); without a pump it is the room's own shots with
    pct None. Times are answered in `tz` (HA local time). Raises ValueError for a span over 48 h.
    """
    start, end = at(start, tz), at(end, tz)
    check_span(start, end)
    now = at(now, tz) if now is not None else datetime.now(UTC)
    wanted = None if zones is None else {int(z) for z in zones}

    def kept(zone, block):
        if wanted is not None and zone not in wanted:
            return False
        return (
            block["start"] is not None
            and block["start"] < end
            and ((block["end"] or block["start"]) >= start)
        )

    pumps = pumps or {}
    asked = {room["room_id"]: room for room in rooms}
    every = _blocks(events, now)
    found = [(r, z, b) for r, z, b in every if r in asked and kept(z, b)]
    seen = set()
    for intent in planned:
        room_id, zone = intent.get("room_id"), intent.get("zone")
        block = _planned(intent, now, (asked.get(room_id) or {}).get("skips") or ())
        if block is None or not kept(zone, block):
            continue
        key = (room_id, zone, block["start"], block["source"])
        if key in seen:
            continue
        seen.add(key)
        found.append((room_id, zone, block))
    found.sort(key=lambda item: item[2]["start"], reverse=True)
    truncated = len(found) > MAX_BLOCKS
    found = found[:MAX_BLOCKS]

    def text(moment):
        return moment.astimezone(tz).isoformat() if moment is not None else None

    answer, markers = [], []
    for room in rooms:
        room_id = room["room_id"]
        mine = sorted(
            ((z, b) for r, z, b in found if r == room_id), key=lambda zb: zb[1]["start"]
        )
        pump = room.get("pump")
        on_pump = pumps.get(pump) if pump else None
        if on_pump:
            load = pump_load(
                [
                    (r, z, b)
                    for r, z, b in every
                    if r in on_pump and b["kind"] == "shot"
                ],
                on_pump,
                room.get("capacity_lph"),
                start,
                end,
            )
        else:
            load = pump_load(
                [(room_id, z, b) for z, b in mine if b["kind"] == "shot"],
                {},
                None,
                start,
                end,
            )
        rows: dict = {}
        for zone, block in mine:
            if block["status"] == "error":
                markers.append(
                    {
                        "room_id": room_id,
                        "zone": zone,
                        "t": text(block["start"]),
                        "code": block["code"],
                        "block_id": block["id"],
                    }
                )
            rows.setdefault(zone, []).append(
                {**block, "start": text(block["start"]), "end": text(block["end"])}
            )
        answer.append(
            {
                "room_id": room_id,
                "lights": lights_windows(room.get("lights_hours"), tz, start, end),
                "rows": [
                    {"zone": zone, "blocks": rows[zone]}
                    for zone in sorted(rows, key=_zone_key)
                ],
                "pump": pump,
                "pump_rooms": sorted(on_pump) if on_pump else [],
                "pump_load": [{"t": text(p["t"]), "pct": p["pct"]} for p in load],
                "planned_source": room.get("planned_source", "unavailable"),
            }
        )
    markers.sort(key=lambda m: m["t"])
    out = {"rooms": answer, "errors": {"count": len(markers), "markers": markers}}
    if truncated:
        out["truncated"] = True
    return out


def summarise(events, days, *, rooms, tz, now=None) -> list[dict]:
    """[{date, rooms: [{room_id, shots, failed, warnings, held, queued}]}] for each of `days` (YYYY-MM-DD, each
    once), each block counted on the local (`tz`) day it started. failed: error blocks; warnings: warning shots and
    alerts (held and queued have their own counts; a running shot is a shot). Raises ValueError for more than 14
    days."""
    wanted = list(dict.fromkeys(check_days(days)))
    now = at(now, tz) if now is not None else datetime.now(UTC)
    counts = {
        (d, r): {"shots": 0, "failed": 0, "warnings": 0, "held": 0, "queued": 0}
        for d in wanted
        for r in rooms
    }
    for room_id, _, block in _blocks(events, now):
        row = counts.get((block["start"].astimezone(tz).date(), room_id))
        if row is None:
            continue
        kind, status = block["kind"], block["status"]
        if kind == "shot":
            row["shots"] += 1
        if kind in ("held", "queued"):
            row[kind] += 1
        elif status == "error":
            row["failed"] += 1
        elif status == "warning":
            row["warnings"] += 1
    return [
        {
            "date": d.isoformat(),
            "rooms": [{"room_id": r, **counts[(d, r)]} for r in rooms],
        }
        for d in wanted
    ]
