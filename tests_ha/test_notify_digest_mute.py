"""A phone that takes a digest and a muted room, in a real Home Assistant (docs/NOTIFICATIONS.md): a notification
setup saved by 3.11.1 (tests_ha/fixtures/notify_3_11_1_staff.json) loads in place with no digest and nothing muted;
the services save both; a push for a muted room goes to nobody but an emergency; a digest phone's pushes wait and
arrive as one on Home Assistant's own clock; and the REAL controller reads the mute from the REAL sensor."""

import json
from datetime import timedelta
from pathlib import Path

from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from test_notify import STAFF_PHONE, STORE, TABLET, _call, _phones, _staff
from test_setup_entry import _install

DOMAIN = "crop_steering"
SENSOR = "sensor.crop_steering_notify_config"
FIXTURE = Path(__file__).parent / "fixtures" / "notify_3_11_1_staff.json"


async def _set_up(hass, hass_admin_user):
    received = _phones(hass, [("Staff phone", await _staff(hass)), ("Office tablet", hass_admin_user)])
    await _install(hass)
    return received


async def test_a_setup_saved_by_3_11_1_loads_in_place_with_no_digest_and_nothing_muted(
    hass, hass_admin_user, hass_storage
):
    """UPGRADE IN PLACE: the 3.11.1 store has no digest, no digest_hours and no mutes."""
    hass_storage[STORE] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    received = await _set_up(hass, hass_admin_user)
    doc = await _call(hass, hass_admin_user, "notify_get")
    assert doc["error"] is None
    config = doc["config"]
    assert (config["revision"], config["idle_hours"]) == (6, 2)
    assert [r["digest"] for r in config["recipients"]] == [False, False]
    assert (config["digest_hours"], config["mutes"]) == (4, {})
    state = hass.states.get(SENSOR)
    assert state.state == "6" and "muted" not in state.attributes
    # Pushes go as they did.
    answer = await _call(hass, None, "notify", key="k", code="CS-102", room="", title="T", message="M")
    assert answer == {"sent_to": [STAFF_PHONE], "error": None}
    assert len(received[STAFF_PHONE]) == 1
    # A save from a page that knows nothing of either changes neither, and the store is the same shape plus them.
    page = [{k: v for k, v in r.items() if k != "digest"} for r in config["recipients"]]
    doc = await _call(hass, hass_admin_user, "notify_save", expected_revision=6, recipients=page)
    assert doc["error"] is None and doc["config"]["digest_hours"] == 4
    await hass.async_block_till_done()
    assert hass_storage[STORE]["data"]["revision"] == 7
    assert hass_storage[STORE]["data"]["mutes"] == {}


async def test_a_muted_room_and_a_digest_phone(hass, hass_admin_user):
    received = await _set_up(hass, hass_admin_user)
    until = (dt_util.utcnow() + timedelta(hours=3)).replace(microsecond=0)
    doc = await _call(
        hass,
        hass_admin_user,
        "notify_save",
        expected_revision=0,
        recipients=[
            {"service": STAFF_PHONE, "kinds": ["sensors", "watering", "emergency"], "digest": True},
            {"service": TABLET, "kinds": ["emergency"]},
        ],
        digest_hours=2,
        mutes={"f1_": until.isoformat()},
    )
    assert doc["error"] is None
    assert doc["config"]["mutes"] == {"f1_": until.isoformat()}
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).attributes["muted"] == {"f1_": until.isoformat()}

    # The muted room: to nobody, on purpose, unless it is an emergency.
    answer = await _call(hass, None, "notify", key="m", code="CS-102", room="f1_", title="T", message="M")
    assert answer == {"sent_to": [], "error": None, "muted": True}
    answer = await _call(
        hass, None, "notify", key="e", code="CS-301", room="f1_", urgent=True, title="F1: fault", message="M"
    )
    assert sorted(answer["sent_to"]) == [TABLET, STAFF_PHONE]

    # The digest phone: what is not an emergency waits for one push two hours after the first it holds.
    notifier = hass.data[DOMAIN]["_notify"]
    clock = {"s": 1000.0}
    notifier._clock = lambda: clock["s"]
    for key, code, title in (("a", "CS-102", "Zone 1: probe"), ("b", "CS-205", "Zone 1: daily limit")):
        answer = await _call(hass, None, "notify", key=key, code=code, room="", title=title, message="M")
        assert answer == {"sent_to": [], "error": None, "held": [STAFF_PHONE]}
    before = len(received[STAFF_PHONE])
    clock["s"] += 2 * 3600
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=2))
    await hass.async_block_till_done()
    digest = received[STAFF_PHONE][before:]
    assert len(digest) == 1
    assert digest[0]["title"] == "Crop Steering: 2 pushes held"
    assert digest[0]["message"] == (
        "Warnings\n• Zone 1: probe\n\nFor your information\n• Zone 1: daily limit"
    )
    assert digest[0]["data"]["tag"] == "crop_steering_digest"


async def test_the_controller_reads_the_mute_from_the_real_sensor(hass, hass_admin_user, controller_for):
    await _set_up(hass, hass_admin_user)
    until = dt_util.utcnow() + timedelta(hours=1)
    doc = await _call(
        hass, hass_admin_user, "notify_save", expected_revision=0, recipients=[], mutes={"": until.isoformat()}
    )
    assert doc["error"] is None
    await hass.async_block_till_done()
    c, fake, _clock = controller_for({"notify_service": "notify/mobile_app_old_phone"})
    room = c.rooms[0]
    assert room.prefix == ""
    assert c._alert("k", "CS-102", "moisture sensor not reporting", "m", room=room, zone=1)
    assert [call for call in fake.calls if call[0] == "notify"] == []  # muted: not even to the option
    assert c._alert("hw", "CS-301", "hardware fault", "m", room=room, zone=1)
    assert [(dom, svc) for dom, svc, _d in fake.calls if dom == "notify"] == [("notify", "mobile_app_old_phone")]
