"""The reservoir minimum is open on upgrade, in a real Home Assistant.

An upgraded room has no tank level mapped until its operator maps one, so the minimum, the plan-ahead refill and
the overfill guard never hold it. A batch tank's full float is not a level: the 3.11.1 room's dosing store
(tests_ha/fixtures/dosing_3_11_1.json, F-3111) and the 3.8 room's stock and dosing stores
(tests_ha/fixtures/stock_dosing_3_8.json, F-38) both carry one, read empty and read full, and the REAL controller
holds neither room on the minimum, publishes no tank level and raises no reservoir card.
"""

import pytest

from conftest import fixture
from test_upgrade_in_place import JEV_3_11_1, _upgrade

DOMAIN = "crop_steering"


def _seed(hass_storage, entry_id, stores):
    for name, data in stores.items():
        key = f"{DOMAIN}.{name}.{entry_id}"
        hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": data}


async def _f3111(hass, hass_storage):
    seed = fixture(JEV_3_11_1)
    _seed(hass_storage, seed["entry_id"], {"dosing": fixture("dosing_3_11_1.json")["dosing"]})
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    return "binary_sensor.tank_full", ("off", "on")


async def _f38(hass, hass_storage):
    seed = fixture("stock_dosing_3_8.json")
    entry = "entry_2_17_wizard.json"
    _seed(hass_storage, fixture(entry)["entry_id"], {name: seed[name] for name in ("stock", "dosing")})
    for entity_id, state in seed["states"].items():
        hass.states.async_set(entity_id, state)
    await _upgrade(hass, entry)
    return "sensor.batch_tank_float", ("Empty", "Full")


@pytest.mark.parametrize("install", [_f3111, _f38], ids=["F-3111", "F-38"])
async def test_a_dosing_store_with_a_full_float_never_holds_on_the_minimum(
    hass, hass_storage, controller_for, install
):
    full_float, states = await install(hass, hass_storage)
    for state in states:
        hass.states.async_set(full_float, state)
        await hass.async_block_till_done()
        c, fake, _clock = controller_for()
        room = c.rooms[0]
        assert room.tank == {}
        assert c._tank_hold(room) is None and c._tank_over(room) is False
        held = c._blocked(room, 1)
        assert held is None or "tank" not in held.split("(")[0], held
        c._watch_tank(room)
        assert not [e for e in fake.sets if e.endswith("tank_level")]
        titles = [
            data["title"]
            for domain, service, data in fake.calls
            if (domain, service) == ("persistent_notification", "create")
        ]
        assert not [t for t in titles if "(CS-9" in t], titles
