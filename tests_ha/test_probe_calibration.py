"""Two-point calibration checks of the feed-water probes in a real Home Assistant: recorded through
its service registry and schemas, kept in a store of the room's own across a reload, and an old
install (2.x and 3.x) that never had the store upgrades in place to an empty history."""

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from test_setup_entry import _install
from test_upgrade_in_place import _upgrade

DOMAIN = "crop_steering"
ROOM = "room:"
PH = "sensor.feed_ph"


async def _service(hass, admin, name, **data):
    return await hass.services.async_call(
        DOMAIN,
        name,
        {"room_id": ROOM, **data},
        blocking=True,
        return_response=True,
        context=Context(user_id=admin.id),
    )


async def test_a_check_is_recorded_kept_across_a_reload_and_refused_when_stale(
    hass, hass_admin_user
):
    hass.states.async_set(PH, "6.1", {"unit_of_measurement": "pH"})
    entry = await _install(hass, {"feed_ph_sensor": PH})

    doc = await _service(hass, hass_admin_user, "calibration_get")
    assert (doc["records"], doc["revision"], doc["error"]) == ([], 0, None)
    assert doc["sensors"] == {"feed_ph": PH, "feed_ec": None}

    doc = await _service(
        hass,
        hass_admin_user,
        "calibration_record",
        expected_revision=0,
        probe="feed_ph",
        points=[
            {"reference": 7.0, "reading": 7.05},
            {"reference": 4.0, "reading": 4.1},
        ],
        note="  new buffers ",
    )
    record = doc["records"][0]
    assert doc["revision"] == 1
    assert (record["probe"], record["entity_id"], record["note"]) == (
        "feed_ph",
        PH,
        "new buffers",
    )
    assert (record["slope_pct"], record["offset"], record["verdict"]) == (
        98.3,
        0.05,
        "pass",
    )

    # A second screen still holding revision 0 is refused, not merged.
    with pytest.raises(HomeAssistantError, match="changed elsewhere"):
        await _service(
            hass,
            hass_admin_user,
            "calibration_record",
            expected_revision=0,
            probe="feed_ph",
            points=[
                {"reference": 7.0, "reading": 7.0},
                {"reference": 4.0, "reading": 4.0},
            ],
        )
    # Two references too close together say nothing about the slope.
    with pytest.raises(HomeAssistantError, match="at least 1 apart"):
        await _service(
            hass,
            hass_admin_user,
            "calibration_record",
            expected_revision=1,
            probe="feed_ph",
            points=[
                {"reference": 7.0, "reading": 7.0},
                {"reference": 6.5, "reading": 6.5},
            ],
        )

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    doc = await _service(hass, hass_admin_user, "calibration_get")
    assert doc["revision"] == 1 and doc["records"][0]["id"] == record["id"]
    assert hass.states.get(PH).state == "6.1"  # a check never changes the reading


@pytest.mark.parametrize(
    "seed", ["entry_2_17_wizard.json", "entry_3_11_1_pumped_room.json"]
)
async def test_an_old_install_upgrades_to_an_empty_history(hass, hass_admin_user, seed):
    await _upgrade(hass, seed)
    doc = await _service(hass, hass_admin_user, "calibration_get")
    assert (doc["records"], doc["revision"], doc["error"]) == ([], 0, None)
    assert doc["sensors"] == {"feed_ph": "sensor.feed_ph", "feed_ec": "sensor.feed_ec"}
    doc = await _service(
        hass,
        hass_admin_user,
        "calibration_record",
        expected_revision=0,
        probe="feed_ec",
        points=[
            {"reference": 1.413, "reading": 1.5},
            {"reference": 12.88, "reading": 12.0},
        ],
    )
    assert doc["records"][0]["verdict"] == "drifting"
