"""The dosing store and its services (docs/DOSING.md, Services): a setup saved against its revision,
requests that wait for the controller app, a stop that always gets through, the entities offered
to pick from, and what sensor.crop_steering_<prefix>dosing_config gives the controller to read."""

import asyncio
import copy
import json
import re
import sys
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from . import ha_stubs
from .test_dosing import BATCH, KNOWN, PUMP

ha_stubs.install()

from custom_components.crop_steering import dosing, dosing_api  # noqa: E402
from custom_components.crop_steering.const import DOMAIN  # noqa: E402
from homeassistant.exceptions import HomeAssistantError  # noqa: E402

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
STATUS = "sensor.crop_steering_dosing"


class MemoryStore:
    def __init__(self, value=None):
        self.value, self.saves = value, 0

    async def async_load(self):
        return copy.deepcopy(self.value)

    async def async_save(self, value):
        self.value, self.saves = copy.deepcopy(value), self.saves + 1


@pytest.fixture(autouse=True)
def dispatcher(monkeypatch):
    module = types.ModuleType("homeassistant.helpers.dispatcher")
    module.sent = []
    module.async_dispatcher_send = lambda hass, signal, *a: module.sent.append(signal)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.dispatcher", module)
    return module


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    now = {"at": NOW}
    monkeypatch.setattr(dosing_api, "_now", lambda: now["at"])
    return now


def rig(value=None, states=None, prefix=""):
    hass = ha_stubs.FakeHass(states={**{e: "off" for e in KNOWN}, **(states or {})})
    entry = ha_stubs.FakeEntry(data={"room_prefix": prefix}, entry_id="entry")
    store = dosing_api.DosingStore(hass, entry, MemoryStore(value))
    asyncio.run(store.async_init())
    return hass, store


def save(store, **data):
    data.setdefault("expected_revision", store.data["revision"])
    data.setdefault("pumps", [copy.deepcopy(PUMP)])
    data.setdefault("batch", copy.deepcopy(BATCH))
    return asyncio.run(store.save(data))


def ask(store, action="dose", by="Ben", **data):
    if action == "dose":
        data = {"pump": "balance", "ml": 25, **data}
    return asyncio.run(store.request({"action": action, **data}, by))


def handled(hass, request_id):
    """What the controller publishes once it has taken a request (docs/DOSING.md, Status)."""
    hass.states.set(STATUS, "idle", {"handled": request_id})


def test_a_fresh_room_answers_with_an_empty_setup_and_what_it_could_use():
    hass, store = rig(
        states={
            "sensor.tank_ec": ha_stubs.FakeState(
                "2.1",
                {
                    "friendly_name": "Tank EC",
                    "unit_of_measurement": "mS/cm",
                    "device_class": "conductivity",
                },
            ),
            "light.room": "on",
            "cover.vent": "open",
        }
    )
    response = store.response()
    assert (response["schema_version"], response["room_id"]) == (1, "room:")
    assert response["config"] == dosing.empty() and response["error"] is None
    assert response["can_edit"] is False and store.response(can_edit=True)["can_edit"]
    offered = {c["entity_id"]: c for c in response["candidates"]}
    assert set(offered) == KNOWN | {"sensor.tank_ec"}  # no light, no cover
    assert offered["sensor.tank_ec"] == {
        "entity_id": "sensor.tank_ec",
        "name": "Tank EC",
        "domain": "sensor",
        "state": "2.1",
        "unit": "mS/cm",
        "device_class": "conductivity",
    }
    assert offered["switch.tank_fill"]["name"] == "switch.tank_fill"  # no friendly name
    assert [c["entity_id"] for c in response["candidates"]] == sorted(offered)
    assert {c["domain"] for c in response["candidates"]} <= set(
        dosing.CANDIDATE_DOMAINS
    )


def test_saving_moves_the_revision_and_a_stale_or_invalid_save_changes_nothing(
    dispatcher,
):
    _, store = rig()
    response = save(store)
    assert response["error"] is None and response["config"]["revision"] == 1
    assert response["config"]["pumps"][0]["dosing_prefix"] == "Dosing"
    assert response["config"]["updated_at"] == NOW.isoformat()
    assert store._store.saves == 1
    assert dispatcher.sent == ["crop_steering_dosing_changed_entry"]

    stale = save(store, expected_revision=0, pumps=[])
    assert stale["error"] == "revision"
    assert stale["config"]["revision"] == 1 and len(stale["config"]["pumps"]) == 1
    missing = save(store, pumps=[{**PUMP, "flow_entity": "number.nowhere"}])
    assert "number.nowhere does not exist" in missing["error"]
    assert store._store.saves == 1 and store.data["revision"] == 1
    assert len(dispatcher.sent) == 1


