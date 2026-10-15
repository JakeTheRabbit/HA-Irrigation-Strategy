"""The exact dose record and the recipe's name, on an upgraded install in a real Home Assistant.

The 3.11.1 room's own dosing store (F-3111), saved before recipes had a name, loads with none and
keeps its batch; a name saved through the real dosing_save service reaches the controller through
sensor.crop_steering_dosing_config; and a dose the REAL controller app runs is recorded with what it
gave (docs/DOSING.md, Exact dose record).
"""

from conftest import fixture
from test_dosing import _call
from test_dosing_in_main_loop import _dose_asked
from test_dosing_units_and_actuators import DOSER, _firmware
from test_upgrade_in_place import JEV_3_11_1, _upgrade

DOMAIN = "crop_steering"
CONFIG = "sensor.crop_steering_dosing_config"


async def test_a_3_11_1_store_loads_with_no_name_and_takes_one(
    hass, hass_storage, hass_admin_user
):
    seed = fixture(JEV_3_11_1)
    old = fixture("dosing_3_11_1.json")["dosing"]
    store = f"{DOMAIN}.dosing.{seed['entry_id']}"
    hass_storage[store] = {"version": 1, "minor_version": 1, "key": store, "data": old}
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    entities = [
        value
        for item in (*old["pumps"], old["batch"])
        for key, value in item.items()
        if key.endswith(("_entity", "_valve", "_pump")) and value
    ]
    for entity_id in entities:  # the room's devices, back after the update
        state = "25" if entity_id.startswith("number.") else "off"
        hass.states.async_set(entity_id, state)
    for entity_id, state in DOSER.items():
        hass.states.async_set(entity_id, state)
    batch = hass.states.get(CONFIG).attributes["batch"]
    assert batch["name"] == "" and batch["recipe"] == old["batch"]["recipe"]

    saved = await _call(
        hass,
        hass_admin_user,
        "dosing_save",
        expected_revision=old["revision"],
        pumps=old["pumps"],
        batch={**old["batch"], "name": "Week 3"},
    )
    assert saved["error"] is None
    await hass.async_block_till_done()
    assert hass.states.get(CONFIG).attributes["batch"]["name"] == "Week 3"


async def test_the_controller_records_what_a_dose_gave(
    hass, hass_storage, hass_admin_user, controller_for, monkeypatch
):
    import controller

    await _dose_asked(hass, hass_storage, hass_admin_user)
    c, fake, clock = controller_for()
    _firmware(c, fake, clock, monkeypatch)
    monkeypatch.setattr(controller.time, "sleep", c.dosing._sleep)
    c._start_dosing()
    c._sleep_for(60)
    attributes = fake.sets["sensor.crop_steering_dosing"][1]
    [dosed] = attributes["history"][0]["dosed"]
    assert dosed == {
        "pump": "part_a",
        "name": "Part A",
        "ml": 22,
        "given": 22,
        "result": "finished",
        "at": attributes["history"][0]["at"],
    }
    assert attributes["pumps"]["part_a"]["last"]["given"] == 22
    assert attributes["last_batch"] is None  # no batch has run in this room yet
