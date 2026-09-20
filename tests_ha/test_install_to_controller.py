"""FRESH INSTALL, across both layers: wizard -> integration -> the real controller -> water.

The integration and the controller only meet through entity ids and state attributes. Each had
its own tests against its own idea of the other, and a blank install fell straight through the
gap: Home Assistant named new entities from their labels (sensor.engine_config,
number.substrate_volume), the controller looked for sensor.crop_steering_engine_config, and a
room that set up cleanly never irrigated. It did not show on a long-running install because an
entity already in the registry keeps its old id.
"""

from __future__ import annotations

import pytest
from homeassistant.helpers import entity_registry as er

from .conftest import TENT_SWITCH, switch_calls
from .test_fresh_install import _install_tent

KILL = "switch.crop_steering_engine_enabled"


async def test_a_blank_install_gets_the_entity_ids_the_controller_looks_for(hass):
    entry = await _install_tent(hass)
    registry = er.async_get(hass)
    ours = [
        e.entity_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    ]
    assert len(ours) > 100
    strays = [
        eid for eid in ours if not eid.split(".", 1)[1].startswith("crop_steering_")
    ]
    assert (
        strays == []
    ), f"named from their labels, invisible to the controller: {strays[:8]}"
    # The ones the controller reads by exact id, spelled out:
    for eid in (
        "sensor.crop_steering_engine_config",
        "sensor.crop_steering_vwc_zone_1",
        "sensor.crop_steering_ec_zone_1",
        "number.crop_steering_substrate_volume",
        "number.crop_steering_dripper_flow_rate",
        "number.crop_steering_drippers_per_plant",
        "number.crop_steering_lights_on_hour",
        "number.crop_steering_zone_1_plant_count",
        "number.crop_steering_zone_1_p1_target_vwc",
        "select.crop_steering_steering_mode",
        "select.crop_steering_zone_1_phase_override",
        "button.crop_steering_zone_1_trigger_shot",
        "switch.crop_steering_zone_1_enabled",
        "switch.crop_steering_system_enabled",
        "switch.crop_steering_auto_irrigation_enabled",
        KILL,
    ):
        assert hass.states.get(eid) is not None, eid


async def test_the_controller_adopts_a_freshly_installed_tent_and_waters_it(
    hass, controller_for
):
    await _install_tent(hass)
    c, fake, clock = controller_for({"enable_flag": KILL})
    room = c.rooms[0]

    # It found the room, from the descriptor alone: no add-on `hardware` option, no YAML.
    assert room.hw == {
        "pump": None,
        "mainline": None,
        "valves": {1: TENT_SWITCH},
        "plumbing": "valves_only",
    }
    assert (
        room.setup_revision == 1 and room._setup_pending is None
    )  # adopted: everything read OFF
    assert room.enable_flag == KILL
    assert list(room.zones) == [1]
    assert room.zones[1]["vwc"] == "sensor.crop_steering_vwc_zone_1"

    # A new room is born safe: the engine is off until the operator arms it.
    assert "disabled" in c._blocked(room, 1)
    for switch in (
        KILL,
        "switch.crop_steering_system_enabled",
        "switch.crop_steering_auto_irrigation_enabled",
        "switch.crop_steering_zone_1_enabled",
    ):
        fake.set_state(switch, "on")
    assert "no hardware mapped" not in (c._blocked(room, 1) or "")

    # The sizing the wizard was given (3 US gal pots, 1 GPH drippers) is what sizes the shot.
    assert c._substrate_l(room, 1) == pytest.approx(
        11.4 * 4
    )  # per-plant litres x 4 plants
    assert c._zone_flow_lps(room, 1) == pytest.approx(4 * 2 * 3.785 / 3600, rel=1e-3)

    fake.calls.clear()
    c._execute_shot(room, 1, 30, 5, flow_lps=c._zone_flow_lps(room, 1))
    assert switch_calls(fake) == [("turn_on", TENT_SWITCH), ("turn_off", TENT_SWITCH)]
    assert room.hardware_fault is None and room.state[1]["shots"] == 1


async def test_the_controller_reads_the_tents_microsiemens_probe_as_millisiemens(
    hass, controller_for
):
    await _install_tent(hass)
    c, _fake, _clock = controller_for({"enable_flag": KILL})
    fused = (
        c._fused_id("", "ec", 1)
        if hasattr(c, "_fused_id")
        else "sensor.crop_steering_ec_zone_1"
    )
    assert fused == "sensor.crop_steering_ec_zone_1"
    assert c._read_sensor(fused, lo=0, hi=20) == pytest.approx(2.3)


async def test_a_room_whose_layout_needs_a_pump_is_held_until_the_pump_is_mapped(
    hass, controller_for
):
    """The other half of 'never assume': a declared pump that is not mapped holds the room."""
    await _install_tent(hass)
    descriptor = dict(hass.states.get("sensor.crop_steering_engine_config").attributes)
    hass.states.async_set(
        "sensor.crop_steering_engine_config",
        "default",
        {**descriptor, "plumbing": "pump_valves", "setup_revision": 2},
    )
    c, fake, _clock = controller_for({"enable_flag": KILL})
    room = c.rooms[0]
    for switch in (
        KILL,
        "switch.crop_steering_system_enabled",
        "switch.crop_steering_auto_irrigation_enabled",
        "switch.crop_steering_zone_1_enabled",
    ):
        fake.set_state(switch, "on")
    block = c._blocked(room, 1)
    assert block and (
        "no hardware mapped" in block or "Invalid setup" in block or "Setup" in block
    )
