"""The stock-tank store: revisions, refills, each fill counted once, and the low-stock Repairs card."""

import asyncio
import copy
from datetime import datetime, timedelta, timezone
import sys
import types

import pytest

from . import ha_stubs

ha_stubs.install()

from custom_components.crop_steering import stock_api  # noqa: E402
from custom_components.crop_steering.const import DOMAIN  # noqa: E402

NZ = timezone(timedelta(hours=12))
FILL = "input_datetime.tank_filled_at"
BLOOM = {"name": "Bloom", "capacity_l": 50, "dose_ml": 1800, "low_l": 10}


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
    monkeypatch.setattr(
        sys.modules["homeassistant.util.dt"],
        "get_default_time_zone",
        lambda: NZ,
        raising=False,
    )
    return module


def rig(value=None, states=None, fill=FILL):
    hass = ha_stubs.FakeHass(
        states=states,
        data={DOMAIN: {"entry": {"hardware": {"tank_last_fill_sensor": fill}}}},
    )
    store = stock_api.StockStore(
        hass, ha_stubs.FakeEntry(entry_id="entry"), MemoryStore(value)
    )
    asyncio.run(store.async_init())
    return hass, store


def mutate(store, action, **data):
    data.setdefault("expected_revision", store.data["revision"])
    return asyncio.run(store.mutate(action, data))


def test_a_fresh_room_has_no_tanks_and_names_its_fill_entity():
    _, store = rig()
    response = store.response()
    assert (response["room_id"], response["revision"], response["tanks"]) == (
        "room:",
        0,
        [],
    )
    assert response["fill_entity"] == FILL
    assert response["error"] is None


def test_saving_refilling_and_a_stale_edit(dispatcher):
    _, store = rig()
    response = mutate(store, "stock_save", tanks=[{**BLOOM, "level_l": 20}])
    assert response["revision"] == 1 and response["tanks"][0]["level_l"] == 20
    assert store._store.saves == 1 and dispatcher.sent == [
        "crop_steering_stock_changed_entry"
    ]
    with pytest.raises(ValueError, match="changed elsewhere"):
        mutate(store, "stock_refill", id="bloom", expected_revision=0)
    assert mutate(store, "stock_refill", id="bloom")["tanks"][0]["level_l"] == 50
    assert (
        mutate(store, "stock_refill", id="bloom", level_l=31.5)["tanks"][0]["level_l"]
        == 31.5
    )


def test_the_low_card_comes_with_the_batches_left_and_goes_on_refill():
    hass, store = rig()
    mutate(store, "stock_save", tanks=[{**BLOOM, "level_l": 8}])
    card = hass._issues["stock_low"]
    assert card["translation_key"] == "stock_low"
    assert card["translation_placeholders"]["count"] == "1"
    assert (
        "Bloom: 8 L of 50 L, about 4 batches left"
        in card["translation_placeholders"]["tanks"]
    )
    assert store.response()["low"] == ["bloom"]
    mutate(store, "stock_refill", id="bloom")
    assert "stock_low" not in hass._issues


def test_each_fill_draws_once_with_what_the_dose_entity_reads():
    hass, store = rig(states={"number.doser_bloom": "1000"})
    mutate(store, "stock_save", tanks=[{**BLOOM, "dose_entity": "number.doser_bloom"}])
    asyncio.run(
        store._fill("2026-09-24 19:16:08")
    )  # set up after this fill: a starting point
    assert store.data["tanks"][0]["level_l"] == 50
    asyncio.run(store._fill("2026-09-25 19:02:00"))
    assert store.data["tanks"][0]["level_l"] == 49
    assert store.data["history"][0]["source"] == "fill"
    assert store.data["history"][0]["draw_ml"] == {"bloom": 1000.0}
    for replay in ("2026-09-25 19:02:00", "unavailable", "2026-09-20 08:00:00"):
        asyncio.run(store._fill(replay))
    assert store.data["tanks"][0]["level_l"] == 49
    # The doser reads nothing usable: the fixed dose stands in.
    hass.states.set("number.doser_bloom", "unavailable")
    asyncio.run(store._fill("2026-09-26 19:00:00"))
    assert store.data["tanks"][0]["level_l"] == 47.2


