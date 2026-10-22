"""The integration's own stores write to the Journal (journal_api.emit): setpoint changes, plan changes, stock
draws and refills, calibration records and setup diffs. A journal that is down never stops any of them."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest

from . import ha_stubs

ha_stubs.install()

from custom_components.crop_steering import journal_api, setup_api  # noqa: E402
from custom_components.crop_steering.setpoint_log import SetpointLog  # noqa: E402

from .test_stock_api import BLOOM, mutate, rig as stock_rig  # noqa: E402
from .test_strategy import manager_fixture, plan  # noqa: E402

ENTITY = "number.crop_steering_f2_zone_3_p2_vwc_threshold"


@pytest.fixture
def emitted(monkeypatch):
    seen = []

    def fake(hass, room_id, kind, **kw):
        seen.append(SimpleNamespace(room_id=room_id, kind=kind, **kw))
        return "id"

    monkeypatch.setattr(journal_api, "emit", fake)
    return seen


class MemoryStore:
    def __init__(self):
        self.saved = None

    async def async_load(self):
        return None

    async def async_save(self, value):
        self.saved = value


def log_rig(operator=True):
    user = SimpleNamespace(system_generated=False)

    async def get_user(user_id):
        return user if operator else None

    hass = ha_stubs.FakeHass()
    hass.auth = SimpleNamespace(async_get_user=get_user)
    entry = ha_stubs.FakeEntry(data={"room_prefix": "f2_"}, entry_id="e")
    log = SetpointLog(hass, entry, MemoryStore())
    asyncio.run(log.async_init())
    return log


def record(log, old, new, context=None, zone=3):
    return asyncio.run(log.record(ENTITY, "p2_vwc_threshold", zone, old, new, context))


def test_a_learner_write_is_journaled_as_learner_with_old_and_new(emitted):
    log = log_rig()
    log.claim(
        {
            "entity_id": ENTITY,
            "value": 52.0,
            "who": "learner",
            "reason": "dryback ran long",
        }
    )
    record(log, 50.0, 52.0)
    (event,) = emitted
    assert (event.room_id, event.kind, event.zone, event.actor) == (
        "room:f2_",
        "target.changed",
        3,
        "learner",
    )
    assert event.user_id is None
    assert event.data == {
        "key": "p2_vwc_threshold",
        "scope": "zone:3",
        "layer": "base",
        "old": 50.0,
        "new": 52.0,
        "expires": None,
        "reason": "dryback ran long",
        "expected": None,
        "entity_id": ENTITY,
    }


def test_an_operator_write_is_manual_with_the_user_id(emitted):
    log = log_rig()
    record(log, 50.0, 51.0, SimpleNamespace(user_id="u1"))
    (event,) = emitted
    assert (event.actor, event.user_id) == ("manual", "u1")


def test_a_write_with_no_person_is_an_automation_and_the_brain_is_ai(emitted):
    log = log_rig(operator=False)
    record(log, 50.0, 51.0, SimpleNamespace(user_id=None), zone=None)
    log.claim(
        {
            "entity_id": ENTITY,
            "value": 49.0,
            "who": "brain",
            "expires": "2026-10-23T07:00:00+13:00",
            "expected": "less runoff",
        }
    )
    record(log, 51.0, 49.0, zone=None)
    auto, ai = emitted
    assert (auto.actor, auto.data["scope"]) == ("automation", "room")
    assert ai.actor == "ai"
    assert (ai.data["layer"], ai.data["expires"], ai.data["expected"]) == (
        "overlay",
        "2026-10-23T07:00:00+13:00",
        "less runoff",
    )


def test_a_safety_put_back_is_safety(emitted):
    log = log_rig()
    log.claim({"entity_id": ENTITY, "value": 50.0, "who": "safety"})
    record(log, 49.0, 50.0)
    assert emitted[0].actor == "safety"


def test_an_unchanged_value_journals_nothing(emitted):
    log = log_rig()
    record(log, 50.0, 50.0)
    assert emitted == [] and log.changes == []


def test_a_journal_that_is_down_never_stops_a_setpoint_write(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("journal exploded")

    monkeypatch.setattr(journal_api, "emit", boom)
    log = log_rig()
    record(log, 50.0, 52.0)
    assert [row["new"] for row in log.changes] == [52.0]
    assert log._store.saved == {"changes": log.changes}


def test_the_plan_journals_saved_armed_activated_disarmed_and_expired(
    monkeypatch, emitted
):
    manager, states, now = manager_fixture(monkeypatch)
    who = {"actor": "manual", "user_id": "u1", "client": None, "proposal_token": None}

    async def scenario():
        await manager.async_init()
        await manager.save(plan(), 0, who=who)
        await manager.activate(1, now, who=who)
        boundary = now + timedelta(hours=2)
        for state in states.values():
            state.last_updated = boundary
        await manager.tick(boundary)
        await manager.disarm(boundary + timedelta(minutes=1), who=who)
        await manager.tick(boundary + timedelta(days=1))

    asyncio.run(scenario())
    assert [e.kind for e in emitted] == [
        "plan.saved",
        "plan.armed",
        "plan.activated",
        "plan.disarmed",
        "plan.expired",
    ]
    saved, armed, activated, disarmed, expired = emitted
    assert (saved.actor, saved.user_id) == ("manual", "u1")
    assert (saved.data["revision"], saved.data["status"]) == (1, "draft")
    assert armed.data["status"] == "armed" and armed.correlation["plan_revision"] == 1
    assert (activated.actor, activated.data["status"]) == ("plan", "active")
    assert activated.data["zones"] == [1]
    assert disarmed.data["status"] == "disarming" and disarmed.user_id == "u1"
    assert (expired.actor, expired.data["status"]) == ("plan", "draft")
    assert all(e.room_id == manager.room_id for e in emitted)


def test_a_plan_that_fails_to_store_journals_nothing(monkeypatch, emitted):
    manager, _, now = manager_fixture(monkeypatch)

    async def scenario():
        await manager.async_init()

        async def fail(_data):
            raise OSError("disk unavailable")

        manager._store.async_save = fail
        with pytest.raises(OSError):
            await manager.save(plan(), 0)

    asyncio.run(scenario())
    assert emitted == []


def test_stock_refills_and_draws_are_journaled(emitted):
    _, store = stock_rig()
    mutate(store, "stock_save", tanks=[{**BLOOM, "level_l": 20}])
    assert emitted == []
    who = {"actor": "manual", "user_id": "u1", "client": None}
    asyncio.run(
        store.mutate("stock_refill", {"expected_revision": 1, "id": "bloom"}, who)
    )
    refilled = emitted.pop()
    assert (refilled.kind, refilled.actor, refilled.user_id) == (
        "stock.refilled",
        "manual",
        "u1",
    )
    assert refilled.data == {
        "tank": "bloom",
        "level_l": 50,
        "old_level_l": 20,
        "full": True,
    }
    asyncio.run(store.mutate("stock_record_batch", {"expected_revision": 2}, who))
    drawn = emitted.pop()
    assert (drawn.kind, drawn.data["tank"], drawn.data["ml"]) == (
        "stock.drawn",
        "bloom",
        1800.0,
    )
    assert (drawn.data["source"], drawn.data["key"]) == ("manual", None)
    asyncio.run(
        store.draw(
            {"key": "dose-1", "draws": {"bloom": 40}, "source": "dose"},
            {"actor": "mcp", "user_id": None, "client": "mcp"},
        )
    )
    controller = emitted.pop()
    assert (controller.actor, controller.data["key"], controller.data["ml"]) == (
        "mcp",
        "dose-1",
        40.0,
    )
    asyncio.run(store.draw({"key": "dose-1", "draws": {"bloom": 40}, "source": "dose"}))
    assert emitted == []  # a repeated key counts nothing and says nothing


def test_the_setup_diff_names_each_changed_path_and_keys_zones_by_id():
    old = {
        "room_name": "Tent",
        "zones": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
    }
    new = {
        "room_name": "Tent",
        "zones": [{"id": 1, "name": "A2"}, {"id": 2, "name": "B"}],
    }
    assert setup_api.setup_diff(old, new) == [
        {"path": "zones.1.name", "old": "A", "new": "A2"}
    ]
    assert setup_api.setup_diff(None, {"a": [1, 2]}) == [
        {"path": "a", "old": None, "new": [1, 2]}
    ]
    assert setup_api.setup_diff(new, new) == []


def test_a_saved_setup_journals_the_whole_setup_before_and_after(emitted):
    before = {
        "prefix": "f2_",
        "revision": 1,
        "room_name": "Tent",
        "safety": {"ready": True},
        "commissioning": {"x": 1},
        "entry_id": "e",
        "plumbing_inferred": "a",
        "active_zone_ids": [1],
        "zones": [{"id": 1, "name": "A", "sizing_generic": ["plant_count"]}],
    }
    room = {
        **before,
        "revision": 2,
        "room_name": "Back room",
        "safety": {"ready": False},
        "plumbing_inferred": "b",
        "active_zone_ids": [1, 2],
        "zones": [{"id": 1, "name": "A", "sizing_generic": []}],
    }
    who = {"actor": "manual", "user_id": "u1", "client": None}
    setup_api._journal(None, "setup_save", before, room, who)
    (event,) = emitted
    assert (event.room_id, event.kind, event.actor) == (
        "room:f2_",
        "config.changed",
        "manual",
    )
    assert event.correlation == {"setup_revision": 2}
    assert event.data["store"] == "setup" and event.data["section"] == "room"
    for side in (event.data["old"], event.data["new"]):
        assert not set(setup_api.DERIVED) & set(side)
        assert side["zones"] == [{"id": 1, "name": "A"}]
    assert event.data["old"]["room_name"] == "Tent"
    assert event.data["new"]["room_name"] == "Back room"
    assert [d["path"] for d in event.data["diff"]] == ["room_name"]
    emitted.clear()
    setup_api._journal(None, "setup_save", room, room, who)
    setup_api._journal(None, "setup_commission", before, room, who)
    assert emitted == []
    setup_api._journal(None, "setup_save", {**room, "revision": 3}, room, who)
    assert emitted == []  # a revision bump alone is not an operator change


def test_a_created_setup_has_no_old_and_a_removed_one_is_archived(emitted):
    who = {"actor": "manual", "user_id": "u1", "client": None}
    room = {"prefix": "f2_", "revision": 1, "room_name": "Tent", "active": True}
    setup_api._journal(None, "setup_create", None, room, who)
    created = emitted.pop()
    assert (created.kind, created.data["old"]) == ("config.changed", None)
    assert created.data["new"] == {"prefix": "f2_", "room_name": "Tent", "active": True}
    assert {"path": "room_name", "old": None, "new": "Tent"} in created.data["diff"]
    setup_api._journal(
        None, "setup_remove", room, {**room, "revision": 2, "active": False}, who
    )
    (removed,) = emitted
    assert removed.data["diff"] == [{"path": "active", "old": True, "new": False}]


def _call(user_id=None, **data):
    return SimpleNamespace(data=data, context=SimpleNamespace(user_id=user_id))


def test_a_calibration_record_is_journaled_as_captured_and_not_applied(emitted):
    from custom_components.crop_steering.calibration import journal_record

    record = {
        "id": "abc",
        "probe": "feed_ph",
        "kind": "ph",
        "entity_id": "sensor.feed_ph",
        "slope_pct": 98.3,
        "offset": 0.05,
        "verdict": "pass",
        "points": [],
        "note": "",
    }
    journal_record(None, "room:f2_", {"records": [record]}, _call("u1"))
    (event,) = emitted
    assert (event.kind, event.room_id, event.actor) == (
        "calibration.captured",
        "room:f2_",
        "manual",
    )
    assert event.data["applied"] is False and event.data["verdict"] == "pass"
    journal_record(
        None, "room:f2_", object(), _call("u1")
    )  # not a response: nothing, no error
    assert len(emitted) == 1


async def _done(value):
    return value


class Hub:
    """A journal that keeps what emit() hands it, after emit's own (real) validate_event."""

    failed = closed = False

    def __init__(self):
        self.events = []

    def schedule(self, room_id, event):
        self.events.append((room_id, event))


