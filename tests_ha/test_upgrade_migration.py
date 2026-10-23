"""THE UPGRADE TO 3.18, in a real Home Assistant, from seeded snapshots of old installs (migration.py).

entry_3_17_0_probe_less_room.json is a named room as 3.17.0 left it, recorded from that release: its config entry,
every entity id, its recipe, notify, dosing and display stores and its controller's state file. It has no feed EC
probe. entry_3_11_1_pumped_room.json is the default room 3.11.1 left, with a feed EC probe.

What must hold: every zone waters exactly as before, the settings that can be carried without a guess are
(presets from the recipe, a rollback preset, °F where Home Assistant uses it, the old feed EC assumption), the
rest is listed for the grower, the old stores are byte for byte what they were, and running it again changes
nothing.
"""

import json
from copy import deepcopy
from datetime import datetime

import pytest
from conftest import fixture, switch_calls
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import State
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_restore_cache

DOMAIN = "crop_steering"
V3_17 = "entry_3_17_0_probe_less_room.json"
V3_11 = "entry_3_11_1_pumped_room.json"
# Mid-afternoon on the day each old controller last saved its state: lights on (6-18 and 12-0), hours after the
# last shot, so a dry zone is due one.
AT = {"entry_3_11_1_pumped_room.json": datetime(2026, 10, 14, 15, 30),
      "entry_3_17_0_probe_less_room.json": datetime(2026, 10, 23, 15, 30)}


def _storage(seed, hass_storage):
    """The old install's Home Assistant stores, as it left them."""
    stores = {}
    for key, data in (seed.get("stores") or {}).items():
        key = key.replace("<entry_id>", seed["entry_id"])
        stores[key] = data
    if "stores" not in seed:  # 3.11.1: the dosing and notify stores recorded beside it
        stores[f"{DOMAIN}.dosing.{seed['entry_id']}"] = fixture("dosing_3_11_1.json")["dosing"]
        stores[f"{DOMAIN}.notify"] = fixture("notify_3_11_1.json")["store"]["data"]
    for key, data in stores.items():
        hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": deepcopy(data)}
    return stores


async def _upgrade(hass, hass_storage, name, monkeypatch=None, migrate=True):
    seed = fixture(name)
    stores = _storage(seed, hass_storage)
    for entity_id, (state, attributes) in seed["states"].items():
        hass.states.async_set(entity_id, state, attributes)
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=seed["version"],
        minor_version=seed["minor_version"],
        entry_id=seed["entry_id"],
        unique_id=seed["unique_id"],
        title=seed["title"],
        data=seed["data"],
        options=seed["options"],
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    for entity_id, key in seed["registry"].items():
        platform, object_id = entity_id.split(".", 1)
        registry.async_get_or_create(
            platform, DOMAIN, f"{DOMAIN}_{seed['entry_id']}_{key}",
            suggested_object_id=object_id, config_entry=entry,
        )
    mock_restore_cache(
        hass,
        [State(e, *(v if isinstance(v, list) else [v])) for e, v in seed["operator_tuned_numbers"].items()],
    )
    if not migrate:
        from custom_components.crop_steering import migration

        async def nothing(*_a, **_k):
            return None

        monkeypatch.setattr(migration, "async_migrate_room", nothing)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry, seed, stores


async def _report(hass, room_id):
    return await hass.services.async_call(
        DOMAIN, "migration_report", {"room_id": room_id}, blocking=True, return_response=True
    )


async def _migration_changes(hass, room_id):
    await hass.async_block_till_done()
    found = await hass.services.async_call(
        DOMAIN, "journal_query",
        {"room_id": room_id, "since": "2000-01-01T00:00:00+00:00", "kinds": ["config.changed"]},
        blocking=True, return_response=True,
    )
    return [
        e for e in found["events"] if (e["source"].get("detail") or "").startswith("migration:")
    ]


def _ids(rows):
    return {r["id"] for r in rows}


def _presets(hass):
    return [p for p in hass.data[DOMAIN]["_site"].document["presets"] if not p.get("deleted_at")]


