"""Stock tanks in a real Home Assistant: the services through its registry and schemas, each batch
counted once from the tank's last-fill entity (a reload of the room included), each tank linked to
a dosing pump drawn once by what that pump runs (a reload in the middle of a dose and an in-place
upgrade included), the low-stock Repairs card, and the room's stock sensor an automation can push
a phone alert from."""

import time

from conftest import fixture
from homeassistant.core import Context
from homeassistant.helpers import issue_registry as ir
from test_dosing import PUMP, _devices
from test_setup_entry import _install
from test_upgrade_in_place import _upgrade

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


def _pump(hass, state, at):
    """test_dosing's Balance pump as its firmware reports it, at `at` (a Unix time): its dosing
    sensor and its power switch, the motor's own switch."""
    hass.states.async_set(PUMP["dosing_entity"], state, timestamp=at)
    hass.states.async_set(PUMP["power_entity"], state, timestamp=at)


async def test_a_tank_linked_to_a_dosing_pump_is_drawn_by_what_it_runs_once(
    hass, hass_admin_user
):
    """docs/DOSING.md, Stock tanks: what the linked pump runs is drawn, whoever started it, once,
    a reload in the middle of a dose included. The controller app's own report of a dose (sent
    asking for the answer, and again until it hears back) is not counted again, and a tank the
    room does not have is still named back to it; a fill Crop Steering stamps skips the linked
    tank, and so does a batch recorded by hand."""
    hass.states.async_set(
        FILL, "2026-09-24T07:16:08+00:00", {"device_class": "timestamp"}
    )
    entry = await _install(hass, {"tank_last_fill_sensor": FILL})
    _devices(hass)
    doc = await _service(hass, hass_admin_user, "stock_get")
    doc = await _service(
        hass,
        hass_admin_user,
        "stock_save",
        expected_revision=doc["revision"],
        tanks=[
            {"name": "Balance", "capacity_l": 10, "dose_ml": 500},
            {"name": "Cal", "capacity_l": 5, "dose_ml": 250},
        ],
    )
    linked = await _service(
        hass,
        hass_admin_user,
        "dosing_save",
        expected_revision=0,
        pumps=[{**PUMP, "stock_tank": "balance"}],
        batch={},
    )
    assert linked["error"] is None
    await hass.async_block_till_done()
    tanks = {t["id"]: t for t in hass.states.get(SENSOR).attributes["tanks"]}
    assert (tanks["balance"]["pump"], tanks["cal"]["pump"]) == ("balance", None)
    assert tanks["balance"]["name"] == "Balance"

    # A 25 mL dose, whoever pressed start: the pump ran 2.26 s at its 11.06 mL/s.
    start = time.time()
    _pump(hass, "on", start)
    await hass.async_block_till_done()
    _pump(hass, "off", start + 2.26)
    await hass.async_block_till_done()
    doc = await _service(hass, hass_admin_user, "stock_get")
    assert [t["level_l"] for t in doc["tanks"]] == [9.975, 5]
    assert doc["history"][0]["source"] == "pump"
    assert doc["history"][0]["draw_ml"] == {"balance": 25.0}
    assert doc["history"][0]["key"].startswith("pump:balance:")

    draw = {"room_id": ROOM, "key": ":balance:2026-09-25T06:00:00+00:00"}
    answer = await hass.services.async_call(  # as the controller app calls it: with the answer
        DOMAIN,
        "stock_draw",
        {**draw, "draws": {"balance": 25, "nope": 5}, "source": "dose"},
        blocking=True,
        return_response=True,
    )
    assert (answer["counted"], answer["duplicate"], answer["skipped"]) == (
        False,
        False,
        ["nope"],
    )
    assert answer["linked"] == ["balance"]
    await hass.services.async_call(  # an older controller asked for no answer
        DOMAIN,
        "stock_draw",
        {**draw, "draws": {"balance": 25}, "source": "dose"},
        blocking=True,
    )
    doc = await _service(hass, hass_admin_user, "stock_get")
    assert [t["level_l"] for t in doc["tanks"]] == [9.975, 5]

    # The room reloads in the middle of the next dose: it is drawn once, from when it started.
    start = time.time()
    _pump(hass, "on", start)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    _pump(hass, "off", start + 2.26)
    await hass.async_block_till_done()
    doc = await _service(hass, hass_admin_user, "stock_get")
    assert [t["level_l"] for t in doc["tanks"]] == [9.95, 5]
    assert [item["source"] for item in doc["history"]] == ["pump", "pump"]

    await _fill(hass, "2026-09-25T07:02:00+00:00")  # the batch's stamp: Cal only
    doc = await _service(hass, hass_admin_user, "stock_get")
    assert [t["level_l"] for t in doc["tanks"]] == [9.95, 4.75]
    # The same batch recorded by hand as well: Cal only again, and the answer says so.
    doc = await _service(
        hass, hass_admin_user, "stock_record_batch", expected_revision=doc["revision"]
    )
    assert [t["level_l"] for t in doc["tanks"]] == [9.95, 4.5]
    assert doc["skipped"] == ["balance"]
    assert doc["history"][0]["draw_ml"] == {"cal": 250.0}


