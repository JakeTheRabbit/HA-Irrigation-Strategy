"""What a room grows in is one choice per room, in Home Assistant: select.crop_steering_<prefix>substrate,
generic until someone chooses. The room's engine_config descriptor publishes it and the controller reads
it from there. An upgraded room reads generic, keeps every entity id it had, and its controller carries
straight on: the substrate is not part of the setup the controller adopts, so it never asks for a
disarm cycle, and a descriptor from an older integration (no substrate in it) runs as generic."""

import json
import os
import re
from pathlib import Path

from conftest import fixture, room_of
from homeassistant.const import ATTR_OPTION
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, UPSTREAM_2_25_1, _jev_3_11_1_app, _upgrade

DOMAIN = "crop_steering"
SUBSTRATE = "select.crop_steering_substrate"
DESCRIPTOR = "sensor.crop_steering_engine_config"
KILL = "switch.crop_steering_engine_enabled"
# A new room has a slug: the wizard's "Tent" is tent_.
NEW_SUBSTRATE = "select.crop_steering_tent_substrate"
NEW_DESCRIPTOR = "sensor.crop_steering_tent_engine_config"


async def _choose(hass, entity_id, option):
    await hass.services.async_call(
        "select", "select_option", {"entity_id": entity_id, ATTR_OPTION: option}, blocking=True
    )
    await hass.async_block_till_done()


def _new_since(hass, entry, seed):
    """Every entity id this entry has now that the old install did not register, and every one it
    did register that is gone or answers to another id (those this code retires on purpose aside)."""
    from custom_components.crop_steering import _RETIRED

    registry = er.async_get(hass)
    now = {e.entity_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)}
    kept = {
        entity_id
        for entity_id, key in seed["registry"].items()
        if re.sub(r"^zone_\d+_", "zone_", key) not in _RETIRED.get(entity_id.split(".")[0], ())
    }
    moved = {
        entity_id
        for entity_id in kept
        if registry.async_get_entity_id(
            entity_id.split(".")[0], DOMAIN, f"{DOMAIN}_{seed['entry_id']}_{seed['registry'][entity_id]}"
        )
        != entity_id
    }
    return now - set(seed["registry"]), moved


async def test_a_new_room_is_generic_until_someone_chooses_and_the_descriptor_follows(
    hass, controller_for
):
    entry = await _install(hass)
    select = hass.states.get(NEW_SUBSTRATE)
    assert select.state == "generic"
    assert select.attributes["options"] == ["generic", "rockwool", "coco"]
    assert hass.states.get(NEW_DESCRIPTOR).attributes["substrate"] == "generic"

    await _choose(hass, NEW_SUBSTRATE, "coco")
    assert hass.states.get(NEW_DESCRIPTOR).attributes["substrate"] == "coco"
    # The choice is the room's: it survives the room being reloaded (a restart restores it the same way).
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(NEW_SUBSTRATE).state == "coco"
    assert hass.states.get(NEW_DESCRIPTOR).attributes["substrate"] == "coco"

    c, _fake, _clock = controller_for({})
    assert room_of(c).substrate == "coco"


async def test_a_named_room_has_its_own_choice(hass, controller_for):
    await _install(hass)
    hass.states.async_set("switch.veg_tent", "off")
    hass.states.async_set("sensor.veg_vwc", "50", {"unit_of_measurement": "%"})
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {"room_name": "Veg tent"})
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {"num_zones": 1})
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        {"zone_1_switch": "switch.veg_tent", "zone_1_vwc": ["sensor.veg_vwc"], "zone_1_plant_count": 2},
    )
    done = await hass.config_entries.flow.async_configure(flow["flow_id"], {"plumbing": "valves_only"})
    assert done["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    await _choose(hass, "select.crop_steering_veg_tent_substrate", "rockwool")
    descriptor = hass.states.get("sensor.crop_steering_veg_tent_engine_config").attributes
    assert descriptor["substrate"] == "rockwool"
    assert hass.states.get(NEW_DESCRIPTOR).attributes["substrate"] == "generic"  # the other room's is its own

    c, _fake, _clock = controller_for({})
    assert {room.prefix: room.substrate for room in c.rooms} == {"": "generic", "tent_": "generic", "veg_tent_": "rockwool"}


async def test_a_2_25_1_room_reads_generic_moves_no_entity_and_carries_straight_on(
    hass, controller_for
):
    seed = fixture(UPSTREAM_2_25_1)
    entry, _seed = await _upgrade(hass, UPSTREAM_2_25_1, registry_ids=seed["registry"])
    assert hass.states.get(SUBSTRATE).state == "generic"
    assert hass.states.get(DESCRIPTOR).attributes["substrate"] == "generic"
    new, moved = _new_since(hass, entry, seed)
    assert SUBSTRATE in new and moved == set()

    hass.states.async_set(KILL, "on")  # armed and growing: nobody is going to disarm it
    c, _fake, _clock = controller_for(seed["addon_options"], saved_state=seed["controller_saved"])
    room = c.rooms[0]
    assert room.substrate == "generic"
    assert room._setup_pending is None and room.setup_revision == 1  # the fingerprint 2.25.1 saved
    assert "Setup" not in (c._blocked(room, 1) or "")


async def test_a_3_11_1_room_gets_only_the_substrate_select_and_its_controller_carries_on(
    hass, controller_for, monkeypatch
):
    seed = fixture(JEV_3_11_1)
    entry, _seed = await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    assert hass.states.get(SUBSTRATE).state == "generic"
    assert hass.states.get(DESCRIPTOR).attributes["substrate"] == "generic"
    new, moved = _new_since(hass, entry, seed)
    # Nothing moves, and nothing appears but the substrate select and the other additive settings
    # (drainage, the sump threshold, each zone's Test Shot button and P3 time between shots).
    others = {"select.crop_steering_drainage", "number.crop_steering_sump_power_threshold_w"}
    assert SUBSTRATE in new and moved == set()
    assert {e for e in new - others - {SUBSTRATE} if not e.endswith(("_test_shot", "_p3_time_between_shots"))} == set()

    hass.states.async_set(KILL, "on")
    c, _fake, _built, _usage, state = _jev_3_11_1_app(
        controller_for, monkeypatch, "options_3_11_1_jev_cf.json"
    )
    room = c.rooms[0]
    assert room.substrate == "generic"
    assert room._setup_pending is None and room.setup_revision == 1  # the fingerprint 3.11.1 saved
    assert "Setup" not in (c._blocked(room, 1) or "")
    assert c._save_state()
    saved = json.loads(Path(os.environ["F2_STATE_PATH"]).read_text(encoding="utf-8"))["default"]
    assert saved["_setup"] == state["default"]["_setup"]  # nothing about the substrate is saved


async def test_a_controller_told_by_an_older_integration_runs_the_room_as_generic(
    hass, controller_for
):
    """An integration from before the select publishes no substrate: the controller still runs."""
    seed = fixture(UPSTREAM_2_25_1)
    await _upgrade(hass, UPSTREAM_2_25_1, registry_ids=seed["registry"])
    await _choose(hass, SUBSTRATE, "coco")
    descriptor = hass.states.get(DESCRIPTOR)
    older = {k: v for k, v in descriptor.attributes.items() if k != "substrate"}
    hass.states.async_set(DESCRIPTOR, descriptor.state, older)
    hass.states.async_set(KILL, "on")

    c, _fake, _clock = controller_for(seed["addon_options"], saved_state=seed["controller_saved"])
    room = c.rooms[0]
    assert room.substrate == "generic"
    assert room._setup_pending is None and "Setup" not in (c._blocked(room, 1) or "")
