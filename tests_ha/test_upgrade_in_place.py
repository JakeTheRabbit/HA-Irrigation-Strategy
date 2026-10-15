"""IN-PLACE UPGRADE, in a real Home Assistant, from SEEDED snapshots of old installs.

"Never break a live install." Each file in tests_ha/fixtures/ is a room as an OLD version
actually left it: its config entry, operator-tuned values in the restore cache, and (for the
controller tests) the state file and setup fingerprint its controller had saved. The new code is
started on top of it the way a HACS update + Supervisor update does - no wizard, no reconfigure.

What must hold: nothing the operator set moves, no entity changes id, and the controller carries
straight on. To cover another kind of old install, add a snapshot rather than hand-building one.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path

import pytest
from conftest import fixture, switch_calls
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import State
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
)

DOMAIN = "crop_steering"
KILL = "switch.crop_steering_engine_enabled"
DESCRIPTOR = "sensor.crop_steering_engine_config"


async def _upgrade(hass, name, *, registry_ids=None):
    """Start the new code on top of a seeded old install."""
    seed = fixture(name)
    for entity_id, (state, attributes) in seed["states"].items():
        hass.states.async_set(entity_id, state, attributes)
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=seed.get("version", 1),
        minor_version=seed.get("minor_version", 1),
        entry_id=seed["entry_id"],
        unique_id=seed["unique_id"],
        title=seed["title"],
        data=seed["data"],
        options=seed["options"],
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    # The old install's registry: these entities are already known under their old ids.
    for entity_id, unique_key in (registry_ids or {}).items():
        platform, object_id = entity_id.split(".", 1)
        registry.async_get_or_create(
            platform,
            DOMAIN,
            f"{DOMAIN}_{seed['entry_id']}_{unique_key}",
            suggested_object_id=object_id,
            config_entry=entry,
        )
    # A value is "30", or ["30", {attributes}] where the old version stored attributes with it:
    # 2.17 records the setup revision a zone-sizing number last adopted, which is how it tells
    # "the operator tuned this" from "setup was just changed" (sizing.prefer_setup_value).
    mock_restore_cache(
        hass,
        [
            State(eid, *(saved if isinstance(saved, list) else [saved]))
            for eid, saved in seed["operator_tuned_numbers"].items()
        ],
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry, seed


def _known_numbers(seed):
    return {
        eid: eid.split("crop_steering_", 1)[1] for eid in seed["operator_tuned_numbers"]
    }


# ------------------------------------------------------------------ a 2.17 wizard install
async def test_everything_the_operator_tuned_survives_the_upgrade(hass):
    seed = fixture("entry_2_17_wizard.json")
    await _upgrade(hass, "entry_2_17_wizard.json", registry_ids=_known_numbers(seed))
    for entity_id, saved in seed["operator_tuned_numbers"].items():
        tuned = saved[0] if isinstance(saved, list) else saved
        assert float(hass.states.get(entity_id).state) == float(tuned), entity_id


async def test_the_upgrade_removes_the_entities_nothing_uses_and_keeps_the_rest(hass):
    """An old install still holds entities that nothing read or set: the trigger button, the
    retired intelligence switches, a zone's group and so on. Setup removes those from the
    registry, and only those: the global P2 EC threshold stays although its per-zone copy goes."""
    seed = fixture("entry_2_17_wizard.json")
    retired = {
        "button.crop_steering_zone_1_trigger_shot": "zone_1_trigger_shot",
        "number.crop_steering_steering_intent": "steering_intent",
        "number.crop_steering_zone_2_shot_size_multiplier": "zone_2_shot_size_multiplier",
        "number.crop_steering_zone_1_p2_ec_high_threshold": "zone_1_p2_ec_high_threshold",
        "select.crop_steering_crop_type": "crop_type",
        "select.crop_steering_zone_2_phase_override": "zone_2_phase_override",
        "sensor.crop_steering_next_irrigation_time": "next_irrigation_time",
        "switch.crop_steering_intelligence_llm_report_enabled": "intelligence_llm_report_enabled",
        "switch.crop_steering_zone_1_dripper_protection": "zone_1_dripper_protection",
    }
    kept = {
        **_known_numbers(seed),
        "number.crop_steering_p2_ec_high_threshold": "p2_ec_high_threshold",
    }
    entry, _seed = await _upgrade(
        hass, "entry_2_17_wizard.json", registry_ids={**retired, **kept}
    )
    registry = er.async_get(hass)
    assert [e for e in retired if registry.async_get(e)] == []
    assert [e for e in kept if registry.async_get(e) is None] == []
    for entity_id, saved in seed["operator_tuned_numbers"].items():
        tuned = saved[0] if isinstance(saved, list) else saved
        assert float(hass.states.get(entity_id).state) == float(tuned), entity_id
    # No platform creates a retired entity again: a second pass finds nothing to remove.
    from custom_components.crop_steering import _remove_retired_entities

    count = len(er.async_entries_for_config_entry(registry, entry.entry_id))
    _remove_retired_entities(hass, entry)
    assert len(er.async_entries_for_config_entry(registry, entry.entry_id)) == count


async def test_lights_hours_set_by_the_operator_beat_the_ones_recorded_at_setup(hass):
    """2.18.1 starts SEEDING the lights hours from the wizard's answers. On this room the wizard
    said 10-22 and the operator later set 8-20 on a dashboard. A seed must only ever apply to an
    entity being created for the first time, or this fix would move a live room's photoperiod."""
    seed = fixture("entry_2_17_wizard.json")
    assert seed["data"]["parameters"]["lights_on_hour"] == 10
    await _upgrade(hass, "entry_2_17_wizard.json", registry_ids=_known_numbers(seed))
    assert float(hass.states.get("number.crop_steering_lights_on_hour").state) == 8
    assert float(hass.states.get("number.crop_steering_lights_off_hour").state) == 20


