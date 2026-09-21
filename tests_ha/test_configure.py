"""Configure (the options flow), in a real Home Assistant.

Two things an operator reaches for after the first install, and neither did anything: editing a
parameter (saved, reloaded, and the entity restored its old value over the top) and removing a
mapping (the form put it straight back).
"""

import pytest
from homeassistant.data_entry_flow import FlowResultType, InvalidData

from test_real_flow import VALVE
from test_setup_entry import _install
from test_upgrade_in_place import _upgrade

TARGET = "number.crop_steering_p1_target_vwc"


async def _open(hass, entry, step):
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert flow["type"] is FlowResultType.MENU and step in flow["menu_options"]
    return await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": step}
    )


def _shown(flow):
    return {
        str(marker): marker.default()
        for marker in flow["data_schema"].schema
        if callable(getattr(marker, "default", None))
    }


EDIT = {
    "substrate_volume": 6.0,
    "dripper_flow_rate": 2.0,
    "p1_target_vwc": 61.0,
    "p2_vwc_threshold": 55.0,
}


# ------------------------------------------------------------------ Edit parameters
async def test_editing_a_parameter_changes_what_the_engine_reads(hass):
    entry = await _install(hass)
    assert float(hass.states.get(TARGET).state) == 65.0

    flow = await _open(hass, entry, "edit_parameters")
    done = await hass.config_entries.options.async_configure(flow["flow_id"], EDIT)
    assert done["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.data["parameters"]["p1_target_vwc"] == 61.0  # it always got this far...
    assert float(hass.states.get(TARGET).state) == 61.0  # ...and never this far
    assert float(hass.states.get("number.crop_steering_p2_vwc_threshold").state) == 55.0


async def test_the_form_opens_on_the_live_value_not_the_one_recorded_at_setup(hass):
    entry = await _install(hass)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": TARGET, "value": 58.5}, blocking=True
    )  # tuned on a dashboard since setup
    flow = await _open(hass, entry, "edit_parameters")
    assert _shown(flow)["p1_target_vwc"] == 58.5
    # Pressing Submit without touching anything must therefore change nothing.
    await hass.config_entries.options.async_configure(flow["flow_id"], _shown(flow))
    await hass.async_block_till_done()
    assert float(hass.states.get(TARGET).state) == 58.5


async def test_an_edit_made_while_a_switch_is_on_is_refused_and_nothing_is_written(hass):
    entry = await _install(hass)
    hass.states.async_set(VALVE, "on")
    flow = await _open(hass, entry, "edit_parameters")
    done = await hass.config_entries.options.async_configure(flow["flow_id"], EDIT)
    assert done["type"] is FlowResultType.ABORT and done["reason"] == "setup_invalid"
    assert float(hass.states.get(TARGET).state) == 65.0  # the live entity was not touched either


# ------------------------------------------------------------------ the form's limits
# 2.18.1 made this form open on the LIVE number entities instead of the values recorded at setup.
# Its own limits were never widened to match: the entities take a P1 target of 5-95 % and a P2
# threshold of 5-85 %, the form still demanded at least 30 and 25. A room steering at P1 20 / P2 15
# (dry-rooted crops, coarse substrates) could not submit the form at all, not even unchanged, and
# not to edit the pot size either. (Review finding on JakeTheRabbit/HA-Irrigation-Strategy#47.)
FIELDS = {
    "substrate_volume": "number.crop_steering_substrate_volume",
    "dripper_flow_rate": "number.crop_steering_dripper_flow_rate",
    "p1_target_vwc": TARGET,
    "p2_vwc_threshold": "number.crop_steering_p2_vwc_threshold",
}


async def _set(hass, values):
    for key, value in values.items():
        await hass.services.async_call(
            "number", "set_value", {"entity_id": FIELDS[key], "value": value}, blocking=True
        )


def _numbers(hass):
    return {s.entity_id: float(s.state) for s in hass.states.async_all("number")}


