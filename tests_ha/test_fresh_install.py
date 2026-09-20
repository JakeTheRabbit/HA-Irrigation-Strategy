"""FRESH INSTALL, in a real Home Assistant: a newcomer with a single-switch tent.

Nothing pre-seeded but the devices a tent has. The wizard is driven exactly as the frontend
drives it (flow.async_init / async_configure), so schema validation, selector coercion and
translations are the real ones.
"""

from __future__ import annotations

import pytest
import voluptuous_serialize
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv

from .conftest import DOMAIN, TENT_SWITCH, seed_tent

SYSTEM = {"num_zones": 1, "plumbing": "valves_only", "volume_unit": "gal", "flow_unit": "gal/hr"}
ZONES = {
    "ec_unit": "auto",
    "zone_1_name": "Tent",
    "zone_1_active": True,
    "zone_1_switch": TENT_SWITCH,
    "zone_1_vwc": ["sensor.gt1_vwc"],
    "zone_1_ec": ["sensor.gt1_ec"],
    "zone_1_plant_count": 4,
}
LIGHTS = {"lights_on_hour": 6, "lights_off_hour": 0}
SUBSTRATE = {
    "substrate_preset": "pot_3gal",
    "substrate_volume": 1,
    "dripper_flow_rate": 1,
    "drippers_per_plant": 2,
    "field_capacity": 70,
    "max_ec": 9,
    "have_catch_test": False,
}


async def _start(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Grow tent 1", "config_method": "manual"}
    )


async def _answer(hass, result, answers, expect_step):
    result = await hass.config_entries.flow.async_configure(result["flow_id"], answers)
    assert result["type"] is FlowResultType.FORM, result
    assert result["step_id"] == expect_step, result.get("errors")
    return result


async def _install_tent(hass):
    seed_tent(hass)
    result = await _start(hass)
    assert result["step_id"] == "manual_zones"
    result = await _answer(hass, result, SYSTEM, "zones")
    result = await _answer(hass, result, ZONES, "hardware")
    result = await _answer(hass, result, LIGHTS, "substrate")
    result = await _answer(hass, result, SUBSTRATE, "extras")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    await hass.async_block_till_done()
    return result["result"]


async def test_a_single_switch_tent_installs_from_nothing(hass):
    entry = await _install_tent(hass)

    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert entry.data["plumbing"] == "valves_only"
    assert entry.data["hardware"]["pump_switch"] == ""

    # What the wizard was told is what the engine will read - in the engine's units.
    def number(key):
        return float(hass.states.get(f"number.crop_steering_{key}").state)

    assert number("substrate_volume") == 11.4  # the 3 US gal preset, in litres
    assert number("dripper_flow_rate") == pytest.approx(3.785, abs=1e-3)  # 1 GPH in L/hr
    assert number("drippers_per_plant") == 2
    assert number("zone_1_plant_count") == 4
    # The lights hours were asked for, stored, and then ignored: the entities seeded to 12/0.
    assert number("lights_on_hour") == 6
    assert number("lights_off_hour") == 0


async def test_a_microsiemens_probe_reaches_the_engine_as_millisiemens(hass):
    await _install_tent(hass)
    fused = hass.states.get("sensor.crop_steering_ec_zone_1")
    assert float(fused.state) == pytest.approx(2.3)
    assert fused.attributes["unit_of_measurement"] == "mS/cm"
    assert float(hass.states.get("sensor.crop_steering_vwc_zone_1").state) == 48


async def test_the_engine_descriptor_declares_the_tents_plumbing(hass):
    await _install_tent(hass)
    descriptor = hass.states.get("sensor.crop_steering_engine_config").attributes
    assert descriptor["plumbing"] == "valves_only"
    assert descriptor["valves"] == {1: TENT_SWITCH}
    assert descriptor["pump"] == "" and descriptor["mainline"] == ""
    assert descriptor["setup_revision"] == 1 and descriptor["active"] is True