async def test_an_entity_the_operator_renamed_keeps_its_name_and_is_not_duplicated(hass):
    entry, _seed = await _upgrade(
        hass,
        "entry_2_17_wizard.json",
        registry_ids={
            "sensor.flower_row_1_moisture": "vwc_zone_1",
            "number.my_pot_size": "substrate_volume",
        },
    )
    assert float(hass.states.get("sensor.flower_row_1_moisture").state) == 54.0  # (52+56)/2
    assert hass.states.get("sensor.crop_steering_vwc_zone_1") is None
    assert hass.states.get("number.my_pot_size") is not None
    assert hass.states.get("number.crop_steering_substrate_volume") is None
    registry = er.async_get(hass)
    ids = [
        e.entity_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    ]
    assert len(ids) == len(set(ids))


async def test_loading_an_old_room_rewrites_nothing_and_publishes_what_it_always_did(hass):
    entry, seed = await _upgrade(hass, "entry_2_17_wizard.json")
    assert entry.data == seed["data"]  # the stored entry is untouched by simply loading
    descriptor = hass.states.get(DESCRIPTOR).attributes
    assert (descriptor["pump"], descriptor["mainline"]) == (
        "switch.main_pump",
        "switch.main_line",
    )
    assert descriptor["setup_revision"] == 4
    # mS/cm probes read exactly as they did.
    assert float(hass.states.get("sensor.crop_steering_ec_zone_1").state) == 3.4


