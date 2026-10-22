"""A real signed-in Home Assistant user who is not an administrator can look, but not change; the
exceptions are stopping a room's dosing and Stop all, which only switch things off.

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
ROOM = "room:tent_"
OVERRIDE = "switch.crop_steering_tent_zone_1_manual_override"
PLAN = "sensor.crop_steering_tent_strategy_plan"
REFUSED = "requires an authenticated Home Assistant administrator"
# Every service that changes something, with data its schema accepts: what refuses it must be the
# administrator check, not validation.
CHANGES = {
    "runs_set_harvest": {"room_id": ROOM, "expected_revision": 0, "run_id": "r", "harvest": None},
    "strategy_save": {"room_id": ROOM, "expected_revision": 0, "plan": {}},
    "strategy_activate": {"room_id": ROOM, "expected_revision": 0},
    "strategy_disarm": {"room_id": ROOM},
    "runs_save": {"room_id": ROOM, "expected_revision": 0, "record": {}},
    "runs_archive": {"room_id": ROOM, "expected_revision": 0, "id": "r", "archived": True},
    "runs_import": {"room_id": ROOM, "expected_revision": 0, "runs": []},
    # The controller app's grow-day summaries, and a backfill from statistics.
    "grow_day_record": {"room_id": ROOM, "days": []},
    "grow_days_backfill": {"room_id": ROOM, "start": "2026-01-01", "end": "2026-01-02"},
    "history_connection_get": {"room_id": ROOM},
    "history_connection_save": {"room_id": ROOM, "expected_revision": 0, "connection": {}},
    "history_long": {"room_id": ROOM, "entity_ids": ["sensor.probe"],
                     "start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z"},
    "stock_save": {"room_id": ROOM, "expected_revision": 0, "tanks": []},
    "stock_refill": {"room_id": ROOM, "expected_revision": 0, "id": "bloom"},
    "stock_record_batch": {"room_id": ROOM, "expected_revision": 0},
    "stock_draw": {"room_id": ROOM, "key": "k", "draws": {}, "source": "dose"},
    "calibration_record": {
        "room_id": ROOM,
        "expected_revision": 0,
        "probe": "feed_ph",
        "points": [],
    },
    # The feed probe calibration wizard: a session pauses the room's dosing, a commit changes what the
    # controller reads from the feed probe.
    "calibration_start": {"room_id": ROOM, "probe": "feed_ph"},
    "calibration_capture": {"session_id": "s", "point": 0},
    "calibration_commit": {"session_id": "s"},
    "calibration_revert": {"room_id": ROOM, "probe": "feed_ph"},
    "calibration_abandon": {"session_id": "s"},
    "dosing_save": {"room_id": ROOM, "expected_revision": 0, "pumps": [], "batch": {}},
    # A stop is the one dosing request anyone may make (test_an_ordinary_user_may_stop_dosing).
    "dosing_request": {"room_id": ROOM, "action": "dose", "pump": "balance", "ml": 5},
    # A push to the phones: the controller app's, as Home Assistant's administrator Supervisor user.
    "notify": {"key": "k", "title": "t", "message": "m"},
    # An ask spends the room's AI budget.
    "brain_ask": {"room_id": ROOM, "question": "why?"},
    "brain_prompt_save": {"room_id": ROOM, "expected_revision": 0, "config": {}},
    "brain_prompt_rollback": {"room_id": ROOM, "expected_revision": 0, "revision": 0},
    "brain_prompt_rebuild": {"room_id": ROOM, "expected_revision": 0},
    "brain_prompt_publish": {"room_id": ROOM, "expected_revision": 0, "live": {}},
    # What the dashboard shows in the room, for everyone who opens it.
    "display_save": {"room_id": ROOM, "expected_revision": 0, "options": {"show_climate": True}},
    "supply_save": {"expected_revision": 0, "irrigation_pumps": []},
    # The room's timer programs and skips: what the controller app waters by.
    "timer_program_set": {"room_id": ROOM, "expected_revision": 0, "program": {}},
    "timer_program_delete": {"room_id": ROOM, "expected_revision": 0, "id": "x"},
    "timer_skip": {"room_id": ROOM, "expected_revision": 0, "zone": 1, "at": "2026-10-22T08:00:00+13:00"},
    "save_recipe": {"recipe": {}},
    "apply_recipe": {},
    "set_manual_override": {"zone": 1},
    "setup_read": {},
    "setup_create": {},
    "setup_save": {},
    "setup_remove": {},
    "setup_commission": {},
    "test_shot": {"room_id": ROOM, "zone": 1},
    "overlay_keep": {"room_id": ROOM, "entity_id": "number.crop_steering_zone_1_p2_shot_size"},
    "overlay_undo": {"room_id": ROOM, "entity_id": "number.crop_steering_zone_1_p2_shot_size"},
    "journal_append": {"room_id": ROOM, "events": []},
}
READS = {
    "harvests_get": {"room_id": ROOM},
    "strategy_get": {"room_id": ROOM},
    "brain_prompt_get": {"room_id": ROOM},
    "strategy_preview": {"room_id": ROOM},
    "runs_get": {"room_id": ROOM},
    "grow_days_get": {"room_id": ROOM},
    "setpoint_log_get": {"room_id": ROOM},
    "overlay_get": {"room_id": ROOM},
    "stock_get": {"room_id": ROOM},
    "calibration_get": {"room_id": ROOM},
    "calibration_status": {"session_id": "s"},
    "dosing_get": {"room_id": ROOM},
    "display_get": {"room_id": ROOM},
    "supply_get": {},
    "timer_program_list": {},
    "timer_program_preview": {"room_id": ROOM, "program": {}},
    "notify_get": {},
    "whats_new_get": {},
    "journal_query": {"room_id": ROOM, "since": "2026-01-01T00:00:00+00:00"},
}
# Changes nothing but whether the dashboard's What's new window shows again: whoever opens the
# dashboard first after an update may dismiss it, administrator or not.
NOTICES = {"whats_new_seen": {"version": "2.0.0"}}
# Anyone signed in may tick what their own phone gets and test it; the store refuses the rest row by
# row (tests_ha/test_notify.py).
PER_USER = {
    "notify_save": {"expected_revision": 0, "recipients": [{"service": "notify.someone_elses"}]},
    "notify_test": {"service": "notify.someone_elses"},
}
# Stop all only switches things off (the kill switch, then the room's pumps and valves): whoever may look at a
# room may stop it, as anyone may stop its dosing.
STOPS = {"stop_all": {"room_id": ROOM}}
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
    assert set(hass.services.async_services()[DOMAIN]) == (
        set(CHANGES) | set(READS) | set(NOTICES) | set(PER_USER) | set(STOPS)
    )
    fired = []
    for event in EVENTS:
        hass.bus.async_listen(event, fired.append)
    plan = dict(hass.states.get(PLAN).attributes)

    for name, data in CHANGES.items():
        with pytest.raises(HomeAssistantError, match=REFUSED):
            await _call(hass, staff, name, data)
    for name, data in NOTICES.items():
        assert "seen" in await _call(hass, staff, name, data)
    # Someone else's phone: reached with who they are, and refused by the store.
    for name, data in PER_USER.items():
        assert (await _call(hass, staff, name, data))["error"].startswith("not allowed: ")
    assert hass.states.get("sensor.crop_steering_notify_config").state == "0"
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


async def test_an_ordinary_user_may_stop_dosing(hass):
    """A stop only switches things off: whoever may look at a room may stop its dosing."""
    await _install(hass)
    staff = await _staff(hass)
    answer = await _call(hass, staff, "dosing_request", {"room_id": ROOM, "action": "stop"})
    assert answer["error"] is None
    assert (answer["request"]["action"], answer["request"]["by"]) == ("stop", "Staff phone")
    await hass.async_block_till_done()
    stored = hass.states.get("sensor.crop_steering_tent_dosing_config").attributes["request"]
    assert stored == answer["request"]


async def test_an_ordinary_user_may_stop_all(hass):
    """Stop all switches the room's kill switch off and nothing on: a staff phone may press it."""
    await _install(hass)
    staff = await _staff(hass)
    kill = "switch.crop_steering_tent_engine_enabled"
    await hass.services.async_call("switch", "turn_on", {"entity_id": kill}, blocking=True)
    answer = await _call(hass, staff, "stop_all", STOPS["stop_all"])
    assert answer["kill_switch"] == [kill] and hass.states.get(kill).state == "off"


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
