"""The alerts inbox in a real Home Assistant: sensor.crop_steering_<prefix>alerts_open follows the
journal's alert events and the live persistent notifications, and alert_ack acknowledges one, by any
signed-in user, through Home Assistant's own services, bus, clock and notifications.
"""

from datetime import timedelta

import pytest
from homeassistant.components import persistent_notification
from homeassistant.core import Context, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from test_non_admin_user import _staff
from test_setup_entry import _install
from test_upgrade_in_place import _upgrade

DOMAIN = "crop_steering"
ROOM = "room:tent_"
INBOX = "sensor.crop_steering_tent_alerts_open"
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


async def _tick(hass, freezer, seconds):
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    # The 5-min republish runs as a background task.
    await hass.async_block_till_done(wait_background_tasks=True)


async def _firing_rule(hass, admin, freezer) -> tuple[str, str]:
    hass.states.async_set(LEVEL, "12", {"unit_of_measurement": "%"})
    saved = await _call(hass, admin, "alert_rule_set", expected_revision=0, rule=RULE)
    await hass.async_block_till_done()
    rule_id = saved["rule"]["id"]
    await _tick(hass, freezer, 60)
    await _tick(hass, freezer, 61)
    await hass.async_block_till_done()
    return rule_id, f"binary_sensor.crop_steering_rule_{rule_id.lower()}"


async def test_a_fresh_room_has_no_open_alerts(hass):
    await _install(hass)
    await hass.async_block_till_done()
    state = hass.states.get(INBOX)
    assert state.state == "0" and state.attributes["alerts"] == []
    assert hass.services.supports_response(DOMAIN, "alert_ack") is SupportsResponse.OPTIONAL


async def test_old_install_loads_with_no_open_alerts(hass, caplog):
    entry, _ = await _upgrade(hass, "entry_3_11_1_pumped_room.json")
    await hass.async_block_till_done()
    from custom_components.crop_steering.room import room_prefix

    state = hass.states.get(f"sensor.crop_steering_{room_prefix(entry)}alerts_open")
    assert state.state == "0" and state.attributes["alerts"] == []
    assert not [r for r in caplog.records if r.levelname in ("ERROR", "CRITICAL")]


async def test_a_staff_ack_closes_a_rule_alert_and_its_sensor_stays_on(
    hass, hass_admin_user, freezer
):
    await _install(hass)
    rule_id, binary = await _firing_rule(hass, hass_admin_user, freezer)
    assert hass.states.get(binary).state == "on"
    state = hass.states.get(INBOX)
    assert state.state == "1"
    (alert,) = state.attributes["alerts"]
    assert alert["rule_id"] == rule_id and alert["entity_id"] == LEVEL
    assert alert["title"].endswith("tank level below 30%") and alert["acknowledged"] is False

    staff = await _staff(hass)
    answer = await _call(
        hass, staff, "alert_ack", room_id=ROOM, alert_event_id=alert["event_id"]
    )
    await hass.async_block_till_done()
    assert answer["alert_event_id"] == alert["event_id"] and answer["event_id"]
    assert hass.states.get(INBOX).state == "0"
    sensor = hass.states.get(binary)
    assert sensor.state == "on" and sensor.attributes["state"] == "acknowledged"
    (acked,) = (
        await _call(
            hass,
            None,
            "journal_query",
            room_id=ROOM,
            since="2000-01-01T00:00:00+00:00",
            kinds=["alert.acknowledged"],
        )
    )["events"]
    assert acked["id"] == answer["event_id"]
    assert acked["source"]["actor"] == "manual" and acked["source"]["user_id"] == staff.id
    assert acked["data"] == {"alert_event_id": alert["event_id"], "rule_id": rule_id}

    # Still breaching: acknowledged stays on; back in range it clears and turns off.
    await _tick(hass, freezer, 60)
    assert hass.states.get(binary).state == "on"
    hass.states.async_set(LEVEL, "45", {"unit_of_measurement": "%"})
    await hass.async_block_till_done()
    assert hass.states.get(binary).state == "off"

    # Already closed, or never there: refused, in v1 and in the v2 envelope.
    with pytest.raises(HomeAssistantError, match="already closed"):
        await _call(hass, staff, "alert_ack", room_id=ROOM, alert_event_id=alert["event_id"])
    out = await _call(
        hass, staff, "alert_ack", room_id=ROOM, alert_event_id="01JAAAAAAAAAAAAAAAAAAAAAAA", api=2
    )
    assert out["ok"] is False and out["error"]["code"] == "invalid"
    assert out["error"]["message"].startswith("No alert")


async def test_a_controller_alert_closes_when_its_notification_is_gone(
    hass, hass_admin_user, freezer
):
    """Until Task 8 the controller journals no alerts; this one is appended as it will be."""
    await _install(hass)
    persistent_notification.async_create(hass, "Probe stale", "Zone 2", "f2_stale_z2")
    raised = {
        "v": 1,
        "id": "01JBBBBBBBBBBBBBBBBBBBBBBB",
        "ts": "2026-10-22T07:00:00+00:00",
        "kind": "alert.raised",
        "zone": 2,
        "outcome": "ok",
        "code": "CS-101",
        "source": {"actor": "engine"},
        "data": {"key": "stale_z2", "title": "Zone 2 probe stale"},
    }
    await _call(hass, hass_admin_user, "journal_append", room_id=ROOM, events=[raised])
    await hass.async_block_till_done()
    (alert,) = hass.states.get(INBOX).attributes["alerts"]
    assert (alert["event_id"], alert["code"], alert["zone"]) == (raised["id"], "CS-101", 2)
    assert alert["entity_id"] is None and "rule_id" not in alert

    persistent_notification.async_dismiss(hass, "f2_stale_z2")
    await _tick(hass, freezer, 5 * 60 + 1)
    assert hass.states.get(INBOX).state == "0"


async def test_the_last_room_unloading_takes_the_inbox_away(hass):
    entry = await _install(hass)
    await hass.async_block_till_done()
    assert hass.states.get(INBOX) is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(INBOX) is None
    assert "_alerts_inbox" not in hass.data.get(DOMAIN, {})
    hass.bus.async_fire("crop_steering_event", {"room_id": ROOM, "kind": "alert.raised"})
    await hass.async_block_till_done()
    assert hass.states.get(INBOX) is None