async def test_the_controller_carries_straight_on_after_the_upgrade_without_a_disarm_cycle(
    hass, controller_for
):
    """The 2026-09-20 incident, across a version change: the kill switch is ON, the room is mid
    grow, and both layers are updated. The new controller must recognise the setup the old one
    adopted. If the descriptor or its fingerprint shifted by one key, every zone would sit
    blocked behind 'Setup changed; disarm...' until someone noticed the plants wilting."""
    await _upgrade(hass, "entry_2_17_wizard.json")
    # Exactly what controller 0.14.0 saved for this room (its _setup_fingerprint, verbatim).
    saved_by_0_14 = json.dumps(
        {
            "active": True,
            "zones": [1, 2],
            "pump": "switch.main_pump",
            "mainline": "switch.main_line",
            "valves": {"1": "switch.row_1_valve", "2": "switch.row_2_valve"},
            "enable_flag": KILL,
            "feed_ec_sensor": "sensor.feed_ec",
            "feed_ph_sensor": "sensor.feed_ph",
        },
        sort_keys=True,
    )
    old_state = {
        "default": {
            "1": {"phase": "P2", "peak": 61.0, "shots": 7, "daily_vol": 9.5},
            "2": {"phase": "P1", "peak": 58.0, "shots": 3, "daily_vol": 4.0},
            "_setup": {"revision": 4, "fingerprint": saved_by_0_14},
        }
    }
    hass.states.async_set(KILL, "on")  # armed and growing: nobody is going to disarm it

    c, fake, _clock = controller_for({"enable_flag": KILL}, saved_state=old_state)
    room = c.rooms[0]

    assert room._setup_pending is None, room._setup_pending
    assert room.setup_revision == 4
    assert room.state[1]["shots"] == 7 and room.state[1]["daily_vol"] == 9.5
    assert room.state[2]["phase"] == "P1"
    assert "Setup" not in (c._blocked(room, 1) or "")
    # ...and it still drives the room the way it always did: pump, mainline, valve.
    for switch in (
        "switch.crop_steering_system_enabled",
        "switch.crop_steering_auto_irrigation_enabled",
        "switch.crop_steering_zone_1_enabled",
    ):
        fake.set_state(switch, "on")
    fake.calls.clear()
    c._execute_shot(room, 1, 10, 5, flow_lps=0.05)
    assert switch_calls(fake) == [
        ("turn_on", "switch.main_pump"),
        ("turn_on", "switch.main_line"),
        ("turn_on", "switch.row_1_valve"),
        ("turn_off", "switch.row_1_valve"),
        ("turn_off", "switch.main_line"),
        ("turn_off", "switch.main_pump"),
    ]


async def test_a_3_8_0_state_file_loads_with_its_history_empty_and_nothing_moves(
    hass, controller_for
):
    """3.8.0 kept no plateau or night history (tests_ha/fixtures/state_3_8_0_mid_grow.json).
    The new controller loads that file exactly as it was, starts the history empty, and writing
    it back changes nothing else but four new zone keys (the day before's peak and the P1 rule's
    state), all saved empty."""
    await _upgrade(hass, "entry_2_17_wizard.json")
    seed = fixture("state_3_8_0_mid_grow.json")["state"]
    hass.states.async_set(KILL, "on")

    c, _fake, _clock = controller_for({"enable_flag": KILL}, saved_state=seed)
    room = c.rooms[0]

    assert room._setup_pending is None, room._setup_pending
    for zone in (1, 2):
        st, old = room.state[zone], seed["default"][str(zone)]
        assert (st["phase"], st["peak"], st["shots"], st["daily_vol"]) == (
            old["phase"],
            old["peak"],
            old["shots"],
            old["daily_vol"],
        )
        assert st["learn"]["night_rate"] == old["learn"]["night_rate"]
        assert (st["plateau_hist"], st["night_hist"], st["night"]) == ([], [], None)
    assert c._save_state()
    saved = json.loads(Path(os.environ["F2_STATE_PATH"]).read_text(encoding="utf-8"))
    for zone in ("1", "2"):
        written = dict(saved["default"][zone])
        kept = (written.pop("plateau_hist"), written.pop("night_hist"), written.pop("night"))
        assert kept == ([], [], None)
        learn = dict(written.pop("learn"))
        new = (written.pop("peak_prev"), written.pop("p1_reached"), written.pop("p1_peak_before"), written.pop("p1_extra"))
        assert new == (None, False, None, 0)  # the day before's peak and the P1 rule's state, saved empty
        old = dict(seed["default"][zone])
        assert learn == old.pop("learn")
        assert written == old


async def test_3_8_0_app_options_keep_their_jev_budget_and_take_the_new_defaults(
    hass, controller_for, monkeypatch
):
    """F2's 3.8.0 options (tests_ha/fixtures/options_3_8_0_f2.json) start Jev on the TypeSafe
    route with the owner's 2000 calls, and every new setting at its default."""
    import functools

    import jev_bridge
    from jev.client import Asker

    # No asker worker thread: Home Assistant's test harness fails a test that leaves one running.
    monkeypatch.setattr(jev_bridge, "Asker", functools.partial(Asker, threaded=False))
    await _upgrade(hass, "entry_2_17_wizard.json")
    options = fixture("options_3_8_0_f2.json")["options"]
    c, _fake, _clock = controller_for(options)
    assert c.jev is not None and c.jev.routes == ["TypeSafe"]
    assert c.jev.asker.daily_budget == 2000  # the owner's value stays until the owner changes it
    settings = (c.jev.reask_max, c.jev.unsure_below, c.jev.strict_after, c.jev.strict_prob)
    assert settings == (2, 0.7, 3, 0.8)
    assert (c.jev.asker.warn_pct, c.jev.asker.transport.tries) == (80, 3)


