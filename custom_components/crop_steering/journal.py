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
            db.executescript(_SCHEMA)
            db.commit()
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
