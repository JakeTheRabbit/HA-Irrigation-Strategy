"""A moisture probe's offset (G9) in a real Home Assistant: matching a handheld meter shows in the
zone's reading and in sensor.<probe>_corrected at once, survives a restart, and reads back from the
store; a preview changes nothing; a curve on a probe that already reads percent is refused."""

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from test_setup_entry import _install

DOMAIN = "crop_steering"
ROOM = "room:tent_"
PROBE = "sensor.gt1_vwc"
CORRECTED = "sensor.gt1_vwc_corrected"
ZONE = "sensor.crop_steering_tent_vwc_zone_1"


async def _service(hass, admin, name, **data):
    return await hass.services.async_call(
        DOMAIN,
        name,
        data,
        blocking=True,
        return_response=True,
        context=Context(user_id=admin.id),
    )


async def test_offset_survives_restart_and_reads_back(hass, hass_admin_user):
    entry = await _install(hass)
    hass.states.async_set(PROBE, "41", {"unit_of_measurement": "%"})
    await hass.async_block_till_done()
    assert hass.states.get(CORRECTED) is None  # no offset, no corrected sensor
    document = await _service(hass, hass_admin_user, "calibration_get", room_id=ROOM)
    assert document["probe_user_offsets"] == {}

    preview = await _service(
        hass,
        hass_admin_user,
        "probe_offset_set",
        room_id=ROOM,
        entity_id=PROBE,
        match_handheld=44.0,
        preview=True,
    )
    assert (preview["offset"], preview["corrected_now"]) == (3.0, 44.0)
    await hass.async_block_till_done()
    assert hass.states.get(CORRECTED) is None
    document = await _service(hass, hass_admin_user, "calibration_get", room_id=ROOM)
    assert document["probe_user_offsets"] == {}
    revision = document["revision"]

    out = await _service(
        hass,
        hass_admin_user,
        "probe_offset_set",
        room_id=ROOM,
        entity_id=PROBE,
        match_handheld=44.0,
        expected_revision=revision,
    )
    await hass.async_block_till_done()
    assert (out["offset"], out["corrected_now"], out["revision"]) == (
        3.0,
        44.0,
        revision + 1,
    )
    assert float(hass.states.get(CORRECTED).state) == 44.0
    assert hass.states.get(PROBE).state == "41"  # the raw probe is never touched
    assert float(hass.states.get(ZONE).state) == 44.0

    document = await _service(hass, hass_admin_user, "calibration_get", room_id=ROOM)
    assert document["probe_user_offsets"][PROBE]["offset"] == 3.0
    assert document["revision"] == revision + 1

    # Restart: the store is read again and the offset applies from the first reading.
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(CORRECTED) is None
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    hass.states.async_set(PROBE, "42", {"unit_of_measurement": "%"})
    await hass.async_block_till_done()
    assert float(hass.states.get(CORRECTED).state) == 45.0
    document = await _service(hass, hass_admin_user, "calibration_get", room_id=ROOM)
    assert document["probe_user_offsets"][PROBE]["offset"] == 3.0

    # Taking the offset off removes the corrected sensor.
    await _service(
        hass,
        hass_admin_user,
        "probe_offset_set",
        room_id=ROOM,
        entity_id=PROBE,
        offset=0,
        expected_revision=document["revision"],
    )
    await hass.async_block_till_done()
    assert hass.states.get(CORRECTED) is None


async def test_a_curve_on_a_percent_probe_is_refused(hass, hass_admin_user):
    await _install(hass)
    document = await _service(hass, hass_admin_user, "calibration_get", room_id=ROOM)
    with pytest.raises(HomeAssistantError, match="already converts to moisture"):
        await _service(
            hass,
            hass_admin_user,
            "probe_offset_set",
            room_id=ROOM,
            entity_id=PROBE,
            curve="rockwool",
            expected_revision=document["revision"],
        )
    assert hass.states.get(CORRECTED) is None