# ------------------------------------------------------------------ an upstream 2.25.1 install
UPSTREAM_2_25_1 = "entry_2_25_1_pumped_room.json"


async def test_a_2_25_1_room_keeps_every_entity_id_and_everything_the_operator_tuned(hass):
    """The last HA-Irrigation-Strategy release before Jev became upstream
    (tests_ha/fixtures/entry_2_25_1_pumped_room.json, recorded from 2.25.1's own wizard). Every
    entity 2.25.1 registered keeps its id and has a state, except those this code retires on
    purpose; the entry is loaded as it is, never rewritten."""
    from custom_components.crop_steering import _RETIRED

    seed = fixture(UPSTREAM_2_25_1)
    entry, _seed = await _upgrade(hass, UPSTREAM_2_25_1, registry_ids=seed["registry"])
    assert (entry.version, entry.minor_version) == (seed["version"], seed["minor_version"])
    assert entry.data == seed["data"] and entry.options == seed["options"]

    registry = er.async_get(hass)
    kept = [
        entity_id
        for entity_id, key in seed["registry"].items()
        if re.sub(r"^zone_\d+_", "zone_", key) not in _RETIRED.get(entity_id.split(".")[0], ())
    ]
    assert len(kept) > 100
    assert [e for e in kept if registry.async_get(e) is None] == []
    assert [e for e in kept if hass.states.get(e) is None] == []

    for entity_id, saved in seed["operator_tuned_numbers"].items():
        tuned = saved[0] if isinstance(saved, list) else saved
        state = hass.states.get(entity_id).state
        if entity_id.startswith("number."):
            assert float(state) == float(tuned), entity_id
        else:
            assert state == tuned, entity_id
    assert float(hass.states.get("number.crop_steering_lights_on_hour").state) == 6
    assert float(hass.states.get("number.crop_steering_lights_off_hour").state) == 18

    descriptor = hass.states.get(DESCRIPTOR).attributes
    assert (descriptor["pump"], descriptor["mainline"], descriptor["plumbing"]) == (
        "switch.irrigation_pump",
        "switch.irrigation_main_line",
        "pump_mainline_valves",
    )
    assert descriptor["setup_revision"] == 1


async def test_the_controller_carries_a_2_25_1_room_straight_on_with_its_options_and_state(
    hass, controller_for
):
    """Both layers updated on an armed 2.25.1 box: the app keeps the /data/options.json and
    /data/state.json 2.25.1 left. The new controller resumes the adopted setup with no disarm
    cycle, takes every new option at its default (no Jev without a key), keeps every counter, and
    writing the state back keeps every value 2.25.1 wrote."""
    seed = fixture(UPSTREAM_2_25_1)
    await _upgrade(hass, UPSTREAM_2_25_1, registry_ids=seed["registry"])
    hass.states.async_set(KILL, "on")  # armed and growing: nobody is going to disarm it
    old = seed["controller_saved"]["default"]

    c, fake, _clock = controller_for(seed["addon_options"], saved_state=seed["controller_saved"])
    room = c.rooms[0]

    assert room._setup_pending is None, room._setup_pending
    assert room.setup_revision == 1
    assert "Setup" not in (c._blocked(room, 1) or "")
    assert c.jev is None  # 2.25.1 options carry no Jev route: the controller stays deterministic
    c._refresh_lights(room)
    assert (room.lights_on_hour, room.lights_off_hour) == (6.0, 18.0)
    for zone in (1, 2):
        st, was = room.state[zone], old[str(zone)]
        assert (st["phase"], st["peak"], st["shots"], st["daily_vol"]) == (
            was["phase"],
            was["peak"],
            was["shots"],
            was["daily_vol"],
        )

    assert c._save_state()
    saved = json.loads(Path(os.environ["F2_STATE_PATH"]).read_text(encoding="utf-8"))["default"]
    assert saved["_setup"] == old["_setup"]
    for zone in ("1", "2"):
        written, was = saved[zone], old[zone]
        assert {k: written[k] for k in was if k != "learn"} == {
            k: v for k, v in was.items() if k != "learn"
        }
        assert {k: written["learn"][k] for k in was["learn"]} == was["learn"]

    # ...and it still drives the room the way 2.25.1 did: pump, main line, valve.
    for switch in (
        "switch.crop_steering_system_enabled",
        "switch.crop_steering_auto_irrigation_enabled",
        "switch.crop_steering_zone_1_enabled",
    ):
        fake.set_state(switch, "on")
    fake.calls.clear()
    c._execute_shot(room, 1, 10, 5, flow_lps=0.05)
    assert switch_calls(fake) == [
        ("turn_on", "switch.irrigation_pump"),
        ("turn_on", "switch.irrigation_main_line"),
        ("turn_on", "switch.zone_1_valve"),
        ("turn_off", "switch.zone_1_valve"),
        ("turn_off", "switch.irrigation_main_line"),
        ("turn_off", "switch.irrigation_pump"),
    ]


