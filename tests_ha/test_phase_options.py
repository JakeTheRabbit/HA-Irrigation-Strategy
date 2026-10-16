"""The opt-in phase settings, in a real Home Assistant with the real controller.

New entities: the P0 minimum wait, the EC flush target, the zone's P2 high EC ratio, the timed P2 numbers and the
P2 end before lights-off (room and per zone), the zone's P2 mode select, the room's P0 stall exit and "use P2 EC
ratios" switches, the room's Max setpoint move per day and the select of which writers it holds. Each starts at
the rule as it was, on a new room and on every room updated in place, and the controller then decides exactly as
before. A controller updated ahead of an older integration (none of the entities) does the same, and raises no
missing-setting alert.
"""

import re
from datetime import datetime

import pytest
from conftest import fixture, room_of
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, UPSTREAM_2_25_1, _upgrade

ZONE_NUMBERS = {  # key: (value it starts at, min, max)
    "p0_minimum_wait_time": (0, 0, 240),
    "ec_flush_target": (0, 0, 9),
    "p2_timed_interval_min": (60, 5, 720),
    "p2_timed_shot_size": (0, 0, 20),
    "p2_timed_first_hours": (0, 0, 24),
    "p2_end_hours_before_off": (0, 0, 12),
    "p2_dilute_ratio": (1.2, 1, 3),
}
ROOM_SWITCHES = ("p0_stall_exit", "use_p2_ec_thresholds")
STEP = "setpoint_max_step_per_day"
SCOPE = "setpoint_step_limit_applies_to"


def _zone_entities(hass, prefix, domain, key):
    pattern = re.compile(rf"{domain}\.crop_steering_{prefix}zone_\d+_{key}$")
    return sorted(s.entity_id for s in hass.states.async_all(domain) if pattern.match(s.entity_id))


def _assert_defaults(hass, prefix, zones):
    for key, (value, lo, hi) in ZONE_NUMBERS.items():
        found = _zone_entities(hass, prefix, "number", key)
        assert len(found) == zones, key
        for entity_id in found:
            state = hass.states.get(entity_id)
            assert (state.attributes["min"], state.attributes["max"]) == (lo, hi), entity_id
            assert float(state.state) == value, entity_id
        room = hass.states.get(f"number.crop_steering_{prefix}{key}")
        assert room is not None and float(room.state) == value, key
    modes = _zone_entities(hass, prefix, "select", "p2_mode")
    assert len(modes) == zones
    for entity_id in modes:
        state = hass.states.get(entity_id)
        assert state.state == "Moisture"
        assert state.attributes["options"] == ["Moisture", "Timed", "Timed with guards"]
    for key in ROOM_SWITCHES:
        assert hass.states.get(f"switch.crop_steering_{prefix}{key}").state == "off", key
    step = hass.states.get(f"number.crop_steering_{prefix}{STEP}")
    assert float(step.state) == 1.0 and (step.attributes["min"], step.attributes["max"]) == (0, 50)
    assert hass.states.get(f"select.crop_steering_{prefix}{SCOPE}").state == "Auto setpoints"
    for entity_id in _zone_entities(hass, prefix, "number", "p1_maximum_extra_shots"):
        assert hass.states.get(entity_id).attributes["max"] == 30


def _as_before(p):
    assert (p.p0_min_wait_min, p.p0_stall_exit, p.ec_flush_target, p.p2_dilute_ratio) == (0, False, 0, 1.2)
    assert (p.p2_mode, p.p2_end_h_before_off) == ("moisture", 0)


async def test_a_new_room_has_every_setting_at_the_rule_as_it_was(hass):
    await _install(hass)  # the wizard's "Tent" is tent_
    _assert_defaults(hass, "tent_", 1)


async def test_the_controller_reads_a_new_room_as_before(hass, controller_for):
    await _install(hass)
    c, _fake, _clock = controller_for({})
    room = room_of(c)
    c.loop_once(datetime.now())
    _as_before(c._params(room, 1))
    assert c._step_limit(room) == 1.0 and c._step_limit_all(room) is False


@pytest.mark.parametrize("name", ["entry_2_17_wizard.json", UPSTREAM_2_25_1, JEV_3_11_1])
async def test_a_room_updated_in_place_gets_them_off_and_nothing_else_moves(hass, name):
    seed = fixture(name)
    await _upgrade(hass, name, registry_ids=seed.get("registry"))
    _assert_defaults(hass, "", seed["data"]["num_zones"])
    for entity_id, saved in seed["operator_tuned_numbers"].items():
        tuned = saved[0] if isinstance(saved, list) else saved
        state = hass.states.get(entity_id).state
        if entity_id.startswith("number."):
            assert float(state) == float(tuned), entity_id
        else:
            assert state == tuned, entity_id


async def test_an_updated_room_is_read_by_the_controller_as_before(hass, controller_for):
    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    c, _fake, _clock = controller_for({})
    room = c.rooms[0]
    c.loop_once(datetime.now())
    for zone in sorted(room.state):
        _as_before(c._params(room, zone))
        assert room.state[zone]["ec_flushing"] is False


async def test_set_by_the_operator_they_reach_the_engine(hass, controller_for):
    await _install(hass)
    z = "number.crop_steering_tent_zone_1_"
    for key, value in (("p0_minimum_wait_time", 30), ("ec_flush_target", 4.5), ("p2_timed_interval_min", 45),
                       ("p2_end_hours_before_off", 2), ("p2_dilute_ratio", 1.5)):
        await hass.services.async_call("number", "set_value", {"entity_id": z + key, "value": value}, blocking=True)
    await hass.services.async_call("select", "select_option", {
        "entity_id": "select.crop_steering_tent_zone_1_p2_mode", "option": "Timed with guards"}, blocking=True)
    for key in ROOM_SWITCHES:
        await hass.services.async_call("switch", "turn_on", {"entity_id": f"switch.crop_steering_tent_{key}"},
                                       blocking=True)
    await hass.services.async_call("number", "set_value", {
        "entity_id": f"number.crop_steering_tent_{STEP}", "value": 0}, blocking=True)
    await hass.services.async_call("select", "select_option", {
        "entity_id": f"select.crop_steering_tent_{SCOPE}", "option": "Auto setpoints and AI"}, blocking=True)
    c, _fake, _clock = controller_for({})
    room = room_of(c)
    p = c._params(room, 1)
    assert (p.p0_min_wait_min, p.p0_stall_exit, p.ec_flush_target, p.p2_dilute_ratio) == (30, True, 4.5, 1.5)
    assert (p.p2_mode, p.p2_timed_interval_min, p.p2_end_h_before_off) == ("timed_guarded", 45, 2)
    assert c._step_limit(room) == float("inf") and c._step_limit_all(room) is True


async def test_a_controller_updated_ahead_of_a_3_11_1_integration_decides_as_before(hass, controller_for):
    """Only the controller app updated: the room's integration is 3.11.1's, which has none of these."""
    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    new = [s.entity_id for s in hass.states.async_all()
           if any(s.entity_id.endswith(k) for k in (*ZONE_NUMBERS, *ROOM_SWITCHES, STEP, SCOPE, "_p2_mode"))]
    for entity_id in new:
        hass.states.async_remove(entity_id)
    c, _fake, _clock = controller_for({})
    room = c.rooms[0]
    c.loop_once(datetime.now())
    for zone in sorted(room.state):
        _as_before(c._params(room, zone))
    assert c._step_limit(room) == 1.0 and c._step_limit_all(room) is False
    missing = {e for e in c._defaulted_this_loop if any(k in e for k in ZONE_NUMBERS)}
    assert missing == set()