# ------------------------------------------------------------------ the report
async def test_a_3_17_0_room_gets_an_upgrade_report_with_what_came_across_and_what_needs_you(
    hass, hass_storage
):
    entry, _seed, _stores = await _upgrade(hass, hass_storage, V3_17)
    report = await _report(hass, "room:flower_room_")
    assert report["release"] == "3.18.0" and report["acknowledged"] is None
    assert _ids(report["carried"]) >= {
        "irrigation.mode", "presets.recipe", "presets.snapshot", "notify.recipients", "dosing.ph_pumps",
    }
    assert _ids(report["needs_you"]) >= {
        "supply.pumps", "alerts.rules", "units.ec", "notify.quiet_hours", "calibration.feed_ph",
        "dosing.pump.part_a", "feed.ec_fallback", "panels.new",
    }
    for row in report["carried"] + report["needs_you"]:
        assert row["page"].startswith("#/") and row["doc"].startswith("docs/UPGRADING.md#"), row
    supply = next(r for r in report["needs_you"] if r["id"] == "supply.pumps")
    assert "switch.irrigation_pump" in supply["detail"] and "switch.irrigation_main_line" in supply["detail"]
    mode = next(r for r in report["carried"] if r["id"] == "irrigation.mode")
    assert mode["detail"] == "Every zone waters by Steering, as before (2 zones)."
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "upgrade_report_3_18_flower_room")
    assert issue is not None and issue.is_fixable and issue.translation_key == "upgrade_report_3_18"
    assert issue.translation_placeholders["needs_you"] == str(len(report["needs_you"]))


async def test_a_fresh_install_has_no_upgrade_report(hass):
    from test_setup_entry import _install

    await _install(hass)
    report = await _report(hass, "room:tent_")
    assert report["carried"] == [] and report["needs_you"] == []
    assert not [i for i in ir.async_get(hass).issues.values() if i.translation_key == "upgrade_report_3_18"]
    steps = hass.data[DOMAIN]["_migration"].document["rooms"]
    assert {s["result"] for room in steps.values() for s in room["steps"].values()} == {"fresh"}


async def test_marking_the_report_read_closes_the_card_for_good(hass, hass_storage):
    from homeassistant.components.repairs import repairs_flow_manager
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "repairs", {})
    entry, _seed, _stores = await _upgrade(hass, hass_storage, V3_17)
    issue_id = "upgrade_report_3_18_flower_room"
    flows = repairs_flow_manager(hass)
    flow = await flows.async_init(DOMAIN, data={"issue_id": issue_id})
    assert flow["step_id"] == "confirm"
    await flows.async_configure(flow["flow_id"], {})
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    assert (await _report(hass, "room:flower_room_"))["acknowledged"] is not None
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


# ------------------------------------------------------------------ H1: water as before
async def _pass(hass, controller_for, seed, saved_state, options, at):
    for switch in ("engine_enabled", "system_enabled", "auto_irrigation_enabled", "zone_1_enabled",
                   "zone_2_enabled"):
        prefix = "" if seed["data"].get("room_prefix") == "" else "flower_room_"
        hass.states.async_set(f"switch.crop_steering_{prefix}{switch}", "on")
    for zone in (1, 2):  # dry: every zone is due a shot (the controller reads the fused zone sensor)
        fused = hass.states.get(f"sensor.crop_steering_{prefix}vwc_zone_{zone}")
        hass.states.async_set(fused.entity_id, "30", fused.attributes)
    c, fake, _clock = controller_for(options, saved_state=deepcopy(saved_state))
    fake.calls.clear()
    c.loop_once(at)
    rooms = {
        room.slug: {z: (st["phase"], st["shots"], round(st["daily_vol"], 6)) for z, st in room.state.items()}
        for room in c.rooms
    }
    return switch_calls(fake), rooms


@pytest.mark.parametrize("name", [V3_11, V3_17])
async def test_upgrade_waters_as_before(hass, hass_storage, controller_for, monkeypatch, name):
    """One controller pass on the old install before the migration, and the same pass after it: the same
    switches in the same order, and every zone in the same phase with the same shots and water."""
    from custom_components.crop_steering import migration

    real = migration.async_migrate_room
    entry, seed, _stores = await _upgrade(hass, hass_storage, name, monkeypatch, migrate=False)
    if name == V3_11:
        saved = fixture("state_3_11_1_learn_jev.json")["state"]
        options = {"enable_flag": "switch.crop_steering_engine_enabled"}
    else:
        saved, options = seed["controller_saved"], seed["addon_options"]
    before = await _pass(hass, controller_for, seed, saved, options, AT[name])
    await real(hass, entry, False)
    await hass.async_block_till_done()
    assert (await _report(hass, "room:" + seed["data"].get("room_prefix", "flower_room_")))["carried"]
    after = await _pass(hass, controller_for, seed, saved, options, AT[name])
    assert after == before
    calls, _rooms = before
    assert ("turn_on", "switch.zone_1_valve") in calls and ("turn_on", "switch.zone_2_valve") in calls


