"""Configure (the options flow), in a real Home Assistant.

Three things an operator reaches for after the first install, each of which did nothing or
could not be done: editing a parameter (saved, reloaded, and the entity restored its old value
over the top), removing a mapping (the form put it straight back), and correcting dripper flow
from a measurement.
"""

from __future__ import annotations

import pytest
from homeassistant.data_entry_flow import FlowResultType

from .conftest import TENT_SWITCH
from .test_fresh_install import _install_tent

FLOW = "number.crop_steering_dripper_flow_rate"


async def _open(hass, entry, step):
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert flow["type"] is FlowResultType.MENU
    assert step in flow["menu_options"]
    return await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": step})


async def test_a_catch_test_sets_the_dripper_flow_the_engine_reads(hass):
    entry = await _install_tent(hass)
    revision = entry.data["setup_revision"]
    assert float(hass.states.get(FLOW).state) == pytest.approx(3.785, abs=1e-3)  # the packet: 1 GPH

    flow = await _open(hass, entry, "calibrate_flow")
    assert flow["type"] is FlowResultType.FORM and flow["step_id"] == "calibrate_flow"
    done = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"catch_seconds": 60, "catch_ml": 200, "catch_drippers": 4})
    await hass.async_block_till_done()

    assert done["type"] is FlowResultType.ABORT and done["reason"] == "calibration_applied"
    assert "0.79 gal/hr" in done["description_placeholders"]["flow"]  # reported in the grower's unit
    assert done["description_placeholders"]["entities"] == FLOW
    assert float(hass.states.get(FLOW).state) == 3.0  # and stored as L/hr
    # It changed a number, not the wiring: no new setup revision, so no disarm cycle is forced.
    assert entry.data["setup_revision"] == revision


async def test_an_implausible_catch_test_is_refused_and_nothing_is_written(hass):
    entry = await _install_tent(hass)
    before = hass.states.get(FLOW).state
    flow = await _open(hass, entry, "calibrate_flow")
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"catch_seconds": 10, "catch_ml": 5000, "catch_drippers": 1})
    assert flow["type"] is FlowResultType.FORM and flow["errors"] == {"base": "catch_test_out_of_range"}
    assert hass.states.get(FLOW).state == before


async def test_editing_a_parameter_changes_what_the_engine_reads(hass):
    """It saved, reloaded, and each number restored its previous value over the edit."""
    entry = await _install_tent(hass)
    target = "number.crop_steering_p1_target_vwc"
    assert float(hass.states.get(target).state) == 65.0

    flow = await _open(hass, entry, "edit_parameters")
    shown = {str(m): m.default() for m in flow["data_schema"].schema}
    assert shown["substrate_volume"] == 11.4  # the LIVE value, not a stale copy from setup
    done = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"substrate_volume": 11.4, "dripper_flow_rate": 3.785,
                          "p1_target_vwc": 61.0, "p2_vwc_threshold": 55.0})
    assert done["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert float(hass.states.get(target).state) == 61.0
    assert float(hass.states.get("number.crop_steering_p2_vwc_threshold").state) == 55.0


async def test_editing_while_the_switch_is_on_is_an_inline_error_that_keeps_the_edit(hass):
    entry = await _install_tent(hass)
    hass.states.async_set(TENT_SWITCH, "on")
    flow = await _open(hass, entry, "edit_parameters")
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"substrate_volume": 11.4, "dripper_flow_rate": 3.785,
                          "p1_target_vwc": 61.0, "p2_vwc_threshold": 55.0})
    assert flow["type"] is FlowResultType.FORM and flow["errors"] == {"base": "must_read_off"}
    assert {str(m): m.default() for m in flow["data_schema"].schema}["p1_target_vwc"] == 61.0
    assert float(hass.states.get("number.crop_steering_p1_target_vwc").state) == 65.0  # not applied


async def test_a_mapping_can_be_removed_not_just_swapped(hass):
    hass.states.async_set("sensor.room_temp", "24", {"unit_of_measurement": "°C"})
    entry = await _install_tent(hass)

    async def save(**hardware):
        flow = await _open(hass, entry, "edit_zones")
        flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"num_zones": 1})
        assert flow["step_id"] == "edit_zones_map"
        done = await hass.config_entries.options.async_configure(
            flow["flow_id"],
            {"plumbing": "valves_only", "ec_unit": "auto", "zone_1_switch": TENT_SWITCH,
             "zone_1_vwc": ["sensor.gt1_vwc"], "zone_1_ec": ["sensor.gt1_ec"],
             "zone_1_plant_count": 4, **hardware})
        assert done["type"] is FlowResultType.CREATE_ENTRY, done.get("errors")
        await hass.async_block_till_done()

    await save(temperature_sensor="sensor.room_temp")
    assert entry.data["hardware"]["temperature_sensor"] == "sensor.room_temp"
    await save()  # the operator clears the field; the frontend then simply omits it
    assert entry.data["hardware"]["temperature_sensor"] == ""


async def test_configure_reports_a_wrong_layout_beside_the_field_instead_of_aborting(hass):
    hass.states.async_set("switch.pump", "off")
    entry = await _install_tent(hass)
    flow = await _open(hass, entry, "edit_zones")
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"num_zones": 1})
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {"plumbing": "valves_only", "ec_unit": "auto", "zone_1_switch": TENT_SWITCH,
         "zone_1_vwc": ["sensor.gt1_vwc"], "zone_1_ec": ["sensor.gt1_ec"],
         "zone_1_plant_count": 4, "pump_switch": "switch.pump"})
    assert flow["type"] is FlowResultType.FORM and flow["step_id"] == "edit_zones_map"
    assert flow["errors"] == {"pump_switch": "plumbing_unused_pump"}
    assert flow["description_placeholders"]["entity"] == "switch.pump"
