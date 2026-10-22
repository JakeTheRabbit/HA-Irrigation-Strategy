"""The SQLite event journal (custom_components/.../journal.py). No HA needed."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.crop_steering.generated.ids import new_id
from custom_components.crop_steering.journal import Journal, validate_event

ROOM = "room:f2_"
T0 = datetime(2026, 10, 22, 7, 0, tzinfo=UTC)


def _ev(kind="shot.completed", at=None, ts=None, zone=3, actor="engine", **over):
    at = at or T0
    ev = {
        "v": 1,
        "id": new_id(),
        "ts": ts or at.isoformat(),
        "kind": kind,
        "zone": zone,
        "outcome": "ok",
        "source": {"actor": actor},
        "correlation": {"intent_id": None},
        "data": {},
    }
    ev.update(over)
    return ev


def _open(tmp_path):
    j = Journal(str(tmp_path / "journal.db"))
    j.open()
    return j


def test_append_assigns_per_room_monotonic_seq_and_is_idempotent(tmp_path):
    j = _open(tmp_path)
    a, b = _ev("shot.completed"), _ev("phase.changed")
    r1 = j.append(ROOM, [a, b])
    r2 = j.append(ROOM, [a])
    assert r1["accepted"] == [a["id"], b["id"]] and r1["seq_max"] == 2
    assert [e["seq"] for e in r1["stored"]] == [1, 2]
    assert r2 == {"accepted": [], "duplicate": [a["id"]], "seq_max": 2, "stored": []}
    assert j.append("room:", [_ev("shot.completed")])["seq_max"] == 1


def test_query_filters_kind_zone_actor_and_pages_with_cursor(tmp_path):
    j = _open(tmp_path)
    evs = [
        _ev("shot.completed", at=T0 + timedelta(minutes=i), zone=1 + i % 2)
        for i in range(7)
    ]
    evs.append(
        _ev("phase.changed", at=T0 + timedelta(minutes=9), zone=1, actor="manual")
    )
    j.append(ROOM, evs)
    since = T0.isoformat()
    seen, cursor, sizes = [], None, []
    while True:
        r = j.query(ROOM, since, kinds=["shot.completed"], limit=3, cursor=cursor)
        sizes.append(len(r["events"]))
        seen += [e["id"] for e in r["events"]]
        cursor = r["cursor"]
        if cursor is None:
            break
    assert sizes == [3, 3, 1] and seen == [e["id"] for e in evs[:7]]
    assert len(j.query(ROOM, since, zones=[2])["events"]) == 3
    assert [e["kind"] for e in j.query(ROOM, since, actor="manual")["events"]] == [
        "phase.changed"
    ]
    desc = j.query(ROOM, since, order="desc", limit=2)
    assert desc["events"][0]["kind"] == "phase.changed" and desc["cursor"]
    assert (
        len(
            j.query(ROOM, since, until=(T0 + timedelta(minutes=2)).isoformat())[
                "events"
            ]
        )
        == 2
    )


def test_query_orders_by_instant_not_by_offset_text(tmp_path):
    j = _open(tmp_path)
    # 07:00+13:00 is 18:00Z the day before, yet as text it sorts after 06:00Z
    early = _ev(ts="2026-10-22T07:00:00+13:00")
    late = _ev(ts="2026-10-22T06:00:00Z")
    j.append(ROOM, [late, early])
    got = j.query(ROOM, "2026-10-21T00:00:00Z")["events"]
    assert [e["id"] for e in got] == [early["id"], late["id"]]


def test_prune_drops_old_shots_but_keeps_changes_forever(tmp_path):
    j = _open(tmp_path)
    old = T0 - timedelta(days=401)
    shot, change = _ev("shot.completed", at=old), _ev("target.changed", at=old)
    fresh = _ev("shot.completed", at=T0 - timedelta(days=399))
    j.append(ROOM, [shot, change, fresh])
    assert j.prune(int(T0.timestamp() * 1000)) == 1
    ids = [e["id"] for e in j.query(ROOM, "2020-01-01T00:00:00Z")["events"]]
    assert ids == [change["id"], fresh["id"]]


@pytest.mark.parametrize(
    "bad",
    [
        {"v": 2},
        {"kind": "nope"},
        {"source": {"actor": "robot"}},
        {"outcome": "meh"},
        {"id": "short"},
    ],
)
def test_validate_event_refuses(bad):
    assert validate_event(_ev())
    with pytest.raises(ValueError):
        validate_event({**_ev(), **bad})


def test_append_is_all_or_nothing_on_a_bad_event(tmp_path):
    j = _open(tmp_path)
    with pytest.raises(ValueError):
        j.append(ROOM, [_ev(), _ev(kind="nope")])
    assert j.query(ROOM, "2020-01-01T00:00:00Z")["events"] == []


def test_limit_is_capped_at_500(tmp_path):
    j = _open(tmp_path)
    j.append(ROOM, [_ev(at=T0 + timedelta(seconds=i)) for i in range(501)])
    r = j.query(ROOM, T0.isoformat(), limit=10_000)
    assert len(r["events"]) == 500 and r["cursor"]
    assert len(j.query(ROOM, T0.isoformat(), cursor=r["cursor"])["events"]) == 1


def test_meta_roundtrip_and_reopen_keeps_seq(tmp_path):
    j = _open(tmp_path)
    assert j.meta_get("k") is None
    j.meta_set("k", "1")
    j.meta_set("k", "2")
    j.append(ROOM, [_ev()])
    j.close()
    j2 = _open(tmp_path)
    assert j2.meta_get("k") == "2"
    assert j2.append(ROOM, [_ev()])["seq_max"] == 2


def test_open_closes_the_connection_when_the_schema_cannot_be_created(
    tmp_path, monkeypatch
):
    import sqlite3

    closed = []

    class Spy:
        def __init__(self, real):
            self._real = real

        def executescript(self, sql):
            raise sqlite3.DatabaseError("file is not a database")

        def close(self):
            closed.append(True)
            self._real.close()

    real_connect = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: Spy(real_connect(*a, **k)))
    with pytest.raises(sqlite3.DatabaseError):
        Journal(str(tmp_path / "j.db")).open()
    assert closed == [True]