async def test_a_2_25_1_room_with_its_engine_switch_off_stays_dry_after_the_upgrade(
    hass, controller_for
):
    """The 2.25.1 app option still names the old helper, but the adopted setup names the engine
    switch. With the engine switch OFF and the old helper ON, the upgraded controller follows the
    engine switch: no water."""
    seed = fixture(UPSTREAM_2_25_1)
    await _upgrade(hass, UPSTREAM_2_25_1, registry_ids=seed["registry"])
    hass.states.async_set(KILL, "off")
    hass.states.async_set(seed["addon_options"]["enable_flag"], "on")

    c, _fake, _clock = controller_for(seed["addon_options"], saved_state=seed["controller_saved"])
    room = c.rooms[0]

    assert room.enable_flag == KILL
    assert c._blocked(room, 1) == "f2-control disabled (kill switch off)"


# ------------------------------------------------------------------ Jev starts only where it has run
def _seeded_app(controller_for, monkeypatch, name, saved_state=None):
    """Start the real controller on an old app as it was left: its options file
    (tests_ha/fixtures/<name>) and the /data folder it names, copied in beside state.json.
    Jev's routes are stubbed: `built` records every route list the brain was given."""
    import functools
    import shutil

    import jev_bridge
    import jev_kit
    from jev.client import Asker

    seed = fixture(name)
    data = Path(os.environ["F2_STATE_PATH"]).parent
    if seed["data"]:
        for path in (Path(__file__).parent / "fixtures" / seed["data"]).iterdir():
            shutil.copy(path, data / path.name)
    built, stub = [], jev_kit.FakeTransport({})
    monkeypatch.setattr(jev_bridge, "Routes", lambda found, **kw: built.append(found) or stub)
    monkeypatch.setattr(jev_bridge, "Asker", functools.partial(Asker, threaded=False))
    c, _fake, _clock = controller_for(seed["options"], saved_state=saved_state)
    return c, seed, built, stub, data


@pytest.mark.parametrize(
    "options", ["options_2_25_1_cf_policy.json", "options_2_25_1_cf_policy_merged.json"]
)
async def test_a_2_25_1_room_with_cloudflare_set_for_the_setpoint_check_gets_no_jev(
    hass, controller_for, monkeypatch, capsys, options
):
    """2.25.1 used Cloudflare only for the hourly Auto Setpoints check. After the update the
    Supervisor serves jev_enabled: true beside those keys, and no Jev file is in /data: the
    acting brain must stay off, while the setpoint check keeps its credentials."""
    seed = fixture(UPSTREAM_2_25_1)
    await _upgrade(hass, UPSTREAM_2_25_1, registry_ids=seed["registry"])
    hass.states.async_set(KILL, "on")
    c, app, built, _stub, data = _seeded_app(
        controller_for, monkeypatch, options, saved_state=seed["controller_saved"]
    )
    assert app["options"].get("jev_enabled") is (True if "merged" in options else None)
    assert c.jev is None and built == []  # no brain, and no route to ask anything through
    assert c._cf[:2] == ("fixture-account", "fixture-token")
    assert [p.name for p in data.iterdir() if p.name.startswith("jev_")] == []
    said = capsys.readouterr().out
    assert "jev: off" in said and "fixture-token" not in said
    assert c.rooms[0]._setup_pending is None  # and the room carries straight on