async def test_an_upgraded_room_draws_each_linked_tank_by_what_its_pump_runs(
    hass, hass_admin_user, hass_storage
):
    """UPGRADE IN PLACE (tests_ha/fixtures/stock_dosing_3_8.json): a room whose four stock tanks
    never moved, because a Home Assistant automation doses them, loads exactly as it was, and from
    then on each dose draws its tank once, from what the pump ran. The doser's status reads
    "Running (Manual)", which the setup's dosing prefix never matches; its power switch reads on.
    """
    seed = fixture("stock_dosing_3_8.json")
    entry_id = fixture("entry_2_17_wizard.json")["entry_id"]
    for name in ("stock", "dosing"):
        key = f"{DOMAIN}.{name}.{entry_id}"
        hass_storage[key] = {
            "version": 1,
            "minor_version": 1,
            "key": key,
            "data": seed[name],
        }
    for entity_id, state in seed["states"].items():
        hass.states.async_set(entity_id, state)
    await _upgrade(hass, "entry_2_17_wizard.json")
    stored = seed["stock"]
    doc = await _service(hass, hass_admin_user, "stock_get")
    assert (doc["revision"], doc["tanks"], doc["history"], doc["last_batch"]) == (
        stored["revision"],
        stored["tanks"],
        stored["history"],
        stored["last_batch"],
    )

    # The automation doses Balance as the doser did on 27 Sep: 27.13 s at 11.0612 mL/s.
    status, power = "sensor.doser_balance_pump_status", "switch.doser_balance_pump_power"
    start = time.time()
    hass.states.async_set(status, "Running (Manual)", timestamp=start)
    hass.states.async_set(power, "on", timestamp=start)
    await hass.async_block_till_done()
    hass.states.async_set(status, "Stopped", timestamp=start + 27.129)
    hass.states.async_set(power, "off", timestamp=start + 27.13)
    await hass.async_block_till_done()
    doc = await _service(hass, hass_admin_user, "stock_get")
    assert [t["level_l"] for t in doc["tanks"]] == [9.6999, 20, 18, 5]
    assert doc["history"][0]["source"] == "pump"
    assert doc["history"][0]["draw_ml"] == {"balance": 300.1}
    assert doc["history"][1:] == stored["history"][:29] and doc["revision"] == 299
    tanks = {t["id"]: t for t in hass.states.get(SENSOR).attributes["tanks"]}
    assert (tanks["balance"]["level_l"], tanks["balance"]["pump"]) == (9.6999, "balance")

    # The controller app's report of a dose is left to the pump's run.
    answer = await hass.services.async_call(
        DOMAIN,
        "stock_draw",
        {
            "room_id": ROOM,
            "key": f":balance:{doc['history'][0]['at']}",
            "draws": {"balance": 300},
            "source": "batch",
        },
        blocking=True,
        return_response=True,
    )
    assert (answer["counted"], answer["skipped"], answer["linked"]) == (
        False,
        [],
        ["balance"],
    )
    assert answer["tanks"][0]["level_l"] == 9.6999


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
