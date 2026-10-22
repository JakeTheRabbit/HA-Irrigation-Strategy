"""The feed pH calibration wizard (G2) in a real Home Assistant: a commit is applied as the room's
corrected sensor and engine_config `feed_calibration` and reads back; the corrected sensor restores its
last value after a restart; an idle session ends on Home Assistant's timer; and an upgraded install
keeps its old checks without a Repairs card (R6)."""

from datetime import timedelta

import pytest
from conftest import fixture
from homeassistant.core import Context, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers import restore_state
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from test_setup_entry import _install
from test_upgrade_in_place import _upgrade

DOMAIN = "crop_steering"
ROOM = "room:tent_"
PH, TEMP = "sensor.feed_ph", "sensor.tank_temp"
CORRECTED = "sensor.crop_steering_tent_feed_ph_corrected"
DESCRIPTOR = "sensor.crop_steering_tent_engine_config"
DOSING = "sensor.crop_steering_tent_dosing_config"


async def _service(hass, admin, name, **data):
    return await hass.services.async_call(
        DOMAIN,
        name,
        data,
        blocking=True,
        return_response=True,
        context=Context(user_id=admin.id),
    )


def _later(manager, seconds):
    """The wizard's clock `seconds` ahead of Home Assistant's: the probe has held still that long."""
    manager._now = lambda: dt_util.utcnow() + timedelta(seconds=seconds)


async def _calibrate(hass, admin, entry):
    manager = hass.data[DOMAIN]["_calibration"][entry.entry_id]
    hass.states.async_set(PH, "7.12", {"unit_of_measurement": "pH"})
    _later(manager, 60)
    started = await _service(
        hass, admin, "calibration_start", room_id=ROOM, probe="feed_ph"
    )
    assert started["raw_entity_id"] == PH and started["temperature_entity_id"] == TEMP
    assert started["dosing_paused"] is True
    await hass.async_block_till_done()
    assert (
        hass.states.get(DOSING).attributes["calibrating"]["session_id"]
        == started["session_id"]
    )
    session = started["session_id"]
    _later(manager, 120)
    point = await _service(
        hass, admin, "calibration_capture", session_id=session, point=0
    )
    assert point["stable"] is True and point["raw"] == 7.12
    await hass.async_block_till_done()
    # A capture moves the session on, and the dosing hold with it.
    until = hass.states.get(DOSING).attributes["calibrating"]["until"]
    assert until > started["expires_at"]
    hass.states.async_set(PH, "4.12", {"unit_of_measurement": "pH"})
    await hass.async_block_till_done()
    _later(manager, 0)
    status = await _service(hass, admin, "calibration_status", session_id=session)
    assert (status["stable"], status["points_captured"]) == (False, 1)
    _later(manager, 45)
    point = await _service(
        hass, admin, "calibration_capture", session_id=session, point=1
    )
    assert point["stable"] is True
    return await _service(hass, admin, "calibration_commit", session_id=session)


async def test_commit_publishes_corrected_sensor_and_reads_back(hass, hass_admin_user):
    hass.states.async_set(TEMP, "21.3", {"unit_of_measurement": "°C"})
    hass.states.async_set(PH, "6.1", {"unit_of_measurement": "pH"})
    entry = await _install(
        hass, {"feed_ph_sensor": PH, "tank_temperature_sensor": TEMP}
    )
    assert hass.states.get(CORRECTED).state == "unknown"
    assert hass.states.get(CORRECTED).attributes["applied"] is False
    assert "feed_calibration" not in hass.states.get(DESCRIPTOR).attributes

    out = await _calibrate(hass, hass_admin_user, entry)
    await hass.async_block_till_done()
    assert (out["verdict"], out["applied"]) == ("drifting", True)
    corrected = hass.states.get(CORRECTED)
    assert float(corrected.state) == 4.0  # 4.12 raw in the pH 4.00 buffer
    assert corrected.attributes["source"] == PH
    assert corrected.attributes["slope_pct"] == 100.0
    calibration = hass.states.get(DESCRIPTOR).attributes["feed_calibration"]
    assert set(calibration) == {"ph"} and calibration["ph"]["gain"] == 1.0
    assert "calibrating" not in hass.states.get(DOSING).attributes
    assert hass.states.get(PH).state == "4.12"  # the raw sensor is never touched

    hass.states.async_set(PH, "6.12", {"unit_of_measurement": "pH"})
    await hass.async_block_till_done()
    assert float(hass.states.get(CORRECTED).state) == 6.0

    reverted = await _service(
        hass, hass_admin_user, "calibration_revert", room_id=ROOM, probe="feed_ph"
    )
    await hass.async_block_till_done()
    assert reverted["applied"] is False
    assert hass.states.get(CORRECTED).state == "unknown"
    assert "feed_calibration" not in hass.states.get(DESCRIPTOR).attributes