@pytest.mark.parametrize(
    "options, route",
    [
        ("options_3_0_0_jev_cf.json", "Cloudflare"),  # a ledger only
        ("options_3_2_0_jev_cf.json", "Cloudflare"),  # ledger, journal and setpoint memory
        ("options_3_3_0_jev_typesafe.json", "TypeSafe"),  # no Jev file: the key is enough
        ("options_3_11_1_jev_cf_usage.json", "Cloudflare"),  # the usage file alone
    ],
)
async def test_a_jev_line_app_keeps_its_brain_with_no_option_changed(
    hass, controller_for, monkeypatch, options, route
):
    """Each app from the Jev line, its options and /data as that version left them, still
    reaches its own route after the update, with nothing changed and no re-setup."""
    await _upgrade(hass, "entry_2_17_wizard.json")
    c, app, built, stub, data = _seeded_app(controller_for, monkeypatch, options)
    assert c.jev is not None and c.jev.routes == [route]
    assert [r.name for r in built[0]] == [route] and c.jev.asker.transport is stub
    token = app["options"]["typesafe_api_key"] or app["options"]["cf_api_token"]
    assert built[0][0].token == token  # its own credentials, as saved
    saved = json.loads((data / "state.json").read_text(encoding="utf-8"))["default"]["1"]
    assert c.rooms[0].state[1]["phase"] == saved["phase"]
    if (data / "jev_ledger.jsonl").exists():
        assert c.jev.ledger.entries  # its ledger is read back, not started again


async def test_a_3_0_0_app_on_cloudflare_whose_brain_never_acted_runs_without_jev(
    hass, controller_for, monkeypatch
):
    """Pinned on purpose. A 3.0.0 app on Cloudflare only whose brain never acted wrote no Jev
    file, so it cannot be told from a 2.x app: it runs without Jev after the update, which the
    release notes say. Changing this is a decision, not a side effect."""
    await _upgrade(hass, "entry_2_17_wizard.json")
    c, _app, built, _stub, _data = _seeded_app(
        controller_for, monkeypatch, "options_3_0_0_jev_cf_quiet.json"
    )
    assert c.jev is None and built == []


# ------------------------------------------------------------------ a Jev 3.11.1 install
JEV_3_11_1 = "entry_3_11_1_pumped_room.json"


async def test_a_3_11_1_room_keeps_every_entity_id_its_moved_ladder_and_its_dosing_setup(
    hass, hass_storage
):
    """The last Jev release (tests_ha/fixtures/entry_3_11_1_pumped_room.json, recorded from 3.11.1's own
    wizard and controller): every entity it registered keeps its id and has a state, except those this
    code retires on purpose; each zone's ladder stays where 3.11.1's Auto setpoints moved it; the entry
    is loaded as it is; and the dosing setup it saved is the one the controller app is shown."""
    from custom_components.crop_steering import _RETIRED

    seed = fixture(JEV_3_11_1)
    dosing = fixture("dosing_3_11_1.json")["dosing"]
    store = f"{DOMAIN}.dosing.{seed['entry_id']}"
    hass_storage[store] = {"version": 1, "minor_version": 1, "key": store, "data": dosing}
    entry, _seed = await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    assert (entry.version, entry.minor_version) == (seed["version"], seed["minor_version"])
    assert entry.data == seed["data"] and entry.options == seed["options"]

    registry = er.async_get(hass)
    kept = [
        entity_id
        for entity_id, key in seed["registry"].items()
        if re.sub(r"^zone_\d+_", "zone_", key) not in _RETIRED.get(entity_id.split(".")[0], ())
    ]
    assert len(kept) > 100
    assert [e for e in kept if registry.async_get(e) is None] == []
    assert [e for e in kept if hass.states.get(e) is None] == []

    for entity_id, saved in seed["operator_tuned_numbers"].items():
        tuned = saved[0] if isinstance(saved, list) else saved
        state = hass.states.get(entity_id).state
        if entity_id.startswith("number."):
            assert float(state) == float(tuned), entity_id
        else:
            assert state == tuned, entity_id
    for entity_id, value in seed["moved_by_the_controller"].items():
        assert float(hass.states.get(entity_id).state) == value, entity_id
    assert float(hass.states.get("number.crop_steering_lights_on_hour").state) == 6
    assert float(hass.states.get("number.crop_steering_lights_off_hour").state) == 18

    descriptor = hass.states.get(DESCRIPTOR).attributes
    assert (descriptor["pump"], descriptor["mainline"], descriptor["plumbing"]) == (
        "switch.irrigation_pump",
        "switch.irrigation_main_line",
        "pump_mainline_valves",
    )
    assert descriptor["setup_revision"] == 1

    shown = hass.states.get("sensor.crop_steering_dosing_config")
    assert int(shown.state) == dosing["revision"]
    assert shown.attributes["pumps"] == dosing["pumps"]
    # Shown with the refill reminder off: the setup was saved before it (docs/DOSING.md).
    assert shown.attributes["batch"] == {**dosing["batch"], "level_entity": None, "remind_pct": 0}


