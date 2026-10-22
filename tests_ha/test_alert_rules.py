"""Threshold alert rules (G6) in a real Home Assistant: the rule's binary sensor comes and goes with
the rule and turns on only after its min_duration_s, through Home Assistant's own clock, services,
entity platform and registry; an old install with no rules gets no binary sensors at all.
"""

from datetime import timedelta

from homeassistant.core import Context
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