async def test_a_probe_less_room_keeps_the_3_0_feed_ec_3_17_0_assumed(hass, hass_storage, controller_for):
    """3.17.0 handed decide() 3.0 mS/cm for a room with no feed EC probe and no recipe EC; 3.18 hands it None
    unless the upgrade kept the old value. It does, and the grower is told (CS-907, Needs you)."""
    entry, seed, _stores = await _upgrade(hass, hass_storage, V3_17)
    descriptor = hass.states.get("sensor.crop_steering_flower_room_engine_config").attributes
    assert descriptor["legacy_feed_ec_fallback"] == 3.0
    c, _fake, _clock = controller_for(seed["addon_options"], saved_state=deepcopy(seed["controller_saved"]))
    room = next(r for r in c.rooms if r.prefix == "flower_room_")
    assert room._setup_pending is None  # no disarm cycle for the new key
    assert room.legacy_feed_ec == 3.0
    snap, _params = c._snapshot(room, 1, AT[V3_17], True, False)
    assert snap.feed_ec == 3.0


async def test_the_kept_feed_ec_survives_every_later_start(hass, hass_storage, controller_for):
    """The descriptor reads the kept value from the ledger, which loads after the sensor first writes: every
    later start (the steps already done) republishes it, or a probe-less room loses its EC flushes."""
    entry, seed, _stores = await _upgrade(hass, hass_storage, V3_17)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    descriptor = hass.states.get("sensor.crop_steering_flower_room_engine_config").attributes
    assert descriptor["legacy_feed_ec_fallback"] == 3.0
    c, _fake, _clock = controller_for(seed["addon_options"], saved_state=deepcopy(seed["controller_saved"]))
    room = next(r for r in c.rooms if r.prefix == "flower_room_")
    snap, _params = c._snapshot(room, 1, AT[V3_17], True, False)
    assert snap.feed_ec == 3.0


async def test_a_ledger_that_failed_to_load_republishes_the_kept_feed_ec_once_it_loads(hass, hass_storage):
    from custom_components.crop_steering import migration
    from homeassistant.helpers.dispatcher import async_dispatcher_send

    entry, _seed, _stores = await _upgrade(hass, hass_storage, V3_17)
    ledger = hass.data[DOMAIN]["_migration"]
    ledger.document, ledger.error = migration.empty(), "disk error"  # this start's load failed
    async_dispatcher_send(hass, f"{migration.SIGNAL}_{entry.entry_id}")
    await hass.async_block_till_done()
    sensor = "sensor.crop_steering_flower_room_engine_config"
    assert "legacy_feed_ec_fallback" not in hass.states.get(sensor).attributes
    await migration.async_migrate_room(hass, entry, False)  # the room's next setup loads it again
    await hass.async_block_till_done()
    assert ledger.error is None
    assert hass.states.get(sensor).attributes["legacy_feed_ec_fallback"] == 3.0


async def test_a_room_with_a_feed_ec_probe_gets_no_kept_value(hass, hass_storage):
    await _upgrade(hass, hass_storage, V3_11)
    assert "legacy_feed_ec_fallback" not in hass.states.get("sensor.crop_steering_engine_config").attributes
    report = await _report(hass, "room:")
    assert "feed.ec_fallback" not in _ids(report["needs_you"])
    assert {"calibration.feed_ph", "calibration.feed_ec"} <= _ids(report["needs_you"])


