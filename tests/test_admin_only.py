"""Only an administrator can change a room through a crop_steering service. Anyone can look.

The sidebar console is registered for every Home Assistant login, because reading is legitimate,
and it calls these services with that login. Before this, any login (a staff phone, the hallway
kiosk) could arm a plan with a future start date, which holds every zone, disarm the live plan,
replace every room's recipe or put a zone on hold. Automations call with no user and must run
exactly as before. Setup has always needed a signed-in administrator, automations included, and
still does. Stopping a room's dosing is the one change open to every login: a stop only switches
things off. Who gets which alerts on their own phone is the other: anyone signed in may save the
row of a phone that is theirs and send it a test, and the store refuses the rest row by row
(tests/test_notify_api.py).
"""

import asyncio
import re
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from . import ha_stubs

ha_stubs.install()

from custom_components.crop_steering import (  # noqa: E402
    dosing_api,
    notify_api,
    run_api,
    services,
    setup_api,
    stock_api,
    strategy_api,
    whats_new,
)
from custom_components.crop_steering.const import DOMAIN  # noqa: E402
from homeassistant.exceptions import HomeAssistantError  # noqa: E402

ADMIN, STAFF, GHOST = "admin-user", "staff-user", "deleted-user"
ROOM = "room:"
READ_ONLY = {
    "strategy_get",
    "strategy_preview",
    "runs_get",
    "stock_get",
    "dosing_get",
    "notify_get",
    "whats_new_get",
}
# Changes nothing but whether the dashboard's What's new window shows again: whoever opens the
# dashboard first after an update may dismiss it, administrator or not.
NOTICES = {"whats_new_seen": {"version": "2.0.0"}}
SETUP = {"setup_read", "setup_create", "setup_save", "setup_remove"}
# Every other service changes something. What each is called with:
CHANGES = {
    "set_manual_override": {"zone": 1},
    "apply_recipe": {"stage": "Bulk"},
    "save_recipe": {"recipe": {"stages": {}}},
    "strategy_save": {"room_id": ROOM, "expected_revision": 0, "plan": {}},
    "strategy_activate": {"room_id": ROOM, "expected_revision": 0},
    "strategy_disarm": {"room_id": ROOM},
    "runs_save": {"room_id": ROOM, "expected_revision": 0, "record": {}},
    "runs_archive": {
        "room_id": ROOM,
        "expected_revision": 0,
        "id": "r",
        "archived": True,
    },
    "runs_import": {"room_id": ROOM, "expected_revision": 0, "runs": []},
    "stock_save": {"room_id": ROOM, "expected_revision": 0, "tanks": []},
    "stock_refill": {"room_id": ROOM, "expected_revision": 0, "id": "bloom"},
    "stock_record_batch": {"room_id": ROOM, "expected_revision": 0},
    # What a dose drew from the stock tanks: the controller app calls it, as Home Assistant's
    # administrator Supervisor user; a signed-in non-administrator may not move a level.
    "stock_draw": {"room_id": ROOM, "key": "k", "draws": {}, "source": "dose"},
    # A dose or a batch is what makes the controller app run a pump: never for a
    # non-administrator. A stop only switches things off (STOP, below).
    "dosing_save": {"room_id": ROOM, "expected_revision": 0, "pumps": [], "batch": {}},
    "dosing_request": {"room_id": ROOM, "action": "dose", "pump": "balance", "ml": 5},
    # A push to the phones: the controller app calls it as the Supervisor user, an administrator.
    "notify": {"key": "k", "title": "t", "message": "m"},
}
# Anyone who may look at a room may stop its dosing; a user id Home Assistant does not know may not.
STOP = {"room_id": ROOM, "action": "stop"}
# Anyone signed in may save their own phone's row and test their own phone: the call goes through
# with who they are, and the store decides row by row. A user id Home Assistant does not know may not.
PER_USER = {
    "notify_save": {"expected_revision": 0, "recipients": []},
    "notify_test": {"service": "notify.mobile_app_phone"},
}


class Services(ha_stubs.FakeServices):
    def async_register(self, domain, name, handler, schema=None, **_response):
        super().async_register(domain, name, handler, schema)


