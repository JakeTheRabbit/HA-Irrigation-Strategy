"""How a zone's probes become its one reading, in a real Home Assistant: a select per zone for its
moisture and another for its EC (Median, Average, Lowest, Highest), Median until someone chooses.

Lowest or Highest lets one probe steer the zone. A probe pulled out of its cube still reports, in
range and on time, so under Lowest it would hold the zone below its threshold and fire shots until
the daily cap. A probe far from the others is left out, and Lowest and Highest need three probes
that agree; with fewer the zone steers on their median.
"""

from datetime import timedelta

from pytest_homeassistant_custom_component.common import async_fire_time_changed

import test_upgrade_in_place
from conftest import fixture
from test_probe_fusion import A, B, C, ZONE, _install, _read
from test_upgrade_in_place import JEV_3_11_1, _upgrade

VWC_METHOD = "select.crop_steering_zone_1_vwc_method"


async def _choose(hass, select, option):
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": select, "option": option},
        blocking=True,
    )
    await hass.async_block_till_done()


async def test_a_3_11_1_room_gets_the_selects_at_median_and_reads_as_before(hass):
    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    for zone in (1, 2):
        for metric in ("vwc", "ec"):
            select = hass.states.get(
                f"select.crop_steering_zone_{zone}_{metric}_method"
            )
            assert select.state == "Median", (zone, metric)
            assert select.attributes["options"] == [
                "Median",
                "Average",
                "Lowest",
                "Highest",
            ]
    # Zone 1's two probes read 50 and 54: their median, as 3.11.1 read it.
    vwc = hass.states.get(ZONE)
    assert float(vwc.state) == 52.0
    assert (vwc.attributes["method"], vwc.attributes["steered_by"]) == (
        "Median",
        "Median",
    )
    assert vwc.attributes["used"] == ["sensor.zone_1_vwc_a", "sensor.zone_1_vwc_b"]


async def test_a_room_that_already_chose_average_keeps_it(hass, monkeypatch):
    """An install that already had these selects (same unique ids) keeps its restored choice."""

    def seeded(name):
        seed = fixture(name)
        seed["operator_tuned_numbers"][VWC_METHOD] = "Average"
        return seed

    monkeypatch.setattr(test_upgrade_in_place, "fixture", seeded)
    await _upgrade(
        hass, "entry_2_17_wizard.json", registry_ids={VWC_METHOD: "zone_1_vwc_method"}
    )
    assert hass.states.get(VWC_METHOD).state == "Average"
    assert hass.states.get(ZONE).attributes["method"] == "Average"


async def test_a_probe_pulled_out_does_not_drive_lowest(hass, freezer):
    await _install(hass, [A, B, C])
    await _choose(hass, VWC_METHOD, "Lowest")
    state = await _read(hass, freezer, **{A: "48", B: "50", C: "52"})
    assert float(state.state) == 48.0 and state.attributes["steered_by"] == "Lowest"

    # C is pulled out of its cube and reads 3 %, fresh and in range.
    state = await _read(hass, freezer, **{A: "48", B: "50", C: "3"})
    assert (
        float(state.state) == 48.0
    )  # Lowest of every probe: 3, and shots until the daily cap
    assert state.attributes["excluded"] == {C: "far from the others"}
    assert (state.attributes["method"], state.attributes["steered_by"]) == (
        "Lowest",
        "Median",
    )


async def test_a_new_choice_shows_at_once(hass, freezer):
    await _install(hass, [A, B, C])
    await _read(hass, freezer, **{A: "40", B: "44", C: "46"})
    assert float(hass.states.get(ZONE).state) == 44.0
    await _choose(hass, VWC_METHOD, "Highest")  # no poll in between
    assert float(hass.states.get(ZONE).state) == 46.0


async def test_what_the_probes_taught_the_zone_survives_a_restart(hass, freezer):
    await _install(hass, [A, B])
    await _read(hass, freezer, **{A: "40", B: "46"})
    entry = hass.config_entries.async_entries("crop_steering")[0]
    learned = hass.states.get(ZONE).attributes["offsets_learned"]
    assert learned
    hass.states.async_set(
        B, "unavailable"
    )  # B is down when the integration starts again
    freezer.tick(timedelta(minutes=1))
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    async_fire_time_changed(hass, fire_all=True)
    await hass.async_block_till_done()
    state = hass.states.get(ZONE)
    assert (
        float(state.state) == 43.0
    )  # 40, a three-point step, without the remembered offsets
    assert state.attributes["offsets_learned"] == learned
