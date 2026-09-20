"""FRESH INSTALL, across both layers: wizard -> integration -> the real controller -> water.

The integration and the controller only meet through entity ids and state attributes. Each had
its own tests against its own idea of the other, and a blank install fell straight through the
gap: Home Assistant named new entities from their labels (sensor.engine_config), the controller
looked for sensor.crop_steering_engine_config, and a room that set up cleanly never irrigated.
test_real_flow.py now pins the ids. This file goes the rest of the way and hands the install to
the controller that has to run it.
"""

import pytest
from conftest import switch_calls
from test_real_flow import VALVE
from test_setup_entry import _install

KILL = "switch.crop_steering_engine_enabled"
ARMED = (
    KILL,
    "switch.crop_steering_system_enabled",
    "switch.crop_steering_auto_irrigation_enabled",
    "switch.crop_steering_zone_1_enabled",
)


async def test_the_controller_finds_adopts_and_waters_a_freshly_installed_one_switch_tent(
    hass, controller_for
):
    await _install(hass, {"lights_on_hour": 6, "lights_off_hour": 22})
    c, fake, _clock = controller_for({"enable_flag": KILL})
    room = c.rooms[0]

    # Found from the descriptor alone: no add-on `hardware` option, no YAML.
    assert room.hw["valves"] == {1: VALVE}
    assert not room.hw.get("pump") and not room.hw.get("mainline")
    assert room.setup_revision == 1 and room._setup_pending is None  # everything read OFF
    assert room.enable_flag == KILL
    assert room.zones[1]["vwc"] == "sensor.crop_steering_vwc_zone_1"

    # A new room is born safe: nothing actuates until the operator arms it.
    assert "disabled" in c._blocked(room, 1)
    for switch in ARMED:
        fake.set_state(switch, "on")
    assert "no hardware mapped" not in (c._blocked(room, 1) or "")

    fake.calls.clear()
    c._execute_shot(room, 1, 30, 5, flow_lps=c._zone_flow_lps(room, 1))
    assert switch_calls(fake) == [("turn_on", VALVE), ("turn_off", VALVE)]
    assert room.hardware_fault is None and room.state[1]["shots"] == 1


async def test_the_controller_sizes_shots_from_what_the_wizard_was_told(hass, controller_for):
    await _install(
        hass,
        {"substrate_volume": 11.4, "dripper_flow_rate": 3.8, "drippers_per_plant": 2},
    )
    c, _fake, _clock = controller_for({"enable_flag": KILL})
    room = c.rooms[0]
    assert c._substrate_l(room, 1) == pytest.approx(11.4 * 4)  # per-plant litres x 4 plants
    assert c._zone_flow_lps(room, 1) == pytest.approx(4 * 2 * 3.8 / 3600)


async def test_the_controller_runs_the_photoperiod_the_wizard_was_told(hass, controller_for):
    """End to end for the lights-hours fix: what was typed is what the controller schedules on.
    Before it, the entities read 12 and 0 and so did the controller, whatever setup was told."""
    await _install(hass, {"lights_on_hour": 6, "lights_off_hour": 22})
    c, _fake, _clock = controller_for(
        {"enable_flag": KILL, "lights_on_hour": 10, "lights_off_hour": 20}
    )
    room = c.rooms[0]
    assert (room.lights_on_hour, room.lights_off_hour) == (10.0, 20.0)  # add-on options, until read
    c._refresh_lights(room)  # what every loop does: the integration's entities win
    assert (room.lights_on_hour, room.lights_off_hour) == (6.0, 22.0)


async def test_the_controller_reads_the_tents_microsiemens_probe_as_millisiemens(
    hass, controller_for
):
    await _install(hass)  # the seeded probe reports 3100 uS/cm
    c, _fake, _clock = controller_for({"enable_flag": KILL})
    assert c._read_sensor("sensor.crop_steering_ec_zone_1", lo=0, hi=20) == pytest.approx(
        3.1
    )
