"""Stock tanks in a real Home Assistant: the services through its registry and schemas, each batch
counted once from the tank's last-fill entity (a reload of the room included), the low-stock
Repairs card, and the room's stock sensor an automation can push a phone alert from."""

from homeassistant.core import Context
from homeassistant.helpers import issue_registry as ir
from test_setup_entry import _install

DOMAIN = "crop_steering"
ROOM = "room:"
FILL = "sensor.batch_tank_last_fill"
DOSE = "number.doser_bloom_dose"
SENSOR = "sensor.crop_steering_stock_low"


async def _service(hass, admin, name, **data):
    return await hass.services.async_call(
        DOMAIN,
        name,
        {"room_id": ROOM, **data},
        blocking=True,
        return_response=True,
        context=Context(user_id=admin.id),
    )


async def _fill(hass, when):
    hass.states.async_set(FILL, when, {"device_class": "timestamp"})
    await hass.async_block_till_done()


async def test_each_batch_draws_once_warns_when_low_and_a_refill_clears_it(
    hass, hass_admin_user
):
    # The tank was last filled before the stock tanks were set up: that fill is not counted.
    hass.states.async_set(
        FILL, "2026-09-24T07:16:08+00:00", {"device_class": "timestamp"}
    )
    hass.states.async_set(DOSE, "1800", {"unit_of_measurement": "mL"})
    entry = await _install(hass, {"tank_last_fill_sensor": FILL})

    doc = await _service(hass, hass_admin_user, "stock_get")
    assert (doc["tanks"], doc["fill_entity"]) == ([], FILL)
    doc = await _service(
        hass,
        hass_admin_user,
        "stock_save",
        expected_revision=doc["revision"],
        tanks=[
            {
                "name": "Bloom",
                "capacity_l": 10,
                "dose_ml": 500,
                "dose_entity": DOSE,
                "low_l": 7,
            }
        ],
    )
    assert doc["tanks"][0]["level_l"] == 10 and doc["doses"] == {"bloom": 1800.0}
    assert hass.states.get(SENSOR).state == "0"

    # A new fill is one batch; the same time coming back (a device reconnecting) is not.
    await _fill(hass, "2026-09-25T07:02:00+00:00")
    await _fill(hass, "unavailable")
    await _fill(hass, "2026-09-25T07:02:00+00:00")
    doc = await _service(hass, hass_admin_user, "stock_get")
    assert doc["tanks"][0]["level_l"] == 8.2
    assert doc["history"][0]["draw_ml"] == {"bloom": 1800.0}

    await _fill(hass, "2026-09-26T07:00:00+00:00")
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "stock_low")
    assert issue is not None and issue.translation_placeholders["count"] == "1"
    assert "about 3 batches left" in issue.translation_placeholders["tanks"]
    state = hass.states.get(SENSOR)
    assert state.state == "1"
    assert state.attributes["tanks"][0]["level_l"] == 6.4
    assert state.attributes["tanks"][0]["batches_left"] == 3

    # A setup change reloads the room: the level and the counted fill survive it.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    doc = await _service(hass, hass_admin_user, "stock_get")
    assert doc["tanks"][0]["level_l"] == 6.4

    doc = await _service(
        hass, hass_admin_user, "stock_refill", expected_revision=doc["revision"], id="bloom"
    )
    assert doc["tanks"][0]["level_l"] == 10
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, "stock_low") is None
    assert hass.states.get(SENSOR).state == "0"


async def test_a_room_without_a_fill_entity_records_batches_by_hand(
    hass, hass_admin_user
):
    await _install(hass)
    doc = await _service(hass, hass_admin_user, "stock_get")
    assert doc["fill_entity"] is None
    doc = await _service(
        hass,
        hass_admin_user,
        "stock_save",
        expected_revision=doc["revision"],
        tanks=[{"name": "Part A", "capacity_l": 5, "dose_ml": 250}],
    )
    doc = await _service(
        hass, hass_admin_user, "stock_record_batch", expected_revision=doc["revision"]
    )
    assert doc["tanks"][0]["level_l"] == 4.75
    assert doc["history"][0]["source"] == "manual"
