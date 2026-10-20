"""The room's setpoint change log (custom_components/crop_steering/setpoint_log.py), in a real Home
Assistant, on the seeded 3.11.1 install: it updates to an empty log that writes nothing until a
setting moves, and then every writer of a setting is recorded as who it is. The operator is a
signed-in person; the learner, the AI brain and its safety put-back are the real controller's
writes, sent to this Home Assistant exactly as the controller sent them, its event first."""

from datetime import datetime, timezone

from conftest import fixture
from homeassistant.core import Context
from test_upgrade_in_place import JEV_3_11_1, KILL, _upgrade

DOMAIN = "crop_steering"
ROOM = "room:"
THRESHOLD = "number.crop_steering_zone_1_p2_vwc_threshold"
SHOT = "number.crop_steering_zone_1_p2_shot_size"
FC = "number.crop_steering_zone_1_field_capacity"


async def _log(hass):
    return await hass.services.async_call(
        DOMAIN, "setpoint_log_get", {"room_id": ROOM}, blocking=True, return_response=True
    )


def _value(hass, entity_id):
    return float(hass.states.get(entity_id).state)


async def test_a_3_11_1_install_updates_to_an_empty_log_and_writes_nothing(hass, hass_storage):
    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    log = await _log(hass)
    assert (log["room_id"], log["changes"], log["error"]) == (ROOM, [], None)
    assert f"{DOMAIN}.setpoint_log.{seed['entry_id']}" not in hass_storage


async def test_every_writer_is_recorded_as_who_it_is(
    hass, hass_storage, hass_admin_user, controller_for
):
    seed = fixture(JEV_3_11_1)
    entry, _seed = await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    expected = []

    # The operator, signed in; then an automation, which no person is behind.
    for value, context, who in ((41.4, Context(user_id=hass_admin_user.id), "operator"), (42.4, None, "home_assistant")):
        old = _value(hass, THRESHOLD)
        await hass.services.async_call(
            "number", "set_value", {"entity_id": THRESHOLD, "value": value}, blocking=True, context=context
        )
        expected.append((who, "p2_vwc_threshold", 1, old, value))

    # The controller: its learner, its AI brain, and the brain's safety put-back.
    c, fake, _clock = controller_for({"enable_flag": KILL})
    room, now = c.rooms[0], datetime.now(timezone.utc)
    shot = _value(hass, SHOT)
    fake.events.clear()
    fake.calls.clear()  # what the controller did on starting up
    for entity, suffix, value, by, who in (
        (THRESHOLD, "p2_vwc_threshold", 43.4, "auto", "learner"),
        (FC, "field_capacity", 56.5, "auto (highest reading)", "learner"),
        (SHOT, "p2_shot_size", shot + 1, "Jev", "brain"),
        (SHOT, "p2_shot_size", shot, "the AI assistant (put back)", "safety"),
    ):
        old = _value(hass, entity)
        assert c._auto_write(room, 1, suffix, old, value, {}, now, by=by)
        for event, data in fake.events:
            hass.bus.async_fire(event, data)
        await hass.async_block_till_done()
        for domain, service, data in fake.calls:
            await hass.services.async_call(domain, service, data, blocking=True)
        fake.events.clear()
        fake.calls.clear()
        expected.append((who, suffix, 1, old, value))

    log = await _log(hass)
    assert [(r["who"], r["field"], r["zone"], r["old"], r["new"]) for r in log["changes"]] == expected
    assert all(r["entity_id"].startswith("number.crop_steering_zone_1_") and r["at"] for r in log["changes"])

    # Kept: the same rows after the integration is reloaded, read back from the store.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert (await _log(hass))["changes"] == log["changes"]
    assert hass_storage[f"{DOMAIN}.setpoint_log.{seed['entry_id']}"]["data"]["changes"] == log["changes"]
