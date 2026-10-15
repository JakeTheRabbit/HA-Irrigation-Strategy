"""The room's dosing hardware profile (docs/DOSING.md, Hardware profile) in a real Home Assistant.

The 3.11.1 room's own dosing store (F-3111), saved before the profile existed, loads with the
default profile, which is today's timings, and the REAL controller app works to exactly those. A
profile saved through dosing_save is published to the controller, which then works to it; a save
that sends none keeps it, and one out of range is refused.
"""

import dosing_runner
from conftest import fixture
from test_dosing import _call
from test_dosing_units_and_actuators import DOSER, _commands, _firmware, _run
from test_upgrade_in_place import JEV_3_11_1, _upgrade

DOMAIN = "crop_steering"
SENSOR = "sensor.crop_steering_dosing_config"
DEFAULTS = {
    "hold_wait_s": 600,
    "fill_open_s": 10,
    "full_blind_s": 15,
    "mix_power_s": 20,
    "min_flow_ml_s": 0.05,
    "max_dose_s": 1200,
}
DEVICES = {
    **DOSER,
    "number.doser_b_volume": "25",
    "button.doser_b_start": "unknown",
    "binary_sensor.doser_b_dosing": "off",
    "switch.doser_b_power": "off",
    "number.doser_b_flow": "11.06",
    "switch.tank_fill": "off",
    "binary_sensor.tank_full": "off",
    "switch.tank_mixer": "off",
    "input_boolean.tank_dosing": "off",
    "input_datetime.tank_filled_at": "2026-10-14 19:00:00",
}


async def _upgraded(hass, hass_storage):
    seed = fixture(JEV_3_11_1)
    store = f"{DOMAIN}.dosing.{seed['entry_id']}"
    data = fixture("dosing_3_11_1.json")["dosing"]
    assert "profile" not in data  # saved before the profile existed
    hass_storage[store] = {"version": 1, "minor_version": 1, "key": store, "data": data}
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    for entity_id, state in DEVICES.items():
        hass.states.async_set(entity_id, state)


async def test_a_3_11_1_store_loads_with_todays_timings(
    hass, hass_storage, hass_admin_user, controller_for
):
    await _upgraded(hass, hass_storage)
    assert hass.states.get(SENSOR).attributes["profile"] == DEFAULTS
    doc = await _call(hass, hass_admin_user, "dosing_get")
    assert doc["error"] is None and doc["config"]["profile"] == DEFAULTS

    c, _fake, _clock = controller_for()
    config = c.dosing._config(c.rooms[0])
    assert dosing_runner._profile(config) == dosing_runner.PROFILE
    assert dosing_runner.PROFILE == {
        "hold_wait_s": dosing_runner.HOLD_WAIT_S,
        "fill_open_s": dosing_runner.FILL_OPEN_S,
        "full_blind_s": dosing_runner.FULL_BLIND_S,
        "mix_power_s": dosing_runner.MIX_POWER_S,
        "min_flow_ml_s": dosing_runner.MIN_FLOW_ML_S,
        "max_dose_s": dosing_runner.MAX_DOSE_S,
    }
    assert dosing_runner.PROFILE == DEFAULTS


async def test_a_saved_profile_reaches_the_controller_and_is_kept(
    hass, hass_storage, hass_admin_user, controller_for, monkeypatch
):
    await _upgraded(hass, hass_storage)
    doc = await _call(hass, hass_admin_user, "dosing_get")
    config = doc["config"]

    refused = await _call(
        hass,
        hass_admin_user,
        "dosing_save",
        expected_revision=config["revision"],
        pumps=config["pumps"],
        batch=config["batch"],
        profile={"max_dose_s": 5},
    )
    assert "longest dose" in refused["error"]
    assert refused["config"]["profile"] == DEFAULTS

    saved = await _call(
        hass,
        hass_admin_user,
        "dosing_save",
        expected_revision=config["revision"],
        pumps=config["pumps"],
        batch=config["batch"],
        profile={"min_flow_ml_s": 20, "fill_open_s": 30},
    )
    profile = {**DEFAULTS, "min_flow_ml_s": 20, "fill_open_s": 30}
    assert saved["error"] is None and saved["config"]["profile"] == profile
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).attributes["profile"] == profile

    again = await _call(  # the dashboard's save sends no profile: the stored one stays
        hass,
        hass_admin_user,
        "dosing_save",
        expected_revision=saved["config"]["revision"],
        pumps=config["pumps"],
        batch=config["batch"],
    )
    assert again["error"] is None and again["config"]["profile"] == profile

    asked = await _call(
        hass, hass_admin_user, "dosing_request", action="dose", pump="part_a", ml=22
    )
    assert asked["error"] is None
    await hass.async_block_till_done()
    c, fake, clock = controller_for()
    _firmware(c, fake, clock, monkeypatch)
    assert c.dosing.recover()
    _run(c.dosing)
    # 11.06 mL/s is below this room's 20 mL/s: nothing is set or pressed.
    assert _commands(fake) == []
    attributes = fake.sets["sensor.crop_steering_dosing"][1]
    assert attributes["handled_result"] == "refused: Part A is not calibrated (flow 11.06)"
