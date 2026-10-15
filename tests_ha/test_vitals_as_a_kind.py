"""The vitals report as a kind of push (docs/NOTIFICATIONS.md), in a real Home Assistant: each room's "Include
Predictions in Notifications" switch, on from the start and on an upgraded room, puts what each zone does next
under its line; with phones set up the REAL controller hands the report to the REAL crop_steering.notify as the
`vitals` kind, and only a phone that ticks Vitals gets it; and a 3.11.1 site's saved phone routes load and route
exactly as they did, none of them gaining Vitals."""

from datetime import datetime

from conftest import fixture
from test_notify import LINK, STAFF_PHONE, TABLET, _call, _set_up, _staff
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, _upgrade

DOMAIN = "crop_steering"
SWITCH = "switch.crop_steering_notify_predictions"
OPTION = "notify/mobile_app_old_phone"


def _vitals(fake):
    (message,) = [
        d["message"]
        for dom, svc, d in fake.calls
        if (dom, svc) == ("persistent_notification", "create")
        and d.get("notification_id") == "f2_vitals"
    ]
    return message.splitlines()


async def _lights_around_now(hass):
    """The probe's reading is only fresh on the real clock: put the lights around it, so the zone is
    mid-photoperiod whenever this runs."""
    hour = datetime.now().hour
    for key, value in (("lights_on_hour", (hour - 4) % 24), ("lights_off_hour", (hour + 8) % 24)):
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": f"number.crop_steering_{key}", "value": value},
            blocking=True,
        )


async def test_the_vitals_say_what_comes_next_until_the_room_switches_it_off(hass, controller_for):
    await _install(hass)
    assert hass.states.get(SWITCH).state == "on"
    await _lights_around_now(hass)
    c, fake, _clock = controller_for({})
    c.loop_once(datetime.now())  # the first pass starts the grow-day
    c.rooms[0].state[1]["phase"] = "P2"
    fake.calls.clear()
    c._last_notify = None  # the next vitals are due
    c.loop_once(datetime.now())
    lines = _vitals(fake)
    zone = next(i for i, line in enumerate(lines) if line.startswith("  Z1 P2:"))
    assert lines[zone + 1].startswith("  Next: shot when VWC < ")

    await hass.services.async_call("switch", "turn_off", {"entity_id": SWITCH}, blocking=True)
    # What the controller reads over REST from now on (the fake is the REST view it was built on).
    fake.set_state(SWITCH, hass.states.get(SWITCH).state)
    fake.calls.clear()
    c._last_notify = None
    c.loop_once(datetime.now())
    assert not [line for line in _vitals(fake) if "Next:" in line]


async def test_the_vitals_reach_only_the_phone_that_ticks_vitals_through_the_integration(
    hass, hass_admin_user, controller_for, monkeypatch
):
    await _install(hass)
    staff = await _staff(hass)
    received, doc = await _set_up(hass, hass_admin_user, staff)
    phone, tablet = doc["config"]["recipients"]
    assert "vitals" not in phone["kinds"] + tablet["kinds"]
    await _call(
        hass,
        hass_admin_user,
        "notify_save",
        expected_revision=1,
        recipients=[phone, {**tablet, "kinds": [*tablet["kinds"], "vitals"]}],
    )
    await hass.async_block_till_done()
    c, fake, _clock = controller_for({"notify_service": OPTION})
    import controller

    def answered(domain, service, data, timeout=12):
        fake.calls.append((domain, service, dict(data)))
        return 200, {"sent_to": [TABLET], "error": None}

    monkeypatch.setattr(controller, "ha_service_response", answered)
    c.loop_once(datetime.now())  # the first pass sends the vitals
    message = "\n".join(_vitals(fake))
    (asked,) = [
        d
        for dom, svc, d in fake.calls
        if (dom, svc) == (DOMAIN, "notify") and d.get("event") == "vitals"
    ]
    assert (asked["key"], asked["message"]) == ("vitals", message)
    assert [call for call in fake.calls if call[0] == "notify"] == []  # nothing to the option

    answer = await hass.services.async_call(
        DOMAIN, "notify", asked, blocking=True, return_response=True
    )
    assert answer == {"sent_to": [TABLET], "error": None}
    assert received[TABLET][-1] == {
        "title": asked["title"],
        "message": message,
        "data": {"tag": "vitals", **LINK},
    }
    assert received[STAFF_PHONE] == []


async def test_a_3_11_1_sites_phone_routes_are_unchanged_and_none_gains_vitals(
    hass, hass_admin_user, hass_storage
):
    store = fixture("notify_3_11_1.json")["store"]
    hass_storage[store["key"]] = store
    received = {}
    for service in ("mobile_app_grower_phone", "mobile_app_office_tablet"):
        box = received[f"notify.{service}"] = []

        async def handler(call, box=box):
            box.append(dict(call.data))

        hass.services.async_register("notify", service, handler)
    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])

    # The new switch is on for the upgraded room, as for a new one.
    assert hass.states.get(SWITCH).state == "on"
    doc = await _call(hass, hass_admin_user, "notify_get")
    assert doc["error"] is None and doc["config"] == store["data"]
    assert "vitals" in [kind["id"] for kind in doc["kinds"]]
    sensor = hass.states.get("sensor.crop_steering_notify_config")
    assert (sensor.state, sensor.attributes["recipients"], sensor.attributes["idle_hours"]) == ("3", 2, 2)

    grower, tablet = "notify.mobile_app_grower_phone", "notify.mobile_app_office_tablet"
    for push, phones in (
        ({"code": "CS-301", "room": "", "urgent": True}, [grower, tablet]),
        ({"code": "CS-608", "room": ""}, [tablet]),
        ({"code": "CS-208", "room": ""}, [grower]),
        ({"code": "CS-302", "room": "f1_"}, []),  # the tablet covers the default room only
        ({"event": "phase", "room": ""}, [grower]),
        ({"event": "jev_setpoint", "room": ""}, [grower]),
        ({"event": "vitals"}, []),  # nobody ticks Vitals until someone does
    ):
        answer = await hass.services.async_call(
            DOMAIN,
            "notify",
            {"key": "k", "title": "t", "message": "m", **push},
            blocking=True,
            return_response=True,
        )
        assert answer == {"sent_to": phones, "error": None}, push
    assert hass_storage[store["key"]]["data"] == store["data"]  # nothing was saved over it
