"""Who gets which alerts, in a real Home Assistant (docs/NOTIFICATIONS.md): the four services through its
registry, schemas and auth store; sensor.crop_steering_notify_config, which the controller app reads, under
that exact id; the phones Home Assistant has and whose they are; a real ordinary user who can tick only their
own phone; a push reaching a mobile_app-like notify service with its tag and its high priority; the site's one
store kept while rooms come and go; the low-stock Repairs card on the phone that ticks stock; and an install
from before any of this that loads with nobody set up."""

import pytest
from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.core import Context, SupportsResponse
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import slugify
from pytest_homeassistant_custom_component.common import MockConfigEntry, MockUser
from test_setup_entry import _install
from test_upgrade_in_place import _upgrade

DOMAIN = "crop_steering"
SENSOR = "sensor.crop_steering_notify_config"
STORE = "crop_steering.notify"
REFUSED = "requires an authenticated Home Assistant administrator"
STAFF_PHONE = "notify.mobile_app_staff_phone"
TABLET = "notify.mobile_app_office_tablet"
# Tapping a push opens the Crop Steering panel (iOS reads url, Android clickAction).
LINK = {"url": "/crop-steering", "clickAction": "/crop-steering"}
URGENT = {
    "priority": "high",
    "channel": "Crop Steering urgent",
    "push": {"interruption-level": "time-sensitive"},
}


async def _staff(hass):
    users = await hass.auth.async_get_group(GROUP_ID_USER)
    return MockUser(name="Staff", groups=[users]).add_to_hass(hass)


def _phones(hass, owners):
    """A phone for each (device name, user), registered the way mobile_app registers one: its notify service
    notify.mobile_app_<device> and a mobile_app config entry naming the user whose app it is. -> what each
    phone's service was sent."""
    received = {}
    for device, user in owners:
        MockConfigEntry(
            domain="mobile_app",
            title=device,
            data={"device_name": device, "user_id": user.id, "app_id": "test.app"},
        ).add_to_hass(hass)
        box = received[f"notify.mobile_app_{slugify(device)}"] = []

        async def handler(call, box=box):
            box.append(dict(call.data))

        hass.services.async_register("notify", f"mobile_app_{slugify(device)}", handler)
    return received


async def _call(hass, user, name, **data):
    return await hass.services.async_call(
        DOMAIN,
        name,
        data,
        blocking=True,
        return_response=True,
        context=Context(user_id=getattr(user, "id", user)),
    )


async def _set_up(hass, admin, staff):
    """Two phones: the staff member's ticks stock tanks, the administrator's tablet emergencies and hardware."""
    received = _phones(hass, [("Staff phone", staff), ("Office tablet", admin)])
    doc = await _call(
        hass,
        admin,
        "notify_save",
        expected_revision=0,
        recipients=[
            {"service": STAFF_PHONE, "kinds": ["stock"], "urgent_high_priority": False},
            {"service": TABLET, "kinds": ["emergency", "hardware"]},
        ],
    )
    assert doc["error"] is None
    await hass.async_block_till_done()
    return received, doc


async def test_the_services_and_the_sensor_the_controller_reads(hass, hass_admin_user):
    await _install(hass)
    for name in ("notify_get", "notify_save", "notify_test"):
        assert hass.services.supports_response(DOMAIN, name) is SupportsResponse.ONLY
    # The controller app asks for the answer; a script may send one without.
    assert hass.services.supports_response(DOMAIN, "notify") is SupportsResponse.OPTIONAL
    state = hass.states.get(SENSOR)
    assert state.state == "0"
    assert (state.attributes["recipients"], state.attributes["idle_hours"]) == (0, 3)

    staff = await _staff(hass)
    _phones(hass, [("Staff phone", staff), ("Office tablet", hass_admin_user)])
    doc = await _call(hass, hass_admin_user, "notify_get")
    assert (doc["schema_version"], doc["error"], doc["can_edit_all"]) == (1, None, True)
    assert doc["user_id"] == hass_admin_user.id
    assert [kind["id"] for kind in doc["kinds"]][:2] == ["emergency", "hardware"]
    assert doc["phones"] == [
        {
            "service": TABLET,
            "name": "Office tablet",
            "user_id": hass_admin_user.id,
            "user_name": hass_admin_user.name,
        },
        {
            "service": STAFF_PHONE,
            "name": "Staff phone",
            "user_id": staff.id,
            "user_name": "Staff",
        },
    ]
    doc = await _call(
        hass,
        hass_admin_user,
        "notify_save",
        expected_revision=0,
        recipients=[{"service": STAFF_PHONE, "kinds": ["stock", "emergency"]}],
        idle_hours=4,
    )
    assert doc["error"] is None and doc["config"]["revision"] == 1
    assert doc["config"]["recipients"][0] == {
        "service": STAFF_PHONE,
        "name": "Staff phone",
        "user_id": staff.id,
        "kinds": ["emergency", "stock"],
        "rooms": [],
        "urgent_high_priority": True,
    }
    await hass.async_block_till_done()
    state = hass.states.get(SENSOR)
    assert state.state == "1"
    assert (state.attributes["recipients"], state.attributes["idle_hours"]) == (1, 4)
    stale = await _call(
        hass, hass_admin_user, "notify_save", expected_revision=0, recipients=[]
    )
    assert stale["error"] == "revision" and stale["config"]["revision"] == 1


