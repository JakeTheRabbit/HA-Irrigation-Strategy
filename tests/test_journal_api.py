"""journal_append, journal_query, the bus event and emit() (journal_api.py), against the stubs."""

import asyncio
import logging
import sys
from types import SimpleNamespace

import pytest

from custom_components.crop_steering.generated.ids import new_id

ROOM = "room:f2_"


def _event(kind="shot.completed", **over):
    ev = {
        "v": 1,
        "id": new_id(),
        "ts": "2026-10-22T07:00:00+00:00",
        "kind": kind,
        "zone": 3,
        "outcome": "ok",
        "source": {"actor": "engine"},
        "correlation": {"intent_id": None},
        "data": {},
    }
    ev.update(over)
    return ev


def _rig(monkeypatch, path):
    from . import ha_stubs

    ha_stubs.install()
    core = sys.modules["homeassistant.core"]
    monkeypatch.setattr(
        core,
        "SupportsResponse",
        SimpleNamespace(ONLY="only", OPTIONAL="optional"),
        raising=False,
    )
    from custom_components.crop_steering import journal_api

    hass = ha_stubs.FakeHass()
    hass.services.async_register = (
        lambda d, n, h, schema=None, supports_response=None: (
            hass.services.registered.__setitem__((d, n), h)
        )
    )
    hass.config = SimpleNamespace(path=lambda *parts: str(path.joinpath(*parts)))
    hass.async_add_executor_job = lambda fn, *a: _done(fn(*a))
    hass.async_create_task = lambda coro: asyncio.ensure_future(coro)
    return hass, journal_api


async def _done(value):
    return value


def test_append_fires_each_new_event_once_on_the_bus(tmp_path, monkeypatch):
    hass, api = _rig(monkeypatch, tmp_path)

    async def go():
        hub = api.JournalHub(hass, str(tmp_path / "journal.db"))
        await hub.async_init()
        assert hub.ok
        first, second = _event(), _event()
        out = await hub.append(ROOM, [first, second, first])
        assert len(out["accepted"]) == 2 and len(out["duplicate"]) == 1
        assert [d["id"] for _, d in hass.bus.events] == [first["id"], second["id"]]
        assert {t for t, _ in hass.bus.events} == {"crop_steering_event"}
        assert [d["seq"] for _, d in hass.bus.events] == [1, 2]
        assert all(d["room_id"] == ROOM for _, d in hass.bus.events)

    asyncio.run(go())


def test_append_refuses_more_than_50_events(tmp_path, monkeypatch):
    hass, api = _rig(monkeypatch, tmp_path)
    from homeassistant.exceptions import HomeAssistantError

    async def go():
        hub = api.JournalHub(hass, str(tmp_path / "journal.db"))
        await hub.async_init()
        with pytest.raises(HomeAssistantError, match="at most 50"):
            await hub.append(ROOM, [_event() for _ in range(51)])
        assert hass.bus.events == []

    asyncio.run(go())


def test_a_journal_that_cannot_open_logs_and_emit_is_a_noop(
    tmp_path, monkeypatch, caplog
):
    hass, api = _rig(monkeypatch, tmp_path)
    (tmp_path / "journal.db").mkdir()  # a directory where the file should be

    async def go():
        hub = api.JournalHub(hass, str(tmp_path / "journal.db"))
        with caplog.at_level(logging.WARNING):
            await hub.async_init()
        assert hub.ok is False
        assert "journal" in caplog.text.lower()
        hass.data.setdefault("crop_steering", {})["_journal"] = hub
        assert api.emit(hass, ROOM, "shot.completed", zone=3) is None
        from homeassistant.exceptions import HomeAssistantError

        with pytest.raises(HomeAssistantError, match="unavailable"):
            await hub.append(ROOM, [_event()])

    asyncio.run(go())


def test_setup_never_raises_when_the_journal_cannot_open(tmp_path, monkeypatch, caplog):
    hass, api = _rig(monkeypatch, tmp_path)
    (tmp_path / "crop_steering").mkdir()
    (tmp_path / "crop_steering" / "journal.db").mkdir()
    monkeypatch.setattr(api, "_wire", lambda hass, hub: [])
    with caplog.at_level(logging.WARNING):

        async def go():
            await api.async_setup_journal(hass)
            await asyncio.sleep(0.05)

        asyncio.run(go())
    assert hass.data["crop_steering"]["_journal"].ok is False
    assert {n for (_, n) in hass.services.registered} == {
        "journal_append",
        "journal_query",
        "history_changes",
        "history_revert",
    }


def test_emit_stores_one_event_and_returns_its_id(tmp_path, monkeypatch):
    hass, api = _rig(monkeypatch, tmp_path)

    async def go():
        hub = api.JournalHub(hass, str(tmp_path / "journal.db"))
        await hub.async_init()
        hass.data.setdefault("crop_steering", {})["_journal"] = hub
        eid = api.emit(
            hass, ROOM, "phase.changed", zone=2, actor="plan", data={"to": "P2"}
        )
        assert eid
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        got = (await hub.query(room_id=ROOM, since="2026-01-01T00:00:00+00:00"))[
            "events"
        ]
        assert [e["id"] for e in got] == [eid]
        assert got[0]["source"]["actor"] == "plan" and got[0]["data"] == {"to": "P2"}

    asyncio.run(go())


