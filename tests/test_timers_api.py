"""Timer programs (G7), integration side: the per-room store, its services and timers_config.

TimerPrograms driven over an in-memory store with a fixed clock: programs are checked and previewed
through generated/timers.py (never a copy), a zone belongs to one active program at most, a preview
writes nothing, a delete is soft, skips expire 24 h after their time, and every save publishes
sensor.crop_steering_<prefix>timers_config and journals config.changed {store: "timers"}.
"""

import asyncio
import copy
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from . import ha_stubs

ha_stubs.install()

from custom_components.crop_steering import timers_api  # noqa: E402

NZ = ZoneInfo("Pacific/Auckland")
DOMAIN = "crop_steering"


class MemoryStore:
    def __init__(self, value=None):
        self.value, self.saves = value, 0

    async def async_load(self):
        if isinstance(self.value, Exception):
            raise self.value
        return copy.deepcopy(self.value)

    async def async_save(self, value):
        self.value, self.saves = copy.deepcopy(value), self.saves + 1


class States:
    def __init__(self):
        self.items = {}

    def async_set(self, entity_id, state, attributes=None):
        self.items[entity_id] = SimpleNamespace(
            state=state, attributes=attributes or {}
        )

    def async_remove(self, entity_id):
        self.items.pop(entity_id, None)

    def get(self, entity_id):
        return self.items.get(entity_id)


class Clock:
    def __init__(self):
        self.at = datetime(2026, 10, 22, 6, 0, tzinfo=NZ)

    def __call__(self):
        return self.at


def rig(prefix="f2_", value=None, hass=None, num_zones=6, entry_id=None):
    hass = hass or SimpleNamespace(states=States(), data={DOMAIN: {}})
    hass.clock = getattr(hass, "clock", None) or Clock()
    entry = SimpleNamespace(
        entry_id=entry_id or f"entry_{prefix}",
        data={"room_prefix": prefix, "num_zones": num_zones},
        options={},
    )
    backing = MemoryStore(value)
    room = timers_api.TimerPrograms(hass, entry, backing, now=hass.clock)
    assert room.sensor == f"sensor.{DOMAIN}_{prefix}timers_config"
    asyncio.run(room.async_init())
    hass.data[DOMAIN].setdefault("_timers", {})[entry.entry_id] = room
    room.publish()
    return hass, room, backing


@pytest.fixture
def journal(monkeypatch):
    seen = []
    monkeypatch.setattr(
        timers_api,
        "note",
        lambda hass, room_id, kind, **kw: seen.append((room_id, kind, kw)),
    )
    return seen


def recycle(**more):
    program = {
        "name": "Mothers AM",
        "type": "recycle",
        "zones": [1],
        "duration_s": 120,
        "interval_min": 30,
        "window": {"kind": "custom", "from": "08:00", "to": "12:00"},
    }
    program.update(more)
    return program


def put(room, program, expected=None):
    return asyncio.run(
        room.set_program(
            room.document["revision"] if expected is None else expected, program
        )
    )


def test_set_returns_a_24h_preview_of_8_shots(journal):
    hass, room, backing = rig()
    out = put(room, recycle())
    assert out["revision"] == 1 and backing.saves == 1
    program = out["program"]
    assert len(program["id"]) == 26 and program["name"] == "Mothers AM"
    assert program["active"] is True
    assert [p["at"][11:16] for p in out["preview"]] == [
        "08:00",
        "08:30",
        "09:00",
        "09:30",
        "10:00",
        "10:30",
        "11:00",
        "11:30",
    ]
    assert {(p["zone"], p["duration_s"]) for p in out["preview"]} == {(1, 120.0)}
    assert out["preview"][0]["at"] == "2026-10-22T08:00:00+13:00"
    published = hass.states.get(room.sensor)
    assert published.state == "1"
    assert published.attributes["revision"] == 1
    assert [p["id"] for p in published.attributes["programs"]] == [program["id"]]
    ((room_id, kind, kw),) = journal
    assert (room_id, kind) == ("room:f2_", "config.changed")
    data = kw["data"]
    assert (data["store"], data["section"], data["old"]) == ("timers", "programs", [])
    assert data["new"] == [program] and data["diff"]