def test_every_kind_the_producers_emit_passes_the_real_validation(monkeypatch):
    from custom_components.crop_steering.calibration import journal_record
    from custom_components.crop_steering.journal import validate_event

    hub = Hub()
    hass = ha_stubs.FakeHass(data={"crop_steering": {"_journal": hub}})
    hass.auth = SimpleNamespace(
        async_get_user=lambda uid: _done(SimpleNamespace(system_generated=False))
    )
    entry = ha_stubs.FakeEntry(data={"room_prefix": "f2_"}, entry_id="e")
    log = SetpointLog(hass, entry, MemoryStore())
    asyncio.run(log.async_init())
    asyncio.run(
        log.record(ENTITY, "p2_vwc_threshold", 3, 50.0, 51.0, _call("u1").context)
    )
    who = {"actor": "manual", "user_id": "u1", "client": None}
    setup_api._journal(
        hass,
        "setup_save",
        {"prefix": "f2_", "revision": 1, "a": 1},
        {"prefix": "f2_", "revision": 2, "a": 2},
        who,
    )
    record = {
        "id": "x",
        "probe": "feed_ph",
        "kind": "ph",
        "entity_id": None,
        "slope_pct": 99.0,
        "offset": 0.0,
        "verdict": "pass",
        "points": [],
        "note": "",
    }
    journal_record(hass, "room:f2_", {"records": [record]}, _call("u1"))
    manager, _, _ = manager_fixture(monkeypatch)
    manager.hass.data["crop_steering"]["_journal"] = hub
    asyncio.run(manager.async_init())
    asyncio.run(manager.save(plan(), 0, who=who))
    _, store = stock_rig()
    store.hass.data["crop_steering"]["_journal"] = hub
    mutate(store, "stock_save", tanks=[{**BLOOM, "level_l": 20}])
    asyncio.run(store.mutate("stock_record_batch", {"expected_revision": 1}, who))
    assert [event["kind"] for _, event in hub.events] == [
        "target.changed",
        "config.changed",
        "calibration.captured",
        "plan.saved",
        "stock.drawn",
    ]
    for _, event in hub.events:
        assert validate_event(event) is event


