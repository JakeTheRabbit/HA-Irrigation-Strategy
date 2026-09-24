"""The stock-tank store: revisions, refills, each fill counted once, and the low-stock Repairs card."""

import asyncio
import copy
from datetime import timedelta, timezone
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


def test_a_failed_save_changes_nothing():
    _, store = rig()
    mutate(store, "stock_save", tanks=[{**BLOOM, "level_l": 20}])

    async def broken(value):
        raise OSError("disk full")

    store._store.async_save = broken
    with pytest.raises(OSError):
        mutate(store, "stock_refill", id="bloom")
    assert store.data["tanks"][0]["level_l"] == 20 and store.data["revision"] == 1
