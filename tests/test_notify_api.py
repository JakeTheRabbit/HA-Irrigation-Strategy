"""Who gets which alerts, for the whole site (docs/NOTIFICATIONS.md, Services): one store saved against its
revision, who may change which row, how a push finds the phones that ask for it, what it carries, a phone that
fails, a test push, and the integration's own Repairs cards going out the same way."""

import asyncio
import copy
import json
import re
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from . import ha_stubs

ha_stubs.install()

from custom_components.crop_steering import notify_api, notify_catalog  # noqa: E402
from custom_components.crop_steering.const import DOMAIN  # noqa: E402
from homeassistant.exceptions import HomeAssistantError  # noqa: E402

STRINGS = (
    Path(__file__).resolve().parents[1] / "custom_components" / DOMAIN / "strings.json"
)
ADMIN = SimpleNamespace(id="admin-user", name="Admin", is_admin=True)
STAFF = SimpleNamespace(id="staff-user", name="Staff", is_admin=False)
OTHER = SimpleNamespace(id="other-user", name="Other", is_admin=False)
USERS = {user.id: user for user in (ADMIN, STAFF, OTHER)}
PHONE_A = "notify.mobile_app_phone_a"  # registered by STAFF's app
PHONE_B = "notify.mobile_app_phone_b"  # an app whose registration is not known
GROUP = "notify.all_phones"  # a notify service that is not a phone
SENSOR = "sensor.crop_steering_notify_config"
# Tapping a push opens the Crop Steering panel (iOS reads url, Android clickAction).
LINK = {"url": "/crop-steering", "clickAction": "/crop-steering"}


class MemoryStore:
    def __init__(self, value=None):
        self.value, self.saves = value, 0

    async def async_load(self):
        return copy.deepcopy(self.value)

    async def async_save(self, value):
        self.value, self.saves = copy.deepcopy(value), self.saves + 1


class States:
    def __init__(self):
        self.values = {}

    def async_set(self, entity_id, state, attributes=None):
        self.values[entity_id] = (state, dict(attributes or {}))

    def async_remove(self, entity_id):
        self.values.pop(entity_id, None)


class Services:
    """Home Assistant's service registry, with notify services that record what they were sent."""

    def __init__(self, notify):
        self.notify = set(notify)
        self.registered = {}
        self.sent = []  # (service, payload)
        self.failing = {}  # service -> the error it raises
        self.slow = set()

    def async_register(self, domain, name, handler, schema=None, **_response):
        self.registered[(domain, name)] = handler

    def async_remove(self, domain, name):
        self.registered.pop((domain, name), None)

    def has_service(self, domain, name):
        return domain == "notify" and name in self.notify

    def async_services(self):
        return {"notify": {name: object() for name in self.notify}}

    async def async_call(self, domain, name, data, blocking=False):
        service = f"{domain}.{name}"
        if service in self.failing:
            raise self.failing[service]
        if service in self.slow:
            await asyncio.sleep(1)
        self.sent.append((service, copy.deepcopy(data)))


class Bus:
    def __init__(self):
        self.listeners = []

    def async_listen(self, event, handler):
        self.listeners.append((event, handler))
        return lambda: self.listeners.remove((event, handler))


class Hass:
    def __init__(self, notify=(PHONE_A, PHONE_B, GROUP), rooms=None):
        self.states = States()
        self.services = Services(name.split(".", 1)[1] for name in notify)
        self.bus = Bus()
        self.data = {}
        self.config = SimpleNamespace(language="en")
        self.auth = SimpleNamespace(async_get_user=AsyncMock(side_effect=USERS.get))
        phone = SimpleNamespace(
            data={"device_name": "Phone A", "user_id": STAFF.id}, title="Phone A"
        )
        self.entries = {
            "mobile_app": [phone],
            DOMAIN: [
                SimpleNamespace(data=room, title=room.get("room_name", ""))
                for room in (rooms or [{"room_slug": "default", "room_prefix": ""}])
            ],
        }
        self.config_entries = SimpleNamespace(
            async_entries=lambda domain: list(self.entries.get(domain, []))
        )
        self.tasks = []

    def async_create_task(self, coro):
        self.tasks.append(coro)