def test_a_restart_keeps_the_levels_and_the_counted_fill():
    _, store = rig()
    mutate(store, "stock_save", tanks=[BLOOM])
    asyncio.run(store._fill("2026-09-24 19:16:08"))
    asyncio.run(store._fill("2026-09-25 19:02:00"))
    _, again = rig(value=store._store.value)
    assert again.data["tanks"][0]["level_l"] == 48.2
    asyncio.run(
        again._fill("2026-09-25 19:02:00")
    )  # HA restarted: the same time comes back
    assert again.data["tanks"][0]["level_l"] == 48.2
    assert again.data["tanks"][0]["id"] == "bloom"


def test_a_batch_recorded_by_hand_takes_the_fixed_dose():
    _, store = rig(fill="")
    mutate(store, "stock_save", tanks=[BLOOM])
    response = mutate(store, "stock_record_batch")
    assert response["tanks"][0]["level_l"] == 48.2
    assert response["history"][0]["source"] == "manual"
    assert response["fill_entity"] is None


def test_a_corrupt_store_is_kept_and_every_change_refused():
    _, store = rig(value={"revision": "seven", "tanks": []})
    assert "not been overwritten" in store.error
    with pytest.raises(ValueError, match="not been overwritten"):
        mutate(store, "stock_save", tanks=[BLOOM])
    asyncio.run(store._fill("2026-09-25 19:02:00"))
    assert store._store.saves == 0 and store._store.value == {
        "revision": "seven",
        "tanks": [],
    }


def _link(hass, **tanks):
    """The room's dosing setup, linking stock tanks to pumps (docs/DOSING.md, Stock tanks)."""
    pumps = [{"id": pump, "stock_tank": tank} for tank, pump in tanks.items()]
    hass.data[DOMAIN].setdefault("_dosing", {})["entry"] = types.SimpleNamespace(
        data={"pumps": pumps}, error=None
    )


def test_what_a_dose_drew_is_counted_once_and_warns_when_low(dispatcher):
    hass, store = rig()
    mutate(store, "stock_save", tanks=[{**BLOOM, "level_l": 10.02}])
    draw = {"key": ":bloom:2026-09-28T01:00:00+00:00", "source": "dose"}
    answer = asyncio.run(store.draw({**draw, "draws": {"bloom": 25, "cal": 5}}))
    assert (answer["counted"], answer["duplicate"], answer["skipped"]) == (
        True,
        False,
        ["cal"],
    )
    assert answer["revision"] == 2 and answer["tanks"][0]["level_l"] == 9.995
    assert answer["history"][0]["key"] == draw["key"]
    assert hass._issues["stock_low"]["translation_placeholders"]["count"] == "1"
    assert dispatcher.sent[-1] == "crop_steering_stock_changed_entry"
    # Sent again (the controller did not hear back): nothing moves.
    again = asyncio.run(store.draw({**draw, "draws": {"bloom": 25}}))
    assert (again["counted"], again["duplicate"], again["revision"]) == (False, True, 2)
    assert again["tanks"][0]["level_l"] == 9.995
    assert store._store.value["draw_keys"] == [draw["key"]]
    # A restart keeps the keys it has counted.
    _, reloaded = rig(value=store._store.value)
    repeat = asyncio.run(reloaded.draw({**draw, "draws": {"bloom": 25}}))
    assert repeat["duplicate"] and repeat["tanks"][0]["level_l"] == 9.995


def test_a_fill_skips_the_tanks_a_dosing_pump_draws():
    hass, store = rig()
    cal = {"name": "Cal", "capacity_l": 5, "dose_ml": 250}
    mutate(store, "stock_save", tanks=[BLOOM, cal])
    _link(hass, bloom="bloom_pump")
    assert store.linked() == {"bloom": "bloom_pump"}
    asyncio.run(store._fill("2026-09-24 19:16:08"))
    asyncio.run(store._fill("2026-09-25 19:02:00"))  # a batch Crop Steering stamped
    assert [t["level_l"] for t in store.data["tanks"]] == [50, 4.75]
    assert store.data["history"][0]["draw_ml"] == {"cal": 250.0}
    # Cal linked too: a fill draws nothing and is not logged, though it is still the newest.
    _link(hass, bloom="bloom_pump", cal="cal_pump")
    asyncio.run(store._fill("2026-09-26 19:00:00"))
    assert [t["level_l"] for t in store.data["tanks"]] == [50, 4.75]
    assert len(store.data["history"]) == 1
    assert store.data["last_batch"] == "2026-09-26T19:00:00+12:00"


