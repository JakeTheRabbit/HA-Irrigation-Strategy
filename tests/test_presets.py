"""Server presets and copy_config (G10): the pure capture/diff, the write with read-back, and the
shared preset list in the site store.

Driven over a fake Home Assistant whose number.set_value writes the state (and can clamp one
entity, as a number at its limit does), so a write that does not hold its value reads back refused.
"""

import asyncio
import copy
import sys
from types import SimpleNamespace

import pytest

from . import ha_stubs

ha_stubs.install()

from custom_components.crop_steering import presets, site_api  # noqa: E402
from custom_components.crop_steering.const import DOMAIN  # noqa: E402

core = sys.modules["homeassistant.core"]
if not hasattr(core, "Context"):

    class Context:
        made = 0

        def __init__(self, user_id=None):
            Context.made += 1
            self.user_id, self.id = user_id, f"context-{Context.made}"

    core.Context = Context

ROOM = "room:f2_"
WHO = {"actor": "manual", "user_id": "admin", "client": None}


def number(key):
    return f"number.{DOMAIN}_f2_{key}"


class States(ha_stubs.FakeStates):
    def async_set(self, entity_id, state, attributes=None):
        self.set(entity_id, state, attributes)

    def async_remove(self, entity_id):
        self._m.pop(entity_id, None)


class Services:
    def __init__(self, hass, clamp):
        self.hass, self.clamp, self.calls = hass, clamp, []

    async def async_call(self, domain, service, data, blocking=False, context=None):
        self.calls.append((domain, service, dict(data)))
        entity_id = data["entity_id"]
        if domain == "number":
            value = min(float(data["value"]), self.clamp.get(entity_id, float("inf")))
            self.hass.states.set(entity_id, str(value))
        else:
            self.hass.states.set(entity_id, data["option"])


def rig(values, clamp=None):
    """One room, f2_, with 3 zones: `values` {entity key: value}, e.g. {"zone_3_p2_shot_size": 5}."""
    entry = ha_stubs.FakeEntry(
        data={"room_prefix": "f2_", "num_zones": 3}, entry_id="f2"
    )
    hass = ha_stubs.FakeHass(entries=[entry])
    hass.states = States()
    hass.services = Services(hass, clamp or {})
    numbers = {}
    for zone in (1, 2, 3):
        numbers[f"zone_{zone}_plant_count"] = SimpleNamespace(
            entity_id=number(f"zone_{zone}_plant_count")
        )
    for key, value in values.items():
        if key.endswith("p2_mode"):
            hass.states.set(f"select.{DOMAIN}_f2_{key}", value)
            continue
        numbers[key] = SimpleNamespace(entity_id=number(key))
        hass.states.set(number(key), str(value))
    hass.data = {DOMAIN: {"_numbers": {"f2": numbers}}}
    return hass


def run(coro):
    return asyncio.run(coro)


def test_capture_keeps_each_sections_keys_and_diff_only_what_differs():
    values = {
        "p2_shot_size": 5.0,
        "p2_mode": "Timed",
        "p0_minimum_wait": 10.0,
        "min_daily_ml_per_plant": 50.0,
        "lights_on_hour": 6.0,  # in no section
    }
    captured = presets.capture(values, ("targets", "water_limits"))
    assert captured == {
        "targets": {"p2_shot_size": 5.0, "p2_mode": "Timed"},
        "water_limits": {"min_daily_ml_per_plant": 50.0},
    }
    current = {"targets": {"p2_shot_size": 5.0, "p2_mode": "Moisture"}}
    assert presets.diff(current, captured) == [
        {"section": "targets", "key": "p2_mode", "old": "Moisture", "new": "Timed"},
        {
            "section": "water_limits",
            "key": "min_daily_ml_per_plant",
            "old": None,
            "new": 50.0,
            "missing": True,
        },
    ]


