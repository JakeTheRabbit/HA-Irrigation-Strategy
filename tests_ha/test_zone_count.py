"""The first real install, in the order it really happened: the controller app was started
BEFORE the integration was set up. It must invent no zones, and must pick the room up by itself
once the wizard is finished, with exactly the zones that room has.

Found on a one-zone tent whose dashboard filled with "Z2 ... no hardware mapped" and
"Z3 ... no hardware mapped": zones that do not exist, from the app's `num_zones: 3` default.
"""

import json
from datetime import datetime

import pytest
from test_real_flow import VALVE, _seed
from test_setup_entry import _install

# what Supervisor writes into a new install's options.json: the defaults in config.yaml
SHIPPED = {"num_zones": 3, "enable_flag": "input_boolean.f2_control_enabled"}
NOW = datetime(2026, 9, 21, 14, 0, 0)


def _sync(hass, fake):
    """Let the controller see Home Assistant as it is NOW, the way its next REST poll would."""
    for state in hass.states.async_all():
        fake.set_state(
            state.entity_id, state.state, json.loads(json.dumps(dict(state.attributes), default=str))
        )


def _zones_published(fake):
    return {
        int(entity_id.split("_zone_")[1].split("_")[0]) for entity_id in fake.sets if "_zone_" in entity_id
    }


async def test_app_first_then_the_wizard_a_one_zone_tent_gets_one_zone(hass, controller_for):
    _seed(hass)  # the tent's switch and probes exist in Home Assistant; Crop Steering is not set up
    c, fake, _clock = controller_for(dict(SHIPPED))
    room = c.rooms[0]
    assert room.zones == {} and c._default_provisional
    c.loop_once(NOW)
    assert _zones_published(fake) == set()  # it said "Z2/Z3 no hardware mapped" here

    await _install(hass)  # the operator finishes the wizard: one zone
    _sync(hass, fake)
    c.loop_once(NOW)  # the very next loop: no restart, no five-minute wait

    assert sorted(room.zones) == [1]
    assert room.hw["valves"] == {1: VALVE}
    assert room.enable_flag == "switch.crop_steering_engine_enabled"  # the room's real kill switch
    assert not c._default_provisional
    assert _zones_published(fake) <= {1}
    heartbeat = fake.sets["sensor.crop_steering_ai_heartbeat"][1]
    assert heartbeat["enable_flag"] == "switch.crop_steering_engine_enabled"  # what the dashboard looks for


@pytest.mark.parametrize("zones", [1, 2, 5, 12, 20, 24])
async def test_wizard_first_then_the_app_any_zone_count_up_to_the_limit(hass, controller_for, monkeypatch, zones):
    from homeassistant import config_entries
    from homeassistant.data_entry_flow import FlowResultType

    hass.states.async_set("sensor.vwc", "41", {"unit_of_measurement": "%"})
    for z in range(1, zones + 1):
        hass.states.async_set(f"switch.valve_{z}", "off")
    flow = hass.config_entries.flow
    result = await flow.async_init("crop_steering", context={"source": config_entries.SOURCE_USER})
    result = await flow.async_configure(result["flow_id"], {"name": "Room", "config_method": "manual"})
    result = await flow.async_configure(result["flow_id"], {"num_zones": zones})
    answers = {}
    for z in range(1, zones + 1):
        answers.update({f"zone_{z}_name": f"Bench {z}", f"zone_{z}_active": True,
                        f"zone_{z}_switch": f"switch.valve_{z}", f"zone_{z}_plant_count": 4})
    answers["zone_1_vwc"] = ["sensor.vwc"]
    result = await flow.async_configure(result["flow_id"], answers)
    assert result["step_id"] == "hardware", result.get("errors")
    result = await flow.async_configure(result["flow_id"], {"plumbing": "valves_only"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    c, fake, _clock = controller_for(dict(SHIPPED))
    room = c.rooms[0]
    assert sorted(room.zones) == list(range(1, zones + 1))
    assert room.hw["valves"] == {z: f"switch.valve_{z}" for z in range(1, zones + 1)}
    assert not c._default_provisional
    c.loop_once(NOW)
    assert _zones_published(fake) <= set(range(1, zones + 1))
