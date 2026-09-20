"""IN-PLACE UPGRADE, in a real Home Assistant, from SEEDED snapshots of old installs.

"Never break a live install." Each file in tests_ha/fixtures/ is a room as an OLD version
actually left it: its config entry, operator-tuned values in the restore cache, and (for the
controller tests) the state file and setup fingerprint its controller had saved. The new code is
started on top of it the way a HACS update + Supervisor update does - no wizard, no reconfigure.

What must hold: nothing the operator set moves, no entity changes id, and the controller carries
straight on. To cover another kind of old install, add a snapshot rather than hand-building one.
"""

import json

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