def test_preview_lists_only_changed_rows():
    hass = rig(
        {
            "zone_3_p2_shot_size": 5.0,
            "zone_3_p1_target_vwc": 60.0,
            "zone_3_p2_mode": "Timed",
            "zone_1_p2_shot_size": 3.0,
            "zone_1_p1_target_vwc": 60.0,
            "zone_1_p2_mode": "Moisture",
            "zone_2_p2_shot_size": 5.0,
            "zone_2_p1_target_vwc": 60.0,
            "zone_2_p2_mode": "Timed",
        }
    )
    source = {"room_id": ROOM, "zone": 3}
    wanted = presets.capture(presets.read_values(hass, source), ("targets",))
    to = [{"room_id": ROOM, "zone": 1}, {"room_id": ROOM, "zone": 2}]
    out = run(presets.apply(hass, wanted, to, True, WHO))
    assert out["diff"] == [
        {"target": to[0], "key": "p2_shot_size", "old": 3.0, "new": 5.0},
        {"target": to[0], "key": "p2_mode", "old": "Moisture", "new": "Timed"},
    ]
    assert "applied" not in out and out["missing"] == []
    assert hass.services.calls == []  # a preview writes nothing


def test_apply_reads_back_each_target_and_reports_refused_ones():
    shot_1 = number("zone_1_p2_shot_size")
    hass = rig(
        {
            "zone_3_p2_shot_size": 5.0,
            "zone_3_p2_time_between_shots": 30.0,
            "zone_1_p2_shot_size": 3.0,
            "zone_1_p2_time_between_shots": 20.0,
        },
        clamp={shot_1: 4.0},  # zone 1's shot size stops at 4
    )
    wanted = presets.capture(
        presets.read_values(hass, {"room_id": ROOM, "zone": 3}),
        ("targets", "phase_timing", "water_limits"),
    )
    to = [{"room_id": ROOM, "zone": 1}]
    out = run(presets.apply(hass, wanted, to, False, WHO))
    assert out["applied"] == [
        {"target": to[0], "key": "p2_shot_size", "readback": "refused", "error": None},
        {
            "target": to[0],
            "key": "p2_time_between_shots",
            "readback": "verified",
            "error": None,
        },
    ]
    assert hass.states.get(shot_1).state == "4.0"
    # The re-preview still shows the refused row, and only that one.
    again = run(presets.apply(hass, wanted, to, True, WHO))
    assert [(r["key"], r["old"], r["new"]) for r in again["diff"]] == [
        ("p2_shot_size", 4.0, 5.0)
    ]


def test_write_numbers_reports_old_new_and_readback_for_each_write():
    shot = number("p2_shot_size")
    wait = number("p0_minimum_wait")
    hass = rig({"p2_shot_size": 3.0, "p0_minimum_wait": 10.0}, clamp={shot: 4.0})
    results = run(
        presets.write_numbers(
            hass,
            "f2",
            [
                {"entity_id": shot, "key": "p2_shot_size", "value": 6.0},
                {"entity_id": wait, "key": "p0_minimum_wait", "value": 12.0},
            ],
            WHO,
        )
    )
    assert results == [
        {
            "entity_id": shot,
            "key": "p2_shot_size",
            "old": 3.0,
            "new": 4.0,
            "readback": "refused",
            "error": None,
        },
        {
            "entity_id": wait,
            "key": "p0_minimum_wait",
            "old": 10.0,
            "new": 12.0,
            "readback": "verified",
            "error": None,
        },
    ]


def test_a_key_with_no_entity_at_the_destination_is_missing_and_never_written():
    hass = rig({"zone_3_p2_mode": "Timed", "zone_3_p2_shot_size": 5.0})
    hass.states.set(number("p2_shot_size"), "3.0")
    hass.data[DOMAIN]["_numbers"]["f2"]["p2_shot_size"] = SimpleNamespace(
        entity_id=number("p2_shot_size")
    )
    wanted = presets.capture(
        presets.read_values(hass, {"room_id": ROOM, "zone": 3}), ("targets",)
    )
    out = run(presets.apply(hass, wanted, [{"room_id": ROOM}], False, WHO))
    # The room has no P2 mode select: listed as missing, not in the diff, not written.
    assert out["missing"] == [{"target": {"room_id": ROOM}, "key": "p2_mode"}]
    assert [r["key"] for r in out["diff"]] == ["p2_shot_size"]
    assert [c[0] for c in hass.services.calls] == ["number"]


