"""A real signed-in Home Assistant user who is not an administrator can look, but not change.

The sidebar console is open to every login and calls the room services with that login; the stub
suite (tests/test_admin_only.py) has the reason and the whole matrix. Here every call goes through
Home Assistant's own service registry, schema validation and auth store, as an ordinary member of
the Users group, which is what a staff phone or the hallway kiosk signs in as; and through a real
automation that such a person sets off, which must still run.
"""

import pytest
from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.components import frontend
from homeassistant.core import Context, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockUser
from test_setup_entry import _install

DOMAIN = "crop_steering"
ROOM = "room:"
OVERRIDE = "switch.crop_steering_zone_1_manual_override"
PLAN = "sensor.crop_steering_strategy_plan"
REFUSED = "requires an authenticated Home Assistant administrator"
# Every service that changes something, with data its schema accepts: what refuses it must be the
# administrator check, not validation.
CHANGES = {
    "strategy_save": {"room_id": ROOM, "expected_revision": 0, "plan": {}},
    "strategy_activate": {"room_id": ROOM, "expected_revision": 0},
    "strategy_disarm": {"room_id": ROOM},
    "runs_save": {"room_id": ROOM, "expected_revision": 0, "record": {}},
    "runs_archive": {"room_id": ROOM, "expected_revision": 0, "id": "r", "archived": True},
    "runs_import": {"room_id": ROOM, "expected_revision": 0, "runs": []},
    "stock_save": {"room_id": ROOM, "expected_revision": 0, "tanks": []},
    "stock_refill": {"room_id": ROOM, "expected_revision": 0, "id": "bloom"},
    "stock_record_batch": {"room_id": ROOM, "expected_revision": 0},
    "save_recipe": {"recipe": {}},
    "apply_recipe": {},
    "set_manual_override": {"zone": 1},
    "setup_read": {},
    "setup_create": {},
    "setup_save": {},
    "setup_remove": {},
}
READS = {
    "strategy_get": {"room_id": ROOM},
    "strategy_preview": {"room_id": ROOM},
    "runs_get": {"room_id": ROOM},
    "stock_get": {"room_id": ROOM},
}
EVENTS = ("crop_steering_manual_override",)


async def _staff(hass):
    users = await hass.auth.async_get_group(GROUP_ID_USER)
    return MockUser(name="Staff phone", groups=[users]).add_to_hass(hass)


async def _call(hass, user, name, data):
    responds = hass.services.supports_response(DOMAIN, name) is not SupportsResponse.NONE
    return await hass.services.async_call(
        DOMAIN,
        name,
        dict(data),
        blocking=True,
        return_response=responds,
        context=Context(user_id=user.id if user else None),
    )


async def test_an_ordinary_user_can_look_and_changes_nothing(hass):
    await _install(hass)
    staff = await _staff(hass)
    assert not staff.is_admin
    assert hass.data[frontend.DATA_PANELS]["crop-steering"].require_admin is False  # still shown
    # Every service the integration registers is one or the other: nothing new slips through.
    assert set(hass.services.async_services()[DOMAIN]) == set(CHANGES) | set(READS)
    fired = []
    for event in EVENTS:
        hass.bus.async_listen(event, fired.append)
    plan = dict(hass.states.get(PLAN).attributes)

    for name, data in CHANGES.items():
        with pytest.raises(HomeAssistantError, match=REFUSED):
            await _call(hass, staff, name, data)
    await hass.async_block_till_done()
    assert hass.states.get(OVERRIDE).state == "off"
    assert dict(hass.states.get(PLAN).attributes) == plan  # not saved, armed or disarmed
    assert not fired

    assert (await _call(hass, staff, "strategy_get", READS["strategy_get"]))["status"] == "draft"
    for name, data in READS.items():
        try:
            await _call(hass, staff, name, data)
        except HomeAssistantError as err:  # e.g. a fresh room's seeded plan may not preview
            assert REFUSED not in str(err), name


@pytest.mark.parametrize("who", ["administrator", "no user"])
async def test_an_administrator_or_a_call_with_no_user_still_changes_it(
    hass, hass_admin_user, who
):
    await _install(hass)
    user = hass_admin_user if who == "administrator" else None
    await _call(hass, user, "set_manual_override", {"zone": 1})
    assert hass.states.get(OVERRIDE).state == "on"
    assert hass.states.get(PLAN).attributes["release_legacy"] is False
    await _call(hass, user, "strategy_disarm", {"room_id": ROOM})
    assert hass.states.get(PLAN).attributes["release_legacy"] is True


async def test_an_automation_an_ordinary_user_sets_off_still_runs(hass):
    """Home Assistant runs an automation with no user of its own, whoever set it off."""
    await _install(hass)
    staff = await _staff(hass)
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "triggers": [{"trigger": "event", "event_type": "hold_zone_1"}],
                "actions": [
                    {"action": f"{DOMAIN}.set_manual_override", "data": {"zone": 1}}
                ],
            }
        },
    )
    with pytest.raises(HomeAssistantError, match=REFUSED):
        await _call(hass, staff, "set_manual_override", {"zone": 1})
    assert hass.states.get(OVERRIDE).state == "off"

    hass.bus.async_fire("hold_zone_1", context=Context(user_id=staff.id))
    await hass.async_block_till_done()
    assert hass.states.get(OVERRIDE).state == "on"
