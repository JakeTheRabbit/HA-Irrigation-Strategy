"""Grow-day summaries in a real Home Assistant: the Record grow days switch (off on a new and an upgraded room), what the
REAL controller module builds taken unchanged by grow_day_record, kept across a reload, one damaged stored record left
out without losing the rest, writes refused to a user who is not an administrator, and grow-days filled from
long-term statistics without ever replacing a recorded one."""

from datetime import datetime, timedelta

import day_summary
import pytest
from conftest import fixture
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, _upgrade

DOMAIN = "crop_steering"
ROOM = "room:tent_"
SWITCH = "switch.crop_steering_tent_record_grow_days"


async def _call(hass, user, service, **data):
    return await hass.services.async_call(
        DOMAIN, service, {"room_id": ROOM, **data}, blocking=True, return_response=True,
        context=Context(user_id=user.id),
    )


def _summary(day="2026-09-22", zone=1):
    """A grow-day as the controller app builds it (day_summary.py)."""
    st = day_summary.fresh()
    start = datetime(2026, 9, 22, 10, 0)
    for hour, vwc in ((11, 50.0), (15, 46.0)):
        day_summary.observe(st, day=day, now=start + timedelta(hours=hour - 10), vwc=vwc, ec=5.2, feed_ec=2.1)
    day_summary.probes(st, day=day, now=start, readings=[("vwc", "sensor.row_1_front", "Row 1 front", "%", 51.0, True)])
    day_summary.shot(st, day=day, now=start, kind="p2_topup", litres=1.5)
    day_summary.alert(st, "CS-104")
    st["plateau_hist"] = [{"date": day, "value": 50.0, "how": "reached the target", "shots": 4}]
    return day_summary.close(st, day=day, now=start, info={
        "zone": zone, "lights": {"on": 10.0, "off": 22.0}, "plant_count": 10, "mode": "Generative",
        "targets": {"p1_target": 55.0}, "litres": 1.5, "plan_day": None, "day_start": start})


async def test_a_new_room_records_nothing_until_the_switch_is_on(hass, hass_admin_user):
    await _install(hass)
    assert hass.states.get(SWITCH).state == "off"
    answer = await _call(hass, hass_admin_user, "grow_days_get")
    assert answer["days"] == [] and answer["first"] is None


async def test_an_upgraded_3_11_1_room_gets_the_switch_off_and_an_empty_store(hass, hass_admin_user):
    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    assert hass.states.get("switch.crop_steering_record_grow_days").state == "off"
    answer = await hass.services.async_call(
        DOMAIN, "grow_days_get", {"room_id": "room:"}, blocking=True, return_response=True,
        context=Context(user_id=hass_admin_user.id))
    assert answer["days"] == []


async def test_what_the_controller_builds_is_kept_as_it_was_sent_and_survives_a_reload(hass, hass_admin_user):
    entry = await _install(hass)
    sent = _summary()
    answer = await _call(hass, hass_admin_user, "grow_day_record", days=[sent, _summary(zone=2)])
    assert answer == {"taken": 2, "refused": []}
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    (kept,) = (await _call(hass, hass_admin_user, "grow_days_get", zone=1))["days"]
    for key, value in sent.items():
        if key != "schema":
            assert kept[key] == value, key
    # sent again (the controller retries after a lost answer): replaced, not doubled
    await _call(hass, hass_admin_user, "grow_day_record", days=[sent])
    assert (await _call(hass, hass_admin_user, "grow_days_get"))["count"] == 2


async def test_a_damaged_stored_record_is_left_out_and_the_rest_load(hass, hass_storage, hass_admin_user):
    entry_id = fixture(JEV_3_11_1)["entry_id"]
    key = f"{DOMAIN}.grow_days.{entry_id}"
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key,
                         "data": {"days": [_summary(), {"date": "not a date", "zone": 1}, {"zone": 99}]}}
    await _upgrade(hass, JEV_3_11_1, registry_ids=fixture(JEV_3_11_1)["registry"])
    answer = await hass.services.async_call(
        DOMAIN, "grow_days_get", {"room_id": "room:"}, blocking=True, return_response=True,
        context=Context(user_id=hass_admin_user.id))
    assert [(d["date"], d["zone"]) for d in answer["days"]] == [("2026-09-22", 1)]


async def test_only_an_administrator_records_and_anyone_reads(hass, hass_admin_user, hass_read_only_user):
    await _install(hass)
    with pytest.raises(HomeAssistantError, match="administrator"):
        await _call(hass, hass_read_only_user, "grow_day_record", days=[_summary()])
    await _call(hass, hass_admin_user, "grow_day_record", days=[_summary()])
    assert len((await _call(hass, hass_read_only_user, "grow_days_get"))["days"]) == 1


@pytest.fixture
def mock_recorder_before_hass(async_test_recorder):
    """The recorder's database is made before Home Assistant is (test_setup_changes_recorded.py)."""


async def test_grow_days_are_filled_from_statistics_and_a_recorded_one_is_never_replaced(
    recorder_mock, hass, hass_admin_user
):
    from homeassistant.components.recorder.models import StatisticMeanType
    from homeassistant.components.recorder.statistics import async_import_statistics
    from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

    await _install(hass)
    on = float(hass.states.get("number.crop_steering_tent_lights_on_hour").state)
    vwc = next(e for e in ("sensor.crop_steering_tent_vwc_zone_1", "sensor.crop_steering_tent_zone_1_vwc")
               if hass.states.get(e))
    tz = dt_util.get_default_time_zone()
    rows = []
    for day, values in (("2026-09-20", (40.0, 52.0)), ("2026-09-21", (41.0, 50.0))):
        start = datetime.fromisoformat(day).replace(tzinfo=tz) + timedelta(hours=on + 1)
        for i, v in enumerate(values):
            rows.append({"start": start + timedelta(hours=i), "min": v - 1, "max": v + 1, "mean": v})
    meta = {"source": "recorder", "statistic_id": vwc, "name": None, "unit_of_measurement": "%",
            "has_sum": False, "mean_type": StatisticMeanType.ARITHMETIC, "unit_class": None}
    async_import_statistics(hass, meta, rows)
    await async_wait_recording_done(hass)
    await _call(hass, hass_admin_user, "grow_day_record", days=[_summary(day="2026-09-21")])
    answer = await _call(hass, hass_admin_user, "grow_days_backfill", start="2026-09-20", end="2026-09-21")
    assert answer["added"] == 1
    filled, recorded = [d for d in answer["days"] if d["zone"] == 1]
    assert filled["date"] == "2026-09-20" and filled["backfilled"] == "partial" and filled["partial"] is True
    assert filled["vwc"] == {"peak": 53.0, "trough": 39.0, "mean": 46.0}
    assert recorded["date"] == "2026-09-21" and recorded["backfilled"] is None and recorded["vwc"]["peak"] == 50.0
