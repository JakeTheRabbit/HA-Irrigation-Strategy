"""The batch tank's refill reminder in the dosing setup (docs/DOSING.md, Refill reminder): a tank
level entity and a reminder level, off by default, refused without the entity that reads the level,
and kept by a save that does not send them, so a page that does not know them never switches the
reminder off. A store saved before the reminder loads with it off."""

import copy

import pytest

from custom_components.crop_steering import dosing

from .test_dosing import BATCH, KNOWN, PUMP
from .test_dosing_api import rig, save

LEVEL = "sensor.tank_level"


def clean(**batch):
    return dosing.clean(
        [copy.deepcopy(PUMP)],
        {**copy.deepcopy(BATCH), **batch},
        {*KNOWN, LEVEL, "input_number.tank_level"}.__contains__,
    )[1]


def test_the_reminder_is_off_by_default_and_needs_the_level_it_reads():
    assert (
        dosing.empty_batch()["level_entity"],
        dosing.empty_batch()["remind_pct"],
    ) == (None, 0)
    off = clean()
    assert (off["level_entity"], off["remind_pct"]) == (None, 0)
    on = clean(level_entity=LEVEL, remind_pct=20)
    assert (on["level_entity"], on["remind_pct"]) == (LEVEL, 20)
    assert (
        clean(level_entity="input_number.tank_level", remind_pct=15.5)["remind_pct"]
        == 15.5
    )
    with pytest.raises(
        dosing.DosingError, match="needs the entity that reads the tank's level"
    ):
        clean(remind_pct=20)
    with pytest.raises(dosing.DosingError, match="between 0 and 100"):
        clean(level_entity=LEVEL, remind_pct=120)
    with pytest.raises(dosing.DosingError, match="tank level entity must be"):
        clean(level_entity="switch.tank_level", remind_pct=20)
    with pytest.raises(dosing.DosingError, match="does not exist"):
        clean(level_entity="sensor.other_tank", remind_pct=20)


def test_a_save_that_does_not_send_the_reminder_keeps_it():
    _hass, store = rig(states={LEVEL: "40"})
    assert (
        save(
            store,
            batch={**copy.deepcopy(BATCH), "level_entity": LEVEL, "remind_pct": 20},
        )["error"]
        is None
    )
    assert (
        save(store, batch=copy.deepcopy(BATCH))["error"] is None
    )  # the page as it was
    kept = store.data["batch"]
    assert (kept["level_entity"], kept["remind_pct"], store.data["revision"]) == (
        LEVEL,
        20,
        2,
    )
    assert store.sensor()[1]["batch"]["remind_pct"] == 20  # what the controller reads
    assert (
        save(
            store, batch={**copy.deepcopy(BATCH), "remind_pct": 0, "level_entity": None}
        )["error"]
        is None
    )  # switched off when sent
    assert (store.data["batch"]["level_entity"], store.data["batch"]["remind_pct"]) == (
        None,
        0,
    )


def test_a_store_saved_before_the_reminder_loads_with_it_off():
    old = {"revision": 3, "pumps": [copy.deepcopy(PUMP)], "batch": copy.deepcopy(BATCH)}
    old["batch"]["recipe"] = []
    _hass, store = rig(old)
    assert store.error is None and store.data["revision"] == 3
    assert (store.data["batch"]["level_entity"], store.data["batch"]["remind_pct"]) == (
        None,
        0,
    )
