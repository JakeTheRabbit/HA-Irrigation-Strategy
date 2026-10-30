"""Records tests_ha/fixtures/entry_3_17_0_probe_less_room.json from the v3.17.0 integration and controller.

Not a test of this tree, and not collected (its name does not start with test_). To record again: copy it to
tests_ha/test_record_3_17_0.py in a `git archive v3.17.0` tree, stream that tree into the tests_ha Docker image
(docs/TESTING.md) with `tests_ha/test_record_3_17_0.py -q -s`, and take the JSON printed between the markers
(the fixture's `_about` is added by hand).
"""

import json
import os
from datetime import datetime
from pathlib import Path

from homeassistant import config_entries
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

DOMAIN = "crop_steering"
DEVICES = {
    "switch.irrigation_pump": ["off", {}],
    "switch.irrigation_main_line": ["off", {}],
    "switch.zone_1_valve": ["off", {}],
    "switch.zone_2_valve": ["off", {}],
    "sensor.zone_1_vwc": ["52", {"unit_of_measurement": "%"}],
    "sensor.zone_2_vwc": ["49", {"unit_of_measurement": "%"}],
    "sensor.zone_1_ec": ["4.2", {"unit_of_measurement": "mS/cm"}],
    "sensor.zone_2_ec": ["3900", {"unit_of_measurement": "µS/cm"}],
    "sensor.feed_ph": ["5.9", {}],
    "number.doser_a_volume": ["25", {}],
    "button.doser_a_start": ["unknown", {}],
    "binary_sensor.doser_a_dosing": ["off", {}],
    "switch.doser_a_power": ["off", {}],
    "number.doser_a_flow": ["11.06", {}],
    "number.doser_ph_volume": ["25", {}],
    "button.doser_ph_start": ["unknown", {}],
    "binary_sensor.doser_ph_dosing": ["off", {}],
    "switch.doser_ph_power": ["off", {}],
    "number.doser_ph_flow": ["9.8", {}],
    "switch.tank_fill": ["off", {}],
    "binary_sensor.tank_full": ["off", {}],
    "switch.tank_mixer": ["off", {}],
}
TUNED = {
    "zone_1_p2_vwc_threshold": 44.0,
    "zone_1_p1_target_vwc": 58.5,
    "zone_2_p2_vwc_threshold": 43.5,
    "zone_2_p1_target_vwc": 57.0,
    "p2_shot_size": 4.5,
    "maximum_ec": 8.0,
}


