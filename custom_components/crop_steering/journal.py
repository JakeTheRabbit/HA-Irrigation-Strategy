"""Per-room event journal on SQLite (spec section 4). Synchronous; callers run it in the executor."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime

from .generated.ids import ULID_RE

KINDS = frozenset(
    {
        "intent.queued",
        "intent.held",
        "intent.refused",
        "shot.started",
        "shot.completed",
        "shot.aborted",
        "dose.completed",
        "batch.step",
        "batch.completed",
        "batch.failed",
        "phase.changed",
        "target.changed",
        "config.changed",
        "plan.saved",
        "plan.armed",
        "plan.activated",
        "plan.disarmed",
        "plan.expired",
        "calibration.started",
        "calibration.captured",
        "calibration.committed",
        "calibration.reverted",
        "pump.primed",
        "pump.calibrated",
        "flow.reconciled",
        "stock.drawn",
        "stock.refilled",
        "alert.raised",
        "alert.cleared",
        "alert.acknowledged",
        "ai.judgement",
        "ai.outcome",
        "run.saved",
        "run.archived",
        "harvest.recorded",
    }
)
ACTORS = frozenset(
    {
        "engine",
        "timer",
        "plan",
        "manual",
        "ai",
        "learner",
        "safety",
        "mcp",
        "aigrow",
        "automation",
        "system",
    }
)
OUTCOMES = frozenset(
    {"ok", "queued", "held", "refused", "aborted", "failed", "partial"}
)
SHORT_KINDS = ("shot.", "intent.", "flow.")
SHORT_DAYS = 400
MAX_LIMIT = 500

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY, room_id TEXT, seq INTEGER, ts TEXT, ts_ms INTEGER,
    kind TEXT, zone INTEGER, actor TEXT, intent_id TEXT, body TEXT,
    UNIQUE(room_id, seq)
);
CREATE INDEX IF NOT EXISTS events_room_ts ON events(room_id, ts_ms);
CREATE INDEX IF NOT EXISTS events_room_kind_ts ON events(room_id, kind, ts_ms);
CREATE INDEX IF NOT EXISTS events_intent ON events(intent_id);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _ts_ms(ts: str) -> int:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)


def validate_event(ev: dict) -> dict:
    """Return ev if it is a well-formed v1 event, else raise ValueError."""
    if not isinstance(ev, dict):
        raise ValueError("event must be an object")
    if ev.get("v") != 1:
        raise ValueError("unsupported event version")
    if not isinstance(ev.get("id"), str) or not ULID_RE.match(ev["id"]):
        raise ValueError("id must be a ULID")
    if ev.get("kind") not in KINDS:
        raise ValueError(f"unknown kind {ev.get('kind')!r}")
    if ev.get("outcome") not in OUTCOMES:
        raise ValueError(f"unknown outcome {ev.get('outcome')!r}")
    source = ev.get("source")
    if not isinstance(source, dict) or source.get("actor") not in ACTORS:
        raise ValueError("source.actor is missing or unknown")
    ts = ev.get("ts")
    if not isinstance(ts, str):
        raise ValueError("ts must be an ISO-8601 string")
    try:
        _ts_ms(ts)
    except ValueError as err:
        raise ValueError(f"bad ts: {err}") from err
    zone = ev.get("zone")
    if zone is not None and (isinstance(zone, bool) or not isinstance(zone, int)):
        raise ValueError("zone must be an integer or null")
    return ev


class Journal:
    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._db: sqlite3.Connection | None = None

    def open(self) -> None:
        with self._lock:
            db = sqlite3.connect(self._path, check_same_thread=False)
            try:
                db.executescript(_SCHEMA)
                db.commit()
            except Exception:
                db.close()
                raise
            self._db = db

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None

    def append(self, room_id: str, events: list[dict]) -> dict:
        checked = [validate_event(e) for e in events]
        accepted: list[str] = []
        duplicate: list[str] = []
        stored: list[dict] = []
        with self._lock:
            db = self._need_db()
            seq = db.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM events WHERE room_id = ?", (room_id,)
            ).fetchone()[0]
            try:
                for ev in checked:
                    if db.execute(
                        "SELECT 1 FROM events WHERE id = ?", (ev["id"],)
                    ).fetchone():
                        duplicate.append(ev["id"])
                        continue
                    seq += 1
                    out = {**ev, "room_id": room_id, "seq": seq}
                    corr = out.get("correlation")
                    db.execute(
                        "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (
                            out["id"],
                            room_id,
                            seq,
                            out["ts"],
                            _ts_ms(out["ts"]),
                            out["kind"],
                            out.get("zone"),
                            out["source"]["actor"],
                            corr.get("intent_id") if isinstance(corr, dict) else None,
                            json.dumps(out, separators=(",", ":")),
                        ),
                    )
                    accepted.append(out["id"])
                    stored.append(out)
                db.commit()
            except Exception:
                db.rollback()
                raise
        return {
            "accepted": accepted,
            "duplicate": duplicate,
            "seq_max": seq,
            "stored": stored,
        }

    def query(
        self,
        room_id: str,
        since: str,
        until: str | None = None,
        kinds: list[str] | None = None,
        zones: list[int] | None = None,
        actor: str | None = None,
        limit: int = 500,
        cursor: str | None = None,
        order: str = "asc",
    ) -> dict:
        limit = max(1, min(int(limit), MAX_LIMIT))
        desc = order == "desc"
        where = ["room_id = ?", "ts_ms >= ?"]
        args: list = [room_id, _ts_ms(since)]
        if until is not None:
            where.append("ts_ms < ?")
            args.append(_ts_ms(until))
        if kinds:
            where.append(f"kind IN ({','.join('?' * len(kinds))})")
            args += list(kinds)
        if zones:
            where.append(f"zone IN ({','.join('?' * len(zones))})")
            args += [int(z) for z in zones]
        if actor:
            where.append("actor = ?")
            args.append(actor)
        if cursor:
            c_ms, c_seq = (int(p) for p in cursor.split(":"))
            where.append(f"(ts_ms, seq) {'<' if desc else '>'} (?, ?)")
            args += [c_ms, c_seq]
        direction = "DESC" if desc else "ASC"
        sql = (
            f"SELECT body, ts_ms, seq FROM events WHERE {' AND '.join(where)} "
            f"ORDER BY ts_ms {direction}, seq {direction} LIMIT ?"
        )
        with self._lock:
            rows = self._need_db().execute(sql, [*args, limit + 1]).fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = f"{rows[-1][1]}:{rows[-1][2]}" if more else None
        return {"events": [json.loads(r[0]) for r in rows], "cursor": next_cursor}

    def prune(self, now_ms: int) -> int:
        cutoff = now_ms - SHORT_DAYS * 86_400_000
        clause = " OR ".join("kind LIKE ?" for _ in SHORT_KINDS)
        with self._lock:
            db = self._need_db()
            cur = db.execute(
                f"DELETE FROM events WHERE ts_ms < ? AND ({clause})",
                [cutoff, *(f"{k}%" for k in SHORT_KINDS)],
            )
            db.commit()
            return cur.rowcount

    def meta_get(self, key: str) -> str | None:
        with self._lock:
            row = (
                self._need_db()
                .execute("SELECT value FROM meta WHERE key = ?", (key,))
                .fetchone()
            )
        return row[0] if row else None

    def meta_set(self, key: str, value: str) -> None:
        with self._lock:
            db = self._need_db()
            db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
            db.commit()

    def _need_db(self) -> sqlite3.Connection:
        if self._db is None:
            raise RuntimeError("journal is not open")
        return self._db


# --- Backfill: the old stores as journal events (run once per room by journal_api) -------------------------------

# The setpoint log's `who` (and an overlay's `by`) -> the journal's source.actor.
_WRITER_ACTORS = {
    "operator": "manual",
    "home_assistant": "automation",
    "learner": "learner",
    "brain": "ai",
    "safety": "safety",
}


def _when(value) -> datetime | None:
    try:
        at = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return at if at.tzinfo is not None else at.replace(tzinfo=UTC)


def _backfilled(room_id, source, row_key, at_text, kind, zone, actor, data):
    """One event for an old row, or None when the row has no usable time. Its id is derived from the row, so
    importing the same row again gives the same id and the journal drops it as a duplicate.
    """
    from .generated.ids import derived_id

    at = _when(at_text)
    if at is None:
        return None
    return {
        "v": 1,
        "id": derived_id(at, f"{source}:{room_id}:{row_key}"),
        "ts": at_text,
        "zone": zone,
        "kind": kind,
        "outcome": "ok",
        "code": None,
        "source": {
            "actor": actor,
            "detail": "backfill",
            "program_id": None,
            "user_id": None,
            "judge": None,
            "client": None,
        },
        "correlation": {
            "intent_id": None,
            "causation_id": None,
            "batch_id": None,
            "run_id": None,
            "plan_revision": None,
            "setup_revision": None,
            "proposal_token": None,
            "ledger_id": None,
        },
        "data": data,
        "readback": None,
    }


def _rows(rows):
    return [row for row in rows or () if isinstance(row, dict)]


def _zone(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _same(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-6
    except (TypeError, ValueError):
        return a == b


def _held_matches(setpoint_rows, overlays) -> dict:
    """For each held overlay, the latest brain row of the setpoint log that made it -> {id(row): overlay}.
    An overlay whose row has been trimmed off the log has no entry."""
    rows = _rows(setpoint_rows)
    found = {}
    for overlay in _rows(overlays):
        hits = [
            r
            for r in rows
            if r.get("entity_id") == overlay.get("entity_id")
            and r.get("who") == "brain"
            and _same(r.get("new"), overlay.get("new"))
            and _when(r.get("at")) is not None
        ]
        if hits:
            found[id(max(hits, key=lambda r: _when(r["at"])))] = overlay
    return found


def import_setpoint_log(room_id: str, rows, overlays=()) -> list[dict]:
    """setpoint_log rows -> `target.changed`, as setpoint_log.record() emits them live. A row keeps no expiry,
    so it reads as the base layer, with one exception: the row that made a still-held AI overlay is that
    overlay's change, so it is imported once on the overlay layer with the overlay's expiry (import_overlays
    leaves that overlay out). Known limit: an overlay that has ended is not stored anywhere, so its row stays
    base.
    """
    held = _held_matches(rows, overlays)
    out = []
    for row in _rows(rows):
        zone = _zone(row.get("zone"))
        overlay = held.get(id(row))
        event = _backfilled(
            room_id,
            "setpoint_log",
            f"{row.get('entity_id')}|{row.get('at')}|{row.get('new')}",
            row.get("at"),
            "target.changed",
            zone,
            _WRITER_ACTORS.get(row.get("who"), "system"),
            {
                "key": row.get("field"),
                "scope": "room" if zone is None else f"zone:{zone}",
                "layer": "base" if overlay is None else "overlay",
                "old": row.get("old"),
                "new": row.get("new"),
                "expires": None if overlay is None else overlay.get("expires"),
                "reason": row.get("reason"),
                "expected": row.get("expected"),
                "entity_id": row.get("entity_id"),
            },
        )
        if event:
            out.append(event)
    return out


def import_stock_history(room_id: str, rows) -> list[dict]:
    """Stock history rows -> one `stock.drawn` per tank in the row (the row key, or its time, plus the tank
    names the event)."""
    out = []
    for row in _rows(rows):
        draws = row.get("draw_ml")
        if not isinstance(draws, dict):
            continue
        base = row.get("key") or row.get("at")
        for tank, ml in draws.items():
            event = _backfilled(
                room_id,
                "stock",
                f"{base}|{tank}",
                row.get("at"),
                "stock.drawn",
                None,
                "manual" if row.get("source") == "manual" else "system",
                {
                    "tank": tank,
                    "ml": ml,
                    "source": row.get("source"),
                    "key": row.get("key"),
                },
            )
            if event:
                out.append(event)
    return out


def import_calibration(room_id: str, records) -> list[dict]:
    """Calibration checks -> `calibration.captured` (a check only judges the probe; nothing was applied)."""
    out = []
    for record in _rows(records):
        event = _backfilled(
            room_id,
            "calibration",
            record.get("id"),
            record.get("at"),
            "calibration.captured",
            None,
            "manual",
            {
                "applied": False,
                "record_id": record.get("id"),
                "probe": record.get("probe"),
                "kind": record.get("kind"),
                "entity_id": record.get("entity_id"),
                "slope_pct": record.get("slope_pct"),
                "offset": record.get("offset"),
                "verdict": record.get("verdict"),
                "points": record.get("points"),
                "note": record.get("note"),
            },
        )
        if event:
            out.append(event)
    return out


def import_overlays(room_id: str, rows, setpoint_rows=()) -> list[dict]:
    """The AI overlays still held -> `target.changed` on the overlay layer (old = the operator's value), except
    those whose change import_setpoint_log already carries (it is given the same `setpoint_rows`).
    """
    merged = {id(o) for o in _held_matches(setpoint_rows, rows).values()}
    out = []
    for row in _rows(rows):
        if id(row) in merged:
            continue
        zone = _zone(row.get("zone"))
        event = _backfilled(
            room_id,
            "overlay",
            f"{row.get('entity_id')}|{row.get('at')}",
            row.get("at"),
            "target.changed",
            zone,
            _WRITER_ACTORS.get(row.get("by"), "system"),
            {
                "key": row.get("field"),
                "scope": "room" if zone is None else f"zone:{zone}",
                "layer": "overlay",
                "old": row.get("old"),
                "new": row.get("new"),
                "expires": row.get("expires"),
                "reason": None,
                "expected": None,
                "entity_id": row.get("entity_id"),
            },
        )
        if event:
            out.append(event)
    return out
