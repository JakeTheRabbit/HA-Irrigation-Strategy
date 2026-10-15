"""The feed schedule in a real Home Assistant (docs/DOSING.md, Feed schedule): each week of the grow
doses its own feed recipe from the day Week 1 starts; sensor.crop_steering_dosing_config, which the
controller app reads, carries that week's recipe; at Home Assistant's midnight that starts a new week
it moves on by itself, and the REAL controller's next batch doses the new week's recipe. A recipe
picked by hand while the schedule runs holds until the schedule's next week starts. A dosing store
saved by 3.11.1, from before the schedule, loads in place with none and doses its own recipe.
"""

from datetime import datetime
from types import SimpleNamespace

from conftest import fixture
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from test_dosing import PUMP, _call, _devices
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, _upgrade

DOMAIN = "crop_steering"
SENSOR = "sensor.crop_steering_dosing_config"
FEED = {
    "recipes": [
        {"id": rid, "name": rid.title(), "doses": [{"pump": "balance", "ml": ml}]}
        for rid, ml in (("vege", 200), ("bloom", 300), ("fade", 100))
    ],
    # Week 1 from Monday 5 October: Vege, then Bloom, Bloom, Fade.
    "schedule": {"start": "2026-10-05", "weeks": ["vege", "bloom", "bloom", "fade"]},
}


def _local(hass, *parts):
    return datetime(*parts, tzinfo=dt_util.get_time_zone(hass.config.time_zone))


def _shown(hass):
    """What the controller is shown: which feed recipe and why, and the batch's doses."""
    attributes = hass.states.get(SENSOR).attributes
    doses = [(dose["pump"], dose["ml"]) for dose in attributes["batch"]["recipe"]]
    return attributes["feed"], doses


async def test_the_schedule_moves_the_recipe_at_midnight_and_a_pick_holds_until_next_week(
    hass, hass_admin_user, freezer, controller_for
):
    freezer.move_to(_local(hass, 2026, 10, 7, 12, 0))  # Wednesday of week 1
    await _install(hass)
    _devices(hass)
    saved = await _call(
        hass,
        hass_admin_user,
        "dosing_save",
        expected_revision=0,
        pumps=[PUMP],
        batch={},
        feed=FEED,
    )
    assert saved["error"] is None and saved["feed_now"]["recipe"] == "Vege"
    await hass.async_block_till_done()
    feed, doses = _shown(hass)
    assert (feed["recipe"], feed["week"], feed["source"], doses) == (
        "Vege",
        1,
        "schedule",
        [("balance", 200)],
    )

    # Picked by hand: it holds until week 2 starts, Monday 12 October.
    picked = await _call(
        hass,
        hass_admin_user,
        "dosing_save",
        expected_revision=1,
        pumps=[PUMP],
        batch={},
        feed={**FEED, "stage": "fade"},
    )
    assert picked["error"] is None
    await hass.async_block_till_done()
    feed, doses = _shown(hass)
    assert (feed["recipe"], feed["source"], feed["held_until"], doses) == (
        "Fade",
        "held",
        "2026-10-12",
        [("balance", 100)],
    )

    # Home Assistant's midnight that starts week 2: Bloom, the hold over, with nobody touching it.
    midnight = _local(hass, 2026, 10, 12, 0, 0, 1)
    freezer.move_to(midnight)
    async_fire_time_changed(hass, dt_util.as_utc(midnight))
    await hass.async_block_till_done()
    feed, doses = _shown(hass)
    assert (feed["recipe"], feed["week"], feed["source"], feed["held_until"]) == (
        "Bloom",
        2,
        "schedule",
        None,
    )
    assert doses == [("balance", 300)]

    # The REAL controller, reading that sensor as REST sends it, plans its next batch on Bloom.
    c, _fake, _clock = controller_for()
    room = c.rooms[0]
    config = c.dosing._config(room)
    why, plan = c.dosing._batch_check(SimpleNamespace(room=room, config=config))
    assert why is None
    assert [(pump["id"], ml) for pump, ml, _flow in plan] == [("balance", 300)]


async def test_a_3_11_1_dosing_store_loads_with_no_schedule_and_doses_its_own_recipe(
    hass, hass_storage, hass_admin_user
):
    """UPGRADE IN PLACE: the 3.11.1 room's dosing store (F-3111) has no feed schedule."""
    seed = fixture(JEV_3_11_1)
    dosing = fixture("dosing_3_11_1.json")["dosing"]
    store = f"{DOMAIN}.dosing.{seed['entry_id']}"
    hass_storage[store] = {"version": 1, "minor_version": 1, "key": store, "data": dosing}
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    shown = hass.states.get(SENSOR)
    assert shown.attributes["batch"] == dosing["batch"]
    assert (shown.attributes["feed"]["recipe"], shown.attributes["feed"]["source"]) == (
        None,
        "batch",
    )
    doc = await _call(hass, hass_admin_user, "dosing_get")
    assert doc["error"] is None and doc["config"]["revision"] == dosing["revision"]
    assert doc["config"]["feed"] == {
        "recipes": [],
        "schedule": {"start": None, "weeks": []},
        "stage": None,
        "held_until": None,
    }
