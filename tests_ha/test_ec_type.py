"""What each EC probe measures, in a real Home Assistant: a select per probe, unknown, pore or bulk.

Bulk EC (substrate and water together) reads lower than pore EC (the water in the pores) from the
same slab. A zone that averaged one of each would steer on a number neither probe measures, so a
zone holding both steers on its pore probes, and on its bulk probes only while no pore probe
reports. unknown, the default, fuses as before, so an upgraded room reads what it read.
"""

from datetime import timedelta

from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from conftest import fixture
from custom_components.crop_steering.plumbing import infer
from test_real_flow import ZONES, _seed, _to_zones_step
from test_upgrade_in_place import JEV_3_11_1, _upgrade

ZONE_EC = "sensor.crop_steering_ec_zone_1"
PORE, BULK = "sensor.slab_pore_ec", "sensor.slab_bulk_ec"


def _type_select(probe, prefix=""):
    return f"select.crop_steering_{prefix}ec_type_{probe.split('.', 1)[1]}"


async def _choose(hass, select, option):
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": select, "option": option},
        blocking=True,
    )
    await hass.async_block_till_done()


async def _read(hass, freezer, **probes):
    for entity_id, value in probes.items():
        hass.states.async_set(entity_id, value, {"unit_of_measurement": "mS/cm"})
    freezer.tick(timedelta(minutes=1))
    async_fire_time_changed(hass, fire_all=True)
    await hass.async_block_till_done()
    return hass.states.get(ZONE_EC)


async def _install(hass):
    _seed(hass)
    for probe, value in ((PORE, "3.0"), (BULK, "1.2")):
        hass.states.async_set(probe, value, {"unit_of_measurement": "mS/cm"})
    flow_id = await _to_zones_step(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {**ZONES, "zone_1_ec": [PORE, BULK]}
    )
    assert result["step_id"] == "hardware", result.get("errors")
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"plumbing": infer({})}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    await hass.async_block_till_done()


async def test_3_11_1_probes_read_unknown_and_fuse_as_before(hass):
    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    for zone, probe, reading in (
        (1, "sensor.zone_1_ec", 3.4),
        (2, "sensor.zone_2_ec", 3.1),
    ):
        select = hass.states.get(_type_select(probe))
        assert select.state == "unknown", probe
        assert select.attributes["options"] == ["unknown", "pore", "bulk"]
        ec = hass.states.get(f"sensor.crop_steering_ec_zone_{zone}")
        assert float(ec.state) == reading  # 3100 µS/cm is 3.1 mS/cm, as 3.11.1 read it
        assert "ec_type" not in ec.attributes and ec.attributes["used"] == [probe]


async def test_a_zone_with_a_bulk_and_a_pore_probe_steers_on_pore(hass, freezer):
    await _install(hass)
    assert (
        float((await _read(hass, freezer, **{PORE: "3.0", BULK: "1.2"})).state) == 2.1
    )
    await _choose(hass, _type_select(PORE), "pore")
    await _choose(hass, _type_select(BULK), "bulk")
    state = await _read(hass, freezer, **{PORE: "3.0", BULK: "1.2"})
    assert float(state.state) == 3.0  # averaged with the bulk probe it read 2.1
    assert state.attributes["ec_type"] == "pore"
    assert state.attributes["excluded"] == {BULK: "bulk EC, kept apart from pore EC"}

    hass.states.async_set(PORE, "unavailable")
    state = await _read(hass, freezer, **{BULK: "1.2"})
    assert float(state.state) == 1.2 and state.attributes["ec_type"] == "bulk"
    assert state.attributes["excluded"] == {PORE: "no reading"}


async def test_the_controller_says_when_a_zone_steers_on_bulk_ec(
    hass, freezer, controller_for
):
    from datetime import datetime

    await _install(hass)
    await _choose(hass, _type_select(PORE), "pore")
    await _choose(hass, _type_select(BULK), "bulk")
    hass.states.async_set(PORE, "unavailable")
    await _read(hass, freezer, **{BULK: "1.2"})
    c, fake, _clock = controller_for(
        {"enable_flag": "switch.crop_steering_engine_enabled"}
    )
    assert c._read_sensor(c._fused_id("", "ec", 1), "ec") == 1.2
    c.loop_once(datetime(2026, 9, 21, 14, 0, 0))
    raised = [
        data
        for domain, service, data in fake.calls
        if (domain, service) == ("persistent_notification", "create")
        and data["notification_id"] == "f2_ec_type_default_z1"
    ]
    assert len(raised) == 1 and raised[0]["title"].endswith("(CS-504)"), raised
    assert PORE in raised[0]["message"]