def _overlay_rig(monkeypatch):
    """A room with the real SetpointLog, Overlays and keep / undo handlers; the number's `set_value` goes back
    through the setpoint log, as number.py does."""
    import sys
    import types

    store_module = types.ModuleType("homeassistant.helpers.storage")
    store_module.Store = lambda *a, **k: MemoryStore()
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.storage", store_module)
    monkeypatch.setattr(
        sys.modules["homeassistant.core"],
        "SupportsResponse",
        SimpleNamespace(ONLY="only"),
        raising=False,
    )
    from custom_components.crop_steering import overlays

    hass = ha_stubs.FakeHass()
    hass.auth = SimpleNamespace(
        async_get_user=lambda uid: _done(
            SimpleNamespace(is_admin=True, system_generated=False)
        )
    )
    hass.bus.async_listen = lambda *a: lambda: None
    hass.services.async_register = (
        lambda d, n, h, schema=None, supports_response=None: (
            hass.services.registered.__setitem__((d, n), h)
        )
    )
    hass.states.set(ENTITY, "47.0")
    entry = ha_stubs.FakeEntry(data={"room_prefix": "f2_"}, entry_id="e")
    log = SetpointLog(hass, entry, MemoryStore())
    asyncio.run(log.async_init())
    hass.data["crop_steering"] = {"_setpoint_log": {"e": log}}

    async def set_value(domain, service, data, blocking=False, context=None):
        old = float(hass.states.get(data["entity_id"]).state)
        hass.states.set(data["entity_id"], str(data["value"]))
        await log.record(
            data["entity_id"], "p2_vwc_threshold", 3, old, data["value"], context
        )

    hass.services.async_call = set_value
    asyncio.run(overlays.async_setup_overlays(hass, entry))
    held = hass.data["crop_steering"]["_overlays"]["e"]
    held.rows[ENTITY] = {
        "entity_id": ENTITY,
        "zone": 3,
        "field": "p2_vwc_threshold",
        "old": 50.0,
        "new": 47.0,
        "by": "brain",
        "at": "2026-10-22T07:00:00+13:00",
        "expires": "2026-10-23T07:00:00+13:00",
    }
    return hass, held, log


