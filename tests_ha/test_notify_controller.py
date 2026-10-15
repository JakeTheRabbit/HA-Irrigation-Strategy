"""The controller app hands its pushes to the integration (docs/NOTIFICATIONS.md), across the real seam: the REAL
controller reads the REAL sensor.crop_steering_notify_config, and what it asks crop_steering.notify for is taken
by the REAL service, whose phones get it with its tag and its priority. The two layers meet only through that
sensor and that call, and each has tests against its own idea of the other."""

from test_notify import LINK, STAFF_PHONE, TABLET, URGENT, _call, _set_up, _staff
from test_setup_entry import _install

DOMAIN = "crop_steering"


def _asked(fake):
    """What the controller asked crop_steering.notify for, as it goes over REST."""
    return [data for domain, service, data in fake.calls if (domain, service) == (DOMAIN, "notify")]


async def test_the_controllers_pushes_reach_the_phones_through_the_integration(
    hass, hass_admin_user, controller_for, monkeypatch
):
    await _install(hass)
    staff = await _staff(hass)
    received, doc = await _set_up(hass, hass_admin_user, staff)
    phone, tablet = doc["config"]["recipients"]
    await _call(  # the staff phone ticks phase changes too, and it is two hours without watering
        hass,
        hass_admin_user,
        "notify_save",
        expected_revision=1,
        recipients=[{**phone, "kinds": ["stock", "phases"]}, tablet],
        idle_hours=2,
    )
    await hass.async_block_till_done()
    c, fake, _clock = controller_for({"notify_service": "notify/mobile_app_old_phone"})
    assert c._notify_config() == (2, 2.0)
    import controller

    # Over REST the controller is answered what the real service answers when the same request is
    # replayed below (each asserted there): an emergency that reached no phone would go to the option.
    answers = {
        "hw_default_z1": {"sent_to": [TABLET], "error": None},
        "phase_default_z1": {"sent_to": [STAFF_PHONE], "error": None},
    }

    def answered(domain, service, data, timeout=12):
        fake.calls.append((domain, service, dict(data)))
        return 200, answers[data["key"]]

    monkeypatch.setattr(controller, "ha_service_response", answered)

    room = c.rooms[0]
    assert c._alert(
        "hw_default_z1",
        "CS-301",
        "CRITICAL hardware fault, watering stopped",
        "The valve did not close.",
        room=room,
        zone=1,
    )
    c._notify_event("phase", room, 1, "P1", "P2", "P1 recovered 42>=40 EC ok 2.5")
    c._send_events()
    alert, phase = _asked(fake)
    assert [call for call in fake.calls if call[0] == "notify"] == []  # nothing to the option
    assert (alert["code"], alert["urgent"], alert["room"], alert["zone"]) == (
        "CS-301",
        True,
        "",
        1,
    )

    answer = await hass.services.async_call(
        DOMAIN, "notify", alert, blocking=True, return_response=True
    )
    assert answer == {"sent_to": [TABLET], "error": None}
    assert received[TABLET][-1]["message"].startswith("The valve did not close.")
    assert received[TABLET][-1]["data"] == {"tag": "hw_default_z1", **LINK, **URGENT}

    answer = await hass.services.async_call(
        DOMAIN, "notify", phase, blocking=True, return_response=True
    )
    assert answer == {"sent_to": [STAFF_PHONE], "error": None}
    assert received[STAFF_PHONE][-1] == {
        "title": phase["title"],
        "message": "P1 recovered 42>=40 EC ok 2.5",
        "data": {"tag": "phase_default_z1", **LINK},
    }
    assert phase["title"].endswith(": P1 → P2")


async def test_with_nobody_set_up_the_controller_pushes_to_its_option_as_before(
    hass, controller_for
):
    await _install(hass)
    c, fake, _clock = controller_for({"notify_service": "notify/mobile_app_old_phone"})
    assert c._notify_config() == (0, 3.0)  # the real sensor: nobody set up
    assert c._alert("k", "CS-102", "moisture sensor not reporting", "m", room=c.rooms[0], zone=1)
    c._notify_event("phase", c.rooms[0], 1, "P1", "P2", "why")
    c._send_events()
    assert _asked(fake) == []
    assert [(dom, svc) for dom, svc, _d in fake.calls if dom == "notify"] == [
        ("notify", "mobile_app_old_phone")
    ]


async def test_jevs_own_alerts_reach_the_phone_that_ticks_jev(
    hass, hass_admin_user, controller_for, monkeypatch
):
    """CS-706 (most of the day's calls used) and CS-707 (a zone on the stricter gate) are in the
    jev kind: the phone that ticks Jev gets both, the tablet that ticks only emergencies and
    hardware gets neither."""
    await _install(hass)
    staff = await _staff(hass)
    received, doc = await _set_up(hass, hass_admin_user, staff)
    phone, tablet = doc["config"]["recipients"]
    await _call(
        hass,
        hass_admin_user,
        "notify_save",
        expected_revision=1,
        recipients=[{**phone, "kinds": ["jev"]}, tablet],
    )
    await hass.async_block_till_done()
    c, fake, _clock = controller_for({"notify_service": "notify/mobile_app_old_phone"})
    import controller

    def answered(domain, service, data, timeout=12):
        fake.calls.append((domain, service, dict(data)))
        return 200, {"sent_to": [STAFF_PHONE], "error": None}

    monkeypatch.setattr(controller, "ha_service_response", answered)
    room = c.rooms[0]
    c._jev_alert(
        room,
        1,
        "ramp",
        {"code": "CS-707", "title": "Jev is on the stricter gate", "message": "Bad run."},
    )
    c._jev_alert(
        room,
        None,
        "budget",
        {"code": "CS-706", "title": "Jev has used most of today's calls", "message": "4000."},
    )
    strict, budget = _asked(fake)
    assert (strict["code"], strict["key"], budget["code"], budget["key"]) == (
        "CS-707",
        "jev_ramp_default_z1",
        "CS-706",
        "jev_budget_default",
    )
    for asked, words in ((strict, "Bad run."), (budget, "4000.")):
        answer = await hass.services.async_call(
            DOMAIN, "notify", asked, blocking=True, return_response=True
        )
        assert answer == {"sent_to": [STAFF_PHONE], "error": None}
        assert received[STAFF_PHONE][-1]["message"].startswith(words)