def _jev_3_11_1_app(controller_for, monkeypatch, options):
    """The real controller on the 3.11.1 room's app: its options file, and the /data/state.json and
    /data/jev_usage.json 3.11.1 left, on the day that usage file was written. Jev's routes are stubbed:
    `built` records every route list the brain was given."""
    import functools

    import jev_bridge
    import jev_kit
    from jev.client import Asker

    usage = fixture("jev_usage_3_11_1.json")["usage"]
    data = Path(os.environ["F2_STATE_PATH"]).parent
    (data / "jev_usage.json").write_text(json.dumps(usage), encoding="utf-8")
    noon = datetime.fromisoformat(usage["day"]).replace(hour=12).timestamp()
    built, stub = [], jev_kit.FakeTransport({})
    monkeypatch.setattr(jev_bridge, "Routes", lambda found, **kw: built.append(found) or stub)
    monkeypatch.setattr(
        jev_bridge, "Asker", functools.partial(Asker, threaded=False, clock=lambda: noon)
    )
    state = fixture("state_3_11_1_learn_jev.json")["state"]
    c, fake, _clock = controller_for(fixture(options)["options"], saved_state=state)
    return c, fake, built, usage, state


async def test_the_controller_carries_a_3_11_1_room_straight_on_with_its_learner_and_jev(
    hass, controller_for, monkeypatch
):
    """Both layers updated on an armed 3.11.1 box on Cloudflare. The new controller resumes the adopted
    setup with no disarm cycle, its brain starts on the same route with the same credentials and the
    day's call count, every learned value (the working peak Jev held above the learned one included)
    and the day before's peak load as they were, and writing the state back keeps every value 3.11.1
    wrote."""
    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    hass.states.async_set(KILL, "on")  # armed and growing: nobody is going to disarm it
    c, fake, built, usage, state = _jev_3_11_1_app(
        controller_for, monkeypatch, "options_3_11_1_jev_cf.json"
    )
    room, old = c.rooms[0], state["default"]

    assert room._setup_pending is None, room._setup_pending
    assert room.setup_revision == 1
    assert "Setup" not in (c._blocked(room, 1) or "")
    assert c.jev is not None and c.jev.routes == ["Cloudflare"]
    assert built[0][0].token == "fixture-token"
    assert c.jev.asker.stats["calls"] == usage["calls"]  # the day's count survives the update
    assert "setpoints" not in {j.name for j in c.jev.judges}  # the judges the operator chose
    c._refresh_lights(room)
    assert (room.lights_on_hour, room.lights_off_hour) == (6.0, 18.0)
    for zone in (1, 2):
        st, was = room.state[zone], old[str(zone)]
        assert (st["phase"], st["peak"], st["peak_prev"], st["shots"], st["daily_vol"]) == (
            was["phase"],
            was["peak"],
            was["peak_prev"],
            was["shots"],
            was["daily_vol"],
        )
        assert st["learn"] == was["learn"]
        assert st["learn"]["peak_adj"] == 1.0 and st["learn"]["jev"]["nudged"] == ["peak"]

    assert c._save_state()
    saved = json.loads(Path(os.environ["F2_STATE_PATH"]).read_text(encoding="utf-8"))["default"]
    assert saved["_setup"] == old["_setup"]
    for zone in ("1", "2"):
        written, was = saved[zone], old[zone]
        assert {k: written[k] for k in was if k != "learn"} == {
            k: v for k, v in was.items() if k != "learn"
        }
        assert {k: written["learn"][k] for k in was["learn"]} == was["learn"]

    # ...and it still drives the room the way 3.11.1 did: pump, main line, valve.
    for switch in (
        "switch.crop_steering_system_enabled",
        "switch.crop_steering_auto_irrigation_enabled",
        "switch.crop_steering_zone_1_enabled",
    ):
        fake.set_state(switch, "on")
    fake.calls.clear()
    c._execute_shot(room, 1, 10, 5, flow_lps=0.05)
    assert switch_calls(fake) == [
        ("turn_on", "switch.irrigation_pump"),
        ("turn_on", "switch.irrigation_main_line"),
        ("turn_on", "switch.zone_1_valve"),
        ("turn_off", "switch.zone_1_valve"),
        ("turn_off", "switch.irrigation_main_line"),
        ("turn_off", "switch.irrigation_pump"),
    ]