def test_a_batch_recorded_by_hand_skips_the_tanks_a_dosing_pump_draws():
    """A batch the controller made draws its linked tanks dose by dose (stock_draw); recorded by
    hand as well, it must not take them a second time. The answer says which it skipped.
    """
    hass, store = rig(fill="")
    cal = {"name": "Cal", "capacity_l": 5, "dose_ml": 250}
    mutate(store, "stock_save", tanks=[BLOOM, cal])
    _link(hass, bloom="bloom_pump")
    response = mutate(store, "stock_record_batch")
    assert [t["level_l"] for t in response["tanks"]] == [50, 4.75]
    assert response["skipped"] == ["bloom"]
    assert response["history"][0] == {
        "at": response["history"][0]["at"],
        "source": "manual",
        "draw_ml": {"cal": 250.0},
    }
    # Unlinked again (the pump was removed from the dosing setup): it is drawn as before.
    _link(hass)
    response = mutate(store, "stock_record_batch")
    assert [t["level_l"] for t in response["tanks"]] == [48.2, 4.5]
    assert response["skipped"] == []
    assert "skipped" not in mutate(store, "stock_refill", id="bloom")


def test_a_corrupt_store_refuses_a_draw_too():
    _, store = rig(value={"revision": "seven", "tanks": []})
    with pytest.raises(ValueError, match="not been overwritten"):
        asyncio.run(store.draw({"key": "k", "draws": {"bloom": 5}, "source": "dose"}))
    assert store._store.saves == 0


def test_a_failed_save_changes_nothing():
    _, store = rig()
    mutate(store, "stock_save", tanks=[{**BLOOM, "level_l": 20}])

    async def broken(value):
        raise OSError("disk full")

    store._store.async_save = broken
    with pytest.raises(OSError):
        mutate(store, "stock_refill", id="bloom")
    assert store.data["tanks"][0]["level_l"] == 20 and store.data["revision"] == 1


# ------------------------------------------------------------------ what the pumps run
# The room's real doser (a 5.1.x ESPHome peristaltic doser), as Home Assistant recorded its doses on
# 27 Sep 2026: an automation pressed its dose button, its status read "Running (Manual)" (which the
# setup's default dosing prefix "Dosing" never matches) and its power switch read on, for
# 27.129756 s at its calibrated 11.061206817627 mL/s: 300 mL, the dose its volume number held.
T0 = datetime(2026, 9, 27, 21, 32, 0, 102000, tzinfo=timezone.utc)
POWER = "switch.doser_balance_pump_power"
STATUS = "sensor.doser_balance_pump_status"
FLOW = "sensor.doser_balance_flow_rate"
PUMP = {
    "id": "balance",
    "name": "Balance",
    "volume_entity": "number.doser_balance_dose_amount",
    "start_entity": "button.doser_balance_dose_now",
    "dosing_entity": STATUS,
    "dosing_prefix": "Dosing",
    "power_entity": POWER,
    "flow_entity": FLOW,
    "max_ml": 2000,
    "restore_volume": True,
    "stock_tank": "balance",
}
BALANCE = {"name": "Balance", "capacity_l": 20, "dose_ml": 300, "low_l": 5}
CAL = {"name": "Cal", "capacity_l": 5, "dose_ml": 250, "low_l": 1}


@pytest.fixture
def tracker(monkeypatch):
    """homeassistant.helpers.event as the stock tanks use it: which entities they follow."""
    module = types.ModuleType("homeassistant.helpers.event")
    module.followed = []

    def track(hass, entities, action):
        followed = {"entities": list(entities), "live": True}
        module.followed.append(followed)
        return lambda: followed.update(live=False)

    module.async_track_state_change_event = track
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.event", module)
    return module