@pytest.fixture
def rig(monkeypatch):
    """Every crop_steering service registered as HA would, over fakes that record what ran."""
    monkeypatch.setattr(
        sys.modules["homeassistant.core"],
        "SupportsResponse",
        SimpleNamespace(ONLY="only", OPTIONAL="optional"),
        raising=False,
    )
    vol = sys.modules["voluptuous"]
    for name, value in (("ALLOW_EXTRA", object()), ("Length", lambda **_: None)):
        if not hasattr(vol, name):
            monkeypatch.setattr(vol, name, value, raising=False)

    recipe = SimpleNamespace(
        entry=ha_stubs.FakeEntry(),
        active_stage="Bulk",
        async_apply=AsyncMock(return_value=0),
        async_save=AsyncMock(),
    )
    override = SimpleNamespace(
        entity_id=f"switch.{DOMAIN}_zone_1_manual_override",
        _override_loaded=True,
        async_set_manual_override=AsyncMock(),
        extra_state_attributes={"manual_override_expires_at": None},
    )
    strategy = SimpleNamespace(
        room_id=ROOM,
        save=AsyncMock(return_value={}),
        activate=AsyncMock(return_value={}),
        disarm=AsyncMock(return_value={}),
        response=MagicMock(return_value={"status": "draft"}),
        preview=MagicMock(return_value={}),
    )
    runs = SimpleNamespace(
        room_id=ROOM,
        async_init=AsyncMock(),
        response=MagicMock(return_value={"runs": []}),
        mutate=AsyncMock(return_value={"runs": []}),
    )
    monkeypatch.setattr(run_api, "RunStore", lambda hass, entry: runs)
    tanks = SimpleNamespace(
        room_id=ROOM,
        async_init=AsyncMock(),
        start=MagicMock(return_value=None),
        response=MagicMock(return_value={"tanks": []}),
        mutate=AsyncMock(return_value={"tanks": []}),
        draw=AsyncMock(return_value={"tanks": []}),
    )
    monkeypatch.setattr(stock_api, "StockStore", lambda hass, entry: tanks)
    dosing = SimpleNamespace(
        room_id=ROOM,
        async_init=AsyncMock(),
        response=MagicMock(return_value={"config": {}}),
        save=AsyncMock(return_value={"config": {}}),
        request=AsyncMock(return_value={"request": None, "error": None}),
    )
    monkeypatch.setattr(dosing_api, "DosingStore", lambda hass, entry: dosing)
    notice = SimpleNamespace(
        async_init=AsyncMock(),
        response=AsyncMock(return_value={"seen": None}),
        mark_seen=AsyncMock(return_value={"seen": "2.0.0"}),
    )
    monkeypatch.setattr(whats_new, "WhatsNew", lambda hass: notice)
    notifier = SimpleNamespace(
        async_init=AsyncMock(),
        publish=MagicMock(),
        listen=MagicMock(),
        response=AsyncMock(return_value={"config": {}}),
        save=AsyncMock(return_value={"config": {}, "error": None}),
        test=AsyncMock(return_value={"sent": True, "error": None}),
        send=AsyncMock(return_value={"sent_to": [], "error": None}),
    )
    monkeypatch.setattr(notify_api, "Notifier", lambda hass: notifier)
    setup = {
        "read_setup": MagicMock(return_value={}),
        "create_setup": AsyncMock(return_value={}),
        "save_setup": AsyncMock(return_value={}),
        "remove_setup": AsyncMock(return_value={}),
    }
    for name, fake in setup.items():
        monkeypatch.setattr(setup_api, name, fake)

    hass = ha_stubs.FakeHass(
        data={
            DOMAIN: {
                "_recipe": {"entry": recipe},
                "_manual_overrides": {"zone_1_manual_override": override},
                "_strategy": {"entry": strategy},
            }
        }
    )
    hass.services = Services()
    users = {
        ADMIN: SimpleNamespace(is_admin=True),
        STAFF: SimpleNamespace(is_admin=False),
    }
    hass.auth = SimpleNamespace(async_get_user=AsyncMock(side_effect=users.get))
    asyncio.run(services.async_setup_services(hass))
    asyncio.run(strategy_api.async_setup_strategy_services(hass))
    asyncio.run(run_api.async_setup_runs(hass, ha_stubs.FakeEntry()))
    asyncio.run(stock_api.async_setup_stock(hass, ha_stubs.FakeEntry()))
    asyncio.run(dosing_api.async_setup_dosing(hass, ha_stubs.FakeEntry()))
    asyncio.run(setup_api.async_setup_setup_services(hass))
    asyncio.run(whats_new.async_setup_whats_new(hass, ha_stubs.FakeEntry(), False))
    asyncio.run(notify_api.async_setup_notify(hass, ha_stubs.FakeEntry()))

    def effects():
        """Everything a handler could have done: events, service calls, writes."""
        writes = (
            recipe.async_apply,
            recipe.async_save,
            override.async_set_manual_override,
            strategy.save,
            strategy.activate,
            strategy.disarm,
            runs.mutate,
            tanks.mutate,
            tanks.draw,
            dosing.save,
            dosing.request,
            notifier.save,
            notifier.test,
            notifier.send,
            setup["create_setup"],
            setup["save_setup"],
            setup["remove_setup"],
        )
        return (
            len(hass.bus.events),
            len(hass.services.calls),
            setup["read_setup"].call_count,
            *(fake.await_count for fake in writes),
        )

    def call(name, user, data=None):
        handler = hass.services.registered[(DOMAIN, name)]
        request = SimpleNamespace(
            service=name,
            data=dict(
                {**CHANGES, **NOTICES, **PER_USER}.get(name, {})
                if data is None
                else data
            ),
            context=SimpleNamespace(user_id=user),
            return_response=True,
        )
        return asyncio.run(handler(request))

    return SimpleNamespace(
        hass=hass, call=call, effects=effects, notice=notice, notifier=notifier
    )