@pytest.fixture(autouse=True)
def home_assistant(monkeypatch):
    """What notify_api imports from Home Assistant that the lean stubs do not have."""
    util = sys.modules["homeassistant.util"]
    monkeypatch.setattr(
        util,
        "slugify",
        lambda text: re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_"),
        raising=False,
    )
    monkeypatch.setattr(
        sys.modules["homeassistant.core"],
        "SupportsResponse",
        SimpleNamespace(ONLY="only", OPTIONAL="optional"),
        raising=False,
    )
    strings = json.loads(STRINGS.read_text(encoding="utf-8"))
    translation = types.ModuleType("homeassistant.helpers.translation")

    async def async_get_translations(hass, language, category, integrations=None):
        return {
            f"component.{DOMAIN}.{category}.{key}.{field}": text
            for key, texts in strings[category].items()
            for field, text in texts.items()
        }

    translation.async_get_translations = async_get_translations
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.translation", translation)


def rig(stored=None, **hass_options):
    hass = Hass(**hass_options)
    notifier = notify_api.Notifier(hass, MemoryStore(stored))
    asyncio.run(notifier.async_init())
    notifier.publish()
    return hass, notifier


def row(service, **extra):
    return {
        "service": service,
        "name": service.split(".")[-1],
        "user_id": None,
        "kinds": [],
        "rooms": [],
        "urgent_high_priority": True,
        **extra,
    }


def save(notifier, user=ADMIN, **data):
    data.setdefault("expected_revision", notifier.data["revision"])
    return asyncio.run(notifier.save(data, user))


def saved(*rows, idle_hours=3, revision=1):
    """A stored setup, as an earlier save wrote it."""
    return {"revision": revision, "idle_hours": idle_hours, "recipients": list(rows)}


def send(notifier, **data):
    return asyncio.run(
        notifier.send({"key": "k", "title": "T", "message": "M", **data})
    )


# ------------------------------------------------------------------ the store and the sensor
def test_a_site_with_no_store_answers_with_an_empty_setup_and_its_phones():
    hass, notifier = rig()
    answer = asyncio.run(notifier.response(ADMIN))
    assert answer["schema_version"] == 1 and answer["error"] is None
    assert answer["config"] == {"revision": 0, "idle_hours": 3, "recipients": []}
    assert answer["kinds"] == notify_catalog.serial()
    assert answer["phones"] == [
        {
            "service": PHONE_A,
            "name": "Phone A",
            "user_id": STAFF.id,
            "user_name": "Staff",
        },
        # A phone whose app registration is not known still shows, with no owner.
        {"service": PHONE_B, "name": "phone b", "user_id": None, "user_name": None},
    ]
    assert (answer["can_edit_all"], answer["user_id"]) == (True, ADMIN.id)
    staff = asyncio.run(notifier.response(STAFF))
    assert (staff["can_edit_all"], staff["user_id"]) == (False, STAFF.id)
    assert asyncio.run(notifier.response(None))["can_edit_all"] is False
    # What the controller app reads: nobody set up, so it pushes to its own option as before.
    assert hass.states.values[SENSOR] == (
        "0",
        {
            "friendly_name": "Crop Steering notifications",
            "recipients": 0,
            "idle_hours": 3,
        },
    )