def pumped(value=None, level=10, pumps=(PUMP,)):
    """A room whose Balance stock tank is linked to the Balance dosing pump, idle; Cal is linked
    to nothing."""
    hass, store = rig(
        value=value,
        states={POWER: "off", STATUS: "Stopped", FLOW: "11.061206817627"},
    )
    hass.tasks = []
    hass.async_create_task = hass.tasks.append
    if value is None:
        mutate(store, "stock_save", tanks=[{**BALANCE, "level_l": level}, CAL])
    hass.data[DOMAIN]["_dosing"] = {
        "entry": types.SimpleNamespace(data={"pumps": list(pumps)}, error=None)
    }
    store._watch()
    return hass, store


def report(hass, store, seconds, states):
    """The doser reports these states, `seconds` after T0, and whatever that starts is done."""
    for entity, state in states.items():
        hass.states.set(entity, state, last_changed=T0 + timedelta(seconds=seconds))
        store._changed(hass.states.get(entity))
    while hass.tasks:
        asyncio.run(hass.tasks.pop(0))


def level(store, tank="balance"):
    return next(t["level_l"] for t in store.data["tanks"] if t["id"] == tank)


def test_a_dose_however_it_was_started_draws_its_stock_tank_once(tracker):
    hass, store = pumped()
    assert tracker.followed[-1] == {"entities": [STATUS, POWER], "live": True}
    report(hass, store, 0, {STATUS: "Running (Manual)", POWER: "on"})
    report(hass, store, 5, {POWER: "on"})  # the same state again
    assert level(store) == 10  # drawn when it stops
    report(hass, store, 27.129, {STATUS: "Stopped"})
    report(hass, store, 27.13, {POWER: "off"})
    assert level(store) == 9.6999
    assert store.data["history"][0] == {
        "at": (T0 + timedelta(seconds=27.13)).isoformat(),
        "source": "pump",
        "draw_ml": {"balance": 300.1},
        "key": f"pump:balance:{T0.isoformat()}",
        "note": "Balance ran 27.1 s at 11.0612 mL/s",
    }
    # Reported again, or the same run's end taken twice: nothing more.
    report(hass, store, 30, {STATUS: "Stopped", POWER: "off"})
    run = {"since": T0, "flow": "11.061206817627"}
    asyncio.run(store._draw_run(PUMP, run, T0 + timedelta(seconds=27.13)))
    assert level(store) == 9.6999 and len(store.data["history"]) == 1
    assert level(store, "cal") == 5  # no pump: only a fill or a batch by hand draws it


def test_the_controllers_report_of_a_dose_the_pump_ran_is_not_counted_again(tracker):
    """One source for a linked tank: its pump's runs. The controller still reports each dose
    (stock_draw); the tank it names is left alone, and the answer says so."""
    hass, store = pumped()
    report(hass, store, 0, {POWER: "on"})
    report(hass, store, 2.26, {POWER: "off"})  # the controller's 25 mL dose
    assert level(store) == 9.975
    draw = {"key": f":balance:{T0.isoformat()}", "source": "dose"}
    answer = asyncio.run(store.draw({**draw, "draws": {"balance": 25}}))
    assert (answer["counted"], answer["duplicate"], answer["skipped"]) == (
        False,
        False,
        [],
    )
    assert answer["linked"] == ["balance"] and answer["tanks"][0]["level_l"] == 9.975
    # A tank no pump is linked to is drawn by a report as before.
    answer = asyncio.run(
        store.draw({**draw, "key": "k2", "draws": {"balance": 25, "cal": 50}})
    )
    assert (answer["counted"], answer["linked"]) == (True, ["balance"])
    assert [t["level_l"] for t in answer["tanks"]] == [9.975, 4.95]