async def test_the_switch_being_on_is_an_inline_error_not_the_end_of_the_wizard(hass):
    """The reported bug, end to end in a real flow manager."""
    seed_tent(hass, switch="on")
    result = await _start(hass)
    result = await _answer(hass, result, SYSTEM, "zones")

    result = await hass.config_entries.flow.async_configure(result["flow_id"], ZONES)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "zones"
    assert result["errors"] == {"zone_1_switch": "must_read_off"}
    assert f"{TENT_SWITCH} is ON" in result["description_placeholders"]["blockers"]

    hass.states.async_set(TENT_SWITCH, "off")
    result = await _answer(hass, result, ZONES, "hardware")  # same flow, same answers, carries on


@pytest.mark.parametrize(
    "unit, pick, outcome",
    [
        ("ppm", "auto", {"zone_1_ec": "ec_unit_ppm_scale"}),
        ("ppm", "ppm_700", None),
        (None, "auto", {"zone_1_ec": "ec_unit_missing"}),
        (None, "us_cm", None),
        ("%", "auto", {"zone_1_ec": "ec_unit_unknown"}),
    ],
)
async def test_an_ec_probe_that_needs_explaining_is_asked_about_beside_its_own_picker(
    hass, unit, pick, outcome
):
    seed_tent(hass, ec_unit=unit)
    result = await _answer(hass, await _start(hass), SYSTEM, "zones")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**ZONES, "ec_unit": pick}
    )
    assert result["type"] is FlowResultType.FORM
    if outcome:
        assert result["step_id"] == "zones" and result["errors"] == outcome
    else:
        assert result["step_id"] == "hardware"


async def test_a_pumped_room_is_asked_for_its_pump_and_cannot_skip_it(hass):
    seed_tent(hass)
    hass.states.async_set("switch.pump", "off")
    result = await _answer(
        hass, await _start(hass), {**SYSTEM, "plumbing": "pump_valves"}, "zones"
    )
    result = await _answer(hass, result, ZONES, "hardware")
    fields = {str(marker) for marker in result["data_schema"].schema}
    assert "pump_switch" in fields and "main_line_switch" not in fields
    result = await _answer(hass, result, {**LIGHTS, "pump_switch": "switch.pump"}, "substrate")


async def test_every_wizard_form_can_be_rendered_by_the_frontend(hass):
    """The frontend receives each schema serialised. A construct it cannot serialise is a
    wizard that throws on open - invisible to stubs where selectors are lambdas."""
    seed_tent(hass)
    result = await _start(hass)
    seen = []
    for answers in (SYSTEM, ZONES, LIGHTS, {**SUBSTRATE, "have_catch_test": True},
                    {"catch_seconds": 60, "catch_ml": 200, "catch_drippers": 4}):
        seen.append(result["step_id"])
        assert voluptuous_serialize.convert(
            result["data_schema"], custom_serializer=cv.custom_serializer
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], answers)
    seen.append(result["step_id"])
    assert voluptuous_serialize.convert(result["data_schema"], custom_serializer=cv.custom_serializer)
    assert seen == ["manual_zones", "zones", "hardware", "substrate", "catch_test", "extras"]
    assert "3 L/hr" not in result["description_placeholders"]["measured"]  # shown in GPH, as chosen
    assert "gal/hr" in result["description_placeholders"]["measured"]


async def test_field_capacity_is_suggested_once_the_controller_has_seen_the_zone_top_out(hass):
    await _install_tent(hass)
    suggestion = "sensor.crop_steering_zone_1_suggested_field_capacity"
    assert hass.states.get(suggestion).state == "unknown"  # nothing learned yet: no guess offered

    # What the add-on publishes over REST once a morning ramp has plateaued.
    hass.states.async_set(
        "sensor.crop_steering_zone_1_auto_setpoints", "off", {"learned_peak": 61.4}
    )
    from homeassistant.helpers.entity_component import async_update_entity

    await async_update_entity(hass, suggestion)
    state = hass.states.get(suggestion)
    assert float(state.state) == 63.4
    assert state.attributes["configured_field_capacity"] == 70.0
    assert state.attributes["difference"] == -6.6