def test_saving_moves_the_revision_and_a_stale_or_invalid_save_changes_nothing():
    hass, notifier = rig()
    answer = save(
        notifier,
        recipients=[
            {"service": PHONE_A, "kinds": ["stock", "emergency"]},
            row(GROUP, name=" Everyone ", kinds=["phases"], rooms=["f1_", ""]),
        ],
        idle_hours=4,
    )
    assert answer["error"] is None and answer["config"]["revision"] == 1
    phone, group = answer["config"]["recipients"]
    # A phone added from the list is named for its device and knows whose it is.
    assert phone == {
        "service": PHONE_A,
        "name": "Phone A",
        "user_id": STAFF.id,
        "kinds": ["emergency", "stock"],
        "rooms": [],
        "urgent_high_priority": True,
    }
    assert (group["name"], group["rooms"], group["user_id"]) == (
        "Everyone",
        ["", "f1_"],
        None,
    )
    assert answer["config"]["idle_hours"] == 4
    assert notifier._store.value == answer["config"] and notifier._store.saves == 1
    assert hass.states.values[SENSOR][0] == "1"
    assert hass.states.values[SENSOR][1]["recipients"] == 2
    assert hass.states.values[SENSOR][1]["idle_hours"] == 4

    stale = save(notifier, expected_revision=0, recipients=[])
    assert stale["error"] == "revision" and len(stale["config"]["recipients"]) == 2
    for recipients, words in (
        ([row(PHONE_A, kinds=["stock", "weather"])], "unknown kind weather"),
        ([row("mobile_app_phone_a")], "notify.<name>"),
        ([row(PHONE_A), row(PHONE_A)], f"{PHONE_A} is listed twice"),
        ([row("notify.mobile_app_nowhere")], "not a notify service"),
        ([row(PHONE_A, rooms=["F1"])], "room prefixes"),
        ([row(PHONE_A, urgent_high_priority="yes")], "true or false"),
        ([row(PHONE_A)] * 21, "at most 20"),
    ):
        refused = save(notifier, recipients=recipients)
        assert words in refused["error"], words
        assert refused["config"]["revision"] == 1
    for hours in (0, 12.5, "3", True):
        refused = save(notifier, recipients=[], idle_hours=hours)
        assert "1 to 12" in refused["error"], hours
    assert notifier._store.saves == 1 and hass.states.values[SENSOR][0] == "1"
    assert save(notifier, recipients=[], idle_hours=1.5)["config"]["idle_hours"] == 1.5


def test_a_kind_this_version_does_not_know_is_dropped_not_the_whole_setup():
    """A row saved by a newer version, before a rollback: its other kinds, and every other row, still count."""
    hass, notifier = rig(
        saved(row(PHONE_A, kinds=["stock", "a_newer_kind"]), row(PHONE_B))
    )
    assert notifier.error is None
    assert [r["kinds"] for r in notifier.data["recipients"]] == [["stock"], []]
    assert hass.states.values[SENSOR][1]["recipients"] == 2


def test_a_phone_saved_before_may_be_away_but_one_added_now_must_exist():
    """An app that has not registered again since Home Assistant started never blocks a save."""
    hass, notifier = rig(saved(row(PHONE_B, kinds=["stock"])))
    hass.services.notify.discard("mobile_app_phone_b")
    assert save(notifier, recipients=[row(PHONE_B, kinds=["dosing"])])["error"] is None
    hass.services.notify.discard("mobile_app_phone_a")
    added = save(notifier, recipients=[row(PHONE_B), row(PHONE_A)])
    assert added["error"] == f"{PHONE_A} is not a notify service in Home Assistant"


def test_a_corrupt_store_is_kept_and_every_change_refused(monkeypatch):
    logged = []
    monkeypatch.setattr(
        notify_api._LOGGER, "error", lambda msg, *args: logged.append(msg % args)
    )
    hass, notifier = rig({"revision": "seven", "recipients": []})
    assert "not been overwritten" in notifier.error
    # Said in Home Assistant's log: until it is fixed, pushes go only to the controller app's option.
    [line] = logged
    assert "notify_service option" in line and notifier.error in line
    assert (
        hass.states.values[SENSOR][0] == "unavailable"
    )  # the controller: nobody set up
    assert "recipients" not in hass.states.values[SENSOR][1]
    assert save(notifier, recipients=[])["error"] == notifier.error
    assert send(notifier, code="CS-301") == {"sent_to": [], "error": notifier.error}
    assert notifier._store.saves == 0
    assert notifier._store.value == {"revision": "seven", "recipients": []}


