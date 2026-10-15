"""The feed EC watering compares pore EC with, in a real Home Assistant with the real controller: a
measured feed EC probe first, then the EC the feed recipe in use today declares (saved through the real
dosing_save, published on sensor.crop_steering_dosing_config), then 3.0.

A declared value can't catch a mis-mixed tank, so a mapped probe always wins: a room upgraded from
3.11.1 with its probe and its dosing store waters on the probe's reading exactly as before, and still
does after a recipe declares an EC.
"""

from datetime import datetime, timezone

from conftest import fixture
from test_dosing import PUMP, _call, _devices
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, _upgrade

DOMAIN = "crop_steering"
SENSOR = "sensor.crop_steering_dosing_config"
FEED = {
    "recipes": [
        {
            "id": "bloom",
            "name": "Bloom",
            "doses": [{"pump": "balance", "ml": 300}],
            "ec": 2.4,
        }
    ],
    "stage": "bloom",  # picked by hand, no schedule: the recipe in use
}


def _feed_ecs(c, fake=None):
    """Each zone's feed EC in the snapshot the engine decides on (a zone with no moisture reading has
    none); with `fake`, every zone is first given a fresh moisture reading."""
    room, now = c.rooms[0], datetime.now()
    out = {}
    for zone in sorted(room.zones):
        if fake is not None:
            stamp = datetime.now(timezone.utc).isoformat()
            fake.set_state(
                f"sensor.crop_steering_{room.prefix}vwc_zone_{zone}",
                "50",
                last_updated=stamp,
            )
        snap, _params = c._snapshot(room, zone, now, True, False)
        if snap is not None:
            out[zone] = snap.feed_ec
    return out


async def test_a_recipe_declared_ec_reaches_the_real_controller_without_a_probe(
    hass, hass_admin_user, controller_for
):
    await _install(hass)
    _devices(hass)
    c, fake, _clock = controller_for()
    # No probe and no declared EC: 3.0, as before.
    assert set(_feed_ecs(c, fake).values()) == {3.0}

    saved = await _call(
        hass,
        hass_admin_user,
        "dosing_save",
        expected_revision=0,
        pumps=[PUMP],
        batch={},
        feed=FEED,
    )
    assert saved["error"] is None and saved["feed_now"]["ec"] == 2.4
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).attributes["feed"]["ec"] == 2.4
    c, fake, _clock = controller_for()
    assert set(_feed_ecs(c, fake).values()) == {2.4}
    assert c._read_feed_ec(c.rooms[0]) is None  # the source-water gate never runs on it


async def test_a_3_11_1_room_waters_on_its_feed_probe_before_and_after_a_recipe_declares_an_ec(
    hass, hass_storage, hass_admin_user, controller_for
):
    """UPGRADE IN PLACE: F-3111 maps a feed EC probe (2.2 mS/cm) and has a dosing store from before
    feed recipes declared an EC."""
    seed = fixture(JEV_3_11_1)
    dosing = fixture("dosing_3_11_1.json")["dosing"]
    store = f"{DOMAIN}.dosing.{seed['entry_id']}"
    hass_storage[store] = {
        "version": 1,
        "minor_version": 1,
        "key": store,
        "data": dosing,
    }
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    assert hass.states.get(SENSOR).attributes["feed"]["ec"] is None
    c, _fake, _clock = controller_for()
    before = _feed_ecs(c)
    assert before and set(before.values()) == {2.2}

    doc = await _call(hass, hass_admin_user, "dosing_get")
    config = doc["config"]
    pump = config["pumps"][0]["id"]
    feed = {
        "recipes": [
            {
                "id": "bloom",
                "name": "Bloom",
                "doses": [{"pump": pump, "ml": 5}],
                "ec": 2.8,
            }
        ],
        "stage": "bloom",
    }
    saved = await _call(
        hass,
        hass_admin_user,
        "dosing_save",
        expected_revision=config["revision"],
        pumps=config["pumps"],
        batch=config["batch"],
        feed=feed,
    )
    assert saved["error"] is None, saved["error"]
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).attributes["feed"]["ec"] == 2.8
    c, _fake, _clock = controller_for()
    assert _feed_ecs(c) == before  # the measured probe still wins
    assert c._read_feed_ec(c.rooms[0]) == 2.2  # and the source-water gate runs on it