def test_start_equal_end_is_refused_with_plain_words():
    _, room, backing = rig()
    with pytest.raises(ValueError, match="^End must be after start$"):
        put(room, recycle(window={"kind": "custom", "from": "08:00", "to": "08:00"}))
    assert backing.saves == 0 and room.document["revision"] == 0


def test_a_zone_in_two_active_programs_is_refused():
    _, room, backing = rig()
    put(room, recycle(zones=[1, 3]))
    with pytest.raises(ValueError, match="^Zone 3 is already in timer 'Mothers AM'$"):
        put(room, recycle(name="Flower PM", zones=[3, 4]))
    assert backing.saves == 1
    # an inactive program may share the zone, and switching it on is refused the same way
    off = put(room, recycle(name="Flower PM", zones=[3, 4], active=False))["program"]
    with pytest.raises(ValueError, match="^Zone 3 is already in timer 'Mothers AM'$"):
        put(room, {**off, "active": True})
    # editing a program never conflicts with itself
    first = room.document["programs"][0]
    assert put(room, {**first, "duration_s": 90})["program"]["duration_s"] == 90.0


def test_a_zone_the_room_does_not_have_is_refused():
    _, room, _ = rig(num_zones=4)
    with pytest.raises(ValueError, match="^Zone 5 is not in this room$"):
        put(room, recycle(zones=[5]))


def test_a_stale_revision_is_refused():
    _, room, backing = rig()
    put(room, recycle())
    with pytest.raises(ValueError, match="changed elsewhere"):
        put(room, recycle(zones=[2]), expected=0)
    assert backing.saves == 1


def test_missing_store_publishes_no_programs():
    hass, room, backing = rig()
    published = hass.states.get(room.sensor)
    assert published.state == "0"
    assert (
        published.attributes["programs"] == [] and published.attributes["skips"] == []
    )
    assert backing.saves == 0


def test_an_unreadable_store_publishes_unavailable_and_is_never_overwritten():
    for value in (
        OSError("disk"),
        {"revision": "x"},
        {"revision": 2, "programs": [{"type": "x"}]},
    ):
        hass, room, backing = rig(value=value)
        published = hass.states.get(room.sensor)
        assert published.state == "unavailable" and "error" in published.attributes
        with pytest.raises(ValueError, match="could not be"):
            put(room, recycle(), expected=room.document["revision"])
        assert backing.saves == 0


def test_preview_of_a_draft_writes_nothing():
    _, room, backing = rig()
    out = room.preview(recycle(), 48)
    assert out["shots"] == 16 and out["total_s"] == 16 * 120.0
    assert len(out["preview"]) == 16
    assert room.document["revision"] == 0 and backing.saves == 0
    with pytest.raises(ValueError, match="hours"):
        room.preview(recycle(), 49)
    with pytest.raises(ValueError, match="End must be after start"):
        room.preview(
            recycle(window={"kind": "custom", "from": "08:00", "to": "08:00"}), 24
        )


def test_delete_is_soft_and_frees_the_zone(journal):
    hass, room, backing = rig()
    program = put(room, recycle(zones=[3]))["program"]
    out = asyncio.run(room.delete_program(1, program["id"]))
    assert out["revision"] == 2
    stored = backing.value["programs"][0]
    assert stored["active"] is False and stored["deleted_at"]
    assert hass.states.get(room.sensor).attributes["programs"] == []
    assert put(room, recycle(name="Again", zones=[3]))["revision"] == 3
    with pytest.raises(ValueError, match="No timer program"):
        asyncio.run(room.delete_program(3, program["id"]))
    assert [e[2]["data"]["section"] for e in journal] == ["programs"] * 3