# ------------------------------------------------------------------ who may change which row
def _two_owners():
    return rig(
        saved(
            row(PHONE_A, user_id=STAFF.id, kinds=["stock"]),
            row(PHONE_B, user_id=OTHER.id, kinds=["emergency"], rooms=["f1_"]),
        )
    )


def _as_saved(notifier):
    return copy.deepcopy(notifier.data["recipients"])


def test_a_non_administrator_changes_only_the_kinds_rooms_and_priority_of_their_own_phones():
    hass, notifier = _two_owners()
    mine, theirs = _as_saved(notifier)
    mine.update(kinds=["stock", "dosing"], rooms=[""], urgent_high_priority=False)
    answer = save(notifier, STAFF, recipients=[mine, theirs])
    assert answer["error"] is None and answer["config"]["revision"] == 2
    assert answer["config"]["recipients"][0]["kinds"] == ["stock", "dosing"]
    assert answer["config"]["recipients"][0]["urgent_high_priority"] is False
    assert answer["config"]["recipients"][1] == theirs
    assert (answer["can_edit_all"], answer["user_id"]) == (False, STAFF.id)
    # In any order: a row is known by its service.
    assert save(notifier, STAFF, recipients=[theirs, mine])["error"] is None


@pytest.mark.parametrize(
    "change, refused",
    [
        (lambda mine, theirs: theirs.update(kinds=["stock"]), "Other"),
        (lambda mine, theirs: theirs.update(rooms=[]), "Other"),
        (lambda mine, theirs: mine.update(name="Mine now"), "rename a phone"),
        (lambda mine, theirs: mine.update(user_id=OTHER.id), "whose phone it is"),
    ],
)
def test_a_non_administrator_may_not_touch_anything_else(change, refused):
    _hass, notifier = _two_owners()
    notifier.data["recipients"][1]["name"] = "Other"
    before = copy.deepcopy(notifier.data)
    mine, theirs = _as_saved(notifier)
    change(mine, theirs)
    answer = save(notifier, STAFF, recipients=[mine, theirs])
    assert answer["error"].startswith("not allowed: ") and refused in answer["error"]
    assert notifier.data == before and answer["config"] == before


def test_a_non_administrator_may_not_add_or_remove_a_phone_or_change_the_threshold():
    _hass, notifier = _two_owners()
    before = copy.deepcopy(notifier.data)
    mine, theirs = _as_saved(notifier)
    for recipients in ([mine], [mine, theirs, row(GROUP)], [mine, mine]):
        answer = save(notifier, STAFF, recipients=recipients)
        assert answer["error"].startswith("not allowed: ") or "once" in answer["error"]
    answer = save(notifier, STAFF, recipients=[mine, theirs], idle_hours=6)
    assert answer["error"].startswith("not allowed: ")
    assert (
        save(notifier, STAFF, recipients=[mine, theirs], idle_hours=3.0)["error"]
        is None
    )
    assert notifier.data["recipients"] == before["recipients"]


def test_an_administrator_or_an_automation_changes_every_row():
    for user in (ADMIN, None):
        _hass, notifier = _two_owners()
        mine, theirs = _as_saved(notifier)
        theirs.update(kinds=["jev"], name="Renamed", user_id=STAFF.id)
        answer = save(notifier, user, recipients=[theirs, row(GROUP)], idle_hours=8)
        assert answer["error"] is None
        assert [r["service"] for r in answer["config"]["recipients"]] == [
            PHONE_B,
            GROUP,
        ]
        assert answer["config"]["recipients"][0]["user_id"] == STAFF.id


# ------------------------------------------------------------------ routing
def _routed():
    return rig(
        saved(
            row(PHONE_A, kinds=["stock", "watering"]),
            row(PHONE_B, kinds=["emergency", "hardware"], rooms=["f1_"]),
            row(
                GROUP,
                kinds=["phases", "emergency"],
                rooms=[""],
                urgent_high_priority=False,
            ),
        )
    )


