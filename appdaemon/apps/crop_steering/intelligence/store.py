"""SQLite analytics store for RootSense.

Single file at ``appdaemon/apps/crop_steering/state/rootsense.db`` (the
``state/`` directory is created on first use). All writes go through this
class so retention, schema migrations, and VACUUM are centralised.

Tables:

- ``shots``             — every irrigation shot (planned, fired, observed)
- ``dryback_episodes``  — peak → valley pairs with timing & EC context
- ``field_capacity``    — accepted FC observations per zone/cultivar
- ``anomalies``         — every anomaly the scanner has raised
- ``run_reports``       — JSON blobs from the nightly aggregator
- ``optimisation``      — per-zone posterior parameters for the bandit loop

Designed to be tiny — a year of 6-zone operation is well under 100 MB.
Daily VACUUM keeps fragmentation in check.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

_LOGGER = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 90

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS shots (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        ts            TEXT    NOT NULL,
        zone          INTEGER NOT NULL,
        phase         TEXT,
        shot_type     TEXT,           -- planned | custom | emergency | flush
        intent        REAL,           -- cultivator intent at the time
        volume_ml     REAL,
        duration_s    REAL,
        vwc_before    REAL,
        vwc_peak      REAL,
        ec_feed       REAL,
        ec_runoff     REAL,
        runoff_pct    REAL,
        tag           TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS dryback_episodes (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        zone          INTEGER NOT NULL,
        peak_ts       TEXT    NOT NULL,
        valley_ts     TEXT    NOT NULL,
        peak_vwc      REAL,
        valley_vwc    REAL,
        pct           REAL,
        duration_min  REAL,
        slope_pct_h   REAL,
        phase         TEXT,
        ec_at_peak    REAL,
        ec_at_valley  REAL,
        vpd_avg       REAL,
        dli_partial   REAL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS field_capacity (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        ts            TEXT    NOT NULL,
        zone          INTEGER NOT NULL,
        cultivar      TEXT,
        fc_pct        REAL    NOT NULL,
        confidence    REAL    NOT NULL,
        sample_count  INTEGER NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS anomalies (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        ts            TEXT    NOT NULL,
        zone          INTEGER,
        code          TEXT    NOT NULL,
        severity      TEXT    NOT NULL,         -- info | warning | critical
        evidence      TEXT,
        remediation   TEXT,
        resolved_ts   TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS run_reports (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        run_date      TEXT    NOT NULL UNIQUE,
        payload_json  TEXT    NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS optimisation (
        zone          INTEGER PRIMARY KEY,
        posterior_json TEXT   NOT NULL,
        updated_ts    TEXT    NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_shots_zone_ts ON shots(zone, ts);",
    "CREATE INDEX IF NOT EXISTS idx_dryback_zone_peak ON dryback_episodes(zone, peak_ts);",
    "CREATE INDEX IF NOT EXISTS idx_anomalies_ts ON anomalies(ts);",
]


class RootSenseStore:
    """Thread-safe SQLite wrapper. One instance per AppDaemon process."""

    def __init__(self, db_path: Path | str, retention_days: int = DEFAULT_RETENTION_DAYS) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days
        self._lock = threading.RLock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn() as c:
            for stmt in SCHEMA:
                c.execute(stmt)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            con = sqlite3.connect(self.db_path, timeout=10.0, isolation_level=None)
            try:
                con.execute("PRAGMA journal_mode=WAL;")
                con.execute("PRAGMA synchronous=NORMAL;")
                yield con
            finally:
                con.close()

    # ------------------------------------------------------------------ writers

    def record_shot(self, **fields: Any) -> int:
        cols = ", ".join(fields.keys())
        placeholders = ", ".join(["?"] * len(fields))
        with self._conn() as c:
            cur = c.execute(f"INSERT INTO shots ({cols}) VALUES ({placeholders})", tuple(fields.values()))
            return int(cur.lastrowid)

    def record_dryback_episode(self, **fields: Any) -> int:
        cols = ", ".join(fields.keys())
        placeholders = ", ".join(["?"] * len(fields))
        with self._conn() as c:
            cur = c.execute(
                f"INSERT INTO dryback_episodes ({cols}) VALUES ({placeholders})",
                tuple(fields.values()),
            )
            return int(cur.lastrowid)

    def record_field_capacity(self, ts: str, zone: int, cultivar: str | None,
                              fc_pct: float, confidence: float, sample_count: int) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO field_capacity (ts, zone, cultivar, fc_pct, confidence, sample_count) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ts, zone, cultivar, fc_pct, confidence, sample_count),
            )

    def record_anomaly(self, ts: str, zone: int | None, code: str, severity: str,
                       evidence: str, remediation: str) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO anomalies (ts, zone, code, severity, evidence, remediation) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ts, zone, code, severity, evidence, remediation),
            )
            return int(cur.lastrowid)

    def write_run_report(self, run_date: str, payload: dict[str, Any]) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO run_reports (run_date, payload_json) VALUES (?, ?)",
                (run_date, json.dumps(payload)),
            )

    def upsert_posterior(self, zone: int, posterior: dict[str, Any]) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO optimisation (zone, posterior_json, updated_ts) VALUES (?, ?, ?) "
                "ON CONFLICT(zone) DO UPDATE SET posterior_json=excluded.posterior_json, "
                "updated_ts=excluded.updated_ts",
                (zone, json.dumps(posterior), datetime.utcnow().isoformat()),
            )

    # ------------------------------------------------------------------ readers

    def latest_field_capacity(self, zone: int) -> tuple[float, float] | None:
        """Returns (fc_pct, confidence) or None if no observation yet."""
        with self._conn() as c:
            row = c.execute(
                "SELECT fc_pct, confidence FROM field_capacity "
                "WHERE zone = ? ORDER BY ts DESC LIMIT 1",
                (zone,),
            ).fetchone()
            return (row[0], row[1]) if row else None

    def recent_shots(self, zone: int, hours: int = 24) -> list[dict[str, Any]]:
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        with self._conn() as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                "SELECT * FROM shots WHERE zone = ? AND ts >= ? ORDER BY ts ASC",
                (zone, cutoff),
            ).fetchall()
            return [dict(r) for r in rows]

    def load_posterior(self, zone: int) -> dict[str, Any] | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT posterior_json FROM optimisation WHERE zone = ?",
                (zone,),
            ).fetchone()
            return json.loads(row[0]) if row else None

    # ------------------------------------------------------------------ retention

    def prune(self) -> None:
        cutoff = (datetime.utcnow() - timedelta(days=self.retention_days)).isoformat()
        with self._conn() as c:
            for table, ts_col in [
                ("shots", "ts"),
                ("dryback_episodes", "peak_ts"),
                ("anomalies", "ts"),
            ]:
                c.execute(f"DELETE FROM {table} WHERE {ts_col} < ?", (cutoff,))
            c.execute("VACUUM;")
        _LOGGER.info("RootSense store pruned (retention=%s days)", self.retention_days)
