"""Pump prime and calibration (G3) in a real Home Assistant: the pump services through its registry,
schemas and auth store; a 30 s run that gave 150 mL calibrates the pump to 300 mL/min, writes its flow
number in mL/s and reads it back, and publishes the pump's two sensors; a prime is capped at 30 s by the
schema; and an ordinary user may check and stop a pump but never prime or calibrate one."""

import pytest
from homeassistant.core import Context, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import voluptuous as vol
from test_dosing import BATCH, DEVICES, PUMP, REFUSED, _staff
from test_setup_entry import _install

DOMAIN = "crop_steering"
ROOM = "room:tent_"
STATUS = "sensor.crop_steering_tent_dosing"
CONFIG = "sensor.crop_steering_tent_dosing_config"
HEARTBEAT = "sensor.crop_steering_tent_ai_heartbeat"
FLOW = "input_number.doser_balance_flow"
ML_MIN = "sensor.crop_steering_tent_dosing_pump_balance_ml_min"
LAST = "sensor.crop_steering_tent_dosing_pump_balance_last_calibrated"


async def _call(hass, user, name, **data):
    return await hass.services.async_call(
        DOMAIN,
        name,
        {"room_id": ROOM, **data},
        blocking=True,
        return_response=True,
        context=Context(user_id=user.id if user else None),
    )


async def _room(hass, admin):
    await _install(hass)
    assert await async_setup_component(
        hass,
        "input_number",
        {
            "input_number": {
                "doser_balance_flow": {
                    "min": 0,
                    "max": 100,
                    "step": 0.001,
                    "initial": 11.06,
                }
            }
        },
    )
    for entity_id, state in DEVICES.items():
        if not entity_id.startswith("number.doser_balance_flow"):
            hass.states.async_set(entity_id, state)
    hass.states.async_set(HEARTBEAT, "ok")
    saved = await _call(
        hass,
        admin,
        "dosing_save",
        expected_revision=0,
        pumps=[{**PUMP, "flow_entity": FLOW}],
        batch=BATCH,
    )
    assert saved["error"] is None
    await hass.async_block_till_done()


async def test_a_30_s_run_of_150_ml_calibrates_the_pump_to_300_ml_min(
    hass, hass_admin_user
):
    await _room(hass, hass_admin_user)
    assert hass.services.supports_response(DOMAIN, "pump_precheck") is (
        SupportsResponse.ONLY
    )
    for name in (
        "pump_prime",
        "pump_stop",
        "pump_calibrate",
        "pump_calibration_commit",
    ):
        assert (
            hass.services.supports_response(DOMAIN, name) is SupportsResponse.OPTIONAL
        )
    assert await _call(hass, hass_admin_user, "pump_precheck", pump="balance") == {
        "ok": True,
        "blockers": [],
    }
    doc = await _call(hass, hass_admin_user, "dosing_get")
    assert doc["catalog"]["hea_h4"]["nominal_ml_min"]["10"] == 1360

    started = await _call(
        hass, hass_admin_user, "pump_calibrate", pump="balance", seconds=30
    )
    assert started["outcome"] == "requested"
    await hass.async_block_till_done()
    request = hass.states.get(CONFIG).attributes["request"]
    assert (request["action"], request["pump"], request["seconds"]) == (
        "calibrate",
        "balance",
        30,
    )
    # The open pump calibration holds the room's dosing: the controller reads it from the descriptor.
    held = hass.states.get(CONFIG).attributes["calibrating"]
    assert (held["pump"], held["session_id"]) == ("balance", started["session_id"])
    with pytest.raises(HomeAssistantError, match="not been reported"):
        await _call(
            hass,
            hass_admin_user,
            "pump_calibration_commit",
            session_id=started["session_id"],
            measured_ml=150,
        )
    # The controller reports the run (Task 20's handled_result); the listener copies its seconds.
    hass.states.async_set(
        STATUS,
        "idle",
        {
            "handled": request["id"],
            "handled_result": {
                "id": request["id"],
                "action": "calibrate",
                "pump": "balance",
                "ran_s": 30,
                "result": "done",
            },
        },
    )
    await hass.async_block_till_done()
    doc = await _call(hass, hass_admin_user, "dosing_get")
    assert doc["config"]["pumps"][0]["calibration_session"]["ran_s"] == 30
    # A batch waits while the jug is read.
    batch = await _call(hass, hass_admin_user, "dosing_request", action="batch")
    assert batch["request"] is None and "calibrated or primed" in batch["error"]

    out = await _call(
        hass,
        hass_admin_user,
        "pump_calibration_commit",
        session_id=started["session_id"],
        measured_ml=150,
    )
    assert out == {"ml_min": 300, "previous_ml_min": None, "flow_entity_written": True}
    await hass.async_block_till_done()
    assert float(hass.states.get(FLOW).state) == 5.0  # 300 mL/min = 5 mL/s, read back
    assert hass.states.get(ML_MIN).state == "300"
    assert hass.states.get(ML_MIN).attributes["unit_of_measurement"] == "mL/min"
    assert dt_util.parse_datetime(hass.states.get(LAST).state) is not None
    pump = hass.states.get(CONFIG).attributes["pumps"][0]
    assert pump["calibrated_ml_min"] == 300 and len(pump["calibrations"]) == 1
    assert "calibrating" not in hass.states.get(CONFIG).attributes


