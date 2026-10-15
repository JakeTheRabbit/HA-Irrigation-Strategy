"""The batch tank's refill reminder (docs/DOSING.md, Refill reminder; CS-906) on an upgraded install in a
real Home Assistant.

The 3.11.1 room's own dosing store (F-3111) loads with the reminder off, and sensor.crop_steering_dosing_config
says so to the controller app. A reminder saved through the real dosing_save service is kept by a later
save from a page that does not send it, and the REAL controller app reads it from that sensor: a low tank
is told (CS-906) on the third read a minute apart, and the notification is dismissed once it is refilled.
"""

import re
from datetime import datetime, timedelta, timezone

from conftest import fixture
from test_dosing import _call as _dosing_call
from test_upgrade_in_place import JEV_3_11_1, _upgrade


async def _call(hass, user, name, **data):
    """test_dosing's call, for this file's upgraded room: it keeps its un-prefixed ids (room:)."""
    return await _dosing_call(hass, user, name, **{"room_id": "room:", **data})


DOMAIN = "crop_steering"
SENSOR = "sensor.crop_steering_dosing_config"
LEVEL = "sensor.tank_level"
NOTE = "f2_dosing_default_906_remind"
BASE = datetime(2026, 10, 15, 1, 0, tzinfo=timezone.utc)


async def _a_3_11_1_room(hass, hass_storage):
    seed = fixture(JEV_3_11_1)
    dosing = fixture("dosing_3_11_1.json")["dosing"]
    store = f"{DOMAIN}.dosing.{seed['entry_id']}"
    hass_storage[store] = {"version": 1, "minor_version": 1, "key": store, "data": dosing}
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    for entity_id in set(re.findall(r"\b[a-z_]+\.[a-z0-9_]+\b", str(dosing))):
        if entity_id.split(".")[0] in ("switch", "binary_sensor", "sensor", "number", "button",
                                       "input_boolean", "input_datetime", "input_number"):
            if hass.states.get(entity_id) is None:
                hass.states.async_set(entity_id, "off")
    return dosing


async def test_a_3_11_1_store_loads_with_the_reminder_off_and_a_page_save_keeps_one_set(
    hass, hass_storage, hass_admin_user
):
    dosing = await _a_3_11_1_room(hass, hass_storage)
    batch = hass.states.get(SENSOR).attributes["batch"]
    assert (batch["level_entity"], batch["remind_pct"]) == (None, 0)
    hass.states.async_set(LEVEL, "40", {"unit_of_measurement": "%"})
    revision = int(hass.states.get(SENSOR).state)
    saved = await _call(
        hass, hass_admin_user, "dosing_save", expected_revision=revision, pumps=dosing["pumps"],
        batch={**dosing["batch"], "level_entity": LEVEL, "remind_pct": 20},
    )
    assert saved["error"] is None
    page = await _call(  # the dosing page as it is: it sends the batch it knows, without the reminder
        hass, hass_admin_user, "dosing_save", expected_revision=revision + 1, pumps=dosing["pumps"],
        batch=dosing["batch"],
    )
    assert page["error"] is None and page["config"]["revision"] == revision + 2
    await hass.async_block_till_done()
    batch = hass.states.get(SENSOR).attributes["batch"]
    assert (batch["level_entity"], batch["remind_pct"]) == (LEVEL, 20)
    assert batch["recipe"] == dosing["batch"]["recipe"]


async def test_the_real_controller_reminds_from_what_the_integration_publishes(
    hass, hass_storage, hass_admin_user, controller_for
):
    dosing = await _a_3_11_1_room(hass, hass_storage)
    hass.states.async_set(LEVEL, "15", {"unit_of_measurement": "%"})
    saved = await _call(
        hass, hass_admin_user, "dosing_save", expected_revision=int(hass.states.get(SENSOR).state),
        pumps=dosing["pumps"], batch={**dosing["batch"], "level_entity": LEVEL, "remind_pct": 20},
    )
    assert saved["error"] is None
    await hass.async_block_till_done()

    c, fake, clock = controller_for()
    c.dosing._mono = clock.monotonic
    c.dosing._now = lambda: BASE + timedelta(seconds=clock.seconds)

    def reads(count):
        for _ in range(count):
            c.dosing.poll()
            clock.sleep(60)

    def notes(service):
        return [data for domain, svc, data in fake.calls
                if (domain, svc) == ("persistent_notification", service) and data["notification_id"] == NOTE]

    reads(2)
    assert notes("create") == []
    reads(1)
    (note,) = notes("create")
    assert note["title"].endswith("batch tank at 15%, refill it (CS-906)")
    reads(30)
    assert len(notes("create")) == 1 and notes("dismiss") == []
    fake.set_state(LEVEL, "95", {"unit_of_measurement": "%"})  # refilled
    reads(1)
    assert len(notes("dismiss")) == 1
    commands = [(d, s) for d, s, _data in fake.calls if d not in ("persistent_notification", DOMAIN)]
    assert ("switch", "turn_on") not in commands  # a reminder moves nothing
