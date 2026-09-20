"""The setup wizard and the entities it creates, in a real Home Assistant."""

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

DOMAIN = "crop_steering"
VALVE = "switch.gt1_irrigation_switch"
ZONES = {
    "zone_1_name": "Tent",
    "zone_1_active": True,
    "zone_1_switch": VALVE,
    "zone_1_vwc": ["sensor.gt1_vwc"],
    "zone_1_ec": ["sensor.gt1_ec"],
    "zone_1_plant_count": 4,
}


def _seed(hass, valve="off"):
    hass.states.async_set(VALVE, valve)
    hass.states.async_set("sensor.gt1_vwc", "41", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.gt1_ec", "3100", {"unit_of_measurement": "µS/cm"})


async def _to_zones_step(hass):
    flow = hass.config_entries.flow
    result = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    result = await flow.async_configure(result["flow_id"], {"name": "Tent", "config_method": "manual"})
    assert result["step_id"] == "manual_zones"
    result = await flow.async_configure(result["flow_id"], {"num_zones": 1})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "zones"
    return result["flow_id"]


def _kept(result):
    """What Home Assistant will prefill the re-shown form with."""
    return {
        str(marker): (marker.description or {}).get("suggested_value")
        for marker in result["data_schema"].schema
        if getattr(marker, "description", None)
    }


async def test_a_valve_that_is_on_keeps_the_wizard_open_with_everything_typed(hass):
    _seed(hass, valve="on")
    flow_id = await _to_zones_step(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, dict(ZONES))
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "zones"  # not an abort
    assert result["errors"] == {"base": "setup_invalid"}
    assert VALVE in result["description_placeholders"]["error"]
    assert "it is ON" in result["description_placeholders"]["error"]
    kept = _kept(result)
    assert kept["zone_1_switch"] == VALVE and kept["zone_1_ec"] == ["sensor.gt1_ec"]
    hass.states.async_set(VALVE, "off")
    result = await hass.config_entries.flow.async_configure(flow_id, dict(ZONES))
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "hardware"


async def test_a_one_switch_tent_becomes_a_room_and_its_switches_get_the_ids_the_controller_reads(hass):
    _seed(hass)
    flow_id = await _to_zones_step(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, dict(ZONES))
    assert result["step_id"] == "hardware"
    result = await hass.config_entries.flow.async_configure(flow_id, {})  # no pump, no main-line valve
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["hardware"]["pump_switch"] == ""
    assert result["data"]["zones"]["1"]["zone_switch"] == VALVE
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    for entity_id in (
        "switch.crop_steering_room_active",
        "switch.crop_steering_auto_setpoints",
        "switch.crop_steering_engine_enabled",
        "switch.crop_steering_system_enabled",
    ):
        assert registry.async_get(entity_id) is not None, f"{entity_id} is not registered under that id"
    assert hass.states.get("switch.crop_steering_room_active").state == "on"  # a new room is growing
    assert hass.states.get("switch.crop_steering_auto_setpoints").state == "off"  # nothing rewrites targets unasked

    # the fused pore-EC sensor converts the probe's uS/cm; the descriptor the controller reads has no pump
    await hass.async_block_till_done()
    descriptor = hass.states.get("sensor.crop_steering_system_engine_config") or hass.states.get(
        "sensor.crop_steering_engine_config"
    )
    assert descriptor is not None
    valves = {str(zone): valve for zone, valve in descriptor.attributes["valves"].items()}
    assert not descriptor.attributes.get("pump") and valves == {"1": VALVE}


async def test_a_fresh_install_registers_every_entity_under_the_id_its_code_asks_for(hass):
    """Home Assistant ignores `_attr_object_id`. Until 2.18.0 a new room's numbers, selects, sensors and
    buttons were named from their labels (`number.p1_target_vwc`, `sensor.engine_config`), so the
    controller never found the room. Existing installs never showed it: the registry keeps old ids."""
    from homeassistant.helpers import entity_platform

    _seed(hass)
    flow_id = await _to_zones_step(hass)
    await hass.config_entries.flow.async_configure(flow_id, dict(ZONES))
    await hass.config_entries.flow.async_configure(flow_id, {})
    await hass.async_block_till_done()

    checked, wrong = 0, []
    for platform in entity_platform.async_get_platforms(hass, DOMAIN):
        for entity in platform.entities.values():
            wanted = getattr(entity, "_attr_object_id", None)
            if wanted:
                checked += 1
                if entity.entity_id != f"{platform.domain}.{wanted}":
                    wrong.append(f"{entity.entity_id} should be {platform.domain}.{wanted}")
    assert checked > 100 and not wrong, wrong


async def test_an_existing_install_keeps_the_entity_ids_its_registry_already_holds(hass):
    """Older installs hold ids the code no longer asks for (F2's fused probe is
    `sensor.crop_steering_zone_1_vwc`, the code asks for `..._vwc_zone_1`). Dashboards, automations and
    recorder history hang off the registered id, so setting `entity_id` must never move one."""
    _seed(hass)
    flow_id = await _to_zones_step(hass)
    await hass.config_entries.flow.async_configure(flow_id, dict(ZONES))
    result = await hass.config_entries.flow.async_configure(flow_id, {})
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    asked, held = "sensor.crop_steering_vwc_zone_1", "sensor.crop_steering_zone_1_vwc"
    unique_id = registry.async_get(asked).unique_id
    registry.async_update_entity(asked, new_entity_id=held)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_reload(result["result"].entry_id)
    await hass.async_block_till_done()

    assert registry.async_get(held).unique_id == unique_id
    assert registry.async_get(asked) is None and hass.states.get(asked) is None
    assert hass.states.get(held) is not None
