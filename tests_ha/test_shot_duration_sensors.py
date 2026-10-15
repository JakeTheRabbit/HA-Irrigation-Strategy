"""The P1, P2 and P3 shot-duration sensors give the seconds the controller runs each shot for.

Before, they divided a room-wide shot by ONE dripper's flow: a room with two drippers per plant
read double, and a zone sized on its own in Rooms & hardware read the room's numbers. Here the
REAL sensors, in a real Home Assistant, are held against the REAL controller's own arithmetic on
the same states: its substrate litres, its flow, its shot size and its room limit.
"""

from homeassistant.helpers.entity_component import async_update_entity
from test_install_to_controller import KILL
from test_mcp_setup_contract import _payload, _room, _service
from test_setup_entry import _install

SHOTS = {
    "p1_shot_duration_seconds": "p1_initial",
    "p2_shot_duration_seconds": "p2_shot_size",
    "p3_shot_duration_seconds": "p3_emergency_shot",
}


async def _sensor(hass, key):
    entity_id = f"sensor.crop_steering_{key}"
    await async_update_entity(hass, entity_id)
    return hass.states.get(entity_id)


def _controller_seconds(c, room, zone, key):
    """What the controller's shot sequence runs this shot for (_act_zone)."""
    size = getattr(c._params(room, zone), SHOTS[key])
    raw = size / 100.0 * c._substrate_l(room, zone) / c._zone_flow_lps(room, zone)
    return max(5, min(int(c._room_duration_cap(room)), int(raw)))


async def test_each_sensor_is_what_the_controller_runs_with_two_drippers_per_plant(
    hass, controller_for
):
    await _install(
        hass,
        {"substrate_volume": 11.4, "dripper_flow_rate": 3.8, "drippers_per_plant": 2},
    )
    c, _fake, _clock = controller_for({"enable_flag": KILL})
    room = c.rooms[0]
    for key in SHOTS:
        state = await _sensor(hass, key)
        expected = _controller_seconds(c, room, 1, key)
        assert int(state.state) == expected, key
        assert state.attributes["zones"] == {"1": expected}
    # 2% of 11.4 L is 228 mL, through two 3.8 L/hr drippers: 108 s, not the 216 one would take.
    assert int((await _sensor(hass, "p1_shot_duration_seconds")).state) == 108


async def test_a_zone_sized_in_rooms_and_hardware_is_timed_by_its_own_sizing(
    hass, hass_admin_user, controller_for
):
    await _install(hass)  # the wizard's room-wide 6 L pot and one 2 L/hr dripper
    room = await _room(hass, hass_admin_user)
    zone = {**room["zones"][0], "substrate_volume": 5.8, "drippers_per_plant": 1}
    zone["dripper_flow_rate"] = 2
    await _service(hass, hass_admin_user, "setup_save", _payload(room, zones=[zone]))
    await hass.async_block_till_done()
    assert hass.states.get("number.crop_steering_zone_1_substrate_volume").state == "5.8"
    c, _fake, _clock = controller_for({"enable_flag": KILL})
    state = await _sensor(hass, "p2_shot_duration_seconds")
    expected = _controller_seconds(c, c.rooms[0], 1, "p2_shot_duration_seconds")
    assert int(state.state) == expected
    # 5% of 5.8 L is 290 mL through one 2 L/hr dripper: 522 s; the room's 6 L would give 540.
    assert expected == 522


async def test_the_room_limit_caps_the_sensor_as_it_caps_the_shot(hass, controller_for):
    await _install(hass)
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.crop_steering_max_shot_duration", "value": 60},
        blocking=True,
    )
    c, _fake, _clock = controller_for({"enable_flag": KILL})
    state = await _sensor(hass, "p2_shot_duration_seconds")
    assert int(state.state) == _controller_seconds(
        c, c.rooms[0], 1, "p2_shot_duration_seconds"
    )
    assert state.state == "60"