def test_an_unknown_room_or_zone_is_refused_before_anything_is_written():
    hass = rig({"zone_3_p2_shot_size": 5.0, "zone_1_p2_shot_size": 3.0})
    wanted = {"targets": {"p2_shot_size": 5.0}}
    for bad in ({"room_id": "room:veg_"}, {"room_id": ROOM, "zone": 9}):
        with pytest.raises(ValueError):
            run(
                presets.apply(
                    hass, wanted, [{"room_id": ROOM, "zone": 1}, bad], False, WHO
                )
            )
    assert hass.services.calls == []


def test_timer_programs_follow_the_zone_into_the_target_room():
    program = {
        "id": "A",
        "name": "Morning",
        "type": "interval",
        "zones": [3],
        "duration_s": 30,
        "active": True,
    }
    shape = {k: v for k, v in program.items() if k not in ("id", "zones")}
    assert presets.timer_value([program], 3) == shape
    assert presets.timer_value([program], 1) is None
    # Zone 1 joins the program that already has the same shape; zone 2 leaves its own.
    other = {**program, "id": "B", "name": "Old", "zones": [2]}
    out = presets.zone_programs([program, other], 1, shape)
    assert [(p["id"], p["zones"]) for p in out] == [("A", [1, 3]), ("B", [2])]
    out = presets.zone_programs(out, 2, shape)
    assert [(p["id"], p["zones"]) for p in out] == [("A", [1, 2, 3])]
    out = presets.zone_programs(out, 1, None)
    assert [(p["id"], p["zones"]) for p in out] == [("A", [2, 3])]


# ------------------------------------------------------------------ the shared preset list
class MemoryStore:
    def __init__(self, value=None):
        self.value = value

    async def async_load(self):
        return copy.deepcopy(self.value)

    async def async_save(self, value):
        self.value = copy.deepcopy(value)


def site(backing):
    hass = SimpleNamespace(states=States(), data={})
    store = site_api.SiteStore(hass, backing)
    run(store.async_init())
    return store


def test_a_preset_saved_once_is_listed_for_every_client():
    backing = MemoryStore()
    phone = site(backing)
    saved = run(
        phone.save_preset(
            {
                "name": "Flower week 3",
                "scope": "targets",
                "from": {"room_id": ROOM, "zone": 3},
                "expected_revision": 0,
            },
            {"targets": {"p2_shot_size": 5.0}},
            WHO,
        )
    )
    assert saved["revision"] == 1
    preset = saved["preset"]
    assert (preset["name"], preset["sections"]) == ("Flower week 3", ["targets"])
    assert preset["values"] == {"targets": {"p2_shot_size": 5.0}}
    listed = phone.presets_response()
    assert [p["id"] for p in listed["presets"]] == [preset["id"]]
    # Another client, or the same one after a restart, reads the one stored list.
    desk = site(backing)
    assert desk.presets_response() == listed
    with pytest.raises(ValueError, match="changed elsewhere"):
        run(
            desk.save_preset(
                {
                    "name": "x",
                    "scope": "all",
                    "from": {"room_id": ROOM},
                    "expected_revision": 0,
                },
                {},
                WHO,
            )
        )
    # A delete is soft: gone from the list, kept in the store.
    run(desk.delete_preset({"id": preset["id"], "expected_revision": 1}, WHO))
    assert desk.presets_response()["presets"] == []
    assert backing.value["presets"][0]["deleted_at"]
    with pytest.raises(ValueError, match="No preset"):
        desk.preset(preset["id"])
    # The supply keeps its own revision.
    assert backing.value["revision"] == 0 and backing.value["presets_revision"] == 2