def _limits(hass, which):
    return {key: float(hass.states.get(eid).attributes[which]) for key, eid in FIELDS.items()}


async def test_a_room_running_low_targets_can_submit_the_form_unchanged(hass):
    entry = await _install(hass)
    await _set(hass, {"p1_target_vwc": 20.0, "p2_vwc_threshold": 15.0})
    flow = await _open(hass, entry, "edit_parameters")
    shown = _shown(flow)
    assert (shown["p1_target_vwc"], shown["p2_vwc_threshold"]) == (20.0, 15.0)
    done = await hass.config_entries.options.async_configure(flow["flow_id"], shown)
    assert done["type"] is FlowResultType.CREATE_ENTRY  # was: "value must be at least 30.0"
    await hass.async_block_till_done()
    assert float(hass.states.get(TARGET).state) == 20.0
    assert float(hass.states.get(FIELDS["p2_vwc_threshold"]).state) == 15.0


async def test_the_pot_size_can_be_edited_while_the_targets_stay_low(hass):
    entry = await _install(hass)
    await _set(hass, {"p1_target_vwc": 20.0, "p2_vwc_threshold": 15.0})
    flow = await _open(hass, entry, "edit_parameters")
    done = await hass.config_entries.options.async_configure(
        flow["flow_id"], {**_shown(flow), "substrate_volume": 3.5}
    )
    assert done["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert float(hass.states.get(FIELDS["substrate_volume"]).state) == 3.5
    assert float(hass.states.get(TARGET).state) == 20.0


@pytest.mark.parametrize("which", ["min", "max"])
async def test_every_value_the_entities_accept_the_form_accepts_up_to_both_limits(hass, which):
    entry = await _install(hass)
    limits = _limits(hass, which)  # read from the live entities, not restated here
    await _set(hass, limits)
    flow = await _open(hass, entry, "edit_parameters")
    assert _shown(flow) == limits
    done = await hass.config_entries.options.async_configure(flow["flow_id"], limits)
    assert done["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    for key, entity_id in FIELDS.items():
        assert float(hass.states.get(entity_id).state) == limits[key], key


@pytest.mark.parametrize("key", sorted(FIELDS))
@pytest.mark.parametrize("which, step", [("min", -0.5), ("max", 0.5)])
async def test_a_value_the_entity_would_refuse_is_refused_by_the_form_too(hass, key, which, step):
    """Aligned, not loosened: the form must never write a number its entity then rejects."""
    entry = await _install(hass)
    flow = await _open(hass, entry, "edit_parameters")
    beyond = {**_shown(flow), key: _limits(hass, which)[key] + step}
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(flow["flow_id"], beyond)
    assert float(hass.states.get(FIELDS[key]).state) == _shown(flow)[key]  # nothing was written


@pytest.mark.parametrize(
    "name", ["entry_2_18_one_switch_tent.json", "entry_2_17_wizard.json", "entry_env_era.json"]
)
async def test_an_upgraded_room_tuned_low_can_use_the_form_and_nothing_else_moves(hass, name):
    """In-place upgrade: the same form on rooms as OLD versions left them (tests_ha/fixtures)."""
    hass.states.async_set("input_boolean.f2_control_enabled", "off")  # an env-era room's kill switch
    entry, seed = await _upgrade(hass, name)
    await _set(hass, {"p1_target_vwc": 20.0, "p2_vwc_threshold": 15.0})
    before = _numbers(hass)
    flow = await _open(hass, entry, "edit_parameters")
    done = await hass.config_entries.options.async_configure(flow["flow_id"], _shown(flow))
    assert done["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert _numbers(hass) == before  # every number this room has, not only the four on the form
    for key in ("zones", "hardware", "num_zones", "room_prefix"):  # a save, but only of parameters
        assert entry.data.get(key) == seed["data"].get(key), key
    assert entry.data["parameters"]["p1_target_vwc"] == 20.0


# ------------------------------------------------------------------ removing a mapping
async def _save_map(hass, entry, **hardware):
    flow = await _open(hass, entry, "edit_zones")
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"num_zones": 1}
    )
    assert flow["step_id"] == "edit_zones_map"
    # What the frontend sends: every field at the value it is showing, plus the change.
    answers = {**_shown(flow), **_suggested(flow), **hardware}
    for key, value in hardware.items():
        if value is None:  # the operator CLEARED this field: the frontend omits the key
            answers.pop(key)
    done = await hass.config_entries.options.async_configure(flow["flow_id"], answers)
    assert done["type"] is FlowResultType.CREATE_ENTRY, done.get("errors")
    await hass.async_block_till_done()
    return flow


def _suggested(flow):
    return {
        str(marker): marker.description["suggested_value"]
        for marker in flow["data_schema"].schema
        if (getattr(marker, "description", None) or {}).get("suggested_value")
        not in (None, "", [])
    }


async def test_a_mapping_can_be_removed_not_just_swapped(hass):
    hass.states.async_set("sensor.room_temp", "24", {"unit_of_measurement": "°C"})
    entry = await _install(hass)
    await _save_map(hass, entry, temperature_sensor="sensor.room_temp")
    assert entry.data["hardware"]["temperature_sensor"] == "sensor.room_temp"

    flow = await _save_map(hass, entry, temperature_sensor=None)
    # The form opened showing the mapping, so an untouched save could not have wiped it...
    assert _suggested(flow)["temperature_sensor"] == "sensor.room_temp"
    # ...and clearing it cleared it. It used to come straight back.
    assert entry.data["hardware"]["temperature_sensor"] == ""


async def test_an_untouched_save_keeps_every_mapping(hass):
    hass.states.async_set("sensor.room_temp", "24", {"unit_of_measurement": "°C"})
    entry = await _install(hass)
    await _save_map(hass, entry, temperature_sensor="sensor.room_temp")
    before = dict(entry.data["hardware"])
    await _save_map(hass, entry)
    assert entry.data["hardware"] == before


async def test_a_pump_can_be_removed_by_saying_the_room_no_longer_has_one(hass):
    hass.states.async_set("switch.pump", "off")
    entry = await _install(hass, {"pump_switch": "switch.pump"})
    assert entry.data["hardware"]["pump_switch"] == "switch.pump"
    assert entry.data["plumbing"] == "pump_valves"
    await _save_map(hass, entry, pump_switch=None, plumbing="valves_only")
    assert entry.data["hardware"]["pump_switch"] == ""
    assert entry.data["plumbing"] == "valves_only"


async def test_clearing_the_pump_of_a_room_that_says_it_has_one_is_refused_in_the_form(hass):
    """The defect this feature exists for. On 2.18.0 this save went through, and the controller
    then opened the valve with no pump running and counted the water as delivered."""
    hass.states.async_set("switch.pump", "off")
    entry = await _install(hass, {"pump_switch": "switch.pump"})
    revision = entry.data["setup_revision"]
    flow = await _open(hass, entry, "edit_zones")
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"num_zones": 1})
    answers = {**_shown(flow), **_suggested(flow)}
    answers.pop("pump_switch")  # cleared in the form; the layout still says "a pump, then zone valves"
    result = await hass.config_entries.options.async_configure(flow["flow_id"], answers)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "edit_zones_map"
    assert "no pump switch is chosen" in result["description_placeholders"]["error"]
    assert entry.data["hardware"]["pump_switch"] == "switch.pump"  # nothing was written
    assert entry.data["setup_revision"] == revision


# ------------------------------------------------------------------ messages
async def test_reloading_env_on_a_room_that_never_used_one_explains_itself(hass):
    """`not_env_config` had no translation, so the dialog showed the raw key."""
    entry = await _install(hass)
    done = await _open(hass, entry, "reload_env")
    assert done["type"] is FlowResultType.ABORT and done["reason"] == "not_env_config"
    assert "not configured from .env" in done["description_placeholders"]["message"]