async def test_corrected_sensor_restores_after_restart(hass, hass_admin_user):
    hass.states.async_set(TEMP, "21.3", {"unit_of_measurement": "°C"})
    hass.states.async_set(PH, "6.1", {"unit_of_measurement": "pH"})
    entry = await _install(
        hass, {"feed_ph_sensor": PH, "tank_temperature_sensor": TEMP}
    )
    await _calibrate(hass, hass_admin_user, entry)
    await hass.async_block_till_done()
    assert float(hass.states.get(CORRECTED).state) == 4.0

    # Restart: the room comes back before the probe has reported. Home Assistant saved the corrected
    # sensor's last state at shutdown (an unload writes it while the room is coming apart, so it is put
    # in place here as the restore cache holds it after a restart).
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    hass.states.async_remove(PH)
    restore_state.async_get(hass).last_states[CORRECTED] = restore_state.StoredState(
        State(CORRECTED, "4.0"), None, dt_util.utcnow()
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert float(hass.states.get(CORRECTED).state) == 4.0
    assert hass.states.get(CORRECTED).attributes["applied"] is True
    assert hass.states.get(CORRECTED).attributes["restored"] is True

    # A probe that has not come back after 2 min is not hidden behind the old value.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=121))
    await hass.async_block_till_done()
    assert hass.states.get(CORRECTED).state == "unknown"

    # The probe's first report: its own reading, corrected.
    hass.states.async_set(PH, "5.12", {"unit_of_measurement": "pH"})
    await hass.async_block_till_done()
    assert float(hass.states.get(CORRECTED).state) == 5.0
    assert "restored" not in hass.states.get(CORRECTED).attributes


async def test_upgrade_keeps_old_calibration_records_without_a_repairs_card(
    hass, hass_storage, hass_admin_user
):
    seed = fixture("entry_3_11_1_pumped_room.json")
    old = {
        "id": "old",
        "probe": "feed_ph",
        "kind": "ph",
        "entity_id": "sensor.feed_ph",
        "at": (dt_util.utcnow() - timedelta(days=400)).isoformat(),
        "points": [
            {"reference": 7.0, "reading": 7.0},
            {"reference": 4.0, "reading": 4.0},
        ],
        "slope_pct": 100.0,
        "offset": 0.0,
        "verdict": "pass",
        "note": "",
    }
    key = f"{DOMAIN}.calibration.{seed['entry_id']}"
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {"revision": 1, "records": [old]},
    }
    await _upgrade(hass, "entry_3_11_1_pumped_room.json")
    doc = await _service(hass, hass_admin_user, "calibration_get", room_id="room:")
    assert doc["records"] == [old] and doc["error"] is None
    assert hass.states.get("binary_sensor.crop_steering_calibration_due").state == "off"
    assert ir.async_get(hass).async_get_issue(DOMAIN, "calibration_due") is None
    assert hass.states.get("sensor.crop_steering_feed_ph_corrected").state == "unknown"
    assert "feed_calibration" not in (
        hass.states.get("sensor.crop_steering_engine_config").attributes
    )


async def test_an_idle_session_ends_and_dosing_carries_on(hass, hass_admin_user):
    hass.states.async_set(PH, "7.0", {"unit_of_measurement": "pH"})
    entry = await _install(hass, {"feed_ph_sensor": PH})
    manager = hass.data[DOMAIN]["_calibration"][entry.entry_id]
    started = await _service(
        hass, hass_admin_user, "calibration_start", room_id=ROOM, probe="feed_ph"
    )
    await hass.async_block_till_done()
    assert "calibrating" in hass.states.get(DOSING).attributes
    _later(manager, 31 * 60)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=31))
    await hass.async_block_till_done()
    assert "calibrating" not in hass.states.get(DOSING).attributes
    with pytest.raises(HomeAssistantError, match="Calibration session expired"):
        await _service(
            hass,
            hass_admin_user,
            "calibration_status",
            session_id=started["session_id"],
        )
    # The due flag is published hourly, from Home Assistant's own clock.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=1, minutes=1))
    await hass.async_block_till_done()
    assert (
        hass.states.get("binary_sensor.crop_steering_tent_calibration_due").state
        == "off"
    )