# ------------------------------------------------------------------ review round 1
def test_a_write_to_the_same_entity_in_another_context_is_still_journaled(monkeypatch):
    from unittest.mock import AsyncMock

    from custom_components.crop_steering import setpoint_log

    shot = number("zone_1_p2_shot_size")
    hass = rig({"zone_1_p2_shot_size": 3.0})
    hass.auth = SimpleNamespace(
        async_get_user=AsyncMock(return_value=SimpleNamespace(system_generated=False))
    )
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    log = setpoint_log.SetpointLog(hass, entry, MemoryStore())
    hass.data[DOMAIN]["_setpoint_log"] = {"f2": log}
    journaled = []
    monkeypatch.setattr(
        setpoint_log,
        "note",
        lambda hass, room, kind, **kw: journaled.append(("log", kw["data"]["new"])),
    )
    monkeypatch.setattr(
        presets,
        "note",
        lambda hass, room, kind, **kw: journaled.append(("preset", kw["data"]["new"])),
    )

    async def call(domain, service, data, blocking=False, context=None):
        old, new = float(hass.states.get(shot).state), float(data["value"])
        hass.states.set(shot, str(new))
        await log.record(shot, "p2_shot_size", 1, old, new, context)
        # Meanwhile an automation moves the same number, in its own context.
        await log.record(shot, "p2_shot_size", 1, new, 7.0, core.Context())

    hass.services.async_call = call

    async def go():
        await log.async_init()
        write = {"entity_id": shot, "key": "p2_shot_size", "value": 5.0}
        return await presets.write_numbers(hass, "f2", [write], WHO)

    run(go())
    assert journaled == [("log", 7.0), ("preset", 5.0)]


def _timer_rig(monkeypatch, programs, set_programs=None):
    from custom_components.crop_steering import timers_api

    hass = rig({"zone_1_p2_shot_size": 3.0})
    hass.data[DOMAIN]["_timers"] = {"f2": SimpleNamespace(error=None)}
    monkeypatch.setattr(timers_api, "get_programs", lambda hass, entry_id: programs)
    monkeypatch.setattr(
        timers_api, "list_programs", lambda hass, room_id: {"revision": 3}
    )

    async def refuse(*args):
        raise AssertionError("set_programs must not be called")

    monkeypatch.setattr(timers_api, "set_programs", set_programs or refuse)
    return hass


AM = {
    "id": "A",
    "name": "AM",
    "type": "recycle",
    "zones": [1],
    "duration_s": 120,
    "active": True,
}


def test_a_source_zone_with_no_timer_program_never_pulls_the_target_from_its_own(
    monkeypatch,
):
    hass = _timer_rig(monkeypatch, [AM])
    wanted = {"timers": {"timer": None}}
    to = [{"room_id": ROOM, "zone": 1}]
    reason = "source zone has no timer program"
    preview = run(presets.apply(hass, wanted, to, True, WHO))
    assert preview["diff"] == []
    assert preview["missing"] == [{"target": to[0], "key": "timer", "reason": reason}]
    out = run(presets.apply(hass, wanted, to, False, WHO))
    assert out["applied"] == [
        {"target": to[0], "key": "timer", "readback": "refused", "error": reason}
    ]


def test_a_timer_write_that_fails_names_its_error_in_the_applied_row(monkeypatch):
    async def fail(hass, entry_id, programs, revision, actor):
        raise ValueError("Zone 1 is already in timer 'PM'")

    hass = _timer_rig(monkeypatch, [], fail)
    shape = {k: v for k, v in AM.items() if k not in ("id", "zones")}
    to = [{"room_id": ROOM, "zone": 1}]
    out = run(presets.apply(hass, {"timers": {"timer": shape}}, to, False, WHO))
    assert out["applied"] == [
        {
            "target": to[0],
            "key": "timer",
            "readback": "refused",
            "error": "Zone 1 is already in timer 'PM'",
        }
    ]


def test_a_stored_preset_without_its_source_is_refused_with_a_value_error():
    backing = MemoryStore(
        {"revision": 0, "presets_revision": 1, "presets": [{"id": "P", "name": "old"}]}
    )
    with pytest.raises(ValueError, match="no source"):
        run(site(backing).delete_preset({"id": "P", "expected_revision": 1}, WHO))


def test_a_source_setting_that_cannot_be_read_is_named_as_skipped():
    hass = rig({"zone_3_p2_shot_size": 5.0, "zone_3_p2_time_between_shots": 30.0})
    hass.states.set(number("zone_3_p2_time_between_shots"), "unavailable")
    captured, skipped = presets.read_source(
        hass, {"room_id": ROOM, "zone": 3}, presets.SCOPES["all"]
    )
    assert captured["targets"] == {"p2_shot_size": 5.0}
    assert captured["phase_timing"] == {}
    # The room's timer programs are not loaded here either.
    assert skipped == ["p2_time_between_shots", "timer"]
