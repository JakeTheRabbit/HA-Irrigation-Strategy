"""Threshold alert rules (G6) in a real Home Assistant: the rule's binary sensor comes and goes with
the rule and turns on only after its min_duration_s, through Home Assistant's own clock, services,
entity platform and registry; an old install with no rules gets no binary sensors at all.
"""

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context, SupportsResponse
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from test_non_admin_user import _staff
from test_setup_entry import _install
from test_upgrade_in_place import _upgrade

DOMAIN = "crop_steering"
ROOM = "room:tent_"
LEVEL = "sensor.crop_steering_tent_tank_level"
RULE = {
    "room_id": ROOM,
    "source": "tank.level",
    "op": "below",
    "threshold": 30,
    "min_duration_s": 120,
}


async def _call(hass, user, service, **data):
    return await hass.services.async_call(
        DOMAIN,
        service,
        data,
        blocking=True,
        return_response=True,
        context=Context(user_id=user.id if user else None),
    )


async def _minute(hass, freezer, seconds=60):
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_rule_entity_appears_and_turns_on_after_min_duration(
    hass, hass_admin_user, freezer
):
    await _install(hass)
    hass.states.async_set(LEVEL, "12", {"unit_of_measurement": "%"})
    saved = await _call(
        hass, hass_admin_user, "alert_rule_set", expected_revision=0, rule=RULE
    )
    await hass.async_block_till_done()
    assert saved["revision"] == 1
    assert saved["summary_sentence"].endswith("tank level stays below 30% for 2 min.")
    entity_id = f"binary_sensor.crop_steering_rule_{saved['rule']['id'].lower()}"
    assert hass.states.get(entity_id).state == "off"
    assert hass.states.get(entity_id).attributes["state"] == "pending"
    assert er.async_get(hass).async_get(entity_id) is not None

    await _minute(hass, freezer)
    assert hass.states.get(entity_id).state == "off"  # 1 min of 2
    await _minute(hass, freezer, 61)
    state = hass.states.get(entity_id)
    assert state.state == "on" and state.attributes["firing_since"]
    # A short name, with the room's name and no sentence.
    assert state.attributes["friendly_name"].endswith(" tank level below 30%")

    listed = await _call(hass, None, "alert_rule_list", room_id=ROOM)
    (row,) = listed["rules"]
    assert row["state"] == "firing" and row["current_value"] == 12.0
    assert (
        row["unit"] == "%" and row["firing_since"] == state.attributes["firing_since"]
    )

    # Back above: the rule clears at once, on the state change.
    hass.states.async_set(LEVEL, "45", {"unit_of_measurement": "%"})
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "off"

    await _call(
        hass,
        hass_admin_user,
        "alert_rule_delete",
        id=saved["rule"]["id"],
        expected_revision=1,
    )
    await hass.async_block_till_done()
    assert hass.states.get(entity_id) is None
    assert er.async_get(hass).async_get(entity_id) is None
    assert (await _call(hass, None, "alert_rule_list"))["rules"] == []


async def test_an_ordinary_user_previews_and_tests_but_cannot_send(hass):
    await _install(hass)
    staff = await _staff(hass)
    preview = await _call(hass, staff, "alert_rule_preview", rule=RULE, hours=24)
    assert preview["summary_sentence"].endswith("tank level stays below 30% for 2 min.")
    assert preview["count"] == 0 and preview["series"] == [] and preview["fires"] == []
    answer = await _call(hass, staff, "alert_rule_test", rule=RULE)
    assert answer["replay"]["count"] == 0 and "delivery" not in answer
    # A refused draft says why, in the v2 envelope too.
    out = await _call(
        hass, staff, "alert_rule_preview", rule={**RULE, "source": "room.vpd"}, api=2
    )
    assert out["ok"] is False and out["error"]["code"] == "invalid"
    assert "climate" in out["error"]["message"]


async def test_old_install_without_rules_loads_with_no_binary_sensors(hass):
    entry, _ = await _upgrade(hass, "entry_3_11_1_pumped_room.json")
    registry = er.async_get(hass)
    assert [
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "binary_sensor"
    ] == []
    assert not [
        s for s in hass.states.async_entity_ids("binary_sensor") if "_rule_" in s
    ]
    site = hass.data[DOMAIN]["_site"]
    assert site.alerts._unsubs == [] and site.alerts._watching == ()
    assert (await _call(hass, None, "alert_rule_list"))["rules"] == []


