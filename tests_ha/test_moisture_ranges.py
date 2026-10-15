"""The engine never clips a moisture level its Home Assistant setting accepts.

A setting accepted a peak target of 87 (5-95) and the engine used 85 with CS-401, because the engine
took 20-85. Each of the four moisture levels now has one range, the same in the setting, the engine,
grow plans and Auto setpoints. The tops are 100, because the order between the levels is what bounds
the water; the floors, where the engine always had them, catch a slipped digit.
"""

import dataclasses
from datetime import datetime

from crop_steering_engine import validate_params
from crop_steering_engine.core import _PARAM_BOUNDS
from custom_components.crop_steering.const import MOISTURE_RANGES
from custom_components.crop_steering.strategy_model import ENGINE_BOUNDS as GROW_PLANS
from setpoint_supervisor import BOUNDS as AUTO_SETPOINTS
from test_setup_entry import _install

# Each setting (its entity key), the engine's name for it, and its one range.
LEVELS = {
    "p1_target_vwc": ("p1_target", (20, 100)),
    "p2_vwc_threshold": ("p2_threshold", (10, 100)),
    "field_capacity": ("field_capacity", (40, 100)),
    "p3_emergency_vwc_threshold": ("p3_emergency_floor", (10, 65)),
}


async def _set(hass, entity_id, value):
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True
    )


async def test_each_level_has_one_range_everywhere(hass, controller_for):
    await _install(hass)
    c, _fake, _clock = controller_for({})
    params = c._params(c.rooms[0], 1)
    for key, (engine, expected) in LEVELS.items():
        for entity_id in (
            f"number.crop_steering_{key}",
            f"number.crop_steering_zone_1_{key}",
        ):
            state = hass.states.get(entity_id)
            assert (state.attributes["min"], state.attributes["max"]) == expected
        assert MOISTURE_RANGES[key] == expected
        assert _PARAM_BOUNDS[engine] == expected
        assert GROW_PLANS[key] == expected
        assert AUTO_SETPOINTS[key] == expected
        # Neither end of what the setting accepts is clipped.
        for value in expected:
            _clamped, warnings = validate_params(
                dataclasses.replace(params, **{engine: float(value)})
            )
            assert not [w for w in warnings if w.startswith(f"{engine}=")], (
                engine,
                value,
            )


async def test_a_peak_target_of_87_is_used_as_set(hass, controller_for):
    await _install(hass)
    await _set(hass, "number.crop_steering_zone_1_field_capacity", 90)
    await _set(hass, "number.crop_steering_zone_1_p1_target_vwc", 87)
    c, fake, _clock = controller_for({})
    assert c._params(c.rooms[0], 1).p1_target == 87
    c.loop_once(datetime.now())
    notices = [
        d.get("title", "")
        for dom, svc, d in fake.calls
        if (dom, svc) == ("persistent_notification", "create")
    ]
    assert not [title for title in notices if "CS-401" in title]
