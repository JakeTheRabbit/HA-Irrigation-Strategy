"""Backfilling the journal from the setpoint log, stock history, calibration history and overlays."""

import asyncio
from types import SimpleNamespace

from .test_journal_api import _rig

ROOM = "room:f2_"
ENTRY = "entry1"

SETPOINTS = [
    {
        "at": "2026-10-20T07:00:00+00:00",
        "entity_id": "number.crop_steering_f2_p1_target",
        "field": "p1_target",
        "zone": 2,
        "old": 50.0,
        "new": 52.0,
        "who": "learner",
        "reason": "dryback long",
    },
    {
        "at": "2026-10-20T08:00:00+00:00",
        "entity_id": "number.crop_steering_f2_day_length",
        "field": "day_length",
        "zone": None,
        "old": 12,
        "new": 13,
        "who": "operator",
    },
]
STOCK = [
    {
        "at": "2026-10-20T09:00:00+00:00",
        "source": "dosing",
        "draw_ml": {"a": 10.0, "b": 5.0},
        "key": "batch-1",
    },
    {"at": "2026-10-19T09:00:00+00:00", "source": "manual", "draw_ml": {"a": 20.0}},
]
CALIBRATION = [
    {
        "id": "abc123",
        "probe": "feed_ph",
        "kind": "ph",
        "entity_id": "sensor.ph",
        "at": "2026-10-18T10:00:00+00:00",
        "points": [
            {"reference": 4.0, "reading": 4.1},
            {"reference": 7.0, "reading": 7.0},
        ],
        "slope_pct": 96.7,
        "offset": 0.05,
        "verdict": "pass",
        "note": "",
    }
]
OVERLAYS = [
    {
        "entity_id": "number.crop_steering_f2_p1_target",
        "zone": 2,
        "field": "p1_target",
        "old": 50.0,
        "new": 55.0,
        "by": "brain",
        "at": "2026-10-21T06:00:00+00:00",
        "expires": "2026-10-21T18:00:00+00:00",
    }
]


def _stores(hass, **only):
    data = hass.data.setdefault("crop_steering", {})
    full = {
        "_setpoint_log": SimpleNamespace(changes=SETPOINTS),
        "_stock": SimpleNamespace(data={"history": STOCK}),
        "_calibration": SimpleNamespace(document={"records": CALIBRATION}),
        "_overlays": SimpleNamespace(rows={o["entity_id"]: o for o in OVERLAYS}),
    }
    for key, store in full.items():
        if not only or key in only:
            data.setdefault(key, {})[ENTRY] = store


def _entry():
    return SimpleNamespace(entry_id=ENTRY, data={"room_prefix": "f2_"})


async def _hub(hass, api, tmp_path):
    hub = api.JournalHub(hass, str(tmp_path / "journal.db"))
    await hub.async_init()
    hass.data.setdefault("crop_steering", {})["_journal"] = hub
    return hub


def _all(hub):
    return hub._journal.query(ROOM, since="2000-01-01T00:00:00+00:00")["events"]


def test_setpoint_rows_become_target_changed_with_their_writer():
    from custom_components.crop_steering import journal

    events = journal.import_setpoint_log(ROOM, SETPOINTS)
    first, second = events
    assert first["kind"] == "target.changed" and first["ts"] == SETPOINTS[0]["at"]
    assert first["source"]["actor"] == "learner" and first["zone"] == 2
    assert first["data"] == {
        "key": "p1_target",
        "scope": "zone:2",
        "layer": "base",
        "old": 50.0,
        "new": 52.0,
        "expires": None,
        "reason": "dryback long",
        "expected": None,
        "entity_id": "number.crop_steering_f2_p1_target",
    }
    assert second["source"]["actor"] == "manual" and second["data"]["scope"] == "room"
    for ev in events:
        journal.validate_event(ev)
    assert events == journal.import_setpoint_log(ROOM, SETPOINTS)  # stable ids


def test_the_other_importers_use_the_live_shapes():
    from custom_components.crop_steering import journal

    stock = journal.import_stock_history(ROOM, STOCK)
    assert [(e["kind"], e["data"]["tank"], e["data"]["ml"]) for e in stock] == [
        ("stock.drawn", "a", 10.0),
        ("stock.drawn", "b", 5.0),
        ("stock.drawn", "a", 20.0),
    ]
    assert (
        stock[0]["data"]["key"] == "batch-1" and stock[2]["source"]["actor"] == "manual"
    )
    assert len({e["id"] for e in stock}) == 3
    (cal,) = journal.import_calibration(ROOM, CALIBRATION)
    assert cal["kind"] == "calibration.captured"
    assert cal["data"]["record_id"] == "abc123" and cal["data"]["applied"] is False
    assert cal["data"]["verdict"] == "pass"
    (ov,) = journal.import_overlays(ROOM, OVERLAYS)
    assert ov["data"]["layer"] == "overlay" and ov["data"]["new"] == 55.0
    assert ov["data"]["expires"] == "2026-10-21T18:00:00+00:00"
    assert ov["source"]["actor"] == "ai"
    for ev in [*stock, cal, ov]:
        journal.validate_event(ev)


def test_rows_without_a_usable_time_are_skipped():
    from custom_components.crop_steering import journal

    assert journal.import_setpoint_log(ROOM, [{"at": "nope", "new": 1}, "x", {}]) == []


def test_backfill_is_idempotent_by_derived_id(tmp_path, monkeypatch):
    hass, api = _rig(monkeypatch, tmp_path)
    _stores(hass)

    async def go():
        hub = await _hub(hass, api, tmp_path)
        await api.async_backfill_room(hass, _entry())
        first = _all(hub)
        assert len(first) == 2 + 3 + 1 + 1
        # Forget the flag: the second run finds every id already there.
        hub._journal.meta_set(f"backfill:{ROOM}:v1", "")
        await api.async_backfill_room(hass, _entry())
        assert [e["id"] for e in _all(hub)] == [e["id"] for e in first]
        assert hass.bus.events == []  # old history is not re-announced

    asyncio.run(go())


def test_backfill_runs_once_per_room(tmp_path, monkeypatch):
    hass, api = _rig(monkeypatch, tmp_path)
    _stores(hass)

    async def go():
        hub = await _hub(hass, api, tmp_path)
        await api.async_backfill_room(hass, _entry())
        assert hub._journal.meta_get(f"backfill:{ROOM}:v1") == "done"

        class Boom:
            @property
            def changes(self):
                raise AssertionError("stores were read again")

        hass.data["crop_steering"]["_setpoint_log"][ENTRY] = Boom()
        await api.async_backfill_room(hass, _entry())
        assert len(_all(hub)) == 7

    asyncio.run(go())


def test_a_missing_store_is_skipped(tmp_path, monkeypatch):
    hass, api = _rig(monkeypatch, tmp_path)
    _stores(hass, _stock=1)

    async def go():
        hub = await _hub(hass, api, tmp_path)
        await api.async_backfill_room(hass, _entry())
        assert {e["kind"] for e in _all(hub)} == {"stock.drawn"}

    asyncio.run(go())


def test_a_journal_that_is_down_is_not_flagged_or_raised(tmp_path, monkeypatch):
    hass, api = _rig(monkeypatch, tmp_path)
    _stores(hass)
    (tmp_path / "journal.db").mkdir()

    async def go():
        hub = api.JournalHub(hass, str(tmp_path / "journal.db"))
        await hub.async_init()
        hass.data["crop_steering"]["_journal"] = hub
        await api.async_backfill_room(hass, _entry())  # must not raise

    asyncio.run(go())