async def test_record(hass, controller_for):
    for entity_id, (state, attributes) in DEVICES.items():
        hass.states.async_set(entity_id, state, attributes)
    for phone in ("mobile_app_grower_phone", "mobile_app_office_tablet"):
        hass.services.async_register("notify", phone, lambda call: None)
    flow = hass.config_entries.flow
    result = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await flow.async_configure(result["flow_id"], {"name": "Flower room"})
    assert result["step_id"] == "manual_zones", result
    result = await flow.async_configure(result["flow_id"], {"num_zones": 2})
    zones = {}
    for z in (1, 2):
        zones.update(
            {
                f"zone_{z}_name": f"Bench {z}",
                f"zone_{z}_active": True,
                f"zone_{z}_switch": f"switch.zone_{z}_valve",
                f"zone_{z}_vwc": [f"sensor.zone_{z}_vwc"],
                f"zone_{z}_ec": [f"sensor.zone_{z}_ec"],
                f"zone_{z}_plant_count": 12,
            }
        )
    result = await flow.async_configure(result["flow_id"], zones)
    assert result["step_id"] == "hardware", result.get("errors")
    result = await flow.async_configure(
        result["flow_id"],
        {
            "pump_switch": "switch.irrigation_pump",
            "main_line_switch": "switch.irrigation_main_line",
            "feed_ph_sensor": "sensor.feed_ph",
            "plumbing": "pump_mainline_valves",
        },
    )
    assert result["type"] == "create_entry", result
    await hass.async_block_till_done()
    entry = result["result"]
    prefix = "crop_steering_flower_room_"

    for key, value in TUNED.items():
        await hass.services.async_call(
            "number", "set_value", {"entity_id": f"number.{prefix}{key}", "value": value}, blocking=True
        )
    # The recipe's Bulk stage edited on the dashboard (save_recipe); every other stage as shipped.
    recipe = hass.data[DOMAIN]["_recipe"][entry.entry_id]
    edited = json.loads(json.dumps(recipe.recipe))
    edited["stages"]["Bulk"].update(p1_target_vwc=60.0, p2_vwc_threshold=47.0, maximum_ec=9.5)
    edited["active_stage"] = "Bulk"
    await recipe.async_save(edited)
    notifier = hass.data[DOMAIN]["_notify"]
    saved = await notifier.save(
        {
            "expected_revision": 0,
            "idle_hours": 3,
            "recipients": [
                {"service": "notify.mobile_app_grower_phone", "name": "Grower phone", "user_id": None,
                 "kinds": ["emergency", "watering", "hardware"], "rooms": [], "urgent_high_priority": True,
                 "digest": False},
                {"service": "notify.mobile_app_office_tablet", "name": "Office tablet", "user_id": None,
                 "kinds": ["emergency", "stock"], "rooms": ["flower_room_"], "urgent_high_priority": False,
                 "digest": True},
            ],
        }
    )
    assert not saved.get("error"), saved
    dosing = hass.data[DOMAIN]["_dosing"][entry.entry_id]
    pump = {"dosing_prefix": "Dosing", "max_ml": 2000, "restore_volume": True, "stock_tank": None}
    saved = await dosing.save(
        {
            "expected_revision": 0,
            "pumps": [
                {**pump, "id": "part_a", "name": "Part A", "volume_entity": "number.doser_a_volume",
                 "start_entity": "button.doser_a_start", "dosing_entity": "binary_sensor.doser_a_dosing",
                 "power_entity": "switch.doser_a_power", "flow_entity": "number.doser_a_flow"},
                {**pump, "id": "ph_down", "name": "pH down", "volume_entity": "number.doser_ph_volume",
                 "start_entity": "button.doser_ph_start", "dosing_entity": "binary_sensor.doser_ph_dosing",
                 "power_entity": "switch.doser_ph_power", "flow_entity": "number.doser_ph_flow",
                 "ph_role": "ph_down", "max_ml": 200},
            ],
            "batch": {"fill_valve": "switch.tank_fill", "full_entity": "binary_sensor.tank_full",
                      "full_state": "on", "fill_timeout_min": 20, "mix_pump": "switch.tank_mixer",
                      "premix_min": 2, "postmix_min": 5,
                      "recipe": [{"pump": "part_a", "ml": 400, "ml_entity": None}]},
        },
        can_edit=True,
    )
    assert not saved.get("error"), saved
    display = hass.data[DOMAIN]["_display"][entry.entry_id]
    await display.save(0, {"show_camera": True})
    await hass.async_block_till_done()

    # The 3.17.0 controller adopts the room (kill switch off), then runs armed for one pass.
    kill = f"switch.{prefix}engine_enabled"
    c, fake, _clock = controller_for({"enable_flag": kill})
    for switch in (kill, f"switch.{prefix}system_enabled", f"switch.{prefix}auto_irrigation_enabled",
                   f"switch.{prefix}zone_1_enabled", f"switch.{prefix}zone_2_enabled"):
        fake.set_state(switch, "on")
    c.loop_once(datetime(2026, 10, 21, 13, 0))
    assert c._save_state()
    controller_saved = json.loads(Path(os.environ["F2_STATE_PATH"]).read_text(encoding="utf-8"))

    registry = er.async_get(hass)
    head = f"{DOMAIN}_{entry.entry_id}_"
    stores = {}
    for key in (f"{DOMAIN}_recipes_{entry.entry_id}", f"{DOMAIN}.notify", f"{DOMAIN}.dosing.{entry.entry_id}",
                f"{DOMAIN}.display.{entry.entry_id}", f"{DOMAIN}.calibration.{entry.entry_id}",
                f"{DOMAIN}.stock.{entry.entry_id}", f"{DOMAIN}.whats_new"):
        value = await Store(hass, 1, key).async_load()
        if value is not None:
            stores[key.replace(entry.entry_id, "<entry_id>")] = value
    tuned = {f"number.{prefix}{k}": hass.states.get(f"number.{prefix}{k}").state for k in TUNED}
    out = {
        "entry_id": entry.entry_id,
        "unique_id": entry.unique_id,
        "title": entry.title,
        "version": entry.version,
        "minor_version": entry.minor_version,
        "data": dict(entry.data),
        "options": dict(entry.options),
        "states": DEVICES,
        "operator_tuned_numbers": tuned,
        "registry": {
            e.entity_id: e.unique_id[len(head):]
            for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        },
        "stores": stores,
        "controller_saved": controller_saved,
        "addon_options": {"enable_flag": kill},
    }
    print("=====FIXTURE=====")
    print(json.dumps(out, default=str))
    print("=====END=====")