def test_a_pump_is_linked_only_to_a_stock_tank_the_room_has():
    hass, store = rig()
    linked = [{**PUMP, "stock_tank": "balance"}]
    assert "not one of this room's stock tanks" in save(store, pumps=linked)["error"]
    hass.data.setdefault(DOMAIN, {})["_stock"] = {
        "entry": SimpleNamespace(data={"tanks": [{"id": "balance"}]})
    }
    response = save(store, pumps=linked)
    assert response["error"] is None
    assert response["config"]["pumps"][0]["stock_tank"] == "balance"


def test_a_request_is_stored_for_the_controller_and_the_revision_does_not_move(
    dispatcher,
):
    _, store = rig()
    save(store)
    answer = ask(store, ml="12.5")
    request = answer["request"]
    assert answer["error"] is None
    assert re.fullmatch(r"[0-9a-f]{32}", request["id"])
    assert {k: v for k, v in request.items() if k != "id"} == {
        "action": "dose",
        "pump": "balance",
        "ml": 12.5,
        "at": NOW.isoformat(),
        "by": "Ben",
    }
    assert store.data["request"] == request and store.data["revision"] == 1
    assert store._store.value["request"] == request  # stored, not only in memory
    assert len(dispatcher.sent) == 2  # the sensor is rewritten for the controller
    batch = ask(handled_by(store), "batch", by=None)["request"]
    assert (batch["action"], batch["pump"], batch["ml"], batch["by"]) == (
        "batch",
        None,
        None,
        None,
    )


def handled_by(store):
    handled(store.hass, store.data["request"]["id"])
    return store


def test_a_dose_or_batch_waits_for_the_one_before_it_but_a_stop_always_gets_through():
    hass, store = rig()
    save(store)
    first = ask(store)["request"]
    assert ask(store) == {"request": None, "error": "busy"}
    assert ask(store, "batch") == {"request": None, "error": "busy"}
    assert save(store)["error"] == "busy"
    assert store.data["request"] == first
    stop = ask(store, "stop")["request"]
    assert stop["action"] == "stop" and store.data["request"] == stop
    assert ask(store, "stop")["error"] is None  # a stop is never refused
    handled(hass, store.data["request"]["id"])
    assert ask(store)["error"] is None
    handled(hass, store.data["request"]["id"])
    assert save(store)["error"] is None


def test_the_setup_is_never_changed_under_a_dose_or_batch_the_controller_reports():
    """A dose or a batch runs from the setup it read when it started: the pump ids, entities and
    recipe it holds must not change under it, whatever the stored request says."""
    hass, store = rig()
    save(store)
    for state in ("dosing", "batch"):
        hass.states.set(STATUS, state, {"handled": "some earlier request"})
        assert save(store)["error"] == "busy"
    assert store.data["revision"] == 1
    for state in ("idle", "unavailable"):
        hass.states.set(STATUS, state, {"handled": None})
        assert save(store)["error"] is None
    assert store.data["revision"] == 3


def test_a_request_the_controller_will_never_act_on_no_longer_blocks(clock):
    _, store = rig()
    save(store)
    ask(store)
    clock["at"] = NOW + timedelta(
        seconds=121
    )  # the controller was down: it never took it
    assert ask(store)["error"] is None
    clock["at"] += timedelta(seconds=121)
    assert save(store)["error"] is None


def test_a_dose_names_a_known_pump_and_an_amount_it_can_dose():
    _, store = rig()
    save(store)
    assert "unknown pump: bloom" in ask(store, pump="bloom")["error"]
    for ml in (0, -5, 2001):
        assert "more than 0 and at most 2000" in ask(store, ml=ml)["error"]
    assert (
        "more than 0"
        in asyncio.run(store.request({"action": "dose", "pump": "balance"}, None))[
            "error"
        ]
    )
    assert store.data["request"] is None and store._store.saves == 1


def test_the_sensor_the_controller_reads():
    _, store = rig()
    assert store.sensor() == (
        0,
        {"pumps": [], "batch": dosing.empty_batch(), "request": None},
    )
    save(store)
    ask(store)
    state, attributes = store.sensor()
    assert state == 1 and set(attributes) == {"pumps", "batch", "request"}
    assert attributes["pumps"][0]["power_entity"] == PUMP["power_entity"]
    assert attributes["batch"]["recipe"][0]["ml_entity"] == "number.recipe_balance"
    assert attributes["request"] == store.data["request"]
    # What the controller gets over REST, and a copy: changing it changes nothing stored.
    assert json.loads(json.dumps(attributes)) == attributes
    attributes["pumps"].clear()
    assert store.sensor()[1]["pumps"]


def test_the_status_it_reads_belongs_to_its_own_room():
    hass, store = rig(prefix="f1_")
    assert store.status_entity == "sensor.crop_steering_f1_dosing"
    save(store)
    request = ask(store)["request"]
    handled(hass, request["id"])  # another room's controller status: not this room's
    assert ask(store)["error"] == "busy"
    hass.states.set(
        "sensor.crop_steering_f1_dosing", "idle", {"handled": request["id"]}
    )
    assert ask(store)["error"] is None