def _sent(hass):
    return [service for service, _payload in hass.services.sent]


def test_a_push_goes_to_each_phone_that_ticks_its_kind_and_covers_its_room_once():
    hass, notifier = _routed()
    assert send(notifier, code="CS-608", room="") == {
        "sent_to": [PHONE_A],
        "error": None,
    }
    hass.services.sent.clear()
    # CS-301 is an emergency AND a hardware lockout: the phone ticking both gets it once.
    answer = send(notifier, code="CS-301", room="f1_", urgent=True)
    assert answer == {"sent_to": [PHONE_B], "error": None} and _sent(hass) == [PHONE_B]
    hass.services.sent.clear()
    # The default room's emergency: not the phone that covers only f1_.
    assert send(notifier, code="CS-301", room="", urgent=True)["sent_to"] == [GROUP]
    hass.services.sent.clear()
    # About no room in particular: everyone who ticks its kind.
    assert send(notifier, code="CS-806")["sent_to"] == []
    assert send(notifier, code="CS-801", urgent=True)["sent_to"] == [PHONE_B, GROUP]
    hass.services.sent.clear()
    assert send(notifier, event="phase", room="")["sent_to"] == [GROUP]
    assert send(notifier, event="phase", room="f1_")["sent_to"] == []
    # Nobody ticks it: nobody gets it, and that is not a failure.
    assert send(notifier, code="CS-705", room="") == {"sent_to": [], "error": None}
    # A newer controller's code: an emergency when it says so, else setup.
    assert send(notifier, code="CS-299", room="", urgent=True)["sent_to"] == [GROUP]
    assert send(notifier, code="CS-299", room="")["sent_to"] == []


def test_an_emergency_no_row_covers_still_reaches_every_phone_that_takes_emergencies():
    """The one push that must reach someone. With no row for its room it goes to every phone that takes
    emergencies for any room; with none at all the answer says so, and the controller app then pushes to its
    own notify_service option. Anything else nobody ticked stays with nobody."""
    hass, notifier = rig(
        saved(
            row(PHONE_A, kinds=["stock"]),
            row(PHONE_B, kinds=["emergency"], rooms=["f1_"]),
        )
    )
    assert send(notifier, code="CS-301", room="", urgent=True) == {
        "sent_to": [PHONE_B],
        "error": None,
    }
    assert send(notifier, code="CS-801", urgent=True)["sent_to"] == [PHONE_B]
    assert send(notifier, code="CS-705", room="") == {"sent_to": [], "error": None}
    hass, notifier = rig(saved(row(PHONE_A, kinds=["stock", "dosing"])))
    assert send(notifier, code="CS-301", room="f1_", urgent=True) == {
        "sent_to": [],
        "error": "no phone takes emergencies",
    }
    assert hass.services.sent == []


def test_every_push_carries_its_key_as_the_tag_and_emergencies_go_high_priority():
    hass, notifier = _routed()
    send(notifier, key="blind_f1_z2", code="CS-301", room="f1_", urgent=True)
    send(notifier, key="stock_low", code="CS-608", room="")
    send(notifier, key="x", code="CS-801", urgent=True)
    payloads = {service: payload for service, payload in hass.services.sent}
    assert payloads[PHONE_B] == {
        "title": "T",
        "message": "M",
        "data": {
            "tag": "x",
            "url": "/crop-steering",
            "clickAction": "/crop-steering",
            "priority": "high",
            "channel": "Crop Steering urgent",
            "push": {"interruption-level": "time-sensitive"},
        },
    }
    assert hass.services.sent[0][1]["data"]["tag"] == "blind_f1_z2"
    # Not urgent: the tag and the link.
    assert payloads[PHONE_A] == {
        "title": "T",
        "message": "M",
        "data": {"tag": "stock_low", **LINK},
    }
    # `data` goes to mobile_app services only; this one asked for no high priority anyway.
    assert payloads[GROUP] == {"title": "T", "message": "M"}
    assert notify_api.push_data(GROUP, "k", True) is None