async def test_a_prime_is_capped_at_30_s_and_only_an_administrator_primes(
    hass, hass_admin_user
):
    await _room(hass, hass_admin_user)
    with pytest.raises((vol.Invalid, HomeAssistantError)):
        await _call(hass, hass_admin_user, "pump_prime", pump="balance", seconds=31)
    staff = await _staff(hass)
    for name, data in (
        ("pump_prime", {"seconds": 10}),
        ("pump_calibrate", {"seconds": 30}),
    ):
        with pytest.raises(HomeAssistantError, match=REFUSED):
            await _call(hass, staff, name, pump="balance", **data)
    # A mix pump left on is named, and nothing is stored.
    hass.states.async_set(BATCH["mix_pump"], "on")
    refused = await _call(
        hass, hass_admin_user, "pump_prime", pump="balance", seconds=10
    )
    assert refused["outcome"] == "refused"
    assert refused["blockers"] == [{"code": "mix_pump_on", "message": "Mix pump is on"}]
    assert (await _call(hass, staff, "pump_precheck", pump="balance"))["ok"] is False
    await hass.async_block_till_done()
    assert hass.states.get(CONFIG).attributes["request"] is None
    hass.states.async_set(BATCH["mix_pump"], "off")
    prime = await _call(hass, hass_admin_user, "pump_prime", pump="balance", seconds=30)
    assert prime["outcome"] == "requested"
    await hass.async_block_till_done()
    # A prime holds the room's dosing too, for its run and 60 s.
    held = hass.states.get(CONFIG).attributes["calibrating"]
    assert (held["pump"], held["request_id"]) == ("balance", prime["request_id"])
    # Anyone signed in may stop it: the stop replaces the waiting prime.
    stop = await _call(hass, staff, "pump_stop", pump="balance")
    await hass.async_block_till_done()
    request = hass.states.get(CONFIG).attributes["request"]
    assert request["id"] == stop["request_id"]
    assert (request["action"], request["pump"], request["by"]) == (
        "stop_pump",
        "balance",
        "Staff phone",
    )


async def test_calibration_abandon_releases_a_pump_calibration_hold(
    hass, hass_admin_user
):
    await _room(hass, hass_admin_user)
    started = await _call(
        hass, hass_admin_user, "pump_calibrate", pump="balance", seconds=30
    )
    request = hass.states.get(CONFIG).attributes["request"]
    hass.states.async_set(
        STATUS,
        "idle",
        {
            "handled": request["id"],
            "handled_result": {"id": request["id"], "ran_s": 30, "result": "done"},
        },
    )
    await hass.async_block_till_done()
    assert "calibrating" in hass.states.get(CONFIG).attributes
    out = await hass.services.async_call(
        DOMAIN,
        "calibration_abandon",
        {"session_id": started["session_id"]},
        blocking=True,
        return_response=True,
        context=Context(user_id=hass_admin_user.id),
    )
    assert out == {"abandoned": True}
    await hass.async_block_till_done()
    assert "calibrating" not in hass.states.get(CONFIG).attributes
    batch = await _call(hass, hass_admin_user, "dosing_request", action="batch")
    assert batch["error"] is None
