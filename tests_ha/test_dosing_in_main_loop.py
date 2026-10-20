"""Dosing as steps of the controller's main loop, on an upgraded install in a real Home Assistant.

The 3.11.1 room's own dosing store (F-3111) is dosed by the REAL controller app's own loop driver
(Controller._sleep_for), with no second thread, and with exactly the calls 3.11.1 sent. A stop signal
in the middle of a dose switches the pump off inside the stop budget and leaves its record in
dosing_state.json, which the next start reads back off and reports (CS-803).
"""

import json
import os
import threading
from pathlib import Path

import pytest

from conftest import fixture
from test_dosing import _call as _dosing_call
from test_dosing_units_and_actuators import DOSER, _commands, _firmware
from test_upgrade_in_place import JEV_3_11_1, _upgrade


async def _call(hass, user, name, **data):
    """test_dosing's call, for this file's upgraded room: it keeps its un-prefixed ids (room:)."""
    return await _dosing_call(hass, user, name, **{"room_id": "room:", **data})


DOMAIN = "crop_steering"


async def _dose_asked(hass, hass_storage, hass_admin_user):
    seed = fixture(JEV_3_11_1)
    store = f"{DOMAIN}.dosing.{seed['entry_id']}"
    hass_storage[store] = {
        "version": 1,
        "minor_version": 1,
        "key": store,
        "data": fixture("dosing_3_11_1.json")["dosing"],
    }
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    for entity_id, state in DOSER.items():
        hass.states.async_set(entity_id, state)
    asked = await _call(
        hass, hass_admin_user, "dosing_request", action="dose", pump="part_a", ml=22
    )
    assert asked["error"] is None
    await hass.async_block_till_done()


async def test_the_main_loop_doses_a_3_11_1_store_with_no_second_thread(
    hass, hass_storage, hass_admin_user, controller_for, monkeypatch
):
    import controller

    await _dose_asked(hass, hass_storage, hass_admin_user)
    c, fake, clock = controller_for()
    _firmware(c, fake, clock, monkeypatch)
    monkeypatch.setattr(controller.time, "sleep", c.dosing._sleep)  # the firmware runs on the loop's sleep
    threads = threading.active_count()
    c._start_dosing()
    c._sleep_for(60)  # the wait between two passes: dosing's steps run inside it
    assert threading.active_count() == threads
    assert _commands(fake) == [
        ["number", "set_value", {"entity_id": "number.doser_a_volume", "value": 22}],
        ["button", "press", {"entity_id": "button.doser_a_start"}],
        ["number", "set_value", {"entity_id": "number.doser_a_volume", "value": 25.0}],
    ]
    attributes = fake.sets["sensor.crop_steering_dosing"][1]
    assert attributes["handled_result"] == "finished"


async def test_a_mid_dose_stop_switches_the_pump_off_and_the_next_start_reports_it(
    hass, hass_storage, hass_admin_user, controller_for, monkeypatch
):
    import controller
    import runtime_env

    await _dose_asked(hass, hass_storage, hass_admin_user)
    c, fake, clock = controller_for()
    _firmware(c, fake, clock, monkeypatch)
    c.dosing._sleep = clock.sleep  # this firmware never stops the motor
    monkeypatch.setattr(controller.time, "sleep", clock.sleep)
    c._start_dosing()
    c._sleep_for(5)
    assert fake.states["binary_sensor.doser_a_dosing"][0] == "on"  # mid-dose
    began = clock.seconds
    with pytest.raises(SystemExit):
        c._safe_exit()
    assert clock.seconds - began < runtime_env.stop_budget(os.environ)
    assert ["switch", "turn_off", {"entity_id": "switch.doser_a_power"}] in _commands(fake)
    path = Path(c.dosing.path)
    assert json.loads(path.read_text(encoding="utf-8"))["rooms"]["default"]["inflight"]["kind"] == "dose"

    again, fake, clock = controller_for()  # the app started again, on the same /data
    assert again.dosing.path == str(path)
    again._start_dosing()
    again._sleep_for(10)
    titles = [
        data["title"]
        for domain, service, data in fake.calls
        if (domain, service) == ("persistent_notification", "create")
    ]
    assert any(title.endswith("(CS-803)") for title in titles)
    assert again.dosing.holds(again.rooms[0]) is None  # it reads off: released