def test_a_phone_that_fails_never_stops_the_others(monkeypatch):
    hass, notifier = _routed()
    hass.services.failing[PHONE_B] = HomeAssistantError("device not connected")
    answer = send(notifier, code="CS-801", urgent=True)
    assert answer == {
        "sent_to": [GROUP],
        "error": f"{PHONE_B}: device not connected",
    }
    assert _sent(hass) == [GROUP]
    # Every phone it went to failed: nothing was sent, and the answer says why.
    answer = send(notifier, code="CS-301", room="f1_")
    assert answer["sent_to"] == [] and PHONE_B in answer["error"]
    # A phone that does not answer in time is a failure too, and does not hold the others up.
    monkeypatch.setattr(notify_api, "SEND_TIMEOUT_S", 0.05)
    hass.services.failing.clear()
    hass.services.slow.add(PHONE_B)
    answer = send(notifier, code="CS-801", urgent=True)
    assert answer["sent_to"] == [GROUP] and "no answer in 0.05 s" in answer["error"]


def test_with_nobody_set_up_nothing_is_sent_and_the_answer_says_so():
    hass, notifier = rig()
    assert send(notifier, code="CS-301") == {
        "sent_to": [],
        "error": "no phone is set up for notifications",
    }
    assert hass.services.sent == []


# ------------------------------------------------------------------ a test push
def test_a_test_push_goes_to_the_phone_asked_for_by_its_owner_or_an_administrator():
    hass, notifier = _two_owners()
    assert asyncio.run(notifier.test(PHONE_B, ADMIN)) == {"sent": True, "error": None}
    service, payload = hass.services.sent[-1]
    assert service == PHONE_B and payload["title"] == "Crop Steering: a test"
    assert payload["message"] == "This phone gets: Emergencies."
    assert payload["data"] == {"tag": "crop_steering_test", **LINK}
    assert asyncio.run(notifier.test(PHONE_A, STAFF))["sent"] is True
    assert asyncio.run(notifier.test(GROUP, None))["sent"] is True  # an automation
    assert "gets nothing yet" in hass.services.sent[-1][1]["message"]
    count = len(hass.services.sent)
    refused = asyncio.run(notifier.test(PHONE_B, STAFF))
    assert refused["sent"] is False and refused["error"].startswith("not allowed: ")
    assert asyncio.run(notifier.test("notify.mobile_app_gone", ADMIN)) == {
        "sent": False,
        "error": "notify.mobile_app_gone is not a notify service in Home Assistant",
    }
    assert len(hass.services.sent) == count
    hass.services.failing[PHONE_A] = HomeAssistantError("rate limited")
    assert asyncio.run(notifier.test(PHONE_A, ADMIN)) == {
        "sent": False,
        "error": "rate limited",
    }


def test_a_phone_not_yet_in_a_row_may_be_tested_by_the_user_whose_app_registered_it():
    _hass, notifier = rig()
    assert asyncio.run(notifier.test(PHONE_A, STAFF))["sent"] is True
    assert asyncio.run(notifier.test(PHONE_A, OTHER))["sent"] is False


# ------------------------------------------------------------------ the services
@pytest.fixture
def services(monkeypatch):
    hass = Hass()
    stores = []

    def notifier(hass_):
        stores.append(MemoryStore())
        return _REAL(hass_, stores[-1])

    monkeypatch.setattr(notify_api, "Notifier", notifier)
    first, second = ha_stubs.FakeEntry(entry_id="one"), ha_stubs.FakeEntry(
        entry_id="two"
    )
    for entry in (first, second):
        asyncio.run(notify_api.async_setup_notify(hass, entry))

    def call(name, user=ADMIN, **data):
        request = SimpleNamespace(
            service=name,
            data=data,
            context=SimpleNamespace(user_id=getattr(user, "id", user)),
        )
        return asyncio.run(hass.services.registered[(DOMAIN, name)](request))

    return SimpleNamespace(hass=hass, call=call, stores=stores, entries=(first, second))