async def test_alert_rule_test_can_send_so_it_answers_optionally(hass):
    await _install(hass)
    supports = hass.services.supports_response
    assert supports(DOMAIN, "alert_rule_test") is SupportsResponse.OPTIONAL
    for read in ("alert_rule_list", "alert_rule_preview"):
        assert supports(DOMAIN, read) is SupportsResponse.ONLY


async def _fire(hass, freezer, entity_id):
    await _minute(hass, freezer)
    assert hass.states.get(entity_id).state == "off"
    await _minute(hass, freezer, 61)
    assert hass.states.get(entity_id).state == "on"


async def test_a_firing_rule_fires_again_after_a_restart(
    hass, hass_admin_user, freezer
):
    """The rule's state lives in memory: a restart arms it again, and a source still out of range
    raises it again once min_duration_s has passed."""
    entry = await _install(hass)
    hass.states.async_set(LEVEL, "12", {"unit_of_measurement": "%"})
    saved = await _call(
        hass, hass_admin_user, "alert_rule_set", expected_revision=0, rule=RULE
    )
    await hass.async_block_till_done()
    entity_id = f"binary_sensor.crop_steering_rule_{saved['rule']['id'].lower()}"
    await _fire(hass, freezer, entity_id)

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.state == "off" and state.attributes["state"] == "pending"
    await _fire(hass, freezer, entity_id)
    events = await _call(
        hass,
        None,
        "journal_query",
        room_id=ROOM,
        since="2000-01-01T00:00:00+00:00",
        kinds=["alert.raised"],
    )
    assert [e["data"]["rule_id"] for e in events["events"]] == [saved["rule"]["id"]] * 2


async def test_the_last_room_unloading_stops_the_rules(hass, hass_admin_user, freezer):
    entry = await _install(hass)
    hass.states.async_set(LEVEL, "12", {"unit_of_measurement": "%"})
    await _call(hass, hass_admin_user, "alert_rule_set", expected_revision=0, rule=RULE)
    await hass.async_block_till_done()
    evaluator = hass.data[DOMAIN]["_site"].alerts
    assert evaluator._unsubs and evaluator._watching
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert evaluator._unsubs == [] and evaluator._watching == ()
    assert "_site" not in hass.data.get(DOMAIN, {})
    before = dict(evaluator.states)
    hass.states.async_set(LEVEL, "5", {"unit_of_measurement": "%"})
    await _minute(hass, freezer, 180)
    assert evaluator.states == before  # nothing evaluates any more


async def _second_room(hass):
    hass.states.async_set("switch.veg_tent", "off")
    hass.states.async_set("sensor.veg_vwc", "50", {"unit_of_measurement": "%"})
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"room_name": "Veg tent"}
    )
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"num_zones": 1}
    )
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        {
            "zone_1_switch": "switch.veg_tent",
            "zone_1_vwc": ["sensor.veg_vwc"],
            "zone_1_plant_count": 2,
        },
    )
    done = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"plumbing": "valves_only"}
    )
    assert done["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    return done["result"]


async def test_a_rule_moved_to_another_room_moves_its_sensor_without_a_collision(
    hass, hass_admin_user, caplog
):
    first, _ = await _upgrade(hass, "entry_2_17_wizard.json")  # the default room, room:
    second = await _second_room(hass)
    rule = {**RULE, "room_id": "room:"}
    saved = await _call(
        hass, hass_admin_user, "alert_rule_set", expected_revision=0, rule=rule
    )
    await hass.async_block_till_done()
    entity_id = f"binary_sensor.crop_steering_rule_{saved['rule']['id'].lower()}"
    registry = er.async_get(hass)
    assert registry.async_get(entity_id).config_entry_id == first.entry_id

    moved = {**saved["rule"], "room_id": "room:veg_tent_"}
    await _call(
        hass, hass_admin_user, "alert_rule_set", expected_revision=1, rule=moved
    )
    await hass.async_block_till_done()
    assert registry.async_get(entity_id).config_entry_id == second.entry_id
    assert hass.states.get(entity_id).attributes["room_id"] == "room:veg_tent_"
    assert (
        hass.states.get(entity_id)
        .attributes["friendly_name"]
        .endswith("Veg tent tank level below 30%")
    )
    assert "unique ID" not in caplog.text and "already exists" not in caplog.text
    assert [
        e.entity_id
        for e in registry.entities.values()
        if e.unique_id == f"crop_steering_rule_{saved['rule']['id']}"
    ] == [entity_id]