# ------------------------------------------------------------------ H2: nothing that waters is turned on
async def test_no_supply_timer_alert_rule_or_calibration_is_turned_on(hass, hass_storage):
    entry, _seed, _stores = await _upgrade(hass, hass_storage, V3_17)
    site = hass.data[DOMAIN]["_site"].document
    assert site["revision"] == 0 and site["irrigation_pumps"] == [] and site["zone_meters"] == {}
    assert site["alert_rules"] == [] and site["water_sources"] == [] and site["zone_groups"] == {}
    assert hass.states.get("sensor.crop_steering_supply_config") is None
    from custom_components.crop_steering import timers_api

    assert timers_api.get_programs(hass, entry.entry_id) == []
    assert "feed_calibration" not in hass.states.get("sensor.crop_steering_flower_room_engine_config").attributes
    for zone in (1, 2):
        mode = hass.states.get(f"select.crop_steering_flower_room_zone_{zone}_irrigation_mode")
        assert mode.state == "steering"


# ------------------------------------------------------------------ what came across
async def test_the_edited_recipe_stage_becomes_one_preset_and_the_recipe_is_untouched(hass, hass_storage):
    from custom_components.crop_steering import presets

    _entry, seed, stores = await _upgrade(hass, hass_storage, V3_17)
    recipe_key = f"{DOMAIN}_recipes_{seed['entry_id']}"
    made = [p for p in _presets(hass) if p["by"].get("detail") == "migration:recipe_presets"]
    assert [p["name"] for p in made] == ["Flower room – Bulk (from 3.17 recipe)"]
    bulk = stores[recipe_key]["stages"]["Bulk"]
    assert made[0]["values"] == {
        s: v for s, v in presets.capture(bulk, ("targets", "phase_timing", "water_limits")).items() if v
    }
    assert made[0]["from"] == {"room_id": "room:flower_room_"} and made[0]["scope"] == "all"
    assert hass_storage[recipe_key]["data"] == stores[recipe_key]  # copied, never moved
    changes = await _migration_changes(hass, "room:flower_room_")
    assert [e["source"]["detail"] for e in changes].count("migration:recipe_presets") == 1
    assert {e["source"]["actor"] for e in changes} == {"system"}


async def test_every_recipe_key_has_a_preset_section():
    from custom_components.crop_steering import presets
    from custom_components.crop_steering.const import DEFAULT_RECIPE

    known = {k for s in ("targets", "phase_timing", "water_limits") for k in presets.SECTIONS[s]}
    for stage, values in DEFAULT_RECIPE["stages"].items():
        assert set(values) <= known, stage


async def test_a_rollback_preset_holds_the_room_settings_as_restored(hass, hass_storage):
    _entry, seed, _stores = await _upgrade(hass, hass_storage, V3_17)
    (snapshot,) = [p for p in _presets(hass) if p["by"].get("detail") == "migration:snapshot_preset"]
    assert snapshot["name"] == "Flower room – before 3.18 update"
    targets = snapshot["values"]["targets"]
    assert targets["p2_shot_size"] == 4.5 and targets["maximum_ec"] == 8.0  # what the operator set on 3.17.0
    assert snapshot["values"]["timers"] == {"timers": []}


async def test_display_units_follow_home_assistant_in_fahrenheit_only(hass, hass_storage):
    _entry, seed, stores = await _upgrade(hass, hass_storage, V3_17)
    key = f"{DOMAIN}.display.{seed['entry_id']}"
    assert hass_storage[key]["data"] == stores[key]  # metric: nothing saved
    assert "migration:display_units" not in {
        e["source"]["detail"] for e in await _migration_changes(hass, "room:flower_room_")
    }


async def test_a_fahrenheit_home_assistant_shows_the_room_in_fahrenheit(hass, hass_storage):
    from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

    hass.config.units = US_CUSTOMARY_SYSTEM
    _entry, seed, stores = await _upgrade(hass, hass_storage, V3_17)
    display = hass.data[DOMAIN]["_display"][seed["entry_id"]].document
    assert display["options"] == {"show_camera": True, "temp_unit": "F"}
    assert display["revision"] == stores[f"{DOMAIN}.display.{seed['entry_id']}"]["revision"] + 1
    report = await _report(hass, "room:flower_room_")
    assert "units.temperature" in _ids(report["carried"]) and "units.clock" in _ids(report["needs_you"])


@pytest.mark.parametrize("name", [V3_11, V3_17])
async def test_old_stores_are_byte_for_byte_what_they_were(hass, hass_storage, name):
    """H4: recipe, notify, dosing and calibration stores are read, never written."""
    _entry, seed, stores = await _upgrade(hass, hass_storage, name)
    for key, data in stores.items():
        if ".display." in key or key.endswith("whats_new"):
            continue  # the display store takes °F only in a °F Home Assistant; What's new is its own
        assert json.dumps(hass_storage[key]["data"], sort_keys=True) == json.dumps(data, sort_keys=True), key
    assert "quiet_hours" not in hass_storage[f"{DOMAIN}.notify"]["data"]