_REAL = notify_api.Notifier


def test_one_setup_for_the_site_however_many_rooms(services):
    hass = services.hass
    assert len(services.stores) == 1  # the second room joined the first one's store
    assert set(hass.services.registered) == {(DOMAIN, s) for s in notify_api.SERVICES}
    assert services.call("notify_get", STAFF)["config"]["revision"] == 0
    saved_ = services.call(
        "notify_save",
        ADMIN,
        expected_revision=0,
        recipients=[row(PHONE_A, kinds=["stock"])],
    )
    assert saved_["error"] is None
    assert services.call(
        "notify", ADMIN, key="k", code="CS-608", room="", title="T", message="M"
    ) == {
        "sent_to": [PHONE_A],
        "error": None,
    }
    asyncio.run(notify_api.async_unload_notify(hass, services.entries[0]))
    assert (
        DOMAIN,
        "notify",
    ) in hass.services.registered and SENSOR in hass.states.values
    asyncio.run(notify_api.async_unload_notify(hass, services.entries[1]))
    assert hass.services.registered == {} and SENSOR not in hass.states.values
    assert hass.bus.listeners == [] and "_notify" not in hass.data[DOMAIN]


def test_who_may_call_which_service(services):
    call = services.call
    for user in (STAFF, "someone-deleted", None):
        assert "config" in call(
            "notify_get", user
        )  # reading is open, as for every read
    for name, data in (
        ("notify_save", {"expected_revision": 0, "recipients": []}),
        ("notify_test", {"service": PHONE_A}),
    ):
        with pytest.raises(
            HomeAssistantError, match="requires a signed-in Home Assistant user$"
        ):
            call(name, "someone-deleted", **data)
    # The controller's call, and an automation's: an administrator's; a signed-in non-administrator: never.
    for user in (ADMIN, None):
        assert call("notify", user, key="k", title="T", message="M")["error"]
    with pytest.raises(
        HomeAssistantError,
        match="requires an authenticated Home Assistant administrator",
    ):
        call("notify", STAFF, key="k", title="T", message="M")
    assert call("notify_test", STAFF, service=PHONE_A)["sent"] is True
    assert call("notify_test", OTHER, service=PHONE_A)["sent"] is False
    assert call("notify_save", STAFF, expected_revision=0, recipients=[row(PHONE_A)])[
        "error"
    ].startswith("not allowed: ")


# ------------------------------------------------------------------ the Repairs cards
@pytest.fixture
def issues(monkeypatch):
    """The issue registry's cards by issue id: what push_issue reads a card's placeholders from."""
    cards = {}
    registry = SimpleNamespace(
        async_get_issue=lambda domain, issue_id: cards.get(issue_id)
    )
    ir = sys.modules["homeassistant.helpers.issue_registry"]
    monkeypatch.setattr(ir, "async_get", lambda hass: registry, raising=False)
    return cards


def _raise(hass, issue_id, action="create", domain=DOMAIN):
    for event, handler in list(hass.bus.listeners):
        if event == notify_api.ISSUE_EVENT:
            handler(
                SimpleNamespace(
                    data={"action": action, "domain": domain, "issue_id": issue_id}
                )
            )
    for task in hass.tasks:
        asyncio.run(task)
    hass.tasks.clear()


