"""A room in a Home Assistant set to US customary units, in a northern-hemisphere time zone.

tests_ha/fixtures/entry_us_units_tent.json is the seeded 2.18 tent whose moisture probe reports a fraction
in m³/m³ and whose EC probe reports μS/cm. Both layers steer in percent and mS/cm, so they must read the
same numbers there as in a metric install, and the controller must carry the room straight on.
"""

import pytest
from conftest import fixture
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from test_upgrade_in_place import _upgrade

NAME = "entry_us_units_tent.json"
KILL = "switch.crop_steering_engine_enabled"


async def _us_home(hass):
    seed = fixture(NAME)
    assert seed["ha_config"]["unit_system"] == "us_customary"
    hass.config.units = US_CUSTOMARY_SYSTEM
    await hass.config.async_set_time_zone(seed["ha_config"]["time_zone"])
    await _upgrade(hass, NAME)
    return seed


async def test_probes_in_us_units_read_in_percent_and_millisiemens(hass):
    await _us_home(hass)
    vwc = hass.states.get("sensor.crop_steering_vwc_zone_1")
    ec = hass.states.get("sensor.crop_steering_ec_zone_1")
    assert float(vwc.state) == pytest.approx(41.0)
    assert float(ec.state) == pytest.approx(3.1)
    assert vwc.attributes["unit_of_measurement"] == "%"
    assert ec.attributes["unit_of_measurement"] == "mS/cm"
    # what the operator tuned is not touched by the unit system either
    assert float(hass.states.get("number.crop_steering_p1_target_vwc").state) == 63


async def test_the_controller_reads_the_same_numbers_and_carries_the_room_on(hass, controller_for):
    seed = await _us_home(hass)
    hass.states.async_set(KILL, "on")
    c, _fake, _clock = controller_for({}, saved_state=seed["controller_saved"])
    room = c.rooms[0]
    assert room._setup_pending is None and room.setup_revision == 1
    assert room.state[1]["phase"] == "P2"
    vwc = c._read_sensor(c._fused_id(room.prefix, "vwc", 1, room.zones[1].get("vwc")), "vwc")
    ec = c._read_sensor(c._fused_id(room.prefix, "ec", 1, room.zones[1].get("ec")), "ec")
    assert vwc == pytest.approx(41.0) and ec == pytest.approx(3.1)