# ------------------------------------------------------------------ H3: once, and safe to run again
async def test_running_it_again_changes_nothing(hass, hass_storage):
    from custom_components.crop_steering import migration

    entry, _seed, _stores = await _upgrade(hass, hass_storage, V3_17)
    before = deepcopy(hass.data[DOMAIN]["_site"].document)
    display = deepcopy(hass.data[DOMAIN]["_display"][entry.entry_id].document)
    changes = len(await _migration_changes(hass, "room:flower_room_"))
    ledger = hass.data[DOMAIN]["_migration"]
    ledger.document["rooms"][entry.entry_id]["steps"] = {}  # every step runs again
    await migration.async_migrate_room(hass, entry, False)
    await hass.async_block_till_done()
    ledger.document = migration.empty()  # and with the ledger lost altogether
    await migration.async_migrate_room(hass, entry, False)
    await hass.async_block_till_done()
    assert hass.data[DOMAIN]["_site"].document["presets"] == before["presets"]
    assert hass.data[DOMAIN]["_display"][entry.entry_id].document == display
    after = await _migration_changes(hass, "room:flower_room_")
    # Only the kept feed EC, which lived in the lost ledger, is written (and journaled) again.
    assert [e["source"]["detail"] for e in after[changes:]] == ["migration:feed_ec_fallback"]


async def test_history_noted_while_the_ledger_loads_keeps_what_the_ledger_held(hass, hass_storage, monkeypatch):
    """The journal backfill runs beside the room's setup: noting history before the ledger has loaded must
    not save an empty ledger over the stored one (Mark as read, the kept feed EC)."""
    import asyncio

    from custom_components.crop_steering import migration

    entry, _seed, _stores = await _upgrade(hass, hass_storage, V3_17)
    await migration.acknowledge(hass, entry.entry_id)
    room = hass.data[DOMAIN]["_migration"].document["rooms"][entry.entry_id]
    room["report"]["carried"] = [r for r in room["report"]["carried"] if r["id"] != "history.import"]
    await hass.data[DOMAIN]["_migration"].save()
    hass.data[DOMAIN].pop("_migration")  # the next start
    hass.services.async_remove(DOMAIN, "migration_report")
    real, gate = migration.Ledger.async_init, asyncio.Event()

    async def slow(self):
        await gate.wait()
        await real(self)

    monkeypatch.setattr(migration.Ledger, "async_init", slow)
    setup = hass.async_create_task(migration.async_setup_migration(hass))
    await asyncio.sleep(0)
    noted = hass.async_create_task(migration.note_history(hass, entry, 5))
    await asyncio.sleep(0)
    gate.set()
    await setup
    await noted
    stored = hass_storage[migration.STORAGE_KEY]["data"]
    assert entry.entry_id in stored["acknowledged"]
    assert stored["rooms"][entry.entry_id]["legacy_feed_ec_fallback"] == 3.0
    assert "history.import" in _ids(stored["rooms"][entry.entry_id]["report"]["carried"])


async def test_a_step_that_failed_runs_again_at_the_next_start(hass, hass_storage, monkeypatch):
    from custom_components.crop_steering import migration

    calls = []

    async def broken(hass_, entry_, room):
        calls.append(1)
        raise RuntimeError("boom")

    steps = tuple((n, broken if n == "alerts:v1" else s) for n, s in migration.SETUP_STEPS)
    monkeypatch.setattr(migration, "SETUP_STEPS", steps)
    entry, _seed, _stores = await _upgrade(hass, hass_storage, V3_17)
    room = hass.data[DOMAIN]["_migration"].document["rooms"][entry.entry_id]
    assert room["steps"]["alerts:v1"]["result"] == "error" and entry.state is ConfigEntryState.LOADED
    assert room["steps"]["recipe_presets:v1"]["result"] == "done"
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(calls) == 2  # tried again; the steps that were done are not
    assert len([p for p in _presets(hass) if p["by"].get("detail") == "migration:recipe_presets"]) == 1