def test_a_repairs_card_goes_to_the_phones_that_tick_its_kind_when_it_is_raised(issues):
    rooms = [
        {"room_slug": "default", "room_prefix": "", "room_name": "Crop Steering"},
        {"room_slug": "f1", "room_prefix": "f1_", "room_name": "Flower 1"},
    ]
    hass, notifier = rig(
        saved(
            row(PHONE_A, kinds=["stock"], rooms=["f1_"]),
            row(PHONE_B, kinds=["emergency"]),
        ),
        rooms=rooms,
    )
    notifier.listen()
    issues["stock_low_f1"] = SimpleNamespace(
        translation_placeholders={"count": "1", "tanks": "- Bloom: 2 L of 20 L"}
    )
    _raise(hass, "stock_low_f1")
    service, payload = hass.services.sent[-1]
    assert service == PHONE_A
    assert payload["title"] == "Flower 1: 1 stock tank(s) running low (CS-608)"
    assert (
        "- Bloom: 2 L of 20 L" in payload["message"]
        and "Code CS-608." in payload["message"]
    )
    assert payload["data"] == {"tag": "stock_low_f1", **LINK}
    # Still raised: an update (new placeholders, or raised again after a restart) is not a new card.
    _raise(hass, "stock_low_f1", "update")
    _raise(hass, "stock_low_f1", "remove")
    _raise(hass, "something_else", domain="another_integration")
    assert len(hass.services.sent) == 1
    # The default room's low stock: not for the phone that covers only f1_.
    issues["stock_low"] = SimpleNamespace(
        translation_placeholders={"count": "2", "tanks": ""}
    )
    _raise(hass, "stock_low")
    assert len(hass.services.sent) == 1
    # A critical card is an emergency, sent as one.
    _raise(hass, "kill_switch_missing_f1")
    service, payload = hass.services.sent[-1]
    assert service == PHONE_B and payload["data"]["priority"] == "high"
    assert payload["title"] == "Flower 1: kill switch helper missing (CS-601)"
    notifier.stop()
    assert hass.bus.listeners == []


def test_a_card_that_comes_and_goes_is_pushed_at_most_every_half_hour(issues):
    """A probe going on and off line clears and raises its card every health check: one push per half hour,
    as the controller app repeats an alert."""
    hass, notifier = rig(saved(row(PHONE_A, kinds=["sensors"])))
    notifier.listen()
    now = {"t": 1000.0}
    notifier._clock = lambda: now["t"]
    _raise(hass, "fused_sensor_unavailable")
    _raise(hass, "fused_sensor_unavailable", "remove")
    now["t"] += 600
    _raise(hass, "fused_sensor_unavailable")
    assert _sent(hass) == [PHONE_A]
    now["t"] += notify_api.CARD_QUIET_S - 600
    _raise(hass, "fused_sensor_unavailable")
    assert _sent(hass) == [PHONE_A, PHONE_A]
    _raise(hass, "zone_no_sensor")  # another card is its own
    assert len(hass.services.sent) == 3


def test_a_card_whose_push_reached_no_phone_is_pushed_when_it_comes_back(issues):
    """The half hour starts only once a phone has the card: a push that failed is not a push."""
    hass, notifier = rig(saved(row(PHONE_A, kinds=["sensors"])))
    notifier.listen()
    hass.services.failing[PHONE_A] = HomeAssistantError("device not connected")
    _raise(hass, "fused_sensor_unavailable")
    _raise(hass, "fused_sensor_unavailable", "remove")
    hass.services.failing.clear()
    _raise(hass, "fused_sensor_unavailable")
    assert _sent(hass) == [PHONE_A]


def test_a_card_pushes_nothing_while_nobody_is_set_up_and_its_wording_never_loses_it(
    issues, monkeypatch
):
    hass, notifier = rig()
    notifier.listen()
    _raise(hass, "engine_offline")
    assert hass.services.sent == []
    hass, notifier = rig(saved(row(PHONE_A, kinds=["watering"])))
    notifier.listen()

    async def broken(*_args, **_kwargs):
        raise OSError("translations unreadable")

    monkeypatch.setattr(
        sys.modules["homeassistant.helpers.translation"],
        "async_get_translations",
        broken,
    )
    _raise(hass, "engine_offline")
    service, payload = hass.services.sent[-1]
    assert service == PHONE_A
    assert payload["title"] == "A card in Settings → Repairs (CS-602)"
    assert "Code CS-602." in payload["message"]