def test_a_setup_saved_before_a_restart_loads_even_before_its_devices_are_back():
    _, store = rig()
    save(store)
    ask(store)
    stored = store._store.value
    _, again = rig(value=stored, states={e: None for e in KNOWN})
    assert again.error is None and again.data == stored


def test_a_corrupt_store_is_kept_and_every_change_refused():
    _, store = rig(value={"revision": "seven", "pumps": []})
    assert "not been overwritten" in store.error
    assert store.response()["error"] == store.error
    assert save(store, expected_revision=0)["error"] == store.error
    assert ask(store)["error"] == store.error
    assert store.sensor() == (None, {"error": store.error})
    assert store._store.saves == 0
    assert store._store.value == {"revision": "seven", "pumps": []}


def test_a_failed_save_changes_nothing():
    _, store = rig()
    save(store)

    async def broken(value):
        raise OSError("disk full")

    store._store.async_save = broken
    with pytest.raises(OSError):
        ask(store)
    assert store.data["request"] is None and store.data["revision"] == 1


@pytest.fixture
def services(monkeypatch):
    monkeypatch.setattr(
        sys.modules["homeassistant.core"],
        "SupportsResponse",
        SimpleNamespace(ONLY="only"),
        raising=False,
    )

    class Services(ha_stubs.FakeServices):
        def async_register(self, domain, name, handler, schema=None, **_response):
            super().async_register(domain, name, handler, schema)

    hass = ha_stubs.FakeHass(states={e: "off" for e in KNOWN})
    hass.services = Services()
    users = {
        "admin": SimpleNamespace(is_admin=True, name="Ben"),
        "staff": SimpleNamespace(is_admin=False, name="Staff phone"),
    }
    hass.auth = SimpleNamespace(async_get_user=AsyncMock(side_effect=users.get))
    entry = ha_stubs.FakeEntry(entry_id="entry")
    monkeypatch.setattr(dosing_api, "DosingStore", _memory_store)
    asyncio.run(dosing_api.async_setup_dosing(hass, entry))

    def call(name, user="admin", **data):
        request = SimpleNamespace(
            service=name,
            data={"room_id": "room:", **data},
            context=SimpleNamespace(user_id=user),
        )
        return asyncio.run(hass.services.registered[(DOMAIN, name)](request))

    return SimpleNamespace(hass=hass, call=call, entry=entry)


_REAL_STORE = dosing_api.DosingStore


def _memory_store(hass, entry):
    return _REAL_STORE(hass, entry, MemoryStore())


def test_the_services_find_the_room_and_record_who_asked(services):
    assert set(services.hass.services.registered) == {
        (DOMAIN, name) for name in dosing_api.SERVICES
    }
    assert services.call("dosing_get")["config"]["revision"] == 0
    # Whether the caller may save: an administrator only, and no one when there is no user.
    assert services.call("dosing_get")["can_edit"] is True
    assert services.call("dosing_get", user="staff")["can_edit"] is False
    assert services.call("dosing_get", user=None)["can_edit"] is False
    assert services.call("dosing_get", user="deleted")["can_edit"] is False
    saved = services.call(
        "dosing_save",
        expected_revision=0,
        pumps=[copy.deepcopy(PUMP)],
        batch=copy.deepcopy(BATCH),
    )
    assert saved["error"] is None and saved["config"]["revision"] == 1
    assert saved["can_edit"] is True
    stale = services.call(
        "dosing_save", user=None, expected_revision=0, pumps=[], batch={}
    )
    assert (stale["error"], stale["can_edit"]) == ("revision", False)
    assert (
        services.call("dosing_request", action="dose", pump="balance", ml=5)["request"][
            "by"
        ]
        == "Ben"
    )
    handled(services.hass, services.call("dosing_get")["config"]["request"]["id"])
    automation = services.call("dosing_request", user=None, action="stop")
    assert automation["request"]["by"] is None  # an automation has no user
    # A stop only switches things off: any signed-in user may ask for one, and is named.
    staff = services.call("dosing_request", user="staff", action="stop")
    assert (staff["error"], staff["request"]["by"]) == (None, "Staff phone")
    for action, data in (("dose", {"pump": "balance", "ml": 5}), ("batch", {})):
        with pytest.raises(HomeAssistantError, match="administrator"):
            services.call("dosing_request", user="staff", action=action, **data)
    with pytest.raises(HomeAssistantError, match="signed-in Home Assistant user"):
        services.call("dosing_request", user="deleted", action="stop")
    assert services.call("dosing_get")["config"]["request"] == staff["request"]
    with pytest.raises(HomeAssistantError, match="unknown or ambiguous"):
        services.call("dosing_get", room_id="room:f1_")
    with pytest.raises(HomeAssistantError, match="canonical room_id"):
        services.call("dosing_get", room_id="f1")
    asyncio.run(dosing_api.async_unload_dosing(services.hass, services.entry))
    assert services.hass.services.registered == {}
