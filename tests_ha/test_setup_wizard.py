"""The setup wizard's live checks (the readiness the setup API reports), in a real Home Assistant with
the real controller.

A room set up from now on is not switched on by the wizard until its safety checks pass: its valves
mapped and reading OFF, its probes reporting in a usable unit, and a test shot the controller ran and a
person saw water from. Sizing still on the generic defaults is a warning, never a block, and nothing
locks the room's engine switch. Saving the wizard's progress never changes the setup revision, so the
controller is never asked for a disarm cycle. A room from before (F-3111) is set up already and never
sees the wizard.
"""

from datetime import datetime

import pytest
from conftest import fixture, room_of
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from test_real_flow import VALVE
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, _upgrade

DOMAIN = "crop_steering"
BUTTON = "button.crop_steering_tent_zone_1_test_shot"
KILL = "switch.crop_steering_tent_engine_enabled"
ARMED = (
    KILL,
    "switch.crop_steering_tent_room_active",
    "switch.crop_steering_tent_system_enabled",
    "switch.crop_steering_tent_auto_irrigation_enabled",
    "switch.crop_steering_tent_zone_1_enabled",
)


async def _service(hass, admin, name, data):
    result = await hass.services.async_call(
        DOMAIN, name, data, blocking=True, return_response=True, context=Context(user_id=admin.id)
    )
    await hass.async_block_till_done()
    return result


async def _room(hass, admin, entry):
    doc = await _service(hass, admin, "setup_read", {})
    assert doc["capabilities"]["commissioning"] is True
    (room,) = [r for r in doc["rooms"] if r["entry_id"] == entry.entry_id]
    return room


def _checks(room):
    return {c["id"]: c for c in room["commissioning"]["checks"]}


async def _commission(hass, admin, room, **data):
    return await _service(
        hass,
        admin,
        "setup_commission",
        {"entry_id": room["entry_id"], "expected_revision": room["revision"], **data},
    )


async def test_a_fresh_room_is_walked_through_its_checks_to_switch_on(
    hass, hass_admin_user, controller_for
):
    entry = await _install(hass)
    room = await _room(hass, hass_admin_user, entry)
    status = room["commissioning"]
    assert status["commissioned"] is False and status["ready"] is False
    checks = _checks(room)
    assert checks["valves"]["ok"] and checks["probes"]["ok"]  # a µS/cm EC probe is a usable unit
    # Sizing on the table's generic defaults warns and never blocks (D18).
    assert not checks["sizing"]["ok"] and checks["sizing"]["blocking"] is False
    assert {c["id"] for c in status["checks"] if c["blocking"]} == {"valves", "probes", "test_shot"}
    assert status["waiting_for"] == "Zone 1: run a test shot"
    with pytest.raises(HomeAssistantError, match="Not ready to switch on: Zone 1: run a test shot"):
        await _commission(hass, hass_admin_user, room, done=True)

    # A valve that is on is named, and so is a probe in a unit that can't be read.
    hass.states.async_set(VALVE, "on")
    hass.states.async_set("sensor.gt1_ec", "1500", {"unit_of_measurement": "ppm"})
    checks = _checks(await _room(hass, hass_admin_user, entry))
    assert any(VALVE in p and "it is ON" in p for p in checks["valves"]["problems"])
    assert checks["probes"]["problems"] == [
        "Zone 1: sensor.gt1_ec reports in 'ppm', which can't be read as EC"
    ]
    hass.states.async_set(VALVE, "off")
    hass.states.async_set("sensor.gt1_ec", "3100", {"unit_of_measurement": "µS/cm"})

    # The test shot, through the real controller. Nothing locks the engine switch: it turns on as
    # ever, with the wizard still open.
    c, fake, _clock = controller_for({"enable_flag": KILL})
    for switch in ARMED:
        await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
        fake.set_state(switch, "on")
    assert hass.states.get(KILL).state == "on"
    c.loop_once(datetime.now())  # the button's state now is where the controller starts from
    await _service(hass, hass_admin_user, "test_shot", {"room_id": "room:tent_", "zone": 1})
    pressed = hass.states.get(BUTTON)
    fake.set_state(BUTTON, pressed.state, dict(pressed.attributes))
    c.loop_once(datetime.now())
    assert room_of(c).state[1]["last_shot"] is not None
    for entity_id in (
        "sensor.crop_steering_tent_zone_1_last_irrigation_app",
        "sensor.crop_steering_tent_ai_heartbeat",
    ):  # what the controller reported, as Home Assistant now has it
        state, attributes = fake.sets[entity_id]
        hass.states.async_set(entity_id, state, attributes)
    room = await _room(hass, hass_admin_user, entry)
    assert _checks(room)["controller"]["ok"]
    assert room["commissioning"]["waiting_for"] == "Zone 1: confirm water reached the drippers"

    # The person saw water: ready, with the sizing warning still showing.
    room = await _commission(hass, hass_admin_user, room, water_seen={"1": pressed.state})
    status = room["commissioning"]
    assert status["ready"] is True and status["waiting_for"] is None
    assert status["draft"]["water_seen"] == {"1": pressed.state}
    assert not _checks(room)["sizing"]["ok"]
    assert room["revision"] == 1  # no disarm cycle: the setup the controller adopted is unchanged

    room = await _commission(hass, hass_admin_user, room, sizing_confirmed=True, done=True)
    assert room["commissioning"]["commissioned"] is True
    assert _checks(room)["sizing"]["ok"]
    assert room["revision"] == 1 and entry.data["setup_revision"] == 1


async def test_a_new_test_shot_needs_seeing_again(hass, hass_admin_user):
    entry = await _install(hass)
    room = await _room(hass, hass_admin_user, entry)
    hass.states.async_set(BUTTON, "2026-10-15T10:00:00+00:00")
    hass.states.async_set(
        "sensor.crop_steering_tent_zone_1_last_irrigation_app", "2026-10-15T10:01:00+00:00"
    )
    room = await _commission(hass, hass_admin_user, room, water_seen={"1": "2026-10-15T10:00:00+00:00"})
    assert room["commissioning"]["ready"] is True
    hass.states.async_set(BUTTON, "2026-10-15T11:00:00+00:00")  # pressed again
    room = await _room(hass, hass_admin_user, entry)
    assert room["commissioning"]["waiting_for"] == (
        "Zone 1: the controller has not reported the test shot yet"
    )


async def test_a_3_11_1_room_is_set_up_already_and_never_sees_the_wizard(hass, hass_admin_user):
    seed = fixture(JEV_3_11_1)
    entry, _seed = await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    assert "commissioning" not in entry.data
    room = await _room(hass, hass_admin_user, entry)
    assert room["commissioning"]["commissioned"] is True
    with pytest.raises(HomeAssistantError, match="already set up"):
        await _commission(hass, hass_admin_user, room, done=True)
    assert "commissioning" not in entry.data
