"""A zone with several probes, in a real Home Assistant: what the zone reading the controller steers by says.

The controller reads one entity per zone, sensor.crop_steering_vwc_zone_N, never the probes behind
it. It measures dryback from the zone's peak and compares the reading with its thresholds, so a
reading that steps because a probe dropped out is taken as the crop drying back or wetting up.
These run the real config flow, the real polled sensor and Home Assistant's own last_reported.
"""

from datetime import timedelta

from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.crop_steering.plumbing import infer
from test_real_flow import ZONES, _seed, _to_zones_step

ZONE = "sensor.crop_steering_vwc_zone_1"
A, B, C = "sensor.gt1_vwc", "sensor.gt1_vwc_b", "sensor.gt1_vwc_c"


async def _install(hass, probes):
    _seed(hass)  # A reads 41 %
    for probe in probes:
        if probe != A:
            hass.states.async_set(probe, "41", {"unit_of_measurement": "%"})
    flow_id = await _to_zones_step(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {**ZONES, "zone_1_vwc": probes}
    )
    assert result["step_id"] == "hardware", result.get("errors")
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"plumbing": infer({})}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    await hass.async_block_till_done()


async def _read(hass, freezer, minutes=1, **probes):
    """Report the given probe values, let the minute pass (every timer, so the sensor polls), and
    return the zone reading."""
    for entity_id, value in probes.items():
        hass.states.async_set(entity_id, value, {"unit_of_measurement": "%"})
    freezer.tick(timedelta(minutes=minutes))
    async_fire_time_changed(hass, fire_all=True)
    await hass.async_block_till_done()
    return hass.states.get(ZONE)


async def test_a_zone_with_one_probe_reads_it_exactly(hass):
    await _install(hass, [A])
    state = hass.states.get(ZONE)
    assert float(state.state) == 41.0
    assert state.attributes["probes"] == 1 and state.attributes["used"] == [A]


async def test_one_wild_probe_among_three_does_not_move_the_zone(hass, freezer):
    await _install(hass, [A, B, C])
    state = await _read(hass, freezer, **{A: "40", B: "42", C: "90"})
    assert float(state.state) == 42.0  # averaged, the zone read 57.33
    assert state.attributes["spread"] == 50.0


async def test_a_probe_going_offline_does_not_step_what_the_controller_reads(
    hass, freezer, controller_for
):
    await _install(hass, [A, B])
    assert float((await _read(hass, freezer, **{A: "40", B: "46"})).state) == 43.0

    hass.states.async_set(B, "unavailable")
    state = await _read(hass, freezer, **{A: "40"})
    assert float(state.state) == 43.0  # averaged, 40: three points of dryback that never happened
    assert state.attributes["excluded"] == {B: "no reading"}

    assert float((await _read(hass, freezer, **{A: "38"})).state) == 41.0
    c, _fake, _clock = controller_for()
    assert c._read_sensor(c._fused_id("", "vwc", 1), lo=0, hi=100) == 41.0


async def test_a_probe_that_stops_reporting_is_set_aside_while_another_still_reports(
    hass, freezer
):
    await _install(hass, [A, B])
    assert float((await _read(hass, freezer, **{A: "40", B: "46"})).state) == 43.0
    for _minute in range(25):  # A keeps reporting 40; B has gone quiet on 46
        await _read(hass, freezer, **{A: "40"})
    state = await _read(hass, freezer, **{A: "39"})
    assert float(state.state) == 42.0  # follows A down; B's last 46 no longer holds the zone up
    assert state.attributes["excluded"] == {B: "not reporting"}