def _serve(hass, name):
    call = SimpleNamespace(
        service=name,
        data={"room_id": "room:f2_", "entity_id": ENTITY},
        context=SimpleNamespace(user_id="u1"),
    )
    asyncio.run(hass.services.registered[("crop_steering", name)](call))


def test_an_undo_is_one_value_change_and_one_overlay_removed_marker(
    monkeypatch, emitted
):
    hass, held, log = _overlay_rig(monkeypatch)
    _serve(hass, "overlay_undo")
    value, marker = emitted
    assert (value.kind, value.actor, value.user_id) == (
        "target.changed",
        "manual",
        "u1",
    )
    assert (value.data["layer"], value.data["old"], value.data["new"]) == (
        "base",
        47.0,
        50.0,
    )
    assert (marker.kind, marker.actor) == ("target.changed", "manual")
    assert (marker.data["layer"], marker.data["old"], marker.data["new"]) == (
        "overlay",
        47.0,
        None,
    )
    assert marker.data["reason"] == "undone" and held.rows == {}


def test_a_keep_is_only_the_overlay_marker_and_an_expiry_says_it_ran_out(
    monkeypatch, emitted
):
    hass, held, log = _overlay_rig(monkeypatch)
    _serve(hass, "overlay_keep")
    (marker,) = emitted
    assert (marker.data["layer"], marker.data["old"], marker.data["new"]) == (
        "overlay",
        47.0,
        None,
    )
    assert marker.data["reason"] == "kept" and log.changes == []
    emitted.clear()
    _, held2, _ = _overlay_rig(monkeypatch)
    asyncio.run(held2.end(ENTITY, put_back=True))  # it ran out: no caller
    (back,) = emitted
    assert (back.actor, back.data["reason"], back.data["new"]) == (
        "ai",
        "overlay ran out",
        50.0,
    )


def test_disarming_a_plan_that_is_already_a_draft_journals_nothing(
    monkeypatch, emitted
):
    manager, _, now = manager_fixture(monkeypatch)

    async def scenario():
        await manager.async_init()
        await manager.disarm(now)

    asyncio.run(scenario())
    assert emitted == []