def test_emit_with_no_hub_returns_none():
    from . import ha_stubs

    ha_stubs.install()
    from custom_components.crop_steering import journal_api

    assert journal_api.emit(ha_stubs.FakeHass(), ROOM, "shot.completed") is None


def test_attribution_follows_the_setpoint_log_rule():
    from . import ha_stubs

    ha_stubs.install()
    from custom_components.crop_steering.journal_api import attribution

    def call(user_id, **data):
        return SimpleNamespace(context=SimpleNamespace(user_id=user_id), data=data)

    assert attribution(None, call("u1", client="mcp"))["actor"] == "mcp"
    assert attribution(None, call(None, client="aigrow"))["actor"] == "aigrow"
    assert attribution(None, call("u1"))["actor"] == "manual"
    assert attribution(None, call(None))["actor"] == "automation"
    got = attribution(None, call("u1", client="mcp", proposal_token="tok"))
    assert got == {
        "actor": "mcp",
        "user_id": "u1",
        "client": "mcp",
        "proposal_token": "tok",
    }


def test_an_event_emitted_while_the_journal_opens_is_stored_once_it_is_open(
    tmp_path, monkeypatch
):
    hass, api = _rig(monkeypatch, tmp_path)

    async def go():
        hub = api.JournalHub(hass, str(tmp_path / "journal.db"))
        hass.data.setdefault("crop_steering", {})["_journal"] = hub
        assert hub.opening
        first = api.emit(hass, ROOM, "phase.changed", zone=1)
        second = api.emit(hass, ROOM, "phase.changed", zone=2)
        assert first and second
        await asyncio.sleep(0)
        await hub.async_init()
        await asyncio.sleep(0.05)
        got = (await hub.query(room_id=ROOM, since="2026-01-01T00:00:00+00:00"))[
            "events"
        ]
        assert [e["id"] for e in got] == [first, second]

    asyncio.run(go())


def test_an_event_emitted_just_before_an_unload_and_reload_is_stored(
    tmp_path, monkeypatch
):
    hass, api = _rig(monkeypatch, tmp_path)

    async def go():
        path = str(tmp_path / "journal.db")
        lock = asyncio.Lock()
        old = api.JournalHub(hass, path, lock)
        await old.async_init()
        data = hass.data.setdefault("crop_steering", {})
        data["_journal"] = old
        eid = api.emit(hass, ROOM, "phase.changed", zone=1)
        old.close_soon()  # the unload
        data.pop("_journal")
        new = api.JournalHub(hass, path, lock)  # the reload
        data["_journal"] = new
        await new.async_init()
        await asyncio.sleep(0.05)
        got = (await new.query(room_id=ROOM, since="2026-01-01T00:00:00+00:00"))[
            "events"
        ]
        assert [e["id"] for e in got] == [eid]

    asyncio.run(go())


def test_a_close_that_lands_while_the_journal_opens_leaves_no_open_connection(
    tmp_path, monkeypatch
):
    hass, api = _rig(monkeypatch, tmp_path)

    async def go():
        hub = api.JournalHub(hass, str(tmp_path / "journal.db"))

        async def slow_open(fn, *a):
            if fn == hub._open:
                await asyncio.sleep(0.1)
            return fn(*a)

        hass.async_add_executor_job = slow_open
        opening = asyncio.ensure_future(hub.async_init())
        await asyncio.sleep(0.01)
        assert hub.opening
        hub.close_soon()  # a reload that lands mid-open
        await opening
        await asyncio.sleep(0.2)
        assert hub._journal._db is None

    asyncio.run(go())


def test_emit_refuses_a_malformed_event_synchronously(tmp_path, monkeypatch, caplog):
    hass, api = _rig(monkeypatch, tmp_path)

    async def go():
        hub = api.JournalHub(hass, str(tmp_path / "journal.db"))
        await hub.async_init()
        hass.data.setdefault("crop_steering", {})["_journal"] = hub
        with caplog.at_level(logging.WARNING):
            assert api.emit(hass, ROOM, "shot.completed", actor="nobody") is None
            assert api.emit(hass, ROOM, "shot.completed", outcome="great") is None
        assert "not recorded" in caplog.text

    asyncio.run(go())


def test_a_failed_wire_leaves_no_hub_and_no_services(tmp_path, monkeypatch):
    hass, api = _rig(monkeypatch, tmp_path)
    hass.services.async_remove = lambda d, n: hass.services.registered.pop((d, n), None)

    def boom(hass, hub):
        raise RuntimeError("no websocket")

    monkeypatch.setattr(api, "_wire", boom)
    with pytest.raises(RuntimeError):
        asyncio.run(api.async_setup_journal(hass))
    assert "_journal" not in hass.data["crop_steering"]
    assert hass.services.registered == {}
