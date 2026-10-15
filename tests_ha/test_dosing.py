"""Batch-tank dosing in a real Home Assistant (docs/DOSING.md): the three services through its
registry, schemas and auth store; sensor.crop_steering_dosing_config, which the controller app reads,
under that exact id; a setup and its request that survive a reload; and an install from before
dosing that loads with an empty setup."""

import pytest
from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.core import Context, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockUser
from test_setup_entry import _install
from test_upgrade_in_place import _upgrade

DOMAIN = "crop_steering"
ROOM = "room:"
SENSOR = "sensor.crop_steering_dosing_config"
REFUSED = "requires an authenticated Home Assistant administrator"
PUMP = {
    "id": "balance",
    "name": "Balance",
    "volume_entity": "number.doser_balance_volume",
    "start_entity": "button.doser_balance_start",
    "dosing_entity": "binary_sensor.doser_balance_dosing",
    "power_entity": "switch.doser_balance_power",
    "flow_entity": "number.doser_balance_flow",
    "max_ml": 2000,
}
BATCH = {
    "fill_valve": "switch.tank_fill",
    "full_entity": "binary_sensor.tank_full",
    "mix_pump": "switch.tank_mixer",
    "hold_entity": "input_boolean.tank_dosing",
    "filled_at_entity": "input_datetime.tank_filled_at",
    "recipe": [{"pump": "balance", "ml": 300}],
}
DEVICES = {
    "number.doser_balance_volume": "25",
    "button.doser_balance_start": "unknown",
    "binary_sensor.doser_balance_dosing": "off",
    "switch.doser_balance_power": "off",
    "number.doser_balance_flow": "11.06",
    "switch.tank_fill": "off",
    "binary_sensor.tank_full": "off",
    "switch.tank_mixer": "off",
    "input_boolean.tank_dosing": "off",
    "input_datetime.tank_filled_at": "2026-09-27 19:00:00",
}


def _devices(hass):
    for entity_id, state in DEVICES.items():
        hass.states.async_set(entity_id, state)


async def _call(hass, user, name, **data):
    return await hass.services.async_call(
        DOMAIN,
        name,
        {"room_id": ROOM, **data},
        blocking=True,
        return_response=True,
        context=Context(user_id=user.id if user else None),
    )


async def test_the_services_and_the_sensor_the_controller_reads(hass, hass_admin_user):
    entry = await _install(hass)
    for name in ("dosing_get", "dosing_save", "dosing_request"):
        assert hass.services.supports_response(DOMAIN, name) is SupportsResponse.ONLY
    registered = er.async_get(hass).async_get(SENSOR)
    assert registered.unique_id == f"{DOMAIN}_{entry.entry_id}_dosing_config"
    state = hass.states.get(SENSOR)
    assert state.state == "0"
    assert (state.attributes["pumps"], state.attributes["request"]) == ([], None)
    assert state.attributes["batch"]["recipe"] == []

    _devices(hass)
    doc = await _call(hass, hass_admin_user, "dosing_get")
    assert (doc["schema_version"], doc["room_id"], doc["error"]) == (1, ROOM, None)
    assert doc["can_edit"] is True
    offered = {c["entity_id"]: c for c in doc["candidates"]}
    assert offered["number.doser_balance_flow"]["state"] == "11.06"
    assert SENSOR in offered  # a sensor like any other; the setup is the operator's to pick

    doc = await _call(
        hass,
        hass_admin_user,
        "dosing_save",
        expected_revision=0,
        pumps=[PUMP],
        batch=BATCH,
    )
    assert doc["error"] is None and doc["config"]["revision"] == 1
    assert doc["can_edit"] is True
    await hass.async_block_till_done()
    state = hass.states.get(SENSOR)
    assert state.state == "1"
    assert state.attributes["pumps"][0] == {
        **PUMP,
        "dosing_prefix": "Dosing",
        "restore_volume": True,
        "stock_tank": None,
    }
    assert state.attributes["batch"]["recipe"] == [
        {"pump": "balance", "ml": 300, "ml_entity": None}
    ]
    stale = await _call(
        hass, hass_admin_user, "dosing_save", expected_revision=0, pumps=[], batch={}
    )
    assert stale["error"] == "revision"

    answer = await _call(
        hass, hass_admin_user, "dosing_request", action="dose", pump="balance", ml=25
    )
    assert answer["error"] is None
    assert answer["request"]["by"] == hass_admin_user.name
    assert (answer["request"]["pump"], answer["request"]["ml"]) == ("balance", 25)
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).attributes["request"] == answer["request"]
    assert hass.states.get(SENSOR).state == "1"  # a request is not a new setup
    busy = await _call(hass, hass_admin_user, "dosing_request", action="batch")
    assert busy == {"request": None, "error": "busy"}
    # The controller app publishes the request as handled: the next one is taken.
    hass.states.async_set(
        "sensor.crop_steering_dosing", "dosing", {"handled": answer["request"]["id"]}
    )
    stop = await _call(hass, hass_admin_user, "dosing_request", action="stop")
    assert stop["error"] is None and stop["request"]["action"] == "stop"
    # Out of range: refused with a reason, nothing stored.
    hass.states.async_set(
        "sensor.crop_steering_dosing", "idle", {"handled": stop["request"]["id"]}
    )
    too_much = await _call(
        hass, hass_admin_user, "dosing_request", action="dose", pump="balance", ml=2500
    )
    assert "at most 2000" in too_much["error"] and too_much["request"] is None