async def test_a_3_11_1_app_on_typesafe_keeps_its_brain_and_the_room_its_state(
    hass, controller_for, monkeypatch
):
    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    hass.states.async_set(KILL, "on")
    c, _fake, built, _usage, state = _jev_3_11_1_app(
        controller_for, monkeypatch, "options_3_11_1_jev_typesafe.json"
    )
    assert c.jev is not None and c.jev.routes == ["TypeSafe"]
    assert built[0][0].token == "fixture-typesafe-key"
    assert c.rooms[0]._setup_pending is None
    assert c.rooms[0].state[1]["learn"] == state["default"]["1"]["learn"]


# ------------------------------------------------------------------ an env-file era install
async def test_an_env_era_install_with_only_front_and_back_probes_still_loads_and_fuses(
    hass,
):
    seed = fixture("entry_env_era.json")
    entry, _ = await _upgrade(
        hass, "entry_env_era.json", registry_ids=_known_numbers(seed)
    )
    assert float(hass.states.get("sensor.crop_steering_vwc_zone_1").state) == 60.0
    assert float(hass.states.get("number.crop_steering_substrate_volume").state) == 8
    assert entry.options == seed["options"]  # old bookkeeping keys are left exactly as found


async def test_a_probe_with_no_unit_on_an_old_install_reads_exactly_as_it_always_did(hass):
    """Setup refuses to MAP a unit-less EC probe. One mapped years ago through the env file must
    not be reinterpreted on upgrade: (3.0 mS/cm + 3.4 unit-less) / 2 was 3.2 and stays 3.2."""
    await _upgrade(hass, "entry_env_era.json")
    assert float(hass.states.get("sensor.crop_steering_ec_zone_1").state) == pytest.approx(
        3.2
    )


async def test_the_upgrade_is_reversible_by_reloading(hass):
    entry, _seed = await _upgrade(hass, "entry_2_17_wizard.json")
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(DESCRIPTOR) is not None


async def test_a_second_room_can_still_be_added_beside_an_upgraded_default_room(hass):
    await _upgrade(hass, "entry_2_17_wizard.json")
    hass.states.async_set("switch.veg_tent", "off")
    hass.states.async_set("sensor.veg_vwc", "50", {"unit_of_measurement": "%"})
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert flow["type"] is FlowResultType.FORM and flow["step_id"] == "room"
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"room_name": "Veg tent"}
    )
    assert flow["step_id"] == "manual_zones"
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {"num_zones": 1})
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        {
            "zone_1_switch": "switch.veg_tent",
            "zone_1_vwc": ["sensor.veg_vwc"],
            "zone_1_plant_count": 2,
        },
    )
    assert flow["step_id"] == "hardware", flow.get("errors")
    done = await hass.config_entries.flow.async_configure(flow["flow_id"], {"plumbing": "valves_only"})
    assert done["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    # Fully isolated: its own prefixed entities, and the default room's are untouched.
    assert hass.states.get("sensor.crop_steering_veg_tent_engine_config") is not None
    assert hass.states.get(DESCRIPTOR).attributes["pump"] == "switch.main_pump"