def test_every_service_is_either_read_only_or_checked(rig):
    """A new service has to be put in one list or the other here, on purpose."""
    registered = {name for _domain, name in rig.hass.services.registered}
    assert registered == READ_ONLY | SETUP | set(CHANGES) | set(NOTICES) | set(PER_USER)


@pytest.mark.parametrize("user", [STAFF, ADMIN, None])
@pytest.mark.parametrize("name", sorted(PER_USER))
def test_anyone_signed_in_reaches_the_store_with_who_they_are(rig, name, user):
    """The store lets a non-administrator change only their own phone's row, and test only their own
    phone; an administrator and an automation (no user) everything."""
    before = rig.effects()
    rig.call(name, user)
    assert rig.effects() != before
    caller = getattr(rig.notifier, name.removeprefix("notify_")).await_args.args[1]
    assert (caller is None) == (user is None)
    if user is not None:
        assert caller.is_admin is (user == ADMIN)


@pytest.mark.parametrize("name", sorted(PER_USER))
def test_a_user_home_assistant_does_not_know_may_not_save_or_test_a_phone(rig, name):
    before = rig.effects()
    with pytest.raises(
        HomeAssistantError,
        match=rf"^crop_steering\.{name} requires a signed-in Home Assistant user$",
    ):
        rig.call(name, GHOST)
    assert rig.effects() == before


@pytest.mark.parametrize("user", [STAFF, ADMIN, None])
def test_anyone_may_dismiss_the_whats_new_window_and_it_changes_nothing_else(rig, user):
    before = rig.effects()
    assert rig.call("whats_new_seen", user) == {"seen": "2.0.0"}
    rig.notice.mark_seen.assert_awaited_once_with("2.0.0")
    assert rig.effects() == before


@pytest.mark.parametrize("user", [STAFF, GHOST])
@pytest.mark.parametrize("name", sorted(set(CHANGES) | SETUP))
def test_a_signed_in_non_administrator_changes_nothing(rig, name, user):
    label = "Setup" if name in SETUP else f"{DOMAIN}.{name}"
    before = rig.effects()
    with pytest.raises(
        HomeAssistantError,
        match=rf"^{re.escape(label)} requires an authenticated Home Assistant administrator$",
    ):
        rig.call(name, user)
    assert rig.effects() == before


@pytest.mark.parametrize("user", [ADMIN, None], ids=["administrator", "automation"])
@pytest.mark.parametrize("name", sorted(CHANGES))
def test_an_administrator_or_an_automation_still_changes_it(rig, name, user):
    before = rig.effects()
    rig.call(name, user)
    assert rig.effects() != before


@pytest.mark.parametrize("name", sorted(SETUP))
def test_setup_still_refuses_a_call_with_no_signed_in_administrator(rig, name):
    before = rig.effects()
    with pytest.raises(HomeAssistantError, match="^Setup requires"):
        rig.call(name, None)
    assert rig.effects() == before
    rig.call(name, ADMIN)
    assert rig.effects() != before


@pytest.mark.parametrize("user", [STAFF, ADMIN, None])
def test_any_signed_in_user_or_an_automation_may_stop_dosing(rig, user):
    before = rig.effects()
    rig.call("dosing_request", user, STOP)
    assert rig.effects() != before
    for action in ("dose", "batch"):  # and nothing more
        if user == STAFF:
            with pytest.raises(HomeAssistantError, match="administrator$"):
                rig.call("dosing_request", user, {**STOP, "action": action})


def test_a_user_home_assistant_does_not_know_may_not_stop_dosing(rig):
    before = rig.effects()
    with pytest.raises(
        HomeAssistantError,
        match=r"^crop_steering\.dosing_request requires a signed-in Home Assistant user$",
    ):
        rig.call("dosing_request", GHOST, STOP)
    assert rig.effects() == before


@pytest.mark.parametrize("user", [STAFF, GHOST, None])
@pytest.mark.parametrize("name", sorted(READ_ONLY))
def test_reading_stays_open_to_every_login(rig, name, user):
    before = rig.effects()
    rig.call(name, user, {"room_id": ROOM})
    assert rig.effects() == before