def test_a_restart_in_the_middle_of_a_dose_draws_it_once(tracker):
    hass, store = pumped()
    report(hass, store, 0, {STATUS: "Running (Manual)", POWER: "on"})
    # The room reloads mid-dose (a setup change): the store that stopped never draws the run,
    # and the new one finds the pump running since its power switch went on.
    reloaded = stock_api.StockStore(
        hass, ha_stubs.FakeEntry(entry_id="entry"), store._store
    )
    asyncio.run(reloaded.async_init())
    reloaded._watch()
    report(hass, reloaded, 27.13, {STATUS: "Stopped", POWER: "off"})
    assert level(reloaded) == 9.6999 and len(reloaded.data["history"]) == 1
    assert reloaded.data["history"][0]["key"] == f"pump:balance:{T0.isoformat()}"
    # Home Assistant restarted mid-dose: the doser comes back running, 100 s in. What ran while
    # Home Assistant was down is not seen, and never guessed at: the rest is drawn, once.
    for entity, state in ((STATUS, "Running (Manual)"), (POWER, "on")):
        hass.states.set(entity, state, last_changed=T0 + timedelta(seconds=100))
    restarted = stock_api.StockStore(
        hass, ha_stubs.FakeEntry(entry_id="entry"), store._store
    )
    asyncio.run(restarted.async_init())
    restarted._watch()
    report(hass, restarted, 117.13, {STATUS: "Stopped", POWER: "off"})
    assert restarted.data["history"][0]["draw_ml"] == {"balance": 189.5}
    assert level(restarted) == 9.5104 and len(restarted.data["history"]) == 2


def test_a_run_never_draws_its_tank_below_empty(tracker):
    hass, store = pumped(level=0.1)
    report(hass, store, 0, {POWER: "on"})
    report(hass, store, 27.13, {POWER: "off"})
    assert level(store) == 0
    assert store.data["history"][0]["draw_ml"] == {"balance": 100.0}


def test_a_run_ends_when_the_doser_drops_off_and_needs_a_flow(tracker, caplog):
    hass, store = pumped()
    report(hass, store, 0, {POWER: "on"})
    report(
        hass, store, 10, {POWER: "unavailable"}
    )  # only what it was seen running counts
    assert store.data["history"][0]["draw_ml"] == {"balance": 110.6}
    hass.states.set(FLOW, "unavailable")
    report(hass, store, 20, {POWER: "on"})
    report(hass, store, 30, {POWER: "off"})
    assert len(store.data["history"]) == 1 and level(store) == 9.8894
    assert "reads nothing usable" in caplog.text


def test_a_firmware_that_says_dosing_is_followed_by_its_dosing_entity(tracker):
    """A doser whose power switch does not move during its own timed dose: its dosing entity
    (a binary sensor here) is enough."""
    binary = {**PUMP, "dosing_entity": "binary_sensor.doser_balance_dosing"}
    hass, store = pumped(pumps=[binary])
    report(hass, store, 0, {"binary_sensor.doser_balance_dosing": "on"})
    report(hass, store, 2.26, {"binary_sensor.doser_balance_dosing": "off"})
    assert store.data["history"][0]["draw_ml"] == {"balance": 25.0}


def test_a_pump_unlinked_is_no_longer_followed(tracker):
    hass, store = pumped()
    report(hass, store, 0, {POWER: "on"})
    hass.data[DOMAIN]["_dosing"]["entry"].data["pumps"] = [{**PUMP, "stock_tank": None}]
    store._watch()  # the dosing setup was saved
    assert tracker.followed[-1]["live"] is False
    report(hass, store, 27.13, {POWER: "off"})
    assert level(store) == 10 and store.data["history"] == []


def test_a_store_from_before_this_loads_and_its_linked_tank_follows_its_pump(tracker):
    """UPGRADE IN PLACE: a stock document as an older integration left it (no draw keys, a
    history of fills that drew nothing) loads unchanged, and its linked tank is drawn.
    """
    old = {
        "revision": 41,
        "tanks": [
            {
                "id": "balance",
                "name": "Balance",
                "capacity_l": 20.0,
                "level_l": 10.0,
                "dose_ml": 300.0,
                "dose_entity": "number.doser_balance_dose_amount",
                "low_l": 5.0,
                "refilled_at": None,
                "updated_at": "2026-09-29T09:12:00+00:00",
            }
        ],
        "last_batch": "2026-10-03T20:39:54+13:00",
        "history": [
            {"at": "2026-10-03T20:39:54+13:00", "source": "fill", "draw_ml": {}}
        ]
        * 30,
    }
    hass, store = pumped(value=old)
    assert store.error is None
    assert store.data["tanks"] == old["tanks"] and store.data["draw_keys"] == []
    report(hass, store, 0, {POWER: "on"})
    report(hass, store, 27.13, {POWER: "off"})
    assert level(store) == 9.6999
    assert store._store.value["history"][0]["source"] == "pump"
    assert len(store._store.value["history"]) == 30
    assert store._store.value["revision"] == 42