async def test_a_real_ordinary_user_ticks_only_their_own_phone(hass, hass_admin_user):
    await _install(hass)
    staff = await _staff(hass)
    assert not staff.is_admin
    received, doc = await _set_up(hass, hass_admin_user, staff)
    mine, theirs = doc["config"]["recipients"]

    doc = await _call(hass, staff, "notify_get")
    assert (doc["can_edit_all"], doc["user_id"]) == (False, staff.id)
    answer = await _call(
        hass,
        staff,
        "notify_save",
        expected_revision=1,
        recipients=[{**mine, "kinds": ["stock", "dosing"], "rooms": [""]}, theirs],
    )
    assert answer["error"] is None and answer["config"]["revision"] == 2
    assert answer["config"]["recipients"][0]["kinds"] == ["stock", "dosing"]
    for recipients in (
        [mine, {**theirs, "kinds": []}],  # someone else's phone
        [mine],  # a phone taken off the list
        [{**mine, "name": "Mine"}, theirs],  # renamed
    ):
        refused = await _call(
            hass, staff, "notify_save", expected_revision=2, recipients=recipients
        )
        assert refused["error"].startswith("not allowed: ")
        assert refused["config"]["revision"] == 2
    # A push to the phones is for the controller app and administrators only.
    with pytest.raises(HomeAssistantError, match=REFUSED):
        await _call(hass, staff, "notify", key="k", title="T", message="M")
    # A test of their own phone, never of someone else's.
    assert await _call(hass, staff, "notify_test", service=STAFF_PHONE) == {
        "sent": True,
        "error": None,
    }
    assert received[STAFF_PHONE][-1]["title"] == "Crop Steering: a test"
    assert received[STAFF_PHONE][-1]["message"] == "This phone gets: Stock tanks, Dosing."
    refused = await _call(hass, staff, "notify_test", service=TABLET)
    assert refused["sent"] is False and refused["error"].startswith("not allowed: ")
    assert received[TABLET] == []
    # A user id Home Assistant does not know may neither save nor test.
    for name, data in (
        ("notify_save", {"expected_revision": 2, "recipients": []}),
        ("notify_test", {"service": STAFF_PHONE}),
    ):
        with pytest.raises(HomeAssistantError, match="signed-in Home Assistant user"):
            await _call(hass, "0" * 32, name, **data)


async def test_a_push_reaches_the_phones_that_ask_for_it_with_its_tag_and_priority(
    hass, hass_admin_user
):
    await _install(hass)
    staff = await _staff(hass)
    received, _doc = await _set_up(hass, hass_admin_user, staff)

    # As the controller app sends a pump fault: an administrator's call (here, no user), asking for the answer.
    answer = await _call(
        hass,
        None,
        "notify",
        key="hw_default_z1",
        code="CS-301",
        room="",
        zone=1,
        title="Zone 1: CRITICAL hardware fault, watering stopped (CS-301)",
        message="The valve did not close.",
        urgent=True,
    )
    assert answer == {"sent_to": [TABLET], "error": None}
    assert received[TABLET] == [
        {
            "title": "Zone 1: CRITICAL hardware fault, watering stopped (CS-301)",
            "message": "The valve did not close.",
            "data": {"tag": "hw_default_z1", **LINK, **URGENT},
        }
    ]
    assert received[STAFF_PHONE] == []
    answer = await _call(
        hass, None, "notify", key="dosing_x", code="CS-807", title="T", message="M"
    )
    assert answer == {"sent_to": [STAFF_PHONE], "error": None}
    assert received[STAFF_PHONE][-1]["data"] == {"tag": "dosing_x", **LINK}
    # A phase change: nobody here ticks phases, so nobody gets it, and that is no failure.
    answer = await _call(
        hass, None, "notify", key="phase_default_z1", event="phase", title="T", message="M"
    )
    assert answer == {"sent_to": [], "error": None}
    # Sent by a script without asking for the answer: taken all the same.
    await hass.services.async_call(
        DOMAIN,
        "notify",
        {"key": "k", "code": "CS-608", "title": "T", "message": "M"},
        blocking=True,
    )
    assert len(received[STAFF_PHONE]) == 2

    # A phone that fails never stops the others, and the answer names it.
    async def broken(call):
        raise HomeAssistantError("device not connected")

    hass.services.async_register("notify", "mobile_app_broken_phone", broken)
    doc = await _call(hass, hass_admin_user, "notify_get")
    await _call(
        hass,
        hass_admin_user,
        "notify_save",
        expected_revision=doc["config"]["revision"],
        recipients=[
            *doc["config"]["recipients"],
            {"service": "notify.mobile_app_broken_phone", "kinds": ["stock"]},
        ],
    )
    answer = await _call(
        hass, None, "notify", key="k2", code="CS-608", title="T", message="M"
    )
    assert answer["sent_to"] == [STAFF_PHONE]
    assert answer["error"] == "notify.mobile_app_broken_phone: device not connected"


