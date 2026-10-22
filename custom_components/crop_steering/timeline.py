"""Timeline (G5): what each zone did, and is planned to do, folded from the journal. Pure: no Home Assistant.

build() turns journal events and the controller's planned intents into the timeline_get answer (spec section 5.2):
per room its lights windows, one row of blocks per zone, the pump load, and the error markers.

- `shot.started` / `shot.completed` / `shot.aborted` with one `correlation.intent_id` are one `shot` block: done when
  completed, error when aborted or failed, warning when partial or still open. Its litres are the commanded ones;
  `metered_l` comes from `shot.completed.data.metered_l`, else from the `flow.reconciled` of the same intent, else
  None. `reason`, `phase`, `vwc_before`, `vwc_expected`, `requested_at` and `pump_wait_s` come from the
  `shot.started` data; any that is missing is None.
- `intent.held` and `intent.queued` are point blocks (`held`, `queued`), `alert.raised` an `alert` block; all warnings.
- `planned` blocks come only from the controller's `projection_app` intents (timer and engine alike, so nothing is
  drawn twice), and only those after now. An engine expectation keeps `expected: true`.

summarise() counts the same blocks per room per local day for timeline_summary.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

MAX_SPAN = timedelta(hours=48)
SPAN_REFUSED = "timeline span is at most 48 h"
MAX_DAYS = 14
DAYS_REFUSED = f"timeline summary covers at most {MAX_DAYS} days"
# timeline_get answers at most this many blocks, the newest (`truncated: true` when it cut).
MAX_BLOCKS = 5000
SHOT_KINDS = ("shot.started", "shot.completed", "shot.aborted")
# The journal kinds a fold reads (journal_query `kinds`).
KINDS = (*SHOT_KINDS, "intent.held", "intent.queued", "alert.raised", "flow.reconciled")
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
        "expected": False,
    }


def _shot(started, ended, metered) -> dict:
    first = started or ended
    begun = (started or {}).get("data") or {}
    done = (ended or {}).get("data") or {}
    end = at(ended["ts"]) if ended else None
    if started:
        start = at(started["ts"])
    else:  # only its end is in the window
        elapsed = _seconds(done.get("elapsed_s"))
        start = end - timedelta(seconds=elapsed) if elapsed is not None else end
    if ended is None:
        status = "warning"  # still open: no completion or abort journaled
        duration = _seconds(begun.get("duration_s"))
        end = start + timedelta(seconds=duration) if duration is not None else None
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
        code=(ended or {}).get("code") or (started or {}).get("code"),
        event_id=(ended or started)["id"],
    )
    block["litres"] = done.get("commanded_l", begun.get("commanded_l"))
    block["metered_l"] = (
        done["metered_l"]
        if done.get("metered_l") is not None
        else metered.get(intent_id)
    )
    for key in STARTED_FIELDS:
        block[key] = begun.get(key)
    return block


def _blocks(events) -> list[tuple[str, object, dict]]:
    """(room_id, zone, block) for every journaled shot, hold, queue and alert. Block times are datetimes."""
    shots: dict = {}
    metered: dict = {}
    out = []
    for ev in events:
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
        block = _shot(slot.get("started"), slot.get("ended"), metered)
        out.append((room_id, slot["zone"], block))
    return out


def _planned(intent, now) -> dict | None:
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
    block["skippable"] = source in PLANNED_SOURCES
    block["expected"] = intent.get("expected") is True
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


def pump_load(shots, demand: dict, capacity_lph) -> list[dict]:
    """[{t, pct}] at each shot start and end: the running zones' demand (L/h) over the room pump's capacity, in %.
    pct is None when the capacity, or a running zone's demand, is not known."""
    windows = [
        (b["start"], b["end"], zone) for zone, b in shots if b["start"] and b["end"]
    ]
    out = []
    for moment in sorted({t for s, e, _ in windows for t in (s, e)}):
        running = [zone for s, e, zone in windows if s <= moment < e]
        needs = [demand.get(str(zone)) for zone in running]
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
) -> dict:
    """The timeline_get answer.

    rooms: [{room_id, lights_hours: (on, off) | None, demand: {"3": L/h}, capacity_lph: float | None,
    planned_source: "projection_app" | "unavailable"}]. planned: projection_app intents, each with its room_id.
    Times are answered in `tz` (HA local time). Raises ValueError for a span over 48 h.
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

    found = [(r, z, b) for r, z, b in _blocks(events) if kept(z, b)]
    seen = set()
    for intent in planned:
        block = _planned(intent, now)
        zone = intent.get("zone")
        key = (intent.get("room_id"), block and block["id"])
        if block is None or key in seen or not kept(zone, block):
            continue
        seen.add(key)
        found.append((intent.get("room_id"), zone, block))
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
        load = pump_load(
            [(z, b) for z, b in mine if b["kind"] == "shot"],
            room.get("demand") or {},
            room.get("capacity_lph"),
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
                "pump_load": [{"t": text(p["t"]), "pct": p["pct"]} for p in load],
                "planned_source": room.get("planned_source", "unavailable"),
            }
        )
    markers.sort(key=lambda m: m["t"])
    out = {"rooms": answer, "errors": {"count": len(markers), "markers": markers}}
    if truncated:
        out["truncated"] = True
    return out


def summarise(events, days, *, rooms, tz) -> list[dict]:
    """[{date, rooms: [{room_id, shots, failed, warnings, held, queued}]}] for each of `days` (YYYY-MM-DD), each
    block counted on the local (`tz`) day it started. failed: error blocks; warnings: warning shots and alerts
    (held and queued have their own counts). Raises ValueError for more than 14 days."""
    wanted = check_days(days)
    counts = {
        (d, r): {"shots": 0, "failed": 0, "warnings": 0, "held": 0, "queued": 0}
        for d in wanted
        for r in rooms
    }
    for room_id, _, block in _blocks(events):
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