def test_list_without_room_returns_every_room_and_hides_deleted():
    hass, f2, _ = rig("f2_")
    _, f1, _ = rig("f1_", hass=hass)
    keep = put(f2, recycle(zones=[1, 2]))["program"]
    gone = put(f2, recycle(name="Old", zones=[4]))["program"]
    asyncio.run(f2.delete_program(2, gone["id"]))
    other = put(f1, recycle(name="F1 timer", zones=[1]))["program"]
    hass.states.async_set(f"select.{DOMAIN}_f2_zone_2_irrigation_mode", "timer")
    hass.states.async_set(f"select.{DOMAIN}_f2_zone_1_irrigation_mode", "steering")

    every = timers_api.list_programs(hass, None)
    assert sorted((p["room_id"], p["id"]) for p in every["programs"]) == sorted(
        [("room:f2_", keep["id"]), ("room:f1_", other["id"])]
    )
    assert every["revisions"] == {"room:f2_": 3, "room:f1_": 1}
    one = timers_api.list_programs(hass, "room:f2_")
    assert one["revision"] == 3
    (listed,) = one["programs"]
    assert listed["id"] == keep["id"] and listed["room_id"] == "room:f2_"
    assert listed["zones_in_timer_mode"] == [2]
    assert listed["next_at"] == "2026-10-22T08:00:00+13:00"
    with pytest.raises(ValueError, match="Room is unknown"):
        timers_api.list_programs(hass, "room:nope_")


def test_skip_is_published_and_expires_after_24h(journal):
    hass, room, backing = rig()
    out = asyncio.run(
        room.skip(
            0, 3, "2026-10-22T08:00:00+13:00", {"actor": "manual", "user_id": "u1"}
        )
    )
    assert out == {
        "skip": {
            "zone": 3,
            "at": "2026-10-22T08:00:00+13:00",
            "until": "2026-10-22T08:15:00+13:00",
        },
        "revision": 1,
    }
    assert backing.value["skips"][0]["by"] == {"actor": "manual", "user_id": "u1"}
    assert hass.states.get(room.sensor).attributes["skips"] == [out["skip"]]
    ((_, kind, kw),) = journal
    assert kind == "config.changed"
    assert (kw["data"]["store"], kw["data"]["section"]) == ("timers", "skip")
    assert kw["data"]["old"] == [] and kw["data"]["new"] == backing.value["skips"]
    # an instant in another offset is the same instant
    hass.clock.at = datetime(2026, 10, 23, 7, 59, tzinfo=NZ)
    put(room, recycle())
    assert len(backing.value["skips"]) == 1  # 23 h 59 min after: kept
    hass.clock.at += timedelta(minutes=2)
    put(room, recycle(name="Two", zones=[2]))
    assert backing.value["skips"] == []  # 24 h after its time: pruned on save
    assert hass.states.get(room.sensor).attributes["skips"] == []


def test_a_skip_names_a_zone_of_the_room_and_a_time_with_meaning():
    _, room, backing = rig(num_zones=2)
    with pytest.raises(ValueError, match="Zone 3 is not in this room"):
        asyncio.run(room.skip(0, 3, "2026-10-22T08:00:00+13:00", {}))
    with pytest.raises(ValueError, match="ISO"):
        asyncio.run(room.skip(0, 1, "tomorrow", {}))
    with pytest.raises(ValueError, match="more than 24 h ago"):
        asyncio.run(room.skip(0, 1, "2026-10-20T08:00:00+13:00", {}))
    assert backing.saves == 0