async def test_the_site_keeps_one_setup_while_rooms_come_and_go(
    hass, hass_admin_user, hass_storage
):
    first = await _install(hass)
    staff = await _staff(hass)
    await _set_up(hass, hass_admin_user, staff)
    # A second room, set up as test_whats_new adds one: it joins the site's setup.
    hass.states.async_set("switch.veg_tent", "off")
    hass.states.async_set("sensor.veg_vwc", "50", {"unit_of_measurement": "%"})
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"room_name": "Veg tent"}
    )
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"num_zones": 1}
    )
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        {
            "zone_1_switch": "switch.veg_tent",
            "zone_1_vwc": ["sensor.veg_vwc"],
            "zone_1_plant_count": 2,
        },
    )
    done = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"plumbing": "valves_only"}
    )
    assert done["type"] is FlowResultType.CREATE_ENTRY
    second = done["result"]
    await hass.async_block_till_done()
    assert (await _call(hass, hass_admin_user, "notify_get"))["config"]["revision"] == 1

    # The room that set it up goes: the other still has it, and the controller still reads it.
    assert await hass.config_entries.async_remove(first.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).state == "1"
    doc = await _call(hass, hass_admin_user, "notify_get")
    assert len(doc["config"]["recipients"]) == 2
    assert await hass.config_entries.async_reload(second.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).attributes["recipients"] == 2
    assert hass_storage[STORE]["data"]["revision"] == 1

    # With the last room, the setup's services and sensor go too; the store stays for the next start.
    assert await hass.config_entries.async_unload(second.entry_id)
    await hass.async_block_till_done()
    assert not hass.services.has_service(DOMAIN, "notify")
    assert hass.states.get(SENSOR) is None
    assert hass_storage[STORE]["data"]["revision"] == 1


async def test_the_low_stock_card_reaches_the_phone_that_ticks_stock_once(
    hass, hass_admin_user
):
    await _install(hass)
    staff = await _staff(hass)
    received, _doc = await _set_up(hass, hass_admin_user, staff)
    stock = await hass.services.async_call(
        DOMAIN,
        "stock_get",
        {"room_id": "room:"},
        blocking=True,
        return_response=True,
    )
    await hass.services.async_call(
        DOMAIN,
        "stock_save",
        {
            "room_id": "room:",
            "expected_revision": stock["revision"],
            "tanks": [
                {"name": "Bloom", "capacity_l": 10, "level_l": 1, "low_l": 2, "dose_ml": 500}
            ],
        },
        blocking=True,
        return_response=True,
        context=Context(user_id=hass_admin_user.id),
    )
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, "stock_low") is not None
    push = received[STAFF_PHONE][-1]
    assert push["title"] == "Tent: 1 stock tank(s) running low (CS-608)"
    assert "- Bloom: 1 L of 10 L" in push["message"]
    assert push["message"].endswith(
        "Code CS-608. What it means and what to do: Crop Steering → Help & tools → Error codes."
    )
    assert push["data"] == {"tag": "stock_low", **LINK}
    assert received[TABLET] == []  # not an emergency

    # Still raised, with new numbers: the card changes, the phone is not pushed again.
    stock = await hass.services.async_call(
        DOMAIN, "stock_get", {"room_id": "room:"}, blocking=True, return_response=True
    )
    await hass.services.async_call(
        DOMAIN,
        "stock_record_batch",
        {"room_id": "room:", "expected_revision": stock["revision"]},
        blocking=True,
        return_response=True,
        context=Context(user_id=hass_admin_user.id),
    )
    await hass.async_block_till_done()
    assert len(received[STAFF_PHONE]) == 1


async def test_an_install_from_before_notifications_loads_with_nobody_set_up(hass):
    """UPGRADE IN PLACE: a 2.17 room has no notification store and no notify_config sensor."""
    await _upgrade(hass, "entry_2_17_wizard.json")
    state = hass.states.get(SENSOR)
    assert state is not None and state.state == "0"
    assert state.attributes["recipients"] == 0
    doc = await _call(hass, None, "notify_get")  # an automation: it reads, and may not edit all
    assert doc["error"] is None and doc["config"]["recipients"] == []
    assert doc["can_edit_all"] is False
    # The controller app, calling anyway, is told nobody is set up: it pushes to its own option.
    answer = await _call(hass, None, "notify", key="k", code="CS-301", title="T", message="M")
    assert answer == {"sent_to": [], "error": "no phone is set up for notifications"}