async def _staff(hass):
    users = await hass.auth.async_get_group(GROUP_ID_USER)
    return MockUser(name="Staff phone", groups=[users]).add_to_hass(hass)


async def test_an_ordinary_user_can_read_and_stop_dosing_but_never_save_or_dose(
    hass, hass_admin_user
):
    await _install(hass)
    _devices(hass)
    await _call(
        hass, hass_admin_user, "dosing_save", expected_revision=0, pumps=[PUMP], batch={}
    )
    staff = await _staff(hass)
    assert not staff.is_admin
    doc = await _call(hass, staff, "dosing_get")
    assert doc["config"]["revision"] == 1 and doc["can_edit"] is False  # read-only for them
    for name, data in (
        ("dosing_save", {"expected_revision": 1, "pumps": [], "batch": {}}),
        ("dosing_request", {"action": "dose", "pump": "balance", "ml": 5}),
        ("dosing_request", {"action": "batch"}),
    ):
        with pytest.raises(HomeAssistantError, match=REFUSED):
            await _call(hass, staff, name, **data)
    await hass.async_block_till_done()
    state = hass.states.get(SENSOR)
    assert (state.state, state.attributes["request"]) == ("1", None)
    # A stop only switches things off: they may ask for one.
    stop = await _call(hass, staff, "dosing_request", action="stop")
    assert stop["error"] is None and stop["request"]["by"] == "Staff phone"
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).attributes["request"] == stop["request"]


async def test_the_setup_is_never_saved_under_a_dose_or_batch_the_controller_reports(
    hass, hass_admin_user
):
    await _install(hass)
    _devices(hass)
    await _call(
        hass, hass_admin_user, "dosing_save", expected_revision=0, pumps=[PUMP], batch={}
    )
    for state in ("dosing", "batch"):
        hass.states.async_set("sensor.crop_steering_dosing", state, {"handled": None})
        busy = await _call(
            hass, hass_admin_user, "dosing_save", expected_revision=1, pumps=[], batch={}
        )
        assert busy["error"] == "busy" and busy["config"]["revision"] == 1
    hass.states.async_set("sensor.crop_steering_dosing", "idle", {"handled": None})
    saved = await _call(
        hass, hass_admin_user, "dosing_save", expected_revision=1, pumps=[], batch={}
    )
    assert saved["error"] is None and saved["config"]["revision"] == 2


async def test_a_saved_setup_and_its_request_survive_a_reload(hass, hass_admin_user):
    entry = await _install(hass)
    _devices(hass)
    await _call(
        hass, hass_admin_user, "dosing_save", expected_revision=0, pumps=[PUMP], batch={}
    )
    request = (
        await _call(
            hass, hass_admin_user, "dosing_request", action="dose", pump="balance", ml=5
        )
    )["request"]
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    doc = await _call(hass, hass_admin_user, "dosing_get")
    assert doc["error"] is None and doc["config"]["revision"] == 1
    assert doc["config"]["pumps"][0]["id"] == "balance"
    assert doc["config"]["request"] == request
    state = hass.states.get(SENSOR)
    assert state.state == "1" and state.attributes["request"] == request


async def test_an_install_from_before_dosing_loads_with_an_empty_setup(hass):
    """UPGRADE IN PLACE: a 2.17 room has no dosing store and no dosing_config entity."""
    await _upgrade(hass, "entry_2_17_wizard.json")
    state = hass.states.get(SENSOR)
    assert state is not None and state.state == "0"
    assert (state.attributes["pumps"], state.attributes["request"]) == ([], None)
    doc = await _call(hass, None, "dosing_get")  # an automation: it reads, and may not edit
    assert doc["error"] is None and doc["config"]["pumps"] == []
    assert doc["can_edit"] is False