def test_python_interface_for_presets(journal):
    hass, room, backing = rig()
    out = asyncio.run(
        timers_api.set_programs(
            hass,
            room.entry.entry_id,
            [recycle(), recycle(name="B", zones=[2])],
            0,
            {"actor": "manual"},
        )
    )
    assert out["revision"] == 1
    got = timers_api.get_programs(hass, room.entry.entry_id)
    assert [p["name"] for p in got] == ["Mothers AM", "B"]
    with pytest.raises(ValueError, match="Zone 1 is already in timer 'Mothers AM'"):
        asyncio.run(
            timers_api.set_programs(
                hass, room.entry.entry_id, [*got, recycle(name="C")], 1, {}
            )
        )
    # a program left out of the list is soft-deleted, not lost
    asyncio.run(timers_api.set_programs(hass, room.entry.entry_id, got[1:], 1, {}))
    assert [p["name"] for p in timers_api.get_programs(hass, room.entry.entry_id)] == [
        "B"
    ]
    assert backing.value["programs"][0]["deleted_at"]
    assert journal[-1][2]["actor"] == "system"


def test_a_program_the_lights_moved_away_from_still_lists():
    hass, room, _ = rig()
    hass.states.async_set(f"number.{DOMAIN}_f2_lights_on_hour", "12")
    hass.states.async_set(f"number.{DOMAIN}_f2_lights_off_hour", "0")
    lit = recycle(window={"kind": "lights_on"}, sync_time="20:00")
    assert put(room, lit)["preview"][0]["at"] == "2026-10-22T20:00:00+13:00"
    hass.states.async_set(f"number.{DOMAIN}_f2_lights_off_hour", "18")
    # never silently stopped: it runs from the start of the moved window
    (listed,) = timers_api.list_programs(hass, "room:f2_")["programs"]
    assert listed["next_at"] == "2026-10-22T12:00:00+13:00" and listed["error"] is None
    # a save checks the sync time against the lights as they are now
    with pytest.raises(ValueError, match="sync time must be inside the window"):
        room.preview(lit, 24)


def test_one_program_that_cannot_be_projected_is_named_and_the_others_still_list(
    monkeypatch,
):
    hass, room, _ = rig()
    bad = put(room, recycle(name="Bad", zones=[1]))["program"]
    good = put(room, recycle(name="Good", zones=[2]))["program"]
    real = timers_api.timers.project

    def project(program, *args):
        if program["id"] == bad["id"]:
            raise RuntimeError("boom")
        return real(program, *args)

    monkeypatch.setattr(timers_api.timers, "project", project)
    listed = {p["name"]: p for p in timers_api.list_programs(hass, None)["programs"]}
    assert listed["Bad"]["next_at"] is None and "boom" in listed["Bad"]["error"]
    assert listed["Good"]["next_at"] == "2026-10-22T08:00:00+13:00"
    assert listed["Good"]["error"] is None and listed["Good"]["id"] == good["id"]


def test_a_skip_more_than_48_h_ahead_is_refused():
    _, room, backing = rig()
    with pytest.raises(ValueError, match="more than 48 h ahead"):
        asyncio.run(room.skip(0, 1, "2026-10-24T06:01:00+13:00", {}))
    assert (
        asyncio.run(room.skip(0, 1, "2026-10-24T06:00:00+13:00", {}))["revision"] == 1
    )
    assert backing.saves == 1


def test_a_hand_edited_skip_without_an_offset_is_dropped_not_fatal(caplog):
    stored = {
        "revision": 4,
        "programs": [],
        "skips": [
            {"zone": 1, "at": "2026-10-22T08:00:00", "until": "2026-10-22T08:15:00"},
            {
                "zone": 2,
                "at": "2026-10-22T09:00:00+13:00",
                "until": "2026-10-22T09:15:00+13:00",
            },
        ],
    }
    hass, room, _ = rig(value=stored)
    assert room.error is None
    assert [s["zone"] for s in hass.states.get(room.sensor).attributes["skips"]] == [2]
    assert "has no offset" in caplog.text
    put(room, recycle(), expected=4)  # prune and compare never raise
    assert [s["zone"] for s in room.document["skips"]] == [2]
